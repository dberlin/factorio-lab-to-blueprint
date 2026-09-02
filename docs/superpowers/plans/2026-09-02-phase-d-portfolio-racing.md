# Phase D Portfolio Racing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `strategy="best"` cost one wall budget per candidate instead of two by racing freeform and sequence-pair in spawned processes that share incumbent bounds and cluster no-goods, and stop the sequence-pair solver overrunning its budget by 5 to 10 seconds.

**Architecture:** Two independently gated halves. Wall discipline first: bound the one uninterruptible call that actually overruns the deadline (`_variant_direct_eligibility`), cap cold-stage admission against the attempt's total budget, poll the clock inside the annealing move loop and the archive routing loop, and measure each pipeline attempt against `budget + ATOMIC_COMPLETION_GRACE_S`. Racing second: a new `flab2bp.layout.strategy_race` module built on the request/outcome/`_terminate_executor` pattern `sequence_islands.py` already runs in production, with two bounded `multiprocessing` queues carrying tagged incumbent and no-good messages, an explicit CP-SAT worker split, and `min(area)` selection left exactly where it is in `pipeline.build`. Racing lands off by default and is flipped on in its own commit only after its gate passes.

**Tech Stack:** Python 3.14, `multiprocessing` spawn contexts, `concurrent.futures.ProcessPoolExecutor`, ortools CP-SAT 9.15, pytest (serial), Ruff, strict MyPy, `uv run`.

**Spec:** `docs/superpowers/specs/2026-09-02-phase-d-portfolio-racing-design.md`

## Global Constraints

- No new search operator, no-good kind, or acceptance rule. This phase transports Phase B's `ClusterRelationNoGood`; it does not invent one.
- No change to routing, strip planning, or any objective.
- No learned scheduling and no bandit over strategies: the portfolio is exactly two arms and both always run.
- No cross-process or on-disk geometry cache. `geometry_memo` stays `id(spec)`-keyed and process-local; each racer pays its own preparation.
- No first-clean-wins early stop: the race ends at the deadline or when both arms finish.
- Cython is the one compiled toolchain; this phase adds no compiled code.
- Racing is **opt-in until Task 17**: `pipeline.build`'s `race` parameter defaults to `False` through Task 16, so every existing `best` caller, test, and web request keeps today's serial semantics while the racing code is reviewed and gated. Task 17 flips it, and is the only task that touches the web ceiling or repairs a serial-`best` test.
- Every task is a separate commit that leaves the tree green: `uv run pytest -q`, `uv run ruff check .`, `uv run mypy` (no new diagnostic against the locked baseline of 176 pre-existing errors).
- Run the full test suite from the repo root with `uv run pytest -q` — serial, never `-n auto`: one CP-SAT solve already runs at ~700% CPU.
- Evidence files are tracked under `docs/superpowers/evidence/2026-09-02-phase-d-portfolio/`. The `.superpowers/sdd/` workspace is git-ignored.
- Timing measurements only on an idle box. `git diff` needs `--no-ext-diff`.
- Commit messages: imperative, sentence case, no trailing period, e.g. `fix(layout): bound the variant direct eligibility scan by the compact seed deadline`.
- A step whose measurement misses its stated goal is not committed as if it passed: record the numbers and report.
- **Gate D1** (Task 7): `scripts/audit.py --budget 30 --jobs 16`, both explicit strategies, three rounds — per-cell `seconds` maximum at or under 35.0 s, `wall p95` at or under 30.0 s, INVALID 0, CRASH 0, no cell CLEAN in Task 1's `baseline-budget30.jsonl` regressing, area within `--noise-area 0.013`.
- **Gate D2** (Task 16): `scripts/audit.py --budget 30 --jobs 16 --strategy all`, three rounds, 108 cells — every `best` cell CLEAN whose freeform or sequence-pair cell is CLEAN in Task 1's `baseline-budget30.jsonl`, per-cell `seconds` maximum at or under 35.0 s, per-strategy cells no worse than Gate D1, and `best` area at most `1.013 x min(freeform_area, sequence_pair_area)` **taken from Task 1's serial baseline**, not from the raced round's own arms.
- **Task 12 is the only task with an unlanded dependency.** It wires the no-good channel into the two receivers' no-good collections and therefore requires Phase B (`ClusterRelationNoGood`, its construction site, and the field naming its `StripInstanceId` tuple) and Phase C (the two collections that consume cluster no-goods) to be on the branch. Every other task, Task 11 included, is executable against the tree as it stands. Resolve Phase B's and Phase C's symbol and field names by symbol lookup in Task 12's first step; do not hard-code them from this document.
- **Starting point.** This plan's worktree is created from the branch carrying Phase C's gate. Every `file:line` below was taken at `b3c990a` and is a hint only: resolve each target by symbol name (Serena `find_symbol`) before editing, and enumerate call sites and protocol implementers with Serena `find_referencing_symbols` / `find_implementations`, never with grep alone (grep misses sites; it is for strings, comments, and config). The `lay_out` implementer list in Task 9 is a starting list, not the authority: Serena decides it.
- **Symbol-tool activation (every implementer and reviewer, first thing):** the tools are deferred, so load them explicitly: `ToolSearch("select:mcp__serena__activate_project,mcp__serena__initial_instructions,mcp__serena__find_symbol,mcp__serena__find_referencing_symbols,mcp__serena__find_implementations,mcp__serena__get_symbols_overview,LSP")`, then call `mcp__serena__activate_project` with the absolute path of the checkout you are editing (the worktree, not the main repository), then `mcp__serena__initial_instructions`. The repository tracks `.serena/project.yml`, so every worktree is its own Serena project once activated at its own path. If `find_symbol` errors or returns nothing for a symbol that exists, use the `LSP` tool (goToDefinition / findReferences) instead. If both fail, stop and report NEEDS_CONTEXT; never substitute grep.
- **Known test facts.** The two wall-clock tests `TestDirectInsertion::test_the_sweep_prefers_area_over_direct_insertion` (0.5 s) and `TestTheTimeBudgetIsAWall::test_magnetic_ring_repeated_one_second_calls_complete` (1.0 s) in `tests/layout/test_freeform.py` were removed from the tree during Phase B (Ruling S) because they flake under load; do not reintroduce them. `tests/test_pipeline.py::test_all_products_sequence_pair_honours_the_exact_layout_deadline` runs at a 1.5 s budget and trips DID NOT RAISE when preparation gets faster; lower the budget if it does.
- **Deviation from the brief, recorded here because it changes Task 2.** The design brief and the Phase D research note attribute the 35-40 s `quantum-chip/no-proliferator` overshoot to cold-stage admission in `_MeasuredStageAdmission.try_start`. Stack sampling shows `solver.search()` running zero stages on that cell, so no admission decision is ever made; the cause is `_variant_direct_eligibility` in `_production_run`. Task 2 fixes the measured cause. Task 3 still caps cold admission because that gap is real, not because it is this cell's cause.

---

### Task 1: Evidence baseline and audit row provenance

**Files:**
- Create: `docs/superpowers/evidence/2026-09-02-phase-d-portfolio/baseline-budget30.jsonl`
- Modify: `scripts/audit.py` (`Result`, `record`, `main`)
- Test: `tests/scripts/test_audit.py`

**Interfaces:**
- Consumes: `flab2bp.layout.route_kernel.selected_backend() -> BackendName` (returns `"python"` or `"cython"`); `scripts/audit.py`'s existing `Job`, `Result`, `Tally`, `record`, `run_cell`.
- Produces: `audit.Result.route_backend: str`; `audit._head_commit() -> str`; module global `audit._COMMIT: str`; two new JSONL keys on every row, `"route_backend"` and `"commit"`. Tasks 7 and 16 read them out of the gate files.

- [ ] **Step 1: Generate the baseline on the starting commit**

```bash
cd "$(git rev-parse --show-toplevel)"
git log --oneline -1   # record this hash in the commit message: it is the baseline commit
mkdir -p docs/superpowers/evidence/2026-09-02-phase-d-portfolio
uv run python scripts/audit.py --budget 30 --jobs 16 \
  --json docs/superpowers/evidence/2026-09-02-phase-d-portfolio/baseline-budget30.jsonl | tail -6
wc -l docs/superpowers/evidence/2026-09-02-phase-d-portfolio/baseline-budget30.jsonl
```

Expected: 72 lines, about 4 minutes. Record the clean count, the `wall p95` and the `wall max` in the commit message. Phase A's three rounds on its own tree were 65/72 with p95 30.4-30.7 s and max 34.8-40.3 s; Phase C's gate should have moved the clean count up. This file, not Phase C's round files, is the baseline for both gates.

- [ ] **Step 2: Write the failing provenance test**

Append to `tests/scripts/test_audit.py`:

```python
def test_every_audit_row_carries_the_routing_backend_and_the_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(audit, "_COMMIT", "0123456789abcdef0123456789abcdef01234567")
    audit._JSONL.clear()
    job = audit.Job(
        strategy="freeform",
        url_id=URL_CORPUS[0].url_id,
        url=URL_CORPUS[0].url,
        tier=URL_CORPUS[0].tier.value,
        spec_index=0,
        candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
        budget=1.0,
        workers=1,
    )
    # `Tally.total` is a read-only property summing the counters, so a Tally is
    # constructed EMPTY and grows as `record` classifies each result.
    tallies = {"freeform": audit.Tally()}
    for status, detail in (("CLEAN", ""), ("REFUSED", "deadline exhausted")):
        audit.record(
            tallies,
            audit.Result(job, status, "no-proliferator", detail, (), 1.0),
        )

    assert tallies["freeform"].total == 2
    assert len(audit._JSONL) == 2
    for row in audit._JSONL:
        assert row["commit"] == "0123456789abcdef0123456789abcdef01234567"
        assert row["route_backend"] in ("python", "cython")


def test_head_commit_is_a_hash_or_the_word_unknown() -> None:
    commit = audit._head_commit()

    assert commit == "unknown" or (len(commit) == 40 and int(commit, 16) >= 0)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/scripts/test_audit.py -q -k "route_backend or head_commit"`
Expected: both FAIL. `test_head_commit_is_a_hash_or_the_word_unknown` fails with `AttributeError: module 'scripts.audit' has no attribute '_head_commit'`; the other fails at its first line, `monkeypatch.setattr(audit, "_COMMIT", ...)`, with `AttributeError: <module 'scripts.audit'> has no attribute '_COMMIT'`.

- [ ] **Step 4: Add the provenance to `scripts/audit.py`**

Add `import subprocess` to the stdlib imports and `route_kernel` to the layout import:

```python
from flab2bp.layout import finalize, route_kernel, validate  # noqa: E402
```

Add the commit helper directly above `_JSONL`:

```python
def _head_commit() -> str:
    """The tree under audit, or ``"unknown"`` when git cannot say.

    An audit JSONL outlives the checkout that produced it.  Without this field a
    comparison of two files is a comparison of two anonymous runs, and the only
    way back to the code is the file's mtime.
    """
    try:
        finished = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=_ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=10.0,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return finished.stdout.strip() or "unknown"


#: Stamped onto every row by ``record``.  Resolved once in ``main`` rather than
#: per cell: it is a property of the run, and 72 subprocess calls to learn one
#: constant is 72 chances to be slow or to disagree with itself.
_COMMIT = "unknown"
```

Add the field at the end of `Result`:

```python
    #: Routing kernel THIS WORKER PROCESS selected.  A property of the process,
    #: not of a placement, so it is present on REFUSED and CRASH rows too --
    #: which is the point: a refusal under the Python fallback is a different
    #: fact from a refusal under Cython, and a JSONL that cannot tell them apart
    #: cannot be compared against one taken with the other backend.
    route_backend: str = field(default_factory=route_kernel.selected_backend)
```

In `record`, add two keys to the dict literal, immediately after `"strategy": r.job.strategy,`:

```python
            "commit": _COMMIT,
            "route_backend": r.route_backend,
```

In `main`, immediately after `args = ap.parse_args()`:

```python
    global _COMMIT
    _COMMIT = _head_commit()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/scripts/test_audit.py -q`
Expected: all pass

- [ ] **Step 6: Prove the fields reach a real JSONL row**

```bash
uv run python scripts/audit.py --budget 1 --jobs 1 --only iron-ingot \
  --strategy freeform --json /tmp/provenance-probe.jsonl >/dev/null
uv run python -c "
import json
rows = [json.loads(l) for l in open('/tmp/provenance-probe.jsonl')]
print(len(rows), rows[0]['commit'][:12], rows[0]['route_backend'])
"
```

Expected: `3 <12 hex chars> cython` — three candidate policies for one URL under one strategy.

- [ ] **Step 7: Lint, type-check, commit**

```bash
uv run ruff check scripts/audit.py tests/scripts/test_audit.py
uv run mypy scripts/audit.py tests/scripts/test_audit.py
git add scripts/audit.py tests/scripts/test_audit.py docs/superpowers/evidence/2026-09-02-phase-d-portfolio
git commit -m "bench: stamp the routing backend and the commit on every audit row"
```

---

### Task 2: Bound the variant direct eligibility scan by the compact seed deadline

**Files:**
- Modify: `src/flab2bp/layout/sequence_solver.py` (`_variant_direct_eligibility` at `:3627`, its call site in `_production_run` at `:4198`, a new constant beside `_COMPACT_SEED_DIRECT_MIN_BUDGET_S` at `:158`)
- Test: `tests/layout/test_sequence_solver.py`

**Interfaces:**
- Consumes: `_selected_direct_targets(spec, strips, problem, variant_indices, *, band_policy) -> tuple[DirectInsertTarget, ...]`; `PlacementProblem.variant_tables`, `PlacementProblem.size`; `VariantDirectInsertTarget(producer_variant, consumer_variant, target)`; the existing fixture `_two_stage_variant_problem() -> tuple[BuildSpec, list[Strip], PlacementProblem]` at `tests/layout/test_sequence_solver.py:3488`, which is what the existing `test_compact_direct_eligibility_contains_exactly_authoritative_variant_targets` (`:3593`) already drives this function with.
- Produces: `_variant_direct_eligibility(spec, strips, problem, *, band_policy, cancelled: Callable[[], bool] | None = None) -> tuple[VariantDirectInsertTarget, ...]`, returning `()` when `cancelled` fires; module constant `_DIRECT_ELIGIBILITY_MIN_REMAINING_S: float = 1.0`.

**Why this is the fix.** Two stack-sampling runs of `SequencePairLayout.lay_out` on `quantum-chip/no-proliferator` at `--budget 30` on an idle box measured 33.41 s (+3.41 s) and 35.33 s (+5.33 s) wall, with **zero** samples inside `solver.search()` and every post-deadline sample inside `_variant_direct_eligibility`. The call site guards it with `not deadline_reached()` once, before the call; the function itself has no clock. `_COMPACT_SEED_DIRECT_MIN_BUDGET_S = 30.0` is why the overshoot appears at the 30 s corpus budget and not at 15 s.

- [ ] **Step 1: Write the failing tests**

Append to `tests/layout/test_sequence_solver.py`. `_two_stage_variant_problem`, `_selected_direct_targets`, `BandPolicy` and `sequence_solver_module` are all already in scope there.

```python
def test_variant_direct_eligibility_returns_nothing_once_cancelled() -> None:
    spec, strips, problem = _two_stage_variant_problem()
    policy = BandPolicy("portable")
    enumerate_eligibility = sequence_solver_module._variant_direct_eligibility

    full = enumerate_eligibility(spec, strips, problem, band_policy=policy)
    never = enumerate_eligibility(
        spec, strips, problem, band_policy=policy, cancelled=lambda: False
    )
    immediately = enumerate_eligibility(
        spec, strips, problem, band_policy=policy, cancelled=lambda: True
    )

    assert full, "the fixture must produce at least one eligible target"
    assert never == full, "an un-fired cancel must not change the result"
    # The empty tuple is what the budget guard at the call site already
    # produces; a PARTIAL tuple would bias the seed by whichever candidates
    # happened to be enumerated before the clock ran out.
    assert immediately == ()


def test_variant_direct_eligibility_polls_its_cancel_more_than_once() -> None:
    spec, strips, problem = _two_stage_variant_problem()
    policy = BandPolicy("portable")
    polls = 0

    def counting() -> bool:
        nonlocal polls
        polls += 1
        return False

    sequence_solver_module._variant_direct_eligibility(
        spec, strips, problem, band_policy=policy, cancelled=counting
    )

    assert polls >= 2, "one poll before the loop is the bug this test exists to catch"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/layout/test_sequence_solver.py -q -k "variant_direct_eligibility"`
Expected: both FAIL with `TypeError: _variant_direct_eligibility() got an unexpected keyword argument 'cancelled'`

- [ ] **Step 3: Add the constant**

Beside `_COMPACT_SEED_DIRECT_MIN_BUDGET_S = 30.0`:

```python
#: Seconds of the compact-seed wall share below which the variant direct
#: eligibility scan is not worth starting.  It is a triple nested loop over
#: (baseline candidate x producer variant x consumer variant), each iteration a
#: full ``_selected_direct_targets`` rebuild; measured at 27s of a 30s budget on
#: quantum-chip/no-proliferator, where it consumed the whole search and ran 5s
#: past the deadline because nothing inside it looked at a clock.
_DIRECT_ELIGIBILITY_MIN_REMAINING_S = 1.0
```

- [ ] **Step 4: Give the scan a cancel**

Replace `_variant_direct_eligibility` entirely:

```python
def _variant_direct_eligibility(
    spec: BuildSpec,
    strips: list[Strip],
    problem: PlacementProblem,
    *,
    band_policy: BandPolicy,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[VariantDirectInsertTarget, ...]:
    """Enumerate only endpoint-variant pairs production can directly attach.

    ``cancelled`` returns the empty tuple, which is exactly what the call site
    already produces when the budget is too small for the scan -- so a cancelled
    scan is an outcome the compact seed has always handled, not a new one.  A
    PARTIAL tuple is deliberately never returned: the seed would then be biased
    by whichever candidates happened to be enumerated before the clock ran out.
    """
    if cancelled is not None and cancelled():
        return ()
    defaults = (0,) * problem.size
    baseline = _selected_direct_targets(
        spec,
        strips,
        problem,
        defaults,
        band_policy=band_policy,
    )
    if not baseline:
        return ()

    variant_counts = (
        tuple(len(table) for table in problem.variant_tables)
        if problem.variant_tables
        else (1,) * problem.size
    )
    eligible: list[VariantDirectInsertTarget] = []
    for candidate in baseline:
        if cancelled is not None and cancelled():
            return ()
        for producer_variant in range(variant_counts[candidate.producer]):
            if cancelled is not None and cancelled():
                return ()
            for consumer_variant in range(variant_counts[candidate.consumer]):
                selection = list(defaults)
                selection[candidate.producer] = producer_variant
                selection[candidate.consumer] = consumer_variant
                selected = {
                    target.key: target
                    for target in _selected_direct_targets(
                        spec,
                        strips,
                        problem,
                        tuple(selection),
                        band_policy=band_policy,
                    )
                }
                target = selected.get(candidate.key)
                if target is not None:
                    eligible.append(
                        VariantDirectInsertTarget(
                            producer_variant,
                            consumer_variant,
                            target,
                        )
                    )
    return tuple(eligible)
```

- [ ] **Step 5: Pass the compact seed's own deadline at the call site**

In `_production_run`, replace the `direct_eligibility = (...)` expression that follows `compact_deadline`:

```python
                def compact_deadline_reached() -> bool:
                    return time.monotonic() >= compact_deadline

                direct_eligibility = (
                    _variant_direct_eligibility(
                        spec,
                        strips,
                        problems[compact_height],
                        band_policy=band_policy,
                        cancelled=compact_deadline_reached,
                    )
                    if (
                        ceiling >= _COMPACT_SEED_DIRECT_MIN_BUDGET_S
                        and compact_deadline - time.monotonic()
                        >= _DIRECT_ELIGIBILITY_MIN_REMAINING_S
                    )
                    else ()
                )
```

`compact_deadline` is `min(deadline, compact_started + ceiling * _COMPACT_SEED_WALL_SHARE)`, already computed on the lines above; the scan is an input to the compact seed, so the compact seed's own wall share is the right bound. The old `not deadline_reached()` term is subsumed, because `compact_deadline <= deadline`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/layout/test_sequence_solver.py tests/layout/test_compact_seed.py -q`
Expected: all pass. Both files reference `_variant_direct_eligibility` by name (`test_sequence_solver.py:3598`, `test_compact_seed.py:790`); if either patched it with a stub whose signature has no `**kwargs`, widen the stub.

- [ ] **Step 7: Measure the cell the fix targets**

```bash
uv run python scripts/audit.py --budget 30 --jobs 1 --only quantum-chip \
  --strategy sequence-pair --json /tmp/qc-after.jsonl | tail -4
uv run python -c "
import json
for r in map(json.loads, open('/tmp/qc-after.jsonl')):
    print(f\"{r['seconds']:6.2f}s {r['spec_label']:16s} {r['status']} {r['detail'][:60]}\")
"
```

Expected: the `no-proliferator` row is at or under 32 s (it was 33.4-40.3 s). Decision rule: if it is still above 35 s, stop and report — re-run the sampling probe from the spec's section 2.2 and say what it names, because the attribution has moved.

- [ ] **Step 8: Lint, type-check, commit**

```bash
uv run ruff check src/flab2bp/layout/sequence_solver.py tests/layout/test_sequence_solver.py
uv run mypy src/flab2bp/layout/sequence_solver.py
git add src/flab2bp/layout/sequence_solver.py tests/layout/test_sequence_solver.py
git commit -m "fix(layout): bound the variant direct eligibility scan by the compact seed deadline"
```

---

### Task 3: Cap cold-stage admission against the attempt's total budget

**Files:**
- Modify: `src/flab2bp/layout/sequence_solver.py` (`_MeasuredStageAdmission` at `:592`, `try_start` at `:620`, its construction in `_production_run` at `:3932`, new constants above `_MeasuredStageRole` at `:571`)
- Test: `tests/layout/test_sequence_solver.py`

**Interfaces:**
- Consumes: `_MeasuredStageHistory(speculative_s, completion_s, completion_observed)`; `_MeasuredStageRole` (`ORDINARY`, `COMPACT`, `FEEDBACK`, `SHARED`, `TOPOLOGY`).
- Produces: `COLD_STAGE_FRACTION: float = 0.25`, `COLD_STAGE_MIN_RESERVE_S: float = 0.25`; `_MeasuredStageAdmission(deadline, monotonic=time.monotonic, total_budget_s=0.0, cold_fraction=COLD_STAGE_FRACTION, cold_floor_s=COLD_STAGE_MIN_RESERVE_S)`. `try_start` keeps its `(role=ORDINARY) -> float | None` signature.

**Why the rule needs the total budget.** `_MeasuredStageAdmission` knows only its `deadline`, so a cold-stage rule written in terms of `remaining` alone is vacuous: `remaining > remaining * fraction` holds for every fraction under 1 and every positive remainder. The admission has to be told the span it is bounding.

- [ ] **Step 1: Write the failing tests**

```python
def test_cold_stage_admission_refuses_the_last_quarter_of_the_budget() -> None:
    """A role with no history must reserve a share of the WHOLE budget.

    deadline 100.0, total_budget_s 100.0, COLD_STAGE_FRACTION 0.25,
    COLD_STAGE_MIN_RESERVE_S 0.25, so a cold role requires
    max(0.25, 0.25 * 100.0) = 25.0 seconds of remaining wall:

        now = 10.0 -> remaining 90.0 > 25.0 -> ADMIT
        now = 80.0 -> remaining 20.0 < 25.0 -> REFUSE
        now = 99.9 -> remaining  0.1 < 25.0 -> REFUSE

    Written out because `remaining > remaining * fraction` is the vacuous rule
    this test exists to keep out of the code.
    """
    from flab2bp.layout.sequence_solver import (
        _MeasuredStageAdmission,
        _MeasuredStageRole,
    )

    now = 0.0

    def clock() -> float:
        return now

    admission = _MeasuredStageAdmission(
        deadline=100.0, monotonic=clock, total_budget_s=100.0
    )

    now = 10.0
    assert admission.try_start(_MeasuredStageRole.ORDINARY) == 10.0
    admission.finish(10.0, _MeasuredStageRole.ORDINARY)

    now = 80.0
    assert admission.try_start(_MeasuredStageRole.COMPACT) is None

    now = 99.9
    assert admission.try_start(_MeasuredStageRole.FEEDBACK) is None


def test_an_unmigrated_admission_keeps_a_quarter_second_floor() -> None:
    """``total_budget_s`` defaults to 0.0, so only the floor applies."""
    from flab2bp.layout.sequence_solver import (
        _MeasuredStageAdmission,
        _MeasuredStageRole,
    )

    now = 0.0

    def clock() -> float:
        return now

    admission = _MeasuredStageAdmission(deadline=100.0, monotonic=clock)

    now = 80.0   # 20.0 remaining, over the 0.25 floor
    assert admission.try_start(_MeasuredStageRole.ORDINARY) == 80.0
    admission.finish(80.0, _MeasuredStageRole.ORDINARY)

    now = 99.9   # 0.1 remaining, under the 0.25 floor
    assert admission.try_start(_MeasuredStageRole.COMPACT) is None


def test_warm_stage_admission_is_unchanged_by_the_cold_cap() -> None:
    """Measured history is the whole requirement -- no floor, no share.

    The first stage runs 0.0 -> 8.0 with 3.0 of that recorded as completion, so
    the ORDINARY history becomes speculative 5.0 + completion 3.0 = 8.0.  At
    now = 90.0 there are 10.0 seconds left: over the measured 8.0 and UNDER the
    25.0 a cold role would have required, which is what makes this a test of the
    warm path rather than a second test of the cold one.
    """
    from flab2bp.layout.sequence_solver import (
        _MeasuredStageAdmission,
        _MeasuredStageRole,
    )

    now = 0.0

    def clock() -> float:
        return now

    admission = _MeasuredStageAdmission(
        deadline=100.0, monotonic=clock, total_budget_s=100.0
    )
    started = admission.try_start(_MeasuredStageRole.ORDINARY)
    assert started == 0.0
    now = 8.0
    admission.record_completion(3.0)
    admission.finish(started, _MeasuredStageRole.ORDINARY)

    now = 90.0
    assert admission.try_start(_MeasuredStageRole.ORDINARY) == 90.0
    admission.finish(90.0, _MeasuredStageRole.ORDINARY)

    now = 93.0   # 7.0 remaining, under the measured 8.0
    assert admission.try_start(_MeasuredStageRole.ORDINARY) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/layout/test_sequence_solver.py -q -k "cold_stage_admission or unmigrated_admission or warm_stage_admission"`
Expected: `test_cold_stage_admission_refuses_the_last_quarter_of_the_budget` and `test_warm_stage_admission_is_unchanged_by_the_cold_cap` FAIL at construction with `TypeError: _MeasuredStageAdmission.__init__() got an unexpected keyword argument 'total_budget_s'`; `test_an_unmigrated_admission_keeps_a_quarter_second_floor` FAILS at its last assertion with `assert 99.9 is None`, because today a cold role is admitted on any positive remainder.

- [ ] **Step 3: Add the constants**

Above `class _MeasuredStageRole`:

```python
#: The share of the attempt's WHOLE budget a role with no measured history must
#: have left before it may start.  A cold stage is admitted on `remaining > 0`
#: today, so the first stage of any role can start with a millisecond left and
#: then run to its move count.  The rule is written against the total rather
#: than the remainder because `remaining > remaining * fraction` is vacuous.
COLD_STAGE_FRACTION = 0.25

#: Absolute floor under :data:`COLD_STAGE_FRACTION`, and the whole requirement
#: for an admission constructed without a ``total_budget_s`` -- which is every
#: caller outside ``_production_run``, the tests included.
COLD_STAGE_MIN_RESERVE_S = 0.25
```

- [ ] **Step 4: Apply the cap in `try_start`**

Add the fields to `_MeasuredStageAdmission`, immediately after `monotonic`:

```python
    #: The attempt's whole wall, so a cold stage can reserve a share of the
    #: BUDGET rather than a share of whatever happens to be left.  ``0.0`` (the
    #: default) leaves only ``cold_floor_s``.
    total_budget_s: float = 0.0
    cold_fraction: float = COLD_STAGE_FRACTION
    cold_floor_s: float = COLD_STAGE_MIN_RESERVE_S
```

and replace `try_start`'s body:

```python
    def try_start(
        self,
        role: _MeasuredStageRole = _MeasuredStageRole.ORDINARY,
    ) -> float | None:
        history = self._history(role)
        now = self.monotonic()
        remaining = self.deadline - now
        required = history.speculative_s + history.completion_s
        if required <= 0.0:
            required = max(
                self.cold_floor_s,
                self.cold_fraction * self.total_budget_s,
            )
        if remaining <= 0.0 or remaining <= required:
            return None
        self._active_started = now
        self._active_role = role
        self._active_completion_s = 0.0
        self._active_completion_observed = False
        return now
```

- [ ] **Step 5: Tell `_production_run` its own budget**

In `_production_run`, at the `_MeasuredStageAdmission` construction:

```python
    stage_admission = _MeasuredStageAdmission(
        deadline=deadline,
        monotonic=time.monotonic,
        total_budget_s=ceiling,
    )
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/layout/test_sequence_solver.py -q`
Expected: all pass. A pre-existing test that admitted a cold stage with a sliver of wall left will now fail; where it does, raise that test's fake `deadline` so `remaining` clears `max(0.25, 0.25 * total_budget_s)` rather than relaxing either constant.

- [ ] **Step 7: Confirm no corpus cell regressed on the small tier**

```bash
uv run python scripts/audit.py --budget 15 --jobs 4 --tier small \
  --strategy sequence-pair --json /tmp/cold-cap-small.jsonl | tail -4
```

Expected: the same clean count as before the change. Decision rule: if any cell moved from CLEAN to REFUSED, lower `COLD_STAGE_FRACTION` to `0.10`, re-run, and record both numbers in the commit message.

- [ ] **Step 8: Lint, type-check, commit**

```bash
uv run ruff check src/flab2bp/layout/sequence_solver.py tests/layout/test_sequence_solver.py
uv run mypy src/flab2bp/layout/sequence_solver.py
git add src/flab2bp/layout/sequence_solver.py tests/layout/test_sequence_solver.py
git commit -m "fix(layout): cap cold stage admission against the attempt budget"
```

---

### Task 4: Poll the clock inside the annealing move loop

**Files:**
- Modify: `src/flab2bp/layout/sequence_pair.py` (`AnnealStageResult` at `:797`, `anneal_stage` at `:1435`, a new constant beside `AnnealConfig` at `:350`)
- Modify: `src/flab2bp/layout/sequence_solver.py` (`SequenceSolver._anneal_restarts` at `:1826`)
- Test: `tests/layout/test_sequence_pair.py`

**Interfaces:**
- Consumes: `AnnealConfig.moves_per_stage`, `EliteArchiveBuilder`, `apply_move`, `_linear_temperature`, `_accept_move`; `SequenceSolver.deadline_reached: Callable[[], bool]`.
- Produces: `ANNEAL_DEADLINE_CHECK_MOVES: int = 256`; `anneal_stage(..., cancelled: Callable[[], bool] | None = None)`; `AnnealStageResult.cancelled: bool` (default `False`, `compare=False`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/layout/test_sequence_pair.py`. `PlacementProblem`, `AnnealState`, `SequencePair`, `GapProfile`, `AnnealConfig` and `anneal_stage` are all already imported there. The scene below was run against the tree: 1024 moves give 411 accepted moves and a four-entry archive on the `cython` backend, and two identical calls compare equal.

```python
def _cancellable_anneal_scene() -> tuple[PlacementProblem, AnnealState]:
    """Four strips, four nets: enough for real moves, small enough to be fast."""
    problem = PlacementProblem(
        sizes=((3, 2), (2, 4), (4, 1), (1, 3)),
        nets=((0, 1), (1, 2), (2, 3), (0, 3)),
        outline_height=6,
        area_lower_bound=20,
    )
    state = AnnealState(
        pair=SequencePair(positive=(0, 1, 2, 3), negative=(3, 2, 1, 0)),
        gaps=GapProfile.zero(problem.size),
        base_seed=20260824,
        stage_index=0,
        variant_indices=(0,) * problem.size,
    )
    return problem, state


def test_anneal_stage_stops_between_moves_when_cancelled() -> None:
    from flab2bp.layout.sequence_pair import ANNEAL_DEADLINE_CHECK_MOVES

    problem, state = _cancellable_anneal_scene()
    config = AnnealConfig(moves_per_stage=4 * ANNEAL_DEADLINE_CHECK_MOVES, elite_count=4)

    full = anneal_stage(problem, state, config)
    polls = 0

    def after_one_poll() -> bool:
        nonlocal polls
        polls += 1
        return polls > 1

    cut = anneal_stage(problem, state, config, cancelled=after_one_poll)

    assert full.cancelled is False
    assert cut.cancelled is True
    assert cut.accepted_moves < full.accepted_moves
    assert len(cut.final_state.gaps.east) == problem.size
    assert cut.archive, "a cancelled stage still returns the elites it scored"


def test_anneal_stage_without_a_cancel_is_byte_identical() -> None:
    problem, state = _cancellable_anneal_scene()
    config = AnnealConfig(moves_per_stage=512, elite_count=4)

    assert anneal_stage(problem, state, config) == anneal_stage(
        problem, state, config, cancelled=None
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/layout/test_sequence_pair.py -q -k "anneal_stage_stops or byte_identical"`
Expected: `test_anneal_stage_stops_between_moves_when_cancelled` FAILS at its import line with `ImportError: cannot import name 'ANNEAL_DEADLINE_CHECK_MOVES' from 'flab2bp.layout.sequence_pair'`; `test_anneal_stage_without_a_cancel_is_byte_identical` FAILS with `TypeError: anneal_stage() got an unexpected keyword argument 'cancelled'`.

- [ ] **Step 3: Add the constant and the result field**

Beside `AnnealConfig`:

```python
#: Moves between clock polls in :func:`anneal_stage`.  A move is a scored state
#: transition, far dearer than ``time.monotonic()``, so the stride exists to keep
#: the poll off the hot path rather than to save the syscall; 256 of 2,000 moves
#: bounds the overrun at an eighth of a stage.
ANNEAL_DEADLINE_CHECK_MOVES = 256
```

In `AnnealStageResult`, after `backend`:

```python
    #: Whether the caller's clock ended the stage before its move count did.
    #: ``compare=False`` for the same reason ``backend`` is: two stages that
    #: reached the same state are the same result however they got there.
    cancelled: bool = field(default=False, compare=False)
```

- [ ] **Step 4: Poll the clock in the move loop**

Add `cancelled: Callable[[], bool] | None = None` to `anneal_stage`'s keyword-only parameters, and replace the move loop and the return:

```python
    stopped = False
    for move_index in range(config.moves_per_stage):
        if (
            cancelled is not None
            and move_index
            and move_index % ANNEAL_DEADLINE_CHECK_MOVES == 0
            and cancelled()
        ):
            stopped = True
            break
        candidate_state = apply_move(
            state=current.state,
            kind=rng.choice(move_kinds),
            rng=rng,
            problem=problem,
        )
        candidate_targets = (
            direct_targets_for_state(problem, candidate_state)
            if direct_targets_for_state is not None
            else None
        )
        candidate = kernel.score_state(candidate_state, direct_targets=candidate_targets)
        archive_builder.add(candidate)
        temperature = _linear_temperature(config, move_index)
        if _accept_move(current.energy, candidate.energy, temperature, rng):
            current = candidate
            accepted_moves += 1

    final_state = AnnealState(
        pair=current.state.pair,
        gaps=current.state.gaps,
        base_seed=state.base_seed,
        stage_index=state.stage_index + 1,
        variant_indices=current.state.variant_indices,
    )
    return AnnealStageResult(
        final_state=final_state,
        incumbent=archive_builder.blended_elites[0],
        accepted_moves=accepted_moves,
        elites=archive_builder.blended_elites,
        archive=archive_builder.archive,
        backend=kernel.backend,
        cancelled=stopped,
    )
```

`move_index and move_index % STRIDE == 0` skips the poll at move 0, so the first `ANNEAL_DEADLINE_CHECK_MOVES` moves always run and `cancelled=lambda: True` still returns a scored archive rather than an empty one.

- [ ] **Step 5: Thread the solver's deadline into both call sites**

In `SequenceSolver._anneal_restarts`, add `cancelled=self.deadline_reached` to both `anneal_stage(...)` calls:

```python
            if self.direct_targets_for_state is None:
                result = anneal_stage(
                    problem,
                    stage_start,
                    restart_config,
                    context,
                    cancelled=self.deadline_reached,
                )
            else:
                result = anneal_stage(
                    problem,
                    stage_start,
                    restart_config,
                    context,
                    direct_targets_for_state=self.direct_targets_for_state,
                    cancelled=self.deadline_reached,
                )
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/layout/test_sequence_pair.py tests/layout/test_sequence_solver.py tests/layout/test_sequence_kernel.py -q`
Expected: all pass

- [ ] **Step 7: Lint, type-check, commit**

```bash
uv run ruff check src/flab2bp/layout/sequence_pair.py src/flab2bp/layout/sequence_solver.py tests/layout/test_sequence_pair.py
uv run mypy src/flab2bp/layout/sequence_pair.py src/flab2bp/layout/sequence_solver.py
git add src/flab2bp/layout/sequence_pair.py src/flab2bp/layout/sequence_solver.py tests/layout/test_sequence_pair.py
git commit -m "fix(layout): poll the deadline between annealing moves"
```

---

### Task 5: Poll the clock inside the archive routing loop

**Files:**
- Modify: `src/flab2bp/layout/sequence_solver.py` (`SequenceSolver._route_archive` at `:2002`, its `completion_reserve_stop` flag at `:2036` and the selection branch at `:2098`)
- Test: `tests/layout/test_sequence_solver.py`

**Interfaces:**
- Consumes: `SequenceSolver.deadline_reached`; `StageAdapters.prepare`; the existing fixtures `_FakeRouting` (`:309`, whose `prepared_candidates` list counts preparations), `_solver(fake, *, heights, config, deadline_reached, ...)` (`:375`) and `_repeat_merged_elite(monkeypatch, count)` (`:412`); `SequenceSolver._select_restart`, `SequenceSolver._run_stage`.
- Produces: a new local flag `deadline_stop` in `_route_archive`, and the `global_skip_reason` value `"deadline"`.

**Why a separate flag.** `completion_reserve_stop` (`:2036`) has exactly one reader, and it selects `global_skip_reason = "completion-reserve"` — a specific claim about the measured completion reserve that stage telemetry then reports. Reusing it for a deadline stop would make every deadline-bound stage report a reserve it never hit.

- [ ] **Step 1: Write the failing test and its control**

Append to `tests/layout/test_sequence_solver.py`. The counts were measured against the tree: with four merged elites and a 400-expansion allowance, `_route_archive` prepares 4 candidates today, with or without a passed deadline.

```python
def test_archive_routing_stops_preparing_candidates_after_the_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _repeat_merged_elite(monkeypatch, 4)
    fake = _FakeRouting()
    solver = _solver(
        fake,
        heights=(40,),
        config=SequenceSolverConfig(
            stages=6, moves_per_stage=1, restarts_per_height=2, global_elites=4
        ),
        deadline_reached=lambda: True,
    )
    height_state = solver._heights[0]

    solver._run_stage(height_state, solver._select_restart(height_state), 400)

    assert len(fake.prepared_candidates) == 1, (
        "preparation is the dearest thing in this loop and a passed deadline "
        "makes every candidate after the first unroutable"
    )


def test_archive_routing_prepares_every_elite_while_the_clock_holds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _repeat_merged_elite(monkeypatch, 4)
    fake = _FakeRouting()
    solver = _solver(
        fake,
        heights=(40,),
        config=SequenceSolverConfig(
            stages=6, moves_per_stage=1, restarts_per_height=2, global_elites=4
        ),
        deadline_reached=lambda: False,
    )
    height_state = solver._heights[0]

    solver._run_stage(height_state, solver._select_restart(height_state), 400)

    assert len(fake.prepared_candidates) == 4
```

- [ ] **Step 2: Run the tests to verify exactly one fails**

Run: `uv run pytest tests/layout/test_sequence_solver.py -q -k "archive_routing_stops or archive_routing_prepares"`
Expected: `test_archive_routing_prepares_every_elite_while_the_clock_holds` PASSES — that is today's behaviour and must survive the change — and `test_archive_routing_stops_preparing_candidates_after_the_deadline` FAILS with `assert 4 == 1`.

- [ ] **Step 3: Add the deadline stop**

In `_route_archive`, beside `completion_reserve_stop = False`:

```python
        deadline_stop = False
```

Insert the check at the top of the candidate loop, immediately after `for index, (tagged, source) in enumerate(candidates):` and before the existing `if proxy_left == 0 and prepared_candidates: break`:

```python
            if prepared_candidates and self.deadline_reached():
                # Preparation is the dearest thing in this loop -- 1.9 to 4.6s
                # per candidate on the largest cells -- and `prepare` turns a
                # passed deadline into `preparation_error="deadline"` anyway, so
                # every further iteration buys a candidate that cannot be routed.
                # The FIRST candidate is always prepared: `detailed_route` maps
                # its deadline error to DetailedRouteStatus.BUDGET, the existing
                # tested path, while an empty `prepared_candidates` would raise.
                deadline_stop = True
                break
```

and extend the selection branch, ahead of the `completion_reserve_stop` arm so a stop that is both reports the deadline:

```python
        if deadline_stop and not global_candidates:
            selected = prepared_candidates[0]
            global_overflow = None
            global_skip_reason = "deadline"
        elif completion_reserve_stop and not global_candidates:
            selected = prepared_candidates[0]
            global_overflow = None
            global_skip_reason = "completion-reserve"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/layout/test_sequence_solver.py tests/layout/test_sequence_islands.py -q`
Expected: all pass

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check src/flab2bp/layout/sequence_solver.py tests/layout/test_sequence_solver.py
uv run mypy src/flab2bp/layout/sequence_solver.py
git add src/flab2bp/layout/sequence_solver.py tests/layout/test_sequence_solver.py
git commit -m "fix(layout): stop preparing archive candidates once the deadline has passed"
```

---

### Task 6: Per-attempt deadline and overshoot reporting in the pipeline

**Files:**
- Modify: `src/flab2bp/pipeline.py` (`build`'s attempt loop at `:524-668`)
- Modify: `src/flab2bp/layout/base.py` (`PlacementStats`)
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `flab2bp.layout.base.ATOMIC_COMPLETION_GRACE_S` (= 5.0); `finalize.finalize_placement(placement, policy, *, cancelled: Callable[[], bool] | None = None)`; `Placement.stats` (`PlacementStats`, `total=False`).
- Produces: two `PlacementStats` keys written on every attempt's placement — `attempt_wall_s: float` and `wall_overshoot_s: float`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pipeline.py`:

```python
@pytest.mark.slow
def test_every_attempt_reports_its_wall_and_its_overshoot() -> None:
    from flab2bp.layout.base import ATOMIC_COMPLETION_GRACE_S

    built = pipeline.build(
        SMALL_URL,
        strategy="freeform",
        candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
        time_budget_s=5.0,
    )

    assert built.attempts
    for attempt in built.attempts:
        stats = attempt.placement.stats
        assert stats["attempt_wall_s"] > 0.0
        assert stats["wall_overshoot_s"] == max(
            0.0, stats["attempt_wall_s"] - 5.0 - ATOMIC_COMPLETION_GRACE_S
        )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_pipeline.py -q -k "reports_its_wall_and_its_overshoot"`
Expected: FAIL with `KeyError: 'attempt_wall_s'`

- [ ] **Step 3: Declare the two stats**

In `src/flab2bp/layout/base.py`, inside `class PlacementStats(TypedDict, total=False)`, keeping alphabetical order:

```python
    attempt_wall_s: float
    wall_overshoot_s: float
```

- [ ] **Step 4: Measure and cancel in the attempt loop**

In `pipeline.py`, add `ATOMIC_COMPLETION_GRACE_S` to the existing `from flab2bp.layout.base import (...)` block and `import time` if absent. In `build`, immediately after `layout = _new_layout(...)` and before the `try:` around `lay_out`:

```python
            attempt_started = time.monotonic()
            # A HARD wall per attempt, in the one place that can see the whole
            # cost.  A strategy's own budget covers its search; compaction,
            # projection, validation and encoding all run AFTER it and are
            # charged to nobody.  `validate.validate` takes no cancellation
            # parameter at all, so this cancels where a hook exists and REPORTS
            # everywhere else -- a number the gate can fail on beats a number
            # nobody produced.
            attempt_deadline = (
                attempt_started + time_budget_s + ATOMIC_COMPLETION_GRACE_S
            )

            def attempt_expired(_deadline: float = attempt_deadline) -> bool:
                return time.monotonic() >= _deadline
```

Pass the cancel into the re-finalization call:

```python
                    placement = finalize.finalize_placement(
                        placement,
                        policy,
                        cancelled=attempt_expired,
                    )
```

Immediately before `attempts.append(Attempt(...))`, stamp the wall onto the placement that is about to be recorded:

```python
            attempt_wall_s = time.monotonic() - attempt_started
            labelled.stats["attempt_wall_s"] = attempt_wall_s
            labelled.stats["wall_overshoot_s"] = max(
                0.0,
                attempt_wall_s - time_budget_s - ATOMIC_COMPLETION_GRACE_S,
            )
```

`Placement` is a frozen dataclass but `stats` is a mutable `TypedDict`; `_sweep` already writes into it the same way (`freeform.py:16975-16979`).

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_pipeline.py -q`
Expected: all pass. `test_all_products_sequence_pair_honours_the_exact_layout_deadline` runs at a 1.5 s budget and trips DID NOT RAISE when preparation gets faster; if Tasks 2-5 made it pass where it should raise, lower its budget to 1.0 and record the new value in the commit message.

- [ ] **Step 6: Lint, type-check, commit**

```bash
uv run ruff check src/flab2bp/pipeline.py src/flab2bp/layout/base.py tests/test_pipeline.py
uv run mypy src/flab2bp/pipeline.py src/flab2bp/layout/base.py
git add src/flab2bp/pipeline.py src/flab2bp/layout/base.py tests/test_pipeline.py
git commit -m "feat(pipeline): measure each attempt against a hard per-attempt deadline"
```

---

### Task 7: Gate D1, the wall discipline corpus gate

**Files:**
- Create: `docs/superpowers/evidence/2026-09-02-phase-d-portfolio/wall-budget30-round{1,2,3}.jsonl`
- Create: `docs/superpowers/evidence/2026-09-02-phase-d-portfolio/gate-d1.md`

**Interfaces:**
- Consumes: `scripts/audit.py --budget 30 --jobs 16 --json PATH`; `scripts/audit_compare.py BASELINE CANDIDATE --noise-area 0.013 --p95-seconds 30 --expect-cells 72`; `baseline-budget30.jsonl` from Task 1.
- Produces: the committed Gate D1 record. Task 16 compares its per-strategy rows against Gate D2's.

- [ ] **Step 1: Confirm the tree is green before measuring**

```bash
uv run python setup.py build_ext --inplace
uv run pytest -q
uv run ruff check .
uv run mypy
```

Expected: the suite passes, ruff is clean, mypy reports no new diagnostic against the locked baseline of 176.

- [ ] **Step 2: Run the three rounds**

```bash
d=docs/superpowers/evidence/2026-09-02-phase-d-portfolio
for r in 1 2 3; do
  uv run python scripts/audit.py --budget 30 --jobs 16 --json "$d/wall-budget30-round$r.jsonl" | tail -6
done
```

Expected: 72 rows per file, about 4 minutes each, on an idle box with nothing else running.

- [ ] **Step 3: Compare each round against the Task 1 baseline**

```bash
d=docs/superpowers/evidence/2026-09-02-phase-d-portfolio
for r in 1 2 3; do
  echo "== round $r"
  uv run python scripts/audit_compare.py "$d/baseline-budget30.jsonl" \
    "$d/wall-budget30-round$r.jsonl" --p95-seconds 30 --expect-cells 72
done
```

Expected: `p95 ... s` at or under 30.0 in every round. `compare` counts every non-CLEAN row as a failure, so a `FAIL REFUSED:` line for a cell that was already refusing in the baseline is expected and is not a Gate D1 failure — Gate D1 is about the wall, and Step 4 is what judges it.

- [ ] **Step 4: Extract the wall figures the gate actually judges**

```bash
uv run python - <<'EOF'
import json, math, pathlib
d = pathlib.Path("docs/superpowers/evidence/2026-09-02-phase-d-portfolio")
base = {(r["strategy"], r["url_id"], r["spec_index"]): r
        for r in map(json.loads, (d / "baseline-budget30.jsonl").open())}
for r_i in (1, 2, 3):
    rows = [json.loads(l) for l in (d / f"wall-budget30-round{r_i}.jsonl").open()]
    secs = sorted(x["seconds"] for x in rows)
    p95 = secs[min(len(secs) - 1, math.ceil(0.95 * len(secs)) - 1)]
    clean = sum(x["status"] == "CLEAN" for x in rows)
    regressed = [
        f'{x["strategy"]} {x["url_id"]}/{x["spec_label"]}'
        for x in rows
        if x["status"] != "CLEAN"
        and base.get((x["strategy"], x["url_id"], x["spec_index"]), {}).get("status") == "CLEAN"
    ]
    print(f"round{r_i}: clean {clean}/72  p95 {p95:.2f}s  max {secs[-1]:.2f}s  "
          f"invalid {sum(x['status'] == 'INVALID' for x in rows)}  "
          f"crash {sum(x['status'] == 'CRASH' for x in rows)}  regressed {regressed}")
    for x in sorted((y for y in rows if y["seconds"] > 30.0), key=lambda y: -y["seconds"]):
        print(f"    {x['seconds']:6.2f}s {x['strategy']:14s} {x['url_id']}/{x['spec_label']} {x['status']}")
EOF
```

Expected, per round: `max` at or under 35.00 s, `p95` at or under 30.00 s, `invalid 0`, `crash 0`, `regressed []`. The Phase A figures this must beat are `p95` 30.53/30.67/30.37 and `max` 34.77/38.97/40.29.

- [ ] **Step 5: Write the gate record**

`gate-d1.md` contains, and nothing else: the commit under test and the baseline commit from Task 1; the three `audit_compare.py` output lines verbatim; the Step 4 block verbatim; the `quantum-chip/no-proliferator` sequence-pair row's `seconds` for each round beside the Phase A values 34.77 / 38.97 / 40.29; and one line per Gate D1 condition stating pass or fail.

- [ ] **Step 6: Commit**

```bash
git add docs/superpowers/evidence/2026-09-02-phase-d-portfolio
git commit -m "bench: record the phase D wall discipline gate at 30s"
```

If any round misses a Gate D1 condition, commit under `bench: record a failed phase D wall discipline gate`, with `gate-d1.md` naming the failing cells and their `detail` strings, and report before starting Task 8.

---

### Task 8: Race messages, channels, and pickling

**Files:**
- Create: `src/flab2bp/layout/strategy_race.py`
- Create: `tests/layout/test_strategy_race.py`

**Interfaces:**
- Consumes: `flab2bp.spec.BuildSpec`; `flab2bp.layout.band_policy.BandPolicy`; `flab2bp.layout.base.{Placement, ProjectionFailureRecord}`; `flab2bp.layout.compact_seed.CompactSeedConfig`; `flab2bp.layout.sequence_solver.SequenceSolverConfig`; `flab2bp.layout.strip_variants.StripInstanceId`; `flab2bp.dsp.catalog.DEFAULT_MAX_BELT_Z`; the fixture `two_stage_spec()` at `tests/layout/test_freeform.py:183`, which `tests/layout/test_sequence_islands.py` already imports the same way.
- Produces: `RACE_STRATEGIES`, `RACE_COMPLETION_GRACE_S`, `RACE_QUEUE_MAXSIZE`, `RACE_DRAIN_MAX_MESSAGES`, `RACE_FREEFORM_WORKER_SHARE`, `RACE_MIN_WORKERS`, `race_worker_split`, `_MessageQueue`, `IncumbentMessage`, `NoGoodMessage`, `RaceMessage`, `RaceChannels`, `_StrategyRaceRequest`, `_StrategyRaceOutcome`, `_ordered`. Tasks 9 to 15 build on every one of them.

- [ ] **Step 1: Write the failing tests**

```python
# tests/layout/test_strategy_race.py
from __future__ import annotations

import pickle
import queue
from dataclasses import fields
from fractions import Fraction

import pytest

from flab2bp.dsp import catalog
from flab2bp.layout.band_policy import BandPolicy
from flab2bp.layout.compact_seed import CompactSeedConfig
from flab2bp.layout.sequence_solver import SequenceSolverConfig
from flab2bp.layout.strategy_race import (
    RACE_DRAIN_MAX_MESSAGES,
    RaceStrategyName,
    RACE_MIN_WORKERS,
    RACE_QUEUE_MAXSIZE,
    RACE_STRATEGIES,
    IncumbentMessage,
    NoGoodMessage,
    RaceChannels,
    _ordered,
    _StrategyRaceOutcome,
    _StrategyRaceRequest,
    race_worker_split,
)
from flab2bp.layout.strip_variants import StripFamilyId, StripInstanceId
from tests.layout.test_freeform import two_stage_spec


def _request(strategy: RaceStrategyName = "freeform") -> _StrategyRaceRequest:
    return _StrategyRaceRequest(
        spec=two_stage_spec(),
        strategy=strategy,
        time_budget_s=30.0,
        soft_deadline=1234.5,
        band_policy=BandPolicy("portable"),
        belt_vertical_construction=True,
        max_belt_z=catalog.DEFAULT_MAX_BELT_Z,
        workers=6,
        arrangements=None,
        sequence_islands=1,
        config=SequenceSolverConfig(),
        compact_seed_config=CompactSeedConfig(),
        share=True,
    )


def test_the_request_round_trips_through_pickle() -> None:
    request = _request()

    assert pickle.loads(pickle.dumps(request)) == request


def test_the_request_carries_no_queue() -> None:
    # A multiprocessing.Queue cannot be pickled as a pool TASK argument.  Putting
    # one in the request fails ONLY under spawn, which is exactly the mode
    # production uses and the mode a fast unit test does not.
    names = {field.name for field in fields(_StrategyRaceRequest)}

    assert not {name for name in names if "queue" in name or "channel" in name}


def test_every_request_field_is_read_by_a_racer() -> None:
    # `power` was in an earlier draft and is deliberately absent: both lay_out
    # implementations hard-code powered emission, so the field would be a knob
    # that does not turn.
    assert {field.name for field in fields(_StrategyRaceRequest)} == {
        "spec",
        "strategy",
        "time_budget_s",
        "soft_deadline",
        "band_policy",
        "belt_vertical_construction",
        "max_belt_z",
        "workers",
        "arrangements",
        "sequence_islands",
        "config",
        "compact_seed_config",
        "share",
    }


@pytest.mark.parametrize(
    "outcome",
    [
        _StrategyRaceOutcome("freeform", "refused", refusal_reason="deadline exhausted"),
        _StrategyRaceOutcome("sequence-pair", "terminated", refusal_reason="overran"),
        _StrategyRaceOutcome("freeform", "crashed", refusal_reason="ValueError: x"),
    ],
)
def test_outcomes_round_trip_through_pickle(outcome: _StrategyRaceOutcome) -> None:
    assert pickle.loads(pickle.dumps(outcome)) == outcome


def test_messages_round_trip_through_pickle() -> None:
    incumbent = IncumbentMessage("freeform", (480, 62))
    no_good = NoGoodMessage(
        "freeform",
        (StripInstanceId(StripFamilyId("iron-ingot", 0), 0, 4),),
        no_good=("relation", 0, 1),
    )

    assert pickle.loads(pickle.dumps(incumbent)) == incumbent
    assert pickle.loads(pickle.dumps(no_good)) == no_good


def test_the_incumbent_message_is_one_key_not_three_numbers() -> None:
    # `area` and `belt_tiles` as separate fields would be the same two numbers a
    # second time, and `height` had no reader at all.
    assert {field.name for field in fields(IncumbentMessage)} == {"strategy", "exact_key"}


def test_channels_publish_drain_and_drop() -> None:
    channels = RaceChannels(
        publish=queue.Queue(maxsize=2),
        consume=queue.Queue(maxsize=RACE_QUEUE_MAXSIZE),
    )
    first = IncumbentMessage("freeform", (480, 62))
    second = IncumbentMessage("freeform", (470, 60))
    third = IncumbentMessage("freeform", (460, 58))

    channels.publish_incumbent(first)
    channels.publish_incumbent(second)
    channels.publish_incumbent(third)   # queue is full: dropped, not raised

    assert channels.dropped == 1

    inbound = RaceChannels(publish=queue.Queue(), consume=channels.publish)

    assert inbound.drain() == (first, second)
    assert inbound.drain() == ()


def test_drain_is_bounded_per_poll() -> None:
    consume: queue.Queue[object] = queue.Queue()
    for area in range(RACE_DRAIN_MAX_MESSAGES + 5):
        consume.put(IncumbentMessage("freeform", (area, 0)))
    channels = RaceChannels(publish=queue.Queue(), consume=consume)

    assert len(channels.drain()) == RACE_DRAIN_MAX_MESSAGES
    assert len(channels.drain()) == 5


@pytest.mark.parametrize(
    ("total", "expected"),
    [
        (1, (1, 1)),
        (2, (1, 1)),
        (3, (2, 1)),
        (4, (3, 1)),
        (8, (6, 2)),
        (16, (12, 4)),
        (128, (96, 32)),
    ],
)
def test_the_worker_split_never_hands_a_racer_zero(
    total: int, expected: tuple[int, int]
) -> None:
    # ortools reads num_search_workers == 0 as ALL CORES, so a split that ever
    # produced 0 would hand one racer the whole box.
    split = race_worker_split(total)

    assert split == expected
    assert min(split) >= RACE_MIN_WORKERS


def test_the_worker_split_refuses_a_nonsense_total() -> None:
    with pytest.raises(ValueError, match="positive integer"):
        race_worker_split(0)


def test_outcomes_are_ordered_by_strategy_not_by_arrival() -> None:
    late = _StrategyRaceOutcome("freeform", "refused", refusal_reason="f")
    early = _StrategyRaceOutcome("sequence-pair", "refused", refusal_reason="s")

    assert tuple(o.strategy for o in _ordered((early, late))) == RACE_STRATEGIES


def test_the_race_runs_exactly_the_two_production_strategies() -> None:
    assert RACE_STRATEGIES == ("freeform", "sequence-pair")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/layout/test_strategy_race.py -q`
Expected: collection FAILS with `ModuleNotFoundError: No module named 'flab2bp.layout.strategy_race'`

- [ ] **Step 3: Write the module's data layer**

```python
# src/flab2bp/layout/strategy_race.py
"""Race the two production strategies for one wall budget, sharing what they prove.

``pipeline.build(strategy="best")`` used to run freeform and then sequence-pair,
each with the FULL budget, and throw the loser's work away.  This module runs
both concurrently in spawned children for ONE budget and lets each tell the
other what it has certified and what it has proved impossible.

The process shape is deliberately the one ``sequence_islands.py`` already runs in
production: a frozen, ``slots=True`` request that is the whole pickled unit; a
frozen outcome that flattens ``NoValidLayout`` in the child rather than pickling
an exception; a spawn-context ``ProcessPoolExecutor`` with
``max_tasks_per_child=1``; one ``wait`` in the parent; and OS-level termination
for whatever is still running when the wall runs out.
"""

from __future__ import annotations

import queue
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Literal, Protocol, TypeAlias

from flab2bp.dsp import catalog
from flab2bp.layout.band_policy import BandPolicy
from flab2bp.layout.base import Placement, ProjectionFailureRecord
from flab2bp.layout.compact_seed import CompactSeedConfig
from flab2bp.layout.sequence_solver import SequenceSolverConfig
from flab2bp.layout.strip_variants import StripInstanceId
from flab2bp.spec import BuildSpec

RaceStrategyName: TypeAlias = Literal["freeform", "sequence-pair"]

#: The portfolio, in the order outcomes are returned.  Same membership and same
#: order as ``pipeline.PRODUCTION_STRATEGIES``; named here so this module does
#: not import ``pipeline``, which imports it.
RACE_STRATEGIES: tuple[RaceStrategyName, ...] = ("freeform", "sequence-pair")

#: Seconds past the soft deadline the parent waits before killing a racer.
#: MEASURED, not guessed: Task 9 records this box's spawn-to-first-instruction
#: cost and sets this to ``ceil(that) + ATOMIC_COMPLETION_GRACE_S``.  It is
#: deliberately NOT ``sequence_islands._ISLAND_COMPLETION_GRACE_S``, which is
#: 90.0: a grace that large is a second budget.
RACE_COMPLETION_GRACE_S = 6.0

#: Messages a direction may hold before publishing starts dropping.  A dropped
#: message costs a hint and never a result, so a bound is strictly better than a
#: block: a full queue must never make a racer wait on its rival.
RACE_QUEUE_MAXSIZE = 64

#: Messages a receiver takes per poll, so a burst cannot turn a poll into a pause.
RACE_DRAIN_MAX_MESSAGES = 32

#: Freeform's ``_pack`` is the only multi-threaded CP-SAT solve in the tree; every
#: sequence-pair sub-solve is pinned to one worker (``compact_seed`` twice, the
#: freeform tie-break, and ``DETERMINISTIC_WORKERS``).  So the split is mostly a
#: bound on freeform, and its share is the larger one.
RACE_FREEFORM_WORKER_SHARE = Fraction(3, 4)

#: Never zero: ortools reads ``num_search_workers == 0`` as ALL CORES.
RACE_MIN_WORKERS = 1


def race_worker_split(total: int) -> tuple[int, int]:
    """Split ``total`` CP-SAT search workers into (freeform, sequence-pair)."""
    if type(total) is not int or total < 1:
        raise ValueError("racing worker total must be a positive integer")
    if total <= 2:
        return (RACE_MIN_WORKERS, RACE_MIN_WORKERS)
    freeform = max(
        RACE_MIN_WORKERS,
        total * RACE_FREEFORM_WORKER_SHARE.numerator
        // RACE_FREEFORM_WORKER_SHARE.denominator,
    )
    return (freeform, max(RACE_MIN_WORKERS, total - freeform))


class _MessageQueue(Protocol):
    """The two methods this module needs from a queue.

    ``multiprocessing.Queue`` and ``queue.Queue`` both satisfy it and share no
    base class, which is what lets one ``RaceChannels`` serve the real race and
    the in-process tests without an ``Any`` or a ``type: ignore``.
    """

    def put_nowait(self, item: object, /) -> None: ...

    def get_nowait(self) -> object: ...


@dataclass(frozen=True, slots=True)
class IncumbentMessage:
    """A validator-clean placement one arm proved, offered to the other as a bound.

    ``exact_key`` is ``(area, belt_tiles)`` -- the same tuple freeform's ``_sweep``
    keeps as ``best_key`` and ``sequence_solver._exact_key`` returns -- which is
    why one schema serves both directions.  It is ONE field: carrying ``area``
    and ``belt_tiles`` separately would be the same two numbers a second time.
    """

    strategy: str
    exact_key: tuple[int, int]


@dataclass(frozen=True, slots=True)
class NoGoodMessage:
    """A proved-impossible cluster relation, with the identity it is keyed by.

    ``instance_ids`` is the assertion: a receiver applies the no-good only when
    every named instance is one of its own CURRENT planned strips.
    ``StripInstanceId`` embeds ``family_id``, ``machine_start`` and
    ``machine_count``, so a receiver that sharded its strips differently fails
    the predicate by construction.

    ``no_good`` is typed ``object`` on purpose: this module is a transport and
    must import at a commit where Phase B's ``ClusterRelationNoGood`` may not
    exist.  The receiver, which does know the type, is what applies it.
    """

    strategy: str
    instance_ids: tuple[StripInstanceId, ...]
    no_good: object


RaceMessage: TypeAlias = IncumbentMessage | NoGoodMessage


@dataclass
class RaceChannels:
    """One racer's end of the two queues: what it publishes, what it consumes."""

    publish: _MessageQueue
    consume: _MessageQueue
    _dropped: int = field(default=0, init=False)

    @property
    def dropped(self) -> int:
        return self._dropped

    def _put(self, message: RaceMessage) -> None:
        try:
            self.publish.put_nowait(message)
        except queue.Full:
            self._dropped += 1

    def publish_incumbent(self, message: IncumbentMessage) -> None:
        self._put(message)

    def publish_no_good(self, message: NoGoodMessage) -> None:
        self._put(message)

    def drain(self) -> tuple[RaceMessage, ...]:
        taken: list[RaceMessage] = []
        while len(taken) < RACE_DRAIN_MAX_MESSAGES:
            try:
                item = self.consume.get_nowait()
            except queue.Empty:
                break
            if isinstance(item, IncumbentMessage | NoGoodMessage):
                taken.append(item)
        return tuple(taken)

    def close(self) -> None:
        """Let this process exit without waiting for a reader that is not coming.

        A ``multiprocessing.Queue`` with unflushed data blocks its process's exit
        until something reads it, and after the deadline there is nothing to.
        """
        canceller = getattr(self.publish, "cancel_join_thread", None)
        if canceller is not None:
            canceller()


@dataclass(frozen=True, slots=True)
class _StrategyRaceRequest:
    """Plain pickleable inputs for one racer.  No queue: see ``run_strategy_race``."""

    spec: BuildSpec
    #: The same alias ``RACE_STRATEGIES`` is typed with, so a third name is a
    #: type error rather than a message nobody reads.
    strategy: RaceStrategyName
    time_budget_s: float
    #: An ABSOLUTE ``time.monotonic()`` value taken in the parent.  Valid because
    #: Linux CLOCK_MONOTONIC is system-wide; ``sequence_islands`` already relies
    #: on exactly this, passing its own ``soft_deadline`` into a child as
    #: ``absolute_deadline``.
    soft_deadline: float
    band_policy: BandPolicy
    belt_vertical_construction: bool
    #: For the child's OWN ``validate.validate`` before it publishes an
    #: incumbent: the bound must meet the standard the parent will apply.
    max_belt_z: Fraction
    workers: int
    arrangements: int | None
    sequence_islands: int
    config: SequenceSolverConfig
    compact_seed_config: CompactSeedConfig
    share: bool


@dataclass(frozen=True, slots=True)
class _StrategyRaceOutcome:
    """One arm's exact result, honest refusal, kill, or crash."""

    strategy: str
    status: Literal["completed", "refused", "invalid", "terminated", "crashed"]
    placement: Placement | None = None
    refusal_reason: str | None = None
    refusal_spec_label: str = ""
    refusal_budget_s: float = 0.0
    refusal_projection_failures: tuple[ProjectionFailureRecord, ...] = ()
    published_incumbents: int = 0
    consumed_incumbents: int = 0
    published_no_goods: int = 0
    consumed_no_goods: int = 0
    dropped_messages: int = 0

    @classmethod
    def refused(
        cls,
        strategy: str,
        reason: str,
        spec_label: str,
        budget_s: float,
        *,
        projection_failures: tuple[ProjectionFailureRecord, ...] = (),
    ) -> _StrategyRaceOutcome:
        return cls(
            strategy,
            "refused",
            refusal_reason=reason,
            refusal_spec_label=spec_label,
            refusal_budget_s=budget_s,
            refusal_projection_failures=projection_failures,
        )


def _ordered(outcomes: Sequence[_StrategyRaceOutcome]) -> tuple[_StrategyRaceOutcome, ...]:
    """Return outcomes in ``RACE_STRATEGIES`` order, never in completion order."""
    by_strategy = {outcome.strategy: outcome for outcome in outcomes}
    return tuple(by_strategy[name] for name in RACE_STRATEGIES if name in by_strategy)


#: Referenced so ``catalog`` is not an unused import: the default belt ceiling a
#: caller gets when it does not know the URL's technology set.
DEFAULT_RACE_MAX_BELT_Z = catalog.DEFAULT_MAX_BELT_Z
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/layout/test_strategy_race.py -q`
Expected: `20 passed` — ten unparametrised tests, three `test_outcomes_round_trip_through_pickle` cases, and seven `test_the_worker_split_never_hands_a_racer_zero` cases.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check src/flab2bp/layout/strategy_race.py tests/layout/test_strategy_race.py
uv run mypy src/flab2bp/layout/strategy_race.py tests/layout/test_strategy_race.py
git add src/flab2bp/layout/strategy_race.py tests/layout/test_strategy_race.py
git commit -m "feat(layout): add the strategy race request, outcome, and message channels"
```

---

### Task 9: The race executor, the child's absolute deadline, and the measured grace

**Files:**
- Modify: `src/flab2bp/layout/strategy_race.py`
- Modify: `src/flab2bp/layout/freeform.py` (`FreeformLayout.lay_out` at `:15568`, its `deadline = started + ceiling` at `:15610`)
- Modify: `src/flab2bp/layout/sequence_solver.py` (`SequencePairLayout.lay_out` at `:5210`)
- Modify: `src/flab2bp/layout/base.py` (`LayoutStrategy.lay_out` at `:461`)
- Modify: `tests/conftest.py` (`_Layout` at `:48-49`, `_key` at `:57-71`, `_install_memo`'s wrapper at `:74-99`)
- Create: `scripts/spawn_cost.py`
- Create: `docs/superpowers/evidence/2026-09-02-phase-d-portfolio/spawn-cost.txt`
- Test: `tests/layout/test_strategy_race.py`, `tests/layout/test_freeform.py`, `tests/layout/test_sequence_solver.py`

**Interfaces:**
- Consumes: everything Task 8 produced; `sequence_islands._terminate_executor`'s behaviour (copied, not imported); `flab2bp.layout.base.{NoValidLayout, ATOMIC_COMPLETION_GRACE_S}`; `FreeformLayout(band_policy, *, workers, arrangements, belt_vertical_construction)`; `SequencePairLayout(band_policy, *, belt_vertical_construction, config, compact_seed_config, islands)`; `_production_run(..., absolute_deadline: float | None = None)`.
- Produces: `FreeformLayout.lay_out(spec, *, time_budget_s=15.0, absolute_deadline: float | None = None)`; `SequencePairLayout.lay_out(spec, *, time_budget_s=15.0, absolute_deadline: float | None = None)`; `RaceSubmit: TypeAlias`; `_install_race_channels`, `_channels_for`, `_run_race_leg`, `_terminate_executor`, `_pool_submit`, `run_strategy_race`. Task 10 hooks publication into `_run_race_leg`; Task 13 wraps `run_strategy_race` in `RacingLayout`.

- [ ] **Step 1: Write the failing `absolute_deadline` tests**

Append to `tests/layout/test_freeform.py`:

```python
def test_lay_out_honours_an_absolute_deadline_from_another_process() -> None:
    """A child cannot compute its own wall: it starts spawn-cost seconds late.

    An absolute deadline already in the past must refuse immediately rather than
    run for `time_budget_s` more seconds.
    """
    import time as _time

    from flab2bp.layout.freeform import FreeformLayout

    layout = FreeformLayout(band_policy=BandPolicy("portable"))
    started = _time.monotonic()

    with pytest.raises(NoValidLayout):
        layout.lay_out(
            two_stage_spec(),
            time_budget_s=30.0,
            absolute_deadline=_time.monotonic() - 1.0,
        )

    assert _time.monotonic() - started < 10.0, (
        "an expired absolute deadline must not buy a fresh 30s budget"
    )
```

Append to `tests/layout/test_sequence_solver.py`:

```python
def test_sequence_lay_out_honours_an_absolute_deadline_from_another_process() -> None:
    import time as _time

    layout = SequencePairLayout(band_policy=BandPolicy("portable"))
    started = _time.monotonic()

    with pytest.raises(NoValidLayout):
        layout.lay_out(
            two_stage_spec(),
            time_budget_s=30.0,
            absolute_deadline=_time.monotonic() - 1.0,
        )

    assert _time.monotonic() - started < 10.0
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/layout/test_freeform.py tests/layout/test_sequence_solver.py -q -k "absolute_deadline_from_another_process"`
Expected: both FAIL with `TypeError: lay_out() got an unexpected keyword argument 'absolute_deadline'`

- [ ] **Step 3: Give both layouts an absolute deadline**

In `FreeformLayout.lay_out`, add the keyword-only parameter and derive the deadline from it:

```python
    def lay_out(
        self,
        spec: BuildSpec,
        *,
        time_budget_s: float = 15.0,
        absolute_deadline: float | None = None,
    ) -> Placement:
```

and replace `deadline = started + ceiling` with:

```python
        # A racing child starts the budget its PARENT started, so it must be
        # told the wall rather than compute one: spawn, interpreter start and
        # unpickling the spec all happen after the clock began.  Same expression
        # `sequence_solver._production_run` already uses for the same reason.
        deadline = started + ceiling if absolute_deadline is None else absolute_deadline
```

In `SequencePairLayout.lay_out`, add the same keyword-only parameter and pass it straight through to the `_production_run(...)` call as `absolute_deadline=absolute_deadline`; `_production_run` already has the parameter and already prefers it over `started + ceiling`. The `islands > 1` branch keeps its own deadline arithmetic — islands inside a raced child are bounded by the child's own budget, and `run_sequence_islands` does not take an absolute deadline.

Add `absolute_deadline: float | None = None` to `base.LayoutStrategy.lay_out`'s protocol signature so both implementations still satisfy it.

- [ ] **Step 4: Widen the test suite's memo wrapper, which otherwise breaks every test**

`tests/conftest.py` replaces `FreeformLayout.lay_out` process-wide with a memoising wrapper (`_install_memo(FreeformLayout)`), and that wrapper's signature is `(self, spec, *, time_budget_s=15.0)`. The moment anything passes `absolute_deadline`, every test that reaches freeform raises `TypeError: lay_out() got an unexpected keyword argument 'absolute_deadline'`. Three edits, all in `tests/conftest.py`:

```python
class _Layout(Protocol):
    def lay_out(
        self,
        spec: BuildSpec,
        *,
        time_budget_s: float = 15.0,
        absolute_deadline: float | None = None,
    ) -> Placement: ...
```

```python
def _key(
    layout: _Layout,
    spec: BuildSpec,
    time_budget_s: float,
    absolute_deadline: float | None,
) -> tuple[str, ...]:
    return (
        f"{type(layout).__module__}.{type(layout).__qualname__}",
        repr(sorted(vars(layout).items(), key=lambda kv: kv[0])),
        spec.model_dump_json(),
        repr(time_budget_s),
        # An absolute deadline changes the result, so it MUST be in the key: a
        # memo that omits an input returns the wrong answer, which is worse than
        # being slow.  `None` and a float are distinct keys.
        repr(absolute_deadline),
    )
```

```python
    @functools.wraps(original)
    def lay_out(
        self: _Layout,
        spec: BuildSpec,
        *,
        time_budget_s: float = 15.0,
        absolute_deadline: float | None = None,
    ) -> Placement:
        if not _enabled:
            return original(
                self,
                spec,
                time_budget_s=time_budget_s,
                absolute_deadline=absolute_deadline,
            )
        key = _key(self, spec, time_budget_s, absolute_deadline)
        try:
            hit = _CACHE[key]
        except KeyError:
            try:
                hit = original(
                    self,
                    spec,
                    time_budget_s=time_budget_s,
                    absolute_deadline=absolute_deadline,
                )
            except NoValidLayout as refusal:
                hit = refusal
            _CACHE[key] = hit
        if isinstance(hit, NoValidLayout):
            raise hit
        return hit
```

`SequencePairLayout` is not memoised (`_install_memo` is called only for `FreeformLayout`), so it needs no change here.

- [ ] **Step 5: Type-check the whole project and fix every flagged protocol double**

```bash
uv run mypy 2>&1 | tail -3
```

Expected: the same locked baseline of 176 errors, no more. Widening `lay_out` changes the arity a `LayoutStrategy` must satisfy, so strict mypy may flag the doubles at `tests/scripts/test_audit.py:106`, `:185`, `:311`, `:424` (values in a dict typed `Callable[[int, bool], LayoutStrategy]`) and `tests/scripts/test_ab_compare.py:93`, `:153` (`monkeypatch.setitem` values, typed `Callable[[bool], LayoutStrategy]`). Decision rule: for each double mypy names, add `absolute_deadline: float | None = None` to that double's `lay_out` — do not silence with `type: ignore`, and do not edit a double mypy did not name. Re-run until the count is back to 176 and record the number of doubles edited in the commit message.

- [ ] **Step 6: Run them to verify they pass**

Run: `uv run pytest tests/layout/test_freeform.py tests/layout/test_sequence_solver.py -q -k "absolute_deadline_from_another_process"`
Expected: 2 passed

- [ ] **Step 7: Measure this box's spawn cost and set the grace**

The measurement cannot run from a heredoc. Under the `spawn` start method the
child re-imports `__main__` by path, and a script fed on stdin has
`__file__ == "<stdin>"`, so the pool fails before it measures anything. Write it
to a file:

```python
# scripts/spawn_cost.py
"""Spawn-to-first-instruction cost, which comes out of a racer's wall budget.

    uv run python scripts/spawn_cost.py

A racing child starts the budget its PARENT started, so whatever it spends
starting is search it does not get.  `RACE_COMPLETION_GRACE_S` is sized from the
worst case here plus `ATOMIC_COMPLETION_GRACE_S`.
"""

from __future__ import annotations

import math
import multiprocessing
import time
from concurrent.futures import ProcessPoolExecutor

ATOMIC_COMPLETION_GRACE_S = 5.0
SPAWNS = 10


def entered(submitted: float) -> float:
    """Runs in the child; the first thing it does is read the clock."""
    return time.monotonic() - submitted


def main() -> int:
    costs: list[float] = []
    for _ in range(SPAWNS):
        with ProcessPoolExecutor(
            max_workers=2,
            mp_context=multiprocessing.get_context("spawn"),
            max_tasks_per_child=1,
        ) as pool:
            submitted = time.monotonic()
            costs.append(pool.submit(entered, submitted).result())
    costs.sort()
    grace = math.ceil(costs[-1]) + ATOMIC_COMPLETION_GRACE_S
    print(
        f"spawns {len(costs)}  min {costs[0]:.3f}s  "
        f"median {costs[len(costs) // 2]:.3f}s  max {costs[-1]:.3f}s"
    )
    print(
        f"RACE_COMPLETION_GRACE_S = ceil(max) + ATOMIC_COMPLETION_GRACE_S = "
        f"{math.ceil(costs[-1])} + {ATOMIC_COMPLETION_GRACE_S} = {grace}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

```bash
uv run python scripts/spawn_cost.py \
  | tee docs/superpowers/evidence/2026-09-02-phase-d-portfolio/spawn-cost.txt
```

Expected: a `max` well under one second, so the printed grace is `6.0` and the
constant Task 8 already wrote is correct. Decision rule: if the printed value
differs from `6.0`, edit `RACE_COMPLETION_GRACE_S` to the printed number and say
so in the commit message — the measurement, not the guess, is what ships. This
script does not import `flab2bp`, so it times the interpreter start alone; the
`BuildSpec` unpickle is charged on top and is covered by the `ceil` to a whole
second.

- [ ] **Step 8: Write the failing executor tests**

Append to `tests/layout/test_strategy_race.py`:

```python
class _NoopExecutor:
    """Stands in for the pool.  Class-level flag so a test can see the kill."""

    terminated = False

    def shutdown(self, wait: bool = True, cancel_futures: bool = False) -> None:
        return None

    def terminate_workers(self) -> None:
        type(self).terminated = True


def _stub_submit(results: dict[str, object]):
    """Resolve both legs synchronously; `None` means "never returns"."""
    from concurrent.futures import Future

    def submit(requests, channels):
        futures: dict[Future[_StrategyRaceOutcome], str] = {}
        for request in requests:
            future: Future[_StrategyRaceOutcome] = Future()
            outcome = results[request.strategy]
            if isinstance(outcome, BaseException):
                future.set_exception(outcome)
            elif outcome is not None:
                assert isinstance(outcome, _StrategyRaceOutcome)
                future.set_result(outcome)
            futures[future] = request.strategy
        return futures, _NoopExecutor()

    return submit


def _race(results: dict[str, object], **kwargs: object) -> tuple[_StrategyRaceOutcome, ...]:
    from flab2bp.layout.strategy_race import run_strategy_race

    return run_strategy_race(
        two_stage_spec(),
        time_budget_s=0.05,
        band_policy=BandPolicy("portable"),
        belt_vertical_construction=True,
        submit=_stub_submit(results),
        **kwargs,
    )


def test_both_arms_return_in_strategy_order() -> None:
    outcomes = _race(
        {
            "sequence-pair": _StrategyRaceOutcome("sequence-pair", "refused", refusal_reason="s"),
            "freeform": _StrategyRaceOutcome("freeform", "refused", refusal_reason="f"),
        }
    )

    assert tuple(o.strategy for o in outcomes) == ("freeform", "sequence-pair")


def test_a_crashed_arm_is_reported_and_the_survivor_decides() -> None:
    outcomes = _race(
        {
            "freeform": ValueError("boom"),
            "sequence-pair": _StrategyRaceOutcome("sequence-pair", "refused", refusal_reason="s"),
        }
    )
    crashed = next(o for o in outcomes if o.strategy == "freeform")

    assert crashed.status == "crashed"
    assert "ValueError: boom" in (crashed.refusal_reason or "")
    assert next(o for o in outcomes if o.strategy == "sequence-pair").status == "refused"


def test_two_crashed_arms_reraise_the_first_in_strategy_order() -> None:
    # freeform is first in RACE_STRATEGIES, so its exception is the one that
    # propagates -- deterministically, not by `done`-set iteration order.
    with pytest.raises(ValueError, match="boom"):
        _race({"freeform": ValueError("boom"), "sequence-pair": KeyError("other")})


def test_an_arm_that_ignores_the_wall_is_terminated() -> None:
    _NoopExecutor.terminated = False
    # A fake clock, so the test does not sit out RACE_COMPLETION_GRACE_S.  The
    # first call sets `started`; every later one is already past the hard
    # deadline, so `wait` is entered with timeout 0.0 and returns at once.
    ticks = iter([0.0] + [10_000.0] * 8)
    outcomes = _race(
        {
            "freeform": None,
            "sequence-pair": _StrategyRaceOutcome("sequence-pair", "refused", refusal_reason="s"),
        },
        monotonic=lambda: next(ticks),
    )
    stuck = next(o for o in outcomes if o.strategy == "freeform")

    assert stuck.status == "terminated"
    assert "was terminated" in (stuck.refusal_reason or "")
    assert _NoopExecutor.terminated is True


def test_share_false_creates_no_channels() -> None:
    seen: list[int] = []

    def submit(requests, channels):
        from concurrent.futures import Future

        seen.append(len(channels))
        futures = {}
        for request in requests:
            future: Future[_StrategyRaceOutcome] = Future()
            future.set_result(
                _StrategyRaceOutcome(request.strategy, "refused", refusal_reason="x")
            )
            futures[future] = request.strategy
        return futures, _NoopExecutor()

    from flab2bp.layout.strategy_race import run_strategy_race

    run_strategy_race(
        two_stage_spec(),
        time_budget_s=0.05,
        band_policy=BandPolicy("portable"),
        belt_vertical_construction=True,
        share=False,
        submit=submit,
    )

    assert seen == [0], "share=False must not build queues the pool cannot pickle"


def test_the_worker_split_reaches_the_requests() -> None:
    seen: dict[str, int] = {}

    def submit(requests, channels):
        from concurrent.futures import Future

        futures = {}
        for request in requests:
            seen[request.strategy] = request.workers
            future: Future[_StrategyRaceOutcome] = Future()
            future.set_result(
                _StrategyRaceOutcome(request.strategy, "refused", refusal_reason="x")
            )
            futures[future] = request.strategy
        return futures, _NoopExecutor()

    from flab2bp.layout.strategy_race import run_strategy_race

    run_strategy_race(
        two_stage_spec(),
        time_budget_s=0.05,
        band_policy=BandPolicy("portable"),
        belt_vertical_construction=True,
        workers=8,
        submit=submit,
    )

    assert seen == {"freeform": 6, "sequence-pair": 2}
```

- [ ] **Step 9: Run them to verify they fail**

Run: `uv run pytest tests/layout/test_strategy_race.py -q -k "arms or wall or split_reaches or share_false"`
Expected: every one FAILS with `ImportError: cannot import name 'run_strategy_race' from 'flab2bp.layout.strategy_race'`

- [ ] **Step 10: Add the child-side leg**

Append to `src/flab2bp/layout/strategy_race.py`:

```python
#: Set by the pool initializer in each child; ``None`` in the parent and when
#: sharing is off.  A module global rather than a request field because a
#: ``multiprocessing.Queue`` cannot be pickled as a TASK argument -- it reaches a
#: child only through ``Process(args=...)``, which is what ``initargs`` becomes.
_RACE_CHANNELS: dict[str, RaceChannels] | None = None


def _install_race_channels(to_freeform: object, to_sequence_pair: object) -> None:
    """Pool initializer: give this child both ends, keyed by who reads which."""
    global _RACE_CHANNELS
    freeform_in = cast(_MessageQueue, to_freeform)
    sequence_in = cast(_MessageQueue, to_sequence_pair)
    _RACE_CHANNELS = {
        "freeform": RaceChannels(publish=sequence_in, consume=freeform_in),
        "sequence-pair": RaceChannels(publish=freeform_in, consume=sequence_in),
    }


def _channels_for(strategy: str) -> RaceChannels | None:
    return None if _RACE_CHANNELS is None else _RACE_CHANNELS.get(strategy)


def _build_layout(
    request: _StrategyRaceRequest,
) -> FreeformLayout | SequencePairLayout:
    from flab2bp.layout.freeform import FreeformLayout
    from flab2bp.layout.sequence_solver import SequencePairLayout

    if request.strategy == "freeform":
        return FreeformLayout(
            band_policy=request.band_policy,
            workers=request.workers,
            arrangements=request.arrangements,
            belt_vertical_construction=request.belt_vertical_construction,
        )
    return SequencePairLayout(
        band_policy=request.band_policy,
        belt_vertical_construction=request.belt_vertical_construction,
        config=request.config,
        compact_seed_config=request.compact_seed_config,
        islands=request.sequence_islands,
    )


def _run_race_leg(request: _StrategyRaceRequest) -> _StrategyRaceOutcome:
    """Reconstruct and run one whole strategy inside a child."""
    from flab2bp.layout.base import NoValidLayout

    channels = _channels_for(request.strategy) if request.share else None
    layout = _build_layout(request)
    try:
        placement = layout.lay_out(
            request.spec,
            time_budget_s=request.time_budget_s,
            absolute_deadline=request.soft_deadline,
        )
    except NoValidLayout as exc:
        return _StrategyRaceOutcome.refused(
            request.strategy,
            exc.reason,
            exc.spec_label,
            exc.budget_s,
            projection_failures=exc.projection_failures,
        )
    finally:
        if channels is not None:
            channels.close()
    return _StrategyRaceOutcome(
        request.strategy,
        "completed",
        placement=placement,
        dropped_messages=0 if channels is None else channels.dropped,
    )
```

Add to the imports: `from typing import TYPE_CHECKING, Literal, Protocol, TypeAlias, cast`, and under `if TYPE_CHECKING:` the two layout classes for the return annotation of `_build_layout`.

- [ ] **Step 11: Add the parent-side race**

```python
RaceSubmit: TypeAlias = Callable[
    [tuple[_StrategyRaceRequest, ...], dict[str, RaceChannels]],
    tuple[dict["Future[_StrategyRaceOutcome]", str], object],
]


def _available_cores() -> int:
    """Cores this process may actually use, Linux-first, with a fallback.

    ``sched_getaffinity`` is Linux-only, so it is probed rather than assumed --
    the same guard ``scripts/audit.py:_available_cores`` already uses.
    """
    affinity = getattr(os, "sched_getaffinity", None)
    if affinity is not None:
        return len(affinity(0)) or 4
    return os.cpu_count() or 4


def _terminate_executor(
    executor: object,
    futures: Sequence["Future[_StrategyRaceOutcome]"],
) -> None:
    """Stop whatever is still running, without waiting for its solve ceiling.

    Copied from ``sequence_islands._terminate_executor`` rather than imported:
    the two callers have the same need today, and a change made for islands must
    not silently change what racing does to a live CP-SAT child.
    """
    for future in futures:
        _ = future.cancel()
    try:
        cast(ProcessPoolExecutor, executor).terminate_workers()
    except BaseException:
        try:
            cast(ProcessPoolExecutor, executor).kill_workers()
        except BaseException:
            cast(ProcessPoolExecutor, executor).shutdown(wait=False, cancel_futures=True)


def _pool_submit(
    requests: tuple[_StrategyRaceRequest, ...],
    channels: dict[str, RaceChannels],
) -> tuple[dict["Future[_StrategyRaceOutcome]", str], object]:
    # An EMPTY `channels` means sharing is off.  The initializer is then omitted
    # entirely rather than handed empty queues: only a `multiprocessing.Queue`
    # survives the spawn hand-off, so passing anything else in `initargs` fails
    # at pickling in the parent.
    extra: dict[str, object] = (
        {}
        if not channels
        else {
            "initializer": _install_race_channels,
            "initargs": (channels["freeform"].consume, channels["sequence-pair"].consume),
        }
    )
    executor = ProcessPoolExecutor(
        max_workers=len(RACE_STRATEGIES),
        mp_context=multiprocessing.get_context("spawn"),
        max_tasks_per_child=1,
        **extra,  # type: ignore[arg-type]
    )
    futures: dict[Future[_StrategyRaceOutcome], str] = {}
    for request in requests:
        futures[executor.submit(_run_race_leg, request)] = request.strategy
    return futures, executor


def run_strategy_race(
    spec: BuildSpec,
    *,
    time_budget_s: float,
    band_policy: BandPolicy,
    belt_vertical_construction: bool,
    max_belt_z: Fraction = DEFAULT_RACE_MAX_BELT_Z,
    workers: int | None = None,
    arrangements: int | None = None,
    sequence_islands: int = 1,
    config: SequenceSolverConfig | None = None,
    compact_seed_config: CompactSeedConfig | None = None,
    share: bool = True,
    submit: RaceSubmit | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> tuple[_StrategyRaceOutcome, ...]:
    """Run both strategies concurrently for ONE budget and return both outcomes.

    The first validator-clean result deliberately does NOT stop the race: the
    other arm may still find something smaller, and ``pipeline.build`` picks the
    winner by ``min(area)`` over whatever both produced.
    """
    if time_budget_s <= 0:
        raise ValueError("racing requires a positive time budget")
    # One queue per direction is a complete graph only for TWO arms, and
    # `_install_race_channels` keys exactly two.  A third strategy must fail
    # loudly here rather than silently receive nothing.
    if len(RACE_STRATEGIES) != 2:
        raise ValueError("the race queue topology is defined for exactly two strategies")
    started = monotonic()
    soft_deadline = started + time_budget_s
    hard_deadline = soft_deadline + RACE_COMPLETION_GRACE_S
    freeform_workers, sequence_workers = race_worker_split(
        _available_cores() if workers is None else workers
    )
    workers_by_strategy = {
        "freeform": freeform_workers,
        "sequence-pair": sequence_workers,
    }
    channels: dict[str, RaceChannels] = {}
    if share:
        context = multiprocessing.get_context("spawn")
        to_freeform = context.Queue(maxsize=RACE_QUEUE_MAXSIZE)
        to_sequence_pair = context.Queue(maxsize=RACE_QUEUE_MAXSIZE)
        channels = {
            "freeform": RaceChannels(publish=to_sequence_pair, consume=to_freeform),
            "sequence-pair": RaceChannels(publish=to_freeform, consume=to_sequence_pair),
        }
    requests = tuple(
        _StrategyRaceRequest(
            spec=spec,
            strategy=name,
            time_budget_s=time_budget_s,
            soft_deadline=soft_deadline,
            band_policy=band_policy,
            belt_vertical_construction=belt_vertical_construction,
            max_belt_z=max_belt_z,
            workers=workers_by_strategy[name],
            arrangements=arrangements,
            sequence_islands=sequence_islands,
            config=config or SequenceSolverConfig(),
            compact_seed_config=compact_seed_config or CompactSeedConfig(),
            share=share,
        )
        for name in RACE_STRATEGIES
    )
    try:
        futures, executor = (submit or _pool_submit)(requests, channels)
        strategy_by_future = dict(futures)
        done, not_done = wait(
            tuple(strategy_by_future),
            timeout=max(0.0, hard_deadline - monotonic()),
        )
        del done
        if not_done:
            _terminate_executor(executor, tuple(strategy_by_future))
        else:
            cast(ProcessPoolExecutor, executor).shutdown(wait=True, cancel_futures=False)
        outcomes: list[_StrategyRaceOutcome] = []
        first_error: BaseException | None = None
        # Walked in RACE_STRATEGIES order, never in `done` order: `done` is a
        # set, and letting its iteration decide which of two crashed arms is
        # re-raised would make a failing race report a different exception run
        # to run.
        for name in RACE_STRATEGIES:
            future = next(
                (item for item, strategy in strategy_by_future.items() if strategy == name),
                None,
            )
            if future is None:
                continue
            if future in not_done:
                outcomes.append(
                    _StrategyRaceOutcome(
                        name,
                        "terminated",
                        refusal_reason=(
                            f"{name} overran the {time_budget_s:g}s budget by more than "
                            f"{RACE_COMPLETION_GRACE_S:g}s and was terminated"
                        ),
                        refusal_spec_label=spec.label,
                        refusal_budget_s=time_budget_s,
                    )
                )
                continue
            error = future.exception()
            if error is not None:
                first_error = first_error or error
                outcomes.append(
                    _StrategyRaceOutcome(
                        name,
                        "crashed",
                        refusal_reason=(
                            f"{name} strategy process failed: "
                            f"{type(error).__name__}: {error}"
                        ),
                    )
                )
                continue
            outcomes.append(future.result())
    finally:
        # Always, even on an exception: an unflushed queue holds its feeder
        # thread, and a held feeder thread holds this process open.
        for side in channels.values():
            side.close()
    if first_error is not None and all(
        outcome.status == "crashed" for outcome in outcomes
    ):
        raise first_error
    return _ordered(outcomes)
```

Add to the module imports:

```python
import multiprocessing
import os
import time
from collections.abc import Callable
from concurrent.futures import Future, ProcessPoolExecutor, wait
```

- [ ] **Step 12: Run the tests to verify they pass**

Run: `uv run pytest tests/layout/test_strategy_race.py -q`
Expected: all pass

- [ ] **Step 13: Prove the real pool works end to end on one small cell**

```bash
uv run python -c "
import sys; sys.path.insert(0, 'src')
from flab2bp.bench.corpus import URL_CORPUS
from flab2bp.lab.data import load_vendored
from flab2bp.lab.url import parse_url
from flab2bp.layout.band_policy import BandPolicy
from flab2bp.layout.strategy_race import run_strategy_race
from flab2bp.rates import DEFAULT_CANDIDATE_POLICIES, build_candidates
entry = next(e for e in URL_CORPUS if e.url_id == 'iron-ingot')
spec = build_candidates(load_vendored(), parse_url(entry.url),
                        candidate_policies=DEFAULT_CANDIDATE_POLICIES).candidates[0]
for o in run_strategy_race(spec, time_budget_s=10.0, band_policy=BandPolicy('portable'),
                           belt_vertical_construction=True, workers=8):
    print(o.strategy, o.status, None if o.placement is None else o.placement.area, o.refusal_reason)
"
```

Expected: two lines, both `completed` with an integer area, in under 17 s (10 s budget plus the measured grace).

- [ ] **Step 14: Lint, type-check, commit**

```bash
uv run ruff check src/flab2bp/layout tests/layout
uv run mypy src/flab2bp/layout/strategy_race.py src/flab2bp/layout/freeform.py src/flab2bp/layout/sequence_solver.py src/flab2bp/layout/base.py
git add src/flab2bp/layout tests/layout docs/superpowers/evidence/2026-09-02-phase-d-portfolio
git commit -m "feat(layout): race both strategies in spawned processes on the parent's wall"
```

---

### Task 10: Publish and consume incumbent bounds

**Files:**
- Modify: `src/flab2bp/layout/strategy_race.py` (`_run_race_leg`)
- Modify: `src/flab2bp/layout/freeform.py` (`FreeformLayout.__init__` at `:15533`, `_sweep`'s soft-deadline computation and its incumbent update at `:16973-16980`)
- Modify: `src/flab2bp/layout/sequence_solver.py` (`SequenceSolver.__init__` at `:874`, `search` at `:1036`, `_complete_routing_stage` at `:2204`, `_production_run` at `:4804`, `SequencePairLayout.__init__` at `:5179`)
- Test: `tests/layout/test_strategy_race.py`, `tests/layout/test_freeform.py`, `tests/layout/test_sequence_solver.py`

**Interfaces:**
- Consumes: `IncumbentMessage`, `RaceChannels`, `_install_race_channels`, `_channels_for` (Task 8/9); `Placement.area`; `Placement.stats["belt_tiles"]`; `sequence_solver._exact_key(placement) -> tuple[int, int]` (`:3010`); `PlacementProblem.area_lower_bound` (`sequence_pair.py:85`); `validate.validate(placement, spec, *, ids, expect_power, max_belt_z, belt_vertical_construction)` and `validate.id_map(spec)`; the fixtures `_FakeRouting` and `_solver` in `tests/layout/test_sequence_solver.py`.
- Produces: `freeform._portfolio_soft_deadline(soft, external_key, best_key, now) -> float` and the `improvement_soft` local in `_sweep`; `FreeformLayout(..., portfolio_incumbent, publish_incumbent)`; `SequencePairLayout(..., portfolio_incumbent, publish_incumbent)`; `SequenceSolver(..., portfolio_area, publish_incumbent)` and `SequenceSolver._portfolio_pruned`; the termination string `"portfolio-bound"`.

**The two consumption rules, and why they differ.**

*Freeform.* `_sweep` exits its candidate loop only by `break`, and a `break` taken with `best is None` ends the sweep with nothing — so an external incumbent must not gate any of them, or it could manufacture a refusal. It is therefore carried in a **separate value, `improvement_soft`**, read at the four sites that are already guarded by `best is not None` and nowhere else. `soft` itself is **never rebound**: two `_room_for_another` sites have no `best` guard — `projection_retry_affordable` (`freeform.py:16144`, called from `:16535`, `:16569`, `:16618`, `:16925`, `:16928`) and the learned-retry promotion at `:16721` — and both are finding paths, deliberately exempt from the soft-deadline breaks, each of which reads `if not projection_retry and ...` (`:16299`, `:16304`, `:16308`, `:16319`). Rebinding `soft` would set it to `now` for the rest of the sweep and refuse every retry, so a spec that only routes after a retry would refuse under racing where the unraced arm succeeds. The rule also compares the external key against freeform's own `best_key` and pulls in only when the external one is at least as good: an incumbent this sweep has already beaten is not a reason to stop polishing.

*Sequence-pair.* Prunes heights on `area_lower_bound`, **strictly** greater than the incumbent's area: there is no per-height lower bound on belt tiles, and the winner is `(area, belt_tiles)` lexicographic, so `>=` would prune exactly the heights that could still tie on area and win on belts.

- [ ] **Step 1: Write the failing freeform tests**

Append to `tests/layout/test_freeform.py`:

```python
def test_the_portfolio_soft_deadline_only_shortens_and_only_for_a_better_bound() -> None:
    """Four cases, and none of them may LENGTHEN the improvement share."""
    from flab2bp.layout.freeform import _portfolio_soft_deadline

    # No bound at all: the sweep's own soft, untouched.
    assert _portfolio_soft_deadline(100.0, None, None, 40.0) == 100.0
    # A bound, no own best yet: pulled in.  (All four read sites are guarded by
    # `best is not None`, so this value is not actually read in that state; the
    # function is still defined for it rather than raising.)
    assert _portfolio_soft_deadline(100.0, (480, 62), None, 40.0) == 40.0
    # A bound BETTER than ours: pulled in.
    assert _portfolio_soft_deadline(100.0, (480, 62), (500, 70.0), 40.0) == 40.0
    # A bound WORSE than ours: it tells us nothing, so nothing moves.
    assert _portfolio_soft_deadline(100.0, (520, 62), (500, 70.0), 40.0) == 100.0
    # An exact tie counts as "at least as good", so it still pulls in.
    assert _portfolio_soft_deadline(100.0, (500, 70), (500, 70.0), 40.0) == 40.0
    # Never pushed OUT, even by a better bound.
    assert _portfolio_soft_deadline(30.0, (480, 62), (500, 70.0), 40.0) == 30.0


@pytest.mark.slow
def test_a_portfolio_bound_never_shortens_a_retry_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`projection_retry_affordable` must keep reading the sweep's own `soft`.

    `_sweep` has two `_room_for_another` sites with NO `best is not None` guard
    -- `projection_retry_affordable` (`freeform.py:16144`, called from `:16535`,
    `:16569`, `:16618`, `:16925`, `:16928`) and the learned-retry promotion at
    `:16721`.  Both are finding paths, deliberately exempt from the soft-deadline
    breaks, each of which is spelled `if not projection_retry and ...`.  If an
    external bound rebound the enclosing `soft`, every retry for the rest of the
    sweep would be refused and a spec that only routes after a retry would refuse
    under racing where the unraced arm succeeds.

    The spy records the `soft` each call site is handed.  Under a bound there
    must be at least two DISTINCT values: the pulled-in improvement deadline and
    the sweep's own, still-later `soft`.

    `monkeypatch` is requested for a second reason besides patching: the autouse
    `_layout_memo_policy` fixture in `tests/conftest.py:120-133` disables the
    layout memo for any test that requests it, so this run is a real solve and
    not a cached placement from an earlier test.
    """
    import flab2bp.layout.freeform as freeform_module
    from flab2bp.layout.freeform import FreeformLayout

    seen: list[float] = []
    original = freeform_module._room_for_another

    def spying(deadline: float | None, soft: float, candidate_s: float) -> bool:
        seen.append(soft)
        return original(deadline, soft, candidate_s)

    monkeypatch.setattr(freeform_module, "_room_for_another", spying)

    placement = FreeformLayout(
        band_policy=BandPolicy("portable"),
        portfolio_incumbent=lambda: (1, 1),
    ).lay_out(two_stage_spec(), time_budget_s=20.0)

    assert placement.area > 0, "an external bound must never cost the placement"
    assert seen, "the sweep must reach _room_for_another at least once"
    assert len(set(seen)) >= 2, (
        "every call saw the same soft, so the improvement deadline was written "
        "back over the sweep's own -- projection_retry_affordable is now bound "
        "by the external incumbent"
    )
    assert max(seen) > min(seen), "the un-pulled soft must still be the later one"
```

**Verification step, with its command and decision rule.** The final assertion holds only if this spec's sweep reaches BOTH kinds of site. Learn that first:

```bash
uv run python - <<'EOF'
import sys
sys.path.insert(0, "src"); sys.path.insert(0, ".")
import flab2bp.layout.freeform as f
from flab2bp.layout.band_policy import BandPolicy
from tests.layout.test_freeform import two_stage_spec

seen = []
original = f._room_for_another
def spying(deadline, soft, candidate_s):
    seen.append(soft)
    return original(deadline, soft, candidate_s)
f._room_for_another = spying
f.FreeformLayout(
    band_policy=BandPolicy("portable"), portfolio_incumbent=lambda: (1, 1)
).lay_out(two_stage_spec(), time_budget_s=20.0)
print("calls:", len(seen), "distinct soft values:", len(set(seen)))
EOF
```

Decision rule, in order:

1. `distinct soft values` is 2 or more — the test as written is correct. Keep it.
2. It is 1 — switch the spec to the first `plastic` candidate, built exactly as
   Task 9 Step 11 builds `iron-ingot`, and re-run the probe.
3. Still 1 on `plastic` — this sweep never reaches a finding-path call, so the
   two `len(set(seen))` and `max/min` assertions have nothing to distinguish and
   must be replaced rather than weakened. Replace them with a direct spy on the
   improvement value:

```python
    calls: list[tuple[float, float]] = []
    original_rule = freeform_module._portfolio_soft_deadline

    def recording(soft, external_key, best_key, now):
        result = original_rule(soft, external_key, best_key, now)
        calls.append((soft, result))
        return result

    monkeypatch.setattr(freeform_module, "_portfolio_soft_deadline", recording)
    # ... run lay_out as above ...
    assert calls, "the improvement deadline must be computed at least once"
    assert all(result <= soft for soft, result in calls)
    assert any(soft in seen for soft, _result in calls), (
        "the sweep's own soft must still reach _room_for_another unpulled"
    )
```

Record which of the three the run took, and the counts, in the commit message.

- [ ] **Step 2: Write the failing sequence-pair tests**

Append to `tests/layout/test_sequence_solver.py`. `search()` **raises** `NoValidLayout` when no incumbent was found, so the pruning outcome is asserted on the refusal reason, not on a returned `termination` field.

```python
def _two_height_solver(
    fake: _FakeRouting, *, area_lower_bounds: tuple[int, int]
) -> SequenceSolver[Prepared]:
    """A solver whose two heights have DIFFERENT area lower bounds.

    `_solver` gives every height `area_lower_bound=1`, which cannot express a
    bound one height clears and the other does not.
    """
    bounds = dict(zip((40, 60), area_lower_bounds, strict=True))
    return SequenceSolver(
        heights=(40, 60),
        problem_for_height=lambda height: PlacementProblem(
            sizes=((1, 1),),
            nets=((0, 0),),
            outline_height=height,
            area_lower_bound=bounds[height],
        ),
        adapters=fake.adapters(),
        expansion_budget=ExpansionBudget(total=1_000),
        config=SequenceSolverConfig(
            stages=6, moves_per_stage=1, restarts_per_height=2, global_elites=1
        ),
    )


def test_the_solver_prunes_only_heights_the_bound_strictly_beats() -> None:
    solver = _two_height_solver(_FakeRouting(), area_lower_bounds=(400, 900))
    solver.portfolio_area = lambda: 500

    pruned = [h.height for h in solver._heights if solver._portfolio_pruned(h)]
    kept = [h.height for h in solver._heights if not solver._portfolio_pruned(h)]

    assert pruned == [60] and kept == [40]


def test_a_height_that_can_still_tie_on_area_survives_pruning() -> None:
    """Strict `>`: an equal-area placement with fewer belt tiles still wins.

    `area_lower_bound` is an area and there is no per-height lower bound on belt
    tiles, so `>=` would prune exactly the heights that could produce the tie.
    """
    solver = _two_height_solver(_FakeRouting(), area_lower_bounds=(500, 501))
    solver.portfolio_area = lambda: 500

    assert not solver._portfolio_pruned(solver._heights[0])
    assert solver._portfolio_pruned(solver._heights[1])


def test_a_fully_pruned_search_refuses_naming_the_portfolio_bound() -> None:
    solver = _two_height_solver(_FakeRouting(), area_lower_bounds=(400, 900))
    solver.portfolio_area = lambda: 100

    with pytest.raises(NoValidLayout, match="area lower bound"):
        solver.search()


def test_no_portfolio_bound_prunes_nothing() -> None:
    solver = _two_height_solver(_FakeRouting(), area_lower_bounds=(400, 900))

    assert not any(solver._portfolio_pruned(h) for h in solver._heights)
```

- [ ] **Step 3: Write the failing channel test**

Append to `tests/layout/test_strategy_race.py`:

```python
def test_an_incumbent_published_by_one_arm_reaches_the_other() -> None:
    from flab2bp.layout.strategy_race import _channels_for, _install_race_channels

    to_freeform: queue.Queue[object] = queue.Queue(maxsize=RACE_QUEUE_MAXSIZE)
    to_sequence_pair: queue.Queue[object] = queue.Queue(maxsize=RACE_QUEUE_MAXSIZE)
    _install_race_channels(to_freeform, to_sequence_pair)

    freeform = _channels_for("freeform")
    sequence = _channels_for("sequence-pair")
    assert freeform is not None and sequence is not None

    freeform.publish_incumbent(IncumbentMessage("freeform", (480, 62)))

    assert sequence.drain() == (IncumbentMessage("freeform", (480, 62)),)
    assert freeform.drain() == (), "a publisher must not read its own message"
```

- [ ] **Step 4: Run all three groups to verify they fail**

Run: `uv run pytest tests/layout/test_freeform.py tests/layout/test_sequence_solver.py tests/layout/test_strategy_race.py -q -k "portfolio or incumbent_published or pruning or prunes"`
Expected: `test_the_portfolio_soft_deadline_only_shortens_and_only_for_a_better_bound` FAILS with `ImportError: cannot import name '_portfolio_soft_deadline'` and `test_a_portfolio_bound_never_shortens_a_retry_decision` with `TypeError: FreeformLayout.__init__() got an unexpected keyword argument 'portfolio_incumbent'`; the sequence-pair four FAIL with `AttributeError: 'SequenceSolver' object has no attribute '_portfolio_pruned'`; `test_an_incumbent_published_by_one_arm_reaches_the_other` PASSES already, because Task 9 added `_install_race_channels` — keep it, it is the regression guard for the queue wiring.

- [ ] **Step 5: Add the freeform hooks**

Above `class FreeformLayout`:

```python
def _portfolio_soft_deadline(
    soft: float,
    external_key: tuple[int, int] | None,
    best_key: tuple[int, float] | None,
    now: float,
) -> float:
    """The IMPROVEMENT deadline, which is NEVER this sweep's own ``soft``.

    ``soft`` is the sweep's own share and is what stops it improving; the hard
    ``deadline`` is what stops it entirely.  The value returned here is bound to
    a SEPARATE name and read only at the four sites already guarded by ``best is
    not None`` -- never written back over ``soft``.  Two ``_room_for_another``
    sites have no such guard, ``projection_retry_affordable`` and the
    learned-retry promotion, and both are finding paths that the soft-deadline
    breaks deliberately exempt (``if not projection_retry and ...``).  Setting
    ``soft`` itself would refuse every retry for the rest of the sweep, and a
    spec that only routes after a retry would then refuse under racing where the
    unraced arm succeeds -- a refusal manufactured by another process.

    A bound WORSE than what this sweep already holds moves nothing: an incumbent
    we have already beaten is not a reason to stop polishing.  Both keys are
    ``(area, belt_tiles)`` in that order, so ``>`` is the same lexicographic rule
    ``best_key`` is selected by.
    """
    if external_key is None:
        return soft
    if best_key is not None and external_key > best_key:
        return soft
    return min(soft, now)
```

In `FreeformLayout.__init__`, add two keyword-only parameters and store them:

```python
        portfolio_incumbent: Callable[[], tuple[int, int] | None] | None = None,
        publish_incumbent: Callable[[Placement], None] | None = None,
```

```python
        #: The best ``(area, belt_tiles)`` another racing strategy has certified,
        #: or ``None``.  A SCHEDULING input only: it never enters ``best_key``,
        #: so it can never select or reject a placement.
        self.portfolio_incumbent = portfolio_incumbent
        #: Called with each placement this sweep certifies, so the other racer
        #: can use it as a bound.
        self.publish_incumbent = publish_incumbent
```

In `_sweep`, at the top of the `while candidate_index < len(candidate_packs):` body, before the existing `if started_at is not None:` charge block, bind a **new local** — do not assign to `soft`:

```python
            # A SECOND deadline, never a replacement for `soft`.  See
            # `_portfolio_soft_deadline` for why rebinding `soft` would let
            # another process refuse this one's retries.
            improvement_soft = _portfolio_soft_deadline(
                soft,
                None if self.portfolio_incumbent is None else self.portfolio_incumbent(),
                best_key,
                time.monotonic(),
            )
```

Then replace `soft` with `improvement_soft` at exactly these four sites, and nowhere else:

| Site | Today | After |
|---|---|---|
| `:16200`, under the `:16198` `best is not None` guard | `_room_for_another(deadline, soft, dearest_candidate_s)` | `_room_for_another(deadline, improvement_soft, dearest_candidate_s)` |
| `:16301`, under the `:16299` `best is not None` guard | same | same substitution |
| `:16309`, the `:16307` arrangement arm reached only after the `:16304` `arrangement and best is None: break` | same | same substitution |
| `:16319` | `time.monotonic() >= soft` | `time.monotonic() >= improvement_soft` |

`soft` keeps its own value at its two remaining reads: `projection_retry_affordable` (`:16144`) and the learned-retry promotion (`:16721`). The loop guard at `:16198` keeps its `best is not None` term exactly as it is — an external incumbent adds no new exit from this loop.

Confirm the substitution is exactly four sites and no assignment:

```bash
git diff --no-ext-diff src/flab2bp/layout/freeform.py | grep -c "improvement_soft"
git diff --no-ext-diff src/flab2bp/layout/freeform.py | grep "^\+.*soft = " || echo "no rebinding of soft: correct"
```

Expected: the first prints `6` (one binding, one comment reference, four reads) and the second prints the `no rebinding` line. If the second prints a `+ soft = _portfolio_soft_deadline(...)` line, the blocking defect this table exists to prevent has been reintroduced.

At the incumbent update, publish after the assignment:

```python
                best, best_key = placement, key
                if self.publish_incumbent is not None:
                    self.publish_incumbent(placement)
```

- [ ] **Step 6: Add the sequence-pair hooks**

In `SequenceSolver.__init__`, add keyword-only parameters and store them:

```python
        portfolio_area: Callable[[], int | None] | None = None,
        publish_incumbent: Callable[[Placement], None] | None = None,
```

```python
        self.portfolio_area = portfolio_area
        self.publish_incumbent = publish_incumbent
```

Add the predicate beside `_has_stable_exact_incumbent`:

```python
    def _portfolio_pruned(self, height_state: _HeightState) -> bool:
        """Can this height still beat what the other racer already certified?

        STRICTLY greater, and on area alone.  ``area_lower_bound`` is the
        smallest area the height could possibly produce and there is no
        per-height lower bound on belt tiles, so the second component of the
        exact key has no counterpart here.  The winner is ``(area, belt_tiles)``
        lexicographic, so a placement of EQUAL area with fewer belt tiles beats
        the incumbent -- and ``>=`` would prune exactly the heights that could
        produce it.
        """
        if self.portfolio_area is None:
            return False
        bound = self.portfolio_area()
        return bound is not None and height_state.problem.area_lower_bound > bound
```

In `search`, filter both selection points. Replace the discovery lookup:

```python
            discovery = next(
                (
                    height
                    for height in self._heights
                    if height.stages == 0 and not self._portfolio_pruned(height)
                ),
                None,
            )
```

and the eligible comprehension and its empty branch:

```python
                eligible = [
                    height
                    for height in self._heights
                    if any(run.stages < self.config.stages for run in height.restarts)
                    and not self._portfolio_pruned(height)
                ]
                if not eligible:
                    termination = (
                        "portfolio-bound"
                        if any(self._portfolio_pruned(height) for height in self._heights)
                        else "candidates"
                    )
                    break
```

Add the reason to the table in the `self._incumbent is None` branch:

```python
                "portfolio-bound": (
                    "every scheduled height's area lower bound is above the "
                    "portfolio incumbent"
                ),
```

In `_complete_routing_stage`, publish where the incumbent is already recorded, immediately after `self._incumbent = _ExactIncumbent(...)`:

```python
                    if self.publish_incumbent is not None:
                        self.publish_incumbent(finalized)
```

- [ ] **Step 7: Thread the hooks through `SequencePairLayout` and `_production_run`**

`SequencePairLayout.__init__` gains `portfolio_incumbent: Callable[[], tuple[int, int] | None] | None = None` and `publish_incumbent: Callable[[Placement], None] | None = None`, stores them, and `lay_out` passes both into `_production_run`, which gains matching keyword-only parameters and forwards them into its `SequenceSolver(...)` construction:

```python
        portfolio_area=(
            None
            if portfolio_incumbent is None
            else lambda: _area_of(portfolio_incumbent())
        ),
        publish_incumbent=publish_incumbent,
```

with, beside `_exact_key`:

```python
def _area_of(exact_key: tuple[int, int] | None) -> int | None:
    """The area component of a portfolio bound, or ``None`` when there is none."""
    return None if exact_key is None else exact_key[0]
```

- [ ] **Step 8: Publish only what the parent would accept**

In `strategy_race._run_race_leg`, build the two callables and validate before publishing:

```python
    from flab2bp.layout import validate

    seen_keys: list[tuple[int, int]] = []
    published = 0
    consumed = 0

    def portfolio_incumbent() -> tuple[int, int] | None:
        nonlocal consumed
        if channels is None:
            return None
        for message in channels.drain():
            if isinstance(message, IncumbentMessage):
                consumed += 1
                seen_keys.append(message.exact_key)
        return min(seen_keys) if seen_keys else None

    def publish(placement: Placement) -> None:
        nonlocal published
        if channels is None:
            return
        # The PARENT's standard of proof, run in the child.  Freeform's in-sweep
        # report and sequence-pair's `validate.certify` are not it, and a bound
        # the parent will reject would prune the other arm on a promise nobody
        # keeps.  One extra validation per PUBLISHED incumbent, off the parent's
        # critical path.
        report = validate.validate(
            placement,
            request.spec,
            ids=validate.id_map(request.spec),
            expect_power=True,
            max_belt_z=request.max_belt_z,
            belt_vertical_construction=request.belt_vertical_construction,
        )
        if not report.ok:
            return
        belt_tiles = int(placement.stats.get("belt_tiles", 0))
        channels.publish_incumbent(
            IncumbentMessage(request.strategy, (placement.area, belt_tiles))
        )
        published += 1
```

Pass `portfolio_incumbent=portfolio_incumbent, publish_incumbent=publish` into both constructions in `_build_layout` — which therefore takes the two callables as parameters — and carry `published_incumbents=published, consumed_incumbents=consumed` into both the `completed` and the `refused` return of `_run_race_leg`.

- [ ] **Step 9: Run the tests to verify they pass**

Run: `uv run pytest tests/layout -q`
Expected: all pass

- [ ] **Step 10: Prove a bound crosses a real process boundary**

```bash
uv run python -c "
import sys; sys.path.insert(0, 'src')
from flab2bp.bench.corpus import URL_CORPUS
from flab2bp.lab.data import load_vendored
from flab2bp.lab.url import parse_url
from flab2bp.layout.band_policy import BandPolicy
from flab2bp.layout.strategy_race import run_strategy_race
from flab2bp.rates import DEFAULT_CANDIDATE_POLICIES, build_candidates
entry = next(e for e in URL_CORPUS if e.url_id == 'plastic')
spec = build_candidates(load_vendored(), parse_url(entry.url),
                        candidate_policies=DEFAULT_CANDIDATE_POLICIES).candidates[0]
for o in run_strategy_race(spec, time_budget_s=20.0, band_policy=BandPolicy('portable'),
                           belt_vertical_construction=True, workers=16):
    print(o.strategy, o.status, o.published_incumbents, o.consumed_incumbents, o.dropped_messages)
"
```

Expected: at least one arm reports `published_incumbents >= 1`. Decision rule: if both report 0, the publication hook is not on the certification path — re-check that `_sweep`'s `best, best_key = placement, key` and `_complete_routing_stage`'s `self._incumbent = ...` are the lines that were edited, and that the child's `validate.validate` is not rejecting placements the parent accepts (print `report.errors` in `publish` and re-run before changing anything else).

- [ ] **Step 11: Lint, type-check, commit**

```bash
uv run ruff check src/flab2bp/layout tests/layout
uv run mypy src/flab2bp/layout/strategy_race.py src/flab2bp/layout/freeform.py src/flab2bp/layout/sequence_solver.py
git add src/flab2bp/layout tests/layout
git commit -m "feat(layout): share validated incumbents between the racing strategies"
```

---

### Task 11: The no-good predicate, inbox, and message routing

**Files:**
- Modify: `src/flab2bp/layout/strategy_race.py` (`_run_race_leg`, plus the new predicate and inbox)
- Test: `tests/layout/test_strategy_race.py`

**Interfaces:**
- Consumes: `NoGoodMessage`, `RaceChannels`, `IncumbentMessage` (Task 8); `StripInstanceId(family_id: StripFamilyId, machine_start: int, machine_count: int)` (`strip_variants.py:480`).
- Produces: `NOGOOD_INBOX_MAX: int = 256`; `applicable_no_good(message: NoGoodMessage, planned: frozenset[StripInstanceId]) -> bool`; `_NoGoodInbox` with `offer(message)`, `applicable(planned) -> tuple[object, ...]`, and `dropped`; `_run_race_leg`'s `external_no_goods` and `publish_no_good` callables and the four message counters on the outcome.

This task has **no dependency on Phase B**: the payload is typed `object` and the tests use a stand-in. Task 12 is what connects it to real `ClusterRelationNoGood`s.

- [ ] **Step 1: Write the failing tests**

Append to `tests/layout/test_strategy_race.py`:

```python
def _instance(group: str, start: int, count: int) -> StripInstanceId:
    return StripInstanceId(StripFamilyId(group, 0), start, count)


def test_a_no_good_naming_only_planned_instances_is_applicable() -> None:
    from flab2bp.layout.strategy_race import applicable_no_good

    planned = frozenset({_instance("iron-ingot", 0, 4), _instance("iron-ingot", 4, 4)})
    message = NoGoodMessage("freeform", (_instance("iron-ingot", 0, 4),), no_good="a")

    assert applicable_no_good(message, planned) is True


def test_a_no_good_from_a_different_shard_or_family_is_dropped() -> None:
    from flab2bp.layout.strategy_race import applicable_no_good

    planned = frozenset({_instance("iron-ingot", 0, 8)})
    differently_sharded = NoGoodMessage(
        "freeform", (_instance("iron-ingot", 0, 4),), no_good="a"
    )
    different_family = NoGoodMessage(
        "freeform", (_instance("copper-ingot", 0, 8),), no_good="b"
    )

    assert applicable_no_good(differently_sharded, planned) is False
    assert applicable_no_good(different_family, planned) is False


def test_an_empty_no_good_is_dropped() -> None:
    from flab2bp.layout.strategy_race import applicable_no_good

    empty = NoGoodMessage("freeform", (), no_good="a")

    assert applicable_no_good(empty, frozenset({_instance("iron-ingot", 0, 4)})) is False


def test_the_inbox_decides_at_application_time_not_at_arrival() -> None:
    """A replan changes every StripInstanceId, so the predicate must re-run.

    `freeform.py:16179-16182` clears the LOCAL relation no-goods on a replan for
    exactly this reason: "these proofs carry offsets, widths, or relation rows
    from the old strip geometry... retaining them can forbid a relation the
    widened strip just made feasible."  A cross-process no-good is the same kind
    of proof and obeys the same rule.
    """
    from flab2bp.layout.strategy_race import _NoGoodInbox

    inbox = _NoGoodInbox()
    inbox.offer(NoGoodMessage("freeform", (_instance("iron-ingot", 0, 4),), no_good="a"))
    inbox.offer(NoGoodMessage("freeform", (_instance("iron-ingot", 0, 8),), no_good="b"))

    before_replan = frozenset({_instance("iron-ingot", 0, 4)})
    after_replan = frozenset({_instance("iron-ingot", 0, 8)})

    assert inbox.applicable(before_replan) == ("a",)
    assert inbox.applicable(after_replan) == ("b",)
    assert inbox.dropped == 0, "a message not applicable NOW may be applicable later"


def test_the_inbox_reports_messages_no_strip_set_can_ever_use() -> None:
    from flab2bp.layout.strategy_race import _NoGoodInbox

    inbox = _NoGoodInbox()
    inbox.offer(NoGoodMessage("freeform", (), no_good="a"))

    assert inbox.applicable(frozenset({_instance("iron-ingot", 0, 4)})) == ()
    assert inbox.dropped == 1, "an empty instance list can never match anything"


def test_the_inbox_is_bounded_and_evicts_the_oldest() -> None:
    """A held message is never discarded by matching, so the inbox needs a cap.

    Without one it grows for the whole solve on the receiver the identity
    predicate exists to protect: one whose strips never match.
    """
    from flab2bp.layout.strategy_race import NOGOOD_INBOX_MAX, _NoGoodInbox

    inbox = _NoGoodInbox()
    planned = frozenset({_instance("iron-ingot", 0, 4)})
    for index in range(NOGOOD_INBOX_MAX + 3):
        inbox.offer(
            NoGoodMessage("freeform", (_instance("iron-ingot", 0, 4),), no_good=index)
        )

    applicable = inbox.applicable(planned)

    assert len(applicable) == NOGOOD_INBOX_MAX
    assert inbox.dropped == 3
    assert applicable[0] == 3, "the three OLDEST were evicted, not the newest"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/layout/test_strategy_race.py -q -k "no_good or inbox"`
Expected: every one FAILS with `ImportError: cannot import name 'applicable_no_good' from 'flab2bp.layout.strategy_race'` or `... '_NoGoodInbox' ...`

- [ ] **Step 3: Add the predicate and the inbox**

Append to `src/flab2bp/layout/strategy_race.py`:

```python
def applicable_no_good(
    message: NoGoodMessage,
    planned: frozenset[StripInstanceId],
) -> bool:
    """May this receiver apply a no-good the other strategy proved?

    Only when every instance the no-good names is one of the receiver's OWN
    planned strips, judged against the set in force RIGHT NOW.  A
    ``StripInstanceId`` embeds the family, the machine start and the machine
    count, so a receiver that sharded the same recipe group differently -- or
    that has replanned since the message arrived -- fails this test by
    construction.  A dropped no-good costs a hint; an applied wrong one would
    forbid a legal placement.
    """
    if not message.instance_ids:
        return False
    return set(message.instance_ids) <= planned


#: No-goods held awaiting a strip set that matches them.  A held message is
#: never discarded by matching -- it may become applicable again after a replan
#: -- so without a bound the inbox grows for the whole solve on exactly the
#: receiver the identity predicate exists to protect: one whose strips never
#: match.  The OLDEST is dropped first, because a proof made earlier is the one
#: most likely to name strips a later replan has already invalidated.
NOGOOD_INBOX_MAX = 256


@dataclass
class _NoGoodInbox:
    """Holds UNDECIDED no-goods and re-judges them on every application.

    Deliberately NOT a set filtered once against a snapshot taken when planning
    finished: freeform replans strips mid-sweep, which changes every
    ``StripInstanceId``, and a message admitted against the old plan could
    forbid a relation the replanned strips just made feasible.
    """

    _held: deque[NoGoodMessage] = field(
        default_factory=lambda: deque(maxlen=NOGOOD_INBOX_MAX), init=False
    )
    _dropped: int = field(default=0, init=False)

    @property
    def dropped(self) -> int:
        return self._dropped

    def offer(self, message: NoGoodMessage) -> None:
        if not message.instance_ids:
            # Nothing names nothing: no strip set can ever match it.
            self._dropped += 1
            return
        if len(self._held) == NOGOOD_INBOX_MAX:
            # `deque(maxlen=...)` evicts silently; count it first so a receiver
            # that never matches anything is visible in the outcome.
            self._dropped += 1
        self._held.append(message)

    def applicable(self, planned: frozenset[StripInstanceId]) -> tuple[object, ...]:
        return tuple(
            message.no_good
            for message in self._held
            if applicable_no_good(message, planned)
        )
```

- [ ] **Step 4: Route both message kinds through the race leg**

In `_run_race_leg`, replace the `portfolio_incumbent` closure with one that routes both kinds, and add the two no-good callables:

```python
    inbox = _NoGoodInbox()
    published_no_goods = 0

    def _drain() -> None:
        nonlocal consumed
        if channels is None:
            return
        for message in channels.drain():
            if isinstance(message, IncumbentMessage):
                consumed += 1
                seen_keys.append(message.exact_key)
            else:
                inbox.offer(message)

    def portfolio_incumbent() -> tuple[int, int] | None:
        _drain()
        return min(seen_keys) if seen_keys else None

    def external_no_goods(planned: frozenset[StripInstanceId]) -> tuple[object, ...]:
        _drain()
        return inbox.applicable(planned)

    def publish_no_good(
        no_good: object, instances: tuple[StripInstanceId, ...]
    ) -> None:
        nonlocal published_no_goods
        if channels is None:
            return
        channels.publish_no_good(NoGoodMessage(request.strategy, instances, no_good))
        published_no_goods += 1
```

`external_no_goods` **takes the receiver's current strip set** — that is the whole point of Task 11 — so Task 12's receivers call it with their live strips rather than registering a snapshot.

Carry the counters into both returns of `_run_race_leg`:

```python
        published_no_goods=published_no_goods,
        consumed_no_goods=len(inbox.applicable(frozenset())),
        dropped_messages=(0 if channels is None else channels.dropped) + inbox.dropped,
```

`consumed_no_goods` is reported against the empty set — which is always `0` — until Task 12 gives the leg a live strip set to count against; leave the expression here so the field has exactly one writer, and Task 12 replaces the argument, not the line's shape.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/layout/test_strategy_race.py -q`
Expected: all pass

- [ ] **Step 6: Lint, type-check, commit**

```bash
uv run ruff check src/flab2bp/layout/strategy_race.py tests/layout/test_strategy_race.py
uv run mypy src/flab2bp/layout/strategy_race.py tests/layout/test_strategy_race.py
git add src/flab2bp/layout/strategy_race.py tests/layout/test_strategy_race.py
git commit -m "feat(layout): route cluster no-goods across the race under a strip identity predicate"
```

---

### Task 12: Wire the no-good channel into both receivers

**Requires Phase B and Phase C on the branch.** Phase B supplies `ClusterRelationNoGood` and its single construction site; Phase C supplies the two collections that consume cluster no-goods. Step 1 resolves every name this task needs by symbol lookup; the rest of the task is written against what Step 1 prints.

**Files:**
- Modify: `src/flab2bp/layout/strategy_race.py` (`_run_race_leg`, `_build_layout`)
- Modify: `src/flab2bp/layout/freeform.py` (`FreeformLayout.__init__`, `lay_out`, the `_pack` no-good assembly)
- Modify: `src/flab2bp/layout/sequence_solver.py` (`SequencePairLayout.__init__`, `_production_run`, the relation-exclusion assembly)
- Test: `tests/layout/test_freeform.py`, `tests/layout/test_sequence_solver.py`

**Interfaces:**
- Consumes: `applicable_no_good`, `_NoGoodInbox`, `_run_race_leg`'s `external_no_goods(planned) -> tuple[object, ...]` and `publish_no_good(no_good, instances)` (Task 11); `Strip.family_id: StripFamilyId | None`, `Strip.machine_start: int`, `Strip.machines: int` (`freeform.py:781-892`); `PlacementProblem.instance_ids` (`sequence_pair.py:86`); Phase B's `ClusterRelationNoGood` and Phase C's two no-good collections.
- Produces: `FreeformLayout(..., external_no_goods, publish_no_good)` and `SequencePairLayout(..., external_no_goods, publish_no_good)`, both `Callable | None` defaulting to `None`; the two call sites in each receiver.

- [ ] **Step 1: Resolve every Phase B and Phase C name this task touches**

```bash
uv run python - <<'EOF'
import dataclasses, importlib, inspect
try:
    last_mile = importlib.import_module("flab2bp.layout.last_mile")
except ModuleNotFoundError as exc:
    raise SystemExit(f"BLOCKED: Phase B has not landed: {exc}")
no_good = getattr(last_mile, "ClusterRelationNoGood", None)
if no_good is None:
    raise SystemExit("BLOCKED: last_mile has no ClusterRelationNoGood")
print("fields:", [(f.name, f.type) for f in dataclasses.fields(no_good)])
print(inspect.getsource(no_good)[:800])
EOF
grep -rn "ClusterRelationNoGood" src/flab2bp/
```

Decision rules, applied in order:

1. If the script prints `BLOCKED:`, stop and report. This task cannot be written honestly without Phase B, and nothing else in the plan depends on it.
2. The printed field list must contain exactly one field whose values are `StripInstanceId`s. Call that name `<IDS>` and substitute it for `instance_ids` wherever this task writes `no_good.instance_ids`. If the type names strips by integer index instead, stop and report: the message cannot be keyed by identity and the phase's identity assertion has no ground.
3. The `grep` output names one construction site (Phase B, in `last_mile.py`) — that is where `publish_no_good` goes — and one consumption site per strategy (Phase C, in `freeform.py` and `sequence_solver.py`) — those are where `external_no_goods(...)` is merged. Record all three `file:line` pairs in the commit message.

- [ ] **Step 2: Write the failing tests**

Append to `tests/layout/test_freeform.py`:

```python
def test_freeform_asks_for_external_no_goods_with_its_current_strips() -> None:
    """The receiver supplies the strip set; the predicate runs against it."""
    from flab2bp.layout.freeform import FreeformLayout
    from flab2bp.layout.strip_variants import StripInstanceId

    asked: list[frozenset[StripInstanceId]] = []

    layout = FreeformLayout(
        band_policy=BandPolicy("portable"),
        external_no_goods=lambda planned: (asked.append(planned), ())[1],
    )
    layout.lay_out(two_stage_spec(), time_budget_s=20.0)

    assert asked, "the no-good hook must be consulted at least once"
    assert all(isinstance(item, StripInstanceId) for planned in asked for item in planned)
```

Append to `tests/layout/test_sequence_solver.py`:

```python
def test_sequence_pair_asks_for_external_no_goods_with_its_current_instances() -> None:
    from flab2bp.layout.strip_variants import StripInstanceId

    asked: list[frozenset[StripInstanceId]] = []

    layout = SequencePairLayout(
        band_policy=BandPolicy("portable"),
        external_no_goods=lambda planned: (asked.append(planned), ())[1],
    )
    with contextlib.suppress(NoValidLayout):
        layout.lay_out(two_stage_spec(), time_budget_s=20.0)

    assert asked
    assert all(isinstance(item, StripInstanceId) for planned in asked for item in planned)
```

Add `import contextlib` to that module if it is not already imported.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/layout/test_freeform.py tests/layout/test_sequence_solver.py -q -k "asks_for_external_no_goods"`
Expected: both FAIL with `TypeError: __init__() got an unexpected keyword argument 'external_no_goods'`

- [ ] **Step 4: Add the two hooks to both layouts**

`FreeformLayout.__init__` and `SequencePairLayout.__init__` each gain, keyword-only:

```python
        external_no_goods: (
            Callable[[frozenset[StripInstanceId]], tuple[object, ...]] | None
        ) = None,
        publish_no_good: (
            Callable[[object, tuple[StripInstanceId, ...]], None] | None
        ) = None,
```

stored on `self` under the same names.

- [ ] **Step 5: Build the receiver's current strip identity, in both strategies**

Freeform's `Strip` carries `family_id`, `machine_start` and `machines` rather than a built `StripInstanceId`; this is the same three-argument construction `_staged_static_clearance_requirement` already makes at `freeform.py:2985`. Add a module-level helper beside `_portfolio_soft_deadline`:

```python
def _planned_instance_ids(strips: Sequence[Strip]) -> frozenset[StripInstanceId]:
    """The identity of the strips as planned RIGHT NOW.

    A strip with no ``family_id`` has no stable identity and so can never be
    named by a no-good; it is left out of the set rather than given a fake id.
    """
    return frozenset(
        StripInstanceId(strip.family_id, strip.machine_start, strip.machines)
        for strip in strips
        if strip.family_id is not None
    )
```

Sequence-pair reads them straight off the problem:

```python
def _problem_instance_ids(problem: PlacementProblem) -> frozenset[StripInstanceId]:
    return frozenset(problem.instance_ids)
```

- [ ] **Step 6: Merge inbound no-goods at each consumption site**

At the Phase C consumption site Step 1 located in `freeform.py`, immediately before the collection is handed to `_pack`:

```python
        if self.external_no_goods is not None:
            cluster_no_goods = tuple(cluster_no_goods) + self.external_no_goods(
                _planned_instance_ids(strips)
            )
```

and at the sequence-pair site:

```python
        if external_no_goods is not None:
            relation_no_goods = tuple(relation_no_goods) + external_no_goods(
                _problem_instance_ids(problem)
            )
```

Substitute the real collection names from Step 1 for `cluster_no_goods` and `relation_no_goods`, and `strips` / `problem` for whichever live variables hold the current plan at each site. If a site's collection is a `frozenset`, union instead of concatenating; if it is a `list`, `extend`.

- [ ] **Step 7: Publish at the construction site**

At the single Phase B site Step 1 located, beside the existing store:

```python
        if publish_no_good is not None:
            publish_no_good(no_good, tuple(no_good.<IDS>))
```

with `<IDS>` the field name Step 1 printed. `_production_run` gains matching keyword-only `external_no_goods` and `publish_no_good` parameters and `SequencePairLayout.lay_out` forwards its own.

- [ ] **Step 8: Give the race leg the receivers' hooks**

In `strategy_race._build_layout`, pass `external_no_goods=external_no_goods, publish_no_good=publish_no_good` into both constructions alongside the Task 10 pair, and in `_run_race_leg` replace the placeholder counter with one that counts what was actually handed out:

```python
    applied_no_goods: set[int] = set()

    def external_no_goods(planned: frozenset[StripInstanceId]) -> tuple[object, ...]:
        _drain()
        applicable = inbox.applicable(planned)
        applied_no_goods.update(id(item) for item in applicable)
        return applicable
```

and `consumed_no_goods=len(applied_no_goods)` in both returns.

- [ ] **Step 9: Run the tests to verify they pass**

Run: `uv run pytest tests/layout -q`
Expected: all pass

- [ ] **Step 10: Lint, type-check, commit**

```bash
uv run ruff check src/flab2bp/layout tests/layout
uv run mypy src/flab2bp/layout/strategy_race.py src/flab2bp/layout/freeform.py src/flab2bp/layout/sequence_solver.py
git add src/flab2bp/layout tests/layout
git commit -m "feat(layout): apply cross-race cluster no-goods against the current strip set"
```

---

### Task 13: `RacingLayout` and its merge rule

**Files:**
- Modify: `src/flab2bp/layout/strategy_race.py`
- Test: `tests/layout/test_strategy_race.py`

**Interfaces:**
- Consumes: `run_strategy_race` (Task 9); `sequence_solver._exact_key` (`:3010`); `flab2bp.layout.base.{NoValidLayout, LayoutStrategy}`; the fixture `_placement(*, area: int, belt_tiles: int, valid: bool = True) -> Placement` at `tests/layout/test_sequence_solver.py:128`.
- Produces: `RacingLayout(band_policy, *, workers=None, arrangements=None, belt_vertical_construction=True, sequence_islands=1, share=True, max_belt_z=DEFAULT_RACE_MAX_BELT_Z)` with `name = "best"`, `lay_out(spec, *, time_budget_s=15.0, absolute_deadline=None) -> Placement`, and `_merge(outcomes) -> Placement`. Task 15 registers it as an audit cell.

- [ ] **Step 1: Write the failing tests**

Append to `tests/layout/test_strategy_race.py`, importing the placement fixture the sequence-solver tests already define:

```python
from tests.layout.test_sequence_solver import _placement


def test_the_racing_layout_merges_by_exact_key_then_strategy_order() -> None:
    from flab2bp.layout.strategy_race import RacingLayout

    layout = RacingLayout(BandPolicy("portable"))
    small = _StrategyRaceOutcome(
        "sequence-pair", "completed", placement=_placement(area=400, belt_tiles=50)
    )
    large = _StrategyRaceOutcome(
        "freeform", "completed", placement=_placement(area=500, belt_tiles=40)
    )

    assert layout._merge((large, small)).area == 400


def test_the_racing_layout_breaks_an_exact_tie_by_strategy_order() -> None:
    from flab2bp.layout.strategy_race import RacingLayout

    layout = RacingLayout(BandPolicy("portable"))
    freeform = _placement(area=400, belt_tiles=50)
    sequence = _placement(area=400, belt_tiles=50)
    merged = layout._merge(
        (
            _StrategyRaceOutcome("sequence-pair", "completed", placement=sequence),
            _StrategyRaceOutcome("freeform", "completed", placement=freeform),
        )
    )

    assert merged is freeform, "ties go to the first name in RACE_STRATEGIES"


def test_the_racing_layout_prefers_fewer_belt_tiles_at_equal_area() -> None:
    from flab2bp.layout.strategy_race import RacingLayout

    layout = RacingLayout(BandPolicy("portable"))
    merged = layout._merge(
        (
            _StrategyRaceOutcome(
                "freeform", "completed", placement=_placement(area=400, belt_tiles=60)
            ),
            _StrategyRaceOutcome(
                "sequence-pair", "completed", placement=_placement(area=400, belt_tiles=50)
            ),
        )
    )

    assert merged.stats["belt_tiles"] == 50


def test_the_racing_layout_refuses_naming_both_arms() -> None:
    from flab2bp.layout.base import NoValidLayout
    from flab2bp.layout.strategy_race import RacingLayout

    layout = RacingLayout(BandPolicy("portable"))
    outcomes = (
        _StrategyRaceOutcome(
            "freeform", "refused", refusal_reason="no pack", refusal_spec_label="np"
        ),
        _StrategyRaceOutcome("sequence-pair", "terminated", refusal_reason="overran"),
    )

    with pytest.raises(NoValidLayout) as caught:
        layout._merge(outcomes)

    assert "freeform: no pack" in caught.value.reason
    assert "sequence-pair: overran" in caught.value.reason
    assert caught.value.spec_label == "np"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/layout/test_strategy_race.py -q -k "racing_layout"`
Expected: all four FAIL with `ImportError: cannot import name 'RacingLayout' from 'flab2bp.layout.strategy_race'`

- [ ] **Step 3: Add `RacingLayout`**

Append to `src/flab2bp/layout/strategy_race.py`:

```python
def _require_placement(outcome: _StrategyRaceOutcome) -> Placement:
    placement = outcome.placement
    if placement is None:
        raise RuntimeError(f"completed race leg {outcome.strategy} returned no placement")
    return placement


class RacingLayout:
    """``LayoutStrategy`` shim so one raced portfolio is a single audit cell.

    ``pipeline.build`` does NOT go through this class: it keeps both outcomes as
    two ``Attempt``s and picks by ``min(area)`` itself.  This exists for callers
    that want one placement out of a race -- the audit's ``best`` cell.
    """

    name = "best"

    def __init__(
        self,
        band_policy: BandPolicy,
        *,
        workers: int | None = None,
        arrangements: int | None = None,
        belt_vertical_construction: bool = True,
        sequence_islands: int = 1,
        share: bool = True,
        max_belt_z: Fraction = DEFAULT_RACE_MAX_BELT_Z,
    ) -> None:
        self.band_policy = band_policy
        self.workers = workers
        self.arrangements = arrangements
        self.belt_vertical_construction = belt_vertical_construction
        self.sequence_islands = sequence_islands
        self.share = share
        self.max_belt_z = max_belt_z

    def _merge(self, outcomes: Sequence[_StrategyRaceOutcome]) -> Placement:
        from flab2bp.layout.base import NoValidLayout
        from flab2bp.layout.sequence_solver import _exact_key

        completed = tuple(
            outcome
            for outcome in outcomes
            if outcome.status == "completed" and outcome.placement is not None
        )
        if completed:
            winner = min(
                completed,
                key=lambda outcome: (
                    *_exact_key(_require_placement(outcome)),
                    RACE_STRATEGIES.index(outcome.strategy),
                ),
            )
            return _require_placement(winner)
        details = "; ".join(
            f"{outcome.strategy}: {outcome.refusal_reason}"
            for outcome in outcomes
            if outcome.refusal_reason
        )
        raise NoValidLayout(
            "both raced strategies refused" + (f": {details}" if details else ""),
            spec_label=next(
                (o.refusal_spec_label for o in outcomes if o.refusal_spec_label), ""
            ),
            budget_s=next((o.refusal_budget_s for o in outcomes if o.refusal_budget_s), 0.0),
            projection_failures=tuple(
                dict.fromkeys(
                    failure
                    for outcome in outcomes
                    for failure in outcome.refusal_projection_failures
                )
            ),
        )

    def lay_out(
        self,
        spec: BuildSpec,
        *,
        time_budget_s: float = 15.0,
        absolute_deadline: float | None = None,
    ) -> Placement:
        del absolute_deadline  # a race owns its own children's walls
        return self._merge(
            run_strategy_race(
                spec,
                time_budget_s=time_budget_s,
                band_policy=self.band_policy,
                belt_vertical_construction=self.belt_vertical_construction,
                max_belt_z=self.max_belt_z,
                workers=self.workers,
                arrangements=self.arrangements,
                sequence_islands=self.sequence_islands,
                share=self.share,
            )
        )
```

The merge key is `(*_exact_key(placement), RACE_STRATEGIES.index(strategy))` — the same shape `_merge_sequence_island_outcomes` uses with `island_id` as its tie-break, so a tie resolves to a fixed strategy rather than to whichever child finished first.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/layout/test_strategy_race.py -q`
Expected: all pass

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check src/flab2bp/layout/strategy_race.py tests/layout/test_strategy_race.py
uv run mypy src/flab2bp/layout/strategy_race.py tests/layout/test_strategy_race.py
git add src/flab2bp/layout/strategy_race.py tests/layout/test_strategy_race.py
git commit -m "feat(layout): merge a raced portfolio into one placement for a single cell"
```

---

### Task 14: `pipeline.build` gains `workers`, `race` (off by default), and `share`

**Files:**
- Modify: `src/flab2bp/pipeline.py` (`build` at `:353`, the islands guard at `:395`, `_new_layout` at `:77`, the attempt loop at `:524-668`)
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `strategy_race.run_strategy_race`, `strategy_race.race_worker_split` (Tasks 9, 8); `pipeline.{Attempt, LayoutAttemptFailure, AttemptProgress, NoValidLayout}`.
- Produces: `pipeline.build(..., workers: int | None = None, race: bool = False, share: bool = True)`; `_new_layout(..., workers: int | None = None)`; a module-level `_solve_one` closure shape inside `build`. Task 17 flips `race`'s default.

**`race=False` is the default here on purpose.** A change that halves a `best` build's wall time and doubles its process count does not go live in the same commit that first makes it possible. Every existing `best` test keeps passing untouched, and Task 17 flips the default after Gate D2.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pipeline.py`:

```python
def test_islands_are_legal_with_best_and_still_illegal_with_freeform() -> None:
    # Islands now live INSIDE the sequence-pair racer, so `best` may ask for
    # them.  The guard fires before any URL work, so a bogus URL proves which
    # rejection we got: `freeform` must fail on the guard's own message, and
    # `best` must get past it and fail on the URL instead.
    with pytest.raises(ValueError, match="sequence islands"):
        pipeline.build("not-a-url", strategy="freeform", sequence_islands=2)

    with pytest.raises(Exception) as caught:
        pipeline.build("not-a-url", strategy="best", sequence_islands=2)

    assert "sequence islands" not in str(caught.value)


def test_best_is_serial_until_a_caller_opts_into_racing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The default must not race, so every existing `best` caller is unchanged."""
    from flab2bp.layout import strategy_race

    races = 0

    def counting(*args: object, **kwargs: object) -> tuple[object, ...]:
        nonlocal races
        races += 1
        raise AssertionError("race=False must never reach run_strategy_race")

    monkeypatch.setattr(strategy_race, "run_strategy_race", counting)
    monkeypatch.setattr(pipeline.strategy_race, "run_strategy_race", counting)

    build = pipeline.build(
        SMALL_URL,
        strategy="best",
        candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
        time_budget_s=3.0,
    )

    assert races == 0
    assert {attempt.strategy for attempt in build.attempts} | {
        failure.strategy for failure in build.refused
    } == {"freeform", "sequence-pair"}


@pytest.mark.slow
def test_racing_best_produces_the_same_attempt_shape_as_the_serial_one() -> None:
    serial = pipeline.build(
        SMALL_URL,
        strategy="best",
        candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
        time_budget_s=8.0,
    )
    raced = pipeline.build(
        SMALL_URL,
        strategy="best",
        candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
        time_budget_s=8.0,
        race=True,
    )

    def shape(build: pipeline.Build) -> set[str]:
        return {a.strategy for a in build.attempts} | {f.strategy for f in build.refused}

    assert shape(raced) == shape(serial)
    assert len(raced.attempts) + len(raced.refused) == 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_pipeline.py -q -k "islands_are_legal or serial_until or same_attempt_shape"`
Expected: `test_islands_are_legal_with_best_and_still_illegal_with_freeform` FAILS on its second block, because today's guard rejects `best` too; `test_best_is_serial_until_a_caller_opts_into_racing` FAILS with `AttributeError: module 'flab2bp.pipeline' has no attribute 'strategy_race'`; `test_racing_best_produces_the_same_attempt_shape_as_the_serial_one` FAILS with `TypeError: build() got an unexpected keyword argument 'race'`.

- [ ] **Step 3: Add the parameters and relax the islands guard**

Import the module at the top of `pipeline.py`:

```python
from flab2bp.layout import strategy_race
```

Add three keyword-only parameters to `build`:

```python
    #: CP-SAT search workers.  ``None`` is every core for an explicit strategy
    #: and ``strategy_race.race_worker_split(every core)`` when racing.  It is
    #: surfaced here because racing puts TWO CP-SAT users on one box and the
    #: split has to be decided by whoever knows both arms exist.
    workers: int | None = None,
    #: Race the two strategies for ONE budget instead of running them serially
    #: for one budget EACH.  OFF by default until the flip commit: a change this
    #: large in wall time and process count opts in before it opts everyone in.
    race: bool = False,
    #: Exchange certified incumbents and cluster no-goods between the racers.
    #: Meaningless unless ``race`` is true.
    share: bool = True,
```

Relax the guard:

```python
    if sequence_islands != 1 and strategy not in ("sequence-pair", "best"):
        raise ValueError("sequence islands require --strategy sequence-pair or best")
```

Add `workers: int | None = None` to `_new_layout`'s keyword-only parameters and pass it to `FreeformLayout(workers=workers, ...)`.

- [ ] **Step 4: Drive the loop body from resolved results**

Immediately above the `for spec in spec_set.candidates:` loop, define the serial path so both modes produce the same shape:

```python
    def _solve_one(
        candidate: BuildSpec, sname: ExplicitStrategyName
    ) -> Placement | NoValidLayout:
        """The pre-racing path, returning the refusal instead of raising it.

        The loop body below branches on the RESULT rather than catching, so one
        shape handles a raced pair and a serial one.
        """
        layout = _new_layout(
            sname,
            belt_vertical_construction=belt_rules.vertical_construction,
            sequence_islands=sequence_islands,
            band_policy=policy,
            workers=workers,
        )
        try:
            return layout.lay_out(candidate, time_budget_s=time_budget_s)
        except NoValidLayout as exc:
            return exc
```

Inside `for spec in spec_set.candidates:`, replace the `for sname in wanted:` header with a resolution step and then the same loop over resolved results:

```python
        if strategy == "best" and race:
            outcomes = strategy_race.run_strategy_race(
                spec,
                time_budget_s=time_budget_s,
                band_policy=policy,
                belt_vertical_construction=belt_rules.vertical_construction,
                max_belt_z=belt_rules.max_z,
                workers=workers,
                sequence_islands=sequence_islands,
                share=share,
            )
            solved: tuple[tuple[str, Placement | NoValidLayout], ...] = tuple(
                (
                    outcome.strategy,
                    outcome.placement
                    if outcome.status == "completed" and outcome.placement is not None
                    else NoValidLayout(
                        outcome.refusal_reason or f"{outcome.strategy} produced nothing",
                        spec_label=spec.label,
                        budget_s=time_budget_s,
                        projection_failures=outcome.refusal_projection_failures,
                    ),
                )
                for outcome in outcomes
            )
        else:
            solved = tuple((sname, _solve_one(spec, sname)) for sname in wanted)

        for sname, result in solved:
            pair_index += 1
            if on_progress is not None:
                on_progress(
                    AttemptProgress(
                        index=pair_index,
                        total=total_pairs,
                        candidate=spec.label,
                        strategy=sname,
                        phase="started",
                    )
                )
            if isinstance(result, NoValidLayout):
                failure = LayoutAttemptFailure(
                    candidate=spec.label,
                    strategy=sname,
                    reason=result.reason,
                    projection_failures=result.projection_failures,
                )
                refused.append(failure)
                if on_progress is not None:
                    on_progress(
                        AttemptProgress(
                            index=pair_index,
                            total=total_pairs,
                            candidate=spec.label,
                            strategy=sname,
                            phase="refused",
                            reason=result.reason,
                            projection_failures=failure.projection_failures,
                        )
                    )
                continue
            placement = result
            # ... the existing body from Task 6's `attempt_started` block through
            # the closing `laid-out` progress call, unchanged, with the removed
            # `try/except NoValidLayout` gone and `attempt_started` now opening
            # this branch.
```

`AttemptProgress` still reports `started` before each pair settles and `laid-out`/`refused` after it, and `pair_index` still counts 1-based over `total_pairs = len(spec_set.candidates) * len(wanted)`. Under racing the two `started` events for a candidate are emitted after the race returns rather than before each solve; that is the only progress-shape change, and it is visible only to a caller timing the gap between `started` and its settlement.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_pipeline.py tests/web -q`
Expected: all pass, including every existing `best` test — `race` is `False`, so the serial path is what runs.

- [ ] **Step 6: Lint, type-check, commit**

```bash
uv run ruff check src/flab2bp/pipeline.py tests/test_pipeline.py
uv run mypy src/flab2bp/pipeline.py
git add src/flab2bp/pipeline.py tests/test_pipeline.py
git commit -m "feat(pipeline): offer racing for strategy best behind an opt-in flag"
```

---

### Task 15: CLI flags and the `best` audit cell

**Files:**
- Modify: `src/flab2bp/cli.py` (the argument block at `:188-289`, the islands rule at `:266`, the `pipeline.build` call at `:288`)
- Modify: `scripts/audit.py` (`_STRATEGIES` at `:107`, `strategy_names` at `:120`, `--strategy` at `:527`)
- Test: `tests/test_pipeline_cli_strategy.py`, `tests/scripts/test_audit.py` (including the four `_STRATEGIES` doubles at `:106`, `:185`, `:311`, `:424`), `tests/scripts/test_audit_compare.py`, `tests/scripts/test_ab_compare.py` (the two `monkeypatch.setitem` doubles at `:93`, `:153`)

**Interfaces:**
- Consumes: `strategy_race.RacingLayout` (Task 13); `pipeline.build(..., workers, race, share)` (Task 14); `audit.build_jobs`, `audit.Tally`, `audit.record`.
- Produces: CLI `--workers N`, `--race`, `--no-share`; `audit._ALL_STRATEGIES`; `audit.strategy_names("all") -> ("freeform", "sequence-pair", "best")`; `audit._STRATEGIES["best"]`. Task 16 runs the 108-cell gate on them.

- [ ] **Step 1: Write the failing tests**

Append to `tests/scripts/test_audit.py`:

```python
def test_all_resolves_to_the_two_strategies_and_the_portfolio() -> None:
    assert audit.strategy_names("all") == ("freeform", "sequence-pair", "best")
    assert audit.strategy_names("both") == ("freeform", "sequence-pair")


def test_the_best_cell_builds_a_racing_layout_at_the_cells_belt_ceiling() -> None:
    from fractions import Fraction

    from flab2bp.layout.strategy_race import RacingLayout

    ceiling = Fraction(171, 20)
    layout = audit._STRATEGIES["best"](6, True, ceiling)

    assert isinstance(layout, RacingLayout)
    assert layout.workers == 6
    assert layout.belt_vertical_construction is True
    # The child validates its own incumbent before publishing it; validating at
    # a different ceiling from `run_cell`'s would publish a bound the cell then
    # rejects.
    assert layout.max_belt_z == ceiling


def test_the_two_explicit_factories_ignore_the_belt_ceiling() -> None:
    from fractions import Fraction

    from flab2bp.layout.freeform import FreeformLayout
    from flab2bp.layout.sequence_solver import SequencePairLayout

    assert isinstance(
        audit._STRATEGIES["freeform"](4, True, Fraction(171, 20)), FreeformLayout
    )
    assert isinstance(
        audit._STRATEGIES["sequence-pair"](4, True, Fraction(171, 20)),
        SequencePairLayout,
    )


def test_a_full_all_strategy_run_plans_one_hundred_and_eight_cells() -> None:
    from flab2bp.bench.corpus import Tier

    jobs = audit.build_jobs(
        list(audit.strategy_names("all")),
        set(Tier),
        [30.0],
        8,
    )

    # 12 corpus URLs x 3 candidate policies x 3 strategies.
    assert len(jobs) == 108
```

Append to `tests/scripts/test_audit_compare.py`:

```python
def test_the_expected_cell_count_covers_a_three_strategy_run() -> None:
    rows = [
        _row(strategy, "plastic", index, "CLEAN", 100.0, 5.0)
        for strategy in ("freeform", "sequence-pair", "best")
        for index in range(36)
    ]

    assert audit_compare.compare(
        rows, rows, noise_area=0.013, p95_seconds=30.0, expect_cells=108
    ).passed
    assert not audit_compare.compare(
        rows, rows, noise_area=0.013, p95_seconds=30.0, expect_cells=72
    ).passed
```

Append to `tests/test_pipeline_cli_strategy.py`:

```python
def test_the_cli_offers_racing_as_an_opt_in() -> None:
    from flab2bp import cli

    parser = cli.build_parser() if hasattr(cli, "build_parser") else None
    assert parser is not None, "resolve the parser factory by name before editing"
    args = parser.parse_args(["https://example/x"])
    assert args.race is False
    assert args.share is True
    assert args.workers is None

    opted_in = parser.parse_args(["https://example/x", "--race", "--no-share", "--workers", "8"])
    assert opted_in.race is True
    assert opted_in.share is False
    assert opted_in.workers == 8
```

**Verification step, with its command and decision rule.** `cli.py` may build its parser inside `main` rather than in a named factory:

```bash
uv run python -c "
import inspect, flab2bp.cli as cli
print([n for n, o in vars(cli).items() if inspect.isfunction(o)])
"
```

If the printed list has no parser factory, extract the `argparse.ArgumentParser(...)` construction and every `add_argument` call out of `main` into `def build_parser() -> argparse.ArgumentParser:` and have `main` call it. That extraction is part of this task, and the test above is what justifies it.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/scripts/test_audit.py tests/scripts/test_audit_compare.py tests/test_pipeline_cli_strategy.py -q -k "all_resolves or best_cell or hundred_and_eight or three_strategy_run or racing_as_an_opt_in"`
Expected: `test_all_resolves_to_the_two_strategies_and_the_portfolio` FAILS with `ValueError: unknown strategy: all`; `test_the_best_cell_builds_a_racing_layout_at_the_cells_belt_ceiling` FAILS with `KeyError: 'best'`; `test_the_two_explicit_factories_ignore_the_belt_ceiling` FAILS with `TypeError: <lambda>() takes 2 positional arguments but 3 were given`; `test_a_full_all_strategy_run_plans_one_hundred_and_eight_cells` FAILS with the same `ValueError`; `test_the_cli_offers_racing_as_an_opt_in` FAILS with `AttributeError: 'Namespace' object has no attribute 'race'`.

`test_the_expected_cell_count_covers_a_three_strategy_run` **PASSES already** — `audit_compare.compare` has taken `expect_cells` since Phase A and needs no change for a third strategy, because it keys on `(strategy, url_id, spec_index)` and `"best"` is simply a third `strategy`. It is added here as the regression guard that says so, and Task 16 is what runs it for real with `--expect-cells 108`.

- [ ] **Step 3: Add the CLI flags**

In `cli.py`, beside the existing `--budget`:

```python
    ap.add_argument(
        "--workers",
        type=int,
        default=None,
        help="CP-SAT search workers (default: every core; split between the two "
        "racers under --strategy best --race)",
    )
    ap.add_argument(
        "--race",
        action="store_true",
        help="run --strategy best as a concurrent race for ONE budget instead of "
        "two serial solves for one budget each",
    )
    ap.add_argument(
        "--no-share",
        dest="share",
        action="store_false",
        help="race without exchanging incumbents or no-goods",
    )
```

Relax the islands rule:

```python
    if args.sequence_islands is not None and args.strategy not in ("sequence-pair", "best"):
        ap.error("--sequence-islands requires --strategy sequence-pair or best")
```

and pass `workers=args.workers, race=args.race, share=args.share` into `pipeline.build`.

- [ ] **Step 4: Add the `best` audit cell**

In `scripts/audit.py`, import the layout and widen the factory. The third
argument is the belt ceiling: `run_cell` validates the winner at
`belt_rules.max_z` (`audit.py:325`), and a raced child that validates its own
incumbent at a *different* ceiling would publish a bound the cell then rejects.
The two existing lambdas ignore it — neither layout takes a belt ceiling, and
only the racing child validates on its own.

```python
from fractions import Fraction  # noqa: E402
from flab2bp.layout.strategy_race import RacingLayout  # noqa: E402
```

```python
_StrategyFactory = Callable[[int, bool, Fraction], LayoutStrategy]
_STRATEGIES: dict[str, _StrategyFactory] = {
    "freeform": lambda workers, vertical, _max_belt_z: FreeformLayout(
        band_policy=BandPolicy("portable"),
        workers=workers,
        belt_vertical_construction=vertical,
    ),
    "sequence-pair": lambda _workers, vertical, _max_belt_z: SequencePairLayout(
        band_policy=BandPolicy("portable"),
        belt_vertical_construction=vertical,
    ),
    "best": lambda workers, vertical, max_belt_z: RacingLayout(
        BandPolicy("portable"),
        workers=workers,
        belt_vertical_construction=vertical,
        max_belt_z=max_belt_z,
    ),
}
```

`max_belt_z` is a `Fraction`, not an `int`: `catalog.BeltAltitudeRules.max_z` is
declared `Fraction` and `validate.validate`'s own default is
`catalog.DEFAULT_MAX_BELT_Z`.

In `run_cell`, pass it at the single `make_strategy(...)` call:

```python
            strategy = make_strategy(
                job.workers,
                belt_rules.vertical_construction,
                belt_rules.max_z,
            )
```

The `job.arrangements is not None and job.strategy == "freeform"` branch above it
constructs `FreeformLayout` directly and is unaffected.

```python
_ALL_STRATEGIES = ("freeform", "sequence-pair", "best")


def strategy_names(requested: str) -> tuple[str, ...]:
    """Resolve ``both`` to the two explicit strategies and ``all`` to all three."""
    if requested == "both":
        return _DEFAULT_STRATEGIES
    if requested == "all":
        return _ALL_STRATEGIES
    if requested not in _STRATEGIES:
        raise ValueError(f"unknown strategy: {requested}")
    return (requested,)
```

and widen the flag:

```python
    ap.add_argument(
        "--strategy",
        default="both",
        choices=("both", "all", "freeform", "sequence-pair", "best"),
    )
```

- [ ] **Step 5: Widen the six existing strategy-factory doubles**

The factory's arity changed, so every double stored in `_STRATEGIES` or
substituted for it needs the third parameter. Six sites, all
`lambda workers, vertical: ...` today:

```python
# tests/scripts/test_audit.py:106, :185, :311, :424
        lambda workers, vertical, _max_belt_z: RefusingStrategy(),
        lambda workers, vertical, _max_belt_z: SuccessfulStrategy(),
        lambda workers, vertical, _max_belt_z: CompletedStrategy(),
        lambda workers, vertical, _max_belt_z: UncompletedStrategy(),
```

`tests/scripts/test_ab_compare.py:93` and `:153` are `monkeypatch.setitem` calls
against a dict typed `Callable[[bool], LayoutStrategy]`; resolve each by reading
the line and adding the parameter the dict's type declares. Run
`uv run mypy tests/scripts` and require no new diagnostic — mypy, not this list,
is the authority on which doubles the widened type actually breaks.

- [ ] **Step 6: Run the whole suite to verify it passes**

```bash
uv run pytest -q
uv run mypy 2>&1 | tail -3
```

Expected: all tests pass and mypy reports the locked baseline of 176. If `tests/test_pipeline_cli_strategy.py` asserts the old islands error text, update that assertion to the new message rather than reverting the rule.

- [ ] **Step 7: Prove one `best` cell end to end**

```bash
uv run python scripts/audit.py --budget 30 --jobs 1 --only plastic \
  --strategy best --json /tmp/best-cell.jsonl | tail -4
uv run python -c "
import json
for r in map(json.loads, open('/tmp/best-cell.jsonl')):
    print(r['strategy'], r['spec_label'], r['status'], round(r['seconds'],2), r['area'])
"
```

Expected: three `best` rows, every one CLEAN, every `seconds` at or under 35.0.

- [ ] **Step 8: Lint, type-check, commit**

```bash
uv run ruff check .
uv run mypy
git add src/flab2bp/cli.py scripts/audit.py tests
git commit -m "feat(cli): offer racing and audit the portfolio as its own cell"
```

---

### Task 16: Gate D2, the portfolio corpus gate

**Files:**
- Create: `docs/superpowers/evidence/2026-09-02-phase-d-portfolio/race-budget30-round{1,2,3}.jsonl`
- Create: `docs/superpowers/evidence/2026-09-02-phase-d-portfolio/gate-d2.md`

**Interfaces:**
- Consumes: `scripts/audit.py --budget 30 --jobs 16 --strategy all --json PATH`; `scripts/audit_compare.py ... --expect-cells 108`; Gate D1's `wall-budget30-round{1,2,3}.jsonl` and Task 1's `baseline-budget30.jsonl`.
- Produces: the committed Gate D2 record, which is what Task 17 is conditional on.

- [ ] **Step 1: Confirm the tree is green before measuring**

```bash
uv run python setup.py build_ext --inplace
uv run pytest -q
uv run ruff check .
uv run mypy
```

Expected: the suite passes, ruff is clean, mypy reports no new diagnostic against the locked baseline of 176.

- [ ] **Step 2: Run the three rounds**

```bash
d=docs/superpowers/evidence/2026-09-02-phase-d-portfolio
for r in 1 2 3; do
  uv run python scripts/audit.py --budget 30 --jobs 16 --strategy all \
    --json "$d/race-budget30-round$r.jsonl" | tail -8
done
wc -l $d/race-budget30-round*.jsonl
```

Expected: 108 rows per file. A `best` cell forks two children, so `--jobs 16` now puts up to 32 solver processes on the box; if the run exceeds `--max-seconds 900` and cells report NOT RUN, re-run with `--jobs 8 --max-seconds 1800` and record which was used.

- [ ] **Step 3: Compare the explicit arms against Gate D1**

```bash
d=docs/superpowers/evidence/2026-09-02-phase-d-portfolio
for r in 1 2 3; do
  uv run python -c "
import json, sys
src, dst = sys.argv[1], sys.argv[2]
rows = [json.loads(l) for l in open(src) if json.loads(l)['strategy'] != 'best']
open(dst, 'w').writelines(json.dumps(r) + '\n' for r in rows)
print(dst, len(rows))
" "$d/race-budget30-round$r.jsonl" "/tmp/race-explicit-round$r.jsonl"
  uv run python scripts/audit_compare.py "$d/wall-budget30-round1.jsonl" \
    "/tmp/race-explicit-round$r.jsonl" --p95-seconds 30 --expect-cells 72
done
```

Expected: 72 rows extracted per round, and each comparison's clean count at or above Gate D1 round 1's.

- [ ] **Step 4: Judge the portfolio conditions against the SERIAL baseline**

The coverage and area conditions are both judged against Task 1's `baseline-budget30.jsonl`, which is the serial two-budget arm. Comparing a `best` cell against the raced round's own arms would compare it with two arms that were themselves squeezed by the race — a regression they all share would cancel out and read as clean.

```bash
uv run python - <<'EOF'
import json, math, pathlib
d = pathlib.Path("docs/superpowers/evidence/2026-09-02-phase-d-portfolio")
base = {(r["strategy"], r["url_id"], r["spec_index"]): r
        for r in map(json.loads, (d / "baseline-budget30.jsonl").open())}
for r_i in (1, 2, 3):
    rows = [json.loads(l) for l in (d / f"race-budget30-round{r_i}.jsonl").open()]
    by = {(r["strategy"], r["url_id"], r["spec_index"]): r for r in rows}
    cells = sorted({(r["url_id"], r["spec_index"]) for r in rows})
    coverage_misses, area_misses = [], []
    for url_id, index in cells:
        best = by.get(("best", url_id, index))
        if best is None:
            coverage_misses.append(f"{url_id}/#{index} MISSING")
            continue
        arms = [base.get((s, url_id, index)) for s in ("freeform", "sequence-pair")]
        if any(a and a["status"] == "CLEAN" for a in arms) and best["status"] != "CLEAN":
            coverage_misses.append(f'{url_id}/#{index} {best["status"]} {best["detail"][:50]}')
        # Area against the SERIAL baseline's clean arms, never the raced round's.
        clean_areas = [a["area"] for a in arms if a and a["status"] == "CLEAN" and a["area"] > 0]
        if best["status"] == "CLEAN" and clean_areas:
            ratio = best["area"] / min(clean_areas)
            if ratio > 1.013:
                area_misses.append(f"{url_id}/#{index} ratio {ratio:.4f}")
    secs = sorted(r["seconds"] for r in rows)
    p95 = secs[min(len(secs) - 1, math.ceil(0.95 * len(secs)) - 1)]
    print(f"round{r_i}: rows {len(rows)}  clean {sum(r['status']=='CLEAN' for r in rows)}/108  "
          f"p95 {p95:.2f}s  max {secs[-1]:.2f}s  "
          f"invalid {sum(r['status']=='INVALID' for r in rows)}  "
          f"crash {sum(r['status']=='CRASH' for r in rows)}")
    print(f"  coverage misses vs serial baseline: {coverage_misses or 'none'}")
    print(f"  area misses vs serial baseline:     {area_misses or 'none'}")
    print(f"  commit {rows[0]['commit'][:12]}  backends "
          f"{sorted({r['route_backend'] for r in rows})}")
EOF
```

Expected, per round: `max` at or under 35.00 s, `invalid 0`, `crash 0`, `coverage misses ... none`, `area misses ... none`, and `backends ['cython']`.

- [ ] **Step 5: Write the gate record**

`gate-d2.md` contains, and nothing else: the commit under test (from the rows' own `commit` field) and Task 1's baseline commit; the three Step 3 `audit_compare.py` lines verbatim; the Step 4 block verbatim; Gate D1's per-round `p95`/`max` beside Gate D2's, so the wall gate is visibly still held; the measured spawn cost from `spawn-cost.txt` and the `RACE_COMPLETION_GRACE_S` it produced; and one line per Gate D2 condition stating pass or fail.

- [ ] **Step 6: Commit**

```bash
git add docs/superpowers/evidence/2026-09-02-phase-d-portfolio
git commit -m "bench: record the phase D portfolio racing gate at 30s"
```

If any round misses a Gate D2 condition, commit under `bench: record a failed phase D portfolio gate`, with `gate-d2.md` naming the failing cells and their `detail` strings, and **do not start Task 17** — the default stays off. The two knobs for a CPU-contention failure are `RACE_FREEFORM_WORKER_SHARE` and `--jobs`; turn neither without re-running the gate and recording both numbers.

---

### Task 17: Flip racing on and change the web contract

**Only if Gate D2 passed.** This is the commit that changes behaviour for callers who never asked for it, so it is the last one and it is on its own.

**Files:**
- Modify: `src/flab2bp/pipeline.py` (`build`'s `race` default)
- Modify: `src/flab2bp/cli.py` (`--race` becomes `--no-race`)
- Modify: `src/flab2bp/web/jobs.py` (`Options.solver_ceiling_s`, the admission message)
- Test: `tests/web/test_options.py`, `tests/web/test_jobs.py`, `tests/test_pipeline.py`, `tests/test_pipeline_cli_strategy.py`

**Interfaces:**
- Consumes: `pipeline.PRODUCTION_STRATEGY_COUNT` (kept as the name for the strategy SET; it stops being a wall multiplier); `MAX_SOLVER_SECONDS = 300.0` (unchanged).
- Produces: `pipeline.build(..., race: bool = True)`; `Options.solver_ceiling_s == effective_candidate_count * budget_s`; CLI `--no-race`.

- [ ] **Step 1: Confirm the gate that authorises this task**

```bash
grep -n "pass\|FAIL" docs/superpowers/evidence/2026-09-02-phase-d-portfolio/gate-d2.md
```

Expected: every Gate D2 condition line reads pass. Decision rule: if any reads FAIL, stop — this task is not authorised, and the plan ends at Task 16 with racing available behind `--race`.

- [ ] **Step 2: Write the failing web tests**

Replace the ceiling arithmetic in the four `tests/web/test_options.py` tests and the two `tests/web/test_jobs.py` assertions the spec names. In `tests/web/test_options.py`:

- `test_the_candidate_policy_ceiling_is_on_the_product_not_the_budget` (`:194-215`): drop `* pipeline.PRODUCTION_STRATEGY_COUNT` from `best_budget`, so it becomes `MAX_SOLVER_SECONDS / len(DEFAULT_CANDIDATE_POLICIES)`.
- `test_best_ceiling_follows_the_selected_candidate_policy_subset` (`:228-229`): `expected = 2 * 5.0`.
- `test_pinned_flow_effective_candidate_count_and_ceiling_are_one` (`:264`): `assert options.solver_ceiling_s == 5.0`.
- `test_candidate_ceiling_error_reports_the_effective_pinned_count` (`:267-276`): unchanged in intent; the message it matches (`r"1 candidate\(s\)"`) still holds, but re-run it — with the ceiling halved, `budget_s=MAX_SOLVER_SECONDS` still exceeds it, so it must still raise.

In `tests/web/test_jobs.py`, `:322` and `:557`: drop `* pipeline.PRODUCTION_STRATEGY_COUNT` from both `snap["solver_ceiling_s"]` assertions.

Then add the new contract test to `tests/web/test_options.py`:

```python
def test_a_best_request_now_costs_one_budget_per_candidate() -> None:
    options = Options(url=URL, strategy="best", budget_s=100.0)

    assert len(DEFAULT_CANDIDATE_POLICIES) == 3
    assert options.solver_ceiling_s == 300.0   # was 600.0: racing halved it
```

- [ ] **Step 3: Run them to verify they fail**

Run: `uv run pytest tests/web/test_options.py tests/web/test_jobs.py -q`
Expected: the six edited assertions FAIL against the current `solver_ceiling_s` (each off by a factor of two on the `best` cases), and `test_a_best_request_now_costs_one_budget_per_candidate` FAILS with `assert 600.0 == 300.0`.

- [ ] **Step 4: Flip the default and the ceiling**

In `pipeline.build`, change the parameter and its comment:

```python
    #: Race the two strategies for ONE budget instead of running them serially
    #: for one budget EACH.  Default since the Gate D2 commit; ``race=False``
    #: restores the serial loop exactly, for A/B and for boxes where two
    #: concurrent CP-SAT users are not wanted.
    race: bool = True,
```

In `web/jobs.py`:

```python
    @property
    def solver_ceiling_s(self) -> float:
        """An upper bound on the LAYOUT solving this job will do.

        The strategy factor is gone: ``best`` races freeform and sequence-pair
        CONCURRENTLY for one budget per candidate, where it used to run them one
        after the other for one budget each.  ``MAX_SOLVER_SECONDS`` is left
        where it is rather than halved: halving it would take away capacity
        callers already have.
        """
        return self.effective_candidate_count * self.budget_s
```

and the admission message loses its strategy term:

```python
        raise InvalidOptions(
            f"{options.effective_candidate_count} candidate(s) at "
            f"{options.budget_s:g}s is up to {options.solver_ceiling_s:g}s of solving, "
            f"over the {MAX_SOLVER_SECONDS:g}s ceiling. Lower the budget or choose "
            f"fewer candidate policies."
        )
```

In `cli.py`, replace `--race` with its inverse so the flag still matches the default:

```python
    ap.add_argument(
        "--no-race",
        dest="race",
        action="store_false",
        help="run --strategy best serially, one full budget per strategy, as it "
        "worked before racing",
    )
```

- [ ] **Step 5: Repair the two pipeline tests named by the spec**

Run them first and repair only what actually breaks:

```bash
uv run pytest tests/test_pipeline.py -q -k "encoding or best_reports_freeform_and_sequence_pairs" -x
```

`tests/test_pipeline.py:336-345` monkeypatches `codec.encode` to fail once; encoding still runs in the PARENT under racing, so it should still pass. `:393-405` asserts two `started` events, indices `[1, 2]`, total `2`, strategies `["freeform", "sequence-pair"]`; the raced loop emits exactly that. Decision rule: if either fails, the failure is a real behaviour change, not a stale assertion — fix the loop in `pipeline.py` to restore the assertion rather than editing the test, and say so in the commit message. Also drop `test_best_is_serial_until_a_caller_opts_into_racing` from Task 14, whose premise this commit reverses, and keep `test_racing_best_produces_the_same_attempt_shape_as_the_serial_one` with `race=False` on the serial arm.

- [ ] **Step 6: Run the whole suite**

```bash
uv run pytest -q
uv run ruff check .
uv run mypy
```

Expected: all pass, ruff clean, no new mypy diagnostic.

- [ ] **Step 7: Commit**

```bash
git add src/flab2bp/pipeline.py src/flab2bp/cli.py src/flab2bp/web/jobs.py tests
git commit -m "feat(pipeline): make racing the default for strategy best"
```

The commit message records the Gate D2 clean count and max wall that authorised the flip.

