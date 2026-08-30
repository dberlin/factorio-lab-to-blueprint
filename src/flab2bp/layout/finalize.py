"""Strategy-independent final projection and cleanup of exact placements."""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from functools import cache
from itertools import combinations
from typing import Literal, cast

from flab2bp.dsp import catalog, codec, colliders, planet, rules
from flab2bp.layout import slots
from flab2bp.layout.band_policy import BandPolicy
from flab2bp.layout.base import AreaFrame, PlacedBuilding, Placement
from flab2bp.layout.validate import certify as _certify
from flab2bp.spec import BuildSpec

type _Direction = Literal["input", "output"]
type _Side = Literal["left", "bottom", "right", "top"]

@dataclass(frozen=True, slots=True)
class ProjectionFailure:
    """One authoritative projected paste refusal."""

    check: str
    buildings: tuple[int, ...]
    detail: str
    band: int


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
    pack_origins: tuple[tuple[int, int], ...]
    failure: ProjectionFailure


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
            )

        @cache
        def power_failure(
            nodes: tuple[tuple[int, PlacedBuilding, rules.PowerNode], ...],
            projection: planet.Projection,
        ) -> ProjectionFailure | None:
            self._power_misses += 1
            failure = projected_power_failure(nodes, projection)
            self.counters.power_pairs += _power_pairs_examined(nodes, failure)
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
            return _projected_addon_failure(belts, addons, projection)

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
            )

        self._sorter_failure = sorter_failure
        self._static_failure = static_failure
        self._power_failure = power_failure
        self._addon_failure = addon_failure
        self._addon_splitter_failure = addon_splitter_failure

    def sorter_failure(
        self,
        sorters: tuple[tuple[int, planet.Sorter], ...],
        projection: planet.Projection,
    ) -> ProjectionFailure | None:
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
) -> tuple[tuple[int, PlacedBuilding, rules.PowerNode], ...]:
    nodes: list[tuple[int, PlacedBuilding, rules.PowerNode]] = []
    for index, building in enumerate(placement.buildings):
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


def _planet_sorters(placement: Placement) -> tuple[tuple[int, planet.Sorter], ...]:
    buildings = placement.buildings
    sorters: list[tuple[int, planet.Sorter]] = []
    for index, building in enumerate(buildings):
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
) -> ProjectionFailure | None:
    for index, sorter in sorters:
        if counters is not None:
            counters.sorters += 1
        condition = planet.sorter_condition(sorter, projection)
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


def projected_power_failure(
    nodes: Sequence[tuple[int, PlacedBuilding, rules.PowerNode]],
    projection: planet.Projection,
) -> ProjectionFailure | None:
    """Return the first authoritative power-pair refusal in one projection."""
    poses = tuple(
        projection.position(*_building_centre(building))
        for _index, building, _node in nodes
    )
    for left, right in combinations(range(len(nodes)), 2):
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
) -> int:
    """Count pairs the shared first-failure predicate necessarily evaluated."""
    for examined, (left, right) in enumerate(combinations(range(len(nodes)), 2), 1):
        if failure is not None and failure.buildings == (
            nodes[left][0],
            nodes[right][0],
        ):
            return examined
    return len(nodes) * (len(nodes) - 1) // 2


def _projected_static_failure(
    tested: Sequence[tuple[int, colliders.Placed]],
    pairs: Sequence[tuple[int, int]],
    projection: planet.Projection,
    *,
    counters: _ProjectionCounters | None = None,
) -> ProjectionFailure | None:
    placed = [building for _index, building in tested]
    if counters is not None:
        counters.collider_pairs += len(pairs)
    hits = planet.collisions_at(placed, projection, pairs)
    if not hits:
        return None
    left, right = hits[0]
    return ProjectionFailure(
        check="geom.collide",
        buildings=(tested[left][0], tested[right][0]),
        detail="build colliders intersect",
        band=projection.band.area_segments,
    )


def projected_static_failure(
    buildings: Sequence[tuple[int, PlacedBuilding]],
    projection: planet.Projection,
    *,
    candidate_index: int | None = None,
) -> ProjectionFailure | None:
    """Return the finalizer's exact static-collider verdict for one projection.

    ``buildings`` retain their placement indices so a prospective object that is
    not committed yet can produce the same structured evidence as finalization.
    Belts and sorters are omitted by the same condition as
    :func:`_projection_invariants`.  When ``candidate_index`` is supplied, only
    candidate pairs involving that staged object are considered, in the order
    :func:`planet.candidate_pairs` gives them.
    """
    retained = tuple(
        (index, building)
        for index, building in buildings
        if not catalog.is_belt(building.item_id)
        and not catalog.is_sorter(building.item_id)
    )
    tested = tuple(
        (index, _collision_placed(building))
        for index, building in retained
    )
    pairs = tuple(
        planet.candidate_pairs(
            tuple(building for _index, building in tested),
            projection.band,
            projection.segment,
            projection.radius,
        )
    )
    if candidate_index is not None:
        try:
            candidate_position = next(
                position
                for position, (index, _building) in enumerate(retained)
                if index == candidate_index
            )
        except StopIteration:
            raise ValueError("prospective static candidate is not collision-tested") from None
        pairs = tuple(
            pair for pair in pairs if candidate_position in pair
        )
    return _projected_static_failure(tested, pairs, projection)


def _projected_addon_failure(
    belts: Sequence[tuple[int, PlacedBuilding]],
    addons: Sequence[
        tuple[int, PlacedBuilding, tuple[catalog.AddonSupplyPose, ...]]
    ],
    projection: planet.Projection,
) -> ProjectionFailure | None:
    if not belts or not addons:
        return None
    belt_positions = tuple(
        projection.position(belt.x, belt.y, float(belt.z))
        for _belt_index, belt in belts
    )
    radius2 = rules.ADDON_AREA_RADIUS**2
    for addon_index, addon, areas in addons:
        for area in areas:
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
            if not any(
                (target[0] - belt[0]) ** 2
                + (target[1] - belt[1]) ** 2
                + (target[2] - belt[2]) ** 2
                < radius2
                for belt in belt_positions
            ):
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
    return any(
        colliders.obb_overlap(coater_box, splitter_box)
        for coater_box in coater_boxes
        for splitter_box in splitter_boxes
    )


def projected_coater_splitter_failure(
    coater: tuple[int, colliders.Placed],
    splitter: tuple[int, colliders.Placed],
    projection: planet.Projection,
) -> ProjectionFailure | None:
    """Return exact structured evidence for one projected Coater/Splitter pair."""
    if not _projected_coater_keepout_overlaps(coater[1], splitter[1], projection):
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


def _projected_addon_splitter_failure(
    coaters: Sequence[tuple[int, colliders.Placed]],
    splitters: Sequence[tuple[int, colliders.Placed]],
    projection: planet.Projection,
) -> ProjectionFailure | None:
    """Authoritative coater/splitter keepout from the broke2 in-game refusal."""
    for coater in coaters:
        for splitter in splitters:
            failure = projected_coater_splitter_failure(
                coater,
                splitter,
                projection,
            )
            if failure is not None:
                return failure
    return None


def _projection_invariants(placement: Placement) -> _ProjectionInvariants:
    tested: list[tuple[int, colliders.Placed]] = []
    belts: list[tuple[int, PlacedBuilding]] = []
    addons: list[
        tuple[int, PlacedBuilding, tuple[catalog.AddonSupplyPose, ...]]
    ] = []
    coaters: list[tuple[int, colliders.Placed]] = []
    splitters: list[tuple[int, colliders.Placed]] = []
    for index, building in enumerate(placement.buildings):
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
    return _ProjectionInvariants(
        tested=tuple(tested),
        nodes=_power_nodes(placement),
        sorters=_planet_sorters(placement),
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
) -> tuple[ProjectionFailure, ...]:
    counters.projections += 1
    failures: list[ProjectionFailure] = []
    if cache is None:
        power_failure = projected_power_failure(invariants.nodes, projection)
        counters.power_pairs += _power_pairs_examined(
            invariants.nodes,
            power_failure,
        )
    else:
        power_failure = cache.power_failure(invariants.nodes, projection)
    pair_key = tuple(pairs)
    sorter_failure = (
        _projected_sorter_failure(
            invariants.sorters,
            projection,
            counters=counters,
        )
        if cache is None
        else cache.sorter_failure(invariants.sorters, projection)
    )
    static_failure = (
        _projected_static_failure(
            invariants.tested,
            pair_key,
            projection,
            counters=counters,
        )
        if cache is None
        else cache.static_failure(invariants.tested, pair_key, projection)
    )
    addon_failure = (
        _projected_addon_failure(
            invariants.belts,
            invariants.addons,
            projection,
        )
        if cache is None
        else cache.addon_failure(
            invariants.belts,
            invariants.addons,
            projection,
        )
    )
    addon_splitter_failure = (
        _projected_addon_splitter_failure(
            invariants.coaters,
            invariants.splitters,
            projection,
        )
        if cache is None
        else cache.addon_splitter_failure(
            invariants.coaters,
            invariants.splitters,
            projection,
        )
    )
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
) -> tuple[ProjectionFailure, ...]:
    building_key = placement.buildings
    invariants = None if cache is None else cache.invariants.get(building_key)
    if invariants is None:
        invariants = _projection_invariants(placement)
        if cache is not None:
            cache.invariants[building_key] = invariants
    else:
        counters.invariant_cache_hits += 1
    pair_buildings = tuple(
        replace(building, x=building.y, y=building.x)
        if pair_rotated
        else building
        for _index, building in invariants.tested
    )
    by_segments = {band.area_segments: band for band in planet.bands()}
    pairs_by_band: dict[int, tuple[tuple[int, int], ...]] = {}
    failures: list[ProjectionFailure] = []
    for segments in frame.certified_bands:
        band = by_segments[segments]
        pairs = pairs_by_band.get(segments)
        if pairs is None:
            pair_key = (building_key, segments, pair_rotated)
            pairs = None if cache is None else cache.pairs.get(pair_key)
            if pairs is None:
                pairs = tuple(
                    planet.candidate_pairs(
                        pair_buildings,
                        band,
                        colliders.PLANET_SEGMENT,
                        colliders.PLANET_RADIUS,
                    )
                )
                if cache is not None:
                    cache.pairs[pair_key] = pairs
            else:
                counters.pair_cache_hits += 1
            pairs_by_band[segments] = pairs
        for anchor in band.anchors(frame.height):
            projection_key = (
                segments,
                frame.height,
                anchor - row_origin,
                quadrant,
            )
            projection = (
                None if cache is None else cache.projections.get(projection_key)
            )
            if projection is None:
                projection = planet.Projection(
                    band=band,
                    anchor_row=anchor - row_origin,
                    segment=colliders.PLANET_SEGMENT,
                    radius=colliders.PLANET_RADIUS,
                    quadrant=quadrant,
                )
                if cache is not None:
                    cache.projections[projection_key] = projection
            else:
                counters.projection_cache_hits += 1
            projection_failures = _failure_at_projection(
                invariants,
                pairs,
                projection,
                counters,
                cache=cache,
            )
            if projection_failures:
                failures.extend(projection_failures)
                if stop_after_failure:
                    return projection_failures
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
) -> Placement:
    """Certify one placement against its required latitude-band policy."""
    if placement.frame is not None and _frame_satisfies_policy(placement, policy):
        return placement

    candidates = frame_candidates(placement, policy)
    if not candidates:
        raise ProjectionRefusal((_extent_failure(placement, policy),))
    counters = _ProjectionCounters()
    cache = _ProjectionCache(counters)
    failures: list[ProjectionFailure] = []
    for candidate in candidates:
        counters.frame_candidates += 1
        framed = _materialize_frame(placement, candidate)
        candidate_failures = _certify_frame(
            framed,
            candidate.frame,
            counters,
            cache=cache,
        )
        if candidate_failures:
            failures.extend(candidate_failures)
            continue
        return _with_projection_stats(framed, counters)
    raise ProjectionRefusal(failures)


def _remove_buildings(placement: Placement, removed: frozenset[int]) -> Placement:
    """Remove indices, bypass their links, and rewrite every surviving reference."""
    if not removed:
        return placement
    size = len(placement.buildings)
    if any(index < 0 or index >= size for index in removed):
        raise ValueError("removed building indices must belong to the placement")
    if len(removed) == size:
        return placement

    mapping = {
        old: new for new, old in enumerate(index for index in range(size) if index not in removed)
    }

    def remap(value: int | None, direction: _Direction) -> int | None:
        seen: set[int] = set()
        while value is not None and value in removed and value not in seen:
            seen.add(value)
            building = placement.buildings[value]
            value = building.output_obj if direction == "output" else building.input_obj
        return mapping.get(value) if value is not None else None

    buildings = tuple(
        replace(
            building,
            output_obj=remap(building.output_obj, "output"),
            input_obj=remap(building.input_obj, "input"),
        )
        for index, building in enumerate(placement.buildings)
        if index not in removed
    )
    candidate = replace(placement, buildings=buildings, frame=None)
    stats = placement.stats.copy()
    if "area" in stats:
        stats["area"] = float(candidate.area)
    if "belt_tiles" in stats:
        belt_tiles = stats["belt_tiles"]
        stats["belt_tiles"] = float(belt_tiles) - len(removed)
    return replace(candidate, stats=stats)


def _prunable_open_belts(placement: Placement) -> frozenset[int]:
    """Unreferenced outer belt leaves that can be removed as one structural wave."""
    buildings = placement.buildings
    belts = {index for index, building in enumerate(buildings) if catalog.is_belt(building.item_id)}
    predecessors: dict[int, set[int]] = {index: set() for index in belts}
    for index in belts:
        target = buildings[index].output_obj
        if target in belts:
            predecessors[target].add(index)
    nonbelt_references = {
        target
        for index, building in enumerate(buildings)
        if index not in belts
        for target in (building.input_obj, building.output_obj)
        if target in belts
    }
    left, bottom, right, top = placement.bounds
    selected: set[int] = set()
    for index in belts:
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


def _boundary_open_belts(placement: Placement, side: _Side) -> frozenset[int]:
    """Open belts on one current bounding side for the certified fallback."""
    left, bottom, right, top = placement.bounds
    return frozenset(
        index
        for index, building in enumerate(placement.buildings)
        if catalog.is_belt(building.item_id)
        and (building.input_obj is None or building.output_obj is None)
        and (
            (side == "left" and building.x == left)
            or (side == "bottom" and building.y == bottom)
            or (side == "right" and building.x + building.width - 1 == right)
            or (side == "top" and building.y + building.height - 1 == top)
        )
    )


def _cleanup_survivor_bounds(
    placement: Placement,
) -> tuple[int, int, int, int]:
    """Innermost bounds reachable through existing cleanup eligibility."""
    candidate = placement
    for _wave in range(len(placement.buildings)):
        removable = set(_prunable_open_belts(candidate))
        for side in ("left", "bottom", "right", "top"):
            removable.update(_boundary_open_belts(candidate, side))
        if not removable:
            break
        candidate = _remove_buildings(candidate, frozenset(removable))
    return candidate.bounds


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
) -> tuple[Placement, int]:
    """Use bounded side batches when structural pruning breaks addon geometry."""
    compacted = placement
    removed_total = 0

    def attempt(removed: frozenset[int]) -> bool:
        nonlocal compacted, removed_total
        candidate = _remove_buildings(compacted, removed)
        if candidate is compacted or candidate.area >= compacted.area:
            return False
        errors = _certify(candidate, spec, expect_power=expect_power).errors
        if errors:
            return False
        compacted = candidate
        removed_total += len(removed)
        return True

    machines = placement.stats.get("machines", 0.0)
    strips = placement.stats.get("strips", 0.0)
    if uses_tall_saturated_role(
        machine_count=float(machines),
        strip_count=float(strips),
        sprayed_lanes=len(spec.spray_lanes),
    ):
        for side in ("left", "bottom", "right", "top"):
            _ = attempt(_boundary_open_belts(compacted, side))
    else:
        for _round in range(4):
            removed = _boundary_open_belts(compacted, "left") | _boundary_open_belts(
                compacted, "bottom"
            )
            if not attempt(removed):
                break
    return compacted, removed_total


def compact_open_boundary_belts(
    placement: Placement,
    spec: BuildSpec,
    *,
    expect_power: bool,
) -> Placement:
    """Prune structural belt leaves once, with a bounded certified fallback."""
    started = time.perf_counter()
    compacted = placement
    removed_total = 0
    for _wave in range(len(placement.buildings)):
        removed = _prunable_open_belts(compacted)
        if not removed:
            break
        candidate = _remove_buildings(compacted, removed)
        if candidate is compacted:
            break
        compacted = candidate
        removed_total += len(removed)

    structural_errors = (
        _certify(compacted, spec, expect_power=expect_power).errors
        if compacted is not placement
        else ()
    )
    tall_role = uses_tall_saturated_role(
        machine_count=float(placement.stats.get("machines", 0.0)),
        strip_count=float(placement.stats.get("strips", 0.0)),
        sprayed_lanes=len(spec.spray_lanes),
    )
    if compacted is placement or structural_errors:
        compacted, removed_total = _certified_side_fallback(
            placement,
            spec,
            expect_power=expect_power,
        )
    elif tall_role:
        compacted, side_removed = _certified_side_fallback(
            compacted,
            spec,
            expect_power=expect_power,
        )
        removed_total += side_removed
    if compacted is placement:
        return placement
    stats = compacted.stats.copy()
    stats["boundary_belts_removed"] = float(removed_total)
    stats["boundary_cleanup_time_s"] = time.perf_counter() - started
    return replace(compacted, stats=stats)
