"""URL in, blueprint string out.

The five stages wired together.  Everything here is orchestration -- no stage
logic lives in this module, so a change of strategy or of rate model does not
touch it.

    URL -> LabRequest -> BuildSpecSet -> Placement -> blueprint string
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from fractions import Fraction
from pathlib import Path
from typing import Literal

from flab2bp.dsp import catalog, codec
from flab2bp.lab.capture import capture_flow_csv
from flab2bp.lab.data import load_vendored
from flab2bp.lab.flow import (
    FlowError,
    FlowSelection,
    cross_check,
    flow_from_text,
    load_flow,
    pin_request,
    unsupplied_inputs,
)
from flab2bp.lab.schema import Dataset
from flab2bp.lab.url import parse_url
from flab2bp.layout import markers, validate
from flab2bp.layout.base import NoValidLayout, Placement
from flab2bp.layout.freeform import FreeformLayout
from flab2bp.layout.spine import SpineLayout
from flab2bp.rates.candidates import build_candidates
from flab2bp.spec import BuildSpec, BuildSpecSet

StrategyName = Literal["spine", "freeform", "best"]

_STRATEGIES = {"spine": SpineLayout, "freeform": FreeformLayout}


def _id_map(spec: BuildSpec) -> validate.IdMap:
    """Bridge FactorioLab string ids to the DSP numeric ids a Placement uses.

    Built from the spec rather than the whole catalog so an unmappable recipe
    elsewhere in the dataset cannot break a build that does not use it.
    """
    recipes: dict[str, int] = {}
    items: dict[str, int] = {}
    known = catalog.known_recipe_ids()
    for g in spec.groups:
        if g.recipe_id in known:
            recipes[g.recipe_id] = catalog.recipe_id(g.recipe_id)
        # The MACHINE is an item too, and spec.machine_counts needs it to match
        # a group against the buildings actually placed. Omitting it made every
        # group read as "spec demands 0" while the placement was correct.
        machine = catalog.get_item_id(g.machine_item_id)
        if machine is not None:
            items[g.machine_item_id] = machine
        for item in (*g.inputs_per_machine, *g.outputs_per_machine):
            got = catalog.get_item_id(item)
            if got is not None:
                items[item] = got
    for item in (*spec.external_inputs, *spec.outputs):
        got = catalog.get_item_id(item)
        if got is not None:
            items[item] = got
    return validate.IdMap(recipes=recipes, items=items)


@dataclass(frozen=True, slots=True)
class Attempt:
    """One (candidate, strategy) pair laid out."""

    candidate: str
    strategy: str
    placement: Placement
    report: validate.Report

    @property
    def area(self) -> int:
        return self.placement.area

    @property
    def ok(self) -> bool:
        return self.report.ok


@dataclass(frozen=True, slots=True)
class Build:
    """The chosen result, plus everything that lost, for reporting."""

    spec: BuildSpec
    placement: Placement
    report: validate.Report
    strategy: str
    blueprint: str
    attempts: tuple[Attempt, ...] = field(default_factory=tuple)
    #: Strategy/candidate pairs that produced no layout at all, with the reason.
    #: Kept so a refusal is reported rather than silently absent from `attempts`.
    refused: tuple[str, ...] = field(default_factory=tuple)
    #: Ways the chosen build's recipe set differs from the pinned flow's, if one
    #: was supplied.  Empty when no flow was given OR when we reproduced it: the
    #: CLI says which, because "no findings" and "nothing was checked" are very
    #: different claims and only one of them is reassuring.
    flow_findings: tuple[str, ...] = field(default_factory=tuple)
    #: Whether a FactorioLab flow export pinned the recipe selection.
    flow_pinned: bool = False


def build(
    url: str,
    *,
    strategy: StrategyName = "best",
    power: bool = True,
    candidates: int = 3,
    time_budget_s: float = 2.0,
    dataset: Dataset | None = None,
    name: str = "",
    flow: Path | None = None,
    fetch_flow: bool = False,
    fetch_timeout_s: float = 90.0,
    browser: str | None = None,
    max_belt_z: Fraction = catalog.DEFAULT_MAX_BELT_Z,
) -> Build:
    """Turn a FactorioLab URL into a pasteable DSP blueprint.

    Every candidate is laid out by every requested strategy and the smallest
    *valid* result wins.  That is deliberate rather than picking the candidate
    with fewest machines: proliferation cuts machine count but forbids direct
    insertion on the sprayed edges, so fewer machines can still lay out larger.
    Only laying them out actually settles it.

    An attempt whose validator reports errors is never selected, even when it is
    the smallest -- a blueprint that pastes cleanly and then does not run is the
    worst outcome available here, since nothing surfaces the failure until you
    are standing in front of it in game.
    """
    data = dataset if dataset is not None else load_vendored()
    request = parse_url(url)

    # A FactorioLab flow export pins WHICH recipe makes what, so we stop
    # re-deriving a decision the player already made. It is applied here, to the
    # request, because the rate solver already treats a request's exclusion set
    # as authoritative -- so pinning needs no new concept downstream and a build
    # without a flow file takes a byte-identical path.
    #
    # There is deliberately no fallback: `load_flow` and `pin_request` raise
    # rather than shrug, because quietly re-deriving the selection is the exact
    # behaviour this argument exists to remove.
    # `--flow` wins over `--fetch-flow`: a file the user chose to hand us is a
    # deliberate act, and silently going to the network instead would be
    # surprising. Both routes end at the same `verify_provenance`.
    selection: FlowSelection | None = None
    if flow is not None:
        selection = load_flow(flow, url=url)
    elif fetch_flow:
        selection = flow_from_text(
            capture_flow_csv(url, timeout_s=fetch_timeout_s, browser=browser), url=url
        )
    if selection is not None:
        request = pin_request(request, data, selection)

    spec_set = build_candidates(data, request, count=candidates, flow=selection)

    # With a flow pinned, a candidate that belts in something FactorioLab's own
    # flow does not is not a legal candidate for this build -- the boundary rule
    # outranks density, and this is where it bites. The frontier trades machines
    # for proliferation, and proliferator arrives on a belt: against an
    # unproliferated flow, choosing `max-proliferation` would quietly add an
    # input the player never asked for. Caught by the first real capture, which
    # picked exactly that candidate and asked for proliferator-3 against a flow
    # whose Modules column is empty.
    #
    # Filtered rather than refused outright: the unproliferated candidate is
    # legal and present, so dropping the illegal ones keeps the build while
    # honouring the boundary. If NONE survive we refuse, naming each.
    if selection is not None:
        exempt = (
            frozenset(
                i
                for spec in spec_set.candidates
                for i in spec.external_inputs
                if i.startswith("proliferator")
            )
            if selection.uses_proliferator
            else frozenset()
        )
        legal: list[tuple[BuildSpec, tuple[str, ...]]] = []
        illegal: list[tuple[BuildSpec, tuple[str, ...]]] = []
        for spec in spec_set.candidates:
            stray = unsupplied_inputs(selection, data, spec.external_inputs, exempt=exempt)
            (legal if not stray else illegal).append((spec, stray))
        if not legal:
            raise FlowError(
                "every candidate would ask for inputs the supplied flow does not "
                "belt in, so none can be built without changing the inputs "
                "FactorioLab chose: "
                + "; ".join(f"{spec.label} wants {list(stray)}" for spec, stray in illegal)
            )
        spec_set = BuildSpecSet(candidates=tuple(spec for spec, _ in legal))
        flow_dropped = tuple(
            f"{spec.label}: dropped, would belt in {list(stray)}" for spec, stray in illegal
        )
    else:
        flow_dropped = ()

    wanted = list(_STRATEGIES) if strategy == "best" else [strategy]

    attempts: list[Attempt] = []
    refused: list[str] = []
    for spec in spec_set.candidates:
        for sname in wanted:
            layout = _STRATEGIES[sname](power=power)
            try:
                placement = layout.lay_out(spec, time_budget_s=time_budget_s)
            except NoValidLayout as exc:
                # One strategy failing a candidate is not a failed build -- the
                # others may well succeed. Record it so the reason survives to
                # the report rather than vanishing into an empty result.
                refused.append(f"{sname}/{spec.label}: {exc.reason}")
                continue
            # Pass the spec AND the id map. Without them the nine
            # spec-dependent checks are skipped, and a build that never ran its
            # throughput or proliferator checks reads as clean.
            report = validate.validate(
                placement,
                spec,
                ids=_id_map(spec),
                expect_power=power,
                max_belt_z=max_belt_z,
            )
            attempts.append(Attempt(spec.label, sname, placement, report))

    valid = [a for a in attempts if a.ok]
    if not attempts:
        raise NoValidLayout(
            "; ".join(refused) or "every strategy refused every candidate",
            spec_label=", ".join(s.label for s in spec_set.candidates),
            budget_s=time_budget_s,
        )
    # Prefer a valid layout. Falling back to the best invalid one is deliberate
    # and visible: the CLI refuses to emit it, and the report names the errors.
    # What must never happen is a broken layout being SELECTED over a working
    # one because it measured smaller -- which it will, since a missing net is a
    # missing belt run.
    pool = valid or attempts
    best = min(pool, key=lambda a: a.area)
    chosen_spec = next(s for s in spec_set.candidates if s.label == best.candidate)

    # Label the belts you have to connect to something. Done here rather than
    # in each strategy: it needs only the Placement graph plus the spec's
    # external inputs, so one implementation covers every layout backend.
    marked = markers.mark_external_inputs(best.placement, chosen_spec)

    # Titles ride on the Placement, not on encode(), so stamp them here.
    labelled = replace(
        marked,
        short_desc=name or chosen_spec.label,
        description=(
            f"flab2bp {best.strategy} layout, {chosen_spec.label} candidate, "
            f"{chosen_spec.machine_count} machines, {best.area} tiles"
        ),
    )
    # Cross-check rather than trust. With the selection pinned this must be
    # empty; anything it names is the pin leaking, and a named leak is worth far
    # more than a silent one.
    findings: tuple[str, ...] = ()
    if selection is not None:
        # The boundary rule is a REFUSAL, not a finding: an input FactorioLab's
        # flow does not contain is the stone bug itself, and shipping the belt
        # would change the inputs the player chose. Proliferator is the one
        # known exemption -- FactorioLab builds it, we belt it in, and removing
        # that asymmetry is separate work that moves the layout stage.
        # A post-condition on what we actually chose. The candidate filter above
        # should have made this unreachable; it is here because "should have" is
        # not a guarantee, and shipping the belt is the failure we cannot take
        # back.
        stray = unsupplied_inputs(
            selection,
            data,
            chosen_spec.external_inputs,
            exempt=(
                frozenset(
                    i for i in chosen_spec.external_inputs if i.startswith("proliferator")
                )
                if selection.uses_proliferator
                else frozenset()
            ),
        )
        if stray:
            raise FlowError(
                f"this build would ask for {list(stray)}, which the supplied flow "
                "does not belt in. FactorioLab's chosen inputs may not be changed, "
                "so refusing rather than emitting a blueprint that demands them."
            )
        findings = cross_check(
            selection,
            data,
            machines={g.recipe_id: g.count for g in chosen_spec.groups},
            machine_items={g.recipe_id: g.machine_item_id for g in chosen_spec.groups},
            external_inputs=chosen_spec.external_inputs,
            outputs=chosen_spec.outputs,
            display_rate=request.display_rate,
        )

    blueprint = codec.encode(labelled)
    return Build(
        spec=chosen_spec,
        placement=labelled,
        report=best.report,
        strategy=best.strategy,
        blueprint=blueprint,
        attempts=tuple(attempts),
        refused=tuple(refused),
        flow_findings=findings + flow_dropped,
        flow_pinned=selection is not None,
    )
