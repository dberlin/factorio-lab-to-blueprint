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

## IN PROGRESS -- emit direct insertion in both strategies

Both strategies wire up direct insertion end to end and it still does not fire.
The machinery is all present -- `spine.py` models `di[e]` and emits it,
`freeform.py` has `_direct_net_candidates`, `MU_DIRECT` in the objective, and
`_bridge` to place the sorter -- yet `docs/AB_RESULTS.md` reports
`direct_inserts` of **0 on every corpus spec but one**, where spine manages a
single insert on `magnetic-coil`. Something in the chain from candidate to
emitted sorter is silently dropping every opportunity.

Every discarded candidate becomes a belt net the router must path around when it
could be one sorter and no belt: better on both axes, fewer nets to route AND
fewer belt tiles.

It also means the bake-off currently cannot measure the axis the candidate
frontier exists to open. Proliferation forbids direct insertion on sprayed edges,
so the `free-proliferation` candidate -- which proliferates only externally-fed
recipes precisely to leave internal edges insertable -- is being compared on a
trade-off that never materialises.

Two constraints shape it:

* **Proliferation forbids it per-edge.** A sprayed input must arrive on a belt,
  because spraying is done by a belt-mounted Spray Coater. So every edge in
  `BuildSpec.belt_required_edges` is ineligible, and under the default
  `--proliferator mk3` that is nearly all of them. This is exactly why the rate
  stage emits the `free-proliferation` candidate, which proliferates only
  recipes fed from outside and leaves internal edges free to direct-insert.
* **It rigidifies placement.** A direct-inserted pair must sit within sorter
  reach (3 tiles), which the packer pays for elsewhere.

Measure against the `no-proliferator` and `free-proliferation` candidates, where
it actually bites.

## Trim lanes to their actual span

Lanes currently run the full content width, so belt *count* is high (1224-1925
buildings on the magnetic-ring spec) even though bounding-box *area* is correct.
Trimming each lane to the span it actually serves would cut building count
substantially at no area cost, and makes the emitted blueprint much pleasanter to
paste.

## Verify `tile_to_local_offset` against the game

`dsp/codec.py::tile_to_local_offset` is the single place tile space becomes DSP world
coordinates, and its centre-vs-corner rule is still an unverified guess -- the
round-trip tests replay decoded structures, so they never exercise it. The bun
cross-validation compares bounds and item histograms, which pins it indirectly. A
real paste into the game settles it.

## Confirm `TESLA_LINK_DISTANCE`

22.5 is not independently pinned: the largest tower nearest-neighbour distance in the
corpus is 11.00, which fits both 22.5-as-radius and 11.25-as-diameter (2.2% apart).
It fails visibly as a disconnected network rather than silently, but if the solver
ever spaces towers 11.25-22.5 apart, that wants an in-game check.

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

## Riser bridges climb a level per tile; the catalog says two

`catalog.RAMP_TILES_PER_LEVEL` is 2 and `BELT_CLIMB_PER_TILE` is 1/2, but
spine's `_bridge` climbs in one tile. `geom.altitude_step` permits it, so the
validator is complicit. Spending the tiles honestly costs two margin columns,
and the margin is the entire area cost of risering. Physical fidelity versus
density -- worth a decision rather than a default.

## A riser carries an item's whole cross-corridor flow on one belt

`flow.belt_capacity` passes on every corpus spec today, but there is no
lane-splitting in the riser, so a spec whose inter-row flow exceeds one belt
tier would bottleneck with no error until that check fires.

## Lane direction is approximate where a lane is filled and drained locally

A lane filled by a producer and drained by a consumer WEST of it: the consumer's
sorter sees nothing, physically. Lanes always run east with taps placed at
machine columns regardless of order. Predates risers, invisible to the
validator.

## `flow.conservation` is not junction-aware, deliberately

It reads only the spec and never touches the placement. The junction-aware
version would be a per-junction balance check, and on spine's *correct*
magnetic-ring output junction 1639 shows downstream demand 12 against upstream
supply 4 -- the supply side is under-counted because external input lanes have
no sorter pushing onto them, and seeding that means guessing how a block's
external rate divides across entry lanes. An untested WARNING that fires on
correct builds is noise.

## `belt.termination` warns too often to carry signal

12 of 25 spine runs and 13 of 17 freeform runs. Honest -- lanes are untrimmed,
which is its own backlog item above -- but at that hit rate nobody will read it.

## The hand-built `magnetic_ring_spec` fixtures are unbalanced

Both `tests/layout/test_spine.py` and `test_freeform.py` build a magnetic-ring
shaped spec by hand with round numbers, and the rates do not balance: 4
magnetic-coil/s supplying 12/s of demand, 17 items/s on a 12/s belt. Any test
asserting flow-clean on them fails for reasons that have nothing to do with
geometry. Real URL specs come from the rate solver and balance exactly.
