"""Immutable logical strip families and pose-valid physical variants.

Logical rate/shard allocation remains independent of placement.  This module
turns each logical shard into cardinal pose candidates using the same catalog
and slot helpers used by validation.  Every variant seats lanes outside the
collider exclusion envelope and carries the exact slot attachments emission
must reproduce.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from enum import Enum
from fractions import Fraction
from itertools import combinations, product
from typing import TYPE_CHECKING, Literal

from flab2bp.dsp import catalog
from flab2bp.layout import slots
from flab2bp.layout.base import Facing, NoValidLayout, PlacedBuilding, Placement
from flab2bp.layout.finalize import (
    ProjectionFailure,
    projection_safe_machine_pitch_x,
)
from flab2bp.spec import BuildSpec

if TYPE_CHECKING:
    from flab2bp.layout.freeform import _Group

LaneKind = Literal["input", "output"]
LaneSide = Literal["north", "south"]
_CARDINAL_YAWS = (0.0, 90.0, 180.0, 270.0)


class CargoDomain(Enum):
    """Treatment identity that must remain disjoint while cargo is routed."""

    UNSPRAYED = "unsprayed"
    REQUIRES_SPRAY = "requires-spray"


@dataclass(frozen=True, slots=True)
class _LogicalStripPlan:
    """One immutable rate/shard allocation before choosing physical geometry."""

    group_key: str
    shard_index: int
    recipe_id: str
    item_id: int
    model_index: int
    total_machine_count: int
    cargo_domain: CargoDomain
    in_above: tuple[tuple[str, ...], ...]
    out_lanes: tuple[tuple[str, str, CargoDomain], ...]
    in_below: tuple[tuple[str, ...], ...]
    mode_params: tuple[int, ...] = ()
    flank_outputs: bool = False


@dataclass(frozen=True, slots=True)
class MachinePlacementGeometry:
    """Oriented occupied footprint and collider-derived exclusion pitch."""

    footprint_width: int
    footprint_height: int
    pitch_x: int
    pitch_y: int
    west_halo: int
    east_halo: int
    north_halo: int
    south_halo: int

    def __post_init__(self) -> None:
        if (
            min(
                self.footprint_width,
                self.footprint_height,
                self.pitch_x,
                self.pitch_y,
            )
            <= 0
        ):
            raise ValueError("placement dimensions and pitches must be positive")
        if (
            min(
                self.west_halo,
                self.east_halo,
                self.north_halo,
                self.south_halo,
            )
            < 0
        ):
            raise ValueError("placement halos must be non-negative")
        if self.west_halo + self.footprint_width + self.east_halo != self.pitch_x:
            raise ValueError("horizontal halos must complete the collider pitch")
        if self.north_halo + self.footprint_height + self.south_halo != self.pitch_y:
            raise ValueError("vertical halos must complete the collider pitch")

    def with_minimum_pitch_x(self, required: int) -> MachinePlacementGeometry:
        """Return this geometry with deterministic east-side X padding."""
        if type(required) is not int or required <= 0:
            raise ValueError("required X pitch must be a positive integer")
        if required <= self.pitch_x:
            return self
        return replace(
            self,
            pitch_x=required,
            east_halo=self.east_halo + required - self.pitch_x,
        )


    @property
    def identity(self) -> tuple[int, ...]:
        return (
            self.footprint_width,
            self.footprint_height,
            self.pitch_x,
            self.pitch_y,
            self.west_halo,
            self.east_halo,
            self.north_halo,
            self.south_halo,
        )


@dataclass(frozen=True, slots=True)
class LaneReachProfile:
    """Every authoritative attachment offered by one legal lane row."""

    side: LaneSide
    lane_y: int
    attachments: tuple[tuple[int, slots.Attachment], ...]

    def __post_init__(self) -> None:
        if self.side not in ("north", "south"):
            raise ValueError("lane reach profile side must be north or south")
        columns = tuple(column for column, _attachment in self.attachments)
        if not columns or columns != tuple(sorted(set(columns))):
            raise ValueError("lane reach profile columns must be non-empty and distinct")
        if any(
            attachment.cell[0] != column or not 1 <= attachment.span <= catalog.SORTER_MAX_REACH
            for column, attachment in self.attachments
        ):
            raise ValueError("lane reach profile contains invalid attachment geometry")

    @property
    def attachable_columns(self) -> tuple[int, ...]:
        return tuple(column for column, _attachment in self.attachments)


@dataclass(frozen=True, order=True, slots=True)
class StripFamilyId:
    """Stable identity of one logical destination shard of a recipe group."""

    group_key: str
    shard_index: int

    def __post_init__(self) -> None:
        if not self.group_key:
            raise ValueError("strip family group key must not be empty")
        if self.shard_index < 0:
            raise ValueError("strip family shard index must be non-negative")


@dataclass(frozen=True, order=True, slots=True)
class LaneSorterAttachment:
    """One item's exact machine-side attachment relative to a machine origin."""

    item: str
    column: int
    cell: tuple[int, int]
    slot: int
    span: int

    def __post_init__(self) -> None:
        if not self.item:
            raise ValueError("lane attachment item must not be empty")
        if self.column < 0 or self.span <= 0:
            raise ValueError("lane attachment column and span must be positive geometry")
        if self.span > catalog.SORTER_MAX_REACH:
            raise ValueError("lane attachment exceeds sorter reach")


@dataclass(frozen=True, order=True, slots=True)
class LogicalLane:
    """Placement-independent lane demand owned by a logical strip family."""

    lane_id: str
    kind: LaneKind
    items: tuple[str, ...]
    destination_group_keys: tuple[str, ...]
    cargo_domain: CargoDomain
    side: LaneSide
    side_index: int

    def __post_init__(self) -> None:
        if not self.lane_id or not self.items or any(not item for item in self.items):
            raise ValueError("logical lanes require an id and at least one named item")
        if len(set(self.items)) != len(self.items):
            raise ValueError("logical lane items must be unique")
        if self.kind not in ("input", "output"):
            raise ValueError("logical lane kind must be input or output")
        if self.side not in ("north", "south"):
            raise ValueError("logical lane side must be north or south")
        if self.side_index < 0:
            raise ValueError("logical lane side index must be non-negative")
        if self.kind == "output" and len(self.items) != 1:
            raise ValueError("an output lane carries exactly one produced item")
        if self.kind == "input" and self.destination_group_keys:
            raise ValueError("input lanes do not own destination group keys")


@dataclass(frozen=True, order=True, slots=True)
class LaneAttachmentPlan:
    """Exact attachments serving one logical lane at its current relative row."""

    lane: LogicalLane
    lane_y: int
    attachments: tuple[LaneSorterAttachment, ...]

    def __post_init__(self) -> None:
        if tuple(attachment.item for attachment in self.attachments) != self.lane.items:
            raise ValueError("lane attachment items must match the logical lane")
        columns = tuple(attachment.column for attachment in self.attachments)
        if len(set(columns)) != len(columns):
            raise ValueError("items sharing a lane need distinct attachment columns")
        if any(attachment.cell[0] != attachment.column for attachment in self.attachments):
            raise ValueError("attachment columns and machine-side cells must agree")

    @property
    def identity(self) -> tuple[str, int, tuple[LaneSorterAttachment, ...]]:
        return (self.lane.lane_id, self.lane_y, self.attachments)


@dataclass(frozen=True, slots=True)
class LanePortDockPlan:
    """One output lane bound to an authoritative prefab belt port."""

    lane: LogicalLane
    lane_y: int
    port: int
    cell: tuple[int, int]
    facing: Facing

    def __post_init__(self) -> None:
        if self.lane.kind != "output":
            raise ValueError("belt ports may drain only an output lane")
        if self.port < 0:
            raise ValueError("belt port index must be non-negative")
        if self.facing.delta[1] <= 0 or self.cell[1] >= self.lane_y:
            raise ValueError("drawing belt port must face and reach its lane below")

    @property
    def identity(self) -> tuple[str, int, int, tuple[int, int], float]:
        return (
            self.lane.lane_id,
            self.lane_y,
            self.port,
            self.cell,
            self.facing.value,
        )


@dataclass(frozen=True, order=True, slots=True)
class LanePlan:
    """Current logical lane assignment bound atomically to a machine pose."""

    machine_row: int
    lane_rows: tuple[tuple[str, int], ...]

    def __post_init__(self) -> None:
        if self.machine_row < 0:
            raise ValueError("machine row must be inside the variant box")
        lane_ids = tuple(lane_id for lane_id, _row in self.lane_rows)
        if len(set(lane_ids)) != len(lane_ids):
            raise ValueError("lane plan contains duplicate logical lanes")

    def row_for(self, lane_id: str) -> int:
        for candidate, row in self.lane_rows:
            if candidate == lane_id:
                return row
        raise KeyError(lane_id)


@dataclass(frozen=True, order=True, slots=True)
class StripVariantId:
    """Complete immutable physical identity of a strip variant."""

    family_id: StripFamilyId
    yaw_degrees: int
    machine_origins_x: tuple[int, ...]
    footprint: tuple[int, int]
    placement_geometry: tuple[int, ...]
    lane_rows: tuple[tuple[str, int], ...]
    attachments: tuple[tuple[str, int, tuple[LaneSorterAttachment, ...]], ...]
    port_docks: tuple[tuple[str, int, int, tuple[int, int], float], ...]
    box: tuple[int, int]


@dataclass(frozen=True, order=True, slots=True)
class StripPoseId:
    """Pitch-independent identity of one logical strip family pose."""

    family_id: StripFamilyId
    yaw_degrees: int
    footprint: tuple[int, int]
    placement_geometry: tuple[int, int, int, int]
    lane_rows: tuple[tuple[str, int], ...]
    attachments: tuple[tuple[str, int, tuple[LaneSorterAttachment, ...]], ...]
    port_docks: tuple[tuple[str, int, int, tuple[int, int], float], ...]
    box_height: int


@dataclass(frozen=True, slots=True)
class StripVariant:
    """One atomic pose, exclusion envelope, lane plan, and endpoint plan."""

    variant_id: StripVariantId
    yaw: float
    footprint_width: int
    footprint_height: int
    placement_geometry: MachinePlacementGeometry
    lane_plan: LanePlan
    box_width: int
    box_height: int
    attachment_plan: tuple[LaneAttachmentPlan, ...]
    machine_origins_x: tuple[int, ...]
    port_dock_plan: tuple[LanePortDockPlan, ...] = ()

    def __post_init__(self) -> None:
        if self.yaw not in _CARDINAL_YAWS:
            raise ValueError("strip variant yaw must be cardinal")
        if self.box_width <= 0 or self.box_height <= 0:
            raise ValueError("variant box dimensions must be positive")
        if self.box_width % self.pitch_x:
            raise ValueError("variant box width must contain whole collider pitches")
        if (self.footprint_width, self.footprint_height) != (
            self.placement_geometry.footprint_width,
            self.placement_geometry.footprint_height,
        ):
            raise ValueError("variant footprint and placement geometry disagree")
        expected_origins = tuple(range(0, self.box_width, self.pitch_x))
        if not expected_origins or self.machine_origins_x != expected_origins:
            raise ValueError("machine origins must advance by collider pitch")
        planned_rows = dict(self.lane_plan.lane_rows)
        attachment_ids = tuple(plan.lane.lane_id for plan in self.attachment_plan)
        port_ids = tuple(plan.lane.lane_id for plan in self.port_dock_plan)
        endpoint_ids = attachment_ids + port_ids
        if len(set(endpoint_ids)) != len(endpoint_ids) or set(endpoint_ids) != set(planned_rows):
            raise ValueError("variant lane and endpoint plans disagree")
        if any(
            planned_rows[plan.lane.lane_id] != plan.lane_y for plan in self.attachment_plan
        ) or any(planned_rows[plan.lane.lane_id] != plan.lane_y for plan in self.port_dock_plan):
            raise ValueError("variant endpoints must use their planned lane rows")
        attachment_slots = tuple(
            attachment.slot for plan in self.attachment_plan for attachment in plan.attachments
        )
        if len(set(attachment_slots)) != len(attachment_slots):
            raise ValueError("variant attachments must use globally distinct machine slots")
        lane_ys = tuple(plan.lane_y for plan in self.attachment_plan) + tuple(
            plan.lane_y for plan in self.port_dock_plan
        )
        envelope_top = -self.placement_geometry.north_halo
        envelope_bottom = self.footprint_height + self.placement_geometry.south_halo
        sorter_lane_ys = tuple(plan.lane_y for plan in self.attachment_plan)
        if any(envelope_top <= lane_y < envelope_bottom for lane_y in sorter_lane_ys):
            raise ValueError("sorter lane enters the collider exclusion envelope")
        minimum_y = min(envelope_top, *lane_ys)
        maximum_y = max(envelope_bottom, *(lane_y + 1 for lane_y in lane_ys))
        if self.lane_plan.machine_row != -minimum_y or self.box_height != maximum_y - minimum_y:
            raise ValueError("variant box does not exactly contain lanes and collider")
        if self.variant_id != _variant_id(
            self.variant_id.family_id,
            self.yaw,
            self.machine_origins_x,
            self.placement_geometry,
            self.lane_plan,
            self.attachment_plan,
            self.port_dock_plan,
            self.box_width,
            self.box_height,
        ):
            raise ValueError("strip variant id does not describe its physical geometry")

    @property
    def pitch_x(self) -> int:
        return self.placement_geometry.pitch_x

    @property
    def pitch_y(self) -> int:
        return self.placement_geometry.pitch_y

    @property
    def template_key(self) -> tuple[object, ...]:
        """Count-independent identity of the pose choice this realizes."""
        return (
            self.variant_id.family_id,
            self.yaw,
            self.footprint_width,
            self.footprint_height,
            self.placement_geometry.identity,
            self.lane_plan,
            self.attachment_plan,
            self.port_dock_plan,
            self.box_height,
        )

    @property
    def sort_key(self) -> tuple[object, ...]:
        return (
            self.box_width * self.box_height,
            self.yaw,
            self.lane_plan.lane_rows,
            tuple(plan.identity for plan in self.attachment_plan),
            tuple(plan.identity for plan in self.port_dock_plan),
            self.box_width,
            self.box_height,
            self.placement_geometry.identity,
        )


def strip_pose_id(variant: StripVariant) -> StripPoseId:
    """Return the bounded pose key shared by ordinary and padded variants."""
    geometry = variant.placement_geometry
    return StripPoseId(
        family_id=variant.variant_id.family_id,
        yaw_degrees=int(variant.yaw),
        footprint=(variant.footprint_width, variant.footprint_height),
        placement_geometry=(
            geometry.pitch_y,
            geometry.west_halo,
            geometry.north_halo,
            geometry.south_halo,
        ),
        lane_rows=variant.lane_plan.lane_rows,
        attachments=tuple(plan.identity for plan in variant.attachment_plan),
        port_docks=tuple(plan.identity for plan in variant.port_dock_plan),
        box_height=variant.box_height,
    )


@dataclass(frozen=True, slots=True)
class StripFamily:
    """Placement-independent work and every feasible cardinal physical pose."""

    family_id: StripFamilyId
    group_key: str
    recipe_id: str
    machine_item_id: int
    model_index: int
    total_machine_count: int
    input_lanes: tuple[LogicalLane, ...]
    output_lanes: tuple[LogicalLane, ...]
    variants: tuple[StripVariant, ...]
    mode_params: tuple[int, ...] = ()
    #: Emitted through east-side gap belts by legacy Freeform. East-face
    #: attachments are not yet representable as cardinal lane variants.
    flank_outputs: bool = False
    #: Machines per strip so that no lane this family owns exceeds the
    #: effective lane capacity (multiple-belts design, section 4.1).  0 means
    #: uncapped, which is what every hand-built family gets; the planner's
    #: `generate_strip_families` always sets a positive value.
    machine_cap: int = 0

    def __post_init__(self) -> None:
        if self.family_id.group_key != self.group_key:
            raise ValueError("strip family id and group key disagree")
        if self.total_machine_count <= 0:
            raise ValueError("logical strip family machine count must be positive")
        lanes = self.input_lanes + self.output_lanes
        if len({lane.lane_id for lane in lanes}) != len(lanes):
            raise ValueError("strip family logical lane ids must be unique")
        for variant in self.variants:
            if variant.variant_id.family_id != self.family_id:
                raise ValueError("strip family contains a variant from another family")
            if len(variant.machine_origins_x) != self.total_machine_count:
                raise ValueError("strip family variant machine count is inconsistent")
            endpoints = {plan.lane for plan in variant.attachment_plan} | {
                plan.lane for plan in variant.port_dock_plan
            }
            if endpoints != set(lanes):
                raise ValueError("strip family variant does not serve every logical lane")


@dataclass(frozen=True, order=True, slots=True)
class StripInstanceId:
    """Stable half-open machine ordinal range within a logical family."""

    family_id: StripFamilyId
    machine_start: int
    machine_count: int

    def __post_init__(self) -> None:
        if self.machine_start < 0 or self.machine_count <= 0:
            raise ValueError("strip instance range must be non-negative and non-empty")


@dataclass(frozen=True, slots=True)
class ProjectionPitchRequirement:
    """One exact projected same-strip collision requiring wider X pitch."""

    family_id: StripFamilyId
    instance_id: StripInstanceId
    variant_id: StripVariantId
    axis: Literal["x"]
    rejected_pitch: int
    required_pitch: int
    failure: ProjectionFailure


@dataclass(frozen=True, slots=True)
class StripInstance:
    """A physical family range bound to one pose-valid variant."""

    instance_id: StripInstanceId
    machine_start: int
    machine_count: int
    variant: StripVariant

    def __post_init__(self) -> None:
        if (self.machine_start, self.machine_count) != (
            self.instance_id.machine_start,
            self.instance_id.machine_count,
        ):
            raise ValueError("strip instance id and range disagree")
        if self.variant.variant_id.family_id != self.instance_id.family_id:
            raise ValueError("strip instance variant belongs to another family")
        if len(self.variant.machine_origins_x) != self.machine_count:
            raise ValueError("strip instance variant must realize its exact machine count")
        if self.variant.box_width != self.machine_count * self.variant.pitch_x:
            raise ValueError("strip instance variant box must realize its exact range")

    @property
    def family_id(self) -> StripFamilyId:
        return self.instance_id.family_id

    @property
    def variant_id(self) -> StripVariantId:
        return self.variant.variant_id

    @property
    def machine_stop(self) -> int:
        return self.machine_start + self.machine_count


def _is_machine_building(building: PlacedBuilding) -> bool:
    if (
        catalog.is_belt(building.item_id)
        or catalog.is_sorter(building.item_id)
        or building.item_id == catalog.SPLITTER_ID
    ):
        return False
    try:
        info = catalog.building(building.item_id)
    except KeyError:
        return False
    if info.is_belt_addon:
        return False
    if info.cover_radius <= 0:
        return True
    return any(
        entry.machine_item_id == building.item_id
        for entry in catalog.MODE_DRIVEN_MACHINE.values()
    )


type _ProjectionMachineKey = tuple[int, str | int, int, float, int, int]


def projection_pitch_requirements(
    placement: Placement,
    *,
    instance_ids: tuple[StripInstanceId, ...],
    variants: tuple[StripVariant, ...],
    failures: tuple[ProjectionFailure, ...],
) -> tuple[ProjectionPitchRequirement | None, ...]:
    """Map an ordered batch of collisions through one exact placement index."""
    if (
        not isinstance(instance_ids, tuple)
        or not isinstance(variants, tuple)
        or not instance_ids
        or len(instance_ids) != len(variants)
        or any(
            not isinstance(instance_id, StripInstanceId)
            or not isinstance(variant, StripVariant)
            or variant.variant_id.family_id != instance_id.family_id
            or len(variant.machine_origins_x) != instance_id.machine_count
            or variant.box_width != instance_id.machine_count * variant.pitch_x
            for instance_id, variant in zip(instance_ids, variants, strict=True)
        )
    ):
        return (None,) * len(failures)

    machine_flags: list[bool] = []
    positions_by_key: dict[_ProjectionMachineKey, set[tuple[int, int]]] = {}
    for building in placement.buildings:
        is_machine = _is_machine_building(building)
        machine_flags.append(is_machine)
        owner = building.owner_strip
        if not is_machine or type(owner) is not int or not 0 <= owner < len(variants):
            continue
        key: _ProjectionMachineKey = (
            owner,
            building.item_id,
            building.model_index,
            building.yaw,
            building.width,
            building.height,
        )
        positions_by_key.setdefault(key, set()).add((building.x, building.y))

    ordinals_by_key: dict[_ProjectionMachineKey, dict[tuple[int, int], int]] = {}
    for key, owned_positions in positions_by_key.items():
        owner, _item_id, _model_index, yaw, width, height = key
        variant = variants[owner]
        if (
            yaw != variant.yaw
            or (width, height)
            != (variant.footprint_width, variant.footprint_height)
            or len(owned_positions) != len(variant.machine_origins_x)
        ):
            continue
        local_origin_x = variant.machine_origins_x[0]
        placed_origin_x, placed_origin_y = min(owned_positions)
        translation_x = placed_origin_x - local_origin_x
        translation_y = placed_origin_y - variant.lane_plan.machine_row
        position_ordinals = {
            (
                translation_x + origin_x,
                translation_y + variant.lane_plan.machine_row,
            ): ordinal
            for ordinal, origin_x in enumerate(variant.machine_origins_x)
        }
        if position_ordinals.keys() == owned_positions:
            ordinals_by_key[key] = position_ordinals

    requirements: list[ProjectionPitchRequirement | None] = []
    building_count = len(placement.buildings)
    for failure in failures:
        if failure.check != "geom.collide" or not isinstance(failure.buildings, tuple):
            requirements.append(None)
            continue
        indices = failure.buildings
        if (
            len(indices) != 2
            or indices[0] == indices[1]
            or any(type(index) is not int for index in indices)
            or any(not 0 <= index < building_count for index in indices)
        ):
            requirements.append(None)
            continue

        left = placement.buildings[indices[0]]
        right = placement.buildings[indices[1]]
        owner = left.owner_strip
        if (
            type(owner) is not int
            or type(right.owner_strip) is not int
            or right.owner_strip != owner
            or not 0 <= owner < len(instance_ids)
            or not machine_flags[indices[0]]
            or not machine_flags[indices[1]]
        ):
            requirements.append(None)
            continue
        instance_id = instance_ids[owner]
        variant = variants[owner]
        key = (
            owner,
            left.item_id,
            left.model_index,
            left.yaw,
            left.width,
            left.height,
        )
        ordinals = ordinals_by_key.get(key)
        left_position = (left.x, left.y)
        right_position = (right.x, right.y)
        if (
            (left.item_id, left.model_index, left.yaw)
            != (right.item_id, right.model_index, right.yaw)
            or left.yaw != variant.yaw
            or (left.width, left.height)
            != (variant.footprint_width, variant.footprint_height)
            or (right.width, right.height)
            != (variant.footprint_width, variant.footprint_height)
            or abs(left.x - right.x) != variant.pitch_x
            or ordinals is None
            or left_position not in ordinals
            or right_position not in ordinals
            or abs(ordinals[left_position] - ordinals[right_position]) != 1
        ):
            requirements.append(None)
            continue
        requirements.append(
            ProjectionPitchRequirement(
                family_id=instance_id.family_id,
                instance_id=instance_id,
                variant_id=variant.variant_id,
                axis="x",
                rejected_pitch=variant.pitch_x,
                required_pitch=variant.pitch_x + 1,
                failure=failure,
            )
        )
    return tuple(requirements)


def projection_pitch_requirement(
    placement: Placement,
    *,
    instance_ids: tuple[StripInstanceId, ...],
    variants: tuple[StripVariant, ...],
    failure: ProjectionFailure,
) -> ProjectionPitchRequirement | None:
    """Map one collision through the same exact indexed batch implementation."""
    return projection_pitch_requirements(
        placement,
        instance_ids=instance_ids,
        variants=variants,
        failures=(failure,),
    )[0]


def placement_geometry(machine_item_id: str | int, yaw: float) -> MachinePlacementGeometry:
    """Return authoritative oriented footprint, pitch, and deterministic halos."""
    item_id = (
        catalog.item_id(machine_item_id) if isinstance(machine_item_id, str) else machine_item_id
    )
    footprint_width, footprint_height = catalog.oriented_footprint(item_id, yaw)
    pitch_x, pitch_y = catalog.clearance(item_id, yaw)
    extra_x = pitch_x - footprint_width
    extra_y = pitch_y - footprint_height
    west_halo = extra_x // 2
    north_halo = extra_y // 2
    return MachinePlacementGeometry(
        footprint_width=footprint_width,
        footprint_height=footprint_height,
        pitch_x=pitch_x,
        pitch_y=pitch_y,
        west_halo=west_halo,
        east_halo=extra_x - west_halo,
        north_halo=north_halo,
        south_halo=extra_y - north_halo,
    )


def lane_reach_profiles(
    machine_item_id: str | int,
    yaw: float,
) -> tuple[LaneReachProfile, ...]:
    """Enumerate exact reachable rows outside one pose's collider envelope."""
    item_id = (
        catalog.item_id(machine_item_id) if isinstance(machine_item_id, str) else machine_item_id
    )
    geometry = placement_geometry(item_id, yaw)
    probe = slots.probe_building(item_id, yaw)
    candidate_rows: tuple[tuple[LaneSide, range], ...] = (
        (
            "south",
            range(
                -geometry.north_halo - 1,
                -catalog.SORTER_MAX_REACH - 1,
                -1,
            ),
        ),
        (
            "north",
            range(
                geometry.footprint_height + geometry.south_halo,
                geometry.footprint_height + catalog.SORTER_MAX_REACH,
            ),
        ),
    )
    profiles: list[LaneReachProfile] = []
    for side, rows in candidate_rows:
        for lane_y in rows:
            reachable = slots.attachable_columns(probe, lane_y)
            if reachable:
                profiles.append(
                    LaneReachProfile(
                        side=side,
                        lane_y=lane_y,
                        attachments=tuple(sorted(reachable.items())),
                    )
                )
    return tuple(profiles)


def _input_logical_lanes(
    in_above: Sequence[tuple[str, ...]],
    in_below: Sequence[tuple[str, ...]],
    cargo_domain: CargoDomain,
    output_count: int,
) -> tuple[LogicalLane, ...]:
    return tuple(
        LogicalLane(
            lane_id=f"input:south:{index}",
            kind="input",
            items=items,
            destination_group_keys=(),
            cargo_domain=cargo_domain,
            side="south",
            side_index=index,
        )
        for index, items in enumerate(in_above)
    ) + tuple(
        LogicalLane(
            lane_id=f"input:north:{index}",
            kind="input",
            items=items,
            destination_group_keys=(),
            side="north",
            cargo_domain=cargo_domain,
            side_index=output_count + index,
        )
        for index, items in enumerate(in_below)
    )


def _output_side_assignments(count: int) -> Iterable[tuple[LaneSide, ...]]:
    """Yield the historical face first, then deterministic overflow assignments."""
    return product(("north", "south"), repeat=count)


def _output_logical_lanes(
    plan: _LogicalStripPlan,
    sides: tuple[LaneSide, ...],
) -> tuple[LogicalLane, ...]:
    from flab2bp.layout.freeform import _dests

    if len(sides) != len(plan.out_lanes):
        raise ValueError("output side assignment does not cover every output lane")
    return tuple(
        LogicalLane(
            lane_id=f"output:{side}:{index}",
            kind="output",
            items=(item,),
            destination_group_keys=_dests(destination),
            cargo_domain=cargo_domain,
            side=side,
            side_index=index,
        )
        for index, ((item, destination, cargo_domain), side) in enumerate(
            zip(plan.out_lanes, sides, strict=True)
        )
    )


def _cargo_keys(sinks: Sequence[tuple[str, str, CargoDomain]]) -> set[tuple[str, CargoDomain]]:
    return {(item, cargo_domain) for item, _destination, cargo_domain in sinks}


def _has_exact_two_face_seating(
    item_id: int,
    in_above: Sequence[tuple[str, ...]],
    in_below: Sequence[tuple[str, ...]],
    input_domain: CargoDomain,
    output_count: int,
) -> bool:
    """Prove one lane per cargo key against exact rows, slots, and sorter spans."""
    # One lane occupies one row, and each of the two faces exposes at most the
    # catalog reach in contiguous rows.  Reject above that physical constant
    # before enumerating side assignments; input size never sets this search.
    if output_count > 2 * catalog.SORTER_MAX_REACH:
        return False
    inputs = _input_logical_lanes(in_above, in_below, input_domain, output_count)
    for sides in _output_side_assignments(output_count):
        outputs = tuple(
            LogicalLane(
                lane_id=f"output:{side}:{index}",
                kind="output",
                items=(f"cargo-{index}",),
                destination_group_keys=(),
                cargo_domain=CargoDomain.UNSPRAYED,
                side=side,
                side_index=index,
            )
            for index, side in enumerate(sides)
        )
        lanes = inputs + outputs
        if any(
            _attachment_plan_seatings(item_id, yaw, lanes)
            for yaw in _CARDINAL_YAWS
        ):
            return True
    return False


def _logical_strip_plans(
    spec: BuildSpec,
    *,
    prefer_shared_proliferation: bool = False,
) -> tuple[_LogicalStripPlan, ...]:
    """Allocate lane shards, admitting exact two-face output overflow.

    The historical planner budgets outputs only on the face below the machine
    band.  Keep that byte-identical path whenever it can represent every cargo
    key.  When it cannot, ask the pose-aware slot matcher whether the minimum
    one-lane-per-cargo representation fits across both existing faces.  This is
    an exact legality proof, not a widened reach: every accepted connection has
    a prefab slot and a span no greater than ``SORTER_MAX_REACH``.
    """
    from flab2bp.layout.freeform import (
        DEST_SEP,
        _adapt,
        _allocate_machines,
        _flank_seat,
        _merge_lanes,
        _seat_inputs,
        _shard_sinks,
        _sink_demand,
    )

    groups = _adapt(spec)
    producers: dict[str, list[str]] = defaultdict(list)
    for key, group in groups.items():
        for item in group.outputs:
            producers[item].append(key)

    consumers: dict[tuple[str, str], list[str]] = defaultdict(list)
    for key, group in groups.items():
        for item in group.inputs:
            for source in producers.get(item, []):
                consumers[source, item].append(key)

    plans: list[_LogicalStripPlan] = []
    for key, group in groups.items():
        above_cap, below_cap = _legacy_side_lane_caps(
            group.item_id,
            group.yaw,
            group.pitch_h,
        )
        input_items = tuple(sorted(group.inputs))
        sinks: list[tuple[str, str, CargoDomain]] = []
        for item in sorted(group.outputs):
            destinations = consumers.get((key, item), [])
            boundary = item in spec.outputs or item in spec.surplus_outputs
            shared_boundary: str | None = None
            if item in spec.surplus_outputs and destinations:
                surplus = spec.surplus_outputs[item]
                shareable = [
                    destination
                    for destination in destinations
                    if not groups[destination].proliferated
                    and surplus + _sink_demand(groups, spec, item, destination)
                    <= spec.lane_capacity
                ]
                if shareable:
                    shared_boundary = min(
                        shareable,
                        key=lambda destination: (
                            _sink_demand(groups, spec, item, destination),
                            destination,
                        ),
                    )
                    boundary = False
            sinks.extend(
                (
                    item,
                    (
                        DEST_SEP.join((destination, ""))
                        if destination == shared_boundary
                        else destination
                    ),
                    (
                        CargoDomain.REQUIRES_SPRAY
                        if groups[destination].proliferated
                        else CargoDomain.UNSPRAYED
                    ),
                )
                for destination in destinations
            )
            if boundary or not destinations:
                sinks.append((item, "", CargoDomain.UNSPRAYED))

        prefer_shared_inputs = (
            prefer_shared_proliferation
            and group.proliferated
            and len(input_items) >= 3
        )
        group_input_rates = tuple(group.inputs.items())

        def input_lane_fits(
            lane: tuple[str, ...],
            input_rates: tuple[tuple[str, Fraction], ...] = group_input_rates,
            machine_count: int = group.count,
        ) -> bool:
            total = sum(
                (
                    rate * machine_count
                    for item, rate in input_rates
                    if item in lane
                ),
                spec.lane_capacity * 0,
            )
            return total <= spec.lane_capacity

        probe = slots.probe_building(group.item_id, group.yaw)
        columns = len(slots.attachable_columns(probe, -1)) or 1
        flank = False
        try:
            in_above, in_below = _seat_inputs(
                input_items,
                len(sinks),
                above_cap,
                below_cap,
                max_per_lane=group.width,
                columns=columns,
                prefer_shared=prefer_shared_inputs,
                lane_fits=input_lane_fits if prefer_shared_inputs else None,
            )
        except ValueError as exc:
            seat = (
                _flank_seat(group.item_id, group.yaw, group.pitch_w)
                if len(sinks) == 1
                else None
            )
            if seat is None:
                raise ValueError(f"recipe {group.recipe_id!r}: {exc}") from None
            try:
                in_above, in_below = _seat_inputs(
                    input_items,
                    len(sinks),
                    above_cap,
                    below_cap,
                    max_per_lane=group.width,
                    columns=columns,
                    flank_outputs=True,
                    prefer_shared=prefer_shared_inputs,
                    lane_fits=input_lane_fits if prefer_shared_inputs else None,
                )
            except ValueError as flanked:
                raise ValueError(f"recipe {group.recipe_id!r}: {flanked}") from None
            flank = True

        south_columns = len(slots.attachable_columns(probe, group.pitch_h))
        out_capacity = below_cap - len(in_below)
        if flank:
            out_capacity = min(out_capacity, 1)
        elif south_columns:
            out_capacity = min(
                out_capacity,
                south_columns - sum(len(lane) for lane in in_below),
            )

        cargo_count = len(_cargo_keys(sinks))
        input_domain = (
            CargoDomain.REQUIRES_SPRAY
            if group.proliferated
            else CargoDomain.UNSPRAYED
        )
        if (
            not flank
            and cargo_count > out_capacity
            and _has_exact_two_face_seating(
                group.item_id,
                in_above,
                in_below,
                input_domain,
                cargo_count,
            )
        ):
            out_capacity = cargo_count

        shards = (
            _shard_sinks(sinks, cap=out_capacity, max_shards=group.count)
            if sinks
            else [[]]
        )
        demand = {
            (item, destination, cargo_domain): _sink_demand(
                groups,
                spec,
                item,
                destination,
            )
            for item, destination, cargo_domain in sinks
        }
        allocation_demand = {
            (item, destination, cargo_domain): _sink_demand(
                groups,
                spec,
                item,
                destination,
                include_boundary=False,
            )
            for item, destination, cargo_domain in sinks
        }
        per_shard = (
            _allocate_machines(group.count, shards, allocation_demand)
            if len(shards) > 1
            else [group.count]
        )
        try:
            lane_shards = [
                _merge_lanes(
                    shard,
                    out_capacity,
                    demand,
                    spec.lane_capacity,
                )
                for shard in shards
            ]
        except ValueError as exc:
            raise ValueError(f"recipe {group.recipe_id!r}: {exc}") from None

        for shard_index, (lane_shard, machine_count) in enumerate(
            zip(lane_shards, per_shard, strict=True)
        ):
            if machine_count <= 0:
                continue
            plans.append(
                _LogicalStripPlan(
                    group_key=key,
                    shard_index=shard_index,
                    recipe_id=group.recipe_id,
                    item_id=group.item_id,
                    model_index=group.model_index,
                    total_machine_count=machine_count,
                    cargo_domain=input_domain,
                    in_above=in_above,
                    out_lanes=tuple(lane_shard),
                    in_below=in_below,
                    mode_params=group.mode_params,
                    flank_outputs=flank,
                )
            )
    return tuple(plans)


def _legacy_side_lane_caps(item_id: int, yaw: float, band_rows: int) -> tuple[int, int]:
    from flab2bp.layout.freeform import _side_lane_caps

    return _side_lane_caps(item_id, yaw, band_rows)


def _logical_lanes(
    plan: _LogicalStripPlan,
    output_sides: tuple[LaneSide, ...] | None = None,
) -> tuple[tuple[LogicalLane, ...], tuple[LogicalLane, ...]]:
    default_output_side: LaneSide = "north"
    sides = output_sides or (default_output_side,) * len(plan.out_lanes)
    return (
        _input_logical_lanes(
            plan.in_above,
            plan.in_below,
            plan.cargo_domain,
            len(plan.out_lanes),
        ),
        _output_logical_lanes(plan, sides),
    )


def _match_attachment_plans(
    seatings: tuple[tuple[LogicalLane, LaneReachProfile], ...],
) -> tuple[LaneAttachmentPlan, ...] | None:
    """Choose the lexicographically first complete one-sorter-per-slot matching."""
    demands = tuple((lane, profile, item) for lane, profile in seatings for item in lane.items)
    available_slots = {
        attachment.slot
        for _lane, profile in seatings
        for _column, attachment in profile.attachments
    }
    if len(demands) > len(available_slots):
        return None

    selected: list[tuple[int, slots.Attachment] | None] = [None] * len(demands)
    used_slots: set[int] = set()

    def match(index: int) -> bool:
        if index == len(demands):
            return True
        _lane, profile, _item = demands[index]
        for candidate in profile.attachments:
            slot = candidate[1].slot
            if slot in used_slots:
                continue
            selected[index] = candidate
            used_slots.add(slot)
            if match(index + 1):
                return True
            used_slots.remove(slot)
            selected[index] = None
        return False

    if not match(0):
        return None

    plans: list[LaneAttachmentPlan] = []
    offset = 0
    for lane, profile in seatings:
        chosen = selected[offset : offset + len(lane.items)]
        offset += len(lane.items)
        if any(candidate is None for candidate in chosen):
            raise AssertionError("complete sorter-slot matching left an item unmatched")
        plans.append(
            LaneAttachmentPlan(
                lane=lane,
                lane_y=profile.lane_y,
                attachments=tuple(
                    LaneSorterAttachment(
                        item=item,
                        column=candidate[0],
                        cell=candidate[1].cell,
                        slot=candidate[1].slot,
                        span=candidate[1].span,
                    )
                    for item, possible in zip(lane.items, chosen, strict=True)
                    if (candidate := possible) is not None
                ),
            )
        )
    return tuple(plans)


def _side_seatings(
    lanes: tuple[LogicalLane, ...],
    profiles: tuple[LaneReachProfile, ...],
    side: LaneSide,
) -> tuple[tuple[tuple[LogicalLane, LaneReachProfile], ...], ...]:
    side_lanes = tuple(
        sorted(
            (lane for lane in lanes if lane.side == side),
            key=lambda lane: (lane.side_index, lane.lane_id),
        )
    )
    if not side_lanes:
        return ((),)
    side_profiles = tuple(profile for profile in profiles if profile.side == side)
    seatings: list[tuple[tuple[LogicalLane, LaneReachProfile], ...]] = []
    for selected in combinations(side_profiles, len(side_lanes)):
        ordered = tuple(sorted(selected, key=lambda profile: profile.lane_y))
        if all(
            len(profile.attachments) >= len(lane.items)
            for lane, profile in zip(side_lanes, ordered, strict=True)
        ):
            seatings.append(tuple(zip(side_lanes, ordered, strict=True)))
    return tuple(seatings)


def _attachment_plan_seatings(
    item_id: int,
    yaw: float,
    lanes: tuple[LogicalLane, ...],
) -> tuple[tuple[LaneAttachmentPlan, ...], ...]:
    profiles = lane_reach_profiles(item_id, yaw)
    south = _side_seatings(lanes, profiles, "south")
    north = _side_seatings(lanes, profiles, "north")
    seatings: list[tuple[LaneAttachmentPlan, ...]] = []
    for south_seatings, north_seatings in product(south, north):
        selected = tuple(
            sorted(
                south_seatings + north_seatings,
                key=lambda seating: (seating[1].lane_y, seating[0].lane_id),
            )
        )
        plans = _match_attachment_plans(selected)
        if plans is not None:
            seatings.append(plans)
    return tuple(seatings)


def _variant_id(
    family_id: StripFamilyId,
    yaw: float,
    machine_origins_x: tuple[int, ...],
    geometry: MachinePlacementGeometry,
    lane_plan: LanePlan,
    attachments: tuple[LaneAttachmentPlan, ...],
    port_docks: tuple[LanePortDockPlan, ...],
    box_width: int,
    box_height: int,
) -> StripVariantId:
    return StripVariantId(
        family_id=family_id,
        yaw_degrees=int(yaw),
        machine_origins_x=machine_origins_x,
        footprint=(geometry.footprint_width, geometry.footprint_height),
        placement_geometry=geometry.identity,
        lane_rows=lane_plan.lane_rows,
        attachments=tuple(plan.identity for plan in attachments),
        port_docks=tuple(plan.identity for plan in port_docks),
        box=(box_width, box_height),
    )


def _with_projection_safe_pitch(
    item_id: int,
    variant: StripVariant,
) -> StripVariant:
    """Reserve the shared exact pitch before either strategy sees a variant."""
    required = projection_safe_machine_pitch_x(
        item_id,
        variant.yaw,
        machine_count=len(variant.machine_origins_x),
        box_height=variant.box_height,
    )
    return variant_with_minimum_pitch(variant, required)


def _port_variants(
    family_id: StripFamilyId,
    item_id: int,
    machine_count: int,
    input_lanes: tuple[LogicalLane, ...],
    output_lanes: tuple[LogicalLane, ...],
    yaw: float,
) -> tuple[StripVariant, ...]:
    """Bind sorterless pure-source lanes to the prefab's drawing belt ports."""
    if input_lanes or not output_lanes:
        return ()
    geometry = placement_geometry(item_id, yaw)
    available = tuple(
        dock
        for _port, dock in sorted(slots.port_docks(slots.probe_building(item_id, yaw)).items())
        if dock.facing.delta[1] > 0
    )
    ordered_lanes = tuple(sorted(output_lanes, key=lambda lane: (lane.side_index, lane.lane_id)))
    if len(available) < len(ordered_lanes):
        return ()
    lane_start = max(
        geometry.footprint_height + geometry.south_halo,
        *(dock.cell[1] + 1 for dock in available[: len(ordered_lanes)]),
    )
    port_docks = tuple(
        LanePortDockPlan(
            lane=lane,
            lane_y=lane_start + index,
            port=dock.port,
            cell=dock.cell,
            facing=dock.facing,
        )
        for index, (lane, dock) in enumerate(zip(ordered_lanes, available, strict=False))
    )
    lane_rows = tuple((plan.lane.lane_id, plan.lane_y) for plan in port_docks)
    minimum_y = -geometry.north_halo
    maximum_y = max(
        geometry.footprint_height + geometry.south_halo,
        *(plan.lane_y + 1 for plan in port_docks),
    )
    lane_plan = LanePlan(machine_row=-minimum_y, lane_rows=lane_rows)
    box_width = machine_count * geometry.pitch_x
    box_height = maximum_y - minimum_y
    machine_origins_x = tuple(range(0, machine_count * geometry.pitch_x, geometry.pitch_x))
    variant_id = _variant_id(
        family_id,
        yaw,
        machine_origins_x,
        geometry,
        lane_plan,
        (),
        port_docks,
        box_width,
        box_height,
    )
    return (
        _with_projection_safe_pitch(
            item_id,
            StripVariant(
                variant_id=variant_id,
                yaw=yaw,
                footprint_width=geometry.footprint_width,
                footprint_height=geometry.footprint_height,
                placement_geometry=geometry,
                lane_plan=lane_plan,
                box_width=box_width,
                box_height=box_height,
                attachment_plan=(),
                port_dock_plan=port_docks,
                machine_origins_x=machine_origins_x,
            ),
        ),
    )


def _variants(
    family_id: StripFamilyId,
    item_id: int,
    machine_count: int,
    lanes: tuple[LogicalLane, ...],
    yaw: float,
) -> tuple[StripVariant, ...]:
    geometry = placement_geometry(item_id, yaw)
    variants: list[StripVariant] = []
    for attachments in _attachment_plan_seatings(item_id, yaw, lanes):
        lane_rows = tuple((plan.lane.lane_id, plan.lane_y) for plan in attachments)
        minimum_y = min(-geometry.north_halo, *(row for _lane_id, row in lane_rows))
        maximum_y = max(
            geometry.footprint_height + geometry.south_halo,
            *(row + 1 for _lane_id, row in lane_rows),
        )
        lane_plan = LanePlan(machine_row=-minimum_y, lane_rows=lane_rows)
        box_width = machine_count * geometry.pitch_x
        box_height = maximum_y - minimum_y
        machine_origins_x = tuple(range(0, machine_count * geometry.pitch_x, geometry.pitch_x))
        variant_id = _variant_id(
            family_id,
            yaw,
            machine_origins_x,
            geometry,
            lane_plan,
            attachments,
            (),
            box_width,
            box_height,
        )
        variants.append(
            _with_projection_safe_pitch(
                item_id,
                StripVariant(
                    variant_id=variant_id,
                    yaw=yaw,
                    footprint_width=geometry.footprint_width,
                    footprint_height=geometry.footprint_height,
                    placement_geometry=geometry,
                    lane_plan=lane_plan,
                    box_width=box_width,
                    box_height=box_height,
                    attachment_plan=attachments,
                    port_dock_plan=(),
                    machine_origins_x=machine_origins_x,
                ),
            )
        )
    return tuple(variants)


def _machine_cap(group: _Group, spec: BuildSpec) -> int:
    """Machines per strip so no single-item lane exceeds its effective capacity.

    A strip's input lane for item X carries ``count * inputs[X]`` and its
    output lanes for item Y carry at most ``count * outputs[Y]``, so the cap
    is the floor of capacity over the largest per-machine single-item rate.
    A machine whose one rate exceeds the capacity cannot be served by any
    strip length; that is refused here, early and with the numbers, instead
    of late by ``flow.belt_capacity``.
    """
    cap: int | None = None
    for item, rate in (*group.inputs.items(), *group.outputs.items()):
        capacity = spec.lane_capacity * spec.planning_stack(item)
        if rate > capacity:
            raise NoValidLayout(
                f"recipe {group.recipe_id!r}: one machine moves {rate} items/s of "
                f"{item!r}, over the {capacity}/s the fastest belt this save can build "
                f"sustains ({spec.belt_tiers[-1].item_id}); no strip length can carry it",
                spec_label=spec.label,
                budget_s=0.0,
                attempt_reasons=(),
                attempt_failures=(),
                projection_failures=(),
            )
        fits = int(capacity // rate)
        cap = fits if cap is None else min(cap, fits)
    return max(1, cap) if cap is not None else 0


def generate_strip_families(
    spec: BuildSpec,
    *,
    prefer_shared_proliferation: bool = False,
) -> tuple[StripFamily, ...]:
    """Generate deterministic pose-valid variants for every logical lane shard."""
    from flab2bp.layout.freeform import _adapt

    groups = _adapt(spec)
    families: list[StripFamily] = []
    for plan in _logical_strip_plans(
        spec,
        prefer_shared_proliferation=prefer_shared_proliferation,
    ):
        family_id = StripFamilyId(plan.group_key, plan.shard_index)
        building = catalog.building(plan.item_id)
        input_lanes, output_lanes = _logical_lanes(plan)
        generated: tuple[StripVariant, ...]
        if plan.flank_outputs:
            generated = ()
        elif building.takes_belt_ports and not building.slot_poses:
            generated = tuple(
                candidate
                for yaw in _CARDINAL_YAWS
                for candidate in _port_variants(
                    family_id,
                    plan.item_id,
                    plan.total_machine_count,
                    input_lanes,
                    output_lanes,
                    yaw,
                )
            )
        else:
            generated = ()
            for sides in _output_side_assignments(len(plan.out_lanes)):
                candidate_inputs, candidate_outputs = _logical_lanes(plan, sides)
                candidates = tuple(
                    candidate
                    for yaw in _CARDINAL_YAWS
                    for candidate in _variants(
                        family_id,
                        plan.item_id,
                        plan.total_machine_count,
                        candidate_inputs + candidate_outputs,
                        yaw,
                    )
                )
                if candidates:
                    input_lanes = candidate_inputs
                    output_lanes = candidate_outputs
                    generated = candidates
                    break
        unique = {candidate.variant_id: candidate for candidate in generated}
        variants = tuple(sorted(unique.values(), key=lambda candidate: candidate.sort_key))
        families.append(
            StripFamily(
                family_id=family_id,
                group_key=plan.group_key,
                recipe_id=plan.recipe_id,
                machine_item_id=plan.item_id,
                model_index=plan.model_index,
                total_machine_count=plan.total_machine_count,
                input_lanes=input_lanes,
                output_lanes=output_lanes,
                variants=variants,
                mode_params=plan.mode_params,
                flank_outputs=plan.flank_outputs,
                machine_cap=_machine_cap(groups[plan.group_key], spec),
            )
        )
    return tuple(families)


def default_strip_variant(family: StripFamily) -> StripVariant:
    """Choose the legacy Freeform pose, with deterministic physical tie-breaking."""
    if not family.variants:
        raise ValueError("logical strip family has no pose-valid default variant")
    preferred_yaw = slots.lane_orientation(family.machine_item_id)
    preferred = tuple(variant for variant in family.variants if variant.yaw == preferred_yaw)
    return min(preferred or family.variants, key=lambda variant: variant.sort_key)


def _variant_for_count(template: StripVariant, machine_count: int) -> StripVariant:
    if machine_count <= 0:
        raise ValueError("realized strip variant machine count must be positive")
    machine_origins_x = tuple(range(0, machine_count * template.pitch_x, template.pitch_x))
    box_width = machine_count * template.pitch_x
    variant_id = _variant_id(
        template.variant_id.family_id,
        template.yaw,
        machine_origins_x,
        template.placement_geometry,
        template.lane_plan,
        template.attachment_plan,
        template.port_dock_plan,
        box_width,
        template.box_height,
    )
    return StripVariant(
        variant_id=variant_id,
        yaw=template.yaw,
        footprint_width=template.footprint_width,
        footprint_height=template.footprint_height,
        placement_geometry=template.placement_geometry,
        lane_plan=template.lane_plan,
        box_width=box_width,
        box_height=template.box_height,
        attachment_plan=template.attachment_plan,
        port_dock_plan=template.port_dock_plan,
        machine_origins_x=machine_origins_x,
    )


def variant_with_minimum_pitch(
    variant: StripVariant,
    required_pitch_x: int,
) -> StripVariant:
    """Regenerate a physically distinct variant at the required X pitch."""
    geometry = variant.placement_geometry.with_minimum_pitch_x(required_pitch_x)
    if geometry is variant.placement_geometry:
        return variant
    machine_count = len(variant.machine_origins_x)
    machine_origins_x = tuple(range(0, machine_count * geometry.pitch_x, geometry.pitch_x))
    box_width = machine_count * geometry.pitch_x
    variant_id = _variant_id(
        variant.variant_id.family_id,
        variant.yaw,
        machine_origins_x,
        geometry,
        variant.lane_plan,
        variant.attachment_plan,
        variant.port_dock_plan,
        box_width,
        variant.box_height,
    )
    return StripVariant(
        variant_id=variant_id,
        yaw=variant.yaw,
        footprint_width=variant.footprint_width,
        footprint_height=variant.footprint_height,
        placement_geometry=geometry,
        lane_plan=variant.lane_plan,
        box_width=box_width,
        box_height=variant.box_height,
        attachment_plan=variant.attachment_plan,
        port_dock_plan=variant.port_dock_plan,
        machine_origins_x=machine_origins_x,
    )


def variants_for_count(
    family: StripFamily,
    machine_count: int,
) -> tuple[StripVariant, ...]:
    """Realize every family pose in stable family order for ``machine_count``."""
    return tuple(_variant_for_count(template, machine_count) for template in family.variants)


def _family_pose_minimum_pitches(family: StripFamily) -> dict[StripPoseId, int]:
    minimum_pitches: dict[StripPoseId, int] = {}
    for candidate in family.variants:
        pose_id = strip_pose_id(candidate)
        minimum_pitches[pose_id] = min(
            candidate.pitch_x,
            minimum_pitches.get(pose_id, candidate.pitch_x),
        )
    return minimum_pitches


def partition_strip_variant(
    family: StripFamily,
    variant: StripVariant,
    *,
    max_machine_count: int,
) -> tuple[StripInstance, ...]:
    """Partition a family through one explicit ordinary or padded variant."""
    if max_machine_count <= 0:
        raise ValueError("maximum strip machine count must be positive")
    minimum_pitches = _family_pose_minimum_pitches(family)
    pose_id = strip_pose_id(variant)
    if variant.variant_id.family_id != family.family_id or pose_id not in minimum_pitches:
        raise ValueError("strip instance variant does not belong to the family")
    if variant.pitch_x < minimum_pitches[pose_id]:
        raise ValueError("strip instance variant pitch is below the ordinary family pose")
    instance_count = max(
        1,
        (family.total_machine_count + max_machine_count - 1) // max_machine_count,
    )
    base, extra = divmod(family.total_machine_count, instance_count)
    instances: list[StripInstance] = []
    machine_start = 0
    for index in range(instance_count):
        machine_count = base + (1 if index < extra else 0)
        instance_id = StripInstanceId(family.family_id, machine_start, machine_count)
        instances.append(
            StripInstance(
                instance_id=instance_id,
                machine_start=machine_start,
                machine_count=machine_count,
                variant=_variant_for_count(variant, machine_count),
            )
        )
        machine_start += machine_count
    result = tuple(instances)
    validate_instance_partition(family, result)
    return result


def partition_strip_family(
    family: StripFamily,
    *,
    max_machine_count: int,
    variant_id: StripVariantId | None = None,
) -> tuple[StripInstance, ...]:
    """Choose an ordinary family variant and partition its logical work."""
    if max_machine_count <= 0:
        raise ValueError("maximum strip machine count must be positive")
    chosen_id = variant_id or default_strip_variant(family).variant_id
    try:
        variant = next(
            candidate for candidate in family.variants if candidate.variant_id == chosen_id
        )
    except StopIteration:
        raise ValueError("strip instance variant does not belong to the family") from None
    return partition_strip_variant(
        family,
        variant,
        max_machine_count=max_machine_count,
    )


def split_strip_instance(
    family: StripFamily,
    parent: StripInstance,
    *,
    left_machine_count: int | None = None,
    child_variant_indices: tuple[int, int] | None = None,
) -> tuple[StripInstance, StripInstance]:
    """Partition one physical range into deterministic count-realized children."""
    if parent.family_id != family.family_id:
        raise ValueError("split parent belongs to another logical family")
    if parent.machine_stop > family.total_machine_count:
        raise ValueError("split parent extends beyond its logical family")
    if parent.machine_count < 2:
        raise ValueError("a one-machine strip cannot be split")
    left_count = (
        (parent.machine_count + 1) // 2 if left_machine_count is None else left_machine_count
    )
    if not 0 < left_count < parent.machine_count:
        raise ValueError("split boundary must lie inside the parent range")
    right_count = parent.machine_count - left_count

    if child_variant_indices is None:
        try:
            parent_index = next(
                index
                for index, variant in enumerate(family.variants)
                if variant.template_key == parent.variant.template_key
            )
        except StopIteration:
            raise ValueError("split parent variant is outside its logical family") from None
        child_variant_indices = (parent_index, parent_index)
    if (
        not isinstance(child_variant_indices, tuple)
        or len(child_variant_indices) != 2
        or any(
            type(index) is not int or not 0 <= index < len(family.variants)
            for index in child_variant_indices
        )
    ):
        raise ValueError("split children require two pose-valid family variant indices")

    children: list[StripInstance] = []
    start = parent.machine_start
    for count, variant_index in zip(
        (left_count, right_count),
        child_variant_indices,
        strict=True,
    ):
        instance_id = StripInstanceId(family.family_id, start, count)
        children.append(
            StripInstance(
                instance_id=instance_id,
                machine_start=start,
                machine_count=count,
                variant=_variant_for_count(family.variants[variant_index], count),
            )
        )
        start += count
    return children[0], children[1]


def merge_strip_instances(
    family: StripFamily,
    left: StripInstance,
    right: StripInstance,
) -> StripInstance | None:
    """Merge adjacent compatible ranges, or return ``None`` when illegal."""
    if (
        left.family_id != family.family_id
        or right.family_id != family.family_id
        or left.machine_stop != right.machine_start
        or left.variant.template_key != right.variant.template_key
        or right.machine_stop > family.total_machine_count
    ):
        return None
    machine_count = left.machine_count + right.machine_count
    instance_id = StripInstanceId(
        family_id=family.family_id,
        machine_start=left.machine_start,
        machine_count=machine_count,
    )
    return StripInstance(
        instance_id=instance_id,
        machine_start=left.machine_start,
        machine_count=machine_count,
        variant=_variant_for_count(left.variant, machine_count),
    )


def validate_instance_partition(
    family: StripFamily,
    instances: tuple[StripInstance, ...],
) -> None:
    """Require active physical ranges to cover ``0..total`` exactly once."""
    expected_start = 0
    minimum_pitches = _family_pose_minimum_pitches(family)
    for instance in sorted(instances, key=lambda candidate: candidate.machine_start):
        if instance.family_id != family.family_id:
            raise ValueError("strip instances do not partition one logical family")
        pose_id = strip_pose_id(instance.variant)
        minimum_pitch = minimum_pitches.get(pose_id)
        if minimum_pitch is None:
            raise ValueError("strip instance uses a variant outside its family")
        if instance.variant.pitch_x < minimum_pitch:
            raise ValueError("strip instance variant pitch is below the ordinary family pose")
        if instance.machine_start != expected_start:
            raise ValueError("strip instance ranges do not partition the logical family")
        expected_start = instance.machine_stop
    if expected_start != family.total_machine_count:
        raise ValueError("strip instance ranges do not partition the logical family")


__all__ = [
    "CargoDomain",
    "LaneAttachmentPlan",
    "LanePortDockPlan",
    "LanePlan",
    "LaneReachProfile",
    "LaneSorterAttachment",
    "LogicalLane",
    "MachinePlacementGeometry",
    "ProjectionPitchRequirement",
    "StripFamily",
    "StripFamilyId",
    "StripInstance",
    "StripInstanceId",
    "StripPoseId",
    "StripVariant",
    "StripVariantId",
    "default_strip_variant",
    "generate_strip_families",
    "lane_reach_profiles",
    "merge_strip_instances",
    "partition_strip_family",
    "partition_strip_variant",
    "placement_geometry",
    "projection_pitch_requirement",
    "projection_pitch_requirements",
    "split_strip_instance",
    "strip_pose_id",
    "validate_instance_partition",
    "variants_for_count",
    "variant_with_minimum_pitch",
]
