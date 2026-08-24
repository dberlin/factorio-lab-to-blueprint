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

import warnings
from fractions import Fraction

from flab2bp.lab.flow import FlowError, FlowSelection
from flab2bp.lab.schema import Dataset
from flab2bp.lab.url import LabRequest
from flab2bp.rates.adjust import ProliferatorTier
from flab2bp.rates.solve import RateSolution, solve, target_rates
from flab2bp.spec import BuildSpec, BuildSpecSet, MachineGroup, ProliferatorMode

#: How many candidates the frontier emits by default.
#:
#: Three, not four.  ``all-speed-mode`` exists and is reachable with
#: ``--candidates 4``; it was measured across the whole corpus and it does not
#: pay for itself.  2,592 layouts -- 12 URLs x both strategies x 9 repetitions,
#: at budget 4 with both power settings and again at the CLI's own default
#: budget of 2.0 -- comparing best-of-3 area against best-of-4 the way
#: ``pipeline.build`` actually chooses, ``min`` over every (candidate,
#: strategy) pair:
#:
#: * A fourth candidate changed the chosen area not at all in 187 of 216 cells
#:   at budget 4, and 90 of 108 at budget 2.  Corpus-wide it saved a median
#:   +0.058%.
#: * The null arm settles it.  Running the SAME three candidates a second time
#:   and keeping the smaller saves **1.10%**; adding a fourth saves **0.67%**.
#:   Both strategies are nondeterministic, so best-of-3 moves 1.84% median and
#:   up to 21% run-to-run on its own -- a fourth candidate buys less density
#:   than another roll of the dice on the three already there, and it is the
#:   noise, not the frontier, that dominates.
#: * It costs +33% layout wall-clock, because the extra spec is laid out by
#:   every strategy.  The extra rate solve is not the cost: +0.51s over all 12
#:   URLs.
#: * The one durable win in the corpus is ``graphene``: 416 -> 403 tiles, 9/9
#:   repetitions, zero baseline spread.  Thirteen tiles on a five-machine
#:   build.
#:
#: ``information-matrix`` is both why this looked promising and why it is not.
#: Spine alone lays ``all-speed-mode`` out ~12% smaller there.  But the CLI
#: defaults to ``strategy="best"``, and freeform lays that same URL out in
#: 2,430 tiles against spine's 4,074, so the fourth candidate wins a race
#: nobody runs: measured gain 0.00% in 9/9 repetitions, both power settings,
#: both budgets.  A per-strategy area win is not a reason to change a default
#: that pools strategies.
#:
#: None of this is a correctness limit.  ``all-speed-mode`` is produced for all
#: 12 corpus URLs, never trips ``_is_runaway``, and caused no new refusal --
#: 0 of 324 build cells lost a valid layout by adding it.
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
    # BuildSpec is a pydantic model, so model_copy rather than dataclasses.replace.
    return spec.model_copy(update={"lanes_requiring_split": lanes_requiring_split(data, spec)})


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


def proliferation_from_flow(
    flow: FlowSelection,
) -> tuple[ProliferatorTier, tuple[ProliferatorMode, ...], frozenset[str]]:
    """What FactorioLab's flow actually sprays: ``(tier, modes, recipes)``.

    ``ProliferatorTier.module_id`` builds exactly the ids FactorioLab carries
    (``proliferator-2-products`` and friends), so this is that map inverted --
    the same inversion ``proliferator_from_request`` does for a URL, but reading
    the solved flow, which is a statement of fact rather than of availability.

    A flow that sprays nothing yields ``ProliferatorTier.NONE``, and that is the
    case that matters most: it means no proliferator may be belted in at all.

    Mixed tiers are refused.  The rate solver takes one tier for the whole
    build, so a flow spraying Mk.I on one recipe and Mk.II on another cannot be
    represented, and quietly picking one would change what the block consumes.
    """
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
        return ProliferatorTier.NONE, (), frozenset()
    tiers = {tier for tier, _ in sprayed.values()}
    if len(tiers) > 1:
        raise FlowError(
            "the flow sprays more than one proliferator tier "
            f"({sorted(t.value for t in tiers)}). This build takes a single tier, "
            "so honouring the flow exactly is not possible; choosing one would "
            "change what the block consumes."
        )
    return (
        tiers.pop(),
        tuple(sorted({mode for _, mode in sprayed.values()})),
        frozenset(sprayed),
    )


def _pinned_candidates(
    data: Dataset,
    request: LabRequest,
    flow: FlowSelection,
    time_limit_s: float,
) -> BuildSpecSet:
    """The single build FactorioLab's flow describes.

    One candidate, not a frontier.  The frontier exists to explore a choice the
    rate stage cannot price; when the player has already made that choice there
    is nothing to explore, and exploring anyway is how a proliferator input the
    player never asked for gets added.  Measured live: against a flow whose
    ``Modules`` column is empty, the frontier picked ``max-proliferation`` and
    asked to belt in ``proliferator-3``.

    A proliferator tier is an IMPLIED INPUT -- the sprayed item is belted in from
    outside, so choosing a tier changes what the block consumes -- and the rule
    is that the inputs FactorioLab chose may never be changed, implied ones
    included.  ``proliferator_from_request`` reasons that an absent proliferator
    in a URL "is not a constraint", which is right for a URL: it states what is
    available, not what is used. A solved flow states what is used.
    """
    tier, modes, recipes = proliferation_from_flow(flow)
    plan = solve(
        data,
        request,
        tier=tier,
        allowed_modes=modes or None,
        proliferable=recipes if tier is not ProliferatorTier.NONE else None,
        time_limit_s=time_limit_s,
    )
    label = "flow-pinned" if tier is ProliferatorTier.NONE else f"flow-pinned-mk{tier.value}"
    specs = [_to_build_spec(data, request, plan, label)]
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

    Ordered ``no-proliferator``, ``free-proliferation``, ``max-proliferation``,
    then ``all-speed-mode``.  Each is independently valid; they differ only in
    how much direct-insertion freedom they trade for fewer machines.  Candidates
    are independent, so the layout stage may lay them out in parallel.

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
    if flow is not None:
        # Everything below this line is the UNPINNED frontier and is reached
        # only when no flow was supplied, so a build without one is unchanged.
        return _pinned_candidates(data, request, flow, time_limit_s)

    # A URL that names a proliferator pins the tier; one that does not leaves
    # the frontier free at Mk.III. The sprayed item is belted in from outside,
    # so spending a tier the player did not ask for asks them to supply an item
    # they may not have -- the plan would be valid and unbuildable.
    chosen: ProliferatorTier = tier or proliferator_from_request(request) or ProliferatorTier.MK3

    baseline = solve(data, request, time_limit_s=time_limit_s)
    specs = [_to_build_spec(data, request, baseline, "no-proliferator")]
    baseline_machines = specs[0].machine_count
    dropped: list[str] = []

    if chosen is not ProliferatorTier.NONE and count > 1:
        free, _costly = partition_recipes(data, request)
        plans: list[tuple[str, RateSolution]] = []

        plans.append(
            (
                "free-proliferation",
                solve(
                    data,
                    request,
                    tier=chosen,
                    proliferable=free,
                    time_limit_s=time_limit_s,
                ),
            )
        )
        if count > 2:
            plans.append(
                ("max-proliferation", solve(data, request, tier=chosen, time_limit_s=time_limit_s))
            )
        if count > 3:
            plans.append(
                (
                    "all-speed-mode",
                    solve(
                        data,
                        request,
                        tier=chosen,
                        allowed_modes=(ProliferatorMode.SPEED,),
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
