# Projected Power-Legality Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove repeated projection-position work from powered preparation while preserving exact tower choices and first-failure evidence.

**Architecture:** Add explicit `_power_plan` timing to the existing profiler, then introduce an attempt-local evaluator that caches accepted peers' projected positions. Candidate towers are projected once per required projection and compared in the existing deterministic order through the authoritative `_power_pair_condition`. Optional projection-envelope memoization is evaluated only after the candidate cache passes parity and its own speed gate.

**Tech Stack:** Python 3.14, NumPy, immutable projection records, pytest, cProfile/wrapper profiling, Ruff, strict MyPy.

**Spec:** `docs/superpowers/specs/2026-08-30-projection-safe-pitch-power-cache-design.md`

## Global Constraints

- Start only after the projection-safe pitch quality gate passes and receives review approval.
- Do not change tower-site order, tie-breaking, keepouts, coverage, connectivity, failure order, or evidence text.
- The pre-existing-node check continues to call `finalize.projected_power_failure` once.
- Cache only repeated candidate-versus-peer projection work in the first implementation.
- Cache state is attempt-local; no persistent or cross-build cache.
- No new dependency, native extension, search budget, retry, or relaxed legality path.
- Discard the cache commit if the measured speed gate fails; retain pitch work independently.

---

### Task 1: Measure powered preparation directly

**Files:**
- Modify: `scripts/route_profile.py`
- Modify: `tests/scripts/test_route_profile.py`
- Modify: `tests/bench/test_route_profile.py`

**Interfaces:**
- Consumes: current wrapper-based `Tally` instrumentation.
- Produces JSON fields:
  - `power_plan_s: float`
  - `power_plan_calls: int`
  - `projection_envelope_s: float`
  - `projection_envelope_calls: int`

- [ ] **Step 1: Write failing profiler-schema tests**

Wrap a small real powered profile and assert all four fields exist, are numeric/non-negative, and normal human output includes a `power planning` row:

```python
def test_json_reports_power_preparation_time() -> None:
    record = run_profile_json("plastic", strategy="freeform", budget=1.0)
    assert record["power_plan_calls"] >= 1
    assert record["power_plan_s"] >= 0.0
    assert record["projection_envelope_calls"] >= 1
    assert record["projection_envelope_s"] >= 0.0
```

Keep the existing route/A* fields unchanged.

- [ ] **Step 2: Run profiler tests to verify RED**

```bash
uv run pytest -q tests/scripts/test_route_profile.py tests/bench/test_route_profile.py -k "power or json"
```

Expected: missing JSON keys.

- [ ] **Step 3: Instrument `_power_plan` and `_projection_envelope`**

Extend `install(tally)` with wrappers matching the exact current signatures. Use `try/finally` so refused/unpowerable attempts still charge elapsed time and calls. Restore both originals in the returned cleanup closure.

Add JSON fields from `tally.t`/`tally.n` and a concise human row without changing existing output lines.

- [ ] **Step 4: Capture the six-case baseline**

Run two repeats each:

```bash
uv run python scripts/route_profile.py plastic --strategy freeform --budget 4 --repeat 2 --json
uv run python scripts/route_profile.py super-magnetic-ring --strategy freeform --budget 4 --repeat 2 --json
uv run python scripts/route_profile.py quantum-chip --strategy freeform --budget 4 --repeat 2 --json
uv run python scripts/route_profile.py plastic --strategy sequence-pair --budget 4 --repeat 2 --json
uv run python scripts/route_profile.py super-magnetic-ring --strategy sequence-pair --budget 4 --repeat 2 --json
uv run python scripts/route_profile.py quantum-chip --strategy sequence-pair --budget 4 --repeat 2 --json
```

Save raw JSON records under `.superpowers/sdd/2026-08-30-projected-power-cache/baseline.jsonl`. Record medians per case; do not infer speed from cProfile seconds.

- [ ] **Step 5: Verify and commit Task 1**

```bash
uv run pytest -q tests/scripts/test_route_profile.py tests/bench/test_route_profile.py
uv run ruff check scripts/route_profile.py tests/scripts/test_route_profile.py tests/bench/test_route_profile.py
uv run mypy scripts/route_profile.py tests/scripts/test_route_profile.py tests/bench/test_route_profile.py
git add scripts/route_profile.py tests/scripts/test_route_profile.py tests/bench/test_route_profile.py
git commit -m "Measure projected power preparation"
```

---

### Task 2: Attempt-local projected peer cache

**Files:**
- Modify: `src/flab2bp/layout/freeform.py`
- Modify: `src/flab2bp/layout/finalize.py`
- Modify: `tests/layout/test_freeform.py`
- Modify: `tests/layout/test_finalize.py`

**Interfaces:**
- Consumes: ordered `projections`, ordered indexed power nodes, `finalize._building_centre`, and a shared exact pair-failure helper in `finalize`.
- Produces internal `_ProjectedPowerEvaluator`:

```python
type _ProjectedPosition = tuple[float, float, float]
type _ProjectedPositions = tuple[_ProjectedPosition, ...]

class _ProjectedPowerEvaluator:
    @classmethod
    def prepare(
        cls,
        projections: tuple[planet.Projection, ...],
        nodes: Sequence[tuple[int, PlacedBuilding, rules.PowerNode]],
    ) -> _ProjectedPowerEvaluator: ...

    def candidate_failure(
        self,
        candidate: tuple[int, PlacedBuilding, rules.PowerNode],
    ) -> tuple[finalize.ProjectionFailure | None, _ProjectedPositions]: ...

    def accept(
        self,
        candidate: tuple[int, PlacedBuilding, rules.PowerNode],
        projected_positions: _ProjectedPositions,
    ) -> None: ...
```

- [ ] **Step 1: Write exact reference-parity tests**

For fixed legal and illegal node sets, compare the evaluator with the current reference loop:

```python
def reference_candidate_failure(nodes, candidate, projections):
    for projection in projections:
        for peer in nodes:
            failure = finalize.projected_power_failure(
                (peer, candidate),
                projection,
            )
            if failure is not None:
                return failure
    return None
```

This is the exact production order: projection outer, existing peer inner. It cannot include old-peer pairs already checked before the greedy starts. Assert equality of the entire `ProjectionFailure` record, including detail text.


Add deterministic randomized cases across bands, anchors, quadrants, ordinary Tesla Towers, Ray Receivers, and Energy Exchangers.

- [ ] **Step 2: Write exact site-sequence tests**

Run `_power_plan` once with the reference evaluator and once with the cache on identical cloned canvases. Assert:

- identical returned sites in order;
- identical `_Unpowerable.failure` when refused;
- identical `canvas.keep_out` and reserved cells;
- identical selected tower count.

- [ ] **Step 3: Run parity tests to verify RED**

```bash
uv run pytest -q tests/layout/test_freeform.py tests/layout/test_finalize.py -k "projected_power_evaluator or cached_power_sites"
```

Expected: `_ProjectedPowerEvaluator` does not exist.

- [ ] **Step 4: Extract exact pair evidence and implement prepared peer positions**

First extract `finalize._projected_power_pair_failure(left, right, left_pose, right_pose, *, band)` from `projected_power_failure`. Both the current reference and the evaluator must call this helper. It must preserve the current arithmetic and formatting exactly:

```python
distance2 = math.dist(left_pose, right_pose) ** 2
condition = _power_pair_condition(left, right, distance2)
```

Return the same `ProjectionFailure` constructor and detail text currently in `projected_power_failure`; the public function retains its current pose projection and `combinations(...)` order.

At evaluator preparation, compute and store `projection.position(*finalize._building_centre(peer_building))` for every accepted peer under every projection, preserving list order.

For a candidate:

1. compute one candidate position per projection;
2. iterate projections in existing order;
3. iterate peers in existing `power_nodes` order;
4. call `_projected_power_pair_failure` with the cached peer pose and candidate pose;
5. return the same first failure;
6. return the candidate's projected-position tuple alongside a successful result so acceptance performs no second projection.

`candidate_failure` must not mutate. `accept` appends the candidate record and its already-computed positions only after legality succeeds.

- [ ] **Step 5: Integrate into `_power_plan`**

Keep the existing pre-existing-node loop unchanged. Prepare one evaluator immediately afterward. Replace only the nested candidate `projections × power_nodes × projected_power_failure((peer, candidate), projection)` loop. On acceptance, append to both `power_nodes` and evaluator in the same order; on rejection, mutate neither.

- [ ] **Step 6: Verify Task 2**

```bash
uv run pytest -q tests/layout/test_freeform.py tests/layout/test_finalize.py -k "power or projection"
uv run pytest -q tests/layout/test_global_router.py tests/layout/test_route_feedback.py tests/layout/test_sequence_solver.py
uv run ruff check src/flab2bp/layout/freeform.py src/flab2bp/layout/finalize.py tests/layout/test_freeform.py tests/layout/test_finalize.py
uv run mypy src/flab2bp/layout/freeform.py src/flab2bp/layout/finalize.py tests/layout/test_freeform.py tests/layout/test_finalize.py
```

- [ ] **Step 7: Commit Task 2**

```bash
git add src/flab2bp/layout/freeform.py src/flab2bp/layout/finalize.py tests/layout/test_freeform.py tests/layout/test_finalize.py
git commit -m "Cache projected power peer positions"
```

---

### Task 3: Apply the cache performance gate

**Files:**
- Modify only if parity or benchmark evidence exposes a defect.
- Record ignored evidence under `.superpowers/sdd/2026-08-30-projected-power-cache/`.

**Interfaces:**
- Consumes: Task 1 baseline and Task 2 cache.
- Produces: keep/discard decision for the cache commit and optional envelope-memoization decision.

- [ ] **Step 1: Re-run the identical six-case profile**

Use the exact commands, worker count, order, and two repeats from Task 1. Save `candidate-cache.jsonl`.

- [ ] **Step 2: Check exact quality parity**

For each paired record assert identical strategy, URL, verdict class, route digest fixture where available, validation result, area, belts, and selected tower-site sequence. Any mismatch rejects the cache regardless of speed.

- [ ] **Step 3: Apply the speed gate**

Keep the cache only if either condition holds:

- median `power_plan_s` improves at least 20% in two cases; or
- median end-to-end `wall_s` improves at least 5% in one case.

No case may lose coverage or regress exact `(area, belt_tiles)`.

If the gate fails, revert only the Task 2 cache commit. Retain Task 1 instrumentation.

- [ ] **Step 4: Evaluate projection-envelope memoization conditionally**

Only when `projection_envelope_s` remains at least 20% of median `power_plan_s` in two cases, add a focused RED/GREEN task:

- immutable cache key `(occupied_bounds, capacity_bounds, BandPolicy)`;
- exact tuple identity/order parity against the uncached reference;
- an attempt-local `dict` owned by one layout call and discarded when that call returns; no decorator or module-global state.

Re-run the same parity and speed gate. Discard this subchange if it does not independently pass.

- [ ] **Step 5: Run complete validation**

```bash
uv run pytest -q
uv run ruff check .
uv run mypy
```

Run both powered strategy smokes and explicitly validate `power.coverage` plus `power.connectivity`.

- [ ] **Step 6: Request whole-cache-range review**

Review for stale cache state, changed first-failure order, changed float formatting, candidate mutation before acceptance, unbounded cache lifetime, and profiler distortion. Fix every Critical and Important finding before completion.
