"""Deterministic proliferation policies, priced after exact machine ceiling.

Spray is applied by belt-mounted coaters and does not survive crafting, so a
proliferated recipe needs its own inputs belted and gives up direct insertion.
The rate stage cannot price that geometry. It therefore emits three explicit
policies -- none, products everywhere legal, and products only on final-output
recipes -- then ranks their physical factories by rounded machine footprint.
The layout stage still lays out each candidate and keeps the smallest layout.
"""

from __future__ import annotations

import warnings
from fractions import Fraction
from math import gcd, lcm

from flab2bp.dsp import rules
from flab2bp.lab.flow import (
    FlowError,
    FlowSelection,
    canonicalize_dataset,
    canonicalize_request,
)
from flab2bp.lab.schema import Dataset
from flab2bp.lab.url import LabRequest
from flab2bp.rates.adjust import ProliferatorTier
from flab2bp.rates.solve import RateSolution, solve, target_producer_ids, target_rates
from flab2bp.spec import (
    BuildSpec,
    BuildSpecSet,
    CoproductBufferProof,
    MachineGroup,
    ProliferatorMode,
)

#: The deterministic mode frontier: none, all legal products, and products only
#: on recipes that directly produce a requested final output.
DEFAULT_CANDIDATES = 3


def _producer_of(solution: RateSolution, item_id: str) -> str | None:
    for group in solution.groups:
        if item_id in group.adjusted.outputs_per_craft:
            return group.recipe_id
    return None


_CHEMICAL_MACHINES = frozenset({"chemical-plant", "quantum-chemical-plant"})


def _rational_gcd(one: Fraction, two: Fraction) -> Fraction:
    denominator = lcm(one.denominator, two.denominator)
    return Fraction(
        gcd(
            one.numerator * (denominator // one.denominator),
            two.numerator * (denominator // two.denominator),
        ),
        denominator,
    )


def _coproduct_buffer_proofs(
    data: Dataset, solution: RateSolution
) -> tuple[CoproductBufferProof, ...]:
    """Prove isolated startup batches against the selected machine's buffer."""
    produced = {
        item_id for group in solution.groups for item_id in group.adjusted.outputs_per_craft
    }
    consumed = {item_id for group in solution.groups for item_id in group.adjusted.inputs_per_craft}
    proofs: list[CoproductBufferProof] = []
    for item_id in sorted(produced & consumed):
        producers = [
            group
            for group in solution.groups
            if item_id in group.adjusted.outputs_per_craft
            and len(data.recipe(group.recipe_id).outputs) > 1
        ]
        consumers = [
            group for group in solution.groups if item_id in group.adjusted.inputs_per_craft
        ]
        if len(producers) != 1 or len(consumers) != 1:
            continue
        producer = producers[0]
        consumer = consumers[0]
        if (
            producer.machines != 1
            or consumer.machines != 1
            or producer.machine_item_id not in _CHEMICAL_MACHINES
            or set(data.recipe(consumer.recipe_id).inputs) != {item_id}
            or not set(data.recipe(producer.recipe_id).inputs) <= set(solution.external_inputs)
        ):
            continue
        producer_batch = data.recipe(producer.recipe_id).outputs[item_id]
        consumer_batch = data.recipe(consumer.recipe_id).inputs[item_id]
        required = producer_batch + consumer_batch - _rational_gcd(producer_batch, consumer_batch)
        intrinsic = producer_batch * rules.CHEMICAL_OUTPUT_BUFFER_CRAFTS
        if intrinsic < required:
            continue
        proofs.append(
            CoproductBufferProof(
                item_id=item_id,
                producer_recipe_id=producer.recipe_id,
                consumer_recipe_id=consumer.recipe_id,
                producer_batch=producer_batch,
                consumer_batch=consumer_batch,
                required_capacity=required,
                intrinsic_capacity=intrinsic,
            )
        )
    return tuple(proofs)


def _to_build_spec(
    data: Dataset,
    request: LabRequest,
    solution: RateSolution,
    label: str,
) -> BuildSpec:
    """Project a solved plan onto the frozen rates/geometry contract."""
    groups: list[MachineGroup] = []
    for group in solution.groups:
        count = group.machines
        groups.append(
            MachineGroup(
                recipe_id=group.recipe_id,
                machine_item_id=group.machine_item_id,
                count=count,
                proliferator_mode=group.mode,
                # Per-machine *actual* flow, not machine capacity: a throttled
                # machine moves less, and belts are sized on what really flows.
                inputs_per_machine={k: v / count for k, v in group.inputs.items()},
                outputs_per_machine={k: v / count for k, v in group.outputs.items()},
            )
        )

    belt_required: set[tuple[str, str]] = set()
    spray_lanes: dict[str, bool] = {}
    for group in solution.groups:
        if group.mode is ProliferatorMode.NONE:
            continue
        for item_id in data.recipe(group.recipe_id).inputs:
            producer = _producer_of(solution, item_id)
            is_external = producer is None
            # A lane already marked internal stays internal.
            spray_lanes[item_id] = spray_lanes.get(item_id, True) and is_external
            if producer is not None:
                belt_required.add((producer, group.recipe_id))
    surplus_outputs = {
        item_id: rate
        for item_id, rate in solution.surplus.items()
        if item_id not in solution.outputs
    }

    belt_id = request.belt_id or "conveyor-belt-1"
    spec = BuildSpec(
        groups=tuple(groups),
        external_inputs=dict(solution.external_inputs),
        outputs=dict(solution.outputs),
        surplus_outputs=surplus_outputs,
        belt_item_id=belt_id,
        belt_items_per_second=data.belt_speed(belt_id),
        label=label,
        belt_required_edges=frozenset(belt_required),
        spray_lanes=spray_lanes,
        coproduct_buffer_proofs=_coproduct_buffer_proofs(data, solution),
    )
    # Needs the finished spec to compute, so fill it in on a copy.
    # BuildSpec is a pydantic model, so model_copy rather than dataclasses.replace.
    return spec.model_copy(update={"lanes_requiring_split": lanes_requiring_split(data, spec)})


def lanes_requiring_split(data: Dataset, spec: BuildSpec) -> frozenset[str]:
    """Sprayed lanes that also feed an unproliferated consumer.

    Such a lane must be split before it is built.  Spray rides on the items, not
    on the machine, so an unproliferated consumer drinking from a sprayed lane
    quietly receives a bonus nobody costed -- it over-produces, and the running
    factory stops matching the numbers in this ``BuildSpec``.

    Explicit policies can still mix proliferated and unproliferated consumers,
    especially ``output-products`` at the boundary of the final recipe. The
    lane must be split between those consumers.
    """
    consumers: dict[str, list[MachineGroup]] = {}
    for group in spec.groups:
        for item_id in data.recipe(group.recipe_id).inputs:
            consumers.setdefault(item_id, []).append(group)
    split: set[str] = set()
    for item_id in spec.spray_lanes:
        eaters = consumers.get(item_id, [])
        if any(g.is_proliferated for g in eaters) and any(not g.is_proliferated for g in eaters):
            split.add(item_id)
    return frozenset(split)


def proliferator_from_request(request: LabRequest) -> ProliferatorTier | None:
    """Which proliferator tier the URL asked for, if it asked for one.

    ``ProliferatorTier.module_id`` builds exactly the ids FactorioLab carries --
    ``proliferator-2-products`` and friends -- so this is that map inverted.

    It has to be read from THREE places, because where FactorioLab puts it
    depends on how the URL was written.  A bare URL carries ``mps=`` and lands
    in ``proliferator_spray_id``; a compressed ``z=`` URL lands in ``modules``,
    in each machine's own ``modules``, or both.  Reading only one form fixes
    half the URLs and looks like a fix.

    Three decisions, all deliberate.

    *Absence is not a constraint.*  A URL with no proliferator returns ``None``
    and the caller keeps its own default, because this tool exists to offer a
    density frontier and most URLs never mention proliferation at all.  Only a
    URL that names one is taken as pinning it.

    *The tier is the maximum named, not the minimum.*  A tier is an availability
    statement -- the sprayed item is belted in from outside, so asking for Mk.III
    asks the player to supply Mk.III.  If they named it anywhere, they have it.

    *The mode is not read.*  ``products`` versus ``speed`` is the frontier's own
    optimisation dimension, and both consume the same sprayed item, so honouring
    the tier costs the player nothing they did not authorise, while honouring
    the mode would remove the exploration that finds the denser build.
    """
    named = [request.proliferator_spray_id]
    named.extend(s.id for s in request.modules)
    for machine in request.machines.values():
        named.extend(s.id for s in machine.modules or ())

    by_id = {
        tier.module_id(mode): tier
        for tier in ProliferatorTier
        for mode in ProliferatorMode
        if tier.module_id(mode) is not None
    }
    tiers = [by_id[n] for n in named if n in by_id]
    return max(tiers, key=lambda t: int(t.value)) if tiers else None


def _proliferation_modes_from_flow(
    flow: FlowSelection,
    tier_override: ProliferatorTier | None = None,
) -> tuple[ProliferatorTier, dict[str, ProliferatorMode]]:
    """Read the exact proliferator mode authored for each flow recipe."""
    if tier_override is ProliferatorTier.NONE:
        return ProliferatorTier.NONE, {}

    by_id = {
        tier.module_id(mode): (tier, mode)
        for tier in ProliferatorTier
        for mode in ProliferatorMode
        if tier.module_id(mode) is not None
    }
    sprayed: dict[str, tuple[ProliferatorTier, ProliferatorMode]] = {}
    for recipe_id, module_id in flow.proliferator_modules().items():
        known = by_id.get(module_id)
        if known is None:
            raise FlowError(
                f"the flow sprays {module_id!r} on {recipe_id!r}, which is not a "
                "proliferator module this dataset defines. Either the export came "
                "from a different mod, or our vendored dataset is out of date."
            )
        sprayed[recipe_id] = known
    if not sprayed:
        return ProliferatorTier.NONE, {}
    tiers = {tier for tier, _ in sprayed.values()}
    if len(tiers) > 1 and tier_override is None:
        raise FlowError(
            "the flow sprays more than one proliferator tier "
            f"({sorted(t.value for t in tiers)}). This build takes a single tier, "
            "so honouring the flow exactly is not possible; choosing one would "
            "change what the block consumes."
        )
    selected_tier = tier_override if tier_override is not None else tiers.pop()
    return selected_tier, {recipe_id: mode for recipe_id, (_, mode) in sprayed.items()}


def proliferation_from_flow(
    flow: FlowSelection,
) -> tuple[ProliferatorTier, tuple[ProliferatorMode, ...], frozenset[str]]:
    """What FactorioLab's flow sprays: ``(tier, modes, recipes)``."""
    tier, by_recipe = _proliferation_modes_from_flow(flow)
    return tier, tuple(sorted(set(by_recipe.values()))), frozenset(by_recipe)


def _dark_fog_items(spec: BuildSpec) -> frozenset[str]:
    """Every synthetic Dark Fog id that would cross the blueprint boundary."""
    items = {
        item_id
        for item_id in (*spec.external_inputs, *spec.outputs, *spec.surplus_outputs)
        if item_id.startswith("df-")
    }
    for group in spec.groups:
        if group.recipe_id.startswith("df-"):
            items.add(group.recipe_id)
        items.update(item_id for item_id in group.inputs_per_machine if item_id.startswith("df-"))
        items.update(item_id for item_id in group.outputs_per_machine if item_id.startswith("df-"))
    return frozenset(items)


def _refuse_derived_dark_fog(spec: BuildSpec) -> None:
    """A URL alone cannot authorize a distinct DF-only source item."""
    items = sorted(_dark_fog_items(spec))
    if items:
        item_id = items[0]
        raise KeyError(
            f"{item_id!r} is a Dark Fog-only item with no normal DSP catalog "
            "identity, so derived solving cannot put it in a blueprint. Supply "
            "this URL's explicit flow to prove it is an external source."
        )


def _pinned_candidates(
    data: Dataset,
    request: LabRequest,
    flow: FlowSelection,
    time_limit_s: float,
    tier: ProliferatorTier | None = None,
) -> BuildSpecSet:
    """Build the single recipe/mode selection FactorioLab's flow describes.

    One candidate, not a frontier.  The frontier exists to explore choices the
    rate stage cannot price; when the player supplies a flow, its recipe and
    per-recipe mode choices stay pinned.

    With no explicit ``tier``, the flow also pins its proliferator tier because
    that tier is an implied input: the sprayed item is belted in from outside.
    An explicit caller selection deliberately replaces only that tier while
    retaining the flow's recipe and mode choices.  This changes the implied
    proliferator input, so it is permitted only through the explicit override;
    ``auto`` continues to preserve the flow exactly.
    """
    tier, fixed_modes = _proliferation_modes_from_flow(flow, tier)
    plan = solve(
        data,
        request,
        tier=tier,
        fixed_modes=fixed_modes,
        time_limit_s=time_limit_s,
    )
    label = "flow-pinned" if tier is ProliferatorTier.NONE else f"flow-pinned-mk{tier.value}"
    spec = _to_build_spec(data, request, plan, label)
    synthetic_groups = sorted(g.recipe_id for g in spec.groups if g.recipe_id.startswith("df-"))
    if synthetic_groups:
        raise FlowError(
            f"the pinned candidate selected synthetic Dark Fog recipe(s) "
            f"{synthetic_groups!r}; those rows are source provenance, never machines"
        )
    unlisted = sorted(_dark_fog_items(spec) - set(flow.by_item))
    if unlisted:
        raise FlowError(
            f"{unlisted[0]!r} is a Dark Fog source needed by the pinned candidate, "
            "but the supplied flow does not explicitly list that item"
        )
    specs = [spec]
    _assert_same_objective(data, request, specs)
    return BuildSpecSet(candidates=tuple(specs))


def build_candidates(
    data: Dataset,
    request: LabRequest,
    *,
    tier: ProliferatorTier | None = None,
    count: int = DEFAULT_CANDIDATES,
    time_limit_s: float = 30.0,
    flow: FlowSelection | None = None,
) -> BuildSpecSet:
    """Emit an ordered frontier of complete, valid builds.

    The deterministic frontier contains ``no-proliferator``, ``all-products``,
    then ``output-products``. Each policy fixes one mode per recipe before the
    continuous solve; products-illegal recipes fall back to ``NONE``. Returned
    candidates are ranked by their actual rounded machine footprint, and the
    layout stage may lay them out in parallel.

    A candidate whose machine count runs away is dropped rather than returned.
    Proliferation exists to CUT machines, so a proliferated plan can never
    legitimately need more of them than the unproliferated baseline; when it
    does, the solve found a degenerate cycle rather than a factory.  Recipes
    that consume an item and produce more of it -- ``reforming-refine`` turns
    two refined oil into three, and ``plasma-refining`` also yields refined oil
    -- form exactly such a loop, and the productivity bonus can tip it.  One
    real URL produced 515,396,248 machines this way, and the layout stage then
    sat trying to place them.
    """
    data = canonicalize_dataset(data)
    request = canonicalize_request(request)
    if count < 1 or count > DEFAULT_CANDIDATES:
        raise ValueError(f"count must be between 1 and {DEFAULT_CANDIDATES}")

    if flow is None:
        df_only_objectives = sorted(
            objective.target_id
            for objective in request.objectives
            if objective.target_id.startswith("df-")
        )
        if df_only_objectives:
            item_id = df_only_objectives[0]
            raise KeyError(
                f"{item_id!r} is a Dark Fog-only item with no normal DSP catalog "
                "identity, so derived solving cannot put it in a blueprint. Supply "
                "this URL's explicit flow to prove it is an external source."
            )
    if flow is not None:
        # A supplied flow fixes recipe and per-recipe mode choices. An explicit
        # tier still wins; None means preserve the flow's own tier exactly.
        return _pinned_candidates(data, request, flow, time_limit_s, tier)

    # A URL that names a proliferator pins the tier; one that does not leaves
    # the frontier free at Mk.III. The sprayed item is belted in from outside,
    # so spending a tier the player did not ask for asks them to supply an item
    # they may not have -- the plan would be valid and unbuildable.
    chosen: ProliferatorTier = tier or proliferator_from_request(request) or ProliferatorTier.MK3

    baseline = solve(
        data,
        request,
        mode_policy=ProliferatorMode.NONE,
        time_limit_s=time_limit_s,
    )
    baseline_spec = _to_build_spec(data, request, baseline, "no-proliferator")
    _refuse_derived_dark_fog(baseline_spec)
    specs = [baseline_spec]
    rounded_areas = {"no-proliferator": baseline.total_area}
    baseline_machines = baseline_spec.machine_count
    dropped: list[str] = []

    if chosen is not ProliferatorTier.NONE and count > 1:
        plans: list[tuple[str, RateSolution]] = [
            (
                "all-products",
                solve(
                    data,
                    request,
                    tier=chosen,
                    mode_policy=ProliferatorMode.PRODUCTS,
                    time_limit_s=time_limit_s,
                ),
            )
        ]
        if count > 2:
            plans.append(
                (
                    "output-products",
                    solve(
                        data,
                        request,
                        tier=chosen,
                        proliferable=target_producer_ids(data, request),
                        mode_policy=ProliferatorMode.PRODUCTS,
                        time_limit_s=time_limit_s,
                    ),
                )
            )
        for label, plan in plans[: count - 1]:
            spec = _to_build_spec(data, request, plan, label)
            if _is_runaway(spec, baseline_machines):
                dropped.append(f"{label} ({spec.machine_count:,} machines)")
                continue
            specs.append(spec)
            rounded_areas[label] = plan.total_area

    if dropped:
        # Surfaced, not swallowed: a silently missing candidate reads as "the
        # frontier had nothing better", which is a different and misleading
        # statement from "the solve degenerated".
        warnings.warn(
            "dropped degenerate candidate(s) whose machine count exceeded the "
            f"unproliferated baseline of {baseline_machines:,}: {', '.join(dropped)}. "
            "This is a self-feeding recipe loop in the rate solve, not a layout limit.",
            RuntimeWarning,
            stacklevel=2,
        )

    # The continuous objective prices fractional machines. Candidate ranking is
    # deliberately based on the physical factory after every exact requirement
    # has been ceiled, so fractional LP cost never masquerades as rounded area.
    specs.sort(key=lambda spec: rounded_areas[spec.label])

    _assert_same_objective(data, request, specs)
    return BuildSpecSet(candidates=tuple(specs))


#: How far past the unproliferated baseline a candidate may sit before it is
#: treated as a degenerate solve rather than a build.  Proliferation should only
#: ever reduce machine count, so in principle any excess is suspect; the slack
#: absorbs integer rounding, where a handful of groups can each gain a machine.
_RUNAWAY_FACTOR = 4


def _is_runaway(spec: BuildSpec, baseline_machines: int) -> bool:
    """Did this candidate's machine count run away from the baseline?

    Guards against self-feeding recipe cycles.  ``reforming-refine`` consumes
    two refined oil and produces three, and ``plasma-refining`` also yields
    refined oil, so the pair forms a loop with net gain; a productivity bonus
    can tip it into a solution with astronomically many machines that is
    arithmetically consistent and physically nonsense.
    """
    if baseline_machines <= 0:
        return False
    return spec.machine_count > baseline_machines * _RUNAWAY_FACTOR


def _assert_same_objective(data: Dataset, request: LabRequest, specs: list[BuildSpec]) -> None:
    """Every candidate must build the same thing, or the set is meaningless."""
    wanted = target_rates(data, request)
    for spec in specs:
        for item_id, rate in wanted.items():
            made = spec.outputs.get(item_id, Fraction(0))
            if made < rate:
                raise AssertionError(
                    f"candidate {spec.label!r} makes {made} {item_id}/s, "
                    f"short of the objective {rate}/s"
                )
