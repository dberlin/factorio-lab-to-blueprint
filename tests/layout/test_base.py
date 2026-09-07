"""Observable geometry contracts shared by every layout strategy."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from flab2bp.layout.band_policy import BAND_SELECTIONS, BandPolicy
from flab2bp.layout.base import AreaFrame, Facing, NoValidLayout, PlacedBuilding, Placement

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


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


def test_bounds_is_memoised_and_matches_the_scan(monkeypatch: pytest.MonkeyPatch) -> None:
    from flab2bp.layout import buildings as buildings_module

    records = tuple(
        PlacedBuilding(item_id=2303, model_index=0, x=i * 4, y=i, width=3, height=3)
        for i in range(20)
    )
    placement = Placement(buildings=records)
    xs = [b.x for b in records] + [b.x + b.width - 1 for b in records]
    ys = [b.y for b in records] + [b.y + b.height - 1 for b in records]
    expected = (min(xs), min(ys), max(xs), max(ys))
    assert placement.bounds == expected

    # Prove the SECOND call answers from the memo rather than recomputing: once
    # the memo is warm, swap in a `bounds_of` that would fail the test if it
    # were ever called again.
    def _must_not_be_called(_records: object) -> tuple[int, int, int, int]:
        raise AssertionError("bounds_of was called again -- the memo did not hold")

    monkeypatch.setattr(buildings_module, "bounds_of", _must_not_be_called)
    assert placement.bounds == expected
    # Answering `bounds` must not build the full nine-bucket index either --
    # that would cost more than the scan it replaced on a candidate asked once
    # and discarded (see `Placement.bounds`'s docstring).
    assert placement.buildings_index is None


def test_bounds_does_not_build_the_full_buildings_index() -> None:
    """Pins the fast path: `bounds` must answer without ever touching
    `buildings_index` -- building the full nine-bucket index (`by_tile`'s
    O(N * width * height) loop included) just to answer a four-number question
    would cost more than the scan it replaced, on exactly the rejected-search-
    candidate path this task was meant to speed up.
    """
    records = tuple(
        PlacedBuilding(item_id=2303, model_index=0, x=i * 4, y=i, width=3, height=3)
        for i in range(5)
    )
    placement = Placement(buildings=records)
    assert placement.buildings_index is None
    _ = placement.bounds
    assert placement.buildings_index is None
    _ = placement.bounds  # second call too
    assert placement.buildings_index is None


def test_replace_does_not_carry_a_stale_index() -> None:
    from dataclasses import replace as dc_replace

    from flab2bp.layout.buildings import Buildings

    first = Placement(buildings=(PlacedBuilding(item_id=2303, model_index=0, x=0, y=0),))
    assert first.bounds == (0, 0, 0, 0)
    first_index = Buildings.of(first)  # force-build the full index too

    second = dc_replace(
        first,
        buildings=(PlacedBuilding(item_id=2303, model_index=0, x=10, y=10),),
    )
    # Nothing has asked `second` anything yet: both memos MUST be unpopulated,
    # not merely "consistent-looking" -- a future regression that eagerly
    # populated either one right after `replace()` has to fail this, not pass
    # it by accident (the same vacuous-assertion class that already bit this
    # branch once, in Task 2's staleness check comparing `()` to `()`).
    assert second.buildings_index is None
    assert second._bounds_cache is None

    assert second.bounds == (10, 10, 10, 10)
    second_index = Buildings.of(second)
    assert second_index is not first_index
    assert len(second_index) == 1


def test_empty_placement_bounds_is_the_origin() -> None:
    assert Placement(buildings=()).bounds == (0, 0, 0, 0)


def test_memoised_bounds_matches_the_old_four_comprehension_scan_on_a_real_layout() -> None:
    """Differential test against a real, non-synthetic layout.

    Decodes ``factory-endgame-distribution-hub.txt`` (1969 buildings) straight
    into ``PlacedBuilding`` records and asserts the memoised ``Placement.bounds``
    equals the LITERAL old four-comprehension expression this task replaced --
    not a re-derivation of it, the exact old code, so a divergence here is
    unambiguously a bug in the memo rather than a second copy of the same typo.
    """
    from flab2bp.dsp import catalog
    from flab2bp.dsp.codec import decode

    text = (FIXTURES / "factory-endgame-distribution-hub.txt").read_text()
    raw = decode(text).buildings

    records: list[PlacedBuilding] = []
    for b in raw:
        try:
            info = catalog.building(b.item_id)
        except KeyError:
            continue
        if not info.occupies_tiles:
            continue
        records.append(
            PlacedBuilding(
                item_id=b.item_id,
                model_index=b.model_index,
                x=round(b.x - info.width / 2 + 0.5),
                y=round(b.y - info.height / 2 + 0.5),
                width=info.width,
                height=info.height,
            )
        )
    assert len(records) > 1000  # sanity: this is the real, large fixture

    placement = Placement(buildings=tuple(records))

    # The literal old `Placement.bounds` body, verbatim.
    old_xs = [b.x for b in placement.buildings] + [b.x + b.width - 1 for b in placement.buildings]
    old_ys = [b.y for b in placement.buildings] + [b.y + b.height - 1 for b in placement.buildings]
    old_bounds = (min(old_xs), min(old_ys), max(old_xs), max(old_ys))

    assert placement.buildings_index is None  # nothing has asked yet
    assert placement.bounds == old_bounds
    assert placement.buildings_index is None  # bounds must not build the full index
    # Second call answers from the memo and still agrees.
    assert placement.bounds == old_bounds
