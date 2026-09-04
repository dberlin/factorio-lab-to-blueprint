# Phase B: Complete Last-Mile Router With Real No-Goods

**Status:** Executed 2026-09-02 on branch `phase-b-last-mile` (725c34e..11c6a9c); corpus gate FAILED: 65/72 CLEAN at 30 s in all three candidate rounds against a 64/65/65 baseline (target 67), both required cells still REFUSED, no regression, INVALID 0, CRASH 0, paired area ratio 1.0068, wall p95 31.6 s / 31.8 s over the 31 s threshold (see `docs/superpowers/evidence/2026-09-02-phase-b-last-mile/gate.md`). Three items are OPEN and deferred: (1) a CBS solution the commit preflight refuses because non-cluster nets keep stale hints at stake time (`last_mile_commit_rejected = 2` on `quantum-chip/all-products`); the rollback is complete so no state is poisoned, but the only known fix, refreshing those hints at stake time with hints added to `_round_state`, is unbounded; (2) run 2 is corpus-inert: the sibling gate turned away 100% of run-1 proofs on both target cells, so `ClusterRelationNoGood` has unit coverage only and §5.2's follow-up trigger has fired; (3) §5.2 follow-up option 2 (unstake only non-cluster, non-sibling nets) is the recorded next step and was not attempted.
**Predecessor:** `docs/superpowers/specs/2026-09-01-evaluation-throughput-design.md` (Phase A, merged at `b3c990a`)
**Successors:** Phase C (ALNS placement with a CP-SAT window repair), Phase D (portfolio racing)

## 1. Decision

Give the detailed router one bounded, complete search over a small conflict
cluster, run at most once per `_route_all` call, and turn its two decisive
outcomes into either a routed pack or a proof.

Today `_route_all` (`freeform.py:7082`) is negotiated-congestion
rip-up-and-reroute: up to `RRR_MAX = 8` rounds (`freeform.py:295`), collapsed to
a single round when `len(nets) >= _SINGLE_ROUND_NETS = 64` (`freeform.py:299`,
`8338`), with up to `_REPAIR_PASSES = 4` crossing-repair passes per round
(`freeform.py:396`, `8550`) that relocate at most `_REPAIR_MAX_VICTIMS = 16`
victim paths (`freeform.py:390`). When that finishes with nets still unrouted,
the pack is discarded and the only thing learned is soft, decaying feedback
(`route_feedback.update_feedback`, `route_feedback.py:294`). Nothing ever
proves the leftover nets cannot be wired, and nothing searches jointly over
them and their blockers.

Phase B adds:

1. **A conflict cluster.** The stranded nets, plus the nets their blame walls
   and blocker lists name, closed transitively to at most `B_MAX_CLUSTER = 8`
   nets. Every cluster path is released from the canvas; every other net's
   path, every building, reserved corridor, guard cell and junction ban stays
   fixed.
2. **Conflict-based search (CBS) over that cluster.** The low level is the
   existing `_astar` (`freeform.py:6198`) with per-net `forbidden` cells — a
   parameter it already takes — run under a private per-search expansion
   allowance of `B_LOW_LEVEL_EXPANSIONS = 50_000`. The high level is a Python
   best-first tree over the sum of path costs, splitting on the first shared
   cell, bounded by `B_MAX_CBS_NODES = 512`, one share of the pack's remaining
   expansion budget covering both runs, and the wall deadline. **Any low-level
   result whose `kind` is `RouteFailureKind.BUDGET` — from the private
   allowance, from the shared budget, or from the deadline — forces the whole
   run to `BOUNDED`.** A tree that closes only because a search was cut short
   has not searched the space and must never be read as if it had.
3. **Two decisive outcomes.** All cluster paths found: stake them through the
   same commit preflight the round uses and finish the pack as routed. Tree
   closed inside its bounds with no search cut short: the cluster's nets cannot
   be routed with the rest of this pack's routing where it stands, which sets
   `DetailedRouteResult.exhaustive` (`route_feedback.py:125`) and, through
   machinery that already exists, produces an `ExactPackNoGood`. Bounds hit
   without either: nothing is claimed, and the pack stays stranded exactly as
   it does today.
4. **A second, stronger statement when run 2 also closes — and only when the
   cluster has no siblings.** When run 1 closes and every cluster net is
   *sibling-free* (`src_group[i]` and `dst_group[i]` both empty), the pass
   unstakes **every** net in the pack — the same `_unstake` sweep the round
   itself performs at the top of each round (`freeform.py:8342`-`8343`) —
   temporarily clears the cluster nets' five routing-derived rejection sets,
   and re-runs CBS. That environment is buildings, keep-outs, the routing box,
   permanent guards and junction bans, and nothing else: every port corridor is
   retired as if its role had been served, `planned_taps` starts EMPTY, and
   `_can_junction`'s one check that tightens as that table shrinks is exempted
   for the duration of the run (§5.2, the loosest-world rule). A tree that
   closes there yields a new
   `ClusterRelationNoGood` naming the cluster's strip instances and their
   relative placement. Freeform's `_pack` (`freeform.py:3179`) forbids that
   relative placement with `add_forbidden_assignments`, exactly as
   `_DirectRelationNoGood` is modelled today (`freeform.py:3415`-`3446`). The
   sequence-pair solver consumes it through its existing relation-repair path
   (`sequence_solver._projection_feedback_stage_update`,
   `sequence_solver.py:2767`). Every net is then re-staked in its original
   stake order with the hints it was staked with, and the same state comparison
   that guards run 1 decides whether the pass may claim anything at all.

   The sibling-free condition is not conservatism: `_ends` builds merge
   frontiers out of sibling paths (§2.2), so unstaking a sibling can remove the
   *only* way a net reaches its lane. Without the condition, run 2 would report
   a closed tree for a net it had disconnected, and that false proof would
   become a region exclusion in both packers and travel on to Phases C and D.
   When the condition does not hold, run 2 is skipped and
   `last_mile_relation_skipped_siblings` is counted.

No search behaviour outside `_route_all` changes, no budget is retuned, no
strip planning or scheduling is touched, and a pack with zero stranded nets
never enters any new code path.

## 2. Evidence

### 2.1 The seven refusing cells

Three interleaved rounds at `--budget 30 --jobs 16`, both strategies, 72 cells,
committed under `docs/superpowers/evidence/2026-09-01-evaluation-throughput/candidate-budget30-round{1,2,3}.jsonl`.
Every round: 65 CLEAN, 7 REFUSED, INVALID 0, CRASH 0. The same seven cells
refuse in all three rounds. Their `detail` strings, verbatim from round 1
(truncated only where the audit row itself truncates):

| # | Cell | Wall | `detail` |
|---|---|---:|---|
| 1 | freeform `universe-matrix/no-proliferator` | 29.6 s | `every packing that wired was rejected by our own validator (game.blueprint_area; findings: band 0 game.blueprint_area (): a 507x163 extent fits no band on a segment-200 planet: it needs 163 latitude r…` |
| 2 | sequence-pair `graphene/output-products` | 2.3 s | `no scheduled stage produced an exact layout` |
| 3 | sequence-pair `quantum-chip/no-proliferator` | 34.8 s | `deadline exhausted before finding an exact layout` |
| 4 | sequence-pair `universe-matrix/no-proliferator` | 21.7 s | `deadline exhausted before finding an exact layout; no legal DSP latitude band/orientation accepts the final placement: band 0 game.blueprint_area (): a 1334x131 extent fits no band on a segment-200 pl…` |
| 5 | sequence-pair `universe-matrix/all-products` | 27.2 s | `deadline exhausted before finding an exact layout` |
| 6 | **freeform `quantum-chip/all-products`** | 30.8 s | `the 30s deadline passed with no completed packing of 28 strips; 8 packs were routed in that time and the best of them still left 1 nets unrouted (worst 2), so a longer clock alone would not have wired…` |
| 7 | **freeform `universe-matrix/output-products`** | 31.4 s | `the 30s deadline passed with no completed packing of 46 strips; 5 packs were routed in that time and the best of them still left 1 nets unrouted (worst 1), so a longer clock alone would not have wired…` |

Cells 6 and 7 are the two Phase B targets. Their stranded counts across the
three rounds:

| Cell | round 1 | round 2 | round 3 |
|---|---|---|---|
| freeform `quantum-chip/all-products` | 8 packs, best 1, worst 2 | 8 packs, best 1, worst 2 | 7 packs, best 1, worst 1 |
| freeform `universe-matrix/output-products` | 5 packs, best 1, worst 1 | 5 packs, best 1, worst 1 | 5 packs, best 1, worst 1 |

Both refuse with **one** net unrouted on their best pack. That is the number
`B_MAX_STRANDED = 3` is sized around, and it is why a bounded joint search over
a handful of nets is the right instrument rather than a bigger clock: the
refusal text itself says "a longer clock alone would not have wired this spec"
(`freeform.py:15857`-`15863`).

Cells 1 through 5 are not Phase B's to fix: 1 and 4 are placements whose extent
fits no latitude band (a placement-shape problem, Phase C's `BAND_BOUNDARY`
operator), 2 is `_search_stage_cap`'s fast-path cap (Phase C item 1), 3 is
deadline overshoot from cold stage admission (Phase D item 1), and 5 is
preparation and packing time on the largest spec (Phase C).

### 2.2 The stranded-net facts

- **Where a net becomes stranded** (`freeform.py:8531`-`8538`): inside the
  round's per-net loop, when `_astar` returns `path is None`, the router
  records `search_failures[i] = searched`, `search_blockers[i] =
  _blocking_nets(searched.wall, source_access_blockers.get(i, ()))`, and
  appends `i` to `stranded`.
- **What is available at that moment**: the live `_Canvas`
  (`freeform.py:4064`) with `blocked`, `reserved`, `guard`, `keep_out`,
  `belt_ban`; the live `_Grid` (`freeform.py:5588`) with `base` (occupancy
  before any path settled this pass) and `occ`; `owner: dict[Cell, int]`
  mapping every settled cell to its net index (`freeform.py:7130`); `history`
  and `blame`; and `budget["left"]`, the one shared expansion counter
  (`freeform.py:7157`, `_ROUTING_BUDGET = 2_000_000` at `freeform.py:471`).
- **The blame wall is bounded and can be empty.** `_astar` builds
  `wall_by_owner` only when `blocking_owners` is supplied — which only
  `_route_all` does — and discards the wall entirely when more than
  `_BLAME_MAX_WALL = 64` distinct owners are accused (`freeform.py:567`),
  returning `RouteFailureKind.SEALED_POCKET` with an empty `wall`. A stranded
  net can therefore arrive with **no** named blockers. Cluster construction has
  to cope with that.
- **`_repair` is a displacement pass, not a harder search**
  (`freeform.py:7965`). It re-searches each stranded net on an open grid built
  from `grid.base` with a `_REPAIR_CROSSING = 60.0` toll per owned cell
  (`freeform.py:383`, `8002`-`8020`), then rips up the paths that cheapest
  route crosses. Its own docstring records the measurement Phase B builds on:
  31 stranded nets across five `universe-matrix` packs were each fixed in
  0.001-0.025 s, and "every one crossed between 1 and 11 of the 93-140 paths
  already down". Packs on these cells hold on the order of 100-150 nets, so a
  cluster of 8 is under 8 % of the pack.
- **Nothing is ever proved today.** `DetailedRouteResult.exhaustive`
  (`route_feedback.py:125`) exists, is validated (`exhaustive=True` is refused
  together with a `BUDGET` status or any `BUDGET`-kind failure), and is
  consumed: `_proof_scoped_no_goods` (`freeform.py:13682`) emits an
  `ExactPackNoGood` from a stranded routing result **only** when
  `routing.exhaustive` is true (`freeform.py:13723`-`13753`), and that no-good
  reaches `_pack` through `_ExactPackNoGoodState` (`freeform.py:2765`,
  `16375`). The only producers of `exhaustive=True` in the tree are the empty
  placeholder results in `_build_prepared` (`freeform.py:13898`-`13905`). **The
  entire environment-scoped no-good pipeline is already built and has no
  producer.** Phase B is its first one.
- **Five per-net rejection sets are routing-derived.** `rejected_starts`,
  `rejected_goals`, `rejected_source_hints` and `rejected_sink_hints`
  (`freeform.py:7534`-`7538`) are consulted **inside `_ends`** at
  `freeform.py:7857`, `7906`-`7907`, `7932` and `7943`-`7944`.
  `rejected_path_cells` is **not** read by `_ends`: it is the round's
  `forbidden` argument to `_astar` (`freeform.py:8395`, `8516`, `8702`). All
  five are filled by commit rejections and illegal attachments, so an
  environment claiming to be a relaxation has to empty all five for the nets it
  relaxes — four so `_ends` stops withdrawing, one so the search stops refusing
  cells.
- **`_ends` builds part of its ends from other nets' committed paths.** Both
  the source side (`freeform.py:7886`-`7895`) and the sink side
  (`:7934`-`7939`) call `_merge_frontier(canvas, paths, siblings, …)`, whose
  docstring says reaching a sibling's belt "is the ONLY option when the lane
  itself is walled in" (`freeform.py:6834`-`6843`); the `src_group` comment
  says the same — "An out-lane sandwiched between its neighbours is only
  reachable at its ends … They BRANCH instead: leave from a sibling's path"
  (`freeform.py:7405`-`7411`). **A sibling's path is an attachment surface, not
  only an obstacle.** Removing it can make a net *unroutable*, so "fewer nets
  is easier" is false in this router. This fact decides how the relaxed run may
  be built and when its result may be believed (§5.2).
- **`grid.reserved` is reassigned during a pass.** `_retire_served_roles`
  filters entries out of it (`freeform.py:7606`-`7610`) and
  `_restore_unserved_roles` rebuilds them (`:7624`-`7632`), guarded by
  `if any(member != index and member in paths …): continue` (`:7618`). The
  field holds a tuple, but it is not constant across a pass.
- **The relaxed global router is not an acceptance surface.**
  `global_router.route_global` (`global_router.py:148`) is used only by
  sequence-pair to triage candidates; its result is explicitly not a placement
  certificate (`tests/layout/test_global_router.py:639`), and nothing feeds its
  paths into `_route_all`. Phase B does not change that.

## 3. Goals

Measurable conditions, all evaluated on an idle box.

1. **Corpus gate (the acceptance gate).** `scripts/audit.py --budget 30
   --jobs 16`, both strategies, three interleaved rounds, compared against the
   Phase A round files with `scripts/audit_compare.py`:
   - freeform `quantum-chip/all-products` is CLEAN in all three rounds;
   - freeform `universe-matrix/output-products` is CLEAN in all three rounds;
   - no cell CLEAN in the Phase A baseline is non-CLEAN in any candidate round;
   - INVALID 0 and CRASH 0 in every round;
   - paired geometric-mean area ratio over cells clean in both arms at most
     `1 + 0.013`;
   - wall p95 per cell at or under **31 s**.
   Target 67/72 or better; the gate record states whatever it is.

   **Why 31 s and not 30 s.** Wall p95 is Phase D's problem, not Phase B's:
   the overshoot comes from cold stage admission in
   `_MeasuredStageAdmission.try_start` and from uncancellable finalize and
   validate, none of which this design touches. The Phase A round files already
   sit above 30 s — p95 30.53 s, 30.67 s and 30.37 s across rounds 1, 2 and 3 —
   so a 30 s threshold would fail Phase B for a defect it inherited. The
   threshold is the worst of those three, 30.67 s, rounded up: 31. The gate
   record carries the line "wall p95 inherited from Phase A, owned by Phase D".
2. **Parity.** `scripts/route_bench.py --cases … --check` digests are
   unchanged on captured `universe-matrix`, `quantum-chip` and `plastic`
   cases, under both `FLAB2BP_ROUTE_KERNEL=python` and the compiled kernel.
   The new search never runs on a pack with zero stranded nets, so no existing
   `_astar` call sequence moves.
3. **Soundness.** Three conditions, each independently checkable:
   - **No cut search is ever read as a closed one.** If any low-level search in
     a run returns `RouteFailureKind.BUDGET` — whether the private
     `B_LOW_LEVEL_EXPANSIONS` allowance ran out, the shared budget floor was
     reached, or the deadline passed — the run's outcome is `BOUNDED`, whatever
     the high-level tree then does. `PROVED` therefore means "the tree closed
     and every search in it ran to a real conclusion".
   - **`ExactPackNoGood` is an environment-conditioned exclusion.** It comes
     from run 1 closing, which searches the cluster completely *with the rest
     of this pack's routing fixed*. It removes one point from the packer's
     domain and it is the meaning `exhaustive` has always carried in this
     repository (§5.4, Risk 3).
   - **`ClusterRelationNoGood` is a statement about the strips, and only for a
     sibling-free cluster.** It comes from run 2 closing, whose environment is
     the pack with every belt removed and the cluster nets' five rejection sets
     emptied. "Removing nets is a relaxation" is true **only** where no cluster
     net needs a sibling's path to reach its lane, because `_ends` builds merge
     frontiers from `paths` (§2.2). So run 2 runs, and a relation no-good is
     emitted, only when every cluster net has empty `src_group` and
     `dst_group`. Under that condition every remaining removal is a pure
     obstacle removal, truncation only removes further nets from run 2's
     problem, and a closed run 2 is a genuine infeasibility statement for the
     cluster's strips at that relative placement.
   No no-good is ever created from a budget or deadline outcome
   (`route_feedback.py:151`-`158` already excludes `BUDGET` from geometric
   feedback; this design keeps the same rule for hard cuts).
4. **Determinism.** For a fixed seed and a fixed deterministic budget, the
   cluster, the CBS expansion order, the chosen solution, and the emitted
   no-goods are identical run to run. Wall-clock and expansion bounds may cut
   the search short, and when they do the outcome is "no claim", never a
   different claim.
5. **Bounded cost.** A last-mile pass spends at most
   `B_CBS_EXPANSION_SHARE = 0.25` of `budget["left"]` measured **once** at pass
   entry, shared by run 1 and run 2 together; at most `B_LOW_LEVEL_EXPANSIONS
   = 50_000` expansions in any single low-level search; at most
   `B_MAX_CBS_NODES = 512` high-level nodes per run; and it refuses to start
   when the remaining wall time is under `B_MIN_SECONDS` (default 0.35 s,
   measured in the plan's Task 8 and adjusted there if the measurement
   disagrees).
6. **The round is left exactly as it was found.** On any outcome other than a
   committed solution, `paths`, `owner`, `grid.occ`, `canvas.guard`, the
   `_TENTATIVE` cells of `canvas.blocked`, `path_tap`, `path_guards`,
   `guard_claims`, `canvas.reserved` and `canvas.port_corridors` are identical
   before and after the pass. A mismatch degrades the outcome to `BOUNDED` and
   increments `last_mile_restore_mismatch`; it never raises.

Non-gate observation to record, not to gate on: the number of last-mile
invocations, solutions, proofs, bounded exits, commit rejections and restore
mismatches. `scripts/audit.py` rows carry no `stats` object, so these reach the
gate record through `scripts/route_profile.py --json` on the two target cells
(§6.8), not through the audit JSONL.

## 4. Non-goals

- No change to strip planning, variant generation, or band policy.
- No ALNS, no new destroy/repair operators, no scheduling change. That is
  Phase C.
- No deadline-overshoot fix, no racing, no cross-process sharing. That is
  Phase D.
- No learned component, no tuning of `RRR_MAX`, `_REPAIR_PASSES`,
  `_REPAIR_MAX_VICTIMS`, `_MAX_EXPANSIONS`, `_ROUTING_BUDGET`, `LEVELS`, or
  any congestion weight.
- No Cython in this phase. The CBS high level is Python over the already
  compiled low-level `_astar`; compiling anything is a later decision made from
  a measurement, not from this document.
- No change to CLI, web, or pipeline interfaces. `scripts/route_bench.py` and
  the new `scripts/last_mile_bench.py` are developer tools.
- No fallback corridor tier and no relaxation of validator rules. A cluster
  solution is committed through the same predicate every other path passes, or
  it is not committed.

## 5. Architecture

### 5.1 Cluster construction

New module `src/flab2bp/layout/last_mile.py`. It imports nothing from
`freeform` at runtime — `_Canvas`, `_Grid`, `_Net` and `_PathSearchResult`
appear only under `if TYPE_CHECKING:` with `from __future__ import
annotations` — so `freeform` can import it without a cycle.

The cluster is built from data `_route_all` already holds at the end of a
round:

- `stranded: list[int]` — net indices, in round order.
- `search_blockers: dict[int, tuple[NetId, ...]]` — from
  `_blocking_nets(searched.wall, …)` (`freeform.py:8533`).
- `owner: dict[Cell, int]` — settled cell to net index (`freeform.py:7130`).
- `search_failures: dict[int, _PathSearchResult]` — each carries `wall`.
- `paths: dict[int, tuple[Cell, ...]]` — the round's live routing.

Growth rule, deterministic:

1. Seed the cluster with `stranded`, sorted ascending by net index.
2. Frontier pass: for each net in the cluster in ascending index order, add
   (a) every net index named by `owner[cell]` for `cell` in that net's
   `search_failures[i].wall`, and (b) every net index whose `NetId` appears in
   `search_blockers[i]`. Both give indices directly — `_blocking_nets` returns
   `NetId`s, so the mapping back is the `net_id -> index` inverse of
   `_net_id` (`freeform.py:7181`), built once per cluster.
3. Repeat step 2 over newly added nets until no net is added or the cluster
   would exceed `B_MAX_CLUSTER = 8`.
4. **Truncation.** When step 2 would push the cluster past `B_MAX_CLUSTER`,
   the candidates added in that pass are ordered by
   `(min Manhattan distance from the candidate's committed path to any
   stranded net's source or destination cell, net index)` and the cheapest are
   taken until the cap is reached. Distance to a net with no committed path is
   the distance between endpoint cells.
5. A stranded net with an empty wall and no blockers contributes only itself.
   A cluster whose only members are the stranded nets is legal and is searched
   — that case is exactly "these k nets cannot be routed even with every other
   belt where it is".

Release: for every cluster net that has a committed path, call the round's
`_unstake` (`freeform.py:7671`). That is the same release `_repair` uses for
victims, and it is the one that also takes the net's conditional junction
guards and port-role retirements away. Everything else — buildings,
`canvas.reserved`, `canvas.keep_out`, `canvas.belt_ban`, permanent guards,
`junction_frame_bans`, and every non-cluster path — stays exactly as it is.

Restore on failure: after a CBS run that does not produce a committed pack,
every released net is re-staked **in its original stake order** with the exact
hint triple it was staked with. All three components are recoverable:
`source_hint[i]`, `sink_hint[i]`, and the junction-guard hint, which
`_claim_junction_guard` stores as `path_tap[index] = tap`
(`freeform.py:7558`, `7562`). Order matters because `_claim_junction_guard`
computes its `excused` set from the sibling paths already down
(`freeform.py:7563`-`7568`); replaying the original order replays the same
inputs. `paths` is an insertion-ordered dict written only by `_stake`, so
`list(paths)` *is* the stake order.

The restore is then verified rather than trusted (§5.5).

### 5.2 CBS

**Low level.** One call per net per constrained search:

```
allowance = min(B_LOW_LEVEL_EXPANSIONS, max(0, budget["left"] - floor))
private = {"left": allowance}
_astar(canvas, starts, goals, history, pressure, bounds, private, deadline,
       {}, grid,
       owned_starts=owned_source_starts.get(i, ()),
       forbidden=frozenset(rejected_path_cells.get(i, ())) | node_constraints[i],
       blocking_owners=owner)
budget["left"] -= allowance - private["left"]
```

This is the round's own call (`freeform.py:8383`-`8397`) with three changes:

- `forbidden` is the union of the net's existing rejected-commit cells and the
  CBS node's constraint set for that net. `rejected_path_cells` is a
  `defaultdict(set)` (`freeform.py:7536`) and the default is `()`, so the union
  is built through an explicit `frozenset(...)` rather than relying on `|`.
- The search runs against a **private** budget dict of at most
  `B_LOW_LEVEL_EXPANSIONS = 50_000`, and the spend is written back to the
  shared `budget["left"]` afterwards. That caps how long one search can run
  between the pass's own bound checks, which is what keeps a last-mile pass
  from sailing past the caller's deadline; `_MAX_EXPANSIONS = 200_000`
  (`freeform.py:466`) is four times too coarse for a pass that may make
  hundreds of searches. Exhausting the private allowance produces
  `RouteFailureKind.BUDGET`, which forces the run to `BOUNDED`.
- `blame` is a fresh empty dict, so CBS never charges the round's blame
  accumulator.

`starts`, `goals` and the endpoint offers come from `_ends(i)`
(`freeform.py:7699`), which also rebinds `canvas.routing_ports`; the caller
clears it afterwards (`canvas.routing_ports = frozenset()`, as at
`freeform.py:8528`). `pressure` is the round's current value.

Cluster paths are absent from `grid.occ` because they were unstaked, and
`_unstake` restores each cell from `grid.base` (`freeform.py:7695`). No
grid rebuild happens: the landmark fields (`_ALT_LANDMARKS = 4`,
`freeform.py:459`) and `hist` stay as the round left them, so the low-level
searches cost what round searches cost.

**High level.** A best-first tree over nodes:

```
_CbsNode = (cost: float, ordinal: int,
            constraints: tuple[tuple[int, Cell], ...],
            paths: dict[int, tuple[Cell, ...]])
```

- `cost` is the sum over cluster nets of `len(path)`. Path length is the
  router's own tie-break currency and is integral, so sums compare exactly;
  no float association question arises.
- The open list is a `heapq` ordered on `(cost, len(constraints), ordinal)`.
  `ordinal` is a monotonically increasing insertion counter, so ties break by
  creation order and the search is deterministic without comparing dicts.
- **Root**: search every cluster net with no constraints, in ascending net
  index. If any net has no path at the root, the root is still a node —
  its cost is `sum(len(p))` over the nets that did find one plus
  `B_UNROUTED_COST = 1_000_000` per net that did not, which keeps unrouted
  nodes ordered after routed ones without special-casing the heap.
- **Conflict detection**: for the node's paths, walk cluster nets in ascending
  index order and record the first cell owned by two of them. A cell is
  `(x, y, level)`, which is what `_astar` returns and what `_Grid` indexes; a
  ramp's `via` cell is already spliced into the path by `_astar` and
  de-duplicated by `_cut_loops` (`freeform.py:5366`), so cell-level conflict
  detection covers ramps without a separate resource model. A node whose paths
  are pairwise disjoint and cover every cluster net is a **solution**.
- **Split**: the standard two-child split. For a conflict on cell `c` between
  nets `a < b`, child 1 adds `(a, c)` to `constraints`, child 2 adds `(b, c)`.
  Each child re-searches only the constrained net. A child whose constrained
  net finds no path is pushed with the unrouted cost rather than dropped, so
  the tree's closure is a closure over the whole space and not over the
  subspace where every net happens to route.
- **Closure**: the tree is closed when the open list empties with no search
  having been cut short.
- **A cut search poisons the run.** The moment any low-level result carries
  `kind is RouteFailureKind.BUDGET`, the run's outcome is `BOUNDED` and the
  tree stops. This is not an optimisation: a `BUDGET` result means the search
  did not decide whether a path exists, so a node built on it does not stand
  for the subspace it claims to, and the eventual empty heap would be an
  artifact of the cap rather than a fact about the grid. `_astar` returns
  `BUDGET` for the private allowance, for the shared budget, and for the
  deadline (`freeform.py:6280`-`6281`, `6545`-`6546`), so one test covers all
  three.
- **Bounds**: the run stops and reports `BOUNDED` when any of
  `expanded >= B_MAX_CBS_NODES`, `budget["left"] <= floor`,
  `len(child_constraints) > B_MAX_CONSTRAINTS = 64` for a child about to be
  created, `_expired(deadline)`, or the `BUDGET` rule above. `ClusterResult`
  records which one fired in a `bound` field, so the bench can tell a
  wall-bounded capture from a node-bounded one.

**Two runs, one budget share.** The floor is computed once at pass entry as
`floor = budget["left"] - int(B_CBS_EXPANSION_SHARE * budget["left"])` and the
same value is passed to both runs, so run 1 and run 2 together spend at most
one share.

1. **Environment run.** The live canvas and grid, non-cluster paths in place.
   A solution here is committed (§5.3). Closure here establishes: *with the
   rest of this pack's routing where it stands, and with these nets' rejection
   sets as routing has filled them, the cluster's nets cannot be wired.*
2. **Relaxed run.** Run only when both of these hold:
   - run 1 closed with no solution; **and**
   - every cluster net is **sibling-free**: `src_group[i]` and `dst_group[i]`
     (`freeform.py:7415`, `:7397`) are both empty for every `i` in the cluster.

   The environment is built by *emptying the round*, not by copying it:
   - `for index in list(paths): _unstake(index)` — every net, not just the
     cluster's. This is verbatim what the round loop does at
     `freeform.py:8342`-`8343` before each round, so it is a state the router
     already enters and leaves routinely. `_unstake` restores `grid.occ` from
     `grid.base`, drops each net's `_TENTATIVE` cells, releases its conditional
     guards, and calls `_restore_unserved_roles`, which puts the port corridors
     back through `_restore_port_corridor` (`freeform.py:7612`, `8870`).
   - the five per-net rejection sets — `rejected_starts`, `rejected_goals`,
     `rejected_source_hints`, `rejected_sink_hints` (read inside `_ends`) and
     `rejected_path_cells` (the `forbidden` argument), `freeform.py:7534`-`7538`
     — are saved and emptied for the cluster's nets, and restored afterwards.
     Without this the "relaxed" environment still carries routing-derived
     exclusions and is not a relaxation at all.
   - the reservation tables are then EMPTIED, not merely swept: the full
     unstake restores every retired corridor to `canvas.reserved`,
     `canvas.port_corridors` and `grid.reserved`, which is TIGHTER than run 1
     saw (see the loosest-world rule below). Every port's corridors are
     retired as if its role had been served, and `grid.occ` is given back only
     for the cells the release actually freed.
   - `planned_taps` starts EMPTY for run 2, so only the cluster's own taps
     accumulate (every realizable world contains those), and `_can_junction`'s
     one check that tightens as the table shrinks — the refusal of a
     `canvas.guard` cell the table does not already hold — is exempted for the
     duration of run 2 (`relaxed_junctions`). Its other three tap checks
     tighten as the table grows, so the empty table is loose-or-equal there.
     Run 1's table is put back afterwards.

   What remains is buildings, `canvas.solid`, `canvas.keep_out`,
   `canvas.belt_ban`, the routing box, permanent guards, and
   `junction_frame_bans`. Nothing derived from this pack's routing survives,
   and nothing the reservation plan holds does either. The same
   `_cluster_search` closure is reused unchanged.

**Why sibling-free, and why "fewer nets is easier" is false here.** `_ends`
calls `_merge_frontier(canvas, paths, siblings, …)` on both the source and the
sink side (`freeform.py:7886`-`7895`, `:7934`-`7939`). For a net whose lane is
walled in by buildings, branching off a sibling's committed path is *the only
way in* — `_merge_frontier`'s docstring and the `src_group` comment both say so
(`:6834`-`6843`, `:7405`-`7411`). Unstake that sibling and the net's `starts`
come back empty; `_astar` returns `DYNAMIC_ACCESS` at zero expansions
(`:6266`, `:6279`, `:6494`); CBS prices the net unrouted; the tree closes; and
the run reports `PROVED` for a net it disconnected itself. That false proof
would become a *region* exclusion in both packers and travel to Phases C and D
— the worst failure mode this design has. Restricting run 2 to clusters whose
nets have no siblings at all removes the mechanism rather than bounding it: with
`src_group[i]` and `dst_group[i]` empty, `_merge_frontier` had nothing to offer
that net in the first place, so unstaking cannot take anything away from it. So
the gate is load-bearing for the loosest-world rule below and not merely
pessimism: `needs_junction` and `_merge_frontier` both read `paths`, and run 2's
empty `paths` is TIGHTER than a world in which the siblings are routed, which
is exactly the thing a region exclusion may not be built on.

**The loosest-world rule.** A relation no-good excludes a REGION, so it is
sound only if run 2's world is at least as loose, cell for cell, as every world
the packer could realise for the cluster's nets at that arrangement. Looser than
needed is safe — it only weakens the cut; TIGHTER is unsound, because run 2 then
forbids a placement some realizable world allows. "Remove every net" does not
give that on its own, and the counter-example is the port corridors: `_stake` →
`_retire_served_roles` deletes a served port's corridor from `canvas.reserved`,
`canvas.port_corridors` and `grid.reserved`, `_unstake` →
`_restore_unserved_roles` puts it back and `grid.block`s the two cells, and
`_Canvas.free` refuses any reserved cell that is not the searching net's own —
so a corridor a staked non-cluster net had retired is FREE in run 1 and RESERVED
again in run 2. `planned_taps` cuts both ways: three of `_can_junction`'s tap
checks refuse MORE as the table grows (frame-ban scan, two taps closing a cell,
collider scan), while the fourth refuses a `canvas.guard` cell unless the table
already holds it, so neither an emptied table nor run 1's table is loose in all
four. Run 2 therefore unstakes every net, retires EVERY port corridor of every
port as if its role had been served, starts with an empty `planned_taps`, and
bypasses the guard-cell refusal while it searches. Under that world — and only
under it —
truncating the cluster at `B_MAX_CLUSTER` removes still more nets from run 2's
problem, so if run 2's problem is infeasible, so is the full problem at that
relative placement. Run 1 has the opposite polarity — its untruncated remainder
is *fixed obstacle*, which makes the problem harder — so run 1's closure
supports only the point exclusion (§5.4).

**Two follow-ups, gated on the measured skip count.** If
`last_mile_relation_skipped_siblings` dominates `last_mile_proved` on the
corpus, sibling-free clusters are too rare and one of these earns its
complexity — neither is in Phase B's scope, and neither may be attempted before
the count says it is needed:
   - *Keep the cluster's own node paths visible to `_ends`.* Run 2 would stake
     nothing, but pass the CBS node's current cluster paths into
     `_merge_frontier` in place of `paths`, so a cluster net can still merge
     onto a cluster sibling. This preserves the relaxation for intra-cluster
     siblings; it does nothing for siblings outside the cluster and it changes
     `_ends`' signature.
   - *Unstake only non-cluster, non-sibling nets.* Keep every net that is in
     some cluster net's `src_group` or `dst_group` staked. The environment is
     then less permissive than "everything gone" but still strictly more
     permissive than run 1, and the relaxation argument survives for the nets
     actually removed. It costs a second definition of "which nets may go".

`ClusterProblem.sibling_closed` (every sibling *inside* the cluster) is retained
as recorded evidence in the capture and the telemetry. It is **not** the gate —
sibling-free is a strictly stronger condition — and it is what the first
follow-up would relax the gate back to.

### 5.3 The commit path

A solution from run 1 is committed through the round's own machinery, in this
order:

1. For each cluster net in ascending index order: **re-query the offers**
   through `ClusterEnvironment.offers(i)`, then
   `_stake(i, path, hints=_selected_hints(path, offers))`
   (`freeform.py:7647`, `7635`). `_stake` writes `canvas.blocked[cell] =
   _TENTATIVE`, `grid.block(cell)` and `owner[cell] = i`, claims the junction
   guard, and retires the served port roles — the same three-way consistency
   the round depends on.

   The re-query is not optional. The offers CBS collected came from `_ends(i)`
   calls made while **no** cluster net was staked; staking happens one net at a
   time, so by the time net `k` is staked the earlier cluster nets have taken
   cells, retired port roles and claimed guards, and an offer map captured
   before that can name a source or sink tile that is no longer available. A
   stale hint is exactly the class of defect `_ends`' docstring names
   (`freeform.py:7710`-`7714`): "a repair that built its ends differently would
   find a path the committer cannot attach at either end". Re-querying means
   `_selected_hints` may return `None` for a component and `_stake` then drops
   that hint, which the commit preflight in step 2 catches.
2. `commit_once()` (`freeform.py:8580`), the round's existing preflight, which
   runs `_commit_paths` (`freeform.py:9090`) against a `deepcopy(canvas)` and
   returns unlinked indices plus `_CommitFailure` details. Junction and
   splitter legality, `_can_junction` (`freeform.py:7453`), lane linking and
   tap placement are all decided there and are not re-implemented.
3. If `commit_once()` returns no unlinked nets and `stranded` is now empty,
   the round returns `_finish(paths, {}, source_hint, sink_hint, path_tap,
   budget_exhausted=False)` — the identical return the round already takes at
   `freeform.py:8640` and `8750`.
4. If `commit_once()` returns unlinked nets, the cluster staking is rolled back
   (`_unstake` each cluster net, then re-stake the released paths in their
   original stake order), the round continues as it would have, and the pass
   reports `BOUNDED` with `last_mile_commit_rejected` incremented. A commit
   rejection is exact static evidence about buildings, not a routing proof.

**A `SOLVED` search can still end as `BOUNDED`.** Steps 1 and 2 are a second
gate that CBS knows nothing about: junction legality, splitter stack geometry,
lane linking and tap placement are decided by `_commit_paths`, and re-queried
offers can come back without the tile a path's endpoint needs. The counter
`last_mile_commit_rejected` is how often that happens; a corpus run where it
dominates `last_mile_solved` means CBS is finding paths the committer will not
take, which is a finding for the gate record rather than something to route
around.

No new commit path, no new legality predicate, and no new `DetailedRouteStatus`
value.

### 5.4 The two-level no-good

**Level 1, environment-scoped.** When run 1 closes with no solution, the pass
records `proved_stranded = set(stranded)` together with the round ordinal.
`_route_all` then passes `exhaustive_claim=True` into `_finish`
(`freeform.py:7281`) for the incumbent produced by that round. `_finish`
converts the claim to `exhaustive=True` only when all of:

- the round that produced the incumbent is the round that proved;
- `set(ordered_failures)` equals `proved` (a commit-link failure added at
  `freeform.py:7327`-`7343` invalidates the claim);
- no failure has `kind is RouteFailureKind.BUDGET`;
- `status` is `DetailedRouteStatus.STRANDED`.

`DetailedRouteResult.__post_init__` (`route_feedback.py:127`-`137`) enforces
the last two independently and raises if the caller gets them wrong, so the
invariant is checked twice.

From there **nothing new is needed in freeform's packer**:
`_proof_scoped_no_goods` (`freeform.py:13682`) already turns an exhaustive
stranded result into an `ExactPackNoGood` with one
`finalize.ProjectionFailure(check="route.exhaustive", …)` per failure, and
`_ExactPackNoGoodState.remember` (`freeform.py:2765`, `2773`) already
deduplicates it into the tuple `_pack` receives
(`freeform.py:16361`-`16376`). One adjacent change is required:
`_build_prepared` composes `routing.exhaustive` as a five-term conjunction —
`not prepared.preparation_failures` and the four sub-routings
(`freeform.py:14010`-`14016`) — and `_route_boundary_nets`
(`freeform.py:10264`) never sets its term. `_route_boundary_nets` returns
`exhaustive=not failures`, which is the same vacuous claim `_build_prepared`
already makes for its `empty_routing` placeholder (`freeform.py:13898`-`13905`)
and cannot conflict with a `BUDGET` status, because a result with no failures
has no `BUDGET` failure and its status is `ROUTED`.

`ExactPackNoGood` is modelled by `_add_exact_pack_no_good`
(`freeform.py:3038`): one `add_forbidden_assignments` over `[width, xs[0],
ys[0], …]` against `[no_good.width, origin[0] - strips[0].west_channel,
origin[1], …]`. It removes exactly one point from the packer's domain.

**Level 2, cluster-scoped.** `_route_all` cannot build this no-good — it knows
nets and cells, not strips and pack origins — so it records the cluster's strip
instances and the proof evidence on `DetailedRouteResult.last_mile`, and
`_proof_scoped_no_goods` assembles the finished object from
`PackAttempt.origins`, `.outline` and `.height`, in the same place and from the
same fields it already assembles `ExactPackNoGood`. The type is a frozen
dataclass in `route_feedback.py`, beside the other routing-evidence types, so
both `last_mile.py` and `freeform.py` can import it without a cycle:

```python
@dataclass(frozen=True, slots=True)
class ClusterRelationNoGood:
    height: int
    outline: tuple[tuple[int, int], ...]
    strips: tuple[int, ...]  # ascending, at least two
    deltas: tuple[tuple[int, int], ...]  # origin[s] - origin[strips[0]]
    evidence: tuple[str, ...]
```

`evidence` is one blob, not one string per net: the useful content is which
cluster this was and that both runs closed, and a per-net tuple only makes the
no-good's equality key noisier without telling a reader anything the strip list
does not.

It is emitted only when **all** of:

- run 1 closed with no solution;
- every cluster net is sibling-free — `src_group[i]` and `dst_group[i]` both
  empty (`freeform.py:7415`, `:7397`). Otherwise run 2 does not run at all and
  `last_mile_relation_skipped_siblings` is counted (§5.2);
- run 2 closed with no solution;
- run 2's restore reproduced the round exactly (§5.5). A restore mismatch after
  run 2 withdraws **both** claims: no relation no-good, and the run-1
  `exhaustive` claim is dropped for that pack too, because the incumbent the
  claim describes is no longer known to be the incumbent that was proved;
- the cluster spans at least two distinct strip instances — the strip set is
  `{net_id.source_strip, net_id.destination_strip}` over the cluster's nets,
  with `None` dropped, and it must hold at least 2 entries after that. A
  one-strip cluster has no relative placement to forbid.

`deltas` are computed from the pack origins the attempt already carries
(`PackAttempt.origins`, `freeform.py:13610`), which is where
`_proof_scoped_no_goods` reads them from today.

**Freeform consumption.** `_pack` gains
`cluster_relation_no_goods: tuple[ClusterRelationNoGood, ...] = ()`, guarded
like the exact no-goods are (`freeform.py:3252`-`3255`): applied only when
`no_good.height == height` and `no_good.outline == tuple(sizes)`. The model,
mirroring `freeform.py:3427`-`3446` exactly:

```python
anchor = no_good.strips[0]
variables: list[cp_model.IntVar] = []
values: list[int] = []
for position, strip_index in enumerate(no_good.strips[1:], start=1):
    dx = model.new_int_var(-width_bound, width_bound, f"cluster_ng{n}_dx{position}")
    dy = model.new_int_var(-height, height, f"cluster_ng{n}_dy{position}")
    model.add(
        dx
        == (xs[strip_index] + strips[strip_index].west_channel)
        - (xs[anchor] + strips[anchor].west_channel)
    )
    model.add(dy == ys[strip_index] - ys[anchor])
    variables.extend((dx, dy))
    values.extend(no_good.deltas[position])
model.add_forbidden_assignments(variables, [tuple(values)])
```

That is the disjunction "at least one of these strips moves relative to the
anchor": every assignment agreeing with the recorded relative placement on
every cluster strip is forbidden, and every assignment differing in at least
one delta is admitted. It is translation-invariant, which is what makes it a
region and not a point.

**Sequence-pair consumption.** The compact-seed model has no no-good input:
`solve_compact_seed` (`compact_seed.py:567`) takes only a problem, seeds, a
config, direct-eligibility targets, a deadline and a cancellation callback, and
`PairwiseRelationSignature` (`compact_seed.py:147`) is a *diagnostic of a
solved packing*, not a constraint surface. What sequence-pair does have is a
state-exclusion path already used for `ExactPackNoGood`: the union type
`_ProjectionPackNoGood` (`sequence_solver.py:2726`), the matcher
`_projection_feedback_matches` (`sequence_solver.py:2729`) and the repairer
`_projection_feedback_stage_update` (`sequence_solver.py:2767`), which swaps a
pair of strips in the positive or negative sequence until the decoded pack no
longer matches the retained no-good. Phase B extends that union with
`ClusterRelationNoGood`, adds a matcher branch (the decoded pack matches when
`problem.selected_sizes(state.variant_indices) == no_good.outline`,
`pack.height == no_good.height`, and every cluster strip's origin delta to the
anchor equals the recorded delta), and yields the cluster's strip pairs
`(strips[0], strips[j])` in ascending order as the pair iterator. This is a
hard state exclusion — the stage boundary refuses to hand back a state that
still matches — so no energy penalty is introduced and the brief's fallback of
"a hard penalty in the energy" is not needed.

### 5.5 Budgets and determinism

- **Expansions.** At entry the pass records `floor = budget["left"] -
  int(B_CBS_EXPANSION_SHARE * budget["left"])` **once**, and passes the same
  value to run 1 and run 2, so both runs together spend at most one share. A
  run stops when `budget["left"] <= floor`. `B_CBS_EXPANSION_SHARE = 0.25`.
- **Per search.** Every low-level call runs against a private budget dict of
  `min(B_LOW_LEVEL_EXPANSIONS, budget["left"] - floor)` and the spend is
  written back to the shared counter afterwards, so the round's later
  behaviour sees exactly the expansions the pass spent.
  `B_LOW_LEVEL_EXPANSIONS = 50_000`.
- **Nodes.** `B_MAX_CBS_NODES = 512` high-level expansions per run. Run 2 gets
  its own node allowance of the same size; the expansion floor is shared.
- **Constraints.** `B_MAX_CONSTRAINTS = 64`; a child that would exceed it is
  not created and the run reports `BOUNDED` rather than pruning the branch,
  because a pruned branch would make an empty heap a lie.
- **Wall.** The pass refuses to start when `deadline is not None and
  deadline - time.monotonic() < B_MIN_SECONDS` (default `0.35`). Inside, the
  same `deadline` is passed to `_astar`, which polls every
  `_DEADLINE_CHECK_EVERY = 4096` expansions (`freeform.py:586`), and the high
  level checks `_expired(deadline)` (`freeform.py:665`) before each expansion.
  The private per-search allowance is the second half of that discipline: it
  bounds how much work one search can start after the last high-level check.
- **Entry conditions.** `1 <= len(stranded) <= B_MAX_STRANDED` (default 3),
  the pass has not already run in this `_route_all` call, and the wall floor
  holds.
- **Restore verification.** Before releasing anything — for the cluster release
  in run 1 and for the whole-pack sweep in run 2 alike — the pass records
  `paths`, `owner`, `grid.occ`, `grid.reserved`, `canvas.guard`, the
  `_TENTATIVE` cells of `canvas.blocked`, `path_tap`, `path_guards`,
  `guard_claims`, `canvas.reserved` and `canvas.port_corridors`. After any
  restore it compares them. `grid.reserved` is in the list because
  `_retire_served_roles` and `_restore_unserved_roles` reassign it
  (`freeform.py:7606`-`7610`, `:7624`-`7632`) and a role that came back in the
  wrong order or not at all is exactly the silent corruption this check exists
  to catch. A mismatch degrades the outcome to `BOUNDED` — dropping every
  claim, including a proof already established — and increments
  `last_mile_restore_mismatch`. It does **not** assert: an `AssertionError`
  inside `_route_all` propagates out of `lay_out`, becomes a CRASH row in
  `scripts/audit.py`, and fails the corpus gate on a condition the gate is
  supposed to be measuring. The exact-equality assertion lives in the test
  suite, where a crash is the correct outcome.
- **Determinism.** Every iteration is over a sorted or index-ordered sequence:
  cluster growth by ascending net index, root searches by ascending net index,
  conflict detection by ascending net index pair, the two children in a fixed
  order, the heap keyed on `(cost, len(constraints), ordinal)` with `ordinal`
  strictly increasing. `_astar` is already deterministic for fixed inputs
  (that is what the Phase A replay digest proves). The only nondeterminism is
  which bound fires first under wall-clock pressure, and every bound produces
  the same outcome: `BOUNDED`, no proof, no commit.

### 5.6 Where it runs in `_route_all`

At the end of a round, after the `_REPAIR_PASSES` loop (`freeform.py:8550`-
`8563`) and after the commit-preflight block (`freeform.py:8637`-`8757`) has
settled `stranded` and `failed`, and **before** the round's history and blame
accounting (`freeform.py:8758`-`8789`) and the incumbent update
(`freeform.py:8801`). That is the one point where `canvas`, `grid`, `owner`,
`paths`, `source_hint`, `sink_hint` and `path_tap` are all mutually consistent
and `stranded` is final for the round.

The brief asks for "after the last round's repair passes". Which round is the
last is not knowable at that point: the loop breaks on `stale >=
_RRR_STALE_ROUNDS`, `it == RRR_MAX - 1`, or `budget["left"] <= 0`
(`freeform.py:8823`), all evaluated afterwards. The rule this design uses
instead is **once per `_route_all` call, at the end of the first round whose
stranded set is small enough**, guarded by a `last_mile_done` flag. On every
cell in the Phase B target set this is the same thing: those packs hold
100-150 nets, so `round_limit = 1` (`freeform.py:8338`,
`_SINGLE_ROUND_NETS = 64`) and there is exactly one round.

On success the round returns through `_finish` immediately (§5.3). On a proof
or a bounded exit the round continues exactly as it would have, with the
cluster's pre-release paths restored, and the proof (if any) is carried to the
final `_finish` at `freeform.py:8825`.

## 6. Interfaces

Public surface unchanged: `FreeformLayout`, `SequencePairLayout`,
`pipeline.build`, CLI, web, `scripts/audit.py`.

### 6.1 `src/flab2bp/layout/last_mile.py` (new)

```python
B_MAX_STRANDED: int = 3
B_MAX_CLUSTER: int = 8
B_MAX_CBS_NODES: int = 512
B_MAX_CONSTRAINTS: int = 64
B_CBS_EXPANSION_SHARE: float = 0.25
B_LOW_LEVEL_EXPANSIONS: int = 50_000
B_MIN_SECONDS: float = 0.35
B_UNROUTED_COST: int = 1_000_000

#: Developer-tool hook.  ``None`` in production; ``scripts/route_bench.py``
#: sets it for the length of one capture run.  A module-level callback rather
#: than a parameter because the alternative is threading a bench-only argument
#: through ``lay_out``, ``_sweep``, ``_build`` and ``_build_prepared``.
CAPTURE: Callable[[ClusterCapture], None] | None = None


class ClusterOutcome(StrEnum):
    SOLVED = "solved"  # every cluster net has a disjoint path
    PROVED = "proved"  # tree closed, no search cut short, no solution
    BOUNDED = "bounded"  # a bound fired; nothing is claimed


class ClusterBound(StrEnum):
    NONE = ""  # the run reached a decision on its own
    NODES = "nodes"
    CONSTRAINTS = "constraints"
    BUDGET = "budget"  # the shared floor, or a cut low-level search
    WALL = "wall"


@dataclass(frozen=True, slots=True)
class ClusterProblem:
    nets: tuple[int, ...]  # ascending net indices
    stranded: tuple[int, ...]  # ascending, subset of nets
    truncated: bool
    sibling_closed: bool  # telemetry only, see 5.4


@dataclass(frozen=True, slots=True)
class ClusterResult:
    outcome: ClusterOutcome
    paths: Mapping[int, tuple[Cell, ...]]  # empty unless SOLVED
    nodes: int
    expansions: int
    seconds: float
    bound: ClusterBound = ClusterBound.NONE


_Offers = tuple[Mapping[Cell, Cell], Mapping[Cell, Cell], Mapping[Cell, Cell]]


@dataclass(frozen=True, slots=True)
class ClusterEnvironment:
    search: Callable[[int, frozenset[Cell]], _PathSearchResult]
    #: Re-query one net's `_ends` offer maps at stake time.  Kept on the
    #: environment rather than in a side-table because the offers CBS saw were
    #: collected with no cluster net staked and are stale by the time the
    #: second net goes down -- see 5.3.  `solve_cluster` never calls it.
    offers: Callable[[int], _Offers]
    budget_left: Callable[[], int]
    budget_floor: int
    expired: Callable[[], bool]
    max_nodes: int = B_MAX_CBS_NODES
    max_constraints: int = B_MAX_CONSTRAINTS


@dataclass(frozen=True, slots=True)
class ClusterCapture:
    """Everything a replay needs to re-run one live cluster search."""

    run: int  # 1 environment, 2 relaxed
    canvas: object  # freeform._Canvas; opaque here
    grid: object  # freeform._Grid; opaque here
    history: Mapping[Cell, float]
    pressure: float
    bounds: tuple[int, int, int, int]
    problem: ClusterProblem
    ends: Mapping[int, tuple[list[Cell], set[Cell], frozenset[Cell]]]
    budget_left: int
    budget_floor: int
    deadline_remaining: float | None


def build_cluster(
    stranded: Sequence[int],
    *,
    walls: Mapping[int, tuple[Cell, ...]],
    blockers: Mapping[int, tuple[int, ...]],
    owner: Mapping[Cell, int],
    paths: Mapping[int, tuple[Cell, ...]],
    endpoints: Mapping[int, tuple[Cell | None, Cell]],
    src_group: Mapping[int, tuple[int, ...]],
    dst_group: Mapping[int, tuple[int, ...]],
    max_cluster: int = B_MAX_CLUSTER,
) -> ClusterProblem: ...


def solve_cluster(
    problem: ClusterProblem,
    environment: ClusterEnvironment,
) -> ClusterResult: ...


def cluster_strips(
    problem: ClusterProblem,
    net_strips: Mapping[int, tuple[int | None, int | None]],
) -> tuple[int, ...]: ...


def relation_no_good(
    *,
    strips: Sequence[int],
    origins: Sequence[tuple[int, int]],
    outline: tuple[tuple[int, int], ...],
    height: int,
    evidence: str,
) -> ClusterRelationNoGood | None: ...
```

`cluster_strips` takes no `strip_count`: `_route_all` does not know how many
strips the pack has, and `relation_no_good` already drops any index outside
`range(len(origins))`, so a bound here would be either inert or wrong.

`relation_no_good` takes the pack's `origins`, `outline` and `height`, which
`_route_all` does not have — it knows nets and cells, not strips and packs. So
`_route_all` records only `relation_strips` and `relation_evidence` on its
report and `_proof_scoped_no_goods` (`freeform.py:13682`) builds the finished
no-good from `PackAttempt.origins`, `.outline` and `.height`, which is exactly
where `ExactPackNoGood` is already built.

`blockers` is `dict[int, tuple[int, ...]]` of **net indices**, not `NetId`s:
`_blocking_nets` (`freeform.py:7201`) is a closure inside `_route_all`, so it
cannot be imported, and `_route_all` inverts its own `_net_id` mapping before
calling `build_cluster`.

### 6.2 `src/flab2bp/layout/route_feedback.py`

```python
@dataclass(frozen=True, slots=True)
class ClusterRelationNoGood:
    height: int
    outline: tuple[tuple[int, int], ...]
    strips: tuple[int, ...]
    deltas: tuple[tuple[int, int], ...]
    evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LastMileReport:
    invocations: int
    solved: int
    proved: int
    bounded: int
    commit_rejected: int
    restore_mismatch: int
    #: Run 1 closed but the cluster had a sibling, so run 2 was not run.
    relation_skipped_siblings: int
    nodes: int
    expansions: int
    seconds: float
    #: Ascending strip instances of a cluster proved unroutable in the relaxed
    #: environment, empty when no relation proof was established.
    relation_strips: tuple[int, ...] = ()
    relation_evidence: str = ""


@dataclass(frozen=True, slots=True)
class DetailedRouteResult:
    ...  # unchanged fields
    exhaustive: bool = False  # unchanged
    last_mile: LastMileReport | None = None  # new
```

### 6.3 `src/flab2bp/layout/freeform.py`

```python
def _route_all(...) -> DetailedRouteResult: ...        # signature unchanged
def _add_cluster_relation_no_good(
    model: cp_model.CpModel,
    xs: Sequence[cp_model.IntVar],
    ys: Sequence[cp_model.IntVar],
    strips: Sequence[Strip],
    height: int,
    width_bound: int,
    index: int,
    no_good: ClusterRelationNoGood,
) -> None: ...
def _pack(..., cluster_relation_no_goods: tuple[ClusterRelationNoGood, ...] = ()) -> _Pack | None: ...
def _proof_scoped_no_goods(
    attempt: PackAttempt,
    strips: list[Strip],
) -> tuple[tuple[_DirectRelationNoGood, ...], ExactPackNoGood | None,
           tuple[ClusterRelationNoGood, ...]]: ...     # third element is new
```

`_route_all`'s public signature does not change: the cluster pass reads and
writes only closures and locals it already has, reports through
`DetailedRouteResult.last_mile`, and reaches the bench through the
module-level `last_mile.CAPTURE` hook rather than through a parameter.

### 6.4 `src/flab2bp/layout/sequence_solver.py`

```python
type _ProjectionPackNoGood = finalize.ProjectionNoGood | ExactPackNoGood | ClusterRelationNoGood
```

`_projection_feedback_matches` and `_projection_feedback_stage_update` gain a
`ClusterRelationNoGood` branch. No other signature changes.

### 6.5 `scripts/route_bench.py`

```
uv run python scripts/route_bench.py --capture universe-matrix \
    [--policy no-proliferator|all-products|output-products] \
    [--stranded] [--budget S] [--every N] [--cap N] [--cases PATH]
```

- `--policy` selects the candidate policy; today `capture()` hardcodes
  `CandidatePolicy.NO_PROLIFERATOR` (`scripts/route_bench.py:98`), which cannot
  reach either Phase B target cell.
- `--stranded` installs a callback on `last_mile.CAPTURE` for the length of the
  run. `_route_all` calls that hook — when it is not `None` — immediately
  before each `solve_cluster` call, handing it a `ClusterCapture` (§6.1) it has
  already built from its own locals. **No frame inspection.** The bench's
  callback deep-copies what a search mutates with the existing `_snapshot` and
  appends one pickled case:

```python
{
    "kind": "cluster",
    "run": 1 | 2,
    "canvas": shot_canvas,  # _snapshot's copy semantics, unchanged
    "grid": shot_grid,  # cluster paths already released from occ
    "history": shot_hist,
    "problem": ClusterProblem,
    # per cluster net, from _ends: starts, goals, and the net's own routing
    # ports, without which a replay refuses starts the capture admitted
    "ends": {index: (list[Cell], set[Cell], frozenset[Cell])},
    "pressure": float,
    "bounds": tuple[int, int, int, int],
    "budget_left": int,
    "budget_floor": int,
    "deadline_remaining": float | None,
    "result": ClusterResult,  # what the live pass returned
}
```

`ClusterCapture.ends` is what makes the offers side-table unnecessary: it holds
the same `(starts, goals, routing_ports)` triples `_ends` produced, so the
replay reconstructs the low level without touching `_route_all` at all.

The captured grid already has the cluster's paths released — run 1's capture
with the cluster unstaked, run 2's with every net unstaked — so replaying a
case needs nothing else: the environment is the canvas, the grid, the history,
the pressure, the bounds, the per-net ends, and the two budget numbers.

`_snapshot` (`scripts/route_bench.py:55`) is reused unchanged; it already
copies `blocked`, `reserved`, `solid`, `keep_out`, `guard`, `belt_ban`,
`routing_ports`, `grid.occ` and `grid.hist` and shares the rest.

### 6.6 `scripts/last_mile_bench.py` (new)

```
uv run python scripts/last_mile_bench.py --cases PATH [--rounds N] [--check]
```

Replays every cluster case by rebuilding a `ClusterEnvironment` over the
captured canvas and grid and calling `last_mile.solve_cluster`. Prints per
round `nodes`, `expansions` and seconds, and a `BEST` line with the outcome and
bound histogram. `--check` compares a SHA-256 digest over
`(outcome, sorted paths)` per case against the captured `result` and exits 1 on
any mismatch — the same contract `route_bench.digest`
(`scripts/route_bench.py:182`) has for paths.

For `--check` to be meaningful the replay must reproduce the *bounds* the live
run had, not only its geometry: a capture that ended `BOUNDED` because the
shared floor was reached would otherwise replay under an unbounded budget,
reach `PROVED`, and report `DIFFER` for a reason that is not a regression. So
the replay seeds `budget = {"left": case["budget_left"]}` and
`budget_floor = case["budget_floor"]` from the capture, **and caps each
low-level search at `B_LOW_LEVEL_EXPANSIONS` with the same private-budget
write-back the live pass uses**. Without that cap a run that ended
`bound is ClusterBound.BUDGET` because one search hit its private allowance
would replay with no per-search cap and take a different branch; with it, the
`BUDGET` bound reproduces and those cases stay in the digest.

The wall clock cannot be replayed. Cases whose captured `result.bound` is
`ClusterBound.WALL` are therefore excluded from the digest and reported as
`skipped N wall-bounded`. That is why `ClusterResult` carries `bound` at all.

### 6.7 `scripts/audit_compare.py`

```
uv run python scripts/audit_compare.py BASELINE.jsonl CANDIDATE.jsonl \
    [--noise-area 0.013] [--p95-seconds 31] [--expect-cells 72] \
    [--regressions-only] [--require-clean STRATEGY/URL_ID/SPEC_LABEL ...]
```

`compare` gains `require_clean: frozenset[str] = frozenset()` and
`regressions_only: bool = False`. Today a single non-CLEAN candidate row is an
unconditional failure (`scripts/audit_compare.py:81`-`85`), so a 67/72 gate
could not be expressed at all. Under `--regressions-only`:

- a `REFUSED` row is a failure only when the paired baseline row is CLEAN
  (reported as `REGRESSION: …`); a carried-over refusal is printed as
  `CARRIED: …` and does not fail;
- an `INVALID` or `CRASH` row **is always a failure**, whatever the baseline
  said. A crash and a validator rejection are never "carried over": Goal 1
  requires INVALID 0 and CRASH 0 outright, and the restore-mismatch hazard
  (§5.5) is precisely a way this phase could manufacture CRASH rows, so the
  mode that relaxes refusals must not relax these.

`--require-clean` names cells that must be CLEAN whatever the baseline said,
and each one that is not produces `NOT CLEAN: …`. Without either flag the
behaviour is byte-for-byte what it is today.

### 6.8 `placement.stats` and the profiler

`PlacementStats` (`base.py:198`, a `TypedDict` with `total=False`) gains, all
`float`:

```
last_mile_invocations  last_mile_solved           last_mile_proved
last_mile_bounded      last_mile_commit_rejected  last_mile_restore_mismatch
last_mile_nodes        last_mile_expansions       last_mile_seconds
last_mile_relation_strips                         last_mile_relation_skipped_siblings
```

They are written once, in `_build_prepared` where the stats dict is built
(`freeform.py:14059`-`14071`), from `internal_routing.last_mile`. Sequence-pair
inherits them for free: its stats start from `placement.stats.copy()`
(`sequence_solver.py:5348`) and that placement came from the same
`_build_prepared`.

**How they reach the gate record.** Not through the audit: `scripts/audit.py`
rows carry `strategy`, `url_id`, `spec_index`, `spec_label`, `power`, `budget`,
`status`, `area`, `seconds` and `detail`, and no `stats` object — a comparison
that reads `row["stats"]` would silently report zeros for every cell. The
counters reach the record through `scripts/route_profile.py --json`, which runs
one cell under one strategy and already emits a JSON row. That script gains:

- `"last_mile"` in `PHASES` (`scripts/route_profile.py:103`) and a shim in
  `install` (`:132`) around `last_mile.solve_cluster`, so the `phases` object
  carries `{"s": …, "n": …}` for it;
- a `"last_mile_stats"` object in the JSON row, taken from the `Placement` the
  run returns. `main` currently discards that placement
  (`scripts/route_profile.py:514`-`516`); it keeps it and copies the
  `last_mile_*` keys out of `placement.stats`.

The gate task runs the profiler once per Phase B target cell and pastes those
two rows into `gate.md`.

## 7. Failure handling

- **A bound fires.** `ClusterOutcome.BOUNDED`. The released paths are restored,
  no no-good is created, the round continues, and the pack ends exactly as it
  does today. This is the only outcome a deadline or an expansion budget can
  produce, which keeps the existing rule that budget failures never create
  no-goods.
- **A low-level search is cut short.** A `_PathSearchResult` with
  `kind is RouteFailureKind.BUDGET` ends the run as `BOUNDED` with
  `bound = ClusterBound.BUDGET` on the spot, before the tree can empty. This is
  the single rule that keeps a per-search cap from manufacturing proofs, and it
  fires identically for the private `B_LOW_LEVEL_EXPANSIONS` allowance, the
  shared floor, and the deadline.
- **The restore does not reproduce the round.** The comparison in §5.5 fails:
  the outcome is downgraded to `BOUNDED`, every claim including an established
  proof is dropped, `last_mile_restore_mismatch` is incremented, and the round
  continues on whatever state it now has. This is a bug report carried in
  telemetry, not an exception: raising here would turn a routing defect into a
  CRASH row and fail the corpus gate on the wrong condition. **After run 2 the
  same rule withdraws the run-1 claim as well**: the `exhaustive` flag names
  the incumbent that was proved, and a round that did not come back the way it
  went out is no longer known to be that incumbent.
- **The cluster has a sibling.** Run 2 is skipped, `ClusterRelationNoGood` is
  not emitted, `last_mile_relation_skipped_siblings` is incremented, and run
  1's `ExactPackNoGood` is unaffected. This is the common case and it is not a
  failure — it is the design refusing to make a claim it cannot support (§5.2).
- **A cluster net cannot even be given ends.** `_ends(i)` can return an empty
  goal set or no admissible start; `_astar` reports
  `RouteFailureKind.DYNAMIC_ACCESS` having expanded nothing
  (`freeform.py:6266`, `6279`, `6494`). CBS treats that as "no path for this
  net under these constraints" and prices the node with `B_UNROUTED_COST`; it
  is not an error and it does not stop the tree.
- **The solution fails the commit preflight.** Rolled back, reported as
  `BOUNDED` with `last_mile_commit_rejected` incremented, and the round's
  existing commit-repair block runs. A commit-link rejection is exact static
  evidence about buildings, not a routing proof, and it must not become one.
  A re-queried offer map that no longer names a path's endpoint tile
  (§5.3) reaches the same place: `_stake` drops the hint and
  `_commit_paths` refuses the link.
- **A proof is contradicted by a later commit-link failure.** `_finish` drops
  the `exhaustive` claim when the failure set it returns is not exactly the
  proved set. `DetailedRouteResult.__post_init__` raises if a caller tries to
  combine `exhaustive=True` with a `BUDGET` status or a `BUDGET` failure, so a
  logic error surfaces as an exception in the test suite rather than as a
  silent bad cut.
- **A `ClusterRelationNoGood` arrives against a different strip plan.** `_pack`
  skips any no-good whose `height` or `outline` does not match, the same guard
  `ExactPackNoGood` gets (`freeform.py:3253`). Sequence-pair's matcher applies
  the same test against `problem.selected_sizes(state.variant_indices)`.
- **A cluster with fewer than two strip instances.** `relation_no_good`
  returns `None`; only the environment-scoped no-good is emitted.
- **`last_mile.py` raises.** It does not catch. An exception propagates out of
  `_route_all` and fails the run loudly, because a router that silently
  swallows a failure is the defect `_route_all`'s own docstring
  (`freeform.py:7099`-`7101`) exists to name. The one deliberate exception to
  this is the restore comparison above, which is a *predictable* failure mode
  with a defined degraded outcome rather than a programming error.

## 8. Testing

### 8.1 Parity

- `scripts/route_bench.py --cases … --check` on captured `universe-matrix`,
  `quantum-chip` and `plastic` cases: digest identical to the pre-change
  capture, under `FLAB2BP_ROUTE_KERNEL=python` and under the compiled kernel.
  The captures are made once, before any behaviour change, and committed to the
  evidence directory.
- A test that runs a full `lay_out` on a spec whose packs all route and asserts
  `last_mile.solve_cluster` was never called (monkeypatched counter). Zero
  stranded nets means zero new work.
- A test that `_route_all` on a pack with `len(stranded) > B_MAX_STRANDED`
  never calls `solve_cluster`.

### 8.2 CBS correctness on hand-built grids

All of these build a `_Canvas(limit=bounds)` and drive `solve_cluster` with a
`ClusterEnvironment` whose `search` calls `freeform._astar` directly, in the
style of `tests/layout/test_freeform.py:11483`-`11530`.

- **Two nets, one corridor, solvable only jointly.** A corridor one cell wide
  that both nets' greedy paths want; CBS returns `SOLVED` with disjoint paths
  and a strictly smaller total cost than any single-net rip-up would give.
- **A proved-infeasible cluster.** Two nets whose endpoints are separated by a
  wall with a single free cell, so any assignment forces both through it. The
  tree closes; the outcome is `PROVED`, `paths` is empty, and `nodes` is less
  than `B_MAX_CBS_NODES`.
- **A bounded run is not a proof.** The same infeasible fixture with
  `max_nodes=1`; the outcome is `BOUNDED`, `paths` is empty, and `bound` is
  `ClusterBound.NODES`.
- **A cut low-level search is not a proof.** The infeasible fixture with a
  `search` that returns `_PathSearchResult(None, RouteFailureKind.BUDGET, (),
  0)` for one net: the tree would otherwise empty and report `PROVED`, and the
  run must instead report `BOUNDED` with `bound is ClusterBound.BUDGET`. This
  is the H1 test: run it before the rule is implemented and it returns
  `PROVED`, which is the bug.
- **Constraints are honoured.** A node's constraint cell never appears in that
  net's path in any descendant.
- **Determinism.** The same fixture solved twice returns identical `paths`,
  `nodes` and `expansions`.
- **Levels.** The conflict detector must not report a conflict between
  `(x, y, 0)` and `(x, y, 2)`, and must report the first cell two paths share
  when they do share one, naming the lower net index first.
- **Cluster construction.** `build_cluster` with a wall naming three owners
  returns those three plus the stranded net; with `max_cluster=2` it truncates
  by distance and sets `truncated=True`; with an empty wall and no blockers it
  returns the stranded net alone; `sibling_closed` is false when a cluster net
  has a `src_group` member outside the cluster.

### 8.3 No-goods

- `_finish` sets `exhaustive=True` only under the four conditions in §5.4, and
  drops it when a commit-link failure is added.
- `_route_boundary_nets` returns `exhaustive=True` on a clean result and
  `False` when it has failures.
- `_proof_scoped_no_goods` returns an `ExactPackNoGood` for an exhaustive
  stranded result (this extends the existing
  `test_exhaustive_non_budget_failure_creates_full_assignment_no_good`,
  `tests/layout/test_freeform.py:3382`) and returns none for a budget result
  (the existing `test_unproved_and_budget_failures_do_not_exclude_geometry`,
  `tests/layout/test_freeform.py:3418`, must still pass unchanged).
- `_add_cluster_relation_no_good` on a three-strip model: `_pack` returns a
  packing whose cluster-strip deltas differ from the recorded ones. Because the
  constraint is written only over relative offsets, translating the recorded
  placement cannot escape it, and the test asserting the returned deltas differ
  is the check that it did not.
- `_pack` skips a `ClusterRelationNoGood` whose `outline` or `height` differs.
- `last_mile.relation_no_good` records offsets from the anchor and returns
  `None` for fewer than two strip instances.
- `_projection_feedback_matches` returns true for a decoded state repeating the
  recorded relative placement and false after one strip moves;
  `_projection_feedback_stage_update` returns a state that no longer matches.
- `transform_stage` turns a routing report carrying `relation_strips` into a
  `projection_relation_feedback` entry holding a `ClusterRelationNoGood`, and
  the stage boundary then moves off the matching state. The wiring lives in the
  `elif detailed.placement is not None:` branch, which runs only when
  `select_feedback_variant` is true (`sequence_solver.py:4655`), so the test
  must call `transform_stage` with `select_feedback_variant=True` and a
  `DetailedStageResult` whose `placement` is not `None`.

### 8.4 Restore and telemetry

- The pre/post comparison covers `paths`, `owner`, `grid.occ`, `grid.reserved`,
  `canvas.guard`, the `_TENTATIVE` cells of `canvas.blocked`, `path_tap`,
  `path_guards`, `guard_claims`, `canvas.reserved` and
  `canvas.port_corridors`, and a test drives a `BOUNDED` outcome on a real pack
  and asserts every one of them is byte-equal. This assertion lives in the
  test, not in `_route_all`.
- A cluster with a non-empty `src_group` or `dst_group` on any member never
  reaches run 2: `solve_cluster` is called exactly once and
  `last_mile_relation_skipped_siblings` is 1. A sibling-free cluster whose run
  1 closes calls it twice.
- A run-2 restore mismatch withdraws both claims: `relation_strips` is empty
  **and** the returned `DetailedRouteResult.exhaustive` is `False`.
- A test with a deliberately broken restore (a monkeypatched `_stake` that
  drops one hint) asserts the outcome degrades to `BOUNDED` and
  `last_mile_restore_mismatch` is 1 — and that nothing raises.
- A test asserts a monkeypatched `BOUNDED` outcome is counted in
  `placement.stats["last_mile_bounded"]` as exactly 1, not merely that the key
  is present and non-negative.

### 8.5 Captured stranded cases

- `route_bench.py --capture universe-matrix --policy output-products
  --stranded` and `--capture quantum-chip --policy all-products --stranded`
  produce at least one cluster case each; the pickles are committed under the
  evidence directory.
- `last_mile_bench.py --cases … --check` exits 0 on both, replaying each case's
  captured `budget_left` and `budget_floor` and skipping cases whose captured
  `bound` is `ClusterBound.WALL`. Its `BEST` line is recorded in the gate
  record. Re-running it after any later change in the phase must keep the
  digest.

### 8.6 The audit comparison

- `--regressions-only` passes a candidate that carries the baseline's refusals
  and fails one that adds a new refusal against a CLEAN baseline cell.
- `--regressions-only` **fails** on an `INVALID` row and on a `CRASH` row even
  when the paired baseline row is also `INVALID` or `CRASH`.
- `--require-clean` fails on a named cell that stayed `REFUSED`.
- Without either flag the verdict is what it is today.

### 8.7 Gate

The three-round corpus audit of §3 item 1, run by the commands in the plan's
final task, with the round JSONL files, the `audit_compare` output lines, the
two `route_profile.py --json` rows carrying the `last_mile_*` counters, and the
gate record committed under
`docs/superpowers/evidence/2026-09-02-phase-b-last-mile/`.

## 9. Delivery order

Each step is a separate commit that leaves the tree green
(`uv run pytest -q`, `uv run ruff check .`, `uv run mypy` against the locked
baseline of 176 pre-existing errors). A step whose gate fails is reverted, not
tuned around.

1. Evidence directory, `route_bench --policy`, and the pre-change `--check`
   digests. The `--stranded` capture waits for step 8, because its only sound
   hook is `last_mile.CAPTURE`, which does not exist until step 2.
2. `last_mile.py` cluster construction with tests.
3. CBS core on hand-built grids with tests, including a proved-infeasible
   cluster, a node-bounded run, and a cut low-level search that must not prove.
4. Integration into `_route_all` behind the constants **and** the commit path
   for cluster solutions, in one task: the offers capability has no reader
   until the commit path exists, so splitting them would ship dead code in a
   green commit. Digest parity re-run.
5. Environment-scoped no-good emission: `_finish`'s `exhaustive` claim and
   `_route_boundary_nets`' vacuous claim.
6. `ClusterRelationNoGood`, `relation_no_good`,
   `_add_cluster_relation_no_good`, and the `_pack` modelling, with tests.
7. The relaxed run behind its sibling-free gate, the three-tuple
   `_proof_scoped_no_goods`, and `lay_out`'s accumulation of cluster no-goods,
   with tests.
8. Sequence-pair consumption through the existing relation-repair path.
9. `route_bench --stranded` on the `last_mile.CAPTURE` hook,
   `last_mile_bench.py`, the captured `universe-matrix` and `quantum-chip`
   cluster cases, and the `B_MIN_SECONDS` measurement.
10. Telemetry in `placement.stats` and in `scripts/route_profile.py --json`.
11. `audit_compare.py`'s regression mode, then the three-round corpus gate and
    the gate record.

## 10. Relationship to Phases A, C and D

**Phase A** made this affordable and made it checkable. The Cython A*
(`_route_kernel.astar_flat`, roughly 9.7x per expansion) is what lets a CBS
tree spend hundreds of low-level searches inside a round's slack; the shared
`geometry_memo` is what leaves slack at all (first-candidate preparation 1.9 to
4.6 s, warmed 0.5 to 1.6 s); and `scripts/route_bench.py --check` is the
instrument that proves the packs which do not strand are untouched. Phase B
adds no compiled code and keeps Cython as the one compiled toolchain.

**Phase C** consumes Phase B's output. Its `LOCAL_EXACT_PACK` operator takes
"Phase B cluster strips" as one of the sources of its implicated-strip window
and re-solves `_pack`'s formulation over that window with the existing no-goods
**and** `ClusterRelationNoGood`. That is why `ClusterRelationNoGood` is defined
in `route_feedback.py` with plain integer strip indices and an `outline` guard:
a window solve restricted to a subset of strips can apply it whenever the
outline matches. Phase C also fixes the four refusals Phase B does not touch.

**Phase D** ships `ClusterRelationNoGood`s across the process boundary between
the two racing strategies, keyed by strip instance identity, applied only when
the receiver plans strips from the same families with the same instance ids.
The `outline` field already carries the check that makes that assertion cheap.

**Ordering.** B before C before D, each with its own worktree, plan and gate,
each gate's baseline the previous phase's three round files.

## 11. Risks

1. **CBS blows up on a cluster of ramps and junctions.** A cluster of 8 nets in
   a congested corridor can generate conflicts faster than the tree can close;
   `LEVELS = 4` (`freeform.py:242`) multiplies the resource space by four and
   ramps make each move two cells, so a single contested column produces many
   distinct conflict cells.
   *Detection:* `last_mile_bounded` in `placement.stats` counts exactly this,
   and `last_mile_nodes / last_mile_invocations` says how close runs came to
   `B_MAX_CBS_NODES`. `last_mile_bench.py` on the captured cases measures it
   off the corpus clock. If bounded exits dominate on the target cells, the
   cluster is too big for CBS as specified and the finding is recorded in the
   gate record rather than papered over by raising the cap.
2. **Removing a net can make the problem HARDER, so a "relaxed" run can prove
   something false.** This is the sharpest risk in the design and it defeated
   the first version of it. `_ends` builds merge frontiers out of other nets'
   committed paths (`_merge_frontier`, `freeform.py:6834`-`6843`, called at
   `:7886`-`7895` and `:7934`-`7939`), and for a net whose lane is walled in by
   buildings that is the *only* way in (`freeform.py:7405`-`7411`). Unstake the
   sibling and the net's `starts` are empty; `_astar` returns `DYNAMIC_ACCESS`
   at zero expansions; CBS prices it unrouted; the tree closes; the run reports
   `PROVED`. A relation no-good built on that would exclude a region of the
   packer's domain in both strategies and be carried into Phases C and D. The
   general claim "fewer nets is easier" is simply false in this router.
   *Mitigation:* run 2 runs only for a cluster in which every net has empty
   `src_group` and `dst_group`, which removes the mechanism instead of bounding
   it — a net with no siblings had no merge frontier to lose. Truncation is
   then benign in run 2's direction: the nets it drops are pure obstacles.
   Run 1 keeps the opposite polarity — its remainder is fixed obstacle, which
   makes the problem harder — so run 1's closure supports only the
   point-exclusion `ExactPackNoGood`, never the relation.
   *Detection:* `last_mile_relation_skipped_siblings` counts every cluster the
   condition turned away; `ClusterProblem.truncated` and `sibling_closed` are
   recorded in the capture and the `last_mile_bench` line. A relation no-good
   emitted for a cluster with a non-empty `src_group` would be a defect, and
   the test in §8.4 asserts `solve_cluster` is called exactly once in that case.
3. **"Unroutable in this environment" is not "unroutable".** The
   environment-scoped `ExactPackNoGood` excludes a packed assignment on
   evidence that a bounded complete search could not wire it *with the rest of
   that pack's routing fixed*. Some other routing of the same pack might have
   wired it. This is a heuristic-strength cut, and it is the semantics the
   repository already assigns to `exhaustive` — Phase B is the first producer,
   not the inventor, of that meaning.
   *Mitigation:* the cut removes exactly one point from the packer's domain
   (`_add_exact_pack_no_good`, `freeform.py:3038`, is a single
   `add_forbidden_assignments` tuple over every strip origin plus the width),
   so at worst one candidate height/arrangement is lost. The region-removing
   `ClusterRelationNoGood` is emitted only from run 2, whose closure is a
   genuine proof for the relation.
   *Detection:* the corpus gate's no-regression condition. A cut that excludes
   a wireable assignment shows up as a cell that was CLEAN in the Phase A
   baseline and is not CLEAN in a candidate round, which
   `audit_compare --regressions-only` reports as `REGRESSION:`.
4. **The stranded nets on the target cells may be stranded for reasons a
   cluster search cannot fix.** The whole design rests on the `_repair`
   docstring's measurement that stranded nets cross 1 to 11 already-placed
   paths (`freeform.py:7983`-`7984`). If the surviving one net on
   `quantum-chip/all-products` and `universe-matrix/output-products` is
   stranded by static geometry — an unreachable port, a `_can_junction`
   refusal, a `keep_out` region — then no rearrangement of belts helps and CBS
   will close immediately with `PROVED`, producing a no-good and no CLEAN cell.
   *Detection:* this is decided before the corpus gate, in the plan's Task 9.
   The captured cluster cases from both cells are replayed with
   `last_mile_bench.py --check`; the outcome distribution over those cases is
   the answer. `PROVED` on every captured case with a cluster of size 1 means
   the failure is static, and the phase's gate is then recorded as failed on
   coverage with that finding, exactly as Phase A recorded its own coverage
   miss. The no-goods still ship, because they are correct and they feed Phase
   C.
5. **A `ClusterRelationNoGood` may be rare, and the sibling-free gate is the
   main reason.** It needs run 1 to close, *every cluster net to have empty
   `src_group` and `dst_group`*, run 2 to close, run 2's restore to verify, and
   at least two distinct strip instances. The gate from Risk 2 is the binding
   condition: on the target cells a stranded net's blockers are the nets it
   crossed, and shared-source families are common, so many clusters will hold
   at least one net with a sibling and be turned away before run 2 starts.
   *Detection:* `last_mile_relation_skipped_siblings` against `last_mile_proved`
   in the profiler rows, plus `last_mile_relation_strips` for the ones that got
   through. A corpus run producing zero relations is reported in the gate
   record; Phase C then consumes only the point exclusions, which is a weaker
   but not a broken input.
   *Escalation:* the two follow-ups in §5.2 — passing the CBS node's own
   cluster paths to `_merge_frontier`, or unstaking only non-cluster
   non-sibling nets — exist for exactly this measurement. Neither is in Phase
   B's scope and neither may be attempted before the skip count says it is
   needed; both are recorded so a later phase does not have to rediscover the
   trap in Risk 2.
6. **Restoring the round is not exact.** The pass releases nets and re-stakes
   them, and `_stake` is not a pure inverse of `_unstake`:
   `_claim_junction_guard` recomputes its `excused` set from the sibling paths
   currently down (`freeform.py:7563`-`7568`), `_retire_served_roles` /
   `_restore_unserved_roles` move port corridors (`freeform.py:7589`, `7612`),
   and `owner`, `grid.occ` and `canvas.blocked` disagreeing is the exact
   failure `_route_all`'s comment at `freeform.py:7126`-`7128` warns about.
   The hint triple itself is fully recoverable — `source_hint`, `sink_hint`,
   and the guard hint that `_claim_junction_guard` stores as
   `path_tap[index] = tap` (`freeform.py:7562`) — so the earlier concern about
   an unrecoverable guard offer was overstated; the live risk is *ordering* and
   the corridor bookkeeping, not the hints.
   *Mitigation:* re-stake in the original stake order, which replays the same
   inputs to `_claim_junction_guard`, and verify with the ten-way comparison in
   §5.5.
   *Detection:* `last_mile_restore_mismatch` in the profiler rows, and a test
   that breaks the restore deliberately. **A mismatch degrades the pass to
   `BOUNDED`; it does not raise.** An `AssertionError` inside `_route_all`
   propagates through `lay_out` into `scripts/audit.py` as a CRASH row, and the
   gate requires CRASH 0 — so an assertion meant to protect the gate would be
   the thing that fails it. The exact-equality assertion belongs in the test
   suite, where a crash is the correct signal.
7. **World-altitude clashes are invisible to cell-level conflict detection.**
   Two ramps crossing one tile in opposite directions hold different lattice
   cells and the same `canvas.world_taken` cell (`freeform.py:4064`, the
   `world_taken` field comment). CBS's disjointness test cannot see that.
   *Consequence:* none new — the round has the identical hole, and the defence
   is identical: `commit_once()` runs `_commit_paths` and the pack later goes
   through `validate.check`'s `geom.belt_single_occupancy`
   (`validate.py:1009`). A cluster solution that trips it is rolled back as a
   commit rejection (§7) and reported `BOUNDED`.
   *Detection:* an INVALID row in the corpus audit would mean the rollback is
   wrong; the gate requires INVALID 0, and `--regressions-only` does not relax
   that (§6.7).
8. **The pass itself overshoots the caller's deadline.** A last-mile pass may
   make hundreds of low-level searches, and `_MAX_EXPANSIONS = 200_000`
   (`freeform.py:466`) lets any one of them run for a large fraction of a
   second before the high level regains control. On the two target cells the
   pass runs at the end of a routing attempt that is already near its budget,
   so an overshoot lands directly on the cell's wall time — the very quantity
   Phase D exists to fix and Phase B must not make worse.
   *Mitigation:* the private per-search allowance
   `B_LOW_LEVEL_EXPANSIONS = 50_000` (§5.2, §5.5), a quarter of the router's
   own per-search cap, chosen so that one search costs roughly 0.14 s at the
   361,816 expansions per second Phase A measured. Combined with the
   `B_MIN_SECONDS` entry floor and the deadline passed into every `_astar`,
   the pass's worst case after its last bound check is one search.
   *Detection:* `--p95-seconds 31` in the gate, and the per-cell `seconds`
   column compared against the Phase A baseline round files. A cell whose wall
   grows beyond the baseline's is a Phase B regression even when it stays under
   31 s, and the gate record names it.
9. **The telemetry never reaches the gate record.** `scripts/audit.py` rows
   have no `stats` object, so any attempt to read `last_mile_*` out of the
   audit JSONL yields zeros for every cell and reads as "the pass never ran"
   when in fact it was never measured. Risks 1, 4, 5 and 6 all depend on these
   counters, so a silent zero would disarm four defences at once.
   *Mitigation:* the counters come from `scripts/route_profile.py --json`
   (§6.8), which returns the `Placement` and copies the keys out of
   `placement.stats`. The plan's gate task runs it once per target cell.
   *Detection:* the gate record is required to contain two profiler rows with
   `last_mile_invocations` greater than zero. If it does not, the phase's
   observational claims are unsupported and the record says so.
