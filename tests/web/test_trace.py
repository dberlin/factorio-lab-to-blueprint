from fractions import Fraction

from flab2bp.layout.base import PlacedBuilding, Placement
from flab2bp.layout.observe import SearchEvent, SearchPhase
from flab2bp.web.trace import (
    TRACE_BUILDING_FIELDS,
    TRACE_MAX_BUILDINGS,
    TraceRing,
    building_row,
    frame_json,
)


def test_building_row_is_ten_positional_numbers_in_the_declared_order() -> None:
    building = PlacedBuilding(
        item_id=2001,
        model_index=35,
        x=4,
        y=7,
        z=Fraction(1, 2),
        yaw=90.0,
        recipe_id=61,
        filter_id=0,
        output_obj=12,
        input_obj=None,
    )
    assert TRACE_BUILDING_FIELDS == (
        "item_id",
        "model_index",
        "x",
        "y",
        "z",
        "yaw",
        "recipe_id",
        "filter_id",
        "output_obj",
        "input_obj",
    )
    # z is a float here on purpose: Fraction is exact because occupancy keys on
    # it (base.py:121-124), but a viewer draws pixels. `None` becomes -1, the
    # DSP convention (dsp/codec.py:276-277).
    assert building_row(building) == [2001, 35, 4, 7, 0.5, 90.0, 61, 0, 12, -1]


def test_frame_json_carries_metadata_and_no_blueprint_string() -> None:
    placement = Placement(
        buildings=(PlacedBuilding(item_id=2001, model_index=35, x=0, y=0),),
        stats={"belt_tiles": 611.0},
    )
    frame = frame_json(
        41,
        3.812,
        SearchEvent(
            strategy="freeform",
            candidate="all-products",
            phase=SearchPhase.INCUMBENT,
            placement=placement,
            height=34,
            arrangement=2,
            area=2244,
            belt_tiles=611,
            incumbent=True,
        ),
    )
    assert frame["seq"] == 41
    assert frame["t"] == 3.812
    assert frame["strategy"] == "freeform"
    assert frame["phase"] == "incumbent"
    assert frame["height"] == 34
    assert frame["restart"] is None
    assert frame["incumbent"] is True
    assert frame["buildings"] == [[2001, 35, 0, 0, 0.0, 0.0, 0, 0, -1, -1]]
    assert frame["bounds"] == [0, 0, 0, 0]
    assert frame["truncated"] is False
    # A frame is a picture, never a paste. Nothing here may be mistaken for one.
    assert "blueprint" not in frame


def test_frame_json_decimates_and_flags_an_oversized_placement() -> None:
    buildings = tuple(
        PlacedBuilding(item_id=2001, model_index=35, x=i, y=0)
        for i in range(TRACE_MAX_BUILDINGS + 100)
    )
    frame = frame_json(
        1,
        0.0,
        SearchEvent(
            strategy="freeform",
            candidate="c",
            phase=SearchPhase.PACKED,
            placement=Placement(buildings=buildings),
        ),
    )
    assert frame["truncated"] is True
    assert len(frame["buildings"]) <= TRACE_MAX_BUILDINGS


def test_ring_since_is_an_exclusive_cursor_and_reports_the_next_one() -> None:
    ring = TraceRing()
    for seq in range(5):
        ring.append({"seq": seq, "buildings": []})
    frames, nxt = ring.since(-1, limit=3)
    assert [f["seq"] for f in frames] == [0, 1, 2]
    assert nxt == 3
    frames, nxt = ring.since(2, limit=3)
    assert [f["seq"] for f in frames] == [3, 4]
    assert nxt == 5
    frames, nxt = ring.since(4, limit=3)
    assert frames == []
    assert nxt == 5


def test_ring_evicts_oldest_on_the_frame_bound_and_counts_it() -> None:
    ring = TraceRing(max_frames=3, max_bytes=1 << 30)
    for seq in range(5):
        ring.append({"seq": seq, "buildings": []})
    frames, _ = ring.since(-1, limit=10)
    assert [f["seq"] for f in frames] == [2, 3, 4]
    assert ring.dropped == 2


def test_ring_evicts_oldest_on_the_byte_bound_and_counts_it() -> None:
    # Each frame with 3 rows of 10 numbers costs 3*80+512 = 752 bytes.
    # max_bytes=2500 retains roughly 3 frames, making eviction order observable.
    ring = TraceRing(max_frames=1000, max_bytes=2500)
    for seq in range(20):
        ring.append({"seq": seq, "buildings": [[0] * 10] * 3})
    frames, _ = ring.since(-1, limit=100)
    # Oldest frames (0-16) are evicted, newest (17-19) survive.
    assert [f["seq"] for f in frames] == [17, 18, 19]
    assert ring.dropped == 17
