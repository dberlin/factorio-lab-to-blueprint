# Physical Admission Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox syntax. Review batches cover related contracts; do not run a project suite per task.

**Goal:** Make physical route admission reusable and connect exact complete-candidate settlement to sound, existing bounded repair.

**Architecture:** Exact ordered-prefix/extent facts reduce prospective work; `_search` schedules an ordinary probe before optional connectors. Existing positive attachment/companion proposals supply bounded physical alternatives. `commit_once` owns disposable materialization and compose-owned settlement; finalizer lineage/witnesses preserve contextual causality. Success passes through once as `PlacementCompleted`. Native path-language machinery is conditional, not required.

**Tech Stack:** Existing Python3.14 worktree environment, Cython native routing kernel, pytest, Ruff and mypy; no new dependency.

**Spec:** `docs/superpowers/specs/2026-09-09-physical-admission-lifecycle-design.md`

**Implementation status:** Tasks1–6 are integrated and scoped source reviews approve the contracts. Online retained gap4 repair and all three original-allowance transfers pass; original titanium passes4/4. Both mall originals remain refused, so factory promotion is **FAIL**. The checkboxes below retain the original combined implementation/acceptance checklist rather than falsely marking every acceptance criterion green. Executed evidence and limitations are recorded in the final disposition below and `docs/superpowers/evidence/2026-09-09-physical-admission-lifecycle/implementation/`.

## Global constraints

- Preserve original URLs, recipe/rate boundaries, machine-rank policy, technology, lane domains, capacities and validators.
- Preserve content-derived final frames with existing0–4 added-row candidates; capacity is not padding.
- Preserve original parent deadline and shared expansion ledger, hierarchy completion deadlines `(deadline, deadline, None)`, atomic slots/certification, `_COMMIT_REPAIR_PASSES=3`, RRR/stale limits and existing bounded CBS limits.
- No new outer settlement loop, global allocator, per-primitive finalizer, cross-build cache, budget escalation, source aliases, merge or push.
- Factory promotion requires complete settled acceptance, not a routed prefix or earlier refusal.
- Existing routing/continuation edits are baseline work, not disposable. Preserve them. Frozen baseline source/native hashes are in `docs/superpowers/evidence/2026-09-09-hierarchy-reassessment/experiments-r1/source-manifest.json`.
- Root/master and other worktrees remain untouched. Do not create a second worktree inside the existing isolation.

## File ownership and execution DAG

| File | Responsibility |
|---|---|
| `layout/finalize.py` | Accepted survivor and bypass-dependency lineage, exact frame witnesses, completion propagation |
| `layout/routing_domain.py` | Prefix admission, search scheduling, commit ownership, contextual bounded repair and success handoff |
| `layout/route_primitives.py` | Exact connector emission/dependency ownership, existing witness generation |
| `layout/route_feedback.py` | Typed hierarchy-neutral settlement outcome on route results |
| `layout/_route_kernel.pyx`, `_route_kernel.pyi` | Native algorithm unchanged; wrapper annotation changes only if needed for existing deadline polling |
| `layout/hierarchy/compose.py` | Complete-candidate callback, actual spec, infill/slots/completion, diagnostic accounting |
| `layout/hierarchy/strategy.py` | Earlier actual-spec construction and single accepted-result consumption |
| `layout/freeform.py`, `layout/sequence_solver.py` | Explicitly unchanged clocks; migrate shared constructor changes without hierarchy settlement |

All paths above are below `src/flab2bp/`. Prefer existing files; no general transaction framework or codebase-wide split.

Task0 precedes production repair and determines whether the proposed finite domain is useful. Tasks1 and2 can be authored independently after the discriminator. Tasks2–6 share routing_domain: serialize those mutations under one integration owner. No unconditional native trie task exists. Task6 consumes preceding contracts. Main runs runtime checks after each integrated batch; writing agents skip tests/build/lint/format during concurrent edits. Review batches cover tasks1–3 and4–6; final review covers integrated source and factory evidence. Architectural redesign uses two communicating whole-design partners, not isolated per-part designers.

LSP references currently fail with `this._token.cancel is not a function`; symbol output previously pointed109 lines before real worktree declarations. Retry the worktree server at execution; if unavailable, use scoped source searches and record the complete caller inventory. Never apply edits at stale server lines.

## Task 0: Demonstrate useful existing physical choices

**Files:** disposable diagnostic probes and retained evidence only; no production mutation.

**Measured:** retained packed4747; unchanged completion6261. Original Splitters6239/6243 are emitted by titanium-glass routes24/23, with causal route sets{24,25}/{23,25}. Selecting route24's first existing alternative source/guard group `(44,18,2)` moves its ground Splitter from(75,18) to(44,18); route23 stays at(73,18). Both fresh treatments produce6292 completion-input buildings and `PlacementCompleted`,26/26 cuts, zero uncovered power, in34.407831s and33.355431s under the unchanged39.770329s allowance. Preparation enters with actual8.010435s/9.031714s remaining and takes1.604790s/1.582493s. The unchanged controls cancel in completion. All113 production source/native hashes and all four restored input proofs match.

- [x] Recover actual emission/shared dependencies; distinguish candidate indices, packed membership and `NetId`. Full observer records preserved.
- [x] Inspect existing offer groups and companion closure without new witness variants, forced waypoints or solver.
- [x] Exercise one existing positive source group in a fresh replay; complete authoritative settlement passes twice and the convicted geometry changes.
- [x] Preserve parent deadline,2,000,000 initial shared expansion budget and native graph. Observed control/treatment each make28 detailed searches; the wrapper adds no calls. Record actual completion-entry clock, not a substituted allowance.
- [x] Record **PASS for reachable physical alternative only**. The intervention chooses before the original refusal is paid; it does not prove an online repair can settle after that cost within existing attempts. Original factories/malls remain unaccepted. Native trie is not indicated by this result; proceed only with the separately specified source lifecycle and its remaining runtime gates.

## Task 1: Accepted cleanup lineage and exact frame witnesses

**Files:** `src/flab2bp/layout/finalize.py`; existing `tests/layout/test_finalize.py` and affected completion consumers.

**Consumes:** existing `_remove_buildings`, `_certified_side_fallback`, `BoundaryCompactionResult`, `ProjectionRefusal`, `prepare_placement_completion`, `complete_placement`.

**Produces:** `survivor_indices: tuple[int, ...] | None` on compaction/candidate-bearing completion results (`None` is identity); sparse `link_dependencies: tuple[CleanupLinkDependency, ...]` with survivor original index, input/output side and traversed original indices; `ProjectionWitness(candidate: FrameCandidate, projection: planet.Projection, failure: ProjectionFailure)` alongside unchanged aggregate refusal failures. Empty dependencies mean no bypass cause, not missing information.

- [ ] Inventory all `_remove_buildings`/fallback/result constructors and `prepare_placement_completion` consumers. Production preparation callers are freeform, sequence_solver and hierarchy.strategy; all retain their current clock contracts.
- [ ] Add real accepted-deletion and rejected-structural/original-fallback regressions. Assert final survivor-to-original identities and causal owners after a removed link chain, including successive accepted bypasses and rollback. No object-equality matching. Distinguish known-empty from unknown/global route ownership; keep no-op/all-removal controls only where a plausible mutation changes observable behavior.
- [ ] Expose the original survivor sequence where `_remove_buildings` constructs it. Compose only accepted transforms. The composition rule for an old optional map `prior` and a new optional map `step` is:

```python
if step is None:
    combined = prior
elif prior is None:
    combined = step
else:
    combined = tuple(prior[index] for index in step)
```

Translate each accepted bypass record's survivor/traversed indices through `prior`, include inherited dependencies along the bypassed chain, and union corresponding original causal owners at the routing boundary. A survivor map alone is insufficient. Reset both maps and dependencies when fallback starts from the original. Rejected proposals contribute neither; preserve cancellation without fabricated partial lineage.

- [ ] Record witnesses at the actual per-frame/per-projection failure site. Preserve candidate order, original aggregate failure deduplication/order and report reuse. A witness distinguishes two south paddings in the same band. Propagate accepted lineage through ready/refused/completed/invalid/certification-expired results; cancellation carries no fabricated geometric verdict.
- [ ] Run focused finalizer cases, then replay the four frozen completion-only controls. Physical hashes/outcomes must match baseline. Add the accepted-deletion case because frozen captures only exercise no-op/rollback. Record the baseline limitation, not a false claim of earlier coverage.

## Task 2: Ordered-prefix prospective admission

**Files:** `routing_domain.py::_CompositionProjection`; existing real selection cases in `tests/layout/hierarchy/test_compose.py`.

**Consumes/produces:** `allows_buildings(candidates, *, committed=(), deadline=None) -> bool` stays unchanged. A private selection node retains parent/full member, children, exact extent handle, completed frame verdicts and optional complete-selection existential verdict. An extent handle stores parent, exact normalized expansion member and completed bounds; it never retains an extended cleanup graph.

- [ ] Replay the existing real pair, farther-neighbor, common-frame, extent-expansion, rip-up and deadline-before-cache cases before editing. Preserve the observable quantifier tests; do not add tests that assert cache hit counts.
- [ ] Replace `_selection_verdicts` with ordered prefix interning of full records. Interior members inherit extent handles. For a novel growth state, reconstruct the immutable root plus exact expansion-member chain transiently, evaluate authoritative bounds, cache only completed bounds and discard graph forks. Preserve the existing helper's skipped-interior and link-normalization semantics. Do not deduplicate chains by equal rectangles or replace cleanup with a bounds union.
- [ ] Keep `allows` dispatching through `_frame_clear(additions, frame)` with its existing signature. Put prefix interning/lookup and incremental evaluation inside that seam, rather than bypassing it with direct member/pair calls in `allows`. Preserve `test_composed_projection_requires_one_frame_for_all_selected_objects` and `test_composed_projection_rechecks_earlier_objects_after_extent_expansion`: both replace `_frame_clear` to defend observable quantifier/reframing behavior. The following recipe is the body-level frame evaluator after obtaining that query's ordered `nodes` and `additions`, not a replacement call path:

```python
start = 0
for offset in range(len(nodes) - 1, -1, -1):
    known = nodes[offset].frame_verdicts.get(frame)
    if known is False:
        return False
    if known is True:
        start = offset + 1
        break
if start == 0 and not self._base_clear(frame):
    return False
for offset in range(start, len(additions)):
    if self.cancelled():
        raise _PreparationDeadline
    building = additions[offset]
    clear = self._member_clear(building, frame)
    if clear:
        clear = all(self._pair_clear(additions[index], building, frame)
                    for index in range(offset))
    if self.cancelled():
        raise _PreparationDeadline
    nodes[offset].frame_verdicts[frame] = clear
    if not clear:
        return False
return True
```

Keep cancellation around snapshot construction and final existential publication too. A complete false verdict is scoped to the exact frame. Bounds expansion creates different frames and cannot use a prior smaller-frame exemption. Query order and duplicate records remain intact.

- [ ] Compare real ordered queries with frozen-source booleans across growth, skipped interior members, external references, removals, rip-up and changed frames. Replay both captured malls under existing allowances; record admission/total wall, useful-search coverage, routed/refused outcomes, distinct prefix/extent/frame states, retained bytes and transient allocation churn. Novel growth still costs O(base + chain); reject retained base graphs per prefix or an unmeasured performance claim.

## Task 3: Budget-accounted ordinary probe and connector fallback

**Files:** `routing_domain.py::_search/_astar/_astar_python_loop`; `_route_kernel.pyi` only if wrapper annotations require it; existing `test_route_kernel.py`, `test_technology_routing_search.py`, `test_route_primitives.py`.

**Produces:** optional `_astar(..., deadline_check_every: int | None = None)` keyword. No native ABI change for this task: native `deadline_every` already exists. `_search` signature remains unchanged.

- [ ] Use the design feasibility probe's real model39 fixture with route bounds `(0,1,0,1)` and physical grid span `(-3,-3,3,3)`. Its executed baseline is ordinary SEALED_POCKET, enriched path `(start, goal)`, no emitted port issues, occupied carry levels. Exercise the eventual scheduling owner, not just direct `_astar`, when adding the regression.
- [ ] Add arithmetic controls for cap stop, private-budget stop, expired subdeadline/live parent, expired parent, and nested cluster debit. Check actual remaining ledger and summed raw expansions separately. Reuse existing native/Python budget parity cases.
- [ ] Implement one ordinary attempt before first enrichment using the spec's `Q=min(M+1,max(0,L-(M+1)))`, where `L=search_budget["left"]`, bypass forQ<2, parent remaining-time fraction1/8, and64-expansion polling. Use private budget, no speculative blame. Debit the immediate `_search` budget, never the closed-over outer ledger:

```python
private = {"left": allowance}
ordinary = _astar(canvas, starts, goals, search_history, pressure, bounds,
                  budget=private, deadline=ordinary_deadline, blame=None,
                  grid=search_grid, owned_starts=owned_starts,
                  released_starts=released_starts, forbidden=forbidden,
                  blocking_owners=owner, extra_edges=None,
                  deadline_check_every=64)
search_budget["left"] -= allowance - private["left"]
total_expansions += ordinary.expansions
```

The shown variables are the existing `_search` call context; preserve its source-owned-start preparation. In ordinary routing `search_budget` is the shared ledger; in `_cluster_search` it is that caller's private allowance. `_cluster_search` alone settles its total private consumption back to the outer `budget` once. The probe must not access/debit that outer ledger directly. After a substop, use original deadline/remaining `search_budget` for existing edges and enriched search. Pass ordinary success through current physical/source admission. Fix the retry0 return shortcut so fallback telemetry is not lost. Do not repeat the ordinary probe on all five admission retries.

- [ ] Before enrichment, restore all applicable original source/destination offers and rebuild graph context. Keep applicable body-local proof separate from ordinary whole-selection refusals and temporary proposal restrictions. Add an actual `_search` regression where ordinary source selection is contextually refused but the same source plus a real connector becomes legal. The direct model39 fixture alone cannot cover this transition.

- [ ] Migrate native capture/replay spies to the new optional keyword. Retain defaults for boundary routing and every direct `_astar` caller. Keep ALT disabled for enriched graphs exactly as now.
- [ ] Run ordinary-positive and real connector-only controls through scheduling, including small budgets that bypass the probe. Rerun the two captured malls; retain all refusal/area/time changes. No theorem of preserving every previous finite-clock success is claimed.

## Task 4: Owned commit materialization and typed settlement boundary

**Files:** `routing_domain.py::_commit_paths/_tap_source/commit_once`; `route_primitives.py::emit`; `route_feedback.py`; `hierarchy/compose.py` records.

**Produces:** owned commit attempt with workspace, candidate-original causal owners and commit failures; typed `RouteSettlement` completed/refused/cancelled/unexpected-Exception outcomes. `DetailedRouteResult.settlement` and `ComposeResult.settlement` are optional; absent means unsettled. Callback consumes materialized `_Canvas` and index-aligned `tuple[frozenset[NetId] | None, ...]`. Empty owner set is known no route cause; `None` is unknown/candidate-global. TYPE_CHECKING avoids hierarchy/finalizer import cycles.

- [ ] Inventory `_commit_paths`/`emit`/source-tap callers and result construction. Preserve emission order: all belts, connector bodies, sinks, then source taps. Keep default non-hierarchy `_route_all` behavior with callback absent.
- [ ] Build ownership during real emission/mutation. Every appended belt/stack/attachment has distinct candidate index. Rewritten and read-dependent base links gain route owner unions. Shared endpoint reuse retains earlier dependent siblings; do not reduce ownership to append spans or nearest geometry.
- [ ] Add real shared-source and co-located attachment regressions. Preserve causal owner unions after later sibling mutation and accepted removed-link bypass. Compose Task1's survivor and sparse dependency records with index-aligned owners; unknown contributors remain unknown rather than becoming empty or nearest-route ownership.
- [ ] Return the disposable committed workspace from commit_once instead of discarding it. Keep partial materialization diagnostics and exact old commit failures; do not yet stamp partial candidates. Zero-net complete selections must reach the eventual callback.
- [ ] Classify the combined prospective-selection failure separately from unconditional source/path failure. It cannot enter `rejected_starts`, `rejected_goals`, or `rejected_path_cells` without a matching contextual constraint.

## Task 5: Bounded physical proposals and contextual refusal

**Files:** `routing_domain.py::_search/retain_commit_failures/_last_mile` and focused routing tests. Native search state/ABI remain unchanged.

**Consumes:** Task0's useful physical-choice evidence and Tasks1–4's contexts/provenance. **Produces:** private positive proposal state and exact whole-choice/full-candidate refusals, separate from ordinary applicable commit failures.

- [ ] Define each proposal by implicated `NetId`, optional existing source/tap offer group, optional existing destination-hint group and frozen construction context. Begin with normal routing, then spend remaining existing slots on alternate source groups, destination groups or existing companion reroute order, deterministically. Re-query `_ends` after staking; use only current canonical connector witnesses.
- [ ] Restrict starts/goals for the positive branch without adding omitted offers to persistent bans. Native A* still finds the legal path for that branch. Preserve admission, three commit-repair passes, RRR/stale, CBS member/node/invocation and shared expansion/deadline limits. Omitted choices remain unsearched/inconclusive.
- [ ] Keep exact whole-choice no-goods only under identical other choices, offer/hint/tap maps, witness graph, grid/guards/ownership and immutable spec/rules/policy context. If path-to-materialization determinism is not established, use complete materialized candidate equality instead; never infer a path/tap/cell/edge ban from projection.
- [ ] Use original-index witness owners plus existing companion closure to choose repair/CBS participants. Do not forge world-to-grid walls. Contextual refusal/exclusion, omitted choices and cancellation cannot publish PROVED, an exhaustive relation or unconditional `ClusterRelationNoGood`.
- [ ] Exercise the Task0 useful alternative with real components. It may share old source/path cells. Verify graph/offer/companion changes restore applicable choices, identical full candidates are skipped, siblings restore exactly, and a tiny budget remains inconclusive.
- [ ] If choices cannot change the recorded cause/frame, return bounded refusal, not a new next-pack loop. A trie is a separately gated alternative only if a useful same-context path-only candidate is demonstrated and current offers cannot reach it. Do not implement `forbidden_paths` or product-state storage in this task.

## Task 6: Authoritative settlement and clean success cutover

**Files:** `hierarchy/compose.py::compose`; `hierarchy/strategy.py`; `routing_domain.py::commit_once/_finish/_last_mile`; affected direct compose consumers.

**Consumes:** Tasks1–5. **Produces:** required compose keyword `settlement_spec: BuildSpec`; compose-owned callback; exact `PlacementCompleted` delivered to hierarchy.strategy without rematerialization.

- [ ] Compute actual `composed_spec` after allocation but before compose in strategy, outside the broad composer crash guard. Split the existing guarded region into the original boundary-lane/allocation calls and the original compose call, with `composed_spec` between them; retain the existing ContractError/composer-refusal handling for those guarded calls only. An unexpected `composed_spec` exception must still propagate, not become `composition crashed`. Keep requested spec owning packing; pass actual built spec separately for settlement. Migrate every direct compose call, including retained replay tools when run on current source.
- [ ] Move success-path power infill, emission, global slot pass and existing prepare/complete calls into the callback. Add power ownership causes; ambiguous causes remain candidate-global. Keep current partial diagnostic infill outside the callback, separately labelled unsettled and using original clock/counting semantics.
- [ ] Invoke full settlement only for complete linked selections with no reservation deficit, including zero nets. Expected power/slot/projected/validation failures are typed refusals; cancellation is budget without a geometric exclusion. The exact clock remains:

```python
prepared = finalize.prepare_placement_completion(
    placement, settlement_spec, policy, belt_rules=belt_rules,
    expect_power=True,
    deadlines=finalize.PlacementCompletionDeadlines(deadline, deadline, None),
)
if isinstance(prepared, finalize.PlacementProjectionReady):
    completion = finalize.complete_placement(prepared)
```

Branch explicitly on every existing result variant; no truthiness/default success. Carry an unexpected settlement `Exception` and traceback across the current broad composer guard, then re-raise outside it. Do not catch process-control BaseException as an outcome.

- [ ] Avoid repeated expensive refused settlement only with exact full linked/infilled/globally-slotted candidate equality, including actual spec, rules, policy, causal provenance and all cleanup-relevant placement metadata. Static/tap/extent equality is not sufficient. Check cancellation before reuse; incomplete work and budget stops never create negative cache entries. Earlier route-choice dedup requires established deterministic materialization. Measure distinct candidates and settlement wall; do not add an outer loop.

- [ ] On refusal, use the existing focused repair/CBS attempts with contextual choices. On accepted result, pass the owned handle directly through every `_finish` success exit. An accepted complete exit performs no second `_commit_paths`, infill, slots, cleanup, projection or certification. A partial/budget/stranded exit with callback present still materializes the selected partial incumbent through the existing `_finish` commit path, including permanent-guard reset, selected hints/taps, unlinked failures and original counts; it carries no completion handle and never invokes full settlement. Compose retains partial diagnostic infill. Do not turn callback presence into a blanket skip of `_commit_paths`. An earlier best-round incumbent cannot inherit the last attempt's handle. Atomic accepted certification gets no new expiry guard afterward.
- [ ] Remove strategy's old slot/prepare/complete block and consume the exact accepted placement/report. Keep packed block metadata clearly in original routing coordinates, never pretending it indexes the cleaned/framed placement. A full route count without completed settlement refuses.
- [ ] Verify zero-net, partial, missing-reservation, unlinked, slot failure, power failure, cancellation, late atomic certification, exact accepted handoff and earlier-incumbent scenarios with real components. The partial case must observe emitted surviving routes and named unrouted/link failures, not merely a missing callback. Exercise unexpected exceptions from `composed_spec` and settlement (propagate with traceback), versus boundary/allocation/compose exceptions (retain original refusal classification). Use structural spies only as secondary checks, never as the sole proof of physical behavior.

## Task 7: Integration, original acceptance and evidence

**Files:** affected source/tests; existing report and hierarchy evidence locations. No additional feature scope.

- [ ] Run focused integrated checks from the worktree environment, with exit code and JUnit evidence retained:

```text
.venv/bin/python -m pytest tests/layout/test_finalize.py tests/layout/test_route_primitives.py tests/layout/test_technology_routing_search.py tests/layout/test_route_kernel.py tests/layout/test_route_witnesses.py tests/layout/hierarchy/test_compose.py -q --tb=short
```

Apply existing Ruff formatting/lint and mypy to changed source; rebuild Cython through the project's existing native-build command before claiming native parity. Verify imported module/native paths belong to this worktree. The comprehensive suite already fails at baseline; accept that reported state without rerunning to confirm it. Extract baseline collected test IDs, outcomes/failure signatures, environment/source identity and cap from retained logs/JUnit first. Run comprehensive Python tests once after integration, capped150s, retaining full logs/JUnit and timeout state. Compare per-test outcomes: new failures, changed failure signatures, lost collection/coverage, new skips and unexecuted cases are regressions or inconclusive findings, not hidden by a shared nonzero exit. Unchanged baseline failures remain explicitly unresolved. If existing evidence cannot discriminate a case, mark it unclassified and use its focused causal check; do not claim a clean comprehensive no-regression gate from incomplete/timeout evidence or silently waive baseline failures. Focused changed-contract checks must pass independently.

The currently retained `2026-09-08-technology-routing/full-suite-r3.json` records exit124 after145.021s. Its4869-byte progress log contains failures but no failed-node summary; the recorded scratch JUnit path and evidence-copy path are absent. These artifacts establish the disclosed failing/incomplete baseline, not a per-test comparison oracle. Preserve this limitation; do not manufacture a complete baseline inventory from progress glyphs.

- [ ] Replay retained gaps4/8/12 with original transfer allowances. Then run original titanium repeats, all-products mall and no-proliferator mall using exact saved URL/argv contracts from `docs/superpowers/evidence/2026-09-08-hierarchy-continuation/original-acceptance-r7/` and retained transfer inputs. Do not substitute completion-only unbounded runs for these acceptance gates.
- [ ] Decode every emitted blueprint and verify authoritative completion/report. Record child coverage, original cuts receiving useful search, routed cuts, distinct settled candidates, settlement/refusal counts and wall, expansions, total runtime, area and source hashes. Keep nested inclusive timers separate. Earlier refusal or a larger routed prefix is not factory acceptance.
- [ ] After focused causal integration is stable, run the unchanged default72-cell guard and compare per-cell outcomes/area/runtime against the established baseline. Do not use the full matrix to rediscover a known focused defect.
- [ ] Review the integrated contracts and test quality. Remove obsolete implementation-pinning tests rather than repinning them; retain behavioral regressions for lineage, context and capability. Update `~/report.md` with exact PASS/FAIL and preserve large replay evidence without arbitrary size reduction. Archive then remove disposable design probes only after their evidence is verified; no production shim remains.

## Review and stop rules

A design/runtime failure pauses only the dependent task; preserve successful independent work. No promotion if gap4 merely fails faster, connector-dependent coverage regresses, settled failures turn into unconditional bans, repeated settlement consumes the parent clock, or original malls remain incomplete. If the bounded exact-choice mechanism cannot supply an alternative under the unchanged domain, report that result explicitly instead of raising limits or claiming infeasibility.

Production lifecycle implementation is complete; factory-solution acceptance is not. The online gap4 treatment pays the initial settlement refusal and certifies within the original allowance. Titanium repeats pass, while both original malls fail without emitting. Existing clocks, geometry, budgets and bounded repair limits remain unchanged. The full72-cell guard has no lost CLEAN/invalid/crashed/unrun cells, but nine historical paired CLEAN areas grow over20%; do not call that area guard passing. Comprehensive tests stop at145s with failures; absent baseline node IDs/JUnit and incomplete candidate execution prevent a per-test no-regression claim. No merge or push.

## Executed disposition

| Gate | Result |
|---|---|
| Tasks1–6 source contracts | Integrated; final scoped admission/settlement reviews approve. No native trie, new outer loop or changed limits. |
| Focused integrated checks |273 passed, zero failures/errors/skips. Native rebuild, changed-source Ruff/mypy pass. |
| Frozen completion compatibility |4/4 exact outcomes/geometry; unbounded completion-only, not factory acceptance. |
| Original-allowance transfers |Gaps4/8/12 certify26/26 in35.586/17.124/19.319s. Gap4 requires two settlements, one refusal, no duplicate reuse. |
| Original titanium |4/4 PASS,40.805–45.469s, unchanged60s requests. |
| Original full9 |PASS,62.369s total including existing atomic tail, unchanged60s search budget. |
| Original malls |Both FAIL, no blueprint; all-products134/134 and no-proliferator272/272 cuts remain unlinked/unresolved at terminal budget. |
| Blueprint codec |Five original outputs and three retained placements decode with valid checksums and exact payload round trips. |
| Ordered admission parity |9379/9379 captured queries match frozen source. Current retained bytes increase136.64→142.53MB and151.94→166.49MB. Traced timings are mixed, not a general speedup. |
| Shared freeform contracts |27 passed, two failures reproduced with frozen routing module. Three stale commit spies migrated; one mock-only hints-forwarding test removed, not re-pinned. |
| Comprehensive candidate |One145s run, exit124:4410 collected,4291 pass/105 failure/four skip progress glyphs, ten unfinished or unreported. No per-test oracle/JUnit; comparison remains inconclusive. |
| Default72-cell historical guard |66 CLEAN/same six REFUSED; no lost CLEAN/invalid/crashed/unrun/backend changes. Area threshold FAIL in nine paired CLEAN cells. Historical source differs from immediate baseline. |

Full logs, captures, native/source identities, per-cell comparisons, reviews and failed attempts are retained in `../evidence/2026-09-09-physical-admission-lifecycle/`. `implementation/final-status.json` is the machine-readable disposition. Evidence limitations are explicit: separate rather than combined accepted-bypass/refusal-owner coverage, no distinct nested plus-one outer-debit case, no cumulative allocation-churn measurement, and no per-net useful-search counters in the original CLI logs. Retained captures/settlements have their own counters; they are not substituted for missing original counters. No factory promotion or blanket no-regression claim follows from this implementation.
