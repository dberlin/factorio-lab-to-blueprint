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

## Original analysis (superseded, kept for the record)

## Speed up the layout solver

**The problem.** The layout stage is by far the slowest thing in the project. With
`dsp` + `lab` + `rates` running in 2.7s, `tests/layout` alone took ~96s, and that is
with tests already passing deliberately small budgets. Tests were rescued by cutting
their budgets to 0.3-0.5s and running under `pytest-xdist`, but that treats the
symptom: the solver itself is slow enough that a realistic budget dominates any loop
it sits in — tests, the bake-off, and eventually the CLI.

**Why it matters beyond tests.** The bake-off runs (URL x candidate x strategy x
power) cells. With 12 URLs, 3 candidates, 2 strategies and 2 power settings that is
144 solves per run. At even 5s each that is 12 minutes for one comparison, which
makes the density experiment painful to iterate on — and iterating on it is the whole
point of building two strategies.

**Where to look, roughly in expected-payoff order.**

1. **Profile before optimising.** Nobody has actually measured where the time goes.
   It may be model *construction* rather than solving — building tens of thousands of
   CP-SAT constraints in Python is not free, and `spine.py` reports ~900 vars for a
   58-machine spec, which should not take seconds to solve. Measure the split between
   build time and solve time first; the answer changes everything below.
2. **Cache the model across candidates.** The rate stage emits several `BuildSpec`
   candidates that differ only in proliferation. Much of the geometry model is
   identical between them. If construction dominates, building once and re-solving
   with changed constraints is a large win.
3. **Warm-start more aggressively.** `spine.py` already does `AddHint` from the
   fallback. Feeding the previous candidate's solution as a hint should help further,
   since candidates are near-neighbours.
4. **Tighten the descending-width sweep.** It currently tries several widths; a
   better initial bound (from the fallback's area, or an area lower bound of
   `sum(machine tiles)`) would prune most of them.
5. **Revisit `num_search_workers`.** Pinned to 1 for bake-off determinism, which is
   correct there — but the CLI has no such constraint and could use all cores.
6. **Reconsider the freeform repair loop.** Strategy B's rip-up-and-reroute has a
   hard iteration cap; if it routinely runs to the cap, that is pure wasted time and
   the routability proxy needs strengthening instead.

**Acceptance.** A realistic single layout solve should be well under a second, and
the default `pytest` run should stay under ~30s wall-clock without relying on
artificially tiny budgets to hide the cost.

## IN PROGRESS -- emit direct insertion in both strategies

Both strategies identify direct-insertion opportunities and then discard them.
`spine.py` models `di[e]` but emission ignores it. `freeform.py` finds **11
candidates** on the magnetic-ring spec, hardcodes `stats["direct_inserts"] = 0.0`,
and passes `direct_pairs` into `_pack` where it is never referenced -- so
`MU_DIRECT = 4` rewards nothing at all.

Every discarded candidate becomes a belt net the router must path around, when it
could be a single sorter and no belt. That is better on both axes: fewer nets to
route (faster) and no belt tiles for that edge (denser -- currently 799 belt tiles
on that spec).

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

## BLOCKING -- neither strategy can serve two destinations from one belt

Found by deleting the fallback. Both strategies hit the same missing primitive,
from opposite directions, and both used to hide it by emitting something.

**Freeform.** A belt tile has one `output_obj`. When several nets leave the same
lane end -- an iron-ingot strip feeding both the gear strip and the motor strip
-- each rewrote that tile to point at its own path and the last to commit won.
The earlier paths stayed on the grid as belts nothing fed: real buildings, real
area, no items. The validator graded them a WARNING about wasted belts, because
the machines drawing from them usually had some other source, so this never
surfaced as an error. `_commit_paths` now counts them as routing failures, which
makes freeform refuse `fan_out_spec`, `graphene`, `electromagnetic-matrix` and
the magnetic-ring corpus spec. Those refusals are correct: nothing was feeding
most of each build. Pinned by
`test_a_producer_feeding_two_consumers_is_refused`, which is written to FAIL
when the gap closes.

**Spine.** The module docstring claims an item spanning non-adjacent rows "takes
a lane in every corridor between, which is correct and routable". It is not
routable: the copies are never joined. Evidence on the magnetic-ring spec --
`copper-ingot` is produced in row 0, whose output sorters fill corridor 1, and
consumed in row 2, whose sorters drain corridor 2. Every `_find_tap` and
`_pick_sorter` call succeeds; the sorters exist and point at the wrong copy.
This is the sole cause of all 11 `flow.lane_sourced` errors.

Joining them needs trunk risers, and risers at a single altitude provably
collide on real specs: `iron-ingot` spans corridors 1-3 and `magnet` spans 2-5,
which properly cross, so no column ordering avoids it. A riser column must also
sit outside the horizontal extent of every lane it crosses, which is why
allocation ORDER matters -- a riser has to be placed after the lanes it crosses
have theirs.

Both are the same shape: a belt that fans out. The answer to both is the
**splitter**, catalog id 2020, already in `BELT_INTEGRATED_IDS` and known to the
encoder (25/25 in the fixture corpus, all on integer offsets), just never
emitted. Spine additionally needs the riser geometry; vertical belt stacking is
sanctioned and `LEVELS`/ramp costs are already modelled in freeform's A*.

Until this lands the tool refuses most real URLs, which is the honest state and
strictly better than the previous one -- it used to emit them, and they did not
run.

## Validator gaps this exposed

* An external input entering corridor 0 does not fill its copies in corridors
  1..n, but `flow.lane_sourced` excuses any run carrying an external item. On
  magnetic-ring, `iron-ore` is consumed in rows 0 and 1 and only row 0's lane is
  actually fed. The exemption should apply to the run the input ENTERS on, not
  to every run carrying that item.
* An orphaned belt run whose consumers happen to have another source is graded a
  WARNING. That is right for a genuinely redundant lane and wrong for the
  freeform fan-out case above, where the "other source" was the one net that won
  the race for the lane end.
