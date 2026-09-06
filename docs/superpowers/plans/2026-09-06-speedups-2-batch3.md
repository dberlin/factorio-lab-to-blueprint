# Speedups round 2, batch 3: freeform budget discipline

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let freeform spend the budget it is given: certify only candidates that could become the incumbent, and stop refusing to start a candidate merely because the dearest completed candidate would not fit.

**Architecture:** Two changes inside `freeform._sweep`'s budget logic. L4 moves `validate.certify` behind an `(area, belt_tiles)` comparison against the current certified incumbent, keeping "certify every new best" so the returned placement is identical. L5 splits `_room_for_another`'s single estimate into the completion tail (still a maximum) and a next-candidate estimate (median of completed candidates), relying on the existing `remaining <= 0` abandonment for over-runs. One paired gate for both, with `wall_overshoot_s` as the check that matters.

**Tech Stack:** Python 3.14, `uv run`, `scripts/audit.py` / `scripts/audit_compare.py`, `docs/superpowers/evidence/2026-09-05-scale-profile/prof_harness.py`.

**Spec:** `docs/superpowers/specs/2026-09-05-speedups-2-design.md` §L4, §L5, §2 (third batch). Evidence: `docs/superpowers/evidence/2026-09-05-speedups-2/README.md` §1 and §4.

## Global Constraints

- Exactness of the result: the placement `_sweep` returns is identical to today's on every input (the winner is always certified before it is returned; a candidate that loses on `(area, belt_tiles)` can never be selected). The certified set becomes a subset of today's.
- The wall stays a wall: the completion tail (`compaction_reserve_s + finalize_reserve_s + validation_reserve_s`) remains a maximum that must fit before a candidate starts; `wall_overshoot_s` must not grow in the gate (max over cells at most today's max, allowance unchanged).
- `validation_reserve_s` keeps being fed by real certify spans: the first completed candidate is always certified (so the reserve is measured early), and any candidate that becomes the incumbent is certified.
- Gate (spec §2 third batch): three paired 30 s rounds against the merge base, regression-only, INVALID 0, CRASH 0, `wall_overshoot_s` max reported and not above baseline's max; freeform area ratio and "budget actually spent" (sum of candidate seconds over budget) per cell before/after; re-profile um60, gm200, um120, qc180 freeform at 30 s reporting candidates attempted, `validate` calls and seconds, unused seconds.
- Known-red on master and lint/type baselines as in batch 2's plan. Verify once per code change.

---

### Task 1: Certify only a would-be incumbent (L4)

**Files:**
- Modify: `src/flab2bp/layout/freeform.py` (`_sweep`: the `validate.certify(placement, spec, expect_power=True)` site ~21252 and the `validation_reserve_s = max(...)` update ~21264; the incumbent comparison that follows)
- Test: `tests/layout/test_freeform.py`

**Interfaces:**
- Produces: a helper `_would_become_incumbent(candidate_key, incumbent_key) -> bool` over `(area, belt_tiles)` (pure), used before certification; stats gain `certify_skipped` (count) alongside the existing validate counters so the gate can see it.

- [ ] **Step 1: Failing tests.** (a) With three completed candidates where the second is worse on area than the first, `certify` is called for the first and third only, the returned placement equals today's (run the same fixture with the old behaviour via monkeypatch of the helper to always-True and compare), and `stats["certify_skipped"] == 1`. (b) When the first certified incumbent turns out INVALID, the next candidate is certified (fallback preserved). (c) `validation_reserve_s` is non-zero after the first candidate.
- [ ] **Step 2: Run, expect failure. Step 3: Implement. Step 4: Verify** `uv run pytest -q -p no:randomly tests/layout/test_freeform.py -k "certif or incumbent or sweep or validation_reserve"` exit 0; ruff/mypy/format. Harness: um120 freeform at 30 s before/after, report `validate` calls and seconds and candidates attempted. **Step 5: Commit** `perf(layout): certify only freeform candidates that would become the incumbent`

### Task 2: Estimate the next candidate honestly (L5)

**Files:**
- Modify: `src/flab2bp/layout/freeform.py` (`_room_for_another` ~21399 and its docstring on Ruling AD; the `dearest_candidate_s` bookkeeping ~19891-20162 and the `turn_cost` computation ~20162/20295)
- Test: `tests/layout/test_freeform.py`

**Interfaces:**
- Produces: `_room_for_another(deadline, soft, *, completion_tail_s, next_candidate_s)`; `next_candidate_s` = median of completed candidate totals (or the single value when one), `completion_tail_s` = the existing reserve sum (maximum). The queued-remainder path (`dearest_remainder_s`) keeps its current semantics. Stats gain `budget_unspent_s`.

- [ ] **Step 1: Failing tests.** (a) Pure predicate table: with completed candidates [4, 4, 12] s and tail 2 s, 9 s left starts another (median 4 + 2 fits), 5 s left does not; with tail 6 s and 7 s left, no start (tail is a maximum). (b) A sweep fixture where the old rule would stop with 8 s left and the new rule starts one more candidate that completes; the returned placement is the better of the two. (c) An over-running extra candidate is abandoned at `remaining <= 0` and the incumbent is returned (existing behaviour, now pinned).
- [ ] **Step 2: Run, expect failure. Step 3: Implement. Step 4: Verify** `-k "room_for_another or unspent or sweep"` exit 0; ruff/mypy/format. Harness: gm200 and um60 freeform at 30 s before/after, report unused seconds and candidates attempted and `wall_overshoot_s`. **Step 5: Commit** `perf(layout): size the next freeform candidate by the median, keep the completion tail a maximum`

### Task 3: Paired gate and re-profile

Same shape as batch 2's Task 3 with evidence dir `docs/superpowers/evidence/2026-09-06-speedups-2-batch3/`, freeform arm as the one under test, the four freeform cells plus the belt3 and mall URLs at 60 s under freeform, and `wall_overshoot_s` max, `certify_skipped` and `budget_unspent_s` per cell in `judge.py`. Commit `evidence: speedups batch 3 gate and re-profile`.
