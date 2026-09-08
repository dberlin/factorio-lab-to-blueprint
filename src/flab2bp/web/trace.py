"""Search snapshots as JSON the viewer can draw, and the ring that holds them.

A frame is a LIGHTWEIGHT PLACEMENT ENCODING and never a blueprint.
``codec.encode`` asserts a finalized frame (dsp/codec.py:281) that a mid-search
pack does not have, and costs seconds on the large placements that are exactly
the ones worth watching.  So a frame carries positional building rows -- ten
numbers each -- which is all ``buildSceneModel`` (web/src/model/layout.ts:44)
ever reads.

Rows are positional and not objects because a 3000-building placement is ~240kB
as arrays and ~1.1MB as objects, and the server's existing gzip
(server.py:143) takes the former to about 30kB.
"""

from __future__ import annotations

import threading
from bisect import bisect_right
from collections import deque
from dataclasses import dataclass, field
from typing import Final, cast

from flab2bp.layout.base import PlacedBuilding
from flab2bp.layout.observe import TRACE_SAMPLE_INTERVAL_S, SampledObserver, SearchEvent
from flab2bp.layout.observe_channel import MessageQueue, drain_trace
from flab2bp.web.payload import Json

#: The row order.  Positional, so the client decodes with a zod tuple and the
#: names live in exactly one place: here.
TRACE_BUILDING_FIELDS: Final = (
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

TRACE_RING_FRAMES: Final = 256
TRACE_RING_BYTES: Final = 32 * 1024 * 1024
TRACE_MAX_BUILDINGS: Final = 6000
TRACE_PAGE_FRAMES: Final = 8

#: A rough per-row cost used for the byte bound.  Ten numbers plus separators;
#: exact enough to bound memory, and far cheaper than serializing to measure.
_ROW_BYTES: Final = 80


def building_row(building: PlacedBuilding) -> list[float]:
    """One building as ten positional numbers, in ``TRACE_BUILDING_FIELDS`` order."""
    return [
        building.item_id,
        building.model_index,
        building.x,
        building.y,
        float(building.z),
        building.yaw,
        building.recipe_id,
        building.filter_id,
        -1 if building.output_obj is None else building.output_obj,
        -1 if building.input_obj is None else building.input_obj,
    ]


def frame_json(seq: int, at_s: float, event: SearchEvent) -> Json:
    """Project one event into the wire frame.

    THE ONLY PLACE that walks ``placement.buildings``.  It runs on the parent's
    trace thread, never on a search thread.
    """
    placement = event.placement
    buildings = () if placement is None else placement.buildings
    original_count = len(buildings)
    truncated = original_count > TRACE_MAX_BUILDINGS
    # Uniform-stride sampling keeps the whole layout in view. Links belong to
    # this dense wire scene, not to the unsampled placement's index space.
    step = (original_count + TRACE_MAX_BUILDINGS - 1) // TRACE_MAX_BUILDINGS if truncated else 1
    rows: list[list[float]] = []
    for index in range(0, original_count, step):
        row = building_row(buildings[index])
        if truncated:
            for field_index in (8, 9):
                target = int(row[field_index])
                row[field_index] = (
                    target // step if 0 <= target < original_count and target % step == 0 else -1
                )
        rows.append(row)
    return {
        "seq": seq,
        "t": at_s,
        "strategy": event.strategy,
        "candidate": event.candidate,
        "phase": str(event.phase),
        "height": event.height,
        "arrangement": event.arrangement,
        "restart": event.restart,
        "stage": event.stage,
        "island": event.island,
        "round": event.round_index,
        "block": event.block,
        "area": event.area,
        "belt_tiles": event.belt_tiles,
        "incumbent": event.incumbent,
        "reason": event.reason,
        "bounds": list(placement.bounds) if placement is not None else [0, 0, 0, 0],
        "buildings": cast(Json, rows),
        "truncated": truncated,
        "stranded": [list(pair) for pair in event.stranded],
        "no_goods": [list(group) for group in event.no_goods],
    }


@dataclass
class TraceRing:
    """The newest frames for one job, bounded by count AND by bytes.

    Both bounds, because 256 frames of 6000 buildings is memory this process
    does not have, and a byte bound alone would let a stream of tiny frames
    grow without limit.
    """

    max_frames: int = TRACE_RING_FRAMES
    max_bytes: int = TRACE_RING_BYTES
    _frames: deque[tuple[Json, int]] = field(default_factory=deque, init=False)
    _bytes: int = field(default=0, init=False)
    _dropped: int = field(default=0, init=False)
    #: ``append`` runs on the collector's daemon thread; ``since`` runs on an
    #: HTTP handler thread.  Without this, a poll landing mid-append iterates
    #: the deque while it is being mutated -- CPython raises
    #: ``RuntimeError: deque mutated during iteration`` -- and a trace poll
    #: would occasionally 500.  The critical section is just the deque copy /
    #: mutation; ``frame_json`` and all projection happen well outside it.
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    @property
    def dropped(self) -> int:
        return self._dropped

    def append(self, frame: Json) -> None:
        rows = frame.get("buildings")
        size = (len(rows) if isinstance(rows, list) else 0) * _ROW_BYTES + 512
        with self._lock:
            self._frames.append((frame, size))
            self._bytes += size
            while len(self._frames) > self.max_frames or (
                self._bytes > self.max_bytes and len(self._frames) > 1
            ):
                _evicted, evicted_size = self._frames.popleft()
                self._bytes -= evicted_size
                self._dropped += 1

    def since(self, cursor: int, *, limit: int = TRACE_PAGE_FRAMES) -> tuple[list[Json], int]:
        """Frames with ``seq > cursor``, and the cursor to pass back next time.

        The cursor is EXCLUSIVE.  ``next`` is the highest ``seq`` actually
        returned in this page -- NOT that plus one -- so ``?from=<next>`` is a
        correct, idempotent continuation: feeding it back asks for
        ``seq > next``, which is exactly "everything after what was just
        delivered."  When nothing is new, ``next`` is the caller's cursor,
        unchanged, rather than jumping ahead of frames the caller never saw.
        """
        with self._lock:
            held = [frame for frame, _size in self._frames]
        # The collector assigns monotonically increasing sequence numbers.
        start = bisect_right(held, cursor, key=lambda frame: int(cast(int, frame["seq"])))
        # Preserve slice semantics even for zero and negative page limits.
        stop = start + limit if limit >= 0 else limit
        page = held[start:stop]
        if not page:
            return [], cursor
        return page, int(cast(int, page[-1]["seq"]))


TRACE_DRAIN_INTERVAL_S: Final = 0.1
TRACE_STAGE1_MAXLEN: Final = 64


@dataclass
class TraceCollector:
    """Stage 1 plus the thread that turns it into stage 2.

    Stage 1 holds REFERENCES to frozen ``SearchEvent``s and is written by the
    search; stage 2 holds projected JSON and is written here.  The split is the
    whole performance argument: ``frame_json`` walks every building, and it must
    never do so on a thread the search is trying to spend its core on.

    Stage 1 evicts the OLDEST on overflow, because a backlog means this thread is
    behind and the newest state is the one worth showing.  The ring evicts oldest
    too, but for the opposite reason: a scrubber wants a contiguous recent
    window.
    """

    ring: TraceRing
    started_at: float
    stage1_maxlen: int = TRACE_STAGE1_MAXLEN
    min_interval_s: float = TRACE_SAMPLE_INTERVAL_S
    #: The parent's read end of a raced build's child-to-parent trace queue, or
    #: ``None`` for an in-process-only build.  Drained in the same
    #: ``drain_once`` pass as ``_pending`` (Task 8), so a cross-process source
    #: and an in-process one land in one ordered ring rather than two.
    queue: object | None = None
    _pending: deque[SearchEvent] = field(init=False)
    _dropped: int = field(default=0, init=False)
    _seq: int = field(default=0, init=False)
    _stop: threading.Event = field(default_factory=threading.Event, init=False)
    _closed: threading.Event = field(default_factory=threading.Event, init=False)
    _failed: threading.Event = field(default_factory=threading.Event, init=False)
    _error: str | None = field(default=None, init=False)
    _thread: threading.Thread | None = field(default=None, init=False)
    observer: SampledObserver = field(init=False)

    def __post_init__(self) -> None:
        self._pending = deque(maxlen=self.stage1_maxlen)
        self.observer = SampledObserver(sink=self._offer, min_interval_s=self.min_interval_s)

    @property
    def dropped(self) -> int:
        """Genuine loss: stage-1 overflow only.

        The ring's own eviction (:attr:`TraceRing.dropped`) is a bounded
        window doing exactly what it is for -- keeping the newest frames --
        and is reported separately (``jobs.py``'s ``trace_page``, wire field
        ``evicted``) so a reader is never told a healthy build lost data
        (fix round, Important 6).
        """
        return self._dropped

    @property
    def closed(self) -> bool:
        """Publication finished successfully; no later frame can appear."""
        return self._closed.is_set()

    @property
    def error(self) -> str | None:
        """A reader/projection failure, published separately from clean closure."""
        return self._error if self._failed.is_set() else None

    def _offer(self, event: SearchEvent) -> None:
        """The sink.  One deque append; a bounded deque evicts silently, so the
        eviction is counted here rather than discovered later."""
        if len(self._pending) == self._pending.maxlen:
            self._dropped += 1
        self._pending.append(event)

    def drain_once(self) -> None:
        try:
            if self.queue is not None:
                for event in drain_trace(cast(MessageQueue, self.queue)):
                    # Same overflow accounting `_offer` uses: a bounded deque
                    # evicts silently, so an eviction forced by a queue-sourced
                    # event must be counted here too or it is discovered later.
                    if len(self._pending) == self._pending.maxlen:
                        self._dropped += 1
                    self._pending.append(event)
        finally:
            # A later transport failure cannot discard earlier dequeues or
            # serial events already retained in the sole stage-1 buffer.
            while self._pending:
                event = self._pending.popleft()
                # `event.monotonic_s`, a CHILD-originated timestamp captured where
                # the event was created (`SearchEvent`'s own `default_factory`,
                # observe.py) -- never the time THIS thread happened to forward or
                # drain it. A raced arm's whole burst of events would otherwise
                # collapse onto the one instant this thread got around to them,
                # which is exactly candidate-settlement time for a queue-sourced
                # burst and defeats a shared `t` axis across strategies.
                self.ring.append(
                    frame_json(self._seq, round(event.monotonic_s - self.started_at, 3), event)
                )
                self._seq += 1

    def start(self) -> None:
        thread = threading.Thread(target=self._run, name="flab2bp-trace", daemon=True)
        # `thread.start()` BEFORE the assignment (fix round, Critical 1): if
        # starting ever raises (OS thread exhaustion), `self._thread` must stay
        # `None` -- the dataclass default -- rather than referencing a Thread
        # that was constructed but never actually started. `stop()` below
        # already treats `None` as "nothing to join, just drain"; getting the
        # order backwards here made `stop()` call `.join()` on a
        # never-started thread instead, which raises `RuntimeError: cannot
        # join thread before it is started` -- in a caller's `finally`
        # (`web/jobs.py`'s `Builder._run`), ahead of the trace queue's own
        # cleanup, leaking it.
        thread.start()
        self._thread = thread

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                self.drain_once()
                self._stop.wait(TRACE_DRAIN_INTERVAL_S)
            self._finish()
        except Exception as exc:
            self._record_failure(exc)

    def _record_failure(self, exc: Exception) -> None:
        self._error = f"trace collection failed: {exc}"
        self._failed.set()

    def _finish(self) -> None:
        try:
            # A queue pass is bounded. Once producers have stopped, keep
            # draining until a pass publishes nothing, not just one last batch.
            while True:
                previous_seq = self._seq
                self.drain_once()
                if self._seq == previous_seq:
                    break
        except Exception as exc:
            self._record_failure(exc)
        else:
            self._closed.set()

    def stop(self, *, timeout: float | None = 2.0) -> bool:
        """Stop after producers finish; false means timeout or a reported error.

        A timeout leaves the reader and its queue owned and alive. The queue
        owner must wait for reader termination before releasing its resources;
        ``timeout=None`` performs that wait without changing solver job state.
        """
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)
            if thread.is_alive():
                return False
        elif not self.closed and self.error is None:
            self._finish()
        return self.closed
