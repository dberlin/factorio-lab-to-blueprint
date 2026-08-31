"""DSP Splitter port acceptance derived from the game's exact port poses.

A belt-to-Splitter connection names one of the Splitter prefab's four
``PrefabDesc.portPoses`` entries.  The index is physical: after the Splitter's
model yaw is applied, its forward vector must point from the Splitter toward the
next belt segment, and its vertical position must be the attached belt's height.
``BuildTool_Path.DeterminePreviews`` chooses that pose geometrically;
``BuildTool_BlueprintPaste.CreatePrebuilds`` writes the recorded index unchanged;
``PlanetFactory.CreateEntityLogicComponents`` and
``CargoTraffic.ConnectToSplitter`` then install exactly that numbered port.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from flab2bp.dsp import catalog, colliders, planet
from flab2bp.dsp.records import BlueprintBuilding
from flab2bp.dsp.rules import (
    BELT_PORT_DRAW_TO_SLOT,
    BELT_PORT_FEED_FROM_SLOT,
    WORLD_UNITS_PER_LEVEL,
)
from flab2bp.layout.base import AreaFrame, PlacedBuilding

type Direction = Literal["feed", "draw"]
type IssueCode = Literal["model", "slot", "own_slot", "height", "position", "direction", "path"]
type OwnSlotField = Literal["output_from_slot", "input_to_slot"]

_HEIGHT_TOLERANCE = 0.01
_POSITION_TOLERANCE = 0.01
_DOCK_POSITION_TOLERANCE = 0.02
_BEST_DIRECTION_TOLERANCE = 1e-6


@dataclass(frozen=True, slots=True)
class SplitterPortIssue:
    """One unsupported Splitter model or invalid physical-port connection."""

    code: IssueCode
    splitter: int
    belt: int | None
    direction: Direction | None
    recorded_port: int | None
    expected_port: int | None
    model_index: int
    message: str
    own_slot_field: OwnSlotField | None = None
    recorded_own_slot: int | None = None
    expected_own_slot: int | None = None

    def detail(self) -> dict[str, object]:
        detail: dict[str, object] = {
            "code": self.code,
            "splitter": self.splitter,
            "belt": self.belt,
            "direction": self.direction,
            "recorded_port": self.recorded_port,
            "expected_port": self.expected_port,
            "model_index": self.model_index,
        }
        if self.code == "model":
            detail["supported_models"] = tuple(sorted(catalog.SPLITTER_MODEL_INDICES))
        if self.own_slot_field is not None:
            detail.update(
                {
                    "own_slot_field": self.own_slot_field,
                    "recorded_own_slot": self.recorded_own_slot,
                    "expected_own_slot": self.expected_own_slot,
                }
            )
        return detail


@dataclass(frozen=True, slots=True)
class _Node:
    id: int
    item_id: int
    model_index: int
    x: float
    y: float
    z: float
    yaw: float
    area_index: int
    output_obj: int | None
    input_obj: int | None
    output_to_slot: int
    input_from_slot: int
    output_from_slot: int
    input_to_slot: int


type _Attachment = tuple[_Node, Direction, int]


@dataclass(frozen=True, slots=True)
class _NodeIndex:
    by_id: Mapping[int, _Node]
    unique_belt_predecessor: Mapping[int, _Node | None]
    attachments_by_splitter: Mapping[int, tuple[_Attachment, ...]]

    @classmethod
    def build(cls, nodes: tuple[_Node, ...]) -> _NodeIndex:
        by_id: dict[int, _Node] = {}
        unique_belt_predecessor: dict[int, _Node | None] = {}
        attachments: dict[int, list[_Attachment]] = defaultdict(list)
        for node in nodes:
            by_id[node.id] = node
            if not catalog.is_belt(node.item_id):
                continue
            if node.output_obj is not None:
                if node.output_obj in unique_belt_predecessor:
                    unique_belt_predecessor[node.output_obj] = None
                else:
                    unique_belt_predecessor[node.output_obj] = node
                attachments[node.output_obj].append((node, "feed", node.output_to_slot))
            if node.input_obj is not None and node.input_obj != node.output_obj:
                attachments[node.input_obj].append((node, "draw", node.input_from_slot))
        return cls(
            by_id=MappingProxyType(by_id),
            unique_belt_predecessor=MappingProxyType(unique_belt_predecessor),
            attachments_by_splitter=MappingProxyType(
                {splitter: tuple(linked) for splitter, linked in attachments.items()}
            ),
        )


def _raw_placement_nodes(buildings: Sequence[PlacedBuilding]) -> tuple[_Node, ...]:
    return tuple(
        _Node(
            id=index,
            item_id=building.item_id,
            model_index=building.model_index,
            x=float(building.x),
            y=float(building.y),
            z=float(building.z),
            yaw=building.yaw,
            area_index=0,
            output_obj=building.output_obj,
            input_obj=building.input_obj,
            output_to_slot=building.output_to_slot,
            input_from_slot=building.input_from_slot,
            output_from_slot=building.output_from_slot,
            input_to_slot=building.input_to_slot,
        )
        for index, building in enumerate(buildings)
    )


def _blueprint_nodes(buildings: Sequence[BlueprintBuilding]) -> tuple[_Node, ...]:
    return tuple(
        _Node(
            id=building.index,
            item_id=building.item_id,
            model_index=building.model_index,
            x=building.x,
            y=building.y,
            z=building.z,
            yaw=building.yaw,
            area_index=building.area_index,
            output_obj=None if building.output_obj_idx < 0 else building.output_obj_idx,
            input_obj=None if building.input_obj_idx < 0 else building.input_obj_idx,
            output_to_slot=building.output_to_slot,
            input_from_slot=building.input_from_slot,
            output_from_slot=building.output_from_slot,
            input_to_slot=building.input_to_slot,
        )
        for building in buildings
    )


def _rotated_port(pose: catalog.SlotPose, yaw: float) -> tuple[float, float, float]:
    radians = math.radians(yaw)
    cosine = math.cos(radians)
    sine = math.sin(radians)
    return (
        pose.fx * cosine + pose.fy * sine,
        -pose.fx * sine + pose.fy * cosine,
        pose.dz / WORLD_UNITS_PER_LEVEL,
    )


def _rotate_vector(
    rotation: planet.Quat,
    vector: planet.Vec3,
) -> planet.Vec3:
    """Apply one Unity quaternion to a vector."""
    x, y, z, w = rotation
    vx, vy, vz = vector
    tx = 2.0 * (y * vz - z * vy)
    ty = 2.0 * (z * vx - x * vz)
    tz = 2.0 * (x * vy - y * vx)
    return (
        vx + w * tx + (y * tz - z * ty),
        vy + w * ty + (z * tx - x * tz),
        vz + w * tz + (x * ty - y * tx),
    )


def _inverse_projection(
    projection: planet.Projection,
    position: planet.Vec3,
) -> tuple[float, float, float]:
    """Invert ``BlueprintUtils.RefreshBuildPreview`` for one world position."""
    radius = math.sqrt(sum(component * component for component in position))
    direction = tuple(component / radius for component in position)
    latitude = math.asin(max(-1.0, min(1.0, direction[1])))
    longitude = math.atan2(direction[0], -direction[2])
    longitude_offset = longitude / projection.longitude_step
    latitude_offset = latitude / projection.latitude_step - projection.anchor_row
    if projection.rotated:
        x, y = latitude_offset, longitude_offset
    else:
        x, y = longitude_offset, latitude_offset
    z = (radius - projection.radius - 0.2) / WORLD_UNITS_PER_LEVEL
    return x, y, z


def blueprint_port_anchor(
    model_index: int,
    port: int,
    yaw: float,
    *,
    x: float,
    y: float,
    z: float,
    frame: AreaFrame,
) -> tuple[float, float, float]:
    """Return a band-safe blueprint coordinate for one physical Splitter port.

    The game writes a port endpoint by adding ``rotation * portPose`` in WORLD
    space and only then converting that point to blueprint angular offsets.
    Longitude compression means ``portPose / GRID_ARC`` is not that inverse
    outside the equator.  A blueprint may move to every legal anchor in its
    recorded band, so this uses the legal anchor that needs the endpoint
    farthest outward.  At every other anchor the direct link remains well below
    the game's four-world-unit building-link limit and cannot move inward into
    the Splitter collider.
    """
    ports = catalog.port_poses_for_model(model_index)
    if not 0 <= port < len(ports):
        raise ValueError(f"model {model_index} defines {len(ports)} ports, not port {port}")
    band = next(
        (
            candidate
            for candidate in planet.bands(colliders.PLANET_SEGMENT)
            if candidate.area_segments == frame.primary_band
        ),
        None,
    )
    if band is None:
        raise ValueError(f"area frame primary band {frame.primary_band} names no DSP band")
    anchors = band.anchors(frame.height)
    if not anchors:
        raise ValueError(
            f"area frame height {frame.height} fits no anchor in band {frame.primary_band}"
        )

    pose = ports[port]
    radians = math.radians(yaw)
    cosine = math.cos(radians)
    sine = math.sin(radians)
    axis_x = pose.dx * cosine + pose.dy * sine
    axis_y = -pose.dx * sine + pose.dy * cosine
    axis_length = math.hypot(axis_x, axis_y)
    if axis_length <= 1e-12:
        raise ValueError(f"model {model_index} port {port} has no horizontal direction")
    axis_x /= axis_length
    axis_y /= axis_length

    candidates: list[tuple[float, tuple[float, float, float]]] = []
    for anchor_row in anchors:
        projection = planet.Projection(
            band=band,
            anchor_row=anchor_row,
            segment=colliders.PLANET_SEGMENT,
            radius=colliders.PLANET_RADIUS,
        )
        centre, rotation = projection.pose(x, y, z, yaw)
        # SlotPose uses our (x, north, up) axes. Unity's local vector is
        # (x, up, forward).
        offset = _rotate_vector(rotation, (pose.dx, pose.dz, pose.dy))
        world_port = (
            centre[0] + offset[0],
            centre[1] + offset[1],
            centre[2] + offset[2],
        )
        local_port = _inverse_projection(projection, world_port)
        score = (local_port[0] - x) * axis_x + (local_port[1] - y) * axis_y
        candidates.append((score, local_port))
    return max(candidates, key=lambda candidate: candidate[0])[1]


def _outward_neighbour(
    belt: _Node,
    direction: Direction,
    by_id: Mapping[int, _Node],
    unique_belt_predecessor: Mapping[int, _Node | None],
) -> _Node | None:
    if direction == "feed":
        return unique_belt_predecessor.get(belt.id)
    neighbour = by_id.get(belt.output_obj) if belt.output_obj is not None else None
    return neighbour if neighbour is not None and catalog.is_belt(neighbour.item_id) else None


def _outward_from_neighbour(belt: _Node, neighbour: _Node | None) -> tuple[float, float] | None:
    if neighbour is None:
        return None
    dx, dy = neighbour.x - belt.x, neighbour.y - belt.y
    if math.hypot(dx, dy) <= _POSITION_TOLERANCE:
        return None
    return dx, dy


def _outward(
    belt: _Node,
    direction: Direction,
    by_id: Mapping[int, _Node],
    unique_belt_predecessor: Mapping[int, _Node | None],
) -> tuple[float, float] | None:
    return _outward_from_neighbour(
        belt,
        _outward_neighbour(belt, direction, by_id, unique_belt_predecessor),
    )


def _expected_port(
    splitter: _Node,
    belt: _Node,
    outward: tuple[float, float],
    ports: tuple[catalog.SlotPose, ...],
) -> int | None:
    return _expected_path_port(
        splitter_yaw=splitter.yaw,
        splitter_z=splitter.z,
        belt_z=belt.z,
        outward=outward,
        ports=ports,
    )


def _expected_path_port(
    *,
    splitter_yaw: float,
    splitter_z: float,
    belt_z: float,
    outward: tuple[float, float],
    ports: tuple[catalog.SlotPose, ...],
) -> int | None:
    belt_height = belt_z - splitter_z
    horizontal = math.hypot(*outward)
    if horizontal <= _POSITION_TOLERANCE:
        return None
    unit_x, unit_y = outward[0] / horizontal, outward[1] / horizontal
    candidates: list[tuple[int, float]] = []
    for index, pose in enumerate(ports):
        forward_x, forward_y, height = _rotated_port(pose, splitter_yaw)
        if abs(height - belt_height) > _HEIGHT_TOLERANCE:
            continue
        candidates.append((index, forward_x * unit_x + forward_y * unit_y))
    if not candidates:
        return None
    best = max(score for _index, score in candidates)
    winners = [index for index, score in candidates if best - score <= _BEST_DIRECTION_TOLERANCE]
    return winners[0] if len(winners) == 1 else None


def _unsupported_model_issue(splitter: _Node) -> SplitterPortIssue:
    supported = ", ".join(str(model) for model in sorted(catalog.SPLITTER_MODEL_INDICES))
    return SplitterPortIssue(
        code="model",
        splitter=splitter.id,
        belt=None,
        direction=None,
        recorded_port=None,
        expected_port=None,
        model_index=splitter.model_index,
        message=(
            f"splitter {splitter.id} uses model {splitter.model_index}, but item "
            f"{catalog.SPLITTER_ID} supports only models {supported}; a foreign "
            "prefab's port table does not make it a Splitter variant"
        ),
    )


def _issue(
    code: IssueCode,
    splitter: _Node,
    belt: _Node,
    direction: Direction,
    recorded: int,
    expected: int | None,
    reason: str,
) -> SplitterPortIssue:
    relation = "feeds" if direction == "feed" else "draws from"
    return SplitterPortIssue(
        code=code,
        splitter=splitter.id,
        belt=belt.id,
        direction=direction,
        recorded_port=recorded,
        expected_port=expected,
        model_index=splitter.model_index,
        message=(
            f"belt {belt.id} {relation} splitter {splitter.id} through recorded port "
            f"{recorded}{'' if expected is None else f', expected port {expected}'}: {reason}"
        ),
    )


def _own_slot_issue(
    splitter: _Node,
    belt: _Node,
    direction: Direction,
    recorded_port: int,
    expected_port: int | None,
) -> SplitterPortIssue | None:
    if direction == "feed":
        field: OwnSlotField = "output_from_slot"
        recorded_own = belt.output_from_slot
        expected_own = BELT_PORT_FEED_FROM_SLOT
    else:
        field = "input_to_slot"
        recorded_own = belt.input_to_slot
        expected_own = BELT_PORT_DRAW_TO_SLOT
    if recorded_own == expected_own:
        return None
    relation = "feeds" if direction == "feed" else "draws from"
    return SplitterPortIssue(
        code="own_slot",
        splitter=splitter.id,
        belt=belt.id,
        direction=direction,
        recorded_port=recorded_port,
        expected_port=expected_port,
        model_index=splitter.model_index,
        message=(
            f"belt {belt.id} {relation} splitter {splitter.id} with {field} = "
            f"{recorded_own}, expected {expected_own}; both ends are connection-pool "
            "cells and a wrong belt-side slot can evict its onward connection"
        ),
        own_slot_field=field,
        recorded_own_slot=recorded_own,
        expected_own_slot=expected_own,
    )


def _issues(
    nodes: tuple[_Node, ...],
    *,
    frame: AreaFrame | None = None,
) -> tuple[SplitterPortIssue, ...]:
    index = _NodeIndex.build(nodes)
    out: list[SplitterPortIssue] = []
    for splitter in nodes:
        if splitter.item_id != catalog.SPLITTER_ID:
            continue
        if splitter.model_index not in catalog.SPLITTER_MODEL_INDICES:
            out.append(_unsupported_model_issue(splitter))
            continue
        ports = catalog.port_poses_for_model(splitter.model_index)
        for belt, direction, recorded in index.attachments_by_splitter.get(splitter.id, ()):
            neighbour = _outward_neighbour(
                belt, direction, index.by_id, index.unique_belt_predecessor
            )
            # Blueprint local offsets are per area.  Without the Blueprint
            # area's placement transform, coordinates from different areas
            # cannot be subtracted.  The belt-side pool slot is independent
            # of geometry and is still checked across an area boundary.
            same_area = belt.area_index == splitter.area_index and (
                neighbour is None or neighbour.area_index == belt.area_index
            )
            outward = _outward_from_neighbour(belt, neighbour) if same_area else None
            expected = (
                _expected_port(splitter, belt, outward, ports) if outward is not None else None
            )
            own_slot_issue = _own_slot_issue(splitter, belt, direction, recorded, expected)
            if own_slot_issue is not None:
                out.append(own_slot_issue)
            if not same_area:
                continue
            if outward is None:
                out.append(
                    _issue(
                        "path",
                        splitter,
                        belt,
                        direction,
                        recorded,
                        None,
                        "the outward belt segment needed to identify a physical "
                        "port is missing or ambiguous",
                    )
                )
                continue
            if not 0 <= recorded < len(ports):
                out.append(
                    _issue(
                        "slot",
                        splitter,
                        belt,
                        direction,
                        recorded,
                        expected,
                        f"model {splitter.model_index} defines {len(ports)} ports",
                    )
                )
                continue
            if frame is not None:
                anchor = blueprint_port_anchor(
                    splitter.model_index,
                    recorded,
                    splitter.yaw,
                    x=splitter.x,
                    y=splitter.y,
                    z=splitter.z,
                    frame=frame,
                )
                position_error = math.dist((belt.x, belt.y, belt.z), anchor)
                if position_error > _DOCK_POSITION_TOLERANCE:
                    out.append(
                        _issue(
                            "position",
                            splitter,
                            belt,
                            direction,
                            recorded,
                            expected,
                            "the endpoint belt is not anchored at the transformed "
                            f"band-safe port pose (error {position_error:.6g} tiles)",
                        )
                    )
            port_z = _rotated_port(ports[recorded], splitter.yaw)[2]
            if abs(port_z - (belt.z - splitter.z)) > _HEIGHT_TOLERANCE:
                out.append(
                    _issue(
                        "height",
                        splitter,
                        belt,
                        direction,
                        recorded,
                        expected,
                        f"port height {port_z:g} does not match belt height "
                        f"{belt.z - splitter.z:g}",
                    )
                )
            if expected is None or recorded != expected:
                out.append(
                    _issue(
                        "direction",
                        splitter,
                        belt,
                        direction,
                        recorded,
                        expected,
                        "the port forward vector does not face the adjoining belt path",
                    )
                )
    return tuple(out)


@dataclass(frozen=True, slots=True)
class PlacementPortContext:
    """One immutable placement index reused across physical-port queries."""

    _nodes: tuple[_Node, ...]
    _index: _NodeIndex

    def expected_port(
        self,
        belt_index: int,
        splitter_index: int,
        direction: Direction,
    ) -> int | None:
        if not (0 <= belt_index < len(self._nodes) and 0 <= splitter_index < len(self._nodes)):
            return None
        belt = self._nodes[belt_index]
        splitter = self._nodes[splitter_index]
        outward = _outward(
            belt,
            direction,
            self._index.by_id,
            self._index.unique_belt_predecessor,
        )
        if outward is None:
            return None
        if splitter.model_index not in catalog.SPLITTER_MODEL_INDICES:
            return None
        ports = catalog.port_poses_for_model(splitter.model_index)
        return _expected_port(splitter, belt, outward, ports)


def placement_port_context(
    buildings: Sequence[PlacedBuilding],
) -> PlacementPortContext:
    """Build the immutable physical-port index for one placement pass."""
    nodes = _raw_placement_nodes(buildings)
    return PlacementPortContext(nodes, _NodeIndex.build(nodes))


def expected_placement_port(
    buildings: Sequence[PlacedBuilding],
    belt_index: int,
    splitter_index: int,
    direction: Direction,
) -> int | None:
    """Return one physical Splitter port without retaining a placement index."""
    return placement_port_context(buildings).expected_port(belt_index, splitter_index, direction)


def expected_path_port(
    splitter: PlacedBuilding,
    belt: PlacedBuilding,
    outward: PlacedBuilding,
) -> int | None:
    """Return the physical port selected by one co-located belt path.

    ``belt`` is the attachment record on the Splitter's tile and ``outward`` is
    its adjoining path segment.  This is the same game-derived direction and
    height rule as :func:`expected_placement_port`, exposed before the records
    are committed so a router cannot create two links naming one physical port.
    """
    if splitter.model_index not in catalog.SPLITTER_MODEL_INDICES:
        return None
    ports = catalog.port_poses_for_model(splitter.model_index)
    return _expected_path_port(
        splitter_yaw=splitter.yaw,
        splitter_z=float(splitter.z),
        belt_z=float(belt.z),
        outward=(outward.x - belt.x, outward.y - belt.y),
        ports=ports,
    )


def model40_carry_stack_conflicts(
    buildings: Sequence[PlacedBuilding],
) -> tuple[tuple[int, int, int], ...]:
    """Return ``(carry, foreign, splitter)`` conflicts in model 40's carry envelope.

    A belt beside model 40 is normally excused when its run reaches the Splitter
    within three hops.  ``full5`` proves the narrow case that invalidates that
    excusal: a foreign run one level above the elevated carry, sharing the same
    columns inside the Splitter collider.  General adjacent-level belt stacks
    remain legal, as do model 40's own lower and elevated port runs.
    """
    belt_indices = tuple(
        index
        for index, building in enumerate(buildings)
        if catalog.is_belt(building.item_id)
    )
    belt_set = frozenset(belt_indices)
    neighbours: dict[int, set[int]] = defaultdict(set)
    attachments: dict[int, set[int]] = defaultdict(set)
    for belt_index in belt_indices:
        belt = buildings[belt_index]
        output = belt.output_obj
        if output is not None and output in belt_set:
            neighbours[belt_index].add(output)
            neighbours[output].add(belt_index)
        for target in (belt.output_obj, belt.input_obj):
            if (
                target is not None
                and 0 <= target < len(buildings)
                and buildings[target].item_id == catalog.SPLITTER_ID
            ):
                attachments[target].add(belt_index)

    def related_belts(splitter_index: int) -> set[int]:
        related: set[int] = set()
        frontier = attachments.get(splitter_index, set()).copy()
        for _hop in range(3):
            related.update(frontier)
            frontier = {
                neighbour
                for belt_index in frontier
                for neighbour in neighbours.get(belt_index, ())
                if neighbour not in related
            }
        return related

    conflicts: set[tuple[int, int, int]] = set()
    for splitter_index, splitter in enumerate(buildings):
        if splitter.item_id != catalog.SPLITTER_ID or splitter.model_index != 40:
            continue
        placed = colliders.Placed(
            splitter.model_index,
            float(splitter.x),
            float(splitter.y),
            float(splitter.z),
            splitter.yaw,
        )
        boxes = colliders.target_boxes(
            placed,
            *colliders.flat_pose(placed.x, placed.y, placed.z, placed.yaw),
        )
        related = related_belts(splitter_index)
        carry = {
            belt_index
            for belt_index in related
            if abs(float(buildings[belt_index].z - splitter.z) - 1.0)
            <= _HEIGHT_TOLERANCE
            and any(
                colliders.sphere_box_overlap(
                    colliders.belt_probe(
                        float(buildings[belt_index].x),
                        float(buildings[belt_index].y),
                        float(buildings[belt_index].z),
                    ),
                    colliders.BELT_PROBE_RADIUS,
                    box,
                )
                for box in boxes
            )
        }
        for carry_index in carry:
            carry_belt = buildings[carry_index]
            for foreign_index in belt_indices:
                if foreign_index in related:
                    continue
                foreign = buildings[foreign_index]
                if (
                    (foreign.x, foreign.y) == (carry_belt.x, carry_belt.y)
                    and abs(foreign.z - carry_belt.z) == 1
                ):
                    conflicts.add((carry_index, foreign_index, splitter_index))
    return tuple(sorted(conflicts))


def placement_issues(
    buildings: Sequence[PlacedBuilding],
) -> tuple[SplitterPortIssue, ...]:
    """Judge a layout placement before the encoder can ship its connections."""
    return _issues(_raw_placement_nodes(buildings))


def blueprint_issues(
    buildings: Sequence[BlueprintBuilding],
    *,
    frame: AreaFrame | None = None,
) -> tuple[SplitterPortIssue, ...]:
    """Judge decoded connections, with strict current-game anchors when framed.

    DSP 0.8 blueprints used centred Splitter endpoint records and the current
    game retains import compatibility, so unframed historical decoding checks
    connection semantics only.  Fresh emission supplies its area frame and is
    checked against the spherical, band-safe port anchor.
    """
    return _issues(_blueprint_nodes(buildings), frame=frame)
