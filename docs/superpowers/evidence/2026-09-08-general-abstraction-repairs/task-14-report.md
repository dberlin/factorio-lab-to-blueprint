# Task14 — completion baseline preparation and gated cutover

Status: Main ran post-cutover completion/reuse/gate probes and all 27 integrated clock cases successfully (EXIT0), following the successful baselines. Main subsequently reports the 106-file mypy gate EXIT0, all eight focused regressions passing after correcting the projected-refusal regression, and independent CompletionContextReview with no findings. Source remains frozen for Main's integration/commit. **No layout/runtime/proof/test/build/lint/formatter/benchmark command was executed by this worker.** Measured probe evidence below is read from retained integrated logs; subsequent gate/review status is attributed to Main. No clock improvement or redundant-certification reduction is claimed.

## Pre-cutover source contracts

Read task-14-brief.md and task-15-brief.md first. Mapping was grounded in the abstraction-general worktree source:

- `freeform.py` current completion block at 22813–23100: cleanup and projection receive `deadline + ATOMIC_COMPLETION_GRACE_S` (or None). It checks after cleanup, after projection, and after atomic certification. The final projected candidate is ranked before certification at `_would_become_incumbent(key, best_key)`; the inbound-choice arm retains its existing exception to the skip gate. Only accepted valid geometry is stamped. Projection no-good learning and retry ownership stay in Freeform.
- `sequence_solver.py::_production_run.certify` current lines 5540–5600: the same +5-second atomic window bounds entry, cleanup, projection, and post-certification acceptance. It currently reuses `compacted.report` without checking whether finalization changed its geometry/frame. Its finalizer signature introspection is a production compatibility path slated for removal, not a contract to preserve.
- `hierarchy/strategy.py::HierarchicalLayout.lay_out` current 865–910: `composed_spec` is recalculated from the actual final blocks, then the parent deadline is checked, then sorter slots are assigned over the whole composed building list. Cleanup and projection use the **parent deadline**, not the +5-second window. Once the finalizer returns, there is **no deadline check before or after atomic certification**. This is intentional extraction policy, not a newly repaired timeout.
- `finalize.py::BoundaryCompactionResult` associates its optional Report with the returned compacted geometry. The result's stats-only replacement does not invalidate the report; a subsequent physical frame transform can. Cleanup currently invokes its imported `_certify` with diagnostic strategy defaults. Task14 must supply the researched rules all the way through cleanup and final certification.
- `finalize_placement` returns the input object on a valid existing frame. Otherwise it materializes candidate geometry and frame; this is the simple ownership boundary at which an earlier report must be dropped. No structural hash, placement copy, or full-building comparison is necessary.
- `validate.py::certify` currently has only `placement, spec, *, expect_power`. Task4's `judge_placement(..., ids, belt_rules, expect_power)` is the researched-policy owner to compose, while generic `validate` remains the deliberate no-URL diagnostic seam.

An LSP symbols lookup and hover/type-definition were used; LSP cross-file locations can refer to the root tree. Direct reads of the worktree establish the policy/field signatures. In particular `BeltAltitudeRules` fields are `max_z` and `vertical_construction`, not validation's keyword names.

## Disposable probe and source inputs

`task-14-completion-probe.py` drives real geometry and real validators, not successful mock Reports:

1. `capture`: runs real Freeform on `tests.layout.hierarchy.conftest.chain_build_spec()`, captures raw wired candidates, independently compacts/projects/judges a clean one, and persists that actual spec/raw candidate plus a clean completed geometry with the stamp cleared in `task-14-wired-fixture.pickle`.
2. `clock`: runs the selected real strategy to its native completion boundary. A disposable source-line debugger trace activates the clock only there. The cleanup input is replaced once with the exact captured specimen; semantic spec equality is required. All cleanup/projection/certification and caller acceptance/refusal handling remain real. Hierarchy still runs actual composition, composed-spec derivation, and whole-list slot assignment first. A before-cleanup hierarchy expiry intentionally refuses at its real admission guard before specimen injection.
3. `reuse`: observes changed and already-clean compaction, whether the returned Report exists, whether projection preserves object/building/frame identity, and an independent researched-rule judgment of the resulting geometry. Identity loss is evidence against reuse validity even when both old and new geometry happen to pass.
4. `gate`: runs native Freeform with observing wrappers around real projection, real certification and the real incumbent gate. It requires an actually rejected projected candidate and an actually skipped certification; if none occurs, the command explicitly refuses to claim the witness. No gate result, routing result, or validator Report is manufactured.

The ready specimen lets every clock case reach a real final certification without a changed-cleanup cached Report bypassing that boundary. Use `--specimen raw` separately for report/geometry transitions. The baseline clock is frozen only after completion starts; no production phase deadline is widened by the probe. The no-expiry control advances to parent-deadline +0.25 only after real certification, ending further search inside the existing atomic grace.

## Historical baseline commands — do not recapture the retained fixture

Run from abstraction-general with `PYTHONPATH=src:.` (the test fixture module needs the worktree root). Use Main's finite subprocess timeout, e.g. 90 seconds per child; preserve stdout/stderr to distinct log files. No server is started.

```sh
PYTHONPATH=src:. uv run python .superpowers/sdd/2026-09-08-general-abstraction-repairs/task-14-completion-probe.py capture
PYTHONPATH=src:. uv run python .superpowers/sdd/2026-09-08-general-abstraction-repairs/task-14-completion-probe.py reuse
PYTHONPATH=src:. uv run python .superpowers/sdd/2026-09-08-general-abstraction-repairs/task-14-completion-probe.py gate
PYTHONPATH=src:. uv run python .superpowers/sdd/2026-09-08-general-abstraction-repairs/task-14-completion-probe.py clock --strategy freeform --boundary none
PYTHONPATH=src:. uv run python .superpowers/sdd/2026-09-08-general-abstraction-repairs/task-14-completion-probe.py clock --strategy sequence --boundary none
PYTHONPATH=src:. uv run python .superpowers/sdd/2026-09-08-general-abstraction-repairs/task-14-completion-probe.py clock --strategy hierarchy --boundary none
PYTHONPATH=src:. uv run python .superpowers/sdd/2026-09-08-general-abstraction-repairs/task-14-completion-probe.py clock --strategy freeform --boundary before_cleanup --offset 0.25
PYTHONPATH=src:. uv run python .superpowers/sdd/2026-09-08-general-abstraction-repairs/task-14-completion-probe.py clock --strategy sequence --boundary after_cleanup --offset 0.25
PYTHONPATH=src:. uv run python .superpowers/sdd/2026-09-08-general-abstraction-repairs/task-14-completion-probe.py clock --strategy hierarchy --boundary after_cleanup --offset 0.25
PYTHONPATH=src:. uv run python .superpowers/sdd/2026-09-08-general-abstraction-repairs/task-14-completion-probe.py clock --strategy freeform --boundary during_certification --offset 5.25
PYTHONPATH=src:. uv run python .superpowers/sdd/2026-09-08-general-abstraction-repairs/task-14-completion-probe.py clock --strategy sequence --boundary during_certification --offset 5.25
PYTHONPATH=src:. uv run python .superpowers/sdd/2026-09-08-general-abstraction-repairs/task-14-completion-probe.py clock --strategy hierarchy --boundary during_certification --offset 5.25
```

Complete clock matrix: strategies `{freeform, sequence, hierarchy}` × boundaries `{before_cleanup, after_cleanup, after_projection, during_certification}` × offsets `{0.25, 5.25}` relative to the parent's original deadline, plus the three `none` controls. All combinations use exactly the same executable/argument contract above. The script asserts the expected distinction on the ready specimen. A native search that cannot reach completion is reported as an unproved fixture, not mislabelled a clock refusal. Clock probes report original phase events, Report findings, and independent judgment of every actual certification and returned placement.

Expected policies, **not measured results**:

| Protocol | Parent expired but +5 remains | +5 expired after certification |
|---|---|---|
| Freeform | cleanup/projection/certification can complete | no completed return |
| SequencePair | cleanup/projection/certification can complete | no completed return |
| Hierarchy | cleanup/projection refuse while their cancellation callback still runs; after projection returns certification is admitted | existing uncancelled certification may still return |

## Implemented concrete two-phase API

Main explicitly required preserving Freeform's pre-certification incumbent gate, without callbacks, generators, strategy hooks, or ranking in the shared mechanism. The following operations are now implemented beside `BoundaryCompactionResult`:

- `prepare_placement_completion(placement, spec, policy, *, belt_rules, expect_power, deadlines) -> PlacementProjectionReady | PlacementProjectionRefused | PlacementCompletionCancelled` performs existing certified cleanup and projection only. The input must already have sorter slots assigned. `PlacementProjectionReady` owns the projected candidate plus its exact spec/rules/power context, any still-valid cleanup Report, and phase timings. Refusal preserves the existing `ProjectionFailure` tuple/check evidence; cancellation names the phase and exposes no successful-placement shape.
- `complete_placement(projected: PlacementProjectionReady) -> PlacementCompleted | PlacementInvalid | PlacementCertificationExpired` is the explicit continuation after the strategy's own projected-candidate gate. It reuses only the context-bound, still-valid Report; otherwise invokes `certify` once. Each variant with certification contains its actual candidate and Report. Only `PlacementCompleted` stamps the candidate. Invalid and expired-certified variants retain the uncompleted candidate/Report for honest refusal/telemetry and cannot be mistaken for successful output.
- A small concrete `PlacementCompletionDeadlines` record names `cleanup`, `projection`, and `acceptance` deadlines. Freeform and SequencePair pass `(D+5, D+5, D+5)`; hierarchy passes `(D, D, None)`. None is an explicit absent deadline, not an inferred grace. Existing strategy entry guards and timing/ranking/no-good logic remain where they are.
  The projection deadline must not become a new post-return certification-admission guard. The finalizer itself owns its strict callback polling; after it returns, only the distinct `acceptance` policy may reject. Hierarchy's None preserves both absent pre-certification and absent post-certification checks.
- Phase timing facts are cleanup/project/certify elapsed values, populated where the real operation ran (zero when certification was reused or not reached). No general-purpose timing/result framework.

Report ownership moves, rather than adds a second validity convention: certified cleanup receives the same required `belt_rules` and `expect_power` as completion and returns its Report bound to its placement. `prepare_placement_completion` retains it only when finalization returns that exact compacted placement object. A materialized placement discards the Report. The typed intermediate carries the same actual spec/rules/power policy into `complete_placement`, so continuation cannot accidentally supply a different policy. This uses the existing finalizer identity guarantee rather than geometry hashing or copying.

The required `belt_rules` context is migrated through all three strategy constructors, pipeline, benchmark/audit factories, race request/publication judgment, SequencePair islands and hierarchy child jobs. Generic `validate` retains its deliberate diagnostic defaults. SequencePair's finalizer signature inspection is removed; its related doubles now accept the real cancellation keyword. Direct certification/cleanup callers and constructor/request tests use concrete researched rules. Existing no-good, retry, funding, race lifecycle, and portable child policy behavior is retained.

## Source release and proof ownership

Main ran the baseline probes and explicitly released the shared boundaries after Task13. `prepare_placement_completion` and `complete_placement` are implemented; the commands below exercise their typed results. Disposable scripts/pickle remain only until Main's final proof and are not permanent test fixtures.

## Main-run baseline evidence

Main reports all three original modes EXIT0:

- `task-14-capture-baseline.log`: real raw wired candidate has 68 buildings; ready completed geometry has 62; independent judgment is clean. These are two naturally selected candidates, not proof that cleanup removed six buildings.
- `task-14-reuse-baseline.log`: neither original raw nor already-completed control returned a cached Report. Therefore the original controls did **not** exercise changed-report reuse; no redundant certification reduction is established.
- `task-14-gate-baseline.log`: 6 real projected candidates, 3 certifications, and 3 actual incumbent-gate rejections. This establishes the native pre-certification checkpoint that the two-phase cutover must preserve.

`task-14-reuse-leaf-baseline.log` now EXIT0: appending one actual isolated outer belt leaf to the clean wired geometry reaches changed cleanup and returns a real cached Report. Subsequent projection replaces the placement object, buildings, and frame; independent final judgment remains clean. The cached cleanup Report therefore must **not** be reused across that projection merely because `cached_ok` is true. This establishes the report-validity ownership boundary, not redundant-certification savings.

Exact complete 27-cell clock command:

```sh
PYTHONPATH=src:. uv run python .superpowers/sdd/2026-09-08-general-abstraction-repairs/task-14-clock-matrix.py
```

The runner enumerates all three neutral controls plus the full 3×4×2 matrix above, retains `task-14-clock-<strategy>-<boundary>-<offset>-baseline.log` per cell and `task-14-clock-matrix-baseline.json`, and reports any failed/unreached cell as unproved. It invokes the current environment's Python directly in each finite child; no independent source mutation or test suite occurs.

## Clock matrix classification and minimal correction

Analyzed all rows of `task-14-clock-matrix-baseline.json` and both failed per-cell logs. Exactly two rows failed: hierarchy `after_projection` at offsets 0.25 and 5.25. Both logs show cleanup finishing, projection finishing, the synthetic clock advancing **after the real finalizer returned**, real certification succeeding, and an independently clean returned placement. The only error was the disposable probe assertion that expected hierarchy refusal.

Source `hierarchy/strategy.py:896–905` confirms the cause: its strict cancellation callback applies inside finalization, but no poll occurs between finalization return and uncancelled certification. The probe conflated “during projection” with “after projection.” Production behavior is consistent and must remain unchanged.

Corrected only that expectation to admit hierarchy at both `after_projection` and `during_certification`; no source edit, deadline change, or validation relaxation. Preserve the original failed logs. Main should rerun **only** these cells into distinct corrected logs:

```sh
PYTHONPATH=src:. uv run python .superpowers/sdd/2026-09-08-general-abstraction-repairs/task-14-completion-probe.py clock --strategy hierarchy --boundary after_projection --offset 0.25
PYTHONPATH=src:. uv run python .superpowers/sdd/2026-09-08-general-abstraction-repairs/task-14-completion-probe.py clock --strategy hierarchy --boundary after_projection --offset 5.25
```

The remaining 25 rows exited zero. Main reran only the two corrected hierarchy cells, both EXIT0: an independently clean certified placement returns after projection at offsets 0.25 and 5.25, including beyond the other strategies' five-second grace. Original failed expectation logs remain retained. The full 27-case matrix is now classified, with no whole-matrix rerun requested. These are policy-boundary observations, not runtime improvements.

## Frozen implementation scope and post-cutover commands

Source ownership:

- `layout/finalize.py`: concrete preparation/completion variants, phase clocks/timings, exact geometry-bound Report reuse, required researched rules in certified cleanup and fallback.
- `layout/validate.py`: `certify` delegates to the single same-save `judge_placement` owner using required `belt_rules`.
- `layout/freeform.py`, `layout/sequence_solver.py`, `layout/hierarchy/strategy.py`: shared two-phase completion; Freeform retains its gate and post-observer deadline check; hierarchy retains composed-spec and whole-list slots and `(D,D,None)` policy.
- `layout/sequence_islands.py`, `layout/strategy_race.py`, `pipeline.py`, `bench/runner.py`: complete rule transport rather than independent bool/height fields.
- `scripts/audit.py`, `ab_compare.py`, `route_profile.py`, `route_bench.py`, `spawn_cost.py`: actual URL-derived rule transport and same-policy fallback cleanup.

All affected existing test constructor, request, cleanup, and direct certification calls are migrated. Test spies now intercept the single finalizer-owned certifier. The former SequencePair clean-compaction reuse test now sends physically changed projected geometry through the real certifier and requires rejection rather than reusing the earlier clean Report. A focused certificate regression distinguishes both altitude ceiling and vertical-construction policy. Existing race/pipeline tests that merely pinned field inventories, copied kwargs, or incidental object defaults were deleted rather than re-pinned to renamed fields. Task15 owns the composer tests separately below.

The disposable `completion` mode exercises raw, already-completed, and changed-cleanup geometry through the real typed operation, independently judges completed results, counts actual final certifications, rejects an unserved real output demand, preserves a real circumference projection refusal, and distinguishes researched altitude ceilings with real Reports. Main executed these assertions successfully; measured outcomes are recorded below. Clock instrumentation switches both strategy and shared completion clocks at the original native strategy boundary and observes the finalizer's concrete certifier; the full integrated matrix preserves the original expected policies.

Run from abstraction-general; use distinct `*-integrated.log` files, never overwrite baseline logs or `task-14-wired-fixture.pickle`. Do **not** run `capture` again.

```sh
PYTHONPATH=src:. uv run python .superpowers/sdd/2026-09-08-general-abstraction-repairs/task-14-completion-probe.py completion
PYTHONPATH=src:. uv run python .superpowers/sdd/2026-09-08-general-abstraction-repairs/task-14-completion-probe.py reuse
PYTHONPATH=src:. uv run python .superpowers/sdd/2026-09-08-general-abstraction-repairs/task-14-completion-probe.py gate
PYTHONPATH=src:. uv run python .superpowers/sdd/2026-09-08-general-abstraction-repairs/task-14-clock-matrix.py --label integrated
uv run pytest -q tests/layout/test_finalize.py::test_certification_applies_the_complete_save_belt_policy tests/layout/test_sequence_solver.py::test_sequence_completion_rejects_invalid_projection_after_clean_compaction tests/layout/test_sequence_solver.py::test_validator_finishes_inside_atomic_completion_grace tests/layout/test_sequence_solver.py::test_validator_crossing_atomic_completion_grace_returns_incomplete_budget tests/layout/test_sequence_solver.py::test_projection_crossing_deadline_returns_incomplete_budget tests/layout/test_freeform.py::test_sweep_validates_exact_compacted_and_finalized_placement_before_completion
```

The matrix owns 90-second child timeouts/process-group termination and writes only `*-integrated.log` plus `task-14-clock-matrix-integrated.json`. Main owns the final import/type/full-test gate and cleanup after actual proof. Nothing from the separately approved v6 hierarchy follow-on was absorbed.

## Main-run integrated evidence

Main reports EXIT0 for `task-14-completion-integrated.log`, `task-14-reuse-integrated.log`, and `task-14-gate-integrated.log`. Analysis of the retained JSON records establishes:

- Shared completion returns independently clean, stamped placements for the raw control (68 buildings, 18×16 frame), already-completed control (62 buildings, 16×16 frame), and removable-leaf case (50 buildings, 13×13 frame). Each performs exactly one final certification; none retains a cached Report at the projected-ready boundary.
- The separate reuse probe records a real clean cached Report only for changed cleanup in the removable-leaf case. Projection replaces the placement, buildings, and frame, and the shared completion correctly discards that earlier Report before its one final certification. The already-completed case preserves projection identity but has no cleanup Report to reuse. This proves invalidation, **not** a saved certification.
- Unserved real output demand produces `PlacementInvalid` with `flow.conservation`. The out-of-circumference geometry produces `PlacementProjectionRefused` with `game.blueprint_area`. Neither is stamped as completed.
- The altered linked-belt altitude produces `geom.altitude_range` under the strict researched ceiling and not under the relaxed ceiling. `sorter.endpoints` remains in **both** Reports: the probe does not hide its deliberately damaged connection or claim the relaxed geometry is clean.
- The native Freeform gate run records 9 projected candidates, 4 final certifications, 5 actual gate rejections, and 5 projected candidates without certification; its returned placement is independently clean. Baseline counts were 6/3/3. The retained gate behavior is proved; differing search-run counts are not a performance comparison.

`task-14-clock-matrix-integrated.json` records **27/27 EXIT0**, nine cases per strategy. Per-cell logs establish:

| Strategy | Neutral control | D+0.25 before/after cleanup or after projection | D+5.25 before/after cleanup or after projection | During certification |
|---|---|---|---|---|
| Freeform | clean return | clean return | refusal, zero final certifications | D+0.25 clean return; D+5.25 refusal after one actual certification |
| SequencePair | clean return | clean return | refusal, zero final certifications | D+0.25 clean return; D+5.25 refusal after one actual certification |
| Hierarchy | clean return | before/after cleanup refuse; after projection clean return | before/after cleanup refuse; after projection clean return | clean return at both offsets |

Every returned clock-case placement is independently clean. Hierarchy's absent post-projection/post-certification deadline check remains visible beyond the other strategies' grace; no deadline was widened to make this pass.

Main additionally reports Ruff fix/format applied to 30 files and Ruff check passing. Its first mypy run found the Freeform exception-binding local alias issue; Main removed the redundant `exc` alias and uses `projection.refusal.failures` directly at the three sites. The subsequent 106-file mypy gate is EXIT0 (`completion-static-final.log`). Seven focused cases passed in `completion-focused.log`; the corrected projected-refusal regression then passed separately (`completion-projected-refusal-final.log`). Main reports independent `CompletionContextReview` with no findings and all 280 belt-policy call sites accounted for. These subsequent gate/review results are Main-reported; this worker did not rerun validation or edit source. Trace/browser evidence belongs to its separate owner and is not relabelled as Task14 coverage.
