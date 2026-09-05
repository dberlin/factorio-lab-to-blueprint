# Additional Solver Lower-Bound Experiments

## Decision

Explore stronger proof-scoped relaxations, but do not treat an arbitrary CP-SAT or ILP bound as a final-layout bound. Every bound must name the closed subproblem it proves and remain sound for the authoritative lexicographic objective `(finalized area, post-compaction belt_tiles)`.

The first task is instrumentation, not another solver. The exact `information-matrix` pipeline invocation used for candidate parallelization has wall-time measurements but no per-process CPU or per-phase profile.

## Known evidence

### Exact pipeline case

- Three canonical candidates: no-proliferator, all-products, output-products.
- Two strategies per candidate: Freeform and SequencePair.
- All six attempts validator-clean; no refusals.
- Serial-candidate wall: 112.17 seconds.
- Parallel-candidate wall: 28.691 seconds.
- Winner: SequencePair `(area=4176, belt_tiles=2297)`.
- Earlier walls for the same three concurrent candidate portfolios: 15.15, 17.71, and 29.32 seconds.

The 83.479-second wall reduction proves that serial candidate admission was the dominant elapsed-time problem. It does not prove a reduction in aggregate CPU work and does not identify a solver hotspot.

No exact-case record currently contains process CPU time, CP-SAT deterministic time/bounds, or preparation/global-route/detailed-route/finalization/validation shares.

### Prepared-route proof harness

The separate no-power/internal eight-second `information-matrix` harness produced the same CLEAN winner `(7074,2823)` with pruning on and off. The audit observed:

- 76 prepared candidates;
- one real dominance hit;
- zero lower-bound violations;
- about 0.339 seconds, or 12% of detailed-route wall, behind the hit.

The production arm skipped two dominated prepared candidates and reduced detailed-route wall from about 2.826 seconds to 2.393 seconds, a 0.433-second or 15.3% reduction. This proves local value, not a share of the 112.17-second pipeline invocation.

### Similar large-case profiles

Existing 15-second profiles contain `universe-matrix`, `quantum-chip`, and `plastic`, not the exact information-matrix pipeline case. Post-throughput `universe-matrix` examples show:

- preparation: roughly 2.985–8.572 seconds;
- total routing: roughly 1.558–9.176 seconds;
- A*: roughly 0.417–1.564 seconds, or 3.2–9.9% of wall;
- power planning: roughly 0.635–3.131 seconds.

A separate 120-second SequencePair refusal spent 55–61% of wall in relaxed global routing, while detailed routing was only about 1–2 seconds. These are mechanism evidence only; they cannot be assigned to the exact pipeline case.

## Experiment 1: Capture the exact CPU and phase profile

Run the identical information-matrix URL pipeline in serial-candidate and three-way candidate modes. Preserve the six attempts and winner. Record per child:

- process user/system CPU time and peak RSS;
- candidate and strategy wall time;
- Freeform CP-SAT wall, deterministic time, status, objective, and best bound;
- SequencePair stages, preparation, global routing, detailed routing, compaction, finalization, validation, and encoding;
- prepared-bound candidates, hits, skips, hit time, and violations.

### Gate

- The profile itself must not change any attempt status or winner key.
- Proceed to a component-specific proof only when that component is at least 10% of exact-case CPU or wall in two attempts, or consumes at least one second in one attempt.
- Do not infer CPU savings from candidate concurrency; it overlaps work.

## Experiment 2: Obstacle-aware prepared-route floor

Strengthen `freeform._prepared_routing_lower_bound` for one concrete `_PreparedRoutingProblem`.

For each prepared net, compute a shortest path in a relaxed graph that retains immutable obstacles, route bounds, legal levels/ramps, and all endpoint alternatives, but ignores dynamic occupancy and inter-net conflicts. Keep:

- maximum path floor within each transitive `src_group`/`dst_group` sharing component;
- sum across components that cannot share route cells;
- protected template belts exactly as the current proof defines them.

Consume it through the existing `StageAdapters.exact_lower_bound` boundary immediately before detailed routing.

### Gate

- Audit-only first.
- Zero accepted-placement bound violations.
- Same six exact-case statuses and winner.
- Helper overhead below 2% of end-to-end wall and below 10% of detailed-route wall.
- Additional dominance hits cover at least 10% of measured detailed-route wall.
- Stop if relaxation time merely replaces detailed-router time.

## Experiment 3: Incumbent-area rectangle feasibility

For one prepared candidate, enumerate only bounding rectangles capable of beating the incumbent area. Each rectangle must contain the cleanup-invariant survivor skeleton. Use permissive connectivity to determine whether every sharing component can connect within the rectangle.

If no incumbent-improving rectangle is feasible even after ignoring inter-net conflicts, the candidate's area is proven dominated. At equal area, prune only when the sound belt floor also meets or exceeds the incumbent belt count.

### Gate

- Zero equal-area/fewer-belt false closures.
- Sub-percent end-to-end overhead.
- At least one additional exact-case area-dominance hit not found by the obstacle-aware belt floor.
- Stop if skeleton slack leaves every candidate rectangle feasible.

## Experiment 4: Cheap separator certificates

Before any multi-commodity ILP, test candidate-local graph certificates:

1. relaxed connected-component reachability;
2. selected x/y and obstacle-boundary separators;
3. capacity across all legal levels for unrelated route-sharing components.

A certificate may produce candidate-local `STRANDED` or an existing relation-scoped no-good only for the exact geometry/domain it proves.

### Gate

- Promote only certificates observed before expensive detailed calls in the exact case.
- Preserve sibling sharing and all legal elevated crossings.
- Stop before a full multi-commodity ILP if cheap relaxations always retain connectivity/capacity.

## Experiment 5: Retain exact local CP-SAT certificates

At `freeform._pack_result` and `_pack_window`, retain typed CP-SAT outcome and best-bound data instead of collapsing every non-install into `None`.

Safe uses:

- memoize `INFEASIBLE` for an identical fixed-height/window/no-good/variant submodel;
- avoid repeating the exact same one-second local-window solve;
- use a best bound only inside that same encoded CP objective.

Unsafe uses:

- treating `FEASIBLE`, `UNKNOWN`, or time limit as closure;
- mapping a width/HPWL objective directly to finalized area or belt count;
- extending a local-window certificate to a height, candidate, or unseen SA/LNS state.

### Gate

Proceed only if the exact profile finds repeated identical local submodels consuming at least one second. Otherwise retain instrumentation only.

## Deferred candidate-wide bound

A BuildSpec-wide mandatory-footprint relaxation could eventually avoid starting or cancel unfinished candidate races after a clean incumbent exists. It must cover every legal Freeform packing and SequencePair height/restart/SA/LNS state. A simple mandatory-ground-footprint bound is safe but likely weak; a strong exact relaxation risks recreating the full layout problem.

Do not implement candidate cancellation until an audit demonstrates a cheap BuildSpec-wide bound that dominates at least one real candidate before its race consumes material CPU.

## Non-claims

- No current evidence says CP-SAT dominated the 112.17-second exact run.
- No current evidence says detailed routing, global routing, preparation, validation, or finalization dominated it.
- `compact_seed.best_objective_bound`, Freeform packing width, and SCIP production objectives are not lower bounds on final `(area,belt_tiles)`.
- The current SA/LNS frontier is not exhaustive; no local proof establishes whole-search optimality.
