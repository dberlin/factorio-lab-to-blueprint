"""Immutable logical strip families and pose-valid physical variants.

Logical rate/shard allocation remains independent of placement.  This module
turns each logical shard into cardinal pose candidates using the same catalog
and slot helpers used by validation.  Every variant seats lanes outside the
collider exclusion envelope and carries the exact slot attachments emission
must reproduce.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations, product
from typing import Literal

from flab2bp.dsp import catalog
from flab2bp.layout import slots
from flab2bp.layout.freeform import _dests, _logical_strip_plans, _LogicalStripPlan
from flab2bp.spec import BuildSpec

LaneKind = Literal["input", "output"]
LaneSide = Literal["north", "south"]
_CARDINAL_YAWS = (0.0, 90.0, 180.0, 270.0)


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
    box: tuple[int, int]


@dataclass(frozen=True, slots=True)
class StripVariant:
    """One atomic pose, exclusion envelope, lane plan, and attachment plan."""

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
        if tuple(plan.lane.lane_id for plan in self.attachment_plan) != tuple(
            lane_id for lane_id, _row in self.lane_plan.lane_rows
        ):
            raise ValueError("variant lane and attachment plans disagree")
        if any(planned_rows[plan.lane.lane_id] != plan.lane_y for plan in self.attachment_plan):
            raise ValueError("variant attachments must use their planned lane rows")
        attachment_slots = tuple(
            attachment.slot for plan in self.attachment_plan for attachment in plan.attachments
        )
        if len(set(attachment_slots)) != len(attachment_slots):
            raise ValueError("variant attachments must use globally distinct machine slots")
        lane_ys = tuple(plan.lane_y for plan in self.attachment_plan)
        envelope_top = -self.placement_geometry.north_halo
        envelope_bottom = self.footprint_height + self.placement_geometry.south_halo
        if any(envelope_top <= lane_y < envelope_bottom for lane_y in lane_ys):
            raise ValueError("variant lane enters the collider exclusion envelope")
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
            self.box_height,
        )

    @property
    def sort_key(self) -> tuple[object, ...]:
        return (
            self.box_width * self.box_height,
            self.yaw,
            self.lane_plan.lane_rows,
            tuple(plan.identity for plan in self.attachment_plan),
            self.box_width,
            self.box_height,
            self.placement_geometry.identity,
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
            if {plan.lane for plan in variant.attachment_plan} != set(lanes):
                raise ValueError("strip family variant does not attach every logical lane")


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


def _logical_lanes(
    plan: _LogicalStripPlan,
) -> tuple[tuple[LogicalLane, ...], tuple[LogicalLane, ...]]:
    in_above = plan.in_above
    out_lanes = plan.out_lanes
    in_below = plan.in_below
    inputs = tuple(
        LogicalLane(
            lane_id=f"input:south:{index}",
            kind="input",
            items=items,
            destination_group_keys=(),
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
            side_index=len(out_lanes) + index,
        )
        for index, items in enumerate(in_below)
    )
    outputs = tuple(
        LogicalLane(
            lane_id=f"output:north:{index}",
            kind="output",
            items=(item,),
            destination_group_keys=_dests(destination),
            side="north",
            side_index=index,
        )
        for index, (item, destination) in enumerate(out_lanes)
    )
    return inputs, outputs


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
        box=(box_width, box_height),
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
            box_width,
            box_height,
        )
        variants.append(
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
                machine_origins_x=machine_origins_x,
            )
        )
    return tuple(variants)


def generate_strip_families(spec: BuildSpec) -> tuple[StripFamily, ...]:
    """Generate deterministic pose-valid variants for every logical lane shard."""
    families: list[StripFamily] = []
    for plan in _logical_strip_plans(spec):
        family_id = StripFamilyId(plan.group_key, plan.shard_index)
        input_lanes, output_lanes = _logical_lanes(plan)
        lanes = input_lanes + output_lanes
        generated = (
            ()
            if plan.flank_outputs
            else tuple(
                candidate
                for yaw in _CARDINAL_YAWS
                for candidate in _variants(
                    family_id,
                    plan.item_id,
                    plan.total_machine_count,
                    lanes,
                    yaw,
                )
            )
        )
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
        machine_origins_x=machine_origins_x,
    )


def variants_for_count(
    family: StripFamily,
    machine_count: int,
) -> tuple[StripVariant, ...]:
    """Realize every family pose in stable family order for ``machine_count``."""
    return tuple(_variant_for_count(template, machine_count) for template in family.variants)


def partition_strip_family(
    family: StripFamily,
    *,
    max_machine_count: int,
    variant_id: StripVariantId | None = None,
) -> tuple[StripInstance, ...]:
    """Create balanced initial physical ranges without mutating the logical family."""
    if max_machine_count <= 0:
        raise ValueError("maximum strip machine count must be positive")
    chosen_id = variant_id or default_strip_variant(family).variant_id
    try:
        template = next(variant for variant in family.variants if variant.variant_id == chosen_id)
    except StopIteration:
        raise ValueError("strip instance variant does not belong to the family") from None
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
                variant=_variant_for_count(template, machine_count),
            )
        )
        machine_start += machine_count
    result = tuple(instances)
    validate_instance_partition(family, result)
    return result


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
    valid_templates = {variant.template_key for variant in family.variants}
    for instance in sorted(instances, key=lambda candidate: candidate.machine_start):
        if instance.family_id != family.family_id:
            raise ValueError("strip instances do not partition one logical family")
        if instance.variant.template_key not in valid_templates:
            raise ValueError("strip instance uses a variant outside its family")
        if instance.machine_start != expected_start:
            raise ValueError("strip instance ranges do not partition the logical family")
        expected_start = instance.machine_stop
    if expected_start != family.total_machine_count:
        raise ValueError("strip instance ranges do not partition the logical family")


__all__ = [
    "LaneAttachmentPlan",
    "LanePlan",
    "LaneReachProfile",
    "LaneSorterAttachment",
    "LogicalLane",
    "MachinePlacementGeometry",
    "StripFamily",
    "StripFamilyId",
    "StripInstance",
    "StripInstanceId",
    "StripVariant",
    "StripVariantId",
    "default_strip_variant",
    "generate_strip_families",
    "lane_reach_profiles",
    "merge_strip_instances",
    "partition_strip_family",
    "placement_geometry",
    "split_strip_instance",
    "validate_instance_partition",
    "variants_for_count",
]
