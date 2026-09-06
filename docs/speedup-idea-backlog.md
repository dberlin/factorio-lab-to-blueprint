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

All four were built on branch `hierarchical-v1` as `--strategy hierarchical`
(explicit, default off) and gated in
`docs/superpowers/evidence/2026-09-07-hierarchical-v1/gate.md` — the gate is a
**FAIL** (no large cell builds), so "done" below means the mechanism exists and
runs, not that it produces a blueprint on a large URL.

- **DONE** Lane-contract block interfaces: a cut item's out-lanes and in-lanes must
  match in count and rate on both sides
  (`src/flab2bp/layout/hierarchy/contracts.py`). *Partly*: a rate shortfall is a
  `ContractError` refusal, not a merge/split — `zurl2/all-products` hit exactly
  that on `hydrogen` (`large-zurl2-all-products-r2.log`), so the merge/split the
  original item asks for is still open.
- **DONE** `_route_all` callable on a prepared canvas so composition reuses the
  real router (`src/flab2bp/layout/hierarchy/compose.py`). The router now runs on
  the composed canvas — and *refuses* the cut lanes on `DYNAMIC_ACCESS`, which is
  the gate's top lever. See gate.md §3.
- **DONE** Compositional finalization: `assign_sorter_slots`,
  `compact_open_boundary_belts`, `finalize_placement` and `certify` all run once
  on the composed placement (`hierarchy/strategy.py`).
- **DONE** Fix the negentropy-smelter 5-6 machine hole (`ee4ead43`, freeform's
  power broad phase now narrows to the candidate's own cleanup-survivor
  rectangle) and the sequence-pair stage-boundary crash (`caf893f3`, a seed-site
  merge a sibling cannot follow abandons the collapse instead of raising).
  Corpus effect measured: no cell regressed; `sequence-pair
  magnetic-coil/output-products` is reproducibly 4.3 % smaller (299 -> 286).

### From hierarchical v2

Branch `hierarchical-v2`, gated in
`docs/superpowers/evidence/2026-09-07-hierarchical-v2/gate.md` — also a **FAIL**
(0 of 8 large cells build), but the failure MOVED: five of the eight cells now
place every block, wire every cut and reach the router, where v1 had one.

- **DONE** Per-(block, item) cut allocation: a consumer block that cannot be
  fully served is left to the player when the parent spec belts the item in,
  else `ContractError`; a (block, item) is wired entirely or not at all
  (`hierarchy/contracts.py`). This closes v1's byproduct lane-contract item:
  `zurl2/all-products` used to refuse on `lane contract: hydrogen`, and now
  reaches the router with `block 16 : hydrogen` player-fed. **No `ContractError`
  occurs anywhere in the v2 gate.**
- **DONE** `partition.strip_count` counts what `freeform.plan_strips` actually
  packs rather than logical strip plans, so the cap is calibrated against the
  right quantity (v1 gate §6's "cheaper than all three" item). Effect: belt3's
  seed partition at cap 12 goes 3 blocks -> 9, the malls 2-3 -> 19 and 24.
- **PARTLY** Round funding: the hierarchical backend now receives the caller's
  raw `--workers` (or `None`) instead of a 16-capped race budget, the pool is
  `min(32, cpus // 4)` rather than `(workers or 16) // 4`, and the settlement
  reserve floor is 5 s rather than 10 s (`hierarchy/strategy.py`,
  `pipeline.py`). Effect: titanium-glass at `--budget 15` went from attempting
  NOTHING to placing and composing all six blocks. **Still open** on the malls,
  which refuse with 22 and 45 blocks never placed: the round's wall is still
  divided by WAVES and the re-cut loop still grows the block count without a
  global bound (gate.md §6 lever 2).
- **PARTLY** A gap ladder for the composition (`GAP_LADDER = (2, 4, 6, 8, 12,
  16)` under `LADDER_WALL_SHARE`, with `_reserve_port_access` over the outer
  ring as its oracle) — design §4 E's reservation, done as a searched gap rather
  than a physical bus lane (`hierarchy/compose.py`). **The mechanism exists and
  is structurally INERT as specified**, which is the v2 gate's headline finding:
  `compose` passes no boundary lanes, so every demand is internal, every
  internal demand has `reaches_boundary == False`, and both the reachability
  probe and the joint matcher's boundary validator skip it — the oracle can
  never answer "no". Measured: five composing cells, 31-168 port demands, rung 0
  and `missing = 0` every time. gate.md §6 lever 1.
- **DONE** A within-build no-good keyed on block shape (`_ShapeNoGood`,
  `stats["nogood_skips"]`), the first of v1 §7's three adaptive memories. Live
  but verdict-neutral: 36 skips on `mall/all-products`, 8 / 4 / 2 elsewhere,
  no cell's verdict, failure class or block count changed.

Still open, and now with measurements behind them (v2 gate.md §6-§7):
- **Make the port-access oracle boundary-aware for internal demands** — the
  cheapest unexplored lever, and the prerequisite for knowing whether a bus
  corridor is even needed, since until the oracle can reject a rung no wider gap
  is ever tried. v2 gate.md §6 lever 1 carries the file:line mechanism.
- A bus corridor reserved BEFORE block placement, rather than routing cuts on
  whatever ground the packing left — design §4 E specifies it. Evidence:
  28 / 15 / 9 / 4 / 3 unrouted cuts across the five composing cells, all
  `COMMIT_LINK` / `SEALED_POCKET` / `DYNAMIC_ACCESS` contention, while the
  reservation reports every port satisfied.
- Round funding that does not divide a round's wall by WAVES, and a global
  bound on re-cut growth, so a finer partition stops being self-defeating (the
  malls refuse with 22 and 45 blocks never placed even at a 32-wide pool).
- The other two adaptive memories: a cross-build solved-block cache (now much
  more valuable — the finer partitions are 6-29 mostly single-recipe blocks, and
  one mall refusal names nine consecutive `magnet` blocks) and a strip cap that
  moves with outcomes (cap 8 gives belt3 8 unrouted lanes against the shipped
  cap 12's 28). v2 gate.md §7 records the evidence for each.

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
