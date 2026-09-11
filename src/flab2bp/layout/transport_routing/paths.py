"""Bounded complete-path templates; no grid routing or physical service claim.

``blocked`` must already contain the interface planner's catalog reservations.
The interval test is an exact lattice-centreline test, not a paste-clearance
proof. Only the independent emitted/decoded audit can discharge that obligation.
"""

from __future__ import annotations

import heapq
from collections.abc import Iterator
from dataclasses import dataclass
from fractions import Fraction

from .budget import TransportRefusal, WorkBudget

Cell = tuple[int, int, int]

Direction = tuple[int, int]

_DIRECTIONS = frozenset(((1, 0), (-1, 0), (0, 1), (0, -1)))


@dataclass(frozen=True, slots=True)
class Endpoint:
    cell: Cell
    outward: Direction
    port_id: int
    junction_id: int | None = None


@dataclass(frozen=True, slots=True)
class Obligation:
    ordinal: int
    item: str
    rate: Fraction
    source: Endpoint
    sink: Endpoint


@dataclass(frozen=True, slots=True)
class FixedPath:
    points: tuple[Cell, ...]
    source: Endpoint
    sink: Endpoint
    item: str


@dataclass(frozen=True, slots=True)
class TemplateProblem:
    obligations: tuple[Obligation, ...]
    blocked: frozenset[Cell]
    fixed_paths: tuple[FixedPath, ...]
    x_tracks: tuple[int, ...]
    y_tracks: tuple[int, ...]
    levels: tuple[int, ...]
    # Compiler-verified actual attachment records, never inferred from coordinates.
    owned_endpoints: tuple[Endpoint, ...] = ()


@dataclass(frozen=True, slots=True)
class _Segment:
    lo: Cell
    hi: Cell


def _segment(a: Cell, b: Cell) -> _Segment:
    return _Segment(
        (min(a[0], b[0]), min(a[1], b[1]), min(a[2], b[2])),
        (max(a[0], b[0]), max(a[1], b[1]), max(a[2], b[2])),
    )


def _intersection(a: _Segment, b: _Segment, budget: WorkBudget) -> _Segment | None:
    budget.charge("predicates")
    low_x, high_x = max(a.lo[0], b.lo[0]), min(a.hi[0], b.hi[0])
    if low_x > high_x:
        return None
    low_y, high_y = max(a.lo[1], b.lo[1]), min(a.hi[1], b.hi[1])
    if low_y > high_y:
        return None
    low_z, high_z = max(a.lo[2], b.lo[2]), min(a.hi[2], b.hi[2])
    if low_z > high_z:
        return None
    return _Segment((low_x, low_y, low_z), (high_x, high_y, high_z))


def _normal(points: tuple[Cell, ...], budget: WorkBudget) -> tuple[Cell, ...]:
    result: list[Cell] = []
    for p in points:
        budget.check()
        if result and p == result[-1]:
            continue
        if result and sum(a != b for a, b in zip(result[-1], p, strict=True)) != 1:
            raise ValueError(f"non-orthogonal segment {result[-1]} -> {p}")
        if len(result) >= 2:
            a, b = result[-2:]
            # Merge only continuation, never erase a reversal/retrace.
            if (
                all((b[i] - a[i]) * (p[i] - b[i]) >= 0 for i in range(3))
                and sum(a[i] != p[i] for i in range(3)) == 1
            ):
                result[-1] = p
                continue
        result.append(p)
    return tuple(result)


@dataclass(frozen=True, slots=True)
class _Geometry:
    path: FixedPath
    segments: tuple[_Segment, ...]
    bounds: _Segment | None


def _geometry(path: FixedPath, budget: WorkBudget) -> _Geometry:
    points = _normal(path.points, budget)
    normalized = FixedPath(points, path.source, path.sink, path.item)
    bounds = None
    if points:
        lo, hi = list(points[0]), list(points[0])
        for i in range(1, len(points)):
            budget.check()
            point = points[i]
            for axis in range(3):
                lo[axis], hi[axis] = min(lo[axis], point[axis]), max(hi[axis], point[axis])
        bounds = _Segment((lo[0], lo[1], lo[2]), (hi[0], hi[1], hi[2]))
    return _Geometry(
        normalized,
        tuple(_segment(a, b) for a, b in zip(points, points[1:], strict=False)),
        bounds,
    )


def _path_error(g: _Geometry, budget: WorkBudget) -> str | None:
    p = g.path
    if len(p.points) < 2 or p.points[0] != p.source.cell or p.points[-1] != p.sink.cell:
        return "path does not connect two declared endpoints"
    if p.source.outward not in _DIRECTIONS or p.sink.outward not in _DIRECTIONS:
        return "non-cardinal endpoint orientation"
    for endpoint, near in ((p.source, p.points[1]), (p.sink, p.points[-2])):
        budget.check()
        delta = tuple(near[i] - endpoint.cell[i] for i in range(3))
        if delta[2] != 0 or delta[0] * endpoint.outward[0] + delta[1] * endpoint.outward[1] <= 0:
            return f"incorrect approach at port {endpoint.port_id}"
    if p.source.port_id == p.sink.port_id:
        return f"path reuses port {p.source.port_id}"
    for i, first in enumerate(g.segments):
        for j in range(i + 1, len(g.segments)):
            overlap = _intersection(first, g.segments[j], budget)
            if overlap is None:
                continue
            if j == i + 1 and overlap.lo == overlap.hi == p.points[j]:
                continue
            return f"self-intersection/retrace at {overlap.lo}"
    return None


def _owned(a: FixedPath, b: FixedPath, cell: Cell, budget: WorkBudget) -> bool:
    if a.item != b.item:
        return False
    for ea, source_a in ((a.source, True), (a.sink, False)):
        for eb, source_b in ((b.source, True), (b.sink, False)):
            budget.charge("predicates")
            if ea.cell != cell or eb.cell != cell:
                continue
            if ea.port_id == eb.port_id:
                if source_a != source_b and ea.outward == (-eb.outward[0], -eb.outward[1]):
                    return True
            elif (
                ea.junction_id is not None
                and ea.junction_id == eb.junction_id
                and ea.outward != eb.outward
            ):
                # The interface planner explicitly declares these colocated
                # stubs as distinct cardinal slots of this actual junction.
                return True
    return False


def _compatible(a: _Geometry, b: _Geometry, budget: WorkBudget) -> bool:
    # Port IDs are physical identities even if contradictory input poses differ.
    for ea in (a.path.source, a.path.sink):
        for eb in (b.path.source, b.path.sink):
            budget.charge("predicates")
            if ea.port_id == eb.port_id and (
                ea.cell != eb.cell or not _owned(a.path, b.path, ea.cell, budget)
            ):
                return False
    for first in a.segments:
        for second in b.segments:
            overlap = _intersection(first, second, budget)
            if overlap is not None and not (
                overlap.lo == overlap.hi and _owned(a.path, b.path, overlap.lo, budget)
            ):
                return False
    return True


def compatible(first: FixedPath, second: FixedPath, budget: WorkBudget) -> bool:
    """Conservative complete-path compatibility, including exact incidence."""
    budget.check()
    try:
        a, b = _geometry(first, budget), _geometry(second, budget)
    except ValueError:
        return False
    return (
        _path_error(a, budget) is None
        and _path_error(b, budget) is None
        and _compatible(a, b, budget)
    )


def _adapter(endpoint: Endpoint, adapter: int) -> tuple[Cell, ...]:
    x, y, z = endpoint.cell
    dx, dy = endpoint.outward
    distance = (2, 4, 6, 2, 2)[adapter]
    corner = (x + distance * dx, y + distance * dy, z)
    if adapter < 3:
        return (endpoint.cell, corner)
    side = 2 if adapter == 3 else -2
    return (endpoint.cell, corner, (corner[0] - side * dy, corner[1] + side * dx, z))


def _middle(a: Cell, b: Cell, shape: tuple[int, int]) -> tuple[Cell, ...]:
    kind, track = shape
    if kind == 0:
        return (a, (b[0], a[1], a[2]), b)
    if kind == 1:
        return (a, (a[0], b[1], a[2]), b)
    if kind == 2:
        return (a, (track, a[1], a[2]), (track, b[1], a[2]), b)
    return (a, (a[0], track, a[2]), (b[0], track, a[2]), b)


@dataclass(frozen=True, slots=True)
class Domain:
    obligation: Obligation
    levels: tuple[int, ...]
    shapes: tuple[tuple[int, int], ...]
    # One small integer per XY combination; no per-level path materialization.
    lengths: tuple[int, ...]
    level_order: tuple[int, ...]

    @property
    def count(self) -> int:
        return len(self.lengths) * len(self.levels)

    def _key(self, combo: int, level_index: int) -> tuple[int, int, int, int, int, int]:
        sa, rest = divmod(combo, 5 * len(self.shapes))
        ta, shape = divmod(rest, len(self.shapes))
        z = self.levels[level_index]
        az, bz = self.obligation.source.cell[2], self.obligation.sink.cell[2]
        return (self.lengths[combo] + abs(z - az) + abs(z - bz), max(z, az, bz), sa, ta, shape, z)

    def _ids(self, budget: WorkBudget) -> Iterator[int]:
        if not self.level_order:
            return
        heap: list[tuple[tuple[int, int, int, int, int, int], int, int]] = []
        for combo in range(len(self.lengths)):
            budget.check()
            heapq.heappush(heap, (self._key(combo, self.level_order[0]), combo, 0))
        while heap:
            budget.check()
            _, combo, rank = heapq.heappop(heap)
            yield combo * len(self.levels) + self.level_order[rank]
            rank += 1
            if rank < len(self.level_order):
                heapq.heappush(heap, (self._key(combo, self.level_order[rank]), combo, rank))

    def _decode(self, candidate_id: int, budget: WorkBudget) -> _Geometry:
        budget.charge("candidates")
        combo, zi = divmod(candidate_id, len(self.levels))
        sa, rest = divmod(combo, 5 * len(self.shapes))
        ta, shape = divmod(rest, len(self.shapes))
        start, finish = _adapter(self.obligation.source, sa), _adapter(self.obligation.sink, ta)
        z = self.levels[zi]
        a, b = (*start[-1][:2], z), (*finish[-1][:2], z)
        points = start + _middle(a, b, self.shapes[shape]) + tuple(reversed(finish))
        return _geometry(
            FixedPath(points, self.obligation.source, self.obligation.sink, self.obligation.item),
            budget,
        )


def domains(problem: TemplateProblem, budget: WorkBudget) -> tuple[Domain, ...]:
    """Exact Cartesian domains before deduplication/static filtering; no search."""
    budget.check()
    levels = tuple(sorted(set(problem.levels)))
    if any(z < 3 for z in levels):
        raise TransportRefusal(
            "UNSUPPORTED_INTERFACE", "global levels must be supplied legal levels >= 3"
        )
    seen: set[int] = set()
    result: list[Domain] = []
    for obligation in sorted(problem.obligations, key=lambda o: o.ordinal):
        budget.check()
        if obligation.ordinal in seen:
            raise TransportRefusal(
                "UNSUPPORTED_INTERFACE", f"duplicate obligation ordinal {obligation.ordinal}"
            )
        seen.add(obligation.ordinal)
        if obligation.rate <= 0:
            raise TransportRefusal(
                "UNSUPPORTED_INTERFACE", f"nonpositive rate at obligation {obligation.ordinal}"
            )
        if any(e.outward not in _DIRECTIONS for e in (obligation.source, obligation.sink)):
            raise TransportRefusal(
                "UNSUPPORTED_INTERFACE", f"non-cardinal endpoint at obligation {obligation.ordinal}"
            )
        chosen: list[tuple[int, ...]] = []
        for axis, tracks in enumerate((problem.x_tracks, problem.y_tracks)):
            a, b = obligation.source.cell[axis], obligation.sink.cell[axis]
            # Keep exactly the registered four nearest lines, once per obligation.
            ordered: list[tuple[int, int]] = []
            for coordinate in set(tracks):
                budget.check()
                ordered.append((abs(a - coordinate) + abs(b - coordinate) - abs(a - b), coordinate))
            chosen.append(tuple(c for _, c in heapq.nsmallest(4, ordered)))
        shapes = (
            ((0, 0), (1, 0)) + tuple((2, x) for x in chosen[0]) + tuple((3, y) for y in chosen[1])
        )
        lengths: list[int] = []
        for sa in range(5):
            for ta in range(5):
                start, finish = _adapter(obligation.source, sa), _adapter(obligation.sink, ta)
                a, b = (*start[-1][:2], 0), (*finish[-1][:2], 0)
                adapter_length = (2, 4, 6, 4, 4)[sa] + (2, 4, 6, 4, 4)[ta]
                for shape in shapes:
                    budget.check()
                    middle = _middle(a, b, shape)
                    lengths.append(
                        adapter_length
                        + sum(
                            abs(p[0] - q[0]) + abs(p[1] - q[1])
                            for p, q in zip(middle, middle[1:], strict=False)
                        )
                    )
        az, bz = obligation.source.cell[2], obligation.sink.cell[2]
        level_order = tuple(
            sorted(
                range(len(levels)),
                key=lambda i: (
                    abs(levels[i] - az) + abs(levels[i] - bz),
                    max(levels[i], az, bz),
                    levels[i],
                ),
            )
        )
        result.append(Domain(obligation, levels, shapes, tuple(lengths), level_order))
    return tuple(result)


@dataclass(frozen=True, slots=True)
class _Obstacle:
    segment: _Segment
    owner: int | None


@dataclass(frozen=True, slots=True)
class _Node:
    bounds: _Segment
    left: int
    right: int
    obstacle: int


class _FixedIndex:
    """Balanced AABB index of compact body runs and immutable local segments."""

    def __init__(self, problem: TemplateProblem, budget: WorkBudget) -> None:
        self.fixed: list[_Geometry] = []
        self.obstacles: list[_Obstacle] = []
        self.nodes: list[_Node] = []
        self.ports: dict[int, list[int]] = {}
        self.owned_endpoints: frozenset[Endpoint] = frozenset(problem.owned_endpoints)
        rows: dict[tuple[int, int], list[int]] = {}
        for x, y, z in problem.blocked:
            budget.check()
            rows.setdefault((y, z), []).append(x)
        for (y, z), xs in sorted(rows.items()):
            budget.check()
            xs.sort()
            lo = hi = xs[0]
            for x in xs[1:]:
                budget.check()
                if x == hi + 1:
                    hi = x
                else:
                    self.obstacles.append(_Obstacle(_Segment((lo, y, z), (hi, y, z)), None))
                    lo = hi = x
            self.obstacles.append(_Obstacle(_Segment((lo, y, z), (hi, y, z)), None))
        for path in problem.fixed_paths:
            budget.check()
            try:
                g = _geometry(path, budget)
            except ValueError as exc:
                raise TransportRefusal("PHYSICAL_ACCESS_CONFLICT", str(exc)) from exc
            error = _path_error(g, budget)
            if error:
                raise TransportRefusal(
                    "PHYSICAL_ACCESS_CONFLICT", f"fixed port {path.source.port_id}: {error}"
                )
            owner = len(self.fixed)
            self.fixed.append(g)
            for endpoint in (path.source, path.sink):
                self.ports.setdefault(endpoint.port_id, []).append(owner)
            self.obstacles.extend(_Obstacle(s, owner) for s in g.segments)
        self.root: int = self._build(list(range(len(self.obstacles))), budget)
        # Refuse inconsistent fixed geometry even if no global candidate visits it.
        for owner, geometry in enumerate(self.fixed):
            error = self.error(geometry, budget, ignore_owner=owner)
            if error:
                raise TransportRefusal("PHYSICAL_ACCESS_CONFLICT", f"fixed path {owner}: {error}")

    def _build(self, ids: list[int], budget: WorkBudget) -> int:
        budget.check()
        if not ids:
            return -1
        lo = list(self.obstacles[ids[0]].segment.lo)
        hi = list(self.obstacles[ids[0]].segment.hi)
        for i in ids[1:]:
            budget.check()
            s = self.obstacles[i].segment
            for axis in range(3):
                lo[axis], hi[axis] = min(lo[axis], s.lo[axis]), max(hi[axis], s.hi[axis])
        bounds = _Segment((lo[0], lo[1], lo[2]), (hi[0], hi[1], hi[2]))
        if len(ids) == 1:
            self.nodes.append(_Node(bounds, -1, -1, ids[0]))
        else:
            axis = max(range(3), key=lambda a: hi[a] - lo[a])
            ids.sort(
                key=lambda i: (
                    self.obstacles[i].segment.lo[axis] + self.obstacles[i].segment.hi[axis]
                )
            )
            middle = len(ids) // 2
            left, right = self._build(ids[:middle], budget), self._build(ids[middle:], budget)
            self.nodes.append(_Node(bounds, left, right, -1))
        return len(self.nodes) - 1

    def _hits(self, segment: _Segment, budget: WorkBudget) -> Iterator[tuple[_Obstacle, _Segment]]:
        stack = [self.root] if self.root >= 0 else []
        while stack:
            budget.check()
            node = self.nodes[stack.pop()]
            if node.obstacle >= 0:
                overlap = _intersection(segment, node.bounds, budget)
                if overlap is not None:
                    yield self.obstacles[node.obstacle], overlap
            else:
                # Internal nodes need only a disjointness test, not an
                # allocated intersection; preserve one predicate per visit.
                budget.charge("predicates")
                lo, hi = segment.lo, segment.hi
                bounds_lo, bounds_hi = node.bounds.lo, node.bounds.hi
                if (
                    lo[0] > bounds_hi[0]
                    or hi[0] < bounds_lo[0]
                    or lo[1] > bounds_hi[1]
                    or hi[1] < bounds_lo[1]
                    or lo[2] > bounds_hi[2]
                    or hi[2] < bounds_lo[2]
                ):
                    continue
                stack.append(node.right)
                stack.append(node.left)

    def error(
        self, geometry: _Geometry, budget: WorkBudget, *, ignore_owner: int | None = None
    ) -> str | None:
        for endpoint in (geometry.path.source, geometry.path.sink):
            for owner in self.ports.get(endpoint.port_id, ()):
                budget.check()
                if owner == ignore_owner:
                    continue
                if not _owned(geometry.path, self.fixed[owner].path, endpoint.cell, budget):
                    return f"duplicate/inconsistent physical port {endpoint.port_id}"
        if (
            self.root >= 0
            and geometry.bounds is not None
            and _intersection(geometry.bounds, self.nodes[self.root].bounds, budget) is None
        ):
            return None
        for segment in geometry.segments:
            for obstacle, overlap in self._hits(segment, budget):
                if obstacle.owner is None:
                    budget.charge("predicates")
                    endpoints = tuple(
                        endpoint.cell
                        for endpoint in (geometry.path.source, geometry.path.sink)
                        if endpoint in self.owned_endpoints
                    )
                    # Neither coordinates nor path endpoint status establish
                    # ownership: require the compiler's exact attachment record.
                    if (
                        overlap.lo in endpoints
                        and overlap.hi in endpoints
                        and sum(overlap.hi[i] - overlap.lo[i] for i in range(3)) <= 1
                    ):
                        continue
                if obstacle.owner is not None and obstacle.owner == ignore_owner:
                    continue
                if (
                    obstacle.owner is not None
                    and overlap.lo == overlap.hi
                    and _owned(geometry.path, self.fixed[obstacle.owner].path, overlap.lo, budget)
                ):
                    continue
                owner = (
                    "body reservation" if obstacle.owner is None else f"fixed path {obstacle.owner}"
                )
                return f"{owner} collision at {overlap.lo}"
        return None
