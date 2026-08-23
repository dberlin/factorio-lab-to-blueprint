"""The production solve: objectives in, exact integer machine counts out.

Formulated as a MILP rather than "solve an LP then round up", because the two
give different answers and the difference is the deliverable.  Measured on the
example chain: minimising exact machine count yields 339 tiles, minimising
footprint area yields 325, and minimising *ceiled* machine count yields 25
machines occupying 330 tiles -- fewer machines on more ground, since an arc
smelter is 9 tiles and an assembler 16.  Density is the goal, so area is the
objective.

The model carries integer machine counts ``n`` alongside continuous craft rates
``x``, which is what DSP actually does: a machine whose output backs up
throttles, so six smelters covering a 5.64 requirement each run at 94%.
Upstream demand follows ``x`` (what is really consumed), never ``n``.

The solver is ortools' SCIP backend rather than HiGHS, and that is not a
preference.  ``highspy`` and ``ortools`` cannot share a process: ortools bundles
its *own* HiGHS inside ``libortools``, so importing ``highspy`` first makes
ortools resolve HiGHS symbols into an incompatible library (ImportError on
``setLocalOptionValue``), and importing it second segfaults mid-solve.  Since
the layout stage needs CP-SAT, the rate stage uses a solver from the same
library.  Do not reintroduce ``highspy``.

The solver returns floats.  Every rate that leaves this module is re-derived in
exact ``Fraction`` arithmetic from the integer solution, so no float ever
reaches ``BuildSpec``.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from types import MappingProxyType

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
    #: LP relaxation of the area objective -- a lower bound the layout bake-off
    #: can score against.
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


def _buildable_producers(
    data: Dataset, item_id: str, excluded: frozenset[str]
) -> tuple[Recipe, ...]:
    """Recipes that could make ``item_id`` inside the blueprint.

    Mining-flagged recipes are excluded by design: extraction happens outside
    and its output arrives on an input belt.  The ``mining`` flag is the cut
    line -- exactly 22 recipes carry it, covering mining machines, the water
    pump, the oil extractor and the orbital collectors uniformly.  Heuristics
    based on ``totalRecipe`` or producer names miss most of those.
    """
    return tuple(
        recipe
        for recipe in data.craftable_recipes_producing(item_id)
        if "mining" not in recipe.flags and recipe.id not in excluded
    )


def _resolve_chain(
    data: Dataset,
    targets: Iterable[str],
    excluded: frozenset[str],
    supplied: frozenset[str] = frozenset(),
) -> tuple[dict[str, tuple[Recipe, ...]], set[str]]:
    """Walk the recipe graph from the targets.

    Returns the producing recipes for each internal item, plus the set of items
    that must be belted in because nothing here can make them.
    """
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
        if not options:
            external.add(item_id)
            continue
        producers[item_id] = options
        for recipe in options:
            for ingredient in recipe.inputs:
                if ingredient not in seen:
                    queue.append(ingredient)
    return producers, external


def _columns(
    data: Dataset,
    producers: Mapping[str, tuple[Recipe, ...]],
    request: LabRequest,
    tier: ProliferatorTier,
    allowed_modes: Sequence[ProliferatorMode] | None,
    proliferable: frozenset[str] | None,
) -> list[AdjustedRecipe]:
    """One column per (recipe, legal proliferator mode) pair."""
    recipes = {r.id: r for options in producers.values() for r in options}
    columns: list[AdjustedRecipe] = []
    for recipe in recipes.values():
        machine_id = select_machine(data, recipe, request.machine_rank_ids)
        modes = available_modes(data, recipe, tier)
        if allowed_modes is not None:
            permitted = set(allowed_modes) | {ProliferatorMode.NONE}
            modes = tuple(m for m in modes if m in permitted)
        if proliferable is not None and recipe.id not in proliferable:
            modes = (ProliferatorMode.NONE,)
        if not modes:
            modes = (ProliferatorMode.NONE,)
        for mode in modes:
            columns.append(adjust(data, recipe, machine_id, mode, tier))
    return columns


def _run_milp(
    columns: Sequence[AdjustedRecipe],
    internal_items: Sequence[str],
    demand: Mapping[str, Fraction],
    *,
    integer: bool,
    time_limit_s: float,
    single_mode: bool = True,
) -> tuple[list[float], list[float]]:
    """Solve for craft rates and machine counts, returning ``(x, n)`` per column.

    With ``integer=False`` this is the LP relaxation, used as a lower bound.
    """
    model = pywraplp.Solver.CreateSolver("SCIP")
    if model is None:  # pragma: no cover - SCIP ships with ortools
        raise InfeasibleError("no MILP solver is available")
    model.SetTimeLimit(int(time_limit_s * 1000))

    crafts = [model.NumVar(0.0, model.infinity(), f"x{i}") for i in range(len(columns))]
    machines = [
        model.IntVar(0, _MAX_MACHINES, f"n{i}")
        if integer
        else model.NumVar(0.0, _MAX_MACHINES, f"n{i}")
        for i in range(len(columns))
    ]

    # A group's craft rate may never exceed what its machines can sustain.
    for craft, machine, column in zip(crafts, machines, columns, strict=True):
        model.Add(craft - float(column.crafts_per_second) * machine <= 0)

    if single_mode:
        # Force one proliferator mode per recipe.  Splitting a recipe across two
        # modes is legal in DSP (mode is a per-machine setting) and the LP loves
        # it, but it lands machine counts a hair past an integer -- 2.0032
        # machines of magnetic-coil costs a whole third machine -- so the split
        # reliably *costs* area once counts are rounded.  It also doubles the
        # groups the layout stage has to place for no structural benefit.
        by_recipe: dict[str, list[int]] = {}
        for index, column in enumerate(columns):
            by_recipe.setdefault(column.recipe_id, []).append(index)
        for indices in by_recipe.values():
            if len(indices) < 2:
                continue
            used = [model.IntVar(0, 1, f"m{index}") for index in indices]
            for flag, index in zip(used, indices, strict=True):
                model.Add(machines[index] - _MAX_MACHINES * flag <= 0)
            model.Add(model.Sum(used) <= 1)

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
            float(column.footprint_area) * machine
            for machine, column in zip(machines, columns, strict=True)
        )
    )

    status = model.Solve()
    if status != pywraplp.Solver.OPTIMAL:
        raise InfeasibleError(
            f"the production solve did not reach optimality (status: {status})"
        )
    return (
        [c.solution_value() for c in crafts],
        [m.solution_value() for m in machines],
    )


def _rational(value: Fraction) -> Rational:
    """``Fraction`` to sympy ``Rational``, exactly."""
    return Rational(value.numerator, value.denominator)


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


def _exact_rates(
    columns: Sequence[AdjustedRecipe],
    raw_machines: Sequence[float],
    internal_items: Sequence[str],
    demand: Mapping[str, Fraction],
) -> list[Fraction]:
    """Re-derive craft rates exactly, taking only *structure* from the solver.

    The MILP decides which columns to run and how many machines each gets.  Its
    machine counts are exact -- they are ``IntVar``s, so they come back as whole
    numbers -- and they are taken at face value here, as the capacity each group
    is allowed to use.  Its *craft* rates are not: they are floats, and belts are
    sized from craft rates, so a rate wrong in the last bits is a belt wrong in
    someone's game.  Measured across the 65-cell corpus, the solver's ``x``
    disagrees with the true requirement on 222 of 533 columns -- ``copper-ingot``
    came back at ``1.0`` where ``2/5`` is what the chain needs -- because once
    the machine counts are fixed the area objective no longer prices ``x`` at
    all, so any feasible rate satisfies it equally.  The magnitudes have to be
    re-derived.

    So they are re-derived as one exact linear program over ``Rational``:

        minimise   sum_j (footprint_j / crafts_per_second_j) * x_j
        subject to sum_j net_j(item) * x_j >= demand(item)   for every item made
                   0 <= x_j <= machines_j * crafts_per_second_j

    which is the MILP's own objective -- floor area -- read continuously, over
    the structure the MILP already chose.  The upper bound is what keeps the two
    answers consistent: a group can never be asked to run past the machines that
    were bought for it, so ``ceil(x_j / crafts_per_second_j) <= machines_j``
    holds by construction and the derived plan is never larger than the MILP's.
    Measured on all 533 groups of the corpus, the two now agree exactly.

    This replaces a hand-rolled fixed-point iteration that propagated demand
    back through the chain a bounded number of times.  That iteration had no
    handling for cycles in the producer graph, and DSP has one:
    ``reforming-refine`` turns two refined oil into three, and
    ``plasma-refining`` also yields refined oil, so refined-oil demand feeds
    back into itself.  Worse, the iteration charged a maker's own draw on the
    item it makes to the requirement *and* netted it out of the supply, which
    counted it twice: the balance read ``x = demand + 2x`` and grew by exactly a
    factor of two per round.  Measured on the reporting URL at Mk.II, the answer
    quadrupled for every two extra iterations -- 732,268 machines at the old
    bound, 46,862,330 six iterations later -- so the figure it printed was only
    ever a record of where the loop stopped.  To a linear program a cycle is an
    ordinary pair of matrix entries and needs no special handling at all.

    Solved rather than iterated, that URL comes back at 49 machines, with
    ``plasma-refining`` at 3 and ``reforming-refine`` at 1 -- exactly the counts
    the MILP had chosen all along.

    The solver is sympy's, not one written here.  Nothing else in reach solves a
    linear program in exact rationals -- ``pywraplp``/SCIP is float64 and is the
    very solver whose rates cannot be trusted at this point, CP-SAT is exact but
    integer-only and these rates are fractions like ``94895947/324`` whose
    denominator is not known until after the solve, and numpy is float64 too --
    and a hand-written simplex is a large piece of subtle numerical code whose
    bugs look exactly like plausible answers, which is the one failure mode this
    program is least able to absorb.

    ``linprog`` raises on an infeasible or unbounded program rather than
    returning something plausible, which is the behaviour wanted: a structure
    that cannot balance is a degenerate recipe graph, not a rounding problem.
    Feasibility is not in doubt for a well-formed chain -- the MILP found an
    integer point inside these very constraints -- so a refusal here names the
    recipes and stops.
    """
    active = [index for index, n in enumerate(raw_machines) if round(n) > 0]
    if not active:
        return [Fraction(0)] * len(columns)

    def net(index: int, item_id: str) -> Fraction:
        column = columns[index]
        return column.outputs_per_craft.get(item_id, Fraction(0)) - column.inputs_per_craft.get(
            item_id, Fraction(0)
        )

    # One balance row per item something here actually makes.  An item with no
    # net producer among the active columns is belted in, and constraining it
    # would be asking the blueprint to make something it never claimed to.
    items = [item_id for item_id in internal_items if any(net(i, item_id) > 0 for i in active)]

    # ``linprog`` minimises over ``A x <= b`` with ``x >= 0`` implied, so the
    # balances are negated into that form.  Surplus is allowed and deficit is
    # not, which is what makes joint products expressible at all.
    matrix: list[list[Rational]] = []
    limits: list[Rational] = []
    for item_id in items:
        matrix.append([_rational(-net(index, item_id)) for index in active])
        limits.append(_rational(-demand.get(item_id, Fraction(0))))
    for position, index in enumerate(active):
        row = [Rational(0)] * len(active)
        row[position] = Rational(1)
        matrix.append(row)
        limits.append(
            _rational(Fraction(round(raw_machines[index])) * columns[index].crafts_per_second)
        )

    cost = [
        _rational(Fraction(columns[index].footprint_area) / columns[index].crafts_per_second)
        for index in active
    ]

    try:
        _optimum, solution = linprog(cost, matrix, limits)
    except (InfeasibleLPError, UnboundedLPError) as exc:
        raise InfeasibleError(
            "the exact rate solve found no balanced, non-negative set of craft "
            "rates for the machines the MILP chose, so the recipe graph over "
            f"{', '.join(sorted({columns[i].recipe_id for i in active}))} does "
            f"not close ({type(exc).__name__})"
        ) from exc

    crafts = [Fraction(0)] * len(columns)
    for position, index in enumerate(active):
        rate = _fraction(solution[position])
        # ``linprog``'s standard form implies ``x >= 0``, but a negative rate
        # would mean negative machines, and sympy's *other* entry points do not
        # honour ``nonnegative=True`` symbols -- so this is checked, not assumed.
        if rate < 0:
            raise InfeasibleError(
                f"the exact rate solve returned a negative craft rate for "
                f"{columns[index].recipe_id}, which would be negative machines"
            )
        crafts[index] = rate
    return crafts


def solve(
    data: Dataset,
    request: LabRequest,
    *,
    tier: ProliferatorTier = ProliferatorTier.NONE,
    allowed_modes: Sequence[ProliferatorMode] | None = None,
    proliferable: frozenset[str] | None = None,
    single_mode: bool = True,
    time_limit_s: float = 30.0,
) -> RateSolution:
    """Solve ``request`` into integer machine counts and exact item flows.

    ``proliferable`` restricts which recipes may be proliferated at all, which
    is how the candidate frontier is generated: proliferating a recipe forces
    its inputs onto belts, and only the layout stage can price that.
    """
    targets = target_rates(data, request)
    supplied = supplied_rates(data, request)
    excluded = frozenset(request.excluded_recipe_ids or ()) | data.default_recipe_excluded
    producers, external = _resolve_chain(data, targets, excluded, frozenset(supplied))
    internal_items = sorted(producers)
    columns = _columns(data, producers, request, tier, allowed_modes, proliferable)
    if not columns:
        raise InfeasibleError("no buildable recipes reach the requested item")

    _, raw_machines = _run_milp(
        columns,
        internal_items,
        targets,
        integer=True,
        time_limit_s=time_limit_s,
        single_mode=single_mode,
    )
    crafts = _exact_rates(columns, raw_machines, internal_items, targets)

    try:
        lp_raw, _ = _run_milp(
            columns,
            internal_items,
            targets,
            integer=False,
            time_limit_s=time_limit_s,
            single_mode=False,
        )
        lower_bound = sum(
            (
                Fraction(x).limit_denominator(10**6)
                / column.crafts_per_second
                * column.footprint_area
                for x, column in zip(lp_raw, columns, strict=True)
                if x > 1e-9
            ),
            Fraction(0),
        )
    except InfeasibleError:  # pragma: no cover - the MILP already succeeded
        lower_bound = Fraction(0)

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
