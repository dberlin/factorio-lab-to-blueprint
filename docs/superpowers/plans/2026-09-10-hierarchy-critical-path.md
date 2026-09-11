# Hierarchy Critical-Path Implementation Plan

> **For agentic workers:** Use subagent-driven-development with disjoint scheduler and routing ownership; Main owns integration, power-rule reuse and serial verification.

**Goal:** Reduce hierarchy's placement and completion critical paths without weakening physical legality, using the user's approved feasibility-first solver selection.

**Architecture:** Work in the existing hierarchy-continuation worktree rebased onto master a3b8ea8a. Preserve the restored uncommitted work and master transport/flow changes. Treat old .superpowers/router-geometric/candidate snapshots as historical evidence, not an overlay for current source. Submit block work on demand; cut useful smaller children before spending another round widening an already-refused parent. Preserve cancellation through projection and retain a successful exact disposable commit instead of repeating its physical construction. Reuse immutable power-spacing results through the existing functools-cache convention.

**Tech Stack:** Python 3.14, existing ProcessPoolExecutor/solver backends, Cython routing kernel, pytest, Ruff and mypy.

## Global constraints

- Original CLI URL, recipe policy, 60-second budget, 32-worker request, case affinity, strategy and rank remain unchanged for acceptance.
- Do not add retries, pool capacity, solver budget or finalization grace; no disabled certification checks.
- User selected feasibility first, then clarified a diminishing-returns time/density objective: roughly30s for2x density is worthwhile,120s for1.05x is not. Roughly15s is a desired fast feasible milestone, not a hard ceiling. Prioritize unsolved blocks and suppress blind optional comparisons; compare measured area and latency, retain naturally completed better results, and do not invent an unmeasured fixed exchange rate.
- No fabricated geometric evidence on timeout. Preserve genuine pre-timeout failures and search counters.
- No cached certificate across changed geometry, ownership, links, policy or spec. A committed partial route is not a complete factory.
- Existing master transport strategy remains available and unchanged.
- Pre-rebase stash 215d3a69b427c5d1a61c2dbc6a2c25008fa4ed7a is retained. Conflict resolutions keep master flank-collision regressions, prior exact projection caches, and both physical-flow regression families; obsolete implementation-pinning tests remain removed.

## Task 1: Demand-driven alternate solver dispatch

**Files:** src/flab2bp/layout/hierarchy/strategy.py; tests/layout/hierarchy/test_strategy.py.

**Consumes:** _RoundPlan grouped shape/arm jobs, existing _BlockJob, _ShapeNoGood, one build-local Executor.
**Produces:** Same _solve_round externally visible results and per-entry placement/verdict/arms_tried semantics, except approved feasibility-first offers; skipped jobs are not recorded as failed or tried.

- Replace eager pool.map submission/barrier with bounded submit/Future completion processing.
- Give each unresolved unique shape its first eligible offered arm before any fallback. Do not launch optional density work merely to fill idle capacity.
- On primary failure, make its next eligible arm available. If a shape succeeds, suppress unsubmitted alternatives. Retain naturally completed better valid results with stable ties, but do not wait solely for a small unmeasured density improvement.
- Preserve same-shape fanout, final-budget no-good eligibility, actual spent-wall no-good accounting, absolute parent deadline, and crash/pool-failure distinction.
- Keep funding conservative within existing limits. Do not refactor independent global strategy races.
- Regression scenarios: successful primary suppresses a queued alternate; failed primary reaches valid alternate; same-shaped consumers share one result; crashing worker never poisons no-good memory; different completion order preserves chosen valid outcomes.

## Task 2: Earlier useful decomposition

**Files:** same scheduler ownership as Task 1; existing partition APIs unchanged.

**Consumes:** _Entry attempts/verdicts/arms_tried, _next_cut, existing global recut limits.
**Produces:** Existing exact child units and rate-preserving derive_cuts flow, scheduled without the obligatory widen-before-cut round for a genuinely refused divisible parent.

- Prefer the next useful existing cut after a genuine parent refusal rather than automatically spending another round trying the full arm set on that same parent.
- If no useful cut exists, retain untried parent-arm fallback. Preserve finite per-entry attempts and global recut bounds; do not recursively create unfunded extra rounds.
- Do not cut successful blocks or interpret infrastructure crashes as structural refusal evidence.
- Regression scenarios: divisible refused parent progresses to exact conserved children before widening; indivisible parent retains alternate rescue; no-good children are skipped without exceeding attempt bounds; solved siblings remain unchanged.

## Task 3: Cancellation and exact committed ownership

**Files:** src/flab2bp/layout/routing_domain.py; focused routing regression tests. One integration owner for this file.

**Consumes:** _PreparationDeadline, _Canvas, _CommittedAttempt, source/sink/tap selections and RouteSettlement result types.
**Produces:** Budget/cancelled routing result with genuine evidence only, and caller-visible canvas owning exactly one successful committed workspace.

- Remove conversion of projection cancellation into a False collider verdict. Catch propagated cancellation at disposable routing/commit ownership boundaries, including candidate search callbacks.
- Never mutate the caller-visible physical canvas through a commit that can subsequently cancel or fail. Retain the successful disposable workspace and transfer its complete owned mutable state only when its exact selection is the returned selection.
- Do not reuse stale attempts after path/hint/primitive/ownership changes, repair, withdrawal or different best-round selection. Preserve existing complete settlement reuse; no new partial-completion certificate.
- Actual False projection, bad links and cycles remain real refusals and retain attribution.
- Regression scenarios: warmed projection cancellation propagates; cancellation during complete selection or linking produces budget evidence without synthetic COMMIT_LINK; late cancellation cannot publish a partial workspace; successful adoption preserves buildings, links, indexes and reservations; changed selected paths cannot reuse earlier proof.

## Task 4: Complete-settlement cost and immutable offsets

**Files:** src/flab2bp/dsp/rules.py and existing power-spacing tests; commit duplication removal in Task 3 contributes to completion cost.

- Use the existing standard functools cache for pure power_node_keepout_offsets. Keep ordered frozen PowerNode descriptors and explicit reach/levels in the key; keep immutable 3D output and exact predicate arithmetic.
- Preserve mutation-harness cache invalidation. Do not install a process-global mutable geometry cache or change final projected power checks.
- Measure the rebased implementation, not the historical candidate. Offset reuse is one bounded optimization, not a claim that 0.35 seconds alone closes the factory gap.
- Run the existing exhaustive spacing predicate oracle and nondefault/asymmetric descriptor controls. Verify completion retains all certification and projection phases.

## Verification and delivery

- Freeze rebased baseline source and native identity before new changes; exercise new regressions against the baseline and changed source.
- Build current native extensions and synchronize lockfile dependencies if needed.
- Run focused scheduler, cancellation, exact ownership, finalization and power/physical-flow tests. Run relevant integration checks serially after writers finish; distinguish baseline failures from newly introduced failures.
- Exercise both original hierarchy CLI contracts without the stale staged-source overlay or diagnostic capacity bypass. Decode every emitted blueprint and validate its full placement/certificate; compare machine counts, area, time and status. Report failures as failures rather than switching strategy to make the gate pass.
- Preserve original staged evidence separately. Review final changes for correctness and scope, run Ruff/mypy on affected source, update this plan and ~/report2.md with actual results.

## Implementation record

- Scheduler and lifecycle implementations are in the ordinary worktree source, not the historical experiment overlay. The fixed ceilings, worker limits, recut limits and final certification gates remain unchanged.
- Rebase prerequisite: native float solutions for merged fractional flows could not obtain an exact certificate. Added a connected-network rate-lattice reconstruction proposal after the existing denominator proposals, with repeated `(component, float)` reconstruction shared locally. Every proposal still passes the original exact node, arc and shared-resource checks.
- Removed two AST-identical duplicate definitions left by overlapping restored finalization work: `_BeltProjectionContext` and `_ProjectionCache.belt_failure`.
- Review found a last-mile cancellation accounting gap. Private expansion allowance is now debited in `finally`; interrupted strict and relaxed cluster runs retain spent work and elapsed time without fabricated geometric conclusions.
- Tests that capture a live routing gate now mutate that gate's actual private workspace rather than the caller canvas. Foreign-reservation exclusion and stale-proof withdrawal assertions remain intact.
- User documentation describes hierarchy's feasibility-first policy separately from the unchanged `best` portfolio.
- Final scoped regression run: 333 passed in 47.828 seconds. The broader run had 82 failures among 1,110 tests; 79 reproduced on the frozen baseline. Two private-workspace test setup mismatches were corrected, and the remaining 0.5-second case passed in the final run without a budget change.
- Ruff passes. Scoped mypy reports only two inherited `ortools.linear_solver` missing-stub errors; no type suppression was added.
- A matched 600/min gear CLI control emits the identical decoded payload before and after: 24 machines, 1,026 tiles, 381 buildings, zero validation errors. One observed pair took 9.753 seconds baseline and 7.977 seconds candidate; this is not a statistical large-factory speedup claim.
- Large-factory acceptance and final source-identity measurements are recorded under `.superpowers/hierarchy-critical-path/` and in `~/report2.md`. The 15-second milestone remains distinct from the original 60-second acceptance contract.
- Final source-immutable original trials still fail: all-products leaves 2 blocks unplaced at 15 seconds and 10/134 cuts unrouted at 60 seconds; no-proliferator leaves 4 blocks unplaced at 15 seconds and 136/290 cuts unrouted at 60 seconds. No blueprint is emitted in any cell. Implementation is complete, but large-factory acceptance and the 15-second target are unmet.
- Diagnostic runners are archived in `runners.zip` with byte-for-byte verification, then removed from active paths. Raw evidence and the pre-rebase recovery stash remain retained.
