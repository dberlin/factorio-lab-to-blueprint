# Backlog

## OPEN -- a corridor ABOVE an inset machine costs a tile, and nothing models it

DIAGNOSED, not fixed. This is the whole of the remaining spine
`machine.inputs_supplied` failure -- ten tests, and every one of them a machine
one ingredient short.

`_allocate_lanes` already carries the right concept for the corridor BELOW a
row. Its docstring states the failure exactly: "the lane is allocated below,
`_find_tap` correctly refuses to wire something out of reach, and the machine
simply gets no sorter for that item at all". A short machine in a tall row stops
above the row's floor, so every lane below it is that gap further away, and
`above_gap` / `_fits_below` order and cap the band to match.

The same thing happens on the corridor ABOVE, for a different reason, and the
model says that side "costs it nothing". A Chemical Plant's poses on that face
sit a row INSIDE its five-deep footprint, so a sorter reaching one is a tile
longer than the gap suggests. Measured, usable lane depths per corridor:

    Chemical Plant, Quantum Chemical Plant    above 2    below 3
    Assembler, Oil Refinery, Matrix Lab       above 3    below 3

The model assumes 3 and 3 for everything. Every rejected tap in the failing
specs was on the `above` side at a gap of 3 or more -- the third depth a plant
cannot reach -- and `_find_taps` correctly refused each one after the allocator
had already put the item there.

Note the asymmetry, because it is why the first attempt missed. `_Group.tap_height`
folds the inset into the gap model as if it applied to both sides, and it changed
none of the ten failures: the gap thresholds are not the per-corridor DEPTH cap,
and taking the worse side for both is not what the geometry says.

THE ALLOCATOR-ONLY FIX WAS BUILT AND IT MADE THINGS WORSE. Mirroring `above_gap`
exactly -- a `below_inset`, the same `_fits_below` greedy with the inset in place
of the gap, the band ordered worst-inset-first, and then the mirror of
`gap_first` so an inset item prefers the side without one -- took spine from 10
failures to 12. `graphene` regressed: a Chemical Plant running sulfuric-acid
still ends one ingredient short, now because the allocator correctly refuses to
seat a third item upward and cannot find room downward either.

That result is worth more than the change was. It says the constraint is real and
the allocator is not where it can be satisfied: if a row's plant can take only
two lanes upward and its ingredients want three, no seating order fixes it --
the ROW is wrong, and the row is chosen by CP-SAT. So the asymmetric per-side cap
has to reach the tap-capacity model, which is what decides that a plant may share
a row at all.

The bound I checked earlier and dismissed was the wrong one: a group's TOTAL lane
need (4) against its total reach (2 + 3 = 5) is not binding, but its need on ONE
SIDE against that side's cap is. A row of items that all prefer upward puts three
against a cap of two, and nothing downstream can undo it.

Do not attempt the allocator half again on its own; it is measured, reverted, and
recorded here precisely so the next attempt starts at the model.

## OPEN -- spine grows elevated lanes

Spine refuses every proliferated spec, and the refusal names why: a Spray Coater
is supplied by a BELT in its addon area, which the prefab puts at
`(0, -1.25, 1)` -- a tile and a quarter behind the coater and exactly one
altitude LEVEL up. So the supply has to be an elevated lane in the coater's OWN
row, and spine runs lanes at ground level in a corridor. Freeform builds it, the
pipeline runs both, so no user-visible capability is lost.

What was found while trying: the drop belt must be fed by the proliferator
lane's TAIL, not by any adjacent tile. Taking a mid-lane tile's output orphans
everything downstream of it -- the lane stops there and its remaining sorters
draw from a belt nothing fills, which reports as
`flow.external_entry_reachable` rather than as anything about coaters.

Freeform's out-lanes start immediately below the machine FOOTPRINT, which puts
them inside the row a machine's collider needs; a junction on such a lane is
illegal, and `junction.site_is_clear` refuses it. Moving lane rows to start
after the clearance band is the obvious fix and is NOT the way in -- it took
freeform from 9 test failures to 80, because the strip's row indices are
consumed in several places that each assume lanes start at `mh`. Whatever fixes
this has to change those together.

## OPEN -- two collider questions left, both deliberately unanswered

`geom.collide` is a normal check now: 443 assembler-on-assembler pairs became 2,
and turning it on cost no coverage. The two that remain are both real and
neither is guessable from where we stand.

**A Chemical Plant is packed too LOOSE.** Its collider needs 7x5 where
`derive_footprint` says 9x5, so there is density to win back --
`catalog.clearance` clamps to at least the footprint and leaves it. Taking it
means trusting the collider over `blueprintBoxSize` for tile OCCUPANCY, not just
for spacing, and those are different questions: occupancy decides which tiles a
sorter anchor may sit on and where a belt may run, and the slot poses are the
authority there rather than either box. Settling it needs the same treatment
spacing got -- a measurement against real blueprints -- not an inference from
the collider being smaller.

**A Splitter one tile from a Tesla Tower collides**, and so does an elevated
Splitter diagonally over an Assembling Machine. The first is a plain pitch
requirement: a splitter is a CROSS of two boxes reaching 1.19 units from its
centre, a tower reaches 0.3, and 1.19 + 0.3 is more than one tile of 1.2566. The
second is not about splitters at all -- it is a belt at level 1 passing over a
machine 5 tiles tall, which is the "may a belt cross a building, and at what
height" question this file already records as unextracted. Both are refusals
today rather than shipped defects, which is the right place for them until the
crossing rule is read out of the game rather than inferred.

Note also that `catalog.clearance` takes an AABB over every collider box, so a
cross-shaped building like the Splitter reserves its empty corners too.
`geom.collide` tests the real boxes and knows better; the clearance is the
conservative one, and where the two disagree it is the clearance that
over-reserves.

## OPEN -- the layout obeys the slot tables now; what it cannot serve is geometry

The game's own predicates are ported (`game.inserter_data`,
`game.inserter_paste`, `game.inserter_skew`, `game.addon_supply` in
`layout/validate.py`), the real `PrefabDesc.slotPoses` and `addonAreaPoses`
tables are extracted from the game's prefabs
(`scripts/extract_dsp_slot_poses.py` -> `dsp/data/slot_poses.json`), and both
strategies now choose a sorter's machine-side anchor from those tables via
`slots.attachment`. **Every placement either serves a machine where the game
has a pose, or does not serve it: zero `game.*` findings on everything that
lays out.**

The cost is coverage, not density. Paired and interleaved over the cells both
arms lay out, constraining the anchor moved total area by **-0.28%** (6494 vs
6512); the 3x3-machine cells are identical to the tile, because for a 3x3 the
table says exactly what the old edge-row assumption said.

WHAT STILL CANNOT BE LAID OUT, AND WHY

`attachable_columns` for a lane one row clear of the machine, both sides:

| building | footprint | from above | from below |
| --- | --- | --- | --- |
| Assembling Machine, Smelter, Depot | 3x3 | 0,1,2 | 0,1,2 |
| Matrix Lab | 5x5 | 1,2,3 | 1,2,3 |
| Chemical Plant, Quantum Chemical Plant | 9x5 | 3,4,5,6 | 3,4,5,6 |
| Miniature Particle Collider | 9x5 | 1,2,3 | 1,2,3 |
| **Oil Refinery** | 3x7 | **none** | 0,1,2 |
| Ray Receiver, Energy Exchanger, Spray Coater | -- | **none** | **none** |

Three structural consequences, each a packer problem rather than a validator
one:

1. **An Oil Refinery cannot be served from the north.** Its nine poses are
   0-2 east, 3-5 west, 6-8 on the south face; there is no pose on the north
   face to be near. A layout that runs its lanes east-west can only feed a
   Refinery from below. The fix is either to rotate it a quarter turn -- at
   yaw 90 its east and west faces become north and south, and its 3x7 becomes
   a 7x3 that suits a row band better -- or to route both of its connections
   from the same side. Neither strategy can rotate a machine today.
2. **A wide machine offers fewer columns than its width**, so fewer parallel
   sorters fit. `_pick_sorter` is now sized against the attachable count rather
   than the footprint width, which buys back capacity by raising the tier, but
   a Chemical Plant still tops out at four sorters per lane.
3. **A Chemical Plant's southern anchor is a row INSIDE its footprint**, so the
   sorter is two tiles long before anything else -- and a lane three tiles clear
   of it is already past `SORTER_MAX_REACH`. Wide machines must be packed
   CLOSER to their lanes than 3x3s, not further.

**51 tests in `test_spine.py` and `test_freeform.py` fail**, all of the form
"this spec lays out and validates clean" for a spec containing an Oil Refinery,
a Chemical Plant or a Spray Coater. They are the diagnosis, not the disease; the
failure mode is `machine.inputs_supplied` / `machine.output_removed` /
`flow.sorter_capacity`, never an invalid blueprint. The audit holds **INVALID 0
and crashed 0** across three runs (tier `small`, budget 4s: 8/30 clean, 22
refused, identical all three times).

### Spray Coaters are belt-fed, and the belt goes one level UP

Both strategies used to run a sorter into a coater. That connection does not
exist: a coater ships zero insert poses, `BuildTool_Inserter` refuses to target
a building with none, and all eight coaters in the corpus carry no connection at
all -- `input_obj` and `output_obj` unset, `(15, 14)` in their four slot fields.
The game attaches an addon's belts positionally, from
`PrefabDesc.addonAreaPoses`, and for a coater area 1 -- the proliferator supply
-- is at `(0, -1.25, 1)`: a tile and a quarter behind it and **exactly one
altitude level up**. The corpus confirms it: every coater there has a belt one
level above and one tile to the side.

So proliferation needs an ELEVATED proliferator lane whose tiles land in each
coater's addon area. Neither strategy can route one, so `game.addon_supply`
reports the coater unsupplied and every proliferated candidate refuses. That is
a real capability loss and it is the right one: the sorter it replaces looked
like a feed and was not one, and nothing could see that because a coater has no
`slotPoses` for `CheckInserterDataLegal` to check.

## OPEN -- the game's own rules are scattered across three forms
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

*The consolidation item below is the same concern seen from the other side: the
rules above now live in a data file, a catalog dataclass, four validator checks
and a layout primitive, and the argument for one module is stronger for it.*

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
whether a belt may cross over a building, and at what height -- deliberately
left unanswered rather than inferred from the fixtures' silence.

Two that were on this list are now answered, and both are recorded in
`layout/validate.py`'s comments rather than as checks, because neither can be
one:

* **`NeedGround`** ("Foundation required") is not a property of a blueprint at
  all. In `BuildTool_BlueprintPaste` it is a terrain raycast per `landPoint`:
  18 m down, refused when the hit is below `-0.3 - landOffset` of the planet
  radius, or when the ground and water layers differ by more than
  `0.27 + landOffset`, or when nothing is hit. The same blueprint pastes one
  tile away. It does not offer to auto-foundation because reform is a separate
  opt-in pass (`ComputeReform`). No offline check can predict it; levelling the
  ground answers it.
* **`TooSkew`** ("Deflection too much", `偏角太大`, condition 15 -- NOT
  `TooBend`/`弯曲过度`) is ported as `game.inserter_skew`. It reads the
  blueprint's own anchors and yaws, not the snapped ones: 30 degrees between the
  two end rotations, 24 degrees between each end's forward and the line the
  sorter runs along, plus a length window that varies with how many ends are on
  a belt. On an integer grid the window cannot bind -- its loosest floor is 0.9
  and the shortest sorter is 1.0.

A third is worth recording because it was got WRONG first and the corpus caught
it: the skew ladder does **not** run on the snapped positions. Reading it that
way rejects 11 Oil Refinery sorters in `factory-quick-start-step-3-red-cube`, a
blueprint the game ships. It also means a backwards sorter yaw is not rejected
by anything ported here -- the yaw is derived from the geometry because 1250 of
1250 real sorters agree on it, not because a predicate refuses the alternative.

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
