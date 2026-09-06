import queue
import threading
import time
from fractions import Fraction

from flab2bp.layout.base import PlacedBuilding, Placement
from flab2bp.layout.observe import SearchEvent, SearchPhase
from flab2bp.web.trace import (
    TRACE_BUILDING_FIELDS,
    TRACE_MAX_BUILDINGS,
    TraceCollector,
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
    """``next`` is the highest ``seq`` actually returned -- not that plus one --

    so that feeding it straight back as ``from`` (unchanged) is a correct,
    idempotent continuation.  When nothing is new, ``next`` is the caller's
    cursor, unchanged, rather than jumping past frames it never saw.
    """
    ring = TraceRing()
    for seq in range(5):
        ring.append({"seq": seq, "buildings": []})
    frames, nxt = ring.since(-1, limit=3)
    assert [f["seq"] for f in frames] == [0, 1, 2]
    assert nxt == 2
    frames, nxt = ring.since(nxt, limit=3)
    assert [f["seq"] for f in frames] == [3, 4]
    assert nxt == 4
    frames, nxt = ring.since(nxt, limit=3)
    assert frames == []
    assert nxt == 4


def test_ring_walk_delivers_every_frame_exactly_once_via_next_as_from() -> None:
    """The point of the cursor fix: repeatedly feeding ``next`` back as ``from``

    must never skip or repeat a frame.  Under the old ``+ 1`` semantics this
    fails -- the first page's ``next`` (3, one past the last delivered seq)
    would be fed back as ``from=3``, and ``since`` filters on ``seq > cursor``,
    so seq 3 itself is silently skipped.
    """
    ring = TraceRing()
    for seq in range(11):
        ring.append({"seq": seq, "buildings": []})

    delivered: list[int] = []
    cursor = -1
    stalls = 0
    while len(delivered) < 11:
        frames, nxt = ring.since(cursor, limit=3)
        if not frames:
            stalls += 1
            assert stalls < 100, "the walk made no progress"
            continue
        delivered.extend(int(f["seq"]) for f in frames)
        cursor = nxt
    assert delivered == list(range(11))


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


def test_ring_append_and_since_from_different_threads_never_raise() -> None:
    """``append`` (the trace daemon) and ``since`` (an HTTP handler) run on

    different threads for real. Without a lock, ``since`` iterating
    ``self._frames`` while ``append`` mutates it is exactly
    ``RuntimeError: deque mutated during iteration`` -- a poll landing mid-drain
    would 500. Hammer both concurrently and require no exception and a
    coherent (non-corrupt) result throughout.
    """
    ring = TraceRing(max_frames=50, max_bytes=1 << 30)
    stop = threading.Event()
    errors: list[BaseException] = []

    def writer() -> None:
        try:
            for seq in range(2000):
                ring.append({"seq": seq, "buildings": []})
        except BaseException as exc:  # noqa: BLE001 -- captured for the assertion
            errors.append(exc)
        finally:
            stop.set()

    def reader() -> None:
        try:
            while not stop.is_set():
                frames, nxt = ring.since(-1, limit=10)
                seqs = [int(f["seq"]) for f in frames]
                assert seqs == sorted(seqs), "a torn read returned frames out of order"
                assert nxt == (seqs[-1] if seqs else -1)
        except BaseException as exc:  # noqa: BLE001 -- captured for the assertion
            errors.append(exc)

    writer_thread = threading.Thread(target=writer)
    reader_thread = threading.Thread(target=reader)
    reader_thread.start()
    writer_thread.start()
    writer_thread.join(timeout=10.0)
    reader_thread.join(timeout=10.0)
    assert not errors, errors


def test_collector_projects_on_its_own_thread_and_pages_by_cursor() -> None:
    collector = TraceCollector(TraceRing(), started_at=time.monotonic())
    collector.start()
    try:
        for _ in range(3):
            collector.observer.note(
                SearchEvent(strategy="freeform", candidate="c", phase=SearchPhase.INCUMBENT)
            )
        deadline = time.monotonic() + 2.0
        while collector.ring.since(-1, limit=10)[0].__len__() < 3:
            assert time.monotonic() < deadline, "the trace thread never drained"
            time.sleep(0.01)
    finally:
        collector.stop()

    frames, nxt = collector.ring.since(-1, limit=2)
    assert [f["seq"] for f in frames] == [0, 1]
    assert nxt == 1
    frames, nxt = collector.ring.since(nxt, limit=2)
    assert [f["seq"] for f in frames] == [2]


def test_collector_drops_and_counts_when_stage_one_overflows() -> None:
    collector = TraceCollector(TraceRing(), started_at=time.monotonic(), stage1_maxlen=2)
    for _ in range(10):
        collector.observer.note(
            SearchEvent(strategy="freeform", candidate="c", phase=SearchPhase.INCUMBENT)
        )
    assert collector.dropped == 8


def test_collector_drains_a_raced_builds_queue_alongside_its_in_process_deque() -> None:
    """Task 8: a raced arm's events arrive on a queue, not through `.note()` --
    ``drain_once`` must pull from both sources in the same pass."""
    trace_queue: queue.Queue[object] = queue.Queue()
    trace_queue.put_nowait(
        SearchEvent(strategy="freeform", candidate="c", phase=SearchPhase.INCUMBENT)
    )
    trace_queue.put_nowait(
        SearchEvent(strategy="sequence-pair", candidate="c", phase=SearchPhase.INCUMBENT)
    )
    collector = TraceCollector(TraceRing(), started_at=time.monotonic(), queue=trace_queue)

    collector.drain_once()

    frames, nxt = collector.ring.since(-1, limit=10)
    assert [f["strategy"] for f in frames] == ["freeform", "sequence-pair"]
    assert nxt == 1


def test_collector_merges_an_in_process_event_and_a_queued_event_into_one_ordered_ring() -> None:
    """'One ordered ring' (Task 8): a cross-process source and an in-process
    one must not race each other into the ring on separate passes."""
    trace_queue: queue.Queue[object] = queue.Queue()
    collector = TraceCollector(TraceRing(), started_at=time.monotonic(), queue=trace_queue)

    collector.observer.note(
        SearchEvent(strategy="freeform", candidate="c", phase=SearchPhase.INCUMBENT)
    )
    trace_queue.put_nowait(
        SearchEvent(strategy="sequence-pair", candidate="c", phase=SearchPhase.INCUMBENT)
    )
    collector.drain_once()

    frames, nxt = collector.ring.since(-1, limit=10)
    assert [(f["seq"], f["strategy"]) for f in frames] == [
        (0, "freeform"),
        (1, "sequence-pair"),
    ]
    assert nxt == 1


def test_collector_stamps_a_frame_from_the_events_own_creation_time_not_drain_time() -> None:
    """Fix round 1, Important 3: a raced arm's burst of queued events must not
    collapse onto whatever instant this thread got around to draining them --
    each frame's `t` comes from `SearchEvent.monotonic_s`, captured where the
    event was made, in the CHILD, not from `time.monotonic()` read here."""
    started_at = 100.0
    trace_queue: queue.Queue[object] = queue.Queue()
    # Two events minted seconds apart in a (simulated) child, put on the queue
    # together -- as a real burst drained long after both were created would
    # arrive. A forward-time stamp would give both the same `t`; a
    # creation-time stamp must not.
    trace_queue.put_nowait(
        SearchEvent(
            strategy="freeform",
            candidate="c",
            phase=SearchPhase.INCUMBENT,
            monotonic_s=started_at + 1.0,
        )
    )
    trace_queue.put_nowait(
        SearchEvent(
            strategy="freeform",
            candidate="c",
            phase=SearchPhase.INCUMBENT,
            monotonic_s=started_at + 4.5,
        )
    )
    collector = TraceCollector(TraceRing(), started_at=started_at, queue=trace_queue)

    # However long AFTER creation this drain actually runs must not matter --
    # only the SearchEvent's own `monotonic_s` should reach `frame["t"]`.
    collector.drain_once()

    frames, _next = collector.ring.since(-1, limit=10)
    assert [f["t"] for f in frames] == [1.0, 4.5]


def test_collector_counts_a_queue_sourced_overflow_the_same_way_a_deque_overflow_is() -> None:
    trace_queue: queue.Queue[object] = queue.Queue()
    for _ in range(10):
        trace_queue.put_nowait(
            SearchEvent(strategy="freeform", candidate="c", phase=SearchPhase.INCUMBENT)
        )
    collector = TraceCollector(
        TraceRing(), started_at=time.monotonic(), stage1_maxlen=2, queue=trace_queue
    )

    collector.drain_once()

    assert collector.dropped == 8
