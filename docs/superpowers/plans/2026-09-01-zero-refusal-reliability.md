# Zero-Refusal Solver Reliability Implementation Plan

> **Required sub-skill:** Use `executing-plans` to implement this plan task-by-task. Use `test-driven-development` for every behavioral change and `verification-before-completion` before each promotion gate.

**Goal:** Eliminate observed valid-input refusals without permitting invalid blueprints, then reduce the wall-clock and CPU cost of that reliability through deterministic classical ALNS before considering learned guidance.

**Architecture:** Keep exact route validation as the only success authority. First remove artificial SequencePair schedule exhaustion and add repeatable production-concurrency reliability measurement. Then expose existing island diversification, add feedback-directed adaptive large-neighborhood search behind a disabled-by-default configuration, and admit only proof-scoped packing/routing cuts. Treat deterministic fallback and learned operator selection as gated experiments: neither reaches the production path unless it beats the explicit corpus, validity, determinism, wall-time, and CPU gates in the linked design.

**Tech Stack:** Python 3.14, pytest, Ruff, mypy, TypeScript, Bun, Vitest, React, Pydantic, existing SequencePair annealing/router stack.

**Spec:** `docs/superpowers/specs/2026-09-01-zero-refusal-reliability-design.md`

## Global Constraints

- Preserve the output contract: only layouts accepted by `layout.validate.validate(...).ok` are successes.
- Preserve safe refusal: a missed deadline or exhausted search returns no blueprint, never a partial or invalid one.
- Keep `SequenceSolver.search(max_stages=...)` as a strict bounded-search API for tests, audits, and controlled experiments.
- Derive every new seed from stable integer inputs. Never use process order, wall time, Python hash randomization, or completion order as seed material.
- Account for both wall time and aggregate CPU time. Faster wall time obtained only by consuming proportionally more cores does not qualify as a solver improvement.
- Change the default budget from 15 seconds to 30 seconds only after the ten-repeat, production-concurrency promotion gate passes.
- Keep `best` and web islands at one until the equal-CPU island gate passes. Preserve the existing explicit SequencePair CLI auto-island behavior.
- Keep classical ALNS disabled by default until its paired gate passes.
- Do not add a model runtime or model artifact to the production dependency graph during the learned-guidance experiments.
- Do not modify the pre-existing user changes in `src/flab2bp/layout/validate.py` or `tests/layout/test_validate.py`.
- Before modifying an exported symbol, use LSP references and migrate every callsite in the same commit.
- Run focused tests after each red/green cycle. Run project-wide verification only in Task 17.

---

## Phase A — Make Reliability Measurable

### Task 1: Add repeatable audit controls and structured outcomes

**Files:**
- Modify: `scripts/audit.py`
- Modify: `tests/scripts/test_audit.py`

- [ ] **Write a failing parser test for repeats and Sequence islands**

Add tests asserting these command-line contracts:

```python
def test_parse_args_accepts_repeats_and_sequence_islands() -> None:
    args = audit._parse_args(
        ["--strategy", "both", "--repeats", "10", "--sequence-islands", "4"]
    )
    assert args.repeats == 10
    assert args.sequence_islands == 4


def test_parse_args_rejects_non_positive_repeats() -> None:
    with pytest.raises(SystemExit):
        audit._parse_args(["--repeats", "0"])
```

- [ ] **Run the parser tests and confirm the red failure**

Run:

```bash
uv run pytest tests/scripts/test_audit.py -k 'repeats or sequence_islands' -q
```

Expected: failure because the flags do not exist.

- [ ] **Extract argument parsing and add validated audit flags**

Extract `_parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace`, call it from `main`, and add:

```python
parser.add_argument("--repeats", type=_positive_int, default=1)
parser.add_argument("--sequence-islands", type=_positive_int, default=1)
```

Pass `sequence_islands` only to `SequencePairLayout`; Freeform construction must remain unchanged. Correct the existing audit help text so it states the actual default of one island.

- [ ] **Write a failing test for stable repeated case identity**

Require every record to expose the original case identity and repeat ordinal without changing the original corpus key:

```python
assert records[0]["case_id"] == records[1]["case_id"]
assert [record["repeat"] for record in records] == [0, 1]
```

- [ ] **Implement repeat expansion before worker submission**

Build work items in deterministic corpus order:

```python
work = [
    AuditWork(case=case, repeat=repeat)
    for repeat in range(args.repeats)
    for case in selected_cases
]
```

Keep result emission sorted by `(repeat, original_case_index)`, not worker completion order. Include `repeat`, `sequence_islands`, `wall_time_s`, `cpu_time_s`, outcome class, refusal reason, and validation result in each JSONL record.

- [ ] **Measure aggregate worker and child-process CPU**

Around each isolated audit cell, sample `resource.getrusage(RUSAGE_SELF)` and `resource.getrusage(RUSAGE_CHILDREN)` and record the delta of user plus system seconds. Because every audit cell runs in its own worker process, the child delta includes that cell's Sequence islands without mixing concurrent cells.

- [ ] **Run focused audit tests**

Run:

```bash
uv run pytest tests/scripts/test_audit.py -q
```

Expected: all audit tests pass.

- [ ] **Commit the audit controls**

```bash
git add scripts/audit.py tests/scripts/test_audit.py
git commit -m "test: make solver reliability audits repeatable"
```

### Task 2: Add a deterministic audit summarizer with CPU accounting

**Files:**
- Create: `scripts/summarize_audit.py`
- Create: `tests/scripts/test_summarize_audit.py`

- [ ] **Write failing tests for outcome and percentile aggregation**

Use a small JSONL fixture assembled in the test. Require per-strategy and per-case counts for `clean`, `refused`, `invalid`, and `crashed`; p50/p95 wall time; total wall time; and aggregate worker CPU time.

```python
summary = summarize(records)
assert summary["totals"]["clean"] == 2
assert summary["totals"]["refused"] == 1
assert summary["totals"]["invalid"] == 0
assert summary["totals"]["cpu_time_s"] == pytest.approx(7.5)
assert summary["by_case"]["sequence-pair:graphene:output"]["refused"] == 1
```

- [ ] **Run the summarizer tests and confirm the red failure**

Run:

```bash
uv run pytest tests/scripts/test_summarize_audit.py -q
```

Expected: import or symbol failure because the summarizer does not exist.

- [ ] **Implement a typed streaming summarizer**

Define a Pydantic input record and typed aggregate. Read JSONL line-by-line; do not load blueprint payloads or raw logs into memory. Reject missing outcome and timing fields rather than silently assigning zero. Compute p95 with a documented nearest-rank rule so repeated runs are comparable.

- [ ] **Expose machine-readable and terminal output**

Support:

```bash
uv run python scripts/summarize_audit.py run.jsonl --json summary.json
```

Terminal output must include the exact promotion fields: total cells, clean/refused/invalid/crashed, p50/p95/max wall time, total worker CPU, refusal reasons, and failing case IDs.

- [ ] **Run focused summarizer tests and type checks**

Run:

```bash
uv run pytest tests/scripts/test_summarize_audit.py -q
uv run mypy scripts/summarize_audit.py
```

Expected: both commands pass.

- [ ] **Commit the summarizer**

```bash
git add scripts/summarize_audit.py tests/scripts/test_summarize_audit.py
git commit -m "feat: summarize repeated solver reliability audits"
```

---

## Phase B — Remove Artificial SequencePair Exhaustion

### Task 3: Continue implicit SequencePair search with deterministic feasibility restarts

**Files:**
- Modify: `src/flab2bp/layout/sequence_solver.py`
- Modify: `tests/layout/test_sequence_solver.py`

- [ ] **Write a failing test for implicit continuation after the configured schedule**

Construct a fake clock and router where every scheduled restart fails, the first appended restart returns an exact validated layout, and shared budget remains. Assert:

```python
result = solver.search()
assert result.feasibility_restart_batches == 1
assert solver.feasibility_restart_batches == 1
```

The same test must assert the appended restart seed equals:

```python
height_seed = derive_stage_seed(config.seed, height.order)
expected = derive_stage_seed(height_seed, config.restarts_per_height)
```

- [ ] **Write a failing test preserving explicit stage limits**

Use the same fake router but call:

```python
with pytest.raises(NoValidLayout, match="no scheduled stage produced"):
    solver.search(max_stages=scheduled_stage_count)
assert solver.feasibility_restart_batches == 0
```

This protects bounded experiments from silently becoming unbounded.

- [ ] **Run both continuation tests and confirm red failures**

Run:

```bash
uv run pytest tests/layout/test_sequence_solver.py \
  -k 'feasibility_restart or explicit_stage_limit' -q
```

Expected: implicit search refuses at the old fixed schedule.

- [ ] **Extract deterministic restart construction**

Add one private helper which appends a restart to an existing `_HeightState`:

```python
def _append_restart(self, height: _HeightState) -> _RestartState:
    ordinal = len(height.restarts)
    height_seed = derive_stage_seed(self.config.seed, height.order)
    seed = derive_stage_seed(height_seed, ordinal)
    restart = _RestartState(
        restart=ordinal,
        seed=seed,
        anneal=AnnealState.initial(height.problem.size, seed),
    )
    height.restarts.append(restart)
    return restart
```

Use the existing constructor fields exactly; do not duplicate annealing initialization elsewhere.

- [ ] **Replace implicit fixed stage exhaustion with continuation batches**

In `SequenceSolver.search`:

1. Preserve the current computed schedule as `initial_stage_limit`.
2. Preserve `max_stages` as an explicit hard cap when it is not `None`.
3. When implicit search has no incumbent and exhausts eligible restarts, append one restart to every still-admissible height in height order.
4. Increase the dynamic stage limit by `config.stages` for each appended restart and resume the existing scheduler.
5. Increment the continuation-batch counter once per append pass.
6. Stop on an exact incumbent under the existing stability policy, deadline, shared expansion-budget exhaustion, cancellation, or proof-scoped admission exhaustion.

Do not append restarts after an exact incumbent exists. Do not reset `height.feedback`; continuation must retain accumulated routing evidence.

- [ ] **Extend existing termination and observational statistics**

Keep the existing `SequenceSearchResult.termination` field and add:

```python
feasibility_restart_batches: int
```

Expose the same counter as a read-only `SequenceSolver.feasibility_restart_batches` property so refusal tests and audit diagnostics can inspect it. Preserve the existing termination strings (`area-optimal`, `deadline`, `exact-stable`, `cancelled`, `budget`, `candidates`, and `stage-limit`); add `admission` only when proof-scoped cuts eliminate every height. Copy the counter and termination into production placement stats in `_with_observational_stats`. Do not infer either value later from refusal text.

- [ ] **Run the focused Sequence solver tests**

Run:

```bash
uv run pytest tests/layout/test_sequence_solver.py -q
```

Expected: all Sequence solver tests pass, including the bounded-search contract.

- [ ] **Commit implicit continuation**

```bash
git add src/flab2bp/layout/sequence_solver.py tests/layout/test_sequence_solver.py
git commit -m "fix: continue sequence feasibility search until deadline"
```

### Task 4: Verify continuation at the declared Sequence reliability gate

**Files:**
- No production file changes
- Artifacts: `/tmp/sequence-graphene120-after-continuation.jsonl`, `/tmp/sequence-hard20-after-continuation.jsonl`, `/tmp/sequence-full10-after-continuation.jsonl`

- [ ] **Run graphene/output-products three times serially at 120 seconds**

Run:

```bash
PYTHONPATH="$PWD/src" uv run python scripts/audit.py \
  --strategy sequence-pair \
  --only graphene \
  --candidate-policy output-products \
  --repeats 3 \
  --budget 120 \
  --jobs 1 \
  --json /tmp/sequence-graphene120-after-continuation.jsonl
```

Required result: three clean, valid outcomes and no `no scheduled stage produced an exact layout` refusal.

- [ ] **Run every observed hard Sequence cell twenty times serially**

Run the two exact policy/case cells separately so unrelated policies do not hide a miss:

```bash
PYTHONPATH="$PWD/src" uv run python scripts/audit.py \
  --strategy sequence-pair \
  --only quantum-chip \
  --candidate-policy no-proliferator \
  --repeats 20 \
  --budget 120 \
  --jobs 1 \
  --json /tmp/sequence-quantum120x20-after-continuation.jsonl
PYTHONPATH="$PWD/src" uv run python scripts/audit.py \
  --strategy sequence-pair \
  --only graphene \
  --candidate-policy output-products \
  --repeats 20 \
  --budget 120 \
  --jobs 1 \
  --json /tmp/sequence-graphene120x20-after-continuation.jsonl
```

Required result: 40 clean, 0 refused, 0 invalid, 0 crashed.

- [ ] **Run ten complete Sequence corpus repeats at 120 seconds**

Run:

```bash
PYTHONPATH="$PWD/src" uv run python scripts/audit.py \
  --strategy sequence-pair \
  --repeats 10 \
  --budget 120 \
  --jobs 4 \
  --json /tmp/sequence-full10-after-continuation.jsonl
```

Required result: 360 clean, 0 refused, 0 invalid, 0 crashed.

- [ ] **Summarize and record exact outcomes in the design evidence section**

Run:

```bash
uv run python scripts/summarize_audit.py \
  /tmp/sequence-graphene120-after-continuation.jsonl
uv run python scripts/summarize_audit.py \
  /tmp/sequence-quantum120x20-after-continuation.jsonl
uv run python scripts/summarize_audit.py \
  /tmp/sequence-graphene120x20-after-continuation.jsonl
uv run python scripts/summarize_audit.py \
  /tmp/sequence-full10-after-continuation.jsonl
```

Append the commands, revision, outcome counts, p50/p95/max wall time, aggregate CPU time, and every refusal reason to the existing evidence table in the design spec. Do not reinterpret a refusal as success.

- [ ] **Commit only the evidence update**

```bash
git add docs/superpowers/specs/2026-09-01-zero-refusal-reliability-design.md
git commit -m "docs: record sequence continuation evidence"
```

## Phase C — Promote the Smallest Reliable Production Configuration

### Task 5: Expose Sequence islands consistently without changing defaults

**Files:**
- Modify: `src/flab2bp/pipeline.py`
- Modify: `src/flab2bp/cli.py`
- Modify: `src/flab2bp/web/jobs.py`
- Modify: `web/src/api/build.ts`
- Modify: `web/src/ui/BuildPanel.tsx`
- Modify: `tests/test_pipeline.py`
- Modify: `tests/test_pipeline_cli_strategy.py`
- Modify: `tests/web/test_options.py`
- Modify: `tests/web/test_jobs.py`
- Modify: `web/tests/api/build.test.ts`
- Modify: `web/tests/ui/BuildPanel.test.tsx`

- [ ] **Write failing pipeline tests for `best` plus islands**

Require `pipeline.build(strategy="best", sequence_islands=4)` to pass four islands to its Sequence candidate while leaving its Freeform candidate unchanged. Preserve the rejection of islands for `strategy="freeform"` because that setting would have no effect.

- [ ] **Write failing CLI and web request tests**

Require:

```text
--strategy best --sequence-islands 4
```

to be accepted, and require the web API request body to contain:

```json
{"strategy":"best","sequence_islands":4}
```

when the user changes the control. Explicit `sequence-pair` behavior remains unchanged.

- [ ] **Run focused tests and confirm red failures**

Run:

```bash
uv run pytest tests/test_pipeline.py tests/test_pipeline_cli_strategy.py \
  tests/web/test_options.py tests/web/test_jobs.py -k sequence_islands -q
bun --cwd web test tests/api/build.test.ts tests/ui/BuildPanel.test.tsx
```

Expected: `best` rejects or drops the setting and the web type/control is absent.

- [ ] **Thread the existing island parameter through every build boundary**

Keep one public field name across Python and TypeScript: `sequence_islands`. Validate integer range `1..16` in `web.jobs.parse_options`, store it on `web.jobs.Options`, pass it through `run_build` to `pipeline.build`, and serialize it in TypeScript `BuildOptions`. In pipeline `_new_layout`, use it only when constructing `SequencePairLayout`; do not fork `run_sequence_islands` or add a second executor.

- [ ] **Add an advanced web control with default one**

Add a numeric/select control under Sequence settings with values `1, 2, 4, 8, 16`, default `1`. Show it for `best` and `sequence-pair`; hide it for `freeform`. The serialized request must preserve an explicit user selection.

- [ ] **Run focused Python and web tests**

Run:

```bash
uv run pytest tests/test_pipeline.py tests/test_pipeline_cli_strategy.py \
  tests/web/test_options.py tests/web/test_jobs.py -k sequence_islands -q
bun --cwd web test tests/api/build.test.ts tests/ui/BuildPanel.test.tsx
bun --cwd web run typecheck
```

Expected: all commands pass.

- [ ] **Commit consistent island controls**

```bash
git add src/flab2bp/pipeline.py src/flab2bp/cli.py src/flab2bp/web/jobs.py \
  web/src/api/build.ts web/src/ui/BuildPanel.tsx \
  tests/test_pipeline.py tests/test_pipeline_cli_strategy.py \
  tests/web/test_options.py tests/web/test_jobs.py \
  web/tests/api/build.test.ts web/tests/ui/BuildPanel.test.tsx
git commit -m "feat: expose sequence islands across build surfaces"
```

### Task 6: Run paired island experiments at an equal CPU ceiling

**Files:**
- No production file changes
- Artifacts: `/tmp/islands-{1,2,4}-hard.jsonl`

- [ ] **Run all island variants inside the same eight-CPU affinity**

Pin the parent audit process; Sequence island children inherit the affinity. This gives every cell the same 30-second, eight-core ceiling:

```bash
taskset -c 0-7 env PYTHONPATH="$PWD/src" uv run python scripts/audit.py \
  --strategy sequence-pair --repeats 20 --sequence-islands 1 \
  --only quantum-chip,graphene --budget 30 --jobs 1 \
  --json /tmp/islands-1-hard.jsonl
taskset -c 0-7 env PYTHONPATH="$PWD/src" uv run python scripts/audit.py \
  --strategy sequence-pair --repeats 20 --sequence-islands 2 \
  --only quantum-chip,graphene --budget 30 --jobs 1 \
  --json /tmp/islands-2-hard.jsonl
taskset -c 0-7 env PYTHONPATH="$PWD/src" uv run python scripts/audit.py \
  --strategy sequence-pair --repeats 20 --sequence-islands 4 \
  --only quantum-chip,graphene --budget 30 --jobs 1 \
  --json /tmp/islands-4-hard.jsonl
```

- [ ] **Summarize all variants**

Run:

```bash
uv run python scripts/summarize_audit.py /tmp/islands-1-hard.jsonl
uv run python scripts/summarize_audit.py /tmp/islands-2-hard.jsonl
uv run python scripts/summarize_audit.py /tmp/islands-4-hard.jsonl
```

- [ ] **Choose the default by the declared gate**

Promote the smallest island count that has zero invalid outputs and either:

- fewer refusals within the same eight-core wall-time ceiling and no measured aggregate CPU increase; or
- equal refusals with at least 25% lower p95 wall time and no measured aggregate CPU increase.

If no variant qualifies, retain one island for `best` and web. Preserve the explicit SequencePair CLI auto-island policy. This is a completed negative result, not an invitation to weaken the gate.

- [ ] **Record the island decision in the design spec**

Add exact commands, revision, affinity, outcome counts, p95 wall time, aggregate CPU, exact `(area, belt_tiles)` comparisons, and selected default to the design evidence table.

- [ ] **Commit the measured decision**

```bash
git add docs/superpowers/specs/2026-09-01-zero-refusal-reliability-design.md
git commit -m "docs: record sequence island promotion result"
```

### Task 7: Promote the 30-second default only after repeated production-concurrency proof

**Files:**
- Modify after passing gate: `src/flab2bp/pipeline.py`
- Modify after passing gate: `src/flab2bp/cli.py`
- Modify after passing gate: `web/src/api/build.ts`
- Modify after passing gate: `src/flab2bp/web/jobs.py`
- Modify after passing gate: `README.md`
- Modify after passing gate: `tests/test_pipeline.py`
- Modify after passing gate: `tests/test_pipeline_cli_strategy.py`
- Modify after passing gate: `web/tests/api/build.test.ts`
- Modify after passing gate: `web/tests/ui/BuildPanel.test.tsx`
- Modify after passing gate: `tests/web/test_options.py`
- Modify after passing gate: `tests/web/test_jobs.py`

- [ ] **Run ten full-corpus repeats under production concurrency**

Run both strategies, all 72 cells, ten repeats, budget 30, with the same `--jobs` value used in production audit runs:

```bash
PYTHONPATH="$PWD/src" uv run python scripts/audit.py \
  --strategy both --repeats 10 --budget 30 --jobs 4 \
  --json /tmp/full-72x10-budget30.jsonl
uv run python scripts/summarize_audit.py \
  /tmp/full-72x10-budget30.jsonl --json /tmp/full-72x10-budget30-summary.json
```

- [ ] **Apply the reliability gate without exceptions**

The gate is exactly:

```text
720 clean
0 refused
0 invalid
0 crashed
```

If it fails, retain the 15-second default and carry the failing case IDs into Phase D. Do not increase the default merely because a single 30-second run passed.

- [ ] **Write failing default-value tests only if the gate passes**

Assert the default is 30 in pipeline, CLI, and web request serialization, while explicit user values remain authoritative:

```python
assert cli.main(["iron-ingot"]) == 0
assert received["time_budget_s"] == 30.0
assert cli.main(["iron-ingot", "--budget", "47"]) == 0
assert received["time_budget_s"] == 47.0
```

```ts
expect(defaultBuildOptions.budget_s).toBe(30)
expect(serializeBuild({ ...defaultBuildOptions, budget_s: 47 }).budget_s).toBe(47)
```

- [ ] **Change every public default in one cutover if the gate passes**

Change `15` to `30` only at user-facing default boundaries. Do not alter explicit budgets, internal remaining-time calculations, per-stage budgets, or test fixtures that intentionally exercise 15 seconds.

- [ ] **Run focused default tests if changed**

Run:

```bash
uv run pytest tests/test_pipeline.py tests/test_pipeline_cli_strategy.py \
  tests/web/test_options.py tests/web/test_jobs.py -k budget -q
bun --cwd web test tests/api/build.test.ts tests/ui/BuildPanel.test.tsx
bun --cwd web run typecheck
```

- [ ] **Record and commit the decision**

If promoted:

```bash
git add src/flab2bp/pipeline.py src/flab2bp/cli.py src/flab2bp/web/jobs.py \
  web/src/api/build.ts README.md tests/test_pipeline.py \
  tests/test_pipeline_cli_strategy.py tests/web/test_options.py \
  tests/web/test_jobs.py web/tests/api/build.test.ts \
  web/tests/ui/BuildPanel.test.tsx \
  docs/superpowers/specs/2026-09-01-zero-refusal-reliability-design.md
git commit -m "feat: promote proven 30 second solver budget"
```

If not promoted, commit only the evidence update:

```bash
git add docs/superpowers/specs/2026-09-01-zero-refusal-reliability-design.md
git commit -m "docs: record default budget gate failure"
```

---

## Phase D — Add Feedback-Directed Classical ALNS

### Task 8: Define the typed ALNS operator and reward model

**Files:**
- Create: `src/flab2bp/layout/sequence_alns.py`
- Create: `tests/layout/test_sequence_alns.py`

- [ ] **Write failing tests for deterministic operator selection**

Cover cold start, stable tie-breaking, context partitioning, and repeatable selection for a fixed seed:

```python
selector = AdaptiveOperatorSelector(seed=7, exploration=0.6, discount=0.97)
choices = [selector.select(context) for _ in range(6)]
assert choices == expected_cold_start_order
```

The expected order must be a literal list ordered by enum value; it must not depend on set or dict iteration.

- [ ] **Write failing tests for lexicographic outcome ranking**

Assert exact success always outranks non-exact outcomes, then fewer failed nets, band overflow, congestion, exact-layout quality, and route seconds:

```python
assert rank(exact_slow) > rank(non_exact_fast)
assert rank(one_failed_net) > rank(two_failed_nets)
assert rank(lower_overflow) > rank(higher_overflow)
```

- [ ] **Run the ALNS model tests and confirm red failure**

Run:

```bash
uv run pytest tests/layout/test_sequence_alns.py -q
```

Expected: module import failure.

- [ ] **Implement immutable operator contracts**

Define exactly these public types:

```python
class DestroyOperator(StrEnum):
    FAILED_ENDPOINTS = "failed_endpoints"
    BLOCKER_COMPONENT = "blocker_component"
    CONGESTED_CUT = "congested_cut"
    RELATED_CARGO = "related_cargo"
    BAND_BOUNDARY = "band_boundary"
    DIVERSIFY = "diversify"


class RepairOperator(StrEnum):
    ROUTING_REGRET = "routing_regret"
    SEQUENCE_REINSERT = "sequence_reinsert"
    LOCAL_EXACT_PACK = "local_exact_pack"


@dataclass(frozen=True, slots=True)
class OperatorChoice:
    destroy: DestroyOperator
    repair: RepairOperator
    scale: int
```

Add frozen, slotted `OperatorContext` and `OperatorOutcome` dataclasses using concrete scalar/tuple fields. Do not pass mutable solver objects into the selector.

- [ ] **Implement discounted-UCB with stable ties**

Partition statistics by a compact deterministic context bucket: failed-net count band, band-overflow band, congestion band, and feedback-stagnation band. Select untried choices in enum/scale order; thereafter use discounted-UCB. Observe only completed attempts. Normalize reward within the lexicographic rank so runtime never makes a non-exact result outrank an exact result.

- [ ] **Run focused tests, Ruff, and mypy**

Run:

```bash
uv run pytest tests/layout/test_sequence_alns.py -q
uv run ruff check src/flab2bp/layout/sequence_alns.py tests/layout/test_sequence_alns.py
uv run mypy src/flab2bp/layout/sequence_alns.py
```

- [ ] **Commit the pure ALNS model**

```bash
git add src/flab2bp/layout/sequence_alns.py tests/layout/test_sequence_alns.py
git commit -m "feat: add deterministic adaptive operator selector"
```

### Task 9: Implement destroy neighborhoods from existing router feedback

**Files:**
- Modify: `src/flab2bp/layout/sequence_alns.py`
- Modify: `src/flab2bp/layout/route_feedback.py`
- Modify: `tests/layout/test_sequence_alns.py`
- Modify: `tests/layout/test_route_feedback.py`

- [ ] **Write a failing test for each destroy operator**

Use a six-strip synthetic problem with explicit failed endpoints, blocker edges, congestion cut, cargo families, and band boundaries. Assert exact `StripInstanceId` sets for each operator and assert the incumbent is never mutated.

- [ ] **Write boundary tests for destroy scale**

Require every operator to return between one and `min(scale, movable_strip_count)` unique movable strips. Fixed strip instances and instances excluded by placement constraints must never be returned.

- [ ] **Run destroy tests and confirm red failures**

Run:

```bash
uv run pytest tests/layout/test_sequence_alns.py tests/layout/test_route_feedback.py \
  -k destroy -q
```

- [ ] **Expose one immutable route-failure projection**

Add a frozen `RouteFailureProjection` and one pure `project_route_failure(...)` function in `route_feedback.py`. It accepts the current `DetailedRouteResult`, `SequencePair`, `GapProfile`, `PlacementProblem`, `DecodedPlacement`, and `FeedbackState`; it returns endpoint strip IDs, blocker components, hot-wall strip IDs, related-cargo groups, direct-insertion dependencies, and boundary contributors as sorted tuples.

Build the projection from existing `NetFailure.net_id`, `blocking_nets`, `wall`, `geometric_failure_instances`, and `select_lns_neighbourhood` evidence. Do not add mutable failure history to `FeedbackState` and do not translate strip IDs into individual machine IDs.

- [ ] **Implement the six destroy operators as pure functions**

Each function accepts `OperatorContext`, `RouteFailureProjection`, incumbent ordering, and deterministic RNG. Each returns a sorted tuple of unique `StripInstanceId` values. `DIVERSIFY` may sample, but only from the provided RNG.

- [ ] **Run focused tests and static checks**

Run:

```bash
uv run pytest tests/layout/test_sequence_alns.py tests/layout/test_route_feedback.py -q
uv run ruff check src/flab2bp/layout/sequence_alns.py src/flab2bp/layout/route_feedback.py \
  tests/layout/test_sequence_alns.py tests/layout/test_route_feedback.py
uv run mypy src/flab2bp/layout/sequence_alns.py src/flab2bp/layout/route_feedback.py
```

- [ ] **Commit destroy neighborhoods**

```bash
git add src/flab2bp/layout/sequence_alns.py src/flab2bp/layout/route_feedback.py \
  tests/layout/test_sequence_alns.py tests/layout/test_route_feedback.py
git commit -m "feat: derive sequence destroy neighborhoods from routing failures"
```

### Task 10: Implement repair operators with exact local legality

**Files:**
- Modify: `src/flab2bp/layout/sequence_alns.py`
- Modify: `src/flab2bp/layout/sequence_pair.py`
- Modify: `tests/layout/test_sequence_alns.py`
- Modify: `tests/layout/test_sequence_pair.py`

- [ ] **Write failing tests for routing-regret repair**

Require reinsertion order to prioritize the strip whose best and second-best legal insertions have the largest route-aware regret. Assert deterministic tie-breaking by `StripInstanceId` and sequence position.

- [ ] **Write failing tests for sequence reinsertion**

Remove known strip instances from both sequence permutations, reinsert them, and assert each instance appears exactly once in each permutation and the decoded placement has no strip overlap.

- [ ] **Write failing tests for local exact packing**

On a bounded strip neighborhood small enough for the existing exact/local packing primitive, require the repair to find the known legal arrangement. On a deadline-expired context, require a typed `RepairStatus.DEADLINE` without modifying the incumbent.

- [ ] **Run repair tests and confirm red failures**

Run:

```bash
uv run pytest tests/layout/test_sequence_alns.py tests/layout/test_sequence_pair.py \
  -k 'repair or reinsert or local_exact_pack' -q
```

- [ ] **Expose one legality-preserving sequence reinsertion API**

Add a single method/function in `sequence_pair.py` that removes and reinserts a specified `StripInstanceId` set while preserving permutation invariants. Reuse the existing decoder and overlap legality checks; do not add a parallel placement representation.

- [ ] **Implement all three repairs**

Return a typed result containing candidate anneal state, status, evaluated insertion count, and elapsed route time. Check the shared deadline before every expensive routing or exact-pack call. A failed repair returns no candidate; it never returns the partially repaired state.

- [ ] **Run focused tests and static checks**

Run:

```bash
uv run pytest tests/layout/test_sequence_alns.py tests/layout/test_sequence_pair.py -q
uv run ruff check src/flab2bp/layout/sequence_alns.py src/flab2bp/layout/sequence_pair.py \
  tests/layout/test_sequence_alns.py tests/layout/test_sequence_pair.py
uv run mypy src/flab2bp/layout/sequence_alns.py src/flab2bp/layout/sequence_pair.py
```

- [ ] **Commit repair operators**

```bash
git add src/flab2bp/layout/sequence_alns.py src/flab2bp/layout/sequence_pair.py \
  tests/layout/test_sequence_alns.py tests/layout/test_sequence_pair.py
git commit -m "feat: add legality-preserving sequence repair operators"
```

### Task 11: Integrate ALNS into continuation restarts behind an explicit flag

**Files:**
- Modify: `src/flab2bp/layout/sequence_solver.py`
- Modify: `src/flab2bp/layout/sequence_islands.py`
- Modify: `src/flab2bp/pipeline.py`
- Modify: `src/flab2bp/cli.py`
- Modify: `scripts/audit.py`
- Modify: `tests/layout/test_sequence_solver.py`
- Modify: `tests/layout/test_sequence_islands.py`
- Modify: `tests/test_pipeline.py`
- Modify: `tests/test_pipeline_cli_strategy.py`
- Modify: `tests/scripts/test_audit.py`

- [ ] **Write a failing integration test for disabled-by-default behavior**

Assert the default config never calls an ALNS operator and preserves the exact pre-integration stage sequence and seed trace.

- [ ] **Write a failing integration test for feedback-directed continuation**

Provide deterministic route failures, enable ALNS, and assert the selected destroy/repair pair runs only after the initial schedule has exhausted without an incumbent. Require `selector.observe` to receive the exact resulting `OperatorOutcome`.

- [ ] **Write a failing island isolation test**

Run two islands with fixed seeds. Assert each island owns a separate selector state and that merging results cannot change either selector's observations.

- [ ] **Run ALNS integration tests and confirm red failures**

Run:

```bash
uv run pytest tests/layout/test_sequence_solver.py tests/layout/test_sequence_islands.py \
  -k alns -q
```

- [ ] **Add explicit experimental configuration**

Add:

```python
sequence_alns: bool = False
```

to pipeline/CLI/audit boundaries and a corresponding `SequenceSolverConfig` field. Do not expose it in the web UI before promotion. Default remains false everywhere.

- [ ] **Run ALNS only in implicit continuation**

After the initial fixed schedule and before appending a cold random restart:

1. Build immutable context from the selected height and shared route feedback.
2. Select one operator choice.
3. Destroy and repair the best near-miss state for that height.
4. Route/evaluate through the existing exact validation path.
5. Observe the completed outcome.
6. Fall back to the deterministic cold restart when repair produces no candidate.

Never replace the exact router or blueprint validator with selector reward.

- [ ] **Add structured ALNS counters**

Report attempts, successful repairs, exact hits, choice counts, cumulative route seconds, and selector reward totals. Keys must be enum string values so JSON output is stable.

- [ ] **Run focused integration and interface tests**

Run:

```bash
uv run pytest tests/layout/test_sequence_solver.py tests/layout/test_sequence_islands.py \
  tests/test_pipeline.py tests/test_pipeline_cli_strategy.py tests/scripts/test_audit.py -q
uv run ruff check src/flab2bp/layout/sequence_solver.py \
  src/flab2bp/layout/sequence_islands.py src/flab2bp/pipeline.py \
  src/flab2bp/cli.py scripts/audit.py
uv run mypy src/flab2bp/layout/sequence_solver.py \
  src/flab2bp/layout/sequence_islands.py src/flab2bp/pipeline.py
```

- [ ] **Commit disabled ALNS integration**

```bash
git add src/flab2bp/layout/sequence_solver.py \
  src/flab2bp/layout/sequence_islands.py src/flab2bp/pipeline.py \
  src/flab2bp/cli.py scripts/audit.py tests/layout/test_sequence_solver.py \
  tests/layout/test_sequence_islands.py tests/test_pipeline.py tests/test_pipeline_cli_strategy.py \
  tests/scripts/test_audit.py
git commit -m "feat: integrate experimental feedback-directed sequence ALNS"
```

---

## Phase E — Add Only Sound Cross-Layer Cuts

### Task 12: Generalize proof-scoped packing/routing cuts

**Files:**
- Modify: `src/flab2bp/layout/route_feedback.py`
- Modify: `src/flab2bp/layout/freeform.py`
- Modify: `src/flab2bp/layout/sequence_solver.py`
- Modify: `tests/layout/test_route_feedback.py`
- Modify: `tests/layout/test_freeform.py`
- Modify: `tests/layout/test_sequence_solver.py`

- [ ] **Write failing tests distinguishing proof from timeout**

Create one exhaustive detailed-routing result carrying a concrete `RoutingCutWitness` and one budget result without a witness:

```python
proved = DetailedRouteResult(
    status=DetailedRouteStatus.STRANDED,
    routed=(),
    failures=(failure,),
    iterations=1,
    expansions=128,
    exhaustive=True,
    cut_witnesses=(cut_witness,),
)
timed_out = DetailedRouteResult(
    status=DetailedRouteStatus.BUDGET,
    routed=(),
    failures=(budget_failure,),
    iterations=1,
    expansions=128,
    exhaustive=False,
    cut_witnesses=(),
)
```

Assert only `proved` produces a placement constraint. Budget exhaustion, node-limit exhaustion, interrupted search, and non-exhaustive reroute-round limits must produce no witness and no cut.

- [ ] **Write failing tests for cut scope and cache identity**

Require a witness to carry logical/physical net IDs, `StripInstanceId` values, endpoint faces or corridor cells, capacity, demand, and the placement/geometry fingerprint. Assert it is not reused when any proof premise changes.

- [ ] **Run cut tests and confirm red failures**

Run:

```bash
uv run pytest tests/layout/test_freeform.py tests/layout/test_route_feedback.py \
  tests/layout/test_sequence_solver.py -k 'routing_cut or cut_scope' -q
```

- [ ] **Add typed witnesses to the detailed-routing result**

Define frozen `RoutingCutWitness` records in `route_feedback.py` and add `cut_witnesses: tuple[RoutingCutWitness, ...] = ()` to `DetailedRouteResult`. Use LSP references to update every constructor. The relaxed `global_router.py` never emits these witnesses because congestion negotiation and expansion exhaustion are not infeasibility proofs.

- [ ] **Emit witnesses only from complete detailed-router proofs**

In `freeform.py`, construct endpoint-face separation or corridor-capacity witnesses only where the detailed router exhaustively proves the relation. A `RouteFailureKind.BUDGET`, deadline, cancelled search, retained incomplete incumbent, or heuristic wall is insufficient and leaves `cut_witnesses` empty.

- [ ] **Translate witnesses into the narrowest sequence constraint**

In route feedback, convert a witness into the narrowest sound constraint expressible by the existing sequence/band model: separate a proved strip subset, reserve proved corridor capacity, or prohibit the exact proved band assignment. Include every proof premise in cache identity.

- [ ] **Apply cuts before ALNS choice construction**

Update the height's admissible search space before selecting destroy/repair operators. If a cut eliminates a height, mark `termination=\"admission\"` only after every height is eliminated by sound constraints.

- [ ] **Run focused routing and solver tests**

Run:

```bash
uv run pytest tests/layout/test_freeform.py tests/layout/test_route_feedback.py \
  tests/layout/test_sequence_solver.py -q
uv run ruff check src/flab2bp/layout/freeform.py \
  src/flab2bp/layout/route_feedback.py src/flab2bp/layout/sequence_solver.py
uv run mypy src/flab2bp/layout/freeform.py \
  src/flab2bp/layout/route_feedback.py src/flab2bp/layout/sequence_solver.py
```

- [ ] **Commit proof-scoped cuts**

```bash
git add src/flab2bp/layout/freeform.py src/flab2bp/layout/route_feedback.py \
  src/flab2bp/layout/sequence_solver.py tests/layout/test_freeform.py \
  tests/layout/test_route_feedback.py tests/layout/test_sequence_solver.py
git commit -m "feat: feed proven routing cuts into sequence placement"
```

## Phase F — Measure and Promote Classical ALNS

### Task 13: Run paired ALNS promotion gates

**Files:**
- Modify only after passing gate: defaults in `src/flab2bp/layout/sequence_solver.py`, `src/flab2bp/pipeline.py`, `src/flab2bp/cli.py`
- Modify: `docs/superpowers/specs/2026-09-01-zero-refusal-reliability-design.md`
- Modify after passing gate: tests covering those defaults

- [ ] **Run 20 paired repeats on every currently failing hard cell**

Use identical revision, corpus order, budgets, process concurrency, island count, and root seeds. Run static continuation and ALNS continuation separately:

```bash
PYTHONPATH="$PWD/src" uv run python scripts/audit.py \
  --strategy sequence-pair --repeats 20 --budget 30 --jobs 4 \
  --only quantum-chip,graphene \
  --json /tmp/alns-off-hard.jsonl
PYTHONPATH="$PWD/src" uv run python scripts/audit.py \
  --strategy sequence-pair --repeats 20 --budget 30 --jobs 4 \
  --only quantum-chip,graphene --sequence-alns \
  --json /tmp/alns-on-hard.jsonl
```

- [ ] **Run ten paired full-corpus repeats**

Run the full 36-cell Sequence corpus for both variants with identical controls, then summarize wall, CPU, validity, and refusal counts.

- [ ] **Apply the classical ALNS promotion gate**

ALNS qualifies only with zero invalid and zero crashed outputs plus at least one of:

- at least 50% fewer refusals at equal wall and aggregate CPU budgets;
- equal refusals with at least 25% lower p95 wall time at no aggregate CPU increase;
- equal refusals and p95 with at least 25% lower aggregate CPU.

It must also reproduce identical success/refusal classes and blueprint validation outcomes when the entire paired experiment is rerun with the same seeds.

- [ ] **Promote ALNS only if qualified**


Report exact `(area, belt_tiles)` distributions separately. A feasibility win may carry a documented quality cost, but an area improvement may never hide a refusal or invalid-output regression.
If qualified, change production defaults to `sequence_alns=True`, retain a CLI/audit opt-out for regression experiments, and update default tests. If not qualified, retain false and keep the implementation as an explicit experimental mode.

- [ ] **Record exact paired results**

Add command lines, revisions, seeds, corpus, outcomes, p95, aggregate CPU, and promotion decision to the design evidence table.

- [ ] **Run changed-default tests if promoted**

Run:

```bash
uv run pytest tests/layout/test_sequence_solver.py tests/test_pipeline.py \
  tests/test_pipeline_cli_strategy.py tests/scripts/test_audit.py -q
```

- [ ] **Commit the measured ALNS decision**

Stage only files actually changed. Use one of:

```bash
git commit -m "feat: promote measured sequence ALNS policy"
```

or:

```bash
git commit -m "docs: record sequence ALNS gate result"
```

---

## Phase G — Prove a Deterministic Feasibility Backstop Before Shipping One

### Task 14: Build a corpus-wide canonical fallback proof harness

**Files:**
- Create: `scripts/probe_sequence_fallback.py`
- Create: `tests/scripts/test_probe_sequence_fallback.py`
- Modify: `docs/superpowers/specs/2026-09-01-zero-refusal-reliability-design.md`

- [ ] **Write failing tests for canonical construction and proof reporting**

Require the harness to construct the widest legal band for a corpus problem, place machines in canonical stable order, reserve explicit sorter/belt corridors and cargo tracks, and report exactly one of:

```python
class FallbackProofStatus(StrEnum):
    VALID = "valid"
    GEOMETRY_IMPOSSIBLE = "geometry_impossible"
    ROUTING_IMPOSSIBLE = "routing_impossible"
    UNPROVEN = "unproven"
```

`UNPROVEN` must include the exhausted bound and must never be reported as impossible.

- [ ] **Run harness tests and confirm red failure**

Run:

```bash
uv run pytest tests/scripts/test_probe_sequence_fallback.py -q
```

- [ ] **Implement the harness using production legality primitives**

Reuse production machine footprints, attachment rules, belt/sorter routing, power placement, and final blueprint validation. The harness may choose deliberately large geometry, but it may not substitute a simplified router or skip power/sorter validation.

- [ ] **Make construction deterministic**

Order by stable problem IDs; use fixed corridor and track formulas; use no random restart. Emit a content hash of canonical placement input and output so repeatability can be checked byte-for-byte.

- [ ] **Run the harness across all 36 corpus problems twice**

Run both repetitions with the same revision and compare status, content hashes, validity, wall time, CPU time, and bounding area.

- [ ] **Apply the fallback proof gate**

A production backstop is eligible for a separate production-integration plan only if every corpus problem is `VALID`, both runs have identical hashes, zero outputs are invalid, and the maximum fallback wall time fits inside the user-visible maximum budget. Any `UNPROVEN` or impossible status blocks production integration; it does not justify returning a partial blueprint.

- [ ] **Record the proof result and delete no evidence**

Add the matrix and decision to the design spec. Keep the harness even on a negative result because it defines a reproducible lower-risk research surface; do not call it from production.

- [ ] **Run focused tests and commit the proof harness**

Run:

```bash
uv run pytest tests/scripts/test_probe_sequence_fallback.py -q
uv run ruff check scripts/probe_sequence_fallback.py \
  tests/scripts/test_probe_sequence_fallback.py
uv run mypy scripts/probe_sequence_fallback.py
```

Then:

```bash
git add scripts/probe_sequence_fallback.py \
  tests/scripts/test_probe_sequence_fallback.py \
  docs/superpowers/specs/2026-09-01-zero-refusal-reliability-design.md
git commit -m "experiment: prove canonical sequence fallback coverage"
```

---

## Phase H — Collect Classical Data Before Learning

### Task 15: Export deterministic operator-decision datasets

**Files:**
- Create: `src/flab2bp/layout/operator_trace.py`
- Modify: `src/flab2bp/layout/sequence_solver.py`
- Modify: `scripts/audit.py`
- Create: `tests/layout/test_operator_trace.py`
- Modify: `tests/layout/test_sequence_solver.py`
- Modify: `tests/scripts/test_audit.py`

- [ ] **Write failing schema and determinism tests**

Require one versioned row per completed operator attempt with:

```python
@dataclass(frozen=True, slots=True)
class OperatorTraceRow:
    schema_version: Literal[1]
    problem_fingerprint: str
    root_seed: int
    island: int
    height: int
    restart: int
    stage: int
    context: OperatorContext
    choice: OperatorChoice
    outcome: OperatorOutcome
```

Assert two fixed-seed fake runs produce byte-identical JSONL.

- [ ] **Write a failing privacy/size test for trace rows**

Assert rows contain no blueprint string, raw URL, machine object graph, or mutable Python serialization. Set and test a maximum encoded row size based on the concrete schema.

- [ ] **Run trace tests and confirm red failures**

Run:

```bash
uv run pytest tests/layout/test_operator_trace.py tests/layout/test_sequence_solver.py \
  tests/scripts/test_audit.py -k operator_trace -q
```

- [ ] **Implement an append-only versioned JSONL writer**

Serialize enums by string value and tuples as arrays. Write only after an operator outcome completes. Use one file per audit worker and merge in `(case, repeat, island, height, restart, stage)` order to avoid interleaved writes.

- [ ] **Add an explicit audit-only trace path**

Support:

```text
--operator-trace /path/to/trace.jsonl
```

No trace file is written unless this flag is present. Production builds must not perform trace I/O.

- [ ] **Run focused tests and static checks**

Run:

```bash
uv run pytest tests/layout/test_operator_trace.py tests/layout/test_sequence_solver.py \
  tests/scripts/test_audit.py -q
uv run ruff check src/flab2bp/layout/operator_trace.py \
  src/flab2bp/layout/sequence_solver.py scripts/audit.py
uv run mypy src/flab2bp/layout/operator_trace.py \
  src/flab2bp/layout/sequence_solver.py
```

- [ ] **Commit deterministic trace export**

```bash
git add src/flab2bp/layout/operator_trace.py \
  src/flab2bp/layout/sequence_solver.py scripts/audit.py \
  tests/layout/test_operator_trace.py tests/layout/test_sequence_solver.py \
  tests/scripts/test_audit.py
git commit -m "feat: export deterministic sequence operator traces"
```

### Task 16: Run the supervised-selector gate before any GNN or RL work

**Files:**
- Create: `experiments/operator_selector/train.py`
- Create: `experiments/operator_selector/evaluate.py`
- Create: `tests/experiments/test_operator_selector.py`
- Modify: `docs/superpowers/specs/2026-09-01-zero-refusal-reliability-design.md`

- [ ] **Write failing split and leakage tests**

Require train/validation/test splits by problem fingerprint, never by individual operator row. Assert no fingerprint appears in more than one split and repeat seeds for one problem remain together.

- [ ] **Write failing baseline-comparison tests**

Require evaluation output to contain static schedule, discounted-UCB, and supervised selector metrics under identical replay data. Reject reports missing refusal, p95 wall, aggregate CPU, invalid, and determinism fields.

- [ ] **Run experiment tests and confirm red failures**

Run:

```bash
uv run pytest tests/experiments/test_operator_selector.py -q
```

- [ ] **Implement a dependency-free supervised baseline**

Implement a deterministic depth-three classification tree in the experiment package. Inputs are the scalar `OperatorContext` fields; leaves score the finite `OperatorChoice` set. Fix feature order, split tie-breaking, depth, and minimum leaf size in code. The experiment must not import from production entry points and production code must not import the experiment.

- [ ] **Evaluate in solver-in-the-loop mode**

Offline classification accuracy is diagnostic only. The qualifying evaluation runs held-out problem fingerprints through the real solver, router, and validator at matched wall and CPU budgets.

- [ ] **Apply the learned-guidance entry gate**

Proceed to a contextual bandit or GNN/RL implementation plan only if the supervised selector beats discounted-UCB by the same promotion thresholds used in Task 13, with zero invalid outputs and deterministic fallback to discounted-UCB on missing or malformed predictions.

If it does not qualify, stop learned-guidance work. Do not add a production inference dependency.

- [ ] **Record results and the next decision**

Document dataset revision/hash, split fingerprints, model/config hash, all solver-in-loop metrics, and whether further learned guidance is justified. Cite the adjacent neural ALNS work as research context, not evidence that this solver benefits.

- [ ] **Run experiment checks and commit**

Run:

```bash
uv run pytest tests/experiments/test_operator_selector.py -q
uv run ruff check experiments/operator_selector tests/experiments/test_operator_selector.py
uv run mypy experiments/operator_selector
```

Then:

```bash
git add experiments/operator_selector tests/experiments/test_operator_selector.py \
  docs/superpowers/specs/2026-09-01-zero-refusal-reliability-design.md
git commit -m "experiment: evaluate learned sequence operator selection"
```

---

## Phase I — Final Verification and Cleanup

### Task 17: Run full verification and final reliability gates

**Files:**
- Modify: `README.md` only for promoted user-facing behavior
- Modify: `docs/superpowers/specs/2026-09-01-zero-refusal-reliability-design.md` only with final evidence
- Do not modify solver behavior during this task

- [ ] **Run the complete Python test suite**

Run:

```bash
uv run pytest
```

Expected: all tests pass.

- [ ] **Run Python lint and type checks**

Run:

```bash
uv run ruff check .
uv run mypy src scripts
```

Expected: both commands pass.

- [ ] **Build the Python package including the Cython kernel**

Run:

```bash
uv build
```

Expected: source and wheel builds succeed and compile the configured Cython sequence kernel.

- [ ] **Run complete web verification from the web workspace**

Run:

```bash
bun --cwd web install --frozen-lockfile
bun --cwd web test
bun --cwd web run typecheck
bun --cwd web run lint
bun --cwd web run build
```

Expected: all commands pass; the production build emits only intended entries.

- [ ] **Run the final ten-repeat 72-cell production audit**

Use the promoted defaults and production concurrency:

```bash
PYTHONPATH="$PWD/src" uv run python scripts/audit.py \
  --strategy both --repeats 10 --jobs 4 \
  --json /tmp/final-zero-refusal-72x10.jsonl
uv run python scripts/summarize_audit.py \
  /tmp/final-zero-refusal-72x10.jsonl \
  --json /tmp/final-zero-refusal-72x10-summary.json
```

Required result: 720 clean, 0 refused, 0 invalid, 0 crashed. If this gate fails, report the exact failing case IDs and retain safe refusal; do not describe the project as zero-refusal.

- [ ] **Repeat the hard-cell deterministic trace check**

Run the hard-cell audit twice with identical roots. Compare success/refusal classes, validation, selected operator sequence, and canonical trace hashes. Blueprint geometry may differ only if an explicitly nondeterministic mode was enabled; production defaults must not enable one.

- [ ] **Smoke the live CLI reliable path**

Run the documented super-magnetic-ring URL through `--strategy best`, the promoted default budget and islands, and `--candidate-policy no-proliferator`; write to `/tmp/zero-refusal-cli-smoke.txt`. Required result: exit zero, a non-empty blueprint file, and no invalid-output override.

- [ ] **Smoke the live browser reliable path**

Start `uv run flab2bp-web --no-build --port 8000` with the process supervisor. Use the Browser tool to open a tool-owned tab, submit the same documented URL with `best`, the promoted budget, and promoted island count, then wait for job completion. Required result: the page reports a successful validator-clean build, exposes a blueprint string, and renders the blueprint without console errors. Close the tool-owned tab and stop the server.

- [ ] **Update existing documentation only for promoted behavior**

Update `README.md` with the actual default budget, island default, ALNS default, audit repeat flags, and safe-refusal semantics. Add final commands and results to the design evidence table. Do not document experimental modes as production guarantees.

- [ ] **Request code review**

Use the `requesting-code-review` skill. Review specifically for deadline propagation, seed stability, aggregate CPU accounting, proof-vs-timeout cut soundness, invalid-output escape paths, and accidental production dependencies on experiment code.

- [ ] **Commit verification-era documentation changes**

Stage only the two documentation files changed by the preceding action:

```bash
git add README.md \
  docs/superpowers/specs/2026-09-01-zero-refusal-reliability-design.md
git commit -m "docs: document proven solver reliability behavior"
```

- [ ] **Use the branch-finishing workflow**

Use `finishing-a-development-branch` only after the full verification and final 720-cell gate pass. Preserve all audit summaries as review evidence.