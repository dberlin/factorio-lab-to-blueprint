"""Observable geometry contracts shared by every layout strategy."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from flab2bp.layout.band_policy import BAND_SELECTIONS, BandPolicy
from flab2bp.layout.base import AreaFrame, Facing, PlacedBuilding, Placement


def test_area_and_bounds_cover_full_footprints() -> None:
    p = Placement(
        buildings=(
            PlacedBuilding(item_id=2302, model_index=62, x=0, y=0, width=3, height=3),
            PlacedBuilding(item_id=2302, model_index=62, x=5, y=2, width=3, height=3),
        )
    )
    assert p.bounds == (0, 0, 7, 4)
    assert p.area == 8 * 5


def test_band_policy_parses_portable_and_every_explicit_selection() -> None:
    expected = (
        "portable",
        "4",
        "8",
        "16",
        "20",
        "32",
        "40",
        "60",
        "80",
        "100",
        "120",
        "160",
        "200",
    )

    assert expected == BAND_SELECTIONS
    assert tuple(BandPolicy.parse(value).selection for value in expected) == expected
    assert BandPolicy.parse("portable").explicit_segments is None
    assert BandPolicy.parse("160").explicit_segments == 160


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
        buildings=(
            PlacedBuilding(item_id=2302, model_index=62, x=0, y=0, width=3, height=3),
        )
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
