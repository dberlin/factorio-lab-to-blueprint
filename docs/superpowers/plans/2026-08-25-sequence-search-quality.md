# Sequence-Pair Search Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Track steps with checkboxes.

**Goal:** Improve SequencePair placement density by retaining width-optimal candidates and redirecting easy-route budget from redundant global routing into best-height SA exploitation.

**Architecture:** Add candidate score breakdown and deterministic Pareto archives to the fixed-cardinality SA stage. Group restart discovery per height, then use zero-overflow detailed success to enter a quality mode that skips global routing and exact-routes the narrowest candidate until failure re-enables feedback.

**Tech Stack:** Typed Python, current sequence-pair SA/LNS, relaxed global router, detailed router, pytest, Ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-08-25-sequence-search-quality-design.md`

## Global constraints

- Work only in the sequence-pair-solver worktree and preserve all current game-rule correctness.
- No pose/collider/slot/coater/altitude/serializer/validator changes.
- Detailed routing plus validation remains the only exact acceptance gate.
- Exact incumbents compare only `(placement.area, belt_tiles)`.
- No increased default budget, timing assertions, accelerators, Pareto promotion, or `best` default change.
- One commit and task review per task.

---

### Task 1: Candidate score and incumbent geometry observability

**Files:**
- Modify: `src/flab2bp/layout/sequence_pair.py`
- Modify: `src/flab2bp/layout/sequence_solver.py`
- Modify: focused tests

**Produces:** `EnergyBreakdown`, candidate HPWL/history/direct metrics, stage/final geometry stats.

- [ ] Write RED tests proving reported width, used height, gap area, HPWL, history, and direct count equal independently recomputed values.
- [ ] Add immutable `EnergyBreakdown` returned by one candidate-scoring function; `SearchEnergy` derives from it rather than recomputing separate logic.
- [ ] Carry breakdown through `AnnealIncumbent`, global candidates, stage observations, and exact-incumbent stats.
- [ ] Prove stats mutation/removal cannot change ordering.
- [ ] Run sequence/solver/feedback tests, Ruff, mypy.
- [ ] Commit:

```bash
git add src/flab2bp/layout/sequence_pair.py src/flab2bp/layout/sequence_solver.py tests/layout/test_sequence_pair.py tests/layout/test_sequence_solver.py
git commit -m "Report sequence candidate quality"
```

---

### Task 2: Deterministic Pareto elite archive

**Files:**
- Modify: `src/flab2bp/layout/sequence_pair.py`
- Modify: `tests/layout/test_sequence_pair.py`

**Produces:** `EliteCategory`, category-tagged deterministic archive.

- [ ] Write RED fixture where blended winner is wider and narrowest must survive.
- [ ] Implement category keys for blended, narrowest, HPWL, and history candidates; hard overflow always leads.
- [ ] Union categories with exact `PlacementKey` deduplication, stable category/order tie breaks, and configured cap that cannot evict mandatory category winners.
- [ ] Retain remaining blended elites after mandatory categories.
- [ ] Test deterministic equality across seeds/input order and legacy fixed-size/variant states.
- [ ] Run focused tests/static checks.
- [ ] Commit:

```bash
git add src/flab2bp/layout/sequence_pair.py tests/layout/test_sequence_pair.py
git commit -m "Retain Pareto sequence elites"
```

---

### Task 3: Group restart discovery by height

**Files:**
- Modify: `src/flab2bp/layout/sequence_solver.py`
- Modify: `tests/layout/test_sequence_solver.py`

**Produces:** one discovery unit per height, merged restart archive, one route selection per height.

- [ ] Write RED scheduler trace: two restarts at each of three heights execute six SA stages but only three global-selection and detailed calls during discovery.
- [ ] Add a height-discovery operation that advances every restart once, unions archives, then routes/selects once.
- [ ] Preserve per-restart state, stage index, seed, accepted moves, and variant selection after archive union.
- [ ] Allocate one equal discovery routing allowance per height; SA moves consume no expansion budget.
- [ ] Prove every height completes discovery before any exploitation stage.
- [ ] Preserve cancellation/deadline and exact incumbent behavior.
- [ ] Run solver/sequence/global/feedback tests and static checks.
- [ ] Commit:

```bash
git add src/flab2bp/layout/sequence_solver.py tests/layout/test_sequence_solver.py
git commit -m "Group sequence restart discovery"
```

---

### Task 4: Zero-overflow quality mode and adaptive routing cadence

**Files:**
- Modify: `src/flab2bp/layout/sequence_solver.py`
- Modify: `src/flab2bp/layout/sequence_pair.py` only if quality archive key belongs there
- Modify: focused tests

**Produces:** `ObjectiveMode`, per-height quality state, global-skip observations, best-height exploitation.

- [ ] Write RED transition test: zero-overflow global + detailed/validated success enters quality mode.
- [ ] Write RED cadence test: next quality stage globally routes zero candidates, detailed-routes the narrowest legal candidate exactly once, and charges only detailed expansions.
- [ ] Write RED failure test: quality detailed failure exits quality mode; following stage runs global routing and updates feedback.
- [ ] Implement quality-mode archive ordering `(hard overflow, width, used height, gap area, HPWL, key)` while preserving Metropolis exploration.
- [ ] Implement post-discovery best-height scheduling from exact/stranded/overflow/narrowest/spend/stable order.
- [ ] Add stagnation/revisit logic so one height cannot monopolize indefinitely without improvement.
- [ ] Record mode entries/exits and skip reasons after decisions.
- [ ] Run complete scheduler/sequence/global/detailed/feedback tests and static checks.
- [ ] Commit:

```bash
git add src/flab2bp/layout/sequence_solver.py src/flab2bp/layout/sequence_pair.py tests/layout/test_sequence_solver.py tests/layout/test_sequence_pair.py
git commit -m "Exploit zero-overflow sequence heights"
```

---

### Task 5: Correctness and refinery quality experiment

**Files:**
- No tracked changes unless a real defect is found
- Write ignored SDD results/blueprints

- [ ] Run focused sequence/scheduler/game-rule suites.
- [ ] Run Ruff, mypy, and full pytest.
- [ ] Run broad sequence audit; require zero INVALID/CRASH/NOT RUN.
- [ ] Run exact refinery URL through SequencePair all three candidates at 30s and 60s, power off, current URL slope rules.
- [ ] Certify, byte-roundtrip, strict TypeScript crossvalidate, and inspect poses/slots/colliders/coaters.
- [ ] Compare with recorded baselines:
  - SequencePair 30/60 best: area 1,950, belts 957, bounds 75×26;
  - Freeform: area 1,196, belts 675, bounds 46×26.
- [ ] Report candidate width, height, gap, HPWL, archive category, stage/global/detailed counts and timing.
- [ ] Save fresh blueprints and results. Do not claim promotion or add a performance threshold test.
- [ ] Request whole-branch review and fix load-bearing findings.

## Deferred

Accelerator selection, formal Pareto promotion, and making sequence-pair part of `best` remain outside this plan.
