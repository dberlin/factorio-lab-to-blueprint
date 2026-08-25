# Sequence-Pair Search Quality Design

**Status:** Approved by user instruction; implementation pending

## Problem

On the refinery max-proliferation candidate, Freeform and SequencePair solve the same 14 strips and 30 nets at the same final height, but SequencePair is 75 tiles wide against Freeform's 46. Final area is 1,950 versus 1,196 and belt count is 957 versus 675.

Raising SequencePair from 30 seconds to 60 seconds does not improve the winning candidate: area, belts, building count, and bounds remain exactly 1,950 / 957 / 1,048 / 75×26. Additional time improves only losing candidates.

The 30-second SequencePair run spends:

- 11.63s placement/SA;
- 13.92s relaxed global routing;
- 0.53s detailed routing;
- 4.13s validation;
- 33 global routes and 10 detailed routes across five heights and two restarts;
- zero LNS, split, merge, feedback-cell, or stranded-net work.

The search pays for routing feedback that has nothing to teach on this easy-to-route instance, while every height/restart receives only one shallow stage. Blended cheap energy can also exclude the narrowest candidate from the elite set before exact routing.

## Decision

Keep the current correctness architecture and change only search policy:

1. retain a deterministic Pareto elite archive, including the narrowest legal candidate independently of blended energy;
2. group restart discovery by height and route once per height after all restarts contribute elites;
3. after a height produces zero global overflow and a validator-clean detailed route, enter quality mode;
4. in quality mode, detailed-route the narrowest candidate every stage and skip relaxed global routing until detailed routing fails;
5. on detailed failure, leave quality mode, run global routing, update feedback, and resume closed-loop LNS;
6. allocate post-discovery stages best-first to the height with the best exact incumbent or near-exact route;
7. record complete incumbent geometry and score components.

Global routing remains authoritative only as a proxy. Detailed routing plus validation remains the only exact acceptance gate.

## Elite archive

Each fixed-cardinality stage returns a deterministic union of these distinct candidates:

- `blended`: minimum existing `SearchEnergy`;
- `narrowest`: minimum `(hard_overflow, width, used_height, gap_area, hpwl, key)`;
- `lowest_hpwl`: minimum `(hard_overflow, hpwl, width, gap_area, key)`;
- `lowest_history`: minimum `(hard_overflow, history_cost, width, hpwl, key)`;
- the remaining best blended elites up to the configured cap.

Candidate identity uses exact `PlacementKey`; duplicates across categories appear once. The narrowest legal candidate is always eligible for exact routing even if it has worse blended energy.

## Energy and objective modes

### Exploration mode

Use existing Metropolis walk and blended energy to cross local minima. The archive independently preserves width/HPWL/history extremes.

### Quality mode

A height enters quality mode only after:

- global overflow is zero; and
- detailed routing and validation produce an exact incumbent.

The SA walk may still accept wider moves by temperature, but incumbent/archive comparison is width-first:

```text
(hard outline overflow, width, used height, gap area, HPWL, key)
```

Quality candidates cannot displace an exact incumbent except through the existing exact `(placement.area, belt_tiles)` comparison.

## Grouped discovery

A discovery unit is one height, not one `(height, restart)`.

For each height:

1. run one cheap SA stage for every restart;
2. union their Pareto archives;
3. relaxed-route the bounded archive once;
4. select one candidate for detailed routing;
5. record exact/near-exact state and feedback.

Every height still receives one discovery unit before exploitation. Discovery retains deterministic restart seeds and equal expansion reservations, but eliminates duplicate route/validation passes per restart.

## Adaptive routing cadence

For a height in exploration mode, route the bounded Pareto archive globally and detailed-route the selected candidate as today.

For a height in quality mode:

- skip global routing;
- detailed-route the current narrowest legal archive candidate;
- if it routes and validates, retain/replace the exact incumbent by `(area, belts)`;
- if it fails or is cancelled, restore normal global routing and feedback on the next stage.

A skipped global route consumes zero expansion budget and is explicitly recorded. No proxy result is fabricated.

## Height exploitation

After grouped discovery, schedule the next height by:

1. smallest exact incumbent key;
2. fewest detailed stranded nets;
3. zero-overflow global state;
4. smallest narrowest legal width/area;
5. least expansion/time already spent;
6. stable original height order.

A height may receive repeated quality stages while it remains the best exact height. Other heights are revisited when it stagnates, fails detailed routing, or another height's exact key is better.

## Observability

Record per stage and final incumbent:

- objective mode;
- restart and height;
- pack width, target height, used height, box area;
- explicit gap area;
- weighted HPWL;
- spatial history cost;
- missed direct inserts;
- archive category membership and exact `PlacementKey`;
- global routing skipped/executed and reason;
- overflow, stranded nets, route times, expansions;
- quality-mode entry/exit and stagnation count.

Stats are written after decisions and cannot affect ordering.

## Constraints

- No changes to pose, collider, slot-anchor, coater, serializer, altitude, validator, or production `best` rules.
- No Numba/JAX work.
- No increased default time budget.
- No removal of global or detailed correctness gates.
- No timing assertions in pytest.

## Verification

- A blended-energy winner cannot remove a distinct narrowest candidate from the archive.
- Archive order and deduplication are deterministic.
- Grouped discovery runs all restarts but exactly one global/detailed selection per height.
- Every height completes discovery before exploitation.
- Zero-overflow exact success enters quality mode.
- Quality mode skips global and still detailed-routes narrowest.
- Detailed failure exits quality mode and produces feedback on the next stage.
- Exact incumbents remain ordered only by `(area, belt_tiles)`.
- Stats report exact candidate geometry/energy without changing decisions.
- Full tests, broad audit, and both supplied game-aware URLs remain validator-clean.
- The refinery max-proliferation SequencePair candidate is re-run at 30s and 60s against baselines 1,950/957 and Freeform 1,196/675. Results are reported even if quality does not improve; no threshold is baked into tests.
