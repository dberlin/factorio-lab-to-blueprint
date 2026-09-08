# General Abstraction Repairs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make algorithms independently changeable and faster to improve by giving shared contracts, mutable lifecycles and cross-component transformations one authoritative owner.

**Architecture:** Repair concrete policy drift at existing owners first. Make the already-shared prepared-routing and completion domains strategy-neutral after the separately approved transport/ownership repairs settle. Keep algorithm policies distinct; remove competing state and repeated adaptation, not merely repeated-looking text.

**Tech Stack:** Python>=3.14, uv, pytest, Ruff/mypy; TypeScript, React19, Zod4, Bun/Rstest, oxlint/oxfmt; existing indexed and DSP catalog APIs. No new dependencies.

**Spec:** [Algorithm-facing contracts and state ownership](../specs/2026-09-08-general-abstraction-repairs-design.md).

## Status, recommendation and scope

Approved for execution by the user on2026-09-08; execution started in isolated worktree `.claude/worktrees/abstraction-general`. The [original eight-task abstraction repair plan](2026-09-08-abstraction-repairs.md) remains the first separate tranche, retaining the two reproduced Piler fixes and all five other original dispositions. Independent request/physical-identity work starts alongside it; routing extraction still waits for its original-owner and v5 prerequisites. Nothing below replaces them.

Recommended: staged domain-owned cutovers. A bug-only pass would leave algorithm coupling and duplicate lifecycle state intact. A broad module-splitting/framework pass would add churn without demonstrating a better contract. This plan takes the middle path: each task below must remove a named coupling, policy divergence or duplicate authority. The routing-domain extraction is selected for that reason, not because Freeform is large.

The portfolio has four independently reviewable workstreams:

- **Request/judgment:** Tasks1–4. Correct intent and one save-policy contract.
- **Execution/measurement:** Tasks5–7. Reliable identities and resource lifetime.
- **Web publication:** Tasks8–12. One graph identity, trace closure and displayed-document authority.
- **Algorithm boundaries:** Tasks13–15. Shared routing, completion and packing feasibility.

Task16 verifies the integrated result. Each workstream can land independently once its dependencies pass; do not hold a sound branch for unrelated later work. The final coverage table explicitly defers two semantic questions instead of burying them.

## Global constraints

- Evidence baseline is `bbc8889d`; read the [general review bundle](../evidence/2026-09-08-abstraction-review/general-review.json), including coverage gaps. Only zero-objective parsing has an additional executed Main probe. Source-backed findings are not automatically reproduced runtime failures.
- **User's functional gate:** each retained abstraction must improve algorithm replaceability, invariant ownership, consumer adaptation or duplicated work/state. Reject cosmetic file splits, renaming campaigns, generic frameworks and wrappers that merely forward arguments without owning a contract.
- Use isolated worktrees at execution time. Reconcile the approved original repairs and hierarchical-v5 owner changes before touching their boundaries. Never modify the topology experiment worktree for this plan.
- Use LSP references before exported API changes and rename/move operations. Re-ground old line numbers against current source. Migrate all source/test/script consumers in the same cutover; no shims, compatibility aliases or deprecated re-exports.
- Reuse catalog, indexed, validator, finalizer and provider owners. Do not rebuild indexes, reload datasets or clone mutable snapshots per consumer. Immutable prepared facts are shared; per-attempt mutation is not.
- No recipe/item/URL special cases, mixed lanes, validator weakening, new backend, persistent cache, enlarged search domain, higher work bound or silently extended deadline.
- Preserve exact Fraction arithmetic and distinguish FactorioLab economic machine size, physical DSP footprint, projection clearance and artistic render dimensions.
- Preserve serial/raced exception semantics, benchmark timing/skip policies, original codec hash-table positions and local-portable versus composed-band policy.
- Python>=3.14 is required; do not add highspy alongside OR-Tools. Use repository-locked tooling. Current web lint is oxlint/oxfmt, not a presumed older formatter.
- Prove each change with the named consumer scenario. Keep a permanent regression only for a plausible observable failure; use temporary instrumentation for work/allocation evidence, not source-text or forwarding assertions.
- Main runs validation only after a mutation batch settles. Independent cases may run in parallel; retain failures and serially adjudicate those only. Bound comprehensive suites at150 seconds. Topology's narrower experimental policy remains topology-specific.

## File ownership and dependency contracts

| Owner | Files | Responsibility after cutover |
|---|---|---|
| Typed request adapter | `src/flab2bp/lab/url.py`, `src/flab2bp/pipeline.py` | Absent-value defaults; one authorized external-input set |
| Canonical physical identity | `src/flab2bp/rates/adjust.py`, existing `dsp/catalog.py` API | Physical footprint without ambient dataset/name cache |
| Save-specific judgment | `src/flab2bp/layout/validate.py` | Required BeltAltitudeRules translation at production-equivalent judgment |
| Compatible audit identity | new `src/flab2bp/bench/identity.py` | Typed audit-cell key, compatibility checks and duplicate rejection |
| Audit execution | `scripts/audit.py`, `scripts/audit_ab.py` | Terminal result per selected job and explicit hard-cap lifetime |
| Race execution | `src/flab2bp/layout/strategy_race.py` | Exception-safe acquisition through child/channel release |
| Trace transport | `src/flab2bp/web/trace.py`, `src/flab2bp/web/jobs.py` | Sampled graph consistency; collector-owned publication closure |
| Displayed document | `web/src/state/BlueprintProvider.tsx` | Atomic publication, source generation, document-local selection/error |
| Operational report facts | `web/src/api/build.ts`, `web/src/ui/BuildReport.tsx` | Winner/attempt instructions preserved through decode and display |
| Render model | `web/src/model/layout.ts` | Bounds matching actual instance transforms |
| Prepared routing | new `src/flab2bp/layout/routing_domain.py` plus existing indexed owners | Current shared prepared data, canvas/workspace and routing mechanisms independent of search strategies |
| Exact completion | `src/flab2bp/layout/finalize.py` | Existing compaction/report/projection/certification protocol, explicit phase windows |
| Composition packing | `src/flab2bp/layout/hierarchy/compose.py` | Skyline candidates consuming the existing band envelope |

Only two production files are proposed as new owners; the remaining work extends existing owners. `routing_domain.py` is not a target for relocating unrelated search code. If its dependency closure contains a separate pre-existing mechanism owner, reuse that owner rather than moving it twice.

Dependencies: Task4 serializes pipeline edits with Task2. Tasks5→6 share audit files. Tasks8→9 serialize trace.py; Tasks9/10 share the trace publication contract, but the client state work need not wait for backend implementation. Tasks10→11 serialize BuildPanel/report integration. Task13 waits for the approved original path/corridor repairs and reconciled v5 Coater changes. Tasks4+13→14; Task13→15. Tasks14/15 share hierarchy strategy and must coordinate one integration writer.

Review batches: request intent/physical identity (1–3), save judgment (4), measurement/lifetime (5–7), trace protocol (8–9), document/report/render (10–12), routing extraction (13), completion/band consumers (14–15), final integration (16). Split a batch if the actual semantic diff exceeds a useful review package. Do not create one review cycle per tiny file.

---

## Task1: Preserve explicit numeric intent at the request boundary

**Files:** modify `src/flab2bp/lab/url.py:_parse_objectives`; test `tests/lab/test_url.py` and the relevant rate consumer in `tests/rates/test_solve.py`. Read `lab/params.py:parse_rational`; leave its already-correct Optional contract alone.

**Contract/payoff:** URL conversion owns absent-versus-zero interpretation. The rate algorithm receives the user's exact constraint and needs no compensation for a lossy parser. This is a local bug fix, not a new numeric abstraction.

- [ ] Add a consumer case with an ordinary positive output and an Items Limit=0 objective; parse the bare and compressed forms using existing test helpers. Assert the limit stays exactly zero and `forbidden_inputs` includes that item. Preserve the missing-value default as a separate boundary case.
- [ ] Run `uv run pytest -q tests/lab/test_url.py tests/rates/test_solve.py -k 'zero or limit or missing' --tb=short` after naming the new cases accordingly. The existing Main probe already establishes the bare parser defect; do not rerun that unchanged probe merely to reconfirm it.
- [ ] Replace only the lossy objective adapter expression:

```python
parsed_value = P.parse_rational(_get(f, 1))
value = Fraction(1) if parsed_value is None else parsed_value
```

Pass `value` to the existing Objective constructor. Do not sweep every truthiness default in the codebase.
- [ ] Run the selected cases and a real parse→rate-constraint smoke. Explicit zero Output/Input must not become positive demand/supply; any unsupported objective mode must still be rejected by the rate domain rather than by the codec.
- [ ] Commit the coherent parser/consumer repair after proof; record exactly which existing behavior changed.

## Task2: Resolve external-input authorization once

**Files:** modify `src/flab2bp/pipeline.py` around candidate filtering and final selected-spec admission; reuse `src/flab2bp/lab/flow.py:unsupplied_inputs` and `rates.solve.supplied_rates`. Test `tests/test_pipeline.py` and `tests/lab/test_flow.py`.

**Contract/payoff:** the pipeline owns one immutable set of additional authorized inputs for this resolved request. Candidate filtering and the final defense-in-depth check consume it; neither reconstructs the policy from a different subset of request facts.

- [ ] Use an existing supplied-flow fixture with a partially supplied intermediate that is also crafted. Add a declared Input and exercise build admission; contrast one undeclared stray item. The former must be admitted at both boundaries and the latter refused. Capture the pre-change mismatch before changing source.
- [ ] Resolve the current policy once, preserving its conditional proliferator allowance:

```python
# request_supplies and proliferator_allowance come from the existing branches.
authorized_extra_inputs = frozenset(request_supplies) | proliferator_allowance
```

Both calls to `unsupplied_inputs` receive that same value through its existing exemption parameter. Flow's own `external_items` remains owned by Flow. Do not authorize inputs from whatever a candidate happens to require.
- [ ] Run `uv run pytest -q tests/test_pipeline.py tests/lab/test_flow.py -k 'suppl or input or proliferator' --tb=short`. Exercise the actual small build path for the partial-supply case and retain the final outcome, not a mock returning its arguments.
- [ ] Cover the existing external-proliferator asymmetry with its current flow/no-flow cases; remove the obsolete second exemption construction and commit the cutover.

## Task3: Use canonical DSP identity for physical machine area

**Files:** modify `src/flab2bp/rates/adjust.py:_footprints_by_lab_id,machine_footprint`; read physical area consumers in `rates/solve.py` and existing `dsp/catalog.py` identity/building APIs. Test `tests/rates/test_adjust.py`, `tests/rates/test_solve.py`; leave `tests/lab/test_machine_size.py` economic semantics unchanged.

**Contract/payoff:** physical footprint resolution no longer loads an unrelated ambient dataset, matches display names, maintains its own alias table or silently gives an unknown machine zero area.

- [ ] Add a renamed-display-label fixture with the same canonical machine IDs; compare physical area with the original dataset. Exercise a known catalog alias, an unknown real machine and the explicitly nonphysical extraction case. Unknown physical identity must fail deliberately; extraction remains its existing explicit zero-area override.
- [ ] Replace the dataset/name resolver with the existing catalog identity→building footprint operation. Delete `_NAME_ALIASES`, `_footprints_by_lab_id` and their process-wide cache once all references migrate. Keep `machine_footprint` as the domain operation if consumers still need it; no second catalog wrapper chain.
- [ ] Do not change `_objective_coefficients` economic machine-size cost or any exact recipe arithmetic. Run `uv run pytest -q tests/rates/test_adjust.py tests/rates/test_solve.py tests/lab/test_machine_size.py -k 'footprint or area or extraction or size' --tb=short`.
- [ ] In a throwaway cold-process probe, make ambient `load_dataset` unavailable and compute the known machine area from the supplied dataset/catalog path. Observe the correct area without an extra load. This instrumentation is proof, not a permanent test of call counts. Commit after the consumer result passes.

## Task4: Give production-equivalent judges a required save-policy contract

**Files:** modify `src/flab2bp/layout/validate.py`, `src/flab2bp/pipeline.py`, `src/flab2bp/bench/runner.py`, `scripts/audit.py`, `scripts/ab_compare.py`; migrate constructor/worker records where they currently discard the resolved object. Tests: `tests/bench/test_runner.py`, `tests/test_audit.py`, `tests/test_pipeline.py`, existing validator cases.

**Interface:** add `judge_placement(placement: Placement, spec: BuildSpec, *, ids: IdMap, belt_rules: catalog.BeltAltitudeRules, expect_power: bool) -> Report` in the existing validation module. This boundary owns the required save-policy→validator-arguments adaptation; it is not a generic forwarding utility. `validate` remains the arbitrary-placement diagnostic API with its documented defaults.

```python
return validate(
    placement, spec, ids=ids, expect_power=expect_power,
    max_belt_z=belt_rules.max_z,
    belt_vertical_construction=belt_rules.vertical_construction,
)
```

**Payoff:** the same immutable resolved rules reach construction and judgment; benchmark callers cannot silently omit half the policy while claiming a production-equivalent verdict.

- [ ] Use a restricted-tech URL and a physically meaningful placement that violates its slope/height policy but is otherwise judged equivalently. Exercise production, audit, bench and A/B judgment seams, distinguishing their existing skip handling. Confirm the two reviewed omissions before editing; retain unrestricted control results.
- [ ] Resolve `BeltAltitudeRules` once per URL; pass it through worker records rather than resolving again or retaining only `vertical_construction`. Algorithms may read individual fields in hot loops. At the public construction boundary, replace redundant partial-policy inputs where the full object is now authoritative and migrate callers cleanly.
- [ ] Implement `judge_placement` and migrate all four production-equivalent judge consumers. Pass already-resolved IdMap where present; do not build a second index/context just to call the helper. Internal strategy completion migration belongs to Task14; do not leave a final benchmark omission pending that larger refactor.
- [ ] Run focused restricted/unrestricted judgment cases, then the affected settled modules. The restricted placement must be rejected by the same physical policy everywhere; verdict strictness for skipped checks and timing/encode/decode scope remain intentionally different.
- [ ] Commit the policy cutover. Do not claim a new production emission bug: the production final validator already passed these researched rules.

## Task5: Make audit comparison identity lossless and duplicate rejecting

**Files:** create `src/flab2bp/bench/identity.py`; modify compatible audit schema/producer consumers in `scripts/audit.py`, `scripts/audit_compare.py`, `scripts/benchmark_projection.py`; modify `src/flab2bp/bench/ab.py:compare` only for its power-scope guard. Tests: `tests/test_audit.py`, `tests/bench/test_ab.py`; add identity cases beside the existing comparison tests rather than a source-import assertion.

**Interface:** `AuditCellKey(strategy: str, url_id: str, spec_index: int, spec_label: str, budget: float, power: bool)`, frozen and slotted. One `index_audit_cells` operation rejects duplicate keys before comparison. Its row type uses the audit fields already emitted: `strategy,url_id,spec_index,spec_label,budget,power,machine_rank,power_tower`. Configuration compatibility is explicit metadata, not silently discarded and not a key on source commit/treatment arm.

```python
if key in indexed:
    raise ValueError(f"duplicate audit cell: {key}")
indexed[key] = row
```

**Payoff:** comparator algorithms can change independently of JSON ordering without accidentally pairing different budgets/candidates. No consumer reconstructs a weaker three-field key.

- [ ] Build a small persisted pair with reordered4/30-second rows, duplicate identities and changed candidate labels. Assert each budget pairs to itself, duplicates fail before counts are credited, and changed candidate/tower/rank scope produces explicit incompatibility unless declared as the experiment's treatment.
- [ ] Reuse projection/promotion's existing strict-scope conventions, not their scoring engines. Share identity only where schemas match. Preserve legacy per-URL regression as a distinct contract. `ab.compare` must select one explicit power scope or reject mixed power; do not bucket them together.
- [ ] Missing identity fields in older evidence must be rejected as insufficient for an exact comparison, not defaulted to a plausible current value. Preserve old evidence files unchanged; an explicitly less strict legacy report is not promoted to an exact gate.
- [ ] Run the actual comparison CLI over the small files and relevant audit/AB tests. Record paired semantic keys and failures, not raw row-count equality. Commit the owner and compatible consumers together.

## Task6: Make audit termination and accounting job owned

**Files:** modify `scripts/audit.py` parallel run/timeout/summary, and `scripts/audit_ab.py` if summary consumption changes; tests in `tests/test_audit.py`. Consume Task5 identity where appropriate, but distinguish pre-result job identity from a result-derived spec label.

**Lifetime scope:** the hard-cap supervisor must own nested layout children as well as audit workers. Establish process-group/resource ownership when spawning; killing only an executor worker can orphan its children. Never terminate an unverified process by guessed PID.

**Decision:** `--max-seconds` remains a hard whole-audit cap, not a stop-waiting hint followed by unbounded executor context shutdown. Stop outstanding supervised work at the cap, preserve already-completed results, and explicitly report terminated/unreached jobs. Do not change each layout attempt's search/completion budget.

**Contract/payoff:** one authoritative terminal result per selected job. Out-of-order completion cannot turn a count into an imaginary submission-order prefix.

```python
unsettled = selected_job_ids - terminal_results.keys()
# Tally each unsettled ID through its actual selected job, never jobs[done:].
```

- [ ] Run a deterministic reverse-completion probe with two strategies and an outer timeout. Show the old attribution error and actual process lifetime separately; no load-dependent sleeps as the sole ordering control.
- [ ] Replace the completion-prefix bookkeeping with job→future and job→terminal-result ownership. Harvest futures already terminal at the cutoff once, then close admission and terminate/join remaining owned workers using the supported Python3.14 lifecycle. Publish each terminal row at most once.
- [ ] Ensure the outer guard covers the advertised audit duration, including whichever preparation phases currently fall within that promise. If preparation is synchronous, measure/check that phase explicitly rather than promising a process cap implemented only around result waiting.
- [ ] Assert selected jobs equal recorded outcomes plus explicitly terminated/unreached jobs for each strategy; no CLEAN credit for dropped rows. Exercise actual slow workers and observe that children stop under the cap plus measured bounded teardown, not an indefinite context-manager wait.
- [ ] Run `uv run pytest -q tests/test_audit.py --tb=short` after settlement, update any changed CLI summary consumer and commit. Do not invent a reusable experiment scheduler for this local ledger.

## Task7: Close race resources on partial acquisition and interrupted collection

**Files:** modify `src/flab2bp/layout/strategy_race.py:_pool_submit,run_strategy_race`; inspect actual `pipeline.py:_run_race` consumers without changing their failure policy. Test `tests/layout/test_strategy_race.py`.

**Contract/payoff:** the code that acquires an executor owns it until returned to a guarded collector; every exit releases children before their channels. No executor can be lost between construction and the second submit.

- [ ] Fault the second submission after a real first worker signals started. Separately interrupt the parent while waiting. Observe child termination and propagation of the original failure. These are probe-gated risks, not already measured leaks.
- [ ] Put partial submission under an exception guard inside `_pool_submit`; use the existing termination helper rather than waiting indefinitely for submitted work on an exceptional exit.
- [ ] Put the whole parent collection lifetime under a finalizer that releases the executor on normal, timeout and exceptional paths, then releases owned trace/sharing channels. Remove competing shutdown paths only after preserving their semantics; cleanup errors must not mask the original exception.
- [ ] Preserve the injected submit seam, deterministic arm ordering, valid-peer survival, one-arm refusal and all-arm-crash rethrow. Do not normalize the serial pipeline's ordinary exceptions into race result records. Do not edit islands without a separate demonstrated ownership defect.
- [ ] Run the two real fault probes plus `uv run pytest -q tests/layout/test_strategy_race.py --tb=short`. Commit only after no owned worker remains active and expected failures still propagate.

## Task8: Encode a self-consistent sampled trace graph

**Files:** modify `src/flab2bp/web/trace.py:frame_json,building_row`; test `tests/web/test_trace.py`, `web/tests/model/traceScene.test.ts`, `web/tests/model/beltGraph.test.ts`. Client adapter changes only if its assumptions need clarification; no backend placement-index changes.

**Decision/interface:** retain dense scene indexes and the current ten-number trace-row wire shape. During sampling, the encoder maps original indexes to dense retained indexes; links to omitted targets become the existing `-1` sentinel. Unsampled links remain unchanged. This avoids a second inspector identity system and preserves compact positional JSON.

```python
original_count = len(original_buildings)
# For each retained row's input/output target; sampling is a uniform stride.
wire_target = (
    original_target // step
    if original_target is not None
    and 0 <= original_target < original_count
    and original_target % step == 0
    else -1
)
```

Iterate retained indexes without copying the full building sequence. Uniform-stride sampling permits this arithmetic remap without allocating an old-to-new dictionary per frame. Keep the transformation on the collector thread.

**Payoff:** graph/render algorithms consume a coherent graph without per-consumer repair or accidental old-index aliasing.

- [ ] Create a frame above TRACE_MAX_BUILDINGS with known retained→retained and retained→omitted links whose old indexes would alias another dense row. Assert actual reconstructed successor/sorter targets, not just tuple lengths.
- [ ] Implement encoder remapping and preserve the truncated label/sampling bound. Standalone `building_row` remains literal encoding; `frame_json` owns the sampling transform.
- [ ] Run `uv run pytest -q tests/web/test_trace.py --tb=short` and `bun run test tests/model/traceScene.test.ts tests/model/beltGraph.test.ts` from `web`.
- [ ] Render the sampled scene in the browser and inspect the known branches/omitted endpoints. No edge may attach to a different retained building. Commit the protocol repair without expanding trace payloads to the entire factory.

## Task9: Let the collector publish trace closure

**Files:** modify `src/flab2bp/web/trace.py:TraceCollector`, `src/flab2bp/web/jobs.py:Builder._run,trace_page`; update `web/src/api/trace.ts` only if the existing wire contract needs explicit typing/documentation. Tests: `tests/web/test_trace.py`, `tests/web/test_jobs.py`, `web/tests/ui/TracePanel.test.tsx`.

**Interface:** collector exposes thread-safe `closed: bool`; `stop() -> bool` reports whether draining/reader termination actually finished. `TracePage.complete` means publication is closed **and** this cursor has no unread frames, not merely that the solver job is terminal.

```python
complete = collector_closed and not unread_frames
```

**Payoff:** one lifecycle owner replaces inference from another subsystem's state. Clients can keep the ordinary drain-until-complete loop.

- [ ] Deterministically pause final drain after job terminal publication. Poll an empty cursor, release one queued final frame, then close. The first empty poll must remain incomplete; the final frame must arrive; only the closed/exhausted page is complete.
- [ ] Make queue closure follow actual reader termination. A timed-out stop cannot close a queue still being read or claim closure. Keep the collector owned and allow the reader to finish; represent a real collector failure explicitly rather than fabricating successful drain. Preserve ring eviction/drop accounting.
- [ ] Run focused server lifecycle and client polling cases; use the actual browser to confirm the last frame remains selectable after solver completion. Do not keep a completed solver job artificially running or stop trace polling early to hide the race.
- [ ] Commit the collector/job contract before integrating automatic canvas publication.

## Task10: Give displayed documents one atomic publication owner

**Files:** modify `web/src/state/BlueprintProvider.tsx`, `web/src/ui/BuildPanel.tsx`, `TracePanel.tsx`, `InputPanel.tsx`, and provenance/selection consumers in `Toolbar.tsx`, `InfoPanel.tsx`. Tests: existing provider/BuildPanel/TracePanel/InputPanel suites.

**Interface:** provider owns a discriminated `DisplayedDocument` (`artifact` versus `trace`), monotonically increasing source generation, and stable publication actions. Artifact contains the actual decoded Blueprint/provenance; trace contains synthetic Blueprint/frame/job identity and is non-pasteable. Document-local error/selection reset in the same successful publication. Form state and solver jobs stay outside the provider.

**Transition contract:** async import/build starts capture a generation. Automatic publication requires that generation still own the canvas. Publishing the final artifact ends automatic trace publication for that generation; explicit later scrubbing acquires a new display generation. A newer manual load wins over an older asynchronous completion. Failure may retain the previous canvas according to existing behavior.

```typescript
if (publication.generation !== currentGeneration) return;
// One state transition publishes document, provenance, frame and fresh selection.
```

**Payoff:** producers publish documents against one authority instead of synchronizing independent blueprint/frame/error/selection fields and repairing stale writes individually.

- [ ] Add deterministic consumer transitions: final artifact then late trace page; slow URL import then newer manual paste; prior invalid parse/selection then explicit trace selection. Assert displayed/copyable document and selected entity, not callback invocation counts.
- [ ] Replace `load`/`loadSnapshot` competing writers with the provider's generation-aware publication actions and migrate every caller using LSP. Keep trace collection independent of display; final result selection must not discard last-frame transport.
- [ ] Show checksum validation only for encoded artifacts; a synthetic trace's `hashValid=false` is not a checksum mismatch. Preserve the non-pasteable snapshot distinction in copy/export controls.
- [ ] Run affected component suites once settled. In a browser, exercise all three transitions and deliberate post-result scrubbing. Stop watching must remain different from cancel solving. Commit after the actual surface stays on the intended document.

## Task11: Preserve actionable attempt facts through decode and display

**Files:** modify `web/src/api/build.ts` and `web/src/ui/BuildReport.tsx`; adjust `BuildPanel.tsx` selected-attempt adaptation if needed. Read `src/flab2bp/web/payload.py:_self_loop_seeds,_belt_tiers,_attempt_detail,describe`; consolidate Python facts only if it removes an actual second construction. Tests: `tests/web/test_payload.py`, `web/tests/api/build.test.ts`, `web/tests/ui/BuildReport.test.tsx`.

**Interface:** one client `AttemptFacts` schema is composed into winner and attempt result schemas and consumed directly by the report view. Include the existing wire `self_loop_seeds` and `belt_tiers.entry_lanes` fields with their exact server types. Keep global flow/research provenance separate from attempt-local facts; do not generate a cross-language schema framework.

**Payoff:** the operational contract no longer disappears through Zod's unknown-field stripping or a manually copied winner→attempt object. Adding an actionable attempt fact has one client owner.

- [ ] Feed an actual-shaped decoded payload with a seed amount, recipe/machine/head coordinates and entry-lane counts. Select a losing attempt with different facts. Assert each selection shows its own instructions and that seeds are labeled PRIME ONCE rather than permanent external inputs.
- [ ] Define the schema from the existing serialized fields, compose both result forms from it, and remove the redundant winner facts copy. Preserve exact rational strings and invalid-artifact withholding. Do not globally reject unknown response fields.
- [ ] Run the payload/schema/report cases. In the browser verify winner and selected-attempt priming/lane instructions, including the no-seed case without a misleading ongoing-supply warning. Commit the contract and its presentation together.

## Task12: Make scene bounds obey the actual render transform

**Files:** modify `web/src/model/layout.ts:buildSceneModel`; read `web/src/scene/BuildingInstances.tsx` and `CameraRig.tsx`. Tests: `web/tests/model/layout.test.ts`, `web/tests/scene/camera.test.ts`.

**Contract/payoff:** camera framing consumes bounds of the same oriented boxes the renderer draws. Fix the local calculation; do not create another general geometry module.

```typescript
const c = Math.abs(Math.cos(yawRad));
const s = Math.abs(Math.sin(yawRad));
const extentX = c * size[0] + s * size[2];
const extentZ = s * size[0] + c * size[2];
```

Use these full extents around the already-transformed center, with the existing half-size convention at bounds expansion. Reuse computed trigonometry where available.

- [ ] Use separated rectangular instances at0,90 and a non-quarter-turn yaw. Compare every transformed box corner with model bounds and framing; an isolated rectangle's invariant diagonal is not a discriminating case.
- [ ] Apply the local correction without changing catalog physical dimensions, visual scale or instance transforms. Run the two focused files from `web`.
- [ ] Frame the actual scene in the browser and confirm all separated objects fit. Commit as a small correctness repair, not as justification for a broader visual/physical unification.

## Task13: Move the existing shared routing domain out of the Freeform strategy

**Prerequisites:** approved original transport/path/corridor repairs reconciled; hierarchical-v5 actual-Coater keepout owner reconciled. This task changes ownership, not those algorithms again.

**Files:** create `src/flab2bp/layout/routing_domain.py`; modify `freeform.py`, `sequence_solver.py`, `global_router.py`, `hierarchy/compose.py` and current shared-routing consumers/tests discovered by LSP. Reuse `layout/buildings.py`, `indexed/nets.py`, `indexed/staked_paths.py`, `indexed/port_reservations.py` owners.

**Interfaces:** move the existing `_PreparedNet`, `_PreparedRoutingProblem`, `_RoutingWorkspace`, shared canvas/grid/port types and their preparation/workspace/transition/detailed-route entry points into the domain owner, retaining their current argument/result semantics. Use symbol-aware rename if public names are chosen; publish the exact move map in the review package before parallel consumer edits. No consumer imports these mechanisms through Freeform after cutover; no moved mechanism imports a search strategy.

**Payoff:** global relaxed routing, detailed routing and composition can evolve without importing a competitor's strategy implementation. One immutable compatibility snapshot and one fresh mutation workspace serve each attempt; no algorithm-specific copy of shared eligibility facts.

- [ ] Inventory the full dependency closure and incoming references using LSP. Separate truly shared mechanisms from CP-SAT/pack-window/ALNS/annealing/variant-selection code. Record the narrow move map; if a proposed move requires a domain→strategy import, move the shared fact owner or pass the existing domain input rather than adding a callback framework.
- [ ] Freeze small actual prepared fixtures covering source sharing, external arrivals, cargo incompatibility and early/late outputs. Run existing relaxed and detailed paths and record connectivity, cut/overflow/refusal outcomes and preparation cost. Use the current original repair owners; do not resurrect baseline Piler defects for comparison.
- [ ] Move the complete domain slice and migrate all consumers. A composer must be able to construct a canvas from placed blocks without pretending they are strips. Compatibility groups stay frozen once; each detailed attempt gets fresh mutable state. Delete obsolete import/re-export paths.
- [ ] Re-run those same actual routing cases, including two attempts against one snapshot with one interrupted/rejected. Their outcomes must not contaminate each other. Preserve independent relaxed-capacity status and detailed physical legality; the neutral validator must not depend on planner acceptance.
- [ ] Use throwaway instrumentation to check no extra full snapshot/index construction, copying or per-transition allocation was introduced. Run affected modules once settled, then review and commit the domain cutover. Do not require an arbitrary speed percentage to justify removing real algorithm coupling.

## Task14: Consolidate exact completion without merging search policy

**Files:** modify `src/flab2bp/layout/finalize.py` beside `BoundaryCompactionResult`, `layout/validate.py:certify`, and the completion blocks in `freeform.py`, `sequence_solver.py`, `hierarchy/strategy.py`. Tests: `tests/layout/test_finalize.py`, `test_freeform.py`, `test_sequence_solver.py`, `hierarchy/test_strategy.py`. Depends on Tasks4 and13.

**Interface:** `complete_placement` consumes a slot-assigned Placement, its actual BuildSpec, BandPolicy, required BeltAltitudeRules/power policy, and explicit projection/completion phase deadlines. Return a typed `PlacementCompletionResult` containing the candidate placement and Report when certification ran, existing projection refusal/cancellation evidence when it did not, and current phase timing facts needed by callers. Use distinct result variants so a caller cannot confuse uncertified projection failure with a completed placement. Define the variants beside this operation, not in a generic result framework.

**Clock decision:** extract current phase-window choices explicitly first. Freeform/SequencePair retain their existing atomic completion windows; hierarchy retains its current stricter projection window. Do not silently give hierarchy more projection time. An absent existing post-certification deadline remains an explicit policy distinction in the first cutover, not an implicitly repaired timeout claim. Any unification of that policy needs a separate measured ruling.

**Payoff:** cleanup, projection, valid report reuse and completion stamping have one mechanism. Search strategies retain ranking, projection no-good learning and retry decisions rather than each implementing completion differently.

- [ ] Probe the current three protocols with equivalent wired placements and controlled clocks: expiry before cleanup, between cleanup/projection, and during certification. Record intentional clock differences separately from invalid completion/report reuse. Keep hierarchy's composed-spec recalculation and full-composed-list sorter assignment before the shared operation.
- [ ] Implement the shared operation by composing existing certified compaction, finalization and Task4 save judgment. Preserve `BoundaryCompactionResult`'s exact report validity contract. Reuse only a report valid for the returned geometry and the same save/power policy; otherwise certify once at the correct boundary. Do not invent structural hashes or copy whole placements to decide reuse.
- [ ] Evolve `certify` to require researched rules for strategy certification and migrate its complete consumer set; generic `validate` remains the deliberate no-URL diagnostic seam. Remove SequencePair's finalizer-signature introspection and update test doubles to the real typed callable rather than keeping a production compatibility path.
- [ ] Migrate the three completion blocks. Only successful certified output receives the existing completed stamp. Projection failures and invalid reports still feed each strategy's existing refusal/continued-search logic; no fallback placement is returned.
- [ ] Run changed/unchanged compaction, projection refusal, invalid-flow and clock cases through the actual shared completion path. Independently certify any reused report's returned geometry under the same rules. Record eliminated redundant certification work where demonstrated; preserve failures and do not claim a clock improvement from extraction alone. Commit after the integrated strategy cases pass.

## Task15: Make final composition packing consume the existing band envelope

**Files:** modify `src/flab2bp/layout/hierarchy/compose.py:pack_blocks,_pack_at,pack_with_access,compose`, `hierarchy/strategy.py` caller; consume `layout/finalize.py:BandPolicySearchEnvelope`. Tests: `tests/layout/hierarchy/test_compose.py`, `test_strategy.py`, `tests/layout/test_finalize.py`. Depends on Task13; serialize strategy mutation with Task14.

**Contract:** resolve the final requested envelope once and thread it to skyline candidate selection. `envelope.frame_candidates(width, height)` is the feasibility query. Keep the current finite width/gap/rung candidates, skyline algorithm and area tie-breaking; prefer exact-envelope-compatible candidates before incompatible diagnostic fallbacks. Block-local backends remain portable because later translation invalidates local latitude certificates.

**Payoff:** changing band feasibility in its real owner no longer requires a second surrogate in hierarchy, and bounded routing is not knowingly spent on an inferior aspect ratio excluded by the requested envelope.

- [ ] Construct a fixed narrow-band block set whose existing candidate domain contains both fitting and non-fitting aspect ratios. Capture which candidate reaches routing. Include rotated fit and circumference overflow. Without this discriminating witness, report the policy-threading risk as unproved rather than claiming improved success.
- [ ] Thread the envelope and replace `min(width,height)<=160` admission with the existing frame-candidate question. Count only geometry guaranteed to belong to the composed extent; do not add an optional full routing margin as a fictitious permanent rim.
- [ ] Remove `BAND_MAX_ROWS` as a production authority if no legitimate consumer remains. Do not expand width candidates, change portable child policy or skip final projection. A fitting pre-route box does not guarantee routed belts/power/colliders will fit.
- [ ] Run the exact packing→routing witness and focused hierarchy/finalizer cases. Compare selected physical extent and final outcome under the unchanged budget. If the existing domain contains no fitting packing, retain the refusal; this is not authorization for a new packing algorithm. Commit the bounded contract change with that result.

## Task16: Verify integrated contracts and preserve truthful acceptance

**Files:** all affected source/tests from the landed workstreams; evidence under `docs/superpowers/evidence/2026-09-08-general-abstraction-repairs/`; update this plan's status and `~/report.md` after actual results.

- [ ] Freeze the reconciled source and collect one review package per semantic batch. Resolve load-bearing findings with focused proof; final independent review checks the whole changed contract set. Do not retest unrelated branches merely because their evidence predates a documentation edit.
- [ ] Run Ruff/mypy for affected Python source, web `bun run typecheck`, `bun run lint`, and settled affected test modules with captured exits. Run web build/browser verification against that same source. Use the current package scripts, not historical tool names. A comprehensive suite is bounded at150 seconds; timeout is not PASS.
- [ ] Exercise real small CLI builds for the affected strategies and explicit restricted/unrestricted save policy, plus the named browser transitions and audit/race lifecycle scenarios. Algorithm extraction gets the frozen prepared-input comparison from Task13. Do not substitute mocks, import checks or a new corpus run for the causal scenarios.
- [ ] Report contract outcomes separately from factory target outcomes. Existing Universe/topology and v5 residual failures remain FAIL unless their own required end-to-end gates actually pass. General refactoring cannot retroactively certify an old invalid capture or an un-emitted factory.
- [ ] After smoke proof, remove disposable instrumentation, retain minimal useful evidence/regressions and update affected API/use documentation. Record each retained abstraction's actual eliminated coupling/authority/work; reject additions that ended up merely moving boilerplate around.

## Coverage and explicit deferrals

| General review finding | Disposition | Why it qualifies / why deferred |
|---|---|---|
| Domain1 zero objective | Task1 | Preserves exact algorithm input; no new abstraction |
| Domain2 machine overrides | Deferred semantic repair | Establish FactorioLab objective-versus-recipe precedence and exact/up-to pinning before choosing behavior |
| Domain3 external authorization | Task2 | One policy answer at both admission boundaries |
| Domain4 ambient footprint resolver | Task3 | Removes extra dataset/name identity authority and work |
| Domain5 nested aliases | Deferred with Domain2 | Typed nested identity/collision policy needs authoritative fixtures; no generic recursive rewriting |
| Orchestration1 save judgment | Task4; internal completion in14 | Required existing immutable rules, one adapter |
| Orchestration2 benchmark identity | Task5 | Lossless comparison contract and duplicate rejection |
| Orchestration3 audit timeout | Task6 | Job-owned terminal ledger and process lifetime |
| Orchestration4 race resources | Task7, fault-probe first | One acquisition-to-release owner |
| Web1 canvas authority | Task10 | Atomic generation-aware document publication |
| Web2 trace identity | Task8 | Consistent sampled graph at producer boundary |
| Web3 operational instructions | Task11 | Shared facts contract instead of lossy manual adaptation |
| Web4 trace closure | Task9, schedule-probe first | Collector-owned closed/drained fact |
| Web5 rotated bounds | Task12 | Local transform contract fix, not geometry framework |
| Layout1 completion | Task14 | Shared mechanism/report validity; explicit policy differences |
| Layout2 band envelope | Task15, candidate-probe first | Reuses feasibility owner without expanding search |
| Layout3 routing-domain ownership | Task13 | Enables independent algorithm work behind existing prepared phase |
| Original seven findings | Separately approved original Tasks1–8 | Piler fixes and original mutable/index ownership cannot disappear into this portfolio |
| CLI writer startup, live-source experiment scripts, ship tie-breaks, unreviewed islands | Not selected without further evidence | No justified new general framework or policy unification |

Deferred machine/alias acceptance prerequisite: an authoritative FactorioLab fixture must establish objective machine-unit normalization, per-recipe producer choice, invalid producer behavior, up-to movement of a user-selected tier, alias/canonical collision precedence and preservation of genuinely DF-only/mode-dependent identities. Keep these findings visible; they are neither dismissed nor silently implemented under an abstraction label.
