# Speedup and solver-architecture idea backlog

Ideas raised on 2026-09-05/06 while discussing the multi-solver orchestrator
(`docs/superpowers/specs/2026-09-06-multi-solver-orchestrator-design.md`), the
tier corpus (`docs/superpowers/evidence/2026-09-06-tier-corpus/`) and the
density decomposition (`docs/superpowers/evidence/2026-09-06-density-decomposition/`).
Framing that binds all of them: coverage and bounded time first, area within a
10-20 % band of the best-known dense result, never "huge strips at near-zero cost".

## Running now (2026-09-06, four experiments)

1. **Routing-difficulty feature vector.** Per spec: for each item, consumer count
   x depth span; plus strips, ingredients per strip, coater count, above-one-belt
   items, both-fed items. Validate against this week's refusal rows. Becomes the
   orchestrator's dispatch input.
2. **Hierarchical decomposition prototype.** Rate-weighted min-cut of the recipe
   DAG into blocks sized for the existing placers, blocks solved independently,
   placed in topological order along a bus, inter-block trunks routed by the
   existing router. Measured on the mall, the compressed 436-machine URL and
   conveyor-belt-3 (coverage, wall, area vs best known). Kill criterion attached.
3. **Trunk pre-assignment for wide-spread items.** Reserve a bus corridor with
   taps for the highest-spread item (proliferator on all-products, copper ingot
   on malls) before placement, as a problem transform in front of both placers.
4. **Why direct insertion never lands.** Zero realized direct inserts on every
   corpus build despite hundreds of candidates; diagnose and fix or explain.

## Backlog (not started)

### Orchestrator and dispatch
- Anytime dispatch of strategy, budget and islands from the feature vector:
  cheapest solver that meets the class density floor, escalate only if time
  remains (design study §5 item 2; 18 of 72 cells pay 28 s for 2 % worse area).
- Narrow the race field to one arm only where the loser lost all three rounds of
  a paired gate; never for an unseen feature vector.
- Raise `DEFAULT_WORKER_BUDGET_CAP` on large boxes so raced builds get more than
  two islands per candidate.
- Gate reshaping: large-URL coverage and wall time primary, area as a tolerance
  band against a pinned best-known-dense figure, 72-cell corpus as the regression
  guard; `audit_compare` p95 default should be budget + grace.

### Structured and specialised solvers
- Revive `spine` (deleted 5072a93) as a port onto today's router/finalizer/
  validator, behind a spike with a kill criterion; it had 66/72 at 1 s and
  parity-to-better density; its six-lane fan-in cap is the port-access class.
- Coater-composite strips: treat spray coater plus strip as one unit so the
  placer never sees the keep-out problem (all-products class).
- Rate-aware nets for freeform (multibelt investigation Task 2): nets carry
  `(item, cargo_domain, rate)` and producer-to-consumer lane assignment is a
  transportation solve; fixes the `flow.belt_capacity` refusals.
- Lane multiplicity inside a strip (multibelt investigation Task 3) and a
  planner-side sorter-rate bound (Task 4).
- Freeform budget non-monotonicity: retain the best completed placement across
  the height sweep (multibelt investigation Task 5).

### Blocks and pre-generation
- Pre-generated block library keyed on recipe subgraph shape, proliferator mode,
  belt tier and machine tier; parametric in machine count; solved offline with
  minutes of budget. Top candidates from the tier corpus: copper-ingot + magnet +
  magnetic-coil (50 % of specs), circuit-board + copper + iron (52 %), gear +
  iron (41 %); two blocks cover 68 % of specs, eight cover 84 %.
- Cluster blocks by machine type as well as recipe adjacency: same footprint
  means same strip height, and uniform heights pack and tile far better.
- Cut-minimising block boundaries: rate-weighted min-cut so the fewest items
  cross a boundary; an item consumed at six positions wants its consumers in one
  block or wants to be a trunk.
- Pre-generated inter-block routes: a small family of trunk templates plus a
  per-block port assignment so inter-block routing becomes escape routing along
  a bus rather than free A* across the board.
- Topological block order along the bus so every trunk flows one way and port
  assignment is nearly forced.
- Block interfaces must carry shared trunks: the density spike showed the
  merge-frontier machinery is what makes multi-consumer lanes feasible, so an
  inter-block trunk feeding two blocks needs the same branching.
- Real saves ask for several targets at once; extend the tier corpus with
  multi-target specs sampled from real URLs so co-occurrence is not a floor.
- Subgraph mining beyond six recipes (the largest spec has 38 groups).

### Router
- Topological (produce-before-consume) net ordering as an alternative to the
  current fan-out-first, longest-first order with negotiated rip-up.
- A spread-aware priority: route the item with the widest consumer span first,
  not only the largest source family.

### Measurement debts
- Peak RSS for island pools is not recorded.
- The sequence-pair arm is no longer bit-reproducible across rounds (islands);
  `islands=1` still is.
- Direct insertion could not be measured as a density mechanism because it never
  lands (experiment 4 above).
- The no-sharing arm of the density spike also blanked two look-ahead probes, so
  it is slightly more crippled than a router designed without sharing would be.
