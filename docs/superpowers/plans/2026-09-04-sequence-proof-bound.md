# SequencePair Proof-Bound Experiment

## Decision

Do not build a full exact frontier first. The current SA/LNS generator does not enumerate a closed universe, and the detailed router does not prove minimum belt cost. A whole-search optimality claim would therefore be false.

Implement and measure the strongest local proof available before the CPU-expensive detailed router:

`prepared_lower_key = (candidate_area_lower_bound, protected_template_belts + sum(max(route_distance_floor) per legal-sharing component))`

Skip a prepared candidate only when a validator-clean incumbent satisfies `incumbent_key <= prepared_lower_key`. This preserves the existing lexicographic `(area, belt_tiles)` objective. It cannot stop unseen placements; it can avoid detailed routing for a concrete prepared placement already proved unable to win.

## Required invariants

1. `prepared_lower_key <= finalized_exact_key` for every accepted placement derived from that prepared candidate.
2. Fixed-belt term counts only distinct template belts protected from boundary cleanup by non-belt input/output references.
3. Route-distance term uses actual prepared nets after direct insertions and prelinked piler transitions are removed.
4. Nets connected by `src_group` or `dst_group` form one legal-sharing component; charge the maximum lower distance in a component, never the sum.
5. Different components are additive only because the detailed router forbids their belt-cell reuse.
6. Area comparison is lexicographic: any candidate with lower area remains open regardless of belt bound.
7. No CP `FEASIBLE`, `UNKNOWN`, budget, cancellation, or heuristic stability observation closes unexplored work.

## Implementation slices

### Slice A — exact-key contract

- Add the failing equal-area/fewer-belts pipeline selection test.
- Select candidates by `(area, belt_tiles)`, preserving valid-first behavior.
- Centralize the exact-key conversion only if existing local helpers can be reused without cross-module churn.

### Slice B — pure lower-bound helper

- Add a pure helper beside the prepared routing problem in `freeform.py` or a small existing routing module.
- Return an immutable typed breakdown: protected template belts, route floor, component count, and total.
- Build compatibility components with union-find or DFS over actual prepared net IDs.
- Compute endpoint-adjacent planar Manhattan floors; ignore altitude and obstacles.
- Handle internal, external-input, external-output, direct-inserted, and prelinked cases explicitly.

### Slice C — falsification tests

- Tiny prepared graphs: unrelated components add; siblings use max; direct/prelinked contribute zero; nearest boundary goal wins.
- Cleanup case: raw template belt count may exceed finalized count, but protected fixed count does not.
- Brute-force tiny grids where practical: assert helper bound never exceeds minimum distinct route cells.
- Production acceptance assertion in tests: for every accepted fixture, bound never exceeds final `belt_tiles`.

### Slice D — audit-only telemetry

- Record the breakdown and whether an existing incumbent would dominate it at each detailed-route call site.
- Do not prune yet.
- Stable stop remains disabled during the measurement so it cannot hide later candidates.
- Measure: safety violations, prepared candidates seen, dominance hits, detailed-route wall time behind hits, and final exact keys.

### Slice E — measured gate

Run deterministic representative cells covering small, direct-insert, sprayed/coater, external-output, and matrix-heavy builds under identical budgets/workers. Promote pruning only when:

- zero safety violations;
- at least one real dominance hit;
- hit candidates consume material detailed-route time (report absolute seconds and share);
- winners and refusal classifications remain identical with pruning on/off.

If the hit rate is negligible, retain only tests/telemetry needed to document the result and do not add production pruning.

### Slice F — safe production pruning

Only after the gate passes:

- expose `StageAdapters.exact_lower_bound(prepared)`;
- check it immediately before all four detailed-routing call sites;
- skip only on `incumbent_key <= lower_key`;
- add a distinct proof-backed observation/termination reason, never `infeasible`;
- assert any subsequently finalized key is not below its declared bound in test/debug paths;
- remove the observation-based `_has_stable_exact_incumbent` stop from any mode claiming optimum preservation.

## Explicit non-goals

- No parent-side process killing before proof messages exist.
- No cross-candidate cancellation before each candidate has a BuildSpec-wide bound.
- No candidate dominance by proliferation label or machine count.
- No claim of whole-search optimality without a frozen exhaustive frontier and min-cost route closure.
