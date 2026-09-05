"""URL in, blueprint string out.

The five stages wired together.  Everything here is orchestration -- no stage
logic lives in this module, so a change of strategy or of rate model does not
touch it.

    URL -> LabRequest -> BuildSpecSet -> Placement -> blueprint string
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from fractions import Fraction
from pathlib import Path
from typing import Literal

from flab2bp.dsp import catalog, codec
from flab2bp.lab.capture import UrlValidator, capture_flow_csv
from flab2bp.lab.data import load_vendored
from flab2bp.lab.flow import (
    FlowError,
    FlowSelection,
    _pin_request_canonical,
    canonicalize_dataset,
    canonicalize_request,
    cross_check,
    flow_from_text,
    load_flow,
    unsupplied_inputs,
)
from flab2bp.lab.schema import Dataset
from flab2bp.lab.techs import belt_rules_for_url
from flab2bp.lab.url import parse_url
from flab2bp.layout import finalize, markers, strategy_race, validate
from flab2bp.layout.band_policy import BandPolicy, BandSelection
from flab2bp.layout.base import (
    ATOMIC_COMPLETION_GRACE_S,
    LayoutAttemptFailure,
    NoValidLayout,
    Placement,
    PlacementCompletion,
    ProjectionFailureRecord,
)
from flab2bp.layout.freeform import FreeformLayout
from flab2bp.layout.sequence_solver import SequencePairLayout, _validate_sequence_islands
from flab2bp.rates.adjust import ProliferatorTier
from flab2bp.rates.candidates import (
    DEFAULT_CANDIDATE_POLICIES,
    CandidatePolicy,
    _build_candidates_canonical,
)
from flab2bp.spec import BuildSpec, BuildSpecSet

ExplicitStrategyName = Literal["freeform", "sequence-pair"]
StrategyName = Literal["best", "freeform", "sequence-pair"]

STRATEGY_CHOICES: tuple[StrategyName, ...] = (
    "best",
    "freeform",
    "sequence-pair",
)
#: Explicit strategies included when callers request ``best``.
PRODUCTION_STRATEGIES: tuple[ExplicitStrategyName, ...] = (
    "freeform",
    "sequence-pair",
)
PRODUCTION_STRATEGY_COUNT = len(PRODUCTION_STRATEGIES)

#: Default aggregate solver-worker budget for one build. More logical CPUs do
#: not improve these time-limited searches enough to justify making every
#: workstation run them unbounded.
DEFAULT_WORKER_BUDGET_CAP = 16


def _available_cpu_count() -> int:
    """Return the CPU set this process may actually schedule on."""
    try:
        return max(1, len(os.sched_getaffinity(0)))
    except (AttributeError, OSError):
        return max(1, os.process_cpu_count() or 1)


def _worker_allocations(
    total_workers: int,
    concurrent_candidates: int,
) -> tuple[int, ...]:
    """Divide one worker budget exactly across a concurrent candidate batch."""
    per_candidate, remainder = divmod(total_workers, concurrent_candidates)
    return tuple(
        per_candidate + int(index < remainder) for index in range(concurrent_candidates)
    )


def _candidate_race_parallelism(
    total_workers: int,
    candidate_count: int,
    requested_parallelism: int,
    sequence_islands: int,
) -> int:
    """Return the widest candidate batch whose nested races fit the budget."""
    widest = min(candidate_count, requested_parallelism)
    for parallelism in range(widest, 0, -1):
        allocations = _worker_allocations(total_workers, parallelism)
        if all(
            candidate_workers >= PRODUCTION_STRATEGY_COUNT
            and strategy_race.race_worker_split(candidate_workers)[1] >= sequence_islands
            for candidate_workers in allocations
        ):
            return parallelism
    return 0


def _strategy_names(strategy: StrategyName) -> tuple[ExplicitStrategyName, ...]:
    """Resolve a request to the implemented production strategies."""
    if strategy == "best":
        return PRODUCTION_STRATEGIES
    return (strategy,)


def _new_layout(
    strategy: ExplicitStrategyName,
    *,
    belt_vertical_construction: bool,
    sequence_islands: int = 1,
    band_policy: BandPolicy,
    #: CP-SAT search workers for the one backend that has a multi-threaded
    #: solve.  ``None`` keeps freeform's own default (all cores), which is what
    #: every caller got before racing existed.  ``SequencePairLayout`` takes no
    #: such argument: its sub-solves are pinned at one worker each, so its share
    #: of a split is headroom for its process rather than a solver setting.
    workers: int | None = None,
) -> FreeformLayout | SequencePairLayout:
    """Construct one explicitly selected layout backend."""
    if strategy == "freeform":
        return FreeformLayout(
            belt_vertical_construction=belt_vertical_construction,
            band_policy=band_policy,
            workers=workers,
        )
    return SequencePairLayout(
        belt_vertical_construction=belt_vertical_construction,
        islands=sequence_islands,
        band_policy=band_policy,
    )


#: One settled pair: its strategy, 1-based index, solve start, optional race
#: finish, completion grace, and result. The race finish excludes time spent
#: waiting for peer candidates or earlier settlement from this pair's wall.
_Resolved = tuple[
    ExplicitStrategyName,
    int,
    float,
    float | None,
    float,
    Placement | NoValidLayout,
]
_CandidateRace = tuple[float, float, tuple[strategy_race._StrategyRaceOutcome, ...]]


def _raced_result(
    outcome: strategy_race._StrategyRaceOutcome,
    spec_label: str,
    budget_s: float,
) -> Placement | NoValidLayout:
    """Reduce one arm's outcome to the two shapes a serial solve returns.

    Only ``completed`` carries geometry.  ``refused``, ``terminated`` and
    ``crashed`` all become a refusal, so the reason reaches ``Build.refused``
    instead of being lost: a terminated arm has no placement at all, and
    admitting it as an ``Attempt`` would put a hole into the selection below.
    """
    if outcome.status == "completed" and outcome.placement is not None:
        outcome.placement.stats.update(
            {
                "process_wall_time_s": outcome.process_wall_time_s,
                "process_user_cpu_s": outcome.process_user_cpu_s,
                "process_system_cpu_s": outcome.process_system_cpu_s,
                "process_peak_rss_kib": outcome.process_peak_rss_kib,
            }
        )
        return outcome.placement
    return NoValidLayout(
        outcome.refusal_reason or f"{outcome.strategy} produced nothing",
        spec_label=spec_label,
        budget_s=budget_s,
        projection_failures=outcome.refusal_projection_failures,
    )


#: Outputs named in a title before it gives up and counts the rest.
_TITLE_OUTPUTS = 2

#: Dyson Sphere Program's save check uses C# ``string.Length`` on this field.
BLUEPRINT_SHORT_DESC_UTF16_LIMIT = 60


def _utf16_units(text: str) -> int:
    """Return the number of C# UTF-16 code units in ``text``."""
    return sum(2 if ord(char) > 0xFFFF else 1 for char in text)


def _utf16_prefix(text: str, max_units: int) -> str:
    """The longest prefix that fits without splitting an astral character."""
    used = 0
    for index, char in enumerate(text):
        width = 2 if ord(char) > 0xFFFF else 1
        if used + width > max_units:
            return text[:index]
        used += width
    return text


def _ellipsize_utf16(
    text: str,
    max_units: int = BLUEPRINT_SHORT_DESC_UTF16_LIMIT,
) -> str:
    """Fit arbitrary text in ``max_units``, reserving one unit for ``…``."""
    if _utf16_units(text) <= max_units:
        return text
    if max_units < 1:
        return ""
    return _utf16_prefix(text, max_units - 1) + "…"


def _product_initials(product_id: str) -> str:
    """Uppercase word initials, preserving whole numeric hyphen tokens."""
    initials = "".join(
        part if part.isdigit() else part[0].upper() for part in product_id.split("-") if part
    )
    return initials or product_id.upper()


def _ranked_title_outputs(spec: BuildSpec) -> list[tuple[str, Fraction]]:
    return sorted(spec.outputs.items(), key=lambda kv: (-kv[1], kv[0]))


def _abbreviate_displayed_product(
    title: str,
    products: Sequence[str],
    target_index: int,
) -> str:
    """Replace the requested displayed product, not an earlier substring."""
    search_from = 0
    for index, product in enumerate(products):
        start = title.index(product, search_from)
        if index == target_index:
            return title[:start] + _product_initials(product) + title[start + len(product) :]
        search_from = start + len(product)
    return title


def _rate_per_minute(per_second: Fraction) -> str:
    """A per-second rate as the per-minute figure a player thinks in.

    FactorioLab's own ``*60`` means sixty per MINUTE, and the spec carries it as
    ``1`` per second, so a title has to multiply back or it reads as a sixtieth
    of what was asked for.  Whole numbers stay whole; anything else keeps two
    decimals, because ``0.83/min`` is a rate and ``5/6/min`` is a puzzle.
    """
    per_minute = per_second * 60
    if per_minute.denominator == 1:
        return str(per_minute.numerator)
    return f"{float(per_minute):.2f}".rstrip("0").rstrip(".")


def _title(spec: BuildSpec) -> str:
    """What this blueprint MAKES, which is what a player is looking for.

    The candidate label -- ``all-products``, ``output-products`` or
    ``no-proliferator`` -- says how the rates were solved, not what comes out,
    and it used to be the whole title. Two blueprints in a library both called
    ``all-products`` are indistinguishable; ``super-magnetic-ring 60/min`` is not.

    The label is not thrown away: it stays in the description, where provenance
    belongs, and a proliferated candidate still says so here -- but after the
    product, never instead of it.
    """
    if not spec.outputs:
        return spec.label or "flab2bp"

    ranked = _ranked_title_outputs(spec)
    named = ", ".join(
        f"{item} {_rate_per_minute(rate)}/min" for item, rate in ranked[:_TITLE_OUTPUTS]
    )
    if len(ranked) > _TITLE_OUTPUTS:
        named += f" +{len(ranked) - _TITLE_OUTPUTS} more"

    # Only when there is something to say. Every spec has a proliferation
    # answer; only two of the three are worth a player's attention.
    note = {
        "all-products": " (all products)",
        "output-products": " (output products)",
    }.get(spec.label or "", "")
    return named + note


def _generated_title(spec: BuildSpec) -> str:
    """Compose the normal title, then fit only auto-generated names for the game."""
    title = _title(spec)
    if _utf16_units(title) <= BLUEPRINT_SHORT_DESC_UTF16_LIMIT:
        return title

    products = [item for item, _rate in _ranked_title_outputs(spec)[:_TITLE_OUTPUTS]]
    for index in (1, 0):
        if index >= len(products):
            continue
        title = _abbreviate_displayed_product(title, products, index)
        if _utf16_units(title) <= BLUEPRINT_SHORT_DESC_UTF16_LIMIT:
            return title
    return _ellipsize_utf16(title)


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
    for item in (*spec.external_inputs, *spec.outputs, *spec.surplus_outputs):
        got = catalog.get_item_id(item)
        if got is not None:
            items[item] = got
    return validate.IdMap(recipes=recipes, items=items)


def _projection_records(
    failures: Sequence[finalize.ProjectionFailure],
) -> tuple[ProjectionFailureRecord, ...]:
    return tuple(
        ProjectionFailureRecord(
            failure.band,
            failure.check,
            failure.buildings,
            failure.detail,
        )
        for failure in failures
    )


@dataclass(frozen=True, slots=True)
class Attempt:
    """One (candidate, strategy) pair laid out."""

    candidate: str
    strategy: str
    #: The spec this attempt was laid out from.  The web payload reports each
    #: attempt's own boundary -- machines, belt-in, outputs -- and without the
    #: spec only the winner's would survive to JSON.
    spec: BuildSpec
    placement: Placement
    report: validate.Report
    blueprint: str
    #: Measured before display-only input markers are added to the blueprint.
    layout_area: int

    @property
    def area(self) -> int:
        return self.layout_area

    @property
    def ok(self) -> bool:
        return self.report.ok


@dataclass(frozen=True, slots=True)
class AttemptProgress:
    """Where a build has got to, reported as each pair starts and settles.

    A build's wall clock is ``candidates x strategies x budget`` plus rates,
    validation and encoding, and nothing outside this loop can tell which of
    those pairs is currently running.  A caller with a progress bar therefore
    has exactly two choices: guess from elapsed time, or be told.  This is being
    told.

    ``index`` is 1-based over ``total`` pairs, counted AFTER any flow filter has
    dropped the illegal candidates, so it never counts a pair that will not run.
    """

    index: int
    total: int
    candidate: str
    strategy: str
    #: ``started`` fires before the solve; the other two after it settles.
    phase: Literal["started", "laid-out", "refused"]
    #: Tiles, on ``laid-out``.
    area: int | None = None
    #: Whether the validator passed it, on ``laid-out``.
    ok: bool | None = None
    #: Why the strategy gave up, on ``refused``.
    reason: str | None = None
    #: Ordered, distinct projection evidence for this refused attempt.
    projection_failures: tuple[ProjectionFailureRecord, ...] = ()


#: Told what a build is doing, as it does it.  Deliberately not wrapped in a
#: try/except: a progress sink that raises is a bug in the caller, and a build
#: that swallowed it would report a number nobody produced.
ProgressSink = Callable[[AttemptProgress], None]


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
    refused: tuple[LayoutAttemptFailure, ...] = field(default_factory=tuple)
    #: Ways the chosen build's recipe set differs from the pinned flow's, if one
    #: was supplied.  Empty when no flow was given OR when we reproduced it: the
    #: CLI says which, because "no findings" and "nothing was checked" are very
    #: different claims and only one of them is reassuring.
    flow_findings: tuple[str, ...] = field(default_factory=tuple)
    #: Whether a FactorioLab flow export pinned the recipe selection.
    flow_pinned: bool = False
    #: The belt altitude rules this build was judged against, and whether
    #: they were READ from the URL's technology set or assumed from a new
    #: save.  Reported, because "we assumed" and "the URL said" are very
    #: different claims about a ceiling.
    belt_rules: catalog.BeltAltitudeRules | None = None


def build(
    url: str,
    *,
    strategy: StrategyName = "best",
    band: BandSelection = "portable",
    candidate_policies: tuple[CandidatePolicy, ...] = DEFAULT_CANDIDATE_POLICIES,
    time_budget_s: float = 15.0,
    proliferator_tier: ProliferatorTier | None = None,
    #: Legal with ``best`` as well as ``sequence-pair``, because islands live
    #: inside the raced sequence-pair arm. Under ``race=True`` the aggregate
    #: worker allocator reserves enough of each candidate's share for every
    #: island. If even a single two-strategy race cannot fund them, strategies
    #: run serially instead.
    sequence_islands: int = 1,
    dataset: Dataset | None = None,
    name: str = "",
    flow: Path | None = None,
    #: A FactorioLab flow export as TEXT rather than a path.  Same pin, same
    #: provenance check, same door -- ``flow_from_text`` is what ``load_flow``
    #: calls once it has read the file.  It exists because the web front ends
    #: receive an upload or a paste and have no file to name: writing that to a
    #: temporary path just to read it back would put a filesystem, and its
    #: failure modes, between the user's bytes and the parser.
    flow_text: str | None = None,
    fetch_flow: bool = False,
    fetch_timeout_s: float = 90.0,
    browser: str | None = None,
    fetch_url_validator: UrlValidator | None = None,
    no_proliferator: bool = False,
    on_progress: ProgressSink | None = None,
    #: Aggregate solver-worker budget for one build. ``None`` uses at most 16
    #: CPUs from the process affinity set. A serial build gives the whole budget
    #: to its current strategy; concurrent candidate races divide it exactly
    #: and reserve the SequencePair arm's island processes.
    workers: int | None = None,
    #: Candidate races to run at once. ``None`` admits the widest batch whose
    #: candidate shares fund Freeform plus every requested SequencePair island.
    #: An unfunded two-strategy race falls back to serial strategies.
    candidate_parallelism: int | None = None,
    #: Race the two strategies for ONE budget instead of running them serially
    #: for one budget EACH.  OFF by default until the flip commit: a change this
    #: large in wall time and process count opts in before it opts everyone in.
    race: bool = False,
    #: Exchange certified incumbents and cluster no-goods between the racers.
    #: Meaningless unless ``race`` is true.
    share: bool = True,
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
    policy = BandPolicy.parse(band)
    _validate_sequence_islands(sequence_islands)
    # Islands now live INSIDE the sequence-pair racer, so `best` may ask for
    # them: the raced sequence-pair child constructs its own SequencePairLayout
    # with this island count. `freeform` still may not -- it has no islands.
    if sequence_islands != 1 and strategy not in ("sequence-pair", "best"):
        raise ValueError("sequence islands require --strategy sequence-pair or best")
    if workers is not None and (type(workers) is not int or workers < 1):
        raise ValueError("workers must be a positive integer")
    worker_budget = (
        workers
        if workers is not None
        else min(_available_cpu_count(), DEFAULT_WORKER_BUDGET_CAP)
    )
    if strategy in ("sequence-pair", "best") and sequence_islands > worker_budget:
        raise ValueError("sequence islands cannot exceed worker budget")
    if candidate_parallelism is not None and (
        type(candidate_parallelism) is not int or candidate_parallelism < 1
    ):
        raise ValueError("candidate parallelism must be a positive integer")
    if (
        candidate_parallelism is not None
        and candidate_parallelism > 1
        and (strategy != "best" or not race)
    ):
        raise ValueError("candidate parallelism requires a raced best-strategy build")
    data = canonicalize_dataset(dataset if dataset is not None else load_vendored())
    request = canonicalize_request(parse_url(url))
    # How high a belt may go, and whether it may climb with no run at all, are
    # properties of the player's SAVE -- so they come from the technologies
    # FactorioLab already recorded in the URL, not from a flag whose default we
    # would have to guess.
    belt_rules = belt_rules_for_url(url, data)

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
    if flow is not None and flow_text is not None:
        # Not a precedence rule. Two flows are two different recipe selections,
        # and picking one silently would pin the build to a selection the
        # caller did not choose -- the exact failure `--flow` exists to remove.
        raise ValueError(
            "both a flow file and flow text were supplied. Pass one: they are "
            "two different recipe selections and there is no right guess."
        )
    selection: FlowSelection | None = None
    if flow is not None:
        selection = load_flow(flow, url=url)
    elif flow_text is not None:
        selection = flow_from_text(flow_text, url=url)
    elif fetch_flow:
        selection = flow_from_text(
            capture_flow_csv(
                url,
                timeout_s=fetch_timeout_s,
                browser=browser,
                url_validator=fetch_url_validator,
            ),
            url=url,
        )
    if selection is not None:
        request = _pin_request_canonical(request, data, selection)

    spec_set = _build_candidates_canonical(
        data,
        request,
        tier=proliferator_tier,
        candidate_policies=candidate_policies,
        flow=selection,
    )

    # With a flow pinned, a candidate that belts in something FactorioLab's own
    # flow does not is not a legal candidate for this build -- the boundary rule
    # outranks density, and this is where it bites. The frontier trades machines
    # for proliferation, and proliferator arrives on a belt: against an
    # unproliferated flow, either products policy would quietly add an input the
    # player never asked for.
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

    # Asked for a build with no proliferation at all. Keep the candidates whose
    # every group is unsprayed, and refuse if none is -- silently building a
    # sprayed one would be the fallback this project does not do, and a
    # particularly bad one, since the caller asked for no coaters.
    #
    # Read off `MachineGroup.proliferator_mode`, never off the candidate's
    # label: the label is a name the frontier chose, and `no-proliferator` is
    # only reliably that candidate by convention. The mode is the thing that
    # decides whether a Spray Coater is emitted.
    if no_proliferator:
        unsprayed = tuple(
            spec
            for spec in spec_set.candidates
            if not any(group.is_proliferated for group in spec.groups)
        )
        if not unsprayed:
            raise ValueError(
                "every candidate this URL produced sprays something, so "
                "--no-proliferator cannot be honoured: "
                + ", ".join(spec.label or "?" for spec in spec_set.candidates)
                + ". The fixed frontier must always include no-proliferator."
            )
        spec_set = BuildSpecSet(candidates=unsprayed)

    wanted = _strategy_names(strategy)
    strategy_race_parallelism = 0
    if strategy == "best" and race:
        requested_parallelism = candidate_parallelism or len(spec_set.candidates)
        strategy_race_parallelism = _candidate_race_parallelism(
            worker_budget,
            len(spec_set.candidates),
            requested_parallelism,
            sequence_islands,
        )
    resolved_candidate_parallelism = max(1, strategy_race_parallelism)

    # Counted here, after the flow filter, so a progress report never promises a
    # pair that was already dropped.
    total_pairs = len(spec_set.candidates) * len(wanted)

    attempts: list[Attempt] = []
    refused: list[LayoutAttemptFailure] = []

    def _announce(index: int, candidate: str, sname: ExplicitStrategyName) -> None:
        """Report that a pair has started.  Fired BEFORE its solve, both modes."""
        if on_progress is not None:
            on_progress(
                AttemptProgress(
                    index=index,
                    total=total_pairs,
                    candidate=candidate,
                    strategy=sname,
                    phase="started",
                )
            )

    def _solve_one(candidate: BuildSpec, sname: ExplicitStrategyName) -> Placement | NoValidLayout:
        """The pre-racing path, returning the refusal instead of raising it.

        The loop below branches on the RESULT rather than catching, so one shape
        handles a raced pair and a serial one.
        """
        layout = _new_layout(
            sname,
            belt_vertical_construction=belt_rules.vertical_construction,
            sequence_islands=sequence_islands,
            band_policy=policy,
            workers=worker_budget,
        )
        try:
            return layout.lay_out(candidate, time_budget_s=time_budget_s)
        except NoValidLayout as exc:
            return exc

    def _solve_serially(candidate: BuildSpec, first_index: int) -> Iterator[_Resolved]:
        """Yield one solved pair at a time, exactly as the pre-racing loop did.

        A generator and not a tuple, deliberately.  Each attempt's compaction,
        finalization, validation and encoding must run before the NEXT strategy
        starts: solving both up front would leave the first attempt's
        finalization to begin a whole budget past its own ``attempt_deadline``,
        and refuse a placement that is fine.
        """
        for offset, sname in enumerate(wanted):
            _announce(first_index + offset, candidate.label, sname)
            attempt_started = time.monotonic()
            result = _solve_one(candidate, sname)
            yield (
                sname,
                first_index + offset,
                attempt_started,
                None,
                ATOMIC_COMPLETION_GRACE_S,
                result,
            )

    def _run_race(candidate: BuildSpec, candidate_workers: int) -> _CandidateRace:
        """Run one candidate's strategy race and retain its actual wall."""
        race_started = time.monotonic()
        outcomes = strategy_race.run_strategy_race(
            candidate,
            time_budget_s=time_budget_s,
            band_policy=policy,
            belt_vertical_construction=belt_rules.vertical_construction,
            max_belt_z=belt_rules.max_z,
            workers=candidate_workers,
            sequence_islands=sequence_islands,
            share=share,
        )
        return race_started, time.monotonic(), outcomes

    def _solve_candidate_batches() -> Iterator[tuple[int, BuildSpec, _CandidateRace]]:
        """Yield one completed batch before admitting the next."""
        parallelism = resolved_candidate_parallelism
        with ThreadPoolExecutor(
            max_workers=parallelism,
            thread_name_prefix="flab2bp-candidate",
        ) as executor:
            for batch_start in range(0, len(spec_set.candidates), parallelism):
                batch = spec_set.candidates[batch_start : batch_start + parallelism]
                for offset_in_batch, spec in enumerate(batch):
                    candidate_ordinal = batch_start + offset_in_batch
                    first_index = candidate_ordinal * len(wanted) + 1
                    for offset, sname in enumerate(wanted):
                        _announce(first_index + offset, spec.label, sname)
                allocations = _worker_allocations(worker_budget, len(batch))
                futures = tuple(
                    executor.submit(_run_race, spec, candidate_workers)
                    for spec, candidate_workers in zip(batch, allocations, strict=True)
                )
                results = tuple(future.result() for future in futures)
                for offset_in_batch, (spec, result) in enumerate(
                    zip(batch, results, strict=True)
                ):
                    yield batch_start + offset_in_batch, spec, result

    parallel_candidates = resolved_candidate_parallelism > 1
    candidate_runs: Iterable[tuple[int, BuildSpec, _CandidateRace | None]]
    if parallel_candidates:
        candidate_runs = _solve_candidate_batches()
    else:
        candidate_runs = (
            (candidate_ordinal, spec, None)
            for candidate_ordinal, spec in enumerate(spec_set.candidates)
        )

    for candidate_ordinal, spec, candidate_race in candidate_runs:
        #: 1-based over ``total_pairs``, candidates outer and strategies inner.
        #: Derived rather than counted so the raced branch, which settles a
        #: candidate's pairs together, cannot renumber them.
        first_index = candidate_ordinal * len(wanted) + 1
        solved: Iterable[_Resolved]
        if strategy_race_parallelism:
            if candidate_race is None:
                # Both arms genuinely start together, so both are announced
                # BEFORE the race. Told afterwards, a caller's progress bar
                # would sit silent for a whole budget and then jump by two.
                for offset, sname in enumerate(wanted):
                    _announce(first_index + offset, spec.label, sname)
                race_started, race_finished, outcomes = _run_race(spec, worker_budget)
            else:
                race_started, race_finished, outcomes = candidate_race
            by_strategy = {outcome.strategy: outcome for outcome in outcomes}
            if set(by_strategy) != set(wanted):
                # A lost arm must never read as a complete build: `total_pairs`
                # promised a settlement for each, and the selection below would
                # happily pick a winner from whatever came back without ever
                # saying that one of them went missing.
                raise ValueError(
                    f"the race settled {sorted(by_strategy)} but this build "
                    f"asked for {sorted(wanted)}"
                )
            solved = [
                (
                    sname,
                    first_index + offset,
                    race_started,
                    race_finished,
                    strategy_race.RACE_COMPLETION_GRACE_S,
                    _raced_result(by_strategy[sname], spec.label, time_budget_s),
                )
                for offset, sname in enumerate(wanted)
            ]
        else:
            solved = _solve_serially(spec, first_index)

        for (
            sname,
            pair_index,
            attempt_started,
            result_finished,
            completion_grace_s,
            result,
        ) in solved:
            if isinstance(result, NoValidLayout):
                # One strategy failing a candidate is not a failed build -- the
                # others may well succeed. Record it so the reason survives to
                # the report rather than vanishing into an empty result.
                failure = LayoutAttemptFailure(
                    candidate=spec.label,
                    strategy=sname,
                    reason=result.reason,
                    projection_failures=result.projection_failures,
                )
                refused.append(failure)
                if on_progress is not None:
                    on_progress(
                        AttemptProgress(
                            index=pair_index,
                            total=total_pairs,
                            candidate=spec.label,
                            strategy=sname,
                            phase="refused",
                            reason=result.reason,
                            projection_failures=failure.projection_failures,
                        )
                    )
                continue
            pipeline_compaction_time_s = 0.0
            pipeline_finalization_time_s = 0.0
            placement = result
            # Candidate peers may finish later, and the previous arm's
            # settlement runs serially. Neither delay belongs to this attempt.
            settlement_started = time.monotonic()
            settlement_wait_s = (
                0.0
                if result_finished is None
                else max(0.0, settlement_started - result_finished)
            )
            # A HARD wall per attempt, in the one place that can see the whole
            # cost. A strategy's own budget covers its search; compaction,
            # projection, validation and encoding consume its remaining grace.
            # Shift only by time spent waiting to be settled, never by solve
            # time, so a real solver overshoot still expires immediately.
            attempt_deadline = (
                attempt_started
                + time_budget_s
                + completion_grace_s
                + settlement_wait_s
            )

            def attempt_expired(_deadline: float = attempt_deadline) -> bool:
                return time.monotonic() >= _deadline

            if placement.completion is not PlacementCompletion.COMPACTED_AND_FINALIZED:
                phase_started = time.monotonic()
                try:
                    placement = finalize.compact_open_boundary_belts(
                        placement,
                        spec,
                        expect_power=True,
                    )
                finally:
                    pipeline_compaction_time_s = time.monotonic() - phase_started
                phase_started = time.monotonic()
                try:
                    placement = finalize.finalize_placement(
                        placement,
                        policy,
                        cancelled=attempt_expired,
                    )
                except finalize.ProjectionRefusal as exc:
                    reason = str(exc)
                    failure = LayoutAttemptFailure(
                        candidate=spec.label,
                        strategy=sname,
                        reason=reason,
                        projection_failures=_projection_records(exc.failures),
                    )
                    refused.append(failure)
                    if on_progress is not None:
                        on_progress(
                            AttemptProgress(
                                index=pair_index,
                                total=total_pairs,
                                candidate=spec.label,
                                strategy=sname,
                                phase="refused",
                                reason=reason,
                                projection_failures=failure.projection_failures,
                            )
                        )
                    continue
                except finalize.ProjectionCancelled:
                    # Every other call site that hands `finalize_placement` a
                    # `cancelled` predicate (freeform.py, sequence_solver.py)
                    # catches this alongside ProjectionRefusal.  It is a bare
                    # Exception, not a ProjectionRefusal subclass, so without
                    # this clause one attempt's deadline firing here would
                    # crash the whole build instead of refusing that attempt --
                    # exactly the failure this per-attempt deadline exists to
                    # replace with a reported number.
                    #
                    # `attempt_expired` is the only `cancelled` predicate this
                    # call site ever hands `finalize_placement`, so a
                    # ProjectionCancelled while it still reads False cannot BE
                    # an attempt-deadline cancellation -- some future,
                    # unrelated cancel source. Re-raise rather than mislabel it
                    # "deadline exhausted".
                    if not attempt_expired():
                        raise
                    reason = (
                        f"attempt deadline exhausted during finalization "
                        f"after {time.monotonic() - attempt_started - settlement_wait_s:.1f}s "
                        f"(budget {time_budget_s:g}s + grace "
                        f"{completion_grace_s:g}s)"
                    )
                    failure = LayoutAttemptFailure(
                        candidate=spec.label,
                        strategy=sname,
                        reason=reason,
                    )
                    refused.append(failure)
                    if on_progress is not None:
                        on_progress(
                            AttemptProgress(
                                index=pair_index,
                                total=total_pairs,
                                candidate=spec.label,
                                strategy=sname,
                                phase="refused",
                                reason=reason,
                            )
                        )
                    continue
                finally:
                    pipeline_finalization_time_s = time.monotonic() - phase_started
                placement = replace(
                    placement,
                    completion=PlacementCompletion.COMPACTED_AND_FINALIZED,
                )
            # Pass the spec AND the id map. Without them the nine
            # spec-dependent checks are skipped, and a build that never ran its
            # throughput or proliferator checks reads as clean.
            phase_started = time.monotonic()
            report = validate.validate(
                placement,
                spec,
                ids=_id_map(spec),
                expect_power=True,
                max_belt_z=belt_rules.max_z,
                belt_vertical_construction=belt_rules.vertical_construction,
            )
            pipeline_validation_time_s = time.monotonic() - phase_started
            marked = markers.mark_external_belts(placement, spec)
            labelled = replace(
                marked,
                short_desc=name or _generated_title(spec),
                description=(
                    f"flab2bp {sname} layout, {spec.label} candidate, "
                    f"{spec.machine_count} machines, {placement.area} tiles"
                ),
            )
            phase_started = time.monotonic()
            try:
                blueprint = codec.encode(labelled)
            except ValueError as exc:
                reason = f"blueprint encoding failed: {exc}"
                refused.append(
                    LayoutAttemptFailure(
                        candidate=spec.label,
                        strategy=sname,
                        reason=reason,
                    )
                )
                if on_progress is not None:
                    on_progress(
                        AttemptProgress(
                            index=pair_index,
                            total=total_pairs,
                            candidate=spec.label,
                            strategy=sname,
                            phase="refused",
                            reason=reason,
                        )
                    )
                continue
            pipeline_encoding_time_s = time.monotonic() - phase_started
            labelled.stats.update(
                {
                    "pipeline_compaction_time_s": pipeline_compaction_time_s,
                    "pipeline_finalization_time_s": pipeline_finalization_time_s,
                    "pipeline_validation_time_s": pipeline_validation_time_s,
                    "pipeline_encoding_time_s": pipeline_encoding_time_s,
                }
            )
            # Each raced arm is charged its shared race plus only its own
            # post-processing. Waiting for peer candidates or earlier arms to
            # settle is deliberately excluded.
            attempt_wall_s = (
                time.monotonic() - attempt_started - settlement_wait_s
            )
            labelled.stats["attempt_wall_s"] = attempt_wall_s
            labelled.stats["wall_overshoot_s"] = max(
                0.0,
                attempt_wall_s - time_budget_s - completion_grace_s,
            )
            attempts.append(
                Attempt(
                    spec.label,
                    sname,
                    spec,
                    labelled,
                    report,
                    blueprint,
                    placement.area,
                )
            )
            if on_progress is not None:
                on_progress(
                    AttemptProgress(
                        index=pair_index,
                        total=total_pairs,
                        candidate=spec.label,
                        strategy=sname,
                        phase="laid-out",
                        area=placement.area,
                        ok=report.ok,
                    )
                )

    valid = [a for a in attempts if a.ok]
    if not attempts:
        raise NoValidLayout(
            "; ".join(map(str, refused)) or "every strategy refused every candidate",
            spec_label=", ".join(s.label for s in spec_set.candidates),
            budget_s=time_budget_s,
            attempt_reasons=tuple(map(str, refused)),
            attempt_failures=tuple(refused),
            projection_failures=tuple(
                dict.fromkeys(
                    projection for failure in refused for projection in failure.projection_failures
                )
            ),
        )
    # Prefer a valid layout. Falling back to the best invalid one is deliberate
    # and visible: the CLI refuses to emit it, and the report names the errors.
    # What must never happen is a broken layout being SELECTED over a working
    # one because it measured smaller -- which it will, since a missing net is a
    # missing belt run.
    pool = valid or attempts
    best = min(
        pool,
        key=lambda attempt: (
            attempt.area,
            float(attempt.placement.stats.get("belt_tiles", float("inf"))),
        ),
    )
    chosen_spec = next(s for s in spec_set.candidates if s.label == best.candidate)

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
                frozenset(i for i in chosen_spec.external_inputs if i.startswith("proliferator"))
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

    return Build(
        spec=chosen_spec,
        placement=best.placement,
        report=best.report,
        strategy=best.strategy,
        blueprint=best.blueprint,
        attempts=tuple(attempts),
        refused=tuple(refused),
        flow_findings=findings + flow_dropped,
        flow_pinned=selection is not None,
        belt_rules=belt_rules,
    )
