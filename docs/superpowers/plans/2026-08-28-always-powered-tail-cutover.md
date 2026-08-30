# Always-Powered Builds and Deadline Cancellation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove power-off from every production interface and cancel detailed-routing attempts before doomed post-deadline emission work.

**Architecture:** Production APIs become always-powered while private validator/routing fixture seams may remain parameterized. Detailed routing gains an explicit cancellation boundary: BUDGET evidence returns before path commit and Placement emission; only ROUTED candidates enter atomic emission, validation, and projection.

**Tech Stack:** Python 3.14, React/TypeScript, pytest, Rstest, Ruff, MyPy, Biome.

**Spec:** `docs/superpowers/2026-08-28-always-powered-tail-cutover-spec.md`

## Global Constraints

- Production always certifies with `expect_power=True`; never infer expected power from tower presence.
- No compatibility aliases or ignored legacy request fields. CLI rejects `--no-power`; web rejects `power`.
- Private fixture-level `expect_power=False` may remain where it isolates unrelated validator rules.
- BUDGET cancellation cannot alter ROUTED/STRANDED paths, walls, expansions, legality, or winner order.
- No new dependencies, `Any`, ignore directives, or increased budgets.

---

### Task 1: Cut over core Python production APIs

**Files:**
- Modify: `src/flab2bp/cli.py`
- Modify: `src/flab2bp/pipeline.py`
- Modify: `src/flab2bp/layout/freeform.py`
- Modify: `src/flab2bp/layout/sequence_solver.py`
- Modify: `src/flab2bp/layout/sequence_islands.py`
- Modify: `src/flab2bp/layout/validate.py`
- Modify: `tests/test_pipeline_cli_strategy.py`
- Modify: `tests/test_pipeline.py`
- Modify: `tests/layout/test_freeform.py`
- Modify: `tests/layout/test_sequence_solver.py`
- Modify: `tests/layout/test_sequence_islands.py`
- Modify: `tests/layout/test_finalize.py`

**Interfaces:**
- `pipeline.build(...)`, `_new_layout(...)`, `FreeformLayout(...)`, `SequencePairLayout(...)`, and `run_sequence_islands(...)` expose no `power` argument.
- Production internal calls pass literal `True` to the retained private power-aware helpers and validators.

- [ ] **Step 1: Run LSP references for every changed public symbol**

Record references for `pipeline.build`, `_new_layout`, `FreeformLayout.__init__`, `SequencePairLayout.__init__`, and `run_sequence_islands` before changing signatures.

- [ ] **Step 2: Write failing public-contract tests**

Add tests that `--help` omits `--no-power`, legacy `--no-power` exits 2, constructor calls with `power=False` raise `TypeError`, and pipeline spies receive no power kwarg while compaction/validation receive `expect_power=True`.

- [ ] **Step 3: Verify RED**

Run the focused CLI/pipeline tests. Expected failures: flag remains accepted and signatures still expose power.

- [ ] **Step 4: Remove public power plumbing**

Delete the CLI flag and public parameters. Collapse production branches to powered behavior, remove `self.power`, and feed literal `True` only at private routing/validation seams. Migrate every LSP-reported caller; no defaulted compatibility parameter.

- [ ] **Step 5: Migrate strategy/island tests**

Public strategy tests become powered. Keep false only in direct private-helper or synthetic validator calls, never through exported constructors or production orchestration.

- [ ] **Step 6: Verify Task 1**

Run focused pipeline, CLI, Freeform public-contract, SequencePair, island, and finalization tests. Run focused MyPy and Ruff on changed Python files.

### Task 2: Remove the web power mode

**Files:**
- Modify: `src/flab2bp/web/jobs.py`
- Modify: `web/src/api/build.ts`
- Modify: `web/src/ui/BuildPanel.tsx`
- Modify: `tests/web/test_options.py`
- Modify: `tests/web/test_jobs.py`
- Modify: `web/tests/api/build.test.ts`
- Modify: `web/tests/ui/BuildPanel.test.tsx`
- Modify: `docs/WEB_UI.md`

**Interfaces:**
- Python `Options` and TypeScript `BuildOptions` contain no `power` field.
- POST bodies containing `power` are rejected with 400.
- Browser UI contains no Tesla Towers/power checkbox and never emits the field.

- [ ] **Step 1: Write failing server and browser contract tests**

Assert default options/request bodies lack `power`, legacy `{power: false}` and `{power: true}` are rejected, and the BuildPanel has no power control.

- [ ] **Step 2: Verify RED**

Run focused Python web and Rstest files. Expected: current field/control exists and legacy input parses.

- [ ] **Step 3: Remove schema, parser, forwarding, and UI control**

Delete the field from both schemas/defaults, reject it as unknown server input, remove pipeline forwarding and the entire checkbox row. Update live web documentation.

- [ ] **Step 4: Verify Task 2**

Run focused Python/web tests, TypeScript typecheck, and Biome on changed web files.

### Task 3: Collapse audit and benchmark generation to powered-only

**Files:**
- Modify: `scripts/audit.py`
- Modify: `scripts/ab_compare.py`
- Modify: `scripts/route_profile.py`
- Modify: `scripts/route_bench.py`
- Modify: `src/flab2bp/bench/runner.py`
- Modify: `src/flab2bp/bench/promotion.py`
- Modify: `src/flab2bp/bench/report.py`
- Modify: affected tests under `tests/scripts/` and `tests/bench/`
- Modify: `docs/AB_COMPARISON.md`
- Modify: `docs/AB_RESULTS.md`

**Interfaces:**
- Current run plans create one powered arm. Persisted `power` metadata remains constant `true` for historical schema compatibility.
- `--power` selectors are removed from comparison/profile/route scripts; supplied legacy flags are argparse errors.

- [ ] **Step 1: Write failing cardinality and CLI tests**

Assert one audit/promotion/runner cell per former power pair, every new record has `power is True`, removed script flags fail, and no skipped `power.*` check is tolerated.

- [ ] **Step 2: Verify RED**

Run focused audit/bench/script tests. Expected: two power arms and public selectors remain.

- [ ] **Step 3: Remove false-producing callers**

Collapse factories and run matrices to powered-only, pass `expect_power=True`, remove selector flags and off-mode report rows. Preserve readers for historical false JSON only where already supported.

- [ ] **Step 4: Update live benchmark documentation**

Remove current instructions using power-off. Mark recorded off-mode results historical rather than current evidence.

- [ ] **Step 5: Verify Task 3**

Run focused audit/bench/script tests plus MyPy and Ruff for changed Python files.

### Task 4: Cancel budgeted routing before emission

**Files:**
- Modify: `src/flab2bp/layout/freeform.py`
- Modify: `src/flab2bp/layout/sequence_solver.py` only if adapter typing/tests require it
- Modify: `tests/layout/test_freeform.py`
- Modify: `tests/layout/test_sequence_solver.py`

**Interfaces:**
- `_BuildResult.placement: Placement | None`.
- Bottom-of-round deadline expiry returns the existing typed all-budget result without `_finish` or `_commit_paths`.
- `_build_prepared` returns immediately for BUDGET before power, sorter slots, Placement, validation, or projection.

- [ ] **Step 1: Write failing bottom-of-round cancellation test**

Drive the deterministic fake clock to expire after a routing round and replace `_commit_paths` with a failing spy. Assert BUDGET failures and unchanged expansions.

- [ ] **Step 2: Verify RED**

Run the focused test. Expected: the spy is called through `_finish`.

- [ ] **Step 3: Return the non-committing budget result**

Replace the bottom-of-round `break`/`_finish(... budget_exhausted=True)` path with `_budget_result()` while retaining identities and charged expansions.

- [ ] **Step 4: Write failing prepared-build emission test**

Stub detailed routing to BUDGET and install failing spies for `_place_power`, `assign_sorter_slots`, and Placement construction boundary. Assert routing evidence remains and `placement is None`.

- [ ] **Step 5: Verify RED, then add the emission cutover**

Make `_BuildResult.placement` optional and return before emission only for BUDGET. Migrate callers to narrow after confirming ROUTED; Freeform failure paths must not read the placement.

- [ ] **Step 6: Verify exact routed behavior**

Run deterministic path-digest, wall, expansion, global/detailed router, Freeform sweep, and SequencePair adapter tests. Re-run the same powered 4-second profile/audit slice and report tails without conflating the audit's independent certification pass.

### Task 5: Full verification and review

- [ ] Run full Python tests.
- [ ] Run Ruff and MyPy.
- [ ] Run all web tests, TypeScript typecheck, Biome lint, and production build.
- [ ] Run one powered end-to-end smoke for each strategy and confirm clean power coverage/connectivity.
- [ ] Request whole-branch review and fix all Important/Critical findings.
