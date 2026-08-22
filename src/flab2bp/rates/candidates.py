"""The proliferation frontier.

Proliferating a recipe buys machines and costs geometry, and the rate stage
cannot see geometry.  Spray is applied by belt-mounted coaters and does not
survive crafting, so a proliferated recipe needs *its own* inputs belted --
which forbids direct insertion on exactly those edges.  Whether that trade is
worth it depends on what a belted edge costs in tiles, and only the layout stage
knows.

So rather than guess, this module emits several complete, valid builds and lets
the layout stage lay out each and keep the smallest.

The partition that makes this tractable is the same one that governs mode
choice.  A recipe fed *entirely* from outside the blueprint has its inputs on
belts by construction, so spraying it forbids no direct insertion at all.  Those
recipes proliferate for free, which is why ``free-proliferation`` is the
candidate to beat rather than a heuristic guess.
"""

from __future__ import annotations

from dataclasses import replace
from fractions import Fraction

from flab2bp.lab.schema import Dataset
from flab2bp.lab.url import LabRequest
from flab2bp.rates.adjust import ProliferatorTier
from flab2bp.rates.solve import RateSolution, solve, target_rates
from flab2bp.spec import BuildSpec, BuildSpecSet, MachineGroup, ProliferatorMode

DEFAULT_CANDIDATES = 3


def partition_recipes(
    data: Dataset, request: LabRequest
) -> tuple[frozenset[str], frozenset[str]]:
    """Split the chain's recipes into ``(free, costly)`` to proliferate.

    *Free* recipes take every input from outside the blueprint, so their inputs
    are belted anyway and a coater costs nothing.  *Costly* recipes have at
    least one internally-produced input, so proliferating them converts a
    direct-insertable edge into a mandatory belt.
    """
    baseline = solve(data, request)
    internal = {group.recipe_id: group for group in baseline.groups}
    made_here = {
        item_id
        for group in baseline.groups
        for item_id in group.adjusted.outputs_per_craft
    }
    free: set[str] = set()
    costly: set[str] = set()
    for recipe_id in internal:
        inputs = data.recipe(recipe_id).inputs
        if any(item_id in made_here for item_id in inputs):
            costly.add(recipe_id)
        else:
            free.add(recipe_id)
    return frozenset(free), frozenset(costly)


def _producer_of(solution: RateSolution, item_id: str) -> str | None:
    for group in solution.groups:
        if item_id in group.adjusted.outputs_per_craft:
            return group.recipe_id
    return None


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

    belt_id = request.belt_id or "conveyor-belt-1"
    spec = BuildSpec(
        groups=tuple(groups),
        external_inputs=dict(solution.external_inputs),
        outputs=dict(solution.outputs),
        belt_item_id=belt_id,
        belt_items_per_second=data.belt_speed(belt_id),
        label=label,
        belt_required_edges=frozenset(belt_required),
        spray_lanes=spray_lanes,
    )
    # Needs the finished spec to compute, so fill it in on a copy.
    return replace(spec, lanes_requiring_split=lanes_requiring_split(data, spec))


def lanes_requiring_split(data: Dataset, spec: BuildSpec) -> frozenset[str]:
    """Sprayed lanes that also feed an unproliferated consumer.

    Such a lane must be split before it is built.  Spray rides on the items, not
    on the machine, so an unproliferated consumer drinking from a sprayed lane
    quietly receives a bonus nobody costed -- it over-produces, and the running
    factory stops matching the numbers in this ``BuildSpec``.

    This is not a rare corner.  Scanning all 151 craftable end products, 42
    candidates need at least one split -- and ``free-proliferation`` is among
    them, despite proliferating only recipes fed from outside.  ``stone``, for
    instance, feeds ``glass`` (fed purely from outside, so proliferated) and
    ``sulfuric-acid`` (which also takes refined-oil, so not), and the lane has
    to be split between them.
    """
    consumers: dict[str, list[MachineGroup]] = {}
    for group in spec.groups:
        for item_id in data.recipe(group.recipe_id).inputs:
            consumers.setdefault(item_id, []).append(group)
    split: set[str] = set()
    for item_id in spec.spray_lanes:
        eaters = consumers.get(item_id, [])
        if any(g.is_proliferated for g in eaters) and any(
            not g.is_proliferated for g in eaters
        ):
            split.add(item_id)
    return frozenset(split)


def build_candidates(
    data: Dataset,
    request: LabRequest,
    *,
    tier: ProliferatorTier = ProliferatorTier.MK3,
    count: int = DEFAULT_CANDIDATES,
    time_limit_s: float = 30.0,
) -> BuildSpecSet:
    """Emit an ordered frontier of complete, valid builds.

    Ordered ``no-proliferator``, ``free-proliferation``, ``max-proliferation``,
    then ``all-speed-mode``.  Each is independently valid; they differ only in
    how much direct-insertion freedom they trade for fewer machines.  Candidates
    are independent, so the layout stage may lay them out in parallel.
    """
    baseline = solve(data, request, time_limit_s=time_limit_s)
    specs = [_to_build_spec(data, request, baseline, "no-proliferator")]

    if tier is not ProliferatorTier.NONE and count > 1:
        free, _costly = partition_recipes(data, request)
        plans: list[tuple[str, RateSolution]] = []

        plans.append(
            (
                "free-proliferation",
                solve(
                    data,
                    request,
                    tier=tier,
                    proliferable=free,
                    time_limit_s=time_limit_s,
                ),
            )
        )
        if count > 2:
            plans.append(
                ("max-proliferation", solve(data, request, tier=tier, time_limit_s=time_limit_s))
            )
        if count > 3:
            plans.append(
                (
                    "all-speed-mode",
                    solve(
                        data,
                        request,
                        tier=tier,
                        allowed_modes=(ProliferatorMode.SPEED,),
                        time_limit_s=time_limit_s,
                    ),
                )
            )
        for label, plan in plans[: count - 1]:
            specs.append(_to_build_spec(data, request, plan, label))

    _assert_same_objective(data, request, specs)
    return BuildSpecSet(candidates=tuple(specs))


def _assert_same_objective(
    data: Dataset, request: LabRequest, specs: list[BuildSpec]
) -> None:
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
