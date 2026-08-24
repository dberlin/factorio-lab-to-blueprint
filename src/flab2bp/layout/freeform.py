"""Strategy B -- free-form packing plus belt routing.

Where Strategy A commits to a global skeleton, this places its units anywhere a
2D packer can fit them and then *routes* the belts through whatever space is
left.  The density ceiling is higher because nothing is reserved in advance; the
risk is the classic place-then-route failure, where phase 1 optimises a proxy
that knows nothing about routing and hands phase 2 a placement it cannot wire.

Three things keep that risk bounded:

* **A strip is routable on its own.**  The placeable unit is not a bare machine
  but a *strip*: a run of machines of one recipe, with its input lanes already
  attached above and its output lanes below, each within sorter reach.  Phase 1
  therefore cannot produce a machine that is impossible to feed -- only one that
  is awkward to reach.
* **A reserved margin** on each strip's east and south faces guarantees a
  connected mesh of free cells for the router, rather than a legal-but-choked
  pack.
* **Negotiated congestion** (PathFinder-style rip-up-and-reroute) resolves the
  contention that remains, and a hard iteration cap plus a guaranteed-feasible
  fallback mean ``lay_out`` always returns something valid.

Deliberate simplifications, each with its reason:

* **No splitters.**  A strip gets one output lane *per destination strip*, so
  every net has exactly one source and one sink.  Belts merge natively in DSP
  (two chains pointing at one tile), so many-to-one needs nothing; giving each
  destination its own lane removes the one-to-many case entirely.  The cost is
  extra lanes, bounded by sorter reach at three per side.
* **Level changes cost two tiles.**  Belts climb 0.5 per tile, so one integer
  level is two tiles of run.  The router reserves both.

Where this differs from the written spec, and why
-------------------------------------------------
The spec's §2.3 chose I/O pads with a solver-chosen face.  This implements the
fixed east/south margin instead: it is the same structural guarantee -- every
unit has free cells adjacent to it -- without a face variable per unit, and the
lanes that pads were meant to reach are already part of the strip.

The spec's §5.3 made the tower lattice a fixed blockage set inside phase 1.  That
encoding fights the objective: the lattice extent depends on the final width,
which is the variable being minimised, so fixing it either inflates the bounding
box or under-covers the result.  Towers are therefore placed after packing, into
the margin cells the packing already reserved, and then *verified* -- coverage
and connectivity are both repaired greedily until they hold.  The guarantee is
the same; only the mechanism is post-hoc.
"""

from __future__ import annotations

import heapq
import math
import time
from collections import defaultdict, deque
from collections.abc import Collection, Mapping, Sequence, Set
from dataclasses import dataclass, field, replace
from fractions import Fraction
from functools import lru_cache

from ortools.sat.python import cp_model

from flab2bp.dsp import catalog, params
from flab2bp.layout import junction, validate
from flab2bp.layout.base import (
    DEFAULT_SEARCH_WORKERS,
    RETRY_BUDGET_S,
    Facing,
    NoValidLayout,
    PlacedBuilding,
    Placement,
)
from flab2bp.layout.spine import BELT_ITEM_IDS, MACHINE_ITEM_IDS, SORTER_TIERS
from flab2bp.spec import BuildSpec

#: Free tiles reserved on a strip's east and south faces.  One is enough for a
#: belt to pass; the router uses upper levels when one is not.
MARGIN = 1

#: Free tiles reserved on a strip's WEST face -- a routing channel the model
#: pays for, rather than a corridor the router hopes to find.
#:
#: THIS IS THE ROUTABILITY CONSTRAINT.  Every net starts at an output lane's
#: EAST end and finishes at an input lane's WEST head (see ``_emit_strip``), and
#: both of those tiles are walled in on three sides by their own strip: a lane's
#: neighbours above and below are the next lane or the machine band, and the
#: fourth neighbour is the lane itself.  A port therefore has exactly ONE way in
#: or out, the tile on its own strip's east or west face, and
#: ``_reserve_port_access`` holds precisely that tile.
#:
#: With a margin on the east face alone, a strip's east margin column IS the
#: column its eastern neighbour's input heads open onto -- one channel serving
#: two faces.  ``add_no_overlap_2d`` is satisfied, the pack is legal and tight,
#: and two ports fight over one cell; the loser is handed an EMPTY start or goal
#: set and A* returns ``None`` having expanded nothing.  That is not congestion
#: and no amount of rip-up can price it away, which is why more solver time made
#: this WORSE: a tighter pack is a pack with more faces pressed together.
#:
#: Measured before this existed, with every unserved port's four neighbours
#: classified: on ``casimir-crystal/no-proliferator`` three ports were boxed in,
#: each by two lane belts, one machine and -- on the one open side -- a cell
#: another port had already claimed.  Every one of them was the shared-column
#: collision.
#:
#: One column, not two: one is what makes the two faces' access cells DISJOINT,
#: which is the whole property.  It costs one tile of width per column of the
#: pack, and it is the cheapest form of "reserve the channel in the model" that
#: the ports actually need.
WEST_CHANNEL = 1

# A SECOND ROW on the south face was tried here and is not worth having.
#
# The reasoning was symmetric to `WEST_CHANNEL`: the corridor between two
# vertically adjacent strips is one row tall, a strip's machine band blocks every
# level, so that row is the only east-west way past a strip and one belt fills
# it.  Widening it to two measured WORSE -- 59/72 clean at 4s against 60/72 --
# because a row costs height on every strip in the pack, the canvas grows, A*
# slows, and the sweep reaches fewer candidate heights inside the same deadline.
# The channel it buys is not free and the heights it costs were paying more.
#
# The west channel is not the same trade and that is the point: it makes two
# ports' access cells DISJOINT, which is a property the router cannot recover by
# searching harder.  A wider corridor only makes an existing search easier.

#: Levels available to the router.  Ground plus two stacked crossing levels,
#: matching what the corpus shows real blueprints using.
LEVELS = catalog.MAX_BELT_STACK_LEVELS

#: Rip-up-and-reroute iterations before a placement is declared unroutable.
RRR_MAX = 8

#: Rip-up rounds with no improvement in the failure count before giving up.
#:
#: Three, not one: pressure grows geometrically (``0.5 * 1.6**it``), so a round
#: that buys nothing at low pressure can still break a deadlock two rounds
#: later. Measured on the magnetic-ring chain, where routing a pack that cannot
#: be wired was the strategy's single largest cost.
_RRR_STALE_ROUNDS = 3

#: Outer repair iterations before falling back.
OUTER_MAX = 3

#: Objective weights.  ``λ`` pulls connected strips together (this is what makes
#: routing tractable); ``μ`` rewards a direct insert, which deletes a whole net.
LAMBDA_HPWL = 1
MU_DIRECT = 4

#: How much of a sweep's clock CP-SAT may have, the rest belonging to the
#: router.  See :meth:`FreeformLayout._sweep`, which is where the measurement
#: that sets it is written down.
_PACK_SHARE = 0.35

#: What a repair search pays, per cell, to cross a belt that is already down.
#:
#: High enough that crossing is a last resort and low enough that it stays
#: possible: a path of a hundred free cells costs about a hundred, so one
#: crossed cell outweighs half a detour of that size.  See
#: :func:`_route_all`'s repair pass.
_REPAIR_CROSSING = 60.0

#: How many settled paths one stranded net may displace before the repair
#: declines the trade.  Measured across five `universe-matrix` packs, every one
#: of 31 stranded nets crossed between 1 and 11 paths, so this refuses only the
#: cases the census never produced -- where re-routing the victims would cost
#: more than the round it is replacing.
_REPAIR_MAX_VICTIMS = 16

#: Repair sweeps per rip-up round.  Each is cheap (a crossing search is
#: 0.001-0.025s against 3.1-4.0s for a round), and a displaced net that strands
#: in turn is worth trying to place the same way -- but a pack where that keeps
#: happening is one negotiation should price rather than one repair should churn.
_REPAIR_PASSES = 4

#: Above this many goals, the A* heuristic switches from exact
#: distance-to-nearest-goal to distance-to-goal-bounding-box.  Both are
#: admissible; the box is weaker but O(1) instead of O(|goals|) per node.
_EXACT_HEURISTIC_GOALS = 64

#: INFLATING THAT HEURISTIC WAS TRIED AND IS WORSE.  Kept because the diagnosis
#: under it is right and only the remedy was wrong.
#:
#: The observation: the heuristic charges 1.0 per step, the cheapest an edge can
#: be, while a negotiating step costs ``1 + level_toll + history * pressure``
#: with ``pressure = 0.5 * 1.6**round``, so by the fifth round a contested cell
#: costs four to twenty times what the heuristic assumes.  Expansions per net
#: per round on `universe-matrix` climb accordingly, with micro-seconds per
#: expansion FLAT at 4-6 across every round -- the search loses its guide, the
#: loop does not get slower:
#:
#:   no-proliferator h=69 power=1   5295 -> 5344 -> 8315 -> 12507 -> 15078
#:   no-proliferator h=69 power=0   3424 -> 3841 -> 6901 -> 7951
#:   max-proliferation h=72 power=1 1365 -> 1688 -> 2413 -> 3742
#:
#: The remedy that does not work is multiplying the heuristic by a constant.  An
#: inflated heuristic is INCONSISTENT, and this search re-opens a settled cell
#: whenever a cheaper way to it turns up, so the re-expansions cost more than
#: the guidance saves.  Measured on a fixed pack (deterministic CP-SAT, so the
#: only difference is the weight), 30 height-cells at each weight:
#:
#:   weight 1.0 -- 12 of 30 wired, round times 2.5/3.6/5.3/6.1s
#:   weight 1.5 --  3 of 30 wired, round times 2.8/4.4/12.6s, expansions UP
#:   weight 2.5 --  3 of 30 wired, round times 2.5/6.7/3.9/9.9s, expansions UP
#:
#: The real gap is not the scale of the estimate, it is that Manhattan cannot
#: see an obstacle: measured `exp/pathlen` is 50.7 median (p90 127) on
#: no-proliferator h=69 and 77.5 median on h=185, with `_MAX_EXPANSIONS` never
#: reached.  An 85-cell path costs 4322 expansions because A* settles every cell
#: whose Manhattan estimate is under the true detour.  That wants a heuristic
#: that knows where the machines are, not a bigger multiplier.  See
#: :data:`_ALT_LANDMARKS`.

#: Landmarks for the DIFFERENTIAL heuristic, which is what does know where the
#: machines are.  Zero falls back to plain Manhattan.
#:
#: For a landmark ``L`` with known distances to every cell, the triangle
#: inequality gives ``d(n, g) >= |d(L, n) - d(L, g)|`` -- a lower bound that
#: costs two array reads and is large exactly where Manhattan is worst, because
#: a wall between ``n`` and ``g`` moves them apart on some landmark's dial even
#: though their coordinates are close.  Taking the max over several landmarks
#: and over Manhattan keeps it admissible and can only tighten it.
#:
#: THE DISTANCES ARE ON THE 2D PROJECTION of the canvas, where a column is
#: passable if any of its levels is, and they count STEPS rather than cost.
#: That is what makes them a valid bound on a 3D search with ramps: a plain step
#: moves one column and costs at least 1.0, a ramp moves two columns and costs
#: 3.0, so cost is never below the number of columns crossed, and the projection
#: is more permissive than any single level.  They are built from ``base`` --
#: the occupancy before any path commits, with port reservations still open --
#: so committing paths can only make the true distance longer, never shorter,
#: and one build serves every round of the pass.
#:
#: Four, from farthest-point selection.  Each is one breadth-first sweep of the
#: projection, ~26k columns on a `universe-matrix` canvas, and the whole build
#: is paid ONCE per routing pass against the tens of seconds the pass costs.
_ALT_LANDMARKS = 4

#: Hard cap on A* node expansions for a single net.  Exceeding it returns
#: ``None``, which the caller already treats as a route failure and handles by
#: ripping up and retrying -- so this degrades routing quality rather than
#: correctness.  Without it a hard net explores every reachable cell x level and
#: the whole layout appears to hang.
_MAX_EXPANSIONS = 200_000

#: Total A* expansions across ALL nets and ALL rip-up rounds of one routing
#: pass.  `_MAX_EXPANSIONS` bounds a single search; this bounds their product,
#: which is what actually runs away at scale.
_ROUTING_BUDGET = 2_000_000

#: Expansions the whole `lay_out` call may spend, per second of its ceiling.
#:
#: A BACKSTOP, not the binding constraint -- the wall clock is what bounds the
#: call, and this exists so a re-run at the same budget explores the same
#: number of nodes rather than however many the machine happened to manage.
#:
#: Sized well above what the clock can actually spend, and that margin is not
#: slack, it is the whole point.  One shared `_ROUTING_BUDGET` was tried and it
#: measured four cells WORSE: A* had just got 2.1x faster, so 2M expansions went
#: from more than a 15s ceiling could reach to less, the second candidate height
#: exhausted it, and every height after that got nothing.  A budget that binds
#: before the clock does not bound the runaway the clock already bounds; it just
#: silently deletes the back half of the sweep.  Four hundred thousand a second
#: is roughly two and a half times the measured 155k/sec.
_ROUTING_EXPANSIONS_PER_SECOND = 400_000

#: Toll a path pays per tile for occupying GROUND LEVEL.
#:
#: Only machines are solid at every altitude, so a belt at z=0 leaves z=1 and
#: z=2 open above it -- but a plain step costs 1 and a ramp costs 3, so A* has
#: no reason to climb and never does unless it is blocked.  The whole block
#: therefore wires on one plane, and a route that crosses it CUTS that plane:
#: ramping over a belt needs two free tiles of run on each side, and a dense
#: pack has not got them.  Measured on ``universe-matrix`` at h=92, where 36% of
#: every failed search's wall was another net's committed path and the largest
#: sealed pocket held 35,105 cells -- half the canvas, walled off by belts.
#:
#: A toll on ground level makes altitude worth buying for THROUGH traffic while
#: leaving it unattractive for short hops.  A run of length L pays L*(1+t) on
#: the ground against roughly L+6 in the air, so it climbs once L exceeds 6/t
#: and not before -- which is the trade wanted, because ports are on the ground
#: and must stay reachable across it.
#:
#: The heuristic stays admissible: every step still costs AT LEAST one, so
#: Manhattan distance is still a lower bound.
_GROUND_TOLL = 0.25

#: Per-level step surcharge, indexed by altitude.  Built once; the inner loop
#: indexes it rather than branching.
_LEVEL_TOLL = tuple(_GROUND_TOLL if lvl == 0 else 0.0 for lvl in range(LEVELS))

#: Owner recorded in :attr:`_Canvas.blocked` for a path laid THIS rip-up round
#: and not yet committed.  It was the bare ``-2`` in four places, one of which
#: is now a hot-loop comparison, so it is named once.
_TENTATIVE = -2

#: Largest reachable region a failed search will census for a wall.
#:
#: The census is four dict lookups per settled cell, so it wants a bound -- but
#: the bound is cheap insurance rather than the thing that makes this
#: affordable.  Running the census with the CHARGE set to zero, so it pays the
#: full cost and changes no decision, measures 66/65/65 clean over the corpus
#: against 65/66/65 with the census switched off entirely.  The walk is free;
#: what costs is what you do with it.
_BLAME_MAX_POCKET = 32_768

#: Largest WALL a failed search will charge anybody for.
#:
#: THIS is what makes the surcharge shippable, and the reasoning is about guilt
#: rather than about time.  A search that dies in a pocket walled by three cells
#: has named three suspects; one of them really did cut this net off.  A search
#: that dies in a pocket walled by three thousand has named no one -- it is
#: describing the whole corridor network, and charging all of it just makes
#: every route longer.
#:
#: Measured, and the split is clean.  Charging every wall regardless of size
#: gives 62-66 clean over thirteen runs, mean 65.0, against 65-66 over nine runs
#: with no surcharge at all: the occasional four-cell loss is a round where
#: diffuse blame sent half the block on a detour and the sweep ran out of clock.
#: Capping it gives 64-66, mean 65.4, while keeping the whole of the gain --
#: `universe-matrix/no-proliferator` at h=69 commits 139 of its 140 paths
#: without the surcharge and ALL 140 with it, capped or not, and routes in 24.6s
#: instead of 36.7s.  The diffuse walls contributed nothing but variance.
#:
#: The capped-versus-off comparison is INTERLEAVED, alternating the two settings
#: run by run rather than measuring one block then the other, because
#: `validate.py` was being edited in the tree at the time and `_sweep` calls
#: `validate.certify` inside its own clock -- a faster validator leaves more
#: seconds for routing and would have looked like a routing result.  Six pairs,
#: with the validator's mtime checked either side to confirm it held still: off
#: 66/64/65/66/65/65, mean 65.2; on 66/65/65/65/65/66, mean 65.3.  INVALID 0 in
#: all twelve.  This buys the h=69 pack and costs nothing, which is the whole
#: case for it -- it is not a corpus win and should not be sold as one.
_BLAME_MAX_WALL = 64

#: What a wall cell costs, in units of the plain per-round history point.
#:
#: The plain term charges one point for having been used at all, which after a
#: few rounds of the geometric pressure ramp is worth a couple of tiles of
#: detour.  A cell that cut the board in two has to be worth more than that or
#: the net holding it simply keeps it.  Forty is where the h=69 pack tips:
#: weights 0 and 12 leave one net with no path at all and 40 leaves none, and 80
#: buys nothing further.
_BLAME_WEIGHT = 40.0

#: A* expansions between wall-clock checks.
#:
#: ``time.monotonic()`` costs about as much as an expansion, so calling it on
#: every one would be a measurable tax on the hot loop for a deadline that is
#: seconds away.  Four thousand expansions is a few milliseconds of overshoot at
#: the rates measured here (~180k expansions/second), which is nothing against a
#: 15-second wall and cheap enough to disappear.
_DEADLINE_CHECK_EVERY = 4096

#: Rings of ground reserved around the packed block, decided BEFORE anything
#: routes.
#:
#: The block's boundary used to MOVE during emission while several passes each
#: assumed it was fixed: the external input runs computed the edge, ran out to
#: it and thereby moved it; the router was then free to lay belts two tiles
#: beyond that, wrapping the runs that had just defined it; the proliferator
#: entry was placed one tile west of whatever the edge happened to be at that
#: moment.  Every entry lane the validator reported as walled in was a tile that
#: had been on the boundary when it was placed and interior by the time the
#: placement was finished.
#:
#: Fixing the extent up front removes the whole class.  ``_ENTRY_RING`` is the
#: outermost ring anything may occupy, and only external entry belts -- the
#: input runs and the proliferator entry -- are ever placed there.  Everything
#: else, the router and the power lattice included, is confined to
#: ``_ROUTE_RING`` by :attr:`_Canvas.limit`.  The ring one beyond
#: ``_ENTRY_RING`` is therefore empty by construction, which is exactly the
#: precondition ``flow.external_entry_reachable`` flood-fills for: a belt
#: sitting on the outermost occupied ring always has open ground on its outward
#: side.
#:
#: Two rings for the router rather than one: that is what it had before on the
#: west and north faces, so the fix costs it no freedom there.
_ROUTE_RING = 2
_ENTRY_RING = _ROUTE_RING + 1

# THERE IS NO FALLBACK PACKING HERE, AND THERE MUST NOT BE ONE.
#
# This has now been built and deleted TWICE: once as `fallback_placement`
# reachable from `lay_out`, and once as `_loose_sweep`, a shelf packing at
# progressively wider margins tried after every solved pack failed to wire.
# The second came with a self-check -- it only returned placements that had
# routed with every net connected -- and the self-check is exactly what made it
# look defensible. It is not.
#
# A check proves the fallback's output is not broken. It says nothing about why
# the solved path had nothing to hand back, and that is the only question worth
# asking: a spec that reaches a fallback has a PACKER PRODUCING PACKS ITS OWN
# ROUTER CANNOT WIRE. Emitting the shelf packing makes that defect invisible --
# the cell goes green, the audit says CLEAN, and nobody looks again.
#
# And it is paid for in the one currency this program exists to minimise.
# Measured on `casimir-crystal/no-proliferator`: solved packs of 4960-6120 tiles
# that did not route, against a shelf packing of 8786-11628 that did. Buying a
# green cell at twice the area is not a rescue, it is the failure being paid for
# in density. Spine measured the same shape, 50,512 tiles against ~39,000.
#
# An unwireable pack is a REFUSAL. If that number is worse, it is the true
# number, and the fix belongs in the PACKER -- routability as a constraint the
# model respects, not a post-hoc test with a rescue behind it.

#: Tower lattice spacing.  A square lattice of spacing ``d`` leaves a worst-case
#: distance of ``d/sqrt(2)`` to the nearest lattice point, so ``d`` must satisfy
#: ``d <= R*sqrt(2)``.
#:
#: Nine, not the twelve the bare covering argument allows.  A lattice point
#: routinely lands on a machine, and ``nearest_free`` then places the tower up
#: to FOUR tiles away -- at which point the guarantee is 8.49 + 4 = 12.49
#: against a 10.5 radius, and no longer a guarantee at all.  That is what the
#: coverage repair pass is for, and on a dense block it has nothing to work
#: with: measured on ``information-matrix``, a matrix lab with 349 tiles inside
#: tower range had FOUR of them free.  At nine the worst case is 6.36 + 4 =
#: 10.36, so the lattice still covers even when every point has to be displaced
#: as far as displacement goes, and 9 is still comfortably inside the 22.5 link
#: distance.  Towers are placed after routing, so the extra ones cost buildings
#: and nothing else.
TOWER_SPACING = 9


def _expired(deadline: float | None) -> bool:
    """Has the caller's wall-clock deadline passed?

    ``lay_out`` takes ONE deadline at the top of the call and threads it through
    every phase, because every phase used to be bounded on its own and nothing
    bounded their sum: the height sweep spent ``time_budget_s``, the escalated
    retry spent ``RETRY_BUDGET_S`` again, the loose sweep had a budget of its
    own, and the routing inside each of them was bounded by an expansion count
    rather than a clock.  A nominal 4-second budget measured at 80 seconds on
    ``quantum-chip`` and over 400 on a refusing ``universe-matrix`` cell.

    ``None`` means no deadline, which is what a caller reaching into these
    functions directly -- a test, a probe -- gets by default.
    """
    return deadline is not None and time.monotonic() >= deadline


def lanes_for(rate: Fraction, capacity: Fraction) -> int:
    """Parallel lanes needed to carry ``rate`` at ``capacity`` per lane.

    Exact throughout: ``math.ceil`` of a ``Fraction`` is exact, so a rate that
    lands precisely on a lane boundary needs no extra lane.  A float would make
    ``24/12`` occasionally demand three lanes.
    """
    if rate <= 0:
        return 0
    if capacity <= 0:
        raise ValueError("belt capacity must be positive")
    return math.ceil(rate / capacity)


# --- adaptation ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Group:
    key: str
    recipe_id: str
    item_id: int
    model_index: int
    count: int
    width: int
    height: int
    inputs: dict[str, Fraction]
    outputs: dict[str, Fraction]
    proliferated: bool
    #: Parameter block for a machine selected by MODE rather than recipe id.
    #: Empty for an ordinary craft.
    mode_params: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class Strip:
    """A run of machines of one recipe, with its lanes attached.

    The lanes are part of the unit, not something routing adds later.  That is
    what makes a strip individually routable and keeps phase 1 from producing a
    machine nothing can feed.

    Vertical layout, top to bottom::

        in_above      (len(in_above) rows, one belt lane each)
        machines      (mh rows)
        out_lanes     (len(out_lanes) rows)
        in_below      (len(in_below) rows)

    Inputs are fed from BOTH sides.  A sorter spans ``SORTER_MAX_REACH`` tiles,
    so the limit is three lanes per *side*, not three per strip -- lanes above
    and below are reached by different sorters.  Stacking every input above
    made a four-ingredient recipe unbuildable, and four ingredients is ordinary:
    ``orbital-collector`` takes accumulator-full, interstellar-logistics-station,
    reinforced-thruster and super-magnetic-ring.

    Outputs sit immediately below the machines and the overflow inputs below
    them, so when ``in_below`` is empty every row index is exactly what it was
    when inputs were above-only.  That is what keeps the change additive.

    An input LANE carries one or more items.  One item per lane is our
    simplification, not a DSP rule -- belts carry mixed items natively and a
    filtered sorter picks off the one it wants, which is how bus designs work
    (236 of 1,288 sorters in the fixture corpus carry a filter, and
    ``falk-v7-mall-full`` filters all 196 of its own).  Mixing is used ONLY as
    overflow, when one item per lane would not fit, because
    ``layout/validate.py`` decomposes its throughput check into independent
    single-commodity flows exactly BECAUSE a lane normally carries one item.
    """

    group_key: str
    recipe_id: str
    item_id: int
    model_index: int
    machines: int
    mw: int
    mh: int
    #: Lanes arriving on the north side, ordered top-down.  Each lane holds one
    #: or more items; more than one means a shared lane whose sorters filter.
    in_above: tuple[tuple[str, ...], ...]
    #: ``(item, destination group key)`` per lane, ordered top-down, starting
    #: directly under the machine band.  A separate lane per destination is what
    #: removes the need for splitters.
    #:
    #: The destination field may name SEVERAL groups, joined by
    #: :data:`DEST_SEP`.  That is the escape hatch for a producer with fewer
    #: machines than the sorter reach needs shards -- see :func:`_merge_lanes`.
    #: Use :func:`_dests` to read it; comparing it to a group key directly is
    #: how the two representations drift apart.
    out_lanes: tuple[tuple[str, str], ...]
    #: Lanes arriving on the south side, below ``out_lanes``.  Non-empty only
    #: when a recipe has more ingredients than one side can reach.
    in_below: tuple[tuple[str, ...], ...] = ()
    #: Parameter block for a machine configured by a MODE rather than a recipe
    #: (Energy Exchanger, Ray Receiver).  Empty for an ordinary craft.
    mode_params: tuple[int, ...] = ()

    @property
    def in_lanes(self) -> tuple[str, ...]:
        """Every ingredient, regardless of which side or lane feeds it."""
        return tuple(item for lane in self.in_above + self.in_below for item in lane)

    @property
    def width(self) -> int:
        return self.machines * self.mw

    @property
    def height(self) -> int:
        return len(self.in_above) + self.mh + len(self.out_lanes) + len(self.in_below)

    @property
    def machine_row(self) -> int:
        """Row index of the machine band's top edge, relative to the strip."""
        return len(self.in_above)

    @property
    def is_mode_driven(self) -> bool:
        return bool(self.mode_params)

    def lane_of_input(self, item: str) -> tuple[str, ...]:
        """The lane carrying ``item``, including anything sharing it."""
        for lane in self.in_above + self.in_below:
            if item in lane:
                return lane
        raise KeyError(f"{item!r} is not an ingredient of {self.recipe_id!r}")

    def input_is_shared(self, item: str) -> bool:
        """Does ``item`` ride a lane with other items?

        A sorter drawing from a shared lane MUST set a filter, or it takes
        whatever passes and starves the machine that wanted the other item.
        """
        return len(self.lane_of_input(item)) > 1

    def slot_of_input(self, item: str) -> int:
        """Position within its lane, which fixes the sorter's column.

        Two sorters serving one machine from one lane cannot share an anchor, so
        each item on a shared lane takes its own column across the machine's
        width.  That caps a lane at ``mw`` items.
        """
        return self.lane_of_input(item).index(item)

    def row_of_input(self, item: str) -> int:
        """Row index carrying ``item``, relative to the strip's top."""
        for j, lane in enumerate(self.in_above):
            if item in lane:
                return j
        for j, lane in enumerate(self.in_below):
            if item in lane:
                return len(self.in_above) + self.mh + len(self.out_lanes) + j
        raise KeyError(f"{item!r} is not an ingredient of {self.recipe_id!r}")

    def row_of_output(self, k: int) -> int:
        """Row index of the ``k``-th output lane, relative to the strip's top."""
        return len(self.in_above) + self.mh + k

    def input_lane_tiles(self, lane: tuple[str, ...]) -> int:
        """Belt tiles an INPUT lane actually needs, counted from its west end.

        An input lane is fed at its head and flows east, and every tile past the
        last sorter drawing from it carries items nothing will ever take -- dead
        belt, one building each to paste and one more cell the router has to path
        around.  ``_link_lane`` puts a sorter at ``machine.x + min(slot, mw - 1)``
        for each machine, so the last tile that does any work is the last
        machine's column plus the highest slot on this lane.

        Output lanes are NOT trimmable the same way: they are filled at every
        machine column and drained at the east end, so every tile between the
        first sorter and the port carries flow.
        """
        last_slot = min(len(lane) - 1, self.mw - 1)
        return (self.machines - 1) * self.mw + last_slot + 1

    def east_of_input(self, item: str) -> int:
        """Offset from the strip's west edge to the last tile of ``item``'s lane."""
        return self.input_lane_tiles(self.lane_of_input(item)) - 1

    @property
    def sid(self) -> str:
        return f"{self.group_key}"


def _box(s: Strip) -> tuple[int, int]:
    """The footprint one strip occupies in a pack: its extent plus its channels.

    Stated once so the shelf seed, the CP-SAT model and the height sweep cannot
    drift apart about how much ground a strip costs -- they did, and a seed
    whose width is not measured the same way as the solver's is not an upper
    bound on anything.
    """
    return s.width + WEST_CHANNEL + MARGIN, s.height + MARGIN


def _sink_demand(
    groups: dict[str, _Group], spec: BuildSpec, item: str, dest_key: str
) -> Fraction:
    """Items/second one sink wants of ``item``.

    An empty ``dest_key`` is the build boundary -- the item leaves on an output
    belt -- so its demand is whatever the spec promises to deliver.
    """
    if not dest_key:
        return spec.outputs.get(item, Fraction(0))
    dest = groups.get(dest_key)
    if dest is None:
        return Fraction(0)
    return dest.count * dest.inputs.get(item, Fraction(0))


#: Separator joining several destination group keys onto ONE output lane.
#:
#: A group key is ``f"{recipe_id}#{index}"`` and a recipe id never contains a
#: pipe, so the join is unambiguous and reversible.
DEST_SEP = "|"


def _dests(dest: str) -> tuple[str, ...]:
    """The destination group keys one output lane serves.

    Empty for a lane that leaves the build, which is what an empty ``dest``
    means everywhere in this module.
    """
    return tuple(dest.split(DEST_SEP)) if dest else ()


def _shard_sinks(
    sinks: Sequence[tuple[str, str]],
    *,
    cap: int | None = None,
    max_shards: int | None = None,
) -> list[list[tuple[str, str]]]:
    """Chunk output sinks so no strip carries more lanes than a sorter can span.

    EVERY shard drains EVERY product.  One machine makes all of its recipe's
    outputs at once, so a shard that carries lanes for only some of them has
    machines that back up on the rest and stop -- and the strip looks perfectly
    healthy, because the lanes it does have are all connected.  Sequential
    chunking did exactly that: ``plasma-refining`` yields refined-oil and
    hydrogen, its four destinations chunked into a shard of three and a shard of
    one, and the second shard's five machines had nowhere to put their hydrogen.

    So the split is per ITEM rather than across the flat list: each product's
    destinations are divided between the shards, and a shard that would come out
    with none of some product is given a repeat of one of that product's
    destinations instead.  A repeat is not waste -- a sharded producer already
    feeds one consumer from several strips, and the router merges them -- it is
    the only way a shard can drain a product whose consumers are fewer than the
    shards.

    ``cap`` is the room left on the south side once any overflow input lanes are
    seated there; it defaults to the full sorter reach.

    ``max_shards`` is the number of MACHINES available.  A shard with no machine
    leaves its destinations unfed, so the split can never be finer than that --
    and a producer with one machine and four consumers is ordinary
    (``mass-energy-storage`` in the universe-matrix build).  Rather than refuse,
    the chunking stops at ``max_shards`` and hands back shards that may exceed
    ``cap`` lanes; :func:`_merge_lanes` then puts several destinations on ONE
    lane, which is the other axis the geometry actually has.  Callers that pass
    ``max_shards`` must therefore call :func:`_merge_lanes` on every shard.
    """
    reach = catalog.SORTER_MAX_REACH if cap is None else cap
    if reach <= 0:
        raise ValueError("no room left on the south side for any output lane")

    by_item: dict[str, list[str]] = {}
    for item, dest in sinks:
        by_item.setdefault(item, []).append(dest)
    if not by_item:
        return []
    if len(by_item) > reach:
        raise ValueError(
            f"a machine yields {len(by_item)} distinct products but only {reach} "
            f"output lane(s) fit inside the {catalog.SORTER_MAX_REACH}-tile sorter "
            "reach, so one of them could never be drained"
        )

    n = 1
    while sum(max(1, math.ceil(len(d) / n)) for d in by_item.values()) > reach:
        if max_shards is not None and n >= max_shards:
            break
        n += 1

    out: list[list[tuple[str, str]]] = [[] for _ in range(n)]
    for item, dests in by_item.items():
        per = math.ceil(len(dests) / n)
        for s in range(n):
            chunk = dests[s * per : (s + 1) * per] or [dests[s % len(dests)]]
            out[s].extend((item, d) for d in chunk)
    return out


def _merge_lanes(
    shard: Sequence[tuple[str, str]],
    reach: int,
    demand: Mapping[tuple[str, str], Fraction],
    capacity: Fraction,
) -> list[tuple[str, str]]:
    """Fold a shard's destinations onto at most ``reach`` output lanes.

    Sharding splits a producer's destinations across STRIPS and needs one
    machine per shard.  A producer with one machine and four destinations has no
    second shard to give, so the other axis has to move: one lane serves several
    destinations, each consumer tapping the same lane end, and ``_tap_source``
    turns the second and later taps into a junction there.  That is the same
    mechanism a lane already uses when one destination group is sharded into
    several consumer strips, so it costs no new machinery -- only the
    bookkeeping that a lane's destination field is now a SET.

    Which destinations share a lane is a bin-packing question, and the bin is a
    belt: two consumers whose combined draw exceeds the tier would jam the lane
    however it is routed.  Destinations are therefore packed largest-demand
    first into the least-loaded lane, and a lane that still comes out over
    capacity raises -- refusing is honest, while emitting it would produce a
    blueprint that pastes and then starves whichever consumer loses the race.

    Lanes are handed out one per product first (a shard must drain every
    product, or its machines back up on the one it cannot) and the spares go to
    whichever product has the most destinations per lane so far.
    """
    if len(shard) <= reach:
        return list(shard)

    by_item: dict[str, list[str]] = {}
    for item, dest in shard:
        by_item.setdefault(item, []).append(dest)
    if len(by_item) > reach:
        raise ValueError(
            f"a machine yields {len(by_item)} distinct products but only {reach} "
            f"output lane(s) fit inside the {catalog.SORTER_MAX_REACH}-tile sorter "
            "reach, so one of them could never be drained"
        )

    alloc = dict.fromkeys(by_item, 1)
    for _ in range(reach - len(by_item)):
        room = [item for item in by_item if alloc[item] < len(by_item[item])]
        if not room:
            break
        alloc[max(room, key=lambda i: (Fraction(len(by_item[i]), alloc[i]), i))] += 1

    out: list[tuple[str, str]] = []
    for item in sorted(by_item):
        k = alloc[item]
        bins: list[list[str]] = [[] for _ in range(k)]
        loads = [Fraction(0)] * k
        order = sorted(
            by_item[item], key=lambda d: (-demand.get((item, d), Fraction(0)), d)
        )
        for dest in order:
            b = min(range(k), key=lambda i: (loads[i], i))
            bins[b].append(dest)
            loads[b] += demand.get((item, dest), Fraction(0))
        for b, group in enumerate(bins):
            if not group:
                continue
            if loads[b] > capacity:
                raise ValueError(
                    f"{item}: destinations {sorted(group)} have to share one "
                    f"output lane carrying {loads[b]} items/s, over the "
                    f"{capacity}/s the belt sustains"
                )
            out.append((item, DEST_SEP.join(sorted(group))))
    return out


def _allocate_machines(
    count: int,
    shards: Sequence[Sequence[tuple[str, str]]],
    demand: Mapping[tuple[str, str], Fraction],
) -> list[int]:
    """Split ``count`` machines across shards in proportion to demand served.

    An even split would starve whichever shard happens to carry the hungrier
    consumers, so each shard's weight is the largest fraction of any one item's
    total demand that it is responsible for -- one machine produces all of its
    recipe's outputs at once, so the binding item is the one needing most.

    Every shard gets at least one machine (a shard with none leaves its
    destinations unfed), and the total is exactly ``count`` so the placement
    still matches the spec's machine counts.
    """
    n = len(shards)
    totals: dict[str, Fraction] = defaultdict(Fraction)
    for (item, _dest), rate in demand.items():
        totals[item] += rate

    weights: list[Fraction] = []
    for shard in shards:
        served: dict[str, Fraction] = defaultdict(Fraction)
        for item, dest in shard:
            served[item] += demand.get((item, dest), Fraction(0))
        weight = Fraction(0)
        for item, rate in served.items():
            total = totals.get(item, Fraction(0))
            weight = max(weight, rate / total if total > 0 else Fraction(1, n))
        weights.append(weight if weight > 0 else Fraction(1, n))

    total_weight = sum(weights, Fraction(0))
    if total_weight <= 0:
        weights = [Fraction(1)] * n
        total_weight = Fraction(n)

    # One machine each, then hand out the rest by largest remainder.
    allocation = [1] * n
    remaining = count - n
    exact = [remaining * w / total_weight for w in weights]
    floors = [int(v) for v in exact]
    for i, f in enumerate(floors):
        allocation[i] += f
    leftover = remaining - sum(floors)
    order = sorted(range(n), key=lambda i: exact[i] - floors[i], reverse=True)
    for i in order[:leftover]:
        allocation[i] += 1
    return allocation


def _adapt(spec: BuildSpec) -> dict[str, _Group]:
    groups: dict[str, _Group] = {}
    for i, mg in enumerate(spec.groups):
        # A mode-driven recipe names its machine in the catalog registry rather
        # than through the spec's producer, and carries no DSP recipe id at all.
        mode = catalog.MODE_DRIVEN_MACHINE.get(mg.recipe_id)
        if mode is not None:
            item_id = mode.machine_item_id
            mode_params = params.parameters_for(mg.recipe_id)
        else:
            resolved = MACHINE_ITEM_IDS.get(mg.machine_item_id)
            if resolved is None:
                raise KeyError(
                    f"no DSP building known for machine {mg.machine_item_id!r}"
                )
            item_id = resolved
            mode_params = ()
        b = catalog.building(item_id)
        groups[f"{mg.recipe_id}#{i}"] = _Group(
            key=f"{mg.recipe_id}#{i}",
            recipe_id=mg.recipe_id,
            item_id=item_id,
            model_index=b.model_index,
            count=mg.count,
            width=b.width,
            height=b.height,
            inputs=dict(mg.inputs_per_machine),
            outputs=dict(mg.outputs_per_machine),
            proliferated=mg.is_proliferated,
            mode_params=mode_params,
        )
    return groups


def _check_shared_lane_capacity(
    g: _Group, lanes: tuple[tuple[str, ...], ...], machines: int, spec: BuildSpec
) -> None:
    """A shared lane must carry the SUM of its items within the belt tier.

    Only shared lanes are checked.  A single-item lane is left exactly as it
    was, so this cannot reject a spec that already worked -- mixing is the new
    thing, so mixing is what gets the new constraint.

    Exact ``Fraction`` throughout: a float here would let a lane that lands
    precisely on the tier's limit read as over capacity, or worse, the reverse.
    """
    cap = spec.belt_items_per_second
    for lane in lanes:
        if len(lane) < 2:
            continue
        total = sum(
            (g.inputs.get(item, Fraction(0)) * machines for item in lane),
            Fraction(0),
        )
        if total > cap:
            raise ValueError(
                f"recipe {g.recipe_id!r}: lane carrying {list(lane)} needs "
                f"{total} items/s across {machines} machine(s), over the "
                f"{cap}/s a {spec.belt_item_id} sustains; these ingredients "
                f"cannot share a belt at this rate"
            )


def _seat_inputs(
    items: tuple[str, ...], n_sinks: int, reach: int, max_per_lane: int
) -> tuple[tuple[tuple[str, ...], ...], tuple[tuple[str, ...], ...]]:
    """Seat ingredients into lanes above and below the machine band.

    Tries one item per lane FIRST and only mixes when that will not fit, which
    is what makes this additive: every spec that already worked seats exactly as
    it did before, so mixing opens new territory rather than trading anything.

    Mixing is capped at ``max_per_lane`` -- the machine's width -- because two
    sorters serving one machine from one lane cannot share an anchor, so each
    item on a shared lane needs its own column across that width.

    Returns ``(above, below)``.  ``below`` shares the south side with the output
    lanes, so it is kept as small as possible.
    """
    n = len(items)
    if n == 0:
        return (), ()
    for k in range(1, max(1, max_per_lane) + 1):
        lanes = [tuple(items[i : i + k]) for i in range(0, n, k)]
        above, below = tuple(lanes[:reach]), tuple(lanes[reach:])
        if len(below) > reach:
            continue  # more lanes than two sides can hold; mix harder
        if n_sinks and reach - len(below) <= 0:
            continue  # no room left below for an output lane
        return above, below
    raise ValueError(
        f"{n} ingredients cannot be seated: two sides of {reach} lanes carrying "
        f"at most {max_per_lane} items each leaves no room for the output lane"
    )


def plan_strips(spec: BuildSpec, *, strip_len: int = 6) -> list[Strip]:
    """Split every group into strips and attach each strip's lanes.

    A strip carries one output lane per destination, which is what removes the
    need for splitters, and a sorter spans at most ``SORTER_MAX_REACH`` tiles.
    A producer feeding more destinations than that therefore cannot reach its
    own bottom lane -- and real recipe graphs hit this routinely, ``copper-ingot``
    feeding four consumers in the orbital-collector build.

    The group is SHARDED instead: its destinations are chunked to fit the reach
    and its machines split between the chunks in proportion to the demand each
    chunk serves.  That keeps the no-splitter invariant intact and stays a
    planning change rather than a geometry one.

    Note that raising ``strip_len`` cannot help here, though an earlier version
    of this error advised exactly that: ``strip_len`` splits the PRODUCER into
    sub-strips and hands each an identical copy of the lane set, so the lane
    count is a property of how many consumer GROUPS the item feeds. Measured
    from ``strip_len`` 2 to 10000, the failure was identical every time.

    INPUTS are handled the other way about.  Sharding cannot help them: a machine
    needs all its ingredients simultaneously, so splitting two ingredients into
    one shard and two into another leaves both shards stalled.  Instead the strip
    is fed from BOTH sides, and where two sides of single-item lanes still will
    not fit, ingredients SHARE a lane and their sorters filter -- see
    :func:`_seat_inputs`.

    Raises rather than truncating: a silently dropped ingredient would produce a
    blueprint that pastes cleanly and then stalls.
    """
    groups = _adapt(spec)

    producers: dict[str, list[str]] = defaultdict(list)
    for key, g in groups.items():
        for item in g.outputs:
            producers[item].append(key)

    # Which groups consume each group's output, so an output lane can be
    # dedicated per destination.
    consumers: dict[tuple[str, str], list[str]] = defaultdict(list)
    for key, g in groups.items():
        for item in g.inputs:
            for src in producers.get(item, []):
                if src != key:
                    consumers[src, item].append(key)

    reach = catalog.SORTER_MAX_REACH
    strips: list[Strip] = []
    for key, g in groups.items():
        in_items = tuple(sorted(g.inputs))

        sinks: list[tuple[str, str]] = []
        for item in sorted(g.outputs):
            dests = consumers.get((key, item), [])
            sinks.extend((item, d) for d in dests)
            if item in spec.outputs or not dests:
                sinks.append((item, ""))  # leaves the build

        try:
            in_above, in_below = _seat_inputs(
                in_items, len(sinks), reach, max_per_lane=g.width
            )
        except ValueError as exc:
            raise ValueError(f"recipe {g.recipe_id!r}: {exc}") from None

        # Output lanes share the south side with any overflow inputs, so the
        # shard size is what is left after those are seated.
        out_cap = reach - len(in_below)
        shards = (
            _shard_sinks(sinks, cap=out_cap, max_shards=g.count) if sinks else [[]]
        )
        demand = {
            (item, dest): _sink_demand(groups, spec, item, dest) for item, dest in sinks
        }
        per_shard = (
            _allocate_machines(g.count, shards, demand) if len(shards) > 1 else [g.count]
        )
        # Machines bound the number of shards, so a producer that still has more
        # destinations than lanes folds several of them onto one lane instead.
        # Merging AFTER the allocation keeps `_allocate_machines` looking at the
        # per-destination demand it was written against.
        try:
            lanes = [
                _merge_lanes(shard, out_cap, demand, spec.belt_items_per_second)
                for shard in shards
            ]
        except ValueError as exc:
            raise ValueError(f"recipe {g.recipe_id!r}: {exc}") from None

        for shard, machines in zip(lanes, per_shard, strict=True):
            n_strips = max(1, math.ceil(machines / max(1, strip_len)))
            base = machines // n_strips
            extra = machines % n_strips
            for s in range(n_strips):
                n = base + (1 if s < extra else 0)
                if n <= 0:
                    continue
                _check_shared_lane_capacity(g, in_above + in_below, n, spec)
                strips.append(
                    Strip(
                        group_key=key,
                        recipe_id=g.recipe_id,
                        item_id=g.item_id,
                        model_index=g.model_index,
                        machines=n,
                        mw=g.width,
                        mh=g.height,
                        in_above=in_above,
                        in_below=in_below,
                        out_lanes=tuple(shard),
                        mode_params=g.mode_params,
                    )
                )
    return strips


# --- direct insertion ------------------------------------------------------


def _direct_insert_candidates(spec: BuildSpec) -> list[tuple[str, str]]:
    """Producer/consumer recipe pairs a sorter could bridge with no belt.

    Excluded entirely, not merely constrained to zero, when the consumer is
    proliferated: spray is applied on a belt and does not survive crafting, so a
    directly-inserted edge could never be sprayed.  Leaving the variable in with
    a zero bound would let ``-MU_DIRECT`` mislead the search toward placements
    whose apparent reward is unrealisable.
    """
    groups = _adapt(spec)
    proliferated = {g.recipe_id for g in groups.values() if g.proliferated}
    producers: dict[str, list[str]] = defaultdict(list)
    for g in groups.values():
        for item in g.outputs:
            producers[item].append(g.recipe_id)

    out: list[tuple[str, str]] = []
    for g in groups.values():
        for item in g.inputs:
            for src in producers.get(item, []):
                if src == g.recipe_id:
                    continue
                if g.recipe_id in proliferated:
                    continue
                if (src, g.recipe_id) in spec.belt_required_edges:
                    continue
                out.append((src, g.recipe_id))
    return sorted(set(out))


@dataclass(frozen=True, slots=True)
class _DirectCandidate:
    """A net a single sorter could replace, and the geometry that would allow it.

    ``prod_row`` and ``cons_row`` are offsets from each strip's origin to the
    lane row the sorter would span, so the alignment condition stays affine in
    the packer's ``x``/``y`` variables.
    """

    item: str
    prod_row: int
    cons_row: int
    #: Belt tiles each lane occupies, counted east from its strip's west edge.
    #: The sorter needs a column both lanes cover, and an input lane is trimmed
    #: to its last sorter, so the consumer's span is usually SHORTER than its
    #: strip.  Using the strip width for both would let the packer commit a pair
    #: whose lanes share no tile, which ``_bridge`` would then refuse -- a
    #: rewarded promise the emission stage cannot keep.
    prod_span: int = 1
    cons_span: int = 1


def _direct_net_candidates(
    strips: list[Strip], spec: BuildSpec
) -> dict[tuple[int, int], _DirectCandidate]:
    """Map eligible nets to the lane rows a bridging sorter would connect.

    Works at *strip* granularity because that is what the packer places, while
    :func:`_direct_insert_candidates` works at recipe granularity -- one recipe
    can be split across several strips, and each of those nets is separately
    eligible.
    """
    eligible = set(_direct_insert_candidates(spec))
    if not eligible:
        return {}

    out: dict[tuple[int, int], _DirectCandidate] = {}
    for i, j in _nets_between(strips):
        src, dst = strips[i], strips[j]
        if (src.recipe_id, dst.recipe_id) not in eligible:
            continue
        # The producer's output lane dedicated to this destination.
        lane = next(
            (
                (k, item)
                for k, (item, dest) in enumerate(src.out_lanes)
                if dst.group_key in _dests(dest)
            ),
            None,
        )
        if lane is None:
            continue
        k, item = lane
        if item not in dst.in_lanes:
            continue
        # Ask the strip for the rows rather than recomputing the layout here:
        # inputs may sit above or below the machine band, and duplicating that
        # arithmetic is how the two drift apart.
        out[i, j] = _DirectCandidate(
            item=item,
            prod_row=src.row_of_output(k),
            cons_row=dst.row_of_input(item),
            prod_span=src.width,
            cons_span=dst.input_lane_tiles(dst.lane_of_input(item)),
        )
    return out


def tie_break_cap(n_terms: int, *, width_bound: int, height: int, n_direct: int) -> int:
    """Weight that makes width outrank every tie-break term put together.

    The objective is lexicographic on purpose: width first, then wirelength and
    direct-insert reward as tie-breaks among equal-width packings.  Blending them
    is what once made *more* solver time produce *worse* area, because the
    blended proxy was anti-correlated with the metric actually reported.

    The cap must therefore exceed the largest value the whole tie-break tier can
    take, and it has to grow when the direct-insert reward joins that tier --
    otherwise direct inserts could buy width, quietly reinstating the blend.
    """
    return n_terms * (width_bound + height) + MU_DIRECT * n_direct + 1


# --- phase 1: packing ------------------------------------------------------


@dataclass
class _Pack:
    """Strip origins chosen by the packer."""

    at: dict[int, tuple[int, int]]
    width: int
    height: int
    status: str
    hit_budget: bool = False
    #: Nets the packer arranged to bridge with a sorter instead of a belt route.
    direct: frozenset[tuple[int, int]] = frozenset()


def _nets_between(strips: list[Strip]) -> list[tuple[int, int]]:
    """Strip index pairs that will need a belt route."""
    by_group: dict[str, list[int]] = defaultdict(list)
    for i, s in enumerate(strips):
        by_group[s.group_key].append(i)
    nets: set[tuple[int, int]] = set()
    for i, s in enumerate(strips):
        for _item, dest in s.out_lanes:
            for d in _dests(dest):
                for j in by_group.get(d, []):
                    nets.add((i, j))
    return sorted(nets)


def _greedy_pack(strips: list[Strip], height: int) -> _Pack:
    """Shelf packing -- always succeeds, and seeds the solver's upper bound.

    A SEED, and only a seed.  It bounds `_pack`'s width from above and hints its
    variables; it is never returned as a layout.  Returning it was tried twice
    and deleted twice -- see the note by :data:`TOWER_SPACING`.
    """
    at: dict[int, tuple[int, int]] = {}
    shelf_x, shelf_y, shelf_h = 0, 0, 0
    width = 0
    for i, s in enumerate(strips):
        w, h = _box(s)
        if shelf_y + h > height and shelf_h:
            shelf_x, shelf_y, shelf_h = width, 0, 0
        # `at` is the CONTENT origin, so the west channel is stepped over here
        # and every consumer of a pack goes on meaning the same thing by it.
        at[i] = (shelf_x + WEST_CHANNEL, shelf_y)
        shelf_y += h
        shelf_h = max(shelf_h, w)
        width = max(width, shelf_x + w)
    return _Pack(at=at, width=width, height=height, status="greedy")


def _pack(
    strips: list[Strip],
    *,
    height: int,
    width_bound: int,
    time_budget_s: float,
    direct_candidates: dict[tuple[int, int], _DirectCandidate],
    workers: int,
    seed: _Pack | None = None,
) -> _Pack | None:
    """Minimise width at a fixed height with CP-SAT.

    Height is swept outside rather than multiplied inside: ``W * H`` is a product
    of two variables, whose CP-SAT relaxation is weak enough that the search
    flounders.  Several easy solves beat one hard one.

    ``seed`` is a shelf packing at this same height -- feasible by construction,
    so it does two things no heuristic guess could.  It hints every ``x``/``y``,
    which gives the search an incumbent immediately instead of after it finds
    one; and its width is a proven upper bound on ``w_var``, which cuts the
    domain the bound has to climb through.  This is the construction that used
    to be the fallback, put to the one use it is genuinely good for.
    """
    model = cp_model.CpModel()
    n = len(strips)
    if n == 0:
        return None

    # Sizes first: several cuts below need them before any variable exists.
    # A size is the strip PLUS its reserved channels -- see `WEST_CHANNEL`. The
    # routing corridors are part of what `add_no_overlap_2d` keeps apart, which
    # is what makes them a constraint the model respects rather than a corridor
    # the router has to hope for.
    sizes = [_box(s) for s in strips]
    if any(h > height for _, h in sizes):
        return None  # this height cannot hold some strip at all

    # CUT 1 -- area.  Everything must fit inside `w_var x height`, so
    # `w_var >= ceil(total_area / height)`.  Without this `w_var`'s lower bound
    # is 1 and the relaxation can drive the width term to nothing, which is most
    # of why the bound crawled while the incumbent sat still.  `height` is a
    # constant here, so this stays linear.
    total_area = sum(w * h for w, h in sizes)
    widest = max(w for w, _ in sizes)
    w_lb = max(widest, -(-total_area // height))  # ceil division
    w_var = model.new_int_var(min(w_lb, width_bound), width_bound, "W")

    xs, ys, x_iv, y_iv = [], [], [], []
    for i, (w, h) in enumerate(sizes):
        x = model.new_int_var(0, max(0, width_bound - w), f"x{i}")
        y = model.new_int_var(0, max(0, height - h), f"y{i}")
        xs.append(x)
        ys.append(y)
        x_iv.append(model.new_fixed_size_interval_var(x, w, f"xi{i}"))
        y_iv.append(model.new_fixed_size_interval_var(y, h, f"yi{i}"))
        model.add(x + w <= w_var)

    model.add_no_overlap_2d(x_iv, y_iv)

    # CUT 3 -- ROUTING CAPACITY was built here, measured, and taken out.
    #
    # The argument is sound as far as it goes and the brief for this work said
    # it had never been built and measured, so it now has been.  A net whose
    # endpoints straddle a vertical cut occupies AT LEAST one cell on that
    # column, so free cells in a column bound the nets crossing it, and nothing
    # in this model said so while the objective drove straight at the bound:
    # `universe-matrix/no-proliferator` at h=69 packs a column with 70 free
    # cells against 70 nets crossing it.  Slack ZERO, with a band of neighbours
    # at 2.  By counting alone no router can wire that, and `_pack` called it
    # feasible.
    #
    # It was expressed as one `add_cumulative` over the strips' CONTENT spans,
    # charging `LEVELS` cells per machine row and one per lane row, against a
    # column budget that reserved one free cell per net in the block.  It works:
    # h=69 becomes infeasible and is no longer offered.
    #
    # AND IT MADE THE SPEC WORSE, which is what the calibration behind it could
    # not see.  The numbers that motivated it compared DIFFERENT specs -- 4.6
    # free cells per crossing net on `casimir-crystal`, 5.0 on `quantum-chip`,
    # 1.0 on the `universe-matrix` pack -- and that comparison is confounded by
    # spec size.  Within ONE spec it inverts: h=69, the saturated pack, routes
    # all but ONE of its 140 nets given no clock, while h=92, h=116, h=145 and
    # h=185 all satisfy the bound comfortably and leave 12, 26, 14 and 17
    # unrouted.  Rejecting h=69 deletes the best candidate the sweep has.
    # Corpus at 4s: 66/65/66 clean with it against 66/66/66 without.
    #
    # So cut capacity is a NECESSARY condition that is not the binding one, and
    # enforcing a necessary condition that correlates the wrong way inside a
    # spec costs more than it buys. What decides routability here is which cells
    # are free, not how many.

    # Symmetry breaking between identical strips of the same recipe: without it
    # the search burns itself on permutations that differ by nothing.
    for i in range(n):
        for j in range(i + 1, n):
            a, b = strips[i], strips[j]
            if (a.group_key, a.machines, a.in_lanes, a.out_lanes) == (
                b.group_key,
                b.machines,
                b.in_lanes,
                b.out_lanes,
            ):
                model.add(xs[i] * height + ys[i] <= xs[j] * height + ys[j])

    # Half-perimeter wirelength over the nets, which is what keeps phase 2's job
    # tractable and costs almost nothing to express.
    terms: list[cp_model.IntVar] = []
    for i, j in _nets_between(strips):
        dx = model.new_int_var(0, width_bound, f"dx{i}_{j}")
        dy = model.new_int_var(0, height, f"dy{i}_{j}")
        model.add_abs_equality(dx, xs[i] - xs[j])
        model.add_abs_equality(dy, ys[i] - ys[j])

        # CUT 2 -- separation.  Two strips cannot overlap, so they are disjoint
        # in x or in y; either way their origins differ by at least the smaller
        # of the two extents on that axis.  Without this every `dx`/`dy` has a
        # relaxation value of 0, so the entire HPWL half of the objective is
        # invisible to the bound -- which is why `bound` sat near the width term
        # alone while `obj` was more than twice it.
        wi, hi = sizes[i]
        wj, hj = sizes[j]
        model.add(dx + dy >= min(min(wi, wj), min(hi, hj)))

        terms.append(dx)
        terms.append(dy)

    # Direct insertion: one Boolean per eligible net, reified against the
    # geometry that would let a single sorter replace the whole belt route.
    #
    # The condition is deliberately strict -- the consumer sits directly EAST of
    # the producer with their two lane rows on the same y -- because a sorter
    # must run straight, never diagonally, and never across altitudes
    # (`catalog.SORTER_SPANS_ALTITUDE` is False). Both lane rows are at z=0 by
    # construction, so alignment in y is the whole altitude story.
    #
    # The gap floor is MARGIN + 1 rather than 1: the packed boxes carry a margin,
    # so anything tighter would collide with `no_overlap_2d` and make the
    # Boolean unsatisfiable rather than merely unattractive.
    direct_vars: dict[tuple[int, int], cp_model.IntVar] = {}
    for (i, j), cand in direct_candidates.items():
        di = model.new_bool_var(f"di{i}_{j}")
        # The consumer sits BELOW the producer, and the sorter runs vertically
        # down a column both lanes share.
        #
        # Vertical is the geometry this architecture actually wants. A strip is
        # input lanes / machines / output lanes stacked top to bottom, so a
        # producer's output lane is its bottom row and a consumer's input lane is
        # its top row -- they meet naturally when one is stacked under the other.
        #
        # The east/west alternative was tried and is strictly worse: it forces
        # the two strips side by side, which WIDENS the pack, and width outranks
        # the direct-insert reward lexicographically. The solver correctly
        # refused every such pair, so the feature never fired.
        gap = (ys[j] + cand.cons_row) - (ys[i] + cand.prod_row)
        model.add(gap >= 1).only_enforce_if(di)
        model.add(gap <= catalog.SORTER_MAX_REACH).only_enforce_if(di)
        # The lanes must share at least one column for the sorter to run
        # straight down, and each lane's span is its own -- an input lane stops
        # at its last sorter, so it is generally narrower than its strip.
        model.add(xs[i] <= xs[j] + cand.cons_span - 1).only_enforce_if(di)
        model.add(xs[j] <= xs[i] + cand.prod_span - 1).only_enforce_if(di)
        direct_vars[i, j] = di

    # Objective: width first, wirelength only as a tie-break.
    #
    # Height is fixed for this solve, so `w_var` IS the area being minimised.
    # Previously width carried weight 5 while HPWL contributed two terms per net
    # each as large as `width_bound`, so wirelength dominated and the solver
    # traded width away to shorten wires.  That is measurable: with the old
    # weights, giving the solver MORE time made the final area WORSE
    # (1460 tiles at 0.1s versus 1566 at 4s), because it was optimising a proxy
    # anti-correlated with the metric we actually report.
    #
    # Scaling width above the largest achievable HPWL sum makes the comparison
    # lexicographic without a second solve: any width saving beats every
    # wirelength saving, and HPWL then breaks ties among equal-width packings --
    # which is all it was ever needed for, since it exists to keep phase 2's
    # routing tractable rather than to shrink the build.
    # The direct-insert reward joins the tie-break tier rather than competing
    # with width: a direct insert deletes belt tiles, not bounding box. It is
    # expressed as a PENALTY for *not* direct-inserting so every term stays
    # non-negative -- a negative reward would let the tier range below zero and
    # a width increase could be bought back, which is exactly the blend this
    # ordering exists to prevent.
    cap = tie_break_cap(
        len(terms), width_bound=width_bound, height=height, n_direct=len(direct_vars)
    )
    missed = sum(di.Not() for di in direct_vars.values())
    model.minimize(w_var * cap + LAMBDA_HPWL * sum(terms) + MU_DIRECT * missed)

    # Warm start.  The seed is feasible at this height by construction, so its
    # width bounds `w_var` from above and its positions give the search an
    # incumbent to improve on rather than one to find.  Values are clamped into
    # each variable's domain: an out-of-domain hint is not a tighter hint, it is
    # a discarded one.
    if seed is not None:
        model.add(w_var <= min(seed.width, width_bound))
        for i, (hx, hy) in seed.at.items():
            if i >= n:
                continue
            w, h = sizes[i]
            # `seed.at` is a CONTENT origin and `xs` is a BOX origin, so the
            # west channel comes back off before the hint is offered. An
            # out-by-one hint is not a weaker hint, it is a hint for a packing
            # that overlaps.
            model.add_hint(xs[i], min(max(hx - WEST_CHANNEL, 0), max(0, width_bound - w)))
            model.add_hint(ys[i], min(max(hy, 0), max(0, height - h)))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(0.05, time_budget_s)
    # Determinism is load-bearing for the bake-off: multi-worker CP-SAT would
    # make the A-vs-B comparison noise rather than measurement.
    solver.parameters.num_search_workers = workers
    solver.parameters.random_seed = 20260822
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None
    return _Pack(
        at={
            i: (solver.Value(xs[i]) + WEST_CHANNEL, solver.Value(ys[i]))
            for i in range(n)
        },
        width=solver.Value(w_var),
        height=height,
        status=solver.StatusName(status),
        hit_budget=status == cp_model.FEASIBLE,
        direct=frozenset(k for k, di in direct_vars.items() if solver.Value(di)),
    )


# --- emission --------------------------------------------------------------


@dataclass
class _Canvas:
    """Buildings under construction, plus what occupies each cell."""

    buildings: list[PlacedBuilding] = field(default_factory=list)
    #: ``(x, y, level)`` -> building index, for cells that block routing.
    blocked: dict[tuple[int, int, int], int] = field(default_factory=dict)
    #: Cells a machine occupies, which block *every* level.
    solid: set[tuple[int, int]] = field(default_factory=set)

    #: ``cell -> port (x, y)``: one way in or out, held for that port's nets.
    #:
    #: A port is a lane's end tile, so it has at most three free neighbours and
    #: often one.  Without a reservation an earlier net's path takes the last
    #: one, and every net using that port is then handed an EMPTY start or goal
    #: set: A* returns ``None`` having expanded zero nodes.  That is
    #: indistinguishable from congestion in the counters and cannot be
    #: negotiated away, because a net that expands nothing never registers a
    #: conflict for the history term to price.  Measured on the magnetic-ring
    #: spec: 48 of 128 searches failed at zero expansions, at every candidate
    #: height, with two thirds of the routing budget still unspent.
    reserved: dict[tuple[int, int, int], tuple[int, int]] = field(default_factory=dict)
    #: Ports the net currently being routed owns; it may use their reservations.
    routing_ports: frozenset[tuple[int, int]] = frozenset()
    #: ``(min_x, min_y, max_x, max_y)`` no building may leave, once the packed
    #: block's extent is known.
    #:
    #: This is the one thing that makes the block's boundary hold still.  Every
    #: later pass -- coater drops, the router, the external input runs, the
    #: power lattice -- asks ``free`` before it places, so the final bounding box
    #: is decided once, by the packer, instead of being pushed outward by
    #: whichever pass ran last.  ``None`` while the extent is still being
    #: established, which is exactly the window in which the strips are emitted.
    limit: tuple[int, int, int, int] | None = None
    #: Cells held for the tower lattice, at every level.
    #:
    #: Claimed before the router runs and released just before the towers go in.
    #: Power used to take whatever was left over once every belt was laid, which
    #: on a dense block is nothing: measured on ``casimir-crystal``, a matrix lab
    #: had FOUR free cells among the 349 inside tower range, and thirteen
    #: buildings shipped unpowered.  A lattice point is one cell in eighty-one;
    #: the router can afford to path around it, and coverage cannot afford to be
    #: whatever is left.
    keep_out: set[tuple[int, int]] = field(default_factory=set)

    def add(self, b: PlacedBuilding, *, solid: bool = False) -> int:
        idx = len(self.buildings)
        self.buildings.append(b)
        if solid:
            for x, y, _ in b.tiles():
                self.solid.add((x, y))
                for lvl in range(LEVELS):
                    self.blocked[x, y, lvl] = idx
        else:
            for x, y, _ in b.tiles():
                self.blocked[x, y, b.z] = idx
        return idx

    def free(self, cell: tuple[int, int, int]) -> bool:
        x, y, _ = cell
        if cell in self.blocked or (x, y) in self.solid or (x, y) in self.keep_out:
            return False
        if self.limit is not None:
            min_x, min_y, max_x, max_y = self.limit
            if not (min_x <= x <= max_x and min_y <= y <= max_y):
                return False
        port = self.reserved.get(cell)
        return port is None or port in self.routing_ports


def _core_bounds(canvas: _Canvas) -> tuple[int, int, int, int]:
    """The INCLUSIVE tile box the packed block occupies.

    Tile extents, not origins.  ``_build`` used to take ``max(b.x)`` and add the
    pack width to it, which over-estimated the east face by a whole block and
    under-estimated it by a machine's width -- so the router had a field to roam
    in on one side and none on the other, and "the edge" meant something
    different depending on which pass asked.
    """
    if not canvas.buildings:
        return (0, 0, 0, 0)
    return (
        min(b.x for b in canvas.buildings),
        min(b.y for b in canvas.buildings),
        max(b.x + b.width - 1 for b in canvas.buildings),
        max(b.y + b.height - 1 for b in canvas.buildings),
    )


def _grow(box: tuple[int, int, int, int], rings: int) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = box
    return (x0 - rings, y0 - rings, x1 + rings, y1 + rings)


def _pick_sorter(rate: Fraction, span: int, machines: int) -> tuple[int, int]:
    """Cheapest sorter tier and count carrying ``rate`` across ``span``.

    Reach is three tiles for every tier, so tiers differ only in throughput --
    there is never a reason to pay for a higher tier than the rate needs.
    """
    per_machine = rate / machines if machines else rate
    for tier in SORTER_TIERS:
        if catalog.sorter_rate(tier, span) >= per_machine:
            return tier, machines
    return SORTER_TIERS[-1], machines


@dataclass(frozen=True, slots=True)
class _Port:
    """Where a net starts or ends: a lane tile, and the way out of it."""

    belt: int
    x: int
    y: int
    #: Inclusive x-range of the whole lane, not just the tile the router
    #: attaches to.  A direct-insert sorter may drop down ANY column the two
    #: lanes share, so it needs the extent rather than the endpoint.
    x0: int = 0
    x1: int = -1
    #: Every belt index in this lane, west to east.
    #:
    #: Carried so that a lane feeding several consumers can give each of them
    #: its OWN tile to leave from.  They used to share the lane's end tile, and
    #: a belt tile has one ``output_obj``, so only one net could be linked --
    #: see ``_commit_paths``.  A tap partway along the lane becomes a junction;
    #: the tiles are what makes choosing distinct taps possible.
    tiles: tuple[int, ...] = ()
    #: Machines behind this lane.
    #:
    #: A strip's lane carries its OWN machines' share of the group's rate, and
    #: the shards of one group are rarely the same size.  ``_connect_short_cuts``
    #: needs it to tell an island that balances from one that starves.
    machines: int = 1

    def columns(self) -> range:
        return range(self.x0, self.x1 + 1)

    def at_tile(self, k: int) -> _Port:
        """This port moved to the ``k``-th tile of its own lane.

        Out-of-range or an unknown tile list leaves the port alone, so a caller
        that asks for more taps than the lane has tiles degrades to sharing --
        which the fan-out check then reports honestly rather than mis-linking.
        """
        if not self.tiles or not 0 <= k < len(self.tiles):
            return self
        return _Port(
            self.tiles[k],
            self.x0 + k,
            self.y,
            self.x0,
            self.x1,
            self.tiles,
            self.machines,
        )


def _lane_filter(item: str) -> int:
    """The DSP item id a sorter on a shared lane must filter to.

    Raises rather than falling back to zero: an unfiltered sorter on a shared
    lane grabs whatever passes and starves the machine that wanted the other
    item, and the blueprint still pastes cleanly.
    """
    got = catalog.get_item_id(item)
    if got is None:
        raise KeyError(
            f"{item!r} shares a belt lane but has no DSP item id, so its sorter "
            f"cannot be filtered; it would take whatever passed instead"
        )
    return got


def _emit_strip(
    canvas: _Canvas,
    s: Strip,
    ox: int,
    oy: int,
    belt_id: int,
    belt_model: int,
    rates: dict[str, Fraction],
    in_rates: Mapping[str, Fraction] | None = None,
    out_rates: Mapping[str, Fraction] | None = None,
) -> tuple[dict[str, _Port], dict[tuple[str, str], _Port], int]:
    """Place one strip's lanes, machines and sorters.

    Returns the west end of each input lane and the east end of each output lane
    -- the points routing connects -- plus the sorter count.

    Inputs may sit on either side of the machine band; ``Strip.row_of_input``
    owns that arithmetic so it is stated once rather than re-derived here.

    Where a lane carries several items, each gets its OWN sorter, filtered to
    that item and offset into its own column across the machine's width.  Two
    sorters serving one machine from one lane cannot share an anchor, and an
    unfiltered sorter on a shared lane takes whatever passes -- starving the
    machine that wanted the other item, with nothing about the paste looking
    wrong.

    Sorter tiers are sized from the rate of the ITEM EACH SORTER MOVES, per
    machine.  Sizing from a machine's average across its sorters is wrong and
    hid a real starvation bug: ``circuit-board`` takes copper at 1/s and iron at
    2/s, and charging both sorters the 1.5/s average exactly meets a Mk.I, so it
    read as clean while the sorter actually carrying the iron starved the
    machine.  An overloaded sorter hides behind an underloaded one whenever
    ingredient rates differ, which is most of the time.
    """
    in_rates = in_rates or {}
    out_rates = out_rates or {}
    in_ports: dict[str, _Port] = {}
    out_ports: dict[tuple[str, str], _Port] = {}
    width = s.width
    n_above = len(s.in_above)

    # Row -> the item that row's belt is labelled with. On a shared lane this is
    # the FIRST item; the authoritative set is the sorters' filters, which is
    # what the validator keys on. Building it up front removes the
    # branch-per-row this used to need, and it is what lets the marker pass
    # label external input belts later: the knowledge is unrecoverable once
    # emission drops it.
    lane_item_of: dict[int, str] = {}
    #: Row -> belt tiles that row's lane actually needs.  Input lanes stop at
    #: their last sorter (see ``Strip.input_lane_tiles``); output lanes run the
    #: full width because their port is the east end.
    lane_tiles_of: dict[int, int] = {}
    for lane in s.in_above + s.in_below:
        row = s.row_of_input(lane[0])
        lane_item_of[row] = lane[0]
        lane_tiles_of[row] = s.input_lane_tiles(lane)
    for k, (item, _dest) in enumerate(s.out_lanes):
        lane_item_of[s.row_of_output(k)] = item
        lane_tiles_of[s.row_of_output(k)] = width

    lane_idx: dict[int, list[int]] = {}
    for row in range(s.height):
        y = oy + row
        if n_above <= row < n_above + s.mh:
            continue  # machine band
        indices = []
        for k in range(lane_tiles_of.get(row, width)):
            indices.append(
                canvas.add(
                    PlacedBuilding(
                        item_id=belt_id,
                        model_index=belt_model,
                        x=ox + k,
                        y=y,
                        width=1,
                        height=1,
                        yaw=Facing.EAST.value,
                        carries_item=lane_item_of.get(row),
                    )
                )
            )
        for a, b in zip(indices, indices[1:], strict=False):
            canvas.buildings[a] = _relink(canvas.buildings[a], output_obj=b)
        lane_idx[row] = indices

    machine_y = oy + n_above
    machines: list[int] = []
    for k in range(s.machines):
        machines.append(
            canvas.add(
                PlacedBuilding(
                    item_id=s.item_id,
                    model_index=s.model_index,
                    x=ox + k * s.mw,
                    y=machine_y,
                    width=s.mw,
                    height=s.mh,
                    # A mode-driven machine carries no recipe id at all: its job
                    # is the word in the parameter block. This was once
                    # `abs(hash(name)) % 30000`, which is not a DSP recipe id and
                    # is not even stable across processes, since Python
                    # randomises string hashing.
                    recipe_id=0 if s.is_mode_driven else catalog.recipe_id(s.recipe_id),
                    parameters=s.mode_params,
                ),
                solid=True,
            )
        )

    bottom = machine_y + s.mh - 1
    sorters = 0

    def item_rate(item: str, table: Mapping[str, Fraction]) -> Fraction:
        """What ONE sorter moves: one machine's rate for this one item."""
        got = table.get(item)
        if got is not None and got > 0:
            return got
        return rates.get(item, Fraction(1))

    def feed(lane: tuple[str, ...], row: int, span: int, near_edge: int) -> int:
        """One filtered sorter per (item, machine) for this lane."""
        placed = 0
        shared = len(lane) > 1
        for slot, item in enumerate(lane):
            in_ports[item] = _Port(
                lane_idx[row][0],
                ox,
                oy + row,
                ox,
                ox + len(lane_idx[row]) - 1,
                tuple(lane_idx[row]),
                s.machines,
            )
            tier, _count = _pick_sorter(item_rate(item, in_rates), span, 1)
            placed += _link_lane(
                canvas,
                lane_idx[row],
                machines,
                oy + row,
                near_edge,
                tier,
                into_machine=True,
                filter_id=_lane_filter(item) if shared else 0,
                column=slot,
            )
        return placed

    for j, lane in enumerate(s.in_above):
        sorters += feed(lane, row=j, span=n_above - j, near_edge=machine_y)

    for j, (item, dest) in enumerate(s.out_lanes):
        row = s.row_of_output(j)
        span = j + 1
        out_ports[item, dest] = _Port(
            lane_idx[row][-1],
            ox + width - 1,
            oy + row,
            ox,
            ox + width - 1,
            tuple(lane_idx[row]),
            s.machines,
        )
        tier, _count = _pick_sorter(item_rate(item, out_rates), span, 1)
        sorters += _link_lane(
            canvas, lane_idx[row], machines, oy + row, bottom, tier, into_machine=False
        )

    # Overflow ingredients, seated below the output lanes and reaching up to the
    # machine band's south edge.
    for j, lane in enumerate(s.in_below):
        row = s.row_of_input(lane[0])
        sorters += feed(
            lane, row=row, span=len(s.out_lanes) + j + 1, near_edge=bottom
        )

    return in_ports, out_ports, sorters


def _link_lane(
    canvas: _Canvas,
    lane: list[int],
    machines: list[int],
    lane_y: int,
    machine_y: int,
    tier: int,
    *,
    into_machine: bool,
    filter_id: int = 0,
    column: int = 0,
) -> int:
    """One sorter per machine, between the lane and the machine's near edge.

    Anchors sit *on* the two buildings and the connection indices carry the
    semantics, which is how the game itself represents this -- a sorter consumes
    no grid cell of its own.

    ``column`` offsets the sorter across the machine's width so several items
    sharing one lane each get their own anchor; ``filter_id`` pins which item
    this sorter moves, which is mandatory on a shared lane and left at zero on a
    plain one.  That zero-versus-set distinction is the signal the validator
    uses to tell the two apart, so do not set a filter where none is needed.
    """
    model_index = catalog.building(tier).model_index
    facing = Facing.SOUTH.value if lane_y < machine_y else Facing.NORTH.value
    placed = 0
    for m_idx in machines:
        m = canvas.buildings[m_idx]
        x = m.x + min(column, m.width - 1)
        belt_idx = next((i for i in lane if canvas.buildings[i].x == x), None)
        if belt_idx is None:
            continue
        if into_machine:
            src, dst = belt_idx, m_idx
            ax, ay, bx, by = x, lane_y, x, machine_y
        else:
            src, dst = m_idx, belt_idx
            ax, ay, bx, by = x, machine_y, x, lane_y
        canvas.buildings.append(
            PlacedBuilding(
                item_id=tier,
                model_index=model_index,
                x=ax,
                y=ay,
                width=1,
                height=1,
                x2=bx,
                y2=by,
                z2=0,
                yaw=facing,
                yaw2=facing,
                input_obj=src,
                output_obj=dst,
                filter_id=filter_id,
            )
        )
        placed += 1
    return placed


def _relink(
    b: PlacedBuilding,
    *,
    output_obj: int | None = None,
    input_obj: int | None = None,
) -> PlacedBuilding:
    """Repoint a belt at its successor or its feeder, preserving everything else.

    Uses ``replace`` rather than rebuilding field by field.  The hand-written
    version enumerated fields and therefore silently dropped any it did not
    mention -- it was already discarding ``parameters``, and it swallowed
    ``carries_item`` the moment that was added, which is why belt markers came
    out empty while the emitter was setting them correctly.

    Only the arguments actually passed are applied, so ``_relink(b,
    input_obj=j)`` cannot clear an ``output_obj`` set moments earlier.
    """
    changes: dict[str, int] = {}
    if output_obj is not None:
        changes["output_obj"] = output_obj
    if input_obj is not None:
        changes["input_obj"] = input_obj
    return replace(b, **changes)  # type: ignore[arg-type]


# --- phase 2: routing ------------------------------------------------------

_STEPS = ((1, 0), (-1, 0), (0, 1), (0, -1))


def _cut_loops(path: list[tuple[int, int, int]]) -> list[tuple[int, int, int]]:
    """Remove any cell that appears twice, keeping the walk connected.

    A ramp edge occupies an extra "run" cell, spliced in from ``via`` during
    reconstruction.  That cell can already lie on the path -- the route leaves
    it, wanders, and comes back to climb from it -- and then the same tile
    appears twice.  Committing such a path fails: the second occurrence finds
    the cell already built and the whole net is dropped, silently until
    ``_commit_paths`` learned to count.  Measured on the magnetic-ring chain, 3
    of 19 routed paths had a repeat.

    Cutting the loop between the two occurrences is safe, and cheaper than
    rerouting: consecutive cells in the walk are adjacent (or a ramp pair) by
    construction, so splicing out everything between a repeat and its first
    occurrence leaves a walk whose consecutive cells were already consecutive.
    The result is also shorter, which is strictly better.
    """
    first: dict[tuple[int, int, int], int] = {}
    out: list[tuple[int, int, int]] = []
    for cell in path:
        seen_at = first.get(cell)
        if seen_at is not None:
            for dropped in out[seen_at + 1 :]:
                first.pop(dropped, None)
            del out[seen_at + 1 :]
            continue
        first[cell] = len(out)
        out.append(cell)
    return out


@dataclass
class _Grid:
    """The routing canvas as flat arrays: one int per cell, one byte of state.

    A cell is ``(x - gx0) * gh * LEVELS + (y - gy0) * LEVELS + lvl`` -- an int,
    hashed by identity, whose four neighbours and eight ramp targets are reached
    by ADDING a precomputed offset rather than by building a tuple.

    ``occ`` folds ``bounds``, ``blocked``, ``solid`` and ``keep_out`` into one
    byte per cell, so :func:`_astar`'s neighbour test is a single indexed read
    where it used to be four hashed probes and two tuple builds.  ``reserved``
    is kept OUT of it and applied per call, because which reservations a net may
    use depends on ``canvas.routing_ports``, which is rebound for every net.

    ``base`` is ``occ`` as it stood before any path was committed.  Rip-up
    restores from it rather than writing 1, because a ripped cell is not
    necessarily free -- it may sit outside ``bounds``, which a start cell is
    allowed to do.  Restoring the byte it actually had cannot get that wrong.

    THE LAYOUT IS X-MAJOR ON PURPOSE.  ``heapq`` breaks a tie on ``(f, cost)`` by
    comparing the third element, so the cell's own ordering decides which of two
    equal-cost paths is taken.  ``x``, then ``y``, then ``lvl`` makes integer
    order the SAME total order as tuple order, so every tie falls the way it did
    when cells were tuples.  A level-major index -- the obvious layout -- is
    measurably a different router: injected as a fault it left the expansion
    count byte-identical and moved the committed paths.

    ``span`` is the indexed extent and is padded two cells beyond anything the
    search may touch, because a ramp travels two tiles and index arithmetic from
    a passable cell must land inside the array rather than wrapping into the next
    column.  Everything in the pad is impassable, which is also how
    out-of-bounds is expressed.
    """

    #: The intersected ``bounds`` this was built for. A caller's grid is only
    #: reusable for the same box, since the box is baked into ``occ``.
    box: tuple[int, int, int, int]
    #: The indexed extent, ``bounds`` (or the canvas limit) plus two cells.
    span: tuple[int, int, int, int]
    gx0: int
    gy0: int
    gh: int
    xstep: int
    size: int
    base: bytes
    occ: bytearray
    #: ``(index, port)`` for every reserved cell inside the box.
    reserved: tuple[tuple[int, tuple[int, int]], ...]
    #: Congestion history as a flat array, or ``None`` on a round that has none.
    hist: list[float] | None
    #: Landmark distance fields over the 2D projection, indexed
    #: ``(x - gx0) * gh + (y - gy0)``, with ``-1`` for a column the landmark
    #: cannot reach.  Empty until :meth:`build_landmarks` is called, which only
    #: :func:`_route_all` does -- see :data:`_ALT_LANDMARKS`.
    alt: tuple[list[int], ...] = ()

    def index(self, cell: tuple[int, int, int]) -> int:
        x, y, lvl = cell
        return (x - self.gx0) * self.xstep + (y - self.gy0) * LEVELS + lvl

    def block(self, cell: tuple[int, int, int]) -> None:
        """Mark a committed path cell impassable."""
        self.occ[self.index(cell)] = 0

    def restore(self, cell: tuple[int, int, int]) -> None:
        """Undo :meth:`block` -- back to whatever the cell was before routing."""
        at = self.index(cell)
        self.occ[at] = self.base[at]

    def _passable_columns(self) -> bytearray:
        """The 2D projection of ``base``: a column is open if any level is.

        Built by OR-ing the ``LEVELS`` strided views of ``base`` together as one
        big integer, because a Python loop over 26k columns is 15ms and this is
        microseconds.  ``base`` is already zero outside the routing box and in
        the two-cell pad, so the pad keeps ``p +- 1`` and ``p +- gh`` in range
        for every passable column and no neighbour test needs a bounds check.
        """
        mv = memoryview(self.base)
        acc = int.from_bytes(bytes(mv[0 :: LEVELS]), "big")
        for lvl in range(1, LEVELS):
            acc |= int.from_bytes(bytes(mv[lvl :: LEVELS]), "big")
        npro = self.size // LEVELS
        return bytearray(acc.to_bytes(npro, "big"))

    def _sweep(self, source: int, passable: bytearray) -> list[int]:
        """Breadth-first step distances from one column. ``-1`` is unreachable."""
        gh = self.gh
        dist = [-1] * len(passable)
        dist[source] = 0
        frontier = [source]
        step = 0
        while frontier:
            step += 1
            nxt: list[int] = []
            push = nxt.append
            for p in frontier:
                for q in (p - 1, p + 1, p - gh, p + gh):
                    if passable[q] and dist[q] < 0:
                        dist[q] = step
                        push(q)
            frontier = nxt
        return dist

    def build_landmarks(self, count: int) -> None:
        """Choose ``count`` landmarks farthest-point and sweep each one.

        Farthest-point rather than corners: the point of a landmark is to sit
        somewhere whose dial separates cells a wall separates, and the corners of
        a rectangle mostly reproduce Manhattan.  Each round picks the column
        farthest from everything chosen so far, which is the standard
        construction and needs no knowledge of the pack.
        """
        if count <= 0:
            return
        passable = self._passable_columns()
        seed = passable.find(1)
        if seed < 0:
            return
        # One throwaway sweep first: starting farthest-point from an ARBITRARY
        # column would put the first landmark wherever the pack's first free
        # column happens to be.
        far = self._sweep(seed, passable)
        best_at, best_d = seed, 0
        for p, d in enumerate(far):
            if d > best_d:
                best_at, best_d = p, d
        fields: list[list[int]] = []
        reach: list[int] = []
        for _ in range(count):
            field_ = self._sweep(best_at, passable)
            fields.append(field_)
            if not reach:
                reach = field_[:]
            else:
                for p, d in enumerate(field_):
                    prev = reach[p]
                    if d >= 0 and (prev < 0 or d < prev):
                        reach[p] = d
            best_at, best_d = -1, -1
            for p, d in enumerate(reach):
                if d > best_d:
                    best_at, best_d = p, d
            if best_at < 0:
                break
        self.alt = tuple(fields)

    def refresh_history(self, history: Mapping[tuple[int, int, int], float]) -> None:
        """Re-flatten ``history``, which changes once per rip-up round."""
        if not history:
            self.hist = None
            return
        lo_x, lo_y, hi_x, hi_y = self.box
        flat = [0.0] * self.size
        gx0, gy0, xstep = self.gx0, self.gy0, self.xstep
        for (cx, cy, clvl), used in history.items():
            if lo_x <= cx <= hi_x and lo_y <= cy <= hi_y and 0 <= clvl < LEVELS:
                flat[(cx - gx0) * xstep + (cy - gy0) * LEVELS + clvl] = used
        self.hist = flat


def _span_for(
    box: tuple[int, int, int, int],
    starts: Sequence[tuple[int, int, int]],
    goals: Sequence[tuple[int, int, int]],
) -> tuple[int, int, int, int]:
    """The indexed extent for a one-off grid: the box, its cells, and two of pad.

    A start may sit outside ``bounds`` -- an external input run begins on the
    entry ring and works inward -- and a goal that is also a start has to be
    recognised, so both are covered even though neither is passable.
    """
    lo_x, lo_y, hi_x, hi_y = box
    xs = [lo_x, hi_x]
    ys = [lo_y, hi_y]
    for cx, cy, _clvl in starts:
        xs.append(cx)
        ys.append(cy)
    for cx, cy, _clvl in goals:
        xs.append(cx)
        ys.append(cy)
    return (min(xs) - 2, min(ys) - 2, max(xs) + 2, max(ys) + 2)


def _route_box(
    canvas: _Canvas, bounds: tuple[int, int, int, int]
) -> tuple[int, int, int, int]:
    """``bounds`` intersected with the canvas limit -- where routing may go.

    Both are inclusive boxes and a cell must sit in BOTH, so they are intersected
    once rather than tested twice per neighbour.  A grid is only reusable for the
    box it was built for, so this has to give the same answer here and in
    :func:`_astar`.
    """
    lo_x, lo_y, hi_x, hi_y = bounds
    if canvas.limit is not None:
        lim_x0, lim_y0, lim_x1, lim_y1 = canvas.limit
        lo_x, lo_y = max(lo_x, lim_x0), max(lo_y, lim_y0)
        hi_x, hi_y = min(hi_x, lim_x1), min(hi_y, lim_y1)
    return (lo_x, lo_y, hi_x, hi_y)


def _canvas_span(canvas: _Canvas, box: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """The indexed extent for a grid shared across a whole routing pass.

    Two cells beyond ``canvas.limit`` when there is one, because every start and
    goal any net offers came through :meth:`_Canvas.free`, which refuses
    anything outside it -- so a limit-sized span is indexable for all of them.
    """
    if canvas.limit is None:
        lo_x, lo_y, hi_x, hi_y = box
        return (lo_x - 2, lo_y - 2, hi_x + 2, hi_y + 2)
    lim_x0, lim_y0, lim_x1, lim_y1 = canvas.limit
    return (lim_x0 - 2, lim_y0 - 2, lim_x1 + 2, lim_y1 + 2)


def _make_grid(
    canvas: _Canvas,
    box: tuple[int, int, int, int],
    span: tuple[int, int, int, int],
    history: Mapping[tuple[int, int, int], float],
) -> _Grid:
    """Flatten the canvas into a :class:`_Grid`. One pass over ``blocked``."""
    lo_x, lo_y, hi_x, hi_y = box
    gx0, gy0, gx1, gy1 = span
    gh = gy1 - gy0 + 1
    xstep = gh * LEVELS
    size = (gx1 - gx0 + 1) * xstep

    occ = bytearray(size)
    if lo_x <= hi_x and lo_y <= hi_y:
        run = b"\x01" * ((hi_y - lo_y + 1) * LEVELS)
        head = (lo_y - gy0) * LEVELS
        width = len(run)
        for gx in range(lo_x - gx0, hi_x - gx0 + 1):
            at = gx * xstep + head
            occ[at : at + width] = run
    holes = bytes(LEVELS)
    for cx, cy, clvl in canvas.blocked:
        if lo_x <= cx <= hi_x and lo_y <= cy <= hi_y and 0 <= clvl < LEVELS:
            occ[(cx - gx0) * xstep + (cy - gy0) * LEVELS + clvl] = 0
    for cx, cy in canvas.solid:
        if lo_x <= cx <= hi_x and lo_y <= cy <= hi_y:
            at = (cx - gx0) * xstep + (cy - gy0) * LEVELS
            occ[at : at + LEVELS] = holes
    for cx, cy in canvas.keep_out:
        if lo_x <= cx <= hi_x and lo_y <= cy <= hi_y:
            at = (cx - gx0) * xstep + (cy - gy0) * LEVELS
            occ[at : at + LEVELS] = holes
    reserved = tuple(
        ((cx - gx0) * xstep + (cy - gy0) * LEVELS + clvl, port)
        for (cx, cy, clvl), port in canvas.reserved.items()
        if lo_x <= cx <= hi_x and lo_y <= cy <= hi_y and 0 <= clvl < LEVELS
    )
    grid = _Grid(
        box=box,
        span=span,
        gx0=gx0,
        gy0=gy0,
        gh=gh,
        xstep=xstep,
        size=size,
        base=bytes(occ),
        occ=occ,
        reserved=reserved,
        hist=None,
    )
    grid.refresh_history(history)
    return grid


def _astar(
    canvas: _Canvas,
    starts: list[tuple[int, int, int]],
    goals: set[tuple[int, int, int]],
    history: dict[tuple[int, int, int], float],
    pressure: float,
    bounds: tuple[int, int, int, int],
    budget: dict[str, int] | None = None,
    deadline: float | None = None,
    blame: dict[tuple[int, int, int], float] | None = None,
    grid: _Grid | None = None,
) -> list[tuple[int, int, int]] | None:
    """Cheapest free-cell path, with congestion history folded into the cost.

    The history term is what makes rip-up-and-reroute converge: a cell that
    several nets have fought over becomes progressively more expensive, so they
    negotiate rather than oscillate.

    ``blame`` is how a search that finds NOTHING still says something.  A
    committed path is ``blocked`` here rather than expensive, so nets never
    overlap and the plain history term only ever records that a cell was used,
    never that using it walled somebody in.  When the heap empties -- and only
    then -- the settled set is the reachable pocket and its blocked neighbours
    are the wall; the committed cells among them are recorded here and priced by
    :func:`_route_all`.  See :data:`_BLAME_MAX_WALL` for why only a small wall
    is worth accusing.

    ``deadline`` is the caller's wall clock, checked every
    :data:`_DEADLINE_CHECK_EVERY` expansions.  A single hard net can spend
    ``_MAX_EXPANSIONS`` nodes, which is seconds on its own, so a deadline that
    only the callers looked at would be a deadline the router could sail past.
    Running out of clock returns ``None``, which is already the route-failure
    path -- and a route failure is a REFUSAL, since ``_sweep`` discards any pack
    with an unrouted net.  A deadline can therefore cost a placement but can
    never degrade one.

    ``bounds`` is the INCLUSIVE box the path may occupy.  It used to be the
    block's bounding box with two tiles of slack added here, which meant the
    caller could not say where the router was allowed to go -- and the router
    going two tiles past a boundary the caller had already promised to somebody
    else is what walled in the external entry lanes.  Start cells are exempt:
    an external input run begins on the entry ring, outside the routing box, and
    works inward.

    THE SEARCH RUNS ON FLAT INTEGER CELL INDICES, not on ``(x, y, level)``
    tuples -- see :class:`_Grid`, which is where the index and its constraints
    are written down.  It is worth roughly 1.8x on this loop, because the wall
    here has always been the interpreter rather than the algorithm and a tuple
    key charges for it twice: once to build the tuple and once to hash it.

    ``grid`` is the caller's, and passing one is the difference between building
    that flattening once for a routing pass and building it 589 times.  Omitting
    it is correct and merely costs a build; :func:`_route_all` passes one and
    keeps it current.
    """
    if not goals:
        return None
    if (budget is not None and budget["left"] <= 0) or _expired(deadline):
        return None

    # Start cells stay exempt from `bounds` -- an external input run begins on
    # the entry ring, outside the routing box, and works inward -- so they are
    # still admitted by `canvas.free`, which applies `limit` and not `bounds`.
    box = _route_box(canvas, bounds)
    goal_list = list(goals)

    # REUSE THE CALLER'S GRID IF IT IS THE SAME BOX, because building one is
    # 9.79ms on a `universe-matrix` canvas and a routing pass makes 589 calls --
    # 5.77s of a 19.5s pass, all of it re-deriving something that changed by a
    # few dozen cells.  `_route_all` builds one and keeps it current; every other
    # caller gets one of its own, which is still far cheaper than the tuple-keyed
    # search it replaces.
    #
    # Every start and goal reached this function through `canvas.free`, which
    # applies `canvas.limit`, and the shared grid spans that limit with two
    # cells of pad -- so they are indexable by construction.  Checked anyway,
    # because an index that silently lands in the wrong column is exactly the
    # kind of fault that reads green.
    flat = grid if grid is not None and grid.box == box else None
    if flat is not None:
        sx0, sy0, sx1, sy1 = flat.span
        for cx, cy, clvl in starts:
            if not (sx0 <= cx <= sx1 and sy0 <= cy <= sy1 and 0 <= clvl < LEVELS):
                flat = None
                break
    if flat is not None:
        sx0, sy0, sx1, sy1 = flat.span
        for cx, cy, clvl in goal_list:
            if not (sx0 <= cx <= sx1 and sy0 <= cy <= sy1 and 0 <= clvl < LEVELS):
                flat = None
                break
    if flat is None:
        flat = _make_grid(canvas, box, _span_for(box, starts, goal_list), history)

    gx0, gy0, gh, xstep, size = flat.gx0, flat.gy0, flat.gh, flat.xstep, flat.size
    ystep = LEVELS

    # A private copy, because the reservations a net may use are its own and
    # `routing_ports` is rebound per net.  Copying 84KB is a memcpy; rebuilding
    # it from four containers is not.
    flags = bytearray(flat.occ)
    routing_ports = canvas.routing_ports
    for at, port in flat.reserved:
        if port not in routing_ports:
            flags[at] = 0

    # Round one of rip-up has no history yet, and round one is the round that
    # usually succeeds. Skipping the array and the multiply there costs one
    # branch on the rounds that do have history.
    hist = flat.hist
    negotiating = hist is not None
    if hist is None:
        hist = []

    # Heuristic: Manhattan distance to the NEAREST goal, in grid-local
    # coordinates so a popped cell's decoded position can be used directly.
    #
    # This used to use the goals' centroid, which is not admissible when the
    # goals are spread out and -- worse -- never reaches 0 at an actual goal.
    # That turned A* into a badly-guided Dijkstra that expanded in every
    # direction, which is what made routing take tens of seconds.
    #
    # Exact min is best but costs O(|goals|) per node, so fall back to distance
    # to the goals' bounding box once that would dominate. The box distance is
    # still admissible (it under-estimates), just weaker.
    if len(goal_list) == 1:
        # By far the commonest shape -- a port with one free neighbour -- and
        # the generator, the `min` and the `float` around them were 17% of the
        # profile between them. One goal needs none of the three.
        only_x = goal_list[0][0] - gx0
        only_y = goal_list[0][1] - gy0

        def h(x: int, y: int) -> float:
            dx = x - only_x
            dy = y - only_y
            return (dx if dx >= 0 else -dx) + (dy if dy >= 0 else -dy)

    elif len(goal_list) <= _EXACT_HEURISTIC_GOALS:
        near = [(c[0] - gx0, c[1] - gy0) for c in goal_list]

        def h(x: int, y: int) -> float:
            return float(min(abs(x - fx) + abs(y - fy) for fx, fy in near))

    else:
        bx0 = min(c[0] for c in goal_list) - gx0
        bx1 = max(c[0] for c in goal_list) - gx0
        by0 = min(c[1] for c in goal_list) - gy0
        by1 = max(c[1] for c in goal_list) - gy0

        def h(x: int, y: int) -> float:
            return float(max(0, bx0 - x, x - bx1) + max(0, by0 - y, y - by1))

    # AND THE PART THAT KNOWS WHERE THE MACHINES ARE -- see `_ALT_LANDMARKS`.
    #
    # For each landmark, the goals occupy a band ``[lo, hi]`` on its dial, and a
    # cell at ``d`` is at least ``lo - d`` or ``d - hi`` steps from the nearest
    # of them.  Reducing the goal set to a band rather than taking a minimum per
    # goal is what keeps this O(landmarks) instead of O(landmarks x goals): it
    # is weaker, and it is the same weakening the bounding box above already
    # makes.
    #
    # A landmark that cannot reach one of the goals is DROPPED, not clamped.
    # Its band would then cover only the goals it can see, and a cell measured
    # against that band could be charged more than its distance to the goal the
    # band left out -- which is the one way this could stop being a lower bound.
    bands: list[tuple[list[int], int, int]] = []
    for field_ in flat.alt:
        lo = hi = -1
        for c in goal_list:
            at = (c[0] - gx0) * gh + (c[1] - gy0)
            dial = field_[at]
            if dial < 0:
                lo = -1
                break
            if lo < 0 or dial < lo:
                lo = dial
            if dial > hi:
                hi = dial
        if lo >= 0:
            bands.append((field_, lo, hi))

    if bands:
        plain = h

        def h(x: int, y: int) -> float:  # noqa: F811
            far = plain(x, y)
            at = x * gh + y
            for field_, lo, hi in bands:
                dial = field_[at]
                if dial < 0:
                    continue
                gap = lo - dial
                if gap > far:
                    far = gap
                gap = dial - hi
                if gap > far:
                    far = gap
            return far

    goal_idx = {
        (c[0] - gx0) * xstep + (c[1] - gy0) * ystep + c[2] for c in goal_list
    }

    # (dx, dy, one-step offset, two-step offset) -- the ramp's run cell is the
    # plain step's target, so one pass over the four directions does both.
    moves = tuple(
        (dx, dy, dx * xstep + dy * ystep, 2 * (dx * xstep + dy * ystep))
        for dx, dy in _STEPS
    )

    expansions = 0
    heappush = heapq.heappush
    heappop = heapq.heappop
    inf = math.inf
    level_toll = _LEVEL_TOLL

    open_heap: list[tuple[float, float, int]] = []
    best = [inf] * size
    prev = [-1] * size
    #: Ramp moves span two cells.  The intermediate "run" cell is recorded here
    #: rather than in ``prev``, because giving it a predecessor of its own lets a
    #: later ramp clobber a predecessor the normal step expansion already set --
    #: which can point a cell's chain back through itself and make ``prev`` cyclic.
    via: dict[int, int] = {}
    via_get = via.get
    for s in starts:
        if not canvas.free(s):
            continue
        si = (s[0] - gx0) * xstep + (s[1] - gy0) * ystep + s[2]
        best[si] = 0.0
        prev[si] = -1
        heappush(open_heap, (h(s[0] - gx0, s[1] - gy0), 0.0, si))

    while open_heap:
        _, g, cur = heappop(open_heap)
        if g > best[cur]:
            continue
        expansions += 1
        if expansions > _MAX_EXPANSIONS:
            return None
        if expansions % _DEADLINE_CHECK_EVERY == 0 and _expired(deadline):
            return None
        if budget is not None:
            budget["left"] -= 1
            if budget["left"] <= 0:
                return None
        if cur in goal_idx:
            path = []
            node = cur
            # ``prev`` must be acyclic; walking a cycle here previously spun at
            # 100% CPU while ``path`` grew without bound.  Guard it rather than
            # trusting it, so a regression fails loudly instead of hanging.
            seen: set[int] = set()
            while node != -1:
                if node in seen:
                    q, lvl = divmod(node, LEVELS)
                    px, py = divmod(q, gh)
                    raise AssertionError(
                        f"cycle in A* predecessor chain at "
                        f"{(px + gx0, py + gy0, lvl)}; "
                        "a ramp move corrupted an existing predecessor"
                    )
                seen.add(node)
                q, lvl = divmod(node, LEVELS)
                px, py = divmod(q, gh)
                path.append((px + gx0, py + gy0, lvl))
                run = via_get(node, -1)
                if run != -1:
                    q, lvl = divmod(run, LEVELS)
                    px, py = divmod(q, gh)
                    path.append((px + gx0, py + gy0, lvl))
                node = prev[node]
            return _cut_loops(list(reversed(path)))
        q, lvl = divmod(cur, LEVELS)
        x, y = divmod(q, gh)
        # A plain step stays on `lvl`, so its toll is fixed for this expansion.
        step_toll = 1.0 + level_toll[lvl]
        # ONE pass over the four directions, doing the plain step and the two
        # ramps that share its ground cell.
        #
        # A ramp's lower half IS the plain step's target, so the separate ramp
        # loop was re-deriving and re-testing a cell the step loop had just
        # tested, twice over for the two level changes.  Fusing them tests each
        # ground cell once and skips both its ramps the moment it is blocked,
        # which on a dense pack is most of the time.
        #
        # Exactly equivalent, not merely close: a ramp lands on ``lvl +- 1`` and
        # a step stays on ``lvl``, so no ramp and no step of one expansion ever
        # touch the same cell, and interleaving them cannot change which of two
        # equal-cost paths is recorded.
        for dx, dy, one, two in moves:
            nxt = cur + one
            if not flags[nxt]:
                continue

            cost = g + step_toll
            if negotiating:
                cost += hist[nxt] * pressure
            if cost < best[nxt]:
                best[nxt] = cost
                prev[nxt] = cur
                # A plain step reaches `nxt` directly, so any ramp via-cell
                # recorded by an earlier, worse ramp is now stale.  Leaving it
                # splices a cell that is not on the path into the result, which
                # shows up as a belt linking diagonally across a level change.
                if via:
                    via.pop(nxt, None)
                heappush(open_heap, (cost + h(x + dx, y + dy), cost, nxt))

            # A level change costs two tiles of run, because belts climb 0.5 per
            # tile.  Both are reserved so the ramp physically exists -- and the
            # lower one is `nxt`, already cleared above.
            run = cur + two
            for step in (1, -1):
                lvl2 = lvl + step
                if not 0 <= lvl2 < LEVELS:
                    continue
                top = run + step
                if not flags[top]:
                    continue
                cost = g + 3.0 + level_toll[lvl2]
                if negotiating:
                    cost += hist[top] * pressure
                if cost < best[top]:
                    best[top] = cost
                    # The ramp is ONE edge cur -> top that happens to occupy an
                    # extra cell.  Record `nxt` as a via, never as a node with
                    # its own predecessor: it may already lie on another cell's
                    # best path, and reassigning its predecessor is what made
                    # `prev` cyclic.
                    prev[top] = cur
                    via[top] = nxt
                    heappush(
                        open_heap,
                        (cost + h(x + 2 * dx, y + 2 * dy), cost, top),
                    )

    # THE HEAP EMPTIED, which is the one ending that proves no path exists -- the
    # `return None`s above are a spent cap, a spent budget or a spent clock, and
    # none of those says the pocket is sealed. So the cells with a finite `best`
    # are exactly the free space this net could reach and the blocked cells
    # touching it are its wall. The ones a committed path put there are the only
    # wall cells any net owns, and `_route_all` charges them so the net holding
    # one pays to keep it.
    if blame is not None:
        # `best` is a flat array rather than a dict now, so the pocket is
        # counted by scanning it. That scan only ever happens on the ending that
        # proves the pocket sealed, and it stops as soon as the pocket is too
        # big to accuse anybody.
        pocket = []
        for i, seen_at in enumerate(best):
            if seen_at != inf:
                pocket.append(i)
                if len(pocket) > _BLAME_MAX_POCKET:
                    break
        if len(pocket) <= _BLAME_MAX_POCKET:
            blocked_get = canvas.blocked.get
            #: The wall as a SET, because its size is the question
            #: `_BLAME_MAX_WALL` asks -- a wall of three has named a suspect, a
            #: wall of three thousand has named the whole corridor network.
            #: Counting a cell once per adjacent pocket cell would make a long
            #: thin pocket look guiltier than a fat one for the same wall.
            wall: set[tuple[int, int, int]] = set()
            for i in pocket:
                q, blvl = divmod(i, LEVELS)
                bx, by = divmod(q, gh)
                bx += gx0
                by += gy0
                for dx, dy in _STEPS:
                    cell = (bx + dx, by + dy, blvl)
                    if blocked_get(cell) == _TENTATIVE:
                        wall.add(cell)
            if len(wall) <= _BLAME_MAX_WALL:
                for cell in wall:
                    blame[cell] = blame.get(cell, 0.0) + 1.0
    return None

@dataclass
class _Net:
    src: _Port
    dst: _Port
    item: str


def _merge_frontier(
    canvas: _Canvas,
    paths: dict[int, list[tuple[int, int, int]]],
    siblings: tuple[int, ...],
) -> set[tuple[int, int, int]]:
    """Free cells beside a sibling net's path -- somewhere to merge into.

    Two belts feeding one is a side merge, which the game allows and
    ``_build_runs`` already models (a tile with two predecessors heads its own
    run).  Reaching a sibling's belt is therefore as good as reaching the lane
    it feeds, and it is the ONLY option when the lane itself is walled in.

    The sibling's own cells are not offered as goals: they are occupied, so A*
    could never step onto them.  Their free neighbours are what a merging belt
    actually needs.
    """
    out: set[tuple[int, int, int]] = set()
    for s in siblings:
        for x, y, lvl in paths.get(s, ()):
            for dx, dy in _STEPS:
                cell = (x + dx, y + dy, lvl)
                if canvas.free(cell):
                    out.add(cell)
    return out


def _route_all(
    canvas: _Canvas,
    nets: list[_Net],
    belt_id: int,
    belt_model: int,
    bounds: tuple[int, int, int, int],
    deadline: float | None = None,
    budget: dict[str, int] | None = None,
) -> tuple[int, int, int]:
    """Route every net, negotiating congestion across iterations.

    Returns ``(routed, failed, iterations)``.  Failures are counted and returned
    rather than raised: the caller decides whether to repair, and a silently
    swallowed failure is exactly the bug that made Strategy A ship a fallback
    wearing a solver's clothes.

    THIS LOOP IS THE OVERRUN.  Up to :data:`RRR_MAX` rounds, each re-routing
    every net, each net allowed :data:`_MAX_EXPANSIONS` nodes -- bounded in
    expansions by :data:`_ROUTING_BUDGET` and, until now, not bounded in seconds
    at all.  A caller asking for four seconds got ten of these per sweep and two
    sweeps, which is how ``quantum-chip`` measured at 80 seconds against a
    nominal 4.

    So ``deadline`` is checked between rounds AND between nets, and running out
    of it abandons the pass with every net counted failed.  That is deliberately
    the harshest reading: an expired routing pass must not be able to hand back
    a partially wired canvas that some later stage mistakes for a result.  The
    caller discards any pack with a failure, so the deadline can cost a
    placement and can never degrade one.
    """
    history: dict[tuple[int, int, int], float] = defaultdict(float)
    #: The live routing -- net index to path -- and the same cells the other way
    #: round.  ``owner`` is what makes a TARGETED rip-up possible: a repair
    #: search that crosses a belt has to be able to say WHOSE belt it crossed.
    #: They are staked and unstaked together, always through `_stake`/`_unstake`,
    #: because `canvas.blocked`, `grid.occ` and `owner` disagreeing is a router
    #: that quietly routes through a committed belt.
    paths: dict[int, list[tuple[int, int, int]]] = {}
    owner: dict[tuple[int, int, int], int] = {}
    iterations = 0
    # A TOTAL expansion budget across every net and every rip-up round.
    #
    # `_MAX_EXPANSIONS` bounds one search; nothing bounded the product. At
    # 470-machine scale that is ~50 nets x 8 rounds x 200k = up to 80M
    # expansions, which ran for over fifteen minutes -- not a hang, just work
    # nobody had bounded. A shared budget is deterministic (no wall clock, so
    # runs stay reproducible) and degrades honestly: an exhausted search returns
    # None, which is already the route-failure path the caller repairs from and
    # records in `route_failures`.
    # ONE budget for the whole `lay_out` call when the caller supplies it, so
    # the sweep's ten-to-twenty routing passes cannot each spend
    # `_ROUTING_BUDGET` afresh. A caller reaching in directly gets a pass of its
    # own, which is what the tests and the probes want.
    if budget is None:
        budget = {"left": _ROUTING_BUDGET}
    fewest_failed = len(nets) + 1
    stale = 0
    #: The BEST round's paths, not the last round's.
    #:
    #: What gets committed used to be whichever round the loop happened to stop
    #: on, and the shared expansion budget makes the last round systematically
    #: the WORST one: round 1 spends the budget, every round after it has
    #: nothing left to search with, and `_astar` returns `None` for every net
    #: before expanding a node. Committing that round throws away a perfectly
    #: good routing and reports the pack unwireable.
    #:
    #: Measured on universe-matrix/max-proliferation: two of the five candidate
    #: heights reported `routed=0 failed=115` -- every net -- while their first
    #: round had routed roughly seventy of them. Rip-up-and-reroute is a search
    #: over rounds; keeping the incumbent is what makes it one.
    best_paths: dict[int, list[tuple[int, int, int]]] = {}

    _reserve_port_access(canvas, nets)

    # ONE flattening of the canvas for the whole pass, kept current instead of
    # rebuilt.
    #
    # `_astar` searches on flat integer cell indices and needs the canvas as
    # flat arrays to do it. Building those is a pass over `blocked` -- measured
    # at 9.79ms on `universe-matrix`, and a pass makes 589 searches, so 5.77s of
    # a 19.5s routing pass went on re-deriving something that changes by a few
    # dozen cells between calls. The reservations have to be staked first, since
    # they are part of what the flattening records.
    #
    # It is maintained at exactly two places, the same two that write
    # `_TENTATIVE` into `canvas.blocked`: `_stake` when a path commits and
    # `_unstake` when it is ripped up, whether by a round or by a repair.
    # History is re-flattened once per round. Any further writer to `blocked`
    # inside this loop must go through those two -- an `occ` that disagrees with
    # `blocked` is a router that quietly routes through a committed belt.
    grid_box = _route_box(canvas, bounds)
    grid = _make_grid(canvas, grid_box, _canvas_span(canvas, grid_box), history)
    # The landmark sweeps go here and NOT in `_make_grid`, because they are only
    # worth their build to a caller that will make hundreds of searches against
    # one grid.  Everybody else routes a handful of nets and gets Manhattan.
    grid.build_landmarks(_ALT_LANDMARKS)

    # Nets that end at the same lane. Ordered, so "the ones before me" is
    # well defined however the router chooses to sequence a round.
    same_dst: dict[tuple[int, int], list[int]] = defaultdict(list)
    for i, net in enumerate(nets):
        same_dst[net.dst.x, net.dst.y].append(i)
    dst_group = {
        i: tuple(g for g in same_dst[net.dst.x, net.dst.y] if g != i)
        for i, net in enumerate(nets)
    }
    # The same story on the producer side, and it needs the same answer. An
    # out-lane sandwiched between its neighbours is only reachable at its ends,
    # so walking it tile by tile hands the later nets a walled-in start. They
    # BRANCH instead: leave from a sibling's path, which becomes a splitter on
    # that path at commit time. Keyed by the LANE (row and west edge), not the
    # port, because `at_tile` moves the port along the lane it belongs to.
    same_src: dict[tuple[int, int], list[int]] = defaultdict(list)
    for i, net in enumerate(nets):
        same_src[net.src.y, net.src.x0].append(i)
    src_group = {
        i: tuple(g for g in same_src[net.src.y, net.src.x0] if g != i)
        for i, net in enumerate(nets)
    }
    # Chained nets -- one net leaving the belt another delivers to, which is what
    # `_proliferator_nets` builds -- used to be allowed to merge into each
    # other's paths in both directions. Neither direction survives inspection.
    #
    # Arriving at a path that LEAVES a belt does not fill that belt: flow runs
    # the other way. A net that "reached" its destination that way carried its
    # items PAST the drop rather than into it, so the coater sprayed nothing and
    # the drop read as an entry lane the player must fill, buried mid-block.
    #
    # Leaving from a path that ARRIVES at the belt does deliver the items, but
    # it builds a SPLITTER on that path to do it, and a branch drawn off a
    # splitter is a belt run of its own that nothing inside the blueprint fills
    # -- the same unreachable entry lane by a different route.
    #
    # What both were standing in for is a drop with two ways in, one for the hop
    # arriving and one for the hop leaving. `_reserve_port_access` holds both,
    # and `_proliferator_nets` links neighbouring drops directly rather than
    # routing between them, so a drop with only one free neighbour never needs a
    # second. That leaves the chain a single linear run, which is the only shape
    # that is both correct and reachable.

    def _stake(index: int, path: list[tuple[int, int, int]]) -> None:
        """Put a path down: canvas, grid and ownership, in step."""
        paths[index] = path
        for cell in path:
            canvas.blocked[cell] = _TENTATIVE
            grid.block(cell)
            owner[cell] = index

    def _unstake(index: int) -> None:
        """Take a path up again, leaving no trace in any of the three."""
        for cell in paths.pop(index):
            if canvas.blocked.get(cell, -1) == _TENTATIVE:
                del canvas.blocked[cell]
                grid.restore(cell)
            if owner.get(cell) == index:
                del owner[cell]

    def _ends(index: int) -> tuple[
        list[tuple[int, int, int]], set[tuple[int, int, int]]
    ]:
        """This net's start and goal cells, and its port claim as a side effect.

        Factored out because the repair pass has to ask the SAME question the
        round asks.  A repair that built its ends differently would find a path
        the committer cannot attach at either end -- which is precisely the class
        of bug `3f04239` and `00d1f78` were.  The caller clears
        ``canvas.routing_ports`` once its search returns.
        """
        net = nets[index]
        # Claim this net's port reservations for the duration of its search,
        # so its own way in and out reads as free while every other port's
        # stays held.
        canvas.routing_ports = frozenset(
            {(net.src.x, net.src.y), (net.dst.x, net.dst.y)}
        )
        starts = [
            (net.src.x + dx, net.src.y + dy, 0)
            for dx, dy in _STEPS
            if canvas.free((net.src.x + dx, net.src.y + dy, 0))
        ]
        # Leaving from a sibling's belt is as good as leaving from the lane,
        # and it is the only option when the lane is walled in. `_tap_source`
        # turns the attachment into a splitter on that belt.
        starts.extend(
            sorted(_merge_frontier(canvas, paths, src_group.get(index, ())) - set(starts))
        )
        goals = {
            (net.dst.x + dx, net.dst.y + dy, 0)
            for dx, dy in _STEPS
            if canvas.free((net.dst.x + dx, net.dst.y + dy, 0))
        }
        # A lane head has one way in. When several producers feed the same
        # lane, only the first can use it; the rest MERGE into whatever
        # already got there, which is what converging belts do in game. The
        # goal set therefore grows to include the free cells beside every
        # path already laid this round for the same destination -- reaching
        # one of those is reaching the lane.
        for cell in _merge_frontier(canvas, paths, dst_group.get(index, ())):
            goals.add(cell)
        return starts, goals

    def _repair(
        stranded: list[int], pressure: float, blame: dict[tuple[int, int, int], float]
    ) -> list[int]:
        """Place stranded nets by CROSSING settled belts and moving those.

        A round is greedy sequential routing, so a net that reaches a full
        corridor last simply fails, and the next round runs the same nets in the
        same order against a map that differs only in price.  On
        `universe-matrix` that costs 3.1-4.0s a round to shuffle one or two
        failures about, and the sweep's whole ceiling buys three or four of them.

        What the failure IS, every time it has been looked at, is contention and
        never geometry.  Re-searching each stranded net on a grid where settled
        belts are passable found a path for all 31 stranded nets across five
        packs, in 0.001-0.025s each, and every one crossed between 1 and 11 of
        the 93-140 paths already down.  So: take that path, rip up only the
        handful it crosses, and send those looking again.  It is aimed at the
        nets that are actually in the way rather than at all of them, and it is
        roughly twenty-five times cheaper than the round it saves.

        This is also the overuse signal negotiation never had here.  A settled
        path is `blocked` rather than dear, so two nets never overlap and the
        history term can only ever record that a cell was USED.  A crossing
        search is the one place this router learns that a cell was WANTED by
        somebody who could not have it.

        Returns whatever is still stranded, which the caller counts as failed.
        """
        if not stranded:
            return stranded
        # A grid whose belts are passable but dear.  `base` is the occupancy
        # before any path settled, so restoring it opens exactly the cells this
        # pass has taken -- machines, keep-outs and the routing box stay shut.
        open_grid = replace(grid, occ=bytearray(grid.base), hist=None)
        # The crossing charge rides on the history array, so the repair search
        # prices congestion exactly as the round does and adds a toll on top.
        # `pressure` is folded in here and the search is given 1.0, which keeps
        # the toll a fixed number of tiles rather than one that grows with the
        # round number.
        settled = grid.hist
        crossing = (
            [0.0] * grid.size if settled is None else [v * pressure for v in settled]
        )
        for cell in owner:
            crossing[grid.index(cell)] += _REPAIR_CROSSING
        open_grid.hist = crossing

        def _leaning(on: set[int]) -> set[int]:
            """Grow a victim set to everything that LEANS on it, transitively.

            A net whose lane head is already taken merges instead: it ends
            beside a sibling's belt and `_commit_paths` links it to that belt.
            So moving a path can leave another path ending against nothing, and
            `_commit_paths` counts that as unlinked -- a route failure by a
            different name and just as fatal to the pack.

            Measured, and it is not a corner: displacing victims without this,
            every one of thirteen `universe-matrix` packs routed MORE nets and
            then failed to link between 2 and 20 of them, against 0 or 1
            unlinked with no repair at all.  The repair was trading a stranded
            net for a stranded belt.

            A leaner is found from the CURRENT arrangement rather than from what
            was true when it routed, because `_commit_paths` also decides at the
            end: whatever sits beside a path's ends now is what it will attach
            to.

            TOUCHING IS NOT THE SAME AS DEPENDING, and the difference is worth
            two tests rather than one.  Plain adjacency grew a displacement of 0
            to 4 paths into a victim set of 10 to 21 -- past
            `_REPAIR_MAX_VICTIMS`, so the repair spent its searches declining
            and a routing pass cost three to seven times what it needed to.

            A net is held up by a path it touches when EITHER of these holds:

            * the path is a SIBLING, sharing its source lane or its destination
              lane.  That is the only kind of path `_ends` offers it to merge
              into and the only kind `_source_for` and `_sink_for` will accept,
              so a belt merely running past somebody's elbow is not the thing
              holding them up.
            * the path is the ONLY one at that end of it.  Restricting to
              siblings alone was measured and lets 1 to 4 nets per pack finish
              beside nothing -- fast, and paying for the speed in exactly the
              currency the repair exists to save.

            Two narrow tests rather than one broad one: `unlinked` goes back to
            zero and the victim sets stay small.
            """
            touch: dict[tuple[int, int, int], set[int]] = {}
            #: Paths that are somebody's ONLY neighbour at one of their ends.
            sole: dict[int, set[int]] = {}
            for other, path in paths.items():
                for end in (path[0], path[-1]):
                    near: set[int] = set()
                    for dx, dy in _STEPS:
                        beside = (end[0] + dx, end[1] + dy, end[2])
                        touch.setdefault(beside, set()).add(other)
                        held = owner.get(beside)
                        if held is not None and held != other:
                            near.add(held)
                    if len(near) == 1:
                        sole.setdefault(other, set()).update(near)
            grown = set(on)
            queue = list(on)
            while queue and len(grown) <= _REPAIR_MAX_VICTIMS:
                leant_on = queue.pop()
                for cell in paths[leant_on]:
                    for other in touch.get(cell, ()):
                        if other in grown:
                            continue
                        if (
                            leant_on in src_group.get(other, ())
                            or leant_on in dst_group.get(other, ())
                            or leant_on in sole.get(other, ())
                        ):
                            grown.add(other)
                            queue.append(other)
            return grown

        def _stands_on(
            index: int,
            through: list[tuple[int, int, int]],
            victims: Set[int],
        ) -> bool:
            """Does ``through`` attach only to paths this swap is about to move?

            Asked at both ends and answered the way `_source_for` and
            `_sink_for` will answer it at commit time: an end beside its OWN
            lane needs nobody, and otherwise the only belts it may attach to are
            its siblings' -- so if every sibling beside it is a victim, it will
            end up beside nothing.  An end with no sibling beside it at all is
            not this swap's doing and is left alone.
            """
            net = nets[index]
            for end, port, group, slack in (
                (through[0], net.src, src_group, 0),
                (through[-1], net.dst, dst_group, 1),
            ):
                if (
                    abs(end[0] - port.x) + abs(end[1] - port.y) <= 1
                    and abs(end[2]) <= slack
                ):
                    continue
                kin = set(group.get(index, ()))
                beside = {
                    who
                    for dx, dy in _STEPS
                    if (who := owner.get((end[0] + dx, end[1] + dy, end[2]))) is not None
                } & kin
                if beside and beside <= set(victims):
                    return True
            return False

        still: list[int] = []
        for index in stranded:
            if _expired(deadline) or (budget is not None and budget["left"] <= 0):
                still.append(index)
                continue
            starts, goals = _ends(index)
            through = _astar(
                canvas, starts, goals, history, 1.0, bounds, budget, deadline,
                None, open_grid,
            )
            canvas.routing_ports = frozenset()
            if through is None:
                # Genuinely nowhere to go even with every belt open. That is a
                # sealed pocket in the PACK, which repair cannot argue with and
                # the next height can.
                still.append(index)
                continue
            victims = _leaning({owner[cell] for cell in through if cell in owner})
            victims.discard(index)
            if len(victims) > _REPAIR_MAX_VICTIMS:
                still.append(index)
                continue
            # AND IT MUST NOT SAW OFF THE BRANCH IT IS STANDING ON.
            #
            # `_leaning` protects every path that ends beside a victim -- except
            # the one net it cannot see, which is the stranded net itself.
            # `index` has no path yet, so it is in neither `paths` nor `owner`
            # and nothing grows it into the victim set; but `_ends` offered it
            # the free cells beside its SIBLINGS' paths as starts and goals, and
            # `through` may well have taken one. Displace that sibling and the
            # net we just placed ends beside nothing.
            #
            # Traced end to end on `universe-matrix/no-proliferator` power=1 at
            # h=185, where it was the ONLY defect left and fired every run:
            # net 46 settles ending at (81,99,2); net 49 strands, repairs, and
            # its path starts at (80,99,2) -- merged onto 46 -- with 46 among
            # its own victims; 46 is unstaked and comes back as a two-cell path
            # at (68,105,1); and 49 is left with an empty neighbourhood. It is
            # not counted as unrouted, because `_source_for`'s last resort still
            # names `net.src.belt` -- so the pack wired, `failed` read 0, and the
            # placement came back with a belt at (65,79,0) linking to one at
            # (80,99,2): `belt.link_adjacent` and `geom.altitude_step`, refused
            # by our own validator two layers later.
            #
            # Declining costs nothing this swap was going to keep. A repair that
            # places a net by unlinking it has placed nothing.
            if _stands_on(index, through, victims):
                still.append(index)
                continue
            # ALL OR NOTHING, and this is the whole difference between a repair
            # and a churn.
            #
            # Taken greedily -- displace the victims, keep whichever of them find
            # a way round -- this LOSES nets: measured on
            # `universe-matrix/no-proliferator` power=1 at h=185, a round that
            # stranded ONE net came out of the greedy repair stranding TEN,
            # because each swap cashed in a settled path for a chance. So the
            # swap is a transaction. Every displaced net must find a new route
            # or the whole thing is rolled back, which makes a repair pass
            # monotone: it can place a net or decline, never subtract one.
            saved = {hurt: paths[hurt] for hurt in victims}
            for hurt in victims:
                _unstake(hurt)
            _stake(index, through)
            # The displaced go looking for a way round, longest first for the
            # same reason the round orders that way.
            moved: list[int] = []
            for hurt in sorted(
                victims,
                key=lambda i: -(
                    abs(nets[i].src.x - nets[i].dst.x)
                    + abs(nets[i].src.y - nets[i].dst.y)
                ),
            ):
                starts, goals = _ends(hurt)
                again = _astar(
                    canvas, starts, goals, history, pressure, bounds, budget,
                    deadline, blame, grid,
                )
                canvas.routing_ports = frozenset()
                if again is None:
                    break
                _stake(hurt, again)
                moved.append(hurt)
            if len(moved) == len(victims):
                continue
            # Roll back to exactly the arrangement we found. The cells every
            # saved path wants are free again the moment the nets that took
            # them are lifted, because nothing outside this transaction moved.
            for hurt in moved:
                _unstake(hurt)
            _unstake(index)
            for hurt, was in saved.items():
                _stake(hurt, was)
            still.append(index)
        return still

    for it in range(RRR_MAX):
        iterations = it + 1
        for index in list(paths):
            _unstake(index)
        # `history` gained a round's worth of use and blame at the end of the
        # last iteration, and the search reads it flattened.
        grid.refresh_history(history)
        pressure = 0.5 * (1.6**it)
        failed = 0
        #: Cells that CUT the board this round, and how many nets each cut off.
        #:
        #: Fresh every round, because a wall only exists while the path that
        #: built it does; `history` is where the charge accumulates.
        blame: dict[tuple[int, int, int], float] = {}
        # PROMOTING LAST ROUND'S FAILURES to the front was tried here and is not
        # worth having.
        #
        # The reasoning was sound and the diagnosis behind it still is: a round
        # is greedy sequential routing -- a committed path is `blocked`, not
        # merely expensive -- so nets never overlap, the history term never sees
        # the overuse that PathFinder prices, and every round runs the same nets
        # in the same order against a slightly dearer map. A net that arrived
        # last to a full corridor arrives last again.
        #
        # Routing the same fifteen packs both ways, so the ONLY difference was
        # the order: five packs lost a failure, three gained one, seven were
        # unchanged -- and one of the three turned a pack that routed every net
        # into one that did not. Over the corpus it measured 60/72 clean at 4s,
        # exactly what the plain order measures, with the refusals merely
        # shuffled between cells. That is noise, not a fix, and an ordering rule
        # that can strand a net which was routing is not noise worth carrying.
        #
        # Length still orders everything. A long net has the most ways to be
        # obstructed and the fewest alternatives, so it goes first.
        order = sorted(
            range(len(nets)),
            key=lambda i: -(
                abs(nets[i].src.x - nets[i].dst.x) + abs(nets[i].src.y - nets[i].dst.y)
            ),
        )
        stranded: list[int] = []
        for i in order:
            if _expired(deadline):
                return 0, len(nets), iterations
            starts, goals = _ends(i)
            routed = _astar(
                canvas, starts, goals, history, pressure, bounds, budget, deadline,
                blame, grid,
            )
            canvas.routing_ports = frozenset()
            if routed is None:
                stranded.append(i)
                continue
            _stake(i, routed)
        # AND THE REPAIR, before conceding the round.
        #
        # Repeated while it keeps placing nets, because a displaced net that
        # strands in turn is the same problem one step along and answers to the
        # same move. It stops the moment a pass places nobody, which is when the
        # contention has stopped being local and negotiation should price it.
        for _ in range(_REPAIR_PASSES):
            if not stranded or _expired(deadline):
                break
            after = _repair(stranded, pressure, blame)
            if len(after) >= len(stranded):
                stranded = after
                break
            stranded = after
        failed = len(stranded)
        if failed == 0:
            unlinked = _commit_paths(
                canvas, nets, paths, belt_id, belt_model, src_group, dst_group
            )
            return len(paths) - unlinked, unlinked, iterations
        for path in paths.values():
            for cell in path:
                history[cell] += 1.0
        # AND A SURCHARGE ON THE CELLS THAT CUT THE BOARD.
        #
        # The point above says a cell was USED. It cannot say that using it cost
        # another net its only way through, because a committed path is `blocked`
        # rather than dear, so two nets never overlap and PathFinder's overuse
        # signal -- the thing a history term exists to carry -- is identically
        # zero here. Without this, every round re-runs the same nets in the same
        # order against a map that is uniformly, uselessly dearer.
        #
        # It is aimed at a defect that is provably the ROUTER'S and not the
        # packer's. The free space `_pack` hands over is ONE connected component:
        # on `universe-matrix/no-proliferator` at h=69, all 197 ports sit in a
        # single 54,077-cell region with none walled in, before a belt exists.
        # Every pocket the router then fails in was cut out by its own committed
        # paths -- greedy sequential routing painting itself into a corner it had
        # no way to price.
        #
        # A search whose heap emptied has PROVED its pocket sealed, `_astar`
        # names the committed cells in its wall, and a wall small enough to
        # accuse somebody (`_BLAME_MAX_WALL`) is charged in proportion to how
        # many nets it cut off. Next round the net holding one pays
        # `_BLAME_WEIGHT` times the plain rate to keep it, which buys a detour
        # instead of a dead end.
        #
        # Measured on the pack it was built for: h=69 commits 139 of 140 paths
        # without it and ALL 140 with it, in 24.6s rather than 36.7s, because a
        # round that stops fighting over one cell converges in fewer rounds.
        for cell, n in blame.items():
            history[cell] += _BLAME_WEIGHT * n
        # Give up once raising the pressure has stopped buying anything.
        #
        # Rip-up-and-reroute converges by making contested cells progressively
        # dearer, so a round that fails no fewer nets than the best round so far
        # is evidence the failures are not contention. Running the remaining
        # rounds anyway is the single largest cost in this strategy when a pack
        # cannot be wired -- and a pack that cannot be wired is exactly when
        # every round runs. Three rounds of no improvement before quitting,
        # because pressure grows geometrically and a late round can still break
        # a deadlock that earlier ones could not.
        if failed < fewest_failed:
            # A COPY. `paths` used to be rebuilt every round, so keeping the
            # reference kept a snapshot; it now persists across rounds and is
            # mutated in place by the rip-up and by the repair, so keeping the
            # reference would make "the best round" mean "the last one".
            fewest_failed, stale, best_paths = failed, 0, dict(paths)
        else:
            stale += 1
        # An exhausted expansion budget ends the search as surely as a stale
        # round does: every further round would re-run every net against a
        # budget of zero and fail all of them, and the counters would read as
        # congestion rather than as work nobody had left to do.
        if (
            stale >= _RRR_STALE_ROUNDS
            or it == RRR_MAX - 1
            or budget["left"] <= 0
            or _expired(deadline)
        ):
            break
    unlinked = _commit_paths(
        canvas, nets, best_paths, belt_id, belt_model, src_group, dst_group
    )
    return len(best_paths) - unlinked, fewest_failed + unlinked, iterations


def _match_access(
    order: Sequence[tuple[int, int]],
    options: Mapping[tuple[int, int], Sequence[tuple[int, int, int]]],
    wants: Mapping[tuple[int, int], int],
) -> dict[tuple[int, int, int], tuple[int, int]]:
    """Assign access cells to ports so that as many CLAIMS as possible are met.

    A claim is one port's need for one cell: a port that both receives and sends
    makes two, and :func:`_reserve_port_access` explains why they are not
    interchangeable.  Returns ``cell -> port``.

    This is a maximum bipartite matching between claims and cells, by augmenting
    paths.  The greedy alternative -- walk the ports and take the first free
    neighbour -- is not merely less tidy, it is *wrong*, because it never gives a
    cell back: a port with two ways out can take the one cell some other port
    has, and no later port can ask it to move.  An augmenting path is exactly the
    request "move, and take your second choice", chained as far as it needs to
    go.

    ``order`` fixes the sequence claims are offered in, and it matters twice.
    Priority: every port's FIRST claim is offered before any port's second, so a
    port that wants two can never leave a port that wants one with nothing --
    matchings only grow, so a rank-0 claim matched in the first pass stays
    matched through every later augmentation.  And determinism: the same pack
    must reserve the same cells, or a routing comparison measures the reservation
    order instead of what it is trying to measure.
    """
    owner: dict[tuple[int, int, int], tuple[tuple[int, int], int]] = {}

    def augment(start: tuple[tuple[int, int], int]) -> bool:
        # Iterative, not recursive: an alternating path can run the length of
        # the port list, and Python's stack limit is not a routing parameter.
        seen: set[tuple[int, int, int]] = set()
        #: claim -> (the claim that wants its cell, that cell).  This is the
        #: path back to ``start``, and it is walked to hand the cells over only
        #: once a free one has actually been found.
        came_from: dict[
            tuple[tuple[int, int], int], tuple[tuple[tuple[int, int], int], tuple[int, int, int]]
        ] = {}
        stack = [start]
        while stack:
            claim = stack.pop()
            for cell in options[claim[0]]:
                if cell in seen:
                    continue
                seen.add(cell)
                holder = owner.get(cell)
                if holder is None:
                    owner[cell] = claim
                    cur = claim
                    while cur in came_from:
                        parent, parent_cell = came_from[cur]
                        owner[parent_cell] = parent
                        cur = parent
                    return True
                if holder != start and holder not in came_from:
                    came_from[holder] = (claim, cell)
                    stack.append(holder)
        return False

    for rank in range(max(wants.values(), default=0)):
        for key in order:
            if wants[key] > rank:
                augment((key, rank))
    return {cell: claim[0] for cell, claim in owner.items()}


def _reserve_port_access(
    canvas: _Canvas, nets: list[_Net], *, twice: Collection[tuple[int, int]] = ()
) -> int:
    """Hold a cell next to every port, so no net can be walled in by another.

    Returns the number of ports that had no free neighbour to reserve -- those
    are genuinely boxed in by the packing and no routing order can save them,
    which is worth knowing separately from a net that merely lost a race.

    Reservations are per PORT, not per net: several nets can share one lane end
    (a lane feeding two consumers), and they can share its access cell too,
    because they all leave from the same tile.  Reserving per net would hand the
    second net a different cell it does not need and take it away from someone
    who does.

    A port that both RECEIVES and SENDS gets two cells without being asked for.
    A coater's drop belt is one: the proliferator chain arrives at it from the
    previous coater and leaves it for the next, so one access cell cannot serve
    both -- whichever net routed first took it and built on it, and the other
    found the drop walled in.  It did not fail loudly, because the router will
    settle for merging into a sibling net's path; the belts that came out of
    that merge carried proliferator PAST the drop instead of INTO it, leaving a
    coater mounted on a belt nothing fills.  The drop then reads as an entry
    lane the player must fill, buried inside the block -- which is exactly what
    ``flow.external_entry_reachable`` was reporting.

    ``twice`` names ports that need one MORE approach on top of that, which is
    what an input lane fed from both outside and inside is.  ``_seat_inputs``
    mixes two ingredients onto one lane when they will not fit one per lane, and
    one of them can be an external input while the other is produced internally;
    the external run then arrives on the lane head's one open side and the
    internal net finds an empty goal set.  Both claims are legitimate and they
    are not the same cell, so both are staked.

    Ports are served shortest-lane-first within a round, which is arbitrary and
    deliberately so: what decides whether a port gets an access cell at all is
    the ROUND, not the position in it, and every port has taken its first before
    any port asks for a second.
    """
    canvas.reserved.clear()
    ports: dict[tuple[int, int], int] = {}
    roles: dict[tuple[int, int], set[str]] = defaultdict(set)
    for net in nets:
        for role, port in (("src", net.src), ("dst", net.dst)):
            key = (port.x, port.y)
            ports[key] = max(ports.get(key, 0), len(port.columns()))
            roles[key].add(role)

    order = sorted(ports, key=lambda k: (ports[k], k))
    wants = {k: len(roles[k]) + (1 if k in twice else 0) for k in order}
    held: dict[tuple[int, int], int] = defaultdict(int)

    # EVERY port gets its first cell before any port gets its second, AND the
    # ports that can only be served one way are served -- which taking the first
    # free neighbour cannot promise, because it never gives a cell back.
    #
    # This used to be two nested loops: rounds outside so no port took a second
    # cell before every port had a first, and inside them "the first neighbour
    # `canvas.free` still likes".  The rounds are right and are kept.  The inner
    # grab is not: it is first-come-first-served over a bipartite graph, so a
    # port with two ways out can take the cell that is another port's ONLY way
    # out, and nothing ever revisits that.
    #
    # Measured, and it is the whole of a refusal rather than a tidiness point.
    # `universe-matrix/max-proliferation` at h=115 packs a coater drop at
    # (66,8): a machine south, its own coater west, and exactly two free
    # neighbours, (67,8) and (66,7).  It is mid-chain, so it both receives and
    # sends and wants two.  Port (65,7) sorts earlier, has other options, and
    # takes (66,7); the drop gets one cell, the hop arriving takes it, and the
    # hop LEAVING is handed an empty start set.  A* returns `None` having
    # expanded zero nodes, which no amount of rip-up can price -- a search that
    # expands nothing registers no conflict -- so net 89 stranded in all seven
    # rounds of three runs and was the ONLY failure on the pack.
    #
    # An assignment where every port gets what it wants exists on that pack; the
    # greedy pass just cannot reach it.  So this is a maximum bipartite
    # b-matching (`_match_access`), taken in the same round order, which finds
    # one whenever one exists.  It costs ~200 ports of at most four options
    # each, once per routing pass, against a CP-SAT solve and hundreds of A*
    # searches.
    options = {
        key: [
            c
            for c in ((key[0] + dx, key[1] + dy, 0) for dx, dy in _STEPS)
            if canvas.free(c)
        ]
        for key in order
    }
    for cell, key in _match_access(order, options, wants).items():
        canvas.reserved[cell] = key
        held[key] += 1

    # A THIRD claim: the one way OUT of an access cell that has only one.
    #
    # An access cell nothing can leave is worth exactly as much as no access
    # cell at all, and the router cannot tell the two apart -- both give A* a
    # start it expands and a heap that empties. Measured on
    # `quantum-chip/no-proliferator` at h=106: of 61 failing searches the median
    # reachable region was ONE CELL, and every one of them was starved on the
    # SOURCE side, at an output lane's east-end port.
    #
    # That port's cul-de-sac is structural. A strip's output lanes are stacked
    # rows, so their east ports' access cells are stacked in one margin column,
    # walled north and south by the siblings' own claims; the lane belt is west;
    # east is the only move left. Staking it here is the same argument that
    # justifies the access cell itself, applied to the move that makes it useful.
    #
    # Only where there is exactly ONE onward move. Two or more and the cell is
    # not a cul-de-sac, and holding ground a port does not need is how a
    # reservation pass starts costing more than it buys.
    exits: list[tuple[tuple[int, int], tuple[int, int, int]]] = []
    for cell, key in canvas.reserved.items():
        cx, cy, lvl = cell
        onward = [
            c for c in ((cx + dx, cy + dy, lvl) for dx, dy in _STEPS) if canvas.free(c)
        ]
        if len(onward) == 1:
            exits.append((key, onward[0]))
    # Applied after the scan, not during it: `free` reads `canvas.reserved`, so
    # staking inside the loop would let an early exit claim decide whether a
    # later cell counts as a cul-de-sac.
    for key, cell in exits:
        if canvas.free(cell):
            canvas.reserved[cell] = key

    return sum(1 for key in order if not held[key])


def _commit_paths(
    canvas: _Canvas,
    nets: list[_Net],
    paths: dict[int, list[tuple[int, int, int]]],
    belt_id: int,
    belt_model: int,
    src_group: Mapping[int, tuple[int, ...]] | None = None,
    dst_group: Mapping[int, tuple[int, ...]] | None = None,
) -> int:
    """Turn reserved cells into real belts, forward-linked source to sink.

    Returns the number of routed nets that could NOT be linked to their source.

    ``src_group`` is the router's own record of which nets share each net's
    SOURCE LANE, and it is the only thing that can tell a legitimate branch from
    a mis-link.  A path that starts away from its own lane started on a
    ``_merge_frontier`` cell of one of these siblings and nowhere else, so
    :func:`_source_for` is handed exactly those cells to attach to.  Omitting it
    lets any adjacent belt of the right item stand in for the source, which is
    how a short-cut net came to be fed by the very lane it was delivering to.

    ``dst_group`` is the same record for the DESTINATION lane, and
    :func:`_sink_for` needs it for the same reason.  A destination lane can be
    mixed -- several items delivered to one tile, which is what a matrix lab's
    input lane is -- so "an adjacent belt carrying my item" identifies neither
    the siblings that ARE going where this net is going nor the strangers that
    are not.  The router already decided the question when it offered those
    cells as goals; handing the answer to the linker is all this does.

    A belt tile has ONE ``output_obj``.  When a lane serves several consumers,
    each of them taps a different tile of it (see ``_Port.at_tile``), and a tap
    partway along a lane is a JUNCTION: the lane has to keep flowing east *and*
    hand items to the branch.  ``_tap_source`` builds that as a splitter, which
    is what the game uses and what the fixture corpus shows.

    Before splitters existed, every such net rewrote the same lane-end tile and
    the last to commit won silently.  The earlier paths stayed on the grid as
    belts nothing fed: real buildings, real area, no items.
    """
    for cell, owner in list(canvas.blocked.items()):
        if owner == _TENTATIVE:
            del canvas.blocked[cell]
    # Release the port reservations. They exist to stop one net's path from
    # taking the last cell another net needs to leave its port, and routing is
    # over -- but `free()` refuses a cell reserved for a port that is not being
    # routed, and nothing is being routed here. Leaving them held made every
    # path that ran through its OWN start or goal cell fail the free() check
    # below and get dropped. Silently, until `_commit_paths` learned to count.
    canvas.reserved.clear()
    canvas.routing_ports = frozenset()
    unlinked = 0
    for i, path in paths.items():
        net = nets[i]
        indices: list[int] = []
        ok = True
        for x, y, lvl in path:
            if not canvas.free((x, y, lvl)):
                ok = False
                break
            indices.append(
                canvas.add(
                    PlacedBuilding(
                        item_id=belt_id,
                        model_index=belt_model,
                        x=x,
                        y=y,
                        z=lvl,
                        width=1,
                        height=1,
                        carries_item=net.item,
                    )
                )
            )
        if not ok or not indices:
            unlinked += 1
            continue
        for a, b in zip(indices, indices[1:], strict=False):
            canvas.buildings[a] = _relink(canvas.buildings[a], output_obj=b)
        kin = {
            cell
            for s in (src_group or {}).get(i, ())
            for cell in paths.get(s, ())
        }
        feeder = _source_for(canvas, indices[0], net, set(indices), kin)
        if feeder is None:
            unlinked += 1
            continue
        if not _tap_source(canvas, feeder, indices[0], belt_id, belt_model):
            unlinked += 1
            continue
        # The SINK side is counted exactly like the source side. A path that
        # reached nothing it can hand items to is unrouted, and reporting it as
        # routed is how a pack with three belts linking 40 tiles across the block
        # came back as `failed = 0`.
        sink_kin = {
            cell
            for s in (dst_group or {}).get(i, ())
            for cell in paths.get(s, ())
        }
        sink = _sink_for(canvas, indices[-1], net, set(indices), sink_kin)
        if sink is None:
            unlinked += 1
            continue
        canvas.buildings[indices[-1]] = _relink(
            canvas.buildings[indices[-1]], output_obj=sink
        )
    return unlinked


def _source_for(
    canvas: _Canvas,
    first: int,
    net: _Net,
    own: set[int],
    kin: Set[tuple[int, int, int]],
) -> int | None:
    """What this path actually left from: the lane tap, or a sibling to branch off.

    The mirror of :func:`_sink_for`.  A path that could not start beside its own
    lane was routed from a sibling's belt instead, and feeding it from
    ``net.src.belt`` regardless would name a building it is nowhere near.

    ``kin`` IS THE SIBLING SET THE ROUTER ACTUALLY OFFERED -- the cells of the
    paths in this net's ``src_group``, the nets that share its source lane --
    and honouring it is what makes the branch carry THIS net's items.

    Without it the scan took the first adjacent belt carrying the right item,
    and at a merge point several do.  ``quantum-chip/free-proliferation``:
    ``titanium-glass`` shards into a four-machine and a three-machine strip,
    ``plane-filter`` into three lanes of 6/5/5, and the cyclic pairing gives the
    four-machine shard eleven consumers.  :func:`_connect_short_cuts` sees that
    island starve and buys exactly one extra net -- three-machine shard to the
    six-machine lane -- which is the only thing joining the two islands.  That
    net routed to a single tile beside its destination and was then fed from the
    belt of the FOUR-machine shard's net, which already delivered there.  A
    one-tile belt taking items from a lane and handing them back to the same
    lane: linked, adjacent, acyclic, carrying the right item, and worth nothing.
    Both source-side and sink-side counters read success, so ``failed`` was 0,
    the sweep accepted the pack, and the island the short-cut was bought to
    close stayed open -- 11 machines drawing 11/4 items/s of titanium-glass from
    the 16/7 four machines make.  Roughly one build in twenty-five, since it
    needs the pack to put the two paths side by side.

    A branch off a belt that does not lead back to our own lane is not a
    cheaper way to reach the source; it is a different source.  So the scan is
    restricted rather than merely reordered.

    ``None`` MEANS THIS PATH LEAVES FROM NOTHING, exactly as it does for
    :func:`_sink_for`, AND IT USED TO RETURN ``net.src.belt`` INSTEAD.
    -------------------------------------------------------------------------
    That fallback was kept because it was MEASURED DEAD -- over 264 audit cells
    this function was called 12,020 times, 11,620 taking the lane tap, 400 a
    sibling from ``kin``, and the fallback 0 -- and because the link it emits is
    at least loud: it crosses the map, so ``belt.link_adjacent`` reports it and
    ``certify`` turns the placement into a refusal rather than a bad build.

    IT IS NOT DEAD ANY MORE, and the count was stale rather than wrong.  When
    ``_repair`` displaced the very sibling a stranded net had just merged onto
    (fixed in the same commit as this), the fallback ran on
    ``universe-matrix/no-proliferator`` power=1 EVERY RUN, and the pack it broke
    reported ``failed = 0``: the source side was linked, to a belt 15 tiles west
    and two altitude levels down.  Refused two layers later by our own
    validator, on ``belt.link_adjacent`` and ``geom.altitude_step``, with the
    packer blamed for a pack that had wired perfectly well.

    So it fails closed.  A path that leaves from nothing is unrouted, saying so
    counts it in ``unlinked``, and the router gets to try again inside the same
    routing pass -- which is what happens for every other kind of routing
    failure and what ``_sink_for`` has done since ``3f04239``.  The asymmetry
    was the last of it.
    """
    head = canvas.buildings[first]
    src = canvas.buildings[net.src.belt]
    if abs(src.x - head.x) + abs(src.y - head.y) <= 1 and src.z == head.z:
        return net.src.belt
    for dx, dy in _STEPS:
        cell = (head.x + dx, head.y + dy, head.z)
        if cell not in kin:
            continue
        who = canvas.blocked.get(cell)
        if who is None or not 0 <= who < len(canvas.buildings) or who in own:
            # Never attach to a belt of THIS path. The cell before the one we
            # are linking is adjacent and carries the same item, so it always
            # matches -- and pointing at it makes a two-belt cycle, which
            # `belt.acyclic` then reports.
            continue
        if who == net.dst.belt:
            # Nor to the lane this net DELIVERS to. A short path that ends up
            # beside its own destination satisfies "a belt carrying my item is
            # next to my head" perfectly, and taking it makes the lane feed the
            # branch that feeds the lane -- through the splitter `_tap_source`
            # builds, so a link-following eye slides straight past it. This was
            # the intermittent `belt.acyclic` on the magnetic-ring fixture:
            # feeder 597 -> splitter -> stub -> branch 1192 -> 597.
            continue
        other = canvas.buildings[who]
        if catalog.is_belt(other.item_id) and other.carries_item == net.item:
            return who
    # Nothing adjacent belongs to a net leaving where we leave, so this path
    # leaves from nobody.
    return None


def _leads_back(canvas: _Canvas, start: int, own: set[int]) -> bool:
    """Does flow leaving ``start`` come back to this path?

    Merging into a neighbouring belt is only legal when that belt runs AWAY from
    us.  Two nets that share a source lane and a destination lane end up beside
    each other twice -- the second branches off the first to leave, and then
    finds the first again at the far end -- and merging both ways closes the
    loop.  The validator reports it as ``belt.acyclic``, and it is a real fault:
    the game would run items round it forever.

    Splitters are followed, not stopped at: they carry no ``output_obj`` of
    their own, so a link-following walk misses exactly the loops a fan-out
    router most easily builds.  Same rule as ``validate._belt_successors``, so
    what this refuses to build is what that refuses to accept.
    """
    from_junction: dict[int, list[int]] = defaultdict(list)
    for i, b in enumerate(canvas.buildings):
        feed = b.input_obj
        if (
            feed is not None
            and 0 <= feed < len(canvas.buildings)
            and canvas.buildings[feed].item_id == catalog.SPLITTER_ID
        ):
            from_junction[feed].append(i)

    seen: set[int] = set()
    stack = [start]
    while stack:
        i = stack.pop()
        if i in own:
            return True
        if i in seen or not 0 <= i < len(canvas.buildings):
            continue
        seen.add(i)
        b = canvas.buildings[i]
        if b.item_id == catalog.SPLITTER_ID:
            stack.extend(from_junction.get(i, ()))
        elif catalog.is_belt(b.item_id) and b.output_obj is not None:
            stack.append(b.output_obj)
    return False


def _sink_for(
    canvas: _Canvas,
    last: int,
    net: _Net,
    own: set[int],
    kin: Set[tuple[int, int, int]],
) -> int | None:
    """What this path actually reached: the lane head, or a sibling to merge into.

    A path that could not get to the lane head was routed to a sibling's belt
    instead (see ``_merge_frontier``), so linking it to ``net.dst.belt``
    regardless would name a building it is nowhere near -- which
    ``belt.link_adjacent`` would then, correctly, report as an error.

    Preference order is the lane head first, so the common case is unchanged and
    a merge only happens where one was actually routed.

    ``kin`` IS THE SIBLING SET THE ROUTER ACTUALLY OFFERED -- the cells of the
    paths in this net's ``dst_group``, the nets delivering to the SAME lane tile
    -- exactly as ``_source_for`` takes the source-lane siblings.  It replaces a
    scan for "an adjacent belt carrying my item", which was wrong in both
    directions on ``universe-matrix``:

    * IT REFUSED MERGES THE ROUTER HAD AIMED AT.  A destination lane can be
      MIXED, and the validator says so in as many words -- ``_entry_items``
      documents an entry lane labelled ``antimatter`` down its whole length
      while sorters draw both ``antimatter`` and ``electromagnetic-matrix`` off
      it.  ``_merge_frontier`` offers the free cells beside a sibling's path as
      goals without consulting items, because sharing a destination tile is what
      makes a sibling; A\\* then ends the path on one of those cells; and this
      function threw it away because the sibling's belt was labelled with the
      OTHER item of the pair.  All seven unlinked paths on
      ``universe-matrix/max-proliferation`` at budget 4 were this, and each one
      was adjacent to exactly one dst-sibling cell: ``information-matrix`` beside
      ``structure-matrix`` into (106,20), ``antimatter`` beside
      ``electromagnetic-matrix`` into (106,18) and (78,33), ``gravity-matrix``
      beside ``energy-matrix`` into (106,19).  A ``carries_item`` label is one
      of the items a mixed run holds, so it cannot answer "is this belt going
      where I am going".
    * IT ADMITTED MERGES NOBODY OFFERED.  An adjacent belt carrying our item
      that is not a sibling runs to a DIFFERENT consumer, and handing it our
      items delivers them there -- the sink-side twin of the ``_source_for``
      defect fixed in ``00d1f78``, where "the first adjacent belt carrying the
      right item" fed a net from the very lane it was delivering to.

    So the scan is restricted rather than merely reordered, on the same argument:
    a belt that does not lead to our own lane is not a cheaper way to reach the
    destination, it is a different destination.  Measured before the restriction
    was made: over three instrumented builds of the target cell every merge that
    already succeeded was a ``kin`` cell (4/4, 5/5, 6/6) and NO merge was made to
    a non-sibling belt, so this drops nothing that was working.

    ``None`` means this path reached NOTHING it can hand items to, and that is a
    route failure like any other.  It used to return ``net.dst.belt`` anyway, on
    the reasoning that a wrong link is at least visible as ``belt.link_adjacent``
    -- but visible to WHOM.  ``_commit_paths`` counted only source-side failures,
    so the sink-side break came back as ``failed = 0``, the sweep accepted the
    pack as fully wired, and the defect surfaced two layers later as a
    placement our own validator threw out.  Measured on
    ``universe-matrix/free-proliferation`` at 120s, where the emitted block
    carried three belts linking to a lane head 35 to 40 tiles away and three more
    stepping two altitude levels in one tile.

    A net that reached nothing is unrouted.  Saying so lets the sweep discard
    that height and try another, which is what it does for every other kind of
    routing failure.
    """
    tail = canvas.buildings[last]
    dst = canvas.buildings[net.dst.belt]
    if abs(dst.x - tail.x) + abs(dst.y - tail.y) <= 1 and abs(dst.z - tail.z) <= 1:
        return net.dst.belt
    for dx, dy in _STEPS:
        cell = (tail.x + dx, tail.y + dy, tail.z)
        if cell not in kin:
            continue
        who = canvas.blocked.get(cell)
        if who is None or not 0 <= who < len(canvas.buildings) or who in own:
            # Never attach to a belt of THIS path. The cell before the one we
            # are linking is adjacent and carries the same item, so it always
            # matches -- and pointing at it makes a two-belt cycle, which
            # `belt.acyclic` then reports.
            continue
        other = canvas.buildings[who]
        if not catalog.is_belt(other.item_id):
            continue
        if _leads_back(canvas, who, own):
            continue  # merging here would close a loop
        return who
    # Nothing adjacent belongs to a net delivering where we deliver, so this
    # path delivers to nobody.
    return None


def _tap_source(
    canvas: _Canvas, belt_idx: int, branch: int, belt_id: int, belt_model: int
) -> bool:
    """Make ``belt_idx`` hand items to ``branch``, junctioning if it must.

    Three cases, and the distinction is the whole point:

    * The tile has no onward link -- it is a lane end -- so it can simply point
      at the branch.
    * The tile already flows onward to the next lane tile.  It cannot also point
      at the branch, so a splitter goes on the tile: the lane feeds it, a new
      co-located belt carries the lane onward from it, and the branch draws from
      it too.  Co-location is not a liberty; it is exactly what the corpus does,
      a belt running *through* a junction being recorded as two belts on the
      tile.
    * The tile already feeds a splitter, because another branch got here first.
      Attach to that same junction if it has a spare side, otherwise report the
      failure rather than exceed a splitter's four ports, which pastes as a
      junction quietly dropping a connection.

    Returns ``False`` when the branch could not be attached.
    """
    b = canvas.buildings[belt_idx]
    onward = b.output_obj
    if onward is None:
        canvas.buildings[belt_idx] = _relink(b, output_obj=branch)
        return True

    if canvas.buildings[onward].item_id == catalog.SPLITTER_ID:
        junction_idx = onward
    else:
        junction_idx = canvas.add(
            junction.make_splitter(b.x, b.y, b.z, carries_item=b.carries_item)
        )
        canvas.buildings[belt_idx] = _relink(b, output_obj=junction_idx)
        # Carry the lane onward FROM the junction, so everything downstream of
        # the tap stays fed. Dropping this would starve the rest of the lane in
        # order to feed the branch -- trading one silent break for another.
        # `replace`, not a fresh PlacedBuilding: the carry belt IS the lane belt
        # continuing past the junction, so every field it does not change should
        # come across untouched. Listing fields by hand is how `carries_item`
        # and `parameters` got silently dropped elsewhere in this file.
        carry = canvas.add(replace(b, input_obj=junction_idx, output_obj=onward))
        del carry  # linked by construction; the index is not needed again

    attached = sum(
        1
        for c in canvas.buildings
        if c.output_obj == junction_idx or c.input_obj == junction_idx
    )
    if attached >= junction.MAX_PORTS:
        return False

    # The branch belt is ADJACENT to the junction, not on it, and every belt
    # attached to a splitter must be CO-LOCATED with it -- that is what the
    # corpus shows and what `junction.colocated` enforces. So the junction gets
    # a stub on its own tile which then runs out to the branch. This is exactly
    # the shape the game records: a splitter's port is a belt on the junction
    # tile, and the route starts from there.
    stub = canvas.add(
        replace(
            b,
            yaw=canvas.buildings[branch].yaw,
            input_obj=junction_idx,
            output_obj=branch,
        )
    )
    del stub  # linked by construction
    return True


# --- power -----------------------------------------------------------------


def _straight_to_edge(
    canvas: _Canvas, port: _Port, bounds: tuple[int, int, int, int]
) -> list[tuple[int, int, int]] | None:
    """A clear straight run from just outside the block to ``port``'s tile.

    Four directions are tried, nearest edge first, and the run must be clear the
    whole way -- a partial run is not a connection.  Returns the cells in FLOW
    order (edge first, lane last) or ``None`` when every direction is blocked,
    at which point the caller falls back to routing.
    """
    min_x, min_y, max_x, max_y = bounds
    options: list[list[tuple[int, int, int]]] = [
        [(x, port.y, 0) for x in range(min_x - 1, port.x)],
        [(x, port.y, 0) for x in range(max_x + 1, port.x, -1)],
        [(port.x, y, 0) for y in range(min_y - 1, port.y)],
        [(port.x, y, 0) for y in range(max_y + 1, port.y, -1)],
    ]
    clear = [
        cells
        for cells in options
        if cells and all(canvas.free(c) for c in cells)
    ]
    if not clear:
        return None
    return min(clear, key=len)


def _route_external_inputs(
    canvas: _Canvas,
    spec: BuildSpec,
    strip_in_ports: list[dict[str, _Port]],
    belt_id: int,
    belt_model: int,
    core: tuple[int, int, int, int],
    deadline: float | None = None,
    budget: dict[str, int] | None = None,
) -> int:
    """Run every outside input from the block edge to the lane that wants it.

    Returns the number of lanes that could not be reached.  A lane the
    ``deadline`` ran out on counts as unreached, which is the same refusal any
    other unreachable lane produces -- never a placement missing an entry run.

    Without this, an external input was just a lane wearing a marker icon.  On a
    packed build that lane is frequently WALLED IN -- above it another lane,
    below it the machine band, either side the lane itself -- so no belt could
    be run to it, by the router or by the player standing in front of it.  The
    icon said "connect here" pointing at a tile nothing can connect to.

    Routing to the boundary fixes three things at once: the lane is reachable,
    the marker now sits on a belt the player can actually see the end of, and
    the blueprint describes its own inputs instead of relying on the operator to
    work out which of forty belts is the iron-ore one.

    Belts flow INWARD here -- from the edge to the lane -- which is the opposite
    direction to every other net, so the path is committed head-first with the
    last belt feeding the lane.

    Runs terminate on the ENTRY RING, the outermost ring anything may occupy.
    That is what makes each of them reachable: nothing else can be placed
    further out, so a run's head is on the finished bounding box and has open
    ground on its outward side whatever the router does afterwards.  Running out
    to "one tile past the current edge" -- which is what this did -- put the head
    on a boundary that later passes moved, and the head then sat interior.
    """
    bounds = _grow(core, _ENTRY_RING - 1)
    min_x, min_y, max_x, max_y = bounds
    # The fallback search may travel ALONG the entry ring, which the straight
    # runs already use; a cell on the outermost ring cannot wall anything in,
    # because outward of it is ground no pass can reach.
    astar_bounds = _grow(core, _ENTRY_RING)
    # One ring outside the block: where the player's belt meets ours.
    edge = [
        (x, y, 0)
        for x in range(min_x - 1, max_x + 2)
        for y in (min_y - 1, max_y + 1)
    ] + [
        (x, y, 0)
        for y in range(min_y, max_y + 1)
        for x in (min_x - 1, max_x + 1)
    ]
    starts = [c for c in edge if canvas.free(c)]
    if not starts:
        return 0

    history: dict[tuple[int, int, int], float] = defaultdict(float)
    if budget is None:
        budget = {"left": _ROUTING_BUDGET}
    # Deduplicate: several strips of one group each want the same item, and each
    # of their lanes needs its own way in.
    # Keyed by LANE, not by item. `_seat_inputs` mixes two ingredients onto one
    # lane when they will not fit one-per-lane, and both then report the same
    # port. Routing per item would try to build a second run to a lane that
    # already has one, find the cell taken, and count a miss -- which is what
    # made the six-ingredient spec refuse outright. One lane needs one way in;
    # what travels on it is the marker pass's business.
    wanted: dict[int, _Port] = {}
    for ports in strip_in_ports:
        for item, port in sorted(ports.items()):
            if item in spec.external_inputs:
                wanted.setdefault(port.belt, port)
    carried = {
        port.belt: item
        for ports in strip_in_ports
        for item, port in sorted(ports.items(), reverse=True)
        if item in spec.external_inputs
    }
    missed = 0
    for done, (belt, port) in enumerate(wanted.items()):
        if _expired(deadline):
            # Everything still to do is unreached. Counting them rather than
            # returning what we have is the difference between a refusal and a
            # placement whose remaining lanes silently have no way in.
            return missed + len(wanted) - done
        item = carried[belt]
        # Spend exactly ONE of this lane's access reservations and leave the
        # rest held. Every other port's stays held too, so bringing one input in
        # cannot wall another lane up -- measured as `belt:external` sitting on
        # the single open side of a lane head, on a canvas that had been clean a
        # moment earlier.
        #
        # Releasing rather than claiming (`routing_ports`) is the point: a lane
        # that also receives an internal net holds TWO cells, and claiming would
        # let one straight run take both. The internal net would then be handed
        # the empty goal set this exists to prevent.
        mine = next(
            (c for c, k in canvas.reserved.items() if k == (port.x, port.y)), None
        )
        if mine is not None:
            del canvas.reserved[mine]
        # Straight out to the edge first. A lane head sits on the west face of
        # its strip, so the run west along its own row is usually clear, costs
        # one belt per tile, and -- unlike a routed path -- cannot compete with
        # the other input lanes for the margin outside the block. That mattered:
        # routing six lanes of a six-ingredient strip through a two-tile margin
        # failed outright, while six parallel straight runs do not interact at
        # all. It is also what spine does, and for the same reason.
        path = _straight_to_edge(canvas, port, bounds)
        if path is None:
            goals = {
                (port.x + dx, port.y + dy, 0)
                for dx, dy in _STEPS
                if canvas.free((port.x + dx, port.y + dy, 0))
            }
            if not goals:
                missed += 1
                continue
            live = [c for c in starts if canvas.free(c)]
            path = _astar(
                canvas, live, goals, history, 1.0, astar_bounds, budget, deadline
            )
        if path is None:
            missed += 1
            continue
        indices: list[int] = []
        for x, y, lvl in path:
            if not canvas.free((x, y, lvl)):
                break
            indices.append(
                canvas.add(
                    PlacedBuilding(
                        item_id=belt_id,
                        model_index=belt_model,
                        x=x,
                        y=y,
                        z=lvl,
                        width=1,
                        height=1,
                        carries_item=item,
                    )
                )
            )
        if not indices:
            missed += 1
            continue
        for a, b in zip(indices, indices[1:], strict=False):
            canvas.buildings[a] = _relink(canvas.buildings[a], output_obj=b)
        canvas.buildings[indices[-1]] = _relink(
            canvas.buildings[indices[-1]], output_obj=port.belt
        )
    return missed


def _nearest_free(canvas: _Canvas, cx: int, cy: int, limit: int) -> tuple[int, int] | None:
    """The closest cell to ``(cx, cy)`` nothing stands on, within ``limit``."""
    for r in range(limit + 1):
        for dx in range(-r, r + 1):
            for dy in (-r, r) if r else (0,):
                for a, b in ((cx + dx, cy + dy), (cx + dy, cy + dx)):
                    if canvas.free((a, b, 0)) and (a, b) not in canvas.solid:
                        return (a, b)
    return None


def _claim_power_sites(canvas: _Canvas, core: tuple[int, int, int, int]) -> list[tuple[int, int]]:
    """Hold a cell for every lattice point, BEFORE anything routes.

    Power is the last pass, and on a dense block "last" means "gets nothing".
    Every belt the router lays is a cell the lattice cannot use, and the coverage
    repair then searches a full tower radius and finds the ground solid:
    measured on ``casimir-crystal``, a matrix lab with 349 tiles inside range had
    four of them free, and thirteen buildings shipped unpowered -- a blueprint
    that pastes and then sits there.

    So the lattice claims its ground while the ground is still empty, and the
    router paths around one cell in eighty-one.  Only machines, sorters and
    coaters draw power, and all of those are inside ``core``, so the lattice is
    laid over the core rather than over the finished bounding box -- the entry
    ring holds nothing but belts, which are unpowered.
    """
    min_x, min_y, max_x, max_y = core
    half = TOWER_SPACING // 2
    sites: list[tuple[int, int]] = []
    y = min_y + half
    while y <= max_y + half:
        x = min_x + half
        while x <= max_x + half:
            spot = _nearest_free(canvas, x, y, 4)
            # Strictly inside the core. A lattice point near the east or south
            # face can be displaced onto the entry ring, and the ring belongs to
            # the input runs: a tower standing in one would break the straight
            # run out to it for no reason, when the machine it was covering has
            # the whole block to be covered from.
            if spot is not None and not (
                min_x <= spot[0] <= max_x and min_y <= spot[1] <= max_y
            ):
                spot = None
            if spot is not None:
                sites.append(spot)
                canvas.keep_out.add(spot)
            x += TOWER_SPACING
        y += TOWER_SPACING
    return sites


@lru_cache(maxsize=8)
def _RING_OFFSETS(limit: int) -> tuple[tuple[int, int], ...]:  # noqa: N802
    """Offsets within ``limit`` tiles, nearest first, built once per radius.

    :func:`_place_power`'s repair rebuilt and re-sorted this square for every
    dark tile it found.  The radius is a constant of the tower, so the square is
    the same one every time.
    """
    return tuple(
        sorted(
            (
                (dx, dy)
                for dx in range(-limit, limit + 1)
                for dy in range(-limit, limit + 1)
            ),
            key=lambda d: (abs(d[0]) + abs(d[1]), d),
        )
    )


def _place_power(canvas: _Canvas, sites: Sequence[tuple[int, int]]) -> int:
    """Towers on the claimed lattice, then repaired until coverage really holds.

    The lattice spacing already guarantees coverage and connectivity in open
    ground; the repair passes exist because a claim can still fail -- a lattice
    point may have had no free cell within reach even before routing -- and a
    tower that could not be placed is exactly the kind of gap that would
    otherwise reach the game as a dead corner of the factory.

    COORDINATES ARE DOUBLED INTEGERS, AND SO IS EVERY DISTANCE TEST.

    A tower's centre falls on a half tile, which is why this used ``Fraction``.
    It is the same predicate written twice the size: multiply both sides of
    ``dx**2 + dy**2 <= r**2`` by four and every term is an integer, so the
    comparison is ``dx2**2 + dy2**2 <= floor((2r)**2)`` -- exact, because the
    left side cannot land between ``floor((2r)**2)`` and ``(2r)**2``.  This is
    not a tolerance and there is no float anywhere near it.

    It is worth the rewrite because this function ran INSIDE the layout
    deadline and was the largest single thing in it.  Profiled on
    `universe-matrix/no-proliferator` power=1 at h=185: `_build` 49.0s, of which
    `_place_power` 28.6s against `_route_all`'s 19.2s -- 4.73 MILLION
    ``Fraction.__pow__`` calls, because ``covered`` was a linear scan of every
    tower, in exact rationals, once per tile of every powered building.  The
    scan is now bucketed on a grid of the cover radius, so a tile looks at the
    nine buckets that could possibly hold a tower covering it instead of at all
    of them.
    """
    if not canvas.buildings:
        return 0
    tower = catalog.building(catalog.TESLA_TOWER_ID)
    radius = tower.cover_radius
    link = tower.connect_distance
    #: ``(2r)**2`` and ``(2d)**2``, floored -- see the docstring.
    reach2 = math.floor((2 * radius) ** 2)
    #: Doubled centres, integers: ``(2x + width, 2y + height)``.
    centres: list[tuple[int, int]] = []
    #: Doubled-centre buckets, side ``span``, so a covering tower is always in
    #: one of the nine buckets around the tile being tested.
    span = max(1, 2 * (int(radius) + 1))
    buckets: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)
    placed = 0

    def try_place(cx: int, cy: int) -> bool:
        nonlocal placed
        if not canvas.free((cx, cy, 0)) or (cx, cy) in canvas.solid:
            return False
        for lvl in range(LEVELS):
            if (cx, cy, lvl) in canvas.blocked:
                return False
        canvas.add(
            PlacedBuilding(
                item_id=catalog.TESLA_TOWER_ID,
                model_index=tower.model_index,
                x=cx,
                y=cy,
                width=tower.width,
                height=tower.height,
            ),
            solid=True,
        )
        centre = (2 * cx + tower.width, 2 * cy + tower.height)
        centres.append(centre)
        buckets[centre[0] // span, centre[1] // span].append(centre)
        placed += 1
        return True

    for site in sites:
        try_place(*site)

    def covered(px: int, py: int) -> bool:
        bx, by = px // span, py // span
        for ox in (-1, 0, 1):
            for oy in (-1, 0, 1):
                for cx, cy in buckets.get((bx + ox, by + oy), ()):
                    if (px - cx) ** 2 + (py - cy) ** 2 <= reach2:
                        return True
        return False

    def place_covering(px: int, py: int, tx: int, ty: int) -> bool:
        """Place a tower that GENUINELY covers ``(px, py)``, nearest first.

        The candidate must satisfy the coverage test before it is placed, not
        merely be free and roughly nearby.  The previous repair searched up to
        ``radius`` tiles away in one axis and then up to 2 more in the other, so
        it could place a tower 11 tiles from a 10.5-radius target and stop --
        having "repaired" a tile that was still dark.  That surfaced as an
        intermittent validator failure (about 1 run in 18) once multi-worker
        CP-SAT started producing varied packs.
        """
        limit = int(radius)
        for dx, dy in _RING_OFFSETS(limit):
            a, b = tx + dx, ty + dy
            cx = 2 * a + tower.width
            cy = 2 * b + tower.height
            if (px - cx) ** 2 + (py - cy) ** 2 > reach2:
                continue
            if try_place(a, b):
                return True
        return False

    # Coverage repair.  Conservative on purpose: every tile of a powered
    # building, not merely its centre, because being wrong here means a machine
    # that pastes fine and never runs.
    for b in list(canvas.buildings):
        if catalog.is_belt(b.item_id) or b.item_id == catalog.TESLA_TOWER_ID:
            continue
        for tx, ty, _ in b.tiles():
            px, py = 2 * tx + 1, 2 * ty + 1
            if covered(px, py):
                continue
            place_covering(px, py, tx, ty)

    # Connectivity repair: a stranded tower powers its neighbourhood but leaves
    # the network in two pieces, which fails visibly in game rather than
    # silently, but fails all the same.
    for _ in range(4):
        groups = _link_groups(centres, math.floor((2 * link) ** 2))
        if len(groups) <= 1:
            break
        main = groups[0]
        other = groups[1]
        ax, ay = centres[main[0]]
        bx, by = centres[other[0]]
        # Doubled coordinates halve back to a tile by one more division by two.
        # Truncated, not floored, because that is what this line always did and
        # the block can start west of the origin once the router's ring grows.
        # Four exact rationals per build is not a hot path.
        mx, my = math.trunc(Fraction(ax + bx, 4)), math.trunc(Fraction(ay + by, 4))
        spot = _nearest_free(canvas, mx, my, 6)
        if not spot or not try_place(*spot):
            break
    return placed


def _link_groups(centres: list[tuple[int, int]], link2: int) -> list[list[int]]:
    """Connected components of the tower network, largest first.

    ``centres`` are DOUBLED integer coordinates and ``link2`` is ``floor((2d)**2)``
    -- see :func:`_place_power` for why that comparison is exact rather than a
    tolerance.  ``OnNodeAdded`` links on a distance, and on the LARGER of the
    pair's reaches; every tower here is a Tesla Tower, so one constant serves.
    """
    n = len(centres)
    seen: set[int] = set()
    groups: list[list[int]] = []
    for start in range(n):
        if start in seen:
            continue
        comp = [start]
        seen.add(start)
        q = deque([start])
        while q:
            ax, ay = centres[q.popleft()]
            for k in range(n):
                if k in seen:
                    continue
                bx, by = centres[k]
                if (ax - bx) ** 2 + (ay - by) ** 2 <= link2:
                    seen.add(k)
                    comp.append(k)
                    q.append(k)
        groups.append(comp)
    groups.sort(key=len, reverse=True)
    return groups


# --- assembly --------------------------------------------------------------


def _pair_lanes(
    srcs: Sequence[_Port],
    sinks: Sequence[_Port],
    *,
    out_rate: Fraction = Fraction(0),
    in_rate: Fraction = Fraction(0),
) -> list[tuple[_Port, _Port]]:
    """Pair one item's producer lanes against its consumer lanes.

    Pair the two sides cyclically so EVERY producer lane is drained and EVERY
    consumer lane is filled, whichever side was sharded further.  One net per
    side-pair; taking the cross product would emit needless belts.

    Every reuse of a lane stays on that lane's END TILE.  Walking inward was
    tried and is worse: a mid-lane tile is WALLED IN -- lane either side,
    machines above, another lane below -- so the branch it was meant to serve has
    nowhere to leave from.  Measured on the free-proliferation chain: three of
    the five walled-in ports were taps this had moved, each with all four
    neighbours occupied on a clean canvas.

    Sharing the end tile is safe because ``_tap_source`` builds a junction there:
    the first net links directly, the second turns the link into a splitter, and
    further nets attach to it until the four sides run out -- at which point it
    reports the failure instead of mis-linking.

    Only the PRODUCER side is ever reused this way.  Walking the consumer lane
    inward was tried and is strictly worse: a strip's inner input lane is walled
    in the same way, and only the lane HEAD is reachable because its west
    neighbour lies outside the strip.  So several producers feeding one consumer
    lane cannot each reach it -- they converge instead, the first net routing to
    the head and the rest merging into that net's path, which is what belts do
    anyway.

    ``out_rate`` and ``in_rate`` are the per-machine production and consumption
    of this item, and they are what :func:`_connect_short_cuts` needs to tell an
    island that balances from one that starves.  Omitting them keeps the pairing
    exactly cyclic, which is what the unit tests of the pairing itself want.
    """
    pairs = [
        (k % len(srcs), k % len(sinks))
        for k in range(max(len(srcs), len(sinks)))
    ]
    for i, j in _connect_short_cuts(srcs, sinks, pairs, out_rate, in_rate):
        pairs.append((i, j))
    return [(srcs[i], sinks[j]) for i, j in pairs]


def _connect_short_cuts(
    srcs: Sequence[_Port],
    sinks: Sequence[_Port],
    pairs: Sequence[tuple[int, int]],
    out_rate: Fraction,
    in_rate: Fraction,
) -> list[tuple[int, int]]:
    """Extra nets joining islands that cannot feed themselves.

    ``flow.conservation``'s placement clause is a CUT argument: within every
    island an item can physically travel across, production must cover
    consumption.  A one-to-one pairing cuts an item's flow graph into as many
    islands as it makes pairs, and each island then has to balance on its own --
    which two independent integer partitions cannot promise.  Measured on
    ``quantum-chip``: ``titanium-glass`` shards into a four-machine and a
    three-machine strip, ``plane-filter`` into sixteen machines across three
    lanes, and the cyclic pairing hands the four-machine shard eleven of them.
    That island needs 11/4 of a machine's output where seven machines covering
    sixteen reach only 16/7, and no routing inside the block can make it up.

    Connecting every such edge in full was built and measured and thrown away.
    Joining ``n + m`` lanes takes ``n + m - 1`` edges against the pairing's
    ``max(n, m)``, so doing it everywhere adds ``min(n, m) - 1`` nets to every
    sharded edge in the build; over the whole corpus at a 4s budget that removed
    the one ``flow.conservation`` cell and cost FOUR others -- 54 of 72 clean
    against 58 -- because the extra belts crowd both the router and the power
    lattice.

    So the join is bought only where it is needed.  The islands the cyclic
    pairing produced are costed against the actual per-machine rates, and if
    every one of them can feed itself nothing is added at all.  If any cannot,
    the islands are chained with one net apiece -- the whole edge becomes a
    single island and the spec's own arithmetic decides it, which is the only
    claim backpressure cannot rescue.
    """
    if out_rate <= 0 or in_rate <= 0 or len(srcs) < 2 or len(sinks) < 2:
        return []

    parent: dict[tuple[str, int], tuple[str, int]] = {}

    def find(k: tuple[str, int]) -> tuple[str, int]:
        parent.setdefault(k, k)
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    for i in range(len(srcs)):
        find(("s", i))
    for j in range(len(sinks)):
        find(("d", j))
    for i, j in pairs:
        a, b = find(("s", i)), find(("d", j))
        if a != b:
            parent[a] = b

    islands: dict[tuple[str, int], tuple[list[int], list[int]]] = defaultdict(
        lambda: ([], [])
    )
    for i in range(len(srcs)):
        islands[find(("s", i))][0].append(i)
    for j in range(len(sinks)):
        islands[find(("d", j))][1].append(j)

    # Chained in DESCENDING BALANCE, so every edge runs surplus -> deficit.
    #
    # This used to sort on the union-find root, which is an implementation
    # artefact -- whichever key happened to win the path-compression race. That
    # is sound for `flow.conservation`, whose island cut is UNDIRECTED
    # (`validate._islands` unions `(input_obj, output_obj)` without regard to
    # which way the belt points), so a backwards edge merges exactly the same
    # two islands and the check passes identically. It is not sound for a belt.
    #
    # A backwards edge runs from the STARVING island's producer into the
    # SATISFIED island's consumer. Backpressure then makes it inert -- the
    # receiving consumer is already fed, so the belt backs up and carries
    # nothing -- and the shortfall it was emitted to fix stays unfixed while the
    # validator reports clean. A latent defect the validator structurally cannot
    # see, which is why it survived.
    #
    # Not live when found: 10 firings across 36 corpus specs, and root order
    # happened to match descending balance in 10/10. But over 8,620,618
    # REACHABLE firing configurations (machine vectors `plan_strips` can
    # actually emit), 53.4% emit a backwards edge and 83.5% emit an edge out of
    # a deficit island. Smallest case: srcs machines [1,1], sinks [2,1], any
    # rates -- the old order emits (0,1), draining the starving island.
    #
    # The balances are hoisted rather than added: the `any(...)` below computed
    # exactly these two sums inline. Emitted pairs are identical on 36/36 corpus
    # cells; this changes nothing today and closes the case that it would.
    # Matches `_join_shard_islands`, which has ordered this way since f346c50.
    balance = {
        r: sum(srcs[i].machines for i in mine) * out_rate
        - sum(sinks[j].machines for j in theirs) * in_rate
        for r, (mine, theirs) in islands.items()
    }
    if all(v >= 0 for v in balance.values()) or len(islands) < 2:
        return []

    order = sorted(islands, key=lambda r: (-balance[r], r))
    extra: list[tuple[int, int]] = []
    for a, b in zip(order, order[1:], strict=False):
        producers, _ = islands[a]
        _, consumers = islands[b]
        if producers and consumers:
            extra.append((producers[0], consumers[0]))
    return extra


def _join_shard_islands(
    pairs: Sequence[tuple[int, int]],
    supply: Mapping[int, Fraction],
    demand: Mapping[int, Fraction],
    external: Fraction,
) -> list[tuple[int, int]]:
    """Extra nets joining an item's islands ACROSS a producer's shards.

    :func:`_connect_short_cuts` makes the same argument one level down and
    cannot see this case.  It is handed the ports of ONE
    ``(producer group, item, destination)`` edge, so the only islands it can
    join are the ones its own cyclic pairing created.  The islands here are
    made by :func:`_shard_sinks`, which divides a producer's destinations
    between STRIPS, and by :func:`_allocate_machines`, which then divides the
    producer's machines between those shards.  Two shards of one group never
    appear in the same call, so nothing downstream of the pairing could ever
    notice that one of them is starving.

    **An integer split of machines cannot serve a fractional split of demand,
    and a rate solver that balances exactly leaves no slack to absorb the
    rounding.**  ``universe-matrix/no-proliferator`` is the clean example and
    the arithmetic is forced, not unlucky: ``energetic-graphite`` makes 41/42
    per machine on 21 machines, exactly 41/2 items/s against exactly 41/2 of
    demand.  Its four consumers do not fit one sorter reach so they shard two
    and two; the shard carrying ``graphene`` and ``plastic`` owes 31/2 items/s,
    which is 15.878 machines, and the other owes 5, which is 5.122.  There is
    no way to write 21 as two integers that cover 15.878 and 5.122, so ONE of
    the two shards starves whatever :func:`_allocate_machines` decides.  It
    chose 15 and 6, and ``flow.conservation`` reported 14 machines reaching
    205/14 items/s of the 31/2 they consume -- short by 6/7, which is exactly
    the surplus sitting on the other shard.  ``iron-ingot`` in the same build
    is the same shape: 7 machines making 14 against 15 of demand, with 6
    against 5 next door.

    Joining the two islands makes the spec's own arithmetic decide it, which is
    the only claim backpressure cannot rescue -- and it is exactly balanced,
    because the deficit was never anything but the other shard's surplus.

    Bought only where it is needed, for the reason recorded in
    :func:`_connect_short_cuts`: joining every sharded edge in full was measured
    corpus-wide and cost four clean cells, because the extra belts crowd both
    the router and the power lattice.  If every island can feed itself this adds
    nothing at all.  Measured over the twelve-URL corpus at three candidates
    each, thirty-six specs: it fires on ``universe-matrix`` alone, on all three
    of its candidates, and adds ONE net per item on two items.

    Islands are chained in order of DESCENDING balance, so each edge runs from
    the side with surplus to the side without.  ``_connect_short_cuts`` chains
    in union-find root order instead, which is arbitrary; that is sound for the
    validator, whose islands are undirected, but a belt is not.  Running the
    surplus downhill is the arrangement that also works in game.

    ``pairs`` are belt indices ``(producer lane, consumer lane)`` already
    linked, ``supply``/``demand`` are items/second per lane, and ``external``
    is what the player belts in -- credited to every island holding a consumer
    lane, because :func:`_route_external_inputs` runs an entry belt to every one
    of them, which is the same credit ``flow.conservation`` gives.
    """
    parent: dict[int, int] = {}

    def find(k: int) -> int:
        parent.setdefault(k, k)
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    # How many nets already meet each lane. A producer lane end becomes a
    # junction under `_tap_source` and a junction has four sides, so the extra
    # net goes on the least-used lane of the island rather than piling onto
    # whichever one sorts first.
    taps: dict[int, int] = defaultdict(int)
    for a, b in pairs:
        union(a, b)
        taps[a] += 1
        taps[b] += 1

    srcs: dict[int, list[int]] = defaultdict(list)
    sinks: dict[int, list[int]] = defaultdict(list)
    for belt in sorted(supply):
        srcs[find(belt)].append(belt)
    for belt in sorted(demand):
        sinks[find(belt)].append(belt)
    roots = sorted(set(srcs) | set(sinks))
    if len(roots) < 2:
        return []

    balance = {
        r: sum((supply[b] for b in srcs[r]), Fraction(0))
        + (external if sinks[r] else Fraction(0))
        - sum((demand[b] for b in sinks[r]), Fraction(0))
        for r in roots
    }
    if all(v >= 0 for v in balance.values()):
        return []

    order = sorted(roots, key=lambda r: (-balance[r], r))
    extra: list[tuple[int, int]] = []
    for a, b in zip(order, order[1:], strict=False):
        if not srcs[a] or not sinks[b]:
            continue
        extra.append(
            (
                min(srcs[a], key=lambda t: (taps[t], t)),
                min(sinks[b], key=lambda t: (taps[t], t)),
            )
        )
    return extra



def _build(
    spec: BuildSpec,
    strips: list[Strip],
    pack: _Pack,
    *,
    power: bool,
    route: bool,
    claim_power: bool = True,
    deadline: float | None = None,
    budget: dict[str, int] | None = None,
) -> tuple[Placement, int, int]:
    """Emit, wire and power one pack.

    Returns ``(placement, failed, towers)``.  ``failed`` is the number of nets
    left unrouted, and every caller discards a placement with any -- which is
    what makes ``deadline`` safe to thread in here.  Running out of clock is
    reported as route failures, so it produces a REFUSAL upstream and can never
    produce a placement missing its belts.
    """
    belt_id = BELT_ITEM_IDS.get(spec.belt_item_id, 2001)
    belt_model = catalog.building(belt_id).model_index
    canvas = _Canvas()

    rates: dict[str, Fraction] = {}
    for g in _adapt(spec).values():
        for item, r in list(g.inputs.items()) + list(g.outputs.items()):
            rates[item] = max(rates.get(item, Fraction(0)), r * g.count)

    # PER-ITEM per-machine rates, keyed by group. One sorter serves one machine
    # and moves one item, so that item's per-machine rate is exactly what the
    # sorter must sustain.
    #
    # This used to be the machine's TOTAL split evenly across its sorters, which
    # under-sizes whenever ingredient rates differ -- and they usually do.
    # `circuit-board` takes copper at 1/s and iron at 2/s; the 1.5/s average
    # exactly meets a Mk.I, so it read as clean while the sorter carrying the
    # iron starved the machine. The overloaded sorter hid behind the underloaded
    # one, and the validator averaged the same way so it never caught it.
    per_item: dict[str, tuple[Mapping[str, Fraction], Mapping[str, Fraction]]] = {
        key: (dict(g.inputs), dict(g.outputs)) for key, g in _adapt(spec).items()
    }

    # EVERY strip of a group keeps its port, not just the last one emitted.
    #
    # `out_lanes` names a destination GROUP, but a group is sharded into as many
    # strips as its machine count needs, and each shard carries its own input
    # lanes. Keying this by `(group_key, item)` alone let the second shard
    # overwrite the first, so exactly one shard became a net sink and every other
    # shard's lane was left orphaned -- belts in place, sorters in place, nothing
    # ever putting items onto them, and the machines behind them starving.
    #
    # It reported `route_failures == 0` throughout, because the nets that existed
    # did route; the missing ones were never created to fail.
    in_ports: dict[tuple[str, str], list[_Port]] = defaultdict(list)
    # The producer side collides the same way: sharding a producer gives several
    # strips the SAME destination set, so keying on (group, item, dest) alone
    # kept only the last strip's output lane. The others were emitted, drained by
    # nobody, and left as dead belts.
    out_ports: dict[tuple[str, str, str], list[_Port]] = defaultdict(list)
    strip_in_ports: list[dict[str, _Port]] = []
    # Flow-graph bookkeeping for `_join_shard_islands`, keyed by BELT index.
    #
    # `lane_supply` is credited PER STRIP, not per lane, and the strip's other
    # lanes for the same item are unioned onto the first through `sibling_lanes`
    # -- because one strip's machines drain into every one of its own output
    # lanes, so those lanes are one island however the destinations divide, and
    # crediting each of them the strip's full output would count a two-lane
    # shard's production twice. That mistake makes a starving shard read as
    # healthy, which is the exact failure this bookkeeping exists to find.
    lane_of: dict[int, _Port] = {}
    lane_supply: dict[str, dict[int, Fraction]] = defaultdict(dict)
    lane_demand: dict[str, dict[int, Fraction]] = defaultdict(dict)
    sibling_lanes: dict[str, list[tuple[int, int]]] = defaultdict(list)
    sorters = 0
    for i, s in enumerate(strips):
        ox, oy = pack.at[i]
        ins, outs, placed = _emit_strip(
            canvas,
            s,
            ox,
            oy,
            belt_id,
            belt_model,
            rates,
            *per_item.get(s.group_key, ({}, {})),
        )
        sorters += placed
        strip_in_ports.append(ins)
        for item, port in ins.items():
            in_ports[s.group_key, item].append(port)
        made = per_item.get(s.group_key, ({}, {}))[1]
        by_item: dict[str, list[int]] = defaultdict(list)
        for (item, dest), port in outs.items():
            out_ports[s.group_key, item, dest].append(port)
            lane_of[port.belt] = port
            by_item[item].append(port.belt)
        for item, belts in by_item.items():
            belts.sort()
            lane_supply[item][belts[0]] = s.machines * made.get(item, Fraction(0))
            for b in belts[1:]:
                lane_supply[item][b] = Fraction(0)
                sibling_lanes[item].append((belts[0], b))

    # Nets the packer arranged to bridge directly become a single sorter and no
    # belt route at all -- that saving IS the feature, so it happens before the
    # net list is built rather than as a post-pass over routed belts.
    direct_keys = {
        (strips[i].group_key, strips[j].group_key) for i, j in pack.direct
    }
    direct_placed = 0

    nets: list[_Net] = []
    # Everything already joined for an item, so `_join_shard_islands` can see
    # the flow graph the whole build makes rather than one edge of it. Keyed by
    # BELT index, which is what makes a lane serving several destinations one
    # node instead of several.
    joined: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for (src_key, item, dest_group), srcs in out_ports.items():
        # One output lane may serve SEVERAL destination groups -- see
        # `_merge_lanes` -- and each of them is its own set of consumer strips to
        # pair against. They all tap the same lane end, where `_tap_source`
        # builds the junction, exactly as it already does when ONE destination is
        # sharded across several consumer strips.
        out_rate = per_item.get(src_key, ({}, {}))[1].get(item, Fraction(0))
        for dest in _dests(dest_group):
            sinks = in_ports.get((dest, item), [])
            if not srcs or not sinks:
                continue
            in_rate = per_item.get(dest, ({}, {}))[0].get(item, Fraction(0))
            # The per-machine rates on both sides, so the pairing can tell an
            # island that feeds itself from one that starves.
            for port, sink in _pair_lanes(
                srcs, sinks, out_rate=out_rate, in_rate=in_rate
            ):
                joined[item].append((port.belt, sink.belt))
                lane_of[sink.belt] = sink
                lane_demand[item][sink.belt] = sink.machines * in_rate
                if (src_key, dest) in direct_keys and _bridge(
                    canvas, port, sink, rates, item
                ):
                    direct_placed += 1
                    continue
                nets.append(_Net(src=port, dst=sink, item=item))

    # A shard of a producer that cannot feed its own destinations is joined to
    # one that can. Nothing inside the pairing above can see this, because two
    # shards of one group are never handed to it together -- see
    # `_join_shard_islands` for the arithmetic that forces it.
    for item in sorted(set(joined) | set(sibling_lanes)):
        for a, b in _join_shard_islands(
            joined[item] + sibling_lanes[item],
            lane_supply[item],
            lane_demand[item],
            spec.external_inputs.get(item, Fraction(0)),
        ):
            nets.append(_Net(src=lane_of[a], dst=lane_of[b], item=item))

    # Hold one cell beside every port BEFORE anything else can take it.
    #
    # Coater drop belts and external input runs are placed onto a canvas that is
    # otherwise empty, so they take whatever cell suits them -- and a lane head's
    # only free neighbour is exactly the sort of cell that suits them. The net
    # that needed it is then handed an EMPTY goal set: A* returns None having
    # expanded nothing, and no amount of rip-up can negotiate for a cell that is
    # occupied by a building rather than contested by another path.
    #
    # Measured across the trivial+small+mid corpus, before this: every boxed-in
    # port on the refusing candidates had a coater drop or an external belt on
    # its one open side, and the boxed-in count equalled the failure count
    # exactly. `_route_all` re-derives these once every path is laid, so this is
    # a claim staked early rather than a second source of truth.
    def hold_ports() -> None:
        # A lane carrying an external ingredient AND an internally produced one
        # has two feeds to accept, not one, so it needs two ways in.
        net_ports = {(p.x, p.y) for n in nets for p in (n.src, n.dst)}
        shared_feed = {
            (port.x, port.y)
            for ports in strip_in_ports
            for item, port in ports.items()
            if item in spec.external_inputs
        } & net_ports
        _reserve_port_access(canvas, nets, twice=shared_feed)

    if route:
        hold_ports()

    # Coaters go in BEFORE routing, because each one needs a proliferator net
    # routed to its drop belt. Placing them afterwards -- as this used to --
    # leaves them mounted on belts with nothing feeding them, so every
    # proliferated recipe silently runs unproliferated.
    coater_list: list[_Coater] = []
    prolif_item = _proliferator_item(spec)
    if spec.spray_lanes:
        coater_list = _place_coaters(
            canvas, spec, strips, strip_in_ports, belt_id, belt_model
        )
    coaters = len(coater_list)

    # THE EXTENT IS DECIDED HERE, and nothing after this point may move it.
    #
    # Every pass that follows -- the proliferator entry, the external input
    # runs, the router, the power lattice -- used to compute "the edge" for
    # itself, from a canvas the previous pass had just extended. Each was
    # correct about where the boundary was when it looked, and wrong by the time
    # the placement was finished; the entry tiles the validator reports as
    # walled in are precisely the ones that were on the boundary when placed.
    #
    # Reordering the passes cannot fix that, and two orderings were measured
    # proving it. Fixing the box can: the strips and their coaters define the
    # core, `_ENTRY_RING` rings of margin are reserved around it, and
    # `canvas.limit` refuses any cell beyond. The ring one further out is then
    # empty by construction, which is what makes an entry belt reachable from
    # outside no matter what else the router does.
    core = _core_bounds(canvas)
    canvas.limit = _grow(core, _ENTRY_RING)
    route_bounds = _grow(core, _ROUTE_RING)

    # The proliferator entry is staked BEFORE the ports are held, not after the
    # external runs have settled. It can be: its cell is reserved ground that no
    # other pass can reach, so it no longer matters who runs first. Having its
    # nets exist at reservation time is what the previous ordering gave up --
    # the coater drops those nets sink into then went unheld, and the external
    # runs walled them in instead.
    if coater_list and prolif_item is not None:
        entry = _place_proliferator_entry(
            canvas, prolif_item, belt_id, belt_model, core
        )
        if entry is not None:
            nets.extend(
                _proliferator_nets(canvas, entry, coater_list, prolif_item)
            )

    # Again, now that every port exists -- strip lanes, coater drops and the
    # proliferator entry alike. A drop is a one-tile lane and the sink of a
    # proliferator net, so it is a port like any other, and it did not exist
    # when the first claim was staked.
    if route:
        hold_ports()

    # The tower lattice claims its ground AFTER the ports have claimed theirs,
    # and before anything routes.
    #
    # Both halves of that matter and they used to be one. The lattice claimed
    # first, on the argument that power is otherwise handed whatever a dense
    # block has left, which is nothing -- that argument is right and the claim
    # stays ahead of the router. But it also ran ahead of the SECOND
    # `hold_ports`, which is the one that sees the coater drops and the
    # proliferator entry, and `_reserve_port_access` clears and re-stakes every
    # reservation when it runs. So a lattice point could sit on a port's one
    # open side and the re-stake would find it gone.
    #
    # Measured on `casimir-crystal/max-proliferation`: twelve ports boxed in,
    # every one of them by a machine, two lane belts and a lattice keep-out
    # cell. The two claims are not symmetric -- a displaced lattice point has a
    # whole tower radius of ground to be displaced INTO, and `_place_power`
    # repairs coverage besides, while a port with no free neighbour has no
    # second option at all and takes its net down with it.
    power_sites = _claim_power_sites(canvas, core) if power and claim_power else []

    # Bring the outside inputs in FIRST. They have no alternative: an internal
    # net can be routed around an obstacle, but an external lane can only be
    # reached from beyond the block, and a strip's inner lanes have exactly one
    # way in. Routing the internal nets first let them take those cells -- on
    # the graphene chain two external lanes were walled in by belts that had a
    # dozen other routes available. First claim goes to the side that has no
    # second choice.
    unreachable = 0
    if route:
        unreachable = _route_external_inputs(
            canvas, spec, strip_in_ports, belt_id, belt_model, core, deadline, budget
        )

    routed, failed, iterations = (0, 0, 0)
    if route and nets:
        routed, failed, iterations = _route_all(
            canvas, nets, belt_id, belt_model, route_bounds, deadline, budget
        )
    failed += unreachable

    # Port access reservations are spent once the last net is committed. Holding
    # them into the power pass costs coverage for nothing: a reserved cell reads
    # as occupied to `free`, so the tower that would have covered a machine
    # cannot be placed there, and the machine ships unpowered. That got sharply
    # worse once a port with two jobs began holding two cells -- twenty coater
    # drops became forty cells the lattice could not use, and the repair pass
    # then failed to cover fourteen buildings on a block with room to spare.
    canvas.reserved.clear()
    # Tentative path markers outlive the round that made them: the round that
    # succeeds commits and returns without clearing its own, and any cell
    # `_commit_paths` decided not to build on keeps a marker with no building
    # under it. `free` reads those as occupied, so the lattice treats empty
    # ground as taken.
    for cell in [c for c, owner in canvas.blocked.items() if owner == _TENTATIVE]:
        del canvas.blocked[cell]
    canvas.keep_out.clear()
    # A build with an unrouted net is a build the caller will discard, so it
    # does not pay for the power pass -- which is a full sweep of every powered
    # tile against every tower and is seconds on a large block.
    #
    # Guarded on `failed`, never on the deadline. A build that WIRED is a real
    # candidate whatever the time is, and returning one with no towers because
    # the clock was short would be a `power.coverage` INVALID manufactured by a
    # stopwatch -- the exact thing a deadline must not do. But `failed` is not a
    # stopwatch: `_sweep` discards any pack with one, unconditionally, so every
    # second spent covering it is spent on something already thrown away.
    #
    # This used to also require the deadline to have passed, which meant a
    # doomed build paid in full whenever it failed EARLY -- the worst case, since
    # failing early is exactly when there was still clock to spend on the next
    # height. Measured at a 15s ceiling on `universe-matrix/no-proliferator`
    # power=1: routing conceded at 8.05s with ten nets short and the power pass
    # then ran to 14.30s, so six of the remaining seven seconds went on a
    # placement nothing was ever going to look at.
    towers = _place_power(canvas, power_sites) if power and not failed else 0

    placement = Placement(
        buildings=tuple(canvas.buildings),
        description=f"flab2bp freeform layout ({spec.label or 'default'})",
        short_desc=spec.label or "flab2bp",
        stats={
            "machines": float(spec.machine_count),
            "strips": float(len(strips)),
            "sorters": float(sorters),
            "towers": float(towers),
            "spray_coaters": float(coaters),
            "nets": float(len(nets)),
            "routed": float(routed),
            "route_failures": float(failed),
            "repair_iterations": float(iterations),
            "belt_tiles": float(
                sum(1 for b in canvas.buildings if catalog.is_belt(b.item_id))
            ),
            "direct_inserts": float(direct_placed),
        },
    )
    return placement, failed, towers


def _bridge(
    canvas: _Canvas,
    src: _Port,
    dst: _Port,
    rates: dict[str, Fraction],
    item: str,
) -> bool:
    """Span two lane ends with one sorter, replacing a whole belt route.

    Returns ``False`` rather than placing an illegal sorter if the packed
    geometry did not actually come out within reach.  The packer's reification
    should guarantee it does, but a sorter that cannot exist would produce a
    blueprint that pastes and then does not run -- the worst failure mode -- so
    this is checked rather than assumed.
    """
    span = dst.y - src.y
    if span < 1 or span > catalog.SORTER_MAX_REACH:
        return False

    # Any column both lanes cover will do, so take the westmost shared one.
    shared = range(max(src.x0, dst.x0), min(src.x1, dst.x1) + 1)
    column = next(
        (
            x
            for x in shared
            if (x, src.y, 0) in canvas.blocked and (x, dst.y, 0) in canvas.blocked
        ),
        None,
    )
    if column is None:
        return False

    src_belt = canvas.blocked[column, src.y, 0]
    dst_belt = canvas.blocked[column, dst.y, 0]
    if src_belt == dst_belt:
        return False

    tier, _ = _pick_sorter(rates.get(item, Fraction(1)), span, 1)
    canvas.buildings.append(
        PlacedBuilding(
            item_id=tier,
            model_index=catalog.building(tier).model_index,
            x=column,
            y=src.y,
            width=1,
            height=1,
            x2=column,
            y2=dst.y,
            z2=0,
            yaw=Facing.SOUTH.value,
            yaw2=Facing.SOUTH.value,
            input_obj=src_belt,
            output_obj=dst_belt,
        )
    )
    return True


@dataclass(frozen=True, slots=True)
class _Coater:
    """A placed Spray Coater and the belt tile that will feed it proliferator."""

    coater: int
    #: A one-tile belt in the strip's east margin, the sink of a proliferator net.
    drop: int
    x: int
    y: int


def _place_coaters(
    canvas: _Canvas,
    spec: BuildSpec,
    strips: list[Strip],
    ports: list[dict[str, _Port]],
    belt_id: int,
    belt_model: int,
) -> list[_Coater]:
    """One Spray Coater per sprayed input lane, each with a supply drop.

    A coater is a belt addon: it consumes no grid tile, so proliferation costs
    almost nothing in area.  The real cost is that it forces its edge onto a
    belt, which is what forbids direct insertion there.

    Two things this has to get right, both of which it previously did not:

    * **The coater must sit on the lane carrying the item it sprays.**  The old
      version took ``next(belt for belt in canvas.buildings ...)`` -- the first
      belt anywhere on the canvas -- so every coater piled onto one unrelated
      tile.
    * **It must be reachable from a proliferator supply.**  A coater with
      nothing feeding it sprays nothing, and the build then runs unproliferated
      while looking perfectly healthy.  Each coater gets a one-tile ``drop``
      belt in its strip's east margin, one tile away, which a proliferator net
      is routed to and a sorter bridges.

    The east margin is reserved by ``_pack`` (each strip claims ``width +
    MARGIN``) and nothing is emitted into it, so the drop cell is free by
    construction rather than by luck.
    """
    coater = catalog.building(catalog.SPRAY_COATER_ID)
    wanted = set(spec.spray_lanes)
    out: list[_Coater] = []

    belt_at: dict[tuple[int, int, int], int] = {
        (b.x, b.y, b.z): i
        for i, b in enumerate(canvas.buildings)
        if catalog.is_belt(b.item_id)
    }

    for s, in_ports in zip(strips, ports, strict=True):
        for item in s.in_lanes:
            if item not in wanted:
                continue
            port = in_ports.get(item)
            if port is None:
                continue
            # East end of this lane: nearest the margin the drop belt lives in.
            cx, cy = port.x1, port.y
            host = belt_at.get((cx, cy, 0))
            drop_cell = (cx + 1, cy, 0)
            if host is None or not canvas.free(drop_cell):
                continue

            drop = canvas.add(
                PlacedBuilding(
                    item_id=belt_id,
                    model_index=belt_model,
                    x=drop_cell[0],
                    y=drop_cell[1],
                    width=1,
                    height=1,
                    carries_item=_proliferator_item(spec),
                )
            )
            idx = len(canvas.buildings)
            canvas.buildings.append(
                PlacedBuilding(
                    item_id=catalog.SPRAY_COATER_ID,
                    model_index=coater.model_index,
                    x=cx,
                    y=cy,
                    width=1,
                    height=1,
                    yaw=Facing.EAST.value,
                )
            )
            # Sorter drop -> coater, span 1. Anchors sit on the two buildings;
            # the connection indices carry the semantics.
            sorter = SORTER_TIERS[0]
            canvas.buildings.append(
                PlacedBuilding(
                    item_id=sorter,
                    model_index=catalog.building(sorter).model_index,
                    x=drop_cell[0],
                    y=drop_cell[1],
                    width=1,
                    height=1,
                    x2=cx,
                    y2=cy,
                    z2=0,
                    yaw=Facing.WEST.value,
                    yaw2=Facing.WEST.value,
                    input_obj=drop,
                    output_obj=idx,
                )
            )
            out.append(_Coater(coater=idx, drop=drop, x=drop_cell[0], y=drop_cell[1]))
    return out


def _proliferator_item(spec: BuildSpec) -> str | None:
    """The proliferator belted in, if any.

    It is an external input with no consuming machine -- coaters consume it --
    which is exactly why no lane was ever created for it.
    """
    for item in sorted(spec.external_inputs):
        if item.startswith("proliferator"):
            return item
    return None


def _proliferator_nets(
    canvas: _Canvas, entry: _Port, coaters: list[_Coater], item: str
) -> list[_Net]:
    """Thread ONE belt from the entry through every coater drop in turn.

    Every coater needs the same item at a trivial rate (well under one item per
    second in total, against a belt that carries twelve), so one lane serves all
    of them and capacity never binds.

    Chained rather than fanned out, for two independent reasons.

    Routing each drop separately from the entry costs far more: eleven paths all
    radiating from one corner roughly doubled the bounding box.

    And a fan-out cannot be built without splitters, which is worse than
    expensive.  A branch drawn off a splitter is a belt run of its own, fed by
    the junction rather than by a belt, and nothing inside the blueprint fills
    it -- so every branch reads as a separate lane the player must belt
    proliferator into, buried in the middle of the block where no belt can
    reach.  Measured: fanning out turned one entry lane into twenty unreachable
    ones across the corpus.  A chain has no junctions at all; it is a single
    linear run that starts at the entry belt, out on the reserved ring where the
    player can get to it.

    Nearest-neighbour order keeps each hop short, and a hop of length one is
    LINKED RATHER THAN ROUTED.  Two coaters on neighbouring lanes of one strip
    put their drops in the same margin column, one directly above the other, and
    the lower one then has a single free neighbour in the world -- the margin is
    one tile wide, the lane is west of it and a machine south.  A chain needs two
    ways into such a drop, one for the hop arriving and one for the hop leaving,
    and there is only ever one: whichever hop routed first took it and the other
    was handed an empty goal set.  Linking the pair directly costs no cell at
    all and leaves each of them needing exactly one.
    """
    remaining = list(coaters)
    src = entry
    nets: list[_Net] = []
    while remaining:
        nxt = min(remaining, key=lambda c: abs(c.x - src.x) + abs(c.y - src.y))
        remaining.remove(nxt)
        dst = _Port(nxt.drop, nxt.x, nxt.y, nxt.x, nxt.x)
        if abs(nxt.x - src.x) + abs(nxt.y - src.y) == 1:
            canvas.buildings[src.belt] = _relink(
                canvas.buildings[src.belt], output_obj=dst.belt
            )
        else:
            nets.append(_Net(src=src, dst=dst, item=item))
        src = dst
    return nets


def _place_proliferator_entry(
    canvas: _Canvas,
    item: str,
    belt_id: int,
    belt_model: int,
    core: tuple[int, int, int, int],
) -> _Port | None:
    """The block's proliferator input belt, on the reserved entry ring.

    A single entry tile: the router fans out from here to each coater's drop,
    and DSP belts merge natively, so no splitter is needed.

    It goes on the NORTH-WEST CORNER of the entry ring, and the corner is the
    point.  Nothing else can ever be placed further out -- the router and the
    power lattice are held inside ``_ROUTE_RING`` and the external input runs
    stop on the entry ring itself -- so this tile is on the finished block's
    bounding box in two directions at once and has open ground beside it by
    construction.  It used to be placed one tile west of wherever the buildings
    happened to reach at that moment, which was the boundary right up until the
    next pass moved it; the tile then sat interior, walled in on four sides,
    with an icon on it telling the player to belt proliferator into somewhere
    they cannot reach.

    A corner also keeps it clear of the straight input runs, which leave along
    strip rows and columns and so never use one.
    """
    x, y = core[0] - _ENTRY_RING, core[1] - _ENTRY_RING
    if not canvas.free((x, y, 0)):
        return None
    idx = canvas.add(
        PlacedBuilding(
            item_id=belt_id,
            model_index=belt_model,
            x=x,
            y=y,
            width=1,
            height=1,
            carries_item=item,
        )
    )
    return _Port(idx, x, y, x, x)


def _fanout_shortfall(strips: list[Strip]) -> list[str]:
    """Producer lanes with fewer tiles than the consumers they must tap.

    ``_build`` pairs the two sides of an edge cyclically -- ``srcs[k % len(srcs)]``
    against ``sinks[k % len(sinks)]`` -- so whichever side is sharded further is
    fully served.  More sinks than sources means a producer lane is reused, and
    each reuse taps a different tile of that lane and junctions there.

    That works right up to the point where the lane runs out of tiles: two taps
    on one tile would need two splitters on one square.  A lane is as wide as
    its strip, so this is rare -- but it is a property of the STRIP PLAN, decided
    before any packing exists, and worth knowing before the height sweep rather
    than after.  A spec that trips it refuses at every height and every budget,
    and each attempt costs a full sweep plus the retry at
    :data:`RETRY_BUDGET_S`.

    Returns one description per offending edge, empty when the plan is servable.
    """
    src_lanes: dict[tuple[str, str, str], int] = defaultdict(int)
    src_tiles: dict[tuple[str, str, str], int] = {}
    sink_lanes: dict[tuple[str, str], int] = defaultdict(int)
    for s in strips:
        for item, dest in s.out_lanes:
            for d in _dests(dest):
                key = (s.group_key, item, d)
                src_lanes[key] += 1
                src_tiles[key] = min(src_tiles.get(key, s.width), s.width)
        for item in s.in_lanes:
            sink_lanes[s.group_key, item] += 1

    out: list[str] = []
    for (src_key, item, dest), n_src in sorted(src_lanes.items()):
        n_sink = sink_lanes.get((dest, item), 0)
        if n_sink <= n_src:
            continue
        # Taps land on the narrowest lane of the group, so that is the one that
        # can run out. Ceiling division: the reuse is spread round-robin.
        per_lane = -(-n_sink // n_src)
        tiles = src_tiles[src_key, item, dest]
        if per_lane > tiles:
            out.append(
                f"{item}: {src_key} lane is {tiles} tile(s) wide but must tap "
                f"{per_lane} consumer lane(s) of {dest}"
            )
    return out


def fallback_placement(spec: BuildSpec, *, power: bool = True) -> Placement:
    """One strip per group, stacked vertically.  NOT a usable layout.

    It cannot fail to *construct*, which is a different and much weaker property
    than the "always valid" it was once documented with.  It calls
    ``_build(route=False)``: it never attempts the wiring, so it cannot report
    that the wiring is impossible, and on real specs it is not routable.  That
    is why :class:`FreeformLayout` no longer falls back to it -- returning it
    when the solver found nothing returned a smaller *broken* layout in place of
    an honest refusal.

    Kept only because :mod:`flab2bp.layout.packsolver`, the rejected
    PackingSolver experiment, still calls it.  Do not add callers; if you want
    the construction for its bounding value, use :func:`_greedy_pack`, which is
    what :func:`_pack` warm-starts from.
    """
    strips = plan_strips(spec, strip_len=max(1, spec.machine_count))
    at: dict[int, tuple[int, int]] = {}
    y = 0
    for i, s in enumerate(strips):
        at[i] = (0, y)
        y += s.height + MARGIN
    width = max((s.width for s in strips), default=1) + MARGIN
    pack = _Pack(at=at, width=width, height=y, status="fallback")
    placement, _failed, _towers = _build(spec, strips, pack, power=power, route=False)
    placement.stats["fallback_used"] = 1.0
    placement.stats["solver_status"] = 0.0
    # The fallback stacks strips vertically without ever asking whether two of
    # them could sit within sorter reach, so it direct-inserts nothing. `_build`
    # already reported 0; this stays only to keep the key present when a caller
    # reads the fallback's stats without checking `fallback_used` first.
    placement.stats.setdefault("direct_inserts", 0.0)
    placement.stats["direct_insert_candidates"] = 0.0
    placement.stats["hit_time_budget"] = 0.0
    placement.stats["area"] = float(placement.area)
    return placement


class FreeformLayout:
    """Free-form packing plus belt routing."""

    name = "freeform"

    def __init__(
        self,
        *,
        power: bool = True,
        strip_len: int = 6,
        workers: int | None = None,
        direct_insert: bool = True,
    ) -> None:
        self.power = power
        self.strip_len = strip_len
        #: CP-SAT search workers. ``None`` takes the module default (all
        #: cores); the bake-off pins ``DETERMINISTIC_WORKERS``.
        self.workers = DEFAULT_SEARCH_WORKERS if workers is None else workers
        #: Off only for A/B measurement -- the feature is worth having, but
        #: proving it works means comparing against its own absence.
        self.direct_insert = direct_insert

    def lay_out(self, spec: BuildSpec, *, time_budget_s: float = 60.0) -> Placement:
        """Return the densest ROUTABLE ``Placement``, or raise :class:`NoValidLayout`.

        Routability is a condition for existing, not a ranking key.  It used to
        be the latter -- packs were ordered ``(routable, area, belt_tiles)`` and
        the least-bad one was returned even when every height failed to wire --
        which meant a pack nothing could connect still came back, still got
        measured, and measured *small*: an unrouted net is a belt run that does
        not exist, so the broken pack has the tighter bounding box and wins.
        That is how a build with 119 unrouted nets scored as the densest
        candidate on offer.

        The old escape hatch, :func:`fallback_placement`, is gone from this path.
        It was documented as routable by construction and is not -- it calls
        ``_build(route=False)``, so it never even attempts the wiring it claims.
        On the calibration spec it returned 3162 tiles against the solver's 2208
        while carrying the same unsourced lanes, so it traded area away for
        nothing.  What replaces it is the shelf packing it was built on, handed
        to :func:`_pack` as a warm start: same construction, bounding the search
        instead of substituting for it.

        A sweep that produces no routable pack is retried ONCE at
        :data:`RETRY_BUDGET_S` before refusing.

        ``time_budget_s`` IS A WALL-CLOCK DEADLINE FOR THE WHOLE CALL, not a
        packing budget.  It used to be the latter, and the difference was
        measured in minutes: the sweep spent it, the retry spent
        ``RETRY_BUDGET_S`` on top, the shelf sweep had a budget of its own, and
        the routing inside every one of them was bounded by an expansion count
        rather than by a clock.  Every phase was bounded and nothing bounded
        their sum, so a nominal 4 seconds measured at 34s on
        ``casimir-crystal``, 80s on ``quantum-chip`` and over 400s on a refusing
        ``universe-matrix`` cell -- which is what made a full corpus audit an
        hour and a half.

        The ceiling is ``max(time_budget_s, RETRY_BUDGET_S)``: the escalation to
        fifteen seconds is a promise this keeps, so a caller asking for less
        still gets the retry, and a caller asking for more gets what they asked
        for.  Every phase takes what is left of it, and a phase that finds the
        clock already spent is not started.

        Running out of it RAISES.  A deadline may cost a placement -- and the
        cells it costs are named in the commit message rather than bought back
        by raising the ceiling -- but it can never return a degraded one: the
        clock is only ever read where the answer is "this net did not route",
        and a pack with an unrouted net is discarded, never emitted.
        """
        if time_budget_s <= 0:
            raise NoValidLayout(
                "no time budget was given, so the packer was never asked",
                spec_label=spec.label,
                budget_s=time_budget_s,
            )

        ceiling = max(time_budget_s, RETRY_BUDGET_S)
        started = time.monotonic()
        deadline = started + ceiling
        # ONE routing budget for the call. `_MAX_EXPANSIONS` bounds a single
        # search and `_ROUTING_BUDGET` bounded one routing pass; nothing bounded
        # the ten to twenty passes a sweep makes, so the packer could spend it
        # over and over. The wall clock bounds them in seconds; this bounds them
        # deterministically, which is what keeps a re-run reproducible -- and it
        # is scaled to the ceiling so that it stays a backstop rather than
        # becoming the thing that ends the sweep. See
        # `_ROUTING_EXPANSIONS_PER_SECOND`.
        budget = {
            "left": max(
                _ROUTING_BUDGET, int(_ROUTING_EXPANSIONS_PER_SECOND * ceiling)
            )
        }

        try:
            strips = plan_strips(spec, strip_len=self.strip_len)
        except (ValueError, KeyError) as exc:
            # One retry with every machine of a group on a single strip. That is
            # the coarsest legal strip plan, so if it also fails the spec cannot
            # be turned into strips at all and no budget will change that.
            try:
                strips = plan_strips(spec, strip_len=max(1, spec.machine_count))
            except (ValueError, KeyError):
                raise NoValidLayout(
                    f"the spec cannot be split into strips: {exc}",
                    spec_label=spec.label,
                    budget_s=time_budget_s,
                ) from exc
        if not strips:
            raise NoValidLayout(
                "the spec contains no machine groups",
                spec_label=spec.label,
                budget_s=time_budget_s,
            )

        # Refuse a strip plan that no packing can serve BEFORE sweeping heights.
        # This is not an optimisation of the failure path, it is the difference
        # between an error that names the cause and one that blames the packer:
        # the sweep would try every height, retry the lot at RETRY_BUDGET_S, and
        # report "left nets unrouted" -- 51s on the magnetic-ring chain to
        # rediscover something fixed the moment the strips were planned.
        #
        # Fan-out itself is no longer a shortfall: a lane serving several
        # consumers taps a different tile for each and junctions there. What
        # remains unservable is a lane with fewer TILES than taps to make, since
        # two taps on one tile would need two splitters on one square.
        shortfall = _fanout_shortfall(strips)
        if shortfall:
            raise NoValidLayout(
                "a producer lane has fewer tiles than the consumers it must tap, "
                "so two junctions would have to share one tile. " + "; ".join(shortfall[:3]),
                spec_label=spec.label,
                budget_s=0.0,
            )

        budgets = [time_budget_s]
        if time_budget_s < RETRY_BUDGET_S:
            budgets.append(RETRY_BUDGET_S)

        #: Checks that threw a placement out AFTER it wired -- see `_sweep`.
        rejected: set[str] = set()
        for sweep_s in budgets:
            if _expired(deadline):
                break
            best = self._sweep(spec, strips, sweep_s, deadline, budget, rejected)
            if best is not None:
                return best

        # A build that WIRED and then failed our own validator is a different
        # defect from one that could not be wired, and saying so is the whole
        # value of checking: "the packer produced packs its own router cannot
        # wire" would be false here and would send the next reader to the packer.
        if rejected:
            raise NoValidLayout(
                "every packing that wired was rejected by our own validator ("
                + ", ".join(sorted(rejected))
                + "); a placement that fails validation is refused rather than "
                "returned, because an invalid blueprint pastes and then does not "
                "run",
                spec_label=spec.label,
                budget_s=budgets[-1],
            )
        if _expired(deadline):
            raise NoValidLayout(
                f"the {ceiling:g}s deadline passed with no wired packing of "
                f"{len(strips)} strips; the sweep and the retry between them ran "
                "out of clock rather than out of candidates, so this is a "
                "REFUSAL and not a verdict on the spec",
                spec_label=spec.label,
                budget_s=ceiling,
            )
        raise NoValidLayout(
            f"no packing of {len(strips)} strips could be wired at any candidate "
            "height; every pack the sweep produced left nets unrouted. That is a "
            "PACKER defect -- it is producing packs its own router cannot wire -- "
            "and it is reported rather than papered over with a looser packing",
            spec_label=spec.label,
            budget_s=budgets[-1],
        )

    def _sweep(
        self,
        spec: BuildSpec,
        strips: list[Strip],
        time_budget_s: float,
        deadline: float | None = None,
        budget: dict[str, int] | None = None,
        rejected: set[str] | None = None,
    ) -> Placement | None:
        """Try every candidate height, returning the best FULLY ROUTED placement.

        ``None`` means no height produced one -- which is a refusal, not a
        degraded answer.  Packs with unrouted nets are discarded here rather than
        ranked below routed ones, so an unwireable pack can never be what this
        returns, and neither can one our own validator rejects.

        ``rejected`` collects the check names of placements thrown out by that
        self-check, so the refusal can say WHICH promise the build broke instead
        of blaming the packer for a pack that wired perfectly well.

        ``time_budget_s`` bounds the WHOLE sweep, not just CP-SAT.  It used to
        bound only the packing: routing is limited by an expansion count, not a
        clock, so a 1s budget could spend 13.5s and a 4s budget 68.6s -- both on
        specs that then refused.  A caller who says one second and waits over a
        minute has not been given a budget, and the bake-off cannot sweep a
        parameter the code ignores.

        The deadline is checked between heights rather than inside them: a
        half-routed pack is not a result, so interrupting one wastes the work
        without producing anything.  Whatever has already been found is
        returned, which is why the heights most likely to pay off are tried
        first.
        """
        candidates = _direct_insert_candidates(spec)
        greedy = _greedy_pack(strips, _height_seed(strips))
        bound = max(greedy.width, max((w for w, _h in map(_box, strips)), default=1))
        net_candidates = (
            _direct_net_candidates(strips, spec) if self.direct_insert else {}
        )

        # SHORTEST FIRST, and TALLEST-first was tried against it and reverted.
        #
        # The case for reversing rested on a diagnosis that later measurement
        # CONTRADICTED, and it is left here with the correction rather than
        # quietly deleted, because the numbers under it are still real.
        #
        # The story was that the scarce resource is the east-west corridor: a
        # strip's machine band blocks every level, so the only way past a strip
        # is the one-row channel on its south face, and a wide pack asks its nets
        # to cross the whole width through those. That is not what the failures
        # are. Flooding from the start cells of failing searches says the median
        # reachable region is ONE CELL -- see `_reserve_port_access`, which now
        # holds the way out of it. Nothing is crossing anything; the source port
        # cannot leave its own access cell. A one-row corridor also carries three
        # belts, not one, since only machines are solid at every level.
        #
        # What the measurement under it DOES show is that some heights wire and
        # others do not, unpredictably, and shortest-first can spend the whole
        # ceiling short of the one that would. Routing every candidate height of
        # `quantum-chip/max-proliferation` with a 20M expansion budget and no
        # clock: h=30 w=104 left two nets unrouted, h=40 w=87 three, h=50 w=61
        # four, h=62 w=52 three, and h=80 w=39 routed EVERY net. It reads as a
        # width story and is not one -- `quantum-chip/no-proliferator` at a fixed
        # w=56 fails 12 nets at h=170, none at h=255 and h=340, and one again at
        # h=595, on a canvas with 33,000 tiles for 40 strips. Which heights wire
        # is a property of the arrangement, not of how much room it has.
        #
        # It measured 60/72 clean at 4s, which is what shortest-first measures,
        # with the refusals shuffled between cells. The gain on `quantum-chip` is
        # paid straight back on `universe-matrix`, whose tall packs are both
        # wider AND slower to route, so the sweep reaches fewer of them. Reverted
        # for want of a number, not for want of a reason: a height ORDER that
        # depended on the strips rather than on a fixed direction is the shape
        # this wants, and nobody has built one.
        #
        # `universe-matrix` is where that would have to pay off and it is not
        # close. With the port exits held, its five candidate heights at 10s of
        # packing each and NO routing clock leave 29, 4, 26, 23 and 10 nets
        # unrouted -- so no order over these five reaches a pack that wires, and
        # each pass costs 25-40 seconds against a ceiling of 15 or 120. All six
        # of its cells refuse at both budgets and they are named in the commit
        # message rather than bought back.
        # SO HERE IS THAT ORDER, AND IT DEPENDS ON THE STRIPS.
        #
        # Not "shortest", not "tallest": NARROWEST-PACK FIRST, measured on the
        # greedy shelf pack each height gets as its warm start.  Routing cost is
        # a function of how far a net has to travel and a pack's width is what
        # sets that, so the cheapest height to WIRE is the one whose pack comes
        # out narrowest -- whichever direction that happens to lie in.
        #
        # Measured on `universe-matrix/no-proliferator` power=0, one routing
        # pass per height on a fixed pack, no routing clock:
        #
        #   h= 69  w=361  26.4s      h= 92  w=309  19.0s
        #   h=116  w=255  28.5s      h=145  w=226  17.3s
        #   h=185  w=188   7.5s
        #
        # Its tallest height is its NARROWEST and routes three times faster than
        # the shortest, which the sweep used to try first and never get past.
        # The note above says tall packs here are "both wider AND slower"; the
        # second half is right and the first is backwards, which is how that
        # experiment came out even.
        #
        # The greedy pack is already built per height as `_pack`'s seed, so
        # building them all up front costs nothing and only moves the work.
        seeds = {height: _greedy_pack(strips, height) for height in _candidate_heights(strips)}
        heights = sorted(seeds, key=lambda height: (seeds[height].width, height))
        # This sweep's own share, never more than the CALL has left. A sweep
        # asked for 15s when 3 remain must not spend 15.
        left = time_budget_s if deadline is None else deadline - time.monotonic()
        share = max(0.1, min(time_budget_s, max(left, 0.0)))
        # AND PACKING ONLY GETS PART OF IT.
        #
        # This was `share / len(heights)`, which hands CP-SAT the WHOLE ceiling
        # -- five heights times a fifth of it each -- and leaves routing to run
        # on whatever the deadline had not already spent.  It only ever looked
        # affordable because the first height's routing overran and the other
        # four were never packed.  Measured at a 15s ceiling on
        # `universe-matrix`: one height packed at 3.18s, routed for 11.45s and
        # hit the wall, and the sweep saw a single candidate.
        #
        # Routing is where the answer is, so packing is capped at a fraction and
        # the rest belongs to the router.  Spending longer in CP-SAT is not even
        # free of charge to routing: a longer solve returns a TIGHTER pack, and
        # tighter is harder to wire.  Same 30 height-cells, pack budget varied,
        # generous routing clock -- 0.5s wired 12 of 30, 3.0s wired 6 of 30, and
        # the widths tell the story (`max-proliferation` h=90 power=1: w=134 and
        # 2 nets unrouted at 0.5s, w=83 and 31 unrouted at 3.0s).
        per_solve = max(0.1, share * _PACK_SHARE / max(len(heights), 1))
        # This sweep's SOFT deadline, and the call's HARD one, and they are not
        # the same rule.
        soft = time.monotonic() + share

        best: Placement | None = None
        best_key: tuple[int, float] | None = None
        for height in heights:
            # The SOFT deadline stops us IMPROVING, never FINDING. A refusal
            # means the model could not lay the spec out; a sweep's own clock
            # must not be able to manufacture one. Breaking on time alone did
            # exactly that: heights are tried shortest-first and the
            # free-proliferation chain only wires at the tallest, so a 2s budget
            # refused a spec that routes every net cleanly given the chance to
            # reach it.
            if best is not None and time.monotonic() >= soft:
                break
            # The HARD deadline is the call's, and it does stop us finding --
            # that is what makes `time_budget_s` a wall rather than a suggestion.
            # `lay_out` turns it into a refusal that names the deadline, so the
            # distinction between "cannot" and "ran out" survives into the error.
            if _expired(deadline):
                break
            pack = _pack(
                strips,
                height=height,
                width_bound=max(bound * 2, 8),
                time_budget_s=per_solve,
                direct_candidates=net_candidates,
                workers=self.workers,
                seed=seeds[height],
            )
            if pack is None:
                continue
            # RATIONING THE CLOCK BETWEEN HEIGHTS WAS TRIED AND IS WORSE.
            #
            # The observation is real: a routing pass that will wire this pack
            # does it in four to eleven seconds and one that will not runs to
            # the wall, so the first candidate can spend a whole cell's ceiling
            # on a pack that was never going to work. Eighteen runs at a 15s
            # ceiling on `universe-matrix`: every refusal reads `f138@13.9s`,
            # one pass, one height, while every success reads 4.0s, 5.6s, 5.7s,
            # 10.7s, 10.8s, 10.9s.
            #
            # Capping a height at a share of what remains buys nothing, because
            # the successes are spread right across the range the cap has to cut.
            # `universe-matrix` at budget 15, three runs each: uncapped 3, 3, 3
            # of 6; at 55% of the remaining clock 2, 2, 2; at 75%, 4, 3, 2 and
            # 2, 3, 4 -- the same mean, more variance. And the corpus pays for
            # it: 68, 69, 68 against 69, 70, 70, 68, 70.
            #
            # What that says is that the spread is not the sweep's to manage.
            # Two solves of one height to the same width differ by seconds of
            # routing and by whether they converge at all, so the clock is not
            # being misallocated between heights -- it is being spent on a pack
            # CP-SAT happened to return. The lever is the packer's arrangement,
            # not the stopwatch.
            placement, failed, _towers = _build(
                spec,
                strips,
                pack,
                power=self.power,
                route=True,
                deadline=deadline,
                budget=budget,
            )
            # There is no `claim_power=False` retry here any more.
            #
            # The retry gave the WHOLE lattice claim up as soon as a pack left
            # one to three nets unrouted, on the reasoning that a build which
            # cannot be wired is worth nothing while coverage still has its
            # repair pass. The second half of that does not hold: the repair
            # pass needs free ground and a pack tight enough to strand a net has
            # none, so what came back was a wired blueprint with buildings
            # outside every tower's radius -- `power.coverage`, an INVALID, in
            # place of a refusal that would have emitted nothing. It fired on
            # `casimir-crystal/free-proliferation` and `information-matrix` at
            # 4s, intermittently, which is exactly how a pack-dependent failure
            # looks.
            #
            # A height that cannot be wired with the lattice in place is simply
            # discarded, and if no height survives the spec is REFUSED. Trading
            # coverage for the last net or two, like trading density for it, is
            # buying a green cell with something the build needed.
            if failed:
                continue
            # AND THE PLACEMENT HAS TO PASS OUR OWN VALIDATOR BEFORE IT COUNTS.
            #
            # `lay_out` promises a valid `Placement` or `NoValidLayout`, and
            # until now freeform ARGUED that promise while `spine` enforced it
            # -- `spine._rejected` has called `validate.certify` all along and
            # this did not. The gap is not theoretical: `quantum-chip`
            # /free-proliferation power=1 emits, roughly one build in sixteen, a
            # placement whose titanium-glass production is cut into islands, so
            # eleven machines can reach 16/7 items/s of an item they consume
            # 11/4 of. It pastes and then does not run, which is the one failure
            # nobody discovers until they are standing in front of it in game.
            #
            # A rejected candidate is DISCARDED, not repaired and not returned
            # with a warning, and the sweep goes on to the next height. That is
            # the same trade `_build`'s `failed` already makes and it goes the
            # same way: several separately solved and separately validated packs
            # is a search, and refusing outright is honest, while an invalid
            # blueprint is the worst outcome this program has.
            #
            # It costs a validation per ROUTED candidate, which is a handful per
            # sweep -- most heights never get here because their pack does not
            # wire -- against a CP-SAT solve and a full routing pass each.
            report = validate.certify(placement, spec, expect_power=self.power)
            if report.errors:
                if rejected is not None:
                    rejected.update(f.check for f in report.errors)
                continue
            # Area, then belt count. Two packs of equal area are not equally
            # good: the one with fewer belt tiles is fewer buildings to paste,
            # and a direct insert shows up here as exactly that. Without the
            # second key, ties fell to whichever height the sweep tried first,
            # which silently discarded direct-inserted packs.
            key = (placement.area, float(placement.stats["belt_tiles"]))
            if best_key is None or key < best_key:
                placement.stats["solver_status"] = 1.0 if pack.status == "OPTIMAL" else 0.5
                placement.stats["hit_time_budget"] = float(pack.hit_budget)
                placement.stats["fallback_used"] = 0.0
                placement.stats["direct_insert_candidates"] = float(len(candidates))
                placement.stats["area"] = float(placement.area)
                best, best_key = placement, key
        return best


def _height_seed(strips: list[Strip]) -> int:
    area = sum(w * h for w, h in map(_box, strips))
    tall = max((h for _w, h in map(_box, strips)), default=1)
    return max(tall, int(math.isqrt(max(1, area))))


def _candidate_heights(strips: list[Strip]) -> list[int]:
    """Heights to sweep, since ``W * H`` is too weak a form to minimise directly."""
    h0 = _height_seed(strips)
    tall = max((h for _w, h in map(_box, strips)), default=1)
    out = {max(tall, int(h0 * f)) for f in (0.6, 0.8, 1.0, 1.25, 1.6)}
    return sorted(out)
