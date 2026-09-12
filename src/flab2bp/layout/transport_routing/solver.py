"""Exact-domain SAT routing under the strategy supervisor."""

from __future__ import annotations

import time
from bisect import bisect_left, bisect_right, insort
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from itertools import combinations

from pysat.solvers import Cadical195

from .budget import TransportRefusal, WorkBudget
from .cnf import FactorCNF
from .geometry import PrimitiveIndex
from .paths import (
    Cell,
    Domain,
    FixedPath,
    TemplateProblem,
    _adapter,
    _compatible,
    _FixedIndex,
    _Geometry,
    _middle,
    _owned,
    _path_error,
    _Segment,
    domains,
)
from .repair import Neighborhood

MAXIMUM_ROUNDS = 2000

MAXIMUM_COLLISION_CUTS = 200000

MAXIMUM_CLAUSES = 20000000

CONFLICTS_PER_CALL = 1000

DECISIONS_PER_CALL = 10000


def cells(points: tuple[Cell, ...]) -> Iterator[Cell]:
    """Expand orthogonal segments; retain retraces but not consecutive duplicates."""
    yield points[0]
    for a, b in zip(points, points[1:], strict=False):
        axes = [axis for axis in range(3) if a[axis] != b[axis]]
        if not axes:
            continue
        if len(axes) != 1:
            raise ValueError("nonorthogonal template segment")
        axis = axes[0]
        step = 1 if a[axis] < b[axis] else -1
        for value in range(a[axis] + step, b[axis] + step, step):
            point = list(a)
            point[axis] = value
            yield point[0], point[1], point[2]


def members(mask: int) -> Iterator[int]:
    while mask:
        bit = mask & -mask
        yield bit.bit_length() - 1
        mask ^= bit


@dataclass(frozen=True)
class IntervalRow:
    coordinates: tuple[int, ...]
    masks: tuple[int, ...]
    _lookups: dict[int, int] = field(default_factory=dict, init=False, compare=False, repr=False)

    def occupants(self, coordinate: int, budget: WorkBudget) -> int:
        budget.check()
        cached = self._lookups.get(coordinate)
        if cached is not None:
            return cached
        lo, hi = 0, len(self.coordinates)
        while lo < hi:
            budget.charge("predicates")
            middle = (lo + hi) // 2
            if self.coordinates[middle] <= coordinate:
                lo = middle + 1
            else:
                hi = middle
        result = self.masks[lo - 1] if lo else 0
        self._lookups[coordinate] = result
        return result


class CellIndex:
    """Exact occupancy of every original ID, without materializing every height."""

    def __init__(self, domain: Domain, budget: WorkBudget) -> None:
        self.domain = domain
        self.middle: dict[tuple[int, int], IntervalRow] = {}
        events: dict[tuple[int, int], dict[int, int]] = {}
        self.ground: dict[Cell, int] = {}
        self.columns: dict[tuple[int, int], list[tuple[int, int]]] = {}
        self.level_indices = {z: i for i, z in enumerate(domain.levels)}
        levels = len(domain.levels)
        all_levels = (1 << levels) - 1
        source_masks = [0] * 5
        sink_masks = [0] * 5
        for combo in range(len(domain.lengths)):
            budget.check()
            source_adapter, rest = divmod(combo, 5 * len(domain.shapes))
            sink_adapter, shape = divmod(rest, len(domain.shapes))
            bit = 1 << (combo * levels)
            source_masks[source_adapter] |= bit
            sink_masks[sink_adapter] |= bit
            start = _adapter(domain.obligation.source, source_adapter)[-1]
            finish = _adapter(domain.obligation.sink, sink_adapter)[-1]
            points = _middle(
                (start[0], start[1], 0), (finish[0], finish[1], 0), domain.shapes[shape]
            )
            # Union one candidate's collinear intervals before XOR events:
            # overlapping/retraced segments must not cancel its occupancy bit.
            intervals: dict[tuple[int, int], list[tuple[int, int]]] = {}
            for a, b in zip(points, points[1:], strict=False):
                axis = 0 if a[1] == b[1] else 1
                key = axis, a[1 - axis]
                intervals.setdefault(key, []).append((min(a[axis], b[axis]), max(a[axis], b[axis])))
            for key, spans in intervals.items():
                row = events.setdefault(key, {})
                spans.sort()
                lo, hi = spans[0]
                for span_start, span_end in spans[1:]:
                    budget.charge("predicates")
                    if span_start <= hi + 1:
                        hi = max(hi, span_end)
                    else:
                        row[lo] = row.get(lo, 0) ^ bit
                        row[hi + 1] = row.get(hi + 1, 0) ^ bit
                        lo, hi = span_start, span_end
                budget.charge("predicates")
                row[lo] = row.get(lo, 0) ^ bit
                row[hi + 1] = row.get(hi + 1, 0) ^ bit
        for key, row in events.items():
            positions = tuple(sorted(row))
            active = 0
            masks: list[int] = []
            for coordinate in positions:
                budget.charge("predicates")
                active ^= row[coordinate]
                masks.append(active)
            assert active == 0
            self.middle[key] = IntervalRow(positions, tuple(masks))
        for endpoint, masks in (
            (domain.obligation.source, source_masks),
            (domain.obligation.sink, sink_masks),
        ):
            for adapter, mask in enumerate(masks):
                points = _adapter(endpoint, adapter)
                for cell in cells(points):
                    budget.charge("audit_cells")
                    self.ground[cell] = self.ground.get(cell, 0) | mask * all_levels
                tip = points[-1]
                self.columns.setdefault((tip[0], tip[1]), []).append((tip[2], mask))

    def occupants(self, cell: Cell, budget: WorkBudget) -> int:
        budget.charge("predicates", 2)
        result = self.ground.get(cell, 0)
        xy = cell[0], cell[1]
        level_index = self.level_indices.get(cell[2])
        if level_index is not None:
            for axis in range(2):
                budget.charge("predicates")
                row = self.middle.get((axis, cell[1 - axis]))
                if row is not None:
                    result |= row.occupants(cell[axis], budget) << level_index
        for endpoint_z, mask in self.columns.get(xy, ()):
            level_mask = 0
            for i, height in enumerate(self.domain.levels):
                budget.charge("predicates")
                if min(endpoint_z, height) <= cell[2] <= max(endpoint_z, height):
                    level_mask |= 1 << i
            result |= mask * level_mask
        return result


class DomainIndex:
    """Conservative domain candidates; exact CellIndex still decides occupancy."""

    def __init__(self, indexes: list[CellIndex], budget: WorkBudget) -> None:
        self.ground: dict[Cell, int] = {}
        self.columns: dict[tuple[int, int], int] = {}
        self.levels: dict[int, int] = {}
        self.middle: dict[tuple[int, int], IntervalRow] = {}
        events: dict[tuple[int, int], dict[int, int]] = {}
        for di, index in enumerate(indexes):
            bit = 1 << di
            for cell in index.ground:
                budget.charge("predicates")
                self.ground[cell] = self.ground.get(cell, 0) | bit
            for xy in index.columns:
                budget.charge("predicates")
                self.columns[xy] = self.columns.get(xy, 0) | bit
            for z in index.level_indices:
                budget.charge("predicates")
                self.levels[z] = self.levels.get(z, 0) | bit
            for key, row in index.middle.items():
                target = events.setdefault(key, {})
                occupied = False
                for coordinate, mask in zip(row.coordinates, row.masks, strict=True):
                    budget.charge("predicates")
                    if bool(mask) != occupied:
                        target[coordinate] = target.get(coordinate, 0) ^ bit
                        occupied = bool(mask)
                assert not occupied
        for key, row_events in events.items():
            coordinates = tuple(sorted(row_events))
            active = 0
            masks: list[int] = []
            for coordinate in coordinates:
                budget.charge("predicates")
                active ^= row_events[coordinate]
                masks.append(active)
            assert active == 0
            self.middle[key] = IntervalRow(coordinates, tuple(masks))

    def domains(self, cell: Cell, budget: WorkBudget) -> int:
        budget.charge("predicates", 3)
        result = self.ground.get(cell, 0) | self.columns.get(cell[:2], 0)
        levels = self.levels.get(cell[2], 0)
        if levels:
            for axis in range(2):
                budget.charge("predicates")
                row = self.middle.get((axis, cell[1 - axis]))
                if row is not None:
                    result |= row.occupants(cell[axis], budget) & levels
        return result


def entry_rejections(
    problem: TemplateProblem,
    indexes: list[CellIndex],
    fixed_cells: list[set[Cell]],
    budget: WorkBudget,
) -> list[int]:
    """Exclude only candidates whose actual ground adapter or riser is blocked."""
    fixed_at: dict[Cell, list[FixedPath]] = {}
    for path, occupied in zip(problem.fixed_paths, fixed_cells, strict=True):
        for cell in occupied:
            budget.charge("predicates")
            fixed_at.setdefault(cell, []).append(path)
    owned = frozenset(problem.owned_endpoints)
    result: list[int] = []

    def forbidden(cell: Cell, representative: FixedPath, owned_cells: set[Cell]) -> bool:
        budget.charge("predicates")
        if cell in problem.blocked and cell not in owned_cells:
            return True
        return any(
            not _owned(representative, path, cell, budget) for path in fixed_at.get(cell, ())
        )

    for index in indexes:
        obligation = index.domain.obligation
        representative = FixedPath((), obligation.source, obligation.sink, obligation.item)
        owned_cells = {
            endpoint.cell for endpoint in (obligation.source, obligation.sink) if endpoint in owned
        }

        rejected = 0
        for cell, mask in index.ground.items():
            if forbidden(cell, representative, owned_cells):
                rejected |= mask
        for (x, y), columns in index.columns.items():
            heights = (*index.domain.levels, *(z for z, _ in columns))
            blocked_heights = [
                z
                for z in range(min(heights), max(heights) + 1)
                if forbidden((x, y, z), representative, owned_cells)
            ]
            for endpoint_z, mask in columns:
                lower = upper = None
                for z in blocked_heights:
                    budget.charge("predicates")
                    if z <= endpoint_z:
                        lower = z
                    if z >= endpoint_z and upper is None:
                        upper = z
                level_mask = 0
                for ordinal, height in enumerate(index.domain.levels):
                    budget.charge("predicates")
                    if (lower is not None and height <= lower) or (
                        upper is not None and height >= upper
                    ):
                        level_mask |= 1 << ordinal
                rejected |= mask * level_mask
        result.append(rejected)
    return result


def exclude_static_middles(
    problem: TemplateProblem,
    indexes: list[CellIndex],
    domain_index: DomainIndex,
    fixed_cells: list[set[Cell]],
    rejected: list[int],
    budget: WorkBudget,
) -> None:
    """Extend exact entry exclusions with forbidden cells at legal middle heights."""
    levels = frozenset(problem.levels)
    budget.charge("predicates", len(problem.blocked))
    obstacles = {cell for cell in problem.blocked if cell[2] in levels}
    fixed_at: dict[Cell, list[FixedPath]] = {}
    for path, occupied in zip(problem.fixed_paths, fixed_cells, strict=True):
        for cell in occupied:
            budget.charge("predicates")
            if cell[2] in levels:
                obstacles.add(cell)
                fixed_at.setdefault(cell, []).append(path)
    owned = frozenset(problem.owned_endpoints)
    representatives = [
        FixedPath(
            (),
            index.domain.obligation.source,
            index.domain.obligation.sink,
            index.domain.obligation.item,
        )
        for index in indexes
    ]
    for cell in sorted(obstacles):
        for di in members(domain_index.domains(cell, budget)):
            mask = indexes[di].occupants(cell, budget)
            if not mask & ~rejected[di]:
                continue
            representative = representatives[di]
            body_collision = cell in problem.blocked and not any(
                endpoint.cell == cell and endpoint in owned
                for endpoint in (representative.source, representative.sink)
            )
            budget.charge("predicates")
            if body_collision or any(
                not _owned(representative, path, cell, budget) for path in fixed_at.get(cell, ())
            ):
                rejected[di] |= mask


@dataclass
class SolveStats:
    started: float = field(default_factory=time.monotonic)
    preparation_seconds: float = 0
    logical_candidates: int = 0
    primary_variables: int = 0
    auxiliary_variables: int = 0
    guard_variables: int = 0
    primitive_occurrences: int = 0
    primitive_descriptors: int = 0
    families: int = 0
    clauses: int = 0
    rounds: int = 0
    native_calls: int = 0
    solver_seconds: float = 0
    collision_cuts: int = 0
    static_cuts: int = 0
    entry_rejected_candidates: int = 0
    static_rejected_candidates: int = 0
    self_rejections: int = 0
    neighborhood_retained: int = 0
    neighborhood_releases: int = 0
    neighborhood_core_relaxations: int = 0
    last_conflict_pairs: int = 0
    best_conflict_pairs: int | None = None
    selected_candidate_ids: dict[int, int] = field(default_factory=dict)


def _identity_conflict(a: FixedPath, b: FixedPath, budget: WorkBudget) -> bool:
    for first in (a.source, a.sink):
        for second in (b.source, b.sink):
            budget.charge("predicates")
            if first.port_id == second.port_id and (
                first.cell != second.cell or not _owned(a, b, first.cell, budget)
            ):
                return True
    return False


def _overlapping_cells(
    left: set[Cell],
    right: set[Cell],
    left_off_level: set[Cell],
    right_off_level: set[Cell],
    *,
    same_level: bool,
) -> set[Cell]:
    if same_level:
        return left & right
    # Distinct horizontal levels cannot meet. Every contact must therefore
    # belong to at least one off-level subset, including all riser crossings.
    return (left_off_level & right) | (left & right_off_level)


_RUN_FIXED_AXES = ((1, 2), (0, 2), (0, 1))

type _RunLine = dict[tuple[int, int, int], int]


@dataclass(slots=True)
class _RunPlane:
    coordinates: list[int] = field(default_factory=list)
    lines: dict[int, _RunLine] = field(default_factory=dict)


class _SelectedRuns:
    """Exact selected-path contacts, indexed by orthogonal runs rather than cells."""

    def __init__(self, count: int) -> None:
        self.rows: list[dict[tuple[int, int], _RunLine]] = [{}, {}, {}]
        self.planes: list[tuple[dict[int, _RunPlane], dict[int, _RunPlane]]] = [
            ({}, {}) for _ in range(3)
        ]
        self.paths: list[tuple[_Segment, ...]] = [() for _ in range(count)]
        self.bits: tuple[int, ...] = tuple(1 << i for i in range(count))
        self.words: int = max(1, (count + 63) // 64)

    @staticmethod
    def _axis(segment: _Segment) -> int:
        if segment.lo[0] != segment.hi[0]:
            return 0
        return 1 if segment.lo[1] != segment.hi[1] else 2

    def _remove(self, segment: _Segment, owner: int, budget: WorkBudget) -> None:
        axis = self._axis(segment)
        b, c = _RUN_FIXED_AXES[axis]
        key = segment.lo[b], segment.lo[c]
        row = self.rows[axis][key]
        record = segment.lo[axis], segment.hi[axis], owner
        budget.charge("predicates", 7)
        count = row[record]
        if count > 1:
            row[record] = count - 1
            return
        del row[record]
        if row:
            return
        del self.rows[axis][key]
        for side in range(2):
            view = self.planes[axis][side]
            plane = view[key[side]]
            coordinate = key[1 - side]
            budget.charge(
                "predicates", 3 + len(plane.coordinates) + len(plane.coordinates).bit_length()
            )
            del plane.lines[coordinate]
            del plane.coordinates[bisect_left(plane.coordinates, coordinate)]
            if not plane.coordinates:
                del view[key[side]]

    def _insert(
        self,
        axis: int,
        key: tuple[int, int],
        low: int,
        high: int,
        owner: int,
        budget: WorkBudget,
    ) -> None:
        budget.charge("predicates", 5)
        row = self.rows[axis].get(key)
        if row is None:
            row = {}
            self.rows[axis][key] = row
            for side in range(2):
                view = self.planes[axis][side]
                plane = view.get(key[side])
                if plane is None:
                    plane = _RunPlane()
                    view[key[side]] = plane
                coordinate = key[1 - side]
                budget.charge(
                    "predicates", 3 + len(plane.coordinates) + len(plane.coordinates).bit_length()
                )
                insort(plane.coordinates, coordinate)
                plane.lines[coordinate] = row
        record = low, high, owner
        row[record] = row.get(record, 0) + 1

    def _partners(
        self, segment: _Segment, axis: int, key: tuple[int, int], budget: WorkBudget
    ) -> int:
        result = 0
        low, high = segment.lo[axis], segment.hi[axis]
        budget.charge("predicates", 3)
        row = self.rows[axis].get(key)
        if row is not None:
            for start, end, owner in row:
                budget.charge("predicates", 2)
                if start <= high and end >= low:
                    budget.charge("predicates", self.words)
                    result |= self.bits[owner]
        # Perpendicular runs share the remaining coordinate. Query only rows
        # within this run's interval, then test the other run's interval.
        for target in range(3):
            if target == axis:
                continue
            shared = 3 - axis - target
            side = 0 if _RUN_FIXED_AXES[target][0] == shared else 1
            budget.charge("predicates", 4)
            plane = self.planes[target][side].get(segment.lo[shared])
            if plane is None:
                continue
            coordinates = plane.coordinates
            budget.charge("predicates", 2 * len(coordinates).bit_length())
            begin, end = bisect_left(coordinates, low), bisect_right(coordinates, high)
            fixed = segment.lo[target]
            for offset in range(begin, end):
                budget.charge("predicates", 2)
                for start, finish, owner in plane.lines[coordinates[offset]]:
                    budget.charge("predicates", 2)
                    if start <= fixed <= finish:
                        budget.charge("predicates", self.words)
                        result |= self.bits[owner]
        return result

    def pairs(
        self, geometries: list[_Geometry], changed: list[bool], budget: WorkBudget
    ) -> Iterator[tuple[int, int]]:
        changed_indices = [i for i, moved in enumerate(changed) if moved]
        budget.charge("predicates", len(changed))
        for owner in changed_indices:
            for segment in self.paths[owner]:
                self._remove(segment, owner, budget)
            self.paths[owner] = geometries[owner].segments
        # Only unchanged and already inserted changed owners are visible, so
        # each changed/changed pair is visited once, by its later endpoint.
        for owner in changed_indices:
            partners = 0
            for segment in geometries[owner].segments:
                axis = self._axis(segment)
                b, c = _RUN_FIXED_AXES[axis]
                key = segment.lo[b], segment.lo[c]
                partners |= self._partners(segment, axis, key, budget)
                self._insert(axis, key, segment.lo[axis], segment.hi[axis], owner, budget)
            partners &= ~self.bits[owner]
            while partners:
                budget.charge("predicates", 1 + self.words)
                bit = partners & -partners
                other = bit.bit_length() - 1
                partners ^= bit
                yield (owner, other) if owner < other else (other, owner)


def select(
    problem: TemplateProblem,
    budget: WorkBudget,
    stats: SolveStats | None = None,
    checkpoint: Callable[[str], None] | None = None,
) -> dict[int, tuple[Cell, ...]]:
    """SAT is only a relaxation until every selected complete path is checked."""
    stats = stats if stats is not None else SolveStats()
    if checkpoint is not None:
        checkpoint("preparation")
    ds = domains(problem, budget)
    fixed_index = _FixedIndex(problem, budget)
    if not ds:
        return {}
    if any(d.count == 0 for d in ds):
        raise TransportRefusal("TEMPLATE_FAMILY_EXHAUSTED", "empty complete candidate domain")
    representatives = [
        FixedPath((), d.obligation.source, d.obligation.sink, d.obligation.item) for d in ds
    ]
    for a, b in combinations(representatives, 2):
        if _identity_conflict(a, b, budget):
            raise TransportRefusal(
                "TEMPLATE_FAMILY_EXHAUSTED", "inconsistent global port identities"
            )
    for a in representatives:
        for b in problem.fixed_paths:
            if _identity_conflict(a, b, budget):
                raise TransportRefusal(
                    "TEMPLATE_FAMILY_EXHAUSTED", "inconsistent fixed/global port identities"
                )
    indexes = [CellIndex(d, budget) for d in ds]
    domain_index = DomainIndex(indexes, budget)
    fixed_cells: list[set[Cell]] = []
    for path in problem.fixed_paths:
        expanded = set(cells(path.points))
        budget.charge("audit_cells", len(expanded))
        fixed_cells.append(expanded)
    for d in ds:
        budget.charge("candidates", d.count)
        stats.logical_candidates += d.count
    rejected_entries = entry_rejections(problem, indexes, fixed_cells, budget)
    stats.entry_rejected_candidates = sum(mask.bit_count() for mask in rejected_entries)
    exclude_static_middles(problem, indexes, domain_index, fixed_cells, rejected_entries, budget)
    stats.static_rejected_candidates = sum(mask.bit_count() for mask in rejected_entries)
    primitive_indexes = [PrimitiveIndex(d, budget) for d in ds]
    stats.primitive_occurrences = sum(index.occurrences for index in primitive_indexes)
    stats.primitive_descriptors = sum(len(index.primitives) for index in primitive_indexes)
    fixed_owners_by_cell: dict[Cell, list[int]] = {}
    for owner, occupied_cells in enumerate(fixed_cells):
        for cell in occupied_cells:
            budget.charge("predicates", 2)
            fixed_owners_by_cell.setdefault(cell, []).append(owner)
    budget.charge("predicates", len(fixed_owners_by_cell))
    fixed_occupied_cells = frozenset(fixed_owners_by_cell)
    static_cuts: set[tuple[int, Cell]] = set()
    validated_choices: dict[int, tuple[int, _Geometry, set[Cell], set[Cell]]] = {}
    # Keep compact static certificates when SAT revisits an earlier choice.
    # Expanded cell sets stay only on each domain's current choice.
    validated_geometries: dict[tuple[int, int], _Geometry] = {}
    active_conflicts: set[tuple[int, int]] = set()
    selected_runs = _SelectedRuns(len(ds))
    previous_selected: tuple[int, ...] | None = None
    neighborhood = Neighborhood(budget)
    with Cadical195(use_timer=True) as solver:
        solver.configure({"seed": 0})

        def add_clause(clause: list[int]) -> None:
            budget.check()
            if stats.clauses >= MAXIMUM_CLAUSES:
                raise TransportRefusal("POLICY_BOUND", "CaDiCaL clause cap")
            solver.add_clause(clause)
            stats.clauses += 1

        factors = FactorCNF(ds, add_clause, budget, MAXIMUM_COLLISION_CUTS)
        stats.primary_variables = factors.primary_variables
        stats.auxiliary_variables = factors.top_id - factors.primary_variables
        for di, rejected in enumerate(rejected_entries):
            factors.exclude_mask(di, rejected)
        # Seed both encodings consistently: positive height literals alone leave
        # default-true thresholds steering every route onto the highest plane.
        # These are only phase preferences: every original height remains legal.
        phases: list[int] = []
        for index, heights in enumerate(factors.height):
            preferred = index % len(heights)
            budget.charge("predicates", 2 * len(heights))
            phases.extend(
                literal if level == preferred else -literal for level, literal in enumerate(heights)
            )
            for level in range(1, len(heights)):
                threshold = factors.thresholds[index][level]
                assert not isinstance(threshold, bool)
                phases.append(threshold if level <= preferred else -threshold)
        solver.set_phases(phases)
        stats.preparation_seconds = time.monotonic() - stats.started
        for _ in range(MAXIMUM_ROUNDS):
            budget.charge("assignments")
            stats.rounds += 1
            status = None
            while status is None:
                budget.check()
                solver.conf_budget(CONFLICTS_PER_CALL)
                solver.dec_budget(DECISIONS_PER_CALL)
                stats.native_calls += 1
                if checkpoint is not None:
                    checkpoint("native-call")
                budget.charge("predicates", len(neighborhood.assumptions))
                started = time.monotonic()
                status = solver.solve_limited(assumptions=neighborhood.assumptions)
                stats.solver_seconds += time.monotonic() - started
                budget.check()
                if checkpoint is not None:
                    checkpoint("checking-model" if status is True else "native-return")
                if status is False and neighborhood.assumptions:
                    stats.neighborhood_releases += neighborhood.relax(solver.get_core())
                    stats.neighborhood_core_relaxations += 1
                    stats.neighborhood_retained = len(neighborhood.retained)
                    status = None
            if status is False:
                raise TransportRefusal(
                    "TEMPLATE_FAMILY_EXHAUSTED",
                    "CaDiCaL UNSAT on full original domains and sound cuts",
                )
            model = solver.get_model()
            if model is None:
                raise TransportRefusal("SOLVER_UNKNOWN", "SAT without a model")
            selected = factors.select(model)
            geometries: list[_Geometry] = []
            occupied: list[set[Cell]] = []
            off_level_occupied: list[set[Cell]] = []
            selected_levels: list[int] = []
            rejected = False
            for di, (domain, choice) in enumerate(zip(ds, selected, strict=True)):
                budget.check()
                level = domain.levels[choice % len(domain.levels)]
                selected_levels.append(level)
                cached_choice = validated_choices.get(di)
                if cached_choice is not None and cached_choice[0] == choice:
                    geometries.append(cached_choice[1])
                    occupied.append(cached_choice[2])
                    off_level_occupied.append(cached_choice[3])
                    continue
                known_geometry = validated_geometries.get((di, choice))
                geometry = known_geometry or domain._decode(choice, budget)
                geometries.append(geometry)
                sequence = list(cells(geometry.path.points))
                budget.charge("audit_cells", len(sequence))
                occupied.append(set(sequence))
                budget.charge("predicates", len(occupied[-1]))
                off_level_occupied.append({cell for cell in occupied[-1] if cell[2] != level})
                if known_geometry is not None:
                    validated_choices[di] = (
                        choice,
                        geometry,
                        occupied[-1],
                        off_level_occupied[-1],
                    )
                    continue
                path_error = _path_error(geometry, budget)
                if path_error:
                    factors.exclude(di, selected[di])
                    stats.self_rejections += 1
                    rejected = True
                    continue
                if len(sequence) != len(occupied[-1]):
                    raise AssertionError("canonical path check missed a retrace")
                owned = {
                    e.cell
                    for e in (geometry.path.source, geometry.path.sink)
                    if e in problem.owned_endpoints
                }
                bad_cells = (occupied[-1] - owned) & problem.blocked
                if problem.bounds is not None:
                    min_x, min_y, max_x, max_y = problem.bounds
                    budget.charge("predicates", len(occupied[-1]))
                    bad_cells.update(
                        cell
                        for cell in occupied[-1]
                        if not (min_x <= cell[0] <= max_x and min_y <= cell[1] <= max_y)
                    )
                for cell in occupied[-1] & fixed_occupied_cells:
                    for owner in fixed_owners_by_cell[cell]:
                        if not _owned(geometry.path, problem.fixed_paths[owner], cell, budget):
                            bad_cells.add(cell)
                canonical_error = fixed_index.error(geometry, budget)
                if bool(canonical_error) != bool(bad_cells):
                    raise AssertionError(
                        ("static geometry disagreement", canonical_error, bad_cells)
                    )
                if bad_cells:
                    cell = min(bad_cells)
                    if (di, cell) in static_cuts:
                        raise AssertionError("static cut failed to exclude its candidate")
                    mask = indexes[di].occupants(cell, budget)
                    if not mask & (1 << selected[di]):
                        raise AssertionError("cell index misses selected static collision")
                    factors.exclude_mask(di, mask)
                    static_cuts.add((di, cell))
                    stats.static_cuts += 1
                    rejected = True
                else:
                    validated_geometries[di, choice] = geometry
                    validated_choices[di] = (
                        choice,
                        geometry,
                        occupied[-1],
                        off_level_occupied[-1],
                    )
            if rejected:
                continue
            new_cuts = 0
            # Domains and endpoint identities are immutable within this solve.
            # Static-rejected rounds do not advance this pair-audit snapshot.
            changed = [
                previous_selected is None or choice != previous_selected[i]
                for i, choice in enumerate(selected)
            ]
            budget.charge("predicates", len(selected))
            budget.charge("predicates", 2 * len(active_conflicts))
            active_conflicts = {
                (i, j) for i, j in active_conflicts if not changed[i] and not changed[j]
            }
            for i, j in selected_runs.pairs(geometries, changed, budget):
                budget.charge("predicates", 2)
                pair = i, j
                same_level = selected_levels[i] == selected_levels[j]
                if not same_level:
                    budget.charge("predicates", 2)
                overlap = _overlapping_cells(
                    occupied[i],
                    occupied[j],
                    off_level_occupied[i],
                    off_level_occupied[j],
                    same_level=same_level,
                )
                collision_cell = next(
                    (
                        cell
                        for cell in sorted(overlap)
                        if not _owned(geometries[i].path, geometries[j].path, cell, budget)
                    ),
                    None,
                )
                # Certify every conflict before it can justify a cut.
                # Clear pairs receive the independent complete-model audit
                # below, rather than repeating that audit on provisional models.
                if collision_cell is not None and _compatible(geometries[i], geometries[j], budget):
                    raise AssertionError("independent selected-path collision disagreement")
                if collision_cell is not None:
                    budget.charge("predicates")
                    active_conflicts.add(pair)
            previous_selected = tuple(selected)
            conflicts = sorted(active_conflicts)
            stats.last_conflict_pairs = len(conflicts)
            neighborhood.consider(selected, conflicts, factors)
            stats.best_conflict_pairs = neighborhood.best_conflicts
            stats.neighborhood_retained = len(neighborhood.retained)
            budget.charge("predicates", len(ds))
            refined = [False] * len(ds)
            for i, j in conflicts:
                budget.charge("predicates", 2)
                if refined[i] or refined[j]:
                    continue
                ca, p = divmod(selected[i], len(ds[i].levels))
                cb, q = divmod(selected[j], len(ds[j].levels))
                family = primitive_indexes[i].family(primitive_indexes[j], ca, cb, p, q, budget)
                try:
                    emitted = factors.forbid(i, j, family)
                finally:
                    stats.collision_cuts = factors.rectangles
                    stats.guard_variables = factors.guard_count
                    stats.auxiliary_variables = factors.top_id - factors.primary_variables
                if not emitted:
                    raise AssertionError("an existing collision cut failed to exclude its witness")
                stats.families += 1
                new_cuts += emitted
                # Re-solve before learning more conflicts incident to this pair.
                # Any deferred pair implies new_cuts, so cannot bypass final audit.
                budget.charge("predicates", 2)
                refined[i] = refined[j] = True
            if new_cuts:
                continue
            if any(not _compatible(a, b, budget) for a, b in combinations(geometries, 2)):
                raise AssertionError("invalid model survived existing collision cuts")
            budget.check()
            stats.selected_candidate_ids = {
                d.obligation.ordinal: ci for d, ci in zip(ds, selected, strict=True)
            }
            if checkpoint is not None:
                checkpoint("geometry-complete")
            return {
                d.obligation.ordinal: g.path.points for d, g in zip(ds, geometries, strict=True)
            }
    raise TransportRefusal("POLICY_BOUND", "CaDiCaL round cap")
