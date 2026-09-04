"""Game-derived Splitter port direction and height regression tests."""

from __future__ import annotations

import hashlib
import math
from collections import Counter
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from typing import Literal, cast

import pytest

from flab2bp.dsp import catalog, codec, colliders, planet, splitter_ports
from flab2bp.dsp.envelope import BlueprintFormatError
from flab2bp.dsp.records import BlueprintBuilding
from flab2bp.dsp.rules import BELT_PORT_DRAW_TO_SLOT, WORLD_UNITS_PER_LEVEL
from flab2bp.layout import slots
from flab2bp.layout.base import AreaFrame, PlacedBuilding, Placement

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
BROKEN = FIXTURES / "ours" / "splitter-broken.blueprint.txt"
BROKEN_SHA256 = "e2881b0a9ca28c22c491f1d5cf2b2b20484650e1f55787f33cc3bb9c3e28b797"


def _factory_blueprints() -> list[tuple[str, tuple[BlueprintBuilding, ...]]]:
    out: list[tuple[str, tuple[BlueprintBuilding, ...]]] = []
    for path in sorted(FIXTURES.glob("*.txt")):
        try:
            buildings = codec.decode(path.read_text(encoding="utf-8").strip()).buildings
        except BlueprintFormatError:
            continue
        out.append((path.name, buildings))
    return out


def _minimal_broken_shape() -> tuple[PlacedBuilding, ...]:
    belt = catalog.building(2002)
    splitter = catalog.building(catalog.SPLITTER_ID)
    return (
        PlacedBuilding(2002, belt.model_index, 3, 2, output_obj=1),
        PlacedBuilding(2002, belt.model_index, 2, 2, output_obj=2),
        PlacedBuilding(
            catalog.SPLITTER_ID,
            splitter.model_index,
            2,
            2,
            input_to_slot=14,
            output_from_slot=15,
        ),
        PlacedBuilding(2002, belt.model_index, 2, 2, input_obj=2, output_obj=4),
        PlacedBuilding(2002, belt.model_index, 1, 2),
        PlacedBuilding(2002, belt.model_index, 2, 2, input_obj=2, output_obj=6),
        PlacedBuilding(2002, belt.model_index, 2, 1),
    )


def _observed_placement(
    model_index: int,
    direction: splitter_ports.Direction,
    port: int,
    *,
    yaw: float = 0.0,
) -> tuple[PlacedBuilding, ...]:
    belt = catalog.building(2002)
    pose = catalog.port_poses_for_model(model_index)[port]
    outward_x, outward_y = (round(value) for value in slots.to_world((pose.fx, pose.fy), yaw))
    height = Fraction(pose.dz / WORLD_UNITS_PER_LEVEL).limit_denominator(10_000)
    attached = PlacedBuilding(2002, belt.model_index, 3, 3, z=height)
    splitter = PlacedBuilding(catalog.SPLITTER_ID, model_index, 3, 3, yaw=yaw)
    neighbour = PlacedBuilding(
        2002,
        belt.model_index,
        3 + outward_x,
        3 + outward_y,
        z=height,
    )
    if direction == "feed":
        return (
            PlacedBuilding(
                neighbour.item_id,
                neighbour.model_index,
                neighbour.x,
                neighbour.y,
                z=height,
                output_obj=1,
            ),
            PlacedBuilding(
                attached.item_id,
                attached.model_index,
                attached.x,
                attached.y,
                z=height,
                output_obj=2,
                output_to_slot=port,
            ),
            splitter,
        )
    return (
        splitter,
        PlacedBuilding(
            attached.item_id,
            attached.model_index,
            attached.x,
            attached.y,
            z=height,
            input_obj=0,
            output_obj=2,
            input_from_slot=port,
            input_to_slot=BELT_PORT_DRAW_TO_SLOT,
        ),
        neighbour,
    )


def _validation_complexity_fixture(
    splitter_count: int,
) -> tuple[PlacedBuilding, ...]:
    splitter_model = catalog.building(catalog.SPLITTER_ID).model_index
    belt_model = catalog.building(2002).model_index
    sorter_model = catalog.building(2011).model_index
    assembler_model = catalog.building(2303).model_index
    buildings = [
        PlacedBuilding(catalog.SPLITTER_ID, splitter_model, 0, 0) for _ in range(splitter_count)
    ]
    buildings.extend(
        PlacedBuilding(
            2002,
            belt_model,
            0,
            0,
            output_obj=splitter,
        )
        for splitter in range(splitter_count)
    )
    buildings.extend(PlacedBuilding(2011, sorter_model, 0, 0) for _ in range(splitter_count))
    buildings.extend(PlacedBuilding(2303, assembler_model, 0, 0) for _ in range(splitter_count))
    return tuple(buildings)


def _validation_node(
    node_id: int,
    item_id: int,
    *,
    output_obj: int | None = None,
    input_obj: int | None = None,
) -> splitter_ports._Node:
    return splitter_ports._Node(
        id=node_id,
        item_id=item_id,
        model_index=catalog.building(item_id).model_index,
        x=0.0,
        y=0.0,
        z=0.0,
        yaw=0.0,
        area_index=0,
        output_obj=output_obj,
        input_obj=input_obj,
        output_to_slot=0,
        input_from_slot=0,
        output_from_slot=0,
        input_to_slot=0,
    )


def _many_observed_placements(
    splitter_count: int,
) -> tuple[PlacedBuilding, ...]:
    buildings: list[PlacedBuilding] = []
    for splitter in range(splitter_count):
        offset = len(buildings)
        for building in _observed_placement(38, "feed", splitter % 4):
            buildings.append(
                replace(
                    building,
                    output_obj=(
                        None if building.output_obj is None else building.output_obj + offset
                    ),
                    input_obj=(None if building.input_obj is None else building.input_obj + offset),
                )
            )
    return tuple(buildings)


def test_supplied_blueprint_is_rejected_with_all_wrong_ports_named() -> None:
    raw = BROKEN.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == BROKEN_SHA256
    blueprint = codec.decode(raw.decode("utf-8"))

    issues = splitter_ports.blueprint_issues(blueprint.buildings)

    assert [
        (
            issue.splitter,
            issue.belt,
            issue.code,
            issue.direction,
            issue.recorded_port,
            issue.expected_port,
        )
        for issue in issues
    ] == [
        (1632, 1013, "direction", "feed", 0, 1),
        (1632, 1633, "own_slot", "draw", 1, 3),
        (1632, 1633, "direction", "draw", 1, 3),
        (1632, 1634, "own_slot", "draw", 2, 2),
        (1635, 996, "direction", "feed", 0, 1),
        (1635, 1636, "own_slot", "draw", 1, 3),
        (1635, 1636, "direction", "draw", 1, 3),
        (1635, 1637, "own_slot", "draw", 2, 2),
        (1638, 1338, "direction", "feed", 0, 1),
        (1638, 1639, "own_slot", "draw", 1, 3),
        (1638, 1639, "direction", "draw", 1, 3),
        (1638, 1640, "own_slot", "draw", 2, 0),
        (1638, 1640, "direction", "draw", 2, 0),
    ]
    assert Counter(issue.code for issue in issues) == {
        "direction": 7,
        "own_slot": 6,
    }
    assert {
        issue.belt: (issue.recorded_port, issue.expected_port)
        for issue in issues
        if issue.code == "direction"
    } == {
        1013: (0, 1),
        1633: (1, 3),
        996: (0, 1),
        1636: (1, 3),
        1338: (0, 1),
        1639: (1, 3),
        1640: (2, 0),
    }
    assert {issue.belt for issue in issues if issue.code == "own_slot"} == {
        1633,
        1634,
        1636,
        1637,
        1639,
        1640,
    }


def test_game_blueprint_controls_accept_every_observed_port_and_height_form() -> None:
    forms: set[tuple[int, str, int, int]] = set()
    checked_splitters = 0
    checked_connections = 0
    for name, buildings in _factory_blueprints():
        issues = splitter_ports.blueprint_issues(buildings)
        assert issues == (), (name, issues)
        by_index = {building.index: building for building in buildings}
        for splitter in buildings:
            if splitter.item_id != catalog.SPLITTER_ID:
                continue
            checked_splitters += 1
            for belt in buildings:
                if belt.output_obj_idx == splitter.index:
                    forms.add(
                        (
                            splitter.model_index,
                            "feed",
                            belt.output_to_slot,
                            round(belt.z - splitter.z),
                        )
                    )
                    checked_connections += 1
                if belt.input_obj_idx == splitter.index:
                    forms.add(
                        (
                            splitter.model_index,
                            "draw",
                            belt.input_from_slot,
                            round(belt.z - splitter.z),
                        )
                    )
                    checked_connections += 1
            assert splitter.index in by_index

    assert checked_splitters == 25
    assert checked_connections == 72
    assert forms == {
        (38, "draw", 1, 0),
        (38, "draw", 2, 0),
        (38, "draw", 3, 0),
        (38, "feed", 0, 0),
        (38, "feed", 1, 0),
        (38, "feed", 3, 0),
        (39, "draw", 0, 0),
        (39, "draw", 1, 1),
        (39, "feed", 0, 0),
        (39, "feed", 2, 0),
        (39, "feed", 3, 1),
    }


def test_every_observed_game_port_form_is_accepted_as_a_layout_control() -> None:
    observed = {
        (38, "draw", 1),
        (38, "draw", 2),
        (38, "draw", 3),
        (38, "feed", 0),
        (38, "feed", 1),
        (38, "feed", 3),
        (39, "draw", 0),
        (39, "draw", 1),
        (39, "feed", 0),
        (39, "feed", 2),
        (39, "feed", 3),
    }
    for model_index, direction, port in observed:
        buildings = _observed_placement(
            model_index,
            cast(Literal["feed", "draw"], direction),
            port,
        )
        assert splitter_ports.placement_issues(buildings) == (), (
            model_index,
            direction,
            port,
        )


def test_assignment_selects_each_port_at_exact_model_yaw_and_height() -> None:
    for model_index in (38, 39, 40):
        for yaw in (0.0, 90.0, 180.0, 270.0):
            for direction in ("feed", "draw"):
                for port in range(4):
                    buildings = list(_observed_placement(model_index, direction, port, yaw=yaw))
                    if direction == "feed":
                        buildings[1] = replace(buildings[1], output_to_slot=0)
                    else:
                        buildings[1] = replace(buildings[1], input_from_slot=0)

                    wired = slots.assign_belt_slots(buildings)

                    actual = (
                        wired[1].output_to_slot if direction == "feed" else wired[1].input_from_slot
                    )
                    assert actual == port, (model_index, yaw, direction, port)
                    assert splitter_ports.placement_issues(wired) == ()


def test_reusable_context_matches_public_convenience_query() -> None:
    buildings = _observed_placement(39, "feed", 3)
    context = splitter_ports.placement_port_context(buildings)

    assert context.expected_port(1, 2, "feed") == 3
    assert splitter_ports.expected_placement_port(buildings, 1, 2, "feed") == 3
    assert context.expected_port(-1, 2, "feed") is None
    assert splitter_ports.expected_placement_port(buildings, -1, 2, "feed") is None


def test_slot_assignment_builds_one_context_for_all_splitter_links(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_raw_placement_nodes = splitter_ports._raw_placement_nodes
    context_builds = 0

    def counted_raw_placement_nodes(
        buildings: tuple[PlacedBuilding, ...],
    ) -> tuple[splitter_ports._Node, ...]:
        nonlocal context_builds
        context_builds += 1
        return real_raw_placement_nodes(buildings)

    monkeypatch.setattr(splitter_ports, "_raw_placement_nodes", counted_raw_placement_nodes)
    buildings = _many_observed_placements(12)

    wired = slots.assign_belt_slots(buildings)

    assert [wired[group * 3 + 1].output_to_slot for group in range(12)] == [
        group % 4 for group in range(12)
    ]
    assert context_builds == 1


def test_validation_examines_each_building_once_when_splitter_count_grows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_is_belt = catalog.is_belt
    examinations = 0

    def counted_is_belt(item_id: int) -> bool:
        nonlocal examinations
        examinations += 1
        return real_is_belt(item_id)

    monkeypatch.setattr(catalog, "is_belt", counted_is_belt)
    measured: list[tuple[int, int]] = []
    for splitter_count in (4, 8, 16):
        buildings = _validation_complexity_fixture(splitter_count)
        issues = splitter_ports.placement_issues(buildings)
        measured.append((len(buildings), examinations))
        examinations = 0

        assert len(issues) == splitter_count
        assert all(issue.code == "path" for issue in issues)

    assert measured == [(16, 16), (32, 32), (64, 64)]


def test_duplicate_splitters_use_bounded_predecessor_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    splitter_count = 8
    predecessor_count = 8
    nodes = (
        *(_validation_node(7, catalog.SPLITTER_ID) for _ in range(splitter_count)),
        _validation_node(100, 2002, output_obj=7),
        *(
            _validation_node(200 + index, 2002, output_obj=100)
            for index in range(predecessor_count)
        ),
        _validation_node(300, 2011, output_obj=7),
        _validation_node(301, 2303, input_obj=7),
    )
    real_is_belt = catalog.is_belt
    examinations = 0

    def counted_is_belt(item_id: int) -> bool:
        nonlocal examinations
        examinations += 1
        return real_is_belt(item_id)

    monkeypatch.setattr(catalog, "is_belt", counted_is_belt)

    issues = splitter_ports._issues(nodes)

    assert [(issue.splitter, issue.belt, issue.code) for issue in issues] == [
        (7, 100, "path")
    ] * splitter_count
    assert examinations == len(nodes)


def test_indexed_attachment_lookup_preserves_order_and_ignores_non_belts() -> None:
    splitter_model = catalog.building(catalog.SPLITTER_ID).model_index
    belt_model = catalog.building(2002).model_index
    sorter_model = catalog.building(2011).model_index
    assembler_model = catalog.building(2303).model_index
    buildings = (
        PlacedBuilding(catalog.SPLITTER_ID, splitter_model, 0, 0),
        PlacedBuilding(2303, assembler_model, 0, 0, output_obj=0),
        PlacedBuilding(2011, sorter_model, 0, 0, output_obj=0),
        PlacedBuilding(2002, belt_model, 0, 0, output_obj=0),
        PlacedBuilding(catalog.SPLITTER_ID, splitter_model, 0, 0),
        PlacedBuilding(
            2002,
            belt_model,
            0,
            0,
            z=Fraction(1),
            input_obj=4,
            output_obj=6,
            input_from_slot=99,
        ),
        PlacedBuilding(2002, belt_model, 0, 1, z=Fraction(1)),
        PlacedBuilding(2303, assembler_model, 0, 0, input_obj=4),
    )

    issues = splitter_ports.placement_issues(buildings)

    assert [
        (
            issue.splitter,
            issue.belt,
            issue.code,
            issue.direction,
            issue.recorded_port,
            issue.expected_port,
        )
        for issue in issues
    ] == [
        (0, 3, "path", "feed", 0, None),
        (4, 5, "own_slot", "draw", 99, None),
        (4, 5, "slot", "draw", 99, None),
    ]


def test_corrected_construction_path_emits_only_game_valid_splitter_ports() -> None:
    wired = slots.assign_belt_slots(_minimal_broken_shape())
    frame = AreaFrame(56, 42, 160, (160,), False)
    placement = Placement(
        buildings=wired,
        frame=frame,
    )
    blueprint = codec.placement_to_blueprint(placement, timestamp=0)
    splitter = blueprint.buildings[2]

    assert splitter_ports.placement_issues(wired) == ()
    assert splitter_ports.blueprint_issues(blueprint.buildings, frame=frame) == ()
    assert (splitter.output_to_slot, splitter.input_from_slot) == (14, 15)
    assert wired[1].output_to_slot == 1
    assert [wired[index].input_from_slot for index in (3, 5)] == [3, 2]
    assert [wired[index].input_to_slot for index in (3, 5)] == [1, 1]
    assert {
        (building.output_from_slot, building.input_to_slot)
        for building in blueprint.buildings
        if catalog.is_belt(building.item_id)
    } == {(0, 1)}
    assert [(wired[index].input_obj, wired[index].output_obj) for index in (3, 5)] == [
        (2, 4),
        (2, 6),
    ]

    attached = (
        (1, wired[1].output_to_slot),
        (3, wired[3].input_from_slot),
        (5, wired[5].input_from_slot),
    )
    for belt_index, port in attached:
        belt = blueprint.buildings[belt_index]
        anchor = splitter_ports.blueprint_port_anchor(
            splitter.model_index,
            port,
            splitter.yaw,
            x=splitter.x,
            y=splitter.y,
            z=splitter.z,
            frame=frame,
        )
        assert (belt.x, belt.y, belt.z) == pytest.approx(anchor)
        assert belt.z > splitter.z
        physical_port = catalog.port_poses_for_model(splitter.model_index)[port]
        port_distance = math.sqrt(physical_port.dx**2 + physical_port.dy**2 + physical_port.dz**2)
        band = next(
            candidate
            for candidate in planet.bands()
            if candidate.area_segments == frame.primary_band
        )
        for anchor_row in band.anchors(frame.height):
            projection = planet.Projection(band, anchor_row, 200, 200.0)
            emitted_distance = math.dist(
                projection.position(splitter.x, splitter.y, splitter.z),
                projection.position(belt.x, belt.y, belt.z),
            )
            assert emitted_distance + 1e-9 >= port_distance

    # Port 1 lies on the longitude-compressed axis in this orientation.  The
    # flat-grid conversion places it inside the real port at a poleward legal
    # anchor; the spherical envelope must therefore sit farther out.
    assert (
        math.dist(
            (blueprint.buildings[1].x, blueprint.buildings[1].y),
            (splitter.x, splitter.y),
        )
        > 0.25 / colliders.GRID_ARC
    )

    centred_belt = replace(
        blueprint.buildings[1],
        x=splitter.x,
        y=splitter.y,
        z=splitter.z,
    )
    centred = blueprint.buildings[:1] + (centred_belt,) + blueprint.buildings[2:]
    position_issues = [
        issue
        for issue in splitter_ports.blueprint_issues(centred, frame=frame)
        if issue.code == "position"
    ]
    assert [(issue.splitter, issue.belt) for issue in position_issues] == [(2, 1)]


def test_foreign_four_port_model_is_not_a_supported_splitter_variant() -> None:
    buildings = _observed_placement(121, "feed", 0)
    assert len(catalog.port_poses_for_model(121)) == 4

    issues = splitter_ports.placement_issues(buildings)

    assert len(issues) == 1
    assert issues[0].code == "model"
    assert issues[0].detail()["model_index"] == 121
    assert issues[0].detail()["supported_models"] == (38, 39, 40)


def test_splitter_model_variants_expose_their_actual_port_heights() -> None:
    assert [pose.dz for pose in catalog.port_poses_for_model(38)] == [0.0] * 4
    assert [
        round(Fraction(pose.dz).limit_denominator(10_000) / Fraction(4, 3))
        for pose in catalog.port_poses_for_model(39)
    ] == [0, 1, 0, 1]
    assert [
        round(Fraction(pose.dz).limit_denominator(10_000) / Fraction(4, 3))
        for pose in catalog.port_poses_for_model(40)
    ] == [1, 0, 1, 0]
