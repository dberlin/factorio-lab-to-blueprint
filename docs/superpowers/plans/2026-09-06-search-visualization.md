# Live Search Visualization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in `trace` mode in which a build streams lightweight search snapshots to the browser and the existing three.js viewer plays them back on a timeline, without measurably slowing the search.

**Architecture:** A `SearchObserver` protocol is threaded through `pipeline.build` exactly as `on_progress` is, with a `due(phase)` gate so the hot path pays one comparison. Sampled `SearchEvent`s go into a stage-1 ring (a `deque` in-process, a bounded `multiprocessing.Queue` across a spawn boundary, modelled on `RaceChannels`), and a parent-side `flab2bp-trace` daemon thread projects them into stage-2 JSON frames of raw building rows. The browser polls a second cursor endpoint, `GET /api/build/<id>/trace?from=<seq>`, and feeds the rows straight into `buildSceneModel` with no blueprint round trip.

**Tech Stack:** Python 3.14 (stdlib `http.server`, `multiprocessing`, `dataclasses`, `StrEnum`), pytest; React 19 + three.js + zod under `web/`, rstest.

**Spec:** `docs/superpowers/specs/2026-09-06-search-visualization-design.md`

## Global Constraints

- **Default off.** `Options.trace` defaults to `False`; `BuildOptions.trace` defaults to `false`. With trace off, `GET /api/build/<id>` must be byte-identical to today.
- **Hot-path contract (spec §5.4).** R1: no observer call inside a CP-SAT callback or solver-driven loop — candidate/stage/round/incumbent boundaries only. R2: an observer call never reads, writes, or keys on anything the search reads. R3: `note` never raises. R4: `SearchEvent` is constructed *inside* the `due()` branch.
- **Never reuse `publish_incumbent`** (`freeform.py:19420`, `sequence_solver.py:6303`) for trace. In the raced child it runs a full `validate.validate` (`strategy_race.py:515-530`). The observer is a separate parameter; both coexist.
- **A trace frame is never pasteable.** No blueprint string on a frame, no validity claim, `snapshotLabel` non-null while one is shown.
- **Constants** (exact values, `src/flab2bp/web/trace.py` unless stated): `TRACE_RING_FRAMES = 256`; `TRACE_RING_BYTES = 32 * 1024 * 1024`; `TRACE_MAX_BUILDINGS = 6000`; `TRACE_PAGE_FRAMES = 8`; `TRACE_DRAIN_INTERVAL_S = 0.1`; `TRACE_STAGE1_MAXLEN = 64`; and in `src/flab2bp/layout/observe_channel.py`: `TRACE_QUEUE_MAXSIZE = 64`, `TRACE_DRAIN_MAX_EVENTS = 32`.
- **Sample intervals:** `0.25` s in-process, `0.5` s inside a spawned child.
- **`web/src/format`, `web/src/model`, `web/src/api` must import neither React nor three.js** — enforced by `web/tests/architecture.test.ts:40-47`.
- **Do not run layouts on this box without checking with the user.** Tasks 1–11 are unit-testable in milliseconds. Task 12 is the only one that runs real solves.
- **Commit trailers** on every commit:
  ```
  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_014jHGF2vGRJ5KDBB3JevhQb
  ```

## File Structure

**Create**

| Path | Responsibility |
| --- | --- |
| `src/flab2bp/layout/observe.py` | `SearchPhase`, `SearchEvent`, `SearchObserver`, `SampledObserver`. Imports only `base.Placement`. |
| `src/flab2bp/layout/observe_channel.py` | `TraceChannel`, the `_TRACE_CHANNEL` global, `install_trace_channel`, `trace_channel`, `drain_trace`. |
| `src/flab2bp/web/trace.py` | `TraceRing`, `building_row`, `frame_json`, `TraceCollector` (stage 1 + the drain thread). |
| `tests/layout/test_observe.py` | Observer vocabulary and sampler. |
| `tests/layout/test_observe_channel.py` | Channel drop/close/drain. |
| `tests/web/test_trace.py` | Ring, cursor, projection. |
| `web/src/api/trace.ts` | zod `TraceFrame` / `TracePage`, `pollTrace`. |
| `web/src/model/traceScene.ts` | `traceFrameToBlueprint`. |
| `web/src/ui/TracePanel.tsx` | Timeline, lanes, block grid, metadata table. |
| `web/src/scene/TraceOverlay.tsx` | Stranded-net segments, no-good tinted footprints. |
| `web/tests/api/trace.test.ts`, `web/tests/model/traceScene.test.ts`, `web/tests/ui/TracePanel.test.tsx` | Client tests. |
| `scripts/trace_overhead.py` | The Rule P / Rule W harness. |

**Modify**

| Path | Change |
| --- | --- |
| `src/flab2bp/pipeline.py:200-224, 562-613, 823-839, 863-889` | `search_observer` parameter, threaded to `_new_layout` and `run_strategy_race`. |
| `src/flab2bp/layout/freeform.py:19410-19452, 21600-21675` | `observer` parameter; five call sites. |
| `src/flab2bp/layout/sequence_solver.py:1010-1037, 2510-2530, 6288-6325` | `observer` parameter; three call sites. |
| `src/flab2bp/layout/strategy_race.py:304-327, 424-451, 469-530, 649-678, 681-696` | Trace queue through `initargs`; observer into `_build_layout`. |
| `src/flab2bp/web/jobs.py:60-84, 180-309, 312-337, 350-377, 386-401, 429-468, 470-519` | `Options.trace`, `Job.trace`, collector lifecycle, snapshot echo. |
| `src/flab2bp/web/server.py:194-223` | The `/api/build/<id>/trace` route. |
| `web/src/api/build.ts:204-241` | `BuildOptions.trace`, `DEFAULT_OPTIONS.trace`, `Job.options`. |
| `web/src/state/BlueprintProvider.tsx:6-20, 24-66` | `loadSnapshot`, `snapshotLabel`. |
| `web/src/ui/BuildPanel.tsx:28-35` | Trace checkbox; mount `<TracePanel>`. |
| `web/src/scene/BlueprintCanvas.tsx` | Mount `<TraceOverlay>`. |
| `tests/web/test_server.py`, `tests/web/test_options.py` | Endpoint and option coverage. |

---

### Task 1: Observer vocabulary and sampler

**Files:**
- Create: `src/flab2bp/layout/observe.py`
- Test: `tests/layout/test_observe.py`

**Interfaces:**
- Consumes: `flab2bp.layout.base.Placement`.
- Produces: `SearchPhase` (StrEnum: `PACKED`, `ROUTED`, `CERTIFIED`, `INCUMBENT`, `REFUSED`, `BLOCK`, `RECUT`, `COMPOSED`); `ALWAYS_SAMPLE: frozenset[SearchPhase]`; `SearchEvent` (frozen slots dataclass, fields in the order below); `SearchObserver` Protocol with `due(phase) -> bool` and `note(event) -> None`; `SampledObserver(sink, min_interval_s=0.25, monotonic=time.monotonic)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/layout/test_observe.py
from fractions import Fraction

import pytest

from flab2bp.layout.base import PlacedBuilding, Placement
from flab2bp.layout.observe import (
    ALWAYS_SAMPLE,
    SampledObserver,
    SearchEvent,
    SearchPhase,
)


def _placement() -> Placement:
    return Placement(buildings=(PlacedBuilding(item_id=2001, model_index=35, x=0, y=0),))


class _Clock:
    """A monotonic that only moves when the test says so."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_event_holds_the_same_placement_object_it_was_given() -> None:
    placement = _placement()
    event = SearchEvent(
        strategy="freeform",
        candidate="all-products",
        phase=SearchPhase.PACKED,
        placement=placement,
    )
    # A copy here would defeat the whole point: Placement is frozen, so a
    # reference costs a pointer and can never change under a reader.
    assert event.placement is placement


def test_sampler_refuses_a_second_ordinary_sample_inside_the_interval() -> None:
    clock = _Clock()
    seen: list[SearchEvent] = []
    observer = SampledObserver(sink=seen.append, min_interval_s=0.25, monotonic=clock)

    assert observer.due(SearchPhase.PACKED) is True
    observer.note(SearchEvent(strategy="freeform", candidate="c", phase=SearchPhase.PACKED))
    clock.now = 0.1
    assert observer.due(SearchPhase.PACKED) is False
    clock.now = 0.25
    assert observer.due(SearchPhase.PACKED) is True
    assert len(seen) == 1


def test_incumbent_and_composed_bypass_the_interval() -> None:
    clock = _Clock()
    observer = SampledObserver(sink=lambda _e: None, min_interval_s=1000.0, monotonic=clock)
    observer.note(SearchEvent(strategy="freeform", candidate="c", phase=SearchPhase.PACKED))
    assert observer.due(SearchPhase.PACKED) is False
    assert observer.due(SearchPhase.INCUMBENT) is True
    assert observer.due(SearchPhase.COMPOSED) is True
    assert ALWAYS_SAMPLE == frozenset({SearchPhase.INCUMBENT, SearchPhase.COMPOSED})


def test_note_never_raises_when_the_sink_does() -> None:
    def explode(_event: SearchEvent) -> None:
        raise RuntimeError("a trace sink must never kill a build")

    observer = SampledObserver(sink=explode)
    # R3: a progress sink that raises is a caller bug worth surfacing; a TRACE
    # sink that raises would kill a real build for a debugging view.
    observer.note(SearchEvent(strategy="freeform", candidate="c", phase=SearchPhase.PACKED))


def test_event_is_frozen() -> None:
    event = SearchEvent(strategy="freeform", candidate="c", phase=SearchPhase.PACKED)
    with pytest.raises(AttributeError):
        event.strategy = "sequence-pair"  # type: ignore[misc]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/layout/test_observe.py -x -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'flab2bp.layout.observe'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/flab2bp/layout/observe.py
"""What a search is doing, told to someone who is only watching.

Deliberately NOT ``pipeline.ProgressSink`` (pipeline.py:529-532).  That sink
reports pair boundaries to a caller with a progress bar and is allowed to raise,
because a progress sink that raises is a bug in the caller.  This one reports
SEARCH INTERIOR to a debugging view, fires orders of magnitude more often, and
must never take a real build down with it.

The two-method protocol is the whole performance story: ``due`` decides whether
a sample is wanted BEFORE ``SearchEvent`` is built, so the cost at a call site
that is not sampling is one attribute lookup, one set membership test, one
``time.monotonic()`` and one float compare -- and nothing ever touches
``placement.buildings``.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final, Protocol

from flab2bp.layout.base import Placement


class SearchPhase(StrEnum):
    """What kind of moment an event describes."""

    PACKED = "packed"
    ROUTED = "routed"
    CERTIFIED = "certified"
    INCUMBENT = "incumbent"
    REFUSED = "refused"
    BLOCK = "block"
    RECUT = "recut"
    COMPOSED = "composed"


#: Phases rare and load-bearing enough to bypass the sample gate.  An incumbent
#: is the one frame nobody wants dropped, and there is at most a handful per
#: build; composition happens once.
ALWAYS_SAMPLE: Final[frozenset[SearchPhase]] = frozenset(
    {SearchPhase.INCUMBENT, SearchPhase.COMPOSED}
)


@dataclass(frozen=True, slots=True)
class SearchEvent:
    """One thing a search did, as an immutable reference to state it already holds.

    ``placement`` is a REFERENCE and never a copy: ``Placement`` (base.py:423)
    and every ``PlacedBuilding`` in it (base.py:93) are frozen, so holding one
    costs a pointer and cannot be mutated out from under a reader.
    """

    strategy: str
    candidate: str
    phase: SearchPhase
    placement: Placement | None = None
    height: int | None = None
    arrangement: int | None = None
    restart: int | None = None
    stage: int | None = None
    island: int | None = None
    round_index: int | None = None
    block: int | None = None
    area: int | None = None
    belt_tiles: int | None = None
    incumbent: bool = False
    reason: str | None = None
    stranded: tuple[tuple[int, int, int, int], ...] = ()
    no_goods: tuple[tuple[int, ...], ...] = ()


class SearchObserver(Protocol):
    """Told what a search is doing.  Read-only, by construction."""

    def due(self, phase: SearchPhase, /) -> bool:
        """Would ``note`` do anything for this phase right now?  O(1)."""
        ...

    def note(self, event: SearchEvent, /) -> None:
        """Record ``event``.  O(1), and never raises."""
        ...


@dataclass(slots=True)
class SampledObserver:
    """Rate-limits by wall time and hands survivors to an O(1) sink.

    ``sink`` is ``deque.append`` in-process and ``TraceChannel.offer`` across a
    process boundary.  Both are non-blocking; a full destination drops and counts
    rather than waiting, exactly as ``RaceChannels._put`` does
    (strategy_race.py:199-203), because a dropped frame costs a picture and never
    a result.
    """

    sink: Callable[[SearchEvent], None]
    min_interval_s: float = 0.25
    monotonic: Callable[[], float] = time.monotonic
    _last_s: float = field(default=float("-inf"), init=False)

    def due(self, phase: SearchPhase, /) -> bool:
        if phase in ALWAYS_SAMPLE:
            return True
        return self.monotonic() - self._last_s >= self.min_interval_s

    def note(self, event: SearchEvent, /) -> None:
        self._last_s = self.monotonic()
        try:
            self.sink(event)
        except Exception:  # noqa: BLE001 -- R3: a view must never kill a build.
            pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/layout/test_observe.py -q`
Expected: exit code 0. (The pytest summary line does not print on this box; check `echo $?`.)

- [ ] **Step 5: Commit**

```bash
git add src/flab2bp/layout/observe.py tests/layout/test_observe.py
git commit -m "feat(observe): add the search observer vocabulary and sampler

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014jHGF2vGRJ5KDBB3JevhQb"
```

---

### Task 2: Trace ring and frame projection

**Files:**
- Create: `src/flab2bp/web/trace.py`
- Test: `tests/web/test_trace.py`

**Interfaces:**
- Consumes: `SearchEvent`, `SearchPhase` (Task 1); `flab2bp.web.payload.Json`.
- Produces: `TRACE_BUILDING_FIELDS`, `TRACE_RING_FRAMES`, `TRACE_RING_BYTES`, `TRACE_MAX_BUILDINGS`, `TRACE_PAGE_FRAMES`; `building_row(b: PlacedBuilding) -> list[float]`; `frame_json(seq: int, at_s: float, event: SearchEvent) -> Json`; `TraceRing()` with `append(frame: Json) -> None`, `since(cursor: int, *, limit: int = TRACE_PAGE_FRAMES) -> tuple[list[Json], int]`, and a `dropped: int` property.

- [ ] **Step 1: Write the failing test**

```python
# tests/web/test_trace.py
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
    ring = TraceRing(max_frames=1000, max_bytes=200)
    for seq in range(20):
        ring.append({"seq": seq, "buildings": [[0] * 10] * 3})
    frames, _ = ring.since(-1, limit=100)
    assert ring.dropped > 0
    assert len(frames) < 20
    assert [f["seq"] for f in frames] == sorted(f["seq"] for f in frames)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/web/test_trace.py -x -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'flab2bp.web.trace'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/flab2bp/web/trace.py
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

from collections import deque
from dataclasses import dataclass, field
from typing import Final

from flab2bp.layout.base import PlacedBuilding
from flab2bp.layout.observe import SearchEvent
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
        "buildings": [building_row(b) for b in buildings],
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

    @property
    def dropped(self) -> int:
        return self._dropped

    def append(self, frame: Json) -> None:
        rows = frame.get("buildings")
        size = (len(rows) if isinstance(rows, list) else 0) * _ROW_BYTES + 512
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

        The cursor is EXCLUSIVE and the returned one is the highest seq held
        plus one, so a caller that asks again with it gets nothing until
        something new arrives -- and a caller whose cursor has aged out of the
        ring gets the oldest retained frame rather than an error.
        """
        held = [frame for frame, _size in self._frames]
        fresh = [frame for frame in held if int(frame["seq"]) > cursor]
        page = fresh[:limit]
        if held:
            nxt = int(held[-1]["seq"]) + 1
        else:
            nxt = cursor + 1
        if page:
            nxt = int(page[-1]["seq"]) + 1
        return page, nxt
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/web/test_trace.py -q; echo $?`
Expected: `0`

- [ ] **Step 5: Commit**

```bash
git add src/flab2bp/web/trace.py tests/web/test_trace.py
git commit -m "feat(trace): project search events into bounded JSON frames

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014jHGF2vGRJ5KDBB3JevhQb"
```

---

### Task 3: Thread `search_observer` through the pipeline and wire freeform

**Files:**
- Modify: `src/flab2bp/pipeline.py:200-224` (`_new_layout`), `:562-613` (`build` signature), `:823-839` (`_solve_one`)
- Modify: `src/flab2bp/layout/freeform.py:19410-19452` (`__init__`), `:21600-21675` (sweep call sites)
- Test: `tests/layout/test_freeform.py` (append), `tests/test_pipeline.py` (append)

**Interfaces:**
- Consumes: `SearchObserver`, `SearchEvent`, `SearchPhase` (Task 1).
- Produces: `pipeline.build(..., search_observer: SearchObserver | None = None)`; `pipeline._new_layout(..., observer: SearchObserver | None = None)`; `FreeformLayout(..., observer: SearchObserver | None = None)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/layout/test_freeform.py  (append)
from flab2bp.layout.observe import SearchEvent, SearchPhase


class _RecordingObserver:
    """Takes everything, so a test sees every site rather than a sample."""

    def __init__(self) -> None:
        self.events: list[SearchEvent] = []

    def due(self, phase: SearchPhase, /) -> bool:
        return True

    def note(self, event: SearchEvent, /) -> None:
        self.events.append(event)


def test_freeform_reports_an_incumbent_to_its_observer(small_spec) -> None:
    observer = _RecordingObserver()
    layout = FreeformLayout(band_policy=BandPolicy.parse("portable"), observer=observer)
    placement = layout.lay_out(small_spec, time_budget_s=5.0)

    incumbents = [e for e in observer.events if e.phase is SearchPhase.INCUMBENT]
    assert incumbents, "a completed freeform sweep has at least one incumbent"
    last = incumbents[-1]
    assert last.strategy == "freeform"
    assert last.candidate == small_spec.label
    assert last.incumbent is True
    assert last.area == placement.area
    assert last.height is not None
    assert last.placement is not None


def test_freeform_without_an_observer_is_unchanged(small_spec) -> None:
    band = BandPolicy.parse("portable")
    a = FreeformLayout(band_policy=band, workers=DETERMINISTIC_WORKERS).lay_out(
        small_spec, time_budget_s=5.0
    )
    b = FreeformLayout(
        band_policy=band, workers=DETERMINISTIC_WORKERS, observer=None
    ).lay_out(small_spec, time_budget_s=5.0)
    assert (a.area, a.stats["belt_tiles"]) == (b.area, b.stats["belt_tiles"])
```

```python
# tests/test_pipeline.py  (append)
def test_build_threads_the_search_observer_to_the_serial_strategy(monkeypatch) -> None:
    seen: dict[str, object] = {}
    real = pipeline._new_layout

    def spy(*args: object, **kwargs: object) -> object:
        seen["observer"] = kwargs.get("observer")
        return real(*args, **kwargs)

    monkeypatch.setattr(pipeline, "_new_layout", spy)
    observer = _RecordingObserver()
    pipeline.build(SMALL_URL, strategy="freeform", time_budget_s=2.0, search_observer=observer)
    assert seen["observer"] is observer
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/layout/test_freeform.py -k observer -x -q`
Expected: FAIL — `TypeError: FreeformLayout.__init__() got an unexpected keyword argument 'observer'`

- [ ] **Step 3: Write minimal implementation**

In `src/flab2bp/layout/freeform.py`, add to `FreeformLayout.__init__` after
`publish_incumbent` (currently `freeform.py:19420`):

```python
        #: Told what this sweep is doing, for a debugging view.  A SEPARATE
        #: parameter from `publish_incumbent` on purpose: in the raced child
        #: that callback runs a full `validate.validate` before publishing
        #: (strategy_race.py:515-530) because a bound the parent would reject
        #: must not prune the peer -- a cost a picture must never pay -- and it
        #: fires only on an improvement, so it cannot express a pack, a refusal,
        #: or a stranded net.
        observer: SearchObserver | None = None,
```

and in the body, after `self.publish_incumbent = publish_incumbent` (`:19452`):

```python
        self.observer = observer
```

Add five call sites in the sweep. After the pack is built and before routing:

```python
                    if self.observer is not None and self.observer.due(SearchPhase.PACKED):
                        self.observer.note(
                            SearchEvent(
                                strategy="freeform",
                                candidate=spec.label,
                                phase=SearchPhase.PACKED,
                                placement=placement,
                                height=height,
                                arrangement=arrangement,
                                area=placement.area,
                            )
                        )
```

Immediately before `key = (placement.area, ...)` at `freeform.py:21607`:

```python
                    if self.observer is not None and self.observer.due(SearchPhase.ROUTED):
                        self.observer.note(
                            SearchEvent(
                                strategy="freeform",
                                candidate=spec.label,
                                phase=SearchPhase.ROUTED,
                                placement=placement,
                                height=height,
                                arrangement=arrangement,
                                area=placement.area,
                                belt_tiles=int(placement.stats.get("belt_tiles", 0)),
                                stranded=_stranded_endpoints(route_result),
                            )
                        )
```

After `report = validate.certify(...)` at `freeform.py:21633`:

```python
                    if self.observer is not None and self.observer.due(SearchPhase.CERTIFIED):
                        self.observer.note(
                            SearchEvent(
                                strategy="freeform",
                                candidate=spec.label,
                                phase=SearchPhase.CERTIFIED,
                                placement=placement,
                                height=height,
                                arrangement=arrangement,
                                area=placement.area,
                                belt_tiles=int(placement.stats.get("belt_tiles", 0)),
                                reason=None if not report.errors else report.errors[0].message,
                            )
                        )
```

Inside the refusal retention at `freeform.py:21649-21651`:

```python
                    if self.observer is not None and self.observer.due(SearchPhase.REFUSED):
                        self.observer.note(
                            SearchEvent(
                                strategy="freeform",
                                candidate=spec.label,
                                phase=SearchPhase.REFUSED,
                                placement=placement,
                                height=height,
                                arrangement=arrangement,
                                reason=report.errors[0].message,
                            )
                        )
```

Immediately after `self.publish_incumbent(placement)` at `freeform.py:21675`:

```python
                        if self.observer is not None and self.observer.due(SearchPhase.INCUMBENT):
                            self.observer.note(
                                SearchEvent(
                                    strategy="freeform",
                                    candidate=spec.label,
                                    phase=SearchPhase.INCUMBENT,
                                    placement=placement,
                                    height=height,
                                    arrangement=arrangement,
                                    area=placement.area,
                                    belt_tiles=int(placement.stats.get("belt_tiles", 0)),
                                    incumbent=True,
                                )
                            )
```

Add the helper beside `_would_become_incumbent` (`freeform.py:21781`):

```python
def _stranded_endpoints(result: object) -> tuple[tuple[int, int, int, int], ...]:
    """Endpoint pairs for the nets a routing result could not wire.

    Typed ``object`` and read defensively for one reason only: this runs on a
    debugging path, and a shape change in ``DetailedRouteResult`` must degrade
    the picture, never the build (observe.SampledObserver's R3 in the caller is
    the second net, not an excuse to skip this one).
    """
    stranded = getattr(result, "stranded", ())
    pairs: list[tuple[int, int, int, int]] = []
    for net in stranded:
        source = getattr(net, "source_cell", None)
        sink = getattr(net, "sink_cell", None)
        if source is None or sink is None:
            continue
        pairs.append((int(source[0]), int(source[1]), int(sink[0]), int(sink[1])))
    return tuple(pairs)
```

In `src/flab2bp/pipeline.py`, add `observer: SearchObserver | None = None` to
`_new_layout` (`pipeline.py:200-212`) and pass it to `FreeformLayout(...)` at
`:215-219` and to `SequencePairLayout(...)` at `:220-224` (the latter is a no-op
until Task 7 and must be added now so the two constructors do not drift). Add
`search_observer: SearchObserver | None = None` to `build`'s keyword-only
parameters beside `on_progress` (`pipeline.py:595`), documented:

```python
    #: Told what the SEARCH is doing, for the trace view.  Distinct from
    #: `on_progress`, which reports pair boundaries: this reports the interior,
    #: fires far more often, and is never allowed to raise.  `None` -- the
    #: default and the shipping path -- costs one `is None` per call site.
    search_observer: SearchObserver | None = None,
```

and pass it in `_solve_one` (`pipeline.py:829-835`) as `observer=search_observer`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/layout/test_freeform.py tests/test_pipeline.py -q; echo $?`
Expected: `0`

- [ ] **Step 5: Commit**

```bash
git add src/flab2bp/pipeline.py src/flab2bp/layout/freeform.py tests/layout/test_freeform.py tests/test_pipeline.py
git commit -m "feat(freeform): report sweep events to an optional search observer

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014jHGF2vGRJ5KDBB3JevhQb"
```

---

### Task 4: Job option, collector, and the trace endpoint

**Files:**
- Create: `TraceCollector` in `src/flab2bp/web/trace.py` (append)
- Modify: `src/flab2bp/web/jobs.py:60-84`, `:195-206`, `:298-309`, `:312-337`, `:350-377`, `:429-468`, `:486-506`
- Modify: `src/flab2bp/web/server.py:205-213`
- Test: `tests/web/test_trace.py` (append), `tests/web/test_options.py` (append), `tests/web/test_server.py` (append)

**Interfaces:**
- Consumes: `TraceRing`, `frame_json` (Task 2); `SampledObserver` (Task 1).
- Produces: `TraceCollector(ring: TraceRing, started_at: float)` with `.observer: SampledObserver`, `.start() -> None`, `.stop() -> None`, `.dropped: int`; `Options.trace: bool`; `Job.trace: TraceCollector | None`; `Builder.trace_page(job, cursor) -> Json`; route `GET /api/build/<id>/trace?from=<seq>`.

- [ ] **Step 1: Write the failing test**

```python
# tests/web/test_trace.py  (append)
import time

from flab2bp.layout.observe import SearchEvent, SearchPhase
from flab2bp.web.trace import TraceCollector, TraceRing


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
    assert nxt == 2
    frames, nxt = collector.ring.since(nxt - 1, limit=2)
    assert [f["seq"] for f in frames] == [2]


def test_collector_drops_and_counts_when_stage_one_overflows() -> None:
    collector = TraceCollector(TraceRing(), started_at=time.monotonic(), stage1_maxlen=2)
    for _ in range(10):
        collector.observer.note(
            SearchEvent(strategy="freeform", candidate="c", phase=SearchPhase.INCUMBENT)
        )
    assert collector.dropped == 8
```

```python
# tests/web/test_options.py  (append)
def test_trace_defaults_off_and_round_trips() -> None:
    assert parse_options({"url": "https://example/x"}).trace is False
    assert parse_options({"url": "https://example/x", "trace": True}).trace is True


def test_trace_must_be_a_boolean() -> None:
    with pytest.raises(InvalidOptions, match="'trace' must be a boolean"):
        parse_options({"url": "https://example/x", "trace": "yes"})
```

```python
# tests/web/test_server.py  (append)
def test_trace_endpoint_reports_an_empty_page_when_trace_is_off(client) -> None:
    job = client.post("/api/build", {"url": SMALL_URL})
    body = client.get(f"/api/build/{job['id']}/trace?from=-1")
    assert body == {"frames": [], "next": -1, "dropped": 0, "complete": False}


def test_trace_endpoint_404s_for_an_unknown_job(client) -> None:
    status, body = client.get_status("/api/build/deadbeef/trace?from=-1")
    assert status == 404
    assert body == {"error": "no such job"}


def test_job_snapshot_echoes_the_trace_option(client) -> None:
    job = client.post("/api/build", {"url": SMALL_URL, "trace": True})
    assert job["options"]["trace"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/web/test_trace.py tests/web/test_options.py tests/web/test_server.py -k trace -x -q`
Expected: FAIL — `ImportError: cannot import name 'TraceCollector'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/flab2bp/web/trace.py`:

```python
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
    min_interval_s: float = 0.25
    _pending: deque[tuple[float, SearchEvent]] = field(init=False)
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
        return self._dropped + self.ring.dropped

    def _offer(self, event: SearchEvent) -> None:
        """The sink.  One deque append; a bounded deque evicts silently, so the
        eviction is counted here rather than discovered later."""
        if len(self._pending) == self._pending.maxlen:
            self._dropped += 1
        self._pending.append((time.monotonic(), event))

    def drain_once(self) -> None:
        while self._pending:
            at, event = self._pending.popleft()
            self.ring.append(frame_json(self._seq, round(at - self.started_at, 3), event))
            self._seq += 1

    def start(self) -> None:
        thread = threading.Thread(target=self._run, name="flab2bp-trace", daemon=True)
        self._thread = thread
        thread.start()

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
        self.drain_once()
```

with `import threading`, `import time`, and `from flab2bp.layout.observe import SampledObserver`
added at the top.

In `src/flab2bp/web/jobs.py`:

- `Options` gains, after `fetch_flow` (`jobs.py:83`):
  ```python
      #: Stream search snapshots to the caller.  OFF by default: a picture of the
      #: search is a debugging instrument, and every build paying for one is not
      #: a trade anybody asked for.
      trace: bool = False
  ```
- `parse_options`: add `"trace"` to `allowed` (`jobs.py:195-206`), and before the
  `return Options(...)`:
  ```python
      trace = raw.get("trace", False)
      if not isinstance(trace, bool):
          raise InvalidOptions("'trace' must be a boolean")
  ```
  then `trace=trace,` in the constructor call (`jobs.py:298-309`).
- `Job` gains `trace: TraceCollector | None = None` (`jobs.py:312-337`).
- `run_build` gains a third parameter and passes it through:
  ```python
  def run_build(
      options: Options,
      on_progress: pipeline.ProgressSink,
      search_observer: SearchObserver | None = None,
  ) -> pipeline.Build:
      return pipeline.build(..., search_observer=search_observer)
  ```
  and `Solve` becomes
  `Callable[[Options, pipeline.ProgressSink, SearchObserver | None], pipeline.Build]`
  (`jobs.py:380-383`).
- `Builder._run` (`jobs.py:429-468`), immediately after the state flip:
  ```python
          collector: TraceCollector | None = None
          if job.options.trace:
              collector = TraceCollector(TraceRing(), started_at=time.monotonic())
              collector.start()
              with job._lock:
                  job.trace = collector
  ```
  the solve call becomes
  `build = self._solve(job.options, note, None if collector is None else collector.observer)`,
  and a `finally:` around the whole try block calls `collector.stop()` when it is
  not `None`.
- `Builder.snapshot` adds `"trace": job.options.trace` to the `"options"` dict
  (`jobs.py:486-506`).
- New method on `Builder`:
  ```python
      def trace_page(self, job: Job, cursor: int) -> Json:
          """The frames after ``cursor``, or an empty page when trace is off."""
          with job._lock:
              collector = job.trace
              done = job.done
          if collector is None:
              return {"frames": [], "next": cursor, "dropped": 0, "complete": done}
          frames, nxt = collector.ring.since(cursor)
          return {
              "frames": frames,
              "next": nxt,
              "dropped": collector.dropped,
              "complete": done and not frames,
          }
  ```

In `src/flab2bp/web/server.py`, before the existing `/api/build/` branch at
`:205`:

```python
        if path.startswith("/api/build/") and path.endswith("/trace"):
            job_id = path.removeprefix("/api/build/").removesuffix("/trace")
            job = self.builder.get(job_id)
            if job is None:
                self._json(HTTPStatus.NOT_FOUND, {"error": "no such job"})
                return
            raw_cursor = parse_qs(parsed.query).get("from", ["-1"])[0]
            try:
                cursor = int(raw_cursor)
            except ValueError:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "'from' must be an integer"})
                return
            self._json(HTTPStatus.OK, self.builder.trace_page(job, cursor))
            return
```

and extend the quiet-logging guard at `server.py:126-130` so a trace poll is not
logged either.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/web -q; echo $?`
Expected: `0`

- [ ] **Step 5: Commit**

```bash
git add src/flab2bp/web/trace.py src/flab2bp/web/jobs.py src/flab2bp/web/server.py tests/web/
git commit -m "feat(web): collect trace frames and serve them on a cursor endpoint

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014jHGF2vGRJ5KDBB3JevhQb"
```

---

### Task 5: The first shippable increment — freeform incumbents live in the viewer

**Files:**
- Create: `web/src/api/trace.ts`, `web/src/model/traceScene.ts`, `web/src/ui/TracePanel.tsx`
- Modify: `web/src/api/build.ts:204-241`, `web/src/state/BlueprintProvider.tsx:6-20, 24-66`, `web/src/ui/BuildPanel.tsx:28-35`
- Test: `web/tests/api/trace.test.ts`, `web/tests/model/traceScene.test.ts`, `web/tests/ui/TracePanel.test.tsx`

**Interfaces:**
- Consumes: the endpoint and schema from Task 4.
- Produces: `TraceFrame`, `TracePage`, `pollTrace(id, from, signal)`; `traceFrameToBlueprint(frame): Blueprint`; `BlueprintState.loadSnapshot(bp, label)`, `BlueprintState.snapshotLabel`; `<TracePanel jobId={string} active={boolean} />`.

- [ ] **Step 1: Write the failing test**

```ts
// web/tests/model/traceScene.test.ts
import { expect, test } from '@rstest/core';
import type { TraceFrame } from '../../src/api/trace';
import { traceFrameToBlueprint } from '../../src/model/traceScene';

const frame: TraceFrame = {
  seq: 1, t: 0.5, strategy: 'freeform', candidate: 'all-products', phase: 'incumbent',
  height: 34, arrangement: 2, restart: null, stage: null, island: null,
  round: null, block: null, area: 12, belt_tiles: 2, incumbent: true, reason: null,
  bounds: [0, 0, 3, 3], truncated: false, stranded: [], no_goods: [],
  buildings: [
    [2001, 35, 0, 0, 0, 0, 61, 0, 1, -1],
    [2001, 35, 1, 0, 0.5, 90, 0, 0, -1, 0],
  ],
};

test('rows become buildings whose index is their array position', () => {
  const bp = traceFrameToBlueprint(frame);
  expect(bp.buildings).toHaveLength(2);
  expect(bp.buildings[0]?.index).toBe(0);
  expect(bp.buildings[1]?.index).toBe(1);
  expect(bp.buildings[0]?.itemId).toBe(2001);
  expect(bp.buildings[1]?.z).toBe(0.5);
  expect(bp.buildings[1]?.yaw).toBe(90);
});

test('connection indices survive so belt runs can be built', () => {
  const bp = traceFrameToBlueprint(frame);
  expect(bp.buildings[0]?.outputObjIdx).toBe(1);
  expect(bp.buildings[0]?.inputObjIdx).toBe(-1);
  expect(bp.buildings[1]?.inputObjIdx).toBe(0);
});

test('a synthesised frame is renderable by buildSceneModel', async () => {
  const { buildSceneModel } = await import('../../src/model/layout');
  const { loadCatalogFixture } = await import('../helpers/catalog');
  const model = buildSceneModel(traceFrameToBlueprint(frame), await loadCatalogFixture());
  expect(model.instances).toHaveLength(2);
});
```

```ts
// web/tests/api/trace.test.ts
import { expect, test } from '@rstest/core';
import { TraceFrame, TracePage } from '../../src/api/trace';

test('a frame parses and rejects a row of the wrong arity', () => {
  const good = { /* the frame literal above */ };
  expect(() => TraceFrame.parse(good)).not.toThrow();
  expect(() => TraceFrame.parse({ ...good, buildings: [[1, 2, 3]] })).toThrow();
});

test('a page carries a cursor, a drop count and a completion flag', () => {
  const page = TracePage.parse({ frames: [], next: 7, dropped: 3, complete: true });
  expect(page.next).toBe(7);
  expect(page.dropped).toBe(3);
  expect(page.complete).toBe(true);
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd web && bun run test -- traceScene trace`
Expected: FAIL — cannot resolve `../../src/api/trace`.

- [ ] **Step 3: Write minimal implementation**

`web/src/api/trace.ts`:

```ts
/**
 * The client half of the trace endpoint — poll with a cursor, parse with zod.
 *
 * A cursor rather than SSE, deliberately: `Handler._send` (server.py:137-158)
 * writes a whole body with a Content-Length, an SSE connection would pin a
 * ThreadingHTTPServer thread for a whole build, and — the part that matters —
 * a cursor is REPLAYABLE. Reopening the tab or scrubbing backwards re-reads
 * the ring at any offset; a stream cannot be rewound.
 *
 * Free of React and three.js, per web/tests/architecture.test.ts:40-47.
 */
import { z } from 'zod';

/** Ten positional numbers, in `TRACE_BUILDING_FIELDS` order (web/trace.py). */
export const TraceBuildingRow = z.tuple([
  z.number(), z.number(), z.number(), z.number(), z.number(),
  z.number(), z.number(), z.number(), z.number(), z.number(),
]);

export const TracePhase = z.enum([
  'packed', 'routed', 'certified', 'incumbent', 'refused', 'block', 'recut', 'composed',
]);

export const TraceFrame = z.object({
  seq: z.number(),
  t: z.number(),
  strategy: z.enum(['freeform', 'sequence-pair', 'hierarchical']),
  candidate: z.string(),
  phase: TracePhase,
  height: z.number().nullable(),
  arrangement: z.number().nullable(),
  restart: z.number().nullable(),
  stage: z.number().nullable(),
  island: z.number().nullable(),
  round: z.number().nullable(),
  block: z.number().nullable(),
  area: z.number().nullable(),
  belt_tiles: z.number().nullable(),
  incumbent: z.boolean(),
  reason: z.string().nullable(),
  bounds: z.tuple([z.number(), z.number(), z.number(), z.number()]),
  buildings: z.array(TraceBuildingRow),
  truncated: z.boolean(),
  stranded: z.array(z.tuple([z.number(), z.number(), z.number(), z.number()])),
  no_goods: z.array(z.array(z.number())),
});

export const TracePage = z.object({
  frames: z.array(TraceFrame),
  next: z.number(),
  dropped: z.number(),
  complete: z.boolean(),
});

export type TraceFrame = z.infer<typeof TraceFrame>;
export type TracePage = z.infer<typeof TracePage>;
export type TracePhase = z.infer<typeof TracePhase>;

/** One trace poll. `from` is exclusive; pass back the returned `next`. */
export async function pollTrace(
  id: string,
  from: number,
  signal?: AbortSignal,
): Promise<TracePage> {
  const response = await fetch(
    `/api/build/${encodeURIComponent(id)}/trace?from=${from}`,
    { signal },
  );
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return TracePage.parse(await response.json());
}

/** Live-tail cadence. Fixed, not the job poll's backoff (build.ts:346-348):
    that backoff exists to keep a five-minute build from making 300 requests,
    which is the opposite of what a live tail wants. */
export const TRACE_POLL_MS = 250;
```

`web/src/model/traceScene.ts`:

```ts
/**
 * A trace frame, rendered by the viewer that already exists.
 *
 * `buildSceneModel` (model/layout.ts:44) reads only `bp.buildings`, so a frame
 * needs no header, no areas, no hash and no patch — and therefore no
 * `parseBlueprint`, no base64, no gzip and no md5f. This is the entire reason
 * a snapshot is raw rows rather than an encoded blueprint: `codec.encode`
 * asserts a finalized frame (dsp/codec.py:281) that a mid-search pack does not
 * have, and costs seconds.
 */
import type { TraceFrame } from '../api/trace';
import type { Blueprint, BlueprintBuilding } from '../format/types';

const EMPTY_HEADER = {
  headerVersion: 0, layout: 10, icons: [], timestamp: 0n,
  gameVersion: '0.0.0.0', shortDesc: '', author: 'flab2bp-trace',
  customVersion: '', attributes: [], description: '',
};

export function traceFrameToBlueprint(frame: TraceFrame): Blueprint {
  const [minX, minY, maxX, maxY] = frame.bounds;
  const buildings: BlueprintBuilding[] = frame.buildings.map((row, index) => {
    const [itemId, modelIndex, x, y, z, yaw, recipeId, filterId, outputObj, inputObj] = row;
    return {
      index, areaIndex: 0, itemId, modelIndex,
      x, y, z, x2: x, y2: y, z2: z,
      yaw, yaw2: yaw, tilt: 0, tilt2: 0, pitch: 0, pitch2: 0,
      outputObjIdx: outputObj, inputObjIdx: inputObj,
      outputToSlot: 0, inputFromSlot: 0, outputFromSlot: 0, inputToSlot: 0,
      outputOffset: 0, inputOffset: 0,
      recipeId, filterId, parameters: [], content: null,
    };
  });
  return {
    header: EMPTY_HEADER,
    // A trace frame was never hashed and never encoded. Saying `true` here
    // would be a claim about an artifact that does not exist.
    hashValid: false,
    version: 1, cursorOffsetX: 0, cursorOffsetY: 0, cursorTargetArea: 0,
    dragBoxSizeX: Math.max(1, maxX - minX + 1),
    dragBoxSizeY: Math.max(1, maxY - minY + 1),
    primaryAreaIdx: 0, patch: null,
    areas: [{
      index: 0, parentIndex: -1, tropicAnchor: 0, areaSegments: 0,
      anchorLocalOffsetX: 0, anchorLocalOffsetY: 0,
      width: Math.max(1, maxX - minX + 1), height: Math.max(1, maxY - minY + 1),
    }],
    buildings,
  };
}

/** The caption shown over a snapshot, so it is never read as a result. */
export function traceFrameLabel(frame: TraceFrame): string {
  const parts = [`TRACE · ${frame.strategy} · ${frame.candidate} · ${frame.phase}`];
  if (frame.height !== null) parts.push(`h=${frame.height}`);
  if (frame.restart !== null) parts.push(`r=${frame.restart}`);
  if (frame.round !== null) parts.push(`round ${frame.round}`);
  if (frame.block !== null) parts.push(`block ${frame.block}`);
  if (frame.area !== null) parts.push(`${frame.area} tiles`);
  if (frame.belt_tiles !== null) parts.push(`${frame.belt_tiles} belt`);
  if (frame.reason !== null) parts.push(frame.reason);
  return parts.join(' · ');
}
```

`web/src/state/BlueprintProvider.tsx`: add to `BlueprintState` (`:6-20`)

```ts
  /** Non-null exactly while a SEARCH SNAPSHOT is on the canvas. A snapshot is
      a picture of a search state: it was never encoded, never validated, and
      must never be mistaken for something pasteable. */
  snapshotLabel: string | null;
  loadSnapshot(bp: Blueprint, label: string): void;
```

and in the provider, a `const [snapshotLabel, setSnapshotLabel] = useState<string | null>(null)`,
`loadSnapshot` setting both blueprint and label, and `load` clearing the label
(`setSnapshotLabel(null)`) at `:41`.

`web/src/api/build.ts`: add `trace: z.boolean()` to `BuildOptions` (`:204-219`),
`trace: false` to `DEFAULT_OPTIONS` (`:228-241`), and `trace: z.boolean()` to the
`options` object inside the `Job` schema.

`web/src/ui/TracePanel.tsx` (minimal for this task; the scrubber lands in Task 11):

```tsx
/** Live tail of a traced build. Polls its own cursor at TRACE_POLL_MS. */
export function TracePanel({ jobId, active }: { jobId: string; active: boolean }) {
  const { loadSnapshot } = useBlueprint();
  const [frames, setFrames] = useState<TraceFrame[]>([]);
  const [dropped, setDropped] = useState(0);
  const [tailing, setTailing] = useState(true);

  useEffect(() => {
    if (!active) return;
    const controller = new AbortController();
    let cursor = -1;
    let stop = false;
    (async () => {
      while (!stop) {
        const page = await pollTrace(jobId, cursor, controller.signal);
        cursor = page.next;
        setDropped(page.dropped);
        if (page.frames.length > 0) setFrames((held) => [...held, ...page.frames].slice(-256));
        if (page.complete) return;
        await new Promise((r) => setTimeout(r, TRACE_POLL_MS));
      }
    })().catch(() => undefined);
    return () => { stop = true; controller.abort(); };
  }, [jobId, active]);

  const newest = frames[frames.length - 1];
  useEffect(() => {
    if (tailing && newest) loadSnapshot(traceFrameToBlueprint(newest), traceFrameLabel(newest));
  }, [tailing, newest, loadSnapshot]);

  /* … the metadata table, the tail toggle, and the dropped count … */
}
```

`web/src/ui/BuildPanel.tsx`: a `trace` checkbox bound into `options`, and
`{job && options.trace && <TracePanel jobId={job.id} active={!isSettled(job)} />}`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd web && bun run test && bun run lint && bun run typecheck`
Expected: all pass, including `web/tests/architecture.test.ts` (the new
`src/api` and `src/model` files import neither React nor three.js).

- [ ] **Step 5: Commit — THIS IS THE SHIPPABLE INCREMENT**

```bash
git add web/src/api/trace.ts web/src/model/traceScene.ts web/src/ui/TracePanel.tsx \
        web/src/api/build.ts web/src/state/BlueprintProvider.tsx web/src/ui/BuildPanel.tsx \
        web/tests/api/trace.test.ts web/tests/model/traceScene.test.ts web/tests/ui/TracePanel.test.tsx
git commit -m "feat(web): live-tail freeform search snapshots in the blueprint viewer

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014jHGF2vGRJ5KDBB3JevhQb"
```

- [ ] **Step 6: Confirm it by hand**

Run `uv run flab2bp-web`, submit a corpus URL with **strategy `freeform`** (the
serial path — `best` is raced and does not trace until Task 8), tick **trace**,
and watch the canvas update as the sweep finds incumbents. The caption must read
`TRACE · freeform · …` throughout and must never show a copyable blueprint.

---

### Task 6: Carry trace across a spawn boundary

**Files:**
- Create: `src/flab2bp/layout/observe_channel.py`
- Test: `tests/layout/test_observe_channel.py`

**Interfaces:**
- Consumes: `SearchEvent` (Task 1); `strategy_race._MessageQueue` (`strategy_race.py:122-132`), `strategy_race._JoinCancellable` (`:135-147`).
- Produces: `TRACE_QUEUE_MAXSIZE = 64`, `TRACE_DRAIN_MAX_EVENTS = 32`; `TraceChannel(publish)` with `offer(event)`, `close()`, `dropped`; `install_trace_channel(queue: object) -> None`; `trace_channel() -> TraceChannel | None`; `drain_trace(queue) -> tuple[SearchEvent, ...]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/layout/test_observe_channel.py
import queue

from flab2bp.layout.observe import SearchEvent, SearchPhase
from flab2bp.layout.observe_channel import (
    TRACE_DRAIN_MAX_EVENTS,
    TraceChannel,
    drain_trace,
    install_trace_channel,
    trace_channel,
)


def _event() -> SearchEvent:
    return SearchEvent(strategy="freeform", candidate="c", phase=SearchPhase.INCUMBENT)


def test_offer_drops_and_counts_when_the_queue_is_full() -> None:
    channel = TraceChannel(publish=queue.Queue(maxsize=2))
    for _ in range(5):
        channel.offer(_event())
    # A dropped frame costs a picture and never a result, exactly as
    # RaceChannels._put has it (strategy_race.py:199-203).
    assert channel.dropped == 3


def test_offer_never_raises_on_an_unexpected_queue_failure() -> None:
    class _Broken:
        def put_nowait(self, item: object, /) -> None:
            raise RuntimeError("the pipe went away")

        def get_nowait(self) -> object:
            raise queue.Empty

    channel = TraceChannel(publish=_Broken())
    channel.offer(_event())
    assert channel.dropped == 1


def test_drain_is_bounded_per_poll() -> None:
    q: queue.Queue[object] = queue.Queue()
    for _ in range(TRACE_DRAIN_MAX_EVENTS + 10):
        q.put_nowait(_event())
    assert len(drain_trace(q)) == TRACE_DRAIN_MAX_EVENTS


def test_drain_ignores_anything_that_is_not_a_search_event() -> None:
    q: queue.Queue[object] = queue.Queue()
    q.put_nowait("not an event")
    q.put_nowait(_event())
    assert len(drain_trace(q)) == 1


def test_install_and_read_back_the_module_global() -> None:
    q: queue.Queue[object] = queue.Queue()
    install_trace_channel(q)
    try:
        channel = trace_channel()
        assert channel is not None
        channel.offer(_event())
        assert isinstance(q.get_nowait(), SearchEvent)
    finally:
        install_trace_channel(None)
        assert trace_channel() is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/layout/test_observe_channel.py -x -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'flab2bp.layout.observe_channel'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/flab2bp/layout/observe_channel.py
"""Getting trace events from a spawned child to the parent.

Modelled directly on ``RaceChannels`` (strategy_race.py:187-236), and for the
same reasons: a ``multiprocessing.Queue`` reaches a child only through
``initargs`` (strategy_race.py:396-401), a full queue must never make a searcher
wait, and an unread queue with buffered data blocks its process's exit until
something reads it -- which after a deadline is nobody.

One direction only.  The race's queues are peer-to-peer because each arm both
publishes and consumes; this one is child-to-parent, and the parent never
answers.
"""

from __future__ import annotations

import queue
from dataclasses import dataclass, field
from typing import Final, Protocol, runtime_checkable

from flab2bp.layout.observe import SearchEvent

TRACE_QUEUE_MAXSIZE: Final = 64
TRACE_DRAIN_MAX_EVENTS: Final = 32


class _MessageQueue(Protocol):
    def put_nowait(self, item: object, /) -> None: ...
    def get_nowait(self) -> object: ...


@runtime_checkable
class _JoinCancellable(Protocol):
    def cancel_join_thread(self) -> None: ...


@dataclass
class TraceChannel:
    """A child's write end of the child -> parent trace queue."""

    publish: _MessageQueue
    _dropped: int = field(default=0, init=False)

    @property
    def dropped(self) -> int:
        return self._dropped

    def offer(self, event: SearchEvent, /) -> None:
        """Enqueue, or drop and count.  Never blocks and never raises.

        Broad except on purpose: this is the last hop of a debugging path, and a
        pipe that went away must cost the picture and not the build.
        """
        try:
            self.publish.put_nowait(event)
        except Exception:  # noqa: BLE001
            self._dropped += 1

    def close(self) -> None:
        if isinstance(self.publish, _JoinCancellable):
            self.publish.cancel_join_thread()


_TRACE_CHANNEL: TraceChannel | None = None


def install_trace_channel(q: object) -> None:
    """Pool initializer half: give this child its write end.  ``None`` clears it."""
    global _TRACE_CHANNEL
    _TRACE_CHANNEL = None if q is None else TraceChannel(publish=q)  # type: ignore[arg-type]


def trace_channel() -> TraceChannel | None:
    return _TRACE_CHANNEL


def drain_trace(q: _MessageQueue) -> tuple[SearchEvent, ...]:
    """Parent side: at most ``TRACE_DRAIN_MAX_EVENTS`` events per poll.

    The bound is on the GETS and not on what survives the type check, for the
    reason ``RaceChannels.drain`` gives (strategy_race.py:212-218): the cost of a
    poll is the dequeue.
    """
    taken: list[SearchEvent] = []
    for _ in range(TRACE_DRAIN_MAX_EVENTS):
        try:
            item = q.get_nowait()
        except queue.Empty:
            break
        if isinstance(item, SearchEvent):
            taken.append(item)
    return tuple(taken)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/layout/test_observe_channel.py -q; echo $?`
Expected: `0`

- [ ] **Step 5: Commit**

```bash
git add src/flab2bp/layout/observe_channel.py tests/layout/test_observe_channel.py
git commit -m "feat(observe): add the child-to-parent trace channel

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014jHGF2vGRJ5KDBB3JevhQb"
```

---

### Task 7: Sequence-pair events

**Files:**
- Modify: `src/flab2bp/layout/sequence_solver.py:1010-1037` (inner search `__init__`), `:2510-2530` (incumbent), `:6288-6325` (`SequencePairLayout.__init__`), plus the site where a `StageObservation` is appended
- Test: `tests/layout/test_sequence_solver.py` (append)

**Interfaces:**
- Consumes: `SearchObserver`, `SearchEvent`, `SearchPhase` (Task 1).
- Produces: `SequencePairLayout(..., observer: SearchObserver | None = None)`, forwarded to the inner search as `observer=`.

- [ ] **Step 1: Write the failing test**

```python
# tests/layout/test_sequence_solver.py  (append)
from flab2bp.layout.observe import SearchEvent, SearchPhase


class _RecordingObserver:
    def __init__(self) -> None:
        self.events: list[SearchEvent] = []

    def due(self, phase: SearchPhase, /) -> bool:
        return True

    def note(self, event: SearchEvent, /) -> None:
        self.events.append(event)


def test_sequence_pair_reports_stage_observations_and_incumbents(small_spec) -> None:
    observer = _RecordingObserver()
    layout = SequencePairLayout(
        band_policy=BandPolicy.parse("portable"),
        config=SequenceSolverConfig.test(),
        islands=1,
        observer=observer,
    )
    layout.lay_out(small_spec, time_budget_s=10.0)

    routed = [e for e in observer.events if e.phase is SearchPhase.ROUTED]
    assert routed, "a sequence-pair search closes at least one stage"
    first = routed[0]
    assert first.strategy == "sequence-pair"
    # Every one of these is already on the StageObservation the search builds
    # anyway (sequence_solver.py:811-856); the observer copies, never computes.
    assert first.height is not None
    assert first.restart is not None
    assert first.stage is not None

    incumbents = [e for e in observer.events if e.phase is SearchPhase.INCUMBENT]
    assert incumbents
    assert incumbents[-1].incumbent is True
    assert incumbents[-1].placement is not None


def test_sequence_pair_islands_report_no_island_index(small_spec) -> None:
    # v1 limitation L1: a second spawn level is not traced. The frame says so
    # with a null rather than implying the merged result is one island's search.
    observer = _RecordingObserver()
    SequencePairLayout(
        band_policy=BandPolicy.parse("portable"),
        config=SequenceSolverConfig.test(),
        islands=2,
        observer=observer,
    ).lay_out(small_spec, time_budget_s=10.0)
    assert all(e.island is None for e in observer.events)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/layout/test_sequence_solver.py -k observer -x -q`
Expected: FAIL — `TypeError: SequencePairLayout.__init__() got an unexpected keyword argument 'observer'`

- [ ] **Step 3: Write minimal implementation**

Add `observer: SearchObserver | None = None` to `SequencePairLayout.__init__`
after `publish_incumbent` (`sequence_solver.py:6303`), store it as
`self.observer = observer` beside `:6325`, and forward it where the inner search
is constructed (`sequence_solver.py:6413-6414`). Add the same parameter to the
inner search's `__init__` after `publish_incumbent` (`:1036`) and store it.

Where a `StageObservation` is appended, add:

```python
        if self.observer is not None and self.observer.due(SearchPhase.ROUTED):
            self.observer.note(
                SearchEvent(
                    strategy="sequence-pair",
                    candidate=spec.label,
                    phase=SearchPhase.ROUTED,
                    placement=selected.placement,
                    height=stage.height,
                    restart=stage.restart,
                    stage=stage.stage_index,
                    area=None if stage.exact_key is None else stage.exact_key[0],
                    belt_tiles=None if stage.exact_key is None else stage.exact_key[1],
                    reason=stage.detailed_skip_reason or stage.global_skip_reason,
                    stranded=(),
                )
            )
```

Immediately after `self.publish_incumbent(finalized)` (`sequence_solver.py:2529`):

```python
                        if self.observer is not None and self.observer.due(
                            SearchPhase.INCUMBENT
                        ):
                            self.observer.note(
                                SearchEvent(
                                    strategy="sequence-pair",
                                    candidate=spec.label,
                                    phase=SearchPhase.INCUMBENT,
                                    placement=finalized,
                                    area=exact_key[0],
                                    belt_tiles=exact_key[1],
                                    incumbent=True,
                                )
                            )
```

and on a failing `ValidationVerdict` (the `else` of `if verdict.ok:` at
`sequence_solver.py:2516`):

```python
                if self.observer is not None and self.observer.due(SearchPhase.REFUSED):
                    self.observer.note(
                        SearchEvent(
                            strategy="sequence-pair",
                            candidate=spec.label,
                            phase=SearchPhase.REFUSED,
                            placement=verdict.placement,
                            reason="; ".join(verdict.failures) or "validation refused",
                        )
                    )
```

`run_sequence_islands` (`sequence_islands.py:272`) is **not** given the observer:
it spawns a second pool, which v1 does not trace (spec §6.4, Limitation L1).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/layout/test_sequence_solver.py -q; echo $?`
Expected: `0`

- [ ] **Step 5: Commit**

```bash
git add src/flab2bp/layout/sequence_solver.py tests/layout/test_sequence_solver.py
git commit -m "feat(sequence-pair): report stage observations and incumbents to the observer

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014jHGF2vGRJ5KDBB3JevhQb"
```

---

### Task 8: Racing — both arms, side by side

**Files:**
- Modify: `src/flab2bp/layout/strategy_race.py:304-327`, `:396-421`, `:424-451`, `:469-530`, `:649-678`, `:681-696`
- Modify: `src/flab2bp/pipeline.py:863-889`
- Modify: `src/flab2bp/web/trace.py` (`TraceCollector` drains a queue as well as a deque)
- Modify: `web/src/ui/TracePanel.tsx` (one lane per strategy)
- Test: `tests/layout/test_strategy_race.py` (append), `web/tests/ui/TracePanel.test.tsx` (append)

**Interfaces:**
- Consumes: `TraceChannel`, `install_trace_channel`, `drain_trace`, `TRACE_QUEUE_MAXSIZE` (Task 6); `SampledObserver` (Task 1).
- Produces: `run_strategy_race(..., trace_queue: object | None = None)`; `_StrategyRaceRequest.trace` (bool); `_StrategyRaceOutcome.trace_dropped` (int); `TraceCollector(..., queue=<mp.Queue>|None)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/layout/test_strategy_race.py  (append)
import multiprocessing

from flab2bp.layout.observe import SearchEvent
from flab2bp.layout.observe_channel import drain_trace


def test_a_raced_build_delivers_events_from_both_arms_to_the_parent(small_spec) -> None:
    ctx = multiprocessing.get_context("spawn")
    trace_queue = ctx.Queue(maxsize=64)
    outcomes = strategy_race.run_strategy_race(
        small_spec,
        time_budget_s=8.0,
        band_policy=BandPolicy.parse("portable"),
        belt_vertical_construction=True,
        workers=4,
        trace_queue=trace_queue,
    )
    assert {o.strategy for o in outcomes} == {"freeform", "sequence-pair"}

    events: list[SearchEvent] = []
    while True:
        batch = drain_trace(trace_queue)
        if not batch:
            break
        events.extend(batch)
    assert events, "a traced race delivers at least one event"
    # Two arms, one time axis: the UI's whole side-by-side view depends on the
    # strategy travelling on every event rather than being inferred.
    assert {e.strategy for e in events} <= {"freeform", "sequence-pair"}
    assert all(e.candidate == small_spec.label for e in events)


def test_a_race_without_a_trace_queue_installs_no_initializer(small_spec, monkeypatch) -> None:
    seen: dict[str, object] = {}
    real = strategy_race._pool_submit

    def spy(requests, channels, trace_queue=None):
        seen["trace_queue"] = trace_queue
        return real(requests, channels, trace_queue)

    monkeypatch.setattr(strategy_race, "_pool_submit", spy)
    strategy_race.run_strategy_race(
        small_spec,
        time_budget_s=4.0,
        band_policy=BandPolicy.parse("portable"),
        belt_vertical_construction=True,
        workers=2,
    )
    assert seen["trace_queue"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/layout/test_strategy_race.py -k trace -x -q`
Expected: FAIL — `TypeError: run_strategy_race() got an unexpected keyword argument 'trace_queue'`

- [ ] **Step 3: Write minimal implementation**

In `src/flab2bp/layout/strategy_race.py`:

- `_StrategyRaceRequest` (`:304-327`) gains `trace: bool` — a plain bool, because
  the queue itself cannot be pickled as a task argument (`:399-400`).
- New composite initializer beside `_install_race_channels` (`:404-417`):
  ```python
  def _install_child_channels(
      to_freeform: object,
      to_sequence_pair: object,
      trace_queue: object,
  ) -> None:
      """Pool initializer.  One function because an executor takes exactly one.

      Either half may be a no-op: sharing off passes both race ends as None,
      trace off passes the trace queue as None, and the child then installs
      nothing rather than an empty channel that would look installed.
      """
      if to_freeform is not None and to_sequence_pair is not None:
          _install_race_channels(to_freeform, to_sequence_pair)
      install_trace_channel(trace_queue)
  ```
- `_build_layout` (`:424-451`) gains `observer: SearchObserver | None = None` and
  passes `observer=observer` to both constructors.
- `_run_race_leg` (`:469`), beside the existing `channels` line at `:479`:
  ```python
      trace = trace_channel() if request.trace else None
      observer = (
          None
          if trace is None
          else SampledObserver(sink=trace.offer, min_interval_s=0.5)
      )
  ```
  `0.5` and not `0.25` in a child: the frame is pickled by the queue's feeder
  thread, and that thread's CPU is the child's. Pass `observer=observer` into
  `_build_layout`, add `trace_dropped=0 if trace is None else trace.dropped` to
  the `_StrategyRaceOutcome`, and call `trace.close()` alongside
  `channels.close()` in the leg's teardown.
- `_pool_submit` (`:649-678`) takes `trace_queue: object | None = None`. The
  executor is built with `initializer=_install_child_channels` and
  `initargs=(freeform_end, sequence_end, trace_queue)` whenever *either* sharing
  or trace is on; when both are off, the no-initializer branch at `:669-674`
  stays exactly as it is.
- `run_strategy_race` (`:681-696`) takes `trace_queue: object | None = None` and
  passes it to `_pool_submit` and `trace=trace_queue is not None` into each
  `_StrategyRaceRequest`.

In `src/flab2bp/pipeline.py`, `_run_race` (`:863-889`) passes
`trace_queue=trace_queue` where `trace_queue` is a `build`-scope local created
once when `search_observer is not None and race`:

```python
    trace_queue = None
    if search_observer is not None and strategy_race_parallelism:
        trace_queue = multiprocessing.get_context("spawn").Queue(
            maxsize=strategy_race.TRACE_QUEUE_MAXSIZE
        )
```

and the settlement loop drains it into `search_observer` after each race:

```python
            for event in observe_channel.drain_trace(trace_queue):
                if search_observer.due(event.phase):
                    search_observer.note(event)
```

In `src/flab2bp/web/trace.py`, `TraceCollector` gains an optional
`queue: object | None = None`; `_run` drains the queue with `drain_trace` in the
same loop iteration as the deque, so an in-process and a cross-process source
land in one ordered ring.

In `web/src/ui/TracePanel.tsx`, group `frames` by `frame.strategy` and render one
lane per group on a shared `t` axis, each frame a tick coloured by phase with
incumbents drawn taller. Clicking a tick loads that frame and turns the tail off.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/layout/test_strategy_race.py -q; echo $?` then
`cd web && bun run test`
Expected: `0`, and the web suite passes.

- [ ] **Step 5: Commit**

```bash
git add src/flab2bp/layout/strategy_race.py src/flab2bp/pipeline.py src/flab2bp/web/trace.py \
        web/src/ui/TracePanel.tsx tests/layout/test_strategy_race.py web/tests/ui/TracePanel.test.tsx
git commit -m "feat(race): carry trace events from both arms to the parent

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014jHGF2vGRJ5KDBB3JevhQb"
```

---

### Task 9: Hierarchical — block rounds and composition

> **Gate:** this task applies to branch `hierarchical-v1` and lands only once that
> branch has merged. If it has not, skip to Task 10 and return here afterwards.

**Files:**
- Modify: `src/flab2bp/layout/hierarchy/strategy.py:263-286` (`__init__`), `:288-299` (`lay_out`), `:460-519` (`_solve_round`), `:522-543` (`_recut`)
- Modify: `web/src/ui/TracePanel.tsx` (round × block grid)
- Test: `tests/layout/hierarchy/test_strategy.py` (append), `web/tests/ui/TracePanel.test.tsx` (append)

**Interfaces:**
- Consumes: `SearchObserver`, `SearchEvent`, `SearchPhase` (Task 1).
- Produces: `HierarchicalLayout(..., observer: SearchObserver | None = None)`; frames with `strategy == "hierarchical"` and `phase` in `{block, recut, composed}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/layout/hierarchy/test_strategy.py  (append)
from flab2bp.layout.observe import SearchEvent, SearchPhase


class _RecordingObserver:
    def __init__(self) -> None:
        self.events: list[SearchEvent] = []

    def due(self, phase: SearchPhase, /) -> bool:
        return True

    def note(self, event: SearchEvent, /) -> None:
        self.events.append(event)


def test_every_block_of_every_round_is_reported(small_spec, fake_block_pool) -> None:
    observer = _RecordingObserver()
    layout = HierarchicalLayout(
        belt_vertical_construction=True,
        band_policy=BandPolicy.parse("portable"),
        observer=observer,
    )
    layout._executor_factory = fake_block_pool
    layout.lay_out(small_spec, time_budget_s=5.0)

    blocks = [e for e in observer.events if e.phase is SearchPhase.BLOCK]
    assert blocks
    # Block placements already come back to the parent (strategy.py:492,
    # 514-519), so hierarchical needs no new IPC at all.
    assert all(e.strategy == "hierarchical" for e in blocks)
    assert all(e.round_index is not None and e.block is not None for e in blocks)
    assert any(e.placement is not None for e in blocks)
    assert any(e.reason is not None for e in blocks), "a verdict travels with a block"


def test_composition_is_reported_once_with_the_composed_canvas(
    small_spec, fake_block_pool
) -> None:
    observer = _RecordingObserver()
    layout = HierarchicalLayout(
        belt_vertical_construction=True,
        band_policy=BandPolicy.parse("portable"),
        observer=observer,
    )
    layout._executor_factory = fake_block_pool
    composed = layout.lay_out(small_spec, time_budget_s=5.0)

    events = [e for e in observer.events if e.phase is SearchPhase.COMPOSED]
    assert len(events) == 1
    assert events[0].placement is composed
    assert events[0].area == composed.area


def test_a_recut_is_reported_with_the_block_it_split(small_spec, refusing_block_pool) -> None:
    observer = _RecordingObserver()
    layout = HierarchicalLayout(
        belt_vertical_construction=True,
        band_policy=BandPolicy.parse("portable"),
        observer=observer,
    )
    layout._executor_factory = refusing_block_pool
    with pytest.raises(NoValidLayout):
        layout.lay_out(small_spec, time_budget_s=5.0)
    recuts = [e for e in observer.events if e.phase is SearchPhase.RECUT]
    assert recuts
    assert all(e.block is not None for e in recuts)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/layout/hierarchy/test_strategy.py -k observer -x -q`
Expected: FAIL — `TypeError: HierarchicalLayout.__init__() got an unexpected keyword argument 'observer'`

- [ ] **Step 3: Write minimal implementation**

`HierarchicalLayout.__init__` (`strategy.py:268-286`) gains
`observer: SearchObserver | None = None` and `self.observer = observer`.

`_solve_round` (`strategy.py:460-519`) gains a `round_index: int` parameter and,
inside the per-block loop at `:512-519`, after `entries[index].verdicts` is set:

```python
            if self.observer is not None and self.observer.due(SearchPhase.BLOCK):
                for (record, placement), arm in zip(outcomes, arms, strict=True):
                    self.observer.note(
                        SearchEvent(
                            strategy="hierarchical",
                            candidate=spec.label,
                            phase=SearchPhase.BLOCK,
                            placement=placement,
                            round_index=round_index,
                            block=index,
                            area=None if placement is None else placement.area,
                            reason=f"{arm}: {record.get('verdict', 'no verdict')}",
                        )
                    )
```

`_recut` (`strategy.py:522-543`) becomes a method or takes the observer, and per
split entry:

```python
        if observer is not None and observer.due(SearchPhase.RECUT):
            observer.note(
                SearchEvent(
                    strategy="hierarchical",
                    candidate=spec.label,
                    phase=SearchPhase.RECUT,
                    round_index=round_index,
                    block=index,
                    reason=f"split into {len(children)} block(s) after {entry.attempts} attempt(s)",
                )
            )
```

In `lay_out` (`strategy.py:288-299`), after composition returns the canvas:

```python
        if self.observer is not None and self.observer.due(SearchPhase.COMPOSED):
            self.observer.note(
                SearchEvent(
                    strategy="hierarchical",
                    candidate=spec.label,
                    phase=SearchPhase.COMPOSED,
                    placement=composed,
                    round_index=round_index,
                    area=composed.area,
                )
            )
```

`_solve_block` (`strategy.py:186-245`) runs in a spawned child and is **not**
given an observer: everything the trace needs — the block placement and the
verdict — comes back to the parent already (`:492`, `:514-519`).

In `web/src/ui/TracePanel.tsx`, when `frames.some(f => f.strategy === 'hierarchical')`,
render a round × block grid instead of the strategy lanes: rows are `round`,
columns are `block`, each cell shows the block's area and verdict and selects
that block's frame. `composed` frames get their own row beneath.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/layout/hierarchy -q; echo $?` then `cd web && bun run test`
Expected: `0`, and the web suite passes.

- [ ] **Step 5: Commit**

```bash
git add src/flab2bp/layout/hierarchy/strategy.py web/src/ui/TracePanel.tsx \
        tests/layout/hierarchy/test_strategy.py web/tests/ui/TracePanel.test.tsx
git commit -m "feat(hierarchy): report block rounds, re-cuts and composition

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014jHGF2vGRJ5KDBB3JevhQb"
```

---

### Task 10: Overlays — stranded nets and no-goods

**Files:**
- Create: `web/src/scene/TraceOverlay.tsx`
- Modify: `web/src/scene/BlueprintCanvas.tsx`, `web/src/ui/TracePanel.tsx`
- Modify: `src/flab2bp/layout/sequence_solver.py` (populate `stranded` from `StageObservation`), `src/flab2bp/layout/freeform.py` (populate `no_goods`)
- Test: `web/tests/scene/TraceOverlay.test.tsx`, `tests/layout/test_observe.py` (append)

**Interfaces:**
- Consumes: `TraceFrame.stranded`, `TraceFrame.no_goods` (Task 5); `SceneModel` (`web/src/model/layout.ts:26-35`).
- Produces: `<TraceOverlay frame={TraceFrame | null} show={{stranded: boolean, noGoods: boolean}} />`.

- [ ] **Step 1: Write the failing test**

```tsx
// web/tests/scene/TraceOverlay.test.tsx
import { expect, test } from '@rstest/core';
import { overlayGeometry } from '../../src/scene/TraceOverlay';

const frame = {
  /* … a TraceFrame with stranded: [[0,0,4,4],[1,1,2,6]] and no_goods: [[3,7]] … */
} as const;

test('each stranded net becomes one segment in world coordinates', () => {
  const { segments } = overlayGeometry(frame, { stranded: true, noGoods: false });
  // World mapping is (bp.x, bp.z, -bp.y), exactly as buildSceneModel has it
  // (model/layout.ts:39-43); an overlay drawn in a different frame would sit
  // beside the buildings it is meant to indict.
  expect(segments).toHaveLength(2);
  expect(segments[0]).toEqual([0, 0.5, -0, 4, 0.5, -4]);
});

test('a hidden layer contributes nothing', () => {
  const { segments, cells } = overlayGeometry(frame, { stranded: false, noGoods: false });
  expect(segments).toHaveLength(0);
  expect(cells).toHaveLength(0);
});

test('a no-good names the strips it forbids', () => {
  const { cells } = overlayGeometry(frame, { stranded: false, noGoods: true });
  expect(cells).toHaveLength(2);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && bun run test -- TraceOverlay`
Expected: FAIL — cannot resolve `../../src/scene/TraceOverlay`.

- [ ] **Step 3: Write minimal implementation**

`web/src/scene/TraceOverlay.tsx` exports a pure `overlayGeometry(frame, show)`
(so it is testable without a renderer) plus the component that feeds its output
to a `<lineSegments>` and an instanced tinted `<boxGeometry>`. World mapping is
`(bp.x, bp.z, -bp.y)` (`web/src/model/layout.ts:39-43`); segments float at
`y = 0.5`.

Mount it inside `BlueprintCanvas` and add two layer toggles to `TracePanel`.

Populate the data:

- `sequence_solver.py`: the `ROUTED` event's `stranded=` comes from the stage's
  own stranded set (`StageObservation.stranded`, `sequence_solver.py:827`)
  resolved to endpoint cells through the prepared net table.
- `freeform.py`: the `ROUTED` event gains
  `no_goods=tuple(tuple(ng.instance_ids) for ng in <the round's cluster no-goods>)`,
  sourced from `route_feedback.ClusterRelationNoGood` (`route_feedback.py:154`).
  Emitting these is what makes the search's *learned state* visible, which
  nothing else in the product surfaces.

Add to `tests/layout/test_observe.py`:

```python
def test_overlay_payloads_are_tuples_so_an_event_stays_hashable() -> None:
    event = SearchEvent(
        strategy="freeform",
        candidate="c",
        phase=SearchPhase.ROUTED,
        stranded=((0, 0, 4, 4),),
        no_goods=((3, 7),),
    )
    assert isinstance(event.stranded, tuple)
    assert isinstance(event.no_goods, tuple)
    hash(event)  # frozen + slots + tuples: an event can key a set.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd web && bun run test && bun run typecheck` then
`uv run pytest tests/layout/test_observe.py -q; echo $?`
Expected: web suite passes; `0`.

- [ ] **Step 5: Commit**

```bash
git add web/src/scene/TraceOverlay.tsx web/src/scene/BlueprintCanvas.tsx web/src/ui/TracePanel.tsx \
        src/flab2bp/layout/sequence_solver.py src/flab2bp/layout/freeform.py \
        web/tests/scene/TraceOverlay.test.tsx tests/layout/test_observe.py
git commit -m "feat(trace): overlay stranded nets and proved no-goods

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014jHGF2vGRJ5KDBB3JevhQb"
```

---

### Task 11: Timeline polish — scrubber, lanes, metadata

**Files:**
- Modify: `web/src/ui/TracePanel.tsx`, `web/src/ui/app.css`
- Test: `web/tests/ui/TracePanel.test.tsx` (append)

**Interfaces:**
- Consumes: everything from Tasks 5, 8, 9, 10.
- Produces: no new exports; `TracePanel` gains scrubber, tail toggle, keyboard stepping, drop reporting, and the metadata table.

- [ ] **Step 1: Write the failing test**

```tsx
// web/tests/ui/TracePanel.test.tsx  (append)
test('scrubbing turns the live tail off and loads the scrubbed frame', async () => {
  const loaded: string[] = [];
  render(<Harness frames={threeFrames} onLoadSnapshot={(_bp, label) => loaded.push(label)} />);
  expect(screen.getByRole('checkbox', { name: /live tail/i })).toBeChecked();

  fireEvent.change(screen.getByRole('slider', { name: /snapshot/i }), { target: { value: '0' } });
  expect(screen.getByRole('checkbox', { name: /live tail/i })).not.toBeChecked();
  expect(loaded.at(-1)).toContain('TRACE · freeform');
});

test('arrow keys step one frame at a time', () => {
  render(<Harness frames={threeFrames} />);
  const slider = screen.getByRole('slider', { name: /snapshot/i });
  fireEvent.keyDown(slider, { key: 'ArrowLeft' });
  expect(slider).toHaveValue('1');
});

test('dropped frames are stated rather than hidden', () => {
  render(<Harness frames={threeFrames} dropped={7} />);
  // A gappy timeline that does not say it is gappy reads as a search that
  // stalled, which is a different bug from the one that happened.
  expect(screen.getByText(/7 snapshot\(s\) dropped/i)).toBeInTheDocument();
});

test('the metadata table names every field the frame carries', () => {
  render(<Harness frames={threeFrames} />);
  for (const label of ['strategy', 'candidate', 'phase', 'height', 'area', 'belt tiles']) {
    expect(screen.getByText(new RegExp(label, 'i'))).toBeInTheDocument();
  }
});

test('a truncated frame says so', () => {
  render(<Harness frames={[{ ...threeFrames[0], truncated: true }]} />);
  expect(screen.getByText(/sampled/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd web && bun run test -- TracePanel`
Expected: FAIL — no slider with an accessible name `snapshot`.

- [ ] **Step 3: Write minimal implementation**

Extend `TracePanel`:

- `<input type="range" aria-label="Snapshot" min={0} max={frames.length - 1} />`,
  whose `onChange` sets `tailing` false and loads `frames[value]`.
- `onKeyDown` handling `ArrowLeft` / `ArrowRight` for one-frame steps and
  `Home` / `End` for the ends.
- A `Live tail` checkbox, checked by default, which on re-check jumps to the
  newest frame.
- The strategy lanes from Task 8 and the round × block grid from Task 9 sharing
  the scrubber's selection.
- A metadata table listing strategy, candidate, phase, height, arrangement,
  restart, stage, island, round, block, area, belt tiles, incumbent, reason,
  and the routed/stranded counts.
- `{dropped > 0 && <p>{dropped} snapshot(s) dropped — the search outran the viewer.</p>}`
- `{frame.truncated && <p>Buildings sampled: this placement is over the frame cap.</p>}`

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd web && bun run test && bun run lint && bun run typecheck`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add web/src/ui/TracePanel.tsx web/src/ui/app.css web/tests/ui/TracePanel.test.tsx
git commit -m "feat(trace): scrubber, lanes and per-snapshot metadata

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014jHGF2vGRJ5KDBB3JevhQb"
```

---

### Task 12: The overhead gate

> **Coordinate with the user before running this task.** It is the only task that
> runs real solves, and other agents may be measuring on this box.

**Files:**
- Create: `scripts/trace_overhead.py`
- Test: `tests/scripts/test_trace_overhead.py`
- Create: `docs/superpowers/evidence/2026-09-06-search-trace/` (results)

**Interfaces:**
- Consumes: `pipeline.build(..., search_observer=)` (Task 3); `SampledObserver` (Task 1); `flab2bp.bench.corpus.URL_CORPUS` (`bench/corpus.py:59`).
- Produces: `CELLS: dict[str, Cell]` with keys `um60`, `qc180`, `belt3`; `purity(cell) -> PurityResult`; `wall(cell, repeat) -> WallResult`; `verdict(results) -> bool`.

- [ ] **Step 1: Write the failing test**

```python
# tests/scripts/test_trace_overhead.py
import pytest

from scripts.trace_overhead import CELLS, WallResult, wall_verdict


def test_the_three_named_cells_exist_with_their_budgets() -> None:
    assert set(CELLS) == {"um60", "qc180", "belt3"}
    assert CELLS["um60"].entry_id == "universe-matrix"
    assert CELLS["um60"].budget_s == 60.0
    assert CELLS["qc180"].entry_id == "quantum-chip"
    assert CELLS["qc180"].budget_s == 180.0
    assert CELLS["belt3"].budget_s == 60.0


def test_wall_verdict_passes_at_exactly_one_percent() -> None:
    result = WallResult(cell="um60", off_s=[100.0] * 5, on_s=[101.0] * 5)
    assert wall_verdict(result) == "PASS"


def test_wall_verdict_fails_above_one_percent() -> None:
    result = WallResult(cell="um60", off_s=[100.0] * 5, on_s=[101.5] * 5)
    assert wall_verdict(result) == "FAIL"


def test_overlapping_spreads_are_reported_as_not_separated_and_are_a_fail() -> None:
    # A verdict whose spreads straddle the 1% line has not measured anything.
    result = WallResult(cell="um60", off_s=[90.0, 110.0], on_s=[91.0, 111.0])
    assert wall_verdict(result) == "NOT SEPARATED"


def test_purity_compares_area_belt_tiles_and_the_refusal_ledger() -> None:
    from scripts.trace_overhead import purity_verdict

    off = {"attempts": [("all-products", "freeform", 2244, 611)], "refused": []}
    on = {"attempts": [("all-products", "freeform", 2244, 611)], "refused": []}
    assert purity_verdict(off, on) == "PASS"
    on_bad = {"attempts": [("all-products", "freeform", 2246, 611)], "refused": []}
    assert purity_verdict(off, on_bad) == "FAIL"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/scripts/test_trace_overhead.py -x -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.trace_overhead'`

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/trace_overhead.py
"""Does trace cost more than 1 % of a build's wall?  Two rules, because one lies.

CP-SAT is nondeterministic under multi-worker, which is the shipping default
(see ab_compare.py:33-36).  "Area byte-identical" therefore cannot be asserted
across independent runs of the shipping configuration, and a gate that asserts
it anyway fails for reasons that have nothing to do with trace.  So:

    RULE P (purity), DETERMINISTIC configuration -- pinned workers, fixed seed,
    islands=1, race off.  Every attempt's (area, belt_tiles) and the whole
    refusal ledger must be EQUAL with trace off and on.  This is the claim that
    the observer is observationally pure.

    RULE W (wall), SHIPPING configuration -- default workers, race on,
    --repeat 5, trace-off and trace-on back to back INSIDE each trial so box
    drift hits both equally.  PASS iff median(on) <= 1.01 * median(off), per
    cell, with both spreads printed.  Spreads that straddle the line are
    NOT SEPARATED, which is a fail: nothing was measured.

Not part of pytest, for the reason ab_compare.py:12-13 gives: a full sweep is
minutes of CP-SAT and the suite stays fast.

    uv run python scripts/trace_overhead.py --purity
    uv run python scripts/trace_overhead.py --wall --repeat 5
    uv run python scripts/trace_overhead.py --wall --cell um60

`vmstat` is captured beside every timing.  This box has 128 cores and is never
idle; the load is I/O wait, so a run is never postponed waiting for an idle
machine -- the contention is RECORDED instead.
"""
```

with:

- `@dataclass(frozen=True) class Cell: entry_id: str; budget_s: float` and
  `CELLS = {"um60": Cell("universe-matrix", 60.0), "qc180": Cell("quantum-chip", 180.0), "belt3": Cell(<the conveyor-belt-3 entry id>, 60.0)}`;
- `WallResult(cell, off_s, on_s)` with `median_off`, `median_on`, `ratio`;
- `wall_verdict(result) -> Literal["PASS", "FAIL", "NOT SEPARATED"]` — `PASS`
  when `median_on <= 1.01 * median_off` and the two ranges do not straddle it,
  `NOT SEPARATED` when they do, `FAIL` otherwise;
- `purity_verdict(off, on) -> Literal["PASS", "FAIL"]` on exact equality of the
  attempt tuples and the refusal ledger;
- a `_capture_vmstat()` that shells `vmstat 1 2` and records the second row
  beside each timing;
- markdown output to `docs/superpowers/evidence/2026-09-06-search-trace/`.

Add `tests/scripts/__init__.py` if it does not exist.

- [ ] **Step 4: Run the unit tests, then the gate**

Run: `uv run pytest tests/scripts/test_trace_overhead.py -q; echo $?`
Expected: `0`

Then, **after checking with the user that the box is free enough**:

```
uv run python scripts/trace_overhead.py --purity
uv run python scripts/trace_overhead.py --wall --repeat 5
```

Expected: Rule P `PASS` on all three cells; Rule W `PASS` on all three cells.
Any `FAIL` or `NOT SEPARATED` blocks the feature — the escalation is spec §3's
Architecture B, not a looser gate.

- [ ] **Step 5: Commit**

```bash
git add scripts/trace_overhead.py tests/scripts/ docs/superpowers/evidence/2026-09-06-search-trace/
git commit -m "test(trace): gate trace overhead at 1 % of wall with a purity check

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014jHGF2vGRJ5KDBB3JevhQb"
```

---

## Self-review

**Spec coverage.** §1 understanding → Tasks 1–12 collectively. §4 snapshot schema
→ Task 2 (server) and Task 5 (client). §5 observer protocol → Task 1; call sites
→ Tasks 3, 7, 9. §6 process boundary → Tasks 6, 8. §7 transport → Task 4;
viewer → Tasks 5, 10, 11. §8 overhead → Task 12. §9 risks: R1 → Task 12 Rule P;
R2 → Task 12 Rule W; R3 → Task 6 `TraceChannel.close`; R4 → Task 2 byte bound;
R5 → Task 5 `snapshotLabel`; R6 → Task 12. L1 → Task 7's island test. L2 → the
gate on Task 9. L3 → Task 11's caption.

**Gaps closed during review.** The spec's §10 open question 3 (a CLI
`--trace-jsonl`) has **no task**: it is deliberately out of scope and needs the
user's answer before it earns one. Open questions 1 and 2 are settled by the
plan's constants (0.25 / 0.5 s) and by Task 3 shipping `PACKED` behind the
sampler; both are cheap to revise after Task 12 produces a baseline.

**Type consistency.** `SearchObserver` / `SearchEvent` / `SearchPhase` are spelled
identically in Tasks 1, 3, 6, 7, 8, 9. The constructor keyword is `observer=`
everywhere in Python and the pipeline parameter is `search_observer=` everywhere
— that asymmetry is deliberate (`build` already distinguishes `on_progress` from
what a strategy takes) and is stated in Task 3. `TraceRing.since` returns
`(frames, next)` in Tasks 2, 4 and is consumed as such. `TRACE_BUILDING_FIELDS`
order is asserted in Task 2 and relied on in Task 5's `traceFrameToBlueprint`.
