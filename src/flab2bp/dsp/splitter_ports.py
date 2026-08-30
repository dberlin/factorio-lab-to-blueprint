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
from collections.abc import Sequence
from dataclasses import dataclass
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
type IssueCode = Literal["slot", "own_slot", "height", "direction", "path"]
type OwnSlotField = Literal["output_from_slot", "input_to_slot"]

_HEIGHT_TOLERANCE = 0.01
_POSITION_TOLERANCE = 0.01
_BEST_DIRECTION_TOLERANCE = 1e-6


@dataclass(frozen=True, slots=True)
class SplitterPortIssue:
    """One connection the game would install on the wrong physical port."""

    code: IssueCode
    splitter: int
    belt: int
    direction: Direction
    recorded_port: int
    expected_port: int | None
    message: str
    own_slot_field: OwnSlotField | None = None
    recorded_own_slot: int | None = None
    expected_own_slot: int | None = None

    def detail(self) -> dict[str, int | str | None]:
        detail: dict[str, int | str | None] = {
            "code": self.code,
            "splitter": self.splitter,
            "belt": self.belt,
            "direction": self.direction,
            "recorded_port": self.recorded_port,
            "expected_port": self.expected_port,
        }
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
    by_id: dict[int, _Node],
    predecessors: dict[int, list[_Node]],
) -> _Node | None:
    if direction == "draw":
        neighbour = by_id.get(belt.output_obj) if belt.output_obj is not None else None
        candidates = (
            [neighbour]
            if neighbour is not None and catalog.is_belt(neighbour.item_id)
            else []
        )
    else:
        candidates = [
            candidate
            for candidate in predecessors.get(belt.id, ())
            if catalog.is_belt(candidate.item_id)
        ]
    return candidates[0] if len(candidates) == 1 else None


def _outward(
    belt: _Node,
    direction: Direction,
    by_id: dict[int, _Node],
    predecessors: dict[int, list[_Node]],
) -> tuple[float, float] | None:
    neighbour = _outward_neighbour(belt, direction, by_id, predecessors)
    if neighbour is None:
        return None
    dx, dy = neighbour.x - belt.x, neighbour.y - belt.y
    if math.hypot(dx, dy) <= _POSITION_TOLERANCE:
        return None
    return dx, dy


def _expected_port(
    splitter: _Node,
    belt: _Node,
    outward: tuple[float, float],
    ports: tuple[catalog.SlotPose, ...],
) -> int | None:
    belt_height = belt.z - splitter.z
    horizontal = math.hypot(*outward)
    unit_x, unit_y = outward[0] / horizontal, outward[1] / horizontal
    candidates: list[tuple[int, float]] = []
    for index, pose in enumerate(ports):
        forward_x, forward_y, height = _rotated_port(pose, splitter.yaw)
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
    by_id = {node.id: node for node in nodes}
    predecessors: dict[int, list[_Node]] = defaultdict(list)
    for node in nodes:
        if node.output_obj is not None:
            predecessors[node.output_obj].append(node)

    out: list[SplitterPortIssue] = []
    for splitter in nodes:
        if splitter.item_id != catalog.SPLITTER_ID:
            continue
        try:
            ports = catalog.port_poses_for_model(splitter.model_index)
        except KeyError:
            ports = ()
        for belt in nodes:
            if not catalog.is_belt(belt.item_id):
                continue
            if belt.output_obj == splitter.id:
                attachments: tuple[tuple[Direction, int], ...] = (
                    ("feed", belt.output_to_slot),
                )
            elif belt.input_obj == splitter.id:
                attachments = (("draw", belt.input_from_slot),)
            else:
                continue
            for direction, recorded in attachments:
                neighbour = _outward_neighbour(
                    belt, direction, by_id, predecessors
                )
                # Blueprint local offsets are per area.  Without the Blueprint
                # area's placement transform, coordinates from different areas
                # cannot be subtracted.  The belt-side pool slot is independent
                # of geometry and is still checked across an area boundary.
                same_area = belt.area_index == splitter.area_index and (
                    neighbour is None or neighbour.area_index == belt.area_index
                )
                outward = (
                    _outward(belt, direction, by_id, predecessors)
                    if same_area
                    else None
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


def expected_placement_port(
    buildings: Sequence[PlacedBuilding],
    belt_index: int,
    splitter_index: int,
    direction: Direction,
) -> int | None:
    """Return the one physical Splitter port selected by a belt path."""
    nodes = _raw_placement_nodes(buildings)
    if not (
        0 <= belt_index < len(nodes)
        and 0 <= splitter_index < len(nodes)
    ):
        return None
    belt = nodes[belt_index]
    splitter = nodes[splitter_index]
    predecessors: dict[int, list[_Node]] = defaultdict(list)
    for node in nodes:
        if node.output_obj is not None:
            predecessors[node.output_obj].append(node)
    outward = _outward(
        belt,
        direction,
        {node.id: node for node in nodes},
        predecessors,
    )
    if outward is None:
        return None
    try:
        ports = catalog.port_poses_for_model(splitter.model_index)
    except KeyError:
        return None
    return _expected_port(splitter, belt, outward, ports)


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
