"""Observable geometry contracts shared by every layout strategy."""

from __future__ import annotations

from flab2bp.layout.base import Facing, PlacedBuilding, Placement


def test_area_and_bounds_cover_full_footprints() -> None:
    p = Placement(
        buildings=(
            PlacedBuilding(item_id=2302, model_index=62, x=0, y=0, width=3, height=3),
            PlacedBuilding(item_id=2302, model_index=62, x=5, y=2, width=3, height=3),
        )
    )
    assert p.bounds == (0, 0, 7, 4)
    assert p.area == 8 * 5


def test_facing_delta_and_opposite_are_consistent() -> None:
    for f in Facing:
        dx, dy = f.delta
        ox, oy = f.opposite().delta
        assert (dx + ox, dy + oy) == (0, 0)
