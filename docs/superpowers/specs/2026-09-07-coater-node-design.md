# The Spray Coater as a placed node — design

Date: 2026-09-07. Branch `design-coater-node`, cut from `master` at `0d88d247`.

---

> ## STATUS: SUPERSEDED — this design's recommendation is the arm that lost
>
> **Superseded 2026-09-07 by
> `docs/superpowers/evidence/2026-09-07-exp-coater-node/README.md`, and
> implemented instead by
> `docs/superpowers/plans/2026-09-07-coater-placed.md`.**
>
> This design recommended **variant A, the seat fix** (§5.1–§5.2): narrow
> `_coater_seats` to start at `1 + half_span` so the 3x1 body cannot cover the
> lane head, and ban the body's own level so `_merge_frontier` cannot offer one
> as a goal. The user challenged the design's case against a real placed node —
> *"You should test making it a real packable machine or a separately placed
> coater node, and see what actually happens. It may be a horrible idea, but if
> so, the evidence you are making is a really weak case against it."*
>
> All four arms were then built and measured at `--budget 30`, two rounds, the
> full 72-cell corpus:
>
> | arm | CLEAN | coater bodies over a merge | area vs `off` | belt vs `off` |
> |---|---|---|---|---|
> | `off` (master) | 71–72 / 72 | 5 / 9 | — | — |
> | `seat` (**this design**) | **48 / 72** | 0 | +4.0–4.7 % | — |
> | `packed` (CP-SAT object) | 34 / 36 (refuses `universe-matrix`) | 0 | +4.1–4.9 % | +50 % |
> | **`placed` (post-pack ring search)** | **72 / 72** | **0** | **+2.7–2.9 %** | **+1.4 %** |
>
> The reported URL builds 6/6 with zero findings under `placed`, against 6/6
> with six coater bodies over a merge under `off`.
>
> **`seat` is the only arm that is worse than doing nothing.** Its mechanism is
> this design's own Risk 1, and the design's estimate of it was wrong by an
> order of magnitude: at `west_channel = 3` the narrowed rule leaves exactly one
> candidate, `ox - 1`, whose body reaches into the machine band, so
> `_coater_keepout_hits` convicts the only seat that cleared the machines.
> Measured, that is **half the corpus** — 24 named cells, zero gained — not the
> countable margin §7 predicted. Raising `_COATER_WEST_CHANNEL` to 4 (open
> question 3) is a *precondition* for A, not a fallback, and it was never
> measured.
>
> **The user has ruled that density may be paid for correctness. `placed` ships
> as the default.** Branch `coater-node` is retained unmerged for its evidence
> only.
>
> **What in this document is still binding**, and travels with the `placed`
> plan:
>
> * §4's migration table, for every row that is not about the seat rule — which
>   mechanisms stay and why;
> * §5.4, the over-proliferation ruling applied: the `forbids_spray` clause of
>   `prolif.sprayed_cargo_reaches_machines` drops to WARNING, and the hard split
>   stays only for differing spray modes on one item;
> * §4's *Relationship to the `selfloop` cheap fix*: `prolif.coater_rides_one_run`
>   stays forever as the arbiter, and its status changes from *the fix* to *the
>   regression test* — which is exactly what `placed` delivers and A did not,
>   because under `placed` the merge cell is the node's in-port by construction;
> * §6.2's net-cost prediction (+55 % input-side nets), which measured
>   **+38–43 %** and is the same for every node arm.
>
> **What is superseded:** §3's recommendation, §5.1 and §5.2 (the seat narrowing
> and the body-level goal ban as *the fix*), §5.3's `CoaterNode` record, the
> "cheapest version that makes both properties structural" argument, and the old
> plan `docs/superpowers/plans/2026-09-07-coater-node.md`. §5.4 of that plan's
> Option-C rejection is also refuted by §5.4 of the evidence README: the
> packer's object model *can* express a three-port belt object, and the domain
> transition that looked like a blocker was not one.

---

## 0. The request

> "i would have assumed spray coaters are treated as a strip/block/whatever that
> must be placed as a whole somehow. Are we just routing and then trying to see
> if we can fit spray coaters? My mental model of a spray coater is that it's
> basically a forced recipe between recipes. So i would expect it to be placed
> and routed as if it was like an assembler that had to take a non-proliferated
> input and produce a proliferated output, and with the thing it feeds into
> required only proliferated inputs." — then: "Or something like this."

The answer to the literal question is **no, not any more, but nearly**: coaters
are seated *before* routing, not after, and the seat is a decoration on a lane
tile rather than a node with ports. This spec makes it a node with ports, at the
cheapest layer that makes the two properties the user cares about *structural*
rather than *checked*.

A second user ruling arrived during this design and is applied throughout:

> "Over-proliferating is actually fine if it makes life easier."

Section 6 measures exactly what that ruling buys, and the honest answer is: two
lanes across the whole corpus. It is applied where it genuinely simplifies the
node model (§5.4) and not used as a licence to remove machinery that costs
nothing.

---

## 1. What exists today, verified against the code

Every claim below was read on this branch. Line numbers are `master@0d88d247`.

### 1.1 The coater is a belt addon; it occupies no tile

`catalog.BuildingInfo.occupies_tiles` is `not is_belt_addon`
(`src/flab2bp/dsp/catalog.py:1359-1365`), and a Spray Coater
(`SPRAY_COATER_ID = 2313`, `catalog.py:227`) is `addon_type == 1`. Its
footprint is `(1, 3)`, so at yaw 90 its body covers three tiles along x. It
carries no connection of its own: the game resolves it by position from
`addon_areas` (`catalog.py:1309-1318`) — area 0 at `(0, 0, 0)` is the cargo belt
it rides, area 1 at `(0, -1.25, 1)` is the proliferator supply, both searched
within `rules.ADDON_AREA_RADIUS = 1.0` (`dsp/rules.py:583`).

**Consequence that constrains every option below:** a coater is not a
free-standing 1x3 building that a packer can place anywhere. It *must* ride a
belt, and the game reads both ends of that belt
(`rules.addon_ride_is_straight`, `dsp/rules.py:721-749`) and refuses the addon
when either end disagrees with the addon's axis. A "node with an item-in port
and an item-out port" is therefore physically **a belt run segment with an addon
on it**, and its ports are the two ends of that segment. Anything else is a
blueprint the game refuses.

### 1.2 Rates and spec

* Proliferator is consumed per *machine group*, not per lane:
  `SolvedGroup.proliferator_rate` (`rates/solve.py:97`) is
  `column.proliferator_per_craft * craft_rate` (`solve.py:1305`), and the total
  is folded into the boundary as an external input
  (`solve.py:1373-1376`). `RateSolution.proliferator_item_id` is
  `tier.sprayed_item_id` (`solve.py:141-143`).
* `BuildSpec.spray_lanes: dict[str, bool]` (`spec.py:187-189`) names the items
  whose lanes need a coater; the bool marks "this lane exists anyway", i.e. the
  item is external (`rates/candidates.py:176-186`).
* `BuildSpec.lanes_requiring_split: frozenset[str]` (`spec.py:191-195`) is
  computed by `rates.candidates.lanes_requiring_split` (`candidates.py:220-229`).
* `BuildSpec.belt_required_edges` (`spec.py:179-185`) forbids direct insertion
  on a proliferated consumer's input edge; `prolif.belt_required_edges_not_direct_inserted`
  (`layout/validate.py:4792-4829`) convicts a violation.
* A spec that sprays without a proliferator in `external_inputs` is rejected at
  construction (`spec.py:268-291`).

**Verified correction to the brief:** `lanes_requiring_split` does *not* force
the lane split. Nothing in `src/flab2bp/layout/` reads it except the validator
(`validate.py:5066`). The split is achieved structurally by `CargoDomain`: a
strip's domain comes from its group's `proliferated` flag
(`freeform.py:2625-2627`, `strip_variants.py:1550`), lane sinks are keyed by
`(destination, item, cargo_domain)` (`freeform.py:16478`), and `_Net.__post_init__`
refuses a net whose ports disagree about domain (`freeform.py:8576-8579`). So a
proliferated and an unproliferated consumer of the same item already get
different lanes and different nets, whatever `lanes_requiring_split` says.

### 1.3 Strip planning: the west channel is bought before packing

`WEST_CHANNEL = 1` and `_COATER_WEST_CHANNEL = 3` (`freeform.py:207-210`). A
strip whose group is proliferated is planned with the wider channel
(`freeform.py:2619`, `2646`), lifted to `_COATER_WEST_CHANNEL + 1` when a staged
static clearance relation demands it (`freeform.py:2683-2699`). `_size` adds the
channel to the strip's box (`freeform.py:1731`) and `_pack` offsets every strip
by it (`freeform.py:3935`, `3949`, `4980`), so the channel is inside the strip's
own reserved box and belongs to nobody else.

Sequence-pair does the same through the same code: `_sequence_reservation_strips`
reserves `_COATER_WEST_CHANNEL + 1` in the proxy box
(`sequence_solver.py:3744-3759`) and `_selected_strips` sets the exact channel
per selected strip (`sequence_solver.py:3851-3877`).

### 1.4 Lane emission: a sprayed lane already starts west of the strip

`_emit_strip` gives a `REQUIRES_SPRAY` lane at least two tiles and starts it at
`-s.west_channel` rather than 0 (`freeform.py:6544-6547`, `6559`). The tiles are
chained west-to-east with `output_obj` (`freeform.py:6572-6574`). The comment at
`freeform.py:6500-6543` records why, with measured evidence: a one-tile lane has
no successor so `game.addon_facing` reads whatever direction the router arrived
from, and a lane whose head is the router's sink lets the belt *turn on the
addon's own tile*, which `game.addon_corner` convicts and `BuildTool_Addon`
refuses — six of twenty coaters on the blueprint the user pasted.

The input `_Port` is the lane **head**: `_Port(lane_indices[0], head.x, …, x0=head.x,
x1=head.x + len - 1, tiles=tuple(lane_indices), cargo_domain=s.cargo_domain)`
(`freeform.py:6621-6640`). One port object is registered for every item on the
lane (`freeform.py:6639-6640`).

### 1.5 Seating: `_place_coaters`, before routing

`_prepare_routing_problem` calls `_place_coaters` **before** routing and before
the extent is fixed (`freeform.py:16708-16743`); the comment there records that
placing them afterwards left them mounted on belts with nothing feeding them.
`coaters = len(coater_list)` and the supply belts are attributed to the host
strip (`freeform.py:16744-16748`). The extent is then frozen
(`freeform.py:16752-16782`), the proliferator entry is staked
(`_place_proliferator_entry`, `freeform.py:19051-19067`) and the supply tree
becomes real nets with `NetRole.PROLIFERATOR` (`freeform.py:16791-16804`,
`_proliferator_supply_tree` at `18803-18845`).

`_place_coaters` (`freeform.py:18141-18770`) iterates strips and their
`in_lanes`, skipping any strip whose `cargo_domain` is not `REQUIRES_SPRAY`
(`freeform.py:18232-18233`), and for each sprayed lane:

* candidate seats come from `_coater_seats` (`freeform.py:18019-18037`):
  `port.tiles[1 : min(len(tiles) - 1, west_channel)]` — i.e. the *interior of the
  west channel*, excluding index 0 (the routing turn) and index `west_channel`
  onward (the machine-facing lane, where a sorter could draw unsprayed cargo);
* the drop cell is `slots.addon_supply_cell(SPRAY_COATER_ID, …, area=1)`
  (`freeform.py:18273-18280`), with a permanent approach belt one further out
  (`18285-18289`, built at `18353-18375`);
* `_coater_keepout_hits` (`freeform.py:5213-5245`) reserves the coater's real
  oriented 3x1 body plus one lateral cell;
* projected static and addon-supply certification runs per DSP frame
  (`freeform.py:18385-18537`, `_projected_coater_supply_frame_failure` at
  `6168`), then again over the whole staged set against the final extent
  (`freeform.py:18594-18660`), then against splitters
  (`_projected_coater_splitter_candidates`, `finalize.py:1617`);
* `_reserve_staged_coater_belt_ban` (`freeform.py:18100-18138`) prices the
  committed coater's collider into `canvas.belt_ban` for later belt routes;
* every failure mode raises `_Unseatable` (`freeform.py:13663`), which
  `_layout_at_height` and `sequence_solver.py:5396-5405` turn into "discard this
  height", and a spec where no height seats them is refused. The docstring at
  `freeform.py:18175-18186` records why this replaced five silent `continue`s.

`_coater_seat` (`freeform.py:18040-18097`) is a *thin wrapper* over
`_coater_seats` used nowhere in the placement path; its docstring still
describes the older "second tile at column 0" rule, which `_place_coaters`
superseded by passing `strip.west_channel`. With `west_channel = 3` the real
candidates are `ox - 2` and `ox - 1`.

### 1.6 The hierarchical composer

`hierarchy/partition.py:299-321` recomputes `spray_lanes` per block and
apportions the proliferator external input by sprayed-machine share;
`partition.py:341-346` recomputes `lanes_requiring_split`. `hierarchy/compose.py`
re-prices each composed coater's collider with `_coater_belt_ban`
(`compose.py:318-363`), which rebuilds a `_StagedCoater` from the committed
building alone. Blocks are solved through `hierarchy/strategy.py:_solve_block`
(`strategy.py:274`), which calls the ordinary strategies — so the composer
inherits whatever `_place_coaters` does and adds no seating logic of its own.

### 1.7 The defect this answers

From the merged self-loop evidence
(`docs/superpowers/evidence/2026-09-06-selfloop/README.md:250-272`) and design
(`docs/superpowers/specs/2026-09-06-self-loop-recipes-design.md:123-146`, §4 F2
at `:293-302`):

```
belt#0   (53,20,0) run 7  pred=[817, 1872]  <<< 2-INTO-1 MERGE, ON A TILE THE COATER BODY COVERS
belt#19  (53,26,0) run 16 pred=[830, 2037]  <<< 2-INTO-1 MERGE, on coater#771's body
```

and coater#768's area 1 held **two** belts at 0.250 inside the 1.0 radius, on
opposite sides — only the yaw convention separated them.

Nothing convicts either: `game.addon_supply` (`validate.py:2188`) asks only
whether *a* belt is in each area; `_coater_rides` (`validate.py:4898-4917`) maps
area 0 to one belt and says nothing about its predecessors;
`belt.acyclic` explicitly accepts many-to-one (`validate.py:3520-3522`).

**Why the geometry happens — the arithmetic, run on this branch.**

```python
>>> catalog.oriented_footprint(catalog.SPRAY_COATER_ID, 90.0)
(3, 1)
>>> x0 = 54 - (3 - 1) // 2; (x0, x0 + 2)          # _coater_keepout_hits:5230-5233
(53, 55)
>>> slots.addon_supply_cell(SPRAY_COATER_ID, x=54, y=20, z=0, yaw=90.0, area=1)
(53, 20, 1)
```

A sprayed lane's tiles are `ox - west_channel … ox + need - 1`
(`freeform.py:6559`), so with `west_channel = 3` the head is `ox - 3` and
`_coater_seats` offers `tiles[1:3]` — `ox - 2` and `ox - 1`
(`freeform.py:18034-18037`). **The first candidate, `ox - 2`, puts the body over
the head**: half-span is `(3 - 1) // 2 = 1`, so the body is
`{ox - 3, ox - 2, ox - 1}` and `ox - 3` *is* the head.

The head is the one cell on that lane a router path can reach — every other lane
tile is an occupied belt — and it is where every merge is therefore *supposed*
to land. `connect_lanes` appends one `_Net` per (producer lane, sink lane) pair
to the same sink port (`freeform.py:16416-16464`), and `_merge_frontier`
(`freeform.py:8935-8975`) offers the free cells beside a sibling net's path as
goals. So two producers into one sprayed lane give the head two predecessors, by
design, correctly — and the body is sitting on it.

That is precisely the reported geometry: coater#768 at `(54, 20, 0)`,
`belt#0 (53, 20, 0) pred=[817, 1872]`. The seat was one tile too far west. The
proliferator drop lands at `(53, 20, 1)`, directly above the same head cell,
which is why the second reported defect — two belts inside area 1 — shares a
cause: the area-1 disc sits over the busiest cell on the lane.

**Nothing told the router the channel interior was a node**, and nothing told the
seat search that the head is load-bearing.

---

## 2. The node, and the layer it lives at

### 2.1 Rate/graph layer: **layout-only. Do not make it a recipe node.**

**Recommendation: a spray node is not a `MachineGroup` and does not appear in
`RateSolution.groups`.**

What breaks if it does:

* `MachineGroup` requires `recipe_id` (`spec.py:82`) and the layout resolves it
  through `data.recipe(...)` in a dozen places (`candidates.py:128`, `:180`,
  `partition.py`, `validate.ctx.recipe_of`). There is no spray recipe in the
  vendored dataset; inventing one is a dataset fiction that every
  `data.recipe()` caller then has to special-case.
* Every metric over `groups` moves for a reason that is not a layout change:
  `RateSolution.machine_count` and `total_area` (`solve.py:125-135`),
  `BuildSpec.is_proliferated` (`spec.py:299-301`), `bench/report.py:40`, the
  audit's density objective (`scripts/audit.py:201-203`), `flow.conservation`
  (`validate.py:5112`), and the hierarchical partition's machine accounting
  (`partition.py:317-321`). 233 phantom "machines" would appear on the corpus.
* `_adapt(spec)` → `plan_strips` (`freeform.py:2470-2500`) would try to give the
  spray group a *strip*, which is precisely the thing a belt addon cannot have
  (§1.1).

What it would buy, and how to get it cheaper: per-coater proliferator demand,
instead of the geometric apportionment `_proliferator_supply_tree` does today
(`freeform.py:18803-18845`) and the sprayed-machine-share apportionment
`partition.py:317-321` does. That is obtainable inside the layout by giving each
node its share of `spec.external_inputs[proliferator_item]` — one line, no
change to `groups`.

**Kept at the rate layer, unchanged:** `spray_lanes`, `belt_required_edges`, the
proliferator external input. **Changed:** §5.4.

### 2.2 Layout layer: the node is a segment of the consumer strip's input lane

The node is the east end of the strip's own west channel: a run of belt tiles
with the addon riding one of them, an in-port strictly west of the body, and the
drop and approach belts it already gets.

```
   ox-3         ox-2          ox-1          ox           ox+1 …
    ▣ ─────────▶ ▣ ──────────▶ ▣ ──────────▶ ▣ ─────────▶ ▣     z = 0
  IN-PORT       [ ────── coater body, 3 tiles ────── ]   machine-facing lane
  merges land               ▲ seat, yaw 90                (sprayed cargo only)
  here, by                  │
  construction         drop (ox-2, y, 1)  ← PROLIFERATOR-IN PORT
                       approach (ox-3, y, 1) — permanent link, reserved
```

* **item-in port** — the lane head at `ox - west_channel`, unchanged
  (`freeform.py:6629-6638`). It stays the only cell of the lane a router path
  can reach, because every other lane tile is an occupied belt.
* **body** — `catalog.oriented_footprint(SPRAY_COATER_ID, yaw)` about the seat,
  half-span 1. **The invariant that makes the node a node: the body must not
  cover the in-port.**
* **item-out port** — the lane from the body's east edge onward,
  `cargo_domain=REQUIRES_SPRAY`. It is a source for sorters and never a net
  destination.
* **proliferator-in port** — the drop cell, already a `_Port` at `z = 1` (the
  `_Port.z` docstring at `freeform.py:6043-6054` exists for exactly this) and
  already the destination of a `NetRole.PROLIFERATOR` net
  (`freeform.py:16791-16804`).

**How "rides exactly one run" becomes structural.** Two facts, together:

1. *The seat starts at index `1 + half_span`, not index 1.* `_coater_seats`
   currently returns `port.tiles[1:stop]` (`freeform.py:18034-18037`); it
   returns `port.tiles[1 + half_span : stop]` instead, where
   `half_span = (oriented_footprint(SPRAY_COATER_ID, yaw)[0] - 1) // 2`. With
   `west_channel = 3` that leaves exactly one candidate, `ox - 1`, whose body is
   `{ox - 2, ox - 1, ox}` — head excluded. This single change removes the
   reported defect at its root: the merge cell is no longer a body cell.
2. *The body's own level becomes un-routable.* `_reserve_staged_coater_belt_ban`
   (`freeform.py:18100-18138`) already bans levels `1 …` above the body; it
   gains level 0 for the body tiles, and the routing problem takes the same
   cells as forbidden goals. The body tiles are occupied belts, so A* cannot
   step onto them anyway — the ban is what stops a *goal* being offered on them
   by `_merge_frontier` (`freeform.py:8935-8975`), which is the one path by
   which a second predecessor could still arrive.

After both, there is no legal path that produces `pred=[817, 1872]` on a body
tile. The property stops being a predicate over a finished placement and becomes
an arithmetic fact about where the seat is allowed to be.

**How "merges only upstream of the in-port" becomes structural.** Once the body
excludes the head, the head is west of the body and it is the only reachable
cell of the lane, so every many-to-one merge and every `_merge_frontier` side
merge lands west of the body. There is nowhere else for it to go.

**And the area-1 ambiguity, addressed by the same ban.** The evidence reports
coater#768's area 1 holding **two** belts inside the 1.0 radius on opposite
sides of the seat — the proliferator drop at `(53, 20, 1)` and a cargo lane at
`(55, 20, 1)`, with the coater at `(54, 20, 0)`. The rival is therefore the cell
mirroring the drop across the seat, `(2 * seat_x - drop_x, y, drop_z)`, and it is
banned at the drop's level. The exact radius arithmetic that admits a cell 2.5
world units from the area centre is *not* reproduced here and reproducing it is
Task 2's first job: the ban is written against the reported geometry, and the
test asserts the reported geometry becomes unbuildable, not that a particular
distance formula holds.

None of this restricts the router anywhere it was free: the channel is inside
the strip's own reserved box (`freeform.py:1731`, `3935`), so the banned cells
were never available to another strip's traffic.

**How "the thing it feeds into requires only proliferated inputs" stays true.**
Unchanged: the out-port carries `CargoDomain.REQUIRES_SPRAY`, sorters on it feed
only the proliferated machines of that strip, and
`prolif.sprayed_cargo_reaches_machines` (`validate.py:5011-5106`) remains the
arbiter.

**Both placers and the composer.** Nothing here is placer-specific.
Sequence-pair reaches `_place_coaters` through the *same*
`_prepare_routing_problem` (`sequence_solver.py:5366-5374`) and differs only in
how it reserves the channel (`sequence_solver.py:3744-3759`, `3851-3877`); the
hierarchical composer inherits it through `_solve_block`
(`hierarchy/strategy.py:274`) and only re-prices the collider afterwards
(`compose.py:318-363`). Making the node a property of the *strip* therefore
covers all three at once — which is the strongest argument for this layer and
against a separately-packed object, which would need a CP-SAT model change in
freeform, a sequence-pair encoding change, and a composer change.

---

## 3. Options, with trade-offs

### Option A — layout-only node on the consumer strip's own lane (**recommended**)

The design of §2.2: the node is the east end of the strip's west channel, its
in-port is the lane head, its body may not cover that head, and the body's cells
are un-routable. `_place_coaters` keeps doing the seating and the certification;
what changes is *where the seat is allowed to be* and *what the router may do to
those cells*.

* Nets added: **zero** (§6).
* Packed objects added: zero.
* Both properties structural.
* Covers freeform, sequence-pair and hierarchy with one change, because all
  three reach the same `_prepare_routing_problem` (`sequence_solver.py:5366`,
  `hierarchy/strategy.py:274`).
* Cost: one fewer seat candidate per sprayed lane at `west_channel = 3` (two
  become one), so a lane whose only viable seat was `ox - 2` now refuses. That
  is the point — that seat is the defect — but it must be *counted*, and the
  gate counts it.

### Option B — full recipe node in the rate solve

Rejected. §2.1 lists the seven downstream consumers of `RateSolution.groups`
that move, the dataset fiction required, and the fact that a belt addon cannot
be given a strip. It also does not make either property structural on its own:
the merge under the body is a *router* fact, and a rate node does not constrain
the router.

### Option C — coater-composite strip, the backlog idea

`docs/speedup-idea-backlog.md:184-185`: "treat spray coater plus strip as one
unit so the placer never sees the keep-out problem". Read literally as "a
composite object the packer places", this is Option A plus a packer change; read
as "the coater is part of the strip's reserved geometry", **it is already true
today** (`freeform.py:1731`, `2619`, `3935`). Option A is the version of C that
does not touch either packer. The backlog entry should be marked as delivered by
A.

If C means a *separately packed* 1x3 object with its own item-in and item-out
nets: +233 nets and +233 packed objects corpus-wide (§6), a CP-SAT model change
in freeform, a sequence-pair encoding change, and the game still requires the
object to ride a belt whose two neighbours the packer does not control. Rejected.

### Option D — one coater per sprayed *item*, shared across consumer strips

Enabled by the over-proliferation ruling. Measured: 233 coaters today against
**171** distinct sprayed items across the 36 corpus specs — a saving of 62
coaters (27%), and only where an item has several proliferated consumer strips.
Rejected: one belt feeding several lanes is a splitter per consumer, which is
the invariant a lane-per-destination exists to keep
(`freeform.py:6775-6780`), and the splitter would sit downstream of the coater
where `_projected_coater_splitter_candidates` (`finalize.py:1617`) already has to
work hard. 62 addons is not worth reintroducing splitters on sprayed cargo.

### Cheapest version that makes both properties structural

**Smaller than the whole of A, and it is two changes:**

1. `_coater_seats` starts at index `1 + half_span` instead of index 1
   (`freeform.py:18034-18037`), so the body cannot cover the in-port;
2. `_reserve_staged_coater_belt_ban` bans the body's own level and the routing
   problem refuses those cells as goals (`freeform.py:18100-18138`), so
   `_merge_frontier` cannot offer one.

Both properties are structural after those two. Everything else in A — the
`CoaterNode` record, deleting `_coater_seat`, deleting the now-vacuous
`selfloop` seat predicate — is consolidation that makes the node visible in the
code rather than implied by a slice index. The plan sequences it that way: the
correctness lands in Tasks 1-2 and can be shipped alone; Tasks 3-6 are the node
and the ruling; Task 7 is the gate.

---

## 4. Migration

| Thing | Fate |
|---|---|
| `_place_coaters` (`freeform.py:18141`) | **Stays**, and gains a `CoaterNode` per committed coater (§5.3). Its seat search, projected-static, addon-supply and splitter certification (`freeform.py:18245-18660`) all stay: they need the finished pack. |
| `_coater_seats` (`freeform.py:18019`) | **Changed**: starts at index `1 + half_span` (§5.1). This is the one-line correctness change. |
| `_coater_seat` (`freeform.py:18040`) | **Deleted.** Unused by the placement path, and its docstring documents a second-tile rule `_place_coaters` no longer follows and that §5.1 now forbids. |
| `_coater_keepout_hits` (`freeform.py:5213`) | **Stays**, unchanged. The body still has to clear machines. |
| `_projected_coater_junction_bans_by_frame` (`freeform.py:14625`) | **Stays**, unchanged. Splitter-versus-coater clearance is a pack-level fact. |
| `_reserve_staged_coater_belt_ban` (`freeform.py:18100`) | **Stays and grows**: the body's own level and the area-1 rival cell, as goal bans as well as cell bans (§5.2). |
| `_COATER_WEST_CHANNEL` (`freeform.py:210`) and the lift (`2683-2699`, `sequence_solver.py:3744`, `3851-3877`) | **Stays.** It is now the node's declared footprint — and §5.1 makes 3 a hard floor rather than a comfortable default, since `west_channel < 3` offers no legal seat at all. Task 3 asserts that. |
| `_Unseatable` (`freeform.py:13663`) | **Stays**, unchanged, raised from the same place. The narrower seat set makes it fire more often; the gate counts by how much. See open question 3. |
| `_place_proliferator_entry`, `_proliferator_supply_tree` (`freeform.py:19051`, `18803`) | **Stay**, unchanged. The proliferator net is the one net the node keeps and it already exists. |
| `hierarchy/compose.py:_coater_belt_ban` (`compose.py:318`) | **Stays.** It reconstructs the ban from the committed building and is agnostic to who seated it. |
| `game.addon_supply` (`validate.py:2188`), `game.addon_facing` (`:2360`), `game.addon_corner` (`:2468`) | **Stay**, unchanged arbiters. |
| `prolif.coaters_are_supplied` (`validate.py:4832`) | **Stays**, unchanged. |
| `prolif.sprayed_cargo_reaches_machines` (`validate.py:5011`) | **Stays** as the end-to-end arbiter. Its `forbids_spray` half (`:5066`, `:5081`, `:5092-5099`) is downgraded to WARNING — §5.4. |
| `prolif.coater_rides_one_run`, landing on `selfloop` | **Stays as an arbiter, its planner half is deleted.** See below. |

### Relationship to the `selfloop` cheap fix

The `selfloop` work (`docs/superpowers/specs/2026-09-06-self-loop-recipes-design.md`
§4 F2 and §5.5) has two halves:

1. a **validator check** `prolif.coater_rides_one_run` — a coater's covered
   tiles must have no belt with two predecessors, and area 1 must hold one belt;
2. a **planner predicate** on `_coater_seats`/`_coater_seat` rejecting such a seat.

**This design is the structural replacement for (2) and a complement to (1).**
Half (2) becomes vacuous once the body tiles cannot be reached by any path — a
predicate that can never fire is dead code and is deleted in Task 6. Half (1)
stays forever, for the same reason `_place_coaters`'s own docstring gives at
`freeform.py:18183-18186`: "so neither this nor a future strategy can put the
miss back". Its status changes from *the fix* to *the regression test*, and the
plan pins that by requiring it to be green before and after.

**Sequencing:** this work starts after `selfloop` lands, so Task 1 rebases onto
a tree where `prolif.coater_rides_one_run` already exists and already passes. If
`selfloop` slips, Task 1 adds the check itself from the code block in that spec
at `:439-452`; nothing else in this plan depends on the rest of `selfloop`.

---

## 5. The change, by layer

### 5.1 `_coater_seats` — the body may not cover the in-port

```python
def _coater_body_half_span(yaw: float) -> int:
    """Tiles the 1x3 body reaches either side of its seat along the lane."""
    return (catalog.oriented_footprint(catalog.SPRAY_COATER_ID, yaw)[0] - 1) // 2


def _coater_seats(
    canvas: _Canvas,
    port: _Port,
    *,
    west_channel: int,
    yaw: float = Facing.EAST.value,
) -> tuple[tuple[int, int], ...]:
    half_span = _coater_body_half_span(yaw)
    stop = min(len(port.tiles) - 1, west_channel)
    return tuple(
        (canvas.buildings[index].x, canvas.buildings[index].y)
        for index in port.tiles[1 + half_span : stop]
    )
```

`1 + half_span` rather than `1`: index 0 is the head and the body reaches
`half_span` tiles west of the seat, so a seat at index `half_span` or less
covers the head. `west_channel` is already 3 (`freeform.py:210`), which leaves
exactly one candidate at `ox - 1`; the clearance lift to 4
(`freeform.py:2683-2699`) leaves two.

### 5.2 `_reserve_staged_coater_belt_ban` — the body's own level, and area 1

`freeform.py:18100-18138` bans levels `1 .. belt_crossing_height` over a
`span`-radius box around the seat, skipping the drop. It gains, before that
loop:

```python
    body_half = _coater_body_half_span(staged.port.yaw)
    for dx in range(-body_half, body_half + 1):
        canvas.belt_ban.setdefault((cx + dx, cy), set()).add(staged.port.host_z)
    # Area 1 must resolve to exactly one belt.  The rival the evidence names is
    # the cell mirroring the drop across the seat, at the drop's own level.
    rival = (2 * cx - staged.port.x, 2 * cy - staged.port.y)
    canvas.belt_ban.setdefault(rival, set()).add(staged.port.z)
```

and the routing problem takes the same cells as forbidden *goals* so
`_merge_frontier` (`freeform.py:8935-8975`) cannot offer one. The head cell and
the drop are excluded: both are legitimate destinations.

`_place_coaters`'s tail already pops the ban on each committed drop
(`freeform.py:18768-18769`); that stays.

### 5.3 `CoaterNode` — the invariant stated in the type

The record that makes the node visible rather than implied:

```python
@dataclass(frozen=True, slots=True)
class CoaterNode:
    """One Spray Coater as a placed node: in-port, body, out-port, supply."""

    item: str
    strip_index: int
    #: Lane belt index of the in-port: the head, and the only cell an item net
    #: may reach on this lane.  Strictly west of every cell in ``body``.
    in_belt: int
    #: Lane belt indices the 1x3 body covers, west to east, at ``host_z``.
    body: tuple[int, ...]
    #: First lane belt east of the body; the out-port sorters draw from.
    out_belt: int
    seat: tuple[int, int, int]
    yaw: float
    drop: tuple[int, int, int]
    approach: tuple[int, int, int]

    def __post_init__(self) -> None:
        if self.in_belt in self.body:
            raise ValueError(
                "a Spray Coater's body may not cover its own in-port: the head "
                "is where producer nets merge, and a merge under the body is "
                "the defect this node exists to make impossible"
            )
```

`_place_coaters` keeps its signature and its projected-frame certification
(`freeform.py:18385-18660`) and gains a `CoaterNode` per committed coater,
returned alongside the `CoaterSupplyPort` list it already returns. The
`__post_init__` above is the invariant of §2.2 stated once, in the type, where
neither placer can route around it.

`freeform.py:16744-16748`, `_proliferator_supply_tree` (`18803`) and
`sequence_solver.py:5536` keep reading `CoaterSupplyPort` and are unchanged.

### 5.4 The over-proliferation ruling, applied

**Measured first (§6): it buys two lanes across the whole corpus.** Exactly two
of 36 specs draw one item in both cargo domains — `super-magnetic-ring` /
`output-products` (`magnet`) and `universe-matrix` / `all-products` (`hydrogen`)
— each contributing one unsprayed lane, and there are **zero** duplicated output
lanes anywhere in the corpus. So the ruling does not simplify the node model by
removing lanes, and this design does **not** remove `CargoDomain`: the domain is
what types the node's out-port and it costs nothing measured.

Where the ruling *is* applied, because it removes a constraint rather than a
lane:

* `prolif.sprayed_cargo_reaches_machines`'s `forbids_spray` clause
  (`validate.py:5066`, `:5081`, `:5092-5099`) drops from `Severity.ERROR` to
  `Severity.WARNING`, and its message says the build over-produces by design.
  This is the clause that would otherwise refuse a legal placement in which a
  sprayed lane happens to reach an unproliferated consumer.
* `BuildSpec.lanes_requiring_split` (`spec.py:191-195`) is **kept as a report**
  and stops being a correctness constraint. It is computed in one place
  (`rates/candidates.py:220-229`), read in one place (`validate.py:5066`), and
  is worth keeping so the CLI can say which items got over-proliferated.
* The node's **out-port may feed unproliferated consumers**, so a producer that
  feeds both kinds of consumer is free to share one lane through one coater when
  the strip planner finds that cheaper. On this corpus it never does; the
  permission costs nothing and removes a refusal class.

**Not applied:** the split stays mandatory when two consumers of one item want
*different* proliferator modes, because a coater holds one proliferator item and
`RateSolution.tier` (`solve.py:118`) is global to the solve. See open question 1.

### 5.5 Validation

No new checks. `prolif.coater_rides_one_run` from `selfloop` becomes the
regression arbiter (§4). `prolif.sprayed_cargo_reaches_machines` is amended per
§5.4. Everything else is unchanged.

---

## 6. Costs, measured

Method: `plan_strips(spec)` over every candidate spec of every
`flab2bp.bench.corpus.URL_CORPUS` entry — the same 12 URLs × 3 candidate
policies = 36 specs that `scripts/audit.py`'s 72 cells are built from (36 specs ×
2 strategies). Rate solve plus strip plan only, no packing and no routing;
5.3 s wall, `uptime` load 13.5 before / 33.5 after. The measurement script is
reproduced in the plan (Task 0) so the numbers can be re-derived.

### 6.1 Sprayed lanes, i.e. coaters

| | specs | strips | sprayed strips | **sprayed lanes = coaters** | input lanes | output lanes |
|---|---|---|---|---|---|---|
| whole corpus | 36 | 393 | 118 | **233** | 663 | 518 |
| proliferated specs only | 24 | — | 118 | **233** | 424 | 331 |

Worst single spec: `universe-matrix` / `all-products` — 46 strips, 42 of them
sprayed, **83 coaters**, 85 input lanes. Next: `quantum-chip` / `all-products`
28, `information-matrix` / `all-products` 27, `super-magnetic-ring` /
`all-products` 16. The `no-proliferator` policy is 0 everywhere, so **12 of 36
specs (24 of 72 audit cells) are untouched by this design.**

### 6.2 Nets added

**Zero, under the recommended Option A.** The coater rides the consumer strip's
own input lane, and the unsprayed→sprayed transition is a belt link that
`_emit_strip` already makes (`freeform.py:6572-6574`). No new net, no new router
hop, no new goal. The proliferator net per coater already exists
(`freeform.py:16791-16804`).

**+233 nets and +233 router hops** is what a separately-placed coater node
(Option C-as-a-packed-object, or Option B taken to the layout) would cost: one
item-in net per coater, on top of the 424 input-lane nets the 24 proliferated
specs already carry — **+55%** input-side nets on proliferated specs, +35%
against all 663 input lanes in the corpus. On `universe-matrix` /
`all-products` alone: +83 nets on 85 input lanes. That number is the reason
Option A is recommended over C.

### 6.3 Packing complexity

Zero added. The node lives inside the strip's existing box: `_size` already adds
`west_channel` (`freeform.py:1731`) and every packer offsets by it
(`freeform.py:3935`, `4980`, `sequence_solver.py:4378`). Option C as a packed
object would add 233 objects to the CP-SAT model corpus-wide and 42 to
`universe-matrix` / `all-products` alone.

### 6.4 Lane sharing

`_merge_lanes` (`strip_variants.py:1591`) and `_merge_frontier`
(`freeform.py:8935`) keep working unchanged **upstream** of the in-port, which is
where every merge already landed and now lands by construction (§2.2). No
producer loses a merge it could legitimately have made: the head was always the
only reachable cell of a sprayed lane, because every other lane tile is an
occupied belt. `_Port` is untouched — the design deliberately does not shrink
`_Port.tiles`, which would break `strip_of_belt` attribution
(`freeform.py:16356-16358`), the port-access column count
(`freeform.py:11627`) and `_coater_seats` itself (`freeform.py:18034`), all of
which read the full lane.

What the router loses is three *goal candidates* per sprayed lane — the body
cells, which `_merge_frontier` could previously offer as merge points. Those are
occupied belts, so a path could never have stepped onto them; only the merge
link was available, and that link is the defect.

### 6.5 What the over-proliferation ruling saves

| | count |
|---|---|
| specs where any item is drawn in both cargo domains | **2 of 36** |
| duplicated output lanes attributable to the domain split | **0** |
| unsprayed lanes that could be folded into a sprayed one | **2** (one each) |
| coaters saved | **0** |

Reported honestly: the ruling is *permission*, not a saving. It is applied for
the refusal class it removes (§5.4), not for lanes.

---

## 7. Risks

1. **Coverage loss from the narrower seat set.** At `west_channel = 3` the two
   candidates become one, so a lane whose `ox - 1` seat hits a keepout or a
   projected collider now raises `_Unseatable` where it previously fell back to
   `ox - 2`. This is the main risk in the whole design and it is *the intended
   behaviour* — the fallback seat is the defect — but it must be counted, not
   discovered. Task 5's gate compares clean-cell counts and the
   `preparation_error="unseatable"` tally against the pre-change baseline on the
   same 72 cells. If the loss is real, the mitigation is already designed and
   costs one column: the clearance lift at `freeform.py:2683-2699` and
   `sequence_solver.py:3866-3874` already knows how to raise the channel to 4,
   which restores two candidates. Raising `_COATER_WEST_CHANNEL` to 4
   unconditionally is the fallback, and open question 2 asks whether the user
   will pay for it up front.
2. **The area-1 rival ban blocks a legitimate crossing.** `(ox - 1, y, 1)` is a
   level-1 cell inside the strip's channel; a ramped belt crossing the strip
   could have wanted it. Mitigation: `belt_ban` is exactly the mechanism the
   router already respects for the coater's other levels
   (`freeform.py:18121-18138`), so the router reroutes rather than failing —
   at some congestion cost the gate measures.
3. **The body-level ban costs routing corridor.** Three cells per sprayed lane
   become un-routable at level 0: ~250 cells on `universe-matrix` /
   `all-products`. They are occupied lane belts already, so the only real loss
   is goal candidates for `_merge_frontier`. Measured by the gate.
4. **`selfloop` slips.** Task 1 carries the check itself in that case (§4).
5. **Over-proliferation surprises the user in a report.** Downgrading
   `forbids_spray` to WARNING means a build can now legitimately over-produce.
   Task 6 requires the CLI to name the items, so it is on the report rather than
   only in this document.
6. **`half_span` is derived per yaw and every coater is yaw 90 today**
   (`freeform.py:18272`). At yaw 0 the oriented footprint is `(1, 3)`, so
   `half_span` along the east-west lane is 0 and index 1 becomes legal again —
   correctly, because the body then does not extend along the lane at all, but
   `addon_ride_is_straight` (`dsp/rules.py:721-749`) would reject the ride for a
   different reason. Task 1's test pins both halves so the derivation is
   exercised rather than assumed to be "always 1".

---

## 8. Open questions for the user

Only the three the code cannot settle.

1. **Different spray modes on one item.** `RateSolution.tier`
   (`rates/solve.py:118`) is one proliferator tier for the whole solve, but
   `MachineGroup.proliferator_mode` (`spec.py:85`) is per group and can be
   `PRODUCTS` on one consumer and `SPEED` on another. A coater holds one
   proliferator item, so one shared sprayed lane cannot serve both modes. The
   over-proliferation ruling does not cover this case (it is not "more spray", it
   is "the wrong spray"). Should such an item keep a hard lane split, or should
   the build pick one tier and accept that the other consumer runs on the wrong
   mode?
2. **A permanent 3-column channel.** Option A pins the node inside
   `_COATER_WEST_CHANNEL = 3` (4 where the clearance lift applies) on **every**
   proliferated strip — 118 sprayed strips corpus-wide, 42 on
   `universe-matrix` / `all-products`. Today the channel is already bought at
   plan time, so this is not a new cost; but it becomes permanent rather than
   something a future tightening could reclaim. "Density may be paid for
   correctness, even a lot" suggests yes — confirm it, because a later
   "reclaim the channel when the seat lands at `ox - 1`" idea is foreclosed.
3. **What to do if the narrower seat set costs clean cells.** At
   `west_channel = 3` the candidates go from two to one, so some lanes will
   raise `_Unseatable` where they previously seated at the bad tile. Two
   responses are available and the code cannot choose between them:
   raise `_COATER_WEST_CHANNEL` from 3 to 4 unconditionally — one column on
   every proliferated strip, 118 of them corpus-wide, restoring two candidates —
   or accept the refusals as honest and let the affected specs fail until a
   different strip pose is found. "Density may be paid for correctness, even a
   lot" points at the first; it is a permanent width cost on every proliferated
   strip, so it should be a decision rather than a reflex. Task 5 measures the
   loss first and this question is answered with that number in hand.
