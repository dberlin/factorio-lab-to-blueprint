"""The production solve: FactorioLab's objective and exact flows out.

Each candidate fixes one proliferator mode per recipe before solving. That
removes mode-activation binaries and leaves a small fixed-charge MILP over craft
rates and integer physical machine counts. The URL's recipe, machine, footprint,
and surplus costs are applied with FactorioLab's exact coefficient semantics.

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
from dataclasses import dataclass, field
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
from flab2bp.spec import ProliferatorMode

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
    items = tuple(
        sorted(
            {
                item_id
                for column in columns
                for item_id in column.outputs_per_craft
            }
        )
    )

    machine: list[Fraction] = []
    surplus: list[Fraction] = []
    continuous: list[Fraction] = []
    for column in columns:
        recipe = data.recipe(column.recipe_id)
        override = request.recipes.get(recipe.id)
        if override is not None and override.cost is not None:
            per_machine = override.cost
        elif recipe.cost is not None:
            output_rate = sum(
                column.outputs_per_craft.values(),
                Fraction(),
            ) * column.crafts_per_second
            per_machine = output_rate * recipe.cost * factor_cost
        else:
            per_machine = machine_cost
            # FactorioLab treats footprint cost as an on/off multiplier: any
            # nonzero value multiplies machine cost by tile area.
            if footprint_cost:
                per_machine *= column.footprint_area

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
        continuous.append(
            per_machine / column.crafts_per_second + surplus_per_craft
        )

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
            cost / column.crafts_per_second
            for cost, column in zip(machine, columns, strict=True)
        ),
        items=(),
    )

def target_rates(data: Dataset, request: LabRequest) -> dict[str, Fraction]:
    """Normalise objectives to items/second, keyed by item id."""
    period = _SECONDS_PER_PERIOD[request.display_rate]
    out: dict[str, Fraction] = {}
    for objective in request.objectives:
        if objective.type is ObjectiveType.Input:
            continue  # a declared external supply; see supplied_rates()
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
            rate = objective.value * data.belt_speed(belt_id)
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
    item", which is exactly what an input belt is here: the item arrives at the
    boundary and nothing inside the blueprint makes it.  Mapping it onto
    ``external_inputs`` is the whole of the support -- an Input objective on
    ``proliferator-3`` is simply a proliferator belt with a declared rate.

    The declared rate is a *supply*, not a demand: it caps nothing and is
    recorded so the belt can be sized and labelled.
    """
    period = _SECONDS_PER_PERIOD[request.display_rate]
    out: dict[str, Fraction] = {}
    for objective in request.objectives:
        if objective.type is not ObjectiveType.Input:
            continue
        if objective.unit is ObjectiveUnit.Items:
            rate = objective.value / period
        elif objective.unit is ObjectiveUnit.Belts:
            rate = objective.value * data.belt_speed(request.belt_id or "conveyor-belt-1")
        else:
            raise UnsupportedObjectiveError(
                f"an Input objective in {objective.unit.name!r} units is not "
                "supported; use Items or Belts"
            )
        out[objective.target_id] = out.get(objective.target_id, Fraction(0)) + rate
    return out


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
        if "mining" not in recipe.flags
        and not recipe.is_technology
        and recipe.id not in excluded
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
    supplied: frozenset[str] = frozenset(),
    *,
    include_consumers: bool = False,
) -> tuple[dict[str, tuple[Recipe, ...]], set[str]]:
    """Walk the recipe graph from the targets.

    Returns the producing recipes for each internal item, plus the set of items
    that must be belted in because nothing here can make them. With a positive
    surplus cost, FactorioLab traverses recipes that either produce or consume
    each visited item and follows both their inputs and outputs. That wider
    closure lets downstream recipes consume coproduct surplus.
    """
    io_recipes: dict[str, list[Recipe]] = {}
    if include_consumers:
        for recipe in data.recipes:
            if (
                "mining" in recipe.flags
                or recipe.is_technology
                or recipe.id in excluded
            ):
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
        if item_id in supplied:
            # Declared as externally supplied, so do not build it even though a
            # recipe exists -- that is the point of an Input objective.
            external.add(item_id)
            continue

        options = _buildable_producers(data, item_id, excluded)
        if options:
            producers[item_id] = options
        else:
            external.add(item_id)

        matches: Iterable[Recipe] = (
            io_recipes.get(item_id, ()) if include_consumers else options
        )
        for recipe in matches:
            for ingredient in recipe.inputs:
                if ingredient not in seen:
                    queue.append(ingredient)
            if include_consumers:
                for product in recipe.outputs:
                    if product not in seen:
                        queue.append(product)
    return producers, external


def _columns(
    data: Dataset,
    producers: Mapping[str, tuple[Recipe, ...]],
    request: LabRequest,
    tier: ProliferatorTier,
    proliferable: frozenset[str] | None,
    fixed_modes: Mapping[str, ProliferatorMode] | None = None,
    mode_policy: ProliferatorMode | None = ProliferatorMode.NONE,
) -> list[AdjustedRecipe]:
    """Build one deterministic mode column per reachable recipe."""
    if fixed_modes is not None and proliferable is not None:
        raise ValueError("fixed_modes cannot be combined with proliferable")
    if fixed_modes is None and mode_policy is None:
        raise ValueError("a deterministic mode_policy is required without fixed_modes")

    recipes = {recipe.id: recipe for options in producers.values() for recipe in options}
    columns: list[AdjustedRecipe] = []
    for recipe in recipes.values():
        machine_id = select_machine(data, recipe, request.machine_rank_ids)
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
            float(cost) * craft
            for cost, craft in zip(objective.continuous, crafts, strict=True)
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
    """Solve the fixed-charge oracle for craft rates and integer machine counts."""
    model = pywraplp.Solver.CreateSolver("SCIP")
    if model is None:  # pragma: no cover - SCIP ships with ortools
        raise InfeasibleError("no MILP solver is available")
    model.SetTimeLimit(int(time_limit_s * 1000))
    objective = objective or _default_objective(columns)

    crafts = [model.NumVar(0.0, model.infinity(), f"x{i}") for i in range(len(columns))]
    machines = [model.IntVar(0, _MAX_MACHINES, f"n{i}") for i in range(len(columns))]
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
                    for cost, machine in zip(
                        objective.machine, machines, strict=True
                    )
                ),
                *(
                    float(cost) * craft
                    for cost, craft in zip(
                        objective.surplus, crafts, strict=True
                    )
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
        raise InfeasibleError(
            f"the production solve did not reach optimality (status: {status})"
        )
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


def _solve_exact_lp(
    columns: Sequence[AdjustedRecipe],
    active: Sequence[int],
    internal_items: Sequence[str],
    demand: Mapping[str, Fraction],
    machine_caps: Sequence[int] | None = None,
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
    matrix: list[list[Rational]] = []
    limits: list[Rational] = []
    for item_id in items:
        matrix.append([_rational(-net(index, item_id)) for index in active])
        limits.append(_rational(-demand.get(item_id, Fraction())))

    if minimum_rates:
        active_positions = {index: position for position, index in enumerate(active)}
        for index, minimum in minimum_rates.items():
            position = active_positions.get(index)
            if position is None:
                raise ValueError("minimum_rates must name active columns")
            row = [_rational(Fraction())] * len(active)
            row[position] = _rational(Fraction(-1))
            matrix.append(row)
            limits.append(_rational(-minimum))

    if machine_caps is not None:
        if len(machine_caps) != len(active):
            raise ValueError("machine_caps must align with active columns")
        for position, (index, machines) in enumerate(
            zip(active, machine_caps, strict=True)
        ):
            row = [_rational(Fraction())] * len(active)
            row[position] = _rational(Fraction(1))
            matrix.append(row)
            limits.append(_rational(Fraction(machines) * columns[index].crafts_per_second))

    objective = objective or _default_objective(columns)
    cost = [_rational(objective.continuous[index]) for index in active]
    try:
        _optimum, solution = linprog(cost, matrix, limits)
    except (InfeasibleLPError, UnboundedLPError) as exc:
        raise InfeasibleError(
            "the exact rate solve found no balanced, non-negative craft rates "
            f"over {', '.join(sorted({columns[i].recipe_id for i in active}))} "
            f"({type(exc).__name__})"
        ) from exc

    crafts = [Fraction()] * len(columns)
    for position, index in enumerate(active):
        rate = _fraction(cast(Expr, solution[position]))
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
    """Recover exact rates inside the fixed-charge MILP's bought capacities."""
    active = [index for index, machines in enumerate(raw_machines) if round(machines) > 0]
    caps = [round(raw_machines[index]) for index in active]
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
    """
    targets = target_rates(data, request)
    supplied = supplied_rates(data, request)
    excluded = _excluded_recipes(data, request)
    has_surplus_cost = _cost(request.costs.surplus, 0) > 0
    producers, external = _resolve_chain(
        data,
        targets,
        excluded,
        frozenset(supplied),
        include_consumers=has_surplus_cost,
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
    if not columns:
        raise InfeasibleError("no buildable recipes reach the requested item")
    objective = _objective_coefficients(data, request, columns)
    balance_items = (
        sorted(set(internal_items) | set(objective.items))
        if has_surplus_cost
        else internal_items
    )

    crafts: list[Fraction] = []
    used_milp = prove_minimal
    if not used_milp:
        try:
            raw_crafts = _run_continuous_lp(
                columns,
                balance_items,
                targets,
                objective=objective,
                time_limit_s=time_limit_s,
            )
            crafts = _exact_continuous_rates(
                columns,
                raw_crafts,
                balance_items,
                targets,
                objective,
            )
        except InfeasibleError:
            used_milp = True

    if used_milp:
        _, raw_machines = _run_milp(
            columns,
            balance_items,
            targets,
            objective=objective,
            time_limit_s=time_limit_s,
        )
        crafts = _exact_rates(
            columns,
            raw_machines,
            balance_items,
            targets,
            objective,
        )

    geometric_objective = _default_objective(columns)
    if used_milp or objective != geometric_objective:
        try:
            lower_raw = _run_continuous_lp(
                columns,
                balance_items,
                targets,
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

    groups: list[SolvedGroup] = []
    for column, craft_rate in zip(columns, crafts, strict=True):
        if craft_rate <= 0:
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
    # after ceiling rather than trusting either LP implementation: every group
    # fits inside its bought capacity and every internally produced item closes
    # its balance including target demand.
    for group in groups:
        capacity = group.machines * group.adjusted.crafts_per_second
        if group.crafts_per_second > capacity:
            raise InfeasibleError(
                f"{group.recipe_id} requires {group.crafts_per_second} crafts/s "
                f"but {group.machines} machine(s) provide only {capacity}"
            )
    for item_id in balance_items:
        required = consumed.get(item_id, Fraction()) + targets.get(item_id, Fraction())
        available = produced.get(item_id, Fraction())
        if available < required:
            raise InfeasibleError(
                f"the exact rate solve leaves {item_id} short: "
                f"produces {available}, requires {required}"
            )

    external_inputs: dict[str, Fraction] = {}
    for item_id, rate in consumed.items():
        shortfall = rate - produced.get(item_id, Fraction(0))
        if shortfall > 0 and (item_id in external or item_id not in produced):
            external_inputs[item_id] = shortfall

    proliferator_total = sum((g.proliferator_rate for g in groups), Fraction(0))
    proliferator_item = tier.sprayed_item_id
    if proliferator_total > 0 and proliferator_item is not None:
        external_inputs[proliferator_item] = proliferator_total

    outputs = {item_id: targets[item_id] for item_id in targets}
    surplus: dict[str, Fraction] = {}
    for item_id, rate in produced.items():
        spare = rate - consumed.get(item_id, Fraction(0)) - targets.get(item_id, Fraction(0))
        if spare > 0:
            surplus[item_id] = spare
    for item_id in targets:
        made = produced.get(item_id, Fraction(0)) - consumed.get(item_id, Fraction(0))
        outputs[item_id] = max(targets[item_id], made)

    return RateSolution(
        groups=tuple(groups),
        external_inputs=MappingProxyType(dict(sorted(external_inputs.items()))),
        outputs=MappingProxyType(outputs),
        surplus=MappingProxyType(dict(sorted(surplus.items()))),
        target_rates=MappingProxyType(targets),
        tier=tier,
        lower_bound_area=lower_bound,
    )
