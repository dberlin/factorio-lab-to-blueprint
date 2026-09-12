from __future__ import annotations

from array import array
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from types import MappingProxyType

from flab2bp.dsp import catalog
from flab2bp.layout import geometric_router, junction
from flab2bp.layout.geometric_world import GeometricWorld
from flab2bp.layout.route_feedback import Cell, FeedbackState, NetId, NetRole
from flab2bp.layout.routing_domain import (
    _STEPS,
    _canvas_span,
    _cut_loops,
    _Grid,
    _make_grid,
    _PreparedNet,
    _PreparedRoutingProblem,
    _route_box,
    _routing_flags,
    _routing_transitions,
    _RoutingTransition,
)

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
    """Relaxed result; ``expansions`` records charged geometric work units."""

    path: tuple[Cell, ...] | None
    expansions: int
    exhausted_budget: bool
    cancelled: bool


@dataclass(slots=True)
class _CapacityLedger:
    """Integer occupancy plus the prepared sibling unit using each cell."""

    size: int
    occupancy: list[int] = field(init=False)
    units: dict[int, list[frozenset[NetId]]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.occupancy = [0] * self.size

    def present_cost(self, index: int, compatible: frozenset[NetId]) -> int:
        units = self.units.get(index)
        if units is None:
            return 0
        shares = any(unit <= compatible for unit in units)
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
            self.units[index] = [frozenset({net_id})]
            self.occupancy[index] = 1
        else:
            position = next(
                (i for i, unit in enumerate(units) if unit <= compatible),
                None,
            )
            if position is None:
                units.append(frozenset({net_id}))
                self.occupancy[index] += 1
            else:
                units[position] = units[position] | {net_id}
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
    reserved_by_owner = _reserved_by_owner(external_grid.reserved)
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
        flags, starts, goals = _route_ends(net, grid, reserved_by_owner)
        compatible = frozenset((*net.src_group, *net.dst_group))
        movement = _relaxed_transitions(
            grid.xstep, grid.levels, grid.vertical_construction, canvas.belt_rules
        )
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
            movement=movement,
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
                and 0 <= cell[2] < grid.levels
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


def _reserved_by_owner(reserved: Sequence[tuple[int, Cell]]) -> dict[Cell, int]:
    """The first reserved grid index for each destination, in source order."""
    by_owner: dict[Cell, int] = {}
    for index, owner in reserved:
        by_owner.setdefault(owner, index)
    return by_owner


def _route_ends(
    net: _PreparedNet,
    grid: _Grid,
    reserved_by_owner: Mapping[Cell, int],
) -> tuple[bytearray, tuple[int, ...], frozenset[int]]:
    destination = (net.dst.x, net.dst.y, net.dst.z)
    released: tuple[int, ...] = ()
    routing_ports: Collection[tuple[int, int, int]] = ()
    if net.net_id.role is NetRole.EXTERNAL:
        released_index = reserved_by_owner.get(destination)
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
    if not (x0 <= x <= x1 and y0 <= y <= y1 and 0 <= level < grid.levels):
        return None
    index = grid.index(cell)
    return index if flags[index] else None


@lru_cache(maxsize=32)
def _relaxed_transitions(
    xstep: int,
    levels: int,
    vertical_construction: bool,
    belt_rules: catalog.BeltAltitudeRules,
) -> tuple[tuple[_RoutingTransition, ...], ...]:
    """Ordinary moves plus a conservative physical Splitter displacement graph.

    Every connector comes from the actual supported model/port geometry and
    save ceiling. Ignoring stack footprints, foreign reservations, and support
    siting deliberately makes this a SUPERSET of detailed physical admission.
    A relaxed path is only congestion guidance, never an emission witness; an
    empty relaxed heap cannot overlook an admitted Splitter shortcut.
    """
    ordinary = _routing_transitions(xstep, levels, vertical_construction)
    connectors: list[dict[tuple[int, int, int], float]] = [{} for _ in range(levels)]
    for carry_level in range(levels):
        for yaw in (0.0, 90.0, 180.0, 270.0):
            for candidate in junction.splitter_route_candidates(
                0, 0, carry_level, yaw=yaw, altitude_rules=belt_rules, carries_item=""
            ):
                sx, sy, source_level = candidate.entry.dock
                tx, ty, target_level = candidate.exit.dock
                dx, dy = tx - sx, ty - sy
                dz = target_level - source_level
                # Nonnegative construction cost and Manhattan-dominating XY
                # travel keep the relaxed kernel's geometric heuristic valid.
                connectors[source_level][(dx, dy, dz)] = float(abs(dx) + abs(dy) + abs(dz))
    return tuple(
        (
            *ordinary[level],
            *(
                (dx * xstep + dy * levels + dz, 0, dx, dy, cost)
                for (dx, dy, dz), cost in sorted(connectors[level].items())
            ),
        )
        for level in range(levels)
    )


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
    *,
    movement: tuple[tuple[_RoutingTransition, ...], ...] | None = None,
) -> _SearchResult:
    if cancelled is not None and cancelled():
        return _SearchResult(None, 0, False, True)
    if not starts or not goals:
        return _SearchResult(None, 0, False, False)
    if budget <= 0:
        return _SearchResult(None, 0, True, False)

    transitions = (
        _routing_transitions(grid.xstep, grid.levels, grid.vertical_construction)
        if movement is None
        else movement
    )
    present = array("d", bytes(8 * grid.size))
    for index in ledger.units:
        present[index] = _PRESENT_COST * ledger.present_cost(index, compatible)
    world = GeometricWorld.from_grid(grid, flags, transitions)
    result = geometric_router.route(
        geometric_router.GeometricQuery(
            world=world,
            starts=tuple(starts),
            goals=tuple(sorted(goals)),
            pressure=1.0 + feedback.net_weight.get(net_id, 0.0),
            max_work=budget,
            present=present,
            charge_occupied_cells=True,
            cancelled=cancelled,
        )
    )
    path = (
        None
        if result.path is None
        else tuple(
            _cut_loops(
                [world.cell(index) for index in result.path],
                ramped=not grid.vertical_construction,
            )
        )
    )
    return _SearchResult(
        path,
        result.metrics["charged_work"],
        result.kind == "budget",
        result.kind == "cancelled",
    )


def _decode_cell(grid: _Grid, index: int) -> Cell:
    column, level = divmod(index, grid.levels)
    x, y = divmod(column, grid.gh)
    return x + grid.gx0, y + grid.gy0, level
