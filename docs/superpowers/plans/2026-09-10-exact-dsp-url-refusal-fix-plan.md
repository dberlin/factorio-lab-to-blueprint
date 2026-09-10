# Exact DSP URL Refusal Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Do not dispatch agents without the user's authorization. This investigation does not authorize implementation or commits.

**Goal:** Remove the demonstrated topology/priming defects and make the exact requested DSP build produce a fully valid blueprint under its unchanged public defaults at 15, 30, and 60 seconds; retain truthful, attributable refusals when a deadline expires.

**Architecture:** Preserve directed material allocation when joining sharded lanes, and use the existing indexed transport graph for same-recipe loop priming. Carry existing failure evidence across island/race boundaries, then address the measured routing and projected-collision branches within the original deadline rather than enlarging it or bypassing validation.

**Tech Stack:** Python 3.14.7, OR-Tools 9.15.6755, existing Cython routing kernels, exact Fraction-based physical-flow certification.

**Spec:** This document's frozen request and acceptance contract below, plus `evidence/request.json`, `evidence/specs.json`, and `evidence/contract.json` in `/tmp/flab-url-refusal-27483797`. All paths below are relative to that isolated source snapshot unless stated otherwise.

## Global Constraints

- Investigation source: `27483797fe9df3e8f1e22635b80953e500bdb842`, the validator-only master commit supplied by Main. No diagnostic scenario used the dirty transport worktree. The older `87be343ff2371fc0dd17edb3943e635c27996045` snapshot was used only for initial inspection.
- No production fix has been made. The implementation tasks below require separate authorization.
- Never increase 15/30/60-second budgets, switch off a validator, allow invalid output, silently change candidate policy, change worker defaults, introduce hidden fallback/retry behavior, or special-case the URL/items/building IDs.
- No function-level profiling. Existing traces, counters, and coarse phase observations are sufficient for the next gates.
- Preserve the validator's simultaneous shared physical-capacity certificate. Correcting a false priming finding does not excuse the separately demonstrated steady-state hydrogen shortage.
- Do not change `git diff.external` or other user Git configuration. Use an isolated implementation tree based on the recorded commit; inspect current changes before integrating.
- Run targeted behavior regressions and actual public-path scenarios. Do not add tests of implementation wiring, exact prose, incidental ordering, or source text. Run project-wide validation once at the integration boundary, not during concurrent edits.

---

## Frozen request and public-surface contract

Exact URL:

```text
https://factoriolab.github.io/dsp/list?z=eJzLt3UyUMu3LdUyNDAw0NIyVMu3TdIyVcu3dYqCUJVwmcykVFsntaLUCtt4tdzcItuCuuK6zLpAtTJbQ0MAnqAUGg__&v=11
```

The decoded output objectives are vertical-launching-silo 1/min, dyson-sphere-component 5/min, and small-carrier-rocket 5/min. Optical-grating-crystal and titanium-ingot each have a URL input objective of 1000/min; these are availability caps, not a requirement to consume the entire quantity. Exact machine ranking selects negentropy-smelter, re-composing-assembler, quantum-chemical-plant, and matrix-lab. Belt choice is conveyor-belt-2. The URL does not encode belt technologies, so the current maxed default rules apply: max_z=531/20, vertical construction enabled, storage level 8, lab level 9.

Common defaults: strategy `best`, band `portable` (smallest fitting plus up to two wider bands), all three candidate policies, exact machine rank, powered/Tesla automatic selection, sharing enabled, invalid output prohibited, no fetched flow, no environment tuning. Effective candidate order is no-proliferator, all-products, output-products. There are 35 recipe groups and respectively 68, 51, and 61 machines; each freeform packing has 39 strips.

This machine has 128 affinity CPUs; the default worker budget resolves to 16. CLI/pipeline defaults use `race=False`, serial candidate/strategy scheduling, and four sequence islands. Web `Options` retains the same requested settings, but `web.jobs.run_build` uses `race=True` for `best`: three concurrent candidate shares (6,5,5), freeform/sequence splits (4,2),(3,2),(3,2), and two sequence islands per candidate. Do not call a CLI-default result a web-default result. Large CP packing currently uses its own deterministic single-worker setting inside these allocations.

`parse_options` admitted all three budgets. At 60 seconds it issued an estimated-duration warning explicitly saying it would still run; this was not an admission refusal.

## Baseline proof and limitations

All six actual API paths refused with diagnostic process exit 3. `diagnose_url.py web B` invokes real `web.jobs.run_build(Options(...), note)`; `diagnose_url.py cli B` invokes real `pipeline.build(..., time_budget_s=B)` with CLI-equivalent defaults. Neither is an HTTP/browser interaction or a literal invocation of `cli.main`.

| Budget | Web pipeline / process elapsed | CLI-contract pipeline / process elapsed |
|---|---:|---:|
| 15s | 18.358 / 20.296s | 96.937 / 98.496s |
| 30s | 33.288 / 34.706s | 183.794 / 185.693s |
| 60s | 63.468 / 65.268s | 353.749 / 355.451s |

Budget is per layout, not end-to-end request latency. The CLI serial schedule explains its much longer wall time. Exact times and all attempts are in `evidence/scenario-summary.json`; original records/logs are retained per scenario. Baseline web runs were isolated from subsequent diagnostic replay work. Later CLI runs overlapped diagnostic requests (up to three requests on this 128-CPU host); timings are observations, not a controlled performance benchmark. Each baseline is one sample. Deterministic graph counterexamples below do not depend on this scheduling caveat.

| Budget | Web failure stages | CLI-contract failure stages |
|---|---|---|
| 15s | Freeform routing deadlines: 57 / 213 / 69 nets left in effective candidate order. Sequence islands reached deadlines before certification. | Freeform routing deadlines: 46 / 195 / 66. All sequence islands reached deadlines before certification. |
| 30s | No-proliferator fully routes but fails hydrogen conservation and priming. All-products/output-products freeform leave 147 / 38 nets. Sequence arms expire. | Same no-proliferator validation failure; all-products/output-products leave 147 / 2. Sequence arms expire. |
| 60s | Same no-proliferator validation failure; all-products/output-products leave 139 / 2. No-proliferator sequence also records flow/priming findings. Output-products sequence island 1 fully routes but rejects three projected belt collisions at band 200, then the arm expires. | Same freeform flow/priming failure; all-products/output-products leave 129 / 2. Sequence records additional flow/priming refusals and five output-products projection records before expiry. |

The evidence does **not** prove that correcting the two deterministic defects alone makes the 15-second workload fit. That remains a required end-to-end acceptance gate, not an accomplished result or a license to raise budgets.

## File and ownership map

- `src/flab2bp/layout/routing_domain.py`: `_join_shard_islands` and its preparation caller; separate directed links from shared producer-lane supply membership and repair directed deficits.
- `src/flab2bp/layout/buildings.py`, `markers.py`, `validate.py`: reuse one indexed, cargo-aware transport reachability operation for priming and existing loop checks without introducing a validate/markers import cycle.
- `src/flab2bp/layout/sequence_islands.py`, `strategy_race.py`, `src/flab2bp/pipeline.py`: preserve structured existing refusal evidence across process boundaries.
- `src/flab2bp/layout/freeform.py`: make deadline attribution use the existing budget/nonbudget distinction; route/projection changes only at witness-localized owners identified in Task 4.
- Existing suites: `tests/layout/test_freeform.py`, `test_markers.py`, `test_buildings.py`, `test_validate.py`, `test_sequence_islands.py`, `test_strategy_race.py`, and `tests/test_pipeline.py`/`test_pipeline_cli_strategy.py`. Add only behavioral cases described below, in their existing homes.
- Existing README/web guidance: update only contract descriptions invalidated or demonstrably stale in the touched behavior. Do not silently change public defaults to make documentation true.

### Task 1: Replace weak-component shard pooling with directed allocation

**Evidence:** `_join_shard_islands` at routing_domain.py:13929-14092 unions producer-to-consumer pairs as undirected edges. Its caller around 14687-14692 mixes sibling producer-lane membership with actual directed links. A single weak component returns no repair even when source output cannot reach enough demand.

The exact rejected hydrogen network needs 61/3 items/s but can deliver at most 4739/240, short by 47/80. Independent exact min-cut agrees with native certification. Graphene machine 565 produces 221/240 hydrogen/s on one directed lane that can reach only the x-ray-cracking demand of 1/3, trapping precisely `221/240 - 1/3 = 47/80`. The real preparation call returns no extra nets. This is a demonstrated producer-side topology defect, not a reason to weaken the new validator.

**Interfaces:** Keep the repair output as directed `(producer_lane, consumer_lane)` additions consumed by the existing net-construction path. Replace the ambiguous `pairs` input with separately named directed transport links and shared producer-output lane groups at every caller. Shared groups allocate one measured producer budget across its physical output lanes; they are not bidirectional transport edges. Each physical machine's output is charged once. External supply remains one global budget connected only to actually available boundary-entry choices. Consumers remain directed sinks with exact residual demand.

- [ ] Add a directed-feasibility regression to the existing shard-repair test section, adapting its established fixtures rather than asserting exact selected edge order. The minimal measured counterexample is:

```python
pairs = [(10, 30), (20, 30), (20, 40)]
supply = {10: Fraction(5), 20: Fraction(5)}
demand = {30: Fraction(1), 40: Fraction(9)}
external = Fraction(0)
# Current helper returns []; directed maximum flow is 6, not the required 10.
# After repair, independently assert that all demand is simultaneously met.
# A source-10 -> sink-40 link can carry the missing four; never credit
# source-10 -> sink-30 -> source-20 as though existing links were reversible.
```

Use the repository's existing exact-flow representation/test helpers for the consumer assertion; do not add NetworkX as a production dependency. Preserve existing meaningful global-external-budget, oversupply, and lane-residual-credit cases. Replace tests whose only claim is that union-find now reports one island with simultaneous directed-delivery assertions.

- [ ] Run `uv run --frozen pytest tests/layout/test_freeform.py -k 'shard or short_cut' -q`; confirm the new directed example fails for the demonstrated reason before modifying the planner. Adjust selection to the actual newly added test name if existing names differ.
- [ ] Build the small allocation network using existing OR-Tools/exact-rational flow facilities, not a second floating-point acceptance rule. Existing `physical_flow.Model`, `Arc`, and `solve(model, frozenset())` support exact demand obligations via arc lower bounds. Model direction and shared-source gates explicitly; use candidate producer-to-consumer additions only where the current domain admits a physical net.

```text
root -> producer-output-budget gate -> its eligible output lanes
actual producer lane -> actual consumer lane             (directed)
root -> global-external-budget gate -> eligible entries  (one budget)
consumer lane -> root                                   (fixed demand)
```

The circulation is an allocation prerequisite, not a replacement for final physical belt/sorter capacity certification. Reuse native solve output and exact certification. On unknown/unproved feasibility, do not mark the allocation repaired.

- [ ] Select additions from residual surplus to unmet reachable demand, with the current tap-count preference only after feasibility. Constrain each chosen transfer by source residual and destination demand credit. Recompute directed delivery after additions rather than subtracting weak-component balances. Stop only with all obligations certified or a structured unsatisfied allocation reason; never manufacture supply or infinite retry.
- [ ] Replay `uv run --frozen python analyze_shards.py` against a freshly prepared source-derived placement in the implementation tree. For the recorded hydrogen case, ensure the 564 producer lane gains a valid outlet toward an unmet downstream hydrogen consumer (131 or 196 in this witness); IDs are diagnostic evidence, not production conditions. Independently verify the final physical graph has no 47/80 deficit.
- [ ] Run the targeted regressions and the actual no-proliferator/freeform 30-second replay. The priming error may remain until Task 2, but conservation must now be certified on any fully routed candidate; otherwise retain the new concrete witness and correct the directed model rather than weakening certification.

### Task 2: Recognize real self-loops across transport devices

**Evidence:** The rejected placement has x-ray machine 1245, own input sorter 1246, own output sorters 1249/1250, and output heads 1242/1234. Existing indexed transport successors show head 1242 reaches the same recipe group's input through splitter 5986. `self_loop_prime_heads` returns `{}` because markers.py:166-181 follows belt.output_obj and stops at a non-belt. Head 1234 does not close this loop. This is a false priming finding independent of the real flow deficit.

**Interfaces:** Preserve `self_loop_prime_heads(placement, spec) -> dict[str, int]`. Add or reuse an indexed reachability operation in `Buildings` that takes a start node, allowed target taps, and cargo identity, walks `transport_successors`, and includes only compatible belt-transfer sorters. Migrate the existing validate.py `_belt_reaches_any` behavior to the same helper; keep its caller-visible semantics. Run LSP references before altering exported symbols. Do not import validate from markers.

- [ ] Extend the existing marker/loop fixture with a splitter between the group's own output and its own input. Assert that the returned head belongs to the group's output and reaches its own input, and that the emitted prime marker appears on that head. Add the discriminating negative case where only an unrelated external same-item run reaches the input; it must not qualify. Keep a cyclic transport case to prove traversal terminates.
- [ ] Run `uv run --frozen pytest tests/layout/test_markers.py tests/layout/test_validate.py -k 'self_loop or prime' -q` and observe the splitter case fail on the original implementation.
- [ ] Implement the single indexed traversal, preserving cargo filtering, bounds checks, visited-node termination, and the own-recipe origin constraint:

```text
pending = [own_output_head]; seen = set()
while pending:
    node = pending.pop()
    if node in seen: continue
    seen.add(node)
    if node in own_input_taps: return true
    append indexed transport successors of node
    append outputs of compatible transfer sorters drawing from node
return false
```

Use the existing `Buildings.transport_successors` and sorter index rather than rescanning every building for each hop. A splitter/piler is a transport device, not proof the loop ended. Do not turn arbitrary graph reachability into proof of adequate flow; Task 1 and final validators still cover that.
- [ ] Run the targeted marker/buildings/loop tests. Replay the captured placement using `analyze_rejected.py`: the same physical loop must be recognized before any geometry change, while its original 47/80 conservation finding must remain until a real topology repair is present.

### Task 3: Preserve true failure stages through islands and races

**Evidence:** `_SequenceIslandOutcome` does not carry `_refusal_stats(run)`; merge rethrows without stats. `_StrategyRaceOutcome` and pipeline `_raced_result` retain process counts but discard detailed solver refusal evidence. Freeform's deadline branch says a longer clock alone would not help even when every failed net is `BUDGET`, often with zero expansions. V2 replay found all-products 60-second packing FEASIBLE, 244 nets, 105 routed, 139 BUDGET failures, with 748050 expansions on attempted work. This is uncompleted routing, not a proof of impossible geometry.

**Interfaces:** Extend the existing internal process outcome records with a picklable structured failure payload containing candidate identity, strategy identity, island identity where applicable, terminal stage/reason, existing solver stats, and existing projection records. Preserve nested per-arm evidence; do not flatten multiple islands into last-writer-wins scalar keys. No new telemetry framework or per-function instrumentation.

- [ ] Add process-boundary behavior regressions in the existing island/race/pipeline tests: a real rejected child outcome with a budget-classified route must remain attributable after aggregation; a separately rejected fully routed projection must retain its findings and witness identity. Assert the client-visible structured evidence, not field-copy implementation details or exact prose.
- [ ] Populate island failure stats before `_run_sequence_island` returns, preserve them in `_merge_sequence_island_outcomes`, then carry the same data through strategy race outcomes and pipeline aggregation. Use existing serialization conventions and verify no MappingProxyType leaks across the process boundary.
- [ ] Apply `_routing_failure_bound`'s budget/nonbudget distinction to the deadline path as well. Format factual categories: preparation deadline; routing deadline with unattempted/attempted counts; proved local route blockage; fully routed but validation-rejected; projected collision rejection. A budget code does not establish that more time would succeed, nor that more time could not help.
- [ ] Run `uv run --frozen pytest tests/layout/test_sequence_islands.py tests/layout/test_strategy_race.py tests/test_pipeline.py tests/test_pipeline_cli_strategy.py -q`. Update only behavioral expectations broken by the new truthful contract; remove incidental prose-pinning tests instead of re-pinning them.
- [ ] Rerun the unchanged web 15-second API scenario and inspect its terminal evidence without diagnostic monkeypatches. Require per-arm budget/finalization distinction to survive. Preserve CLI/web scheduling differences in documentation; correct the stale eight-island CLI help/current four-island default and stale web admission-limit prose only after checking their current source.

### Task 4: Close measured routing/projection gaps inside the original budgets

This is a witness-led implementation gate, not a claimed solved optimization. Do not infer a function-level hot spot from the phase totals. Re-run after Tasks 1-3 because the necessary new material link changes detailed routing.

**Evidence:** At 15 seconds, v2 freeform all-products spent 10.690 seconds in preparation and 1.979 seconds in routing, leaving 216 budget-classified nets. At 60 seconds it spent 10.653/47.378 seconds and left 139. Output-products at 60 seconds reached 111/113 nets in its first pack, then spent the remaining budget on later packs; the last-mile path was invoked but had zero expansion allowance. No-proliferator's first fully routed pack is usable only after Tasks 1-2. Sequence output-products had a fully routed band-200 candidate rejected for actual belt/building pairs (1679,239), (3295,87), (1401,941); the existing evidence does not establish the shortest safe geometric repair.

- [ ] Run fresh web and CLI-contract 15/30/60 scenarios serially with Tasks 1-3 applied. If fully valid defaults now succeed at every budget, no speculative routing rewrite is justified. If any refuse, capture the exact remaining phase, attempted/unattempted route counts, pack dimensions, and projection witnesses using the existing structured evidence.
- [ ] For a remaining last-two-net routing deadline, replay that existing prepared pack within the same total budget. Use the existing bounded last-mile repair before advancing to another large pack; explicitly reserve that work from the current arm's allowance, never add grace or silently start another request. Compare completed nets and certification result, not just expansion count. If moving the bounded repair cannot produce a certified candidate, retain the witness rather than assert an optimization worked.
- [ ] For a remaining preparation-dominated 15-second request, record its existing coarse preparation substage counters/observations; distinguish domain construction from packing and detailed-route work. Remove only duplicate request-invariant construction demonstrated across the three candidates, caching at the narrow existing owner with an exact key containing every consumed geometry/technology/policy input. If no duplication is demonstrated, do not introduce a cache. Do not declare the 10.690 seconds a CP-SAT timeout: the measured pack was FEASIBLE. This gate must yield a measured source-level cause before choosing a further performance edit.
- [ ] For a remaining projected collision, retain the actual rejected finalized placement and re-evaluate its band-200 collider witness using the existing `dsp_colliders.stable_belt_collisions` path. Feed a witness-local repair into existing `_projection_feedback_stage_update`/freeform projection feedback. A belt/machine conflict calls for a route-local avoidance constraint; only a proven static block-pair conflict qualifies for an exact pack no-good. Include the relevant band/geometry scope. Do not add universal padding, ban unrelated item types, or make belt collisions advisory.
- [ ] Exercise each repaired witness in the actual finalization/certification path. Keep a regression only for the uncertain boundary exposed by that concrete defect. If any fixed-budget public scenario still refuses, report that exact remaining prerequisite; do not mark this plan's end-to-end goal achieved.

### Task 5: End-to-end acceptance and evidence handoff

- [ ] Use a fresh isolated implementation environment with recorded source identity, no FLAB_* overrides, and the same native backend. Preserve decoded request/spec identities, workers, policies, band, machine-rank, and admission results.
- [ ] Run the six commands below **serially**, retaining stdout, stderr, exit, wall time, progress, refusal details or emitted blueprint, and independent decode/validation results. They must use an unmodified version of the API harness apart from its source root.

```text
uv run --frozen python diagnose_url.py web 15
uv run --frozen python diagnose_url.py web 30
uv run --frozen python diagnose_url.py web 60
uv run --frozen python diagnose_url.py cli 15
uv run --frozen python diagnose_url.py cli 30
uv run --frozen python diagnose_url.py cli 60
```

- [ ] Also invoke the actual CLI executable with the exact URL and `--budget 15`, `--budget 30`, and `--budget 60`, leaving strategy/policy/band/workers/race unset. Use its documented output argument to preserve each blueprint. Exercise the browser or HTTP job submission surface with the corresponding public Options, verifying 60-second warning is not rejection. API-only evidence must continue to be labeled API-only if that surface is unavailable.
- [ ] Acceptance requires an emitted blueprint for every specified default-surface budget, no hidden candidate omission, correct requested outputs and power, clean physical-flow/priming checks, and clean game/projection checks for the accepted portable band certification. A merely fully routed graph or a missing error message is not success. A success at 60 seconds alone does not satisfy the 15/30-second contract.
- [ ] Re-run the meaningful targeted regressions from Tasks 1-4, then the integration owner's single project-wide validation pass. Update existing user-facing documentation/changelog if behavior or refusal structure changed, remove throwaway scripts from the production change, and preserve their evidence outside source control. Review source changes for accidental acceptance weakening and any policy/budget/default changes before committing, only when separately authorized.

## Diagnostic inventory and known harness failures

`evidence/{web,cli}-{15,30,60}s/` contains authoritative uninstrumented baseline process/terminal/progress/stdout/stderr records. `evidence/contract.json` records source and native module hashes; `backend-identity.json`, `environment.json`, and `public-admission.json` record runtime and admission. `request.json` and `specs.json` retain full decoding.

`capture_replay.py` captures existing coarse outcomes in a diagnostic process only. Its corrected v2 runs live at `evidence/replay-v2-web-{15,30,60}s/`. The earlier v1 runs at `evidence/replay-web-*` hit a diagnostic-only `TypeError: cannot pickle 'mappingproxy' object`; retain them but exclude their modified terminal outcomes from solver conclusions. `capture_replay_v1.py` preserves the faulty harness; v2 changes serialization only and has no capture errors. Initial runtime setup exceeded the MCP transport's 30-second response window but completed successfully; later finite runs used the asynchronous shell facility. Neither event is a production solver refusal.

`evidence/hydrogen-freeform-30s/`, `hydrogen-rejected-analysis.json`, `hydrogen-mincut.json`, `shard-pooling-calls.json`, and `minimal-pooling-counterexample.json` preserve the narrowed causal replays. That one-candidate freeform replay is explicitly not a substitute for either default-surface matrix.
