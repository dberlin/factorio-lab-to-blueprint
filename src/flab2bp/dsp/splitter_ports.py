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

from flab2bp.dsp import catalog
from flab2bp.dsp.records import BlueprintBuilding
from flab2bp.dsp.rules import (
    BELT_PORT_DRAW_TO_SLOT,
    BELT_PORT_FEED_FROM_SLOT,
    WORLD_UNITS_PER_LEVEL,
)
from flab2bp.layout.base import PlacedBuilding

type Direction = Literal["feed", "draw"]
type IssueCode = Literal["model", "slot", "own_slot", "height", "direction", "path"]
type OwnSlotField = Literal["output_from_slot", "input_to_slot"]

_HEIGHT_TOLERANCE = 0.01
_POSITION_TOLERANCE = 0.01
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
            detail["supported_models"] = tuple(
                sorted(catalog.SPLITTER_MODEL_INDICES)
            )
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
                attachments[node.output_obj].append(
                    (node, "feed", node.output_to_slot)
                )
            if node.input_obj is not None and node.input_obj != node.output_obj:
                attachments[node.input_obj].append(
                    (node, "draw", node.input_from_slot)
                )
        return cls(
            by_id=MappingProxyType(by_id),
            unique_belt_predecessor=MappingProxyType(unique_belt_predecessor),
            attachments_by_splitter=MappingProxyType(
                {
                    splitter: tuple(linked)
                    for splitter, linked in attachments.items()
                }
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


def _rotated_port(
    pose: catalog.SlotPose, yaw: float
) -> tuple[float, float, float]:
    radians = math.radians(yaw)
    cosine = math.cos(radians)
    sine = math.sin(radians)
    return (
        pose.fx * cosine + pose.fy * sine,
        -pose.fx * sine + pose.fy * cosine,
        pose.dz / WORLD_UNITS_PER_LEVEL,
    )




def _outward_neighbour(
    belt: _Node,
    direction: Direction,
    by_id: Mapping[int, _Node],
    unique_belt_predecessor: Mapping[int, _Node | None],
) -> _Node | None:
    if direction == "feed":
        return unique_belt_predecessor.get(belt.id)
    neighbour = by_id.get(belt.output_obj) if belt.output_obj is not None else None
    return (
        neighbour
        if neighbour is not None and catalog.is_belt(neighbour.item_id)
        else None
    )


def _outward_from_neighbour(
    belt: _Node, neighbour: _Node | None
) -> tuple[float, float] | None:
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
        _outward_neighbour(
            belt, direction, by_id, unique_belt_predecessor
        ),
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
    winners = [
        index
        for index, score in candidates
        if best - score <= _BEST_DIRECTION_TOLERANCE
    ]
    return winners[0] if len(winners) == 1 else None


def _unsupported_model_issue(splitter: _Node) -> SplitterPortIssue:
    supported = ", ".join(
        str(model) for model in sorted(catalog.SPLITTER_MODEL_INDICES)
    )
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


def _issues(nodes: tuple[_Node, ...]) -> tuple[SplitterPortIssue, ...]:
    index = _NodeIndex.build(nodes)
    out: list[SplitterPortIssue] = []
    for splitter in nodes:
        if splitter.item_id != catalog.SPLITTER_ID:
            continue
        if splitter.model_index not in catalog.SPLITTER_MODEL_INDICES:
            out.append(_unsupported_model_issue(splitter))
            continue
        ports = catalog.port_poses_for_model(splitter.model_index)
        for belt, direction, recorded in index.attachments_by_splitter.get(
            splitter.id, ()
        ):
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
            outward = (
                _outward_from_neighbour(belt, neighbour) if same_area else None
            )
            expected = (
                _expected_port(splitter, belt, outward, ports)
                if outward is not None
                else None
            )
            own_slot_issue = _own_slot_issue(
                splitter, belt, direction, recorded, expected
            )
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
                        "the port forward vector does not face the adjoining "
                        "belt path",
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
        if not (
            0 <= belt_index < len(self._nodes)
            and 0 <= splitter_index < len(self._nodes)
        ):
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
    return placement_port_context(buildings).expected_port(
        belt_index, splitter_index, direction
    )


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


def placement_issues(
    buildings: Sequence[PlacedBuilding],
) -> tuple[SplitterPortIssue, ...]:
    """Judge a layout placement before the encoder can ship its connections."""
    return _issues(_raw_placement_nodes(buildings))


def blueprint_issues(
    buildings: Sequence[BlueprintBuilding],
) -> tuple[SplitterPortIssue, ...]:
    """Judge the exact connection fields decoded from a blueprint artifact."""
    return _issues(_blueprint_nodes(buildings))
