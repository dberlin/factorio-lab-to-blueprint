# Backlog

## OPEN -- sorters may only touch a machine where the game says they may

The game's own predicates are now ported (`game.inserter_data`,
`game.inserter_paste`, `game.inserter_skew` in `layout/validate.py`), and the
real `PrefabDesc.slotPoses` table is extracted from the game's prefabs
(`scripts/extract_dsp_slot_poses.py` -> `dsp/data/slot_poses.json`). They agree
with the game on all 1142 usable machine-side sorter records in the fixture
corpus and disagree with **us** on four building types and three whole classes
of connection. None of this was visible before, because nothing here had the
table.

Measured over both strategies and the whole URL corpus (`--time-budget 1`,
one candidate each): **8 of 22 placements are clean; the other 14 carry 5,946
findings, and every single one of them touches an Oil Refinery (2,247), a
Chemical Plant (504), a Quantum Chemical Plant (236) or a Matrix Lab (228).**
Not one 3x3 machine is implicated. Three separate defects:

1. **A face wider than three tiles has no slot out at its ends.** A Matrix Lab
   is five wide and its slots sit at `x in {-1, 0, 1}`; the Oil Refinery's
   seven-deep sides carry three. Both strategies choose the machine-side column
   from the belt's position, so a wide machine gets sorters where no slot is.
2. **The Chemical Plant is not a ring at all.** Eight slots: four along the
   north face at `x in {-1, 0, 1, 2}`, and four at `z = -0.9`, which is one row
   INSIDE a footprint five deep. Neither long side takes a sorter anywhere, and
   the south attachment is not on the edge tile.
3. **The Oil Refinery's south face sits 0.6 tiles outside its last tile row**,
   so a one-tile sorter from it is 0.4 long once the game snaps the end onto the
   pose -- under the 0.6 minimum. Those need a two-tile sorter.

Three building types accept **no sorter at all** -- Spray Coater, Energy
Exchanger and both logistics stations ship zero insert poses, and
`BuildTool_Inserter` will not even let a sorter target a building with none.
They are fed by BELT. Both strategies wire a sorter into a Spray Coater, so
every proliferated candidate now refuses rather than emitting a connection the
game cannot make. That is the correct failure and it is also a real capability
loss: proliferation needs a belt-fed coater.

**83 tests in `test_spine.py` and `test_freeform.py` fail as a result**, all of
them of the form "this spec lays out and validates clean" for a spec containing
one of the four buildings, or a spray-coater spec. They are the checks working.
The audit stays at **INVALID 0** across three runs (tier `small`, budget 4s:
8/30 clean, 22 refused, 0 invalid, 0 crashed, identical all three times) --
refusing emits nothing, which is the failure mode this project prefers.

Fixing it is a layout change and was deliberately left out of the branch that
found it: the machine-side column has to come from the target's slot table
rather than from the belt, and the coater has to be belt-fed.

## RESOLVED -- layout solver speed

*Kept as a record of what the numbers actually said, because the first diagnosis
below was wrong in an instructive way.*

Freeform went from **15.0s to 1.16s at identical density** (area 1435), and the
default test run from minutes to ~13s. None of it came from tuning budgets or
worker counts. Three real defects:

1. **A cycle in the A\* predecessor graph.** The ramp branch wrote the
   intermediate cell's state gated on a *different* cell's improvement, breaking
   the strictly-decreasing invariant that makes `prev` acyclic. Path
   reconstruction then walked the cycle forever -- 100% CPU *and* an unbounded
   list, which is where the 24-38 GB per worker came from.
2. **An inadmissible heuristic and no expansion cap.** `h` used the goals'
   *centroid*, so it never reached 0 at a goal and misled the search whenever
   goals were spread. A\* degenerated into an unguided Dijkstra over every
   reachable cell x level.
3. **An objective anti-correlated with the metric.** Height is fixed per solve,
   so `w_var` *is* area -- yet it carried weight 5 against 22 HPWL terms each up
   to `width_bound`. Wirelength dominated and the solver traded width away to
   shorten wires, which is why **more solver time produced worse layouts** (1460
   tiles at 0.1s versus 1566 at 4s). Width now outranks HPWL lexicographically.

Two bound cuts came out of it and stayed: `w_var >= ceil(total_area / height)`
(its lower bound was **1**), and `dx + dy >= min(min(w_i,w_j), min(h_i,h_j))`
for each net pair (every HPWL term relaxed to 0, so half the objective was
invisible to the bound). Bound moved 320 -> 470 immediately.

**The lesson worth keeping:** the original diagnosis here was "model
construction is too slow, cache it and warm-start". That was wrong, and profiling
first -- as this file's own step 1 advised -- would have caught it. A 71-variable
model was never the problem.

**Also measured and rejected:** weighting the A\* heuristic to break ties on the
equal-cost Manhattan plateau. Controlled at `workers=1` it cut A\* time ~15% but
produced **12% more belt tiles**, and A\* is only 0.32s of 0.85s, so the net was
~5% speed for materially more buildings to paste. Not worth it.

## RESOLVED -- direct insertion fires; the COUNTER could not see it

The item said both strategies find direct-insertion opportunities and discard
them, on the evidence of `direct_inserts = 0` across the whole bake-off. The
premise was wrong. Freeform emits **17 bridging sorters across the 24 (URL,
candidate) pairs**; `bench/metrics.py::measure` defines a direct insert as a
sorter with a MACHINE AT BOTH ENDS, and freeform's bridge spans the producer's
output-lane belt to the consumer's input-lane belt. The counter reported zero
however many were placed. `bench/runner.py` now reads what the strategy
reported. Counting belt-to-belt sorters instead would swap the error round --
spine's trunk taps are belt-to-belt too, and are not direct inserts.

It is worth what it costs. Measured on/off at `workers=1`, 8s, all 24 pairs
shipping both ways: **5210 belt tiles against 5302, and 10786 area against
10890**. Biggest single win is `processor`/`no-proliferator` at 171 belt tiles
against 275, a 38% cut. By candidate: `no-proliferator` 7 bridges,
`free-proliferation` 10, `max-proliferation` 0 -- correctly zero, since every
edge there is belt-required. One honest regression, `super-magnetic-ring`/
`no-proliferator`, which is larger with it than without.

### Machine-to-machine insertion is geometrically impossible in freeform

Not a bug, and proved rather than assumed: producer machine bottom to consumer
machine top is `out_lanes + MARGIN + in_lanes + 1 >= 4` rows against a
`SORTER_MAX_REACH` of 3. A true machine-pair insert needs the strip planner to
omit both lanes for that edge, which changes every strip height and therefore
the pack. A test pins the arithmetic so it cannot go stale silently.

## RESOLVED -- lanes are trimmed, and most of them should not have existed

The real finding was bigger than trimming. Risers made intermediate lane copies
vestigial and nothing removed them: **321 of 975 spine lanes were joined to
nothing at either end, holding 34,372 of 80,620 lane belt tiles**. A lane is also
a tile of corridor height, so they cost AREA, not just buildings. `_lane_requirements`
now gives a corridor exactly the lanes it is tapped for; extents stop at the
columns sorters actually use. Dangling tails 595 -> 151, dead lanes 321 -> ~0.

Freeform trims input lanes to their last sorter. Output lanes are deliberately
left alone -- filled at every machine column, drained at the east end, so every
tile carries flow. Building counts: processor 327 -> 248, graphene 208 -> 160,
super-magnetic-ring 1309 -> 1147.

## RESOLVED -- `tile_to_local_offset` is correct

No paste into the game was needed. A blueprint the game itself emitted is
necessarily legal, and the fixtures are therefore a real oracle -- one nobody had
pointed at this. On the three fixtures with no latitude compression, the centre
reading gives **0 footprint overlaps, 0 of 2,656 belts inside a machine, and 686
of 686 machine-side sorter endpoints inside the machine they serve**. The two
corner readings score 18 and 38 overlaps, 675 and 669 buried belts, and 248/676
and 174/666 endpoints. Locked by `tests/dsp/test_local_offset.py`.

Two things worth keeping, both of which nearly wasted the exercise:

* **The round-trip check this item originally proposed is nearly vacuous.**
  Every catalog footprint is odd, so `w/2 - 0.5` is always an integer and
  "recovered tile is an integer" reduces to "the building is on-grid" -- it would
  pass under any wrong per-footprint integer offset. Only checks that compare
  DIFFERENT footprint sizes against each other discriminate.
* **Alignment is not enough to call a fixture geometry-safe.**
  `temple-of-effectiveness` is 796/796 integer-aligned and still stacks 83
  buildings onto occupied cells, because polar longitude collapse keeps whole
  numbers while merging distinct tiles. `GEOMETRY_SAFE_FIXTURES` is wrong in
  both directions as a result: it lists `factory-quick-start-step-3-red-cube`
  (21 of 232 off-grid, 9 collapsed) and omits `12-s-purple-science`, which is
  3,008 clean buildings across a real mix of footprint sizes.

The even-footprint half-tile branch is **unreachable rather than verified** --
no catalog footprint is even, so it never fires. `test_no_catalog_footprint_is_even`
fails if that stops being true.

## RESOLVED -- `TESLA_LINK_DISTANCE` is 22.5, from the game's own code

`PowerSystem.OnNodeAdded` links two nodes when
`dx*dx + dy*dy + dz*dz <= max(a.connDistance2, b.connDistance2)`, where
`connDistance2` is `PowerDesc.connectDistance` squared, carried through
`PrefabDesc.powerConnectDistance` and `NewNodeComponent` with no scaling. It is a
centre-to-centre distance; 11.25-as-diameter is refuted, and `PowerDesc` has no
diameter field at all. Read out of `Assembly-CSharp.dll` with `ikdasm`.

Two consequences the constant's users need:

* The rule takes the **larger** of the two nodes' reaches. A Wireless Power Tower
  (`connectDistance` 45.5) links to a Tesla Tower at up to 45.5, so a solver
  treating 22.5 as a universal link budget under-reaches whenever a long-range
  node is present.
* Node positions are projected onto a sphere of radius `realRadius + 0.2` before
  the comparison, so the constant is only valid for flat, non-polar layouts.

## RESOLVED -- neither strategy could serve two destinations from one belt

Both strategies hit the same missing primitive from opposite directions, and
both used to hide it by emitting something. Closed by `layout/junction.py`,
whose convention is read off the 25 splitters in the fixture corpus and
verified through both our codec and the TypeScript viewer.

* **Freeform** now taps a different TILE of a lane for each consumer and puts a
  splitter there. Fixing it uncovered three silent failures worth remembering:
  port reservations still held at commit time (every path through its own start
  cell was dropped), A\*'s ramp reconstruction splicing a cell twice into one
  path (3 of 19 routed paths), and a strip's inner lanes being WALLED IN so that
  only the head is reachable -- which was all 40 A\* failures on magnetic-ring,
  every one at zero expansions with two thirds of the routing budget unspent.
* **Spine** joins an item's corridor copies with trunk risers in a margin east
  of the block, y-spans coloured as an interval graph, cross-column stubs
  bridged at z=1. `flow.lane_sourced` on magnetic-ring: 11 -> 0.

## MEASURED AND REJECTED -- a routing-capacity constraint in freeform's packer

This was the top item and it was the wrong diagnosis. Recorded because the
reasoning was plausible enough that somebody will propose it again.

The theory: `_pack` minimises width then wirelength and discovers only
afterwards, in `_build`, whether the result can be WIRED -- so give it a
horizontal cut, `crossings(row) <= free width on that row`. That is a genuine
necessary condition, and it is the shape spine uses for tap capacity, having
learned the same lesson: "rejecting after the fact cannot work here; routability
is a property of the packing, so the packer has to know."

It does not pay. Over the whole trivial+small+mid corpus, every candidate, three
repeats: **one** more valid pair out of 24 and one more valid sample out of 72 --
inside the noise -- for 0.5% more area and a test suite going 39s to 67s. A
single 6s sample had shown it winning decisively (0 unrouted nets against 2,
1240 tiles against 1504); that did not reproduce at any other budget.

**The packer was never the binding constraint.** Classifying every routing
failure showed empty A\* frontiers outnumbering genuine search exhaustion about
ten to one. The failures are GEOMETRY -- a lane port with no free neighbour --
not congestion. A strip's inner lanes are walled in (lane above, machines below,
lane either side), so only the head of an in-lane and the end of an out-lane are
reachable at all, and three of the five walled-in ports on the free-proliferation
chain turned out to be taps that an earlier fix had itself moved mid-lane.

If freeform's remaining refusals are to be fixed, they will be fixed by making
ports reachable, not by making packs roomier.

## RESOLVED -- riser bridges spend the ramp tiles honestly

Bridges now spend `RAMP_TILES_PER_LEVEL` per level change, which needs a free
ramp column beside each trunk, so the margin doubles. Isolated on the final
tree: **+6.1% area overall, +9.1% on the median run, 6 of 66 runs pay nothing**.
Worst case is magnetic-coil at +40%, a nine-machine spec whose block is narrower
than its margin. Against a -21.5% total, fidelity won.

## RESOLVED -- risers split into parallel lanes, and it was NOT latent

This file claimed `flow.belt_capacity` passed on every corpus spec, so the
single-belt trunk was only a future risk. Wrong: `quantum-chip` moves 48
crude-oil/s and 48 refined-oil/s against a 30/s Mk.III belt -- **8
`flow.belt_capacity` errors across the corpus**. `_lane_copies` sizes parallel
lanes from the rate, machines deal round-robin across them, and each copy gets
its own trunk. Isolated: **+2.3% area, 8 errors to 0**. Where splitting makes a
corridor unwireable it is abandoned rather than the layout -- coverage outranks
throughput.

## RESOLVED -- lane direction is derived from the taps

Also measured against this file's guess, which was that it was pervasive: it is
**3 of 656 lanes**, on magnetic-coil, plastic and processor. Real every time -- a
machine that pastes and never runs -- and invisible to the validator.
`_lane_direction` derives direction from the taps where physics leaves it free
and forces it where it does not. 3 starved drains to 0 corpus-wide.
`stats["starved_taps"]` counts the residue, because drains on BOTH sides of the
fills cannot be served by any single direction and has no cheap fix.

## RESOLVED -- `flow.conservation` reads the placement, as a reachability cut

The previous note said the junction-aware version could not be seeded soundly,
citing junction 1639 showing downstream demand 12 against upstream supply 4. That
reading was wrong on the facts: `magnetic-coil` is not an external input, so no
seeding was involved -- the fixture genuinely runs 4 magnetic-coil machines at
1/s against 12/s of demand, and the existing spec-arithmetic clause was already
reporting it. The seeding problem was solvable too; `_entry_items` divides
`external_inputs` across entry lanes in proportion to demand.

The per-junction form was then built, measured, and **rejected**: 15 lanes
reported short across `processor` and `super-magnetic-ring`, every one a false
positive. Three things in this model divide a rate evenly where DSP does not -- a
splitter feeds whichever output has room, a machine with two output sorters fills
whichever lane is not backed up, and a lane fed by two producers draws from
whichever is not empty. All three self-balance under backpressure.

What shipped instead is a **cut argument**, which backpressure cannot rescue:
union-find everything an item can physically reach (lanes, junctions, transfer
sorters, machines), and within each island production plus external supply must
cover consumption. 10 findings over 512 belt runs of the corpus, every one on a
build already refused by `machine.inputs_supplied`, none on a build that
otherwise validates clean.

### Known weakness: islands are undirected

A producer joined DOWNSTREAM of its consumer's tap reads as connected. This is
conservative on purpose -- it can hide a shortfall, never invent one -- but it is
the direction to tighten if the check ever needs to be stronger.

## RESOLVED -- `belt.termination` now measures overshoot, not tapping

The rule was wrong rather than merely noisy. It asked whether the TAIL TILE was
tapped, and both strategies end a lane a couple of tiles past its last consumer,
so correct lanes failed while wasting 2 tiles in 50. It now measures the size of
the overshoot against `SORTER_MAX_REACH`, and always reports a lane no sorter
touches anywhere.

Controlled on identical placements, old rule against new: hand-built fixtures 32
of 123 runs to 3; corpus 127 of 535 to 74. The survivors carry their own
justification -- median 8 dead tiles, tail of 44 -- and every finding names the
tile count to cut.

## RESOLVED -- transfer sorters were invisible to the flow graph

Found while doing the above, and the same theme as every other hole in this file:
a check that counted buildings instead of following connections.

A sorter with a BELT ON BOTH ENDS -- how both strategies tap a trunk onto a
branch without spending a splitter -- appeared in neither the successor/
predecessor graph nor the sorter-flow table, because `_sorter_demand` returns
`None` when neither end is a machine. So a trunk drained by a transfer sorter was
charged **zero**, and `flow.belt_capacity` could not see load leaving a lane that
way at all: a Mk.II belt carrying 20/s reported clean. Transfer sorters are now
graph edges and the rate is derived rather than guessed.

## RESOLVED -- the hand-built fixtures balance

`magnetic_ring_spec` is now the exact stoichiometric solution at 2 rings/s: 9
groups, 54 machines, supply equals demand for every item, Mk.III belt because
iron-ore at 22/s does not fit on Mk.II. Both strategies use the same numbers, so
they are compared on one spec rather than two. `two_stage_spec` was unbalanced
as well. `balanced_pair_spec` is deleted -- balancing it made it identical to
`two_stage_spec`, and dodging the imbalance was its only reason to exist.
Arithmetic tests pin both so they cannot rot back.

## RESOLVED -- freeform supplies its coaters; the numbers below are historical

**Re-measured 2026-08-23 and this no longer reproduces.** On trivial+small+mid
freeform is **48/48 clean** -- 0 refused, 0 invalid, 6s wall -- against the
14-of-24 recorded below. Across the full stress corpus it is 62-66/72 over nine
runs with **zero** `prolif.*` findings in any of them; every remaining miss is
`<refused>`, and those are concentrated in `universe-matrix` (6) and
`quantum-chip/max-proliferation` (2), neither of which is a proliferator-entry
failure.

No single commit closed this. It went out under the accumulated 2026-08-23
freeform work -- most likely `e1174f0` (stacked output lanes were walling in
their own east access cells, which is the same shape of defect as the entry lane
being walled in) and `a834293` (a ground-level toll that sends through-traffic
upstairs, so runs stop cutting the plane the entry sits on).

The diagnosis below is kept because it is a good description of a real hazard
that could recur: **the block's boundary MOVES during emission while several
passes each assume it is fixed.** If an entry lane is ever unreachable again,
start there. What is stale is only the measurement.

### The original entry, as written

The largest open defect. On the trivial+small+mid corpus freeform ships **14 of
24 (URL, candidate) pairs**, and **15 of the 22 remaining errors are
`proliferator-3` entry lanes that no belt can reach**.

The proliferator entry is a single tile placed one column west of everything --
the boundary at the moment it is placed. Then the external-input runs extend the
block west past it and it is interior, walled in on four sides. Two fixes were
tried and measured:

* Routing it to the edge in the same pass as the other external inputs made it
  **worse** (11 unreachable to 17): every run targets a boundary computed before
  any of them move it, so adding a run just moves the edge again.
* Placing it after the external runs have settled the edge helps (11 to 14 pairs
  shipping, 26 errors to 22) but introduces a refusal on `graphene`/
  `max-proliferation`, because the proliferator nets now do not exist when port
  access is first staked.

That second version is what is committed, on the measurement. The underlying
problem is that the block's boundary MOVES during emission while several passes
each assume it is fixed. The fix is probably to decide the final extent up front
-- reserve the entry ring before anything routes -- rather than to re-order the
passes again.

## OPEN -- the game's own rules are scattered across three forms

The first in-game paste (2026-08-24) turned a pile of inferred rules into
extracted ones: the game is installed at `/home/dannyb/Dyson Sphere Program/`,
`Assembly-CSharp.dll` decompiles with `ilspycmd`, and `Locale/1033/base.txt`
(UTF-16LE, tab-separated) maps each Chinese condition key to the English text the
build cursor shows. That ended a long run of guessing -- but the rules landed
wherever each fix happened to need them, in three different FORMS:

* **Extracted data** -- `dsp/data/slot_poses.json`, 35 buildings of real
  `PrefabDesc.slotPoses`, produced by `scripts/extract_dsp_slot_poses.py`.
* **Derived constants** -- in `dsp/catalog.py`: the 3/4 world-to-blueprint z
  conversion, `BELT_CLIMB_PER_TILE`, `buildMaxHeight = labLevel*4 - 0.6`, the
  technology ids behind `beltVerticalConstruction`.
* **Ported predicates** -- in `layout/validate.py`: `CheckInserterDataLegal`
  (the 0.8 slot-pose radius and the slot-forward dot product) and the
  `TooSteep` slope rule.

Nothing is wrong with any of them individually. The problem is that a reader
asking "what does the game actually require?" has to know to look in three
places, and the C# provenance lives in whichever docstring the author was
writing at the time. That is exactly the condition under which somebody
re-derives a rule from the corpus and gets it wrong -- which is how we arrived
at a belt-height ceiling of 1.0 when the real answer, from the game, is
`3*labLevel - 0.45` and reaches 38.55 on a developed save.

The fix is a single module -- `flab2bp/dsp/gamerules.py` or similar -- holding
each rule next to the C# it came from: the function name, the condition in
`EBuildCondition`, and the decompiled snippet. Data files stay data files, but
the module should own the loading and be the one import a caller needs.
`catalog.py` keeps physical facts about buildings; `gamerules.py` owns what the
game will REFUSE.

Worth doing when the `game-rules` and `altitude-study` branches land, since both
touch `catalog.py` and `validate.py` and will conflict anyway -- the
consolidation is nearly free at merge time and expensive later.

**Rules still unextracted**, and each is a place the guessing could resume:
`NeedGround` ("Foundation required", still unexplained -- the game does not
offer to auto-place foundation); `TooSkew` ("Deflection too much"); and whether
a belt may cross over a building, and at what height -- deliberately left
unanswered rather than inferred from the fixtures' silence.

**And when it lands, `gamerules.py` must carry each rule's GUARD, not just its
threshold.** The belt slope rule is not `slope <= 0.8`; it is

    if (!history.beltVerticalConstruction && num25 > 0.8f)

and the guard is the whole point. `altitude-study` extracted the threshold
correctly, then applied it unconditionally, and paid 19 of 72 audit cells
against master's 2 -- every net spending two tiles per level change under a
constraint that most saves, including the user's, do not carry. Gating it on
the technology returned the audit to master's 2/0/1 exactly.

The same shape is waiting in the others: `TooSteep` has a second, tighter form
guarded by the same flag, `inserterBidirectional` and `inserterStackInput` gate
sorter behaviour, and `labLevel` gates the height ceiling. A rule recorded
without its guard reads as universal, and the cost of that mistake is not a
wrong blueprint -- it is a quietly worse one, everywhere, which is much harder
to notice.


## OPEN -- our footprints are a tile grid; the game's collision is not

The fourth and last unexplained error from the first in-game paste,
"Collide with other object" (`EBuildCondition.Collide = 34`), is ours colliding
with ourselves. It is now extracted, modelled and measured; what is NOT done is
the layout fix, which is why this entry is OPEN.

**The rule.** `BuildTool_BlueprintPaste.CheckBuildConditions` (decompiled
145712-145760) puts every preview's `PrefabDesc.buildColliders` into the live
physics world -- `ActiveColliders` -> `BuildPreviewModel.SetCollider` -- and
runs `Physics.OverlapBoxNonAlloc(collider.pos, collider.ext, ..., mask 395264)`
per preview. Mask 395264 is layers 11, 17 and **18**, and layer 18 is
"Build Preview" (confirmed from the TagManager), so previews test against each
other. An un-excused hit is `condition = EBuildCondition.Collide` at 146071.
Its guards, which narrow it a long way: a sorter is excused against anything
that is not a sorter and vice versa; a machine is excused against a belt but
**not** the reverse, because the clause tests `!A.isBelt`; belt-vs-belt is
excused only when `dotsCursor > 1`, which a single paste is not.

**Why our tile model cannot see it.** A tile is not one world unit. Rows are
`GetLatitudeRadPerGrid = 2*pi/(segment*5)` apart, and `segment` tracks the
planet radius, so the arc is `2*pi/5 = 1.2566` units on every planet. An
Assembling Machine's build collider is 3.82 units across. Three tiles is 3.770.
`catalog.derive_footprint` returns `2*ceil(box/2) - 1 = 3` for it, both
strategies duly place assemblers three tiles apart, and the game refuses every
one of those pastes. The corpus agrees and always did: across every fixture,
assemblers appear at a pitch of 4 or more and NEVER at 3, Matrix Labs at 5 or
more and never 4, Arc Smelters at 3. The extracted model reproduces each of
those minimum pitches exactly.

**Measured**, three runs, both strategies, every tier: 13 of 24 cells collide in
every run. 443 of ~530 pairs are assembler-on-assembler; the rest are a Tesla
Tower one tile from a Splitter.

**What landed:** `dsp/data/colliders.json` (252 models of real
`buildColliders`, from `scripts/extract_dsp_colliders.py`), `dsp/colliders.py`
holding the predicate next to the C# it came from, and `geom.collide` in
`layout/validate.py` -- an ERROR check, in `validate.OPT_IN` so it does not turn
every build into a refusal before the footprints are fixed.

**What is left, in order:**

1. **Fix the footprints.** The right question is not "which tile centres does
   this cover" but "how far apart must two of these be", which is
   `ceil(blueprintBoxSize / GRID_ARC)` -- and that is EVEN for an Assembling
   Machine (4). `derive_footprint`'s "always odd, as the corpus requires" is
   wrong, and `tile_to_local_offset` has a half-tile branch for even footprints
   that its own docstring calls unreachable. It is about to be reached.
2. **`blueprintBoxSize` is the wrong field for this** even after that. The game
   computes it FROM a collider (`ReadPrefab` 217456) and picks the LAST Build
   box -- which, when a prefab has three or more, is exactly the one EXCLUDED
   from `buildColliders`. Use the colliders. A Spray Coater's
   `blueprintBoxSize` is 0.7 x 2.0; the box actually tested is 0.7 x 3.5, and it
   turns with the building's yaw.
3. **Belts are still unmodelled.** They ARE tested -- as a 0.23 sphere at
   `lpos + lpos.normalized * 0.2`, and a belt hitting a machine is not excused
   -- but that model flags belts three tiles from an Interstellar Logistics
   Station in `12-s-purple-science`, which the game wrote. Something in it is
   wrong; it is left out rather than shipped. So `geom.collide` is a LOWER bound
   on what the game rejects.
4. **Sorters likewise**, and for a known reason: a sorter's box is rebuilt from
   the poses of the buildings it connects, which needs the `slotPoses` data this
   repository had wrong.

**Not a defect, and worth not re-discovering:** columns compress by `cos(lat)`
away from the paste anchor, because the longitude step is fixed at the anchor's
latitude (`RefreshBuildPreview` 179977). Two Matrix Labs five tiles apart are
clear at the equator and collide 81 rows north of it. That is why a blueprint
can paste in one place and not another, and it is a property of WHERE it lands,
not of the blueprint -- so `geom.collide` evaluates on a flat grid at
`GRID_ARC`, the loosest spacing any equatorial paste can give, and reports only
what no paste can avoid. Asking the other question is `collisions(anchor_lat=)`.
On one `information-matrix` layout the two differ by 5 pairs against 15.
