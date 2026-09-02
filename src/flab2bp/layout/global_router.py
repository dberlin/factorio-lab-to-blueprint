from __future__ import annotations

import heapq
import math
from array import array
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import cast

from flab2bp.layout import route_kernel
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
_MAX_ROUNDS = 5
_HOT_CELL_LIMIT = 256


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
    exhausted_budget: bool
    hot_cells: tuple[Cell, ...]
    hot_regions: tuple[tuple[int, int, int, int], ...]
    cancelled: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "paths", MappingProxyType(dict(self.paths)))


@dataclass(frozen=True, slots=True)
class _SearchResult:
    path: tuple[Cell, ...] | None
    expansions: int
    exhausted_budget: bool
    cancelled: bool


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
        shares = any(all(owner in compatible for owner in unit) for unit in units)
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
                (unit for unit in units if all(owner in compatible for owner in unit)),
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
    *,
    cancelled: Callable[[], bool] | None = None,
) -> GlobalRouteResult:
    """Route all prepared nets once with relaxed provisional occupancy.

    This is deliberately a metrics-and-paths pass. It never emits buildings,
    mutates the production canvas, constructs a Placement, or implies validity.
    """
    _check_budget(budget)
    result, overflows, grid = _route_round(
        problem,
        feedback,
        feedback.cell_history,
        budget,
        problem.nets,
        cancelled,
    )
    hot_cells, hot_regions = _hot_summary(dict(overflows), grid)
    return GlobalRouteResult(
        net_results=result.net_results,
        paths=result.paths,
        overflow_cells=result.overflow_cells,
        total_overflow=result.total_overflow,
        max_overflow=result.max_overflow,
        unreachable_ports=result.unreachable_ports,
        rounds=1,
        expansions=result.expansions,
        exhausted_budget=result.exhausted_budget,
        hot_cells=hot_cells,
        hot_regions=hot_regions,
        cancelled=result.cancelled,
    )


def route_global(
    problem: _PreparedRoutingProblem,
    feedback: FeedbackState,
    budget: int,
    *,
    max_rounds: int = _MAX_ROUNDS,
    cancelled: Callable[[], bool] | None = None,
) -> GlobalRouteResult:
    """Negotiate congestion for the whole prepared problem deterministically."""
    _check_budget(budget)
    _check_max_rounds(max_rounds)
    history = dict(feedback.cell_history)
    nets = _routing_order(problem.nets)
    remaining = budget
    expansions = 0

    for round_number in range(1, max_rounds + 1):
        result, overflows, grid = _route_round(
            problem,
            feedback,
            history,
            remaining,
            nets,
            cancelled,
        )
        remaining -= result.expansions
        expansions += result.expansions
        for cell, overflow in overflows:
            history[cell] = history.get(cell, 0.0) + overflow
        hot_cells, hot_regions = _hot_summary(history, grid)
        negotiated = GlobalRouteResult(
            net_results=result.net_results,
            paths=result.paths,
            overflow_cells=result.overflow_cells,
            total_overflow=result.total_overflow,
            max_overflow=result.max_overflow,
            unreachable_ports=result.unreachable_ports,
            rounds=round_number,
            expansions=expansions,
            exhausted_budget=result.exhausted_budget,
            hot_cells=hot_cells,
            hot_regions=hot_regions,
            cancelled=result.cancelled,
        )
        if result.cancelled or result.exhausted_budget or result.total_overflow == 0:
            return negotiated

    return negotiated


def _check_budget(budget: int) -> None:
    if type(budget) is not int or budget < 0:
        raise ValueError("global routing budget must be a non-negative integer")


def _check_max_rounds(max_rounds: int) -> None:
    if type(max_rounds) is not int or max_rounds <= 0:
        raise ValueError("global routing rounds must be a positive integer")


def _route_round(
    problem: _PreparedRoutingProblem,
    feedback: FeedbackState,
    history: Mapping[Cell, float],
    budget: int,
    nets: Sequence[_PreparedNet],
    cancelled: Callable[[], bool] | None,
) -> tuple[GlobalRouteResult, tuple[tuple[Cell, int], ...], _Grid]:
    workspace = problem.new_workspace()
    canvas = workspace.canvas
    internal_box = _route_box(canvas, problem.route_bounds)
    external_box = _route_box(canvas, problem.limit or problem.route_bounds)
    span = _canvas_span(canvas, external_box)
    external_grid = _make_grid(canvas, external_box, span, history)
    internal_grid = (
        external_grid
        if internal_box == external_box
        else _make_grid(canvas, internal_box, span, history)
    )

    ledger = _CapacityLedger(external_grid.size)
    paths: dict[NetId, tuple[Cell, ...]] = {}
    net_results: list[GlobalNetResult] = []
    remaining = budget
    expansions = 0
    unreachable = 0
    exhausted_budget = False
    was_cancelled = False

    for net_index, net in enumerate(nets):
        if cancelled is not None and cancelled():
            unreachable += len(nets) - net_index
            was_cancelled = True
            break
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
            cancelled,
        )
        remaining -= searched.expansions
        expansions += searched.expansions
        exhausted_budget = exhausted_budget or searched.exhausted_budget
        path = searched.path
        if path is None:
            unreachable += 1
            net_results.append(GlobalNetResult(net.net_id, 0, 0, 0, searched.expansions))
            if searched.cancelled:
                unreachable += len(nets) - net_index - 1
                was_cancelled = True
                break
            continue

        overflow = sum(ledger.occupy(grid.index(cell), net.net_id, compatible) for cell in path)
        paths[net.net_id] = path
        net_results.append(
            GlobalNetResult(
                net_id=net.net_id,
                length=max(0, len(path) - 1),
                level_changes=sum(
                    before[2] != after[2] for before, after in zip(path, path[1:], strict=False)
                ),
                overflow=overflow,
                expansions=searched.expansions,
            )
        )

    if not was_cancelled and cancelled is not None:
        was_cancelled = cancelled()

    overflow_indices = tuple(
        sorted(index for index, units in ledger.units.items() if len(units) > 1)
    )
    overflows = tuple(
        (_decode_cell(external_grid, index), ledger.occupancy[index] - 1)
        for index in overflow_indices
    )
    return (
        GlobalRouteResult(
            net_results=tuple(net_results),
            paths=paths,
            overflow_cells=len(overflows),
            total_overflow=sum(overflow for _cell, overflow in overflows),
            max_overflow=max(
                (overflow for _cell, overflow in overflows),
                default=0,
            ),
            unreachable_ports=unreachable,
            rounds=1,
            expansions=expansions,
            exhausted_budget=exhausted_budget,
            hot_cells=(),
            hot_regions=(),
            cancelled=was_cancelled,
        ),
        overflows,
        external_grid,
    )


def _routing_order(nets: Sequence[_PreparedNet]) -> tuple[_PreparedNet, ...]:
    indexed = enumerate(nets)
    return tuple(
        net
        for _index, net in sorted(
            indexed,
            key=lambda pair: (-_estimated_length(pair[1]), pair[0]),
        )
    )


def _estimated_length(net: _PreparedNet) -> int:
    destination = (net.dst.x, net.dst.y, net.dst.z)
    if net.src is not None:
        return (
            abs(net.src.x - destination[0])
            + abs(net.src.y - destination[1])
            + abs(net.src.z - destination[2])
        )
    return min(
        (
            abs(x - destination[0]) + abs(y - destination[1]) + abs(level - destination[2])
            for x, y, level in net.boundary_goals
        ),
        default=0,
    )


def _hot_summary(
    history: Mapping[Cell, float],
    grid: _Grid,
) -> tuple[tuple[Cell, ...], tuple[tuple[int, int, int, int], ...]]:
    x0, y0, x1, y1 = grid.box
    hot_cells = tuple(
        sorted(
            (
                cell
                for cell, value in history.items()
                if value > 0.0
                and x0 <= cell[0] <= x1
                and y0 <= cell[1] <= y1
                and 0 <= cell[2] < LEVELS
            ),
            key=lambda cell: (-history[cell], grid.index(cell)),
        )[:_HOT_CELL_LIMIT]
    )
    return hot_cells, _hot_regions(hot_cells)


def _hot_regions(
    hot_cells: Sequence[Cell],
) -> tuple[tuple[int, int, int, int], ...]:
    remaining = {(x, y) for x, y, _level in hot_cells}
    regions: list[tuple[int, int, int, int]] = []
    while remaining:
        seed = min(remaining)
        remaining.remove(seed)
        component = [seed]
        pending = [seed]
        while pending:
            x, y = pending.pop()
            for neighbour in ((x - 1, y), (x, y - 1), (x, y + 1), (x + 1, y)):
                if neighbour not in remaining:
                    continue
                remaining.remove(neighbour)
                component.append(neighbour)
                pending.append(neighbour)
        regions.append(
            (
                min(x for x, _y in component),
                min(y for _x, y in component),
                max(x for x, _y in component) + 1,
                max(y for _x, y in component) + 1,
            )
        )
    return tuple(sorted(regions))


def _route_ends(
    net: _PreparedNet,
    grid: _Grid,
) -> tuple[bytearray, tuple[int, ...], frozenset[int]]:
    destination = (net.dst.x, net.dst.y, net.dst.z)
    released: tuple[int, ...] = ()
    routing_ports: Collection[tuple[int, int, int]] = ()
    if net.net_id.role is NetRole.EXTERNAL:
        released_index = next(
            (at for at, owner in grid.reserved if owner == destination),
            None,
        )
        if released_index is not None:
            released = (released_index,)
    elif net.src is not None:
        routing_ports = ((net.src.x, net.src.y, net.src.z), destination)

    flags = _routing_flags(
        grid,
        routing_ports=routing_ports,
        released_reservations=released,
    )
    goals = frozenset(
        index
        for cell in _adjacent_port(destination)
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
                    for cell in _adjacent_port((net.src.x, net.src.y, net.src.z))
                    if (index := _live_index(grid, flags, cell)) is not None
                }
            )
        )
    else:
        starts = ()
    return flags, starts, goals


def _adjacent_port(port: tuple[int, int, int]) -> tuple[Cell, ...]:
    x, y, level = port
    return tuple((x + dx, y + dy, level) for dx, dy in _STEPS)


def _live_index(grid: _Grid, flags: bytearray, cell: Cell) -> int | None:
    x, y, level = cell
    x0, y0, x1, y1 = grid.span
    if not (x0 <= x <= x1 and y0 <= y <= y1 and 0 <= level < LEVELS):
        return None
    index = grid.index(cell)
    return index if flags[index] else None


def _kernel_bounds_hold(
    grid: _Grid,
    starts: Sequence[int],
    goals: Sequence[int],
) -> bool:
    """Whether the compiled relaxed loop's index preconditions hold on ``grid``.

    THE TEST IS ``span`` MINUS THE TWO-CELL PAD, not ``span`` itself, and the
    margin is the point rather than the containment.  A ramp travels two cells
    and the loop indexes ``cur +- 2 * xstep +- 2 * LEVELS +- 1`` with no bounds
    check of its own -- see :class:`_Grid` on why the pad exists.  A cell
    sitting IN the pad is inside ``span`` and still one whose neighbour
    arithmetic leaves the array: the compiled loop would read
    ``flags[cur - 2 * xstep]`` below zero, which the Python loop merely wrapped
    around silently.

    Two facts together cover every index the kernel touches.  ``box`` two cells
    inside ``span`` covers the reached cells, because ``_routing_flags`` only
    ever clears bytes of ``occ`` and ``occ`` is 1 only inside ``box``, so every
    cell the loop expands after passing ``flags[...]`` is inside the margin.
    The explicit sweep covers the seeds, which are pushed without a
    ``flags`` test.  Nothing reaches here with such a cell today -- starts and
    goals both come from :func:`_live_index`, which demands a passable cell --
    so this refuses no grid any test or corpus produces and moves no digest; it
    makes the kernel's precondition the wrapper's job to enforce rather than an
    invariant held at a distance.  A grid that fails it falls through to the
    Python loop, which is memory-safe on any input.
    """
    gx0, gy0, gx1, gy1 = grid.span
    lo_x, lo_y, hi_x, hi_y = grid.box
    if not (gx0 + 2 <= lo_x and hi_x <= gx1 - 2 and gy0 + 2 <= lo_y and hi_y <= gy1 - 2):
        return False
    width = gx1 - gx0 + 1
    for index in (*starts, *goals):
        if not 0 <= index < grid.size:
            return False
        x, y = _local_xy(grid, index)
        if not (2 <= x <= width - 3 and 2 <= y <= grid.gh - 3):
            return False
    return True


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
    cancelled: Callable[[], bool] | None,
) -> _SearchResult:
    if cancelled is not None and cancelled():
        return _SearchResult(None, 0, False, True)
    if not starts or not goals:
        return _SearchResult(None, 0, False, False)
    if budget <= 0:
        return _SearchResult(None, 0, True, False)

    goal_set = frozenset(goals)
    sorted_goals = sorted(goal_set)
    goal_coordinates = tuple(_local_xy(grid, goal) for goal in sorted_goals)
    transitions = _routing_transitions(grid.xstep)
    history = grid.hist
    weight = 1.0 + feedback.net_weight.get(net_id, 0.0)

    if route_kernel._compiled_relaxed is not None and _kernel_bounds_hold(
        grid, starts, sorted_goals
    ):
        # The compiled loop takes flat buffers rather than the closures: the
        # congestion term densified (already multiplied by `_PRESENT_COST`, so
        # the kernel's `weight * (present + historical)` is the same double),
        # the per-level transition table flattened behind a count slot, and the
        # goal columns the heuristic scans.
        present = array("d", bytes(8 * grid.size))
        for index in ledger.units:
            present[index] = _PRESENT_COST * ledger.present_cost(index, compatible)
        targets = array("q")
        vias = array("q")
        costs = array("d")
        for level_transitions in transitions:
            targets.append(len(level_transitions))
            vias.append(len(level_transitions))
            costs.append(0.0)
            for target_offset, via_offset, _dx, _dy, base_cost in level_transitions:
                targets.append(target_offset)
                vias.append(via_offset)
                costs.append(base_cost)
        goal_xy = array("q", [value for pair in goal_coordinates for value in pair])
        history_buffer: array[float]
        if history is None:
            history_buffer = array("d")
        elif isinstance(history, array):
            history_buffer = history
        else:
            history_buffer = array("d", history)
        # The extension is typed by `_route_kernel.pyi`, but the backend holds
        # it as a `Callable[..., object]` so a missing extension is a None
        # rather than an import error; the shape it returns is that stub's.
        path_indices, kernel_expansions, kernel_exhausted, kernel_cancelled = cast(
            "tuple[Sequence[int] | None, int, bool, bool]",
            route_kernel._compiled_relaxed(
                flags, present, history_buffer, weight, targets, vias, costs,
                array("q", starts), array("q", sorted_goals), goal_xy,
                grid.gh, LEVELS, budget, cancelled,
            ),
        )
        if path_indices is None:
            return _SearchResult(None, kernel_expansions, kernel_exhausted, kernel_cancelled)
        cells = [_decode_cell(grid, index) for index in path_indices]
        return _SearchResult(
            tuple(_cut_loops(cells)), kernel_expansions, kernel_exhausted, kernel_cancelled
        )

    best = [math.inf] * grid.size
    predecessor = array("i", [-2]) * grid.size
    via: dict[int, int] = {}
    open_heap: list[tuple[float, float, int]] = []

    def heuristic(index: int) -> int:
        x, y = _local_xy(grid, index)
        first_goal_x, first_goal_y = goal_coordinates[0]
        closest = abs(x - first_goal_x) + abs(y - first_goal_y)
        for goal_x, goal_y in goal_coordinates[1:]:
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
        if cancelled is not None and cancelled():
            return _SearchResult(None, expansions, False, True)
        _estimated, cost, current = heapq.heappop(open_heap)
        if cost > best[current]:
            continue
        if expansions >= budget:
            return _SearchResult(None, expansions, True, False)
        expansions += 1
        if current in goal_set:
            return _SearchResult(
                _reconstruct(grid, current, predecessor, via),
                expansions,
                False,
                False,
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

    return _SearchResult(None, expansions, False, False)


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
