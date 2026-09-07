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
  than a physical bus lane (`hierarchy/compose.py`). **The BOUNDARY half of its
  oracle is structurally unreachable**, which is the v2 gate's headline finding:
  `compose` passes no boundary lanes, so every demand is internal, every
  internal demand has `reaches_boundary == False`, and both the reachability
  probe and the joint matcher's boundary validator skip it — the only thing the
  ladder can ever reject a rung over is a LOCAL doorstep claim. Measured: five
  composing cells, 31-168 port demands, rung 0 committed with `missing = 0`
  every time; the one firing in the whole gate is at strip cap 8, where rung 0
  missed one `internal-arrival` demand of 111, gap 4 satisfied it, and the
  router still refused 8 cut lanes. gate.md §3.4 and §6 lever 1.
- **DONE** A within-build no-good keyed on block shape (`_ShapeNoGood`,
  `stats["nogood_skips"]`), the first of v1 §7's three adaptive memories. Live
  but verdict-neutral: 36 skips on `mall/all-products`, 8 / 4 / 2 elsewhere,
  no cell's verdict, failure class or block count changed.

### From hierarchical v3

Branch `hierarchical-v3`, gated in
`docs/superpowers/evidence/2026-09-07-hierarchical-v3/gate.md` — also a
**FAIL** (0 of 8 large cells emit a blueprint), and again the failure moved.
Two of v2's three open levers closed as mechanisms; both malls now attempt
every block; and one cell reached `validate.certify` with every cut lane
wired, which no hierarchical build had ever done.

- **DONE** Every diagnostic the gate needs is carried into every refusal and
  printed by the CLI as `  stats <strategy>/<candidate>: key=value ...`
  (`cli.py`, `layout/base.py`, `hierarchy/strategy.py`). v3's gate harness
  monkeypatches nothing, where v2's had to wrap four production functions to
  read `nogood_skips`, `player_fed` and the composition gap. Limit: the line
  is printed on the refusal path only.
- **DONE** Round funding that does not divide a round's wall by WAVES alone,
  plus a global bound on re-cut growth: `block_budget = clamp(remaining /
  rounds_left / waves, 5, 20)` with `rounds_left = 1 + allowed_recuts -
  recut_rounds`, `MAX_RECUT_ROUNDS = 2` and `allowed_recut_rounds(wall) =
  min(2, max(0, int(wall // 5) - 1))`, which is 0 at the web UI's 15 s
  (`hierarchy/strategy.py`). **Effect: `blocks_unattempted` goes from 22 and
  45 on the two malls to 0 — and to 0 on all eight gate cells in both
  rounds.** This closes v2's "round funding" item outright.
- **PARTLY** The port-access oracle can now be asked a per-demand question:
  a demand carries its own reachability goal (`layout/freeform.py`) and
  `compose` gives each cut lane's demand its trunk partner's doorstep
  (`hierarchy/compose.py`). This supersedes v2's "make the oracle
  boundary-aware" item — the boundary half was structurally unreachable and
  the fix was to stop asking a boundary question at all. **It is inert in
  production**: `_match_access_corridors` exhausts `_ACCESS_CUT_ROUNDS = 8`
  and returns a wholesale EMPTY assignment, which the composer discards as an
  unusable answer and re-asks locally, recording `reservation_degraded = 1` —
  on all five composing cells in both rounds, ten runs of ten. v3 gate.md §5
  lever 1.
- **PARTLY** One arm per block, dispatched from a routing-difficulty feature
  key with widen-before-cut (`hierarchy/dispatch.py`). Measured cost where the
  key has no signal: on `mall/no-proliferator` the policy creates no spray
  lanes, so `coaters == 0` on every block and the whole cell goes to
  `sequence-pair` — **6 blocks never placed under both arms against 31 under
  one**. v3 gate.md §5 lever 3.
- **KILLED AT STEP 0** The bus corridor (design §4 E). Task 6 walked every
  `GAP_LADDER` rung on belt3 and zurl2 and found the oracle rejects no rung
  for a sealed-trunk reason (`missing_sealed = 0` on all twelve judged rungs);
  every rejection is the wholesale matcher give-up above.
  `corridor-spike.md` records the verdict and its own caveat: a corridor's
  value cannot be judged while the oracle cannot grade a rung.

Still open, and now with measurements behind them (v3 gate.md §5-§6):
- **Make `_match_access_corridors` return its partial assignment instead of
  giving up wholesale** — the headline lever. `freeform.py:11875` /
  `:11881`, `_ACCESS_CUT_ROUNDS = 8` at `:375`. It is a matcher-scaling
  problem with a worked counterexample, not a wall: zurl2's gap-16 rung came
  back complete at 144/144 in 4.17 s. Until it is fixed the ladder cannot
  rank a rung, `compose_gap` is pinned at 2 on every cell, and Tasks 4-5 are
  paid for and thrown away on every build.
- **Power the ground COMPOSITION adds.** `titanium-glass/all-products` at 60 s
  composes, wires all 26 cut lanes and fails `certify` with
  `errors_by_check == {power.coverage: 4}` — nothing else wrong with the
  placement. All four are cut-lane splitters; the canvas has 61 Tesla towers
  and 80 splitters, 76 covered and 4 not, because each block brought towers
  sized for its own footprint and the gap `compose` opens carries none. The
  smallest measured distance between this strategy and a validator-clean
  blueprint in three gates. v3 gate.md §2.3.
- **A bus corridor reserved BEFORE block placement** — design §4 E specifies
  it. Not dead, but not judgeable yet: the spike was killed at Step 0 because
  the oracle cannot grade a rung, and it should be revisited once the wholesale
  give-up above is fixed.
- **An "abstain" answer for `dispatch_arms`** on a feature vector the evidence
  does not cover: `coaters == 0` with `strips` under `UNCOVERED_STRIPS = 85`
  is currently indistinguishable from a genuine sequence-pair block
  (`dispatch.py:109-111`), and that is the 6-versus-31 regression above.
- The other two adaptive memories, **neither of them planned, each for a
  stated reason**:
  - *A cross-build solved-block cache.* Deliberately NOT planned: related work
    is already planned as the "background compound block cache" (`42c9e0e`)
    and duplicating it would be two designs for one cache.
  - *A strip cap that moves with outcomes.* Deliberately NOT attached to the
    `_ShapeNoGood` memo v2 shipped, because it is not cheap to attach:
    `_ShapeNoGood` is consulted BEFORE a block solve and keyed on
    `(shape, arm)`, while the signal the cap should adapt on is the ROUTER's
    verdict (unrouted lanes per cut), which arrives once per build after every
    block has already been solved and composed. There is no second composition
    within a build to feed it, so an outcome-driven cap needs a cross-build
    memory — which is the previous bullet.
- **A residual risk carried deliberately**, not a plan: Ruling R7's discard
  fires only on an assignment of exactly zero (`compose.py:899`), so a small
  PARTIAL assignment would commit and report `reservation_degraded = 0` — a
  stats line claiming a trustworthy verdict. No evidence either way; a narrow
  trigger was preferred to a tuned threshold. v3 gate.md §6.

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
