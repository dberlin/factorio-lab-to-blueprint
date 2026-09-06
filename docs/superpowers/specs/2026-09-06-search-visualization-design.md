# Live search visualization — design

*2026-09-06. Branch `design-search-viz`, cut from master `d57bc7cd`. Docs only.*

> "It would be neat if the web UI and blueprint viewer could be used to visualize
> the search without slowing it down. That way you can see what is really
> happening a bit."

This document describes an opt-in **trace mode**: a build streams search
snapshots to the browser, and the existing three.js viewer plays them back with a
timeline scrubber and a live tail. It is a *debugging instrument*, not a product
feature, and the whole design is shaped by one constraint: **a build that has
trace on must run the same search, at the same speed, as one that does not.**

---

## 1. The system as it stands

Every line number below is `d57bc7cd` unless the file is named as being on
branch `hierarchical-v1`.

### 1.1 The web job model

A build is submit-and-poll. There is no push channel anywhere in the stack.

| Step | Where |
| --- | --- |
| `POST /api/build` → `parse_options` → `Builder.submit` → 202 with the job id | `src/flab2bp/web/server.py:177-189`, `src/flab2bp/web/jobs.py:180-309`, `jobs.py:402-408` |
| One `ThreadPoolExecutor` worker (default `workers=1`) runs `Builder._run` | `jobs.py:396`, `jobs.py:429-468` |
| `_run` calls `self._solve(job.options, note)`, i.e. `run_build` | `jobs.py:442`, `jobs.py:350-377` |
| `run_build` calls `pipeline.build(..., on_progress=note, race=strategy == "best")` | `jobs.py:364-377` |
| `note` is the progress sink: stores the latest `AttemptProgress` and appends every non-`started` one to `job.settled`, under `job._lock` | `jobs.py:434-440` |
| `GET /api/build/<id>` → `Builder.snapshot(job)` → the **whole job**, every poll | `server.py:205-213`, `jobs.py:470-519` |
| Response framing: whole body, `Content-Length`, gzip above 1 KiB, `Cache-Control: no-store` | `server.py:137-158` |
| Server is `ThreadingHTTPServer` with `daemon_threads`, HTTP/1.1 | `server.py:34`, `server.py:349-350` |

Client side:

| Step | Where |
| --- | --- |
| `submitBuild` → `pollBuild` in a loop until `isSettled` | `web/src/api/build.ts:326-344`, `:370-392` |
| Poll backoff 300 ms → 2000 ms, ×1.5 | `web/src/api/build.ts:346-348` |
| Every response parsed through zod, never cast | `web/src/api/build.ts:178-193` (`Job`), `:166-176` (`Step`) |
| `BuildPanel` drives it and calls `load(chosen.blueprint)` when it settles | `web/src/ui/BuildPanel.tsx:74`, `:81`, `:86` |

**There is no SSE and no websocket.** `Handler._send` (`server.py:137-158`) is a
whole-body writer: it computes a length, optionally gzips, and writes once.
Streaming would be a second, parallel write path.

### 1.2 What the viewer renders

The viewer's whole input is a base64 DSP blueprint string:

```
blueprint string
  → parseBlueprint            web/src/format/blueprint.ts
  → Blueprint { header, areas, buildings: BlueprintBuilding[] }
                              web/src/format/types.ts:25-69
  → buildSceneModel(bp, catalog)
                              web/src/model/layout.ts:44-167
  → SceneModel { instances, bounds, center, radius, beltRuns, beltHeadings, ... }
                              web/src/model/layout.ts:26-35
  → <BlueprintCanvas> / <BuildingInstances> / <BeltChevrons> / <IconInstances>
```

The load-bearing observation for this design: **`buildSceneModel` reads only
`bp.buildings`.** It touches `index`, `itemId`, `modelIndex`, `x`, `y`, `z`,
`yaw`, `recipeId`, `filterId`, `parameters` (`layout.ts:60-112`), and
`buildBeltRuns` / `beltSuccessors` additionally read the connection indices
(`layout.ts:114-119`). It never reads the header, the areas, the hash, or the
patch. A snapshot that supplies those per-building numbers can be rendered by the
existing pipeline with **no blueprint round trip at all** — no base64, no gzip, no
md5f.

State lives in `BlueprintProvider` (`web/src/state/BlueprintProvider.tsx:6-20`),
which already carries a `stale` flag whose entire job is to say "what is on the
canvas is not the outcome of the last build" (`:12-16`).

### 1.3 Where a placement becomes a blueprint

```
placement                                   pipeline.py:1023  finalize.compact_open_boundary_belts
  → finalize.finalize_placement             pipeline.py:1033
  → validate.certify / validate.validate    2–10 s per candidate on batch-3 cells
  → markers.mark_external_belts(placement, spec)   pipeline.py:1143, markers.py:96
  → codec.encode(labelled)                  pipeline.py:1155, dsp/codec.py:401-403
        → placement_to_blueprint            dsp/codec.py:267-283
        → encode_blueprint                  dsp/codec.py:135
```

Two facts that kill the obvious design:

1. `placement_to_blueprint` **asserts `placement.frame is not None`**
   (`dsp/codec.py:281`). A mid-search pack has no `AreaFrame` — the frame is set
   by `finalize` — so most of what is worth watching cannot be encoded at all.
2. `codec.encode` and `validate.certify` cost seconds on large placements. They
   are exactly the two things a trace must never touch.

### 1.4 Where the search produces state worth seeing

**Freeform** (`src/flab2bp/layout/freeform.py`, 22 044 lines):

- `FreeformLayout.__init__` already takes two portfolio hooks —
  `portfolio_incumbent: Callable[[], tuple[int, int] | None] | None` and
  `publish_incumbent: Callable[[Placement], None] | None` (`freeform.py:19419-19420`,
  documented at `:19446-19452`).
- The sweep runs over `(height, arrangement)` candidates. Each candidate is
  packed, routed, and keyed as `key = (placement.area, float(placement.stats["belt_tiles"]))`
  (`freeform.py:21607`).
- `_would_become_incumbent(key, best_key)` (`freeform.py:21781-21823`) gates
  certification; a skip bumps `certify_skipped` (`:21626`).
- `validate.certify` runs at `freeform.py:21633`.
- `publish_incumbent(placement)` fires at `freeform.py:21674-21675`, inside
  `if best_key is None or key < best_key` (`:21667`).
- Refusal reasons and route feedback no-goods live in
  `src/flab2bp/layout/route_feedback.py`: `DetailedRouteStatus.STRANDED`
  (`:81-83`), `NetFailure` (`:91`), `ClusterRelationNoGood` (`:154`),
  `DetailedRouteResult.stranded` (`:238-261`).

**Sequence-pair** (`src/flab2bp/layout/sequence_solver.py`, 6 782 lines):

- `SequencePairLayout.__init__` carries the same two hooks
  (`sequence_solver.py:6302-6303`), and the inner search takes
  `publish_incumbent` at `:1036`.
- `publish_incumbent(finalized)` fires at `sequence_solver.py:2528-2529`, guarded
  by `exact_key < self._incumbent.exact_key` (`:2520`).
- **`StageObservation`** (`sequence_solver.py:811-856`) is already a complete
  per-stage record: `height`, `restart`, `stage_index`, `seed`, `accepted_moves`,
  `anneal_stages`, `anneal_moves`, `global_routes`, `detailed_status`,
  `stranded`, `expansions`, `lns_size`, `exact_key`, `validation_failures`,
  `projection_failures`, `split_count`, `merge_count`, plus four timings.
  `SequenceSearchResult.stages` retains every one of them
  (`sequence_solver.py:882`).
- Islands: `run_sequence_islands` (`sequence_islands.py:272-283`) spawns a
  `ProcessPoolExecutor` with a `spawn` context (`:321-323`) **inside** whatever
  process the sequence-pair solve is already in.

**Racing** (`src/flab2bp/layout/strategy_race.py`):

- Both arms run in spawned children, `max_tasks_per_child=1`
  (`strategy_race.py:660-674`).
- The children already talk to each other over two bounded
  `multiprocessing.Queue`s, `maxsize = RACE_QUEUE_MAXSIZE = 64`
  (`:86`, `:730-731`), handed in through `initargs` because a queue cannot be
  pickled as a task argument (`:396-401`, `:404-417`, `:667`).
- `RaceChannels._put` **drops on `queue.Full` and counts the drop**
  (`:199-203`); `drain()` is bounded at `RACE_DRAIN_MAX_MESSAGES = 32` per poll
  (`:89`, `:211-227`); `close()` calls `cancel_join_thread()` so an unread queue
  cannot hold a child's exit (`:229-236`).
- `_build_layout` is where the child constructs its strategy and wires the two
  hooks (`:424-451`).
- **The child validates before it publishes.** `publish` in `_run_race_leg` runs
  a full `validate.validate` on every published incumbent
  (`strategy_race.py:515-530`), because a bound the parent would reject must not
  prune the other arm. *This is why trace must not reuse `publish_incumbent`.*
- The parent is **not** a consumer of either queue. Nothing today carries a
  message from a child to the parent except the `Future`'s result.

**Hierarchical** (branch `hierarchical-v1`,
`src/flab2bp/layout/hierarchy/strategy.py`, 576 lines):

- `HierarchicalLayout.lay_out` (`:288-299`) runs rounds.
- `_solve_round` (`:460-519`) builds one `_BlockJob` per (block × arm), runs
  `pool.map(_solve_block, jobs)` (`:492`), and **receives every block's
  `Placement` back in the parent** (`:514-519`), keeping `min(winners, key=area)`.
- `_Entry` (`:248-260`) holds `units`, `placement`, `verdicts`, `attempts`.
- `_recut` (`:522-543`) replaces refusing entries with children; `_next_cut`
  (`:544-558`) produces the cut.
- Composition lives in `src/flab2bp/layout/hierarchy/compose.py`.

Because block placements already cross back into the parent, hierarchical needs
**no new IPC at all** — its observer can live entirely on the parent side.

### 1.5 Cost constraints

- A build has a 1.00-core allowance for its whole budget; the pipeline divides a
  16-CPU ceiling across candidates and arms (`pipeline.py:596-605`,
  `jobs.py:1-17`).
- `Placement` is a frozen, slotted dataclass of frozen `PlacedBuilding`s
  (`base.py:423-459`, `:93-171`). Passing one around in-process is a pointer
  copy; there is nothing to defensively deep-copy.
- `validate.certify` costs 2–10 s per candidate on batch-3 evidence.
  `codec.encode` costs seconds on large placements.
- Both production strategies run their search in **spawned** children
  (`strategy_race.py:660`, `sequence_islands.py:321-323`), so any observer that
  wants to see the race must cross a process boundary. Freeform candidates share
  learned state (`route_feedback.FeedbackState`, the no-good inbox) — the
  observer must never write into it.

---

## 2. Goals and non-goals

### Goals

- **G1.** An opt-in `trace` flag on a build request that makes the job stream
  search snapshots the browser can render.
- **G2.** Snapshots rendered by the *existing* viewer: same catalog, same
  `buildSceneModel`, same instanced meshes.
- **G3.** Per-snapshot metadata visible in the UI: strategy, candidate, phase,
  height / arrangement / restart / stage / round / block, area, belt tiles,
  refusal reason, routed vs stranded nets, incumbent flag.
- **G4.** A timeline: scrub backwards through retained snapshots, or live-tail
  the newest.
- **G5.** Racing shown as two arms side by side on one time axis.
- **G6.** Hierarchical shown as block rounds plus a composed canvas — a distinct
  view, not a flattened stream.
- **G7.** Overhead under 1 % of wall on the hot path, default off, measured.

### Non-goals

- **N1.** A trace frame is **never pasteable**. It carries no blueprint string,
  makes no validity claim, and the UI labels it as a picture of a search state.
- **N2.** No persistence. Trace frames die with the job, exactly as the job dies
  with the server (`server.py:402-404`). Disk spill is listed as an extension.
- **N3.** No trace-driven control. The observer can never steer, pause, or cancel
  a search. It is read-only by construction (§5.4).
- **N4.** Not a replacement for `AttemptProgress`. The existing progress bar and
  `settled` list keep working byte-for-byte when trace is off.
- **N5.** v1 does not trace inside sequence-pair **islands** (a second spawn
  level). See §9, Limitation L1.

---

## 3. Architectures considered

### Architecture A — encode on a background thread, reuse `load()`

Hook `publish_incumbent`, hand the `Placement` to a background thread in the
parent, run `markers.mark_external_belts` + `codec.encode`, put the resulting
blueprint string on the job, and let the browser call the existing
`load(text)` path (`BlueprintProvider.tsx:40-50`).

*For:* zero viewer change, zero new client schema, and the string is
demonstrably the same artifact the result panel shows.

*Against, decisively:*

1. `placement_to_blueprint` asserts `frame is not None` (`dsp/codec.py:281`).
   Only certified, finalized placements have a frame. Every pack, every refused
   candidate, every mid-anneal state — the interesting majority — cannot be
   encoded.
2. `codec.encode` is seconds of pure-Python work. A "background thread" in the
   same interpreter contends for the GIL with the search that is trying to spend
   its one core.
3. In the raced configuration the placement is in a child; getting it to the
   parent needs the IPC of Architecture C anyway, and then encoding it there
   costs the parent seconds it is supposed to spend supervising.
4. It cannot express anything that is not a whole placement: no stranded nets,
   no no-goods, no block/round structure.

**Rejected.**

### Architecture B — a sidecar tracer process over shared memory

Search processes write fixed-width building records into a
`multiprocessing.shared_memory` ring; a dedicated tracer process maps it,
projects, serializes, and serves the browser.

*For:* the search core genuinely never serializes anything — a memcpy is all it
pays. Highest possible ceiling on snapshot rate.

*Against:*

1. It adds a **third** process-management layer on top of two that already exist
   (`strategy_race`'s pool, `sequence_islands`' pool). Lifetime, cleanup, and
   orphan handling for a process that outlives a build is real work with real
   failure modes, for a debugging view.
2. Placements are variable length. A fixed-width ring needs a max-buildings cap
   and a fallback path anyway, so the "just a memcpy" claim only holds for the
   common case — and the fallback is a serializer, which is Architecture C.
3. It duplicates a solved problem. `RaceChannels` (`strategy_race.py:187-236`) is
   a bounded, drop-counting, `cancel_join_thread`-aware channel that this repo
   already ships, tests (`tests/layout/test_strategy_race.py`) and trusts.
4. The web server would have to talk to it, which means a second transport into
   `flab2bp.web` for data the parent process could have handed over directly.

**Rejected as over-built.** Kept on file as the escalation if §8's gate ever
fails on serialization cost.

### Architecture C — observer protocol + a parent-drained bounded queue, snapshots as raw building rows *(chosen)*

Four separable pieces:

1. **A `SearchObserver` protocol** threaded exactly like `on_progress` is today
   (`pipeline.py:595` → `jobs.py:434-440`), with a cheap `due(phase)` gate so the
   hot path pays one attribute lookup and one float compare when a sample is not
   due.
2. **A two-stage ring.** Stage 1 is written by the search and holds *references*
   to already-immutable `SearchEvent`s (in-process: a `collections.deque`;
   cross-process: a bounded `multiprocessing.Queue`). Stage 2 is written by a
   dedicated `flab2bp-trace` daemon thread in the parent and holds **projected
   JSON**. Every walk over `placement.buildings` happens in stage 2, off the
   search's core.
3. **Transport by a second polled endpoint with a cursor**,
   `GET /api/build/<id>/trace?from=<seq>`, so the existing job poll's body and
   cadence are untouched.
4. **A viewer adapter** that turns a trace frame's building rows straight into
   the `Blueprint` shape `buildSceneModel` already consumes — no base64, no gzip,
   no md5f, no `parseBlueprint`.

### Why C

- It is the only one of the three that can show a **pack with no frame** and a
  **refusal**, which is most of what "see what is really happening" means.
- It reuses the one IPC pattern this codebase has already proved: a bounded queue
  through `initargs`, drop-on-full with a counter, `cancel_join_thread` on
  shutdown (`strategy_race.py:187-236`, `:396-421`, `:649-678`). No new process,
  no new lifetime.
- Every expensive transform — walking buildings, building JSON, gzipping —
  happens on the parent's side of the boundary, on a thread whose CPU is bounded
  by the sample rate rather than by the search.
- It is *additive*. With `trace=false` the only new work in the whole tree is
  `if observer is not None` at a handful of call sites, and the existing
  `/api/build/<id>` response is byte-identical.

---

## 4. The snapshot

### 4.1 What a snapshot is

**A snapshot is a lightweight placement encoding plus scalar metadata. It is
never a validated blueprint.** Concretely: an array of positional building rows,
a bounding box, and about fifteen numbers and strings.

Rationale, in one line each:

- Not a blueprint string, because `codec.encode` asserts a frame (`dsp/codec.py:281`)
  and costs seconds.
- Not a validated placement, because `validate.certify` costs 2–10 s and the
  point of a trace is to show the states that *fail* validation.
- Positional rows and not objects, because a 3 000-building placement is ~240 kB
  as `[[…],[…]]` and ~1.1 MB as `[{…},{…}]`; the existing gzip path
  (`server.py:143`) takes the former to ~30 kB.
- Rows carry the two connection indices so `buildBeltRuns`
  (`web/src/model/layout.ts:114`) works and belts get direction and chevrons for
  free.

### 4.2 Building row

```python
#: src/flab2bp/web/trace.py
TRACE_BUILDING_FIELDS: Final = (
    "item_id", "model_index", "x", "y", "z", "yaw",
    "recipe_id", "filter_id", "output_obj", "input_obj",
)
```

Ten numbers, in that order, per building. `z` is `float(b.z)` — a `Fraction` is
exact because occupancy is keyed on it (`base.py:121-124`), but a viewer draws
pixels, so the trace frame carries the float and says so. `output_obj` /
`input_obj` are `-1` when `None`, matching the DSP convention
(`dsp/codec.py:276-277`).

`index` is not carried: it is the row's array position, exactly as
`placement_to_blueprint` derives it (`dsp/codec.py:276`).

### 4.3 Wire schema

```jsonc
// GET /api/build/<id>/trace?from=<seq>
{
  "frames": [
    {
      "seq": 41,                       // strictly increasing per job
      "t": 3.812,                      // seconds since job.started_at
      "strategy": "freeform",          // freeform | sequence-pair | hierarchical
      "candidate": "all-products",     // BuildSpec.label
      "phase": "incumbent",            // see SearchPhase, §5.1
      "height": 34,
      "arrangement": 2,
      "restart": null,
      "stage": null,
      "island": null,
      "round": null,
      "block": null,
      "area": 2244,
      "belt_tiles": 611,
      "incumbent": true,
      "reason": null,                  // refusal text on phase == "refused"
      "bounds": [0, 0, 65, 33],        // Placement.bounds, base.py:444-451
      "buildings": [[2001, 35, 4, 0, 0.0, 0.0, 61, 0, -1, -1], /* … */],
      "truncated": false,              // true when over TRACE_MAX_BUILDINGS
      "stranded": [[4, 0, 61, 12], /* … */],   // net endpoint pairs, overlay
      "no_goods": [[3, 7], /* … */]            // strip-index tuples, overlay
    }
  ],
  "next": 42,        // pass back as ?from=
  "dropped": 3,      // frames the ring or a full queue discarded, cumulative
  "complete": false  // the job has settled and no further frames will appear
}
```

Every field is non-optional in the response; unknown values are `null`, exactly
as `_step` does today for `AttemptProgress` (`jobs.py:522-538`).

### 4.4 Overlays

Two overlays ride on the frame rather than in the building rows, because they are
not buildings and must be drawable separately:

- **`stranded`** — one `[x1, y1, x2, y2]` per net the detailed router could not
  wire, sourced from `DetailedRouteResult.stranded`
  (`route_feedback.py:238-261`) and, for sequence-pair, from
  `StageObservation.stranded` (`sequence_solver.py:827`). Drawn as red segments
  above the floor.
- **`no_goods`** — the strip index tuple from a `ClusterRelationNoGood`
  (`route_feedback.py:154`). Drawn as tinted footprints on the strips a proved
  no-good names. This is the "learned state" view: it is what the search *knows
  it cannot do*, which nothing else in the product surfaces.

### 4.5 Retention

Per job, in `TraceRing` (`src/flab2bp/web/trace.py`):

```python
TRACE_RING_FRAMES: Final = 256          # newest 256 frames
TRACE_RING_BYTES: Final = 32 * 1024 * 1024   # …or 32 MiB, whichever bites first
TRACE_MAX_BUILDINGS: Final = 6000       # above this, decimate and set truncated
TRACE_PAGE_FRAMES: Final = 8            # frames per trace poll response
```

Eviction is oldest-first on both bounds. A job evicted from `Builder._jobs`
(`jobs.py:423-427`, `HISTORY = 32` at `jobs.py:57`) takes its ring with it. Disk
spill is a deliberate non-goal (§2, N2); if it is ever wanted, it belongs in
`TraceRing` behind the same `since(cursor)` interface and nowhere else.

---

## 5. The observer

### 5.1 Vocabulary

New module `src/flab2bp/layout/observe.py`. It imports `Placement` from
`base` and nothing else from the layout tree, so both strategies and the
hierarchy package can import it without a cycle.

```python
class SearchPhase(StrEnum):
    PACKED    = "packed"      # a pack exists; no frame, no routing yet
    ROUTED    = "routed"      # routing settled (possibly with stranded nets)
    CERTIFIED = "certified"   # validate.certify ran and passed
    INCUMBENT = "incumbent"   # this placement became the arm's best
    REFUSED   = "refused"     # this candidate/height/block gave up, with a reason
    BLOCK     = "block"       # hierarchical: one block, one arm, one round
    RECUT     = "recut"       # hierarchical: a block was split
    COMPOSED  = "composed"    # hierarchical: blocks wired onto one canvas


#: Phases that are rare and load-bearing enough to bypass the sample gate.
ALWAYS_SAMPLE: Final[frozenset[SearchPhase]] = frozenset(
    {SearchPhase.INCUMBENT, SearchPhase.COMPOSED}
)


@dataclass(frozen=True, slots=True)
class SearchEvent:
    """One thing a search did, as an immutable reference to state it already holds.

    ``placement`` is a REFERENCE, never a copy: ``Placement`` and every
    ``PlacedBuilding`` in it are frozen (base.py:423, base.py:93), so holding one
    costs a pointer and can never be mutated out from under a reader.
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
```

### 5.2 The protocol

```python
class SearchObserver(Protocol):
    """Told what a search is doing.  Read-only, by construction.

    Two methods and not one so the SAMPLE DECISION can be made before the event
    is built: constructing a nineteen-field dataclass on every anneal move would
    be the very cost this exists to avoid.
    """

    def due(self, phase: SearchPhase, /) -> bool:
        """Would ``note`` do anything for this phase, right now?

        Must be O(1) and must not read anything the search reads.
        """
        ...

    def note(self, event: SearchEvent, /) -> None:
        """Record ``event``.  Must be O(1) and must never raise."""
        ...
```

### 5.3 The sampler

```python
@dataclass(slots=True)
class SampledObserver:
    """Rate-limits by wall time and hands survivors to a sink.

    ``sink`` is an O(1) enqueue: ``deque.append`` in-process, ``put_nowait`` on a
    bounded queue across a process boundary.  It must never block and never
    raise; a full queue drops and counts, exactly as ``RaceChannels._put`` does
    (strategy_race.py:199-203).
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
        self.sink(event)
```

Defaults: `min_interval_s = 0.25` in-process, `0.5` in a spawned child (§6.2).

### 5.4 The hot-path contract

Every call site reads exactly:

```python
if observer is not None and observer.due(SearchPhase.PACKED):
    observer.note(SearchEvent(
        strategy="freeform",
        candidate=spec.label,
        phase=SearchPhase.PACKED,
        placement=placement,
        height=height,
        arrangement=arrangement,
        area=placement.area,
        belt_tiles=int(placement.stats.get("belt_tiles", 0)),
    ))
```

With `observer is None` — the default and the shipping path — that is one
identity comparison. With an observer installed and no sample due, it is one
attribute lookup, one set membership test, one `time.monotonic()` and one float
compare. **Nothing** in the branch touches `placement.buildings`.

Four rules the reviewer enforces:

- **R1.** No observer call may appear inside a CP-SAT solution callback or any
  loop the solver drives. Call sites live at candidate, stage, round, and
  incumbent boundaries only.
- **R2.** No observer call may read, write, or key on any structure the search
  reads — no touching `FeedbackState`, the no-good inbox, or `best_key`.
- **R3.** `note` must never raise. A sink that could raise wraps its own body.
  (This is deliberately the opposite of `ProgressSink`'s contract at
  `pipeline.py:529-532`: a progress sink that raises is a caller bug worth
  surfacing; a *trace* sink that raises would kill a real build for a debugging
  view.)
- **R4.** `SearchEvent` construction happens **inside** the `due()` branch,
  never before it.

### 5.5 Why not reuse `publish_incumbent`

`FreeformLayout` and `SequencePairLayout` already accept
`publish_incumbent: Callable[[Placement], None] | None`
(`freeform.py:19420`, `sequence_solver.py:6303`), and it fires on exactly the
event a trace most wants. Reusing it is still wrong:

1. In the raced configuration the callback installed there runs a full
   `validate.validate` before publishing (`strategy_race.py:515-530`), because a
   bound the parent would reject must not prune the peer. Trace would inherit
   that cost.
2. It only ever fires on an improvement (`freeform.py:21667`,
   `sequence_solver.py:2520`). It cannot express `PACKED`, `ROUTED`, `REFUSED`,
   or anything hierarchical.
3. Overloading it would couple the portfolio bound's semantics to a debugging
   view — a change to one would silently change the other.

The observer is a **second, separate** parameter. Both hooks coexist.

### 5.6 Call sites

| Strategy | Phase | Site | Data available there |
| --- | --- | --- | --- |
| freeform | `PACKED` | after the pack, before routing, in the sweep body | height, arrangement, placement |
| freeform | `ROUTED` | after `route_seconds` is taken, before `freeform.py:21607` | + belt tiles, stranded nets |
| freeform | `CERTIFIED` | after `freeform.py:21633` | + `report.errors` |
| freeform | `INCUMBENT` | beside `freeform.py:21674` | + `key`, best so far |
| freeform | `REFUSED` | at the `_retain_refusal` sites (`freeform.py:21649-21651`) | reason, projection failures |
| sequence-pair | `ROUTED` | where a `StageObservation` is appended | height, restart, stage, stranded, exact key |
| sequence-pair | `INCUMBENT` | beside `sequence_solver.py:2528` | finalized placement, exact key |
| sequence-pair | `REFUSED` | on a `ValidationVerdict` failure | `validation_failures` |
| hierarchical | `BLOCK` | in `_solve_round` after `pool.map` (`strategy.py:512-519`) | round, block, arm, verdict, placement |
| hierarchical | `RECUT` | in `_recut` (`strategy.py:522`) | round, block, child count |
| hierarchical | `COMPOSED` | after composition in `lay_out` | the composed placement, cut lanes |

Sequence-pair's `ROUTED` is nearly free to populate: every field it needs is
already in the `StageObservation` the search builds anyway
(`sequence_solver.py:811-856`).

---

## 6. Crossing the process boundary

### 6.1 The mechanism

Modelled directly on `RaceChannels`. New in
`src/flab2bp/layout/observe_channel.py`:

```python
TRACE_QUEUE_MAXSIZE: Final = 64
TRACE_DRAIN_MAX_EVENTS: Final = 32


@dataclass
class TraceChannel:
    """A child's write end of the one child → parent trace queue."""

    publish: _MessageQueue          # the Protocol at strategy_race.py:122-132
    _dropped: int = field(default=0, init=False)

    @property
    def dropped(self) -> int: ...

    def offer(self, event: SearchEvent, /) -> None:
        """Enqueue, or drop and count.  Never blocks, never raises."""

    def close(self) -> None:
        """cancel_join_thread, so an unread queue cannot hold this child's exit."""


#: Set by the pool initializer in each child; None in the parent and when trace
#: is off.  A module global for the same reason `_RACE_CHANNELS` is one: a
#: multiprocessing.Queue reaches a child only through initargs
#: (strategy_race.py:396-401).
_TRACE_CHANNEL: TraceChannel | None = None


def install_trace_channel(queue: object) -> None: ...
def trace_channel() -> TraceChannel | None: ...


def drain_trace(queue: _MessageQueue) -> tuple[SearchEvent, ...]:
    """Parent side: take at most TRACE_DRAIN_MAX_EVENTS off the queue."""
```

Wiring: `strategy_race._pool_submit` (`strategy_race.py:649-678`) already builds
the executor with an `initializer` and `initargs` when sharing is on. The trace
queue is appended to `initargs` and the initializer becomes a small composite
that calls both `_install_race_channels` and `install_trace_channel`. When trace
is off, `initargs` is unchanged and the existing two branches at
`strategy_race.py:661-674` stay exactly as they are.

`_run_race_leg` (`strategy_race.py:469`) builds a `SampledObserver` whose sink is
`TraceChannel.offer` and passes it to `_build_layout`
(`strategy_race.py:424-451`), which passes it to the strategy constructor
alongside the existing two hooks.

### 6.2 Drop policy

Identical in spirit to the race's, and for the same reason
(`strategy_race.py:84-86`): a dropped frame costs a picture and never a result,
so a bound is strictly better than a block.

- `put_nowait` on a full queue → drop, increment `_dropped`.
- The child reports its final `dropped` in `_StrategyRaceOutcome`, so the UI can
  say "3 frames dropped" instead of quietly showing a gappy timeline.
- Stage 1 in-process is a `deque(maxlen=64)`; an append past the bound evicts the
  **oldest**, and the eviction is counted.
- Stage 2 (`TraceRing`) evicts oldest on both the frame and byte bound (§4.5),
  also counted. All three counters sum into the response's `dropped`.

Why drop the oldest in stage 1 but keep newest in the ring? Because stage 1 is a
hand-off — a backlog there means the trace thread is behind, and the *newest*
state is the one worth showing. Stage 2 is history — the scrubber wants a
contiguous recent window, which is what a `maxlen` deque gives.

### 6.3 The parent's trace thread

`Builder` gains one daemon thread per traced job, `thread_name_prefix="flab2bp-trace"`:

```
loop until job.done and both stage-1 sources are empty:
    events = drain(stage 1)          # deque.popleft ×N, or drain_trace(queue)
    for event in events:
        ring.append(frame_json(seq, at_s, event, dropped=...))
    sleep(TRACE_DRAIN_INTERVAL_S)    # 0.1
```

`frame_json` is the only place that walks `placement.buildings`. It runs here,
in the parent, on a thread that is asleep most of the time — never on the search.

This thread costs CPU that the build's 1.00-core allowance does not budget for.
That is precisely what §8's wall gate measures; it is not waved away.

### 6.4 Two spawn levels

`run_sequence_islands` (`sequence_islands.py:272`) spawns a *second* pool inside
the sequence-pair child. Passing the trace queue down a second level is
mechanically the same trick, but it doubles the surface for a queue that can hold
a child's exit open.

**v1 decision:** islands do not trace. The sequence-pair child emits its own
merge and incumbent events and the frame carries `"island": null`. The UI says
"island detail unavailable" rather than implying the merged result is one
island's search. Listed as Limitation L1 (§9) with the follow-on named.

---

## 7. Transport and the viewer

### 7.1 Transport: a second polled endpoint with a cursor

```
GET /api/build/<id>/trace?from=<seq>   →   { frames, next, dropped, complete }
```

Chosen over SSE and over a query parameter on the existing job poll.

**Why not SSE.**

1. `Handler._send` (`server.py:137-158`) computes a `Content-Length`, optionally
   gzips, and writes the whole body once. SSE needs chunked transfer and a second
   write path through the same handler.
2. An SSE connection pins a `ThreadingHTTPServer` thread for the life of a build
   — minutes — and an abandoned tab holds it until TCP notices.
3. The client already has a tested poll-with-backoff-and-abort loop
   (`web/src/api/build.ts:350-392`). SSE would need reconnection and
   `Last-Event-ID` handling to be no better than a cursor.
4. **A cursor is replayable.** Reopening the tab, or scrubbing backwards, re-reads
   the ring at any offset. An SSE stream cannot be rewound.

**Why not a parameter on `/api/build/<id>`.** That response is already the whole
job on every poll, `settled` included (`jobs.py:470-519`). Adding frames to it
couples the trace cadence (~4 Hz while live-tailing) to the job poll's backoff
(300 ms → 2 s, `build.ts:346-348`) and grows a body that is currently a few
hundred bytes. A separate endpoint keeps the existing contract **byte-identical
when trace is off**, which is the property that makes this feature safe to ship.

Cursor semantics: `from` is exclusive; `next` is the highest `seq` returned plus
one, or `from` unchanged when nothing is new. A `from` older than the ring's
oldest retained frame returns the oldest available and reports the gap in
`dropped`. `complete` goes true once the job has settled and the trace thread has
joined.

The response body is plain nested JSON and rides the existing gzip path
(`server.py:143`, `_compressible` at `:95-103`).

### 7.2 Request and job plumbing

- `Options` gains `trace: bool = False` (`jobs.py:60-84`), and `"trace"` joins
  the allowed key set at `jobs.py:195-206`. **Default off**, non-negotiable.
- `Job` gains `trace: TraceRing | None = None` (`jobs.py:312-337`).
- `Builder.snapshot` echoes `"trace": job.options.trace` inside `"options"`
  (`jobs.py:486-506`) so the client knows whether to start a trace poll.
- `run_build` builds the observer and passes it as
  `pipeline.build(..., search_observer=observer)` (`jobs.py:364-377`).
- `pipeline.build` gains `search_observer: SearchObserver | None = None`
  alongside `on_progress` (`pipeline.py:595`), threads it into `_new_layout`
  (`pipeline.py:200-224`) for the serial path and into
  `strategy_race.run_strategy_race` (`pipeline.py:875-888`,
  `strategy_race.py:681-696`) for the raced one.

### 7.3 Viewer

**Client schema** — `web/src/api/trace.ts`, zod, no React and no three.js so it
stays inside `web/tests/architecture.test.ts:40-47`:

```ts
export const TraceFrame = z.object({ /* §4.3, exactly */ });
export const TracePage  = z.object({
  frames: z.array(TraceFrame), next: z.number(),
  dropped: z.number(), complete: z.boolean(),
});
export type TraceFrame = z.infer<typeof TraceFrame>;
export async function pollTrace(id: string, from: number, signal?: AbortSignal): Promise<TracePage>;
```

**Adapter** — `web/src/model/traceScene.ts`:

```ts
export function traceFrameToBlueprint(frame: TraceFrame): Blueprint;
```

Synthesises a minimal header and one area, then maps each row to a
`BlueprintBuilding` (`web/src/format/types.ts:25-54`) with `index` = array
position and every unused connection field at `-1`. The result goes straight into
`buildSceneModel` (`web/src/model/layout.ts:44`). **No `parseBlueprint`, no
base64, no gzip, no md5f** — the frame never was a blueprint and is not made to
look like one.

Because the rows carry `output_obj` / `input_obj`, `buildBeltRuns`
(`layout.ts:114`) and `computeBeltHeadings` (`:119`) work unchanged: belts get
direction and chevrons.

**Provider** — `web/src/state/BlueprintProvider.tsx` gains:

```ts
loadSnapshot(bp: Blueprint, label: string): void;
snapshotLabel: string | null;   // null when what is shown is a real result
```

`loadSnapshot` sets the blueprint and the label and leaves `stale` alone; the
existing `stale` machinery (`BlueprintProvider.tsx:12-16`) plus a non-null
`snapshotLabel` is what stops a trace frame being mistaken for a result (N1).
The canvas caption reads e.g.
`TRACE · freeform · all-products · h=34 a=2 · packed · 2244 tiles · 611 belt`.

**Overlay** — `web/src/scene/TraceOverlay.tsx`, an instanced line segment set for
`stranded` and an instanced tinted box set for `no_goods`, mounted inside
`BlueprintCanvas` and toggled per layer.

**Timeline** — `web/src/ui/TracePanel.tsx`:

- a `<input type="range">` scrubber over the buffered frames, with keyboard
  stepping;
- a **live tail** toggle (default on) that pins the scrubber to the newest frame;
- one **lane per strategy** on a shared `t` axis, so a race reads as two rows —
  each frame a tick, coloured by phase, incumbents drawn taller;
- a **round × block grid** when `strategy === "hierarchical"`, each cell showing
  the block's area and verdict and selecting that block's frame (G6);
- a dropped-frame count, stated rather than hidden;
- the per-frame metadata table (G3).

Trace polling runs its own loop in `TracePanel` at a fixed 250 ms while live and
stops when `complete` is true — deliberately not the job poll's backoff, which
exists to keep a five-minute build from making 300 requests.

---

## 8. Overhead budget and how it is measured

### 8.1 Budget

| Path | Budget |
| --- | --- |
| Search hot path, trace **off** | one `is None` comparison per call site |
| Search hot path, trace **on**, sample not due | one attribute lookup + one set test + one `monotonic()` + one float compare |
| Search hot path, trace **on**, sample due | `SearchEvent` construction + one `deque.append` / `put_nowait` |
| Parent trace thread | walks `placement.buildings` at most `1 / min_interval_s` times per second per arm |
| **Whole build wall** | **≤ +1 %** |

### 8.2 Two rules, because one would be unfalsifiable

CP-SAT is nondeterministic under multi-worker, which is the shipping default
(`ab_compare.py:33-36`). "Area byte-identical" therefore cannot be asserted
across independent runs of the shipping configuration, and a gate that asserts it
anyway would fail for reasons that have nothing to do with trace. So the gate is
split:

**Rule P (purity), deterministic configuration.** Pinned `DETERMINISTIC_WORKERS`,
fixed seed, `sequence_islands=1`, `race=False`. For each cell, run trace-off and
trace-on and assert:

- every attempt's `(area, belt_tiles)` is **equal**;
- the `Build.refused` ledger — candidate, strategy, reason — is **equal**;
- `AttemptProgress` sequence is **equal**.

This is the claim that the observer is observationally pure (§5.4, R1–R4). Any
inequality is a hard fail.

**Rule W (wall), shipping configuration.** Default workers, `race=True`,
`--repeat 5`, trace-off and trace-on run **back-to-back within each trial** so
box drift hits both equally (the fairness discipline of `ab_compare.py:40-43`).
Per cell:

```
median(wall_on) <= 1.01 * median(wall_off)
```

and the spread of both is printed. A verdict whose spreads overlap the 1 % line
is reported as **not separated** and is a fail, not a pass.

### 8.3 Cells

| Id | Corpus entry | Budget | Why |
| --- | --- | --- | --- |
| `um60` | `universe-matrix` (`bench/corpus.py:146-147`) | 60 s | the largest routine cell; most buildings per frame |
| `qc180` | `quantum-chip` (`bench/corpus.py:139-140`) | 180 s | the longest run; most frames per build |
| `belt3` | a `conveyor-belt-3` entry (`bench/corpus.py:124`, `:132`) | 60 s | multibelt geometry, most belt tiles |

### 8.4 Harness

`scripts/trace_overhead.py`, outside pytest for the same reason
`ab_compare.py` is (`ab_compare.py:12-13`): a full sweep is minutes of CP-SAT and
the suite stays fast.

```
uv run python scripts/trace_overhead.py --purity            # Rule P, all cells
uv run python scripts/trace_overhead.py --wall --repeat 5   # Rule W, all cells
uv run python scripts/trace_overhead.py --wall --cell um60
```

It records `vmstat` alongside every timing. This box has 128 cores and is never
idle; the load is I/O wait, so a run is never postponed waiting for an idle
machine — the contention is *recorded* instead. Evidence lands in
`docs/superpowers/evidence/2026-09-06-search-trace/`.

Fast guards that *do* live in pytest, because they are microseconds:

- `tests/layout/test_observe.py` — `due()` is O(1); `note` never raises;
  `SearchEvent` holds the same `Placement` object it was given (no copy).
- `tests/web/test_trace.py` — ring eviction on both bounds, cursor semantics,
  drop accounting, `frame_json` row shape.
- `tests/web/test_server.py` — the trace endpoint, including 404 for an unknown
  job and an empty page for a job with trace off.

---

## 9. Risks and limitations

**R1 — sampling perturbs the search.** Any `time.monotonic()` inside a solver
loop could change scheduling. *Mitigation:* R1/R4 of §5.4 keep every call site at
a candidate/stage/round boundary, and Rule P (§8.2) is the falsification test.

**R2 — the child's pickle cost.** `put_nowait` on a `multiprocessing.Queue`
appends to an internal buffer and a **feeder thread** does the pickling, so the
search thread does not pay it — but the feeder thread's CPU is still the child's.
At `min_interval_s = 0.5` that is ≤ 2 pickles/s of a ~250 kB structure.
*Mitigation:* `TRACE_MAX_BUILDINGS` caps the payload; Rule W measures the rest.
If it fails, Architecture B is the escalation.

**R3 — a full queue holding a child's exit.** An unread `multiprocessing.Queue`
with buffered data blocks its process's exit. *Mitigation:* `TraceChannel.close`
calls `cancel_join_thread`, exactly as `RaceChannels.close` does
(`strategy_race.py:229-236`), and the parent's trace thread drains until the job
is done.

**R4 — memory.** 256 frames × 6 000 buildings × 10 numbers is ~120 MB of Python
floats if held as objects. *Mitigation:* the ring holds **projected JSON-ready
dicts**, not `Placement`s, and is bounded by `TRACE_RING_BYTES` as well as frame
count. A `SearchEvent`'s `Placement` reference is released as soon as
`frame_json` returns.

**R5 — a trace frame mistaken for a result.** *Mitigation:* N1 — no blueprint
string on the frame, `snapshotLabel` non-null while one is shown, and the
existing `stale` caption.

**R6 — the parent trace thread's CPU is unbudgeted.** Stated plainly rather than
assumed away; Rule W is the whole answer.

**L1 (limitation) — islands do not trace in v1** (§6.4). Frames carry
`"island": null`.

**L2 (limitation) — hierarchical is on a branch.** The hierarchical work in the
plan is written against `hierarchical-v1`'s
`src/flab2bp/layout/hierarchy/strategy.py` and is gated on that branch merging.

**L3 (limitation) — belt-run inference is weaker on a frame than on a
blueprint.** `inferCarried` (`web/src/model/layout.ts:115`) uses catalog data
that is present, but a mid-search placement has no external markers
(`markers.mark_external_belts` runs at `pipeline.py:1143`, after the search), so
endpoint icons will be sparser than on a finished blueprint. Correct, and worth
saying in the UI.

---

## 10. Open questions

1. **Default sample interval.** 250 ms in-process / 500 ms in a child is a
   guess sized to keep Rule W comfortable. Should the UI expose it (a "detail"
   slider that trades frames for the 1 % budget), or is a fixed, defensible
   number better?
2. **`PACKED` frames on freeform.** Emitting a frame *before* routing is the
   single most informative thing here — you see the pack the router then fails on
   — but it is also the highest-frequency site in the sweep. Ship it in v1 behind
   the sampler, or start with `ROUTED` and above and add `PACKED` once Rule W has
   a baseline?
3. **Trace in the CLI.** `pipeline.build` grows `search_observer`, so a
   `--trace-jsonl <path>` flag on the CLI is nearly free and would make the
   harness in §8 and offline analysis much easier. In scope for this plan, or a
   follow-on?
