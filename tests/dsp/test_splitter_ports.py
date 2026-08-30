"""Game-derived Splitter port direction and height regression tests."""

from __future__ import annotations

import hashlib
from collections import Counter
from fractions import Fraction
from pathlib import Path

from flab2bp.dsp import catalog, codec, splitter_ports
from flab2bp.dsp.envelope import BlueprintFormatError
from flab2bp.dsp.records import BlueprintBuilding
from flab2bp.dsp.rules import WORLD_UNITS_PER_LEVEL
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
    model_index: int, direction: splitter_ports.Direction, port: int
) -> tuple[PlacedBuilding, ...]:
    belt = catalog.building(2002)
    pose = catalog.port_poses_for_model(model_index)[port]
    outward_x, outward_y = round(pose.fx), round(pose.fy)
    height = Fraction(pose.dz / WORLD_UNITS_PER_LEVEL).limit_denominator(10_000)
    splitter = PlacedBuilding(catalog.SPLITTER_ID, model_index, 3, 3)
    attached = PlacedBuilding(2002, belt.model_index, 3, 3, z=height)
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
        ),
        neighbour,
    )


def test_supplied_blueprint_is_rejected_with_all_wrong_ports_named() -> None:
    raw = BROKEN.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == BROKEN_SHA256
    blueprint = codec.decode(raw.decode("utf-8"))

    issues = splitter_ports.blueprint_issues(blueprint.buildings)

    assert Counter(issue.code for issue in issues) == {"direction": 7}
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
        buildings = _observed_placement(model_index, direction, port)
        assert splitter_ports.placement_issues(buildings) == (), (
            model_index,
            direction,
            port,
        )


def test_corrected_construction_path_emits_only_game_valid_splitter_ports() -> None:
    wired = slots.assign_belt_slots(_minimal_broken_shape())
    placement = Placement(
        buildings=wired,
        frame=AreaFrame(8, 4, 4, (4,), False),
    )
    blueprint = codec.placement_to_blueprint(placement, timestamp=0)

    assert splitter_ports.placement_issues(wired) == ()
    assert splitter_ports.blueprint_issues(blueprint.buildings) == ()
    assert wired[1].output_to_slot == 1
    assert [wired[index].input_from_slot for index in (3, 5)] == [3, 2]


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
