"""The production solve: FactorioLab's objective and exact flows out.

Each candidate fixes one proliferator mode per recipe before solving. That
removes mode-activation binaries and leaves a small fixed-charge MILP over craft
rates and integer physical machine counts. The URL's recipe, machine, footprint,
and surplus costs are applied with FactorioLab's exact coefficient semantics,
including every enabled extraction recipe as an ordinary priced column
competing with crafting rather than a structural cut.

Every rate leaving the solver is recovered by an exact Rational LP inside the
bought capacities. Machines may idle, so upstream demand follows exact craft
rates rather than spare capacity, and no float reaches ``BuildSpec``.

``prove_minimal=False`` is the explicit continuous alternative: optimise the
same FactorioLab costs, recover exact rates over the selected support, then take
the exact machine ceiling. It preserves every material support column and
expands exact recovery if a discarded tiny flow is required for balance.

Both solvers come from ortools. Do not reintroduce ``highspy``: it and ortools
cannot safely share a process because ortools bundles its own incompatible
HiGHS library, while the layout stage also requires ortools' CP-SAT backend.
"""

from __future__ import annotations

import warnings
from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, fields
from fractions import Fraction
from types import MappingProxyType
from typing import cast

# Neither ortools nor sympy ships a py.typed marker, so both read as untyped.
from ortools.linear_solver import pywraplp  # type: ignore[import-untyped]
from sympy import Expr, Rational, nsimplify  # type: ignore[import-untyped]
from sympy.solvers.simplex import (  # type: ignore[import-untyped]
    InfeasibleLPError,
    UnboundedLPError,
    linprog,
)

from flab2bp.lab.schema import Dataset, Recipe
from flab2bp.lab.url import DisplayRate, LabRequest, ObjectiveType, ObjectiveUnit
from flab2bp.rates.adjust import (
    AdjustedRecipe,
    ProliferatorTier,
    adjust,
    available_modes,
    select_machine,
)
from flab2bp.rates.machine_choice import MachineMove, MachineRank, rechoose_columns
from flab2bp.spec import MAX_CARGO_STACK, ProliferatorMode

_SECONDS_PER_PERIOD = {
    DisplayRate.PerSecond: Fraction(1),
    DisplayRate.PerMinute: Fraction(60),
    DisplayRate.PerHour: Fraction(3600),
}

#: Machines per recipe column.  Generous: the example chain's largest group is
#: 17, and a 1000x headroom costs the solver nothing at this scale.
_MAX_MACHINES = 100_000

#: GLOP is float64. Values below both tolerances are treated as solver noise
#: while selecting support, then every retained magnitude is discarded and
#: recovered by an exact Rational LP. If that support cannot balance exactly,
#: recovery retries with every column so a genuinely required tiny flow is
#: never silently dropped.
_LP_SUPPORT_ABS_TOLERANCE = 1e-9
_LP_SUPPORT_REL_TOLERANCE = 1e-9


class UnsupportedObjectiveError(ValueError):
    """Raised for objectives that do not describe a finite thing to build."""


class InfeasibleError(RuntimeError):
    """Raised when no combination of recipes can meet the objective."""


@dataclass(frozen=True, slots=True)
class SolvedGroup:
    """``machines`` machines running one recipe in one proliferator mode."""

    recipe_id: str
    machine_item_id: str
    mode: ProliferatorMode
    machines: int
    #: The continuous requirement before rounding up.  ``machines`` is its
    #: ceiling, and the gap is the group's idle headroom.
    exact_machines: Fraction
    crafts_per_second: Fraction
    adjusted: AdjustedRecipe
    #: Group totals in items/second, across all ``machines``.
    inputs: Mapping[str, Fraction]
    outputs: Mapping[str, Fraction]
    proliferator_rate: Fraction = Fraction(0)

    @property
    def utilisation(self) -> Fraction:
        capacity = self.machines * self.adjusted.crafts_per_second
        return self.crafts_per_second / capacity if capacity else Fraction(0)

    @property
    def area(self) -> int:
        return self.machines * self.adjusted.footprint_area


@dataclass(frozen=True, slots=True)
class RateSolution:
    """A complete, internally consistent production plan."""

    groups: tuple[SolvedGroup, ...]
    external_inputs: Mapping[str, Fraction]
    outputs: Mapping[str, Fraction]
    surplus: Mapping[str, Fraction] = field(default_factory=dict)
    target_rates: Mapping[str, Fraction] = field(default_factory=dict)
    tier: ProliferatorTier = ProliferatorTier.NONE
    #: Exact continuous footprint before each physical group is rounded up.
    lower_bound_area: Fraction = Fraction(0)
    #: Items the URL forbade as inputs (``Limit`` objectives at zero); every
    #: one of them was crafted here, or the solve refused.
    forbidden_inputs: frozenset[str] = frozenset()
    #: Recipes whose ranked machine moved down under ``machine_rank=up-to``.
    machine_moves: tuple[MachineMove, ...] = ()

    @property
    def machine_count(self) -> int:
        return sum(g.machines for g in self.groups)

    @property
    def exact_machine_count(self) -> Fraction:
        return sum((g.exact_machines for g in self.groups), Fraction(0))

    @property
    def total_area(self) -> int:
        return sum(g.area for g in self.groups)

    @property
    def proliferator_rate(self) -> Fraction:
        return sum((g.proliferator_rate for g in self.groups), Fraction(0))

    @property
    def proliferator_item_id(self) -> str | None:
        return self.tier.sprayed_item_id if self.proliferator_rate else None


@dataclass(frozen=True, slots=True)
class _ObjectiveCoefficients:
    """FactorioLab's per-column machine and surplus objective coefficients."""

    machine: tuple[Fraction, ...]
    surplus: tuple[Fraction, ...]
    continuous: tuple[Fraction, ...]
    items: tuple[str, ...]


def _cost(value: Fraction | None, default: int) -> Fraction:
    return Fraction(default) if value is None else value


def _objective_coefficients(
    data: Dataset,
    request: LabRequest,
    columns: Sequence[AdjustedRecipe],
) -> _ObjectiveCoefficients:
    """Mirror FactorioLab ``adjustCosts`` plus its surplus-variable objective."""
    factor_cost = _cost(request.costs.factor, 1)
    machine_cost = _cost(request.costs.machine, 1)
    footprint_cost = _cost(request.costs.footprint, 1)
    surplus_cost = _cost(request.costs.surplus, 0)
    items = tuple(sorted({item_id for column in columns for item_id in column.outputs_per_craft}))

    machine: list[Fraction] = []
    surplus: list[Fraction] = []
    continuous: list[Fraction] = []
    for column in columns:
        recipe = data.recipe(column.recipe_id)
        override = request.recipes.get(recipe.id)
        if override is not None and override.cost is not None:
            per_machine = override.cost
        elif recipe.cost is not None:
            output_rate = (
                sum(
                    column.outputs_per_craft.values(),
                    Fraction(),
                )
                * column.crafts_per_second
            )
            per_machine = output_rate * recipe.cost * factor_cost
        else:
            per_machine = machine_cost
            # FactorioLab's ``adjustCosts`` multiplies the machine cost by the
            # machine's tile area only when the DATASET declares
            # ``machine.size`` and the footprint cost is nonzero.  The DSP
            # dataset declares no size for any of its 52 machines, so every
            # DSP machine -- collider, chemical plant or orbital collector --
            # costs exactly ``costs.machine``.  Weighting crafting columns by
            # our own catalog footprint instead made five colliders dearer than
            # 31 deuterium collectors and belted deuterium in where FactorioLab
            # crafts it from collected hydrogen; that changed the blueprint's
            # inputs.  Area is the LAYOUT stage's concern and the geometric
            # lower bound's, not the recipe choice's.
            size = data.machine(column.machine_item_id).size
            if footprint_cost and size is not None:
                per_machine *= size[0] * size[1]

        surplus_per_craft = surplus_cost * sum(
            (
                column.outputs_per_craft.get(item_id, Fraction())
                - column.inputs_per_craft.get(item_id, Fraction())
                for item_id in items
            ),
            Fraction(),
        )
        machine.append(per_machine)
        surplus.append(surplus_per_craft)
        continuous.append(per_machine / column.crafts_per_second + surplus_per_craft)

    return _ObjectiveCoefficients(
        machine=tuple(machine),
        surplus=tuple(surplus),
        continuous=tuple(continuous),
        items=items,
    )


def _default_objective(
    columns: Sequence[AdjustedRecipe],
) -> _ObjectiveCoefficients:
    machine = tuple(Fraction(column.footprint_area) for column in columns)
    surplus = (Fraction(),) * len(columns)
    return _ObjectiveCoefficients(
        machine=machine,
        surplus=surplus,
        continuous=tuple(
            cost / column.crafts_per_second for cost, column in zip(machine, columns, strict=True)
        ),
        items=(),
    )


def cargo_stack(request: LabRequest) -> int:
    """Items per cargo on the URL's belts: FactorioLab's ``ist``, clamped.

    Design rule 1: a URL that says nothing about stacking, or says 1, is judged
    exactly as it is today -- one item per cargo unit -- so nothing about an
    unstacked build can move because this exists.  Above 1 the value is the
    player's bus, capped at ``spec.MAX_CARGO_STACK``, because the game cannot
    put more than that on a belt however large a number the URL holds.

    One function, so the two ``Belts`` branches below and ``_to_build_spec``
    cannot drift: an objective counted in belts and the spec's own
    ``belt_stack`` have to mean the same belt.
    """
    stack = request.stack
    if stack is None or stack <= 1:
        return 1
    return min(MAX_CARGO_STACK, int(stack))


def target_rates(data: Dataset, request: LabRequest) -> dict[str, Fraction]:
    """Normalise objectives to items/second, keyed by item id."""
    period = _SECONDS_PER_PERIOD[request.display_rate]
    out: dict[str, Fraction] = {}
    forbidden = forbidden_inputs(request)  # validates the Limit objectives too
    for objective in request.objectives:
        if objective.type is ObjectiveType.Input:
            if objective.target_id in forbidden:
                raise UnsupportedObjectiveError(
                    f"{objective.target_id} carries both a declared Input and a Limit "
                    "of zero: it cannot be supplied from outside and forbidden as an "
                    "input at once"
                )
            continue  # a declared external supply; see supplied_rates()
        if objective.type is ObjectiveType.Limit:
            continue  # a constraint on the boundary, not a target; see forbidden_inputs()
        if objective.type is not ObjectiveType.Output:
            raise UnsupportedObjectiveError(
                f"objective type {objective.type.name!r} is not supported: only "
                "Output objectives describe a finite factory to build"
            )
        if objective.unit is ObjectiveUnit.Items:
            rate = objective.value / period
            item_id = objective.target_id
        elif objective.unit is ObjectiveUnit.Belts:
            belt_id = request.belt_id or "conveyor-belt-1"
            # A belt's speed is CARGO per second; each cargo carries `ist`
            # items.  At `ist=1` (design rule 1) this is the old arithmetic
            # unchanged.
            rate = objective.value * data.belt_speed(belt_id) * cargo_stack(request)
            item_id = objective.target_id
        elif objective.unit is ObjectiveUnit.Machines:
            recipe = data.recipe(objective.target_id)
            machine_id = select_machine(data, recipe, request.machine_rank_ids)
            adjusted = adjust(data, recipe, machine_id)
            item_id = next(iter(recipe.outputs))
            rate = objective.value * adjusted.output_rate(item_id)
        else:
            raise UnsupportedObjectiveError(
                f"objective unit {objective.unit.name!r} is not supported"
            )
        out[item_id] = out.get(item_id, Fraction(0)) + rate
    if not out:
        raise UnsupportedObjectiveError(
            "the URL carries no objectives, so there is nothing to build"
        )
    return out


def supplied_rates(data: Dataset, request: LabRequest) -> dict[str, Fraction]:
    """Items the URL declares as externally supplied, in items/second.

    FactorioLab's ``Input`` objective means "I already have this much of this
    item": the item arrives at the boundary at up to the declared rate, and
    demand is served from it before anything is built.  An Input objective on
    ``proliferator-3`` is simply a proliferator belt with a declared rate.

    The declared rate BOUNDS that supply, and every consumer nets against it --
    the requested output and the chain's own intermediate demand alike -- so
    only the remainder is crafted (:func:`net_target_rates`, and the LP demand
    in :func:`solve`).  Captured from FactorioLab for the URL that prompted
    this: 2000/min copper ingot requested with 600/min declared as an Input
    exports ``=70/3`` arc smelters and ``=1400`` copper ore, i.e. 1400/min
    crafted.  A supply beyond the demand is simply unused.

    A rate of zero or less is not a quantity to net against; it keeps the older
    all-or-nothing reading (belted in, never built). The URL adapter preserves
    an explicit zero; only a missing objective value defaults to one.
    """
    period = _SECONDS_PER_PERIOD[request.display_rate]
    out: dict[str, Fraction] = {}
    for objective in request.objectives:
        if objective.type is not ObjectiveType.Input:
            continue
        if objective.unit is ObjectiveUnit.Items:
            rate = objective.value / period
        elif objective.unit is ObjectiveUnit.Belts:
            # The declared supply arrives on the same belts, so it stacks the
            # same way; leaving this branch unstacked would under-declare the
            # player's bus while the Output branch above counted it in full.
            rate = (
                objective.value
                * data.belt_speed(request.belt_id or "conveyor-belt-1")
                * cargo_stack(request)
            )
        else:
            raise UnsupportedObjectiveError(
                f"an Input objective in {objective.unit.name!r} units is not "
                "supported; use Items or Belts"
            )
        out[objective.target_id] = out.get(objective.target_id, Fraction(0)) + rate
    return out


def forbidden_inputs(request: LabRequest) -> frozenset[str]:
    """Items the URL forbids as inputs: every ``Limit`` objective at zero.

    FactorioLab's ``Limit`` objective bounds how much of an item may arrive
    from outside.  A bound of zero has one meaning this solver can honour
    exactly -- the item must never be belted in, so whatever the chain needs
    of it is crafted here or the build refuses -- and that is the only bound
    supported: a positive limit needs an LP row that caps one boundary flow,
    which does not exist yet, so it is refused rather than silently read as
    zero or ignored.
    """
    out: set[str] = set()
    for objective in request.objectives:
        if objective.type is not ObjectiveType.Limit:
            continue
        if objective.unit is not ObjectiveUnit.Items or objective.value != 0:
            raise UnsupportedObjectiveError(
                f"objective type 'Limit' on {objective.target_id} is supported for "
                "only a Limit of zero in items, which forbids the item as an input; "
                f"a limit of {objective.value} {objective.unit.name.lower()} would need "
                "a bounded boundary flow the rate solve cannot express"
            )
        out.add(objective.target_id)
    return frozenset(out)


def _supply_cap(supplied: Mapping[str, Fraction], item_id: str) -> Fraction:
    """The bounded part of a declared supply: never negative, never a demand."""
    return max(Fraction(0), supplied.get(item_id, Fraction(0)))


def net_target_rates(data: Dataset, request: LabRequest) -> dict[str, Fraction]:
    """What the blueprint must MAKE: each requested rate less its declared supply.

    FactorioLab serves demand from an ``Input`` objective first and builds the
    remainder, so a URL asking for 2000/min of an item it also supplies at
    600/min describes a 1400/min factory.  The block delivers that 1400/min at
    its boundary; the player's own 600/min never enters the blueprint, exactly
    as the other declared supplies never do.

    Clamped at zero: a supply larger than the request leaves nothing to build
    for that item rather than a negative objective.
    """
    targets = target_rates(data, request)
    supplied = supplied_rates(data, request)
    return {
        item_id: max(Fraction(0), rate - _supply_cap(supplied, item_id))
        for item_id, rate in targets.items()
    }


def _lp_demand(
    targets: Mapping[str, Fraction], supplied: Mapping[str, Fraction]
) -> dict[str, Fraction]:
    """The balance row right-hand sides: demand net of the declared supply.

    UNCLAMPED, unlike :func:`net_target_rates`.  Each row reads "net production
    of this item is at least this", so a negative value is the statement that
    the block may consume up to the surplus supply -- which is how an
    intermediate with a partial Input gets its remainder crafted and its
    declared share belted in.  Clamping here would silently re-craft supply the
    player already has.
    """
    items = set(targets) | set(supplied)
    return {
        item_id: targets.get(item_id, Fraction(0)) - _supply_cap(supplied, item_id)
        for item_id in items
    }


def _excluded_recipes(data: Dataset, request: LabRequest) -> frozenset[str]:
    """Which recipes the player has turned off.

    A URL that carries an exclusion set carries the WHOLE of it, and it is
    authoritative.  FactorioLab's UI is where recipe choice is made; the set in
    the URL is the state of that UI, not a delta against the mod's defaults.

    This used to union ``data.default_recipe_excluded`` on top, which silently
    re-disabled every recipe the player had deliberately ENABLED.  Measured on a
    real user URL: the set carried 14 recipes and the defaults carried 14, but
    they were not the same 14 --

        enabled by the player, re-excluded by us:  graphene-advanced, ice-giant
        disabled by the player, not in defaults:   gas-giant-deuterium,
                                                   gas-giant-hydrogen

    -- so the URL is provably not a delta, since a delta would not need to list
    the twelve it shares with the defaults.  Killing ``graphene-advanced`` left
    only ``graphene`` (energetic-graphite + sulfuric-acid), and the build then
    asked the player to belt in STONE for a flow that contains none.  The player
    had chosen fire ice from an ice giant; we overrode that and changed the
    blueprint's inputs, which is exactly the thing that may never happen.

    Absence is different from emptiness.  ``None`` means the URL said nothing,
    so the mod's defaults are the player's state and are used.  An empty set
    means the player turned everything on, and is honoured as such.
    """
    if request.excluded_recipe_ids is None:
        return frozenset(data.default_recipe_excluded)
    return frozenset(request.excluded_recipe_ids)


def _buildable_producers(
    data: Dataset, item_id: str, excluded: frozenset[str]
) -> tuple[Recipe, ...]:
    """Recipes that could make ``item_id`` inside the blueprint.

    Mining-flagged recipes are excluded by design: extraction happens outside
    and its output arrives on an input belt.  The ``mining`` flag is the cut
    line -- exactly 22 recipes carry it, covering mining machines, the water
    pump, the oil extractor and the orbital collectors uniformly.  Heuristics
    based on ``totalRecipe`` or producer names miss most of those.

    Technology recipes consume items to advance research rather than producing
    goods, so they are never a way to make something.

    Reads the NEUTRAL index and applies ``excluded`` itself, rather than calling
    ``craftable_recipes_producing`` -- which drops the dataset's defaults
    internally.  That was the second of two layers applying the same defaults,
    and it survived a fix to the first: the player's own exclusion set reached
    this function intact and was then overruled one call deeper.  ``excluded``
    is the player's set; nothing else may narrow it.
    """
    return tuple(
        recipe
        for recipe in data.recipes_producing(item_id)
        if "mining" not in recipe.flags and not recipe.is_technology and recipe.id not in excluded
    )


def _extraction_producers(
    data: Dataset, item_id: str, excluded: frozenset[str]
) -> tuple[Recipe, ...]:
    """Enabled mining-flagged recipes for ``item_id``: extra priced LP columns.

    FactorioLab's ``adjustCosts`` (``src/state/adjustment.ts``) prices every
    enabled recipe rather than cutting extraction from the graph: a recipe
    with a declared ``cost`` (veins 100-200, ocean/orbital collectors 1) is
    priced at its output rate times that cost times the cost factor (default
    1); a recipe with no declared cost is priced at the machine cost (default
    1), times footprint tiles when the footprint cost is nonzero. The
    production LP then minimises over whichever mix of crafting and
    extraction columns is globally cheapest -- not the cheapest single
    recipe, since the crafting alternative also drags in its own upstream
    machines and their costs.

    That is why ``_resolve_chain`` treats an item with an entry here as an
    ordinary internal item with *extra* producers, rather than cutting it to
    an external the way ``_buildable_producers`` cuts mining recipes from
    crafting: the LP needs both routes as columns before it can choose. It is
    also why the choice is not uniform per item -- in one captured flow,
    ``graphene-advanced`` (fire ice plus a hydrogen coproduct from an
    ``ice-giant`` collector, priced around 0.18/unit) still beats crafting
    particle containers from coal and sulfuric acid veins priced at
    100-200/unit, while hydrogen for deuterium fuel rods is instead collected
    directly from ``ice-giant-hydrogen`` / ``gas-giant-hydrogen`` rather than
    made via ``graphene-advanced``: each is simply the cheaper total route for
    its own request. A structural "extraction is always a free input" rule
    cannot tell these apart; only pricing can.

    The player's exclusion set is the lever in both directions: turning every
    extraction recipe for an item off removes those columns and leaves only
    the crafting routes.
    """
    return tuple(
        recipe
        for recipe in data.recipes_producing(item_id)
        if recipe.is_mining and recipe.id not in excluded
    )


def target_producer_ids(data: Dataset, request: LabRequest) -> frozenset[str]:
    """Recipes that may directly produce a requested final output."""
    excluded = _excluded_recipes(data, request)
    return frozenset(
        recipe.id
        for item_id in target_rates(data, request)
        for recipe in _buildable_producers(data, item_id, excluded)
    )


def _resolve_chain(
    data: Dataset,
    targets: Iterable[str],
    excluded: frozenset[str],
    supplied: Mapping[str, Fraction] = MappingProxyType({}),
    *,
    include_consumers: bool = False,
    forbidden: frozenset[str] = frozenset(),
) -> tuple[dict[str, tuple[Recipe, ...]], set[str]]:
    """Walk the recipe graph from the targets.

    Returns the producing recipes for each internal item, plus the set of items
    that may be belted in.  An item is belted in when the URL supplies it (an
    Input objective) or when nothing here can make it.  A declared supply with
    a rate does NOT stop the walk: the item is external AND internal at once,
    belted in up to the declared rate and crafted for whatever demand is left
    over (``_lp_demand``).  Otherwise the item stays
    internal, with its crafting recipes and (unless it is a requested output)
    its enabled extraction recipes (``_extraction_producers``) BOTH offered as
    producers: the production LP prices every one of them and picks whichever
    mix is globally cheapest, exactly as FactorioLab's ``adjustCosts`` does. A
    requested output never gets an extraction option -- an Output objective
    asks for the item to be MADE, and a blueprint of zero machines satisfies
    nobody -- so it is always crafted.  Known over-reach: that removes the
    extraction option for the item's INTERNAL demand too, so an Output
    objective on an item the chain also consumes (sulfuric acid alongside
    graphene) crafts the consumed share as well, where FactorioLab would
    extract it; forcing only the objective quantity to be crafted needs an
    extra LP row and is not done yet. Extraction recipes
    contribute no further edges to the walk: they have no inputs.

    With a positive surplus cost, FactorioLab traverses recipes that either
    produce or consume each visited item and follows both their inputs and
    outputs. That wider closure lets downstream recipes consume coproduct
    surplus.
    """
    targets = tuple(targets)
    requested = frozenset(targets)
    io_recipes: dict[str, list[Recipe]] = {}
    if include_consumers:
        for recipe in data.recipes:
            if "mining" in recipe.flags or recipe.is_technology or recipe.id in excluded:
                continue
            for item_id in recipe.inputs:
                io_recipes.setdefault(item_id, []).append(recipe)
            for item_id in recipe.outputs:
                if item_id not in recipe.inputs:
                    io_recipes.setdefault(item_id, []).append(recipe)

    producers: dict[str, tuple[Recipe, ...]] = {}
    external: set[str] = set()
    queue: deque[str] = deque(targets)
    seen: set[str] = set()
    while queue:
        item_id = queue.popleft()
        if item_id in seen:
            continue
        seen.add(item_id)
        declared = supplied.get(item_id)
        if declared is not None and declared > 0:
            # A declared RATE is a bounded supply, so the item is belted in AND
            # kept internal: demand nets against the supply and the LP crafts
            # only the remainder.  One real user URL asked for 2000/min copper
            # ingot and listed 600/min copper ingot among fifteen declared
            # supplies; FactorioLab builds the 1400/min difference, so cutting
            # the item to external here (which is what a supply used to do)
            # would build nothing at all and ask the player for the lot.
            external.add(item_id)
        elif declared is not None and item_id not in requested:
            # A supply with no usable rate is not a quantity to net against, so
            # it keeps the all-or-nothing reading: do not build it even though a
            # recipe exists -- that is the point of an Input objective.
            #
            # A REQUESTED output is the exception, for the same reason the
            # extraction cut below spares it: an Output objective asks for the
            # item to be made, and a blueprint of zero machines satisfies
            # nobody.
            external.add(item_id)
            continue

        crafting = _buildable_producers(data, item_id, excluded)
        # A forbidden input gets no extraction option either: extraction is a
        # belt-in by another name (the ore still arrives at the boundary), and
        # a Limit of zero is exactly the promise that it will not.
        extraction = (
            ()
            if item_id in requested or item_id in forbidden
            else _extraction_producers(data, item_id, excluded)
        )
        options = crafting + extraction
        if options:
            producers[item_id] = options
        else:
            external.add(item_id)

        matches: Iterable[Recipe] = io_recipes.get(item_id, ()) if include_consumers else crafting
        for recipe in matches:
            for ingredient in recipe.inputs:
                if ingredient not in seen:
                    queue.append(ingredient)
            if include_consumers:
                for product in recipe.outputs:
                    if product not in seen:
                        queue.append(product)
    return producers, external


@dataclass(frozen=True, slots=True)
class _ExtractionColumn(AdjustedRecipe):
    """An enabled extraction recipe, priced like FactorioLab but never built.

    Mining, pumping, and orbital collection happen outside the blueprint (see
    ``Recipe.is_mining``), so an extraction column never turns into a
    ``SolvedGroup`` and its ``footprint_area`` is 0 regardless of what the
    catalog reports for its machine -- charging tile area for a vein or a
    collector would be meaningless, since nothing is ever placed for one.
    Identify these columns everywhere with ``isinstance(column,
    _ExtractionColumn)``.
    """

    @property
    def footprint_area(self) -> int:
        return 0


def _columns(
    data: Dataset,
    producers: Mapping[str, tuple[Recipe, ...]],
    request: LabRequest,
    tier: ProliferatorTier,
    proliferable: frozenset[str] | None,
    fixed_modes: Mapping[str, ProliferatorMode] | None = None,
    mode_policy: ProliferatorMode | None = ProliferatorMode.NONE,
) -> list[AdjustedRecipe]:
    """Build one deterministic mode column per reachable recipe.

    An extraction recipe (``recipe.is_mining``) is never proliferated and
    never takes a flow-pinned mode -- FactorioLab does not spray a vein or a
    collector -- so it skips the mode-selection machinery entirely and comes
    back as an ``_ExtractionColumn`` adjusted under ``ProliferatorMode.NONE``.
    """
    if fixed_modes is not None and proliferable is not None:
        raise ValueError("fixed_modes cannot be combined with proliferable")
    if fixed_modes is None and mode_policy is None:
        raise ValueError("a deterministic mode_policy is required without fixed_modes")

    recipes = {recipe.id: recipe for options in producers.values() for recipe in options}
    columns: list[AdjustedRecipe] = []
    for recipe in recipes.values():
        machine_id = select_machine(data, recipe, request.machine_rank_ids)
        if recipe.is_mining:
            adjusted = adjust(data, recipe, machine_id, ProliferatorMode.NONE, tier)
            columns.append(
                _ExtractionColumn(**{f.name: getattr(adjusted, f.name) for f in fields(adjusted)})
            )
            continue
        available = available_modes(data, recipe, tier)
        if fixed_modes is not None:
            mode = fixed_modes.get(recipe.id, ProliferatorMode.NONE)
            if mode not in available:
                raise InfeasibleError(
                    f"{recipe.id} cannot use the flow-pinned proliferator mode {mode.value!r}"
                )
        else:
            assert mode_policy is not None
            applies = proliferable is None or recipe.id in proliferable
            mode = mode_policy if applies and mode_policy in available else ProliferatorMode.NONE
        columns.append(adjust(data, recipe, machine_id, mode, tier))
    return columns


def _run_continuous_lp(
    columns: Sequence[AdjustedRecipe],
    internal_items: Sequence[str],
    demand: Mapping[str, Fraction],
    *,
    objective: _ObjectiveCoefficients | None = None,
    time_limit_s: float,
) -> list[float]:
    """Find the FactorioLab-style continuous cost optimum."""
    model = pywraplp.Solver.CreateSolver("GLOP")
    if model is None:  # pragma: no cover - GLOP ships with ortools
        raise InfeasibleError("no continuous LP solver is available")
    model.SetTimeLimit(int(time_limit_s * 1000))
    objective = objective or _default_objective(columns)
    crafts = [model.NumVar(0.0, model.infinity(), f"x{i}") for i in range(len(columns))]

    for item_id in internal_items:
        terms = []
        for craft, column in zip(crafts, columns, strict=True):
            net = column.outputs_per_craft.get(item_id, Fraction()) - column.inputs_per_craft.get(
                item_id, Fraction()
            )
            if net:
                terms.append(float(net) * craft)
        if terms:
            model.Add(model.Sum(terms) >= float(demand.get(item_id, Fraction())))

    if not columns:
        raise InfeasibleError("no recipes available to build the objective")
    model.Minimize(
        model.Sum(
            float(cost) * craft for cost, craft in zip(objective.continuous, crafts, strict=True)
        )
    )
    status = model.Solve()
    if status != pywraplp.Solver.OPTIMAL:
        raise InfeasibleError(
            f"the continuous production solve found no optimum (status: {status})"
        )
    return [craft.solution_value() for craft in crafts]


def _run_milp(
    columns: Sequence[AdjustedRecipe],
    internal_items: Sequence[str],
    demand: Mapping[str, Fraction],
    *,
    objective: _ObjectiveCoefficients | None = None,
    time_limit_s: float,
) -> tuple[list[float], list[float]]:
    """Solve the fixed-charge oracle for craft rates and integer machine counts.

    Extraction columns get a continuous machine variable
    instead of an integer one: FactorioLab never rounds a vein or a collector
    to a whole machine count, and this file never builds one, so there is no
    fixed charge to round for.
    """
    model = pywraplp.Solver.CreateSolver("SCIP")
    if model is None:  # pragma: no cover - SCIP ships with ortools
        raise InfeasibleError("no MILP solver is available")
    model.SetTimeLimit(int(time_limit_s * 1000))
    objective = objective or _default_objective(columns)

    crafts = [model.NumVar(0.0, model.infinity(), f"x{i}") for i in range(len(columns))]
    machines = [
        model.NumVar(0.0, model.infinity(), f"n{i}")
        if isinstance(column, _ExtractionColumn)
        else model.IntVar(0, _MAX_MACHINES, f"n{i}")
        for i, column in enumerate(columns)
    ]
    # A group's craft rate may never exceed what its machines can sustain.
    for craft, machine, column in zip(crafts, machines, columns, strict=True):
        model.Add(craft - float(column.crafts_per_second) * machine <= 0)

    # Item balance. ">=" rather than "==" admits surplus, which joint-product
    # recipes make unavoidable.
    for item_id in internal_items:
        expr = None
        for craft, column in zip(crafts, columns, strict=True):
            net = column.outputs_per_craft.get(item_id, Fraction(0)) - column.inputs_per_craft.get(
                item_id, Fraction(0)
            )
            if net:
                term = float(net) * craft
                expr = term if expr is None else expr + term
        if expr is None:
            continue
        model.Add(expr >= float(demand.get(item_id, Fraction(0))))

    if not columns:
        raise InfeasibleError("no recipes available to build the objective")
    model.Minimize(
        model.Sum(
            [
                *(
                    float(cost) * machine
                    for cost, machine in zip(objective.machine, machines, strict=True)
                ),
                *(
                    float(cost) * craft
                    for cost, craft in zip(objective.surplus, crafts, strict=True)
                ),
            ]
        )
    )

    status = model.Solve()
    if status == pywraplp.Solver.FEASIBLE:
        # Hit the clock with a valid plan it had not finished proving minimal.
        # That used to raise, which threw away a whole buildable factory in
        # exchange for a proof we do not need: since the balances are solved
        # exactly downstream, the MILP is only choosing STRUCTURE here, and a
        # feasible structure is a real factory -- possibly not the smallest.
        #
        # universe-matrix sits right on the edge: ~25s of a 30s budget on a
        # quiet machine, so it tips over under load and the failure looked
        # like an infeasible spec rather than a timer.
        #
        # Warned rather than swallowed, because "we may have shipped a larger
        # plan than necessary" is exactly the kind of thing that becomes
        # invisible and then becomes the baseline nobody questions.
        warnings.warn(
            f"the production solve hit its {time_limit_s:g}s limit with a feasible "
            "but unproven-minimal plan; the structure is valid and the rates "
            "below are still exact, but the factory may be larger than needed",
            RuntimeWarning,
            stacklevel=2,
        )
    elif status != pywraplp.Solver.OPTIMAL:
        raise InfeasibleError(f"the production solve did not reach optimality (status: {status})")
    return (
        [c.solution_value() for c in crafts],
        [m.solution_value() for m in machines],
    )


def _rational(value: Fraction) -> Rational:
    """``Fraction`` to sympy ``Rational``, exactly."""
    return cast(Rational, Rational(value.numerator, value.denominator))


def _fraction(value: Expr) -> Fraction:
    """sympy ``Rational`` back to ``Fraction``, exactly.

    A float here would mean the LP had left exact arithmetic somewhere, so this
    refuses rather than coercing: the whole point of the round trip is that it
    is lossless.
    """
    number = nsimplify(value, rational=True)
    if not isinstance(number, Rational):
        raise InfeasibleError(
            f"the exact rate solve returned a non-rational craft rate ({value!r})"
        )
    return Fraction(int(number.p), int(number.q))


def _linprog_checked(
    cost: Sequence[Fraction],
    rows: Sequence[Sequence[Fraction]],
    limits: Sequence[Fraction],
    bounds: Mapping[int, tuple[Fraction, Fraction | None]] | None = None,
) -> list[Fraction] | None:
    """Minimise ``cost . x`` over ``rows . x <= limits``, or ``None`` if unproven.

    sympy's two-phase simplex has an escape hatch: when phase 1 starts
    oscillating between the same pivot twice it breaks out with an INFEASIBLE
    basis, optimises from there anyway, and validates only that the answer is
    non-negative (``_simplex`` in ``sympy/solvers/simplex.py``, "Not sure what
    to do here").  An oscillating system therefore comes back as a
    plausible-looking point that violates its own constraints -- for the rate
    solve, a factory that eats an item nothing makes.  So every answer is
    re-checked here in exact rationals and ``None`` means "sympy answered, but
    the answer is not a solution".  Genuine infeasibility still raises
    ``InfeasibleLPError``/``UnboundedLPError`` for the caller to name.

    ``bounds`` gives per-variable ``(low, high)`` ranges (``high`` ``None`` for
    unbounded), keyed by column position; sympy rewrites those with auxiliary
    variables rather than as rows, which is a different matrix and so pivots
    differently.  They are checked here too, since they are not in ``rows``.
    """
    _optimum, solution = linprog(
        [_rational(value) for value in cost],
        [[_rational(value) for value in row] for row in rows],
        [_rational(value) for value in limits],
        # sympy empties the dict it is handed, so this is always a fresh one.
        bounds=(
            None
            if not bounds
            else {
                position: (
                    _rational(low),
                    None if high is None else _rational(high),
                )
                for position, (low, high) in bounds.items()
            }
        ),
    )
    values = [_fraction(cast(Expr, value)) for value in solution]
    # Only the columns the solver actually used can move a row off its limit.
    support = [(position, value) for position, value in enumerate(values) if value]
    for row, limit in zip(rows, limits, strict=True):
        total = Fraction(0)
        for position, value in support:
            coefficient = row[position]
            if coefficient:
                total += coefficient * value
        if total > limit:
            return None
    for position, (low, high) in (bounds or {}).items():
        if values[position] < low or (high is not None and values[position] > high):
            return None
    return values


def _solve_exact_lp(
    columns: Sequence[AdjustedRecipe],
    active: Sequence[int],
    internal_items: Sequence[str],
    demand: Mapping[str, Fraction],
    machine_caps: Sequence[int | None] | None = None,
    minimum_rates: Mapping[int, Fraction] | None = None,
    objective: _ObjectiveCoefficients | None = None,
) -> list[Fraction]:
    """Recover exact rates over selected support and optional exact bounds."""
    if not active:
        raise InfeasibleError("the approximate rate solve selected no recipe support")

    def net(index: int, item_id: str) -> Fraction:
        column = columns[index]
        return column.outputs_per_craft.get(item_id, Fraction()) - column.inputs_per_craft.get(
            item_id, Fraction()
        )

    items = [item_id for item_id in internal_items if any(net(i, item_id) > 0 for i in active)]
    balance_rows: list[list[Fraction]] = []
    balance_limits: list[Fraction] = []
    for item_id in items:
        balance_rows.append([-net(index, item_id) for index in active])
        balance_limits.append(-demand.get(item_id, Fraction()))

    # The single-variable constraints are collected apart from the balance rows
    # so the retry below can hand them to sympy as variable bounds instead.
    ranges: dict[int, tuple[Fraction, Fraction | None]] = {}
    if minimum_rates:
        active_positions = {index: position for position, index in enumerate(active)}
        for index, minimum in minimum_rates.items():
            position = active_positions.get(index)
            if position is None:
                raise ValueError("minimum_rates must name active columns")
            ranges[position] = (minimum, None)

    if machine_caps is not None:
        if len(machine_caps) != len(active):
            raise ValueError("machine_caps must align with active columns")
        for position, (index, machines) in enumerate(zip(active, machine_caps, strict=True)):
            if machines is None:
                # Extraction columns are never capped: they never buy integer
                # machines, so there is nothing to cap.
                continue
            low, _high = ranges.get(position, (Fraction(0), None))
            ranges[position] = (low, Fraction(machines) * columns[index].crafts_per_second)

    matrix = list(balance_rows)
    limits = list(balance_limits)
    for position, (low, _high) in ranges.items():
        if not low:
            continue
        row = [Fraction()] * len(active)
        row[position] = Fraction(-1)
        matrix.append(row)
        limits.append(-low)
    for position, (_low, high) in ranges.items():
        if high is None:
            continue
        row = [Fraction()] * len(active)
        row[position] = Fraction(1)
        matrix.append(row)
        limits.append(high)

    objective = objective or _default_objective(columns)
    cost = [objective.continuous[index] for index in active]
    try:
        solution = _linprog_checked(cost, matrix, limits)
        if solution is None and ranges:
            # sympy oscillated on the row form and answered with a point that
            # is not a solution. The same system with the single-variable
            # constraints as bounds is a different matrix, so it pivots
            # differently; it is still checked before it is believed.
            solution = _linprog_checked(cost, balance_rows, balance_limits, ranges)
    except (InfeasibleLPError, UnboundedLPError) as exc:
        raise InfeasibleError(
            "the exact rate solve found no balanced, non-negative craft rates "
            f"over {', '.join(sorted({columns[i].recipe_id for i in active}))} "
            f"({type(exc).__name__})"
        ) from exc
    if solution is None:
        raise InfeasibleError(
            "the exact rate solve could not prove balanced, non-negative craft "
            f"rates over {', '.join(sorted({columns[i].recipe_id for i in active}))} "
            "(the simplex oscillated and returned a point that breaks its own "
            "constraints)"
        )

    crafts = [Fraction()] * len(columns)
    for position, index in enumerate(active):
        rate = solution[position]
        if rate < 0:
            raise InfeasibleError(
                f"the exact rate solve returned a negative craft rate for "
                f"{columns[index].recipe_id}, which would be negative machines"
            )
        crafts[index] = rate
    return crafts


def _exact_rates(
    columns: Sequence[AdjustedRecipe],
    raw_machines: Sequence[float],
    internal_items: Sequence[str],
    demand: Mapping[str, Fraction],
    objective: _ObjectiveCoefficients | None = None,
) -> list[Fraction]:
    """Recover exact rates inside the fixed-charge MILP's bought capacities.

    Extraction columns get a continuous machine variable in ``_run_milp``, so
    their raw value is never an integer machine count to
    round: one is active iff its raw value clears the solver's support
    tolerance, and it carries no machine cap -- FactorioLab never rounds
    extraction and this file never builds it. Crafting columns keep the
    integer-rounded activity and cap they always had.
    """
    active = [
        index
        for index, machines in enumerate(raw_machines)
        if (
            machines > _LP_SUPPORT_ABS_TOLERANCE
            if isinstance(columns[index], _ExtractionColumn)
            else round(machines) > 0
        )
    ]
    caps: list[int | None] = [
        None if isinstance(columns[index], _ExtractionColumn) else round(raw_machines[index])
        for index in active
    ]
    if not active:
        return [Fraction()] * len(columns)
    return _solve_exact_lp(
        columns,
        active,
        internal_items,
        demand,
        caps,
        objective=objective,
    )


def _exact_continuous_rates(
    columns: Sequence[AdjustedRecipe],
    raw_crafts: Sequence[float],
    internal_items: Sequence[str],
    demand: Mapping[str, Fraction],
    objective: _ObjectiveCoefficients | None = None,
) -> list[Fraction]:
    """Turn approximate LP support into exact rates without epsilon groups.

    GLOP supplies only the support. Every magnitude is solved again over exact
    rationals. Values below the documented absolute/relative tolerance are
    omitted as numerical noise. If that support cannot balance, exact recovery
    retries with every column so a genuinely required tiny rate is never
    silently discarded.
    """
    scale = max((abs(rate) for rate in raw_crafts), default=0.0)
    threshold = max(
        _LP_SUPPORT_ABS_TOLERANCE,
        scale * _LP_SUPPORT_REL_TOLERANCE,
    )
    active = [index for index, rate in enumerate(raw_crafts) if rate > threshold]
    if not active:
        return _solve_exact_lp(
            columns,
            tuple(range(len(columns))),
            internal_items,
            demand,
            objective=objective,
        )

    # Preserve every materially positive GLOP column as a physical group. The
    # floor is three orders below the support cutoff: large enough to be exact
    # and positive, small enough not to reuse the approximate magnitude.
    floor = Fraction.from_float(threshold).limit_denominator(10**12) / 1024
    minimum_rates = {index: floor for index in active}
    try:
        return _solve_exact_lp(
            columns,
            active,
            internal_items,
            demand,
            minimum_rates=minimum_rates,
            objective=objective,
        )
    except InfeasibleError:
        # A sub-tolerance column may still be genuinely required for balance.
        # Expand to all columns, while retaining every material support column.
        return _solve_exact_lp(
            columns,
            tuple(range(len(columns))),
            internal_items,
            demand,
            minimum_rates=minimum_rates,
            objective=objective,
        )


def solve(
    data: Dataset,
    request: LabRequest,
    *,
    tier: ProliferatorTier = ProliferatorTier.NONE,
    proliferable: frozenset[str] | None = None,
    fixed_modes: Mapping[str, ProliferatorMode] | None = None,
    mode_policy: ProliferatorMode = ProliferatorMode.NONE,
    time_limit_s: float = 30.0,
    prove_minimal: bool = True,
    machine_rank: MachineRank = MachineRank.EXACT,
    pinned_machines: frozenset[str] = frozenset(),
) -> RateSolution:
    """Solve ``request`` into exact flows and exact-ceiling machine counts.

    Production defaults to the fixed-charge MILP and minimises FactorioLab's
    recipe, machine, footprint, and surplus objective under the already-fixed
    mode policy. Every selected structure's rates are recovered exactly inside
    its bought capacities.

    ``prove_minimal=False`` selects the continuous form of that same objective,
    followed by exact support recovery and exact machine ceiling. If continuous
    support cannot be recovered, the fixed-charge model is the fallback.
    ``time_limit_s`` applies to either path.

    ``mode_policy`` deterministically applies one mode to every legal recipe in
    ``proliferable`` (or every recipe when it is ``None``), falling back to
    ``NONE`` where products are illegal. ``fixed_modes`` instead preserves
    authored per-recipe flow modes.

    ``machine_rank`` controls whether FactorioLab's ranked machine is exact or
    a speed ceiling. ``UP_TO`` re-chooses after rates are final because machine
    speed changes craft time, not the per-craft input and output vectors.
    ``pinned_machines`` names recipes whose supplied flow fixed the machine.

    Demand is served from the URL's declared ``Input`` supplies before anything
    is built, exactly as FactorioLab does it, so what comes back is the factory
    for the REMAINDER: ``target_rates`` records what the URL asked for and
    ``outputs`` what this block actually makes.
    """
    targets = target_rates(data, request)
    supplied = supplied_rates(data, request)
    # Demand is served from the declared supply first, so what this factory has
    # to MAKE is the remainder. ``demand`` carries that netting into every
    # balance row; ``targets`` stays the URL's ask, for reporting.
    demand = _lp_demand(targets, supplied)
    if targets and not any(
        rate > _supply_cap(supplied, item_id) for item_id, rate in targets.items()
    ):
        raise UnsupportedObjectiveError(
            "this URL already supplies every item it asks for -- "
            + ", ".join(sorted(targets))
            + " -- at or above the requested rate, so netting the declared Input "
            "objectives against the request leaves nothing to build"
        )
    excluded = _excluded_recipes(data, request)
    forbidden = forbidden_inputs(request)
    has_surplus_cost = _cost(request.costs.surplus, 0) > 0
    producers, external = _resolve_chain(
        data,
        targets,
        excluded,
        supplied,
        include_consumers=has_surplus_cost,
        forbidden=forbidden,
    )
    internal_items = sorted(producers)
    columns = _columns(
        data,
        producers,
        request,
        tier,
        proliferable,
        fixed_modes,
        None if fixed_modes is not None else mode_policy,
    )
    if not any(not isinstance(column, _ExtractionColumn) for column in columns):
        # Extraction alone is not a factory: at least one crafting column must
        # reach the requested item, or there is nothing here to build.
        wanted = ", ".join(f"{item} at {rate}/s" for item, rate in sorted(targets.items()))
        tried = (
            ", ".join(request.machine_rank_ids)
            if request.machine_rank_ids
            else "the default machine ranking"
        )
        raise InfeasibleError(
            f"no buildable recipes reach {wanted or 'the requested item'} with "
            f"{tried} enabled ({len(excluded)} recipe(s) excluded, "
            f"{len(producers)} intermediate item(s) reachable)"
        )
    objective = _objective_coefficients(data, request, columns)
    balance_items = (
        sorted(set(internal_items) | set(objective.items)) if has_surplus_cost else internal_items
    )

    crafts: list[Fraction] = []
    used_milp = prove_minimal
    if not used_milp:
        try:
            raw_crafts = _run_continuous_lp(
                columns,
                balance_items,
                demand,
                objective=objective,
                time_limit_s=time_limit_s,
            )
            crafts = _exact_continuous_rates(
                columns,
                raw_crafts,
                balance_items,
                demand,
                objective,
            )
        except InfeasibleError:
            used_milp = True

    if used_milp:
        _, raw_machines = _run_milp(
            columns,
            balance_items,
            demand,
            objective=objective,
            time_limit_s=time_limit_s,
        )
        crafts = _exact_rates(
            columns,
            raw_machines,
            balance_items,
            demand,
            objective,
        )

    # Rebuild before the lower bound and group materialisation so every
    # downstream count, area, and capacity check sees the same machine.
    columns, machine_moves = rechoose_columns(
        data,
        request,
        columns,
        crafts,
        machine_rank=machine_rank,
        tier=tier,
        pinned=pinned_machines,
    )

    geometric_objective = _default_objective(columns)
    if used_milp or objective != geometric_objective:
        try:
            lower_raw = _run_continuous_lp(
                columns,
                balance_items,
                demand,
                objective=geometric_objective,
                time_limit_s=time_limit_s,
            )
            lower_bound = sum(
                (
                    Fraction(rate).limit_denominator(10**6)
                    / column.crafts_per_second
                    * column.footprint_area
                    for rate, column in zip(lower_raw, columns, strict=True)
                    if rate > _LP_SUPPORT_ABS_TOLERANCE
                ),
                Fraction(),
            )
        except InfeasibleError:  # pragma: no cover - the production solve succeeded
            lower_bound = Fraction()
    else:
        lower_bound = sum(
            (
                craft_rate / column.crafts_per_second * column.footprint_area
                for craft_rate, column in zip(crafts, columns, strict=True)
            ),
            Fraction(),
        )

    # Extraction columns never become a SolvedGroup -- mining, pumping, and
    # orbital collection all happen outside the blueprint -- so their output
    # is accumulated separately and never counted as "produced" below.
    groups: list[SolvedGroup] = []
    extracted: dict[str, Fraction] = {}
    for column, craft_rate in zip(columns, crafts, strict=True):
        if craft_rate <= 0:
            continue
        if isinstance(column, _ExtractionColumn):
            for item_id, per_craft in column.outputs_per_craft.items():
                extracted[item_id] = extracted.get(item_id, Fraction(0)) + per_craft * craft_rate
            continue
        exact = craft_rate / column.crafts_per_second
        count = -((-exact.numerator) // exact.denominator)  # ceil, exactly
        groups.append(
            SolvedGroup(
                recipe_id=column.recipe_id,
                machine_item_id=column.machine_item_id,
                mode=column.mode,
                machines=int(count),
                exact_machines=exact,
                crafts_per_second=craft_rate,
                adjusted=column,
                inputs=MappingProxyType(
                    {k: v * craft_rate for k, v in column.inputs_per_craft.items()}
                ),
                outputs=MappingProxyType(
                    {k: v * craft_rate for k, v in column.outputs_per_craft.items()}
                ),
                proliferator_rate=column.proliferator_per_craft * craft_rate,
            )
        )
    groups.sort(key=lambda g: g.recipe_id)

    produced: dict[str, Fraction] = {}
    consumed: dict[str, Fraction] = {}
    for group in groups:
        for item_id, rate in group.outputs.items():
            produced[item_id] = produced.get(item_id, Fraction(0)) + rate
        for item_id, rate in group.inputs.items():
            consumed[item_id] = consumed.get(item_id, Fraction(0)) + rate

    # Continuous rates are exact at this boundary. Revalidate both invariants
    # after ceiling rather than trusting either LP implementation: every
    # crafting group fits inside its bought capacity, and every internally
    # produced item closes its balance including target demand -- crafted
    # plus extracted supply against consumption plus what was requested.
    for group in groups:
        capacity = group.machines * group.adjusted.crafts_per_second
        if group.crafts_per_second > capacity:
            raise InfeasibleError(
                f"{group.recipe_id} requires {group.crafts_per_second} crafts/s "
                f"but {group.machines} machine(s) provide only {capacity}"
            )
    for item_id in balance_items:
        required = consumed.get(item_id, Fraction()) + targets.get(item_id, Fraction())
        # The declared supply counts toward what is available, capped at the
        # declared rate: that is the whole of the netting, restated here so a
        # solve that leant on more supply than the URL offers cannot ship.
        available = (
            produced.get(item_id, Fraction())
            + extracted.get(item_id, Fraction())
            + _supply_cap(supplied, item_id)
        )
        if available < required:
            raise InfeasibleError(
                f"the exact rate solve leaves {item_id} short: "
                f"produces {available}, requires {required}"
            )

    # Every crafting group's input that crafting alone does not cover is a
    # belt-in input: either the item is genuinely external (no producer here,
    # or a declared Input objective) or it is an enabled extraction recipe's
    # output, which never becomes a SolvedGroup either -- its chosen supply
    # arrives on a belt exactly as a raw ore's does. If neither covers the
    # shortfall, something upstream is broken: the balance check above should
    # already have caught it, so this is a defensive invariant, not a normal
    # path.
    external_inputs: dict[str, Fraction] = {}
    for item_id, rate in consumed.items():
        shortfall = rate - produced.get(item_id, Fraction(0))
        if shortfall <= 0:
            continue
        available_extracted = extracted.get(item_id, Fraction(0))
        if available_extracted < shortfall and item_id not in external:
            raise InfeasibleError(
                f"the exact rate solve leaves {item_id} short by "
                f"{shortfall - available_extracted} after crafting and "
                "extraction, and it is not a declared external input"
            )
        external_inputs[item_id] = shortfall

    proliferator_total = sum((g.proliferator_rate for g in groups), Fraction(0))
    proliferator_item = tier.sprayed_item_id
    if proliferator_total > 0 and proliferator_item is not None:
        external_inputs[proliferator_item] = proliferator_total

    # Check the completed boundary, including auxiliary consumption added
    # after recipe balancing. No source of demand may bypass an input limit.
    for item_id, rate in external_inputs.items():
        if item_id in forbidden and rate > 0:
            raise InfeasibleError(
                f"{item_id} is limited to zero as an input, but the build needs "
                f"{rate} items/s of it from outside"
            )

    surplus: dict[str, Fraction] = {}
    for item_id, rate in produced.items():
        spare = rate - consumed.get(item_id, Fraction(0)) - targets.get(item_id, Fraction(0))
        if spare > 0:
            surplus[item_id] = spare
    # What leaves the boundary is what this block MAKES, which for a requested
    # item the URL also supplies is the netted remainder: the player's declared
    # rate covers the difference and never enters the blueprint, so claiming the
    # full request here would label a lane with a rate it does not carry.
    outputs: dict[str, Fraction] = {}
    for item_id in targets:
        made = produced.get(item_id, Fraction(0)) - consumed.get(item_id, Fraction(0))
        rate = max(targets[item_id] - _supply_cap(supplied, item_id), made)
        if rate > 0:
            outputs[item_id] = rate

    return RateSolution(
        groups=tuple(groups),
        external_inputs=MappingProxyType(dict(sorted(external_inputs.items()))),
        outputs=MappingProxyType(outputs),
        surplus=MappingProxyType(dict(sorted(surplus.items()))),
        target_rates=MappingProxyType(targets),
        tier=tier,
        forbidden_inputs=forbidden,
        lower_bound_area=lower_bound,
        machine_moves=machine_moves,
    )
