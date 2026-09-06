# Speedup and solver-architecture idea backlog

Ideas raised on 2026-09-05/06 while discussing the multi-solver orchestrator
(`docs/superpowers/specs/2026-09-06-multi-solver-orchestrator-design.md`), the
tier corpus (`docs/superpowers/evidence/2026-09-06-tier-corpus/`) and the
density decomposition (`docs/superpowers/evidence/2026-09-06-density-decomposition/`).
Framing that binds all of them: coverage and bounded time first, area within a
10-20 % band of the best-known dense result, never "huge strips at near-zero cost".

## Experiments run 2026-09-06 (evidence under `docs/superpowers/evidence/2026-09-06-exp-*/`)

1. **Routing-difficulty feature vector** (`exp-features`, plus experiment 5:
   live range and cut pressure). Strips and distinct items predict freeform
   wall better than spread; summed live range is the best wall predictor
   (rho 0.93 vs 0.88 for strips, inside the data's resolution); items above one
   belt is the only zero-false-positive refusal signal; coaters is the arm-choice
   feature. Lane pressure equals item pressure on every corpus cell. Proliferator
   is never an ingredient (scored from spray lanes). Dispatch key: strips,
   sum_live_range, items_above_one_belt, coaters. Sequence-pair wall is
   budget-bound on every corpus cell, so its timing carries no difficulty signal.
2. **Hierarchical decomposition prototype** (`exp-hierarchical`): GO with
   conditions. Validator-clean blueprints for belt3, zurl2 and BOTH malls (449
   and 935 machines, which refuse everywhere today). zurl2 composed at 0.78-0.82x
   the best known area; belt3 at 1.23x with the cut-pressure partition (1.52x
   with the size cap: kill criterion fired by 1.2 %). Sum of block areas is
   1.05x the monolith, so the overage is composition packing. Cut pressure
   picks where to cut (16 % area, 40 % serial wall on belt3) but does not predict
   block hardness; strip count does. Conditions: block interfaces are lane
   contracts (10 of 11 zurl2 cuts mismatch lane counts; the malls go INVALID on
   one `flow.conservation` when corridors are wired); `_route_all` is not
   callable on a prepared canvas; finalization is not compositional
   (`power_too_close`, gap >= 2, latitude bands at 935 machines); 8-21 belt
   loops left to the player. Side findings: a one-recipe negentropy-smelter spec
   refuses at 5 and 6 machines on both placers at any budget; a
   `SequencePairLayout` stage-boundary crash (`sequence_solver.py:2660`).
3. **Trunk pre-assignment** (`exp-trunk`): dead. 0 refusals rescued, 5 cells
   broken, area +5 % and belt tiles +8 %. The proliferator supply tree already
   is a perimeter trunk with taps, and producer sharding has dissolved every
   internal fan-out. The default-off switch lives only on branch `exp-trunk`
   (commit e4679db); master carries the evidence.
4. **Direct insertion** (`exp-direct-insert`): tuning, not a bug. The mechanism
   validates when forced; a bridge costs 1.5-2.9 tiles of area per belt tile
   saved, so the packer's width-first objective correctly refuses it. A
   documented clearance defect in `_direct_clear_columns` (proves clearance
   only against the bridged lane's own attachments) is unfixed; patch in the
   README. Block libraries should not assume direct insertion for density.

6. **Pressure-driven place and route** (`exp-pressure`, gate in
   `exp-pressure-gate/`). Corridor width by lane pressure: dead (reserved rows
   move the height sweep, area moves both ways, belt tiles never track the rows
   bought; it did move belt3 no-proliferator from a routing refusal to a
   belt-capacity validator refusal, 42-45/s on a 30/s tier). Net order by cut
   pressure: bimodal. Large reproducible wins (belt3 route_all -36 %, mall
   -44 %, quantum-chip[2] -48 %, zero area change) but about four cells
   genuinely slower by 18-90 % and a bit-identical +6.4 % area regression on
   sequence-pair information-matrix/output-products (the switch also reorders
   sequence-pair nets via `_build_prepared`). Three-round gate: 0 regressions,
   INVALID 0, CRASH 0, overshoot 0, freeform area +0.1 %, but the corpus
   route_all clause FAILED (0.96 / 0.98 / 1.11; the same-arm control moves
   +16.7 %, so the metric cannot resolve it on cells under 0.5 s). Default not
   flipped; both switches live only on branch `exp-pressure` (commit 3fc11be5);
   master carries the evidence. Next step if revived: a cut-pressure threshold
   predicate deciding WHEN to apply the order, then re-gate. Also found:
   `audit.py` emits no `route_all_s` (only `prof_harness` installs the tally),
   so the gate used `detailed_route_time_s`.

## Backlog (not started)

### From experiment 6
- Cut-pressure threshold predicate for the net order (apply only above a lane
  pressure / strip count floor); scope it to freeform or gate sequence-pair
  separately.
- Emit `route_all_s` and rip-up rounds from `audit.py` rows so routing time is
  gateable without the harness.

### From the hierarchical prototype (a production version must solve first)
- Lane-contract block interfaces: a cut item's out-lanes and in-lanes must match
  in count and rate on both sides, or the corridor must merge/split.
- `_route_all` callable on a prepared canvas so composition reuses the real
  router instead of a corridor router.
- Compositional finalization: power towers, gap rules and latitude bands checked
  on the composed placement, not per block.
- Fix the negentropy-smelter 5-6 machine hole and the sequence-pair
  stage-boundary crash.

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
