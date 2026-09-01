# Evaluation Throughput Design

**Status:** Approved design; implementation not started
**Companion:** `docs/superpowers/specs/2026-09-01-zero-refusal-reliability-design.md`

## 1. Decision

Make one candidate evaluation cheap for both production strategies without
changing what any evaluation concludes. Two halves, both gated on the same
profiler and the same corpus audit:

1. **Preparation.** Stop repeating exact spherical-projection legality work:
   run the cheap reach filter before materializing splitter stacks in the
   coater junction-ban scan, share pure offset caches process-wide, share the
   staged-static cache across every candidate, height, and strategy that
   evaluates one spec in a process, drop a deep copy of frozen buildings, and
   generate strip families once per `lay_out` call.
2. **Routing.** Move the detailed A* inner loop and the relaxed global search
   into one Cython extension over the flat-integer grid they already use, with
   a Python fallback selected the way the sequence kernel selects its backend.
   Paths, expansion counts, and budget accounting are byte-identical to the
   Python implementation, proven by the existing replay digest.

Nothing in this design adds search behaviour, changes an objective, alters a
refusal reason, or retunes a budget. It exists so that the zero-refusal
reliability program can afford its stages, restarts, islands, ALNS moves, and
cuts inside a 30-second budget.

## 2. Evidence

All figures from `master` on 2026-09-01, powered emission, one cell, this
machine, so they are ratios to act on rather than constants to quote.

**Corpus at `scripts/audit.py`, both strategies, 36 specs each:**

| Budget | Freeform | SequencePair |
|---|---:|---:|
| 15 s | 32/36 | 31/36 |
| 30 s | 36/36 | 32/36 |
| 60 s | not run | 34/36 |

Every refusal but one is clock-bound. The largest cells are `universe-matrix`
(46 coarse strips, 70 to 73 nets, up to 331 machines) and
`quantum-chip/output-products` (37 strips, 66 nets).

**Where 15 seconds go on `universe-matrix/all-products`** (cProfile, one run,
cumulative seconds):

| Phase | Freeform | SequencePair |
|---|---:|---:|
| strip planning and variant generation | 2.9 (called twice) | inside 6.5 "planning" |
| compact CP-SAT seed | none | 4.3 |
| `_prepare_routing_problem`, one candidate | 9.9 | 8.4 |
| detailed A* | 1.4 (54 nets routed, then the clock expired) | 0.0 (never reached) |

Inside preparation on that cell: `_projected_coater_junction_bans_by_frame`
3.4 s, `_place_coaters` 2.3 s, `_prepared_junction_ban` 1.5 s with 15,885
`planet.collisions_at` calls, `_power_plan` 1.5 s,
`_staged_static_relation_projection_risks` 1.3 s. Underneath those:
129,412 `dataclasses.replace` calls, 63,298 `materialize_frame_building`
calls, 156,663 `obb_overlap` calls, 77,536 `planet.pose` calls.

**Where routing goes when it does run** (`scripts/route_profile.py
universe-matrix --budget 8`, wrapper tally, seconds are real): `_route_all`
4.84 s of 8.02 s wall; A* 4.66 s over 54 searches and 1,686,128 expansions,
361,816 expansions per second, 2.76 microseconds per expansion.

So on the cells that miss, one candidate costs 8 to 10 seconds before a single
belt is searched, and a routing pass costs seconds more. SequencePair gets one
stage per 15 seconds; Freeform routes one pack. Neither number moves with
smarter search until evaluation is cheap.

## 3. Goals

- One candidate preparation on `universe-matrix` at or under 1.0 s, measured by
  the profiler added in this design.
- One routing pass on the same cell at or under 0.2 s for the A* share.
- Corpus gate: `scripts/audit.py --budget 30 --jobs 16`, both strategies, three
  interleaved paired rounds against the committed baseline: 72/72 CLEAN in
  every round, INVALID 0, CRASH 0, wall p95 per cell at or under 30 s, and
  paired area over cells clean in both arms no worse than the baseline beyond
  the measured same-arm noise floor.
- Every prepared problem, path, expansion count, and refusal reason identical
  to the Python implementation on the same inputs.
- Deterministic for fixed seeds and deterministic budgets, as today.

## 4. Non-goals

- No change to the compact seed share, expansion budgets, stage caps, or
  restart schedules. Retuning belongs to the reliability program.
- No change to strip variants, pitches, junction geometry, coater seating
  rules, or power coverage rules.
- No new search operator, no-good, or acceptance rule.
- No cross-process or on-disk cache. Memo state lives in one process and dies
  with it.
- No Rust, C++, Numba, or JAX. Cython is the one compiled toolchain. A PyO3
  bake-off was considered and dropped: A* is under 1.5 s per candidate on the
  largest cells, so a second toolchain cannot move the gate.
- No change to CLI, web, or pipeline interfaces.

## 5. Architecture

### 5.1 Profiler split

`scripts/route_profile.py` gains per-phase seconds for one cell run under
either strategy: strip planning, variant generation, compact seed, each
preparation sub-phase (coater seating, coater junction bans by frame, splitter
junction ban, power plan, staged static risks, port access reservation), A*,
global search, commit, finalization, validation. The JSON schema is covered by
the existing profiler tests. Every later step of this design is accepted or
rejected on these fields, not on wall clock alone.

### 5.2 Preparation work removed

Four exact changes, in the order the profile ranks them:

1. **Coater junction bans by frame** (3.4 to 3.8 s). The scan materializes a
   whole splitter stack for every (cell, frame) pair before testing whether
   the cell is within reach of the coater. Every member of a stack shares its
   materialized x and y, so the reach test is evaluated once on the first
   member and the stack is materialized only when some projection state
   passes it. The rejected pairs produced no ban before; they still produce
   none.
2. **Junction ban offsets** (1.5 s). The cancellable offset computation
   stores only into an attempt-local dict while the uncancellable one uses a
   process-wide LRU. Both consult and fill one process-wide dict keyed by
   the immutable obstacle pose, so a set proved once is never re-derived.
3. **Spec-scoped staged-static cache.** `_StagedStaticCache` is already
   attempt-local per `lay_out`; `geometry_memo.for_spec(spec)` hands out one
   per spec object for the life of the process, bounded to a few specs, so
   the second strategy in a `best` build and later `lay_out` calls reuse it.
   It gains a `stats()` method reporting entries per table.
4. **Building templates** (0.4 s). `_prepare_routing_problem` deep-copies a
   list of frozen `PlacedBuilding` instances; a tuple of the same instances
   is equivalent.

Batching frame materialization and OBB overlap with NumPy is the next lever
if the profiler still shows the coater scan above 1.0 s after change 1, and
memoizing the power-plan peer condition is the lever after that if it shows
above 0.5 s; both are written as follow-up tasks from the measured phase
table rather than guessed at here.

Invariants: every change stores or skips outputs of pure functions only.
Iteration order, tie-breaking, first failure selection, failure evidence
text, and `preparation_failures` content are unchanged. Parity tests build
the prepared problem with and without each change on representative corpus
specs in the suite, and a script does the same for every corpus spec at the
gate.

### 5.3 Planning reuse

`FreeformLayout.lay_out` calls `plan_strips` and `generate_strip_families`
twice per call on the largest cells. Both become once-per-call, keyed by spec
identity and band policy, inside the strategy object. SequencePair's planning
shares the same functions and benefits without a second change.

### 5.4 Routing kernel

`src/flab2bp/layout/_route_kernel.pyx`, built by `setup.py` beside
`_sequence_kernel.pyx`, exports two functions over the existing flat grid:

- `astar_flat(...)`: the loop of `freeform._astar` from the first heap push to
  the return, over typed memoryviews of `flags`, `hist`, landmark fields, the
  goal-flag bytearray, move and ramp tables, tolls, `pressure`, the expansion
  cap, the shared budget, the deadline check cadence, and a monotonic deadline.
  Returns the path as cell indices plus the `via` cells, the expansion count,
  the exit kind, and the settled `best` array for the sealed-pocket case.
- `relaxed_search_flat(...)`: the loop of `global_router._search_relaxed` over
  the same grid with the capacity ledger's present cost and the feedback net
  weight folded in as arrays.

The heap orders on `(f, g, index)` exactly as `heapq` does today, with the
same float association order for costs, so ties fall identically. Heuristic
caching by column, single-goal and bounded-goal branches, and landmark bands
are reproduced, not approximated.

The Python `_astar` and `_search_relaxed` become wrappers: build arrays, call
the kernel, and keep blame-wall and pocket post-processing, owner attribution,
and result construction in Python. Backend selection mirrors
`sequence_kernel.build_sequence_kernel`: compiled when importable and its
fixed-width domain is exact, Python otherwise; the chosen backend is recorded
in stage telemetry as it is for the sequence kernel.

Parity: `scripts/route_bench.py --check` digests must be identical on captured
cases from `universe-matrix`, `quantum-chip`, and `plastic`, and a property
test compares kernel and Python paths and expansion counts on random small
grids with random history, landmarks, ramps, budgets, and deadlines.

### 5.5 Budget policy

Unchanged. The compact seed keeps its wall share, expansion budgets keep their
values, and the deadline is polled at the same checkpoints inside the kernel.
The gain is that the same budgets buy many more stages and packs.

## 6. Interfaces

Unchanged public surface: `FreeformLayout`, `SequencePairLayout`,
`pipeline.build`, CLI, web, `scripts/audit.py`.

Internal additions:

```python
# flab2bp.layout.geometry_memo
MEMO_SPECS_RETAINED: int
def for_spec(spec: BuildSpec) -> _StagedStaticCache: ...
def stats_for_spec(spec: BuildSpec) -> MemoStats: ...
def clear() -> None: ...

# flab2bp.layout.freeform
_JUNCTION_BAN_OFFSET_CACHE: dict[JunctionOffsetKey, frozenset[Cell]]
class _StagedStaticCache:
    def stats(self) -> MemoStats: ...
def _astar_python_loop(...) -> tuple[list[int] | None, int, int, list[int]]: ...

# flab2bp.layout._route_kernel (Cython)
def astar_flat(...) -> tuple[array[int] | None, int, int, array[int], int]: ...
def relaxed_search_flat(...) -> tuple[array[int] | None, int, bool, bool]: ...

# flab2bp.layout.route_kernel
def compiled_available() -> bool: ...
def selected_backend() -> Literal["python", "cython"]: ...
```

`_prepare_routing_problem` keeps its existing `staged_static_cache` keyword;
`None` still builds a private cache so every existing caller and test keeps
its behaviour. `FLAB2BP_ROUTE_KERNEL=python` forces the Python loops for
parity runs. Placement stats carry `route_backend`.

## 7. Failure handling

- A memo hit and a memo miss are indistinguishable to callers; refusal reasons
  and evidence are computed from the same values either way.
- Deadline expiry inside the kernel reports `RouteFailureKind.BUDGET` at the
  same expansion checkpoints as today and writes back the shared budget with
  the same off-by-one rules.
- If the extension fails to import, the Python path runs and every test and
  the audit still pass; only the profiler numbers differ. CI builds the
  extension so parity tests always exercise it.
- Memo eviction cannot change a result, only cost; a full table is a
  performance observation reported by `stats()`, never a failure.

## 8. Testing

- Profiler: schema tests for the new fields; a smoke run on one small spec.
- Preparation: parity with and without each change on representative corpus
  specs in the suite; a script proving parity on every corpus spec at the
  gate; registry identity and eviction tests; offset-cache sharing tests.
- Planning reuse: call-count test on a small spec.
- Kernel: replay digest identity on three captured corpora under both
  backends; parity on every real search of two specs; random-grid parity
  for the relaxed search; budget and expansion-cap write-back tests; backend
  selection and fallback tests.
- Gate: the corpus audit described in section 3, run by script, with the
  baseline JSONL and the candidate JSONL committed under the plan's evidence
  directory.

## 9. Delivery order

Starting point: the master that includes the boundary-routing rewrite in
flight in the main checkout on 2026-09-01 (it rewrites
`_prepare_routing_problem`, `_route_all`, `_build_prepared`,
`_commit_paths`, `_PreparedRoutingProblem`, and `_production_run`). The
plan's worktree is created from that master and the baselines are generated
there, not copied from earlier runs.

1. Generate the 30-second and 15-second audit baselines on the starting
   master into the evidence directory.
2. Profiler split; record the pre-change profile for the three largest cells.
3. Planning reuse; re-profile.
4. The four preparation changes, each with its parity test; re-profile after
   each; accept only if the targeted phase drops or the profile explains why
   not.
5. Cython A* kernel with digest parity, then the Cython relaxed search;
   re-profile.
6. Corpus gate; commit the JSONL files, the parity output, and the
   comparison.

Each step is a separate commit that leaves the tree green. A step whose gate
fails is reverted, not tuned around.

## 10. Relationship to the reliability program

The reliability design's delivery steps 2 through 7 (feasibility-first
continuation, islands, ALNS, generalized cuts) each multiply the number of
candidate evaluations per budget. At 8 to 10 seconds per evaluation on the
largest cells, none of them fits a 30-second budget. This design is the
prerequisite: it changes only the cost of an evaluation and leaves every
contract those steps rely on intact. Its two later phases, a complete
last-mile router for a handful of stranded nets and concurrent scheduling of
both strategies with shared incumbents, are recorded in the session research
note and will be specified separately after this design's gate passes.

## 11. Risks

- A shared cache's keys may miss a dependency, producing a stale hit. The
  parity script over the whole corpus is the defence; any mismatch fails the
  gate.
- Cython float association order may differ from CPython for the same
  expression. The digest check is the defence; the kernel keeps the exact
  expression shapes the Python code uses.
- Preparation may have a long tail this design does not name. The profiler is
  built first so the tail is measured before it is guessed at.
- The reach prefilter's exactness argument rests on every member of a
  splitter stack sharing one materialized x and y. The parity test compares
  the filtered and unfiltered scans on a spec with coaters, and the corpus
  parity script covers the rest.
