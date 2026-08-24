from __future__ import annotations

import heapq
import math
from array import array
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType

from flab2bp.layout.freeform import (
    _STEPS,
    LEVELS,
    _canvas_span,
    _cut_loops,
    _Grid,
    _make_grid,
    _PreparedNet,
    _PreparedRoutingProblem,
    _route_box,
    _routing_flags,
    _routing_transitions,
)
from flab2bp.layout.route_feedback import Cell, FeedbackState, NetId, NetRole

_PRESENT_COST = 1.0


@dataclass(frozen=True, slots=True)
class GlobalNetResult:
    net_id: NetId
    length: int
    level_changes: int
    overflow: int
    expansions: int


@dataclass(frozen=True, slots=True)
class GlobalRouteResult:
    net_results: tuple[GlobalNetResult, ...]
    paths: Mapping[NetId, tuple[Cell, ...]]
    overflow_cells: int
    total_overflow: int
    max_overflow: int
    unreachable_ports: int
    rounds: int
    expansions: int
    hot_cells: tuple[Cell, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "paths", MappingProxyType(dict(self.paths)))


@dataclass(frozen=True, slots=True)
class _SearchResult:
    path: tuple[Cell, ...] | None
    expansions: int


@dataclass(slots=True)
class _CapacityLedger:
    """Integer occupancy plus the prepared sibling unit using each cell."""

    size: int
    occupancy: list[int] = field(init=False)
    units: dict[int, list[list[NetId]]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.occupancy = [0] * self.size

    def present_cost(self, index: int, compatible: frozenset[NetId]) -> int:
        units = self.units.get(index)
        if units is None:
            return 0
        shares = any(
            all(owner in compatible for owner in unit)
            for unit in units
        )
        return max(0, len(units) - 1) if shares else len(units)

    def occupy(
        self,
        index: int,
        net_id: NetId,
        compatible: frozenset[NetId],
    ) -> int:
        units = self.units.get(index)
        before = max(0, self.occupancy[index] - 1)
        if units is None:
            self.units[index] = [[net_id]]
            self.occupancy[index] = 1
        else:
            shared = next(
                (
                    unit
                    for unit in units
                    if all(owner in compatible for owner in unit)
                ),
                None,
            )
            if shared is None:
                units.append([net_id])
                self.occupancy[index] += 1
            else:
                shared.append(net_id)
        return max(0, self.occupancy[index] - 1) - before


def route_global_once(
    problem: _PreparedRoutingProblem,
    feedback: FeedbackState,
    budget: int,
) -> GlobalRouteResult:
    """Route all prepared nets once with relaxed provisional occupancy.

    This is deliberately a metrics-and-paths pass. It never emits buildings,
    mutates the production canvas, constructs a Placement, or implies validity.
    """
    if type(budget) is not int or budget < 0:
        raise ValueError("global routing budget must be a non-negative integer")

    workspace = problem.new_workspace()
    canvas = workspace.canvas
    internal_box = _route_box(canvas, problem.route_bounds)
    external_box = _route_box(canvas, problem.limit or problem.route_bounds)
    span = _canvas_span(canvas, external_box)
    external_grid = _make_grid(canvas, external_box, span, feedback.cell_history)
    internal_grid = (
        external_grid
        if internal_box == external_box
        else _make_grid(canvas, internal_box, span, feedback.cell_history)
    )

    ledger = _CapacityLedger(external_grid.size)
    paths: dict[NetId, tuple[Cell, ...]] = {}
    net_results: list[GlobalNetResult] = []
    remaining = budget
    expansions = 0
    unreachable = 0

    for net in problem.nets:
        grid = external_grid if net.net_id.role is NetRole.EXTERNAL else internal_grid
        flags, starts, goals = _route_ends(net, grid)
        compatible = frozenset((*net.src_group, *net.dst_group))
        searched = _search_relaxed(
            grid,
            flags,
            starts,
            goals,
            ledger,
            compatible,
            feedback,
            net.net_id,
            remaining,
        )
        remaining -= searched.expansions
        expansions += searched.expansions
        path = searched.path
        if path is None:
            unreachable += 1
            net_results.append(
                GlobalNetResult(net.net_id, 0, 0, 0, searched.expansions)
            )
            continue

        overflow = sum(
            ledger.occupy(grid.index(cell), net.net_id, compatible)
            for cell in path
        )
        paths[net.net_id] = path
        net_results.append(
            GlobalNetResult(
                net_id=net.net_id,
                length=max(0, len(path) - 1),
                level_changes=sum(
                    before[2] != after[2]
                    for before, after in zip(path, path[1:], strict=False)
                ),
                overflow=overflow,
                expansions=searched.expansions,
            )
        )

    hot_indices = tuple(
        sorted(
            index
            for index, units in ledger.units.items()
            if len(units) > 1
        )
    )
    hot_cells = tuple(_decode_cell(external_grid, index) for index in hot_indices)
    overflows = tuple(ledger.occupancy[index] - 1 for index in hot_indices)
    return GlobalRouteResult(
        net_results=tuple(net_results),
        paths=paths,
        overflow_cells=len(hot_indices),
        total_overflow=sum(overflows),
        max_overflow=max(overflows, default=0),
        unreachable_ports=unreachable,
        rounds=1,
        expansions=expansions,
        hot_cells=hot_cells,
    )


def _route_ends(
    net: _PreparedNet,
    grid: _Grid,
) -> tuple[bytearray, tuple[int, ...], frozenset[int]]:
    destination = (net.dst.x, net.dst.y)
    released: tuple[int, ...] = ()
    routing_ports: Collection[tuple[int, int]] = ()
    if net.net_id.role is NetRole.EXTERNAL:
        released_index = next(
            (at for at, owner in grid.reserved if owner == destination),
            None,
        )
        if released_index is not None:
            released = (released_index,)
    elif net.src is not None:
        routing_ports = ((net.src.x, net.src.y), destination)

    flags = _routing_flags(
        grid,
        routing_ports=routing_ports,
        released_reservations=released,
    )
    goals = frozenset(
        index
        for cell in _adjacent_ground(destination)
        if (index := _live_index(grid, flags, cell)) is not None
    )
    if net.net_id.role is NetRole.EXTERNAL:
        starts = tuple(
            sorted(
                {
                    index
                    for cell in net.boundary_goals
                    if (index := _live_index(grid, flags, cell)) is not None
                }
            )
        )
    elif net.src is not None:
        starts = tuple(
            sorted(
                {
                    index
                    for cell in _adjacent_ground((net.src.x, net.src.y))
                    if (index := _live_index(grid, flags, cell)) is not None
                }
            )
        )
    else:
        starts = ()
    return flags, starts, goals


def _adjacent_ground(port: tuple[int, int]) -> tuple[Cell, ...]:
    x, y = port
    return tuple((x + dx, y + dy, 0) for dx, dy in _STEPS)


def _live_index(grid: _Grid, flags: bytearray, cell: Cell) -> int | None:
    x, y, level = cell
    x0, y0, x1, y1 = grid.span
    if not (x0 <= x <= x1 and y0 <= y <= y1 and 0 <= level < LEVELS):
        return None
    index = grid.index(cell)
    return index if flags[index] else None


def _search_relaxed(
    grid: _Grid,
    flags: bytearray,
    starts: Sequence[int],
    goals: Collection[int],
    ledger: _CapacityLedger,
    compatible: frozenset[NetId],
    feedback: FeedbackState,
    net_id: NetId,
    budget: int,
) -> _SearchResult:
    if budget <= 0 or not starts or not goals:
        return _SearchResult(None, 0)

    goal_set = frozenset(goals)
    goal_coordinates = tuple(_local_xy(grid, goal) for goal in sorted(goal_set))
    transitions = _routing_transitions(grid.xstep)
    history = grid.hist
    weight = 1.0 + feedback.net_weight.get(net_id, 0.0)
    best = [math.inf] * grid.size
    predecessor = array("i", [-2]) * grid.size
    via: dict[int, int] = {}
    open_heap: list[tuple[float, float, int]] = []

    def heuristic(index: int) -> int:
        x, y = _local_xy(grid, index)
        closest = 1 << 30
        for goal_x, goal_y in goal_coordinates:
            distance = abs(x - goal_x) + abs(y - goal_y)
            if distance < closest:
                closest = distance
        return closest

    def congestion(index: int) -> float:
        present = ledger.present_cost(index, compatible)
        historical = history[index] if history is not None else 0.0
        return weight * (_PRESENT_COST * present + historical)

    for start in starts:
        cost = congestion(start)
        if cost < best[start]:
            best[start] = cost
            predecessor[start] = -1
            heapq.heappush(open_heap, (cost + heuristic(start), cost, start))

    expansions = 0
    while open_heap:
        _estimated, cost, current = heapq.heappop(open_heap)
        if cost > best[current]:
            continue
        if expansions >= budget:
            return _SearchResult(None, expansions)
        expansions += 1
        if current in goal_set:
            return _SearchResult(
                _reconstruct(grid, current, predecessor, via),
                expansions,
            )

        _column, level = divmod(current, LEVELS)
        for target_offset, via_offset, _dx, _dy, base_cost in transitions[level]:
            target = current + target_offset
            if not flags[target]:
                continue
            run = current + via_offset if via_offset else -1
            if run != -1 and not flags[run]:
                continue
            next_cost = cost + base_cost + congestion(target)
            if run != -1:
                next_cost += congestion(run)
            if next_cost >= best[target]:
                continue
            best[target] = next_cost
            predecessor[target] = current
            if run == -1:
                via.pop(target, None)
            else:
                via[target] = run
            heapq.heappush(
                open_heap,
                (next_cost + heuristic(target), next_cost, target),
            )

    return _SearchResult(None, expansions)


def _reconstruct(
    grid: _Grid,
    goal: int,
    predecessor: array[int],
    via: Mapping[int, int],
) -> tuple[Cell, ...]:
    reversed_path: list[Cell] = []
    seen: set[int] = set()
    node = goal
    while node != -1:
        if node in seen:
            raise AssertionError("cycle in relaxed A* predecessor chain")
        seen.add(node)
        reversed_path.append(_decode_cell(grid, node))
        run = via.get(node)
        if run is not None:
            reversed_path.append(_decode_cell(grid, run))
        node = predecessor[node]
    return tuple(_cut_loops(list(reversed(reversed_path))))


def _local_xy(grid: _Grid, index: int) -> tuple[int, int]:
    column, _level = divmod(index, LEVELS)
    return divmod(column, grid.gh)


def _decode_cell(grid: _Grid, index: int) -> Cell:
    column, level = divmod(index, LEVELS)
    x, y = divmod(column, grid.gh)
    return x + grid.gx0, y + grid.gy0, level
