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
    truncated = len(buildings) > TRACE_MAX_BUILDINGS
    if truncated:
        # Every Nth building rather than the first N: a prefix of a packed
        # placement is one corner of it, which reads as a smaller layout instead
        # of a sampled one.
        step = (len(buildings) + TRACE_MAX_BUILDINGS - 1) // TRACE_MAX_BUILDINGS
        buildings = buildings[::step]
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
        "buildings": cast(Json, [building_row(b) for b in buildings]),
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
        fresh = [frame for frame in held if int(cast(int, frame["seq"])) > cursor]
        page = fresh[:limit]
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

    def _offer(self, event: SearchEvent) -> None:
        """The sink.  One deque append; a bounded deque evicts silently, so the
        eviction is counted here rather than discovered later."""
        if len(self._pending) == self._pending.maxlen:
            self._dropped += 1
        self._pending.append(event)

    def drain_once(self) -> None:
        if self.queue is not None:
            for event in drain_trace(cast(MessageQueue, self.queue)):
                # Same overflow accounting `_offer` uses: a bounded deque
                # evicts silently, so an eviction forced by a queue-sourced
                # event must be counted here too or it is discovered later.
                if len(self._pending) == self._pending.maxlen:
                    self._dropped += 1
                self._pending.append(event)
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
        while not self._stop.is_set():
            self.drain_once()
            self._stop.wait(TRACE_DRAIN_INTERVAL_S)
        self.drain_once()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)
        # Only drain here if the daemon thread is gone: `frame_json` reads and
        # then increments `self._seq`, and if the join above timed out (a
        # wedged thread), that thread could still be mid-drain -- draining
        # again concurrently from this thread would race on `_seq` and could
        # emit two frames with the same seq, or lose an increment.
        if thread is None or not thread.is_alive():
            self.drain_once()
