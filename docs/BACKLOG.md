# Backlog

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

## OPEN -- freeform cannot supply proliferator to its coaters reliably

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
