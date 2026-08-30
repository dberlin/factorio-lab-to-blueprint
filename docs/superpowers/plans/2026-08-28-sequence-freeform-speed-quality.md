# SequencePair and Freeform Speed/Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce solver latency and repeated late failures while improving valid-layout yield under unchanged budgets.

**Architecture:** First restore measurement and refusal evidence. Then remove redundant exact projection and shared-router allocations without changing route semantics. Finally introduce one bounded Freeform near-miss rescue and make SequencePair quality exploitation use route feedback and a closer proxy for the exact objective.

**Tech Stack:** Python 3.14, dataclasses, OR-Tools CP-SAT, pytest, Ruff, MyPy.

**Spec:** `docs/superpowers/2026-08-28-sequence-freeform-speed-quality-spec.md`

## Global Constraints

- Exact `(area, belt_tiles)` remains the only authoritative winner key.
- Exact detailed routing, `validate.certify`, and `finalize.finalize_placement` remain authoritative.
- Do not change route ordering, path digest, failure kind/wall, expansion accounting, or emitted buildings in performance-only tasks.
- Freeform rescue is fixed-work and only follows 1–3 non-budget routing failures at the same height.
- SequencePair archive capacity and configured budgets do not increase.
- No new dependencies and no `Any`.
- Use TDD: each production change follows a focused test observed failing for the intended reason.

---

### Task 1: Restore profiling and refusal evidence

**Files:**
- Modify: `scripts/route_profile.py:60-174`
- Modify: `scripts/audit.py:79-168,206-245`
- Create: `tests/scripts/test_route_profile.py`
- Modify: `tests/scripts/test_audit.py` if present; otherwise create it

**Interfaces:**
- Consumes: `_PathSearchResult.path`, `.kind`, `.wall`, `.expansions`; `NoValidLayout.attempt_failures`; `NoValidLayout.projection_failures`.
- Produces: `Result.attempt_failures: tuple[LayoutAttemptFailure, ...]` and `Result.projection_failures: tuple[ProjectionFailureRecord, ...]`.

- [ ] **Step 1: Write failing profiler tests**

Add a focused test which patches `freeform._astar` to return `_PathSearchResult(path=((0, 0, 0),), kind=None, wall=(), expansions=7)`, installs the profiler shim, and asserts one hit, one path cell, and seven expansions. Add a second case with `path=None` and a failure kind.

- [ ] **Step 2: Run profiler tests and verify RED**

Run: `uv run pytest -q tests/scripts/test_route_profile.py`
Expected: failure because `install()` treats `_PathSearchResult` as a sequence or checks it against `None`.

- [ ] **Step 3: Update the shim for `_PathSearchResult`**

Use `out.path` and `out.expansions`; keep returning the original result unchanged. Do not infer expansions from the mutable budget when the result supplies the authoritative count.

- [ ] **Step 4: Write failing audit evidence test**

Construct `NoValidLayout` with one `LayoutAttemptFailure` and one `ProjectionFailureRecord`, make a fake strategy raise it from `run_cell`, and assert both typed tuples survive in `Result`.

- [ ] **Step 5: Run audit test and verify RED**

Run the focused audit test. Expected: `Result` has no typed evidence fields and the refusal branch returns only `("<refused>",)`.

- [ ] **Step 6: Preserve typed evidence**

Import `LayoutAttemptFailure` and `ProjectionFailureRecord`, add immutable defaulted fields to `Result`, and populate them in the `NoValidLayout` branch. Keep `checks` compact for terminal tables, but do not truncate `Result.detail` or structured evidence.

- [ ] **Step 7: Verify Task 1**

Run the two focused test files, then smoke: `uv run python scripts/route_profile.py --help`.

### Task 2: Return the already-finalized SequencePair winner

**Files:**
- Modify: `src/flab2bp/layout/sequence_solver.py:535-543,1409-1451,3105-3114,3513-3591`
- Modify: `tests/layout/test_sequence_solver.py`

**Interfaces:**
- Consumes: an adapter validation result carrying the authoritative finalized placement.
- Produces: `_ExactIncumbent.placement` is the finalized placement returned by `SequencePairLayout.lay_out`; validation projects exactly once.

- [ ] **Step 1: Run LSP references**

Find every construction and read of `_ExactIncumbent`, `ValidationVerdict`, and the production `certify` adapter before modifying their contract.

- [ ] **Step 2: Write failing finalization-count test**

Use a successful deterministic SequencePair solve with a spy around `finalize.finalize_placement`. Assert the returned object is the placement produced by the one authoritative finalization and the call count is one.

- [ ] **Step 3: Verify RED**

Run the focused test. Expected: two finalization calls.

- [ ] **Step 4: Carry finalized placement through validation**

Extend the validation verdict/adapter boundary with `placement: Placement | None`. A successful production adapter stores the finalized placement; failures store `None`. `_complete_routing_stage` computes the exact key from and stores the finalized placement. Remove the final `finalize_placement` call from `SequencePairLayout.lay_out`.

- [ ] **Step 5: Verify Task 2**

Run the focused test plus all SequencePair solver tests.

### Task 3: Remove shared-router reconstruction allocations

**Files:**
- Modify: `src/flab2bp/layout/freeform.py:3861-3915,4140-4169,4740-4789`
- Modify: `tests/layout/test_freeform.py`
- Modify: `tests/layout/test_global_router.py`

**Interfaces:**
- Produces: `_Grid.routing_flags` is a grid-owned reusable `bytearray`; `_routing_flags` returns it after exact refresh from current `grid.occ` and per-net reservation masking.
- Produces: `_PreparedRoutingProblem.new_workspace()` shallow-copies the tuple of frozen `PlacedBuilding` templates into an attempt-local list rather than deep-copying immutable records.

- [ ] **Step 1: Write failing allocation-ownership tests**

Assert repeated `_routing_flags(grid, ...)` calls return the same buffer object while reflecting intervening `grid.block()`/`restore()` changes and different routing-port reservations. Assert two prepared workspaces have distinct building lists but share the same immutable `PlacedBuilding` values by identity; appending to one list does not affect the other.

- [ ] **Step 2: Verify RED**

Run the focused tests. Expected: routing flags are newly allocated and prepared buildings are deep-copied.

- [ ] **Step 3: Add grid-owned scratch flags**

Initialize a reusable buffer in `_make_grid`; before each search perform an exact full slice refresh from `grid.occ`, then apply the current reservations in existing order. A* remains sequential per grid, so no shared concurrent use is introduced.

- [ ] **Step 4: Reuse immutable building records**

Replace `deepcopy(list(self.building_templates))` with `list(self.building_templates)`. `PlacedBuilding` is frozen; all attempt mutations remain list replacement/appends and mutable canvas containers remain copied.

- [ ] **Step 5: Verify deterministic equivalence**

Run detailed/global router tests and the existing deterministic path-digest/expansion tests. Then run `scripts/benchmark_projection.py --samples 3` only as a smoke; do not claim router speed from projection timings.

### Task 4: Let Freeform rescue strong near misses

**Files:**
- Modify: `src/flab2bp/layout/freeform.py:9553-10021`
- Modify: `tests/layout/test_freeform.py`

**Interfaces:**
- Produces: a small pure predicate `_is_rescuable_near_miss(routing: DetailedRouteResult) -> bool` returning true only for 1–3 failures with no `RouteFailureKind.BUDGET`.
- `_sweep` may admit one existing later arrangement at the same height before an incumbent when that predicate holds; it does not add arrangements or extend deadlines.

- [ ] **Step 1: Write failing predicate tests**

Cover zero failures, one geometric failure, three mixed non-budget failures, four failures, and any set containing `BUDGET`.

- [ ] **Step 2: Verify RED**

Run the focused tests. Expected: predicate is absent.

- [ ] **Step 3: Implement the pure predicate**

Use the authoritative routing result only; no string parsing and no projection/validation inference.

- [ ] **Step 4: Write failing sweep rescue test**

Drive `_sweep` with deterministic patched pack/build boundaries: arrangement zero returns two non-budget failures, arrangement one returns a valid placement. Assert arrangement one is attempted before any incumbent. Add controls proving a budget failure and four failures do not unlock it.

- [ ] **Step 5: Verify RED, then implement fixed-work admission**

Track rescuable heights. Replace the current `best is None` arrangement gate only for one already-configured next arrangement at that exact height. Consume normal candidate/deadline accounting; never append a candidate.

- [ ] **Step 6: Verify Task 4**

Run Freeform tests and the focused quantum-chip audit case at the existing short budget, recording validity and elapsed time without changing acceptance based on a single stochastic run.

### Task 5: Align SequencePair quality exploitation

**Files:**
- Modify: `src/flab2bp/layout/sequence_pair.py:1795-1810,1839-1888`
- Modify: `src/flab2bp/layout/sequence_solver.py:1179-1220,1481-1555`
- Modify: `tests/layout/test_sequence_pair.py`
- Modify: `tests/layout/test_sequence_solver.py`
- Modify: `tests/layout/test_route_feedback.py`

**Interfaces:**
- `quality_archive_key` orders legal candidates by overflow, projected rectangle area, missed direct inserts, routing/history proxy, then deterministic `PlacementKey`; exact winner selection remains unchanged.
- Quality-mode detailed results always pass through `decay_feedback` and `update_feedback` for non-static, non-budget evidence.
- Existing archive capacity is unchanged; when closing an archive, one slot that would duplicate an existing relation signature is replaced by the best candidate with a distinct `_archive_dedupe_key` relation signature.

- [ ] **Step 1: Write failing quality-key tests**

Construct candidates where the narrower rectangle has worse area/direct inserts and assert the area-aligned candidate wins; assert overflow remains first and key ordering remains deterministic.

- [ ] **Step 2: Verify RED, then update the key**

Use only existing `EnergyBreakdown` fields. Do not introduce an acceptance proxy or change `_exact_key`.

- [ ] **Step 3: Write failing quality-feedback test**

Start a stage in `ObjectiveMode.QUALITY`, return a non-budget detailed route failure, and assert feedback/history and repeated failure signature update exactly as exploration mode does. Add a static/budget control.

- [ ] **Step 4: Verify RED, then preserve feedback**

Remove the exploration-only suppression around feedback decay/update and failure-signature tracking. Keep exploration-only LNS and topology transforms unchanged.

- [ ] **Step 5: Write failing fixed-cap diversity test**

Build an archive whose final two width-first candidates share a relation signature and whose next candidate has a distinct signature. Assert capacity is unchanged and the distinct candidate is retained deterministically.

- [ ] **Step 6: Verify RED, then implement diversity substitution**

Reuse `_archive_dedupe_key`; replace redundant work rather than increasing `effective_cap` or configured elite counts.

- [ ] **Step 7: Verify Task 5**

Run SequencePair, feedback, and kernel tests. Full branch validation remains the final integration task.

### Task 6: Profile and conditionally compile exact A*

**Files:**
- Modify: `scripts/route_profile.py:231-325`
- Create only when the materiality gate passes: `Cargo.toml`
- Create only when the materiality gate passes: `native/astar/src/lib.rs`
- Modify only when the materiality gate passes: `setup.py`
- Modify only when the materiality gate passes: `pyproject.toml`
- Modify only when the materiality gate passes: `src/flab2bp/layout/freeform.py:4180-4673`
- Create: `tests/bench/test_route_profile.py`
- Create only when the materiality gate passes: `tests/layout/test_native_astar.py`

**Interfaces:**
- Profiling consumes the repaired `Tally` fields and emits machine-readable per-run wall, `_route_all`, and `_astar` seconds.
- The conditional native kernel consumes flat flags/history, dimensions, starts/goals, exact movement/toll parameters, and expansion/deadline limits. It produces the same path indices or ordered exhausted wall plus exact expansion accounting as Python `_astar`.

- [ ] **Step 1: Write failing machine-readable profiler test**

Invoke the profiler entry point around a synthetic `Tally` and assert a JSON record contains `wall_s`, `route_all_s`, `astar_s`, `astar_routing_share`, `astar_wall_share`, expansions, hits, and misses. Assert `--strategy sequence-pair` selects `SequencePairLayout` rather than always constructing Freeform.

- [ ] **Step 2: Verify RED, then implement bounded JSON output**

Run: `uv run pytest -q tests/bench/test_route_profile.py`. Add `--json` without changing existing human output and honor the existing `--strategy` option in normal mode.

- [ ] **Step 3: Measure the materiality gate**

Run two 4-second repeats for `plastic`, `super-magnetic-ring`, and `quantum-chip`. Save the six JSON records in the ignored SDD report, compute medians per case, and apply this exact gate: build native code only when A* is at least 25% of `_route_all` and 10% of wall in two cases, or at least 1.0 second absolute in any case.

- [ ] **Step 4: Record the conditional decision**

If the gate is false, record `NO BUILD`, the six measurements, and the dominant measured phase in the report; commit only the profiler/test work and proceed to full validation. If the gate is true, record `BUILD PYO3` and continue.

- [ ] **Step 5: Write failing exact replay tests**

Capture deterministic in-memory cases through public test fixtures: one successful flat path, one ramp path, one many-goal path, one history-heavy path, one budget exhaustion, and one sealed-pocket failure. Before native integration, assert `_native_astar` is unavailable or lacks the semantic-mirror entry point.

- [ ] **Step 6: Add the PyO3 build alongside Cython**

Keep setuptools as the build backend. Add current `setuptools-rust` and PyO3 build configuration alongside the existing Cython extension; do not replace `_sequence_kernel`. The Rust module name is `flab2bp.layout._native_astar`.

- [ ] **Step 7: Implement the semantic mirror**

Port only the flat per-expansion heap/search loop. Preserve Python's `(f, g, x-major-index)` ordering, float expression order, stale entry behavior, reopening behavior, four planar moves, two-cell ramp/via legality, exact goal termination, periodic budget/deadline checkpoints, predecessor/via reconstruction, and exhausted reachable-pocket ordering. Keep reservations, stake/unstake, owner mapping, blame, and result construction in Python.

- [ ] **Step 8: Verify RED to GREEN and differential equality**

Run the focused native replay tests. Every expected field must compare exactly; equal route cost alone is insufficient. Then run the complete detailed/global router tests.

- [ ] **Step 9: Benchmark the native replay**

Measure warm steady-state replay excluding compilation. Keep the extension only if it is at least 2x faster end-to-end on the captured A* calls and passes exact differential tests; otherwise remove all Rust/build changes and retain the profiler commit only.

- [ ] **Step 10: Verify the full branch**

Run the full Python suite, `uv run ruff check .`, and `uv run mypy src scripts`. When Rust remains, also run `cargo test` and `cargo clippy --all-targets -- -D warnings`.
