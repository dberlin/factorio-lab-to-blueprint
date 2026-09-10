"""Exact-domain SAT routing under the strategy supervisor."""

from __future__ import annotations

import time
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
    _middle,
    _owned,
    _path_error,
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
                for start, end in spans[1:]:
                    budget.charge("predicates")
                    if start <= hi + 1:
                        hi = max(hi, end)
                    else:
                        row[lo] = row.get(lo, 0) ^ bit
                        row[hi + 1] = row.get(hi + 1, 0) ^ bit
                        lo, hi = start, end
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
        for key, row in events.items():
            coordinates = tuple(sorted(row))
            active = 0
            masks: list[int] = []
            for coordinate in coordinates:
                budget.charge("predicates")
                active ^= row[coordinate]
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
    if not ds:
        return {}
    if any(d.count == 0 for d in ds):
        raise TransportRefusal("TEMPLATE_FAMILY_EXHAUSTED", "empty complete candidate domain")
    fixed_index = _FixedIndex(problem, budget)
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
    static_cuts: set[tuple[int, Cell]] = set()
    validated_choices: dict[int, tuple[int, set[Cell]]] = {}
    validated_pairs: dict[tuple[int, int], tuple[int, int, Cell | None]] = {}
    path_indexes: dict[int, tuple[int, _FixedIndex]] = {}
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
            for ci in members(rejected):
                factors.exclude(di, ci)
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
            geometries = [d._decode(ci, budget) for d, ci in zip(ds, selected, strict=True)]
            occupied: list[set[Cell]] = []
            rejected = False
            for di, geometry in enumerate(geometries):
                budget.check()
                cached_choice = validated_choices.get(di)
                if cached_choice is not None and cached_choice[0] == selected[di]:
                    occupied.append(cached_choice[1])
                    continue
                sequence = list(cells(geometry.path.points))
                budget.charge("audit_cells", len(sequence))
                occupied.append(set(sequence))
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
                for fixed, fixed_occupied in zip(problem.fixed_paths, fixed_cells, strict=True):
                    for cell in occupied[-1] & fixed_occupied:
                        if not _owned(geometry.path, fixed, cell, budget):
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
                    for ci in members(mask):
                        factors.exclude(di, ci)
                    static_cuts.add((di, cell))
                    stats.static_cuts += 1
                    rejected = True
                else:
                    validated_choices[di] = selected[di], occupied[-1]
            if rejected:
                continue
            new_cuts = 0
            conflicts: list[tuple[int, int]] = []
            for i, j in combinations(range(len(ds)), 2):
                budget.check()
                budget.charge("predicates", 2)
                pair = i, j
                cached_pair = validated_pairs.get(pair)
                if cached_pair is not None and cached_pair[:2] == (selected[i], selected[j]):
                    cell = cached_pair[2]
                else:
                    cell = next(
                        (
                            cell
                            for cell in sorted(occupied[i] & occupied[j])
                            if not _owned(geometries[i].path, geometries[j].path, cell, budget)
                        ),
                        None,
                    )
                    cached_index = path_indexes.get(i)
                    if cached_index is None or cached_index[0] != selected[i]:
                        path_index = _FixedIndex(
                            TemplateProblem((), frozenset(), (geometries[i].path,), (), (), ()),
                            budget,
                        )
                        path_indexes[i] = selected[i], path_index
                    else:
                        path_index = cached_index[1]
                    if (path_index.error(geometries[j], budget) is None) != (cell is None):
                        raise AssertionError("independent selected-path collision disagreement")
                    validated_pairs[pair] = selected[i], selected[j], cell
                if cell is None:
                    continue
                budget.charge("predicates")
                conflicts.append(pair)
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
                    raise AssertionError("an existing exact family failed to exclude its witness")
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
