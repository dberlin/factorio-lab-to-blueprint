# Hierarchical v5 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Fund real deduplicated block work and improve fully certified composition reliability without larger limits or special cases.

**Architecture:** Retain the current partition/dispatch/pool/compose/finalize pipeline. One immutable round-work description owns funding and submission. Exact composition-stage captures determine which bounded causal repair is admissible; historical failure strings alone do not justify a patch.

**Tech Stack:** Python, existing dataclasses/Pydantic models, CP-SAT block packing, existing Cython routing, pytest, Ruff, mypy, uv.

**Spec:** `docs/superpowers/specs/2026-09-08-hierarchical-v5-design.md` (user accepted the direction on 2026-09-08).

## Global Constraints

- Mixed-item input lanes remain banned. No recipe-id, URL-id, or corpus-index predicates in production behavior.
- Block budgets remain 5–20 seconds; global recuts remain at most two; per-entry split attempts remain at most four. Existing parent deadline clipping and settlement reserve remain binding.
- No new backend, persistent cache, enlarged expansion bounds, increased retry counts, or validator exceptions.
- Compute offered arms once per round. Preserve stable shape/arm order, explicit single-arm requests, same-round result sharing, call-local no-goods and genuine-refusal-only memoization.
- Compose, assign sorter slots, compact, project, and certify the same candidate. No partial factory is an emitted success.
- V4's failed target remains failed unless a new named measurement passes it. Diagnostic instrumentation is not a timing benchmark; certification of a new rebuild is not certification of an earlier file.
- Independent readers/experiments can run concurrently. Main owns integration, runs validation after edits settle, and reruns only failures serially when concurrency was involved.

## File ownership and DAG

| Owner/task | Files | Responsibility |
|---|---|---|
| Main / Task 1 | `docs/superpowers/evidence/2026-09-08-hierarchical-v5/` | Frozen manifests, current baseline, trusted exact-stage captures |
| Funding / Task 2 | `src/flab2bp/layout/hierarchy/strategy.py`, `tests/layout/hierarchy/test_strategy.py` | Round grouping, budget selection, submission and deadline contracts |
| Composition / Task 3 | `src/flab2bp/layout/hierarchy/compose.py`, `tests/layout/hierarchy/test_compose.py`; earliest proved geometry owner if different | Causal composition repair, only after exact reproduction |
| Main / Task 4 | Same composition boundary, serialized after Task 3 | Bounded route/reservation discrimination experiment |
| Main / Task 5 | Existing gate/report/backlog documents and evidence | Final CLI proof, paired matrix, reviews, outcome |

Task 1 feeds Tasks 2 and 3. Their investigation is independent, but Task 3 must not edit `strategy.py` until Task 2 integrates. Task 4 consumes the exact snapshots from Task 1 and the corrected geometry, if any, from Task 3. Task 5 follows all edits. Universe's general topology portfolio is separate and must not be merged into these controls mid-gate.

## Task 1: Freeze current inputs and capture real failing phases

**Files:** Create evidence-local `capture.py`, `manifest.json`, original result records and trusted local snapshots under `docs/superpowers/evidence/2026-09-08-hierarchical-v5/`. Reuse v4 `run_cell.py`, `probe.py`, `block_probe.py`, and their saved argv instead of hand-copying compressed URLs.

**Interfaces:** Existing `HierarchicalLayout.lay_out(spec, *, time_budget_s, absolute_deadline=None) -> Placement`; `compose.compose(placements, flows, spec, *, gap, ramped, deadline) -> ComposeResult`; `strategy.finalize_placement` at the actual finalization boundary. No public diagnostic API.

- [ ] Freeze `bbc8889d` as baseline before source edits. Create an isolated `hierarchical-v5` worktree. Record source/dependency/catalog hashes, current working changes, mode, worker/affinity and exact argv.
- [ ] Run the current titanium-glass all-products60 and15 cases plus both mall60 policies using saved v4 URLs, PLACED,32 workers,CPU0–31. Preserve original exits, byte hashes and complete findings. Four original titanium runs at each budget are the reliability population; do not replace them with successful retries.
- [ ] Wrap the real boundaries in the evidence process only. Retain exact input objects before mutation; serialize trusted local snapshots, never expose a pickle-loading public interface. Record remaining wall on boundary entry and instrumentation cost. Full routing outcomes must retain `NetId`, detailed kind, router status, attempted/routed counts and termination reason. Distinguish power infill not run from zero uncovered.
- [ ] Replay the identical composed placement through slot assignment, compaction, finalization and certification without rebuilding blocks. Map each convicted building back to copied block, routed belt/splitter or infill site. Store emitted bytes and decode/certification output where a build succeeds.

Evidence wrapper shape (the actual callable signature is retained by `*args, **kwargs`; this is an evidence-only wrapper, not a new production API):

```python
from functools import wraps
from time import monotonic

def capture_call(function, retain):
    @wraps(function)
    def wrapped(*args, **kwargs):
        entered = monotonic()
        retain(function.__name__, args, kwargs, entered)
        return function(*args, **kwargs)
    return wrapped
```

`retain` writes or buffers a snapshot at that boundary and records its own elapsed time; failures in evidence persistence fail the diagnostic, not the product. Instruments call the original once with unchanged arguments. Use guarded `__main__` for spawned workers.

**Acceptance:** A real current-stage capture and executable replay for every reproduced failure class; a named no-longer-reproduces result for absent historical classes; actual bytes for each claimed emission. No production geometry edits yet.

## Task 2: Make funding and submission consume the same round work

**Files:** Modify `strategy.py` around the round loop, `_solve_round`, and `_ShapeNoGood`; extend `test_strategy.py` using its existing deterministic pool/clock fixtures. Main owns tests/validation while concurrent tasks are active.

**Interfaces:** Private ordered grouped work maps `(ShapeKey, arm)` to the existing entry slots. A private immutable round plan carries final budget, active keys, memo-skipped keys and sharing slots. Keep `_BlockJob`'s existing spec/arm/budget/vertical/workers/parent-deadline payload and returned record/placement contract. Do not introduce a second public scheduler.

- [ ] Add a regression where repeated identical block shapes fit the real available waves, but counting raw block-arm slots refuses the round. Assert that the consumer gets a completed layout (or reaches the real composition boundary), not merely that a mocked map was called.
- [ ] Add the budget-sensitive no-good boundary: a key remembered at10 seconds must be retried when deduplication funds it at15; it may remain skipped at10. Also cover all-remembered zero work, distinct same-recipe shapes, and parent-clipped refusal lifetime through existing tests rather than duplicating them.
- [ ] Run those tests against the unchanged source and retain the expected behavioral failure before implementation.
- [ ] Build stable grouped work once. Compute funding from that map; evaluate no-good thresholds at the final candidate budget. Enumerate memo-threshold and wave-derived budget breakpoints in descending budget order; preserve the existing five-second-floor/seed behavior and fixed settlement reserve.

Core funding rule (integrate with existing constants and types, not a separately exported utility):

```python
from bisect import bisect_left
from math import ceil

def funded_budget(thresholds, width, remaining, rounds_left):
    # One threshold per unique key: -inf means no remembered refusal.
    thresholds = sorted(thresholds)
    if bisect_left(thresholds, 20.0) == 0:
        return 20.0, 0
    candidates = {5.0, 20.0}
    candidates.update(t for t in thresholds if 5.0 <= t <= 20.0)
    candidates.update(
        min(20.0, max(5.0, remaining / rounds_left / waves))
        for waves in range(1, ceil(len(thresholds) / width) + 1)
    )
    for budget in sorted(candidates, reverse=True):
        waves = ceil(bisect_left(thresholds, budget) / width)
        if waves == 0 or budget <= min(20.0, max(5.0, remaining / rounds_left / waves)):
            return budget, waves
    raise AssertionError("the five-second floor is always an admitted candidate")
```

The calling round still checks whether actual floor waves fit `remaining` before a non-seed submission. Numerical boundaries must use the existing `remembers` semantics (`seen >= budget`), including equality. Construct the active key list once after choosing the final budget. No repeated `sub_spec`, `plan_strips`, dispatch or pool creation during budget enumeration.

Review correction: include remembered-threshold breakpoints, not only wave-derived budgets. Add a consumer-level regression where one unseen key needs10 seconds, another key is remembered at10, width1 and remaining15: one actual10-second job fits, whereas the wave-only algorithm underfunds it at7.5. Main executed the original algorithm and independently reproduced that counterexample before this correction.

- [ ] Pass the finalized plan into `_solve_round`; remove its duplicate grouping/filtering ownership. Preserve result fanout, stable winner selection, errors, actual-wall memo recording and per-entry `arms_tried`.
- [ ] Run focused strategy tests, then replay captured mall rounds and run actual mall CLI cases. Record raw demands/unique keys/memo hits/submitted jobs/waves/funded budget and unattempted versus attempted-refused blocks. Do not claim the mall target passes unless every block reaches composition.
- [ ] Review the source/test change for spec compliance and quality; integrate only after focused proof and review.

**Acceptance:** Duplicates and skipped work cannot create fictitious funding waves; higher budgets cannot incorrectly inherit lower-budget no-goods; deadlines and all existing seed/recut contracts survive. Real mall outcome is reported separately from this mechanism's correctness.

## Task 3: Repair the earliest reproduced composition defect

**Files:** Start with `compose.py` canvas registration/routing/power path and `test_compose.py`. If exact replay identifies a shared projection/catalog owner instead, modify that owner and its existing behavioral tests; record the evidence-backed ownership change before editing. Main serializes any `strategy.py` change after Task 2.

**Interfaces:** `PackedCanvas`, `ComposeResult`, existing `canvas_for`, `_route_all`, `plan_power_infill`, and strict finalization/certification. Do not add a fallback return type or public mode switch.

- [ ] Classify current replay failures into geometry registration, deadline propagation, internal work exhaustion, reservation access, or genuine unpowerable geometry. Preserve full entities/net identities and stage wall; the categories must come from the captured failing object.
- [ ] For a geometry mismatch, reduce the exact copied/routed/infilled entities until the same finalization rule still fails. Add a regression asserting legal emitted geometry through the real projection/validator, not private occupancy-table contents. Run it red.
- [ ] Repair the earliest invariant owner: use the existing catalog footprint/slot/coater/splitter query at the point where the entity is admitted or moved. Apply it to all callers of that invariant, not a building-id blacklist. Run the retained failing placement and transfer controls green.
- [ ] For a live-parent BUDGET case, instrument the passed deadline and existing work bound separately. Repair an actually stale/reset deadline or eliminate demonstrated duplicate work. An intentional expansion exhaustion is not permission to increase the bound; send that captured case to Task 4's discriminator experiment.
- [ ] If current source no longer reproduces a historical collision, retain the exact successful replay and make no speculative fix. Continue with current failed inputs. This is an explicit experimental result, not an implemented geometry repair.

**Acceptance:** Each retained source change has a failing exact replay that becomes valid without weakening rules; absent historical failures are explicitly distinguished. Re-run the real titanium CLI after changes. A named residual may leave the release target FAIL; it must never be relabeled fixed because a probe or a smaller factory succeeds.

## Task 4: Test whether reservation quality predicts real cut routability

**Files:** Evidence-local replay driver and result table; production `compose.py` only if the admission rule below is met. Existing `test_compose.py` covers held-safe top-up and bounded ladder behavior.

**Interfaces:** Replay identical solved `Placement` blocks and `LaneFlow` inputs into current `pack_with_access`/`compose`; existing gap rungs2,4,6,8,12,16, unchanged margin and parent wall. Snapshots are local diagnostic fixtures, not a persistent solved-block cache.

- [ ] Replay belt3/all, belt3/no-proliferator, zurl2/all and current titanium failures with the existing first-complete policy as control. Record missing demands, goal-held versus topped-up corridors, full unique failed NetIds, route kinds, area, and phase costs.
- [ ] Independently evaluate the existing gap rungs on the same input to learn whether a successful rung exists and what property before routing distinguishes it. Keep these diagnostic per-rung runs separate from a deployable schedule; they do not receive a six-times-larger production clock.
- [ ] Reject missing=0 or convergence alone as a success score. Admit a selection change only if a measured local/goal access property rejects the failing rung and retains the successful one across transfer cases within the existing ladder share. Preserve the current partial corridors and rollback; do not introduce full-route retries per rung.
- [ ] If no existing rung fixes the captured case, record that falsification and retain current selection. Feed the actual failed topology to the separate general experiment portfolio instead of inventing a bus or special case.

**Acceptance:** A bounded proven selection improvement, or a reproducible rejection of this lever with unchanged production policy. Both outcomes are legitimate experiment results; only real certified emission passes the corresponding factory target.

## Task 5: Verify source, measure acceptance, and retain honest outcomes

- [ ] Run focused changed modules together after edits settle, then the affected Python/static checks under the project's150-second suite ceiling. Keep inherited failures explicit; do not spend another full suite confirming user-reported inherited failures.
- [ ] Run actual installed CLI small hierarchy and selected-power cases; retain blueprint bytes and decode/certify results. A web UI change is not in scope; if implementation changes UI behavior, verify the real browser separately.
- [ ] Run the preregistered paired large matrix from the spec and four original titanium runs at each budget. Compare exact operating points. Record every failed target, source boundary, area and wall.
- [ ] Run the complete72-cell default guard before/after with explicit PLACED, matching128-CPU affinity, `--jobs 1 --budget 30 --strategy both --max-seconds 7200 --json <new path>`. The actual audit flag is `--json`, not `--jsonl`; it appends, so use fresh files. Compare72 identities, status losses, invalids/crashes and grace overruns. Universe's inherited six failures remain separately named.
- [ ] Perform independent task and final integration reviews; resolve load-bearing findings with regression proof. Update this plan, spec outcome, evidence report and existing `docs/speedup-idea-backlog.md`. Do not claim a failed large gate passed merely because source work is reviewed.
- [ ] After real smoke proof, remove only disposable diagnostics; retain the minimal replay fixtures, original failures, exact commands and review evidence. No unrelated worktree deletion, merge to master or push without the applicable user authorization.

**Completion report:** source commit/worktree; real emitted examples; target-by-target PASS/FAIL; original versus serial outcomes; area/wall; exact unresolved mechanisms; no all-CLEAN claim unless all72 actually passed at the named source and operating point.
