"""Shared physical flow constraints, solved natively and certified rationally.

GLOP proposes a primal flow and dual prices. Neither its floating-point status
nor a rounded objective is an acceptance/refusal certificate. Feasible flows
must satisfy every original rational constraint; refusals require an exact
weak-duality upper bound below the required flow.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from math import lcm
from typing import Literal

from ortools.linear_solver import pywraplp

ResourceKind = Literal["belt", "sorter"]


@dataclass(frozen=True, slots=True)
class Arc:
    source: int
    sink: int
    capacity: Fraction
    item: str
    lower: Fraction = Fraction(0)


@dataclass(frozen=True, slots=True)
class Resource:
    arcs: tuple[int, ...]
    capacity: Fraction
    kind: ResourceKind
    buildings: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class Model:
    nodes: int
    arcs: tuple[Arc, ...]
    resources: tuple[Resource, ...]


@dataclass(frozen=True, slots=True)
class Result:
    feasible: bool | None
    required: Fraction
    upper_bound: Fraction | None
    flows: tuple[Fraction, ...]
    resource_prices: tuple[Fraction, ...]


@dataclass(frozen=True, slots=True)
class _Edge:
    source: int
    sink: int
    capacity: Fraction
    original: int = -1


def solve(
    model: Model,
    kinds: frozenset[ResourceKind],
    *,
    items: frozenset[str] | None = None,
    resources: frozenset[int] | None = None,
) -> Result:
    """Find one simultaneous flow, or certify that none satisfies its bounds.

    Fixed machine/export rates are arc lower bounds. Their node imbalances
    become ordinary source/sink obligations; this is a model transformation,
    not a handwritten LP algorithm. All capacity-constrained cargo competes
    in the same native solve. ``items`` projects conservation onto supplied
    items without giving mixed cargo separate physical capacity allowances.
    """
    active = [items is None or arc.item in items for arc in model.arcs]
    balances = [Fraction(0)] * model.nodes
    edges: list[_Edge] = []
    positions: dict[int, int] = {}
    for index, arc in enumerate(model.arcs):
        if not active[index]:
            continue
        if not (0 <= arc.source < model.nodes and 0 <= arc.sink < model.nodes):
            raise ValueError("flow arc endpoints must reference existing nodes")
        if not 0 <= arc.lower <= arc.capacity:
            raise ValueError("flow arc must have ordered nonnegative bounds")
        if arc.lower:
            balances[arc.source] -= arc.lower
            balances[arc.sink] += arc.lower
        if arc.capacity > arc.lower:
            positions[index] = len(edges)
            capacity = arc.capacity - arc.lower if arc.lower else arc.capacity
            edges.append(_Edge(arc.source, arc.sink, capacity, index))
    source, sink = model.nodes, model.nodes + 1
    required = Fraction(0)
    for node, balance in enumerate(balances):
        if balance > 0:
            edges.append(_Edge(source, node, balance))
            required += balance
        elif balance < 0:
            edges.append(_Edge(node, sink, -balance))
    prices = [Fraction(0)] * len(model.resources)
    limits: dict[int, Fraction] = {}
    for index, resource in enumerate(model.resources):
        if resource.kind not in kinds or (resources is not None and index not in resources):
            continue
        lower = sum(
            (model.arcs[i].lower for i in resource.arcs if active[i] and model.arcs[i].lower),
            Fraction(0),
        )
        limit = resource.capacity - lower if lower else resource.capacity
        if limit < 0:
            prices[index] = Fraction(1)
            return Result(False, required, required + limit, (), tuple(prices))
        limits[index] = limit
    if required == 0:
        flows = tuple(
            arc.lower if enabled else Fraction(0)
            for arc, enabled in zip(model.arcs, active, strict=True)
        )
        return Result(True, required, required, flows, tuple(prices))

    solver = pywraplp.Solver.CreateSolver("GLOP")
    if solver is None:
        raise RuntimeError("OR-Tools GLOP backend is unavailable")
    rows = [solver.Constraint(0, 0) for _ in range(model.nodes)]
    variables = []
    objective = solver.Objective()
    objective.SetMaximization()
    for edge in edges:
        variable = solver.NumVar(0, float(edge.capacity), "")
        variables.append(variable)
        if edge.source < model.nodes and edge.source != edge.sink:
            rows[edge.source].SetCoefficient(variable, -1)
        if edge.sink < model.nodes and edge.source != edge.sink:
            rows[edge.sink].SetCoefficient(variable, 1)
        if edge.source == source:
            objective.SetCoefficient(variable, 1)
    resource_rows = {}
    for index, limit in limits.items():
        row = solver.Constraint(-solver.infinity(), float(limit))
        resource_rows[index] = row
        for arc_index in model.resources[index].arcs:
            position = positions.get(arc_index)
            if position is not None:
                row.SetCoefficient(variables[position], 1)
    status = solver.Solve()
    if status != pywraplp.Solver.OPTIMAL:
        # Zero residual flow is feasible after checking negative resource
        # limits above. An infeasible/abnormal native status is not a proof.
        return Result(None, required, None, (), tuple(prices))

    floats = tuple(variable.solution_value() for variable in variables)
    constrained = frozenset(limits)
    lattice = 0
    for denominator in (1_000_000, 1_000_000_000):
        # Transport chains repeat native values; equal floats reconstruct identically.
        rational_values = {
            value: Fraction(value).limit_denominator(denominator) for value in set(floats)
        }
        values = tuple(rational_values[value] for value in floats)
        flows = _certify_primal(model, active, edges, values, constrained, required)
        if flows is not None:
            return Result(True, required, required, flows, tuple(prices))
        # Independent bounded-denominator approximations can break conservation
        # on larger-denominator inputs. The residual bounds provide another
        # rational reconstruction grid, not permission to round a constraint.
        if not lattice:
            denominators = {edge.capacity.denominator for edge in edges}
            denominators.update(limit.denominator for limit in limits.values())
            lattice = lcm(*denominators)
        lattice_values = {value: Fraction(round(value * lattice), lattice) for value in set(values)}
        recovered = tuple(lattice_values[value] for value in values)
        flows = _certify_primal(model, active, edges, recovered, constrained, required)
        if flows is not None:
            return Result(True, required, required, flows, tuple(prices))

    potentials = [Fraction(row.dual_value()).limit_denominator(1_000_000) for row in rows]
    potentials.extend((Fraction(0), Fraction(0)))
    resource_cost = [Fraction(0)] * len(edges)
    upper_bound = Fraction(0)
    for index, row in resource_rows.items():
        # Any nonnegative prices yield a valid weak-duality bound. This is
        # not a tolerance-based load adjustment or a claimed native proof.
        price = max(Fraction(0), Fraction(row.dual_value()).limit_denominator(1_000_000))
        prices[index] = price
        if not price:
            continue
        upper_bound += price * limits[index]
        for arc_index in model.resources[index].arcs:
            position = positions.get(arc_index)
            if position is not None:
                resource_cost[position] += price
    for edge, cost in zip(edges, resource_cost, strict=True):
        reduced = (
            int(edge.source == source) + potentials[edge.source] - potentials[edge.sink] - cost
        )
        upper_bound += max(Fraction(0), reduced) * edge.capacity
    return Result(
        False if upper_bound < required else None, required, upper_bound, (), tuple(prices)
    )


def _certify_primal(
    model: Model,
    active: list[bool],
    edges: list[_Edge],
    values: tuple[Fraction, ...],
    resources: frozenset[int],
    required: Fraction,
) -> tuple[Fraction, ...] | None:
    balance = [Fraction(0)] * model.nodes
    delivered = Fraction(0)
    flows = [
        arc.lower if enabled else Fraction(0)
        for arc, enabled in zip(model.arcs, active, strict=True)
    ]
    for edge, value in zip(edges, values, strict=True):
        if not 0 <= value <= edge.capacity:
            return None
        if not value:
            continue
        if edge.source < model.nodes:
            balance[edge.source] -= value
        else:
            delivered += value
        if edge.sink < model.nodes:
            balance[edge.sink] += value
        if edge.original >= 0:
            flows[edge.original] += value
    if delivered != required or any(balance):
        return None
    for index, resource in enumerate(model.resources):
        if (
            index in resources
            and sum((flows[i] for i in resource.arcs if flows[i]), Fraction(0)) > resource.capacity
        ):
            return None
    return tuple(flows)
