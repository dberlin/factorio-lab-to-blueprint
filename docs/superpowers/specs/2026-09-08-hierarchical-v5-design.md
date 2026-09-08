# Hierarchical v5: actual work funding and composition reliability

Status: direction accepted by the user on 2026-09-08. Implementation and measured outcome are separate acceptance decisions. Baseline source: `bbc8889d`.

## Goal and scope

Make the existing hierarchy spend its bounded wall on real block jobs and deliver reliable, fully finalized compositions. Do not create another backend, restore mixed-item lanes, introduce recipe-specific behavior, weaken validation, increase search limits, or absorb the sibling-owned cross-build solved-block cache.

There are already real hierarchical blueprints. V4's original titanium-glass/60-second series emitted 1/4; separate successful certification rebuilds had zero errors. V4's large gate failed. Existing success is neither scaffolding nor reliable coverage. V5 must report both facts.

## Evidence

- [V4 gate](../evidence/2026-09-07-hierarchical-v4/gate.md): 17 REFUSED / 18 original large runs; titanium routing-budget and finalization failures; both malls fail to reach composition.
- [Real mall block replay](../evidence/2026-09-07-hierarchical-v4/packer-defect.md): captured recut block20, not initial partition index20; 15 attempts over five heights, static/dynamic access failures, no BUDGET and no common failing logical net. More wall is not the demonstrated lever.
- Current `strategy.py` counts raw block-arm pairs to fund waves, then `_solve_round` deduplicates shape-arm jobs and skips call-local no-goods. This accounting mismatch is confirmed; its contribution to mall starvation is not yet measured.
- Current `compose.py` already retains partial reservations, tops up only missing demands without disturbing held corridors, bounds its gap ladder, and infills power. `reservation.complete` stops the ladder even when the completed reservation came from a nonconverged top-up. Missing=0 is not evidence of routability.
- [Universe diagnosis](../evidence/2026-09-08-universe-refusal-diagnosis/README.md): earlier 72/72 and final 66/72 used different source geometry and operating points. Universe repair is a separate general-topology experiment portfolio, not evidence that v5 may weaken physical rules.

## Alternatives and decision

1. **Raise budgets / thresholds:** rejected. Block20 exhausts its admitted search, and the measured sequence dispatch floor exceeds the current block cap; increasing wall is not a causal repair.
2. **Replace hierarchy with a bus or add persistent caching:** rejected here. A bus proposal already failed without grading the actual sealed-trunk condition; cache ownership is separate.
3. **Fund actual work, then repair the earliest demonstrated composition failure:** selected. Reuse current partition, block arms, pool, router, and strict finalization. Capture exact stage inputs so geometry and clock failures are not conflated.

## Invariants

- Mixed-item input lanes remain banned. No recipe-id, URL-id, or corpus-index predicates in production behavior.
- Block budgets remain 5–20 seconds; global recuts remain at most two; per-entry split attempts remain at most four. Existing parent deadline clipping and settlement reserve remain binding.
- Compute offered arms once per round. Preserve explicit single-arm requests, shape identity, once-per-build no-good lifetime, genuine-refusal-only memoization, and stable submission/fanout order.
- Fund deduplicated work using no-good eligibility at the final funded budget, not a stale budget. Increasing a budget can reactivate previously remembered jobs.
- A block cannot outlive the parent deadline. An unaffordable seed round still attempts the existing clipped seed; later unfunded work is explicitly unattempted, not proved impossible.
- Preserve held-safe top-up and cancellation rollback. Do not substitute convergence for completeness or completeness for routing success.
- Compose, assign sorter slots, compact, project, and certify the same candidate. No unwired, unpowered, colliding, or uncertified candidate is emitted.
- Capture exact objects at the failing phase. Rebuilding a fresh stochastic layout is not certification of earlier bytes.

## Funding design

Build one stable ordered map `(ShapeKey, arm) -> consuming entry slots` before funding. Derive raw demand, unique work, and the memo threshold of each key from that map. The selected round record contains the final budget and the exact active keys to submit. `_solve_round` consumes that record rather than deriving a second work list.

For width `W`, remaining block wall `R`, and rounds left `L`, evaluate the finite budget breakpoints:5,20, every remembered threshold within5–20, and `clamp(R / L / waves, 5, 20)` for wave counts1 through `ceil(unique/W)`. In descending budget order, count keys whose remembered threshold is strictly below the candidate budget; accept the first whose budget fits `clamp(R / L / actual_waves, 5, 20)`, or whose active work is zero. Including remembered thresholds is essential: thresholds `[-inf,10]`, width1, remaining15, one round have optimum10 seconds for one job; wave-only candidates incorrectly select7.5. Reject a non-seed round only if its actual waves at the five-second floor cannot fit remaining block wall. Preserve existing floor borrowing and seed clipping rather than inventing new recut limits.

This is a finite bounded calculation over already discovered keys. No repeated strip planning, speculative block solving, additional threads, or cross-build state. Sorted refusal thresholds plus binary search count active work without rebuilding key collections for each budget breakpoint.

## Composition work: causal admission gate

Capture, on current source, the solved blocks and flows entering `compose`, its exact output before slot assignment, and the placement entering finalization. Capture full per-net status and router termination reason rather than the first 400 characters of a refusal.

A production repair is admitted only when a retained input demonstrates one of these boundaries:

- **Geometry registration mismatch:** a copied or newly emitted entity is legal on the routing canvas but collides after a deterministic slot/compaction/projection step. Repair the earliest incorrect occupancy/attachment calculation using catalog rules. Do not add a late validator exception or blacklist the reported building.
- **Clock/work mismatch:** routing ends BUDGET despite a live parent deadline. Distinguish an internal work bound from an accidentally clipped/reset deadline before editing. Preserve both bounds; remove duplicate work or repair deadline propagation, never increase a constant merely to pass.
- **Reservation/routing mismatch:** a topped-up complete reservation still strands cuts. On the identical solved blocks, compare existing gap rungs and retain full route outcomes. A rung-selection change needs a replay showing an earlier observable access property discriminates the failed and successful rung within the existing ladder budget. Missing count alone does not qualify.

If a historical failure no longer reproduces, retain that result and move to the next current failing capture. Do not invent a geometry patch for an obsolete failure. General new block geometries belong to the separately prepared experiment portfolio.

## Measurement contract

Preregister source/dependency/catalog hashes, exact URL, policy, coater mode, rank, tower, band, worker count, CPU affinity, layout budget, wall, exit status, and emitted-byte hash. Baseline and candidate use the same values. Diagnostic instrumentation is not an uninstrumented timing gate.

Use PLACED explicitly. For the large hierarchy matrix use 32 requested workers, CPUs 0–31, one case at a time, budgets 15/60 seconds, and the existing six-second pool completion grace. Record this as a new paired operating point, not a reproduction of v4's unspecified worker allocation. The default 72-cell guard uses 128 workers per cell through `--jobs 1`, CPUs 0–127, budget30, on both sources.

V5 targets: titanium60 emits and certifies 4/4 original runs; titanium15 emits at least once in four original runs; both mall policies place every block and reach compose at60; no new loss of a paired-baseline CLEAN cell, invalid output, crash, or grace overrun. Other retained large cases must have full named failure evidence, not truncated prefixes. Smaller starvation counters alone do not pass the mall target. Report area against the paired emitted baseline and historical dense references; flag >20% expansion rather than hiding coverage gains in huge layouts.

Original failures remain failures even if a failed-case serial rerun passes. Any target not met leaves the corresponding v5 gate FAIL; an implemented funding mechanism is not the whole large-case acceptance.
