"""Strategy-independent final projection and cleanup of exact placements."""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from functools import cache
from typing import Literal, cast

from flab2bp.dsp import catalog, codec, colliders, planet, rules
from flab2bp.layout import slots
from flab2bp.layout.band_policy import BandPolicy
from flab2bp.layout.base import AreaFrame, PlacedBuilding, Placement
from flab2bp.layout.validate import Report
from flab2bp.layout.validate import certify as _certify
from flab2bp.spec import BuildSpec

type _Direction = Literal["input", "output"]
type _Side = Literal["left", "bottom", "right", "top"]
_NO_PROTECTED_ROOTS: frozenset[int] = frozenset()


@dataclass(frozen=True, slots=True)
class ProjectionFailure:
    """One authoritative projected paste refusal."""

    check: str
    buildings: tuple[int, ...]
    detail: str
    band: int


ProjectionCancelled = planet.ProjectionCancelled

type ProjectionGeometrySignature = tuple[object, ...]



@dataclass(frozen=True, slots=True)
class ProjectionNoGood:
    """One pair-specific packed origin assignment rejected by projection."""

    left_strip: int
    right_strip: int
    delta_x: int
    delta_y: int
    pack_width: int
    pack_height: int
    left_origin: tuple[int, int]
    right_origin: tuple[int, int]
    left_geometry: ProjectionGeometrySignature
    right_geometry: ProjectionGeometrySignature
    failure: ProjectionFailure



    def __post_init__(self) -> None:
        if (
            not isinstance(self.left_geometry, tuple)
            or not self.left_geometry
            or not isinstance(self.right_geometry, tuple)
            or not self.right_geometry
        ):
            raise ValueError("projection no-good requires two physical geometry signatures")


class ProjectionRefusal(ValueError):
    """No requested latitude frame accepts the placement's real geometry."""

    def __init__(self, failures: Sequence[ProjectionFailure]) -> None:
        distinct = tuple(dict.fromkeys(failures))
        self.failures: tuple[ProjectionFailure, ...] = distinct
        self.checks: tuple[str, ...] = tuple(
            sorted({failure.check for failure in distinct})
        )
        detail = "; ".join(
            f"band {failure.band} {failure.check} {failure.buildings}: {failure.detail}"
            for failure in distinct
        )
        super().__init__(
            "no legal DSP latitude band/orientation accepts the final placement"
            + (f": {detail}" if detail else "")
        )


@dataclass(frozen=True, slots=True)
class FrameCandidate:
    """One deterministic latitude-only frame choice awaiting certification."""

    frame: AreaFrame
    south_padding: int
    added_rows: int



@dataclass(frozen=True, slots=True)
class BandPolicySearchEnvelope:
    """Pure fixed-perimeter capacity shared by layout search strategies."""

    policy: BandPolicy
    perimeter: int
    band: planet.Band | None

    @property
    def boundary_core_height(self) -> int | None:
        """The fixed band's unrotated latitude boundary, excluding perimeter."""
        if self.band is None:
            return None
        boundary = self.band.rows - 2 * self.perimeter
        return boundary if boundary > 0 else None

    def frame_candidates(
        self,
        core_width: int,
        core_height: int,
    ) -> tuple[FrameCandidate, ...]:
        """Return exact finalizer frames for one reserved core envelope."""
        if core_width <= 0 or core_height <= 0:
            return ()
        margin = 2 * self.perimeter
        return _frame_candidates_for_extent(
            core_width + margin,
            core_height + margin,
            self.policy,
        )

    def extent_failure(
        self,
        core_width: int,
        core_height: int,
    ) -> ProjectionFailure:
        """Return structured evidence for an empty exact frame-candidate set."""
        if self.frame_candidates(core_width, core_height):
            raise ValueError("extent failure requested for a fitting search envelope")
        margin = 2 * self.perimeter
        return _extent_failure_for_dimensions(
            core_width + margin,
            core_height + margin,
            self.policy,
        )

    def reserve_boundary_height(
        self,
        ordered: tuple[int, ...],
        *,
        minimum_width_for_height: Mapping[int, int],
    ) -> tuple[int, ...]:
        """Replace the first proved-infeasible fixed height without adding work."""
        boundary = self.boundary_core_height
        if boundary is None or boundary in ordered:
            return ordered
        for index, height in enumerate(ordered):
            minimum_width = minimum_width_for_height[height]
            if self.frame_candidates(minimum_width, height):
                continue
            return ordered[:index] + (boundary,) + ordered[index + 1 :]
        return ordered


def band_policy_search_envelope(
    policy: BandPolicy,
    *,
    perimeter: int,
) -> BandPolicySearchEnvelope:
    """Build the one exact band-policy capacity used before costly preparation."""
    if type(perimeter) is not int or perimeter < 0:
        raise ValueError("search-envelope perimeter must be a non-negative integer")
    explicit = policy.explicit_segments
    band = (
        next(
            candidate
            for candidate in planet.bands()
            if candidate.area_segments == explicit
        )
        if explicit is not None
        else None
    )
    return BandPolicySearchEnvelope(policy, perimeter, band)

@dataclass(frozen=True, slots=True)
class _ProjectionInvariants:
    tested: tuple[tuple[int, colliders.Placed], ...]
    nodes: tuple[tuple[int, PlacedBuilding, rules.PowerNode], ...]
    sorters: tuple[tuple[int, planet.Sorter], ...]
    belts: tuple[tuple[int, PlacedBuilding], ...]
    addons: tuple[
        tuple[int, PlacedBuilding, tuple[catalog.AddonSupplyPose, ...]],
        ...,
    ]
    coaters: tuple[tuple[int, colliders.Placed], ...]
    splitters: tuple[tuple[int, colliders.Placed], ...]


@dataclass(slots=True)
class _ProjectionCounters:
    frame_candidates: int = 0
    projections: int = 0
    collider_pairs: int = 0
    power_pairs: int = 0
    sorters: int = 0
    invariant_cache_hits: int = 0
    pair_cache_hits: int = 0
    projection_cache_hits: int = 0
    sorter_result_cache_hits: int = 0
    static_result_cache_hits: int = 0
    power_result_cache_hits: int = 0
    addon_result_cache_hits: int = 0
    addon_splitter_result_cache_hits: int = 0


type _SorterFailureCache = Callable[
    [tuple[tuple[int, planet.Sorter], ...], planet.Projection],
    ProjectionFailure | None,
]
type _StaticFailureCache = Callable[
    [
        tuple[tuple[int, colliders.Placed], ...],
        tuple[tuple[int, int], ...],
        planet.Projection,
    ],
    ProjectionFailure | None,
]

type _FailureCache = Callable[..., ProjectionFailure | None]

@dataclass(slots=True)
class _ProjectionCache:
    counters: _ProjectionCounters
    cancelled: Callable[[], bool] | None = None
    invariants: dict[tuple[PlacedBuilding, ...], _ProjectionInvariants] = field(
        default_factory=dict
    )
    pairs: dict[
        tuple[tuple[PlacedBuilding, ...], int, bool],
        tuple[tuple[int, int], ...],
    ] = field(default_factory=dict)
    projections: dict[tuple[int, int, int, int], planet.Projection] = field(
        default_factory=dict
    )
    sorter_conditions: dict[tuple[object, ...], str | None] = field(
        default_factory=dict
    )
    _sorter_misses: int = field(init=False, default=0)
    _static_misses: int = field(init=False, default=0)
    _power_misses: int = field(init=False, default=0)
    _addon_misses: int = field(init=False, default=0)
    _addon_splitter_misses: int = field(init=False, default=0)
    _sorter_failure: _SorterFailureCache = field(init=False, repr=False)
    _static_failure: _StaticFailureCache = field(init=False, repr=False)
    _power_failure: _FailureCache = field(init=False, repr=False)
    _addon_failure: _FailureCache = field(init=False, repr=False)
    _addon_splitter_failure: _FailureCache = field(init=False, repr=False)

    def __post_init__(self) -> None:
        @cache
        def sorter_failure(
            sorters: tuple[tuple[int, planet.Sorter], ...],
            projection: planet.Projection,
        ) -> ProjectionFailure | None:
            self._sorter_misses += 1
            return _projected_sorter_failure(
                sorters,
                projection,
                counters=self.counters,
                cancelled=self.cancelled,
                _condition_cache=self.sorter_conditions,
            )

        @cache
        def static_failure(
            tested: tuple[tuple[int, colliders.Placed], ...],
            pairs: tuple[tuple[int, int], ...],
            projection: planet.Projection,
        ) -> ProjectionFailure | None:
            self._static_misses += 1
            return _projected_static_failure(
                tested,
                pairs,
                projection,
                counters=self.counters,
                cancelled=self.cancelled,
            )

        @cache
        def power_failure(
            nodes: tuple[tuple[int, PlacedBuilding, rules.PowerNode], ...],
            projection: planet.Projection,
        ) -> ProjectionFailure | None:
            self._power_misses += 1
            failure = projected_power_failure(
                nodes,
                projection,
                cancelled=self.cancelled,
            )
            self.counters.power_pairs += _power_pairs_examined(
                nodes,
                failure,
                projection,
                cancelled=self.cancelled,
            )
            return failure

        @cache
        def addon_failure(
            belts: tuple[tuple[int, PlacedBuilding], ...],
            addons: tuple[
                tuple[
                    int,
                    PlacedBuilding,
                    tuple[catalog.AddonSupplyPose, ...],
                ],
                ...,
            ],
            projection: planet.Projection,
        ) -> ProjectionFailure | None:
            self._addon_misses += 1
            return _projected_addon_failure(
                belts,
                addons,
                projection,
                cancelled=self.cancelled,
            )

        @cache
        def addon_splitter_failure(
            coaters: tuple[tuple[int, colliders.Placed], ...],
            splitters: tuple[tuple[int, colliders.Placed], ...],
            projection: planet.Projection,
        ) -> ProjectionFailure | None:
            self._addon_splitter_misses += 1
            return _projected_addon_splitter_failure(
                coaters,
                splitters,
                projection,
                cancelled=self.cancelled,
            )

        self._sorter_failure = sorter_failure
        self._static_failure = static_failure
        self._power_failure = power_failure
        self._addon_failure = addon_failure
        self._addon_splitter_failure = addon_splitter_failure


    def _poll_cancellation(self) -> None:
        if self.cancelled is not None and self.cancelled():
            raise ProjectionCancelled

    def sorter_failure(
        self,
        sorters: tuple[tuple[int, planet.Sorter], ...],
        projection: planet.Projection,
    ) -> ProjectionFailure | None:
        self._poll_cancellation()
        misses = self._sorter_misses
        failure = self._sorter_failure(sorters, projection)
        if self._sorter_misses == misses:
            self.counters.sorter_result_cache_hits += 1
        return failure

    def static_failure(
        self,
        tested: tuple[tuple[int, colliders.Placed], ...],
        pairs: tuple[tuple[int, int], ...],
        projection: planet.Projection,
    ) -> ProjectionFailure | None:
        self._poll_cancellation()
        misses = self._static_misses
        failure = self._static_failure(tested, pairs, projection)
        if self._static_misses == misses:
            self.counters.static_result_cache_hits += 1
        return failure

    def power_failure(
        self,
        nodes: tuple[tuple[int, PlacedBuilding, rules.PowerNode], ...],
        projection: planet.Projection,
    ) -> ProjectionFailure | None:
        self._poll_cancellation()
        misses = self._power_misses
        failure = self._power_failure(nodes, projection)
        if self._power_misses == misses:
            self.counters.power_result_cache_hits += 1
        return failure

    def addon_failure(
        self,
        belts: tuple[tuple[int, PlacedBuilding], ...],
        addons: tuple[
            tuple[
                int,
                PlacedBuilding,
                tuple[catalog.AddonSupplyPose, ...],
            ],
            ...,
        ],
        projection: planet.Projection,
    ) -> ProjectionFailure | None:
        self._poll_cancellation()
        misses = self._addon_misses
        failure = self._addon_failure(belts, addons, projection)
        if self._addon_misses == misses:
            self.counters.addon_result_cache_hits += 1
        return failure

    def addon_splitter_failure(
        self,
        coaters: tuple[tuple[int, colliders.Placed], ...],
        splitters: tuple[tuple[int, colliders.Placed], ...],
        projection: planet.Projection,
    ) -> ProjectionFailure | None:
        self._poll_cancellation()
        misses = self._addon_splitter_misses
        failure = self._addon_splitter_failure(coaters, splitters, projection)
        if self._addon_splitter_misses == misses:
            self.counters.addon_splitter_result_cache_hits += 1
        return failure

def _extent_fits(width: int, height: int) -> tuple[planet.Fit, ...]:
    fits: list[planet.Fit] = []
    for band in sorted(planet.bands(), key=lambda candidate: candidate.area_segments):
        for rotated, (columns, rows) in (
            (False, (width, height)),
            (True, (height, width)),
        ):
            if rows <= band.rows and columns <= band.columns:
                fits.append(planet.Fit(band, rotated, rows, columns))
    return tuple(fits)




def _collision_placed(building: PlacedBuilding) -> colliders.Placed:
    return colliders.Placed(
        building.model_index,
        *codec.tile_to_local_offset(
            building.x,
            building.y,
            building.z,
            building.width,
            building.height,
        ),
        building.yaw,
    )


def _power_nodes(
    placement: Placement,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[tuple[int, PlacedBuilding, rules.PowerNode], ...]:
    nodes: list[tuple[int, PlacedBuilding, rules.PowerNode]] = []
    for index, building in enumerate(placement.buildings):
        if cancelled is not None and cancelled():
            raise ProjectionCancelled
        try:
            info = catalog.building(building.item_id)
        except KeyError:
            continue
        if not info.is_power_node:
            continue
        nodes.append(
            (
                index,
                building,
                rules.PowerNode(
                    is_power_node=True,
                    is_accumulator=info.is_accumulator,
                    wind_forced_power=info.wind_forced_power,
                    geothermal=info.geothermal,
                ),
            )
        )
    return tuple(nodes)


def _building_centre(building: PlacedBuilding) -> tuple[float, float, float]:
    return codec.tile_to_local_offset(
        building.x,
        building.y,
        building.z,
        building.width,
        building.height,
    )


def _planet_sorters(
    placement: Placement,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[tuple[int, planet.Sorter], ...]:
    buildings = placement.buildings
    sorters: list[tuple[int, planet.Sorter]] = []
    for index, building in enumerate(buildings):
        if cancelled is not None and cancelled():
            raise ProjectionCancelled
        if not catalog.is_sorter(building.item_id):
            continue
        if building.x2 is None or building.y2 is None:
            continue

        emitted = slots.emitted_sorter(building, buildings)
        seated = slots.seated_sorter(emitted, buildings)
        if seated is None:
            continue

        input_peer = (
            buildings[emitted.input_obj]
            if emitted.input_obj is not None and 0 <= emitted.input_obj < len(buildings)
            else None
        )
        output_peer = (
            buildings[emitted.output_obj]
            if emitted.output_obj is not None and 0 <= emitted.output_obj < len(buildings)
            else None
        )
        input_belt = input_peer is not None and catalog.is_belt(input_peer.item_id)
        output_belt = output_peer is not None and catalog.is_belt(output_peer.item_id)

        x = seated.x
        y = seated.y
        z = seated.z
        x2 = seated.x2
        y2 = seated.y2
        z2 = seated.z2
        if input_belt and not output_belt and output_peer is not None:
            ref_x, ref_y, ref_z = _building_centre(output_peer)
        elif output_belt and not input_belt and input_peer is not None:
            ref_x, ref_y, ref_z = _building_centre(input_peer)
        else:
            ref_x = (x + x2) / 2.0
            ref_y = (y + y2) / 2.0
            ref_z = (z + z2) / 2.0

        sorters.append(
            (
                index,
                planet.Sorter(
                    x=x,
                    y=y,
                    z=z,
                    x2=x2,
                    y2=y2,
                    z2=z2,
                    yaw=emitted.yaw,
                    yaw2=emitted.yaw if emitted.yaw2 is None else emitted.yaw2,
                    input_belt=input_belt,
                    output_belt=output_belt,
                    ref_x=ref_x,
                    ref_y=ref_y,
                    ref_z=ref_z,
                ),
            )
        )
    return tuple(sorters)


def _projected_sorter_failure(
    sorters: Sequence[tuple[int, planet.Sorter]],
    projection: planet.Projection,
    *,
    counters: _ProjectionCounters | None = None,
    cancelled: Callable[[], bool] | None = None,
    _condition_cache: dict[tuple[object, ...], str | None] | None = None,
) -> ProjectionFailure | None:
    conditions = {} if _condition_cache is None else _condition_cache
    projection_context = (
        projection.band,
        projection.segment,
        projection.radius,
        projection.quadrant,
    )
    for index, sorter in sorters:
        if cancelled is not None and cancelled():
            raise ProjectionCancelled
        if counters is not None:
            counters.sorters += 1
        if projection.rotated:
            longitude_origin = sorter.ref_y
            condition_key = (
                *projection_context,
                sorter.y - longitude_origin,
                projection.anchor_row + sorter.x,
                sorter.z,
                sorter.y2 - longitude_origin,
                projection.anchor_row + sorter.x2,
                sorter.z2,
                sorter.yaw,
                sorter.yaw2,
                sorter.input_belt,
                sorter.output_belt,
                projection.anchor_row + sorter.ref_x,
                sorter.ref_z,
            )
        else:
            longitude_origin = sorter.ref_x
            condition_key = (
                *projection_context,
                sorter.x - longitude_origin,
                projection.anchor_row + sorter.y,
                sorter.z,
                sorter.x2 - longitude_origin,
                projection.anchor_row + sorter.y2,
                sorter.z2,
                sorter.yaw,
                sorter.yaw2,
                sorter.input_belt,
                sorter.output_belt,
                projection.anchor_row + sorter.ref_y,
                sorter.ref_z,
            )
        if condition_key in conditions:
            condition = conditions[condition_key]
        else:
            condition = planet.sorter_condition(sorter, projection)
            conditions[condition_key] = condition
        if condition is not None:
            return ProjectionFailure(
                check="game.inserter_paste",
                buildings=(index,),
                detail=f"sorter is {condition}",
                band=projection.band.area_segments,
            )
    return None


def _power_pair_condition(
    left: tuple[int, PlacedBuilding, rules.PowerNode],
    right: tuple[int, PlacedBuilding, rules.PowerNode],
    distance2: float,
) -> str | None:
    _left_index, left_building, left_node = left
    _right_index, right_building, right_node = right
    lo, hi = rules.PASTE_POWER_NODE_IDS
    condition = None
    if lo <= right_building.item_id < hi:
        condition = rules.power_node_condition(left_node, right_node, distance2)
    if condition is None and lo <= left_building.item_id < hi:
        condition = rules.power_node_condition(right_node, left_node, distance2)
    return condition


def _projected_power_candidates(
    nodes: Sequence[tuple[int, PlacedBuilding, rules.PowerNode]],
    projection: planet.Projection,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[tuple[tuple[float, float, float], ...], tuple[tuple[int, int], ...]]:
    """Projected poses and every pair that can reach an authoritative gate."""
    poses_list: list[tuple[float, float, float]] = []
    for _index, building, _node in nodes:
        if cancelled is not None and cancelled():
            raise ProjectionCancelled
        poses_list.append(projection.position(*_building_centre(building)))
    poses = tuple(poses_list)
    if len(nodes) < 2:
        return poses, ()

    # Every spacing refusal first requires ``distance² < node.gate_sqr``.
    # Buckets as wide as the largest gate therefore make the 26 neighbours a
    # conservative broadphase.  Candidate pairs are sorted back into
    # ``itertools.combinations`` order before the unchanged exact predicate
    # runs, preserving the validator's first failure and deterministic detail.
    cell_size = math.sqrt(max(node.gate_sqr for _index, _building, node in nodes))
    grid: dict[tuple[int, int, int], list[int]] = {}
    pairs: list[tuple[int, int]] = []
    for right, pose in enumerate(poses):
        if cancelled is not None and cancelled():
            raise ProjectionCancelled
        cell = cast(
            tuple[int, int, int],
            tuple(math.floor(axis / cell_size) for axis in pose),
        )
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    pairs.extend(
                        (left, right)
                        for left in grid.get(
                            (cell[0] + dx, cell[1] + dy, cell[2] + dz),
                            (),
                        )
                    )
        grid.setdefault(cell, []).append(right)
    pairs.sort()
    return poses, tuple(pairs)


def projected_power_failure(
    nodes: Sequence[tuple[int, PlacedBuilding, rules.PowerNode]],
    projection: planet.Projection,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> ProjectionFailure | None:
    """Return the first authoritative power-pair refusal in one projection."""
    poses, pairs = _projected_power_candidates(
        nodes,
        projection,
        cancelled=cancelled,
    )
    for left, right in pairs:
        if cancelled is not None and cancelled():
            raise ProjectionCancelled
        distance2 = math.dist(poses[left], poses[right]) ** 2
        condition = _power_pair_condition(nodes[left], nodes[right], distance2)
        if condition is not None:
            return ProjectionFailure(
                check="game.power_too_close",
                buildings=(nodes[left][0], nodes[right][0]),
                detail=(
                    f"{distance2**0.5:.4f} world units apart, below the "
                    f"3.5-unit PowerTooClose gate ({condition})"
                ),
                band=projection.band.area_segments,
            )
    return None


def _power_pairs_examined(
    nodes: Sequence[tuple[int, PlacedBuilding, rules.PowerNode]],
    failure: ProjectionFailure | None,
    projection: planet.Projection,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> int:
    """Count exact pair predicates the shared first-failure scan evaluated."""
    _poses, pairs = _projected_power_candidates(
        nodes,
        projection,
        cancelled=cancelled,
    )
    for examined, (left, right) in enumerate(pairs, 1):
        if failure is not None and failure.buildings == (
            nodes[left][0],
            nodes[right][0],
        ):
            return examined
    return len(pairs)


def _projected_static_failure(
    tested: Sequence[tuple[int, colliders.Placed]],
    pairs: Sequence[tuple[int, int]],
    projection: planet.Projection,
    *,
    counters: _ProjectionCounters | None = None,
    _box_cache: dict[
        tuple[colliders.Placed, planet.Projection],
        tuple[colliders.Box, ...],
    ]
    | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> ProjectionFailure | None:
    placed = [building for _index, building in tested]
    if counters is not None:
        counters.collider_pairs += len(pairs)
    hits = planet.collisions_at(
        placed,
        projection,
        pairs,
        _box_cache=_box_cache,
        cancelled=cancelled,
    )
    if not hits:
        return None
    left, right = hits[0]
    return ProjectionFailure(
        check="geom.collide",
        buildings=(tested[left][0], tested[right][0]),
        detail="build colliders intersect",
        band=projection.band.area_segments,
    )


def first_projected_static_failure(
    buildings: Sequence[tuple[int, PlacedBuilding]],
    projections: Sequence[planet.Projection],
    *,
    candidate_index: int | None = None,
    _clean_contexts: set[tuple[object, ...]] | None = None,
    _box_cache: dict[
        tuple[colliders.Placed, planet.Projection],
        tuple[colliders.Box, ...],
    ]
    | None = None,
    _placed_cache: dict[PlacedBuilding, colliders.Placed] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> ProjectionFailure | None:
    """Return the first exact static failure across ordered projections.

    Building collider poses are invariant within one materialized frame and the
    broad-phase candidate pairs vary only by band geometry, not by anchor row.
    Prepare each pose once and each distinct band context once, then run the
    authoritative exact verdict in caller-supplied projection order.
    """
    if cancelled is not None and cancelled():
        raise ProjectionCancelled
    retained = tuple(
        (index, building)
        for index, building in buildings
        if not catalog.is_belt(building.item_id)
        and not catalog.is_sorter(building.item_id)
    )
    tested_list: list[tuple[int, colliders.Placed]] = []
    pending_placed: dict[PlacedBuilding, colliders.Placed] = {}
    for index, building in retained:
        placed = (
            None
            if _placed_cache is None
            else _placed_cache.get(building, pending_placed.get(building))
        )
        if placed is None:
            placed = _collision_placed(building)
            if _placed_cache is not None:
                pending_placed[building] = placed
        tested_list.append((index, placed))
    tested = tuple(tested_list)
    if _placed_cache is not None:
        _placed_cache.update(pending_placed)
    candidate_position: int | None = None
    if candidate_index is not None:
        try:
            candidate_position = next(
                position
                for position, (index, _building) in enumerate(retained)
                if index == candidate_index
            )
        except StopIteration:
            raise ValueError(
                "prospective static candidate is not collision-tested"
            ) from None

    pair_buildings = tuple(building for _index, building in tested)
    pairs_by_context: dict[
        tuple[planet.Band, int, float, int],
        tuple[tuple[int, int], ...],
    ] = {}
    for projection in projections:
        if cancelled is not None and cancelled():
            raise ProjectionCancelled
        context = (
            projection.band,
            projection.segment,
            projection.radius,
            projection.quadrant,
        )
        pairs = pairs_by_context.get(context)
        if cancelled is not None and cancelled():
            raise ProjectionCancelled
        if pairs is None:
            broad_phase_buildings = (
                tuple(
                    replace(building, x=building.y, y=building.x)
                    for building in pair_buildings
                )
                if projection.rotated
                else pair_buildings
            )
            if cancelled is None:
                pairs = tuple(
                    planet.candidate_pairs(
                        broad_phase_buildings,
                        projection.band,
                        projection.segment,
                        projection.radius,
                        candidate_position=candidate_position,
                    )
                )
            else:
                pairs = tuple(
                    planet.candidate_pairs(
                        broad_phase_buildings,
                        projection.band,
                        projection.segment,
                        projection.radius,
                        candidate_position=candidate_position,
                        cancelled=cancelled,
                    )
                )
            pairs_by_context[context] = pairs
        clean_context: tuple[object, ...] | None = None
        if _clean_contexts is not None:
            wanted = tuple(sorted({position for pair in pairs for position in pair}))
            # Uniform longitude is a rigid rotation of the whole spherical
            # configuration. Normalize it away so capacity frames that differ
            # only by that rotation share the same exact clean verdict.
            base_longitude = 0.0
            if wanted:
                base = tested[wanted[0]][1]
                base_longitude = (
                    base.y if projection.rotated else base.x
                )
            placed_context: list[tuple[object, ...]] = []
            for position in wanted:
                if cancelled is not None and cancelled():
                    raise ProjectionCancelled
                placed = tested[position][1]
                longitude, latitude = (
                    (placed.y, placed.x)
                    if projection.rotated
                    else (placed.x, placed.y)
                )
                placed_context.append(
                    (
                        position,
                        placed.model_index,
                        longitude - base_longitude,
                        projection.anchor_row + latitude,
                        placed.z,
                        placed.yaw,
                    )
                )
            clean_context = (
                projection.band.area_segments,
                projection.segment,
                projection.radius,
                projection.quadrant,
                pairs,
                tuple(placed_context),
            )
            if clean_context in _clean_contexts:
                continue
        if cancelled is not None and cancelled():
            raise ProjectionCancelled
        failure = (
            _projected_static_failure(
                tested,
                pairs,
                projection,
                _box_cache=_box_cache,
            )
            if cancelled is None
            else _projected_static_failure(
                tested,
                pairs,
                projection,
                _box_cache=_box_cache,
                cancelled=cancelled,
            )
        )
        if failure is not None:
            return failure
        if clean_context is not None and _clean_contexts is not None:
            _clean_contexts.add(clean_context)
    return None


def projected_static_failure(
    buildings: Sequence[tuple[int, PlacedBuilding]],
    projection: planet.Projection,
    *,
    candidate_index: int | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> ProjectionFailure | None:
    """Return the finalizer's exact static-collider verdict for one projection.

    ``buildings`` retain their placement indices so a prospective object that is
    not committed yet can produce the same structured evidence as finalization.
    Belts and sorters are omitted by the same condition as
    :func:`_projection_invariants`.  When ``candidate_index`` is supplied, only
    candidate pairs involving that staged object are considered, in the order
    :func:`planet.candidate_pairs` gives them.
    """
    return first_projected_static_failure(
        buildings,
        (projection,),
        candidate_index=candidate_index,
        cancelled=cancelled,
    )


def _projected_addon_failure(
    belts: Sequence[tuple[int, PlacedBuilding]],
    addons: Sequence[
        tuple[int, PlacedBuilding, tuple[catalog.AddonSupplyPose, ...]]
    ],
    projection: planet.Projection,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> ProjectionFailure | None:
    if not belts or not addons:
        return None
    radius2 = rules.ADDON_AREA_RADIUS**2
    latitude_step = planet.latitude_rad_per_grid(projection.segment)
    poleward = min(
        math.cos(
            min(
                abs(grid),
                planet.pole_grid_idx(projection.segment),
            )
            * latitude_step
        )
        for grid in (
            projection.band.grid_lo,
            projection.band.grid_hi,
        )
    )
    column_lower_bound = (
        projection.radius
        * poleward
        * planet.longitude_rad_per_grid(projection.band.area_segments)
        * 0.9
    )
    row_lower_bound = projection.radius * latitude_step * 0.9
    column_reach = min(
        projection.band.columns,
        math.ceil(rules.ADDON_AREA_RADIUS / max(column_lower_bound, 1e-9)) + 1,
    )
    row_reach = math.ceil(
        rules.ADDON_AREA_RADIUS / max(row_lower_bound, 1e-9)
    ) + 1

    def transformed(x: float, y: float) -> tuple[float, float]:
        return (y, x) if projection.rotated else (x, y)

    # Index in blueprint space first.  Projecting all belts for every legal
    # latitude was the dominant cost here; the lower bounds above can only
    # over-include, and the exact projected distance remains the verdict.
    belt_position_by_index = {
        belt_index: belt_position
        for belt_position, (belt_index, _belt) in enumerate(belts)
    }
    predecessor_by_position: dict[int, int] = {}
    for belt_position, (_belt_index, placed_belt) in enumerate(belts):
        target_position = (
            belt_position_by_index.get(placed_belt.output_obj)
            if placed_belt.output_obj is not None
            else None
        )
        if target_position is not None:
            predecessor_by_position[target_position] = belt_position
    belt_grid: dict[tuple[int, int], list[int]] = {}
    for belt_position, (_belt_index, placed_belt) in enumerate(belts):
        if cancelled is not None and cancelled():
            raise ProjectionCancelled
        longitude, latitude = transformed(placed_belt.x, placed_belt.y)
        cell = (
            math.floor(longitude) % projection.band.columns,
            math.floor(latitude),
        )
        belt_grid.setdefault(cell, []).append(belt_position)
    belt_positions: dict[int, tuple[float, float, float]] = {}

    def projected_belt(belt_position: int) -> tuple[float, float, float]:
        cached = belt_positions.get(belt_position)
        if cached is not None:
            return cached
        placed = belts[belt_position][1]
        projected = projection.position(
            placed.x,
            placed.y,
            float(placed.z),
        )
        belt_positions[belt_position] = projected
        return projected

    for addon_index, addon, areas in addons:
        if cancelled is not None and cancelled():
            raise ProjectionCancelled
        for area in areas:
            if cancelled is not None and cancelled():
                raise ProjectionCancelled
            wanted = slots.addon_supply_position(
                addon.item_id,
                x=addon.x,
                y=addon.y,
                z=addon.z,
                yaw=addon.yaw,
                area=area.area,
            )
            target = projection.position(
                float(wanted[0]),
                float(wanted[1]),
                float(wanted[2]),
            )
            longitude, latitude = transformed(float(wanted[0]), float(wanted[1]))
            target_column = math.floor(longitude) % projection.band.columns
            target_row = math.floor(latitude)
            candidates = sorted(
                {
                    belt_position
                    for dx in range(-column_reach, column_reach + 1)
                    for dy in range(-row_reach, row_reach + 1)
                    for belt_position in belt_grid.get(
                        (
                            (target_column + dx) % projection.band.columns,
                            target_row + dy,
                        ),
                        (),
                    )
                }
            )
            supplied = False
            line_misses: list[tuple[float, int, float]] = []
            for belt_position in candidates:
                if cancelled is not None and cancelled():
                    raise ProjectionCancelled
                belt_point = projected_belt(belt_position)
                distance2 = (
                    (target[0] - belt_point[0]) ** 2
                    + (target[1] - belt_point[1]) ** 2
                    + (target[2] - belt_point[2]) ** 2
                )
                if distance2 >= radius2:
                    continue
                placed = belts[belt_position][1]
                neighbour_position = (
                    belt_position_by_index.get(placed.output_obj)
                    if placed.output_obj is not None
                    else None
                )
                if neighbour_position is None:
                    neighbour_position = predecessor_by_position.get(belt_position)
                if neighbour_position is None:
                    supplied = True
                    break
                line_distance = rules.addon_line_distance(
                    target,
                    belt_point,
                    projected_belt(neighbour_position),
                )
                if line_distance < rules.ADDON_LINE_MAX_DISTANCE:
                    supplied = True
                    break
                line_misses.append((distance2, belt_position, line_distance))
            if supplied:
                continue
            if line_misses:
                _distance2, belt_position, line_distance = min(line_misses)
                belt_index = belts[belt_position][0]
                return ProjectionFailure(
                    check="game.addon_supply",
                    buildings=(addon_index, belt_index),
                    detail=(
                        f"addon area {area.area} misses belt {belt_index}'s line by "
                        f"{line_distance:.4f} world units"
                    ),
                    band=projection.band.area_segments,
                )
            return ProjectionFailure(
                check="game.addon_supply",
                buildings=(addon_index,),
                detail=(
                    f"addon area {area.area} has no belt within "
                    f"{rules.ADDON_AREA_RADIUS} world unit"
                ),
                band=projection.band.area_segments,
            )
    return None


def projected_coater_keepout_boxes(
    coater: colliders.Placed,
    projection: planet.Projection,
) -> tuple[colliders.Box, ...]:
    """Materialize one Coater's exact projected lateral keepout boxes."""
    coater_boxes = colliders.target_boxes(
        coater,
        *projection.pose(coater.x, coater.y, coater.z, coater.yaw),
    )
    lateral_step = (1, 0) if round(coater.yaw) % 180 == 0 else (0, 1)
    lateral_arc = math.dist(
        projection.position(coater.x, coater.y, coater.z),
        projection.position(
            coater.x + lateral_step[0],
            coater.y + lateral_step[1],
            coater.z,
        ),
    )
    expanded: list[colliders.Box] = []
    for box in coater_boxes:
        half_x, half_y, half_z = box.half
        expanded_half = (
            (half_x + lateral_arc, half_y, half_z)
            if half_x <= half_z
            else (half_x, half_y, half_z + lateral_arc)
        )
        expanded.append(replace(box, half=expanded_half))
    return tuple(expanded)


def _projected_coater_keepout_overlaps(
    coater: colliders.Placed,
    splitter: colliders.Placed,
    projection: planet.Projection,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> bool:
    """Whether one Splitter enters one Coater's exact projected keepout."""
    coater_boxes = projected_coater_keepout_boxes(coater, projection)
    splitter_boxes = colliders.target_boxes(
        splitter,
        *projection.pose(
            splitter.x,
            splitter.y,
            splitter.z,
            splitter.yaw,
        ),
    )
    for coater_box in coater_boxes:
        if cancelled is not None and cancelled():
            raise ProjectionCancelled
        for splitter_box in splitter_boxes:
            if cancelled is not None and cancelled():
                raise ProjectionCancelled
            if colliders.obb_overlap(coater_box, splitter_box):
                return True
    return False


def projected_coater_splitter_failure(
    coater: tuple[int, colliders.Placed],
    splitter: tuple[int, colliders.Placed],
    projection: planet.Projection,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> ProjectionFailure | None:
    overlaps = (
        _projected_coater_keepout_overlaps(
            coater[1],
            splitter[1],
            projection,
        )
        if cancelled is None
        else _projected_coater_keepout_overlaps(
            coater[1],
            splitter[1],
            projection,
            cancelled=cancelled,
        )
    )
    if not overlaps:
        return None
    return ProjectionFailure(
        check="game.addon_splitter_clearance",
        buildings=(coater[0], splitter[0]),
        detail=(
            "Splitter connection body enters the Spray Coater projected lateral "
            "keepout"
        ),
        band=projection.band.area_segments,
    )

type _CoaterSplitterCoordinates = tuple[float, float, float]


@dataclass(frozen=True, slots=True)
class _CoaterSplitterKdPoint:
    position: int
    coordinates: _CoaterSplitterCoordinates


@dataclass(frozen=True, slots=True)
class _CoaterSplitterKdNode:
    point: _CoaterSplitterKdPoint
    lower: _CoaterSplitterCoordinates
    upper: _CoaterSplitterCoordinates
    left: _CoaterSplitterKdNode | None
    right: _CoaterSplitterKdNode | None


def _coater_splitter_point_distance2(
    left: _CoaterSplitterCoordinates,
    right: _CoaterSplitterCoordinates,
) -> float:
    return sum((a - b) ** 2 for a, b in zip(left, right, strict=True))


def _coater_splitter_box_distance2(
    point: _CoaterSplitterCoordinates,
    lower: _CoaterSplitterCoordinates,
    upper: _CoaterSplitterCoordinates,
) -> float:
    return sum(
        (lo - value) ** 2
        if value < lo
        else (value - hi) ** 2
        if value > hi
        else 0.0
        for value, lo, hi in zip(point, lower, upper, strict=True)
    )


def _coater_splitter_kd_tree(
    points: Sequence[_CoaterSplitterKdPoint],
    *,
    cancelled: Callable[[], bool] | None = None,
) -> _CoaterSplitterKdNode | None:
    """Build a balanced 3D range tree in ``O(S log S)`` preprocessing."""
    if not points:
        return None
    orders_list: list[tuple[_CoaterSplitterKdPoint, ...]] = []
    for axis in range(3):
        if cancelled is not None and cancelled():
            raise ProjectionCancelled
        orders_list.append(
            tuple(
                sorted(
                    points,
                    key=lambda point: (
                        point.coordinates[axis],
                        point.position,
                    ),
                )
            )
        )
    orders = tuple(orders_list)

    def build(
        ordered: tuple[tuple[_CoaterSplitterKdPoint, ...], ...],
        depth: int,
    ) -> _CoaterSplitterKdNode | None:
        if cancelled is not None and cancelled():
            raise ProjectionCancelled
        if not ordered[0]:
            return None
        axis = depth % 3
        axis_order = ordered[axis]
        middle = len(axis_order) // 2
        point = axis_order[middle]
        left_positions = {
            candidate.position for candidate in axis_order[:middle]
        }
        right_positions = {
            candidate.position for candidate in axis_order[middle + 1 :]
        }
        left = build(
            tuple(
                tuple(
                    candidate
                    for candidate in order
                    if candidate.position in left_positions
                )
                for order in ordered
            ),
            depth + 1,
        )
        right = build(
            tuple(
                tuple(
                    candidate
                    for candidate in order
                    if candidate.position in right_positions
                )
                for order in ordered
            ),
            depth + 1,
        )
        lower = list(point.coordinates)
        upper = list(point.coordinates)
        for child in (left, right):
            if cancelled is not None and cancelled():
                raise ProjectionCancelled
            if child is None:
                continue
            for coordinate in range(3):
                lower[coordinate] = min(
                    lower[coordinate],
                    child.lower[coordinate],
                )
                upper[coordinate] = max(
                    upper[coordinate],
                    child.upper[coordinate],
                )
        return _CoaterSplitterKdNode(
            point=point,
            lower=(lower[0], lower[1], lower[2]),
            upper=(upper[0], upper[1], upper[2]),
            left=left,
            right=right,
        )

    return build(orders, 0)


def _coater_splitter_kd_range(
    node: _CoaterSplitterKdNode | None,
    centre: _CoaterSplitterCoordinates,
    radius2: float,
    found: set[int],
    *,
    cancelled: Callable[[], bool] | None = None,
) -> None:
    """Report every indexed point inside one exact broad-phase sphere."""
    if cancelled is not None and cancelled():
        raise ProjectionCancelled
    if node is None or _coater_splitter_box_distance2(
        centre,
        node.lower,
        node.upper,
    ) > radius2:
        return
    if (
        _coater_splitter_point_distance2(
            centre,
            node.point.coordinates,
        )
        <= radius2
    ):
        found.add(node.point.position)
    for child in (node.left, node.right):
        if cancelled is None:
            _coater_splitter_kd_range(
                child,
                centre,
                radius2,
                found,
            )
        else:
            _coater_splitter_kd_range(
                child,
                centre,
                radius2,
                found,
                cancelled=cancelled,
            )


def _projected_coater_splitter_candidates(
    coaters: Sequence[tuple[int, colliders.Placed]],
    splitters: Sequence[tuple[int, colliders.Placed]],
    projection: planet.Projection,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[tuple[tuple[int, colliders.Placed], ...], ...]:
    """Conservative coater-to-Splitter candidates in exact input order.

    The exact rule expands each Coater OBB by one projected lateral grid arc.
    A sphere around that expanded OBB is therefore bounded by the immutable
    Coater model's collider radius plus that exact arc.  The Splitter uses the
    largest collider radius present in the index, admitting conservative false
    positives when a multi-level junction mixes models 38, 39, and 40.  As in
    :func:`planet.candidate_pairs`, the distance below
    is a lower bound: row spacing is fixed, column spacing uses the band's
    poleward minimum, and both arcs are reduced for chord curvature.  Thus a
    pair omitted here cannot reach the authoritative OBB predicate.

    A projection in quadrant 1 swaps blueprint axes before applying those
    spacings, and longitude wraps after ``band.columns`` cells.  Splitters are
    indexed once in a balanced three-dimensional range tree over periodic
    longitude, latitude, and level.  Each coater performs three seam-aware
    spherical range queries and only the radially possible positions reach the
    exact OBB predicate.  Sorting those original positions preserves Splitter
    order, including co-located and seam duplicates, without a density-dependent
    box-candidate product.
    """
    if cancelled is not None and cancelled():
        raise ProjectionCancelled
    if not coaters:
        return ()
    if not splitters:
        return tuple(() for _coater in coaters)

    latitude_step = planet.latitude_rad_per_grid(projection.segment)
    poleward = min(
        math.cos(
            min(
                abs(grid),
                planet.pole_grid_idx(projection.segment),
            )
            * latitude_step
        )
        for grid in (
            projection.band.grid_lo,
            projection.band.grid_hi,
        )
    )
    column_lower_bound = (
        projection.radius
        * poleward
        * planet.longitude_rad_per_grid(projection.band.area_segments)
        * 0.9
    )
    row_lower_bound = projection.radius * latitude_step * 0.9

    def transformed(building: colliders.Placed) -> tuple[float, float]:
        return (
            (building.y, building.x)
            if projection.rotated
            else (building.x, building.y)
        )

    coater_bounds: list[float] = []
    for _index, coater in coaters:
        if cancelled is not None and cancelled():
            raise ProjectionCancelled
        lateral_step = (
            (1, 0) if round(coater.yaw) % 180 == 0 else (0, 1)
        )
        lateral_arc = math.dist(
            projection.position(coater.x, coater.y, coater.z),
            projection.position(
                coater.x + lateral_step[0],
                coater.y + lateral_step[1],
                coater.z,
            ),
        )
        coater_bounds.append(
            planet.collider_radius(coater.model_index) + lateral_arc
        )
    splitter_bound = 0.0
    for _index, splitter in splitters:
        if cancelled is not None and cancelled():
            raise ProjectionCancelled
        splitter_bound = max(
            splitter_bound,
            planet.collider_radius(splitter.model_index),
        )

    def coordinates(building: colliders.Placed) -> _CoaterSplitterCoordinates:
        longitude, latitude = transformed(building)
        return (
            (longitude % projection.band.columns) * column_lower_bound,
            latitude * row_lower_bound,
            building.z * 4.0 / 3.0,
        )

    points: list[_CoaterSplitterKdPoint] = []
    for position, splitter_entry in enumerate(splitters):
        if cancelled is not None and cancelled():
            raise ProjectionCancelled
        points.append(
            _CoaterSplitterKdPoint(
                position=position,
                coordinates=coordinates(splitter_entry[1]),
            )
        )
    tree = (
        _coater_splitter_kd_tree(tuple(points))
        if cancelled is None
        else _coater_splitter_kd_tree(
            tuple(points),
            cancelled=cancelled,
        )
    )
    longitude_period = projection.band.columns * column_lower_bound
    candidates: list[tuple[tuple[int, colliders.Placed], ...]] = []
    for coater_entry, coater_bound in zip(coaters, coater_bounds, strict=True):
        if cancelled is not None and cancelled():
            raise ProjectionCancelled
        centre = coordinates(coater_entry[1])
        radius = coater_bound + splitter_bound
        radius2 = math.nextafter(radius * radius, math.inf)
        found: set[int] = set()
        for longitude in {
            centre[0] - longitude_period,
            centre[0],
            centre[0] + longitude_period,
        }:
            if cancelled is not None and cancelled():
                raise ProjectionCancelled
            if cancelled is None:
                _coater_splitter_kd_range(
                    tree,
                    (longitude, centre[1], centre[2]),
                    radius2,
                    found,
                )
            else:
                _coater_splitter_kd_range(
                    tree,
                    (longitude, centre[1], centre[2]),
                    radius2,
                    found,
                    cancelled=cancelled,
                )
        candidates.append(
            tuple(splitters[position] for position in sorted(found))
        )
    return tuple(candidates)




def _projected_addon_splitter_failure(
    coaters: Sequence[tuple[int, colliders.Placed]],
    splitters: Sequence[tuple[int, colliders.Placed]],
    projection: planet.Projection,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> ProjectionFailure | None:
    """Authoritative coater/splitter keepout from the broke2 in-game refusal."""
    candidates = (
        _projected_coater_splitter_candidates(
            coaters,
            splitters,
            projection,
        )
        if cancelled is None
        else _projected_coater_splitter_candidates(
            coaters,
            splitters,
            projection,
            cancelled=cancelled,
        )
    )
    for coater, peers in zip(coaters, candidates, strict=True):
        if cancelled is not None and cancelled():
            raise ProjectionCancelled
        for splitter in peers:
            if cancelled is not None and cancelled():
                raise ProjectionCancelled
            failure = (
                projected_coater_splitter_failure(
                    coater,
                    splitter,
                    projection,
                )
                if cancelled is None
                else projected_coater_splitter_failure(
                    coater,
                    splitter,
                    projection,
                    cancelled=cancelled,
                )
            )
            if failure is not None:
                return failure
    return None


def _projection_invariants(
    placement: Placement,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> _ProjectionInvariants:
    tested: list[tuple[int, colliders.Placed]] = []
    belts: list[tuple[int, PlacedBuilding]] = []
    addons: list[
        tuple[int, PlacedBuilding, tuple[catalog.AddonSupplyPose, ...]]
    ] = []
    coaters: list[tuple[int, colliders.Placed]] = []
    splitters: list[tuple[int, colliders.Placed]] = []
    for index, building in enumerate(placement.buildings):
        if cancelled is not None and cancelled():
            raise ProjectionCancelled
        is_belt = catalog.is_belt(building.item_id)
        is_sorter = catalog.is_sorter(building.item_id)
        if is_belt:
            belts.append((index, building))
        if not is_belt and not is_sorter:
            placed = _collision_placed(building)
            tested.append((index, placed))
            if building.item_id == catalog.SPRAY_COATER_ID:
                coaters.append((index, placed))
            elif building.item_id == catalog.SPLITTER_ID:
                splitters.append((index, placed))
        try:
            areas = catalog.building(building.item_id).addon_areas
        except KeyError:
            continue
        if len(areas) >= 2:
            addons.append((index, building, areas))
    if cancelled is None:
        nodes = _power_nodes(placement)
        sorters = _planet_sorters(placement)
    else:
        nodes = _power_nodes(placement, cancelled=cancelled)
        sorters = _planet_sorters(placement, cancelled=cancelled)
    return _ProjectionInvariants(
        tested=tuple(tested),
        nodes=nodes,
        sorters=sorters,
        belts=tuple(belts),
        addons=tuple(addons),
        coaters=tuple(coaters),
        splitters=tuple(splitters),
    )


def _failure_at_projection(
    invariants: _ProjectionInvariants,
    pairs: Sequence[tuple[int, int]],
    projection: planet.Projection,
    counters: _ProjectionCounters,
    *,
    cache: _ProjectionCache | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[ProjectionFailure, ...]:
    if cancelled is not None and cancelled():
        raise ProjectionCancelled
    counters.projections += 1
    failures: list[ProjectionFailure] = []
    use_cache = (
        cache is not None
        and (cancelled is None or cache.cancelled is cancelled)
    )
    if not use_cache:
        power_failure = (
            projected_power_failure(invariants.nodes, projection)
            if cancelled is None
            else projected_power_failure(
                invariants.nodes,
                projection,
                cancelled=cancelled,
            )
        )
        counters.power_pairs += _power_pairs_examined(
            invariants.nodes,
            power_failure,
            projection,
            cancelled=cancelled,
        )
    else:
        assert cache is not None
        power_failure = cache.power_failure(invariants.nodes, projection)
    if cancelled is not None and cancelled():
        raise ProjectionCancelled
    pair_key = tuple(pairs)
    if not use_cache:
        if cancelled is None:
            sorter_failure = _projected_sorter_failure(
                invariants.sorters,
                projection,
                counters=counters,
            )
            static_failure = _projected_static_failure(
                invariants.tested,
                pair_key,
                projection,
                counters=counters,
            )
            addon_failure = _projected_addon_failure(
                invariants.belts,
                invariants.addons,
                projection,
            )
            addon_splitter_failure = _projected_addon_splitter_failure(
                invariants.coaters,
                invariants.splitters,
                projection,
            )
        else:
            sorter_failure = _projected_sorter_failure(
                invariants.sorters,
                projection,
                counters=counters,
                cancelled=cancelled,
            )
            static_failure = _projected_static_failure(
                invariants.tested,
                pair_key,
                projection,
                counters=counters,
                cancelled=cancelled,
            )
            addon_failure = _projected_addon_failure(
                invariants.belts,
                invariants.addons,
                projection,
                cancelled=cancelled,
            )
            addon_splitter_failure = _projected_addon_splitter_failure(
                invariants.coaters,
                invariants.splitters,
                projection,
                cancelled=cancelled,
            )
    else:
        assert cache is not None
        sorter_failure = cache.sorter_failure(invariants.sorters, projection)
        static_failure = cache.static_failure(invariants.tested, pair_key, projection)
        addon_failure = cache.addon_failure(
            invariants.belts,
            invariants.addons,
            projection,
        )
        addon_splitter_failure = cache.addon_splitter_failure(
            invariants.coaters,
            invariants.splitters,
            projection,
        )
    if cancelled is not None and cancelled():
        raise ProjectionCancelled
    for failure in (
        power_failure,
        sorter_failure,
        static_failure,
        addon_failure,
        addon_splitter_failure,
    ):
        if failure is not None:
            failures.append(failure)
    return tuple(failures)


def _certify_frame(
    placement: Placement,
    frame: AreaFrame,
    counters: _ProjectionCounters,
    *,
    quadrant: int = 0,
    row_origin: int = 0,
    pair_rotated: bool = False,
    stop_after_failure: bool = False,
    cache: _ProjectionCache | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[ProjectionFailure, ...]:
    if cancelled is not None and cancelled():
        raise ProjectionCancelled
    active_cache = (
        cache
        if cache is not None
        and (cancelled is None or cache.cancelled is cancelled)
        else None
    )
    building_key = placement.buildings
    invariants = (
        None
        if active_cache is None
        else active_cache.invariants.get(building_key)
    )
    if invariants is None:
        invariants = (
            _projection_invariants(placement)
            if cancelled is None
            else _projection_invariants(placement, cancelled=cancelled)
        )
        if active_cache is not None:
            active_cache.invariants[building_key] = invariants
    else:
        counters.invariant_cache_hits += 1
    pair_buildings_list: list[colliders.Placed] = []
    for _index, building in invariants.tested:
        if cancelled is not None and cancelled():
            raise ProjectionCancelled
        pair_buildings_list.append(
            replace(building, x=building.y, y=building.x)
            if pair_rotated
            else building
        )
    pair_buildings = tuple(pair_buildings_list)
    by_segments = {band.area_segments: band for band in planet.bands()}
    pairs_by_band: dict[int, tuple[tuple[int, int], ...]] = {}
    failures: list[ProjectionFailure] = []
    for segments in frame.certified_bands:
        if cancelled is not None and cancelled():
            raise ProjectionCancelled
        band = by_segments[segments]
        pairs = pairs_by_band.get(segments)
        if pairs is None:
            pair_key = (building_key, segments, pair_rotated)
            pairs = (
                None
                if active_cache is None
                else active_cache.pairs.get(pair_key)
            )
            if pairs is None:
                if cancelled is None:
                    pairs = tuple(
                        planet.candidate_pairs(
                            pair_buildings,
                            band,
                            colliders.PLANET_SEGMENT,
                            colliders.PLANET_RADIUS,
                        )
                    )
                else:
                    pairs = tuple(
                        planet.candidate_pairs(
                            pair_buildings,
                            band,
                            colliders.PLANET_SEGMENT,
                            colliders.PLANET_RADIUS,
                            cancelled=cancelled,
                        )
                    )
                if active_cache is not None:
                    active_cache.pairs[pair_key] = pairs
            else:
                counters.pair_cache_hits += 1
            pairs_by_band[segments] = pairs
        for anchor in band.anchors(frame.height):
            if cancelled is not None and cancelled():
                raise ProjectionCancelled
            projection_key = (
                segments,
                frame.height,
                anchor - row_origin,
                quadrant,
            )
            projection = (
                None
                if active_cache is None
                else active_cache.projections.get(projection_key)
            )
            if projection is None:
                projection = planet.Projection(
                    band=band,
                    anchor_row=anchor - row_origin,
                    segment=colliders.PLANET_SEGMENT,
                    radius=colliders.PLANET_RADIUS,
                    quadrant=quadrant,
                )
                if active_cache is not None:
                    active_cache.projections[projection_key] = projection
            else:
                counters.projection_cache_hits += 1
            projection_failures = (
                _failure_at_projection(
                    invariants,
                    pairs,
                    projection,
                    counters,
                    cache=active_cache,
                )
                if cancelled is None
                else _failure_at_projection(
                    invariants,
                    pairs,
                    projection,
                    counters,
                    cache=active_cache,
                    cancelled=cancelled,
                )
            )
            if projection_failures:
                failures.extend(projection_failures)
                if stop_after_failure:
                    return projection_failures
    if cancelled is not None and cancelled():
        raise ProjectionCancelled
    return tuple(dict.fromkeys(failures))


def materialize_frame_building(
    building: PlacedBuilding,
    *,
    bounds: tuple[int, int, int, int],
    candidate: FrameCandidate,
    prior_rotated: bool = False,
) -> PlacedBuilding:
    """Apply the finalizer's exact frame transform to one building."""
    min_x, min_y, _max_x, max_y = bounds
    relative_rotation = prior_rotated ^ candidate.frame.rotated
    if relative_rotation:
        height = max_y - min_y + 1
        materialized = replace(
            building,
            x=height - (building.y - min_y + building.height),
            y=building.x - min_x,
            width=building.height,
            height=building.width,
            yaw=(building.yaw - 90.0) % 360.0,
            x2=(
                None
                if building.x2 is None or building.y2 is None
                else height - 1 - (building.y2 - min_y)
            ),
            y2=None if building.x2 is None else building.x2 - min_x,
            yaw2=(
                None
                if building.yaw2 is None
                else (building.yaw2 - 90.0) % 360.0
            ),
        )
    else:
        materialized = replace(
            building,
            x=building.x - min_x,
            y=building.y - min_y,
            x2=None if building.x2 is None else building.x2 - min_x,
            y2=None if building.y2 is None else building.y2 - min_y,
        )
    if candidate.south_padding:
        materialized = replace(
            materialized,
            y=materialized.y + candidate.south_padding,
            y2=(
                None
                if materialized.y2 is None
                else materialized.y2 + candidate.south_padding
            ),
        )
    return materialized


def target_bands(
    primary: planet.Band,
    policy: BandPolicy,
) -> tuple[planet.Band, ...]:
    """Bands required by ``policy``, starting at the fixed primary band."""
    if policy.explicit_segments is not None:
        return (primary,)
    ordered = tuple(sorted(planet.bands(), key=lambda band: band.area_segments))
    start = ordered.index(primary)
    return ordered[start : start + 3]


_PROJECTION_VARIANT_PERIMETER = 3


@cache
def _adjacent_machine_collides_in_band(
    item_id: int,
    yaw: float,
    pitch_x: int,
    *,
    rotated: bool,
    band_segments: int,
) -> bool:
    """Whether one repeated-machine relation fails anywhere in one exact band."""
    info = catalog.building(item_id)
    width, height = catalog.oriented_footprint(item_id, yaw)
    if rotated:
        left = PlacedBuilding(
            item_id=item_id,
            model_index=info.model_index,
            x=0,
            y=0,
            width=height,
            height=width,
            yaw=(yaw - 90.0) % 360.0,
        )
        right = replace(left, y=pitch_x)
        pair_height = pitch_x + width
    else:
        left = PlacedBuilding(
            item_id=item_id,
            model_index=info.model_index,
            x=0,
            y=0,
            width=width,
            height=height,
            yaw=yaw,
        )
        right = replace(left, x=pitch_x)
        pair_height = height
    placed = (_collision_placed(left), _collision_placed(right))
    band = next(
        candidate
        for candidate in planet.bands()
        if candidate.area_segments == band_segments
    )
    return any(
        planet.collisions_at(
            placed,
            planet.Projection(
                band=band,
                anchor_row=anchor,
                segment=colliders.PLANET_SEGMENT,
                radius=colliders.PLANET_RADIUS,
            ),
            ((0, 1),),
        )
        for anchor in band.anchors(pair_height)
    )


def _projection_pitch_contexts(
    width: int,
    height: int,
    policy: BandPolicy,
) -> tuple[tuple[bool, int], ...]:
    """Every orientation/band a containing exact candidate may certify."""
    ordered = tuple(sorted(planet.bands(), key=lambda band: band.area_segments))
    primaries = (
        tuple(
            band
            for band in ordered
            if band.area_segments == policy.explicit_segments
        )
        if policy.explicit_segments is not None
        else ordered
    )
    contexts: set[tuple[bool, int]] = set()
    for primary in primaries:
        for rotated, (columns, rows) in (
            (False, (width, height)),
            (True, (height, width)),
        ):
            if columns > primary.columns or rows > primary.rows:
                continue
            contexts.update(
                (rotated, band.area_segments)
                for band in target_bands(primary, policy)
            )
    return tuple(sorted(contexts, key=lambda context: (context[1], context[0])))


@cache
def projection_safe_machine_pitch_x(
    machine_item_id: str | int,
    yaw: float,
    *,
    machine_count: int,
    box_height: int,
    perimeter: int = _PROJECTION_VARIANT_PERIMETER,
    policy: BandPolicy | None = None,
) -> int:
    """Return the first adjacent-machine pitch safe in every reachable frame.

    Physical strip variants are chosen before packing fixes the final extent.
    Their own box plus the shared entry perimeter therefore defines the smallest
    containing candidate.  Unrelated packed geometry may promote that candidate
    to any wider primary band, so portable selection must cover the union of
    every such primary's certified bands and both fitting frame orientations.
    Every legal latitude translation is tested with the finalizer's exact
    collider projection.  If no padded envelope fits at all, retain the catalog
    pitch and let the unchanged extent gate/finalizer report the refusal.
    """
    if type(machine_count) is not int or machine_count <= 0:
        raise ValueError("machine count must be a positive integer")
    if type(box_height) is not int or box_height <= 0:
        raise ValueError("strip box height must be a positive integer")
    if type(perimeter) is not int or perimeter < 0:
        raise ValueError("projection perimeter must be a non-negative integer")
    item_id = (
        catalog.item_id(machine_item_id)
        if isinstance(machine_item_id, str)
        else machine_item_id
    )
    pitch_x = catalog.clearance(item_id, yaw)[0]
    if machine_count == 1:
        return pitch_x
    active_policy = BandPolicy("portable") if policy is None else policy
    maximum_pitch = max(
        max(band.columns, band.rows) for band in planet.bands()
    )
    for candidate_pitch in range(pitch_x, maximum_pitch + 1):
        contexts = _projection_pitch_contexts(
            machine_count * candidate_pitch + 2 * perimeter,
            box_height + 2 * perimeter,
            active_policy,
        )
        if not contexts:
            break
        if all(
            not _adjacent_machine_collides_in_band(
                item_id,
                yaw,
                candidate_pitch,
                rotated=rotated,
                band_segments=band_segments,
            )
            for rotated, band_segments in contexts
        ):
            return candidate_pitch
    return pitch_x


def _primary_band_for_extent(
    width: int,
    height: int,
    policy: BandPolicy,
) -> planet.Band | None:
    explicit = policy.explicit_segments
    if explicit is not None:
        return next(
            band for band in planet.bands() if band.area_segments == explicit
        )
    try:
        return planet.band_for_extent(width, height).band
    except planet.BandRefusal:
        return None


def _frame_candidate_for_primary(
    width: int,
    height: int,
    policy: BandPolicy,
    primary: planet.Band,
    *,
    prior_rotated: bool,
    rotated: bool,
    south_padding: int,
    north_padding: int,
) -> FrameCandidate | None:
    if south_padding < 0 or north_padding < 0:
        raise ValueError("latitude padding must be non-negative")
    columns, content_rows = (height, width) if rotated else (width, height)
    added_rows = south_padding + north_padding
    rows = content_rows + added_rows
    if columns > primary.columns or rows > primary.rows:
        return None
    required = target_bands(primary, policy)
    return FrameCandidate(
        frame=AreaFrame(
            width=columns,
            height=rows,
            primary_band=primary.area_segments,
            certified_bands=tuple(band.area_segments for band in required),
            rotated=prior_rotated ^ rotated,
        ),
        south_padding=south_padding,
        added_rows=added_rows,
    )


@cache
def _frame_candidates_for_extent(
    width: int,
    height: int,
    policy: BandPolicy,
    *,
    prior_rotated: bool = False,
) -> tuple[FrameCandidate, ...]:
    """Apply the finalizer's one frame convention to an exact content extent."""
    primary = _primary_band_for_extent(width, height, policy)
    if primary is None:
        return ()
    candidates: list[FrameCandidate] = []
    for rotated in (False, True):
        for added_rows in range(5):
            for south_padding in range(added_rows + 1):
                candidate = _frame_candidate_for_primary(
                    width,
                    height,
                    policy,
                    primary,
                    prior_rotated=prior_rotated,
                    rotated=rotated,
                    south_padding=south_padding,
                    north_padding=added_rows - south_padding,
                )
                if candidate is not None:
                    candidates.append(candidate)
    return tuple(
        sorted(
            candidates,
            key=lambda candidate: (
                candidate.frame.width * candidate.frame.height,
                candidate.added_rows,
                candidate.frame.rotated,
                candidate.south_padding,
            ),
        )
    )


def frame_candidates(
    placement: Placement,
    policy: BandPolicy,
) -> tuple[FrameCandidate, ...]:
    """Enumerate every approved frame in deterministic minimum-area order."""
    min_x, min_y, max_x, max_y = placement.bounds
    return _frame_candidates_for_extent(
        max_x - min_x + 1,
        max_y - min_y + 1,
        policy,
        prior_rotated=(
            placement.frame.rotated if placement.frame is not None else False
        ),
    )


def _materialize_frame(
    placement: Placement,
    candidate: FrameCandidate,
) -> Placement:
    prior_rotated = placement.frame.rotated if placement.frame is not None else False
    bounds = placement.bounds
    return replace(
        placement,
        buildings=tuple(
            materialize_frame_building(
                building,
                bounds=bounds,
                candidate=candidate,
                prior_rotated=prior_rotated,
            )
            for building in placement.buildings
        ),
        frame=candidate.frame,
    )


_PAIR_PROOF_MAX_CASES = 250_000


def independent_projection_pair(
    pair: tuple[tuple[int, PlacedBuilding], tuple[int, PlacedBuilding]],
    policy: BandPolicy,
) -> tuple[int, int] | None:
    """Prove a pair collision without consulting unrelated placement bounds.

    The cut conditions only the compact pack and two physical strip records,
    while routing may expand the outer content bounds.  This proof therefore
    over-approximates every translation, orientation, containing frame size,
    certified band, latitude anchor, and padding row reachable anywhere in an
    authoritative band.  If the finite proof would be too large, no smaller cut
    is emitted and the caller retains the full exact assignment.
    """
    if (
        len(pair) != 2
        or pair[0][0] == pair[1][0]
        or any(
            catalog.is_belt(building.item_id)
            or catalog.is_sorter(building.item_id)
            for _index, building in pair
        )
    ):
        return None
    indices = (pair[0][0], pair[1][0])
    bands = (
        tuple(
            band
            for band in planet.bands()
            if band.area_segments == policy.explicit_segments
        )
        if policy.explicit_segments is not None
        else planet.bands()
    )
    if not bands:
        return None

    cases: list[
        tuple[
            tuple[tuple[int, colliders.Placed], tuple[int, colliders.Placed]],
            int,
            int,
            planet.Band,
            tuple[int, ...],
        ]
    ] = []
    case_count = 0
    for rotated in (False, True):
        oriented = tuple(
            (
                index,
                (
                    replace(
                        building,
                        x=-(building.y + building.height),
                        y=building.x,
                        width=building.height,
                        height=building.width,
                        yaw=(building.yaw - 90.0) % 360.0,
                    )
                    if rotated
                    else building
                ),
            )
            for index, building in pair
        )
        min_x = min(building.x for _index, building in oriented)
        min_y = min(building.y for _index, building in oriented)
        normalized = cast(
            tuple[
                tuple[int, colliders.Placed],
                tuple[int, colliders.Placed],
            ],
            tuple(
                (
                    index,
                    _collision_placed(
                        replace(
                            building,
                            x=building.x - min_x,
                            y=building.y - min_y,
                        )
                    ),
                )
                for index, building in oriented
            ),
        )
        pair_width = max(
            building.x + building.width for _index, building in oriented
        ) - min(building.x for _index, building in oriented)
        pair_height = max(
            building.y + building.height for _index, building in oriented
        ) - min(building.y for _index, building in oriented)
        # The outer content bounds are not part of the cut.  Using the full
        # authoritative band capacity covers the union of every containing
        # frame size and every row translation that unrelated routed tiles can
        # induce.  A shared column translation is exactly a rigid rotation
        # around the planet's polar axis, so x=0 represents every column.
        # Anchors likewise cover every feasible frame height.
        for band in bands:
            x_count = 1 if pair_width <= band.columns else 0
            y_count = band.rows - pair_height + 1
            if x_count <= 0 or y_count <= 0:
                continue
            anchors = tuple(
                sorted(
                    {
                        anchor
                        for frame_height in range(1, band.rows + 1)
                        for anchor in band.anchors(frame_height)
                    }
                )
            )
            case_count += x_count * y_count * len(anchors)
            if case_count > _PAIR_PROOF_MAX_CASES:
                return None
            cases.append((normalized, x_count, y_count, band, anchors))

    if not cases:
        return None
    for normalized, x_count, y_count, band, anchors in cases:
        for x in range(x_count):
            for y in range(y_count):
                tested = tuple(
                    (
                        index,
                        replace(
                            placed,
                            x=placed.x + x,
                            y=placed.y + y,
                        ),
                    )
                    for index, placed in normalized
                )
                for anchor in anchors:
                    exact = _projected_static_failure(
                        tested,
                        ((0, 1),),
                        planet.Projection(
                            band=band,
                            anchor_row=anchor,
                            segment=colliders.PLANET_SEGMENT,
                            radius=colliders.PLANET_RADIUS,
                        ),
                    )
                    if exact is None or exact.buildings != indices:
                        return None
    return indices


def _frame_content_valid(placement: Placement) -> bool:
    frame = placement.frame
    if frame is None:
        return False
    if tuple(dict.fromkeys(frame.certified_bands)) != frame.certified_bands:
        return False
    by_segments = {band.area_segments: band for band in planet.bands()}
    if any(segments not in by_segments for segments in frame.certified_bands):
        return False
    if any(
        frame.width > by_segments[segments].columns
        or frame.height > by_segments[segments].rows
        for segments in frame.certified_bands
    ):
        return False
    for building in placement.buildings:
        if (
            building.width <= 0
            or building.height <= 0
            or building.x < 0
            or building.y < 0
            or building.x + building.width > frame.width
            or building.y + building.height > frame.height
        ):
            return False
        if building.x2 is not None:
            second_y = building.y2 if building.y2 is not None else 0
            if (
                building.x2 < 0
                or building.x2 >= frame.width
                or second_y < 0
                or second_y >= frame.height
            ):
                return False
    left, bottom, right, top = placement.bounds
    return (
        left == 0
        and right == frame.width - 1
        and bottom >= 0
        and top < frame.height
        and bottom + (frame.height - top - 1) <= 4
    )


def _frame_satisfies_policy(
    placement: Placement,
    policy: BandPolicy,
) -> bool:
    if not _frame_content_valid(placement):
        return False
    frame = placement.frame
    assert frame is not None
    explicit = policy.explicit_segments
    if explicit is not None:
        return (
            frame.primary_band == explicit
            and frame.certified_bands == (explicit,)
        )
    min_x, min_y, max_x, max_y = placement.bounds
    try:
        primary = planet.band_for_extent(
            max_x - min_x + 1,
            max_y - min_y + 1,
        ).band
    except planet.BandRefusal:
        return False
    required = tuple(
        band.area_segments for band in target_bands(primary, policy)
    )
    return (
        frame.primary_band == primary.area_segments
        and frame.certified_bands == required
    )


def _with_projection_stats(
    placement: Placement,
    counters: _ProjectionCounters,
) -> Placement:
    stats = placement.stats.copy()
    stats["projection_frame_candidates"] = counters.frame_candidates
    stats["projection_count"] = counters.projections
    stats["projection_collider_pairs"] = counters.collider_pairs
    stats["projection_power_pairs"] = counters.power_pairs
    stats["projection_sorters"] = counters.sorters
    cache_stats = cast(dict[str, float], cast(object, stats))
    cache_stats["projection_invariant_cache_hits"] = counters.invariant_cache_hits
    cache_stats["projection_pair_cache_hits"] = counters.pair_cache_hits
    cache_stats["projection_object_cache_hits"] = counters.projection_cache_hits
    cache_stats["projection_sorter_result_cache_hits"] = (
        counters.sorter_result_cache_hits
    )
    cache_stats["projection_static_result_cache_hits"] = (
        counters.static_result_cache_hits
    )
    cache_stats["projection_power_result_cache_hits"] = (
        counters.power_result_cache_hits
    )
    cache_stats["projection_addon_result_cache_hits"] = (
        counters.addon_result_cache_hits
    )
    cache_stats["projection_addon_splitter_result_cache_hits"] = (
        counters.addon_splitter_result_cache_hits
    )
    return replace(placement, stats=stats)


def _extent_failure_for_dimensions(
    width: int,
    height: int,
    policy: BandPolicy,
) -> ProjectionFailure:
    """Build the finalizer's structured extent refusal from exact dimensions."""
    explicit = policy.explicit_segments
    if explicit is not None:
        band = next(
            candidate
            for candidate in planet.bands()
            if candidate.area_segments == explicit
        )
        return ProjectionFailure(
            check="game.blueprint_area",
            buildings=(),
            detail=(
                f"frame {width}x{height} exceeds the requested band's "
                f"{band.columns}x{band.rows} capacity"
            ),
            band=explicit,
        )
    try:
        _ = planet.band_for_extent(width, height)
    except planet.BandRefusal as exc:
        return ProjectionFailure(
            check="game.blueprint_area",
            buildings=(),
            detail=str(exc),
            band=0,
        )
    raise AssertionError("extent failure requested for geometry with a fitting band")


def _extent_failure(
    placement: Placement,
    policy: BandPolicy,
) -> ProjectionFailure:
    min_x, min_y, max_x, max_y = placement.bounds
    return _extent_failure_for_dimensions(
        max_x - min_x + 1,
        max_y - min_y + 1,
        policy,
    )




def finalize_placement(
    placement: Placement,
    policy: BandPolicy,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> Placement:
    """Certify one placement against its required latitude-band policy."""
    if cancelled is not None and cancelled():
        raise ProjectionCancelled
    if placement.frame is not None and _frame_satisfies_policy(placement, policy):
        return placement

    candidates = frame_candidates(placement, policy)
    if not candidates:
        raise ProjectionRefusal((_extent_failure(placement, policy),))
    counters = _ProjectionCounters()
    cache = _ProjectionCache(counters, cancelled=cancelled)
    rejected_frames: list[tuple[Placement, AreaFrame]] = []
    for candidate in candidates:
        if cancelled is not None and cancelled():
            raise ProjectionCancelled
        counters.frame_candidates += 1
        framed = _materialize_frame(placement, candidate)
        candidate_failures = _certify_frame(
            framed,
            candidate.frame,
            counters,
            stop_after_failure=True,
            cache=cache,
            cancelled=cancelled,
        )
        if candidate_failures:
            rejected_frames.append((framed, candidate.frame))
            continue
        if cancelled is not None and cancelled():
            raise ProjectionCancelled
        return _with_projection_stats(framed, counters)

    failures: list[ProjectionFailure] = []
    for framed, frame in rejected_frames:
        if cancelled is not None and cancelled():
            raise ProjectionCancelled
        failures.extend(
            _certify_frame(
                framed,
                frame,
                counters,
                stop_after_failure=False,
                cache=cache,
                cancelled=cancelled,
            )
        )
    raise ProjectionRefusal(failures)


def _remove_buildings(
    placement: Placement,
    removed: frozenset[int],
    *,
    cancelled: Callable[[], bool] | None = None,
) -> Placement:
    """Remove indices, bypass their links, and rewrite every surviving reference."""
    if cancelled is not None and cancelled():
        raise ProjectionCancelled
    if not removed:
        return placement
    size = len(placement.buildings)
    if any(index < 0 or index >= size for index in removed):
        raise ValueError("removed building indices must belong to the placement")
    if len(removed) == size:
        return placement

    mapping: dict[int, int] = {}
    for old in range(size):
        if cancelled is not None and cancelled():
            raise ProjectionCancelled
        if old not in removed:
            mapping[old] = len(mapping)

    def remap(value: int | None, direction: _Direction) -> int | None:
        seen: set[int] = set()
        while value is not None and value in removed and value not in seen:
            if cancelled is not None and cancelled():
                raise ProjectionCancelled
            seen.add(value)
            building = placement.buildings[value]
            value = building.output_obj if direction == "output" else building.input_obj
        return mapping.get(value) if value is not None else None

    surviving: list[PlacedBuilding] = []
    for index, building in enumerate(placement.buildings):
        if cancelled is not None and cancelled():
            raise ProjectionCancelled
        if index in removed:
            continue
        surviving.append(
            replace(
                building,
                output_obj=remap(building.output_obj, "output"),
                input_obj=remap(building.input_obj, "input"),
            )
        )
    candidate = replace(
        placement,
        buildings=tuple(surviving),
        frame=None,
        completion=None,
    )
    stats = placement.stats.copy()
    if "area" in stats:
        stats["area"] = float(candidate.area)
    if "belt_tiles" in stats:
        belt_tiles = stats["belt_tiles"]
        stats["belt_tiles"] = float(belt_tiles) - len(removed)
    if cancelled is not None and cancelled():
        raise ProjectionCancelled
    return replace(candidate, stats=stats)


def _prunable_open_belts(
    placement: Placement,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> frozenset[int]:
    """Unreferenced outer belt leaves that can be removed as one structural wave."""
    buildings = placement.buildings
    belts: set[int] = set()
    for index, building in enumerate(buildings):
        if cancelled is not None and cancelled():
            raise ProjectionCancelled
        if catalog.is_belt(building.item_id):
            belts.add(index)
    predecessors: dict[int, set[int]] = {index: set() for index in belts}
    for index in belts:
        if cancelled is not None and cancelled():
            raise ProjectionCancelled
        target = buildings[index].output_obj
        if target in belts:
            predecessors[target].add(index)
    nonbelt_references: set[int] = set()
    for index, building in enumerate(buildings):
        if cancelled is not None and cancelled():
            raise ProjectionCancelled
        if index in belts:
            continue
        for target in (building.input_obj, building.output_obj):
            if cancelled is not None and cancelled():
                raise ProjectionCancelled
            if target in belts:
                assert target is not None
                nonbelt_references.add(target)
    left, bottom, right, top = placement.bounds
    selected: set[int] = set()
    for index in belts:
        if cancelled is not None and cancelled():
            raise ProjectionCancelled
        building = buildings[index]
        successor = building.output_obj if building.output_obj in belts else None
        neighbours = len(predecessors[index]) + int(successor is not None)
        open_end = not predecessors[index] or successor is None
        outer = (
            building.x == left
            or building.x + building.width - 1 == right
            or building.y == bottom
            or building.y + building.height - 1 == top
        )
        protected = index in nonbelt_references or bool(building.parameters)
        if outer and open_end and not protected and neighbours <= 1:
            selected.add(index)
    return frozenset(selected)


def _boundary_open_belts(
    placement: Placement,
    side: _Side,
    *,
    protected_roots: frozenset[int] = _NO_PROTECTED_ROOTS,
    cancelled: Callable[[], bool] | None = None,
) -> frozenset[int]:
    """Open belts on one current bounding side for the certified fallback."""
    left, bottom, right, top = placement.bounds
    selected: set[int] = set()
    for index, building in enumerate(placement.buildings):
        if cancelled is not None and cancelled():
            raise ProjectionCancelled
        if (
            index not in protected_roots
            and catalog.is_belt(building.item_id)
            and (building.input_obj is None or building.output_obj is None)
            and (
                (side == "left" and building.x == left)
                or (side == "bottom" and building.y == bottom)
                or (side == "right" and building.x + building.width - 1 == right)
                or (side == "top" and building.y + building.height - 1 == top)
            )
        ):
            selected.add(index)
    return frozenset(selected)


def _required_external_input_boundary_roots(
    placement: Placement,
    spec: BuildSpec,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> frozenset[int]:
    """Find required player-fed roots from the emitted graph and build spec."""
    belts: list[bool] = []
    for building in placement.buildings:
        if cancelled is not None and cancelled():
            raise ProjectionCancelled
        belts.append(catalog.is_belt(building.item_id))
    incoming: set[int] = set()
    connected: set[int] = set()
    for source, building in enumerate(placement.buildings):
        if cancelled is not None and cancelled():
            raise ProjectionCancelled
        for target in (building.input_obj, building.output_obj):
            if target is None or not 0 <= target < len(belts):
                continue
            if belts[source]:
                connected.add(source)
            if belts[target]:
                connected.add(target)
        target = building.output_obj
        if (
            belts[source]
            and target is not None
            and 0 <= target < len(belts)
            and belts[target]
        ):
            incoming.add(target)
    left, bottom, right, top = placement.bounds
    roots: set[int] = set()
    for index, building in enumerate(placement.buildings):
        if cancelled is not None and cancelled():
            raise ProjectionCancelled
        if (
            belts[index]
            and index not in incoming
            and index in connected
            and building.carries_item in spec.external_inputs
            and (
                building.x == left
                or building.y == bottom
                or building.x + building.width - 1 == right
                or building.y + building.height - 1 == top
            )
        ):
            roots.add(index)
    return frozenset(roots)


@dataclass(slots=True)
class _CleanupOperations:
    """Aggregate work shared by immutable cleanup-prefix snapshots."""

    node_visits: int = 0
    edge_visits: int = 0
    coordinate_visits: int = 0


class _CleanupSurvivorGraph:
    """Event-driven form of the cleanup wave fixed point.

    Active belt records are graph vertices.  A belt output contributes one
    predecessor edge to the first active belt reached by following removed
    outputs; non-belt references contribute protection in the same way.
    Removing a wave contracts those reference chains.  Counts and linked owner
    bags move across each contraction once, while four coordinate indexes wake
    belts only when they become part of the active bounding rectangle.
    """

    _COORDINATE_MIN = -(1 << 63)
    _COORDINATE_MAX = (1 << 63) - 1
    _EXTERNAL = -1

    def __init__(
        self,
        placement: Placement,
        *,
        cancelled: Callable[[], bool] | None = None,
        _operations: _CleanupOperations | None = None,
        _include_boundary_open: bool = True,
        _protected_roots: frozenset[int] = _NO_PROTECTED_ROOTS,
    ) -> None:
        self.buildings = placement.buildings
        self.cancelled = cancelled
        self._operations = _operations or _CleanupOperations()
        self.include_boundary_open = _include_boundary_open
        self.protected_roots: frozenset[int] = _protected_roots
        self.active = [True] * len(self.buildings)
        self.active_count = len(self.buildings)
        self.belts: list[bool] = []
        for building in self.buildings:
            self._poll()
            self.node_visits += 1
            self.belts.append(catalog.is_belt(building.item_id))

        self.input_jump = [building.input_obj for building in self.buildings]
        self.output_jump = [building.output_obj for building in self.buildings]
        self.remapped_once = False
        size = len(self.buildings)
        self.predecessors = [0] * size
        self.nonbelt_input = [0] * size
        self.nonbelt_output = [0] * size
        self.input_head: list[int | None] = [None] * size
        self.input_tail: list[int | None] = [None] * size
        self.input_next: list[int | None] = [None] * size
        self.output_head: list[int | None] = [None] * size
        self.output_tail: list[int | None] = [None] * size
        self.output_next: list[int | None] = [None] * size
        self.external_input_sources: list[int] = []
        self.external_output_sources: list[int] = []

        for source, building in enumerate(self.buildings):
            self._poll()
            references: tuple[tuple[_Direction, int | None], ...] = (
                ("input", building.input_obj),
                ("output", building.output_obj),
            )
            for direction, target in references:
                self.edge_visits += 1
                if self.belts[source]:
                    if target is not None and 0 <= target < size and self.belts[target]:
                        self._append_owner(direction, target, source)
                        if direction == "output":
                            self.predecessors[target] += 1
                    elif target is not None and not 0 <= target < size:
                        external = (
                            self.external_input_sources
                            if direction == "input"
                            else self.external_output_sources
                        )
                        external.append(source)
                elif target is not None and 0 <= target < size and self.belts[target]:
                    protected = (
                        self.nonbelt_input
                        if direction == "input"
                        else self.nonbelt_output
                    )
                    protected[target] += 1

        self.left_records: dict[int, list[int]] = {}
        self.bottom_records: dict[int, list[int]] = {}
        self.right_records: dict[int, list[int]] = {}
        self.top_records: dict[int, list[int]] = {}
        self.left_counts: dict[int, int] = {}
        self.bottom_counts: dict[int, int] = {}
        self.right_counts: dict[int, int] = {}
        self.top_counts: dict[int, int] = {}
        for index, building in enumerate(self.buildings):
            self._poll()
            right = building.x + building.width - 1
            top = building.y + building.height - 1
            for coordinate, records, counts in (
                (building.x, self.left_records, self.left_counts),
                (building.y, self.bottom_records, self.bottom_counts),
                (right, self.right_records, self.right_counts),
                (top, self.top_records, self.top_counts),
            ):
                records.setdefault(coordinate, []).append(index)
                counts[coordinate] = counts.get(coordinate, 0) + 1
        self.left_coordinates = self._ordered_coordinates(self.left_counts)
        self.bottom_coordinates = self._ordered_coordinates(self.bottom_counts)
        self.right_coordinates = self._ordered_coordinates(
            self.right_counts,
            reverse=True,
        )
        self.top_coordinates = self._ordered_coordinates(
            self.top_counts,
            reverse=True,
        )
        self.left_position = 0
        self.bottom_position = 0
        self.right_position = 0
        self.top_position = 0

    @property
    def node_visits(self) -> int:
        return self._operations.node_visits

    @node_visits.setter
    def node_visits(self, value: int) -> None:
        self._operations.node_visits = value

    @property
    def edge_visits(self) -> int:
        return self._operations.edge_visits

    @edge_visits.setter
    def edge_visits(self, value: int) -> None:
        self._operations.edge_visits = value

    @property
    def coordinate_visits(self) -> int:
        return self._operations.coordinate_visits

    @coordinate_visits.setter
    def coordinate_visits(self, value: int) -> None:
        self._operations.coordinate_visits = value

    def _ordered_coordinates(
        self,
        counts: Mapping[int, int],
        *,
        reverse: bool = False,
    ) -> list[int]:
        """Order validated signed-64 coordinates in eight cancellable radix passes."""
        values: list[int] = []
        for value in counts:
            self._poll()
            self.coordinate_visits += 1
            if not self._COORDINATE_MIN <= value <= self._COORDINATE_MAX:
                raise ValueError("cleanup coordinates must fit a signed 64-bit integer")
            values.append(value)
        if len(values) < 2:
            return values
        for shift in range(0, 64, 8):
            buckets: list[list[int]] = []
            for _bucket in range(256):
                self._poll()
                self.coordinate_visits += 1
                buckets.append([])
            for value in values:
                self._poll()
                self.coordinate_visits += 1
                unsigned = value - self._COORDINATE_MIN
                buckets[(unsigned >> shift) & 0xFF].append(value)
            ordered: list[int] = []
            for bucket in buckets:
                self._poll()
                self.coordinate_visits += 1
                for value in bucket:
                    self._poll()
                    self.coordinate_visits += 1
                    ordered.append(value)
            values = ordered
        if reverse:
            descending: list[int] = []
            for value in reversed(values):
                self._poll()
                self.coordinate_visits += 1
                descending.append(value)
            values = descending
        return values

    def _fork(self) -> _CleanupSurvivorGraph:
        """Copy mutable cleanup state while sharing its aggregate work counter."""
        fork = object.__new__(type(self))
        fork.buildings = self.buildings
        fork.cancelled = self.cancelled
        fork._operations = self._operations
        fork.include_boundary_open = self.include_boundary_open
        fork.protected_roots = self.protected_roots
        fork.active = self.active.copy()
        fork.active_count = self.active_count
        fork.belts = self.belts.copy()
        fork.input_jump = self.input_jump.copy()
        fork.output_jump = self.output_jump.copy()
        fork.remapped_once = self.remapped_once
        fork.predecessors = self.predecessors.copy()
        fork.nonbelt_input = self.nonbelt_input.copy()
        fork.nonbelt_output = self.nonbelt_output.copy()
        fork.input_head = self.input_head.copy()
        fork.input_tail = self.input_tail.copy()
        fork.input_next = self.input_next.copy()
        fork.output_head = self.output_head.copy()
        fork.output_tail = self.output_tail.copy()
        fork.output_next = self.output_next.copy()
        fork.external_input_sources = self.external_input_sources.copy()
        fork.external_output_sources = self.external_output_sources.copy()
        fork.left_records = {
            coordinate: records.copy()
            for coordinate, records in self.left_records.items()
        }
        fork.bottom_records = {
            coordinate: records.copy()
            for coordinate, records in self.bottom_records.items()
        }
        fork.right_records = {
            coordinate: records.copy()
            for coordinate, records in self.right_records.items()
        }
        fork.top_records = {
            coordinate: records.copy()
            for coordinate, records in self.top_records.items()
        }
        fork.left_counts = self.left_counts.copy()
        fork.bottom_counts = self.bottom_counts.copy()
        fork.right_counts = self.right_counts.copy()
        fork.top_counts = self.top_counts.copy()
        fork.left_coordinates = self.left_coordinates.copy()
        fork.bottom_coordinates = self.bottom_coordinates.copy()
        fork.right_coordinates = self.right_coordinates.copy()
        fork.top_coordinates = self.top_coordinates.copy()
        fork.left_position = self.left_position
        fork.bottom_position = self.bottom_position
        fork.right_position = self.right_position
        fork.top_position = self.top_position
        return fork

    def extended(
        self,
        additions: Sequence[PlacedBuilding],
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> _CleanupSurvivorGraph:
        """Return an immutable-prefix extension without rescanning prefix edges."""
        extended = self._fork()
        extended.cancelled = cancelled if cancelled is not None else self.cancelled
        old_size = len(extended.buildings)
        additions = tuple(additions)
        extended.buildings += additions
        extended.active.extend(True for _building in additions)
        extended.active_count += len(additions)
        for building in additions:
            extended._poll()
            extended.node_visits += 1
            extended.belts.append(catalog.is_belt(building.item_id))
            extended.input_jump.append(building.input_obj)
            extended.output_jump.append(building.output_obj)
            extended.predecessors.append(0)
            extended.nonbelt_input.append(0)
            extended.nonbelt_output.append(0)
            extended.input_head.append(None)
            extended.input_tail.append(None)
            extended.input_next.append(None)
            extended.output_head.append(None)
            extended.output_tail.append(None)
            extended.output_next.append(None)

        size = len(extended.buildings)
        for source in range(old_size, size):
            extended._poll()
            building = extended.buildings[source]
            edges: tuple[tuple[_Direction, int | None], ...] = (
                ("input", building.input_obj),
                ("output", building.output_obj),
            )
            for direction, target in edges:
                extended.edge_visits += 1
                if extended.belts[source]:
                    if target is not None and 0 <= target < size and extended.belts[target]:
                        extended._append_owner(direction, target, source)
                        if direction == "output":
                            extended.predecessors[target] += 1
                    elif target is not None and not 0 <= target < size:
                        external = (
                            extended.external_input_sources
                            if direction == "input"
                            else extended.external_output_sources
                        )
                        external.append(source)
                elif target is not None and 0 <= target < size and extended.belts[target]:
                    protected = (
                        extended.nonbelt_input
                        if direction == "input"
                        else extended.nonbelt_output
                    )
                    protected[target] += 1

        for index in range(old_size, size):
            extended._poll()
            building = extended.buildings[index]
            right = building.x + building.width - 1
            top = building.y + building.height - 1
            for coordinate, records, counts in (
                (building.x, extended.left_records, extended.left_counts),
                (building.y, extended.bottom_records, extended.bottom_counts),
                (right, extended.right_records, extended.right_counts),
                (top, extended.top_records, extended.top_counts),
            ):
                records.setdefault(coordinate, []).append(index)
                counts[coordinate] = counts.get(coordinate, 0) + 1
        extended.left_coordinates = extended._ordered_coordinates(
            extended.left_counts,
        )
        extended.bottom_coordinates = extended._ordered_coordinates(
            extended.bottom_counts,
        )
        extended.right_coordinates = extended._ordered_coordinates(
            extended.right_counts,
            reverse=True,
        )
        extended.top_coordinates = extended._ordered_coordinates(
            extended.top_counts,
            reverse=True,
        )
        extended.left_position = 0
        extended.bottom_position = 0
        extended.right_position = 0
        extended.top_position = 0
        return extended

    def snapshot_bounds(self) -> tuple[int, int, int, int]:
        """Evaluate this immutable prefix without consuming it."""
        return self._fork().survivor_bounds()

    def extended_snapshot(
        self,
        additions: Sequence[PlacedBuilding],
        bounds: tuple[int, int, int, int],
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> tuple[_CleanupSurvivorGraph, tuple[int, int, int, int]]:
        """Extend a prefix, reevaluating only additions that can change survivors."""
        extended = self.extended(additions, cancelled=cancelled)
        if all(
            building.input_obj is None
            and building.output_obj is None
            and (
                catalog.is_belt(building.item_id)
                or (
                    bounds[0] <= building.x
                    and bounds[1] <= building.y
                    and building.x + building.width - 1 <= bounds[2]
                    and building.y + building.height - 1 <= bounds[3]
                )
            )
            for building in additions
        ):
            return extended, bounds
        return extended, extended.snapshot_bounds()


    def _poll(self) -> None:
        if self.cancelled is not None and self.cancelled():
            raise ProjectionCancelled

    def _append_owner(self, direction: _Direction, target: int, source: int) -> None:
        heads, tails, following = self._bags(direction)
        tail = tails[target]
        if tail is None:
            heads[target] = source
        else:
            following[tail] = source
        tails[target] = source

    def _bags(
        self,
        direction: _Direction,
    ) -> tuple[list[int | None], list[int | None], list[int | None]]:
        if direction == "input":
            return self.input_head, self.input_tail, self.input_next
        return self.output_head, self.output_tail, self.output_next

    def _move_owner_bag(
        self,
        direction: _Direction,
        source_target: int,
        destination: int | None,
        pending: set[int],
    ) -> None:
        heads, tails, following = self._bags(direction)
        head = heads[source_target]
        tail = tails[source_target]
        heads[source_target] = None
        tails[source_target] = None
        if head is None:
            return
        if (
            destination is not None
            and destination != self._EXTERNAL
            and self.active[destination]
            and self.belts[destination]
        ):
            destination_tail = tails[destination]
            if destination_tail is None:
                heads[destination] = head
            else:
                following[destination_tail] = head
            tails[destination] = tail
            return

        owner: int | None = head
        while owner is not None:
            self._poll()
            self.edge_visits += 1
            if self.active[owner]:
                pending.add(owner)
            owner = following[owner]

    def _resolve(
        self,
        value: int | None,
        direction: _Direction,
    ) -> int | None:
        jump = self.input_jump if direction == "input" else self.output_jump
        path: list[int] = []
        positions: set[int] = set()
        while value is not None:
            self._poll()
            self.edge_visits += 1
            if value < 0 or value >= len(self.buildings):
                result = None if self.remapped_once else self._EXTERNAL
                break
            if self.active[value]:
                result = value
                break
            if value in positions:
                result = None
                break
            positions.add(value)
            path.append(value)
            value = jump[value]
        else:
            result = None
        for removed in path:
            self._poll()
            jump[removed] = result
        return result

    def _current_bounds(self) -> tuple[int, int, int, int]:
        indexed = (
            (self.left_coordinates, self.left_counts, "left_position"),
            (self.bottom_coordinates, self.bottom_counts, "bottom_position"),
            (self.right_coordinates, self.right_counts, "right_position"),
            (self.top_coordinates, self.top_counts, "top_position"),
        )
        values: list[int] = []
        for coordinates, counts, position_name in indexed:
            self._poll()
            position = cast(int, getattr(self, position_name))
            while not counts[coordinates[position]]:
                self._poll()
                position += 1
            setattr(self, position_name, position)
            values.append(coordinates[position])
        return cast(tuple[int, int, int, int], tuple(values))

    def _enqueue_outer(
        self,
        bounds: tuple[int, int, int, int],
        pending: set[int],
        *,
        prior: tuple[int, int, int, int] | None = None,
    ) -> None:
        for side, (coordinate, records) in enumerate(
            zip(
                bounds,
                (
                    self.left_records,
                    self.bottom_records,
                    self.right_records,
                    self.top_records,
                ),
                strict=True,
            )
        ):
            self._poll()
            if prior is not None and coordinate == prior[side]:
                continue
            for index in records[coordinate]:
                self._poll()
                if self.active[index] and self.belts[index]:
                    pending.add(index)

    def _is_outer(
        self,
        index: int,
        bounds: tuple[int, int, int, int],
    ) -> bool:
        building = self.buildings[index]
        left, bottom, right, top = bounds
        return (
            building.x == left
            or building.y == bottom
            or building.x + building.width - 1 == right
            or building.y + building.height - 1 == top
        )

    def _eligible(
        self,
        index: int,
        bounds: tuple[int, int, int, int],
    ) -> bool:
        self._poll()
        self.node_visits += 1
        if not self.active[index] or not self._is_outer(index, bounds):
            return False
        building = self.buildings[index]
        input_target = self._resolve(building.input_obj, "input")
        output_target = self._resolve(building.output_obj, "output")
        boundary_open = input_target is None or output_target is None
        successor_is_belt = (
            output_target is not None
            and output_target != self._EXTERNAL
            and self.active[output_target]
            and self.belts[output_target]
        )
        predecessor_count = self.predecessors[index]
        open_end = predecessor_count == 0 or not successor_is_belt
        protected = (
            index in self.protected_roots
            or self.nonbelt_input[index] > 0
            or self.nonbelt_output[index] > 0
            or bool(building.parameters)
        )
        prunable = (
            open_end
            and not protected
            and predecessor_count + int(successor_is_belt) <= 1
        )
        return (self.include_boundary_open and boundary_open) or prunable

    def _transfer_protection(
        self,
        direction: _Direction,
        removed: int,
        pending: set[int],
    ) -> None:
        counts = (
            self.nonbelt_input if direction == "input" else self.nonbelt_output
        )
        count = counts[removed]
        if not count:
            return
        target = self._resolve(
            self.input_jump[removed]
            if direction == "input"
            else self.output_jump[removed],
            direction,
        )
        if (
            target is not None
            and target != self._EXTERNAL
            and self.active[target]
            and self.belts[target]
        ):
            counts[target] += count
            pending.add(target)

    def _remove_wave(
        self,
        wave: set[int],
        bounds: tuple[int, int, int, int],
        pending: set[int],
    ) -> tuple[int, int, int, int]:
        removed_sources: dict[int, int] = {}
        for source in wave:
            self._poll()
            target = self._resolve(self.buildings[source].output_obj, "output")
            if (
                target is not None
                and target != self._EXTERNAL
                and self.belts[target]
            ):
                removed_sources[target] = removed_sources.get(target, 0) + 1

        for index in wave:
            self._poll()
            self.node_visits += 1
            self.active[index] = False
            self.active_count -= 1
            building = self.buildings[index]
            right = building.x + building.width - 1
            top = building.y + building.height - 1
            self.left_counts[building.x] -= 1
            self.bottom_counts[building.y] -= 1
            self.right_counts[right] -= 1
            self.top_counts[top] -= 1
        first_remap = not self.remapped_once
        self.remapped_once = True

        for target, count in removed_sources.items():
            self._poll()
            if self.active[target]:
                self.predecessors[target] -= count
                pending.add(target)

        for removed in wave:
            self._poll()
            remaining_predecessors = (
                self.predecessors[removed] - removed_sources.get(removed, 0)
            )
            output_target = self._resolve(self.output_jump[removed], "output")
            if (
                output_target is not None
                and output_target != self._EXTERNAL
                and self.active[output_target]
                and self.belts[output_target]
            ):
                self.predecessors[output_target] += remaining_predecessors
                pending.add(output_target)
            self._move_owner_bag(
                "output",
                removed,
                output_target,
                pending,
            )
            input_target = self._resolve(self.input_jump[removed], "input")
            self._move_owner_bag(
                "input",
                removed,
                input_target,
                pending,
            )
            self._transfer_protection("output", removed, pending)
            self._transfer_protection("input", removed, pending)

        if first_remap:
            for sources in (
                self.external_input_sources,
                self.external_output_sources,
            ):
                for source in sources:
                    self._poll()
                    self.edge_visits += 1
                    if self.active[source]:
                        pending.add(source)
        changed_bounds = self._current_bounds()
        if changed_bounds != bounds:
            self._enqueue_outer(changed_bounds, pending, prior=bounds)
        return changed_bounds

    def _peel(self) -> tuple[int, int, int, int]:
        """Consume exact simultaneous peel waves and return survivor bounds."""
        self._poll()
        if not self.active_count:
            self._poll()
            return (0, 0, 0, 0)
        bounds = self._current_bounds()
        pending: set[int] = set()
        self._enqueue_outer(bounds, pending)
        while pending:
            wave = {
                index
                for index in pending
                if self._eligible(index, bounds)
            }
            pending.clear()
            if not wave:
                break
            # `_remove_buildings` intentionally keeps an all-removed placement.
            if len(wave) == self.active_count:
                break
            bounds = self._remove_wave(wave, bounds, pending)
        self._poll()
        return bounds

    def survivor_indices(self) -> frozenset[int]:
        """Return original indices surviving the exact simultaneous peel waves."""
        _ = self._peel()
        survivors: set[int] = set()
        for index, active in enumerate(self.active):
            self._poll()
            self.node_visits += 1
            if active:
                survivors.add(index)
        return frozenset(survivors)

    def survivor_bounds(self) -> tuple[int, int, int, int]:
        """Return the survivor bounds after the exact simultaneous peel waves."""
        return self._peel()


def _cleanup_survivor_bounds(
    placement: Placement,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[int, int, int, int]:
    """Innermost bounds reachable through existing cleanup eligibility."""
    return _CleanupSurvivorGraph(
        placement,
        cancelled=cancelled,
    ).survivor_bounds()


def uses_tall_saturated_role(
    *,
    machine_count: float,
    strip_count: float,
    sprayed_lanes: int,
) -> bool:
    """Whether the shared pack/cleanup should use the tall saturated role."""
    return sprayed_lanes > 0 and 13 < strip_count <= 24 and machine_count >= 4 * strip_count


def _certified_side_fallback(
    placement: Placement,
    spec: BuildSpec,
    *,
    expect_power: bool,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[Placement, int, Report | None]:
    """Use bounded side batches when structural pruning breaks addon geometry."""
    compacted = placement
    removed_total = 0
    accepted_report: Report | None = None

    def attempt(removed: frozenset[int]) -> bool:
        nonlocal compacted, removed_total, accepted_report
        if cancelled is not None and cancelled():
            raise ProjectionCancelled
        candidate = _remove_buildings(compacted, removed, cancelled=cancelled)
        if candidate is compacted or candidate.area >= compacted.area:
            return False
        report = _certify(candidate, spec, expect_power=expect_power)
        if cancelled is not None and cancelled():
            raise ProjectionCancelled
        if report.errors:
            return False
        compacted = candidate
        removed_total += len(removed)
        accepted_report = report
        return True

    machines = placement.stats.get("machines", 0.0)
    strips = placement.stats.get("strips", 0.0)
    if uses_tall_saturated_role(
        machine_count=float(machines),
        strip_count=float(strips),
        sprayed_lanes=len(spec.spray_lanes),
    ):
        for side in ("left", "bottom", "right", "top"):
            protected_roots = _required_external_input_boundary_roots(
                compacted,
                spec,
                cancelled=cancelled,
            )
            _ = attempt(
                _boundary_open_belts(
                    compacted,
                    side,
                    protected_roots=protected_roots,
                    cancelled=cancelled,
                )
            )
    else:
        for _round in range(4):
            protected_roots = _required_external_input_boundary_roots(
                compacted,
                spec,
                cancelled=cancelled,
            )
            removed = _boundary_open_belts(
                compacted,
                "left",
                protected_roots=protected_roots,
                cancelled=cancelled,
            ) | _boundary_open_belts(
                compacted,
                "bottom",
                protected_roots=protected_roots,
                cancelled=cancelled,
            )
            if not attempt(removed):
                break
    return compacted, removed_total, accepted_report


@dataclass(frozen=True, slots=True)
class BoundaryCompactionResult:
    """Compacted placement and its reusable exact certification, when changed."""

    placement: Placement
    report: Report | None


def compact_open_boundary_belts_certified(
    placement: Placement,
    spec: BuildSpec,
    *,
    expect_power: bool,
    cancelled: Callable[[], bool] | None = None,
) -> BoundaryCompactionResult:
    """Prune structural belt leaves once, retaining exact certification."""
    started = time.perf_counter()
    if cancelled is not None and cancelled():
        raise ProjectionCancelled
    protected_roots = _required_external_input_boundary_roots(
        placement,
        spec,
        cancelled=cancelled,
    )
    graph = _CleanupSurvivorGraph(
        placement,
        cancelled=cancelled,
        _include_boundary_open=False,
        _protected_roots=protected_roots,
    )
    survivors = graph.survivor_indices()
    removed_values: set[int] = set()
    for index in range(len(placement.buildings)):
        if cancelled is not None and cancelled():
            raise ProjectionCancelled
        if index not in survivors:
            removed_values.add(index)
    removed = frozenset(removed_values)
    compacted = _remove_buildings(
        placement,
        removed,
        cancelled=cancelled,
    )
    removed_total = len(removed) if compacted is not placement else 0
    structural_report = (
        _certify(compacted, spec, expect_power=expect_power)
        if compacted is not placement
        else None
    )
    if cancelled is not None and cancelled():
        raise ProjectionCancelled
    tall_role = uses_tall_saturated_role(
        machine_count=float(placement.stats.get("machines", 0.0)),
        strip_count=float(placement.stats.get("strips", 0.0)),
        sprayed_lanes=len(spec.spray_lanes),
    )
    report = structural_report
    if compacted is placement or (
        structural_report is not None and structural_report.errors
    ):
        compacted, removed_total, report = _certified_side_fallback(
            placement,
            spec,
            expect_power=expect_power,
            cancelled=cancelled,
        )
    elif tall_role:
        compacted, side_removed, fallback_report = _certified_side_fallback(
            compacted,
            spec,
            expect_power=expect_power,
            cancelled=cancelled,
        )
        removed_total += side_removed
        if fallback_report is not None:
            report = fallback_report
    if compacted is placement:
        return BoundaryCompactionResult(placement, None)
    stats = compacted.stats.copy()
    stats["boundary_belts_removed"] = float(removed_total)
    stats["boundary_cleanup_time_s"] = time.perf_counter() - started
    return BoundaryCompactionResult(
        replace(compacted, stats=stats),
        report,
    )


def compact_open_boundary_belts(
    placement: Placement,
    spec: BuildSpec,
    *,
    expect_power: bool,
    cancelled: Callable[[], bool] | None = None,
) -> Placement:
    """Prune structural belt leaves once, with a bounded certified fallback."""
    return compact_open_boundary_belts_certified(
        placement,
        spec,
        expect_power=expect_power,
        cancelled=cancelled,
    ).placement
