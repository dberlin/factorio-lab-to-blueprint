# Routing Reliability and Cost Reduction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. User approved execution on 2026-09-10; execution evidence is recorded in `.superpowers/sdd/2026-09-10-routing-reliability-and-cost/progress.md`.

**Goal:** Eliminate the captured commit-link failure mechanisms, reduce junction-frontier and power-planning costs without weakening legality, and demonstrate complete factories under the original workload contracts.

**Architecture:** Preserve the existing router, disposable commit transaction, hierarchy-owned settlement, and exact physical-flow certificate authority. Fix disagreement between selected routing choices and physical emission before optimizing the hot predicates. Make frontier and power changes independently measurable against frozen inputs; do not introduce a general incremental committer or a new search engine.

**Tech Stack:** Python >=3.14, existing NumPy/Cython/OR-Tools/Pydantic infrastructure, pytest, Ruff and mypy; no new dependencies.

**Spec:** The design contract below, the measured post-fix profiling section of `/home/dannyb/report2.md`, and the preserved lifecycle constraints in `2026-09-09-physical-admission-lifecycle.md` and its linked design.

**Status:** Execution and evidence collection complete; **overall final acceptance FAIL** because both original workload contracts fail all three repetitions. Component correctness/performance and five consecutive diagnostic captured compositions pass. The original electric-motor COMMIT_LINK mechanism remains independently unclassified. No master promotion is authorized.

## Global Constraints

- Worktree: `/home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/technology-routing`.
- Production edits target `.superpowers/router-geometric/candidate/src/flab2bp/`, not the worktree's ordinary `src` or master. Confirm import provenance before executing a gate. Another person's master integration is outside this plan; do not overwrite it or silently switch baselines.
- Preserve URLs, recipes/rates, machine rank, technology, source/destination ownership, mixed destination lanes, directed links, altitude profiles, belt/sorter capacities, projection rules, power coverage/connectivity and exact certification.
- Preserve original parent deadlines and expansion accounting, hierarchy completion deadlines `(deadline, deadline, None)`, atomic completion semantics, existing repair/RRR/CBS limits and `_COMMIT_REPAIR_PASSES=3`.
- No additional outer retry loop, budget escalation, global allocator, cross-build cache, GC disabling, invented stronger belt tier, or certificate bypass.
- Do not restore the rejected unconditional fork-before-merge policy. Legal low-load merge-before-fork routing must remain possible.
- Keep `RoutingFlowLimits`, `_flow_frontier_ranges`, constrained rational reconstruction and exact primal/dual checks intact unless a new independent correctness defect is demonstrated. Their measured cost is not the first optimization target.
- Reuse existing types and indexes; no untyped public mapping, compatibility alias or speculative framework. No module split solely because `routing_domain.py` is large.
- Before modifying an exported contract, inspect LSP references and all callers. If the known worktree LSP failure recurs, record it and use scoped source/AST inspection; do not trust incorrect server line numbers.
- Preserve Git configuration, including `diff.external`. No merge, push or master promotion is authorized by this plan.

## Design Contract

### Evidence and what it does not prove

The coarse successful probe spends 12.821s in `_merge_frontier`, 7.372s in power planning, 6.784s in final certification, 6.359s in overhead proposals, and 4.801s in the A* wrapper. New rate accounting costs 0.640s and cleanup 0.252s. About 80–81% of frontier time is `_can_junction` in both finer probes.

One successful probe commits once in 2.985s. The failed probe calls `_commit_paths` eight times for 21.021s, ending with copper-ingot block 13→16 and electric-motor block 22→23 COMMIT_LINK failures. These must be distinguished from the already-fixed exact-certificate problem and the old motor capacity deficit.

The three probes have different deadline-sensitive topologies. Their 59.944s, 73.088s and 70.436s wall times are not comparative benchmarks. The second also monitored a 1.9-million-call projection lambda, adding instrumentation cost. Use their attribution to select work, not to claim speedups.

### Chosen approach and rejected alternatives

1. **Chosen: fix commit semantics, then optimize exact local work.** Lowest architectural risk; directly addresses the measured costs and preserves all authorities.
2. **Defer: general incremental commit/settlement caching.** Could reduce repeated materialization, but link order, reverse feeders, ownership, cleanup lineage and projected frames make invalidation load-bearing. Establish the failure cause and remove failed retry amplification first.
3. **Reject for this work: replace A*, LP or the hierarchy scheduler.** The profiles do not support prioritizing those changes. Keep the decomposition goal and current search semantics.

### Required invariants

- A frozen selected attachment is either physically realizable under its exact context or rejected with truthful existing failure evidence. An approximate offer is not an authoritative construction certificate.
- `_commit_paths` continues to lay all belts, finalize sinks, attach sources, and check the final linked graph. Do not move checks earlier and remove the final check: later feeders can change collision exemptions.
- No failed transaction leaks belts, links, guards or ownership into the accepted canvas. Successful settlement transfers its accepted workspace without rebuilding it.
- Unknown/global causality remains unknown; never turn an inconclusive certificate or missing owner into a local geometric ban.
- Static geometry reuse must exclude live reservations, selected taps, occupancy changes and selected-frame-dependent results unless those dependencies are represented explicitly.
- Power site selection preserves the exact doubled-integer predicates, current common-frame projection checks, current connectivity semantics and lexicographic tie-break.

## File Ownership and Execution Order

All source paths in this table are beneath `.superpowers/router-geometric/candidate/src/flab2bp/`.

| Files/symbols | Responsibility |
|---|---|
| `layout/routing_domain.py`: `_route_all`, `commit_once`, `_commit_paths`, `_source_for`, `_sink_for`, `_tap_source` | Selected attachment realization, truthful failure feedback, bounded repair |
| Same file: `_merge_frontier`, `_can_junction`, `_Canvas._junction_geometry_is_clear`, `_building_collider_hits` | Exact candidate junction legality and static collider work |
| Same file: `plan_power_infill`, `_CompositionProjection` | Coverage selection and relay-ground preparation; projection authority unchanged |
| `layout/hierarchy/compose.py`: `_CompositionSettlement` | Integration/capture boundary only; retain settlement lifecycle |
| `tests/layout/test_freeform.py`, `tests/layout/hierarchy/test_compose.py` | Real routing, ownership, collision and power regressions |
| `tests/layout/test_physical_flow.py`, `tests/layout/test_validate.py` | Existing exact-flow and final acceptance guards; no planned semantics change |
| `.superpowers/wide-overhead-repair/` | Disposable replay harnesses, fixed input snapshots, source hashes and measured results |

Task 1 → Task 2 → Task 3 → Task 4 → Task 5 is the conservative integration order. Frontier and power investigations are independent after the frozen baseline, but all three production slices share `routing_domain.py`: one integration owner serializes edits. Do not dispatch concurrent same-file writers. Read-only review or separate diagnostic harness work may overlap. Delegated writers skip formatting, lint and suites; Main runs each integrated gate once. Do not create another nested worktree.

## Task 1: Freeze the failures and component workload

**Files:** Diagnostic harnesses and artifacts in `.superpowers/wide-overhead-repair/`; no permanent production mutation.

**Consumes:** `run.py`, `recapture-r1/compose-0.pickle`, `capacity-phase-profile-r{1,2,3}*`, `capacity-phase-verification.json`, current `_CommitFailure` records and the actual `_commit_paths` argument contract.

**Produces:** Replayable pre-commit inputs for each distinct failure mechanism, one known-success control, sampled frontier inputs, and raw pre-power canvases from a successfully settled factory. Each artifact includes source/native identities and technology/spec context. No new public interface.

- [ ] Freeze the current staged source and verify it matches the profiling manifest. Record Python/native versions, CPU affinity and imported source paths. Preserve the original recorded failures as ground truth; do not spend another full workload merely confirming that they exist.
- [ ] Add an external diagnostic wrapper at `_commit_paths`. Capture data-only argument state **before mutation**, including canvas buildings/occupancy/reservations/guards, nets, ordered paths, source/destination groups, source/sink hints, source taps, primitive witnesses and ownership. Rebuild native indexes, callbacks and derived caches through existing constructors on restoration; do not assume live closures or native workspace objects can be pickled. Verify restored state against the capture before drawing conclusions. After the real call, retain failed snapshots with all `_CommitFailure` fields: side, cell, tap, reason, blocking cells and owner indices. Keep one successful control. Do not add production logging or a second commit operation.
- [ ] Replay each retained pre-commit snapshot directly on a fresh restoration, without the router or a wall deadline. This is an explicitly diagnostic geometric replay, not a change to production clocks. Repeat three times and require the same failure mechanism. If a projected-selection refusal disappears, check captured deadline/cancellation evidence and restoration fidelity before classifying it; disappearance alone does not prove cancellation or a geometric defect.
- [ ] Find the first divergence: path emission, sink selection, feeder selection, splitter attachment, final stable-belt collision, or cycle check. Trace the corresponding selected offer and the final physical link graph. Do not assume copper and motor failures share a cause because both are COMMIT_LINK.
- [ ] Minimize each distinct geometric failure while retaining the shared provider/consumer relationships, reverse feeders, exact altitude and technology that cause it. Do not minimize by changing capacities or eliminating the final graph check.
- [ ] Capture representative `_merge_frontier`/junction inputs and raw `plan_power_infill` inputs from a successful composition. A post-infill placement is not a valid power-planner workload. Freeze current expected offers, provenance, selected power sites, final report and source identities.

**Gate:** Three direct deterministic reproductions per distinct geometric cause, a successful control, and a written cause-to-predicate map. If no geometric defect survives direct replay, diagnose the captured cancellation/state-transition path instead; do not invent an attachment fix. Capture instrumentation may affect routing deadlines, so only direct frozen replays support component comparisons.

## Task 2: Repair selected-attachment realization and feedback

**Files:** `routing_domain.py` commit/attachment/repair symbols listed above; `test_freeform.py`; `hierarchy/test_compose.py` when the cause crosses settlement ownership.

**Consumes:** Task 1 failure snapshots and exact cause-to-predicate map.

**Produces:** The same `_commit_paths(...) -> tuple[int, ...]`, `_CommitFailure`, `RouteOwnership` and `RouteSettlement` contracts, with the captured defect corrected. No new commit cache or retry limit.

- [ ] Keep one minimized regression per distinct observed defect. Assert observable linking/flow/physical legality and preserved unaffected consumers, not failure-message wording or helper invocation counts. Show it fails on the frozen baseline before the fix.
- [ ] Correct the actual divergence at its owner. For a hint/port mismatch, make the selected identity and committer interpretation agree. For a final-graph collision or cycle, reject or repair that exact contextual attachment using the existing feedback path. For stale-state failure, correct the state transition/ownership update. Do not weaken `_legal_link`, collider exemptions or final cycle checks.
- [ ] Reuse shared exact predicates when admission and emission ask the same question with the same information. Where only the completed graph has enough information, keep final commit authoritative and feed its real support into existing bounded repair; do not pretend a local preflight proves the completed graph.
- [ ] Preserve dependencies when a provider is ripped up: withdraw dependent hints, guards and capacity reservations through existing closure/unstake paths, then regenerate offers against live state. An unsuccessful attempt must lead to a changed supported choice or an honest refusal within the existing limits.
- [ ] Run the minimized replays and successful controls, then the real integration scenarios below. Verify full final certification, including belt and sorter flow. Keep direct-goal precedence, mixed destinations, valid merge-before-fork sharing and unaffected branches covered.

Existing regression anchors include `test_commit_link_rejection_reroutes_the_same_net_before_emission`, `test_commit_preflight_repairs_a_routed_net_while_another_remains_stranded`, `test_commit_rolls_back_a_failed_path_before_laying_later_paths`, and `test_route_feedback_preflight_commit_link_retains_exact_endpoint_evidence`.

**Gate:** Captured causes no longer fail; all previously valid controls remain valid; a complete captured composition settles with all checks. Do not declare the issue fixed because retry counts fell or a partial path was accepted. Keep unrelated commit paths unchanged.

## Task 3: Reduce exact junction-frontier cost

**Files:** `routing_domain.py` frontier/junction/index helpers; relevant existing routing and composition tests.

**Consumes:** Task 1 frozen frontier workload and Task 2 corrected attachment semantics.

**Produces:** Unchanged `_merge_frontier` inputs/results and exact endpoint provenance; a cheaper implementation of existing static geometry checks. No new frontier cap, lazy truncation policy or public type.

- [ ] Separate measured work into static cache misses, nearby selected-stack checks, live reservation checks and projected selection checks. Count distinct cells/model/altitude contexts in the diagnostic harness; no per-cell production timer. `junction_ok` already caches cell verdicts—do not add an equivalent second cache.
- [ ] On static misses, reuse immutable placed-collider data and the existing `Buildings.in_box` index. Avoid rebuilding the same placed geometry per stack member. Any prepared data belongs to the owning canvas/immutable prefix and must be rebuilt or invalidated when committed buildings change, including clones that receive new splitters. Never key correctness only by object identity or building count.
- [ ] Replace the full `planned_taps` scan only if its measured contribution warrants it: use a private spatial bucket index maintained alongside the existing tap-claim/unstake operations, with conservative nearby candidate enumeration followed by the unchanged exact collider test. Do not cache a dynamic admission verdict.
- [ ] Preserve whole-path altitude profiles, permitted capacity ranges, every legal offer and deterministic provenance. Do not introduce first-N candidate limits or cache results across a changed reservation/guard context.
- [ ] Differentially replay the frozen workload against baseline and candidate in separate processes. Compare complete offer sets, provenance/source choices and subsequent physical acceptance. Exercise exact collider boundaries, stacked model-40 mixed-height ports, existing splitters, live reservation changes, rip-up/restake and clone mutation. Keep only genuinely discriminating cases as permanent tests.

Existing anchors include `test_junction_clearance_uses_building_centre_at_exact_boundary`, `test_source_junction_stack_respects_live_port_reservation_ownership`, `test_composed_junction_admission_rejects_projected_copied_splitter_collision`, and the source/sink capacity-boundary tests already added to `test_freeform.py`.

**Performance gate:** At least 30% lower median frontier time on the same fixed workload across five alternating fresh-process baseline/candidate pairs, exact output parity, and no increase in peak memory above 10%. These are proposed engineering targets, not measured gains. If a proposed index/cache fails the gate, remove it rather than layering another cache over it.

## Task 4: Make power candidate scoring incremental

**Files:** `routing_domain.py::plan_power_infill`; existing power cases in `test_freeform.py` and `hierarchy/test_compose.py`. Keep `_CompositionProjection` legality unchanged.

**Consumes:** Frozen raw pre-infill canvases, spec/policy and current power rules.

**Produces:** The existing `plan_power_infill(...) -> (sites, uncovered)` result and failure/cancellation behavior, with unchanged exact decisions when allowed to finish.

- [ ] Build the initial unique coverage candidate domain once from the initially dark tiles and static free-site constraints. Current dark tiles only disappear; do not regenerate their overlapping dilation each round. Recheck changing keepouts, connectivity and common-frame projection against the current selected sites.
- [ ] Compute one integer coverage score per candidate using the existing doubled-centre squared-distance predicate. After selecting a site, enumerate only the tiles it newly covers and decrement affected candidate scores via the inverse coverage stencil and candidate-coordinate lookup. Do not store a dense candidate-by-tile incidence matrix or copy a coverage set for every candidate.
- [ ] Retain sorted-coordinate iteration and the strict-better-score rule. Evaluate current connectivity/projection only for a candidate whose score can improve the current winner. Compute the actual covered-tile set for the selected winner, then update scores. A temporarily unlinked or projection-refused candidate stays eligible for reconsideration after another site changes the context; do not permanently blacklist it.
- [ ] Accelerate relay-ground enumeration with a per-call ground-anchor legality mask derived from the existing footprint/blocked-column rules, using existing NumPy support. Keep the full finite canvas domain and lexicographic anchor order. Differentially compare the mask against scalar `free_site` at every anchor on frozen controls before using it. Selected-node keepouts remain a dynamic mask; exact projected admission remains the final gate. If an exact equivalent cannot be established, retain scalar enumeration rather than approximating legal ground.
- [ ] Prove selection/output parity on frozen inputs without deadlines, and cancellation responsiveness under the unchanged production clock. Include equal-coverage ties, nodes initially disconnected despite complete coverage, blocked/guarded footprints, mixed power-node link radii, selected-site keepout growth, and a site becoming usable after connectivity or reachable-frame changes. Verify emitted power through final coverage/connectivity/projection checks.

Core algorithm, retaining the existing decision rule:

```text
scores = exact coverage counts over the initial candidate domain
while dark tiles remain:
    best = none
    for site in lexicographic candidate order:
        skip unless its current score strictly improves best
        skip unless current keepout, link and common-frame checks pass
        best = site
    stop with the existing uncovered result if no site qualifies
    select best using the existing node/keepout update
    remove its newly covered tiles
    decrement scores of candidates covering each removed tile
```

Existing anchor: `test_composed_infill_selects_projected_legal_site_without_losing_power`; retain the clone/infill and substation-halo regressions as well. No test should assert cache hits, chosen container types or an incidental loop count.

**Performance gate:** At least 25% lower median total power-planner time on the same frozen raw canvases across five alternating fresh-process pairs, identical completed decisions, unchanged final legality, and peak memory within 10% of baseline. Include both coverage-heavy and connectivity-heavy controls; do not claim a relay optimization from a case that never reaches relay planning.

## Task 5: Integrate, verify and establish the remaining budget gap

**Files:** Integrated staged source/tests, diagnostic results, and `/home/dannyb/report2.md`. No new production feature.

**Consumes:** Reviewed Tasks 2–4 and frozen baseline evidence.

**Produces:** An evidence-backed pass/fail disposition for component correctness, captured composition reliability and both original workload contracts. A passing component benchmark is not factory completion.

- [ ] Run the focused gate after integration, in one process to preserve existing test-cache behavior and avoid oversubscribing solver workers:

```bash
env PYTHONPATH=.superpowers/router-geometric/candidate/src .venv/bin/python -B -m pytest -q -o addopts= tests/layout/test_validate.py tests/layout/test_physical_flow.py tests/layout/hierarchy/test_compose.py .superpowers/wide-overhead-repair/admission_regressions.py
env PYTHONPATH=.superpowers/router-geometric/candidate/src .venv/bin/python -B -m pytest -q -o addopts= tests/layout/test_freeform.py -k 'commit or frontier or junction or infill or source_hint or destination_merge'
```

- [ ] Run project Ruff formatting/lint once on changed files and mypy with the staged source root. Do not add suppressions for the existing missing OR-Tools typing metadata. Run the full relevant suite against the integrated source, comparing failures to a source-pinned baseline; report exact unresolved failures. The historical 73-failure run belongs to a rejected experiment, and only three were individually baseline-confirmed—do not call all 73 pre-existing. Do not silently deselect failing tests or claim a full-suite pass from the focused gate.
- [ ] Run five consecutive captured-composition attempts, without the added function/line profiling probes, using fresh processes, fixed affinity and the same source/input manifest. Each must finish 288/288 with `RouteSettlementCompleted`, zero validation errors, no skipped checks, and no uncovered power. Use distinct output names for each run:

```bash
env FLAB2BP_DIAGNOSTIC_SKIP_SHARED_FLOW=0 .venv/bin/python -B .superpowers/wide-overhead-repair/run.py remediation-composition-r1.json 120 --input .superpowers/wide-overhead-repair/recapture-r1/compose-0.pickle
```

The 120s allowance is diagnostic only. Record median/max wall time, settlement time, route/commit attempts, all check results and source identities. Keep failed trials in the denominator. Five successes support this repeatability gate, not a universal reliability claim.

- [ ] Run both original workloads three consecutive times with their exact existing 60s internal contract, 32 workers, original URLs/rank/strategy and capacity checks. Do not add the 120s captured allowance or change timeout semantics. Use a distinct `--out-name` each time:

```bash
env FLAB2BP_DIAGNOSTIC_SKIP_SHARED_FLOW=0 .venv/bin/python -B .superpowers/router-geometric/originals.py --control overhead --out-name originals-remediation-r1 --require-completion
```

Require exit 0, nonempty emitted blueprint, complete routing/settlement and all mandatory physical checks. Verify the emitted artifact decodes through the existing blueprint decoder rather than accepting a CLI log alone. Distinguish the internal budget from allowed atomic post-deadline completion; do not impose a new external 60s cutoff.

- [ ] Run two review rounds: first, focused correctness review of selected-attachment/ownership and frontier/power state invalidation; second, integrated review of actual source changes plus complete factory evidence. Reviewers do not run competing suites during mutation.
- [ ] If the original contracts still fail, record the remaining whole-factory stage breakdown and stop calling this a complete factory fix. Propose the next measured scope for approval; do not keep escalating budgets, add retries, or silently redesign the scheduler. The current composition profiles cannot prove these local changes alone will fit the entire original workload into 60s.

**Final acceptance:** Tasks 2–4 meet their correctness/performance gates; five captured replays complete; both original contracts pass three consecutive times; no newly introduced test/type/lint failure; unresolved baseline issues are explicitly recorded. No promotion to master without separate authorization.

## Plan Review and Scope Disposition

- Commit cost has a deterministic cause-discovery gate instead of a guessed patch.
- Frontier work targets exact geometry, not the already-small capacity accountant; existing static caching is acknowledged.
- Power scoring preserves dynamic admissibility and deterministic selection; relay acceleration requires exhaustive parity against the existing predicate on the captured domains.
- No proposed cache is reused across unrepresented mutation, and no final validator becomes optional.
- Component benchmarks use fixed inputs and alternating processes; deadline-sensitive end-to-end runs remain separate acceptance evidence.
- Admission/certification reuse, general incremental commit, GC suppression and A*/LP replacement are intentionally outside this design. Re-profile after the three changes before proposing any of them.
- User approved execution on 2026-09-10. This authorization does not include master promotion, merging or pushing.

## Execution Disposition — 2026-09-10

The criteria above remain the original contract; recording an executed gate does not turn its failing result into acceptance.

| Area | Measured disposition |
|---|---|
| Captured attachment mechanism | Graphite/copper deterministic failure reproduced; contextual source/sink admission repaired; legal upstream/far controls retained. Original motor mechanism unclassified, not asserted fixed. |
| Frontier | Five alternating pairs, exact full parity,40.828% median reduction; peak RSS increase below0.2%. |
| Total power | Five alternating pairs, exact ordered output parity,40.915% combined reduction. Small connectivity-only control improves3.20%, not an individual25% pass. |
| Captured composition | 5/5 completed288/288,67checks,zeroerrors,no skippedchecks,no uncovered power. Median55.064s,max57.477s under120s diagnostic allowance. |
| Original all-products | 0/3; exits3,no blueprint. |
| Original no-proliferator | 0/3; exits3,no blueprint. No emitted artifact to decode in either case. |
| Tests | Focused489passed. Broad2,618passed/90failed vs frozen baseline2,613passed/92failed; zero new failing IDs. Final targeted80passed/4baseline failures after removing two implementation-pinning cache tests. |
| Static/reviews | Ruff passes; scoped changed-file mypy passes. Two routing/power review rounds find no actionable patch defect. |
| Remaining budget | Corrected coarse original diagnostics enter composition after37.413s/28.169s, leaving24.735s/34.033s. All-products ends128/129; no-proliferator reaches288/288 but cancels settlement after3.423s. Successful captured settlement costs20.121–20.924s; differing routes prevent a direct speedup inference. |

Complete evidence, exact unresolved test IDs, limitations and the proposed next measured scope are in `/home/dannyb/report2.md` and `.superpowers/sdd/2026-09-10-routing-reliability-and-cost/progress.md`. All raw acceptance trials, including failures, are retained. Eight disposable scripts are archived and removed from the loose experiment directory; reusable replay harnesses remain. No new retries, deadline escalation, scheduler change, master edit, merge or push.
