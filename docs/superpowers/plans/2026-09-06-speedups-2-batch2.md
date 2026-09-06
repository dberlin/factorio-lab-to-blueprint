# Speedups round 2, batch 2: memoize the direct-insert eligibility pre-pass

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the sequence-pair strategy from re-enumerating direct-insert targets for every producer/consumer variant pair, so the one-call `_variant_direct_eligibility` pre-pass stops eating 55 to 67 percent of the search on large cells.

**Architecture:** Two exact rewrites in `flab2bp.layout`: memoize `freeform._direct_alignment_targets` on the identity of the `_DirectCandidateSnapshot` it is called with plus the two changed entries, and give `DirectInsertTarget` a checked copy path so `replace(...)` revalidates only the fields it changes. Then one paired gate, alone, because the failure mode here is a wrong answer rather than a slow one.

**Tech Stack:** Python 3.14, `uv run`, OR-Tools CP-SAT, `scripts/audit.py` / `scripts/audit_compare.py`, `docs/superpowers/evidence/2026-09-05-scale-profile/prof_harness.py` (`--url`, `--islands`).

**Spec:** `docs/superpowers/specs/2026-09-05-speedups-2-design.md` §L3 and §2 (second batch). Evidence: `docs/superpowers/evidence/2026-09-05-speedups-2/README.md` §7.

## Global Constraints

- Exactness: with the memo disabled, every function returns byte-identical results; with it enabled, results equal the unmemoized ones on every call (tests assert equality against the uncached path, and a drift guard classifies every field the key must cover, following `_DIRECT_GEOMETRY_KEY_FIELDS` / `test_direct_geometry_key_classifies_every_strip_field` in `tests/layout/test_freeform.py`).
- Memos are run-scoped (created inside the run function, threaded as a parameter) or bounded module memos with clear-on-overflow at 65536, cleared by the autouse fixture in `tests/conftest.py`.
- Validation stays at the construction boundary: `DirectInsertTarget.__post_init__` remains the validator for fresh targets; the copy path may skip only checks whose inputs are unchanged, and the argument for why must be written in the docstring.
- Gate (spec §2 second batch): three paired 30 s `audit_compare` rounds against the master this branch starts from, regression-only (no cell CLEAN in all three baseline rounds and non-CLEAN in all three candidate rounds), INVALID 0, CRASH 0, `wall_overshoot_s` within allowance; sequence-pair and freeform area ratios reported per arm. Plus the four large sequence-pair cells and the large URLs at 60 s: qc180, um120, mall, zurl2, with `decoded candidates`, `anneal moves`, `detailed routes` and `_variant_direct_eligibility` wall before/after from the harness.
- `audit.py` prints `NOT CLEAN` whenever any cell refuses; judge by counts and differing cells. The pytest summary line never prints; judge by exit code. Known-red on master: `tests/layout/test_freeform.py::test_all_products_band_160_cold_proof_reaches_a_valid_layout`; load flake `tests/test_pipeline.py::test_all_products_sequence_pair_honours_the_exact_layout_deadline`.
- Lint/type baseline: `ruff check` 0, `mypy src` 0, `ruff format --check` 0 files (master is fully formatted since bfe5ffe).
- Verify once per code change; reviewers read the implementer's evidence rather than re-running suites.

---

### Task 1: Memoize `_direct_alignment_targets` on the candidate snapshot

**Files:**
- Modify: `src/flab2bp/layout/freeform.py` (`_DirectCandidateSnapshot` ~3189, `_direct_alignment_targets` ~3239), `src/flab2bp/layout/sequence_solver.py` (`_selected_direct_targets` ~3819, `_variant_direct_eligibility` ~4364, the `_production_run` caller that threads the existing `selected_strip_memo`)
- Test: `tests/layout/test_freeform.py`, `tests/layout/test_sequence_solver.py`

**Interfaces:**
- Produces: `freeform._direct_alignment_targets(candidates, *, memo: dict | None = None)`; key = `(id(snapshot) or snapshot identity, tuple of the (index, variant) entries that differ from the snapshot's base plan)`; the memo lives next to `selected_strip_memo` in `_production_run` and in `_variant_direct_eligibility` (run-scoped dicts), threaded through `_selected_direct_targets(..., alignment_memo=)`.
- Constants `_DIRECT_ALIGNMENT_KEY_FIELDS` / `_UNREAD_BY_DIRECT_ALIGNMENT` over the `_DirectCandidateSnapshot` fields (and any strip fields the function reads), with the partition guard test.

- [ ] **Step 1: Failing tests.** (a) `test_direct_alignment_targets_memo_is_transparent`: build a snapshot the way `_variant_direct_eligibility` does for a two-strip fixture (reuse the fixture the eligibility tests use), call the function twice with a memo and once without, assert all three results are equal and the memo has exactly one entry per distinct (snapshot, delta). (b) `test_direct_alignment_key_classifies_every_snapshot_field` in the style of the existing drift guards. (c) `test_variant_direct_eligibility_is_unchanged_by_the_alignment_memo`: run the pre-pass with the memo neutralised (monkeypatch the memo param to None) and enabled; equal outputs; count `_direct_alignment_targets` uncached-body calls with a counter and assert the memoized run makes fewer.
- [ ] **Step 2: Run, expect failure.**
- [ ] **Step 3: Implement** the memo (body moved to `_direct_alignment_targets_uncached`), the key builder, the constants, and thread the dict from both run-scoped sites. Do not memoize across runs.
- [ ] **Step 4: Verify** `uv run pytest -q -p no:randomly tests/layout/test_freeform.py -k "direct_alignment or geometry_key" tests/layout/test_sequence_solver.py -k "direct or eligibility"` exit 0; ruff/mypy/format clean. Measure: `uv run python docs/superpowers/evidence/2026-09-05-scale-profile/prof_harness.py quantum-chip --rate 180 --strategy sequence-pair --budget 30 --cprofile --out /tmp/b2-t1-qc180` before (master, from a throwaway worktree) and after; report `_variant_direct_eligibility` cumtime and the decoded-candidate count.
- [ ] **Step 5: Commit** `perf(layout): memoize direct alignment targets per candidate snapshot`

### Task 2: A checked copy path for `DirectInsertTarget`

**Files:**
- Modify: `src/flab2bp/layout/sequence_pair.py` (`DirectInsertTarget`, its `__post_init__` and the two `origin_deltas` generator expressions it runs), the `replace(...)` call sites in `sequence_solver.py` (`_refinement_direct_targets` and neighbours; find them with Serena `find_referencing_symbols` on `DirectInsertTarget`)
- Test: `tests/layout/test_sequence_pair.py` (or wherever `DirectInsertTarget` is tested), `tests/layout/test_sequence_solver.py`

**Interfaces:**
- Produces: `DirectInsertTarget.with_(**changes)` (or `moved(...)`, name to match the codebase's style) that copies the frozen instance and revalidates only the invariants whose inputs are among `changes`; `__post_init__` unchanged for fresh construction.

- [ ] **Step 1: Failing tests.** Parity: for a sample of valid targets and every field the replace sites change, `target.with_(**c) == replace(target, **c)`; an invalid change (one that `__post_init__` would reject) is still rejected by `with_`; a counter on the full validator shows `with_` does not re-run it for unchanged-field copies.
- [ ] **Step 2: Run, expect failure.** **Step 3: Implement**, switching the replace sites. **Step 4: Verify** as in Task 1 (add `-k "DirectInsertTarget or refinement_direct"`); measure `DirectInsertTarget.__post_init__` call count and cumtime before/after on qc180 sequence-pair. **Step 5: Commit** `perf(layout): revalidate only the changed fields when copying a direct-insert target`

### Task 3: Paired gate and re-profile

**Files:**
- Create: `docs/superpowers/evidence/2026-09-06-speedups-2-batch2/` with `gate.md`, `baseline-<sha>-round{1,2,3}.*`, `candidate-round{1,2,3}.*`, `compare-round{1,2,3}.txt`, `judge-round{1,2,3}.txt`, `judge.py` (copy from `2026-09-05-speedups-2/judge.py`), `profile-before.jsonl`, `profile-after.jsonl`
- Modify: `docs/superpowers/specs/2026-09-05-speedups-2-design.md` status line

- [ ] **Step 1:** Record the baseline: three `scripts/audit.py --budget 30 --json` rounds from a throwaway worktree at this branch's merge base, interleaved with the three candidate rounds from this worktree; `(uptime; vmstat 1 3 | tail -1)` before each; never two audits at once.
- [ ] **Step 2:** `judge.py` per round against the paired baseline round; flake re-runs (3x both trees, `--only`/`--strategy`) for partial disagreements.
- [ ] **Step 3:** Re-profile qc180, um120 (rate 120), gm200 with `--strategy sequence-pair --budget 30 --islands 4 --cprofile`, and the mall and zurl2 URLs (`docs/superpowers/evidence/2026-09-05-speedups-2/large-urls/urls.txt`) at `--budget 60 --policy all-products --strategy sequence-pair --islands 4`, before (merge-base worktree) and after; two runs at a time at most. Report `_variant_direct_eligibility` cumtime, `DirectInsertTarget.__post_init__` calls, decoded candidates, anneal moves, detailed routes, area, verdict.
- [ ] **Step 4:** `gate.md` (commits, counts table, differing cells with rulings, area ratios per arm, overshoot, the profile table, the §2 verdict); status line.
- [ ] **Step 5: Commit** `evidence: speedups batch 2 gate and re-profile`
