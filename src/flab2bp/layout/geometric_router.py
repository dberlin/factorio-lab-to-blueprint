"""Analytic overhead proposals admitted by the router's unchanged physical rules.

These constructions accelerate ordinary search, not replace its fallback or
claim exhaustion. Every proposal is rechecked as a complete physical path.
"""

from __future__ import annotations

import heapq
import time
from collections import deque
from collections.abc import Callable, Collection, Iterator, Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from itertools import count, islice
from typing import TYPE_CHECKING, NamedTuple

from flab2bp.layout.route_feedback import Cell

if TYPE_CHECKING:
    from flab2bp.layout.geometric_world import FlatScreen, GeometricWorld

Direction = tuple[int, int]
Box = tuple[int, int, int, int]
DIRECTIONS: tuple[Direction, ...] = ((1, 0), (-1, 0), (0, 1), (0, -1))


@dataclass(frozen=True, slots=True)
class State:
    cell: Cell
    heading: Direction | None = None
    mode: str = "flat"
    # Saturation at two is sufficient: the ordinary graph has no history
    # prerequisite; a ramp contains its entire two-tile launch/run itself.
    # Keep arrival distinctions for constrained goal/portal consumers.
    run: int = 0


@dataclass(frozen=True, slots=True)
class FlatRun:
    direction: Direction
    length: int


@dataclass(frozen=True, slots=True)
class Ramp:
    direction: Direction
    delta: int
    levels: int


@dataclass(frozen=True, slots=True)
class Vertical:
    delta: int
    levels: int


Part = FlatRun | Ramp | Vertical
Construction = tuple[Part, ...]


@dataclass(frozen=True, slots=True)
class Piece:
    start: Cell
    part: Part

    @property
    def end(self) -> Cell:
        x, y, z = self.start
        part = self.part
        if isinstance(part, FlatRun):
            dx, dy = part.direction
            return x + dx * part.length, y + dy * part.length, z
        if isinstance(part, Ramp):
            dx, dy = part.direction
            return x + 2 * dx * part.levels, y + 2 * dy * part.levels, z + part.delta * part.levels
        return x, y, z + part.delta * part.levels

    def contains(self, cell: Cell, altitude: Fraction | None, *, ramped: bool) -> bool:
        """Exact membership without expanding an earlier run's interior.

        altitude=None asks about occupied routing cells, otherwise world cells.
        """
        x, y, z = self.start
        cx, cy, cz = cell
        part = self.part
        if isinstance(part, Vertical):
            return (
                cx == x
                and cy == y
                and min(z, self.end[2])
                <= (cz if altitude is None else altitude)
                <= max(z, self.end[2])
                and (altitude is None or altitude.denominator == 1)
            )
        dx, dy = part.direction
        distance = (cx - x) * dx + (cy - y) * dy
        if (cx - x) * dy != (cy - y) * dx:
            return False
        length = part.length if isinstance(part, FlatRun) else 2 * part.levels
        if not 0 <= distance <= length:
            return False
        if isinstance(part, FlatRun):
            return (cz if altitude is None else altitude) == z
        lattice = z + part.delta * (distance // 2)
        world = Fraction(2 * z + part.delta * distance, 2) if ramped else Fraction(lattice)
        return cz == lattice if altitude is None else altitude == world


@dataclass(frozen=True, slots=True)
class MacroEdge:
    start: State
    end: State
    construction: Construction
    pieces: tuple[Piece, ...]
    cost: float


@dataclass(slots=True)
class Counters:
    constructions: int = 0
    selected_macroedges: int = 0
    selected_parts: int = 0
    selected_cells: int = 0
    primitive_inspections: int = 0
    geometry_inspections: int = 0
    spatial_queries: int = 0
    static_cache_hits: int = 0
    static_cache_misses: int = 0
    static_cache_resets: int = 0
    feature_records: int = 0
    feature_inputs: int = 0
    feature_queries: int = 0
    feature_candidates: int = 0
    prefix_rejections: int = 0
    static_rejections: int = 0
    setup_s: float = 0.0
    validation_s: float = 0.0
    selected_expansion_s: float = 0.0


class Deadline(Exception):
    pass


def check_deadline(deadline: float | None) -> None:
    if deadline is not None and time.monotonic() >= deadline:
        raise Deadline


def inside(cell: Cell, box: Box) -> bool:
    return box[0] <= cell[0] <= box[2] and box[1] <= cell[1] <= box[3]


def flat_templates(start: Cell, end: Cell) -> Iterator[Construction]:
    """Offer corner routes and midpoint doglegs using the same cardinal runs.

    _routing_transitions permits every cardinal turn with zero turn surcharge
    and no preceding-run prerequisite. No extra turn placement is constructed.
    """
    if start[2] != end[2]:
        return
    dx, dy = end[0] - start[0], end[1] - start[1]
    horizontal = FlatRun((1 if dx > 0 else -1, 0), abs(dx)) if dx else None
    vertical = FlatRun((0, 1 if dy > 0 else -1), abs(dy)) if dy else None
    if horizontal and vertical:
        yield horizontal, vertical
        yield vertical, horizontal
        # A clear branch column can lie between the endpoint axes. These
        # doglegs have the same Manhattan length, without inventing a move.
        if horizontal.length > 1:
            first = abs((start[0] + end[0]) // 2 - start[0])
            yield (
                FlatRun(horizontal.direction, first),
                vertical,
                FlatRun(horizontal.direction, horizontal.length - first),
            )
        if vertical.length > 1:
            first = abs((start[1] + end[1]) // 2 - start[1])
            yield (
                FlatRun(vertical.direction, first),
                horizontal,
                FlatRun(vertical.direction, vertical.length - first),
            )
    elif horizontal is not None:
        yield (horizontal,)
    elif vertical is not None:
        yield (vertical,)
    else:
        yield ()


def movement_costs(
    levels: int, vertical: bool
) -> tuple[dict[tuple[int, int, int, bool], float], ...]:
    """Decode the actual movement table; no parallel cost/rule convention."""
    from flab2bp.layout.routing_domain import _routing_transitions

    xstep = 3 * levels
    return tuple(
        {
            (dx, dy, offset - dx * xstep - dy * levels, via != 0): cost
            for offset, via, dx, dy, cost in row
        }
        for row in _routing_transitions(xstep, levels, vertical)
    )


def primitive_moves(
    piece: Piece, ramped: bool
) -> Iterator[tuple[Cell, Cell | None, Fraction | None]]:
    """Yield target, optional via, via world altitude; transient values only."""
    x, y, z = piece.start
    part = piece.part
    if isinstance(part, FlatRun):
        dx, dy = part.direction
        for distance in range(1, part.length + 1):
            yield (x + dx * distance, y + dy * distance, z), None, None
    elif isinstance(part, Ramp):
        dx, dy = part.direction
        for step in range(part.levels):
            level = z + part.delta * step
            via = x + dx * (2 * step + 1), y + dy * (2 * step + 1), level
            altitude = Fraction(2 * level + part.delta, 2) if ramped else Fraction(level)
            yield (
                (x + 2 * dx * (step + 1), y + 2 * dy * (step + 1), level + part.delta),
                via,
                altitude,
            )
    elif isinstance(part, Vertical):
        for step in range(1, part.levels + 1):
            yield (x, y, z + part.delta * step), None, None


def evaluate(
    state: State,
    construction: Construction,
    world: GeometricWorld,
    scope: Box,
    counters: Counters,
    deadline: float | None,
    *,
    previous: Sequence[Piece] = (),
    root: Cell | None = None,
) -> MacroEdge | None:
    """Validate complete runs with original moves, cost, and occupied geometry.

    'previous' holds compact prefix pieces, never prefix cells. Endpoint flat
    altitude is fixed at every macro boundary; adding a suffix cannot rewrite
    the previous endpoint's physical altitude.
    """
    started = time.monotonic()
    counters.constructions += 1
    current = state.cell
    heading, mode, run = state.heading, state.mode, state.run
    pieces: list[Piece] = []
    cost = 0.0
    try:
        if not world.source_clear(state.cell) or not world.source_geometry_clear(
            state.cell, deadline
        ):
            return None
        for part in construction:
            check_deadline(deadline)
            if isinstance(part, (FlatRun, Ramp)) and part.direction not in DIRECTIONS:
                return None
            if isinstance(part, FlatRun) and part.length <= 0:
                return None
            if isinstance(part, (Ramp, Vertical)) and (
                part.delta not in (-1, 1) or part.levels <= 0
            ):
                return None
            piece = Piece(current, part)
            last = current
            occupied_prefix = (*previous, *pieces)
            for target, via, altitude in primitive_moves(piece, world.canvas.ramped):
                check_deadline(deadline)
                counters.primitive_inspections += 1
                if not 0 <= target[2] < world.canvas.levels:
                    return None
                key = target[0] - last[0], target[1] - last[1], target[2] - last[2], via is not None
                base_cost = world.costs[last[2]].get(key)
                if base_cost is None:
                    return None
                placements = (
                    ((via, altitude), (target, Fraction(target[2])))
                    if via is not None
                    else ((target, Fraction(target[2])),)
                )
                for cell, z in placements:
                    assert cell is not None and z is not None
                    if not inside(cell, scope) or not world.cell_clear(cell, z, deadline):
                        counters.static_rejections += 1
                        return None
                    if root == cell or any(
                        p.contains(cell, None, ramped=world.canvas.ramped)
                        or p.contains(cell, z, ramped=world.canvas.ramped)
                        for p in occupied_prefix
                    ):
                        counters.prefix_rejections += 1
                        return None
                cost += base_cost + world.history.get(target, 0.0) * world.pressure
                last = target
            current = piece.end
            pieces.append(piece)
            if isinstance(part, FlatRun):
                run = (
                    min(2, run + part.length)
                    if heading == part.direction and mode == "flat"
                    else min(2, part.length)
                )
                heading, mode = part.direction, "flat"
            elif isinstance(part, Ramp):
                heading, mode, run = part.direction, "rising" if part.delta > 0 else "falling", 0
            elif isinstance(part, Vertical):
                mode, run = "vertical", 0

        if not pieces:
            return None
        return MacroEdge(
            state, State(current, heading, mode, run), construction, tuple(pieces), cost
        )
    finally:
        counters.validation_s += time.monotonic() - started


def selected_path(
    edges: Sequence[MacroEdge],
    start: Cell,
    world: GeometricWorld,
    counters: Counters,
    deadline: float | None,
) -> tuple[Cell, ...]:
    """Only the selected route becomes a placement sequence, then certify it."""
    from flab2bp.layout.routing_domain import _altitude_profile, _legal_link

    started = time.monotonic()
    path: list[Cell] = [start]
    for edge in edges:
        for piece in edge.pieces:
            check_deadline(deadline)
            for target, via, _altitude in primitive_moves(piece, world.canvas.ramped):
                check_deadline(deadline)
                if via is not None:
                    path.append(via)
                path.append(target)
    altitudes = _altitude_profile(path, ramped=world.canvas.ramped)
    if altitudes is None:
        raise AssertionError("macro route violates original altitude profile")
    if len(set(path)) != len(path):
        raise AssertionError("selected macro route repeats a lattice cell")
    world_cells: set[tuple[int, int, Fraction]] = set()
    for index, (cell, altitude) in enumerate(zip(path, altitudes, strict=True)):
        check_deadline(deadline)
        physical = cell[0], cell[1], altitude
        if physical in world_cells:
            raise AssertionError("selected macro route repeats a world cell")
        world_cells.add(physical)
        if index == 0 and not world.source_geometry_clear(cell, deadline):
            raise AssertionError("selected source disagrees with geometry admission")
        if index and not world.cell_clear(cell, altitude, deadline):
            raise AssertionError("selected route disagrees with construction admission")
        if index:
            prior = path[index - 1]
            if not _legal_link(
                prior[0],
                prior[1],
                altitudes[index - 1],
                cell[0],
                cell[1],
                altitude,
                ramped=world.canvas.ramped,
            ):
                raise AssertionError("selected macro route contains an illegal physical link")
    counters.selected_macroedges = len(edges)
    counters.selected_parts = sum(len(edge.pieces) for edge in edges)
    counters.selected_cells = len(path)
    counters.selected_expansion_s += time.monotonic() - started
    return tuple(path)


class Node(NamedTuple):
    box: tuple[int, int, int, int]
    first: tuple[int, int, int]
    size: int
    left: Node | None
    right: Node | None


def build(cells: Sequence[Cell], deadline: float | None) -> Node:
    check_deadline(deadline)
    box = (
        min(c[0] for c in cells),
        min(c[1] for c in cells),
        max(c[0] for c in cells),
        max(c[1] for c in cells),
    )
    first = min(cells)
    if len(cells) == 1:
        return Node(box, first, 1, None, None)
    axis = 0 if box[2] - box[0] >= box[3] - box[1] else 1
    ordered = sorted(cells, key=lambda c: c[axis])
    middle = len(ordered) // 2
    return Node(
        box, first, len(cells), build(ordered[:middle], deadline), build(ordered[middle:], deadline)
    )


def endpoint_pairs(
    starts: Collection[Cell], goals: Collection[Cell], deadline: float | None
) -> Iterator[tuple[Cell, Cell]]:
    """Yield exact (distance, start, goal) order without a Cartesian allocation."""
    if not starts or not goals:
        return
    serial = count()
    queue: list[tuple[int, Cell, Cell, int, Node, Node]] = []

    def push(left: Node, right: Node) -> None:
        a, b = left.box, right.box
        distance = max(0, a[0] - b[2], b[0] - a[2]) + max(0, a[1] - b[3], b[1] - a[3])
        heapq.heappush(queue, (distance, left.first, right.first, next(serial), left, right))

    push(build(tuple(starts), deadline), build(tuple(goals), deadline))
    while queue:
        check_deadline(deadline)
        _, _, _, _, left, right = heapq.heappop(queue)
        if left.size == right.size == 1:
            yield left.first, right.first
        elif left.size >= right.size:
            assert left.left is not None and left.right is not None
            push(left.left, right)
            push(left.right, right)
        else:
            assert right.left is not None and right.right is not None
            push(left, right.left)
            push(left, right.right)


def _approaches(
    world: GeometricWorld,
    endpoint: Cell,
    height: int,
    bounds: Box,
    deadline: float | None,
    *,
    reverse: bool,
) -> Iterator[MacroEdge | None]:
    """Yield a leg, or a scheduling checkpoint for a rejected attempt."""
    if height == endpoint[2]:
        state = State(endpoint)
        yield MacroEdge(state, state, (), (), 0.0)
        return
    rise = height - endpoint[2]
    directions = list(DIRECTIONS)
    lead = 1
    while directions:
        continuing = []
        for dx, dy in directions:
            check_deadline(deadline)
            ground = (endpoint[0] + dx * lead, endpoint[1] + dy * lead, endpoint[2])
            # A longer straight approach cannot cross a refused prefix cell.
            if not inside(ground, bounds) or not world.cell_clear(
                ground, Fraction(endpoint[2]), deadline
            ):
                yield None
                continue
            continuing.append((dx, dy))
            for vertical in (True, False):
                if vertical and not world.canvas.belt_rules.vertical_construction:
                    continue
                normal_extension = 1 if vertical else 2
                for extension in (0, normal_extension):
                    direction = (-dx, -dy) if reverse else (dx, dy)
                    change = -1 if reverse else 1
                    transition = (
                        Vertical(change, rise) if vertical else Ramp(direction, change, rise)
                    )
                    upper_run = (FlatRun(direction, extension),) if extension else ()
                    lower_run = FlatRun(direction, lead)
                    if reverse:
                        distance = lead + extension + (0 if vertical else 2 * rise)
                        start = (
                            endpoint[0] + dx * distance,
                            endpoint[1] + dy * distance,
                            height,
                        )
                        construction = (*upper_run, transition, lower_run)
                    else:
                        start = endpoint
                        construction = (lower_run, transition, *upper_run)
                    edge = evaluate(
                        State(start),
                        construction,
                        world,
                        bounds,
                        world.counters,
                        deadline,
                        root=start,
                    )
                    yield edge
        directions = continuing
        lead += 1


@dataclass(slots=True)
class _Legs:
    source: Iterator[MacroEdge | None]
    values: list[MacroEdge] = field(default_factory=list)
    exhausted: bool = False

    def ensure(self, index: int) -> bool | None:
        """Pull at most one approach; None lets a rejected attempt yield."""
        if index < len(self.values):
            return True
        if self.exhausted:
            return False
        try:
            edge = next(self.source)
        except StopIteration:
            self.exhausted = True
            return False
        if edge is not None:
            self.values.append(edge)
        return True if index < len(self.values) else None


def _leg_pairs(first: _Legs, second: _Legs) -> Iterator[tuple[MacroEdge, MacroEdge] | None]:
    queue = [(0, 0, 0)]
    seen = {(0, 0)}
    while queue:
        _rank, left, right = heapq.heappop(queue)
        while (ready := first.ensure(left)) is None:
            yield None
        if not ready:
            continue
        while (ready := second.ensure(right)) is None:
            yield None
        if not ready:
            continue
        yield first.values[left], second.values[right]
        for pair in ((left + 1, right), (left, right + 1)):
            if pair not in seen:
                seen.add(pair)
                heapq.heappush(queue, (sum(pair), *pair))


def overhead_path(
    world: GeometricWorld,
    starts: Sequence[Cell],
    goals: Collection[Cell],
    bounds: Box,
    deadline: float | None,
    *,
    blocked: Collection[Cell] = (),
    screen: FlatScreen | None = None,
    admit_proposal: Callable[[tuple[Cell, ...], float | None], bool] | None = None,
) -> tuple[Cell, ...] | None:
    """Retain a certified proposal while comparing sampled congestion costs.

    History is a price, not a wall. An unpriced first proposal keeps the fast
    path; otherwise the existing query deadline bounds alternative comparison.
    Every returned incumbent has already passed full path certification.
    Caller-owned source obligations can reject a proposal without ending this
    candidate family. Final placement admission remains the caller's authority.
    """
    best: tuple[Cell, ...] | None = None
    best_cost = float("inf")
    comparing = False
    try:
        for edge, start in _candidate_edges(
            world, starts, goals, bounds, deadline, blocked=blocked, screen=screen
        ):
            if edge.cost >= best_cost:
                continue
            path = selected_path((edge,), start, world, world.counters, deadline)
            if admit_proposal is not None and not admit_proposal(path, deadline):
                continue
            if best is None:
                comparing = world.pressure > 0 and any(
                    world.history.get(cell, 0.0) > 0 for cell in islice(path, 1, None)
                )
            best, best_cost = path, edge.cost
            if not comparing:
                return best
    except Deadline:
        if best is None:
            raise
    return best


def _candidate_edges(
    world: GeometricWorld,
    starts: Sequence[Cell],
    goals: Collection[Cell],
    bounds: Box,
    deadline: float | None,
    *,
    blocked: Collection[Cell] = (),
    screen: FlatScreen | None = None,
) -> Iterator[tuple[MacroEdge, Cell]]:
    """Enumerate geometrically admitted constructions within the query slice."""
    if screen is None:
        from flab2bp.layout.geometric_world import FlatScreen

        screen = FlatScreen(blocked, deadline, world)
    else:
        screen.reset(blocked, deadline)
    counters = world.counters
    clear: dict[Cell, bool] = {}
    launches: dict[tuple[Cell, int], _Legs] = {}
    landings: dict[tuple[Cell, int], _Legs] = {}
    landing_first = len(goals) < len(starts)
    flat_screen = screen

    def pair_edges(start: Cell, goal: Cell) -> Iterator[MacroEdge | None]:
        check_deadline(deadline)
        for cell in (start, goal):
            if cell not in clear:
                clear[cell] = world.source_clear(cell) and world.source_geometry_clear(
                    cell, deadline
                )
        if not clear[start] or not clear[goal]:
            return
        for construction in flat_templates(start, goal):
            if flat_screen.rejects(start, construction, bounds):
                yield None
                continue
            edge = evaluate(
                State(start), construction, world, bounds, counters, deadline, root=start
            )
            yield edge
        minimum = max(start[2], goal[2]) + int(start[2] == goal[2])
        streams: deque[Iterator[tuple[MacroEdge, MacroEdge] | None]] = deque()
        for height in range(minimum, world.canvas.levels):
            check_deadline(deadline)
            launch_key, landing_key = (start, height), (goal, height)
            if launch_key not in launches:
                launches[launch_key] = _Legs(
                    _approaches(world, start, height, bounds, deadline, reverse=False)
                )
            if landing_key not in landings:
                landings[landing_key] = _Legs(
                    _approaches(world, goal, height, bounds, deadline, reverse=True)
                )
            first, second = launches[launch_key], landings[landing_key]
            if landing_first:
                first, second = second, first
            streams.append(_leg_pairs(first, second))
        # A low plane with many admissible but obstructed approaches must not
        # consume the entire query before a higher plane gets one bridge trial.
        while streams:
            check_deadline(deadline)
            stream = streams.popleft()
            try:
                pair = next(stream)
            except StopIteration:
                continue
            streams.append(stream)
            if pair is None:
                yield None
                continue
            a, b = pair
            launch, landing = (b, a) if landing_first else (a, b)
            launch_end = launch.end.cell
            landing_start = landing.start.cell
            for bridge in flat_templates(launch_end, landing_start):
                construction = (
                    *launch.construction,
                    *bridge,
                    *landing.construction,
                )
                if flat_screen.rejects(start, construction, bounds):
                    yield None
                    continue
                edge = evaluate(
                    State(start), construction, world, bounds, counters, deadline, root=start
                )
                yield edge

    pairs = iter(endpoint_pairs(starts, goals, deadline))
    active: deque[tuple[Cell, Iterator[MacroEdge | None]]] = deque()
    more_pairs = True
    while more_pairs or active:
        check_deadline(deadline)
        if more_pairs:
            pair = next(pairs, None)
            if pair is None:
                more_pairs = False
            else:
                start, goal = pair
                active.append((start, pair_edges(start, goal)))
        # Admit one new endpoint pair per wave, then advance every live pair
        # once. Rejected constructions yield too: an obstructed nearest pair
        # must not exhaust its approach combinations before another can start.
        for _ in range(len(active)):
            start, candidates = active.popleft()
            try:
                edge = next(candidates)
            except StopIteration:
                continue
            active.append((start, candidates))
            if edge is not None:
                yield edge, start
