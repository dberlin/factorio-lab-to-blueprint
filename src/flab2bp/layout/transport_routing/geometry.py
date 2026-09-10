"""Exact, demand-driven raw-primitive conflict families; no global pair join."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .budget import WorkBudget
from .paths import (
    Cell,
    Domain,
    FixedPath,
    _adapter,
    _intersection,
    _middle,
    _owned,
    _Segment,
    _segment,
)

type Rectangle = tuple[int, int, int, int]


@dataclass(frozen=True, slots=True)
class Primitive:
    kind: Literal["G", "M", "R"]
    lo: Cell
    hi: Cell
    endpoint_z: int = 0

    def at(self, height: int, budget: WorkBudget) -> _Segment:
        budget.charge("predicates")
        if self.kind == "G":
            return _Segment(self.lo, self.hi)
        if self.kind == "M":
            return _Segment((*self.lo[:2], height), (*self.hi[:2], height))
        return _Segment(
            (*self.lo[:2], min(self.endpoint_z, height)),
            (*self.lo[:2], max(self.endpoint_z, height)),
        )


@dataclass(frozen=True, slots=True)
class Family:
    left_mask: int
    right_mask: int
    rectangles: tuple[Rectangle, ...]


def _bound(levels: tuple[int, ...], value: int, inclusive: bool, budget: WorkBudget) -> int:
    lo, hi = 0, len(levels)
    while lo < hi:
        budget.charge("predicates")
        mid = (lo + hi) // 2
        if levels[mid] < value or (inclusive and levels[mid] == value):
            lo = mid + 1
        else:
            hi = mid
    return lo


def _forbidden(a: _Segment, b: _Segment, owners: frozenset[Cell], budget: WorkBudget) -> bool:
    overlap = _intersection(a, b, budget)
    return overlap is not None and not (overlap.lo == overlap.hi and overlap.lo in owners)


def _middle_relation(
    a: Primitive,
    b: Primitive,
    left_levels: tuple[int, ...],
    right_levels: tuple[int, ...],
    owners: frozenset[Cell],
    budget: WorkBudget,
) -> tuple[Rectangle, ...]:
    # Two middle segments can meet only at equal heights. Their planar overlap
    # is invariant, so intersect once and merge the sorted height sequences.
    overlap = _intersection(a.at(0, budget), b.at(0, budget), budget)
    if overlap is None:
        return ()
    singleton = overlap.lo == overlap.hi
    rectangles: list[Rectangle] = []
    p = q = 0
    while p < len(left_levels) and q < len(right_levels):
        budget.charge("predicates")
        left_height, right_height = left_levels[p], right_levels[q]
        if left_height < right_height:
            p += 1
        elif left_height > right_height:
            q += 1
        else:
            budget.charge("predicates")
            if not singleton or (overlap.lo[0], overlap.lo[1], left_height) not in owners:
                budget.charge("predicates")
                rectangles.append((p, p, q, q))
            p += 1
            q += 1
    budget.charge("predicates", len(rectangles))
    return tuple(rectangles)


def _fixed_right_relation(
    a: Primitive,
    b: Primitive,
    left_levels: tuple[int, ...],
    right_levels: tuple[int, ...],
    owners: frozenset[Cell],
    budget: WorkBudget,
) -> tuple[Rectangle, ...]:
    # Every column has the same fixed segment. Only transitions between
    # forbidden and permitted left rows can start or end a rectangle.
    bound = b.at(right_levels[0], budget)
    rectangles: list[Rectangle] = []
    first_row: int | None = None
    for p in range(1 if a.kind == "G" else len(left_levels)):
        forbidden = _forbidden(a.at(left_levels[p], budget), bound, owners, budget)
        budget.charge("predicates")
        if forbidden:
            if first_row is None:
                first_row = p
        elif first_row is not None:
            budget.charge("predicates")
            rectangles.append((first_row, p - 1, 0, len(right_levels) - 1))
            first_row = None
    if first_row is not None:
        budget.charge("predicates")
        rectangles.append((first_row, len(left_levels) - 1, 0, len(right_levels) - 1))
    budget.charge("predicates", len(rectangles))
    return tuple(rectangles)


def relation(
    a: Primitive,
    b: Primitive,
    left_levels: tuple[int, ...],
    right_levels: tuple[int, ...],
    owners: frozenset[Cell],
    budget: WorkBudget,
) -> tuple[Rectangle, ...]:
    """Construct exact canonical rectangles without a height-pair table."""
    budget.charge("predicates")
    if not left_levels or not right_levels:
        return ()
    if a.kind == "M" and b.kind == "M":
        return _middle_relation(a, b, left_levels, right_levels, owners, budget)
    if b.kind == "G":
        return _fixed_right_relation(a, b, left_levels, right_levels, owners, budget)
    rectangles: list[Rectangle] = []
    previous: tuple[tuple[int, int], ...] = ()
    first_row = 0
    # A fixed left segment has one invariant row; compile it only once.
    for p in range(1 if a.kind == "G" else len(left_levels)):
        height = left_levels[p]
        bound = a.at(height, budget)
        constants = {bound.lo[2], bound.hi[2], b.endpoint_z if b.kind == "R" else b.lo[2]}
        constants.update(cell[2] for cell in owners)
        budget.charge("predicates", len(constants) + len(owners))
        boundaries = {0, len(right_levels)}
        for value in constants:
            boundaries.add(_bound(right_levels, value, False, budget))
            boundaries.add(_bound(right_levels, value, True, budget))
        budget.charge("predicates", len(boundaries) * max(1, len(boundaries).bit_length()))
        ordered = sorted(boundaries)
        runs: list[tuple[int, int]] = []
        for lo, end in zip(ordered, ordered[1:], strict=False):
            budget.charge("predicates")
            if _forbidden(bound, b.at(right_levels[lo], budget), owners, budget):
                if runs and runs[-1][1] + 1 == lo:
                    runs[-1] = runs[-1][0], end - 1
                else:
                    runs.append((lo, end - 1))
        row = tuple(runs)
        budget.charge("predicates", 1 + len(row) + len(previous))
        if p and row != previous:
            rectangles.extend((first_row, p - 1, lo, hi) for lo, hi in previous)
            first_row = p
        previous = row
    rectangles.extend((first_row, len(left_levels) - 1, lo, hi) for lo, hi in previous)
    budget.charge("predicates", len(rectangles))
    return tuple(rectangles)


class PrimitiveIndex:
    def __init__(self, domain: Domain, budget: WorkBudget) -> None:
        self.domain = domain
        self.representative = FixedPath(
            (), domain.obligation.source, domain.obligation.sink, domain.obligation.item
        )
        self.primitives: list[Primitive] = []
        self.masks: list[int] = []
        self.combos: list[tuple[int, ...]] = []
        interned: dict[Primitive, int] = {}
        self.occurrences = 0
        shape_count = len(domain.shapes)
        row_width = 5 * shape_count
        words = max(1, (len(domain.lengths) + 63) // 64)
        budget.charge("predicates", 4 * words)
        row_mask = (1 << row_width) - 1
        shape_mask = (1 << shape_count) - 1
        sink_mask = 0
        for sa in range(5):
            budget.charge("predicates", 2 * words)
            sink_mask |= shape_mask << (sa * row_width)

        def intern(primitive: Primitive, mask: int) -> int:
            budget.charge("predicates", 2)
            pid = interned.get(primitive)
            if pid is None:
                pid = len(self.primitives)
                interned[primitive] = pid
                self.primitives.append(primitive)
                self.masks.append(0)
            width = max(mask.bit_length(), self.masks[pid].bit_length())
            budget.charge("predicates", max(1, (width + 63) // 64))
            self.masks[pid] |= mask
            return pid

        def adapter(side: int, index: int, mask: int) -> tuple[Cell, tuple[int, ...]]:
            endpoint = domain.obligation.source if side == 0 else domain.obligation.sink
            points = _adapter(endpoint, index)
            ids: list[int] = []
            for a, b in zip(points, points[1:], strict=False):
                segment = _segment(a, b)
                ids.append(intern(Primitive("G", segment.lo, segment.hi), mask))
            column = (*points[-1][:2], 0)
            ids.append(intern(Primitive("R", column, column, points[-1][2]), mask))
            return column, tuple(ids)

        # Intern lazily in the original source/sink/shape traversal order.
        # Adapter masks cover all their combinations; middle masks stay per-combo.
        sinks: dict[int, tuple[Cell, tuple[int, ...]]] = {}
        for sa in range(5):
            budget.charge("predicates", words)
            start, source_ids = adapter(0, sa, row_mask << (sa * row_width))
            for ta in range(5):
                budget.charge("predicates")
                sink = sinks.get(ta)
                if sink is None:
                    budget.charge("predicates", words)
                    sink = adapter(1, ta, sink_mask << (ta * shape_count))
                    sinks[ta] = sink
                finish, sink_ids = sink
                budget.charge("predicates", len(source_ids))
                prefix = list(source_ids)
                for pid in sink_ids:
                    budget.charge("predicates", 1 + len(prefix))
                    if pid not in prefix:
                        prefix.append(pid)
                for shape in domain.shapes:
                    budget.charge("predicates", 1 + len(prefix))
                    combo = len(self.combos)
                    ids = list(prefix)
                    self.occurrences += len(source_ids) + len(sink_ids)
                    bit = 1 << combo
                    middle = _middle(start, finish, shape)
                    for a, b in zip(middle, middle[1:], strict=False):
                        segment = _segment(a, b)
                        pid = intern(Primitive("M", segment.lo, segment.hi), bit)
                        self.occurrences += 1
                        if pid not in ids:
                            ids.append(pid)
                    self.combos.append(tuple(ids))

    def owners(self, other: PrimitiveIndex, budget: WorkBudget) -> frozenset[Cell]:
        result: set[Cell] = set()
        for endpoint in (self.representative.source, self.representative.sink):
            budget.charge("predicates")
            if _owned(self.representative, other.representative, endpoint.cell, budget):
                result.add(endpoint.cell)
        return frozenset(result)

    def witness(
        self,
        other: PrimitiveIndex,
        ca: int,
        cb: int,
        p: int,
        q: int,
        owners: frozenset[Cell],
        budget: WorkBudget,
    ) -> tuple[int, int] | None:
        left = [
            (pid, self.primitives[pid].at(self.domain.levels[p], budget)) for pid in self.combos[ca]
        ]
        right = [
            (pid, other.primitives[pid].at(other.domain.levels[q], budget))
            for pid in other.combos[cb]
        ]
        for ai, a in left:
            for bi, b in right:
                if _forbidden(a, b, owners, budget):
                    return ai, bi
        return None

    def incompatible(
        self, other: PrimitiveIndex, ca: int, cb: int, p: int, q: int, budget: WorkBudget
    ) -> bool:
        return self.witness(other, ca, cb, p, q, self.owners(other, budget), budget) is not None

    def family(
        self, other: PrimitiveIndex, ca: int, cb: int, p: int, q: int, budget: WorkBudget
    ) -> Family:
        owners = self.owners(other, budget)
        witness = self.witness(other, ca, cb, p, q, owners, budget)
        if witness is None:
            raise AssertionError("canonical forbidden pair has no raw primitive provenance")
        a, b = witness
        rectangles = relation(
            self.primitives[a],
            other.primitives[b],
            self.domain.levels,
            other.domain.levels,
            owners,
            budget,
        )
        if not any(lo <= p <= hi and start <= q <= end for lo, hi, start, end in rectangles):
            raise AssertionError("primitive family does not exclude its current witness")
        return Family(self.masks[a], other.masks[b], rectangles)
