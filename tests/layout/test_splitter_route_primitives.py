"""Physical single-stream Splitter alternatives, including supported height changes."""

from __future__ import annotations

from dataclasses import replace
from fractions import Fraction

import pytest

from flab2bp.dsp import catalog, splitter_ports
from flab2bp.dsp.rules import BELT_PORT_DRAW_TO_SLOT
from flab2bp.layout import junction
from flab2bp.layout.base import PlacedBuilding

_RULES = catalog.BeltAltitudeRules(Fraction(9), False, 4, 3, True)


def _candidates(
    level: int = 0, *, yaw: float = 0.0, rules: catalog.BeltAltitudeRules = _RULES
) -> tuple[junction.SplitterRouteCandidate, ...]:
    return junction.splitter_route_candidates(
        4, 5, level, yaw=yaw, altitude_rules=rules, carries_item="iron-ore"
    )


def test_parallel_height_model_uses_north_upper_port_not_east() -> None:
    candidate = next(
        candidate
        for candidate in _candidates()
        if candidate.stack_members[-1].model_index == 39
        and candidate.entry.slot == 0
        and candidate.exit.slot == 1
    )

    assert candidate.entry.dock == (4, 6, 0)
    assert candidate.exit.dock == (4, 6, 1)
    assert candidate.entry.physical_pose.dy == 0.25
    assert candidate.exit.physical_pose.dy == 0.25
    assert candidate.exit.physical_pose.dz == pytest.approx(1.3333)
    assert candidate.exit.physical_pose.fx == 0.0
    assert candidate.exit.physical_pose.fy == 1.0


def test_rotated_cross_height_model_uses_exact_ports() -> None:
    candidate = next(
        candidate
        for candidate in _candidates(1, yaw=90.0)
        if candidate.stack_members[-1].model_index == 40
        and candidate.entry.slot == 0
        and candidate.exit.slot == 1
    )

    assert candidate.entry.dock == (5, 5, 1)
    assert candidate.exit.dock == (4, 4, 0)
    assert candidate.entry.physical_pose.dx == 0.25
    assert candidate.entry.physical_pose.dy == 0.0
    assert candidate.exit.physical_pose.dx == 0.0
    assert candidate.exit.physical_pose.dy == -0.25


def test_height_and_stack_unlocks_are_independent_of_vertical_belt_unlock() -> None:
    low_ceiling = replace(_RULES, max_z=Fraction(3, 4))
    ground_only = _candidates(rules=low_ceiling)
    assert {candidate.stack_members[-1].model_index for candidate in ground_only} == {38, 39, 40}
    assert all(candidate.entry.dock[2] == candidate.exit.dock[2] == 0 for candidate in ground_only)
    assert _candidates(1, rules=low_ceiling) == ()

    one_member = replace(_RULES, storage_level=1)
    assert any(
        candidate.entry.dock[2] != candidate.exit.dock[2]
        for candidate in _candidates(1, rules=one_member)
    )
    assert _candidates(2, rules=one_member) == ()
    assert _candidates(0, rules=replace(_RULES, storage_level=0)) == ()


def test_support_chain_is_exact_and_does_not_transfer_cargo_between_members() -> None:
    candidate = junction.splitter_route_candidates(
        4, 5, 5, yaw=0.0, altitude_rules=_RULES, carries_item="iron-ore", first_index=7
    )[0]

    assert [
        (member.z, member.input_obj, member.carries_item) for member in candidate.stack_members
    ] == [
        (Fraction(0), None, None),
        (Fraction(2), 7, None),
        (Fraction(4), 8, "iron-ore"),
    ]
    assert candidate.entry.dock[2] in (4, 5)
    assert candidate.exit.dock[2] in (4, 5)
    assert (4, 5, 0) in candidate.foreign_keepout
    assert (4, 5, 2) in candidate.foreign_keepout
    assert (4, 5, 4) in candidate.foreign_keepout
    assert _candidates(8) == ()


@pytest.mark.parametrize("yaw", [0.0, 90.0, 180.0, 270.0])
@pytest.mark.parametrize("level", [0, 3])
def test_every_candidate_emits_two_distinct_valid_physical_attachments(
    yaw: float, level: int
) -> None:
    belt_model = catalog.building(2002).model_index
    candidates = _candidates(level, yaw=yaw)
    expected_models = {38, 39, 40} if level == 0 else {39, 40}
    assert {candidate.stack_members[-1].model_index for candidate in candidates} == expected_models
    for candidate in candidates:
        top_index = len(candidate.stack_members) - 1
        before_index = len(candidate.stack_members)
        input_index = before_index + 1
        after_index = before_index + 3
        entry_x, entry_y, entry_z = candidate.entry.dock
        exit_x, exit_y, exit_z = candidate.exit.dock
        buildings = (
            *candidate.stack_members,
            PlacedBuilding(
                2002, belt_model, entry_x, entry_y, Fraction(entry_z), output_obj=input_index
            ),
            PlacedBuilding(
                2002,
                belt_model,
                4,
                5,
                Fraction(entry_z),
                output_obj=top_index,
                output_to_slot=candidate.entry.slot,
                carries_item="iron-ore",
            ),
            PlacedBuilding(
                2002,
                belt_model,
                4,
                5,
                Fraction(exit_z),
                input_obj=top_index,
                input_from_slot=candidate.exit.slot,
                input_to_slot=BELT_PORT_DRAW_TO_SLOT,
                output_obj=after_index,
                carries_item="iron-ore",
            ),
            PlacedBuilding(2002, belt_model, exit_x, exit_y, Fraction(exit_z)),
        )

        assert candidate.entry.slot != candidate.exit.slot
        assert splitter_ports.placement_issues(buildings) == ()


@pytest.mark.parametrize("level,yaw", [(-1, 0.0), (0, 45.0)])
def test_nonphysical_anchor_or_orientation_is_rejected(level: int, yaw: float) -> None:
    with pytest.raises(ValueError):
        _candidates(level, yaw=yaw)
