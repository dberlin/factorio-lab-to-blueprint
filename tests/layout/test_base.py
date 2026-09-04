"""Observable geometry contracts shared by every layout strategy."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from flab2bp.layout.band_policy import BAND_SELECTIONS, BandPolicy
from flab2bp.layout.base import AreaFrame, Facing, NoValidLayout, PlacedBuilding, Placement


def test_area_and_bounds_cover_full_footprints() -> None:
    p = Placement(
        buildings=(
            PlacedBuilding(item_id=2302, model_index=62, x=0, y=0, width=3, height=3),
            PlacedBuilding(item_id=2302, model_index=62, x=5, y=2, width=3, height=3),
        )
    )
    assert p.bounds == (0, 0, 7, 4)
    assert p.area == 8 * 5


def test_band_policy_parses_the_exact_authoritative_dimensions_in_order() -> None:
    expected = (
        "portable",
        "5x20",
        "5x40",
        "5x80",
        "5x100",
        "10x160",
        "10x200",
        "15x300",
        "15x400",
        "25x500",
        "25x600",
        "50x800",
        "160x1000",
    )

    assert expected == BAND_SELECTIONS
    assert tuple(BandPolicy.parse(value).selection for value in expected) == expected
    assert BandPolicy.parse("portable").explicit_segments is None
    assert BandPolicy.parse("50x800").explicit_segments == 160
    assert BandPolicy.parse("160x1000").explicit_segments == 200


def test_band_policy_keeps_meaningful_area_segment_requests_compatible() -> None:
    assert BandPolicy.parse("4").selection == "5x20"
    assert BandPolicy.parse("160").selection == "50x800"
    assert BandPolicy.parse("200").selection == "160x1000"


def test_band_policy_rejects_unknown_latitude_band() -> None:
    with pytest.raises(ValueError, match="latitude band"):
        BandPolicy.parse("240")


@pytest.mark.parametrize(("width", "height"), ((0, 7), (12, 0), (-1, 7), (12, -1)))
def test_area_frame_requires_positive_dimensions(width: int, height: int) -> None:
    with pytest.raises(ValueError, match="positive"):
        AreaFrame(width, height, 40, (40,), False)


def test_area_frame_requires_at_least_one_certified_band() -> None:
    with pytest.raises(ValueError, match="certified band"):
        AreaFrame(12, 7, 40, (), False)


def test_area_frame_requires_primary_band_first() -> None:
    with pytest.raises(ValueError, match="primary band"):
        AreaFrame(12, 7, 40, (60, 80), False)


def test_finalized_placement_area_comes_from_immutable_frame() -> None:
    placement = Placement(
        buildings=(PlacedBuilding(item_id=2302, model_index=62, x=0, y=0, width=3, height=3),)
    )
    frame = AreaFrame(12, 7, 40, (40, 60, 80), False)

    finalized = replace(placement, frame=frame)

    assert finalized.area == 84
    with pytest.raises(FrozenInstanceError):
        frame.width = 13  # type: ignore[misc]


def test_facing_delta_and_opposite_are_consistent() -> None:
    for f in Facing:
        dx, dy = f.delta
        ox, oy = f.opposite().delta
        assert (dx + ox, dy + oy) == (0, 0)


def test_no_valid_layout_carries_optional_solver_stats() -> None:
    """A REFUSED row with no stats is a refusal nobody can attribute.

    R3 §5.3 measured it: every `alns_*` stat is written in
    `_with_observational_stats`, which only runs on a SUCCESSFUL placement, so a
    refused cell reported nothing about the search that refused it.
    """
    bare = NoValidLayout("nothing wired", spec_label="x", budget_s=30.0)
    carried = NoValidLayout(
        "nothing wired",
        spec_label="x",
        budget_s=30.0,
        stats={"stages": 11.0, "alns_operators": "destroy:failed-endpoints:9"},
    )

    assert bare.stats == {}
    assert carried.stats["stages"] == 11.0
    assert carried.stats["alns_operators"] == "destroy:failed-endpoints:9"
