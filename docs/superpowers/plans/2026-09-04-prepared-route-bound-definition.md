# Prepared-Route Proof Bound Definition

Implemented by commit `4982494` (`feat: prune proof-dominated route candidates`).

## Exact bound

For a concrete prepared problem `P`, define the cleanup-invariant survivor skeleton

`S(P) = {all non-belt building templates} union {belt templates whose index is named by a non-belt template's input_obj or output_obj}`.

The area floor is the axis-aligned footprint of that skeleton:

`A_lb(P) = 0` if `S(P)` is empty, otherwise

`(max_{b in S}(b.x + b.width - 1) - min_{b in S}(b.x) + 1) * (max_{b in S}(b.y + b.height - 1) - min_{b in S}(b.y) + 1)`.

Certified boundary cleanup removes only belts and cannot remove one still named by a surviving non-belt. Routing and final-frame padding cannot shrink this survivor extent.

For the belt floor, let `F(P)` be the number of distinct protected belt indices above. Use the actual prepared route demand `P.nets + P.external_output_nets`, excluding `prelinked` nets. Direct-inserted nets are already absent from prepared demand.

For each net `n`, use planar endpoint sets:

- internal: four cardinal neighbors of source port to four cardinal neighbors of destination port;
- external input: prepared boundary goals to four cardinal neighbors of destination;
- external output: four cardinal neighbors of source to prepared boundary goals.

Then

`d_n = min_{s in starts(n), g in goals(n)} (|s.x-g.x| + |s.y-g.y| + 1)`, defaulting to zero only for an empty endpoint set.

Build undirected sharing components from the prepared nets' actual `src_group` and `dst_group` memberships. The belt lower bound is

`B_lb(P) = F(P) + sum_{component C} max_{n in C} d_n`.

The implementation deliberately ignores obstacles, altitude, ramps, access restrictions, and turn costs. Those can only lengthen an accepted route. Component maxima allow every legal sibling stem/merge reuse; separate components add because detailed routing does not permit their route cells to be shared.

The detailed call is skipped exactly when the current validator-clean incumbent `K*` satisfies

`K* <=lex (A_lb(P), B_lb(P))`.

Equality is safe because the candidate cannot strictly improve the authoritative lexicographic objective `(finalized area, post-compaction belt_tiles)`.

## Implementation points

- `src/flab2bp/layout/freeform.py`
  - Immutable `PreparedRoutingLowerBound`.
  - `_protected_template_belt_indices`.
  - `_prepared_candidate_area_lower_bound`.
  - `_prepared_routing_lower_bound`.
- `src/flab2bp/layout/sequence_solver.py`
  - Prepared-lower-bound observation at all four detailed-routing boundaries.
  - Audit violation detection and production proof-skipping.
  - Prepared-bound candidate, hit, skip, time, and violation telemetry.
  - No exact-stability or area-only optimal termination paths.
- `src/flab2bp/layout/route_feedback.py`
  - `DetailedRouteStatus.DOMINATED` records work intentionally skipped by proof.

## Safety evidence

Focused TDD covered:

- fixed-belt survivor accounting;
- unrelated sharing components adding their floors;
- related siblings using the component maximum;
- different legal sibling source taps;
- nearest external boundary goal selection;
- direct-inserted and prelinked demand contributing zero;
- later-better and equal-area/fewer-belts counterexamples;
- audit violations and pruning on/off equivalence;
- production telemetry and certified-placement behavior.

The final focused command passed 12 tests:

```bash
uv run pytest tests/layout/test_freeform.py tests/layout/test_sequence_solver.py -q \
  -k 'prepared_routing_bound or stable_observations_do_not_hide or temporary_non_improvement_does_not_hide or equal_area_with_fewer_belts_remains_open or prepared_lower_bound_audit or proof_dominated_prepared_skip_is_on_off_equivalent or sequence_backend_returns_only_certified_powered_placements'
```

An independent review found two soundness hazards during development:

1. sibling nets can legally choose different source taps, so the route floor must use the full sibling access sets rather than one selected tap;
2. a proof-dominated detailed-route result must use a neutral state transition rather than the generic failure transition, which changes the future quality frontier.

Both were corrected with red/green regression coverage before commit. Final review found no remaining Critical or Important issues.

## Measured gate

The audit-only five-case corpus covered:

- `single_recipe_spec()`;
- `two_stage_spec()`;
- `proliferated_spec()`;
- `plastic_spec()`;
- `information-matrix` with the no-proliferator candidate.

Final audit measurement observed 76 prepared candidates, one real dominance hit, zero lower-bound violations, and about 0.339 seconds—12% of detailed-route time—behind that hit.

The five-case pruning on/off comparison preserved every winner or refusal classification. The focused `information-matrix` comparison produced the same CLEAN winner `(7074, 2823)` in both arms. The audit arm observed one hit; the production arm skipped two dominated prepared candidates with zero violations and reduced detailed-routing time from about 2.826 seconds to 2.393 seconds in that run.

Published telemetry:

- `prepared_lower_bound_candidates`;
- `prepared_lower_bound_hits`;
- `prepared_lower_bound_skips`;
- `prepared_lower_bound_hit_time_s`;
- `prepared_lower_bound_hit_time_share`;
- `prepared_lower_bound_violations`.

Each skipped stage is recorded as `DetailedRouteStatus.DOMINATED` with `detailed_skip_reason == "prepared-lower-bound"`, consumes zero detailed-route expansions, and does not call the detailed adapter.

## Proof limits

- This proves domination only for one concrete prepared candidate. It does not cover unseen annealing/LNS placements and therefore does not prove whole-search optimality.
- The current SA/LNS candidate generator is not an exhaustive frontier; no termination is labeled `optimal` from this bound.
- `ROUTED` is an accepted route, not proof that the router minimized belt count.
- CP `FEASIBLE`, `UNKNOWN`, `BUDGET`, and `CANCELLED`, and router/validation budget outcomes remain incomplete/open rather than proof of exhaustion.
- Detailed exhaustive `STRANDED` evidence remains scoped to its exact routing/no-good domain, not a whole height or search universe.
- The area skeleton and belt floor are deliberately conservative; direct insertion, prelinked transitions, boundary cleanup, sibling sharing, external goals, obstacles, altitude, ramps, and spherical projection are handled only in the sound direction described above.
