"""Attempt-owned exact collider preparation and necessary flat-run screening."""

from __future__ import annotations

import bisect
import math
import time
from bisect import bisect_left, insort
from collections import defaultdict
from collections.abc import Collection, Iterator, Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import TYPE_CHECKING

from flab2bp.dsp import catalog, codec, colliders, planet
from flab2bp.indexed import BeltOverlap
from flab2bp.layout import routing_proposals as r
from flab2bp.layout.routing_proposals import Box, Counters, check_deadline, movement_costs
from flab2bp.layout.route_feedback import Cell

if TYPE_CHECKING:
    from flab2bp.layout.routing_domain import _Canvas


@dataclass(frozen=True, slots=True)
class Feature:
    # Clearance-expanded rectangle in plan coordinates; real collision boxes
    # and occupied cells remain in the original world, not this approximation.
    x0: float
    y0: float
    x1: float
    y1: float
    low: float
    high: float
    kind: str


class FeatureIndex:
    """Sorted-X obstacle records, the existing projected-index broadphase shape.

    Buildings.in_box enumerates every cell in the query window, so is unsuitable
    for radar. This index visits obstacle records only, not an alternative grid.
    Its bounds come from _collider_broad_phase_bounds, not new collision rules.
    """

    def __init__(self, features: Sequence[Feature]) -> None:
        self.features = tuple(sorted(features, key=lambda f: (f.x0, f.y0, f.x1, f.y1, f.low)))
        self.xs = tuple(feature.x0 for feature in self.features)
        self.max_width = max((f.x1 - f.x0 for f in self.features), default=0.0)

    def query(self, box: Box, deadline: float | None, counters: Counters) -> Iterator[Feature]:
        counters.feature_queries += 1
        lo = bisect.bisect_left(self.xs, box[0] - self.max_width)
        hi = bisect.bisect_right(self.xs, box[2])
        for index in range(lo, hi):
            check_deadline(deadline)
            feature = self.features[index]
            counters.feature_candidates += 1
            if feature.x1 >= box[0] and feature.y0 <= box[3] and feature.y1 >= box[1]:
                yield feature


class GeometricWorld:
    """Cache fixed collider geometry while consulting live routing masks each time.

    One instance belongs to one private routing canvas. Physical commits happen
    on separate clones, so tentative staking cannot stale the static cache.
    """

    def __init__(
        self,
        canvas: _Canvas,
        *,
        history: Mapping[Cell, float] | None = None,
        pressure: float = 0.0,
        forbidden: Collection[Cell] = (),
        owned_starts: Collection[Cell] = (),
        released_starts: Collection[Cell] = (),
        projection: planet.Projection | None = None,
        deadline: float | None = None,
    ) -> None:
        from flab2bp.layout.routing_domain import _collider_broad_phase_bounds, _collision_pose

        started = time.monotonic()
        self.canvas = canvas
        self.history: Mapping[Cell, float] = history if history is not None else {}
        self.pressure = pressure
        if pressure < 0 or any(not math.isfinite(v) or v < 0 for v in self.history.values()):
            raise ValueError("geometric proposals require nonnegative finite congestion costs")
        self.forbidden = frozenset(forbidden)
        self.owned_starts = frozenset(owned_starts)
        self.released_starts = frozenset(released_starts)
        self.projection = projection
        self.counters = Counters()
        self.costs = movement_costs(canvas.levels, canvas.belt_rules.vertical_construction)
        self._static_point_cache: dict[tuple[int, int, Fraction], bool] = {}
        features: list[Feature] = []
        boxes: list[list[colliders.Box]] = []
        for building in canvas.buildings:
            check_deadline(deadline)
            self.counters.feature_inputs += 1
            if catalog.is_belt(building.item_id) or catalog.is_sorter(building.item_id):
                continue
            pose = _collision_pose(building)
            rx, ry, rz = _collider_broad_phase_bounds(building.model_index, building.yaw)
            clearance = colliders.BELT_PROBE_RADIUS / colliders.GRID_ARC
            features.append(
                Feature(
                    pose.x - rx / colliders.GRID_ARC - clearance,
                    pose.y - ry / colliders.GRID_ARC - clearance,
                    pose.x + rx / colliders.GRID_ARC + clearance,
                    pose.y + ry / colliders.GRID_ARC + clearance,
                    float(building.z),
                    float(building.z) + rz * 3 / 4,
                    "collider",
                )
            )
            # Coater passage follows the original grid's explicit addon excusal.
            # Other unlinked graph-rescue cases remain the ordinary A*'s domain.
            if building.item_id == catalog.SPRAY_COATER_ID:
                continue
            transform = (
                colliders.flat_pose(pose.x, pose.y, pose.z, pose.yaw)
                if projection is None
                else projection.pose(pose.x, pose.y, pose.z, pose.yaw)
            )
            boxes.append(colliders.target_boxes(pose, *transform))
        self.collider_features = FeatureIndex(features)
        self.boxes = tuple(tuple(row) for row in boxes)
        check_deadline(deadline)
        self.overlap = BeltOverlap.of(
            colliders._belt_cells(self.boxes, spherical=projection is not None)
        )
        check_deadline(deadline)
        self.counters.feature_records += len(features)
        self.counters.setup_s += time.monotonic() - started

    def source_clear(self, cell: Cell) -> bool:
        from flab2bp.layout.routing_domain import _TENTATIVE

        return (
            cell not in self.forbidden
            and 0 <= cell[2] < self.canvas.levels
            and (
                self.canvas.free(cell)
                or (cell in self.owned_starts and self.canvas.free_owned_guard(cell))
                or (cell in self.released_starts and self.canvas.blocked.get(cell) == _TENTATIVE)
            )
        )

    def source_geometry_clear(self, cell: Cell, deadline: float | None) -> bool:
        # Preserve source ownership exceptions without exempting its actual
        # fractional/world occupancy or static collider probe.
        return self.canvas.free_world(cell[0], cell[1], Fraction(cell[2])) and self._point_clear(
            cell, Fraction(cell[2]), deadline
        )

    def cell_clear(self, cell: Cell, altitude: Fraction, deadline: float | None) -> bool:
        check_deadline(deadline)
        canvas = self.canvas
        if (
            cell in self.forbidden
            or not canvas.free(cell)
            or not canvas.free_world(cell[0], cell[1], altitude)
        ):
            return False
        return self._point_clear(cell, altitude, deadline)

    def _point_clear(self, cell: Cell, altitude: Fraction, deadline: float | None) -> bool:
        check_deadline(deadline)
        point = cell[0], cell[1], altitude
        cached = self._static_point_cache.get(point)
        if cached is not None:
            self.counters.static_cache_hits += 1
            return cached
        self.counters.static_cache_misses += 1
        if len(self._static_point_cache) >= 32768:
            self._static_point_cache.clear()
            self.counters.static_cache_resets += 1
        self.counters.geometry_inspections += 1
        x, y, z = codec.tile_to_local_offset(cell[0], cell[1], altitude, 1, 1)
        projection = self.projection
        key: tuple[int, int] | tuple[int, int, int]
        if projection is None:
            probe = colliders.belt_probe(x, y, z)
            key = int(probe[0] // 8.0), int(probe[2] // 8.0)
        else:
            radius = projection.shell_radius(z) + colliders.BELT_PROBE_LIFT
            direction = projection.direction(x, y)
            probe = direction[0] * radius, direction[1] * radius, direction[2] * radius
            key = int(probe[0] // 8.0), int(probe[1] // 8.0), int(probe[2] // 8.0)
        self.counters.spatial_queries += 1
        for index in self.overlap.candidates(key):
            check_deadline(deadline)
            for box in self.boxes[index]:
                self.counters.geometry_inspections += 1
                if colliders.sphere_box_overlap(probe, colliders.BELT_PROBE_RADIUS, box):
                    self._static_point_cache[point] = False
                    return False
        self._static_point_cache[point] = True
        return True


class FlatScreen:
    def __init__(
        self, blocked: Collection[Cell], deadline: float | None, world: GeometricWorld
    ) -> None:
        self.world = world
        self.levels = world.canvas.levels
        self.probed: dict[tuple[Cell, Cell, Cell], bool] = {}
        self.rows: dict[int, list[int]] = defaultdict(list)
        self.columns: dict[int, list[int]] = defaultdict(list)
        self.blocked: set[Cell] = set()
        self.reset(blocked, deadline)

    def reset(self, blocked: Collection[Cell], deadline: float | None) -> None:
        self.deadline = deadline
        self.probed.clear()
        current: set[Cell] = set()
        for index, cell in enumerate(blocked):
            if index % 1024 == 0:
                r.check_deadline(deadline)
            if 0 <= cell[2] < self.levels:
                current.add(cell)
        r.check_deadline(deadline)
        # Each mutation leaves both sorted indexes and membership coherent.
        # If a deadline interrupts the update, the next reset resumes from that
        # exact intermediate state rather than trusting a partial snapshot.
        for cell in self.blocked - current:
            r.check_deadline(deadline)
            x, y, z = cell
            row = self.rows[y * self.levels + z]
            column = self.columns[x * self.levels + z]
            row.pop(bisect_left(row, x))
            column.pop(bisect_left(column, y))
            self.blocked.remove(cell)
        for cell in current - self.blocked:
            r.check_deadline(deadline)
            x, y, z = cell
            insort(self.rows[y * self.levels + z], x)
            insort(self.columns[x * self.levels + z], y)
            self.blocked.add(cell)

    def rejects(self, start: Cell, construction: r.Construction, bounds: r.Box) -> bool:
        current = start
        flats: list[tuple[int, int, int, int, int, int]] = []
        ordinal = 0
        for part in construction:
            end = r.Piece(current, part).end
            if end == current:
                continue
            if not r.inside(end, bounds):
                return True
            if isinstance(part, r.FlatRun):
                x0, y0 = min(current[0], end[0]), min(current[1], end[1])
                x1, y1 = max(current[0], end[0]), max(current[1], end[1])
                z = current[2]
                for px0, py0, px1, py1, pz, previous in flats:
                    if pz != z:
                        continue
                    ix0, iy0 = max(x0, px0), max(y0, py0)
                    ix1, iy1 = min(x1, px1), min(y1, py1)
                    if ix0 <= ix1 and iy0 <= iy1:
                        join = (current[0], current[1], current[0], current[1])
                        if previous != ordinal - 1 or (ix0, iy0, ix1, iy1) != join:
                            return True
                flats.append((x0, y0, x1, y1, z, ordinal))
                horizontal = current[1] == end[1]
                values = (
                    self.rows.get(current[1] * self.levels + z, ())
                    if horizontal
                    else self.columns.get(current[0] * self.levels + z, ())
                )
                lo, hi = (x0, x1) if horizontal else (y0, y1)
                # The selected root alone may carry an owned/released-source
                # exception. All later cells use ordinary blocked occupancy.
                if ordinal == 0:
                    if part.direction[0 if horizontal else 1] > 0:
                        lo += 1
                    else:
                        hi -= 1
                at = bisect_left(values, lo)
                if at < len(values) and values[at] <= hi:
                    return True
                key = (start, current, end)
                rejected = self.probed.get(key)
                if rejected is None:
                    rejected = False
                    # Features choose probes, never certify free space. A failed
                    # authoritative check at an actual run cell rejects the run;
                    # missed obstacles still reach the complete evaluator.
                    for feature in self.world.collider_features.query(
                        (x0, y0, x1, y1), self.deadline, self.world.counters
                    ):
                        if feature.kind != "collider" or not feature.low <= z <= feature.high:
                            continue
                        low = math.ceil(
                            max(x0 if horizontal else y0, feature.x0 if horizontal else feature.y0)
                        )
                        high = math.floor(
                            min(x1 if horizontal else y1, feature.x1 if horizontal else feature.y1)
                        )
                        if low > high:
                            continue
                        middle = (low + high) // 2
                        cell = (middle, current[1], z) if horizontal else (current[0], middle, z)
                        if cell != start and not self.world.cell_clear(
                            cell, Fraction(z), self.deadline
                        ):
                            rejected = True
                            break
                    self.probed[key] = rejected
                if rejected:
                    return True
            current = end
            ordinal += 1
        return False
