# Phase C: ALNS Placement with a CP-SAT Window Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the placement search choose its own local repair from measured evidence, and give it an exact one — a CP-SAT window over a handful of strips with the rest pinned — so that `graphene/output-products` and `universe-matrix/no-proliferator` stop refusing at a 30-second budget.

**Architecture:** Three layers. `SequenceSolver.search` gains a feasibility-first continuation that appends deterministic restarts instead of stopping at a derived stage limit. A new `src/flab2bp/layout/sequence_alns.py` owns two destroy operators (`FAILED_ENDPOINTS`, `BAND_BOUNDARY`), two repair operators (`SEQUENCE_REINSERT`, `LOCAL_EXACT_PACK`), immutable context/choice/metrics/outcome records, and a deterministic discounted-UCB selector over a lexicographic reward; it replaces the hardcoded neighbourhood rule in `_routing_feedback_substitution`. `freeform._pack` is refactored into a model builder plus a solve so the same formulation can be re-solved with every strip outside a window pinned to its current origin, which is the `LOCAL_EXACT_PACK` repair for both strategies; a new placement-to-sequence-pair encoder carries the repaired placement back into the annealing state.

**Tech Stack:** Python 3.14, ortools 9.15.6755 CP-SAT, existing Cython kernels (`_route_kernel`, `_sequence_kernel`), pytest (serial), Ruff, strict MyPy, `uv run`.

**Spec:** `docs/superpowers/specs/2026-09-02-phase-c-alns-window-repair-design.md`

## Global Constraints

- **Phase B must have landed on master before this plan starts.** Create this plan's worktree from that master and generate the baseline there. Two Phase B deliverables are consumed: `route_feedback.ClusterRelationNoGood` (the window model reads it) and `scripts/audit_compare.py`'s `--regressions-only` and `--require-clean <cell>` flags (the gate uses them). Task 10 verifies the record's field names before writing the accessor.
- **The shipped operator portfolio is four operators**: destroy `{FAILED_ENDPOINTS, BAND_BOUNDARY}`, repair `{SEQUENCE_REINSERT, LOCAL_EXACT_PACK}`. `BLOCKER_COMPONENT`, `CONGESTED_CUT`, `RELATED_CARGO`, `DIVERSIFY`, `ROUTING_REGRET` are enum members with no dispatch branch and no arm. Do not implement them in this plan. The rule for adding one later: an operator is added when a refusing cell names its mechanism.
- **`select_lns_neighbourhood`'s ring-growth branch stays off.** `FAILED_ENDPOINTS` passes `stagnation=0`, as production always has.
- **The selector never reads a clock into its ledgers.** `reward_vector` has no time divisor; `routing_seconds` is telemetry only.
- Every `file:line` below was read at commit `b3c990a` and is a hint only. Resolve each target by symbol name (Serena `find_symbol`) before editing, and enumerate call sites with Serena `find_referencing_symbols`, never with grep alone (grep misses sites; it is for strings, comments, and config). When a step says "grep for X" and X is a Python symbol, use Serena; grep only cross-checks `getattr`-style dynamic dispatch and the current import lines of a file.
- **Symbol-tool activation (every implementer and reviewer, first thing):** the tools are deferred, so load them explicitly: `ToolSearch("select:mcp__serena__activate_project,mcp__serena__initial_instructions,mcp__serena__find_symbol,mcp__serena__find_referencing_symbols,mcp__serena__get_symbols_overview,LSP")`, then call `mcp__serena__activate_project` with the absolute path of the checkout you are editing (the worktree, not the main repository), then `mcp__serena__initial_instructions`. The repository tracks `.serena/project.yml`, so every worktree is its own Serena project once activated at its own path. If `find_symbol` errors or returns nothing for a symbol that exists, use the `LSP` tool (goToDefinition / findReferences) instead. If both fail, stop and report NEEDS_CONTEXT; never substitute grep.
- No learned selector beyond discounted UCB. No PyTorch or other training dependency enters the package.
- No new strip variant, pitch, pose, junction geometry, coater seating rule, or power rule.
- No cross-strategy sharing of incumbents or no-goods; that is Phase D.
- No change to the routing kernel, to `_ROUTING_BUDGET = 2_000_000`, `_ROUTING_EXPANSIONS_PER_SECOND = 400_000`, `_COMPACT_SEED_WALL_SHARE = Fraction(1, 3)`, `_PACK_SHARE = 0.35`, or the arrangement schedule.
- No change to `_MeasuredStageAdmission.try_start`'s cold-stage behaviour; the deadline overshoot on `quantum-chip/no-proliferator` is Phase D's.
- No change to CLI, web, or `pipeline.build` interfaces. `scripts/audit.py`'s JSONL schema is unchanged.
- No new compiled code. Everything in this phase is Python over the existing Cython kernels.
- No on-disk or cross-process cache of geometry. `OperatorSession` state lives in one `_production_run` or one `lay_out` call and dies with it.
- Every CP-SAT window solve pins `num_search_workers = 1` and sets `max_deterministic_time`.
- An explicit `max_stages` remains a hard deterministic cap: `feasibility_continuation` defaults to `False`.
- **`PlacementStats` (`src/flab2bp/layout/base.py:198`) is a `TypedDict(total=False)` with alphabetically ordered keys. Every new stat key is declared there in the task that first writes it, and `base.py` is listed in that task's Files.** New keys, in alphabetical order: `alns_applied`, `alns_choices`, `alns_encode_errors`, `alns_encode_inexact`, `alns_evaluations`, `alns_operators` (`str`), `alns_routing_seconds`, `alns_skipped_no_goods`, `alns_window_accepted`, `alns_window_seconds`, `alns_window_solves`, `feasibility_restart_batches`.
- **Measurement discipline.** Intermediate tasks measure with a single-cell audit on their target cell (`scripts/audit.py --only <url_id> --jobs 4`). The full three-round 72-cell audit runs once, in Task 14. A 72-cell round costs 3 to 5 minutes.
- Each task is a separate commit that leaves the tree green: `uv run pytest -q`, `uv run ruff check .`, `uv run mypy` (no new diagnostic against the locked baseline of 176 pre-existing errors).
- Run the full suite from the repo root with `uv run pytest -q`. Never `-n auto`: CP-SAT already saturates the box (`pyproject.toml:69-77`).
- `git diff` needs `--no-ext-diff`. (`git status` does not accept that flag; use plain `git status --porcelain`.)
- Timing measurements and every audit run happen on an idle box.
- Evidence files are tracked under `docs/superpowers/evidence/2026-09-02-phase-c-alns/`. The `.superpowers/sdd/` workspace is git-ignored and holds only task briefs and reports.
- Corpus gate: `uv run python scripts/audit.py --budget 30 --jobs 16`, both strategies, three rounds against the Phase B round files, verified by `scripts/audit_compare.py --regressions-only --require-clean` for each of the three target cells: `graphene/output-products` and `universe-matrix/no-proliferator` under both strategies CLEAN in every round, no cell that was CLEAN in the baseline refuses, INVALID 0, CRASH 0, wall p95 per cell at or under 30 s, paired geometric-mean area no worse than `1 + 0.013`.
- Known test facts: the two wall-clock tests `TestDirectInsertion::test_the_sweep_prefers_area_over_direct_insertion` (0.5 s) and `TestTheTimeBudgetIsAWall::test_magnetic_ring_repeated_one_second_calls_complete` (1.0 s) in `tests/layout/test_freeform.py` were removed from the tree during Phase B (Ruling S) because they flake under load; do not reintroduce them. `tests/test_pipeline.py::test_all_products_sequence_pair_honours_the_exact_layout_deadline` runs at a 1.5 s budget and trips DID NOT RAISE when preparation gets faster — **Task 2 makes it more fragile**, see the note there.
- The existing tests at `tests/layout/test_sequence_pair.py:2182-2320` (LNS neighbourhood and repair) and the no-good scoping tests in `tests/layout/test_freeform.py` must pass unchanged. If one needs a change, that is a finding to report, not a fix to make silently.
- The `slow` pytest marker is declared at `pyproject.toml:89` and still runs by default; use it for the two tests that drive a whole solver at a real budget.
- Commit messages: imperative, sentence case, no trailing period, e.g. `feat(layout): add discounted-UCB operator selection`.
- A step whose measurement misses its stated goal is not committed as if it passed: record the numbers and report.

---

### Task 1: Evidence directory and the Phase B baseline pointer

**Files:**
- Create: `docs/superpowers/evidence/2026-09-02-phase-c-alns/baseline.md`
- Create: `docs/superpowers/evidence/2026-09-02-phase-c-alns/baseline-budget30-round{1,2,3}.jsonl`

**Interfaces:**
- Consumes: `scripts/audit.py --budget 30 --jobs 16 --json PATH` (JSONL rows keyed `strategy`, `url_id`, `spec_index`, `spec_label`, `power`, `budget`, `status`, `area`, `seconds`, `detail`) and Phase B's `scripts/audit_compare.py BASELINE.jsonl CANDIDATE.jsonl [--noise-area 0.013] [--p95-seconds 30] [--regressions-only] [--require-clean CELL]`.
- Produces: the three baseline JSONL files every later measurement in this plan compares against, and `baseline.md` naming the commit they were generated at.

- [ ] **Step 1: Record the starting commit and confirm the Phase B prerequisites**

```bash
cd "$(git rev-parse --show-toplevel)"
git log --oneline -3
git status --porcelain
uv run python -c "from flab2bp.layout.route_feedback import ClusterRelationNoGood; print('cluster no-good OK')"
uv run python scripts/audit_compare.py --help | grep -E 'regressions-only|require-clean'
```

Expected: a clean tree whose HEAD is the master that includes Phase B; `cluster no-good OK`; both flags listed. If either check fails, **stop**: Phase B has not landed and this plan's Global Constraints make it a prerequisite. Copy the short hash; it goes into `baseline.md` and this task's commit message.

- [ ] **Step 2: Generate three interleaved baseline rounds**

```bash
mkdir -p docs/superpowers/evidence/2026-09-02-phase-c-alns
for round in 1 2 3; do
  uv run python scripts/audit.py --budget 30 --jobs 16 \
    --json "docs/superpowers/evidence/2026-09-02-phase-c-alns/baseline-budget30-round${round}.jsonl" \
    | tail -6
done
wc -l docs/superpowers/evidence/2026-09-02-phase-c-alns/*.jsonl
```

Expected: 72 lines per file, roughly 3 to 5 minutes per round. Record each round's CLEAN count. If Phase B landed as gated, expect 67/72 or better; if a round differs from its neighbours by more than two cells, say so in `baseline.md` and continue — the gate compares against these files, whatever they say.

- [ ] **Step 3: Write the baseline note**

```markdown
<!-- docs/superpowers/evidence/2026-09-02-phase-c-alns/baseline.md -->
# Phase C baseline

Generated on <DATE> on an idle box from commit `<HASH>` (`<SUBJECT>`), which is the master that
includes Phase B.

Command, three interleaved rounds:

    uv run python scripts/audit.py --budget 30 --jobs 16 --json baseline-budget30-round<N>.jsonl

| Round | CLEAN | REFUSED | INVALID | CRASH | p95 wall (s) |
|---|---:|---:|---:|---:|---:|
| 1 | <N> | <N> | <N> | <N> | <N> |
| 2 | <N> | <N> | <N> | <N> | <N> |
| 3 | <N> | <N> | <N> | <N> | <N> |

Same-arm noise, round 2 against round 1: area ratio <N> (this is the number `--noise-area` must
not be tightened below).

Cells this phase targets, and what they say in the baseline:

| Cell | Strategy | Baseline status | Wall (s) | Area | Detail |
|---|---|---|---:|---:|---|
| graphene/output-products | sequence-pair | <STATUS> | <N> | <N> | <DETAIL> |
| universe-matrix/no-proliferator | sequence-pair | <STATUS> | <N> | <N> | <DETAIL> |
| universe-matrix/all-products | sequence-pair | <STATUS> | <N> | <N> | <DETAIL> |
| universe-matrix/no-proliferator | freeform | <STATUS> | <N> | <N> | <DETAIL> |

Every later measurement in `docs/superpowers/plans/2026-09-02-phase-c-alns-window-repair.md`
compares a candidate JSONL against these three files with `scripts/audit_compare.py`.
```

Fill every `<...>` from the run output:

```bash
cd docs/superpowers/evidence/2026-09-02-phase-c-alns
jq -r 'select(.url_id=="graphene" or .url_id=="universe-matrix")
       | [.strategy,.url_id,.spec_label,.status,.seconds,.area,.detail] | @tsv' \
  baseline-budget30-round1.jsonl
cd -
```

- [ ] **Step 4: Record the same-arm noise**

Run: `uv run python scripts/audit_compare.py docs/superpowers/evidence/2026-09-02-phase-c-alns/baseline-budget30-round1.jsonl docs/superpowers/evidence/2026-09-02-phase-c-alns/baseline-budget30-round2.jsonl --regressions-only`
Expected: a line beginning `clean ... paired ... area ratio ... p95 ...`. Round 2 against round 1 measures same-arm noise. Put the printed `area ratio` in `baseline.md`.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/evidence/2026-09-02-phase-c-alns
git commit -m "bench: add phase C baseline evidence at 30s over three rounds"
```

---

### Task 2: Feasibility-first continuation

**Files:**
- Modify: `src/flab2bp/layout/sequence_solver.py` — `SequenceSearchResult` (`:756`), `SequenceSolver.search` (`:1036`), the `NoValidLayout` reason map (`:1345-1351`), `_SearchSolver` (`:5164`), the `search()` call sites at `:5229` and `:5281`, the production stats dict (`:5390-5445`)
- Modify: `src/flab2bp/layout/sequence_islands.py:139` (the island child's `search()` call)
- Modify: `src/flab2bp/layout/base.py:198` (`PlacementStats`) — add `feasibility_restart_batches: float`
- Test: `tests/layout/test_sequence_solver.py`, `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `_RestartState(restart, seed, anneal, ...)` (`sequence_solver.py:774`), `_HeightState(order, height, problem, feedback, restarts, ...)` (`:786`), `derive_stage_seed(base_seed, stage_index)` (`sequence_pair.py:1242`), `AnnealState.initial(size, seed)` (`sequence_pair.py:516`), `quality_archive_key` (`sequence_pair.py:1975`), `_counts_as_scheduled_stage`.
- Produces: `SequenceSolver.search(*, max_stages: int | None = None, feasibility_continuation: bool = False) -> SequenceSearchResult`; `SequenceSearchResult.feasibility_restart_batches: int = 0`; the placement stat `feasibility_restart_batches`; the module constant `C_FEASIBILITY_RESTART_BATCHES = 8`.

> **Fragility note.** `tests/test_pipeline.py::test_all_products_sequence_pair_honours_the_exact_layout_deadline` asserts a refusal at a 1.5 s budget. Before this task the search often stopped at its stage limit; after it, the search keeps going until the deadline. That is what the test wants, but it also means the refusal now depends on the continuation not finding an exact layout inside 1.5 s. If Step 6 shows that test failing with DID NOT RAISE, **lower its `time_budget_s` until it refuses again and record the new value in the commit message.** Never delete the assertion.

- [ ] **Step 1: Write the failing solver tests**

Add to `tests/layout/test_sequence_solver.py`. The module already constructs `SequenceSolver` with stub adapters; find the existing helper with `grep -n 'StageAdapters(' tests/layout/test_sequence_solver.py` and reuse it. If none exists, add this one beside the new tests and resolve `StageAdapters`, `DetailedStageResult`, `ValidationVerdict` and `ExpansionBudget` against their real signatures in `sequence_solver.py` first.

**Test-module imports this task adds.** Run `grep -n '^from \|^import ' tests/layout/test_sequence_solver.py` first and add only what is missing:

```python
from collections.abc import Callable
from dataclasses import replace

import pytest

from flab2bp.layout import sequence_solver
from flab2bp.layout.route_feedback import (
    DetailedRouteResult,
    DetailedRouteStatus,
    NetFailure,
    NetId,
    NetRole,
    RouteFailureKind,
)
from flab2bp.layout.sequence_pair import PlacementProblem, derive_stage_seed
from flab2bp.layout.sequence_solver import (
    ExpansionBudget,
    SequenceSolver,
    SequenceSolverConfig,
    StageAdapters,
)
```

`DetailedStageResult`, `ValidationVerdict` and `NoValidLayout` are also needed; resolve each one's module with `grep -rn 'class DetailedStageResult\|class ValidationVerdict\|class NoValidLayout' src/flab2bp/` and import from there.

```python
def _never_certifying_solver(
    *,
    heights: tuple[int, ...],
    deadline_reached: Callable[[], bool],
) -> SequenceSolver[object]:
    """A solver whose detailed route always strands one net, so no incumbent appears."""
    base = PlacementProblem(
        sizes=((4, 3), (4, 3)),
        nets=((0, 1),),
        outline_height=heights[0],
        area_lower_bound=24,
    )
    problems = {height: replace(base, outline_height=height) for height in heights}
    routing = DetailedRouteResult(
        status=DetailedRouteStatus.STRANDED,
        routed=(),
        failures=(
            NetFailure(
                net_id=NetId(0, 1, "iron-ore", NetRole.INTERNAL, 0),
                kind=RouteFailureKind.CONGESTION_WALL,
                wall=((1, 1, 0),),
                blocking_nets=(),
                expansions=1,
            ),
        ),
        iterations=1,
        expansions=1,
    )
    adapters = StageAdapters[object](
        prepare=lambda height, decoded: object(),
        global_route=lambda prepared, feedback, allowance: None,
        detailed_route=lambda prepared, allowance: DetailedStageResult(
            routing=routing, expansions=1
        ),
        validate=lambda placement: ValidationVerdict(False, ("stranded",), None),
    )
    return SequenceSolver[object](
        heights=heights,
        problem_for_height=problems.__getitem__,
        adapters=adapters,
        expansion_budget=ExpansionBudget(total=10_000),
        config=SequenceSolverConfig.test(),
        deadline_reached=deadline_reached,
    )


def test_search_without_continuation_stops_at_the_derived_stage_limit() -> None:
    solver = _never_certifying_solver(heights=(12, 16), deadline_reached=lambda: False)
    with pytest.raises(NoValidLayout) as excinfo:
        solver.search()
    assert "no scheduled stage produced an exact layout" in str(excinfo.value)


def test_search_appends_feasibility_restarts_until_the_deadline() -> None:
    ticks = iter(range(400))
    solver = _never_certifying_solver(
        heights=(12, 16),
        deadline_reached=lambda: next(ticks, 400) >= 40,
    )
    with pytest.raises(NoValidLayout) as excinfo:
        solver.search(feasibility_continuation=True)
    assert "deadline exhausted before finding an exact layout" in str(excinfo.value)
    assert len(solver._heights[0].restarts) > SequenceSolverConfig.test().restarts_per_height


def test_explicit_max_stages_remains_a_hard_cap_under_the_default_keyword() -> None:
    solver = _never_certifying_solver(heights=(12,), deadline_reached=lambda: False)
    with pytest.raises(NoValidLayout):
        solver.search(max_stages=1)
    assert len(solver._heights[0].restarts) == SequenceSolverConfig.test().restarts_per_height


def test_appended_restart_seeds_derive_from_seed_height_order_and_ordinal() -> None:
    config = SequenceSolverConfig.test()
    solver = _never_certifying_solver(heights=(12,), deadline_reached=lambda: False)
    assert solver._append_feasibility_restarts()
    height_state = solver._heights[0]
    added = height_state.restarts[-1]
    assert added.restart == config.restarts_per_height
    assert added.seed == derive_stage_seed(
        derive_stage_seed(config.seed, height_state.order), added.restart
    )
    assert added.stages == 0


def test_feasibility_exhaustion_has_its_own_refusal_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sequence_solver, "C_FEASIBILITY_RESTART_BATCHES", 1)
    solver = _never_certifying_solver(heights=(12,), deadline_reached=lambda: False)
    with pytest.raises(NoValidLayout) as excinfo:
        solver.search(feasibility_continuation=True)
    assert "feasibility continuation exhausted its restart budget" in str(excinfo.value)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/layout/test_sequence_solver.py -q -k "feasibility or hard_cap or derived_stage_limit"`
Expected: FAIL with `TypeError: search() got an unexpected keyword argument 'feasibility_continuation'` and `AttributeError: 'SequenceSolver' object has no attribute '_append_feasibility_restarts'`.

- [ ] **Step 3: Add the constant and the restart appender**

Beside the other module constants in `sequence_solver.py` (after `_MID_NO_SPRAY_COMPACT_MAX_STRIPS`):

```python
#: How many feasibility-restart batches one production search may append when
#: its derived stage schedule ends with no exact incumbent and clock remains.
#: Bounded so a pathological cell cannot spin: the wall deadline, the measured
#: stage admission, and the expansion ledger are still the binding stops.
C_FEASIBILITY_RESTART_BATCHES = 8
```

Resolve the imports this needs before writing the method:

```bash
grep -n 'quality_archive_key\|AnnealIncumbent\|QualityArchiveKey' src/flab2bp/layout/sequence_solver.py | head
grep -n 'QualityArchiveKey' src/flab2bp/layout/sequence_pair.py | head -3
```

Add whichever of `AnnealIncumbent`, `quality_archive_key`, `QualityArchiveKey` are missing to the existing `from flab2bp.layout.sequence_pair import (...)` block (`QualityArchiveKey` is the return type of `quality_archive_key`; if it is a bare `tuple` alias rather than a name, annotate the local as `tuple[object, ...]` and say so in the commit message).

Add the method to `SequenceSolver`, directly after `_select_restart`:

```python
    def _append_feasibility_restarts(self) -> bool:
        """Append one deterministic feasibility restart to every height.

        The seed is a pure function of ``(config.seed, height order, restart
        ordinal)`` -- the same derivation :func:`_new_height_state` uses -- so a
        continuation never depends on the order stages happened to complete in.
        The starting state is the best archived incumbent for that height, which
        is what makes this a continuation rather than a cold restart; a height
        with no archive falls back to a fresh anneal seed.
        """
        appended = False
        for height_state in self._heights:
            ordinal = len(height_state.restarts)
            seed = derive_stage_seed(
                derive_stage_seed(self.config.seed, height_state.order),
                ordinal,
            )
            best: AnnealIncumbent | None = None
            best_key: QualityArchiveKey | None = None
            for restart in height_state.restarts:
                for tagged in restart.archive:
                    key = quality_archive_key(tagged.incumbent)
                    if best_key is None or key < best_key:
                        best, best_key = tagged.incumbent, key
            anneal = (
                AnnealState.initial(height_state.problem.size, seed)
                if best is None
                else replace(best.state, base_seed=seed, stage_index=0)
            )
            height_state.restarts.append(
                _RestartState(restart=ordinal, seed=seed, anneal=anneal)
            )
            appended = True
        return appended
```

- [ ] **Step 4: Rewrite the search loop head**

The current head is:

```python
    def search(self, *, max_stages: int | None = None) -> SequenceSearchResult:
        """Search until its stage cap, deadline, or searchable budget is exhausted."""
        stage_limit = (
            (1 + (self.config.stages - 1) * self.config.restarts_per_height)
            * len(self._heights)
            if max_stages is None
            else max_stages
        )
        if type(stage_limit) is not int or stage_limit < 0:
            raise ValueError("maximum stages must be a non-negative integer")

        termination = "stage-limit"
        while (
            sum(_counts_as_scheduled_stage(stage) for stage in self._stage_stats)
            < stage_limit
        ):
```

Replace it with:

```python
    def search(
        self,
        *,
        max_stages: int | None = None,
        feasibility_continuation: bool = False,
    ) -> SequenceSearchResult:
        """Search until its stage cap, deadline, or searchable budget is exhausted.

        ``feasibility_continuation`` is the production path.  When the derived
        schedule ends with no exact incumbent and the clock, the admission, and
        the ledger all still allow work, one deterministic restart is appended
        per height and the schedule grows.  An explicit ``max_stages`` keeps the
        default and stays a hard cap, because tests and diagnostic probes need
        one.
        """
        stage_limit = (
            (1 + (self.config.stages - 1) * self.config.restarts_per_height)
            * len(self._heights)
            if max_stages is None
            else max_stages
        )
        if type(stage_limit) is not int or stage_limit < 0:
            raise ValueError("maximum stages must be a non-negative integer")
        if type(feasibility_continuation) is not bool:
            raise ValueError("feasibility continuation mode must be a bool")

        termination = "stage-limit"
        feasibility_restart_batches = 0
        while True:
            if (
                sum(_counts_as_scheduled_stage(stage) for stage in self._stage_stats)
                >= stage_limit
            ):
                if (
                    not feasibility_continuation
                    or self._incumbent is not None
                    or feasibility_restart_batches >= C_FEASIBILITY_RESTART_BATCHES
                    or self.budget.shared_left == 0
                    or self.deadline_reached()
                    or not self._append_feasibility_restarts()
                ):
                    if feasibility_continuation and self._incumbent is None:
                        termination = (
                            "deadline"
                            if self.deadline_reached()
                            else "feasibility-exhausted"
                        )
                    break
                feasibility_restart_batches += 1
                stage_limit += len(self._heights)
                continue
```

The rest of the loop body is unchanged. In the `SequenceSearchResult(...)` construction at the end of `search`, add `feasibility_restart_batches=feasibility_restart_batches`.

- [ ] **Step 5: Add the result field and the refusal reason**

In `SequenceSearchResult` (`:756`), after `termination: str`:

```python
    #: Continuation batches appended after the derived schedule ended without an
    #: exact incumbent.  Observational only; nothing branches on it.
    feasibility_restart_batches: int = 0
```

In the reason map inside `search` (`:1345-1351`), add one entry:

```python
                "feasibility-exhausted": (
                    "feasibility continuation exhausted its restart budget "
                    "before an exact layout"
                ),
```

- [ ] **Step 6: Run the solver tests and the whole suite**

```bash
uv run pytest tests/layout/test_sequence_solver.py -q
uv run pytest -q
```

Expected: all pass, including the five new tests. If `test_all_products_sequence_pair_honours_the_exact_layout_deadline` fails with DID NOT RAISE, apply the fragility note above: lower that test's `time_budget_s` (it is a literal in the test) until it refuses again, and record the old and new values in the commit message.

- [ ] **Step 7: Turn the production path on, widen the protocol, declare the stat**

In `SequencePairLayout.lay_out` (`sequence_solver.py:5281`):

```python
                result = run.solver.search(
                    max_stages=run.max_search_stages,
                    feasibility_continuation=True,
                )
```

At `sequence_solver.py:5229`, the bare `solver.search().placement` becomes:

```python
                    solver.search(feasibility_continuation=True).placement,
```

Read the ten lines around `:5229` first (`sed -n '5215,5240p' src/flab2bp/layout/sequence_solver.py`): if that call site is inside a test-only or probe-only branch that deliberately wants a hard cap, leave it and say so in the commit message.

In `sequence_islands.py:139`, `result = run.solver.search()` becomes `result = run.solver.search(feasibility_continuation=True)` — an island child carries its own `absolute_deadline`, so the same rule applies inside it.

In `_SearchSolver` (`sequence_solver.py:5164`):

```python
class _SearchSolver(Protocol):
    def search(
        self,
        *,
        max_stages: int | None = None,
        feasibility_continuation: bool = False,
    ) -> SequenceSearchResult: ...
```

In `PlacementStats` (`base.py:198`), in alphabetical position:

```python
    feasibility_restart_batches: float
```

In the production stats dict (`sequence_solver.py:5390-5445`), beside `"termination"`:

```python
            "feasibility_restart_batches": float(result.feasibility_restart_batches),
```

- [ ] **Step 8: Write the graphene gate test**

Add to `tests/test_pipeline.py`, beside the existing graphene fixtures at `:559-566`:

```python
@pytest.mark.slow
def test_graphene_output_products_sequence_pair_uses_feasibility_continuation() -> None:
    """The tiny fast-path stage cap must no longer end the search with clock left.

    `_search_stage_cap` returns 2 for this spec (6 machines, under
    `_TOPOLOGY_BEAM_MIN_STRIPS`, two spray lanes).  Before the continuation the
    search spent two stages, refused with "no scheduled stage produced an exact
    layout", and handed back most of its budget unused.
    """
    from flab2bp.lab.data import load_vendored
    from flab2bp.lab.url import parse_url

    entry = next(candidate for candidate in URL_CORPUS if candidate.url_id == "graphene")
    built = build_candidates(
        load_vendored(),
        parse_url(entry.url),
        candidate_policies=DEFAULT_CANDIDATE_POLICIES,
    )
    spec = next(
        candidate.spec for candidate in built.candidates if candidate.label == "output-products"
    )
    placement = SequencePairLayout(band_policy=BandPolicy.parse("any")).lay_out(
        spec, time_budget_s=30.0
    )
    assert placement.stats["feasibility_restart_batches"] >= 1.0
```

`flab2bp.lab.data.load_vendored` and `flab2bp.lab.url.parse_url` are the import paths
`tests/layout/test_freeform.py:215-216` uses. Resolve `built.candidates`, `candidate.label` and
`candidate.spec` against that same fixture (`plastic_spec()` at `:206-219`) and mirror whatever it
does.

- [ ] **Step 9: Run the gate test**

Run: `uv run pytest tests/test_pipeline.py::test_graphene_output_products_sequence_pair_uses_feasibility_continuation -v`
Expected: PASS in roughly 5 to 30 seconds. If it fails with `NoValidLayout`, the continuation is running but not finding a layout: record the raised reason and the `feasibility_restart_batches` value from a manual run, and report before changing anything else. If it fails on `KeyError: 'feasibility_restart_batches'`, Step 7's stats line did not land.

- [ ] **Step 10: Confirm gate 1 on the real audit cell**

```bash
uv run python scripts/audit.py --budget 30 --jobs 4 --strategy sequence-pair --only graphene \
  --json /tmp/phase-c-task2.jsonl | tail -6
jq -r '[.strategy,.spec_label,.status,.seconds,.detail] | @tsv' /tmp/phase-c-task2.jsonl
```

Expected: every graphene cell `CLEAN`. Record the `output-products` line in the commit message. If it is still `REFUSED`, stop and report the detail string.

- [ ] **Step 11: Lint, type-check, commit**

```bash
uv run ruff check src/flab2bp/layout tests/layout/test_sequence_solver.py tests/test_pipeline.py
uv run mypy src/flab2bp/layout/sequence_solver.py src/flab2bp/layout/base.py
uv run pytest -q
git add src/flab2bp/layout/sequence_solver.py src/flab2bp/layout/sequence_islands.py src/flab2bp/layout/base.py tests/layout/test_sequence_solver.py tests/test_pipeline.py
git commit -m "feat(layout): continue sequence-pair search for feasibility past the stage schedule"
```

---

### Task 3: `sequence_alns.py` — identities, records, selector, reward

**Files:**
- Create: `src/flab2bp/layout/sequence_alns.py`
- Test: `tests/layout/test_sequence_alns.py`

**Interfaces:**
- Consumes: `RouteFailureKind`, `DetailedRouteResult`, `FeedbackState`, `select_lns_neighbourhood` (`route_feedback.py:72`, `:119`, `:163`, `:549`); `DecodedPlacement`, `GapProfile`, `PlacementProblem`, `SequencePair` (`sequence_pair.py`).
- Produces: `DestroyOperator`, `RepairOperator`, `SHIPPED_DESTROY`, `SHIPPED_REPAIR`, `OperatorContext`, `OperatorChoice`, `OperatorMetrics`, `OperatorOutcome`, `reward_vector`, `operator_scale`, `remaining_fraction_bucket`, `metrics_from_evaluation`, `destroy_strips`, `operator_tally`, `OperatorSession`; the constants `REWARD_RANKS = 5`, `C_DUCB_DISCOUNT = 0.9`, `C_DUCB_EXPLORATION = 0.5`, `C_DUCB_SCORE_QUANTUM = 1e-9`, `C_CONTEXT_FRACTION_STEPS = 10`, `C_WINDOW_FRACTION_FLOOR = 1`, `C_MIN_DESTROY_STRIPS = 2`, `C_MAX_DESTROY_STRIPS = 12`, `C_SCALE_FRACTION = 0.15`, `C_SCALE_GROWTH = 2`, `C_GROW_AFTER = 2`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/layout/test_sequence_alns.py
from __future__ import annotations

import math

import pytest

from flab2bp.layout.route_feedback import (
    DetailedRouteResult,
    DetailedRouteStatus,
    FeedbackState,
    NetFailure,
    NetId,
    NetRole,
    RouteFailureKind,
    select_lns_neighbourhood,
)
from flab2bp.layout.sequence_alns import (
    C_CONTEXT_FRACTION_STEPS,
    C_DUCB_DISCOUNT,
    C_MAX_DESTROY_STRIPS,
    C_MIN_DESTROY_STRIPS,
    REWARD_RANKS,
    SHIPPED_DESTROY,
    SHIPPED_REPAIR,
    DestroyOperator,
    OperatorChoice,
    OperatorContext,
    OperatorMetrics,
    OperatorOutcome,
    OperatorSession,
    RepairOperator,
    destroy_strips,
    metrics_from_evaluation,
    operator_scale,
    operator_tally,
    remaining_fraction_bucket,
    reward_vector,
)
from flab2bp.layout.sequence_pair import AnnealState, PlacementProblem, decode_state


def _context(**overrides: object) -> OperatorContext:
    base: dict[str, object] = {
        "strip_count": 20,
        "stagnation": 0,
        "remaining_fraction": 7,
    }
    base.update(overrides)
    return OperatorContext(**base)  # type: ignore[arg-type]


def _metrics(**overrides: object) -> OperatorMetrics:
    base: dict[str, object] = {
        "validator_clean": False,
        "failed_nets": 4,
        "band_overflow": 10,
        "congestion": 8.0,
        "area": 1000,
    }
    base.update(overrides)
    return OperatorMetrics(**base)  # type: ignore[arg-type]


def _choice(destroy: DestroyOperator, repair: RepairOperator) -> OperatorChoice:
    return OperatorChoice(destroy=destroy, repair=repair, scale=4, ordinal=0)


def _outcome(before: OperatorMetrics, after: OperatorMetrics) -> OperatorOutcome:
    return OperatorOutcome(
        choice=_choice(DestroyOperator.FAILED_ENDPOINTS, RepairOperator.SEQUENCE_REINSERT),
        before=before,
        after=after,
        applied=True,
    )


def _problem() -> PlacementProblem:
    return PlacementProblem(
        sizes=((4, 3), (4, 3), (4, 3), (4, 3)),
        nets=((0, 1), (1, 2), (2, 3)),
        outline_height=12,
        area_lower_bound=48,
    )


def _routing() -> DetailedRouteResult:
    return DetailedRouteResult(
        status=DetailedRouteStatus.STRANDED,
        routed=(),
        failures=(
            NetFailure(
                net_id=NetId(0, 1, "iron-ore", NetRole.INTERNAL, 0),
                kind=RouteFailureKind.CONGESTION_WALL,
                wall=((2, 2, 0), (2, 3, 0)),
                blocking_nets=(NetId(2, 3, "copper-ore", NetRole.INTERNAL, 1),),
                expansions=17,
            ),
        ),
        iterations=1,
        expansions=17,
    )


# --- portfolio ---------------------------------------------------------------


def test_only_the_shipped_operators_are_ever_selected() -> None:
    session = OperatorSession()
    for _ in range(12):
        choice = session.select(_context())
        assert choice.destroy in SHIPPED_DESTROY
        assert choice.repair in SHIPPED_REPAIR
        session.observe(choice, (0.0,) * REWARD_RANKS, applied=True)


def test_a_follow_up_destroy_operator_has_no_dispatch_branch() -> None:
    problem = _problem()
    state = AnnealState.initial(problem.size, 7)
    decoded = decode_state(problem, state)
    with pytest.raises(NotImplementedError):
        destroy_strips(
            DestroyOperator.BLOCKER_COMPONENT,
            scale=4,
            result=_routing(),
            pair=state.pair,
            gaps=state.gaps,
            problem=problem,
            decoded=decoded,
            band_target_width=decoded.width,
        )


# --- selector ----------------------------------------------------------------


def test_every_arm_is_played_once_before_any_arm_is_played_twice() -> None:
    session = OperatorSession()
    seen_destroy: list[DestroyOperator] = []
    seen_repair: list[RepairOperator] = []
    for _ in range(max(len(SHIPPED_DESTROY), len(SHIPPED_REPAIR))):
        choice = session.select(_context(remaining_fraction=C_CONTEXT_FRACTION_STEPS))
        seen_destroy.append(choice.destroy)
        seen_repair.append(choice.repair)
        session.observe(choice, (1.0, 0.0, 0.0, 0.0, 0.0), applied=True)
    assert seen_destroy[: len(SHIPPED_DESTROY)] == list(SHIPPED_DESTROY)
    assert seen_repair[: len(SHIPPED_REPAIR)] == list(SHIPPED_REPAIR)
    assert len(set(seen_destroy[: len(SHIPPED_DESTROY)])) == len(SHIPPED_DESTROY)


def test_a_tie_on_rank_zero_is_broken_by_rank_one() -> None:
    session = OperatorSession()
    rewards = {
        DestroyOperator.FAILED_ENDPOINTS: (0.0, 1.0, 0.0, 0.0, 0.0),
        DestroyOperator.BAND_BOUNDARY: (0.0, 5.0, 0.0, 0.0, 0.0),
    }
    for _ in range(len(SHIPPED_DESTROY)):
        choice = session.select(_context())
        session.observe(choice, rewards[choice.destroy], applied=True)
    assert session.select(_context()).destroy is DestroyOperator.BAND_BOUNDARY


def test_rank_zero_outranks_every_later_rank() -> None:
    session = OperatorSession()
    rewards = {
        DestroyOperator.FAILED_ENDPOINTS: (1.0, 0.0, 0.0, 0.0, 0.0),
        DestroyOperator.BAND_BOUNDARY: (0.0, 9.0, 9.0, 9.0, 9.0),
    }
    for _ in range(len(SHIPPED_DESTROY)):
        choice = session.select(_context())
        session.observe(choice, rewards[choice.destroy], applied=True)
    assert session.select(_context()).destroy is DestroyOperator.FAILED_ENDPOINTS


def test_the_exploration_bonus_only_breaks_a_tie_on_every_mean() -> None:
    session = OperatorSession()
    for _ in range(len(SHIPPED_DESTROY)):
        choice = session.select(_context())
        session.observe(choice, (0.0,) * REWARD_RANKS, applied=True)
    # Both arms have identical (zero) means, so the less-played arm wins on the bonus.
    first = session.select(_context())
    session.observe(first, (0.0,) * REWARD_RANKS, applied=True)
    assert session.select(_context()).destroy is not first.destroy


def test_selection_is_deterministic_for_the_same_observation_sequence() -> None:
    def run() -> tuple[OperatorChoice, ...]:
        session = OperatorSession()
        rewards = [
            (0.0, 1.0, 0.0, 0.0, 0.0),
            (0.0, 0.0, 2.0, 0.0, 0.0),
            (1.0, 0.0, 0.0, 0.0, 0.0),
        ]
        for index in range(24):
            choice = session.select(_context(stagnation=index % 3))
            session.observe(choice, rewards[index % 3], applied=True)
        return session.choices

    assert run() == run()


def test_discounting_decays_every_arm_on_every_observation() -> None:
    session = OperatorSession()
    played = session.select(_context())
    for _ in range(4):
        session.observe(played, (0.0,) * REWARD_RANKS, applied=True)
    expected = sum(C_DUCB_DISCOUNT**index for index in range(4))
    assert math.isclose(
        session.credit[f"count:{played.destroy.value}"], expected, rel_tol=1e-12
    )


def test_local_exact_pack_is_not_offered_without_room_for_a_window() -> None:
    session = OperatorSession()
    for _ in range(12):
        choice = session.select(_context(remaining_fraction=0))
        assert choice.repair is not RepairOperator.LOCAL_EXACT_PACK
        session.observe(choice, (0.0,) * REWARD_RANKS, applied=True)


def test_local_exact_pack_is_offered_with_room() -> None:
    session = OperatorSession()
    repairs = set()
    for _ in range(len(SHIPPED_REPAIR)):
        choice = session.select(_context(remaining_fraction=C_CONTEXT_FRACTION_STEPS))
        repairs.add(choice.repair)
        session.observe(choice, (0.0,) * REWARD_RANKS, applied=True)
    assert RepairOperator.LOCAL_EXACT_PACK in repairs


def test_scale_grows_with_stagnation_and_stays_inside_its_bounds() -> None:
    assert operator_scale(_context(strip_count=4, stagnation=0)) == C_MIN_DESTROY_STRIPS
    assert operator_scale(_context(strip_count=200, stagnation=0)) == C_MAX_DESTROY_STRIPS
    assert operator_scale(_context(strip_count=20, stagnation=0)) == 3
    assert operator_scale(_context(strip_count=20, stagnation=2)) == 7
    assert operator_scale(_context(strip_count=3, stagnation=9)) == 2


def test_remaining_fraction_bucket_quantizes_a_real_ratio() -> None:
    assert remaining_fraction_bucket(30.0, 30.0) == C_CONTEXT_FRACTION_STEPS
    assert remaining_fraction_bucket(0.0, 30.0) == 0
    assert remaining_fraction_bucket(15.0, 30.0) == C_CONTEXT_FRACTION_STEPS // 2
    assert remaining_fraction_bucket(-1.0, 30.0) == 0
    assert remaining_fraction_bucket(5.0, 0.0) == 0


# --- reward ------------------------------------------------------------------


def test_reward_is_the_lexicographic_improvement_with_no_time_divisor() -> None:
    after = _metrics(failed_nets=1, band_overflow=4, congestion=3.0)
    assert reward_vector(_outcome(_metrics(), after)) == (0.0, 3.0, 6.0, 5.0, 0.0)
    # The outcome record carries no seconds at all, so there is nothing a clock
    # could perturb; `observe` takes them separately, for telemetry only.
    assert "routing_seconds" not in OperatorOutcome.__dataclass_fields__


def test_a_clean_placement_outranks_every_other_improvement() -> None:
    clean = reward_vector(_outcome(_metrics(), _metrics(validator_clean=True, area=1200)))
    dirty = reward_vector(
        _outcome(_metrics(), _metrics(failed_nets=0, band_overflow=0, congestion=0.0))
    )
    assert clean > dirty


def test_area_credit_requires_a_clean_placement() -> None:
    assert reward_vector(_outcome(_metrics(), _metrics(area=500)))[4] == 0.0
    assert reward_vector(
        _outcome(_metrics(), _metrics(validator_clean=True, area=500))
    )[4] == 0.5


def test_regressions_never_produce_negative_reward() -> None:
    assert reward_vector(
        _outcome(_metrics(), _metrics(failed_nets=9, band_overflow=99, congestion=99.0))
    ) == (0.0, 0.0, 0.0, 0.0, 0.0)


def test_an_unapplied_outcome_costs_a_count_and_earns_nothing() -> None:
    session = OperatorSession()
    choice = session.select(_context())
    session.observe(choice, (1.0, 1.0, 1.0, 1.0, 1.0), applied=False)
    assert session.credit[f"count:{choice.destroy.value}"] == 1.0
    assert session.credit[f"reward:{choice.destroy.value}:0"] == 0.0
    assert session.applied == 0


def test_observe_and_select_credits_the_pending_choice_before_choosing() -> None:
    session = OperatorSession()
    first = session.observe_and_select(_metrics(), _context())
    assert session.pending == first
    # The first call has no baseline to compare against, so it credits nothing.
    assert all(
        value == 0.0 for key, value in session.credit.items() if key.startswith("count:")
    )
    second = session.observe_and_select(
        _metrics(failed_nets=1), _context(), routing_seconds=1.5
    )
    assert session.pending == second
    assert session.credit[f"count:{first.destroy.value}"] == 1.0
    assert session.choices == (first, second)
    assert session.routing_seconds == 1.5


def test_observe_and_select_with_no_baseline_only_selects() -> None:
    session = OperatorSession()
    choice = session.observe_and_select(_metrics(), _context())
    assert session.choices == (choice,)
    assert all(
        value == 0.0 for key, value in session.credit.items() if key.startswith("count:")
    )


# --- shared helpers ----------------------------------------------------------


def test_failed_endpoints_destroy_matches_the_existing_lns_neighbourhood() -> None:
    problem = _problem()
    state = AnnealState.initial(problem.size, 7)
    decoded = decode_state(problem, state)
    expected = select_lns_neighbourhood(
        _routing(), state.pair, state.gaps, problem, decoded, stagnation=0, grow_after=2
    )
    assert (
        destroy_strips(
            DestroyOperator.FAILED_ENDPOINTS,
            scale=problem.size,
            result=_routing(),
            pair=state.pair,
            gaps=state.gaps,
            problem=problem,
            decoded=decoded,
            band_target_width=decoded.width,
        )
        == expected
    )


def test_destroy_respects_its_scale_cap() -> None:
    problem = _problem()
    state = AnnealState.initial(problem.size, 7)
    decoded = decode_state(problem, state)
    assert (
        len(
            destroy_strips(
                DestroyOperator.FAILED_ENDPOINTS,
                scale=1,
                result=_routing(),
                pair=state.pair,
                gaps=state.gaps,
                problem=problem,
                decoded=decoded,
                band_target_width=decoded.width,
            )
        )
        <= 1
    )


def test_metrics_read_failed_nets_overflow_congestion_and_realized_area() -> None:
    problem = _problem()
    state = AnnealState.initial(problem.size, 7)
    decoded = decode_state(problem, state)
    feedback = FeedbackState(
        outline=(decoded.width, problem.outline_height),
        net_weight={},
        # (0, 0, 0) is the decoy: heavy, NOT on either wall cell, and inside the
        # outline whatever the decode width turns out to be.  A decoy outside the
        # outline raises in `FeedbackState.__post_init__`.
        cell_history={(2, 2, 0): 1.5, (2, 3, 0): 2.5, (0, 0, 0): 4.0},
    )
    metrics = metrics_from_evaluation(
        _routing(),
        decoded,
        feedback,
        outline_height=problem.outline_height,
        band_target_width=decoded.width - 2,
        validator_clean=False,
    )
    assert metrics.failed_nets == 1
    assert metrics.band_overflow == (
        max(0, decoded.used_height - problem.outline_height) + 2
    )
    assert metrics.congestion == 4.0
    assert metrics.area == decoded.width * decoded.used_height


def test_operator_tally_names_both_ledgers() -> None:
    session = OperatorSession()
    session.observe(session.select(_context()), (0.0,) * REWARD_RANKS, applied=True)
    tally = operator_tally(session)
    assert tally.startswith("destroy:")
    assert "|repair:" in tally
    for part in tally.split("|"):
        kind, name, count = part.split(":")
        assert kind in {"destroy", "repair"}
        assert name
        assert count.isdigit()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/layout/test_sequence_alns.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'flab2bp.layout.sequence_alns'`.

- [ ] **Step 3: Write the module head, identities and records**

```python
# src/flab2bp/layout/sequence_alns.py
"""Adaptive large-neighbourhood operator selection for the placement search.

The measured finding this module is built around is a negative one, recorded in
full at ``freeform._pack``'s removed routing-capacity cut: no cheap surrogate
predicts whether a placement will route (four estimates, 270 real packs, AUC
0.500 / 0.500 / 0.535 / 0.525, with cut-capacity slack anti-correlated at 0.422
as the control).  So an operator here is never scored by a proxy at selection
time.  It is paid, one evaluation later, by what the real detailed router then
did -- which is why :meth:`OperatorSession.observe_and_select` credits the
previous choice before it makes the next one.

Nothing in selection reads a clock.  ``reward_vector`` has no time divisor and
consults no RNG, so for a fixed seed and a fixed deterministic budget the
sequence of choices replays exactly.  ``routing_seconds`` is carried on the
outcome and summed for telemetry, and is read nowhere else.

The shipped portfolio is deliberately four operators.  The other enum members
exist so adding one later is a new dispatch branch rather than a redesign; the
rule for adding one is that a refusing corpus cell names its mechanism.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from flab2bp.layout.route_feedback import (
    DetailedRouteResult,
    FeedbackState,
    select_lns_neighbourhood,
)
from flab2bp.layout.sequence_pair import (
    DecodedPlacement,
    GapProfile,
    PlacementProblem,
    SequencePair,
)

#: Per-observation discount applied to EVERY arm's count and reward sums, which
#: is what makes this a discounted UCB rather than a stationary one: an operator
#: that helped ten stages ago should not outvote what the router said last.
C_DUCB_DISCOUNT = 0.9
#: Coefficient of the SINGLE exploration bonus, appended after the five means as
#: the last tie-break.  A bonus added to every rank would let exploration on
#: rank 4 outvote a real difference on rank 1, which is the exchange a
#: lexicographic reward exists to forbid.
C_DUCB_EXPLORATION = 0.5
#: Means are quantized before comparison so float association order cannot
#: decide an arm.  Ties then fall to declaration order.
C_DUCB_SCORE_QUANTUM = 1e-9
#: Buckets for ``OperatorContext.remaining_fraction``.
C_CONTEXT_FRACTION_STEPS = 10
#: Bucket below which LOCAL_EXACT_PACK is not offered: a window started with no
#: room to finish spends its whole cost and buys nothing.
C_WINDOW_FRACTION_FLOOR = 1
#: Destroy-cardinality bounds and the schedule between them.
C_MIN_DESTROY_STRIPS = 2
C_MAX_DESTROY_STRIPS = 12
C_SCALE_FRACTION = 0.15
C_SCALE_GROWTH = 2
#: `select_lns_neighbourhood`'s ring-growth threshold.  Production has never
#: passed a non-zero stagnation, so the branch stays dormant; the constant is
#: here so the call site is explicit rather than relying on a default.
C_GROW_AFTER = 2
#: Reward ranks, in lexicographic order.  See :func:`reward_vector`.
REWARD_RANKS = 5


class DestroyOperator(StrEnum):
    """Which strips a repair may move.  Declaration order is the tie-break."""

    FAILED_ENDPOINTS = "failed-endpoints"
    BAND_BOUNDARY = "band-boundary"
    #: Follow-ups: named so the enum is extensible, with no dispatch branch and
    #: no arm.  Added when a refusing cell names the mechanism.
    BLOCKER_COMPONENT = "blocker-component"
    CONGESTED_CUT = "congested-cut"
    RELATED_CARGO = "related-cargo"
    DIVERSIFY = "diversify"


class RepairOperator(StrEnum):
    """How destroyed strips are put back.  Declaration order is the tie-break."""

    SEQUENCE_REINSERT = "sequence-reinsert"
    LOCAL_EXACT_PACK = "local-exact-pack"
    #: Follow-up, as above.
    ROUTING_REGRET = "routing-regret"


SHIPPED_DESTROY: tuple[DestroyOperator, ...] = (
    DestroyOperator.FAILED_ENDPOINTS,
    DestroyOperator.BAND_BOUNDARY,
)
SHIPPED_REPAIR: tuple[RepairOperator, ...] = (
    RepairOperator.SEQUENCE_REINSERT,
    RepairOperator.LOCAL_EXACT_PACK,
)


@dataclass(frozen=True, slots=True)
class OperatorContext:
    """The situation the selector chooses in.  Every field has a reader."""

    #: Read by :func:`operator_scale`.
    strip_count: int
    #: Read by :func:`operator_scale`.
    stagnation: int
    #: Read by :meth:`OperatorSession.select` to gate LOCAL_EXACT_PACK.
    remaining_fraction: int

    def __post_init__(self) -> None:
        for value, name in (
            (self.strip_count, "strip count"),
            (self.stagnation, "stagnation"),
            (self.remaining_fraction, "remaining fraction"),
        ):
            if type(value) is not int or value < 0:
                raise ValueError(f"operator context {name} must be a non-negative integer")
        if self.remaining_fraction > C_CONTEXT_FRACTION_STEPS:
            raise ValueError("remaining fraction must be a bucket index")


@dataclass(frozen=True, slots=True)
class OperatorChoice:
    """One destroy/repair pairing at one cardinality, with its selection index."""

    destroy: DestroyOperator
    repair: RepairOperator
    scale: int
    ordinal: int

    def __post_init__(self) -> None:
        if type(self.scale) is not int or self.scale < 1:
            raise ValueError("operator scale must be a positive integer")
        if type(self.ordinal) is not int or self.ordinal < 0:
            raise ValueError("operator ordinal must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class OperatorMetrics:
    """The five measured quantities the reward ranks over, in rank order."""

    validator_clean: bool
    failed_nets: int
    band_overflow: int
    congestion: float
    #: The REALIZED extent, ``width * used_height``.  The outline height is a
    #: search parameter; the extent is what gets built and validated.
    area: int

    def __post_init__(self) -> None:
        if type(self.validator_clean) is not bool:
            raise ValueError("validator-clean marker must be a bool")
        for value, name in (
            (self.failed_nets, "failed nets"),
            (self.band_overflow, "band overflow"),
            (self.area, "area"),
        ):
            if type(value) is not int or value < 0:
                raise ValueError(f"operator metric {name} must be a non-negative integer")
        if not math.isfinite(self.congestion) or self.congestion < 0.0:
            raise ValueError("operator metric congestion must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class OperatorOutcome:
    """One choice, the evaluation before it, and the evaluation after it.

    No measured seconds live here.  A wall-clock divisor would make the ledger a
    function of machine load, and the corpus audit runs sixteen cells in parallel
    by design -- so rather than carry a field nothing reads (and invite someone
    to read it), seconds go straight to :meth:`OperatorSession.observe`, which
    sums them for telemetry.
    """

    choice: OperatorChoice
    before: OperatorMetrics
    after: OperatorMetrics
    applied: bool

    def __post_init__(self) -> None:
        if type(self.applied) is not bool:
            raise ValueError("outcome applied marker must be a bool")
```

- [ ] **Step 4: Add the pure functions**

Append to `sequence_alns.py`:

```python
def reward_vector(outcome: OperatorOutcome) -> tuple[float, ...]:
    """Return one lexicographic reward vector.  No divisor, no clock.

    The ordering is the reliability design's: a validator-clean placement, then
    fewer failed nets, then less projection/band overflow, then less congestion,
    then a smaller area.  Area is credited only when the placement is clean, so
    no amount of density can buy back validity -- that is the whole reason the
    reward is a vector rather than a weighted sum.
    """
    before, after = outcome.before, outcome.after
    clean = 1.0 if after.validator_clean and not before.validator_clean else 0.0
    failed = float(max(0, before.failed_nets - after.failed_nets))
    overflow = float(max(0, before.band_overflow - after.band_overflow))
    congestion = max(0.0, before.congestion - after.congestion)
    area = (
        max(0, before.area - after.area) / before.area
        if after.validator_clean and before.area > 0
        else 0.0
    )
    return (clean, failed, overflow, congestion, area)


def remaining_fraction_bucket(remaining_s: float, ceiling_s: float) -> int:
    """Quantize a real clock ratio so wall jitter cannot flip a decision."""
    if ceiling_s <= 0.0:
        return 0
    ratio = min(1.0, max(0.0, remaining_s / ceiling_s))
    return int(ratio * C_CONTEXT_FRACTION_STEPS)


def operator_scale(context: OperatorContext) -> int:
    """Return the destroy cardinality for one situation.

    Scale is a function of the context and not a learned arm: folding
    cardinalities into the arm identity would multiply an arm count that already
    has only two to eight observations per budget to learn from on the largest
    cells.
    """
    base = max(C_MIN_DESTROY_STRIPS, round(C_SCALE_FRACTION * context.strip_count))
    grown = base + C_SCALE_GROWTH * context.stagnation
    return max(1, min(grown, C_MAX_DESTROY_STRIPS, max(1, context.strip_count - 1)))


def metrics_from_evaluation(
    result: DetailedRouteResult,
    decoded: DecodedPlacement,
    feedback: FeedbackState,
    *,
    outline_height: int,
    band_target_width: int,
    validator_clean: bool,
) -> OperatorMetrics:
    """Read the five reward quantities off one completed evaluation.

    ``congestion`` is the summed cell history over the failure walls, which is
    the same evidence `_pack`'s feedback terms and the annealing `history_cost`
    already consume; it is the only rank whose scale is spec-dependent, which is
    why every rank is compared as an improvement rather than as a level.
    """
    congestion = 0.0
    for failure in result.failures:
        for cell in failure.wall:
            congestion += feedback.cell_history.get(cell, 0.0)
    overflow = max(0, decoded.used_height - outline_height) + max(
        0, decoded.width - band_target_width
    )
    return OperatorMetrics(
        validator_clean=validator_clean,
        failed_nets=result.failed_count,
        band_overflow=overflow,
        congestion=congestion,
        area=decoded.width * decoded.used_height,
    )


def _capped(strips: Iterable[int], *, scale: int) -> frozenset[int]:
    """Truncate a destroy set in the order its operator ranked it.

    Order-preserving on purpose.  `FAILED_ENDPOINTS` hands over an unordered set
    and sorts it itself, so index order is its ranking; `BAND_BOUNDARY` ranks by
    overflow contribution, and truncating THAT by index would drop the worst
    offender and keep the mildest, which is the opposite of the operator.
    """
    return frozenset(list(strips)[:scale])


def destroy_strips(
    operator: DestroyOperator,
    *,
    scale: int,
    result: DetailedRouteResult,
    pair: SequencePair,
    gaps: GapProfile,
    problem: PlacementProblem,
    decoded: DecodedPlacement,
    band_target_width: int,
) -> frozenset[int]:
    """Return the strips one destroy operator frees, capped at ``scale``.

    An operator whose evidence is absent returns an empty set; the caller
    credits that as an unapplied choice rather than retrying it forever.
    """
    if operator is DestroyOperator.FAILED_ENDPOINTS:
        return _capped(
            sorted(
                select_lns_neighbourhood(
                    result,
                    pair,
                    gaps,
                    problem,
                    decoded,
                    stagnation=0,
                    grow_after=C_GROW_AFTER,
                )
            ),
            scale=scale,
        )
    raise NotImplementedError(
        f"destroy operator {operator.value} is a follow-up with no dispatch branch"
    )
```

`BAND_BOUNDARY`'s branch lands in Task 6; until then the shipped portfolio is restricted at the
call site (Task 5) so the `NotImplementedError` is unreachable in production.

- [ ] **Step 5: Add the ledger, the session and the tally**

Append to `sequence_alns.py`:

```python
@dataclass(slots=True)
class _Ledger:
    """One discounted count and one discounted reward sum per rank, per arm."""

    counts: dict[str, float]
    rewards: dict[str, list[float]]
    order: tuple[str, ...]

    @classmethod
    def over(cls, arms: Sequence[str]) -> _Ledger:
        return cls(
            counts=dict.fromkeys(arms, 0.0),
            rewards={arm: [0.0] * REWARD_RANKS for arm in arms},
            order=tuple(arms),
        )

    def decay(self, discount: float) -> None:
        for arm in self.order:
            self.counts[arm] *= discount
            rewards = self.rewards[arm]
            for rank in range(REWARD_RANKS):
                rewards[rank] *= discount

    def credit(self, arm: str, reward: Sequence[float]) -> None:
        self.counts[arm] += 1.0
        rewards = self.rewards[arm]
        for rank in range(REWARD_RANKS):
            rewards[rank] += float(reward[rank])

    def best(self, exploration: float, *, among: Sequence[str] | None = None) -> str:
        """Return the winning arm: five means lexicographically, then one bonus."""
        arms = tuple(among) if among else self.order
        untried = [arm for arm in arms if self.counts[arm] == 0.0]
        if untried:
            return untried[0]
        total = sum(self.counts[arm] for arm in self.order)
        logarithm = math.log(max(total, math.e))
        best_arm = arms[0]
        best_score: tuple[float, ...] | None = None
        for arm in arms:
            count = self.counts[arm]
            means = tuple(
                round((self.rewards[arm][rank] / count) / C_DUCB_SCORE_QUANTUM)
                * C_DUCB_SCORE_QUANTUM
                for rank in range(REWARD_RANKS)
            )
            score = (*means, exploration * math.sqrt(logarithm / count))
            if best_score is None or score > best_score:
                best_arm, best_score = arm, score
        return best_arm


class OperatorSession:
    """Deterministic discounted-UCB selection over destroy and repair arms.

    Two independent ledgers rather than one over pairs: the product of the two
    portfolios cannot be learned inside a thirty-second budget, and destroy
    quality and repair quality are separately attributable because both are
    credited by the same realized outcome.
    """

    def __init__(
        self,
        *,
        destroy_arms: Sequence[DestroyOperator] = SHIPPED_DESTROY,
        repair_arms: Sequence[RepairOperator] = SHIPPED_REPAIR,
        discount: float = C_DUCB_DISCOUNT,
        exploration: float = C_DUCB_EXPLORATION,
    ) -> None:
        if not 0.0 < discount <= 1.0:
            raise ValueError("discount must lie in (0, 1]")
        if exploration < 0.0:
            raise ValueError("exploration coefficient must be non-negative")
        destroy = tuple(destroy_arms)
        repair = tuple(repair_arms)
        if not destroy or not repair:
            raise ValueError("an operator session needs at least one arm of each kind")
        if len(set(destroy)) != len(destroy) or len(set(repair)) != len(repair):
            raise ValueError("operator arms must be distinct")
        self._discount = discount
        self._exploration = exploration
        self._destroy = _Ledger.over([operator.value for operator in destroy])
        self._repair = _Ledger.over([operator.value for operator in repair])
        self._repair_arms = repair
        self._choices: list[OperatorChoice] = []
        self._pending: OperatorChoice | None = None
        self._baseline: OperatorMetrics | None = None
        self._applied = 0
        self._routing_seconds = 0.0

    @property
    def choices(self) -> tuple[OperatorChoice, ...]:
        """Every choice this session has made, in order."""
        return tuple(self._choices)

    @property
    def pending(self) -> OperatorChoice | None:
        """The choice awaiting an outcome, if any."""
        return self._pending

    @property
    def applied(self) -> int:
        """How many observed choices actually ran a destroy and a repair."""
        return self._applied

    @property
    def routing_seconds(self) -> float:
        """Summed measured routing seconds across observations.  Telemetry only."""
        return self._routing_seconds

    @property
    def credit(self) -> Mapping[str, float]:
        """Flat discounted ledger, for telemetry and tests."""
        flat: dict[str, float] = {}
        for ledger in (self._destroy, self._repair):
            for arm in ledger.order:
                flat[f"count:{arm}"] = ledger.counts[arm]
                for rank in range(REWARD_RANKS):
                    flat[f"reward:{arm}:{rank}"] = ledger.rewards[arm][rank]
        return flat

    def _affordable_repairs(self, context: OperatorContext) -> tuple[str, ...]:
        if context.remaining_fraction >= C_WINDOW_FRACTION_FLOOR:
            return self._repair.order
        affordable = tuple(
            operator.value
            for operator in self._repair_arms
            if operator is not RepairOperator.LOCAL_EXACT_PACK
        )
        return affordable or self._repair.order

    def select(self, context: OperatorContext) -> OperatorChoice:
        """Choose the next destroy/repair pairing.  Consults no RNG, no clock."""
        choice = OperatorChoice(
            destroy=DestroyOperator(self._destroy.best(self._exploration)),
            repair=RepairOperator(
                self._repair.best(
                    self._exploration, among=self._affordable_repairs(context)
                )
            ),
            scale=operator_scale(context),
            ordinal=len(self._choices),
        )
        self._choices.append(choice)
        self._pending = choice
        return choice

    def observe(
        self,
        choice: OperatorChoice,
        reward: Sequence[float],
        *,
        applied: bool,
        routing_seconds: float = 0.0,
    ) -> None:
        """Credit one choice with its realized reward vector.

        An unapplied choice still costs a count and earns nothing, so an
        operator whose evidence is chronically absent loses its turn instead of
        being retried forever.
        """
        if len(reward) != REWARD_RANKS:
            raise ValueError(f"reward vector must carry {REWARD_RANKS} ranks")
        if any(not math.isfinite(value) or value < 0.0 for value in reward):
            raise ValueError("reward components must be finite and non-negative")
        credited = tuple(reward) if applied else (0.0,) * REWARD_RANKS
        self._destroy.decay(self._discount)
        self._repair.decay(self._discount)
        self._destroy.credit(choice.destroy.value, credited)
        self._repair.credit(choice.repair.value, credited)
        self._routing_seconds += max(0.0, routing_seconds)
        if applied:
            self._applied += 1
        if self._pending == choice:
            self._pending = None

    def observe_and_select(
        self,
        metrics: OperatorMetrics,
        context: OperatorContext,
        *,
        routing_seconds: float = 0.0,
        applied: bool = True,
    ) -> OperatorChoice:
        """Credit the pending choice with what the router just did, then choose.

        The credit lands one evaluation late by design: an operator is paid by
        the realized routing outcome, never by a surrogate scored at selection
        time.  The first call has nothing pending and no baseline, and only
        selects.
        """
        pending = self._pending
        baseline = self._baseline
        if pending is not None and baseline is not None:
            self.observe(
                pending,
                reward_vector(
                    OperatorOutcome(
                        choice=pending,
                        before=baseline,
                        after=metrics,
                        applied=applied,
                    )
                ),
                applied=applied,
                routing_seconds=routing_seconds,
            )
        self._baseline = metrics
        return self.select(context)


def operator_tally(session: OperatorSession) -> str:
    """Per-arm play counts for both ledgers, in declaration order.

    Shaped ``destroy:<name>:<n>|...|repair:<name>:<n>`` so one placement stat
    carries the whole portfolio's usage without a second key per operator.
    """
    destroy = dict.fromkeys((operator for operator in DestroyOperator), 0)
    repair = dict.fromkeys((operator for operator in RepairOperator), 0)
    for choice in session.choices:
        destroy[choice.destroy] += 1
        repair[choice.repair] += 1
    parts = [
        f"destroy:{operator.value}:{count}"
        for operator, count in destroy.items()
        if count or operator in SHIPPED_DESTROY
    ]
    parts += [
        f"repair:{operator.value}:{count}"
        for operator, count in repair.items()
        if count or operator in SHIPPED_REPAIR
    ]
    return "|".join(parts)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/layout/test_sequence_alns.py -q`
Expected: 23 passed.

- [ ] **Step 7: Lint, type-check, commit**

```bash
uv run ruff check src/flab2bp/layout/sequence_alns.py tests/layout/test_sequence_alns.py
uv run mypy src/flab2bp/layout/sequence_alns.py
git add src/flab2bp/layout/sequence_alns.py tests/layout/test_sequence_alns.py
git commit -m "feat(layout): add discounted-UCB operator selection with a lexicographic reward"
```

---

### Task 4: `_alns_substitution`

A standalone function with unit tests and **no call sites yet**, so it is reviewable on its own.
Task 5 switches the call sites.

**Files:**
- Modify: `src/flab2bp/layout/sequence_solver.py` — add `_RepairAdapters` and `_alns_substitution` directly after `_lns_neighbourhood` (`:2711`)
- Test: `tests/layout/test_sequence_solver.py`

**Interfaces:**
- Consumes: `_routing_feedback_substitution` (`:2653`), `repair_neighbourhood` (`sequence_pair.py:1508`), `derive_stage_seed` (`sequence_pair.py:1242`), and from Task 3 `OperatorSession`, `OperatorContext`, `OperatorMetrics`, `REWARD_RANKS`, `RepairOperator`, `destroy_strips`, `metrics_from_evaluation`.
- Produces: `_RepairAdapters(window_pack=None)` and `_alns_substitution(detailed, selected_state, problem, decoded, *, seed, stage_index, session, context, metrics, routing_seconds, band_target_width, adapters) -> tuple[AnnealState, frozenset[int]]`.

- [ ] **Step 1: Write the failing test**

Add to `tests/layout/test_sequence_solver.py`. **Imports this task adds** (Task 2 already brought
the routing and solver names):

```python
from flab2bp.layout.route_feedback import FeedbackState, select_lns_neighbourhood
from flab2bp.layout.sequence_alns import (
    REWARD_RANKS,
    DestroyOperator,
    OperatorContext,
    OperatorSession,
    RepairOperator,
    metrics_from_evaluation,
)
from flab2bp.layout.sequence_pair import AnnealState, DecodedPlacement, decode_state
```

```python
def _substitution_fixture() -> tuple[
    PlacementProblem, AnnealState, DecodedPlacement, DetailedRouteResult
]:
    problem = PlacementProblem(
        sizes=((4, 3), (4, 3), (4, 3), (4, 3)),
        nets=((0, 1), (1, 2), (2, 3)),
        outline_height=12,
        area_lower_bound=48,
    )
    state = AnnealState.initial(problem.size, 11)
    decoded = decode_state(problem, state)
    routing = DetailedRouteResult(
        status=DetailedRouteStatus.STRANDED,
        routed=(),
        failures=(
            NetFailure(
                net_id=NetId(0, 1, "iron-ore", NetRole.INTERNAL, 0),
                kind=RouteFailureKind.CONGESTION_WALL,
                wall=((2, 2, 0),),
                blocking_nets=(NetId(2, 3, "copper-ore", NetRole.INTERNAL, 1),),
                expansions=5,
            ),
        ),
        iterations=1,
        expansions=5,
    )
    return problem, state, decoded, routing


def _call_alns(
    *,
    session: OperatorSession,
    adapters: sequence_solver._RepairAdapters,
) -> tuple[AnnealState, frozenset[int]]:
    problem, state, decoded, routing = _substitution_fixture()
    feedback = FeedbackState.empty((decoded.width, problem.outline_height))
    return sequence_solver._alns_substitution(
        routing,
        state,
        problem,
        decoded,
        seed=11,
        stage_index=0,
        session=session,
        context=OperatorContext(strip_count=problem.size, stagnation=0, remaining_fraction=10),
        metrics=metrics_from_evaluation(
            routing,
            decoded,
            feedback,
            outline_height=problem.outline_height,
            band_target_width=decoded.width,
            validator_clean=False,
        ),
        routing_seconds=0.5,
        band_target_width=decoded.width,
        adapters=adapters,
    )


def test_alns_substitution_matches_the_legacy_rule_for_the_legacy_arms() -> None:
    """With FAILED_ENDPOINTS + SEQUENCE_REINSERT the selector is the old rule."""
    problem, state, decoded, routing = _substitution_fixture()
    legacy_state, legacy_neighbourhood = sequence_solver._routing_feedback_substitution(
        routing, state, problem, decoded, seed=11, stage_index=0
    )
    alns_state, alns_neighbourhood = _call_alns(
        session=OperatorSession(
            destroy_arms=(DestroyOperator.FAILED_ENDPOINTS,),
            repair_arms=(RepairOperator.SEQUENCE_REINSERT,),
        ),
        adapters=sequence_solver._RepairAdapters(),
    )
    assert alns_neighbourhood == legacy_neighbourhood
    assert alns_state.pair == legacy_state.pair
    assert alns_state.gaps == legacy_state.gaps


def test_alns_substitution_ignores_budget_only_failures() -> None:
    problem = PlacementProblem(
        sizes=((4, 3), (4, 3)), nets=((0, 1),), outline_height=12, area_lower_bound=24
    )
    state = AnnealState.initial(problem.size, 3)
    decoded = decode_state(problem, state)
    routing = DetailedRouteResult(
        status=DetailedRouteStatus.BUDGET,
        routed=(),
        failures=(
            NetFailure(
                net_id=NetId(0, 1, "iron-ore", NetRole.INTERNAL, 0),
                kind=RouteFailureKind.BUDGET,
                wall=(),
                blocking_nets=(),
                expansions=9,
            ),
        ),
        iterations=1,
        expansions=9,
    )
    session = OperatorSession()
    result_state, neighbourhood = sequence_solver._alns_substitution(
        routing,
        state,
        problem,
        decoded,
        seed=3,
        stage_index=0,
        session=session,
        context=OperatorContext(strip_count=2, stagnation=0, remaining_fraction=10),
        metrics=metrics_from_evaluation(
            routing,
            decoded,
            FeedbackState.empty((decoded.width, problem.outline_height)),
            outline_height=problem.outline_height,
            band_target_width=decoded.width,
            validator_clean=False,
        ),
        routing_seconds=0.1,
        band_target_width=decoded.width,
        adapters=sequence_solver._RepairAdapters(),
    )
    assert neighbourhood == frozenset()
    assert result_state.pair == state.pair
    assert session.choices == ()


def test_alns_substitution_credits_an_empty_destroy_set_immediately() -> None:
    """A choice that ran nothing must not be charged the NEXT evaluation's result."""
    session = OperatorSession(
        destroy_arms=(DestroyOperator.FAILED_ENDPOINTS,),
        repair_arms=(RepairOperator.SEQUENCE_REINSERT,),
    )
    problem = PlacementProblem(
        sizes=((4, 3), (4, 3)), nets=((0, 1),), outline_height=12, area_lower_bound=24
    )
    state = AnnealState.initial(problem.size, 3)
    decoded = decode_state(problem, state)
    routing = DetailedRouteResult(
        status=DetailedRouteStatus.STRANDED,
        routed=(),
        failures=(
            NetFailure(
                net_id=NetId(0, 1, "iron-ore", NetRole.INTERNAL, 0),
                kind=RouteFailureKind.CONGESTION_WALL,
                wall=((1, 1, 0),),
                blocking_nets=(),
                expansions=2,
            ),
        ),
        iterations=1,
        expansions=2,
    )
    sequence_solver._alns_substitution(
        routing,
        state,
        problem,
        decoded,
        seed=3,
        stage_index=0,
        session=session,
        context=OperatorContext(strip_count=2, stagnation=0, remaining_fraction=10),
        metrics=metrics_from_evaluation(
            routing,
            decoded,
            FeedbackState.empty((decoded.width, problem.outline_height)),
            outline_height=problem.outline_height,
            band_target_width=decoded.width,
            validator_clean=False,
        ),
        routing_seconds=0.1,
        band_target_width=decoded.width,
        adapters=sequence_solver._RepairAdapters(),
    )
    # The neighbourhood is the whole two-strip problem, so nothing was applied.
    assert session.pending is None
    assert session.applied == 0


def test_alns_substitution_uses_the_full_neighbourhood_until_the_scale_is_capped() -> None:
    """`cap_scale=False` must reproduce the legacy destroy set exactly."""
    problem, state, decoded, routing = _substitution_fixture()
    _repaired, neighbourhood = _call_alns(
        session=OperatorSession(
            destroy_arms=(DestroyOperator.FAILED_ENDPOINTS,),
            repair_arms=(RepairOperator.SEQUENCE_REINSERT,),
        ),
        adapters=sequence_solver._RepairAdapters(),
    )
    expected = select_lns_neighbourhood(
        routing, state.pair, state.gaps, problem, decoded, stagnation=0, grow_after=2
    )
    assert neighbourhood == expected or (
        problem.size > 1 and len(expected) == problem.size and neighbourhood == frozenset()
    )
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/layout/test_sequence_solver.py -q -k alns_substitution`
Expected: FAIL with `AttributeError: module 'flab2bp.layout.sequence_solver' has no attribute '_alns_substitution'`.

- [ ] **Step 3: Add the imports**

At the top of `sequence_solver.py`, in the existing import block:

```python
from flab2bp.layout.sequence_alns import (
    C_CONTEXT_FRACTION_STEPS,
    REWARD_RANKS,
    SHIPPED_DESTROY,
    DestroyOperator,
    OperatorContext,
    OperatorMetrics,
    OperatorSession,
    RepairOperator,
    destroy_strips,
    metrics_from_evaluation,
    operator_tally,
    remaining_fraction_bucket,
)
```

Ruff will flag whichever names are not yet used; add each one in the task that first uses it rather
than importing them all now. This task needs `REWARD_RANKS`, `OperatorContext`, `OperatorMetrics`,
`OperatorSession`, `RepairOperator`, `destroy_strips`.

- [ ] **Step 4: Add `_RepairAdapters` and `_alns_substitution`**

Directly after `_lns_neighbourhood` (`:2711`):

```python
@dataclass(frozen=True, slots=True)
class _RepairAdapters:
    """Run-scoped callables a repair operator needs but this module cannot own."""

    #: Repair a decoded placement with a bounded CP-SAT window and hand back the
    #: WHOLE encoding -- pair, gaps and the decoded compaction; ``None`` when the
    #: window is unaffordable, infeasible, or returns the incumbent unchanged.
    #: The encoding rather than the placement, because the round trip is not
    #: exact: re-encoding the compaction here could yield a second, different
    #: pair.  Wired in a later task; until then LOCAL_EXACT_PACK finds no adapter
    #: and credits itself unapplied.
    window_pack: (
        Callable[
            [frozenset[int], PlacementProblem, AnnealState, DecodedPlacement],
            EncodedPlacement | None,
        ]
        | None
    ) = None


def _alns_substitution(
    detailed: DetailedRouteResult,
    selected_state: AnnealState,
    problem: PlacementProblem,
    decoded: DecodedPlacement,
    *,
    seed: int,
    stage_index: int,
    session: OperatorSession,
    context: OperatorContext,
    metrics: OperatorMetrics,
    routing_seconds: float,
    band_target_width: int,
    adapters: _RepairAdapters,
    cap_scale: bool = False,
) -> tuple[AnnealState, frozenset[int]]:
    """Replace a failed candidate with the local repair the selector chose.

    Same contract as :func:`_routing_feedback_substitution`, which stays in this
    module as the implementation behind the FAILED_ENDPOINTS + SEQUENCE_REINSERT
    pairing: geometric failures only (never BUDGET), never the whole problem,
    and the unchanged state when there is nothing to repair.
    """
    unchanged = AnnealState(
        pair=selected_state.pair,
        gaps=selected_state.gaps,
        base_seed=seed,
        stage_index=stage_index,
        variant_indices=selected_state.variant_indices,
    )
    if not any(
        failure.kind
        in {
            RouteFailureKind.STATIC_ACCESS,
            RouteFailureKind.DYNAMIC_ACCESS,
            RouteFailureKind.SEALED_POCKET,
            RouteFailureKind.CONGESTION_WALL,
            RouteFailureKind.COMMIT_LINK,
        }
        for failure in detailed.failures
    ):
        return unchanged, frozenset()

    choice = session.observe_and_select(
        metrics, context, routing_seconds=routing_seconds
    )
    neighbourhood = destroy_strips(
        choice.destroy,
        # ``cap_scale`` is False until the portfolio opens.  The legacy rule
        # destroyed the whole neighbourhood `select_lns_neighbourhood` returned,
        # so capping it here would be a behaviour change smuggled into a wiring
        # commit; Task 7 turns it on beside the arms that need it.
        scale=choice.scale if cap_scale else problem.size,
        result=detailed,
        pair=selected_state.pair,
        gaps=selected_state.gaps,
        problem=problem,
        decoded=decoded,
        band_target_width=band_target_width,
    )
    if not neighbourhood or (problem.size > 1 and len(neighbourhood) == problem.size):
        # Credit it now, as unapplied.  Leaving it pending would charge the next
        # evaluation's outcome to a choice that never ran.
        session.observe(choice, (0.0,) * REWARD_RANKS, applied=False)
        return unchanged, frozenset()

    if choice.repair is RepairOperator.LOCAL_EXACT_PACK and adapters.window_pack is not None:
        encoded = adapters.window_pack(neighbourhood, problem, selected_state, decoded)
        if encoded is None:
            session.observe(choice, (0.0,) * REWARD_RANKS, applied=False)
            return unchanged, frozenset()
        # The adapter already encoded its result; re-encoding the compaction here
        # could produce a second, different pair, because the round trip is not
        # exact.  Use the one that was measured.
        return (
            AnnealState(
                pair=encoded.pair,
                gaps=encoded.gaps,
                base_seed=seed,
                stage_index=stage_index,
                variant_indices=selected_state.variant_indices,
            ),
            neighbourhood,
        )

    repaired = repair_neighbourhood(
        selected_state.pair,
        selected_state.gaps,
        neighbourhood,
        seed=derive_stage_seed(seed, stage_index + 1),
        variant_indices=selected_state.variant_indices,
    )
    return (
        AnnealState(
            pair=repaired.pair,
            gaps=repaired.gaps,
            base_seed=seed,
            stage_index=stage_index,
            variant_indices=repaired.variant_indices,
        ),
        neighbourhood,
    )
```

`EncodedPlacement` arrives in Task 8 and `window_pack` in Task 11, so at this point the
`LOCAL_EXACT_PACK` branch is unreachable — `adapters.window_pack` is always `None`, and the
`RepairOperator.LOCAL_EXACT_PACK` arm is not in the session either (Task 5 opens only
`SEQUENCE_REINSERT`). The branch is written now anyway, because writing it later means editing a
function two tasks after its tests were reviewed. To keep the module importable before Task 8, type
`_RepairAdapters.window_pack`'s return as `"EncodedPlacement | None"` in quotes and add the real
`from flab2bp.layout.sequence_pair import EncodedPlacement` import in Task 8's commit; if that
offends mypy's `--strict` before the name exists, leave `window_pack` typed as
`Callable[..., object] | None` here and tighten it in Task 11 Step 3, recording the change in that
commit message.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/layout/test_sequence_solver.py -q -k alns_substitution`
Expected: 4 passed.

- [ ] **Step 6: Lint, type-check, commit**

```bash
uv run ruff check src/flab2bp/layout/sequence_solver.py tests/layout/test_sequence_solver.py
uv run mypy src/flab2bp/layout/sequence_solver.py
uv run pytest -q
git add src/flab2bp/layout/sequence_solver.py tests/layout/test_sequence_solver.py
git commit -m "feat(layout): add the operator-driven repair substitution"
```

---

### Task 5: Switch the call sites and plumb the session through `_production_run`

**Behaviour-preserving.** The session is opened with only `FAILED_ENDPOINTS` and
`SEQUENCE_REINSERT`, and **`scale` is not capped**: the legacy rule used the whole neighbourhood, so
this task passes the whole neighbourhood too. The scale cap arrives in Task 7 with the portfolio.

**Files:**
- Modify: `src/flab2bp/layout/sequence_solver.py` — `SequenceSolver.__init__` (`:874`), the call sites at `:1555` and `:2433`, `_ProductionTelemetry` (`:3806`), `_production_run`'s `SequenceSolver(...)` construction (`:4804`), the production stats dict (`:5390-5445`)
- Modify: `src/flab2bp/layout/base.py:198` (`PlacementStats`) — add `alns_choices`, `alns_applied`, `alns_evaluations`, `alns_routing_seconds` (float) and `alns_operators` (str)
- Test: `tests/layout/test_sequence_solver.py`

**Interfaces:**
- Consumes: `_alns_substitution`, `_RepairAdapters` (Task 4); `operator_tally`, `remaining_fraction_bucket`, `C_CONTEXT_FRACTION_STEPS` (Task 3); `_ProductionRun(solver, telemetry, heights, direct_candidates, started, ceiling, max_search_stages)` (`:3831`).
- Produces: `SequenceSolver(..., alns_session=None, alns_adapters=None, remaining_fraction=None)` with the attributes `alns_session`, `alns_adapters`, `_remaining_fraction`; the placement stats `alns_choices`, `alns_applied`, `alns_evaluations`, `alns_routing_seconds`, `alns_operators`.

- [ ] **Step 1: Write the failing test**

**Imports this task adds to `tests/layout/test_sequence_solver.py`:**

```python
from flab2bp.layout.band_policy import BandPolicy
from flab2bp.layout.sequence_alns import C_CONTEXT_FRACTION_STEPS
from flab2bp.layout.sequence_solver import SequencePairLayout

from tests.layout.test_freeform import plastic_spec
```

If importing `plastic_spec` across test modules is not how this suite already shares corpus
fixtures (`grep -rn 'plastic_spec' tests/ | head`), copy its four-line body instead and say so in
the commit message.

```python
def test_sequence_solver_exposes_a_default_operator_session() -> None:
    solver = _never_certifying_solver(heights=(12,), deadline_reached=lambda: False)
    assert solver.alns_session is not None
    assert solver.alns_adapters.window_pack is None
    assert solver._remaining_fraction() == C_CONTEXT_FRACTION_STEPS


@pytest.mark.slow
def test_production_stats_carry_the_operator_telemetry() -> None:
    spec = plastic_spec()
    placement = SequencePairLayout(band_policy=BandPolicy.parse("any")).lay_out(
        spec, time_budget_s=15.0
    )
    for key in (
        "feasibility_restart_batches",
        "alns_choices",
        "alns_applied",
        "alns_evaluations",
        "alns_routing_seconds",
    ):
        assert isinstance(placement.stats[key], float), key
    tally = placement.stats["alns_operators"]
    assert isinstance(tally, str)
    for part in filter(None, tally.split("|")):
        kind, name, count = part.split(":")
        assert kind in {"destroy", "repair"}
        assert name
        assert count.isdigit()
```

`plastic_spec()` lives in `tests/layout/test_freeform.py:206`; import it or duplicate its four-line
body, whichever the existing `tests/layout/test_sequence_solver.py` already does for corpus specs.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/layout/test_sequence_solver.py -q -k "operator_session or operator_telemetry"`
Expected: FAIL with `AttributeError: 'SequenceSolver' object has no attribute 'alns_session'`.

- [ ] **Step 3: Add the solver's constructor keywords**

In `SequenceSolver.__init__` (`:874`), add three keyword-only parameters after `stage_admission`:

```python
        alns_session: OperatorSession | None = None,
        alns_adapters: _RepairAdapters | None = None,
        remaining_fraction: Callable[[], int] | None = None,
```

and, beside the other attribute assignments:

```python
        # Only the legacy pairing is armed here.  Opening the portfolio is its
        # own commit so any corpus movement is attributable to that commit.
        self.alns_session = alns_session or OperatorSession(
            destroy_arms=(DestroyOperator.FAILED_ENDPOINTS,),
            repair_arms=(RepairOperator.SEQUENCE_REINSERT,),
        )
        self.alns_adapters = alns_adapters or _RepairAdapters()
        #: Remaining wall as a bucket index.  A solver built without one -- a
        #: test or a probe -- reports "all the time in the world", which is the
        #: honest answer when there is no deadline to divide by.
        self._remaining_fraction = remaining_fraction or (
            lambda: C_CONTEXT_FRACTION_STEPS
        )
```

- [ ] **Step 4: Switch the ordinary stage-boundary call site (`:2433`)**

Replace the `_routing_feedback_substitution(...)` call inside
`if starting_mode is ObjectiveMode.EXPLORATION:` with:

```python
            band_target = selected.decoded.width
            next_anneal, neighbourhood = _alns_substitution(
                detailed.routing,
                selected.state,
                problem,
                selected.decoded,
                seed=restart.seed,
                stage_index=annealed.final_state.stage_index,
                session=self.alns_session,
                context=OperatorContext(
                    strip_count=problem.size,
                    stagnation=restart.feedback_stagnation,
                    remaining_fraction=self._remaining_fraction(),
                ),
                metrics=metrics_from_evaluation(
                    detailed.routing,
                    selected.decoded,
                    height_state.feedback,
                    outline_height=problem.outline_height,
                    band_target_width=band_target,
                    validator_clean=False,
                ),
                routing_seconds=detailed_route_time_s,
                band_target_width=band_target,
                adapters=self.alns_adapters,
            )
```

`detailed_route_time_s` is the local this block already computes for the stage observation; find it
with `grep -n 'detailed_route_time_s' src/flab2bp/layout/sequence_solver.py` and use the name in
scope. If no such local exists at this point, pass `0.0` and record that in the commit message —
`routing_seconds` is telemetry only, so a zero there costs nothing but a telemetry line.

- [ ] **Step 5: Switch the compact-seed call site (`:1555`)**

The local names differ there: the candidate is `incumbent`, the stage index is
`restart.anneal.stage_index`, and there is no `starting_mode`. Use:

```python
            band_target = incumbent.decoded.width
            next_anneal, neighbourhood = _alns_substitution(
                detailed.routing,
                incumbent.state,
                problem,
                incumbent.decoded,
                seed=restart.seed,
                stage_index=restart.anneal.stage_index,
                session=self.alns_session,
                context=OperatorContext(
                    strip_count=problem.size,
                    stagnation=0,
                    remaining_fraction=self._remaining_fraction(),
                ),
                metrics=metrics_from_evaluation(
                    detailed.routing,
                    incumbent.decoded,
                    height_state.feedback,
                    outline_height=problem.outline_height,
                    band_target_width=band_target,
                    validator_clean=False,
                ),
                routing_seconds=detailed_route_time_s,
                band_target_width=band_target,
                adapters=self.alns_adapters,
            )
```

Neither call site passes `cap_scale`, so it stays `False` and `destroy_strips` receives
`problem.size`: the legacy rule destroyed the whole neighbourhood, and capping it here would be a
behaviour change smuggled into a wiring commit. Task 7 turns it on.

- [ ] **Step 6: Count evaluations and build the session in `_production_run`**

Add to `_ProductionTelemetry` (`:3806`):

```python
    alns_evaluations: int = 0
```

In `_production_run`, increment it where the detailed router adapter is invoked — inside the
`detailed_route` adapter closure (`:4524-4556`), on entry:

```python
        telemetry.alns_evaluations += 1
```

Pass the session, adapters and clock into `SequenceSolver(...)` (`:4804`):

```python
        alns_session=OperatorSession(
            destroy_arms=(DestroyOperator.FAILED_ENDPOINTS,),
            repair_arms=(RepairOperator.SEQUENCE_REINSERT,),
        ),
        alns_adapters=_RepairAdapters(),
        remaining_fraction=lambda: remaining_fraction_bucket(
            max(0.0, (started + ceiling) - time.monotonic()), ceiling
        ),
```

`started` and `ceiling` are the locals `_ProductionRun` is built from at `:5126-5136`; confirm they
are in scope at the `SequenceSolver(...)` call with `sed -n '4790,4815p'` and hoist them if not.

- [ ] **Step 7: Declare and write the stats**

In `PlacementStats` (`base.py:198`), in alphabetical position:

```python
    alns_applied: float
    alns_choices: float
    alns_evaluations: float
    alns_operators: str
    alns_routing_seconds: float
```

In the production stats dict, beside `"feasibility_restart_batches"`:

```python
            "alns_choices": float(len(run.solver.alns_session.choices)),
            "alns_applied": float(run.solver.alns_session.applied),
            "alns_evaluations": float(telemetry.alns_evaluations),
            "alns_routing_seconds": run.solver.alns_session.routing_seconds,
            "alns_operators": operator_tally(run.solver.alns_session),
```

- [ ] **Step 8: Run the suite**

Run: `uv run pytest -q`
Expected: all pass. In particular the six neighbourhood tests and
`test_lns_repair_is_deterministic_for_seed_and_weights` at `tests/layout/test_sequence_pair.py:2182-2320` must be untouched and green.

- [ ] **Step 9: Prove the corpus did not move on the targeted cells**

```bash
uv run python scripts/audit.py --budget 30 --jobs 4 --strategy sequence-pair \
  --only graphene,universe-matrix --json /tmp/phase-c-task5.jsonl | tail -6
uv run python scripts/audit_compare.py \
  docs/superpowers/evidence/2026-09-02-phase-c-alns/baseline-budget30-round1.jsonl \
  /tmp/phase-c-task5.jsonl --regressions-only
```

Expected: no regression against the baseline rows for those cells, and `graphene/output-products`
still CLEAN from Task 2. `--regressions-only` reports only cells that were CLEAN in the baseline and
are not CLEAN now; an empty regression list is the pass condition. If a cell regresses, this commit
is not behaviour-preserving: report the cell and its detail rather than adjusting a constant.

- [ ] **Step 10: Lint, type-check, commit**

```bash
uv run ruff check src/flab2bp/layout tests/layout
uv run mypy src/flab2bp/layout/sequence_solver.py src/flab2bp/layout/base.py
git add src/flab2bp/layout tests/layout
git commit -m "refactor(layout): select the sequence-pair repair neighbourhood through an operator session"
```

---

### Task 6: `finalize.band_target_width` and the `BAND_BOUNDARY` operator

No wiring: the operator gains a dispatch branch and tests, but the shipped arms are still the legacy
pairing, so behaviour is unchanged. Task 7 opens the portfolio.

**Files:**
- Modify: `src/flab2bp/layout/finalize.py` — add `C_BAND_SCAN_MAX` and `band_target_width` after `band_policy_search_envelope` (`:163-181`)
- Modify: `src/flab2bp/layout/sequence_alns.py` — the `BAND_BOUNDARY` branch in `destroy_strips`
- Test: `tests/layout/test_finalize.py`, `tests/layout/test_sequence_alns.py`

**Interfaces:**
- Consumes: `BandPolicySearchEnvelope.frame_candidates(core_width, core_height) -> tuple[FrameCandidate, ...]` (`finalize.py:115`), `band_policy_search_envelope(policy, *, perimeter)` (`:163`), `freeform._ENTRY_RING` (`freeform.py:613`), `PlacementProblem.sizes`, `DecodedPlacement.x`/`used_height`/`width`.
- Produces: `finalize.C_BAND_SCAN_MAX = 4096`, `finalize.band_target_width(envelope, *, height, width) -> int`, and the `BAND_BOUNDARY` branch of `destroy_strips`.

- [ ] **Step 1: Write the monotonicity experiment as a test**

Add to `tests/layout/test_finalize.py`:

```python
def test_frame_candidates_are_monotone_in_width_at_a_fixed_height() -> None:
    """Once a core width fits a band, every narrower core at that height fits too.

    `band_target_width` is a binary search only if this holds.  It is a property
    of `_frame_candidates_for_extent`, not an axiom, so it is asserted rather
    than assumed.
    """
    envelope = finalize.band_policy_search_envelope(
        BandPolicy.parse("any"), perimeter=freeform._ENTRY_RING
    )
    for height in (40, 131):
        fitting_seen = False
        for width in range(600, 0, -1):
            fits = bool(envelope.frame_candidates(width, height))
            if fits:
                fitting_seen = True
            elif fitting_seen:
                raise AssertionError(
                    f"non-monotone at height={height}: width {width} does not fit "
                    f"but a wider core did"
                )
        assert fitting_seen, f"no width from 1 to 600 fits at height={height}"
```

- [ ] **Step 2: Run the monotonicity test and decide the implementation**

Run: `uv run pytest tests/layout/test_finalize.py::test_frame_candidates_are_monotone_in_width_at_a_fixed_height -v`

Decision rule:
- **PASS** → implement `band_target_width` as the binary search in Step 4 and keep this test as a
  standing guard.
- **FAIL** → keep the test but mark it `@pytest.mark.xfail(strict=True, reason="frame candidates are not monotone in width; band_target_width uses a linear scan")`, and implement `band_target_width` as a **descending linear scan** instead:

```python
    for candidate in range(min(width, C_BAND_SCAN_MAX), 0, -1):
        if envelope.frame_candidates(candidate, height):
            return candidate
    return 1
```

Record which branch was taken in the commit message. Either way the rest of this task is unchanged.

- [ ] **Step 3: Write the failing `band_target_width` tests**

Add to `tests/layout/test_finalize.py`:

```python
def _any_envelope() -> finalize.BandPolicySearchEnvelope:
    return finalize.band_policy_search_envelope(
        BandPolicy.parse("any"), perimeter=freeform._ENTRY_RING
    )


def test_band_target_width_returns_the_widest_core_a_band_accepts() -> None:
    envelope = _any_envelope()
    height = 131
    fitting = finalize.band_target_width(envelope, height=height, width=4000)
    assert envelope.frame_candidates(fitting, height)
    assert not envelope.frame_candidates(fitting + 1, height)


def test_band_target_width_returns_the_input_when_it_already_fits() -> None:
    assert finalize.band_target_width(_any_envelope(), height=40, width=20) == 20


def test_band_target_width_rejects_an_implausible_core() -> None:
    with pytest.raises(ValueError):
        finalize.band_target_width(
            _any_envelope(), height=40, width=finalize.C_BAND_SCAN_MAX + 1
        )
```

- [ ] **Step 4: Run to verify they fail, then implement**

Run: `uv run pytest tests/layout/test_finalize.py -q -k band_target_width`
Expected: FAIL with `AttributeError: module 'flab2bp.layout.finalize' has no attribute 'band_target_width'`.

Insert directly after `band_policy_search_envelope` (`finalize.py:163-181`):

```python
#: Largest core width :func:`band_target_width` accepts.  The corpus peaks near
#: 1334 on `universe-matrix`, so anything past this is a programming error and
#: is raised rather than silently clamped -- a clamp would return a "target"
#: that is not the widest fitting core, which is exactly the number callers act
#: on.
C_BAND_SCAN_MAX = 4096


def band_target_width(
    envelope: BandPolicySearchEnvelope,
    *,
    height: int,
    width: int,
) -> int:
    """Return the widest core at ``height`` this policy's bands still accept.

    This is the quantity behind the `no legal DSP latitude band/orientation
    accepts the final placement` refusals: a placement whose extent exceeds it
    cannot be finalized at that height no matter how it routes.  A width that
    already fits is returned unchanged.

    ``frame_candidates`` is monotone in width at a fixed height -- a wider core
    needs a strictly larger frame -- which
    ``test_frame_candidates_are_monotone_in_width_at_a_fixed_height`` asserts,
    so one binary search answers the question.
    """
    if type(height) is not int or height <= 0:
        raise ValueError("band target height must be a positive integer")
    if type(width) is not int or width <= 0:
        raise ValueError("band target width must be a positive integer")
    if width > C_BAND_SCAN_MAX:
        raise ValueError(f"band target width must not exceed {C_BAND_SCAN_MAX}")
    if envelope.frame_candidates(width, height):
        return width
    low, high = 0, width
    while low + 1 < high:
        middle = (low + high) // 2
        if envelope.frame_candidates(middle, height):
            low = middle
        else:
            high = middle
    return max(1, low)
```

- [ ] **Step 5: Run the finalize tests**

Run: `uv run pytest tests/layout/test_finalize.py -q -k "band_target_width or monotone"`
Expected: 4 passed (or 3 passed and 1 xfail, if Step 2 took the linear-scan branch).

- [ ] **Step 6: Write the failing `BAND_BOUNDARY` tests**

Append to `tests/layout/test_sequence_alns.py`:

```python
def _band_destroy(*, band_target_width: int, scale: int = 4) -> frozenset[int]:
    problem = _problem()
    state = AnnealState.initial(problem.size, 7)
    decoded = decode_state(problem, state)
    return destroy_strips(
        DestroyOperator.BAND_BOUNDARY,
        scale=scale,
        result=_routing(),
        pair=state.pair,
        gaps=state.gaps,
        problem=problem,
        decoded=decoded,
        band_target_width=band_target_width,
    )


def test_band_boundary_is_empty_when_the_placement_already_fits() -> None:
    problem = _problem()
    decoded = decode_state(problem, AnnealState.initial(problem.size, 7))
    assert _band_destroy(band_target_width=decoded.width + 10) == frozenset()


def test_band_boundary_selects_the_strips_past_the_target_width() -> None:
    problem = _problem()
    decoded = decode_state(problem, AnnealState.initial(problem.size, 7))
    target = max(1, decoded.width - 1)
    selected = _band_destroy(band_target_width=target)
    assert selected
    assert all(
        decoded.x[strip] + problem.sizes[strip][0] > target for strip in selected
    )


def test_band_boundary_falls_back_to_the_widest_edges_when_nothing_exceeds() -> None:
    problem = _problem()
    decoded = decode_state(problem, AnnealState.initial(problem.size, 7))
    # Target equals the width, so no strip exceeds it; an outline overflow is
    # what makes the operator applicable, and this fixture has none, so the
    # operator is empty.  Force the overflow branch with a tiny outline.
    tight = PlacementProblem(
        sizes=problem.sizes,
        nets=problem.nets,
        outline_height=1,
        area_lower_bound=problem.area_lower_bound,
    )
    tight_decoded = decode_state(tight, AnnealState.initial(tight.size, 7))
    selected = destroy_strips(
        DestroyOperator.BAND_BOUNDARY,
        scale=2,
        result=_routing(),
        pair=AnnealState.initial(tight.size, 7).pair,
        gaps=AnnealState.initial(tight.size, 7).gaps,
        problem=tight,
        decoded=tight_decoded,
        band_target_width=tight_decoded.width,
    )
    assert 0 < len(selected) <= 2


def test_band_boundary_keeps_the_worst_offenders_when_it_is_capped() -> None:
    """A small `scale` must keep the strips that own the overflow, not the mildest."""
    problem = _problem()
    decoded = decode_state(problem, AnnealState.initial(problem.size, 7))
    worst_two = {
        strip
        for _edge, strip in sorted(
            (
                (-(decoded.x[strip] + problem.sizes[strip][0]), strip)
                for strip in range(problem.size)
            )
        )[:2]
    }
    selected = _band_destroy(band_target_width=1, scale=2)
    assert len(selected) == 2
    assert selected == worst_two
```

- [ ] **Step 7: Run to verify they fail, then implement the branch**

Run: `uv run pytest tests/layout/test_sequence_alns.py -q -k band_boundary`
Expected: FAIL with `NotImplementedError: destroy operator band-boundary is a follow-up with no dispatch branch`.

In `sequence_alns.py`, insert before the `raise NotImplementedError` in `destroy_strips`:

```python
    if operator is DestroyOperator.BAND_BOUNDARY:
        return _capped(
            _band_boundary(problem, decoded, band_target_width=band_target_width),
            scale=scale,
        )
```

and add the helper above `destroy_strips`:

```python
def _band_boundary(
    problem: PlacementProblem,
    decoded: DecodedPlacement,
    *,
    band_target_width: int,
) -> list[int]:
    """Strips ranked by how much they push the extent past what a band accepts.

    This is the operator the "fits no latitude band" refusals name: the failure
    is that the finished extent has no legal frame, and the strips that own the
    extent are exactly the ones whose right edge reaches beyond the target.

    A RANKED list, not a set, because `_capped` truncates in the order it is
    given: the worst offender must survive a small `scale`, and index order
    would keep the mildest instead.  Ties on the edge fall to index order so the
    result is deterministic.
    """
    if (
        band_target_width >= decoded.width
        and decoded.used_height <= problem.outline_height
    ):
        return []
    ranked = sorted(
        range(problem.size),
        key=lambda strip: (
            -(decoded.x[strip] + problem.sizes[strip][0]),
            strip,
        ),
    )
    over = [
        strip
        for strip in ranked
        if decoded.x[strip] + problem.sizes[strip][0] > band_target_width
    ]
    # Nothing over the width but the outline still overflows: the extent problem
    # is vertical, and the widest strips are still the ones with room to move.
    return over or ranked
```

- [ ] **Step 8: Run the module tests**

Run: `uv run pytest tests/layout/test_sequence_alns.py -q`
Expected: 27 passed (Task 3's 23 plus this task's 4).

- [ ] **Step 9: Lint, type-check, commit**

```bash
uv run ruff check src/flab2bp/layout/finalize.py src/flab2bp/layout/sequence_alns.py tests/layout
uv run mypy src/flab2bp/layout/finalize.py src/flab2bp/layout/sequence_alns.py
uv run pytest -q
git add src/flab2bp/layout/finalize.py src/flab2bp/layout/sequence_alns.py tests/layout
git commit -m "feat(layout): add the band-boundary destroy operator and its width target"
```

---

### Task 7: Open the destroy portfolio

One switch and one measurement. This is the first commit in the phase that can change the corpus.

**Files:**
- Modify: `src/flab2bp/layout/sequence_solver.py` — `SequenceSolver.__init__`'s default session, `_production_run`'s session, the two `_alns_substitution` call sites (`cap_scale=True`), the `band_target_width` argument
- Test: `tests/layout/test_sequence_solver.py`

**Interfaces:**
- Consumes: `finalize.band_target_width` (Task 6), `SHIPPED_DESTROY` (Task 3), `_alns_substitution`'s `cap_scale` keyword (Task 5 Step 6).
- Produces: a `SequenceSolver` whose destroy arms are `SHIPPED_DESTROY` and whose destroy sets are capped by `operator_scale`.

- [ ] **Step 1: Write the failing test**

**Imports this task adds to `tests/layout/test_sequence_solver.py`:**
`SHIPPED_DESTROY` and `operator_scale` from `flab2bp.layout.sequence_alns`.

```python
def test_the_production_destroy_portfolio_is_the_shipped_set() -> None:
    solver = _never_certifying_solver(heights=(12,), deadline_reached=lambda: False)
    played: set[DestroyOperator] = set()
    for _ in range(len(SHIPPED_DESTROY)):
        choice = solver.alns_session.select(
            OperatorContext(strip_count=20, stagnation=0, remaining_fraction=10)
        )
        played.add(choice.destroy)
        solver.alns_session.observe(choice, (0.0,) * REWARD_RANKS, applied=True)
    assert played == set(SHIPPED_DESTROY)


def test_the_substitution_caps_the_destroy_set_once_the_portfolio_is_open() -> None:
    session = OperatorSession()
    problem, state, decoded, routing = _substitution_fixture()
    _repaired, neighbourhood = sequence_solver._alns_substitution(
        routing,
        state,
        problem,
        decoded,
        seed=11,
        stage_index=0,
        session=session,
        context=OperatorContext(strip_count=problem.size, stagnation=0, remaining_fraction=10),
        metrics=metrics_from_evaluation(
            routing,
            decoded,
            FeedbackState.empty((decoded.width, problem.outline_height)),
            outline_height=problem.outline_height,
            band_target_width=decoded.width,
            validator_clean=False,
        ),
        routing_seconds=0.5,
        band_target_width=decoded.width,
        adapters=sequence_solver._RepairAdapters(),
        cap_scale=True,
    )
    assert len(neighbourhood) <= operator_scale(
        OperatorContext(strip_count=problem.size, stagnation=0, remaining_fraction=10)
    )
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/layout/test_sequence_solver.py -q -k "destroy_portfolio or caps_the_destroy_set"`
Expected: FAIL on `assert played == set(SHIPPED_DESTROY)` — the default session still holds only `FAILED_ENDPOINTS`.

- [ ] **Step 3: Open the arms**

In `SequenceSolver.__init__`, replace the restricted default with the shipped one:

```python
        self.alns_session = alns_session or OperatorSession()
```

In `_production_run`'s `SequenceSolver(...)` construction, replace

```python
        alns_session=OperatorSession(
            destroy_arms=(DestroyOperator.FAILED_ENDPOINTS,),
            repair_arms=(RepairOperator.SEQUENCE_REINSERT,),
        ),
```

with

```python
        # The full destroy portfolio; the repair portfolio stays at the
        # heuristic arm until the window adapter is wired.
        alns_session=OperatorSession(repair_arms=(RepairOperator.SEQUENCE_REINSERT,)),
```

- [ ] **Step 4: Cap the scale and pass the real band target**

At both `_alns_substitution` call sites, add `cap_scale=True` and replace the placeholder
`band_target = <decoded>.width` with the real target. Both closures need the envelope; hoist the
`finalize.band_policy_search_envelope(...)` built at `sequence_solver.py:4100` into a
`_production_run`-scoped local and pass it into `SequenceSolver` as one more keyword:

```python
        band_target_for: Callable[[int, int], int] | None = None,
```

stored as

```python
        self._band_target_for = band_target_for or (lambda height, width: width)
```

and supplied from `_production_run` as

```python
        band_target_for=lambda height, width: finalize.band_target_width(
            projection_envelope, height=height, width=width
        ),
```

Then at both call sites:

```python
            band_target = self._band_target_for(
                problem.outline_height, selected.decoded.width
            )
```

(and `incumbent.decoded.width` at the compact-seed site), with `cap_scale=True` added to the call.

The `lambda height, width: width` default keeps every existing test construction of
`SequenceSolver` working without a band policy, and makes `BAND_BOUNDARY` inert there — which is
correct, since a solver with no envelope has no band to overflow.

- [ ] **Step 5: Run the suite**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 6: Measure the target cells**

```bash
uv run python scripts/audit.py --budget 30 --jobs 4 --strategy sequence-pair \
  --only graphene,universe-matrix --json /tmp/phase-c-task7.jsonl | tail -6
uv run python scripts/audit_compare.py \
  docs/superpowers/evidence/2026-09-02-phase-c-alns/baseline-budget30-round1.jsonl \
  /tmp/phase-c-task7.jsonl --regressions-only
jq -r '[.strategy,.spec_label,.status,.seconds,.area,.detail] | @tsv' /tmp/phase-c-task7.jsonl
```

Expected: no regression. Record every row in the commit message, including whether any
`universe-matrix` cell moved. `BAND_BOUNDARY` alone, with only the heuristic repair behind it, may
not flip a cell; that is not a failure of this task. A regression is.

- [ ] **Step 7: Lint, type-check, commit**

```bash
uv run ruff check src/flab2bp/layout/sequence_solver.py tests/layout/test_sequence_solver.py
uv run mypy src/flab2bp/layout/sequence_solver.py
git add src/flab2bp/layout/sequence_solver.py tests/layout/test_sequence_solver.py
git commit -m "feat(layout): open the destroy portfolio to the band-boundary operator"
```

---

### Task 8: Placement-to-sequence-pair encoder

**Files:**
- Modify: `src/flab2bp/layout/sequence_pair.py` — add `EncodedPlacement`, `encode_placement` and `_topological_order` directly after `decode_state` (`:893`)
- Test: `tests/layout/test_sequence_pair.py`

**Interfaces:**
- Consumes: `decode_sequence_pair(pair, gaps, sizes, *, outline_height, outline_width=None)` (`:819`), `GapProfile.zero(size)` (`:71`), `SequencePair` (`:29`), `_validate_sizes` (`:2133`), `_validate_positive_integer` (`:2145`).
- Produces: `EncodedPlacement(pair, gaps, decoded, exact)` and `encode_placement(sizes, x, y, *, outline_height) -> EncodedPlacement`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/layout/test_sequence_pair.py`:

```python
def _shelf_placement(
    rng: random.Random,
) -> tuple[tuple[tuple[int, int], ...], tuple[int, ...], tuple[int, ...], int]:
    """A random multi-row shelf packing: non-overlapping, with real vertical relations.

    A single-row generator would exercise only the horizontal half of the
    encoder, which is exactly the half that was never wrong.
    """
    sizes: list[tuple[int, int]] = []
    xs: list[int] = []
    ys: list[int] = []
    row_y = 0
    for _row in range(rng.randrange(2, 4)):
        row_height = rng.randrange(2, 5)
        cursor = 0
        for _column in range(rng.randrange(1, 4)):
            width = rng.randrange(2, 7)
            sizes.append((width, rng.randrange(1, row_height + 1)))
            xs.append(cursor)
            ys.append(row_y)
            cursor += width + rng.randrange(0, 3)
        row_y += row_height + rng.randrange(0, 3)
    return tuple(sizes), tuple(xs), tuple(ys), row_y + 4


def test_encode_is_exact_for_a_tight_row() -> None:
    """Every pair horizontal with separation zero: the compaction is the input."""
    sizes = ((4, 3), (5, 3), (4, 3))
    encoded = encode_placement(sizes, (0, 4, 9), (0, 0, 0), outline_height=6)
    assert encoded.exact
    assert encoded.decoded.x == (0, 4, 9)
    assert encoded.decoded.y == (0, 0, 0)


def test_encode_is_exact_for_a_tight_column() -> None:
    """Every pair vertical with separation zero: the compaction is the input.

    This is the case revision 1 got backwards -- an inverted vertical direction
    decodes this column upside down and fails `decoded <= input`.
    """
    sizes = ((4, 3), (4, 2), (4, 3))
    encoded = encode_placement(sizes, (0, 0, 0), (0, 3, 5), outline_height=12)
    assert encoded.exact
    assert encoded.decoded.x == (0, 0, 0)
    assert encoded.decoded.y == (0, 3, 5)


def test_encode_is_never_wider_or_taller_than_its_input() -> None:
    """The ONE guaranteed property.  Exactness is not promised; this is."""
    rng = random.Random(20260902)
    for _trial in range(80):
        sizes, xs, ys, outline = _shelf_placement(rng)
        encoded = encode_placement(sizes, xs, ys, outline_height=outline)
        for index in range(len(sizes)):
            assert encoded.decoded.x[index] <= xs[index], (sizes, xs, ys, index)
            assert encoded.decoded.y[index] <= ys[index], (sizes, xs, ys, index)
        assert encoded.decoded.width <= max(
            xs[i] + sizes[i][0] for i in range(len(sizes))
        )
        assert encoded.decoded.used_height <= max(
            ys[i] + sizes[i][1] for i in range(len(sizes))
        )


def test_encode_produces_vertical_relations_on_a_multi_row_placement() -> None:
    """Guard on the generator itself: a fixture with no vertical pair proves nothing."""
    rng = random.Random(20260902)
    saw_vertical = False
    for _trial in range(80):
        sizes, xs, ys, outline = _shelf_placement(rng)
        encoded = encode_placement(sizes, xs, ys, outline_height=outline)
        negative_position = {
            strip: position for position, strip in enumerate(encoded.pair.negative)
        }
        for first_position, first in enumerate(encoded.pair.positive):
            for second in encoded.pair.positive[first_position + 1 :]:
                if negative_position[first] > negative_position[second]:
                    saw_vertical = True
    assert saw_vertical


def test_encode_never_overlaps() -> None:
    rng = random.Random(1789)
    for _trial in range(80):
        sizes, xs, ys, outline = _shelf_placement(rng)
        encoded = encode_placement(sizes, xs, ys, outline_height=outline)
        boxes = [
            (
                encoded.decoded.x[i],
                encoded.decoded.y[i],
                encoded.decoded.x[i] + sizes[i][0],
                encoded.decoded.y[i] + sizes[i][1],
            )
            for i in range(len(sizes))
        ]
        for i in range(len(sizes)):
            for j in range(i + 1, len(sizes)):
                a, b = boxes[i], boxes[j]
                assert a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1]


def test_encode_is_replayable_for_the_same_placement() -> None:
    sizes = ((4, 3), (5, 3), (4, 4))
    first = encode_placement(sizes, (0, 6, 12), (0, 4, 0), outline_height=12)
    second = encode_placement(sizes, (0, 6, 12), (0, 4, 0), outline_height=12)
    assert first.pair == second.pair
    assert first.gaps == second.gaps


def test_encode_rejects_an_overlapping_placement() -> None:
    with pytest.raises(ValueError):
        encode_placement(((4, 3), (4, 3)), (0, 1), (0, 1), outline_height=6)
```

`random` is imported at the top of `tests/layout/test_sequence_pair.py` already; add
`import random` if `grep -n '^import random' tests/layout/test_sequence_pair.py` finds nothing.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/layout/test_sequence_pair.py -q -k encode`
Expected: FAIL with `NameError: name 'encode_placement' is not defined`.

- [ ] **Step 3: Implement the encoder**

Insert into `sequence_pair.py` directly after `decode_state`. First fix the imports:

```bash
grep -n 'from collections.abc' src/flab2bp/layout/sequence_pair.py
```

`_topological_order` needs both `Callable` and `Sequence` from `collections.abc`; add whichever of
the two the existing line lacks.

```python
@dataclass(frozen=True, slots=True)
class EncodedPlacement:
    """A sequence pair for one concrete placement, and what it decodes back to.

    ``exact`` is ``False`` when the input carried slack the encoding does not
    express: the emitted gaps are zero, and :func:`decode_sequence_pair` then
    returns the compaction of the constraint graph.  Exactness is NOT promised
    -- it holds when every pair's chosen relation is tight, and on a twenty-seed
    fixture it held nine times.

    What IS promised: the compaction is never wider and never taller.  Every
    relation the encoder emits is an inequality the input already satisfies --
    that is how the relation was chosen -- so the input is a feasible point of
    the emitted system, and the longest-path sweep returns the
    componentwise-minimum feasible point.  Hence ``decoded.x[i] <= x[i]`` and
    ``decoded.y[i] <= y[i]`` for every strip.  What it CAN change is a
    direct-insert offset, because a strip moved; score the decoded placement
    before accepting it.
    """

    pair: SequencePair
    gaps: GapProfile
    decoded: DecodedPlacement
    exact: bool


def encode_placement(
    sizes: tuple[tuple[int, int], ...],
    x: tuple[int, ...],
    y: tuple[int, ...],
    *,
    outline_height: int,
) -> EncodedPlacement:
    """Return the sequence pair whose decode reproduces one concrete placement.

    This is the inverse of :func:`decode_sequence_pair`'s relation construction,
    and the vertical direction is read off `_earliest_coordinates`, not off a
    variable's name.  That sweep treats ``successors[s]`` as the strips that come
    AFTER ``s``, so ``vertical[second].append(first)`` -- what the decoder writes
    when ``first`` precedes ``second`` in the positive permutation and follows it
    in the negative -- means ``y_first >= y_second + h_second``: **first is ABOVE
    second**.  Encoding the opposite relation there produces placements that
    decode upside down and violate ``decoded <= input``.

    So the relations are "west" and "above", and:

    * ``i`` before ``j`` in BOTH permutations  ==  i is west of j
    * ``i`` before ``j`` in positive, after in negative  ==  i is ABOVE j

    A pair may be disjoint on both axes, which leaves the choice open.  The rule
    is the axis with the SMALLER non-negative separation -- the tighter of the
    two relations.  Keeping the tight one pins the boxes where they already are;
    keeping the loose one discards a binding constraint and lets the compaction
    slide a box past its real neighbour.  The rule is symmetric in the pair and
    reads only the coordinates, so encoding the same placement twice gives the
    same pair.

    Both edge kinds strictly increase a coordinate, so both graphs are acyclic.
    """
    _validate_sizes(sizes)
    size = len(sizes)
    if len(x) != size or len(y) != size:
        raise ValueError("encoded coordinates must cover every rectangle")
    if any(type(value) is not int or value < 0 for value in (*x, *y)):
        raise ValueError("encoded coordinates must be non-negative integers")
    _validate_positive_integer(outline_height, "outline height")

    #: ``west[a]`` holds every ``b`` with ``x_b >= x_a + w_a``.
    west: list[set[int]] = [set() for _ in range(size)]
    #: ``above[a]`` holds every ``b`` with ``y_a >= y_b + h_b``.
    above: list[set[int]] = [set() for _ in range(size)]
    for first in range(size):
        for second in range(first + 1, size):
            fw, fh = sizes[first]
            sw, sh = sizes[second]
            horizontal = max(x[first] - (x[second] + sw), x[second] - (x[first] + fw))
            vertical = max(y[first] - (y[second] + sh), y[second] - (y[first] + fh))
            if horizontal < 0 and vertical < 0:
                raise ValueError("encoded placement must not overlap")
            if horizontal >= 0 and (vertical < 0 or horizontal <= vertical):
                if x[first] + fw <= x[second]:
                    west[first].add(second)
                else:
                    west[second].add(first)
            elif y[first] + fh <= y[second]:
                above[second].add(first)   # second sits above first
            else:
                above[first].add(second)   # first sits above second

    positive = _topological_order(
        [west[index] | above[index] for index in range(size)],
        key=lambda index: (x[index], y[index], index),
    )
    negative = _topological_order(
        [
            west[index] | {other for other in range(size) if index in above[other]}
            for index in range(size)
        ],
        key=lambda index: (x[index], -y[index], index),
    )
    pair = SequencePair(positive, negative)
    gaps = GapProfile.zero(size)
    decoded = decode_sequence_pair(pair, gaps, sizes, outline_height=outline_height)
    return EncodedPlacement(
        pair=pair,
        gaps=gaps,
        decoded=decoded,
        exact=decoded.x == tuple(x) and decoded.y == tuple(y),
    )


def _topological_order(
    successors: Sequence[set[int]],
    *,
    key: Callable[[int], tuple[int, ...]],
) -> tuple[int, ...]:
    """Kahn's algorithm with a total ready-set order, so the result is unique."""
    size = len(successors)
    indegree = [0] * size
    for sources in successors:
        for destination in sources:
            indegree[destination] += 1
    ready = sorted((index for index in range(size) if indegree[index] == 0), key=key)
    order: list[int] = []
    while ready:
        node = ready.pop(0)
        order.append(node)
        added = False
        for destination in sorted(successors[node]):
            indegree[destination] -= 1
            if indegree[destination] == 0:
                ready.append(destination)
                added = True
        if added:
            ready.sort(key=key)
    if len(order) != size:
        raise ValueError("encoded placement relations must be acyclic")
    return tuple(order)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/layout/test_sequence_pair.py -q -k encode`
Expected: 7 passed. If `test_encode_is_never_wider_or_taller_than_its_input` fails, print the
failing `(sizes, x, y, index)` from the assertion message: a componentwise violation means the
relation assignment disagrees with `decode_sequence_pair`'s, and the first thing to check is the
vertical direction — `vertical[second] ∋ first` means `first` is ABOVE `second`, so `above[second]`
must gain `first` when `first` sits BELOW `second`. That is a real bug, not a tolerance to widen.
If `test_encode_is_exact_for_a_tight_column` fails while the row test passes, the direction is
inverted.

- [ ] **Step 5: Run the whole sequence-pair suite**

Run: `uv run pytest tests/layout/test_sequence_pair.py -q`
Expected: all pass.

- [ ] **Step 6: Lint, type-check, commit**

```bash
uv run ruff check src/flab2bp/layout/sequence_pair.py tests/layout/test_sequence_pair.py
uv run mypy src/flab2bp/layout/sequence_pair.py
git add src/flab2bp/layout/sequence_pair.py tests/layout/test_sequence_pair.py
git commit -m "feat(layout): encode a concrete placement back into a sequence pair"
```

---

### Task 9: Split `_pack` into a model builder and a solve

Pure refactor. `_pack`'s signature, model and results are unchanged; the equivalence is proved by
the existing freeform suite plus one new byte-level check.

**Files:**
- Modify: `src/flab2bp/layout/freeform.py` — `_pack` (`:3179-3638`) split into `_pack_model`, `_pack_result` and a thin `_pack`; new `_PackModel`; new `_add_cluster_relation_no_good` beside `_add_projection_no_good` (`:3062`)
- Test: `tests/layout/test_freeform.py`

**Interfaces:**
- Consumes: `_box` (`:1544`), `_nets_between` (`:2999`), `tie_break_cap` (`:2646`), `_add_exact_pack_no_good` (`:3038`), `_add_projection_no_good` (`:3062`), `_feedback_objective_evidence`, `_width_slack_cap`, `_Pack` (`:2812`), `_DirectCandidate` (`:2381`), `LAMBDA_HPWL` (`:369`), `MU_DIRECT` (`:370`), `_PACK_RANDOM_SEED` (`:361`), `_ARRANGEMENT_STRIDE` (`:365`), `_DETERMINISTIC_PACK_WORK` (`:318`), `catalog.SORTER_MAX_REACH`, `route_feedback.ClusterRelationNoGood` (Phase B).
- Produces: `_PackModel`, `_pack_model(...) -> _PackModel | None`, `_pack_result(...) -> _Pack | None`, `_add_cluster_relation_no_good(...)`. `_pack` keeps its signature and behaviour.

- [ ] **Step 1: Establish the Phase B no-good record's shape**

```bash
uv run python -c "
from flab2bp.layout.route_feedback import ClusterRelationNoGood
print(list(ClusterRelationNoGood.__dataclass_fields__))
"
```

Decision rule: Step 5's accessor assumes the fields `height` (int), `strip_instances` (a tuple of
packed strip indices) and `origins` (a tuple of `(x, y)` content origins aligned to
`strip_instances`). If the printed names differ, rename the three accesses in
`_add_cluster_relation_no_good` to match and note the actual names in the commit message. If the
import fails, stop and report — Phase B is a prerequisite (Task 1 Step 1 should already have
caught it).

- [ ] **Step 2: Capture the pre-refactor model as a tracked snapshot**

This must run **before** any edit to `_pack`. It is what makes the split provable: after the
refactor there is only one code path, so nothing inside the tree can testify that the model did not
change.

```bash
mkdir -p tests/layout/data
uv run python - <<'PY'
from pathlib import Path

from flab2bp.layout import freeform
from flab2bp.layout.band_policy import BandPolicy  # noqa: F401  (import parity)

import tests.layout.test_freeform as tf

spec = tf.plastic_spec()
strips = freeform.plan_strips(spec, strip_len=6)
height = freeform._candidate_heights(strips)[0]
candidates = freeform._direct_candidate_snapshot(strips, spec, enabled=True)
bound = max(8, 2 * sum(freeform._box(strip)[0] for strip in strips))

# Reach into `_pack` for the model it builds.  Before the split there is no
# `_pack_model`, so capture the proto by monkeypatching `CpSolver.Solve` to stash
# the model and stop.
captured = {}
original_solve = freeform.cp_model.CpSolver.Solve


def capturing(self, model, callback=None):
    captured["proto"] = str(model.Proto())
    return original_solve(self, model, callback)


freeform.cp_model.CpSolver.Solve = capturing
freeform._pack(
    strips,
    height=height,
    width_bound=bound,
    time_budget_s=5.0,
    direct_candidates=candidates,
    workers=1,
    deterministic=True,
)
freeform.cp_model.CpSolver.Solve = original_solve
Path("tests/layout/data/plastic_pack_model.pbtxt").write_text(captured["proto"])
print(len(captured["proto"]), "bytes captured")
PY
wc -l tests/layout/data/plastic_pack_model.pbtxt
```

Expected: a few thousand bytes. Resolve `_direct_candidate_snapshot(strips, spec, enabled=True)`
against `freeform.py:15934-15939` and pass whatever `_sweep` passes to `_pack` as
`direct_candidates` at `:16369` (`net_candidates`); the capture and the test must use the identical
expression. Commit this file with the task. Regenerating it later is a separate, reviewed commit —
it is the only record of what the model looked like before the split.

- [ ] **Step 3: Write the failing structural equivalence test**

Add to `tests/layout/test_freeform.py`:

```python
def _plastic_pack_inputs() -> tuple[list[Strip], int, int, Mapping[tuple[int, int], object]]:
    spec = plastic_spec()
    strips = freeform.plan_strips(spec, strip_len=6)
    height = freeform._candidate_heights(strips)[0]
    candidates = freeform._direct_candidate_snapshot(strips, spec, enabled=True)
    bound = max(8, 2 * sum(freeform._box(strip)[0] for strip in strips))
    return strips, height, bound, candidates


def test_pack_model_with_no_pinned_strips_is_the_model_pack_built_before_the_split() -> None:
    """The split must not change one byte of the production model.

    The baseline was captured from `_pack` BEFORE the refactor and is tracked at
    `tests/layout/data/plastic_pack_model.pbtxt`.  Regenerating it is a separate,
    reviewed commit: this file is the only record of the pre-split model.

    Stability: the proto text is deterministic only for the ortools version that
    captured it (serialization and presolve annotations can shift between
    versions), and only while every collection that feeds model construction
    iterates in insertion order (lists, dicts, and int/tuple-keyed sets are
    fine; a set of strings is not, because string hashing is per-process).
    If this test fails right after an ortools upgrade, regenerate the capture
    on the new version in its own commit and say so; if it fails on the same
    version, a set-of-strings iteration has crept into the model build.
    """
    strips, height, bound, candidates = _plastic_pack_inputs()
    built = freeform._pack_model(
        strips,
        height=height,
        width_bound=bound,
        direct_candidates=candidates,
    )
    assert built is not None
    assert built.skipped_no_goods == 0
    baseline = (
        Path(__file__).parent / "data" / "plastic_pack_model.pbtxt"
    ).read_text()
    assert str(built.model.Proto()) == baseline


def test_pack_model_counts_match_its_inputs() -> None:
    """A second fence that survives a deliberate model change, unlike the snapshot."""
    strips, height, bound, candidates = _plastic_pack_inputs()
    built = freeform._pack_model(
        strips,
        height=height,
        width_bound=bound,
        direct_candidates=candidates,
    )
    assert built is not None
    assert len(built.xs) == len(strips)
    assert len(built.ys) == len(strips)
    assert len(built.direct_vars) == len(candidates)
    proto = built.model.Proto()
    assert sum(1 for c in proto.constraints if c.HasField("no_overlap_2d")) == 1
    # One abs-equality pair per net, plus the feedback terms (none here).
    assert sum(1 for c in proto.constraints if c.HasField("lin_max")) == 2 * len(
        freeform._nets_between(list(strips))
    )
```

`Path` is imported at the top of `tests/layout/test_freeform.py`; add `from pathlib import Path` if
`grep -n 'from pathlib import Path' tests/layout/test_freeform.py` finds nothing. The `lin_max`
field name is how CP-SAT encodes `add_abs_equality`; confirm with
`uv run python -c "from ortools.sat.python import cp_model; m=cp_model.CpModel(); a=m.new_int_var(0,9,'a'); b=m.new_int_var(-9,9,'b'); m.add_abs_equality(a,b); print(m.Proto().constraints[0].WhichOneof('constraint'))"`
and use whatever it prints. No test asserts variable-domain shapes: a strip whose height equals the
candidate height legitimately gets a singleton `y` domain with nothing pinned at all.

`_direct_candidate_snapshot(strips, spec, enabled=True)` is the call `_sweep` makes at
`freeform.py:15934-15939`; the value `_pack` receives as `direct_candidates` is whatever `_sweep`
passes at `:16369` (`net_candidates`). Resolve both with
`grep -n '_direct_candidate_snapshot\|net_candidates' src/flab2bp/layout/freeform.py | head` and
use the same expression here.

- [ ] **Step 4: Run to verify it fails**

Run: `uv run pytest tests/layout/test_freeform.py -q -k pack_model`
Expected: FAIL with `AttributeError: module 'flab2bp.layout.freeform' has no attribute '_pack_model'`.

- [ ] **Step 5: Add the record and the constants**

Three import edits to `freeform.py`, each checked first:

```bash
grep -n 'MappingProxyType' src/flab2bp/layout/freeform.py             # need: from types import MappingProxyType
grep -n 'from collections.abc import' src/flab2bp/layout/freeform.py  # need: Iterable, for `_no_good_is_live`
grep -n 'from flab2bp.layout.route_feedback import' src/flab2bp/layout/freeform.py
```

Add `MappingProxyType` if absent, add `Iterable` to the `collections.abc` import (Step 7's
`_no_good_is_live` annotates its parameters with it), and add `ClusterRelationNoGood` to the
existing `route_feedback` import block. Above `_pack`:

```python
#: Wall limit of one fix-and-reoptimize window solve.  A window is affordable
#: exactly because it is not a full pack: the full solve on the largest cells
#: gets `share * _PACK_SHARE / len(heights)` and is followed by a 1.9-4.6 s
#: preparation, so a repair that costs more than a second buys nothing.
C_WINDOW_SECONDS = 1.0
#: Deterministic work bound for a window solve.  A full pack of fifteen or more
#: strips gets `_DETERMINISTIC_PACK_WORK` and is expected to stop at its first
#: incumbent from a shelf warm start; a window has at most twelve free strips
#: but no such guarantee, and is expected to close a small model, so it gets
#: twenty-five times that allowance.  On an idle box this is the limit that
#: fires; under `--jobs 16` the wall limit above fires first.
C_WINDOW_DETERMINISTIC_WORK = 25 * _DETERMINISTIC_PACK_WORK
#: One CP-SAT worker per window.  `pyproject.toml` records that a single solve
#: already runs at ~700% CPU; a window must not race the packer for cores.
C_WINDOW_WORKERS = 1
#: Margin a window solve keeps between itself and the run deadline.
C_WINDOW_DEADLINE_SAFETY_SECONDS = 0.05


@dataclass(frozen=True, slots=True)
class _PackModel:
    """One built packing model and the handles a caller needs to read it back."""

    model: cp_model.CpModel
    w_var: cp_model.IntVar
    xs: list[cp_model.IntVar]
    ys: list[cp_model.IntVar]
    direct_vars: dict[tuple[int, int], cp_model.IntVar]
    sizes: list[tuple[int, int]]
    #: No-goods dropped because a pinned strip contradicted them or because they
    #: named no free strip.  Adding either would constrain the sub-model for a
    #: reason outside the window.
    skipped_no_goods: int
```

- [ ] **Step 6: Add the cluster no-good adder**

Beside `_add_projection_no_good` (`:3062`):

```python
def _add_cluster_relation_no_good(
    model: cp_model.CpModel,
    xs: Sequence[cp_model.IntVar],
    ys: Sequence[cp_model.IntVar],
    strips: Sequence[Strip],
    no_good: ClusterRelationNoGood,
) -> None:
    """Forbid one proved-unroutable relative placement of a whole cluster.

    "At least one of these strips moves" -- the same shape
    :func:`_add_projection_no_good` uses for two strips, widened to the cluster
    Phase B's conflict search proved cannot be wired in this environment.
    """
    variables: list[cp_model.IntVar] = []
    values: list[int] = []
    for strip_index, origin in zip(no_good.strip_instances, no_good.origins, strict=True):
        variables.extend((xs[strip_index], ys[strip_index]))
        values.extend((origin[0] - strips[strip_index].west_channel, origin[1]))
    model.add_forbidden_assignments(variables, [tuple(values)])
```

- [ ] **Step 7: Move `_pack`'s body into `_pack_model`**

Create `_pack_model` with this signature and move the body of `_pack` from
`model = cp_model.CpModel()` down to (but not including) `if time_budget_s <= 0:` into it:

```python
def _pack_model(
    strips: list[Strip],
    *,
    height: int,
    width_bound: int,
    direct_candidates: Mapping[tuple[int, int], _DirectCandidate],
    fixed_at: Mapping[int, tuple[int, int]] = MappingProxyType({}),
    width_target: int | None = None,
    projection_no_goods: tuple[ProjectionNoGood, ...] = (),
    exact_pack_no_goods: tuple[ExactPackNoGood, ...] = (),
    direct_relation_no_goods: tuple[_DirectRelationNoGood, ...] = (),
    cluster_relation_no_goods: tuple[ClusterRelationNoGood, ...] = (),
    feedback: FeedbackState | None = None,
    seed: _Pack | None = None,
) -> _PackModel | None:
    """Build the packing model, optionally with some strips pinned in place.

    ``fixed_at`` maps a strip index to its CONTENT origin -- the same convention
    ``_Pack.at`` uses -- and pins that strip by giving its ``x``/``y`` variables a
    singleton domain.  A singleton domain rather than a constant expression is
    deliberate: every constraint below is then written by the SAME code for a
    pinned strip as for a free one, so the window model is provably the full
    model with fewer degrees of freedom rather than a second formulation that
    has to be kept in step.  With ``fixed_at`` empty this is exactly the model
    ``_pack`` has always built.
    """
```

Six edits inside the moved body, and no others. Start `skipped = 0` right after `n = len(strips)`.

**(a) Pinned domains** — replace the `for i, (w, h) in enumerate(sizes):` loop (`:3241-3248`):

```python
    for i, (w, h) in enumerate(sizes):
        pinned = fixed_at.get(i)
        if pinned is None:
            x = model.new_int_var(0, max(0, width_bound - w), f"x{i}")
            y = model.new_int_var(0, max(0, height - h), f"y{i}")
        else:
            bx = pinned[0] - strips[i].west_channel
            by = pinned[1]
            if not (0 <= bx <= max(0, width_bound - w)) or not (0 <= by <= max(0, height - h)):
                return None  # the pin is outside this outline; nothing to repair here
            x = model.new_int_var(bx, bx, f"x{i}")
            y = model.new_int_var(by, by, f"y{i}")
        xs.append(x)
        ys.append(y)
        x_iv.append(model.new_fixed_size_interval_var(x, w, f"xi{i}"))
        y_iv.append(model.new_fixed_size_interval_var(y, h, f"yi{i}"))
        model.add(x + w <= w_var)
```

**(b) A reusable no-good guard** — add above the no-good loops:

```python
    def _no_good_is_live(named: Iterable[int], origins: Iterable[tuple[int, int]]) -> bool:
        """Is this no-good worth adding to a model with pinned strips?

        No, twice over.  If a pinned strip already sits somewhere else, the
        forbidden tuple is unreachable and the constraint is dead weight.  If
        every strip it names is pinned, its only free variable is ``w_var`` and
        it would forbid a WIDTH for no geometric reason.
        """
        named = tuple(named)
        origins = tuple(origins)
        if all(index in fixed_at for index in named):
            return False
        for index, origin in zip(named, origins, strict=True):
            current = fixed_at.get(index)
            if current is not None and current != origin:
                return False
        return True
```

**(c) The exact-pack loop** (`:3252-3255`):

```python
    for exact_no_good in exact_pack_no_goods:
        if exact_no_good.height != height or exact_no_good.outline != tuple(sizes):
            continue
        if not _no_good_is_live(range(n), exact_no_good.origins):
            skipped += 1
            continue
        _add_exact_pack_no_good(model, w_var, xs, ys, strips, exact_no_good)
```

**(d) The projection loop** (`:3257-3266`) — after the existing `pack_height` check:

```python
        if not _no_good_is_live(
            (projection_no_good.left_strip, projection_no_good.right_strip),
            (projection_no_good.left_origin, projection_no_good.right_origin),
        ):
            skipped += 1
            continue
```

and, in the direct-relation loop (`:3415-3446`), after `direct_var` is resolved:

```python
        if pair[0] in fixed_at and pair[1] in fixed_at:
            skipped += 1
            continue
```

Add the cluster loop directly after the direct-relation loop:

```python
    for cluster_no_good in cluster_relation_no_goods:
        if cluster_no_good.height != height:
            continue
        if not _no_good_is_live(cluster_no_good.strip_instances, cluster_no_good.origins):
            skipped += 1
            continue
        _add_cluster_relation_no_good(model, xs, ys, strips, cluster_no_good)
```

**(e) Symmetry breaking** (`:3339-3348`) — first statement of the `for j` body:

```python
            if i in fixed_at or j in fixed_at:
                continue
```

**(f) Warm start** (`:3567-3585`) — the hint loop skips pinned strips:

```python
        for i, (hx, hy) in seed.at.items():
            if i >= n or i in fixed_at:
                continue
```

Then, after the objective and warm start, the width target and the return:

```python
    if width_target is not None:
        if all(
            fixed_at[index][0] - strips[index].west_channel + sizes[index][0] <= width_target
            for index in fixed_at
        ):
            model.add(w_var <= width_target)
        else:
            # A pinned strip already reaches past the target, so the bound cannot
            # be added without making the sub-model infeasible for a reason
            # outside the window.  Count it: a target that never applies is a
            # repair aimed at nothing, and the gate must be able to see that.
            skipped += 1

    return _PackModel(
        model=model,
        w_var=w_var,
        xs=xs,
        ys=ys,
        direct_vars=direct_vars,
        sizes=sizes,
        skipped_no_goods=skipped,
    )
```

- [ ] **Step 8: Add `_pack_result` and rebuild `_pack` on the split**

```python
def _pack_result(
    built: _PackModel,
    solver: cp_model.CpSolver,
    strips: Sequence[Strip],
    direct_candidates: Mapping[tuple[int, int], _DirectCandidate],
    height: int,
    admission: cp_model.CpSolverSolutionCallback | None,
) -> _Pack | None:
    """Solve one built model and read its assignment back as a `_Pack`."""
    status = solver.Solve(built.model, admission)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None
    return _Pack(
        at={
            i: (solver.Value(built.xs[i]) + strips[i].west_channel, solver.Value(built.ys[i]))
            for i in range(len(strips))
        },
        width=solver.Value(built.w_var),
        height=height,
        status=solver.StatusName(status),
        hit_budget=status == cp_model.FEASIBLE,
        direct=frozenset(
            DirectInsertId(
                i,
                j,
                direct_candidates[i, j].item,
                direct_candidates[i, j].cargo_domain,
            )
            for (i, j), di in built.direct_vars.items()
            if solver.Value(di)
        ),
    )
```

`_pack` keeps its signature and docstring and becomes:

```python
    built = _pack_model(
        strips,
        height=height,
        width_bound=width_bound,
        direct_candidates=direct_candidates,
        projection_no_goods=projection_no_goods,
        exact_pack_no_goods=exact_pack_no_goods,
        direct_relation_no_goods=direct_relation_no_goods,
        feedback=feedback,
        seed=seed,
    )
    if built is None or time_budget_s <= 0:
        return None
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_budget_s
    solver.parameters.num_search_workers = workers
    if deterministic:
        solver.parameters.max_deterministic_time = min(
            time_budget_s,
            _DETERMINISTIC_PACK_WORK,
        )
    solver.parameters.random_seed = _PACK_RANDOM_SEED + _ARRANGEMENT_STRIDE * arrangement

    class SeedAdmission(cp_model.CpSolverSolutionCallback):
        """End this solve once its exact incumbent admits the routed seed."""

        def on_solution_callback(self) -> None:
            assert seed is not None
            if seed.width <= _width_slack_cap(self.Value(built.w_var)):
                self.StopSearch()

    admission = SeedAdmission() if stop_when_seed_admissible and seed is not None else None
    return _pack_result(built, solver, strips, direct_candidates, height, admission)
```

- [ ] **Step 9: Run the freeform suite**

```bash
uv run pytest tests/layout/test_freeform.py -q
uv run pytest -q
```

Expected: all pass. The no-good scoping tests
(`test_projection_no_good_forbids_only_the_exact_failed_pair_context`,
`test_staged_static_exact_pack_no_good_forbids_only_the_full_assignment`, and neighbours at
`tests/layout/test_freeform.py:3298`, `:3382`, `:5639`, `:5713`, `:5770`, `:5824`, `:5885`, `:6064`,
`:6671`) are the ones that would catch a mis-moved constraint. If one fails, the split changed the
model: do not weaken the assertion, find the moved line.

- [ ] **Step 10: Lint, type-check, commit**

```bash
uv run ruff check src/flab2bp/layout/freeform.py tests/layout/test_freeform.py
uv run mypy src/flab2bp/layout/freeform.py
git add src/flab2bp/layout/freeform.py tests/layout/test_freeform.py tests/layout/data/plastic_pack_model.pbtxt
git commit -m "refactor(layout): split the packing model builder from its solve"
```

---

### Task 10: `_pack_window`

**Files:**
- Modify: `src/flab2bp/layout/freeform.py` — add `_pack_window` after `_pack_result`
- Test: `tests/layout/test_freeform.py`

**Interfaces:**
- Consumes: `_pack_model`, `_pack_result`, `_PackModel`, `C_WINDOW_SECONDS`, `C_WINDOW_DETERMINISTIC_WORK`, `C_WINDOW_WORKERS` (Task 9).
- Produces: `_pack_window(...) -> _Pack | None` with the signature in the spec's section 6.

- [ ] **Step 1: Write the failing tests**

Add to `tests/layout/test_freeform.py`:

```python
def test_pack_window_over_every_strip_reproduces_the_full_pack() -> None:
    """The window model IS `_pack` with some domains collapsed; with none
    collapsed and no seed on either side, it must return the same assignment."""
    strips, height, bound, candidates = _plastic_pack_inputs()
    full = freeform._pack(
        strips,
        height=height,
        width_bound=bound,
        time_budget_s=5.0,
        direct_candidates=candidates,
        workers=1,
        deterministic=True,
    )
    assert full is not None
    windowed = freeform._pack_window(
        strips,
        height=height,
        width_bound=bound,
        direct_candidates=candidates,
        window=frozenset(range(len(strips))),
        fixed_at={},
        seed=None,
        time_budget_s=5.0,
        deterministic_work=freeform._DETERMINISTIC_PACK_WORK,
    )
    assert windowed is not None
    assert windowed.width == full.width
    assert windowed.at == full.at
    assert windowed.direct == full.direct


def test_pack_window_leaves_every_pinned_strip_where_it_was() -> None:
    strips, height, bound, candidates = _plastic_pack_inputs()
    seed = freeform._pack(
        strips,
        height=height,
        width_bound=bound,
        time_budget_s=5.0,
        direct_candidates=candidates,
        workers=1,
        deterministic=True,
    )
    assert seed is not None
    window = frozenset({0})
    fixed = {index: origin for index, origin in seed.at.items() if index not in window}
    windowed = freeform._pack_window(
        strips,
        height=height,
        width_bound=seed.width,
        direct_candidates=candidates,
        window=window,
        fixed_at=fixed,
        seed=seed,
    )
    assert windowed is not None
    for index, origin in fixed.items():
        assert windowed.at[index] == origin
    assert windowed.width <= seed.width


def test_pack_window_never_widens_past_its_bound() -> None:
    strips, height, bound, candidates = _plastic_pack_inputs()
    seed = freeform._pack(
        strips,
        height=height,
        width_bound=bound,
        time_budget_s=5.0,
        direct_candidates=candidates,
        workers=1,
        deterministic=True,
    )
    assert seed is not None
    free = min(3, len(strips))
    windowed = freeform._pack_window(
        strips,
        height=height,
        width_bound=seed.width,
        direct_candidates=candidates,
        window=frozenset(range(free)),
        fixed_at={
            index: origin for index, origin in seed.at.items() if index >= free
        },
        seed=seed,
    )
    assert windowed is None or windowed.width <= seed.width


def _pinned_exact_no_good(strips: list[Strip], height: int, pack: object) -> object:
    return freeform.ExactPackNoGood(
        height=height,
        outline=tuple(freeform._box(strip) for strip in strips),
        width=pack.width,  # type: ignore[attr-defined]
        origins=tuple(pack.at[index] for index in range(len(strips))),  # type: ignore[attr-defined]
        evidence=(
            finalize.ProjectionFailure(check="test.pinned", buildings=(), detail="", band=0),
        ),
    )


def test_pack_model_skips_an_exact_no_good_with_no_free_strip() -> None:
    """Every strip pinned: the no-good's only free variable would be `w_var`.

    Written against `_pack_model` and not `_pack_window`, because `_pack_window`
    forbids an empty window -- and an empty window is exactly the case that makes
    the no-good degenerate.
    """
    strips, height, bound, candidates = _plastic_pack_inputs()
    seed = freeform._pack(
        strips,
        height=height,
        width_bound=bound,
        time_budget_s=5.0,
        direct_candidates=candidates,
        workers=1,
        deterministic=True,
    )
    assert seed is not None
    built = freeform._pack_model(
        strips,
        height=height,
        width_bound=seed.width,
        direct_candidates=candidates,
        fixed_at=dict(seed.at),
        exact_pack_no_goods=(_pinned_exact_no_good(strips, height, seed),),
    )
    assert built is not None
    assert built.skipped_no_goods == 1


def test_pack_model_skips_an_unapplicable_width_target() -> None:
    """A target the pinned strips already exceed is dropped and counted."""
    strips, height, bound, candidates = _plastic_pack_inputs()
    seed = freeform._pack(
        strips,
        height=height,
        width_bound=bound,
        time_budget_s=5.0,
        direct_candidates=candidates,
        workers=1,
        deterministic=True,
    )
    assert seed is not None
    built = freeform._pack_model(
        strips,
        height=height,
        width_bound=seed.width,
        direct_candidates=candidates,
        fixed_at={index: origin for index, origin in seed.at.items() if index != 0},
        width_target=1,
    )
    assert built is not None
    assert built.skipped_no_goods == 1


def test_pack_window_keeps_a_no_good_that_still_has_a_free_strip() -> None:
    """The mirror case: strip 0 is free, so the no-good is live and must be added."""
    strips, height, bound, candidates = _plastic_pack_inputs()
    seed = freeform._pack(
        strips,
        height=height,
        width_bound=bound,
        time_budget_s=5.0,
        direct_candidates=candidates,
        workers=1,
        deterministic=True,
    )
    assert seed is not None
    skipped: list[int] = []
    windowed = freeform._pack_window(
        strips,
        height=height,
        width_bound=seed.width,
        direct_candidates=candidates,
        window=frozenset({0}),
        fixed_at={index: origin for index, origin in seed.at.items() if index != 0},
        seed=seed,
        exact_pack_no_goods=(_pinned_exact_no_good(strips, height, seed),),
        on_skipped=skipped.append,
    )
    assert skipped == []
    # The forbidden assignment is the seed's, so the solve must move strip 0 or
    # find nothing at all -- it must not hand back the pack it was told to reject.
    assert windowed is None or windowed.at[0] != seed.at[0]


def test_pack_window_reports_a_skip_through_on_skipped() -> None:
    strips, height, bound, candidates = _plastic_pack_inputs()
    seed = freeform._pack(
        strips,
        height=height,
        width_bound=bound,
        time_budget_s=5.0,
        direct_candidates=candidates,
        workers=1,
        deterministic=True,
    )
    assert seed is not None
    skipped: list[int] = []
    freeform._pack_window(
        strips,
        height=height,
        width_bound=seed.width,
        direct_candidates=candidates,
        window=frozenset({0}),
        fixed_at={index: origin for index, origin in seed.at.items() if index != 0},
        seed=seed,
        width_target=1,
        on_skipped=skipped.append,
    )
    assert skipped == [1]
```

`finalize.ProjectionFailure`'s real field names are at `finalize.py`; resolve with
`grep -n 'class ProjectionFailure' -A 8 src/flab2bp/layout/finalize.py` and match, dropping the
`object`/`type: ignore` shims in `_pinned_exact_no_good` for the real `_Pack` annotation once
`_Pack` is in scope in the test module (`grep -n '_Pack' tests/layout/test_freeform.py | head -3`).
`ExactPackNoGood` is a module-level class at `freeform.py:2745`.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/layout/test_freeform.py -q -k pack_window`
Expected: FAIL with `AttributeError: module 'flab2bp.layout.freeform' has no attribute '_pack_window'`.

- [ ] **Step 3: Implement `_pack_window`**

```python
def _pack_window(
    strips: list[Strip],
    *,
    height: int,
    width_bound: int,
    direct_candidates: Mapping[tuple[int, int], _DirectCandidate],
    window: frozenset[int],
    fixed_at: Mapping[int, tuple[int, int]],
    seed: _Pack | None = None,
    width_target: int | None = None,
    arrangement: int = 0,
    projection_no_goods: tuple[ProjectionNoGood, ...] = (),
    exact_pack_no_goods: tuple[ExactPackNoGood, ...] = (),
    direct_relation_no_goods: tuple[_DirectRelationNoGood, ...] = (),
    cluster_relation_no_goods: tuple[ClusterRelationNoGood, ...] = (),
    feedback: FeedbackState | None = None,
    time_budget_s: float = C_WINDOW_SECONDS,
    deterministic_work: float = C_WINDOW_DETERMINISTIC_WORK,
    on_skipped: Callable[[int], None] | None = None,
) -> _Pack | None:
    """Re-solve `_pack`'s formulation for ``window`` with everything else pinned.

    This is a sub-model, not a re-solve: every strip, constraint, no-good and
    objective term of the full model is present, and only the pinned strips'
    domains are collapsed.  `test_pack_window_over_every_strip_reproduces_the_full_pack`
    pins that claim by asking for the whole problem as the window, with no seed
    on either side, and comparing against `_pack`.

    Returns ``None`` only when the sub-model is infeasible or the solve returns
    no incumbent.  An assignment identical to the seed's is returned as-is: the
    caller decides what that means, because "the window found nothing better" is
    a signal, not an error.
    """
    if not window:
        raise ValueError("a repair window must name at least one strip")
    if any(index in fixed_at for index in window):
        raise ValueError("window strips must not also be pinned")
    if set(fixed_at) | window != set(range(len(strips))):
        raise ValueError("window and pinned strips must cover every strip")
    if time_budget_s <= 0:
        return None
    built = _pack_model(
        strips,
        height=height,
        width_bound=width_bound,
        direct_candidates=direct_candidates,
        fixed_at=fixed_at,
        width_target=width_target,
        projection_no_goods=projection_no_goods,
        exact_pack_no_goods=exact_pack_no_goods,
        direct_relation_no_goods=direct_relation_no_goods,
        cluster_relation_no_goods=cluster_relation_no_goods,
        feedback=feedback,
        seed=seed,
    )
    if built is None:
        return None
    if on_skipped is not None and built.skipped_no_goods:
        on_skipped(built.skipped_no_goods)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_budget_s
    solver.parameters.num_search_workers = C_WINDOW_WORKERS
    solver.parameters.max_deterministic_time = min(time_budget_s, deterministic_work)
    solver.parameters.random_seed = _PACK_RANDOM_SEED + _ARRANGEMENT_STRIDE * arrangement
    return _pack_result(built, solver, strips, direct_candidates, height, None)
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/layout/test_freeform.py -q -k "pack_window or pack_model_skips"`
Expected: 7 passed. If `test_pack_window_over_every_strip_reproduces_the_full_pack` fails on `at`,
the two paths are not building the same model: print `str(built.model.Proto())` under both and diff
against `tests/layout/data/plastic_pack_model.pbtxt`. Do not weaken the assertion.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check src/flab2bp/layout/freeform.py tests/layout/test_freeform.py
uv run mypy src/flab2bp/layout/freeform.py
uv run pytest -q
git add src/flab2bp/layout/freeform.py tests/layout/test_freeform.py
git commit -m "feat(layout): re-solve the packing model over a window with the rest pinned"
```

---

### Task 11: `LOCAL_EXACT_PACK` in sequence-pair

**Files:**
- Modify: `src/flab2bp/layout/sequence_solver.py` — the `window_pack` closure in `_production_run` (beside `commit_stage`, `:4791`), `_ProductionTelemetry` (`:3806`), the `SequenceSolver(...)` construction (`:4804`), `_alns_substitution`'s `LOCAL_EXACT_PACK` branch (Task 4 Step 4), the production stats dict
- Modify: `src/flab2bp/layout/base.py:198` (`PlacementStats`) — add `alns_encode_errors`, `alns_encode_inexact`, `alns_skipped_no_goods`, `alns_window_accepted`, `alns_window_seconds`, `alns_window_solves`
- Test: `tests/layout/test_sequence_solver.py`

**Interfaces:**
- Consumes: `_pack_window`, `C_WINDOW_SECONDS`, `C_WINDOW_DEADLINE_SAFETY_SECONDS` (Tasks 9-10); `encode_placement` (Task 8); `_decoded_pack(height, decoded, *, west_channels, direct_candidates)` (`sequence_solver.py:5138`); `_selected_strips(strips, problem, variant_indices, *, band_policy)`; `PlacementProblem.selected_sizes(variant_indices)` (`sequence_pair.py:162`).
- Produces: a populated `_RepairAdapters.window_pack`; `LOCAL_EXACT_PACK` in the production repair portfolio; the placement stats `alns_window_solves`, `alns_window_accepted`, `alns_window_seconds`, `alns_encode_inexact`, `alns_encode_errors`, `alns_skipped_no_goods`.

- [ ] **Step 1: Write the failing tests**

**Imports this task adds to `tests/layout/test_sequence_solver.py`:** `SHIPPED_REPAIR` from
`flab2bp.layout.sequence_alns`.

```python
@pytest.mark.slow
def test_the_window_adapter_returns_a_decodable_placement() -> None:
    spec = plastic_spec()
    run = sequence_solver._production_run(
        spec,
        time_budget_s=10.0,
        power=True,
        band_policy=BandPolicy.parse("any"),
        strip_len=6,
        config=SequenceSolverConfig.test(),
    )
    adapters = run.solver.alns_adapters
    assert adapters.window_pack is not None
    problem = run.solver._heights[0].problem
    state = run.solver._heights[0].restarts[0].anneal
    decoded = decode_state(problem, state)
    repaired = adapters.window_pack(frozenset({0}), problem, state, decoded)
    if repaired is not None:
        repaired.pair.validate(problem.size)
        assert len(repaired.decoded.x) == problem.size
        assert repaired.decoded.used_height <= problem.outline_height
        assert repaired.decoded.width <= decoded.width
        assert repaired.decoded.variant_indices == state.variant_indices


@pytest.mark.slow
def test_local_exact_pack_is_in_the_production_repair_portfolio() -> None:
    spec = plastic_spec()
    run = sequence_solver._production_run(
        spec,
        time_budget_s=10.0,
        power=True,
        band_policy=BandPolicy.parse("any"),
        strip_len=6,
        config=SequenceSolverConfig.test(),
    )
    session = run.solver.alns_session
    played: set[RepairOperator] = set()
    for _ in range(len(SHIPPED_REPAIR)):
        choice = session.select(
            OperatorContext(strip_count=8, stagnation=0, remaining_fraction=10)
        )
        played.add(choice.repair)
        session.observe(choice, (0.0,) * REWARD_RANKS, applied=True)
    assert played == set(SHIPPED_REPAIR)
```

`_production_run`'s real keyword list is at `sequence_solver.py:3915-3928`; match it exactly.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/layout/test_sequence_solver.py -q -k "window_adapter or repair_portfolio"`
Expected: FAIL with `AssertionError: assert None is not None` on `adapters.window_pack`.

- [ ] **Step 3: Add the telemetry fields and the adapter**

Add to `_ProductionTelemetry` (`:3806`):

```python
    alns_window_solves: int = 0
    alns_window_accepted: int = 0
    alns_window_seconds: float = 0.0
    alns_encode_inexact: int = 0
    alns_encode_errors: int = 0
    alns_skipped_no_goods: int = 0
```

Beside `commit_stage` in `_production_run` (`:4791`), where `strips`, `band_policy`,
`direct_candidates`, `deadline`, `projection_envelope` and `telemetry` are in scope (hoist
`projection_envelope` from `:4100` if it is not — Task 7 already needed it there):

```python
    def _count_skipped_no_goods(count: int) -> None:
        telemetry.alns_skipped_no_goods += count

    def window_pack(
        window: frozenset[int],
        problem: PlacementProblem,
        state: AnnealState,
        decoded: DecodedPlacement,
    ) -> EncodedPlacement | None:
        """Repair a decoded placement with a bounded CP-SAT window, then encode it.

        Returns the whole encoding, not just its placement: the round trip is not
        exact, so re-encoding the compaction upstream could yield a second,
        different pair.  The compaction itself is provably never wider and never
        taller, so this cannot lose area or band fit.  It can move a strip and so
        change a direct-insert offset, which is why the caller scores the
        returned placement before accepting it: what the search then evaluates is
        what would be built.
        """
        if not window or len(window) >= problem.size:
            return None
        remaining = None if deadline is None else deadline - time.monotonic()
        if remaining is not None and remaining <= C_WINDOW_SECONDS:
            return None
        selected = _selected_strips(
            strips, problem, state.variant_indices, band_policy=band_policy
        )
        pack = _decoded_pack(
            problem.outline_height,
            decoded,
            west_channels=tuple(strip.west_channel for strip in selected),
            direct_candidates=direct_candidates,
        )
        telemetry.alns_window_solves += 1
        started_window = time.monotonic()
        repaired = _pack_window(
            list(selected),
            height=problem.outline_height,
            width_bound=decoded.width,
            direct_candidates=direct_candidates,
            window=window,
            fixed_at={
                index: origin for index, origin in pack.at.items() if index not in window
            },
            seed=pack,
            width_target=finalize.band_target_width(
                projection_envelope,
                height=problem.outline_height,
                width=decoded.width,
            ),
            time_budget_s=(
                C_WINDOW_SECONDS
                if remaining is None
                else min(C_WINDOW_SECONDS, remaining - C_WINDOW_DEADLINE_SAFETY_SECONDS)
            ),
            on_skipped=_count_skipped_no_goods,
        )
        telemetry.alns_window_seconds += time.monotonic() - started_window
        if repaired is None or repaired.at == pack.at:
            # An unchanged assignment is not a repair.  The caller credits the
            # choice as unapplied rather than re-evaluating a placement the
            # router has already refused.
            return None
        try:
            encoded = encode_placement(
                problem.selected_sizes(state.variant_indices),
                tuple(
                    repaired.at[index][0] - selected[index].west_channel
                    for index in range(problem.size)
                ),
                tuple(repaired.at[index][1] for index in range(problem.size)),
                outline_height=problem.outline_height,
            )
        except ValueError:
            # An overlapping result cannot happen for a pack CP-SAT returned; a
            # cyclic relation graph has never been produced but is not proven
            # impossible. Either way the choice is dropped, not repaired.
            telemetry.alns_encode_errors += 1
            return None
        if not encoded.exact:
            telemetry.alns_encode_inexact += 1
        if encoded.decoded.used_height > problem.outline_height:
            return None
        telemetry.alns_window_accepted += 1
        return replace(
            encoded,
            decoded=replace(encoded.decoded, variant_indices=state.variant_indices),
        )
```

Add the imports this needs: `_pack_window`, `C_WINDOW_SECONDS`, `C_WINDOW_DEADLINE_SAFETY_SECONDS`
from `flab2bp.layout.freeform` (the block at `sequence_solver.py:33-78` already imports from that
module), and `EncodedPlacement` plus `encode_placement` from `flab2bp.layout.sequence_pair`. If
Task 4 left `_RepairAdapters.window_pack` typed as `Callable[..., object] | None`, tighten it to
`Callable[[frozenset[int], PlacementProblem, AnnealState, DecodedPlacement], EncodedPlacement | None] | None`
now and say so in this commit message.

- [ ] **Step 4: Wire the adapter and open the repair portfolio**

In `_production_run`'s `SequenceSolver(...)` construction, replace the Task 7 line with:

```python
        # Both portfolios open: the window adapter exists, so LOCAL_EXACT_PACK
        # has an implementation behind it.
        alns_session=OperatorSession(),
        alns_adapters=_RepairAdapters(window_pack=window_pack),
```

- [ ] **Step 5: Declare and write the stats**

In `PlacementStats` (`base.py:198`), in alphabetical position:

```python
    alns_encode_errors: float
    alns_encode_inexact: float
    alns_skipped_no_goods: float
    alns_window_accepted: float
    alns_window_seconds: float
    alns_window_solves: float
```

In the production stats dict, beside the Task 5 keys:

```python
            "alns_window_solves": float(telemetry.alns_window_solves),
            "alns_window_accepted": float(telemetry.alns_window_accepted),
            "alns_window_seconds": telemetry.alns_window_seconds,
            "alns_encode_inexact": float(telemetry.alns_encode_inexact),
            "alns_encode_errors": float(telemetry.alns_encode_errors),
            "alns_skipped_no_goods": float(telemetry.alns_skipped_no_goods),
```

- [ ] **Step 6: Run the suite**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 7: Measure the sequence-pair half of gate 2**

```bash
uv run python scripts/audit.py --budget 30 --jobs 4 --strategy sequence-pair \
  --only universe-matrix,graphene --json /tmp/phase-c-task11.jsonl | tail -6
uv run python scripts/audit_compare.py \
  docs/superpowers/evidence/2026-09-02-phase-c-alns/baseline-budget30-round1.jsonl \
  /tmp/phase-c-task11.jsonl --regressions-only
jq -r '[.strategy,.spec_label,.status,.seconds,.area] | @tsv' /tmp/phase-c-task11.jsonl
uv run python -c "
from flab2bp.bench.corpus import URL_CORPUS
from flab2bp.lab.data import load_vendored
from flab2bp.lab.url import parse_url
from flab2bp.layout.band_policy import BandPolicy
from flab2bp.layout.sequence_solver import SequencePairLayout
from flab2bp.rates.candidates import DEFAULT_CANDIDATE_POLICIES, build_candidates
entry = next(c for c in URL_CORPUS if c.url_id == 'universe-matrix')
built = build_candidates(load_vendored(), parse_url(entry.url), candidate_policies=DEFAULT_CANDIDATE_POLICIES)
spec = next(c.spec for c in built.candidates if c.label == 'no-proliferator')
p = SequencePairLayout(band_policy=BandPolicy.parse('any')).lay_out(spec, time_budget_s=30.0)
print({k: v for k, v in p.stats.items() if k.startswith('alns') or k == 'feasibility_restart_batches'})
"
```

Expected: no regression, and `graphene/output-products` still CLEAN. Record every row and the
whole `alns_*` dict in the commit message — these are gate 2's sequence-pair absolutes. If
`alns_window_solves` is 0, the operator never fired: report that rather than tuning
`C_WINDOW_FRACTION_FLOOR`.

- [ ] **Step 8: Lint, type-check, commit**

```bash
uv run ruff check src/flab2bp/layout tests/layout
uv run mypy src/flab2bp/layout/sequence_solver.py src/flab2bp/layout/base.py
git add src/flab2bp/layout tests/layout
git commit -m "feat(layout): repair sequence-pair placements with a bounded CP-SAT window"
```

---

### Task 12: Freeform window adapters

Three pure helpers plus the cost function, with unit tests and **no sweep changes**. Task 13 wires
them.

**Files:**
- Modify: `src/flab2bp/layout/freeform.py` — add `_window_candidate_seconds` beside `_room_for_another` (`:16984`), and `_decoded_from_pack`, `_pack_relation_problem`, `_pack_relation_pair` beside `_pack_window`
- Test: `tests/layout/test_freeform.py`

**Interfaces:**
- Consumes: `_box` (`:1544`), `_nets_between` (`:2999`), `_Pack` (`:2812`), `encode_placement` (Task 8), `DecodedPlacement`, `GapProfile`, `PlacementProblem`, `SequencePair` (`sequence_pair.py`), `C_WINDOW_SECONDS` (Task 9).
- Produces: `_window_candidate_seconds(*, dearest_candidate_s, dearest_pack_s) -> float`, `_decoded_from_pack(pack, strips, height) -> DecodedPlacement`, `_pack_relation_problem(pack, strips, height) -> PlacementProblem`, `_pack_relation_pair(pack, strips, height) -> SequencePair`.

- [ ] **Step 1: Write the failing tests**

```python
def test_window_candidate_cost_charges_the_window_plus_the_measured_remainder() -> None:
    assert freeform._window_candidate_seconds(
        dearest_candidate_s=6.0, dearest_pack_s=2.0
    ) == freeform.C_WINDOW_SECONDS + 4.0
    assert freeform._window_candidate_seconds(
        dearest_candidate_s=1.0, dearest_pack_s=4.0
    ) == freeform.C_WINDOW_SECONDS


def test_decoded_from_pack_views_a_pack_as_a_decoded_placement() -> None:
    strips, height, bound, candidates = _plastic_pack_inputs()
    pack = freeform._pack(
        strips,
        height=height,
        width_bound=bound,
        time_budget_s=5.0,
        direct_candidates=candidates,
        workers=1,
        deterministic=True,
    )
    assert pack is not None
    decoded = freeform._decoded_from_pack(pack, strips, height)
    assert len(decoded.x) == len(strips)
    assert decoded.width == pack.width
    for index, strip in enumerate(strips):
        assert decoded.x[index] == pack.at[index][0] - strip.west_channel
        assert decoded.y[index] == pack.at[index][1]
    assert decoded.used_height == max(
        decoded.y[index] + freeform._box(strip)[1]
        for index, strip in enumerate(strips)
    )


def test_pack_relation_problem_carries_the_packs_sizes_and_nets() -> None:
    strips, height, bound, candidates = _plastic_pack_inputs()
    pack = freeform._pack(
        strips,
        height=height,
        width_bound=bound,
        time_budget_s=5.0,
        direct_candidates=candidates,
        workers=1,
        deterministic=True,
    )
    assert pack is not None
    problem = freeform._pack_relation_problem(pack, strips, height)
    assert problem.sizes == tuple(freeform._box(strip) for strip in strips)
    assert problem.nets == tuple(freeform._nets_between(list(strips)))
    assert problem.outline_height == height
    assert problem.logical_net_ids == ()


def test_pack_relation_pair_decodes_back_to_the_packs_relations() -> None:
    strips, height, bound, candidates = _plastic_pack_inputs()
    pack = freeform._pack(
        strips,
        height=height,
        width_bound=bound,
        time_budget_s=5.0,
        direct_candidates=candidates,
        workers=1,
        deterministic=True,
    )
    assert pack is not None
    pair = freeform._pack_relation_pair(pack, strips, height)
    pair.validate(len(strips))
    assert sorted(pair.positive) == list(range(len(strips)))
    assert sorted(pair.negative) == list(range(len(strips)))
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/layout/test_freeform.py -q -k "window_candidate_cost or decoded_from_pack or pack_relation"`
Expected: FAIL with `AttributeError: module 'flab2bp.layout.freeform' has no attribute '_window_candidate_seconds'`.

- [ ] **Step 3: Add the cost function**

Beside `_room_for_another` (`:16984`):

```python
def _window_candidate_seconds(*, dearest_candidate_s: float, dearest_pack_s: float) -> float:
    """What one windowed retry costs, measured rather than tuned.

    A full retry is charged the dearest completed candidate, pack included.  A
    window replaces the pack with a bounded solve and leaves everything after it
    -- preparation, routing, power, finalize, validate -- exactly where it was,
    so its charge is that bounded solve plus the measured remainder.  Like
    `_room_for_another`'s `candidate_s`, this is a measurement: a fixed constant
    cannot span a corpus running from one to 955 machines.
    """
    return C_WINDOW_SECONDS + max(0.0, dearest_candidate_s - dearest_pack_s)
```

- [ ] **Step 4: Add the three adapters**

Beside `_pack_window`. Add `from flab2bp.layout.sequence_pair import DecodedPlacement,
PlacementProblem, SequencePair, encode_placement` to `freeform.py`'s imports — check first that
this does not create a cycle (`grep -n 'import' src/flab2bp/layout/sequence_pair.py | head -20`;
`sequence_pair` must not import `freeform`, and at `b3c990a` it does not):

```python
def _decoded_from_pack(pack: _Pack, strips: Sequence[Strip], height: int) -> DecodedPlacement:
    """View one packed assignment as a decoded placement for the destroy operators.

    `_Pack.at` holds CONTENT origins and a decoded placement holds BOX origins,
    so the west channel comes back off.  The coordinate windows are degenerate
    (each equals its coordinate) because a packed assignment has no slack left
    to describe: nothing downstream of a destroy operator reads them.
    """
    sizes = [_box(strip) for strip in strips]
    xs = tuple(pack.at[index][0] - strips[index].west_channel for index in range(len(strips)))
    ys = tuple(pack.at[index][1] for index in range(len(strips)))
    return DecodedPlacement(
        x=xs,
        y=ys,
        width=pack.width,
        used_height=max(
            (ys[index] + sizes[index][1] for index in range(len(strips))), default=0
        ),
        x_windows=tuple((value, value) for value in xs),
        y_windows=tuple((value, value) for value in ys),
        gap_area=0,
    )


def _pack_relation_problem(
    pack: _Pack, strips: Sequence[Strip], height: int
) -> PlacementProblem:
    """A placement problem carrying this pack's sizes and nets, for operator reuse.

    ``logical_net_ids`` is left empty on purpose.  No shipped destroy operator
    reads it, and `_nets_between` returns bare strip-index pairs with no item
    identity, so filling it would mean synthesizing `LogicalNetId`s nothing
    consumes.  The operator that would need them (RELATED_CARGO) is a follow-up,
    and populating this field belongs to that operator's task.
    """
    sizes = tuple(_box(strip) for strip in strips)
    return PlacementProblem(
        sizes=sizes,
        nets=tuple(_nets_between(list(strips))),
        outline_height=height,
        area_lower_bound=sum(width * box_height for width, box_height in sizes),
    )


def _pack_relation_pair(pack: _Pack, strips: Sequence[Strip], height: int) -> SequencePair:
    """The sequence pair this pack encodes to, for the sequence-neighbour operator.

    Its gaps are zero by construction, so `select_lns_neighbourhood`'s
    gap-rectangle branch never fires on a freeform pack: the neighbourhood there
    is failure endpoints plus sequence neighbours only.
    """
    decoded = _decoded_from_pack(pack, strips, height)
    return encode_placement(
        tuple(_box(strip) for strip in strips),
        decoded.x,
        decoded.y,
        outline_height=height,
    ).pair
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/layout/test_freeform.py -q -k "window_candidate_cost or decoded_from_pack or pack_relation"`
Expected: 4 passed. If `_pack_relation_pair` raises `ValueError: encoded placement must not overlap`,
the pack's boxes overlap, which `add_no_overlap_2d` forbids: report it, do not catch it here.

- [ ] **Step 6: Lint, type-check, commit**

```bash
uv run ruff check src/flab2bp/layout/freeform.py tests/layout/test_freeform.py
uv run mypy src/flab2bp/layout/freeform.py
uv run pytest -q
git add src/flab2bp/layout/freeform.py tests/layout/test_freeform.py
git commit -m "feat(layout): view a freeform pack as a placement the destroy operators can read"
```

---

### Task 13: Freeform sweep integration

**Files:**
- Modify: `src/flab2bp/layout/freeform.py` — `FreeformLayout.lay_out` (`:15567-15888`, construct the session), `_sweep` (`:15891-16981`): the state block near `dearest_candidate_s` (`:16118`), the candidate loop head (`:16184-16185`), the `_pack` call site (`:16350-16400`), the `if failed:` block (`:16669-16755`), the acceptance path (`:16948-16980`), the return
- Modify: `src/flab2bp/layout/base.py:198` — no new keys (Tasks 5 and 11 declared them all); confirm with `grep -n 'alns_' src/flab2bp/layout/base.py`
- Test: `tests/layout/test_freeform.py`

**Interfaces:**
- Consumes: `_room_for_another` (`:16984`), `_window_candidate_seconds`, `_decoded_from_pack`, `_pack_relation_problem`, `_pack_relation_pair` (Task 12), `_pack_window` (Task 10), `finalize.band_target_width` (Task 6), `OperatorSession`/`OperatorContext`/`OperatorOutcome`/`destroy_strips`/`metrics_from_evaluation`/`remaining_fraction_bucket`/`reward_vector`/`operator_tally` (Tasks 3, 6), `PackAttempt` (`:13607`).
- Produces: `FreeformLayout._sweep(..., session=...)`; `window_packs`, `window_queue`, `window_choices`, `solved_windows` sweep state; the freeform placement stats `alns_choices`, `alns_applied`, `alns_evaluations`, `alns_routing_seconds`, `alns_operators`, `alns_window_solves`, `alns_window_accepted`, `alns_window_seconds`, `alns_encode_errors`, `alns_skipped_no_goods`.

- [ ] **Step 1: Write the failing tests**

```python
def test_the_sweep_repairs_a_window_when_a_full_resolve_is_unaffordable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed pack with no clock for a full re-solve still gets a bounded repair.

    `_room_for_another` charges the DEAREST COMPLETED candidate for a full
    retry; a window costs `C_WINDOW_SECONDS` plus the measured post-pack work,
    which is a different and much smaller charge.  When only the second one is
    affordable, the sweep must take it, and it must not call `_pack` again for
    that candidate.
    """
    spec = plastic_spec()
    window_calls: list[frozenset[int]] = []
    pack_calls: list[tuple[int, int]] = []
    original_window = freeform._pack_window
    original_pack = freeform._pack

    def counting_window(*args: object, **kwargs: object) -> object:
        window = kwargs["window"]
        assert isinstance(window, frozenset)
        window_calls.append(window)
        return original_window(*args, **kwargs)  # type: ignore[arg-type]

    def counting_pack(*args: object, **kwargs: object) -> object:
        pack_calls.append((int(str(kwargs["height"])), int(str(kwargs.get("arrangement", 0)))))
        return original_pack(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(freeform, "_pack_window", counting_window)
    monkeypatch.setattr(freeform, "_pack", counting_pack)
    # A clock that always says "no room for a full retry, room for a window":
    # `projection_retry_affordable()` charges `dearest_candidate_s`, the window
    # charges `C_WINDOW_SECONDS` plus the post-pack remainder.
    monkeypatch.setattr(
        freeform,
        "_room_for_another",
        lambda deadline, soft, candidate_s: candidate_s <= freeform.C_WINDOW_SECONDS + 0.5,
    )
    layout = freeform.FreeformLayout(band_policy=BandPolicy.parse("any"), workers=1)
    try:
        layout.lay_out(spec, time_budget_s=10.0)
    except NoValidLayout:
        pass
    # Every window solve names at least one strip, and no candidate is packed twice.
    assert all(window for window in window_calls)
    assert len(pack_calls) == len(set(pack_calls))


def test_the_sweep_never_solves_the_same_window_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = plastic_spec()
    seen: list[tuple[int, int, frozenset[int]]] = []
    original_window = freeform._pack_window

    def recording(*args: object, **kwargs: object) -> object:
        window = kwargs["window"]
        height = kwargs["height"]
        arrangement = kwargs.get("arrangement", 0)
        assert isinstance(window, frozenset)
        key = (int(str(height)), int(str(arrangement)), window)
        assert key not in seen, f"window {key} solved twice"
        seen.append(key)
        return original_window(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(freeform, "_pack_window", recording)
    monkeypatch.setattr(
        freeform,
        "_room_for_another",
        lambda deadline, soft, candidate_s: candidate_s <= freeform.C_WINDOW_SECONDS + 0.5,
    )
    layout = freeform.FreeformLayout(band_policy=BandPolicy.parse("any"), workers=1)
    try:
        layout.lay_out(spec, time_budget_s=10.0)
    except NoValidLayout:
        pass


def test_the_sweep_never_windows_when_neither_clock_allows_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = plastic_spec()
    calls: list[object] = []
    monkeypatch.setattr(
        freeform,
        "_pack_window",
        lambda *args, **kwargs: calls.append(kwargs) or None,
    )
    monkeypatch.setattr(freeform, "_room_for_another", lambda *args, **kwargs: False)
    layout = freeform.FreeformLayout(band_policy=BandPolicy.parse("any"), workers=1)
    try:
        layout.lay_out(spec, time_budget_s=10.0)
    except NoValidLayout:
        pass
    assert calls == []


@pytest.mark.slow
def test_freeform_placement_stats_carry_the_operator_telemetry() -> None:
    spec = plastic_spec()
    placement = freeform.FreeformLayout(band_policy=BandPolicy.parse("any")).lay_out(
        spec, time_budget_s=15.0
    )
    for key in (
        "alns_choices",
        "alns_applied",
        "alns_evaluations",
        "alns_routing_seconds",
        "alns_window_solves",
        "alns_window_accepted",
        "alns_window_seconds",
        "alns_encode_errors",
        "alns_skipped_no_goods",
    ):
        assert isinstance(placement.stats[key], float), key
    assert isinstance(placement.stats["alns_operators"], str)
    # Sequence-pair only: freeform never re-encodes a compaction.
    assert "alns_encode_inexact" not in placement.stats
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/layout/test_freeform.py -q -k "repairs_a_window or same_window_twice or never_windows or freeform_placement_stats"`
Expected: FAIL — `_pack_window` is never called (`assert calls == []` passes vacuously but the stats test fails with `KeyError: 'alns_choices'`, and `window_calls` stays empty so the first test's assertions are vacuous). Confirm the stats test is the failing one; the three sweep tests become meaningful only after Step 5.

- [ ] **Step 3: Construct the session in `lay_out` and thread it into `_sweep`**

In `FreeformLayout.lay_out`, before the `budgets` loop that calls `self._sweep(...)`:

```python
        # One session for the whole call, so credit survives a strip replan and
        # a second arrangement pass.  It dies with this call: nothing here is
        # process-wide.
        alns_session = OperatorSession()
```

and pass `session=alns_session` to `self._sweep(...)`. Add the matching keyword-only parameter to
`_sweep`'s signature:

```python
        session: OperatorSession,
```

Import `OperatorChoice`, `OperatorContext`, `OperatorMetrics`, `OperatorOutcome`,
`OperatorSession`, `REWARD_RANKS`, `destroy_strips`, `metrics_from_evaluation`, `operator_tally`,
`remaining_fraction_bucket` and `reward_vector` from `flab2bp.layout.sequence_alns`, and add
`GapProfile` to the `flab2bp.layout.sequence_pair` import Task 12 opened, all at the top of
`freeform.py`. `REWARD_RANKS` is needed for the `(0.0,) * REWARD_RANKS` unapplied credits and
`GapProfile` for `GapProfile.zero(len(strips))` in Step 6.

- [ ] **Step 4: Add the sweep state**

Beside `dearest_candidate_s = 0.0` (`:16118`):

```python
        #: The dearest `_pack` solve this sweep has completed, so a windowed
        #: retry can be charged for what it actually replaces.
        dearest_pack_s = 0.0
        #: Window repairs waiting to be evaluated, and the queue that drains
        #: them.  `candidate_packs` is iterated by index and already mutated in
        #: four places; a separate queue adds no fifth mutation.
        window_packs: dict[tuple[int, int], _Pack] = {}
        window_queue: list[tuple[int, int]] = []
        #: The choice and the pre-repair metrics that produced each queued pack,
        #: so credit lands on the choice that earned it rather than on whatever
        #: the selector happened to pick last.
        window_choices: dict[tuple[int, int], tuple[OperatorChoice, OperatorMetrics]] = {}
        #: Asked-and-answered windows, so the same question is never put to
        #: CP-SAT twice inside one `lay_out`.
        solved_windows: set[tuple[int, int, frozenset[int]]] = set()
        window_solves = 0
        window_accepted = 0
        window_seconds = 0.0
        window_skipped_no_goods = 0
        window_encode_errors = 0
        evaluations = 0
```

- [ ] **Step 5: Drain the queue at the loop head and honour a stored pack**

The loop head is `while candidate_index < len(candidate_packs):` followed by
`height, arrangement, projection_retry = candidate_packs[candidate_index]` (`:16184-16185`).
Replace those two lines with:

```python
        while window_queue or candidate_index < len(candidate_packs):
            queued = window_queue.pop(0) if window_queue else None
            if queued is not None:
                height, arrangement = queued
                projection_retry = False
            else:
                height, arrangement, projection_retry = candidate_packs[candidate_index]
```

and, at every place the loop currently advances `candidate_index`, advance it **only when `queued
is None`**. Find them with `grep -n 'candidate_index' src/flab2bp/layout/freeform.py` and guard each
increment; a queued entry has already been removed from `window_queue` by the `pop`, so it must not
also consume a `candidate_packs` slot.

At the `_pack` call site (`:16369-16389`), record the pack cost and honour a stored pack:

```python
            pending_pack = window_packs.pop((height, arrangement), None)
            if pending_pack is not None:
                pack = pending_pack
            else:
                pack_started = time.monotonic()
                pack = _pack(...)          # the existing call, unchanged
                dearest_pack_s = max(dearest_pack_s, time.monotonic() - pack_started)
```

- [ ] **Step 6: Launch a window when the full retry is unaffordable**

**The trigger, stated against the code.** `freeform.py:16700-16752` admits a retry through three
gates, all of which must pass:

```python
promote_retry = arrangement == 0 and (learned or feedback_retry)   # :16700
if promote_retry:
    try:
        next_index = candidate_packs.index(next_candidate, candidate_index)  # :16705
    except ValueError:
        pass                         # no slot: nothing to promote into
    else:
        if feedback_retry or _room_for_another(deadline, soft, retry_cost):   # :16719
            ... admit the retry ...
```

A window launches **exactly when a retry was promoted and its slot exists but the retry was not
admitted** — that is, `promote_retry` and the slot lookup succeeded and `not feedback_retry` and
`not _room_for_another(deadline, soft, retry_cost)`. It never launches alongside an admitted retry
(the retry is the better repair and already re-solves the whole pack), and never when there was no
retry to promote in the first place (no `learned` evidence and no `feedback_retry` means the sweep
has nothing to aim a window at either).

Make that testable by recording the two facts the existing block already knows. Before
`if promote_retry:` add:

```python
                retry_slot_found = False
                retry_admitted = False
```

set `retry_slot_found = True` as the first statement of the `else:` clause after the
`candidate_packs.index(...)` lookup, and set `retry_admitted = True` inside the
`if feedback_retry or _room_for_another(...)` body beside the existing
`candidate_packs.pop`/`insert` pair.

Then, in the `if failed:` block, replace the bare `continue` at `:16755` with the block below.
`attempt`, `pack`, `strips`, `height`, `arrangement`, `net_candidates`, `projection_envelope`,
`feedback_by_height`, `projection_no_goods`, `exact_pack_no_goods` and `direct_relation_no_goods`
are all in scope there; confirm each with `grep -n` before writing.

```python
                if promote_retry and retry_slot_found and not retry_admitted:
                    window_cost = _window_candidate_seconds(
                        dearest_candidate_s=dearest_candidate_s,
                        dearest_pack_s=dearest_pack_s,
                    )
                    if (
                        (height, arrangement) not in window_packs
                        and (height, arrangement) not in window_choices
                        and _room_for_another(deadline, soft, window_cost)
                    ):
                        target = finalize.band_target_width(
                            projection_envelope, height=height, width=pack.width
                        )
                        relation_problem = _pack_relation_problem(pack, strips, height)
                        relation_decoded = _decoded_from_pack(pack, strips, height)
                        feedback_state_now = feedback_by_height.get(
                            height, FeedbackState.empty((pack.width, height))
                        )
                        before_metrics = metrics_from_evaluation(
                            attempt.routing,
                            relation_decoded,
                            feedback_state_now,
                            outline_height=height,
                            band_target_width=target,
                            validator_clean=False,
                        )
                        choice = session.select(
                            OperatorContext(
                                strip_count=len(strips),
                                stagnation=0,
                                remaining_fraction=remaining_fraction_bucket(
                                    soft - time.monotonic(), max(time_budget_s, 1e-6)
                                ),
                            )
                        )
                        try:
                            window = destroy_strips(
                                choice.destroy,
                                scale=choice.scale,
                                result=attempt.routing,
                                pair=_pack_relation_pair(pack, strips, height),
                                gaps=GapProfile.zero(len(strips)),
                                problem=relation_problem,
                                decoded=relation_decoded,
                                band_target_width=target,
                            )
                        except ValueError:
                            # The encoder refused this pack.  Impossible for a
                            # `no_overlap_2d` result, so it is a bug detector.
                            window_encode_errors += 1
                            window = frozenset()
                        key = (height, arrangement, window)
                        if not window or len(window) >= len(strips) or key in solved_windows:
                            session.observe(choice, (0.0,) * REWARD_RANKS, applied=False)
                        else:
                            solved_windows.add(key)
                            window_solves += 1
                            window_started = time.monotonic()
                            repaired = _pack_window(
                                strips,
                                height=height,
                                width_bound=pack.width,
                                direct_candidates=net_candidates,
                                window=window,
                                fixed_at={
                                    index: origin
                                    for index, origin in pack.at.items()
                                    if index not in window
                                },
                                seed=pack,
                                width_target=target,
                                arrangement=arrangement,
                                projection_no_goods=tuple(projection_no_goods),
                                exact_pack_no_goods=exact_pack_no_goods,
                                direct_relation_no_goods=tuple(direct_relation_no_goods),
                                feedback=feedback_by_height.get(height),
                                on_skipped=_count_window_skips,
                            )
                            window_seconds += time.monotonic() - window_started
                            if repaired is None or repaired.at == pack.at:
                                session.observe(
                                    choice, (0.0,) * REWARD_RANKS, applied=False
                                )
                            else:
                                window_accepted += 1
                                window_packs[height, arrangement] = repaired
                                window_choices[height, arrangement] = (
                                    choice,
                                    before_metrics,
                                )
                                window_queue.append((height, arrangement))
                continue
```

`_count_window_skips` is the accumulator this block passes to `_pack_window`; define it beside the
state block from Step 4:

```python
        def _count_window_skips(count: int) -> None:
            nonlocal window_skipped_no_goods
            window_skipped_no_goods += count
```

- [ ] **Step 7: Credit the choice when its candidate finishes**

Every path that finishes evaluating a candidate must settle any choice stored for it. Add one
helper beside the state block:

```python
        def settle_window_credit(
            height: int,
            arrangement: int,
            *,
            after: OperatorMetrics | None,
            routing_seconds: float,
        ) -> None:
            """Credit the choice that produced this candidate, if there was one.

            ``after=None`` means the candidate was never evaluated -- the
            deadline arrived first -- which is a cost with no reward, so it is
            credited unapplied.
            """
            stored = window_choices.pop((height, arrangement), None)
            if stored is None:
                return
            choice, before = stored
            if after is None:
                session.observe(choice, (0.0,) * REWARD_RANKS, applied=False)
                return
            session.observe(
                choice,
                reward_vector(
                    OperatorOutcome(
                        choice=choice, before=before, after=after, applied=True
                    )
                ),
                applied=True,
                routing_seconds=routing_seconds,
            )
```

Call it in three places:

1. In the `if failed:` block, immediately before the window-launch block added in Step 6, with the
   *current* attempt's metrics — a queued pack that fails again settles its own credit:

```python
                settle_window_credit(
                    height,
                    arrangement,
                    after=metrics_from_evaluation(
                        attempt.routing,
                        _decoded_from_pack(pack, strips, height),
                        feedback_by_height.get(
                            height, FeedbackState.empty((pack.width, height))
                        ),
                        outline_height=height,
                        band_target_width=finalize.band_target_width(
                            projection_envelope, height=height, width=pack.width
                        ),
                        validator_clean=False,
                    ),
                    routing_seconds=route_seconds,
                )
```

   where `route_seconds` is the measured routing span of this attempt. Find the local the sweep
   already computes for it with `grep -n 'route_all_s\|route_started\|routing_seconds' src/flab2bp/layout/freeform.py`; if none exists, add `route_started = time.monotonic()` immediately before the `_build(...)` call at `:16501` and `route_seconds = time.monotonic() - route_started` immediately after, and say so in the commit message.

2. At the acceptance path (`:16948-16961`), after `report = validate.certify(...)`:

```python
            settle_window_credit(
                height,
                arrangement,
                after=metrics_from_evaluation(
                    result.routing,
                    _decoded_from_pack(pack, strips, height),
                    feedback_by_height.get(
                        height, FeedbackState.empty((pack.width, height))
                    ),
                    outline_height=height,
                    band_target_width=finalize.band_target_width(
                        projection_envelope, height=height, width=pack.width
                    ),
                    validator_clean=not report.errors,
                ),
                routing_seconds=route_seconds,
            )
```

3. After the candidate loop exits, for anything still outstanding:

```python
        for (height, arrangement) in list(window_choices):
            settle_window_credit(height, arrangement, after=None, routing_seconds=0.0)
```

Count evaluations where the sweep calls `_build(..., route=True, ...)` (`:16501`):
`evaluations += 1`.

- [ ] **Step 8: Stamp the stats at the end of `_sweep`**

`stats["route_backend"]` is set in `lay_out` (`freeform.py:15758`), where none of `_sweep`'s locals
exist. These counters therefore go at the **end of `_sweep`**, immediately before its final
`return best` (`:16981`), guarded because `best` may be `None`:

```python
        if best is not None:
            best.stats["alns_choices"] = float(len(session.choices))
            best.stats["alns_applied"] = float(session.applied)
            best.stats["alns_evaluations"] = float(evaluations)
            best.stats["alns_routing_seconds"] = session.routing_seconds
            best.stats["alns_operators"] = operator_tally(session)
            best.stats["alns_window_solves"] = float(window_solves)
            best.stats["alns_window_accepted"] = float(window_accepted)
            best.stats["alns_window_seconds"] = window_seconds
            best.stats["alns_encode_errors"] = float(window_encode_errors)
            best.stats["alns_skipped_no_goods"] = float(window_skipped_no_goods)
        return best
```

`alns_encode_inexact` is **not** stamped on the freeform path. Freeform's only encoder call is
`_pack_relation_pair`, which uses the pair and discards the `exact` flag, so there is no re-encode
whose inexactness would mean anything here. The gate's freeform column omits it; it is a
sequence-pair number.

- [ ] **Step 9: Run the tests**

```bash
uv run pytest tests/layout/test_freeform.py -q
uv run pytest -q
```

Expected: all pass, including the pre-existing direct-insertion and no-good tests.

- [ ] **Step 10: Measure gate 2**

```bash
uv run python scripts/audit.py --budget 30 --jobs 4 --strategy freeform \
  --only universe-matrix --json /tmp/phase-c-task13-ff.jsonl | tail -6
uv run python scripts/audit.py --budget 30 --jobs 4 --strategy sequence-pair \
  --only universe-matrix --json /tmp/phase-c-task13-sp.jsonl | tail -6
for arm in ff sp; do
  uv run python scripts/audit_compare.py \
    docs/superpowers/evidence/2026-09-02-phase-c-alns/baseline-budget30-round1.jsonl \
    "/tmp/phase-c-task13-${arm}.jsonl" --regressions-only
done
jq -r '[.strategy,.spec_label,.status,.seconds,.area,.detail] | @tsv' \
  /tmp/phase-c-task13-ff.jsonl /tmp/phase-c-task13-sp.jsonl
uv run python -c "
from flab2bp.bench.corpus import URL_CORPUS
from flab2bp.lab.data import load_vendored
from flab2bp.lab.url import parse_url
from flab2bp.layout.band_policy import BandPolicy
from flab2bp.layout.freeform import FreeformLayout
from flab2bp.rates.candidates import DEFAULT_CANDIDATE_POLICIES, build_candidates
entry = next(c for c in URL_CORPUS if c.url_id == 'universe-matrix')
built = build_candidates(load_vendored(), parse_url(entry.url), candidate_policies=DEFAULT_CANDIDATE_POLICIES)
spec = next(c.spec for c in built.candidates if c.label == 'no-proliferator')
p = FreeformLayout(band_policy=BandPolicy.parse('any')).lay_out(spec, time_budget_s=30.0)
print({k: v for k, v in p.stats.items() if k.startswith('alns')})
"
```

Gate 2 passes when `universe-matrix/no-proliferator` is CLEAN under both strategies and neither
`--regressions-only` run reports a cell. Record every row, both `alns_*` dicts (this task's and
Task 11's), and the mean window second (`alns_window_seconds / alns_window_solves`) — if that mean
exceeds `C_WINDOW_SECONDS`, the wall limit is doing the work under contention: lower
`C_WINDOW_DETERMINISTIC_WORK` and re-measure, and record both values.

- [ ] **Step 11: Lint, type-check, commit**

```bash
uv run ruff check src/flab2bp/layout/freeform.py tests/layout/test_freeform.py
uv run mypy src/flab2bp/layout/freeform.py
uv run pytest -q
git add src/flab2bp/layout/freeform.py tests/layout/test_freeform.py
git commit -m "feat(layout): repair an unaffordable freeform retry with a CP-SAT window"
```

---

### Task 14: Three-round corpus gate and evidence

**Files:**
- Create: `docs/superpowers/evidence/2026-09-02-phase-c-alns/candidate-budget30-round{1,2,3}.jsonl`
- Create: `docs/superpowers/evidence/2026-09-02-phase-c-alns/compare-round{1,2,3}.txt`
- Create: `docs/superpowers/evidence/2026-09-02-phase-c-alns/gate.md`

**Interfaces:**
- Consumes: `scripts/audit.py --budget 30 --jobs 16 --json PATH`; `scripts/audit_compare.py BASELINE CANDIDATE --noise-area 0.013 --p95-seconds 30 --regressions-only --require-clean CELL`; the baselines from Task 1; the `alns_*` placement stats from Tasks 5, 11 and 13.
- Produces: the committed gate record. Nothing in this plan consumes it; Phase D's gate uses these three round files as its baseline.

- [ ] **Step 1: Confirm the tree is green and clean before measuring**

```bash
uv run pytest -q
uv run ruff check .
uv run mypy 2>&1 | tail -3
git status --porcelain
git log --oneline -1
```

Expected: tests pass, ruff clean, mypy reporting the locked 176 pre-existing errors and no more, a
clean tree. Record the HEAD hash for `gate.md`.

- [ ] **Step 2: Run three interleaved candidate rounds on an idle box**

```bash
for round in 1 2 3; do
  uv run python scripts/audit.py --budget 30 --jobs 16 \
    --json "docs/superpowers/evidence/2026-09-02-phase-c-alns/candidate-budget30-round${round}.jsonl" \
    | tail -6
done
wc -l docs/superpowers/evidence/2026-09-02-phase-c-alns/candidate-budget30-round*.jsonl
```

Expected: 72 lines per file.

- [ ] **Step 3: Compare each round against its baseline with the machine verdict**

```bash
cd docs/superpowers/evidence/2026-09-02-phase-c-alns
for round in 1 2 3; do
  uv run python ../../../../scripts/audit_compare.py \
    "baseline-budget30-round${round}.jsonl" "candidate-budget30-round${round}.jsonl" \
    --noise-area 0.013 --p95-seconds 30 --regressions-only \
    --require-clean "sequence-pair/graphene/output-products" \
    --require-clean "sequence-pair/universe-matrix/no-proliferator" \
    --require-clean "freeform/universe-matrix/no-proliferator" \
    | tee "compare-round${round}.txt"
done
cd -
```

Check `scripts/audit_compare.py --help` for `--require-clean`'s exact cell syntax and use it; the
three-part `strategy/url_id/spec_label` form above is the guess. `--regressions-only` restricts the
failure list to cells that were CLEAN in the baseline and are not CLEAN now, so a pre-existing
refusal does not mask a real regression.

Expected: three files, each ending `PASS`. A `FAIL` names either a regression or an unmet
`--require-clean`; both are gate failures.

- [ ] **Step 4: Record the gate-2 absolutes**

```bash
cd docs/superpowers/evidence/2026-09-02-phase-c-alns
for round in 1 2 3; do
  echo "== round ${round} =="
  jq -r 'select((.url_id=="graphene" and .spec_label=="output-products")
                or (.url_id=="universe-matrix"))
         | [.strategy,.url_id,.spec_label,.status,.seconds,.area] | @tsv' \
    "candidate-budget30-round${round}.jsonl"
  jq -s 'map(.seconds) | sort | .[(length*0.95|ceil)-1]' \
    "candidate-budget30-round${round}.jsonl"
  jq -r 'select(.status!="CLEAN") | [.strategy,.url_id,.spec_label,.status,.detail] | @tsv' \
    "candidate-budget30-round${round}.jsonl"
done
cd -
```

Then the per-cell telemetry, once per strategy for each of the four target cells:

```bash
uv run python - <<'PY'
from flab2bp.bench.corpus import URL_CORPUS
from flab2bp.lab.data import load_vendored
from flab2bp.lab.url import parse_url
from flab2bp.layout.band_policy import BandPolicy
from flab2bp.layout.freeform import FreeformLayout
from flab2bp.layout.sequence_solver import SequencePairLayout
from flab2bp.rates.candidates import DEFAULT_CANDIDATE_POLICIES, build_candidates

CELLS = [
    ("graphene", "output-products", "sequence-pair"),
    ("universe-matrix", "no-proliferator", "sequence-pair"),
    ("universe-matrix", "all-products", "sequence-pair"),
    ("universe-matrix", "no-proliferator", "freeform"),
]
policy = BandPolicy.parse("any")
for url_id, label, strategy in CELLS:
    entry = next(c for c in URL_CORPUS if c.url_id == url_id)
    built = build_candidates(
        load_vendored(), parse_url(entry.url), candidate_policies=DEFAULT_CANDIDATE_POLICIES
    )
    spec = next(c.spec for c in built.candidates if c.label == label)
    layout = (
        SequencePairLayout(band_policy=policy)
        if strategy == "sequence-pair"
        else FreeformLayout(band_policy=policy)
    )
    try:
        placement = layout.lay_out(spec, time_budget_s=30.0)
    except Exception as exc:  # noqa: BLE001 - reporting, not control flow
        print(url_id, label, strategy, "REFUSED", exc)
        continue
    stats = {
        key: value
        for key, value in placement.stats.items()
        if key.startswith("alns") or key == "feasibility_restart_batches"
    }
    print(url_id, label, strategy, stats)
PY
```

`flab2bp.lab.data.load_vendored` and `flab2bp.lab.url.parse_url` are the paths
`tests/layout/test_freeform.py:215-216` uses; `built.candidates`/`candidate.label`/`candidate.spec`
mirror that fixture. Adjust if it does something different.

Gate criteria, all three rounds:
- `graphene/output-products` sequence-pair CLEAN;
- `universe-matrix/no-proliferator` CLEAN under both `freeform` and `sequence-pair`;
- `compare-round<N>.txt` ends `PASS` (no regression, every `--require-clean` met);
- zero `INVALID`, zero `CRASH`;
- the printed p95 at or under 30;
- each `compare-round<N>.txt`'s `area ratio` at or under `1.013`.

- [ ] **Step 5: Write the gate record**

```markdown
<!-- docs/superpowers/evidence/2026-09-02-phase-c-alns/gate.md -->
# Phase C gate

Commit `<HASH>` (`<SUBJECT>`), idle box, `uv run python scripts/audit.py --budget 30 --jobs 16`,
three interleaved rounds against `baseline-budget30-round{1,2,3}.jsonl` from `<BASELINE HASH>`.

## Corpus

| Round | CLEAN | REFUSED | INVALID | CRASH | p95 wall (s) | area ratio | compare verdict |
|---|---:|---:|---:|---:|---:|---:|---|
| 1 | <N> | <N> | <N> | <N> | <N> | <N> | <PASS/FAIL> |
| 2 | <N> | <N> | <N> | <N> | <N> | <N> | <PASS/FAIL> |
| 3 | <N> | <N> | <N> | <N> | <N> | <N> | <PASS/FAIL> |

Baseline for the same three rounds: <N>/<N>/<N> CLEAN.

## Gate 1 -- feasibility continuation

`graphene/output-products` under sequence-pair: <STATUS> in every round.
`feasibility_restart_batches` on that cell: <N>.

## Gate 2 -- window repair (absolutes, not deltas)

The audit JSONL carries no per-candidate column, so these come from
`PlacementStats["alns_evaluations"]` on single-cell 30 s runs, alongside status, wall and area from
the audit rows.

| Cell | Strategy | Baseline status | Candidate status | Wall (s) | Area | alns_evaluations | alns_window_solves | alns_window_accepted | alns_window_seconds | alns_encode_errors | alns_skipped_no_goods | alns_encode_inexact |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| graphene/output-products | sequence-pair | <STATUS> | <STATUS> | <N> | <N> | <N> | <N> | <N> | <N> | <N> | <N> | <N> |
| universe-matrix/no-proliferator | sequence-pair | <STATUS> | <STATUS> | <N> | <N> | <N> | <N> | <N> | <N> | <N> | <N> | <N> |
| universe-matrix/all-products | sequence-pair | <STATUS> | <STATUS> | <N> | <N> | <N> | <N> | <N> | <N> | <N> | <N> | <N> |
| universe-matrix/no-proliferator | freeform | <STATUS> | <STATUS> | <N> | <N> | <N> | <N> | <N> | <N> | <N> | <N> | n/a |

`alns_encode_inexact` is sequence-pair only: freeform's single encoder call keeps the pair and
discards the flag, so the freeform row reads `n/a` rather than `0`.

Mean window solve: `alns_window_seconds / alns_window_solves` = <N> s against
`C_WINDOW_SECONDS = 1.0`. <If above 1.0: the wall limit is ending window solves under contention;
record whether `C_WINDOW_DETERMINISTIC_WORK` was lowered and to what.>

Operator usage (`alns_operators`), per cell: <VALUES>.

## Gate 3 -- corpus

<PASS or FAIL, with every cell that changed status in either direction, and its detail string.>

## Cells still refusing

| Cell | Strategy | Detail | Owner |
|---|---|---|---|
| <CELL> | <STRATEGY> | <DETAIL> | <phase B / phase D / open> |

## Follow-up operators

The shipped portfolio is destroy `{FAILED_ENDPOINTS, BAND_BOUNDARY}` and repair
`{SEQUENCE_REINSERT, LOCAL_EXACT_PACK}`.  If any refusal above names a mechanism one of the
follow-up operators covers -- blocker component, congested cut, cargo relation, search stagnation,
routing regret -- record which, so the next phase adds that operator under the spec's section 4
rule rather than widening an existing one.
```

Fill every `<...>` from the run output.

- [ ] **Step 6: Commit the evidence**

```bash
git add docs/superpowers/evidence/2026-09-02-phase-c-alns
git commit -m "bench: record the phase C corpus gate at 30s over three rounds"
```

- [ ] **Step 7: Report**

State, in the hand-off: the three CLEAN counts against the three baseline counts; whether each of
the three gates passed; every cell whose status changed in either direction with its detail string;
the p95, area ratio and compare verdict per round; the gate-2 absolutes table; the mean window
second and whether `C_WINDOW_DETERMINISTIC_WORK` was changed; and any follow-up operator a refusal
now names. A failed gate is reported with its numbers, not tuned around: the spec's rule is that a
step whose gate fails is reverted.
