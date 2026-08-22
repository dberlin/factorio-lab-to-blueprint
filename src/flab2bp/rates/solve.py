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

# ortools ships no py.typed marker, so its modules read as untyped.
from ortools.linear_solver import pywraplp  # type: ignore[import-untyped]

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
    data: Dataset, targets: Iterable[str], excluded: frozenset[str]
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


def _exact_rates(
    columns: Sequence[AdjustedRecipe],
    raw_machines: Sequence[float],
    internal_items: Sequence[str],
    demand: Mapping[str, Fraction],
) -> list[Fraction]:
    """Re-derive craft rates exactly, taking only *structure* from the solver.

    The MILP decides which columns to use and, where an item has several
    producers, in what proportion.  Nothing else about its answer is trusted:
    the magnitudes are recomputed here by propagating demand through the chain
    in exact rational arithmetic.

    This matters more than it sounds.  Adopting the solver's floats directly --
    even snapped to rationals -- yields values like ``999/1000`` machines of
    copper-ingot where the true answer is exactly ``1``.  Those are genuine
    ``Fraction``s and would pass an ``isinstance`` check while being quietly
    wrong, so the fix has to be in the derivation, not the type.

    For the ~466 of 473 DSP items with a single producer this is plain
    back-substitution and is exactly right.  For the seven with several, the
    solver's split is adopted as an exact rational partition of unity.
    """
    capacity = [
        Fraction(round(n)) * column.crafts_per_second
        for n, column in zip(raw_machines, columns, strict=True)
    ]
    active = [i for i, n in enumerate(raw_machines) if round(n) > 0]
    if not active:
        return [Fraction(0)] * len(columns)

    def net(index: int, item_id: str) -> Fraction:
        column = columns[index]
        return column.outputs_per_craft.get(item_id, Fraction(0)) - column.inputs_per_craft.get(
            item_id, Fraction(0)
        )

    # Producers of each item, in a deterministic order.  Which columns exist and
    # their relative sizes come from the solver; the ordering only has to be
    # stable, so ties break on recipe id and mode.
    producers: dict[str, list[int]] = {}
    for item_id in internal_items:
        makers = [i for i in active if net(i, item_id) > 0]
        if makers:
            makers.sort(key=lambda i: (-round(raw_machines[i]), columns[i].recipe_id,
                                       columns[i].mode.value))
            producers[item_id] = makers

    crafts = [Fraction(0)] * len(columns)
    for _ in range(len(internal_items) + 8):
        required: dict[str, Fraction] = {}
        for item_id in producers:
            need = demand.get(item_id, Fraction(0))
            for i in active:
                consumed_per_craft = columns[i].inputs_per_craft.get(item_id, Fraction(0))
                if consumed_per_craft:
                    need += crafts[i] * consumed_per_craft
            required[item_id] = need

        updated = [Fraction(0)] * len(columns)
        for item_id, makers in producers.items():
            remaining = required[item_id]
            for position, index in enumerate(makers):
                if remaining <= 0:
                    break
                rate = net(index, item_id)
                available = capacity[index] * rate
                last = position == len(makers) - 1
                supplied = remaining if last or remaining <= available else available
                want = supplied / rate
                # A column may make several items; it must run fast enough for
                # whichever binds hardest.
                if want > updated[index]:
                    updated[index] = want
                remaining -= supplied
        if updated == crafts:
            break
        crafts = updated

    # Guarantee feasibility even if the loop above stopped short on a cyclic
    # chain: scale any item still in deficit up until it balances.
    for _ in range(len(internal_items) + 2):
        changed = False
        for item_id in internal_items:
            produced = sum(
                (crafts[i] * columns[i].outputs_per_craft.get(item_id, Fraction(0))
                 for i in range(len(columns))),
                Fraction(0),
            )
            consumed = demand.get(item_id, Fraction(0)) + sum(
                (crafts[i] * columns[i].inputs_per_craft.get(item_id, Fraction(0))
                 for i in range(len(columns))),
                Fraction(0),
            )
            makers = [i for i in producers.get(item_id, ()) if crafts[i] > 0]
            if produced >= consumed or not makers or produced <= 0:
                continue
            scale = consumed / produced
            for i in makers:
                crafts[i] *= scale
            changed = True
        if not changed:
            break
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
    excluded = frozenset(request.excluded_recipe_ids or ()) | data.default_recipe_excluded
    producers, external = _resolve_chain(data, targets, excluded)
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
