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
box or under-covers the result.

Towers are therefore placed between packing and routing, by :func:`_power_plan`,
which covers by NEED rather than by grid: every powered tile must have a free
cell within the tower radius, that condition is checked exactly, and a pack that
fails it is refused as infeasible before a belt is laid.  A pack that passes gets
a placement built greedily against the same condition, connected as it grows, and
held in ``keep_out`` so the router paths around it.

This replaced a lattice with a coverage repair behind it, and the repair is the
part that mattered: it ran AFTER routing, so it searched ground the packing and
the router had already spent, and when it found none it returned quietly and the
candidate died on `power.coverage` having paid for a full routing pass first.
The guarantee is now genuinely structural rather than post-hoc -- and covering by
need measured 2-4x fewer towers than the grid it replaced, which is density
rather than tidiness.
"""

from __future__ import annotations

import heapq
import math
import time
from collections import defaultdict
from collections.abc import Callable, Collection, Mapping, Sequence, Set
from copy import deepcopy
from dataclasses import dataclass, field, replace
from enum import Enum
from fractions import Fraction

import numpy as np
from ortools.sat.python import cp_model

from flab2bp.dsp import catalog, codec, colliders, params, rules
from flab2bp.layout import junction, slots, validate
from flab2bp.layout.base import (
    DEFAULT_SEARCH_WORKERS,
    RETRY_BUDGET_S,
    Facing,
    NoValidLayout,
    PlacedBuilding,
    Placement,
)
from flab2bp.layout.route_feedback import (
    Cell,
    DetailedRouteResult,
    DetailedRouteStatus,
    NetFailure,
    NetId,
    NetRole,
    RouteFailureKind,
)
from flab2bp.layout.slots import SlotUndetermined, assign_sorter_slots
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
#: set and A* reports dynamic access loss having expanded nothing.  That is not
#: congestion and no amount of rip-up can price it away, which is why more solver
#: time made this WORSE: a tighter pack is a pack with more faces pressed
#: together.
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

#: Height of one routing level, in blueprint world units.  Derived rather than
#: written as ``1`` so it stays tied to the two measured constants it is made
#: of: a belt climbs ``BELT_CLIMB_PER_TILE`` per tile and a ramp spends
#: ``RAMP_TILES_PER_LEVEL`` tiles to gain one.
_LEVEL_HEIGHT = catalog.BELT_CLIMB_PER_TILE * catalog.RAMP_TILES_PER_LEVEL

#: Levels this router's lattice offers: ground plus three.
#:
#: NOT the game's ceiling, which is ``catalog.belt_max_z`` -- 8.55 on a new save
#: and 26.55 at the corpus's lab level 9.  This is how much of it THIS router
#: can use.
#:
#: It was 1 + crossing clearance = 2 while the ceiling was believed to be 1.
#: Measured at 2 the freeform suite failed 12, then 2, then 5 tests on
#: different runs -- `magnetic-ring` wiring stochastically because one crossing
#: plane leaves no slack.  At 3 the same suite is 0.  The game's slope rule
#: says a ramp to z=2 is legal on any save (world slope 2/3 against a limit of
#: 4/5), so the third level costs nothing in legality.
#:
#: **THE FOURTH LEVEL IS THE ONE THAT LETS A BELT CROSS A MACHINE**, and it is
#: worth nothing without :func:`_crossing_ban_levels`.  This comment used to
#: justify the value with "it treats machines as solid at every altitude, so
#: headroom beyond a crossing plus one buys it nothing" -- circular, and the
#: constraint under it was invented.  With the real rule in place the shortest
#: collider in the packable set is a Mining Machine's at 2.610 and the tallest
#: that still fits under level 3 is a Self-evolution Lab's at 2.947, so level 3
#: is the FIRST altitude at which any production machine may be crossed at all.
#:
#: Measured on the 72-cell corpus audit, paired and interleaved, four arms
#: rotated so none always ran first -- 14 rounds, then 8 more with two extra
#: arms, `--budget 4 --jobs 16`:
#:
#: * The null arm is the calibration.  The band rule at ``LEVELS = 3`` is
#:   PROVABLY the same geometry as the blanket ban (nothing packable clears
#:   level 2) and it still "won" 45 discordant cells to 42, share 0.517,
#:   p = 0.83, and still measured 0.63% denser cell-for-cell.  Read every
#:   number below against that: a 0.6% density delta here is what nothing looks
#:   like.
#: * ``LEVELS = 4`` with the rule: clean 62.36/72 against 61.43 over 14 rounds,
#:   better in 9 rounds and worse in 2 (p = 0.065); pooled over both runs, 46
#:   discordant cells to 29, share 0.613, p = 0.064.  Two independent runs, the
#:   same direction, the same size.
#: * ``LEVELS = 4`` WITHOUT the rule -- more altitude that machines still
#:   block -- is worse than shipped master: -1.12 clean cells, and it loses to
#:   the rule 21 discordant cells to 8.  So the gain is the crossing, not the
#:   lattice.
#: * ``LEVELS = 5`` gives back the gain: 61.50 clean, share 0.519 against
#:   master.  The search cost of the fifth plane exceeds what an Assembling
#:   Machine crossing (3.532, so level 4) returns.
#: * **Density did not move.** -0.91% cell-for-cell against master, versus the
#:   null arm's -0.63% and a same-arm noise floor of 1.33% median / 3.59% p90
#:   over 273 same-arm pairs.  What the fourth level buys is REFUSALS, not area.
#: * INVALID stayed 0 in all 62 rounds -- 4,464 cells -- and the crossings are
#:   real: 254 belt tiles stand over a machine's footprint across 30 placements
#:   at ``LEVELS = 4``, against 0 at ``LEVELS = 3``.
LEVELS = 4


def _crossing_ban_levels(b: PlacedBuilding) -> tuple[int, ...]:
    r"""Routing levels no belt may stand on over ``b``. **The game's rule.**

    A machine is NOT solid at every altitude.  Nothing in the game says so.
    The belt-versus-building test on a blueprint paste is one sphere against
    the building's build collider and nothing else --
    ``BuildTool_BlueprintPaste.cs`` line 2179 in the decompiled assembly (dump
    line 145760; the per-file offset for this type is +143581, established
    against the three citations this repo already carries into it)::

        int num17 = ((!buildPreview2.desc.isBelt)
            ? Physics.OverlapBoxNonAlloc(colliderData.pos, colliderData.ext,
                  BuildTool._tmp_cols, colliderData.q, mask, ...)
            : Physics.OverlapSphereNonAlloc(
                  buildPreview2.lpos + buildPreview2.lpos.normalized * 0.2f,
                  0.23f, BuildTool._tmp_cols, 395264, ...));

    There is no footprint term, no tile test, and no altitude ceiling: a belt
    whose 0.23-radius probe misses the collider is ``Ok`` however far inside the
    machine's FOOTPRINT it sits.  Colliders start at the ground and rise
    (:func:`colliders.belt_keepout_offsets` searches negative ``dz`` and comes
    back empty for every model in the catalog), so "misses the collider" is
    purely a question of height, and
    :func:`flab2bp.dsp.colliders.belt_crossing_height` solves it in closed form
    against the collider's own top.  ``spine`` has priced crossings this way in
    ``_belt_floor_over`` all along; this is freeform being brought level with
    it.

    **What the rule depends on**, since a KEEP row owes that and not only a
    number: the crossed building's ``model_index``, through its build collider.
    It is a lookup, never a constant -- 0.758 over a Sorter, 1.747 over a
    Splitter, 2.797 over an Arc Smelter, 3.532 over an Assembling Machine of
    any of the three tiers, 4.973 over a Chemical Plant, 7.785 over an Oil
    Refinery.  Tiers within a family often share a collider (Mk.I/II/III
    assemblers all read 3.532) and often do not (Depot Mk.I 1.897, Mk.II
    2.835), so a single constant here would be right by coincidence.  The
    building's own ``z`` is added because the bound is measured from ITS
    ground.  Whether the answer is REACHABLE is a second, save-dependent
    question that :class:`catalog.BeltAltitudeRules` owns -- ``max_z`` from lab
    level and ``vertical_construction`` from Super Magnetic Field Generator --
    and it is FactorioLab's technology set that decides it, never this module.

    Strictly greater clears, which is why a level exactly ON the bound is
    banned.
    """
    top = colliders.belt_crossing_height(b.model_index) + b.z
    return tuple(lvl for lvl in range(LEVELS) if lvl * _LEVEL_HEIGHT <= top)

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

#: How many ARRANGEMENTS of each height the sweep may ask CP-SAT for.
#:
#: One was the whole search until this was measured.  ROUTABILITY IS A PROPERTY
#: OF ARRANGEMENT, not of how much room a pack has: over 270 packs really routed
#: across `casimir-crystal`, `information-matrix`, `quantum-chip` and
#: `universe-matrix`, 28 of 50 (spec, height) groups had CP-SAT seeds that
#: DISAGREED on whether the pack wires, and 21 of those 50 disagreed at
#: IDENTICAL WIDTH -- same height, same width, one arrangement wires and another
#: does not.  Seed 0 wired 34 of 50 height-groups; some seed of five wired 48.
#:
#: That is a real property and it is NOT a licence to spend the clock on it. See
#: :meth:`FreeformLayout._sweep`, which gates arrangements past the first on
#: having a routed pack to improve: they buy density where there is clock to
#: spare and buy nothing at all where the deadline is the binding constraint.
#:
#: Three, because that is what the density measurement supports -- -1.98% area
#: over four paired rounds at the budget where arrangements are affordable, and
#: -0.25 cells (95% CI [-1.40, +0.90]) over twelve at the budget where mostly
#: they are not -- and every further draw costs a CP-SAT solve and a routing
#: pass.  ``1`` is the search as it stood before this existed and is the control
#: the A/B compares against; see ``audit.py --arrangements``.
_ARRANGEMENTS = 3

#: CP-SAT's random seed for arrangement 0 -- the constant this always used.
_PACK_RANDOM_SEED = 20260822

#: Gap between one arrangement's seed and the next.  Any coprime-ish stride does;
#: what matters is that it is FIXED, so a re-run asks for the same arrangements.
_ARRANGEMENT_STRIDE = 7919

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

#: Hard cap on A* node expansions for a single net.  Exceeding it reports
#: budget exhaustion, which the caller treats as a route failure and handles by
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
#: A belt at z=0 leaves z=1 and z=2 open above it -- only a machine denies all
#: three, and only because its collider outreaches this lattice
#: (:func:`_crossing_ban_levels`) -- but a plain step costs 1 and a ramp 3, so A* has
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

#: The ramps a cell at each altitude may take: ``(level step, toll of the level
#: it lands on)``.  The bottom and top levels have one apiece and every level
#: between them has two, so the inner loop iterates exactly the legal moves
#: instead of testing two candidates and discarding one -- 10M discarded
#: comparisons in a `universe-matrix` routing pass.
_RAMPS = tuple(
    tuple(
        (step, _LEVEL_TOLL[lvl + step])
        for step in (1, -1)
        if 0 <= lvl + step < LEVELS
    )
    for lvl in range(LEVELS)
)

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

# AND THERE IS NO TOWER LATTICE HERE EITHER, FOR THE SAME REASON.
#
# Power used to be a square lattice of spacing 9, each point dragged to the
# nearest free cell within four, with a coverage repair after routing for every
# tile the result left dark. The spacing was justified exactly: 9/sqrt(2) = 6.36
# to the worst-placed tile, plus 4 of displacement, is 10.36 against a 10.5
# radius. The repair was not justified at all, and it is the half that decided
# whether a build shipped.
#
# A dark tile is repairable only if some cell of its 346-cell radius is still
# free, and by the time the repair runs the packing and the router have both had
# the ground. When they have taken all of it the repair searches, finds nothing,
# and returns quietly -- so the placement fails `power.coverage` and the whole
# candidate is discarded, having paid for a pack AND a full routing pass first.
# Measured on `information-matrix`: a matrix lab with 349 tiles inside tower
# range had FOUR of them free.
#
# A solution that cannot be powered is not feasible. So `_power_plan` decides
# coverage BEFORE anything routes, refuses the pack outright when no placement
# exists, and covers by need rather than by grid -- which is also 2-4x fewer
# towers, because a lattice point every nine tiles ignores that a tower reaches
# 10.5 in every direction.


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
    #: Grid extents AS BUILT -- already swapped when ``yaw`` is a quarter turn,
    #: so nothing downstream has to remember to swap them.
    width: int
    height: int
    #: Which way this machine is turned, chosen from its own insert poses by
    #: `slots.lane_orientation`. A building with no pose facing the lane cannot
    #: be wired at all however it is packed.
    yaw: float
    #: Tiles to reserve per machine, from the rotated collider.
    pitch_w: int
    pitch_h: int
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
    #: The machines' yaw, carried from the group so the emitted record and the
    #: extents above cannot disagree about which way they are turned.
    yaw: float
    #: Tiles to RESERVE per machine, from the rotated collider -- see
    #: `catalog.clearance`. An Assembling Machine covers `mw` = 3 and needs 4:
    #: its 3.82-unit collider does not fit a 3-tile pitch at 1.2566 units per
    #: tile. Spacing and the pack use these; anchors and slots use `mw`/`mh`.
    pw: int
    ph: int
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
    #: Does the product leave by the machines' EAST face instead of their south?
    #:
    #: A machine slot holds one connection and a face offers three, so a lane-fed
    #: strip has a hard ceiling of six: three columns north, three south.
    #: ``universe-matrix`` is six ingredients and a product, and seven does not
    #: fit -- the only recipe in the dataset where the true bound binds.
    #:
    #: The east face is the way out, and the OUTPUT is what goes there, because
    #: an output MERGES and an input would have to split.  Each machine drops its
    #: product east into a one-tile belt in the gap beside it; those gap belts run
    #: south and join the output row under the band, which is where it always was.
    #: Several belts feeding one is a thing a belt does; one belt feeding several
    #: is a splitter, and the no-splitter invariant is what buys the whole
    #: lane-per-destination design.
    #:
    #: The gap is bought, not found: ``pw`` is the machine's clearance PLUS ONE
    #: when this is set, and the extra column is the belt's.  Clearance is what
    #: the collider needs, so a belt inside it would paste as a collision.
    flank_outputs: bool = False

    @property
    def in_lanes(self) -> tuple[str, ...]:
        """Every ingredient, regardless of which side or lane feeds it."""
        return tuple(item for lane in self.in_above + self.in_below for item in lane)

    @property
    def width(self) -> int:
        return self.machines * self.pw

    @property
    def height(self) -> int:
        return len(self.in_above) + self.ph + len(self.out_lanes) + len(self.in_below)

    @property
    def band_rows(self) -> int:
        """Rows the machine band RESERVES -- clearance, not footprint.

        THE strip row map lives on these two members and nothing else may
        compute a row from `mh`. `mh` is how tall the machines are; `ph` is how
        much room their colliders need, and lanes have to start after the second
        or a junction on them is illegal against the machine beside it.

        The two were the same number until spacing landed, so every consumer
        that wanted "the first row after the band" wrote `mh` and was right by
        accident. There were SEVEN of them -- `row_of_output`, `row_of_input`'s
        `in_below` branch, the band skip in emission, the probe lane in
        `_attachable_columns`, `height`, and the two SPAN expressions that size
        sorters from the machine's bottom edge -- and moving a subset is what
        took this module from 9 failing tests to 80, twice. They move together
        or not at all, which is what this exists to make possible.

        THE TWO SPAN CONSUMERS HAVE SINCE LEFT, and that is a correction rather
        than a subset move: a span is not a row-map question at all. It is the
        distance from a lane to the machine's insert POSE, and `sorter_span`
        reads that from the slot table, because a Chemical Plant's northern
        anchor is a row inside its footprint and no arithmetic on `mh` or `ph`
        can know it. Five consumers ask here now, and they still move together.
        """
        return self.ph

    @property
    def first_row_below_band(self) -> int:
        """Row index of the first lane under the machine band."""
        return self.machine_row + self.band_rows

    def sorter_span(self, row: int) -> int:
        """Tiles a sorter crosses between lane ``row`` and the machine it serves.

        Chebyshev, matching ``validate._sorter_span``, and read from the
        machine's OWN insert poses rather than from the edge of its footprint.

        THIS REPLACES ``rows_below_machines``, WHICH COUNTED FROM THE FOOTPRINT
        EDGE, and which was right only for a machine whose poses sit on that
        edge.  A Chemical Plant's NORTHERN anchor is a row INSIDE its 9x5
        footprint, so a lane one row clear of it is TWO tiles from the anchor,
        not one -- the same correction ``_find_taps`` took in 954bea2, arriving
        one layer later in the same module.

        The span sizes the sorter tier, so understating it by one picks a Mk.II
        where a Mk.III is needed: ``_pick_sorter(2/s, span=1)`` returns a Mk.II
        and a Mk.II sustains 3/2 across the two tiles it actually crosses.  That
        is a starvation with nothing to see at paste time, and it is what
        ``flow.sorter_capacity`` reported on every refiner of
        ``two-product-producer``.

        The WORST column is taken, never the one ``_link_lane`` happens to pick.
        Over-stating a span costs one sorter tier; under-stating it starves a
        machine.

        Zero means no pose is reachable from that row at all.  That is a
        different failure and belongs to ``_machines_without_poses``.
        """
        lane_y = row - self.machine_row
        probe = slots.probe_building(self.item_id, self.yaw)
        reach = slots.attachable_columns(probe, lane_y)
        if not reach:
            return 0
        return max(abs(lane_y - a.cell[1]) for a in reach.values())

    @property
    def machine_row(self) -> int:
        """Row index of the machine band's top edge, relative to the strip."""
        return len(self.in_above)

    @property
    def takes_belt_ports(self) -> bool:
        """Is this strip's machine wired by a belt docked into a port?

        True only when the prefab offers ports and NO insert pose, which is the
        whole of the belt-port class -- Ray Receiver, Energy Exchanger,
        Fractionator, the mining machines, the water pump, the oil extractor,
        the logistic stations.  A machine with both would be a machine a sorter
        can reach, and the sorter path is the denser one; the catalog has none,
        and this asks rather than assuming.
        """
        info = catalog.building(self.item_id)
        return info.takes_belt_ports and not info.slot_poses

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
                return self.first_row_below_band + len(self.out_lanes) + j
        raise KeyError(f"{item!r} is not an ingredient of {self.recipe_id!r}")

    def row_of_output(self, k: int) -> int:
        """Row index of the ``k``-th output lane, relative to the strip's top.

        Counted from the machine FOOTPRINT, not the clearance band. Moving it to
        `ph` was tried, to keep a lane out of the row a machine's collider needs
        so that a junction on it would be legal -- it took freeform from 9
        failures to 80, because the strip's row indices are consumed in several
        places that each assume lanes start at `mh`. The junction constraint is
        real; solving it by moving lane rows is not the way in.
        """
        return self.first_row_below_band + k

    def column_offset(self, lane: tuple[str, ...]) -> int:
        """The first machine column this input lane may use.

        A MACHINE SLOT HOLDS ONE CONNECTION.  The game stores connections as
        ``entityConnPool[objId * 16 + slot]`` and ``WriteObjectConn`` evicts the
        sitting tenant rather than refusing, so two sorters on one slot paste
        with one of them unwired and both standing on the same tile --
        ``validate.game.slot_occupancy``.

        Columns therefore have to be rationed across every lane on the same
        FACE, not just across the items sharing one lane.  Each lane consumes
        one column per item it carries, and this returns how many the lanes
        before it have already taken.  North is ``in_above`` in order; south is
        the output lanes -- one column each -- and then ``in_below``.

        Before this existed, every lane started at column 0 and the surplus was
        clamped onto the last reachable column.  Measured on a pristine tree at
        budget 4, that put two or more sorters on one slot in 54 of 60 freeform
        corpus cells (1412 shared slots), and all 60 validated CLEAN.
        """
        seen = 0
        for other in self.in_above:
            if other is lane or other == lane:
                return seen
            seen += len(other)
        # A flanked output takes no south column at all -- its sorters leave by
        # the east face -- so the ingredients below start at zero.  Charging them
        # for it would ration away the very column the flank exists to free.
        seen = 0 if self.flank_outputs else len(self.out_lanes)
        for other in self.in_below:
            if other is lane or other == lane:
                return seen
            seen += len(other)
        raise KeyError(f"{lane!r} is not an input lane of {self.recipe_id!r}")

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

        The columns come from the machine's own insert poses, not from
        ``min(slot, mw - 1)``.  A seven-wide Oil Refinery offers only its middle
        three and a nine-wide Chemical Plant four of nine, so a lane trimmed to
        the left edge stopped short of every column that could be wired and the
        last machine got no sorter at all.

        ZERO IS A REAL ANSWER AND ITS CALLER MUST HAVE REFUSED ALREADY.  A
        machine whose prefab ships no insert pose at all -- a Ray Receiver, an
        Energy Exchanger -- offers no column on either side, so a lane serving it
        needs no belt tiles because no sorter could ever draw from one.
        ``_machines_without_poses`` refuses such a spec before the sweep starts;
        emission may not be reached with one, because a zero-tile lane is an
        empty ``lane_idx`` row and ``feed`` indexes its head.

        The lane's own items are not the whole story: it starts at
        :meth:`column_offset`, because the lanes before it on the same face have
        already claimed columns and a slot takes one connection.  A lane trimmed
        as if it began at column 0 stops short of the column it is actually
        given, and the machine goes unfed -- which is how the first version of
        the slot rationing turned six ``magnetic-coil`` cells from invalid into
        refused rather than into correct.
        """
        cols = self.attachable_columns
        if not cols:
            return 0
        first = self.column_offset(lane)
        last_slot = cols[min(first + len(lane) - 1, len(cols) - 1)]
        return (self.machines - 1) * self.pw + last_slot + 1

    def _attachable_columns(self, *, above: bool) -> tuple[int, ...]:
        """Columns of ONE of this strip's machines a sorter can reach, from 0."""
        probe = slots.probe_building(self.item_id, self.yaw)
        lane_y = -1 if above else self.band_rows
        return tuple(sorted(slots.attachable_columns(probe, lane_y)))

    @property
    def attachable_columns(self) -> tuple[int, ...]:
        """Columns of one of this strip's machines ANY sorter could reach.

        The two sides are UNIONED rather than asked for separately.  Every
        building we place offers the same columns above and below, so the union
        is the same answer; where it would not be, it is the longer one, and a
        tile of dead belt is a warning where a missing tile is an unfed machine.

        EMPTY MEANS NO SORTER CAN TOUCH THIS MACHINE ANYWHERE, which is a
        different thing from a narrow choice and is what
        ``_machines_without_poses`` refuses on.
        """
        return tuple(
            sorted(
                set(self._attachable_columns(above=True))
                | set(self._attachable_columns(above=False))
            )
        )

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
        yaw = slots.lane_orientation(item_id)
        gw, gh = catalog.oriented_footprint(item_id, yaw)
        pw, ph = catalog.clearance(item_id, yaw)
        groups[f"{mg.recipe_id}#{i}"] = _Group(
            key=f"{mg.recipe_id}#{i}",
            recipe_id=mg.recipe_id,
            item_id=item_id,
            model_index=b.model_index,
            count=mg.count,
            width=gw,
            height=gh,
            yaw=yaw,
            pitch_w=pw,
            pitch_h=ph,
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


def _side_lane_caps(item_id: int, yaw: float, band_rows: int) -> tuple[int, int]:
    """Lane rows above and below the machine band a sorter can actually reach.

    THIS IS THE SEATING HALF OF THE CORRECTION ``sorter_span`` TOOK IN 5e982bb.
    Both sides were assumed to carry ``SORTER_MAX_REACH`` lanes, counted from the
    machine's FOOTPRINT EDGE, and that is right only for a machine whose insert
    poses sit on that edge with no clearance padding under it.  Two families in
    the catalog break it, in opposite directions:

    * a **Chemical Plant** (and its quantum variant) anchors its north face on
      the row INSIDE its top edge, so the outermost of three lanes above is FOUR
      tiles from anything a sorter can hold: two rows above, three below;
    * an **Assembling Machine** (and the Re-composing Assembler) covers three
      rows and RESERVES four -- its 3.82-unit collider does not fit a 3-tile
      pitch -- and ``_emit_strip`` seats the machines at the top of that band, so
      the padding lands on the south side: three rows above, two below.

    Seating a lane outside that is not a near miss.  ``slots.attachment``
    returns ``None`` for it, ``_link_lane`` places no sorter at all, and the
    machine ships joined to nothing on that lane -- which is what
    ``_machines_without_poses`` refuses on and why the ``organic-crystal`` URL
    refused on every candidate.  Tightening the seat is the fix; widening the
    reach would emit a sorter the game rejects on paste.

    A row is counted only while every row nearer the machine is reachable too,
    so the answer is a contiguous run outward from the band.  It cannot have a
    hole in practice -- span grows monotonically as a lane moves away from the
    one pose row a face offers -- and a prefix is the conservative reading if it
    ever did.

    A BUILDING WITH NO POSES AT ALL GETS THE OLD CONSTANT BACK, deliberately.  A
    Ray Receiver and an Energy Exchanger ship a zero-length ``slotPoses``, so
    every row would score 0 and seating would raise ``cannot be seated`` -- a
    worse message than ``_machines_without_poses``' own, which names the prefab
    and says the game gives it no pose on any face.  That refusal stays the
    owner of this case.
    """
    if not catalog.building(item_id).slot_poses:
        return catalog.SORTER_MAX_REACH, catalog.SORTER_MAX_REACH
    probe = slots.probe_building(item_id, yaw)
    caps: list[int] = []
    for lane_ys in (
        [-(k + 1) for k in range(catalog.SORTER_MAX_REACH)],
        [band_rows + k for k in range(catalog.SORTER_MAX_REACH)],
    ):
        n = 0
        for lane_y in lane_ys:
            if not slots.attachable_columns(probe, lane_y):
                break
            n += 1
        caps.append(n)
    return caps[0], caps[1]


def _flank_seat(item_id: int, yaw: float, gap: int) -> slots.Attachment | None:
    """Where a machine's product leaves eastward, for a belt in column ``gap``.

    ``gap`` is measured from the machine's own west edge and is its CLEARANCE
    width, so the belt stands one column clear of everything the collider needs.
    Putting it inside the clearance would paste as a collision on the belt, which
    is the same rule that makes an Assembling Machine reserve four columns for a
    three-column footprint.

    The row nearest the machine's south edge wins: the gap belt runs from that
    row down to the output lane under the band, and every row above it is another
    belt tile to lay and another cell the router has to path around.

    ``None`` means this building offers no pose on its east face a sorter of that
    span could name.  There is no nearest-legal answer -- refusing to flank is the
    caller's only honest move, and the six-slot ceiling stands.
    """
    probe = slots.probe_building(item_id, yaw)
    rows = slots.attachable_rows(probe, gap)
    if not rows:
        return None
    return rows[max(rows)]


def _seat_inputs(
    items: tuple[str, ...],
    n_sinks: int,
    above_cap: int,
    below_cap: int,
    max_per_lane: int,
    columns: int,
    *,
    flank_outputs: bool = False,
) -> tuple[tuple[tuple[str, ...], ...], tuple[tuple[str, ...], ...]]:
    """Seat ingredients into lanes above and below the machine band.

    Tries one item per lane FIRST and only mixes when that will not fit, which
    is what makes this additive: every spec that already worked seats exactly as
    it did before, so mixing opens new territory rather than trading anything.

    Mixing is capped at ``max_per_lane`` -- the machine's width -- because two
    sorters serving one machine from one lane cannot share an anchor, so each
    item on a shared lane needs its own column across that width.

    ``above_cap`` and ``below_cap`` are THIS MACHINE's rows per side, from
    :func:`_side_lane_caps`, and they are not both ``SORTER_MAX_REACH``: a
    Chemical Plant carries two lanes above and an Assembling Machine two below.

    ``columns`` is how many insert poses one FACE of this machine offers a lane,
    and it bounds the side differently from the row caps: a row cap counts
    LANES, this counts SORTERS.  Every item on a side needs its own column,
    because a machine slot holds exactly one connection -- see
    :data:`~flab2bp.dsp.rules.CONN_SLOTS_PER_OBJECT` and
    ``validate.game.slot_occupancy``.  Mixing two items onto one lane saves a
    row and saves no column at all, so without this bound "mix harder" walks
    straight past the real limit.

    It was missing, and what it cost was not hypothetical.  ``universe-matrix``
    takes six ingredients and produces one, and a Matrix Lab offers three
    columns above and three below: seven sorters into six slots.  The old
    seating accepted it, and the emitted blueprint put THREE sorters on slot 6
    and three more on slot 7 of every Matrix Lab -- measured, 4 shared slots per
    build -- which pastes with four of the six unwired.  A refusal here is the
    honest answer, and it is raised where the arithmetic is visible rather than
    left to surface downstream as an unfed machine.

    ``flank_outputs`` says the product leaves by the machines' EAST face, so the
    output lane costs a ROW below the band and no COLUMN on it.  That is the one
    degree of freedom that seats seven connections on a building that offers six
    per pair of faces, and it is why ``universe-matrix`` seats at all: three
    ingredients mixed onto one lane above, three onto one below, and the product
    out east.  It changes only the column arithmetic here -- the rows, the reach
    caps and the mixing ladder are the same for both.

    Returns ``(above, below)``.  ``below`` shares the south side with the output
    lanes, so it is kept as small as possible.
    """
    # The output lane still needs its ROW under the band even when flanked -- the
    # gap belts drain into it -- so only the column charge goes away.
    out_columns = 0 if flank_outputs else (1 if n_sinks else 0)
    n = len(items)
    if n == 0:
        return (), ()
    for k in range(1, max(1, max_per_lane) + 1):
        lanes = [tuple(items[i : i + k]) for i in range(0, n, k)]
        # The split point is searched rather than fixed at `above_cap`.  Filling
        # the north side first was harmless while only ROWS were rationed --
        # a full north side left the whole south side for the rest.  With
        # columns rationed too it is not: four ingredients mixed two-to-a-lane
        # give two lanes, both of which fit above by row count and neither of
        # which fits by column count, and a fixed split would have refused a
        # spec that seats perfectly well one lane per side.  Largest `above`
        # first, so `below` stays as small as it can and leaves the output lane
        # its room.
        for a in range(min(len(lanes), above_cap), -1, -1):
            above, below = tuple(lanes[:a]), tuple(lanes[a:])
            if len(below) > below_cap:
                continue  # more lanes than that side can hold; mix harder
            if n_sinks and below_cap - len(below) <= 0:
                continue  # no room left below for an output lane
            if sum(len(lane) for lane in above) > columns:
                continue  # more sorters than the north face has slots
            if sum(len(lane) for lane in below) + out_columns > columns:
                continue  # ... or than the south face has, output lane included
            return above, below
    flanked = " with the product leaving east" if flank_outputs else ""
    raise ValueError(
        f"{n} ingredients cannot be seated{flanked}: {above_cap} lane(s) above "
        f"and {below_cap} below carrying at most {max_per_lane} items each, over "
        f"a face that offers {columns} insert pose(s) per side, leaves no room "
        f"for {n} ingredient sorter(s) and the output lane. A machine slot holds "
        f"one connection, so two sorters cannot share a column"
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

    strips: list[Strip] = []
    for key, g in groups.items():
        # How many lane rows THIS machine's poses actually reach, per side. Not
        # `SORTER_MAX_REACH` on both: a Chemical Plant's north anchor is a row
        # inside its footprint and an Assembling Machine's clearance pads its
        # south, so one carries two lanes above and the other two below.
        above_cap, below_cap = _side_lane_caps(g.item_id, g.yaw, g.pitch_h)
        in_items = tuple(sorted(g.inputs))

        sinks: list[tuple[str, str]] = []
        for item in sorted(g.outputs):
            dests = consumers.get((key, item), [])
            sinks.extend((item, d) for d in dests)
            if item in spec.outputs or not dests:
                sinks.append((item, ""))  # leaves the build

        columns = (
            len(slots.attachable_columns(slots.probe_building(g.item_id, g.yaw), -1))
            or 1
        )
        # THE EAST FACE IS THE SECOND ATTEMPT, NEVER THE FIRST.  Flanking buys a
        # seventh connection and costs a belt column per machine, so a recipe that
        # seats on the north and south faces alone must keep seating exactly as it
        # did -- otherwise every strip in the corpus pays for a slot only
        # `universe-matrix` needs.
        flank = False
        try:
            in_above, in_below = _seat_inputs(
                in_items,
                len(sinks),
                above_cap,
                below_cap,
                max_per_lane=g.width,
                columns=columns,
            )
        except ValueError as exc:
            # One sink, because one gap belt beside a machine carries one item.
            # A producer feeding several destinations would need a gap column
            # each, and the second one is not free the way the first is.
            seat = _flank_seat(g.item_id, g.yaw, g.pitch_w) if len(sinks) == 1 else None
            if seat is None:
                raise ValueError(f"recipe {g.recipe_id!r}: {exc}") from None
            try:
                in_above, in_below = _seat_inputs(
                    in_items,
                    len(sinks),
                    above_cap,
                    below_cap,
                    max_per_lane=g.width,
                    columns=columns,
                    flank_outputs=True,
                )
            except ValueError as flanked:
                raise ValueError(f"recipe {g.recipe_id!r}: {flanked}") from None
            flank = True

        # Output lanes share the south side with any overflow inputs, so the
        # shard size is what is left after those are seated.
        # Output lanes take columns on the south face too, so they are bounded
        # by what the inputs seated there left as well as by the row cap.
        #
        # A machine with NO insert pose at all is left alone here: zero columns
        # would bound this to zero and raise "no room on the south side", which
        # is true but useless -- `_machines_without_poses` already refuses such
        # a spec by name, and preempting it replaced a diagnosis with an
        # arithmetic complaint.
        south_columns = len(
            slots.attachable_columns(slots.probe_building(g.item_id, g.yaw), g.pitch_h)
        )
        out_cap = below_cap - len(in_below)
        if flank:
            # A flanked output takes no south column, so `south_columns` does not
            # bound it -- but one gap belt carries one item, so one lane is the
            # whole allowance.
            out_cap = min(out_cap, 1)
        elif south_columns:
            out_cap = min(
                out_cap, south_columns - sum(len(lane) for lane in in_below)
            )
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
                        yaw=g.yaw,
                        # The gap belt's column is bought here, once: clearance
                        # plus one, so the belt stands clear of the collider that
                        # made the clearance necessary.
                        pw=g.pitch_w + 1 if flank else g.pitch_w,
                        ph=g.pitch_h,
                        in_above=in_above,
                        in_below=in_below,
                        out_lanes=tuple(shard),
                        mode_params=g.mode_params,
                        flank_outputs=flank,
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
    and deleted twice -- see the note above ``_ENTRY_RING``.
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
    arrangement: int = 0,
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

    ``arrangement`` asks for a DIFFERENT optimum of the SAME model.  Nothing
    about the model changes -- not the objective, not a cut, not the warm start
    -- only which of many equally wide packings CP-SAT walks to.  ``0`` is the
    constant this always used, so a caller that does not ask gets exactly the
    solve it used to get.  See :meth:`FreeformLayout._sweep` for why a second
    arrangement is worth a solve.
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
    #
    # AND NO CHEAP ESTIMATE OF "WHICH CELLS ARE FREE" PREDICTS IT EITHER. That
    # was the open question the note above left, so it has now been measured
    # rather than argued, because a cheap predictor is the hinge on which a whole
    # class of redesign turns: replace CP-SAT with a sequence-pair search under
    # annealing, score each arrangement with a fast global router instead of the
    # real one, and search thousands of arrangements instead of five. All of that
    # rests on the surrogate agreeing with `_route_all`.
    #
    # Four estimates were computed on the REAL canvas at the moment before
    # routing -- 270 packs, really routed, on `casimir-crystal`,
    # `information-matrix`, `quantum-chip` and `universe-matrix`, 55 of which
    # failed -- and scored by AUC against what the router then did. AUC 0.5 is a
    # coin flip. Pooled WITHIN (spec, candidate), which is the comparison that
    # matters and the one the calibration above got wrong:
    #
    #   connectivity, nets whose ports are in different components   0.500
    #   the same test on real 3D cells rather than a projection      0.500
    #   coarse capacity-based global router, total overflow          0.535
    #   the same router's worst single-edge overflow                 0.525
    #   free-column fraction                                         0.491
    #   cut-capacity slack -- THE CONTROL                            0.422
    #
    # The control is what makes the nulls trustworthy: cut slack comes out
    # ANTI-correlated, independently reproducing the finding above, so the
    # instrument could have detected a signal and there was none to detect. Hold
    # the height fixed as well, so only arrangement varies, and every one of them
    # sits between 0.495 and 0.513.
    #
    # The global router is genuinely fast -- 69ms against 13.5s of real routing
    # on `universe-matrix`, some 200x -- and a 200x-faster oracle at AUC 0.51 is
    # worth nothing. Emission alone is 0.108s there, which is the floor on ANY
    # routability evaluation since you cannot know which cells are free without
    # it, so such a search gets ~130 evaluations per 15s ceiling and not the
    # thousands annealing wants. What survives the experiment is the opposite
    # conclusion: arrangement decides routability and only the real router can
    # tell you, which is what `_ARRANGEMENTS` spends its solves on.

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
    #
    # A BACKWARD-NET PENALTY WAS BUILT HERE, MEASURED, AND TAKEN OUT -- and its
    # numbers are worth keeping, because half of it was right.
    #
    # The argument: `dx` is an ABSOLUTE value, so a net running the wrong way
    # costs exactly what the same net running the right way costs. But a net
    # leaves its producer's output lane at the EAST end and arrives at its
    # consumer's input lane at the WEST head, so a consumer placed west of its
    # producer makes the belt wrap all the way around the producer. HPWL cannot
    # see that. The term is `max(0, x_i + w_i - x_j)`, the overlap a net has to
    # double back over -- one variable and one inequality per net, since a
    # positive coefficient in a minimisation drives it to its floor unaided.
    #
    # It was tried in two positions, with `tie_break_cap` grown to cover it so
    # width stayed lexicographically above it either way: inside this tie-break
    # tier beside HPWL, and in a tier of its own between width and HPWL. Both
    # move the quantity they aim at -- backward overlap on `super-magnetic-ring`
    # h=29 fell 614 -> 205 -> 144 across off, tier and own-tier.
    #
    # AND BOTH COST CLEAN CELLS, dose-responsively, which is what says it is the
    # term and not the encoding. Corpus at `--budget 4`, against 70.88 clean of
    # 72 over eight runs: 69.00 in the tie-break tier (t = -3.49), 68.62 in its
    # own tier (t = -3.89), and 68.00 when weighted eight times harder inside the
    # tie-break tier (t = -8.21). The harder it is enforced the more it costs.
    # An arrangement multi-start does not rescue it either -- paired against the
    # same multi-start without it, still -1.25 cells.
    #
    # THE OTHER HALF IS REAL AND IS LEFT ON THE TABLE DELIBERATELY. On the 61
    # cells clean in every run of every arm it is -2.40% AREA -- denser on 32
    # cells, larger on 9, biggest wins `information-matrix/free-proliferation` at
    # -572 and -450 tiles -- and the mechanism is plain enough: a belt that does
    # not wrap around its producer does not push the bounding box out. So this is
    # a DENSITY lever that is anti-correlated with routability at a fixed clock,
    # not the routability fix it was proposed as. It belongs in a build that has
    # cells to spare, and it does not belong in the objective while the binding
    # constraint is still whether a pack wires at all.
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
    # A FUNCTION of `arrangement`, never a clock or a counter: two runs of the
    # same sweep must ask for the same arrangements in the same order, or the
    # bake-off is comparing samples rather than strategies.
    solver.parameters.random_seed = _PACK_RANDOM_SEED + _ARRANGEMENT_STRIDE * arrangement
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

    #: Whether this save is under the game's belt SLOPE limit, and so needs
    #: ramps.  The game's test is
    #: ``!history.beltVerticalConstruction && num25 > 0.8f``, so the limit
    #: applies only WITHOUT the tech; with it there is no slope limit at all
    #: and a belt may step a whole level in one tile.  Default ``False``
    #: because an absent technology set means every technology researched --
    #: see :func:`catalog.belt_rules_for_technologies`.
    ramped: bool = False

    buildings: list[PlacedBuilding] = field(default_factory=list)
    #: ``(x, y, level)`` -> building index, for cells that block routing.
    #: Lattice cell -> index of the building holding it.  The altitude is a
    #: LEVEL INDEX when the router writes it and a world altitude when a caller
    #: looks a :class:`PlacedBuilding` up by ``(x, y, b.z)`` -- the two agree
    #: because ``Fraction(0) == 0`` and the two hash alike, so a belt resting on
    #: a level is found either way.  A ramp tile at ``1/2`` is deliberately NOT
    #: a lattice cell: it reserves the level it climbs from (see
    #: :meth:`_Canvas.add`) and a world-altitude lookup for it finds nothing.
    blocked: dict[tuple[int, int, int], int] = field(default_factory=dict)

    #: World cells a belt already stands on -- ``(x, y, altitude)``, the real
    #: altitude and not a level index.  Distinct from ``blocked`` because a
    #: ramp tile is at ``1/2`` while the lattice cell it holds is an integer:
    #: two ramps crossing one tile in opposite directions hold DIFFERENT
    #: lattice cells and the same world cell, so ``blocked`` cannot see the
    #: clash and this can.  Measured on a real URL candidate, where it showed up
    #: as ``geom.belt_single_occupancy`` and cost the whole layout a refusal.
    world_taken: set[tuple[int, int, Fraction]] = field(default_factory=set)
    #: Cells a machine occupies. Ground truth for "is there a machine here",
    #: which several passes ask; NOT a routing refusal.
    #:
    #: It blocked every level and that was an invented rule -- see
    #: :func:`_crossing_ban_levels`.  What a machine actually denies is the
    #: BAND under its collider's top, and ``add`` writes exactly that band into
    #: ``blocked``, so ``free`` and the flat grid both learn it from there.
    #: A membership test on this set says a machine stands on the tile and
    #: says nothing about altitude.
    solid: set[tuple[int, int]] = field(default_factory=set)

    #: ``cell -> port (x, y)``: one way in or out, held for that port's nets.
    #:
    #: A port is a lane's end tile, so it has at most three free neighbours and
    #: often one.  Without a reservation an earlier net's path takes the last
    #: one, and every net using that port is then handed an EMPTY start or goal
    #: set: A* reports dynamic access loss having expanded zero nodes.  That is
    #: distinguishable from congestion in diagnostics but still cannot be
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
    #: Cells a junction's build collider denies to any belt not on its own run.
    #:
    #: A splitter is belt-integrated: it shares the tile of the belts it joins
    #: and `add` marks nothing, so no pass after the one that built it knows it
    #: is there.  Its collider is a 2.38-unit cross standing 2.30 units tall,
    #: which the game's belt probe catches a tile out and a level up --
    #: `junction.keepout_cells`, measured in `colliders.belt_keepout_offsets`.
    #: Held for the rest of the build, because the runs, spurs and lattices that
    #: come after routing would otherwise walk straight through it.
    guard: set[tuple[int, int, int]] = field(default_factory=set)

    #: ``(x, y)`` -> routing LEVELS no belt may stand on there.
    #:
    #: A BAND, not a floor, and the difference is the whole of it.  A belt may
    #: cross a building and the price is height --
    #: ``colliders.belt_crossing_height`` solves it per model -- but a belt at
    #: the building's OWN level is beside it, not over it, and the game's own
    #: blueprints are full of belts flanking a Spray Coater on the ground.  What
    #: is forbidden is the band between: above the addon and under its
    #: clearance.
    #:
    #: Machines never need this -- ``add`` writes their band straight into
    #: ``blocked``, from :func:`_crossing_ban_levels`, which is the same rule
    #: expressed on the cells they actually own.  A belt ADDON does need it,
    #: because it reserves no tile at all: it rides
    #: its belt, and its collider is still 1.8975 high and three tiles long.  A
    #: route crossing a Spray Coater at level 1 pastes as
    #: ``EBuildCondition.Collide`` on the crossing BELT, confirmed in game on a
    #: cut-down blueprint carrying one coater, its tower and nothing else.
    #:
    #: The addon's own raised area is deliberately absent: that cell carries the
    #: proliferator connection and a belt is REQUIRED there, one level up.
    belt_ban: dict[tuple[int, int], set[int]] = field(default_factory=dict)

    def add(self, b: PlacedBuilding, *, solid: bool = False, level: int | None = None) -> int:
        """Place ``b`` and mark the lattice cells it takes out of play.

        ``level`` is the integer ROUTING level to reserve, for callers whose
        building sits at a world altitude that is not a lattice value -- a ramp
        tile rests at ``1/2`` but occupies a lattice cell all the same, and
        keying it on ``1/2`` would leave both real cells free for the next net
        to route straight through the ramp.  Routed belts pass the level the
        search verified; everything else takes the level below.
        """
        idx = len(self.buildings)
        self.buildings.append(b)
        #: A ramp tile rests between levels, so which lattice cell it takes out
        #: of play is a choice, not a reading.  Routed belts pass the level A*
        #: actually verified; everything else -- the `replace(b, ...)` copies a
        #: tap makes of a lane belt, which inherit its altitude -- falls back to
        #: the level BELOW, the one a ramp climbs from.
        cell_z = level if level is not None else math.floor(b.z)
        #: ONE lattice cell, as it has always been.  Reserving both levels a
        #: ramp spans looked prudent and measured catastrophic: it stranded 7 of
        #: 153 joins on `magnetic-ring` and cost `titanium-crystal` +85.5% area,
        #: because doubling every ramp's footprint is a footprint the packer has
        #: to spread out to afford.  It also contradicts the corpus, where 35
        #: ramp tiles sit directly over a ground belt: a ramp does NOT reserve
        #: the ground beneath it.
        #:
        #: The collision it was guarding against is real -- with two levels an
        #: ascent through a tile holds level 0 and a descent through the same
        #: tile holds level 1, so both stand and both emit `z = 1/2` -- and
        #: `world_taken` forbids exactly that, one cell rather than one level.
        held = (cell_z,)
        if solid:
            # NOT every level.  :func:`_crossing_ban_levels` is the game's own
            # rule and it is a BAND from the ground to the collider's top, so a
            # belt with the altitude to clear that top may cross this building
            # -- which is what the game allows, what `spine` has always priced,
            # and what this router used to forbid on no authority at all.
            banned = _crossing_ban_levels(b)
            for x, y, _ in b.tiles():
                self.solid.add((x, y))
                for lvl in banned:
                    self.blocked[x, y, lvl] = idx
        else:
            for x, y, _ in b.tiles():
                for lvl in held:
                    if 0 <= lvl < LEVELS:
                        self.blocked[x, y, lvl] = idx
        if catalog.is_belt(b.item_id):
            for x, y, _ in b.tiles():
                self.world_taken.add((x, y, b.z))
        return idx

    def free_world(self, x: int, y: int, z: Fraction) -> bool:
        """Is the real cell at this altitude clear of belts?

        ``free`` asks the LATTICE, which cannot answer for a ramp: an ascent and
        a descent through one tile take different lattice cells and stand at the
        same height.
        """
        return (x, y, z) not in self.world_taken

    def free(self, cell: tuple[int, int, int]) -> bool:
        x, y, z = cell
        # `solid` is deliberately NOT consulted: a machine denies the levels
        # `add` wrote into `blocked`, and the ones above its collider are the
        # game's to sell.  `_make_grid` must agree, and does.
        if cell in self.blocked or (x, y) in self.keep_out:
            return False
        # Two independent refusals, added by two branches to the same gate and
        # kept both: `belt_ban` is the height a belt owes whatever it crosses
        # (a Spray Coater wants 1.8975), `guard` is a junction's own collider.
        # Either one alone would let the other's case through.
        if z in self.belt_ban.get((x, y), ()) or cell in self.guard:
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
    #: Blueprint z the port sits at.
    #:
    #: NOT ALWAYS ZERO, and assuming it was is a real defect this exists to fix.
    #: A Spray Coater's drop belt is one altitude LEVEL up -- its addon area is
    #: at ``(0, -1.25, 1)`` -- so a drop port lives at ``z = 1`` while every lane
    #: port lives at 0.  ``_reserve_port_access`` and ``_net_ends`` both looked
    #: for a free cell beside a port at level 0 regardless, which for a drop is
    #: the plane BELOW it, and that plane is solid lane belt.  The port reported
    #: no free neighbour, the reservation could not hold one, and A* was handed
    #: an empty start set -- a search that expands zero nodes and so registers no
    #: congestion for any amount of negotiation to price.
    z: int = 0

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
            self.z,
        )


@dataclass(frozen=True, slots=True)
class _PreparedPort:
    belt_index: int
    x: int
    y: int
    x0: int
    x1: int
    tiles: tuple[int, ...]
    machines: int


def _prepare_port(port: _Port) -> _PreparedPort:
    return _PreparedPort(
        belt_index=port.belt,
        x=port.x,
        y=port.y,
        x0=port.x0,
        x1=port.x1,
        tiles=port.tiles,
        machines=port.machines,
    )


def _bind_prepared_port(
    port: _PreparedPort, buildings: list[PlacedBuilding]
) -> _Port:
    # Validate every index against this attempt's fresh building list.  _Port
    # stores indices rather than objects, so no mutable template can leak in.
    buildings[port.belt_index]
    for tile_index in port.tiles:
        buildings[tile_index]
    return _Port(
        belt=port.belt_index,
        x=port.x,
        y=port.y,
        x0=port.x0,
        x1=port.x1,
        tiles=port.tiles,
        machines=port.machines,
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
    sprayed: Set[str] = frozenset(),
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
    #: Rows whose lane starts one tile WEST of the strip, in the reserved
    #: ``WEST_CHANNEL`` column.  See the comment at the assignment below.
    lane_starts_west: set[int] = set()
    for lane in s.in_above + s.in_below:
        row = s.row_of_input(lane[0])
        lane_item_of[row] = lane[0]
        need = s.input_lane_tiles(lane)
        # A LANE THAT CARRIES A SPRAY COATER NEEDS TWO TILES, because a one-tile
        # lane has no direction of flow at all.
        #
        # `game.addon_facing` reads the ridden belt's flow from its link graph:
        # its successor if it has one, otherwise its predecessor.  A one-tile
        # lane has no successor, so the direction is whichever way the ROUTER
        # happened to arrive -- decided long after `_place_coaters` has had to
        # commit to a yaw, and the yaw is what aims the addon's areas.  Measured
        # on `electromagnetic-matrix/max-proliferation`: every coater convicted
        # was on a single-tile lane fed from the south, flowing 0 against a yaw
        # of 90.  A second tile makes the successor the lane's own next tile, so
        # the flow is east by construction and the yaw is right by construction.
        #
        # One belt, no area: the tile is inside the strip's existing width, and
        # `min(..., width)` keeps it there.  It is dead belt in the sense
        # `input_lane_tiles` means -- no sorter draws from it -- which is the
        # price of a coater the game will accept.
        #
        # AND IT STARTS ONE TILE WEST OF THE STRIP, which is the other half and
        # the one that was missing.  A second tile fixes the SUCCESSOR; the
        # coater's PREDECESSOR is still whichever cell the router arrived from,
        # and the router is free to come down the west channel and turn east on
        # the head tile.  That is a belt turning ON THE ADDON'S OWN TILE, which
        # `game.addon_corner` convicts and `BuildTool_Addon` refuses outright --
        # measured at six of twenty coaters on the blueprint the user pasted,
        # every one of them entering (0, 1) and leaving (1, 0).
        #
        # Prepending one tile moves the turn OFF the coater: the router sinks
        # into the new head at `ox - 1`, the coater rides `ox` with a lane tile
        # on both sides, and a plain belt tile is free to turn.  The coater
        # stays at column 0, so it is still upstream of every sorter on the lane
        # -- which seating it at the second tile instead would have given up.
        # The tile is inside the strip's own reserved box: `_size` adds
        # `WEST_CHANNEL` and `_pack` offsets every strip by it, so `ox - 1` is
        # this strip's channel column and belongs to nobody else.  The drop
        # cell is unchanged, still `(ox - 1, y)` one LEVEL up.
        if need and any(it in sprayed for it in lane):
            need = min(max(need, 2), width)
            lane_starts_west.add(row)
        lane_tiles_of[row] = need
    for k, (item, _dest) in enumerate(s.out_lanes):
        lane_item_of[s.row_of_output(k)] = item
        lane_tiles_of[s.row_of_output(k)] = width

    lane_idx: dict[int, list[int]] = {}
    for row in range(s.height):
        y = oy + row
        if n_above <= row < s.first_row_below_band:
            continue  # machine band, clearance rows included
        indices = []
        start = -1 if row in lane_starts_west else 0
        for k in range(start, lane_tiles_of.get(row, width)):
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
                    x=ox + k * s.pw,
                    y=machine_y,
                    width=s.mw,
                    height=s.mh,
                    yaw=s.yaw,
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
    # Machine index -> the slot indices already spoken for on it. ONE dict for
    # the whole strip, because the two faces of a machine are served by
    # different callers -- `in_above` from the north, `out_lanes` and `in_below`
    # from the south -- and a per-caller map would let the two collide exactly
    # where a per-lane `column` used to.
    claimed: dict[int, set[int]] = {}

    def item_rate(item: str, table: Mapping[str, Fraction]) -> Fraction:
        """What ONE sorter moves: one machine's rate for this one item."""
        got = table.get(item)
        if got is not None and got > 0:
            return got
        return rates.get(item, Fraction(1))

    def feed(lane: tuple[str, ...], row: int, span: int, near_edge: int) -> int:
        """One filtered sorter per (item, machine) for this lane.

        The column each sorter asks for is the lane's own
        ``Strip.column_offset`` plus the item's position within it -- NOT the
        position alone.  A machine slot holds one connection, so the columns are
        rationed across every lane on the face, and this has to be the same
        arithmetic ``Strip.input_lane_tiles`` trimmed the lane with or the
        sorter asks for a column with no belt under it.
        """
        placed = 0
        shared = len(lane) > 1
        offset = s.column_offset(lane)
        for slot, item in enumerate(lane):
            # The port is the lane's OWN first tile, read off the canvas rather
            # than assumed to be `ox`.  A sprayed lane starts one column west,
            # and a port that named `ox` would have the router sink its net into
            # the coater's tile instead of the head -- giving that tile a second
            # input, which the game refuses an addon on outright
            # (`GetBeltInputCount(num19) < 2`, decompiled 145812).
            head = canvas.buildings[lane_idx[row][0]]
            in_ports[item] = _Port(
                lane_idx[row][0],
                head.x,
                oy + row,
                head.x,
                head.x + len(lane_idx[row]) - 1,
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
                claimed=claimed,
                filter_id=_lane_filter(item) if shared else 0,
                column=offset + slot,
            )
        return placed

    for j, lane in enumerate(s.in_above):
        sorters += feed(lane, row=j, span=s.sorter_span(j), near_edge=machine_y)

    for j, (item, dest) in enumerate(s.out_lanes):
        row = s.row_of_output(j)
        span = s.sorter_span(row)
        out_ports[item, dest] = _Port(
            lane_idx[row][-1],
            ox + width - 1,
            oy + row,
            ox,
            ox + width - 1,
            tuple(lane_idx[row]),
            s.machines,
        )
        if s.takes_belt_ports:
            # No sorter can attach to this machine at all, so the product leaves
            # by a belt docked into a PORT. Counted with the sorters because the
            # figure is "connections this strip made", which is what the caller
            # tests against the machines it asked to wire.
            sorters += _dock_lane(
                canvas,
                machines,
                lane_idx[row],
                oy + row,
                item,
                belt_id,
                belt_model,
                claimed,
            )
            continue
        if s.flank_outputs:
            sorters += _flank_lane(
                canvas,
                s,
                machines,
                lane_idx[row],
                oy + row,
                item,
                item_rate(item, out_rates),
                belt_id,
                belt_model,
                claimed,
            )
            continue
        tier, _count = _pick_sorter(item_rate(item, out_rates), span, 1)
        sorters += _link_lane(
            canvas,
            lane_idx[row],
            machines,
            oy + row,
            bottom,
            tier,
            into_machine=False,
            claimed=claimed,
            column=j,
        )

    # Overflow ingredients, seated below the output lanes and reaching up to the
    # machine band's south edge.
    for lane in s.in_below:
        row = s.row_of_input(lane[0])
        sorters += feed(lane, row=row, span=s.sorter_span(row), near_edge=bottom)

    return in_ports, out_ports, sorters


def _flank_lane(
    canvas: _Canvas,
    s: Strip,
    machines: list[int],
    out_lane: list[int],
    lane_y: int,
    item: str,
    rate: Fraction,
    belt_id: int,
    belt_model: int,
    claimed: dict[int, set[int]],
) -> int:
    """One product sorter per machine, EAST into the gap belt beside it.

    The south face of a lane-fed machine offers three columns and so does the
    north, and ``universe-matrix`` wants seven connections.  This is where the
    seventh comes from: the product leaves by the east face instead of the south,
    which hands the whole south face back to the ingredients.

    Geometry, per machine:

    * a belt stands in the column one past the machine's CLEARANCE -- ``pw - 1``
      from its west edge, with ``pw`` already bought a column wider for exactly
      this.  Inside the clearance the game's own collider check would call it a
      collision;
    * a sorter runs from the machine's lowest free east pose into that belt;
    * the belt runs SOUTH to the output lane under the band and joins it.

    JOINING, NOT SPLITTING, IS WHY THE OUTPUT IS WHAT GETS FLANKED.  A belt tile
    takes several feeders and has one successor, so several gap belts draining
    into one output lane is a shape a belt makes natively.  An ingredient would
    have to go the other way -- one lane feeding a gap belt per machine -- and
    that is a splitter per machine, which is the invariant a lane per destination
    exists to keep.

    A machine whose east slots are all spoken for is SKIPPED, silently and
    beltless, exactly as ``_link_lane`` skips one whose columns are.  It is not a
    fallback: an unwired product is what the flow checks convict, so the
    placement is refused rather than shipped short.  The belt is laid only after
    the slot is secured, so a skip leaves no orphan belt behind either.
    """
    placed = 0
    for m_idx in machines:
        m = canvas.buildings[m_idx]
        gx = m.x + s.pw - 1
        rows = slots.attachable_rows(m, gx)
        taken = claimed.setdefault(m_idx, set())
        # Lowest free row first: the gap belt runs from there down to the output
        # lane, so every row further north is another belt tile and another cell
        # the router has to path around.
        ry = next((y for y in sorted(rows, reverse=True) if rows[y].slot not in taken), None)
        if ry is None:
            continue
        got = rows[ry]
        tail = next((i for i in out_lane if canvas.buildings[i].x == gx), None)
        if tail is None:
            continue
        taken.add(got.slot)
        column: list[int] = []
        for y in range(ry, lane_y):
            column.append(
                canvas.add(
                    PlacedBuilding(
                        item_id=belt_id,
                        model_index=belt_model,
                        x=gx,
                        y=y,
                        width=1,
                        height=1,
                        yaw=Facing.SOUTH.value,
                        carries_item=item,
                    )
                )
            )
        for a, b in zip(column, column[1:], strict=False):
            canvas.buildings[a] = _relink(canvas.buildings[a], output_obj=b)
        canvas.buildings[column[-1]] = _relink(canvas.buildings[column[-1]], output_obj=tail)
        tier, _count = _pick_sorter(rate, got.span, 1)
        canvas.buildings.append(
            PlacedBuilding(
                item_id=tier,
                model_index=catalog.building(tier).model_index,
                x=got.cell[0],
                y=got.cell[1],
                width=1,
                height=1,
                x2=gx,
                y2=ry,
                z2=Fraction(0),
                yaw=Facing.EAST.value,
                yaw2=Facing.EAST.value,
                input_obj=m_idx,
                output_obj=column[0],
            )
        )
        placed += 1
    return placed


def _dock_lane(
    canvas: _Canvas,
    machines: list[int],
    out_lane: list[int],
    lane_y: int,
    item: str,
    belt_id: int,
    belt_model: int,
    claimed: dict[int, set[int]],
) -> int:
    """One BELT per machine, docked into a port and run down to the output lane.

    This is the connection a Ray Receiver takes, and the only one it takes.  Its
    prefab ships ZERO insert poses and two belt PORTS, and the game's two build
    tools mirror each other on exactly that: ``BuildTool_Inserter`` drops a cast
    target whose ``slotPoses`` is empty, ``BuildTool_Path`` drops one whose
    ``portPoses`` is empty.  So no sorter can attach to such a machine on any
    face at any distance, and a belt can.

    WHAT THE RECORD LOOKS LIKE, read off the game's own blueprints rather than
    reasoned out.  178 belt-to-port connections across five of the ten fixtures
    -- 20 Energy Exchangers in ``temple-of-effectiveness``, one in
    ``falk-v7-mall-full``, and the Interstellar Logistic Stations of four more
    -- and they are unanimous:

    * the BUILDING records nothing.  ``output_obj = input_obj = -1`` on all 28
      hosts, every slot field zero.  The belt does the naming, exactly as it
      does for a splitter;
    * a belt DRAWING from a port carries ``input_obj = <building>``,
      ``input_from_slot = <port index>`` and ``input_to_slot = 1``;
    * a belt FEEDING one carries ``output_obj = <building>``,
      ``output_to_slot = <port index>`` and ``output_from_slot = 0``;
    * both offsets are 0 on all 178.

    The port index is a subscript into ``catalog.Building.port_poses`` and NOT
    into ``slot_poses``.  They are different arrays; a Ray Receiver's second is
    empty.

    Geometry, per machine, and it is the mirror of :func:`_flank_lane`:

    * the belt stands on the tile nearest the port POSE, which for a Ray
      Receiver is 1.12 tiles from the centre of a 7x7 -- INSIDE the footprint.
      That is not something to design around.  ``geom.overlap`` already excuses
      a belt against any building, and it says why: a belt running through a
      Storage Tank appears in blueprints that work in game;
    * what could still convict it is the build-collider probe, and the game
      excuses that itself.  ``colliders.belt_run_ends_in_a_building`` lets off
      the belt whose run ends in the machine, and ``belt_chain_excuses`` lets
      off the two behind it.  A Ray Receiver's belt keepout reaches two tiles
      from its centre, so exactly two of this column's tiles are inside it and
      both are within those excusals -- measured, not hoped;
    * the column runs to the output lane under the band and joins it, several
      machines draining into one lane, which is a shape a belt makes natively.

    THE PORT IS CLAIMED IN THE SAME MAP AS A SORTER SLOT, deliberately.  The
    game addresses a connection as ``entityConnPool[objId * 16 + slot]`` -- ONE
    address space per object -- so a port index and an insert-pose index of the
    same number are the SAME cell.  No building in the catalog carries both
    arrays, so the two can never actually collide; sharing the map is what makes
    that a fact rather than an assumption.

    A machine whose ports on this side are all spoken for is SKIPPED, silently
    and beltless, exactly as :func:`_link_lane` and :func:`_flank_lane` skip one
    whose columns or rows are.  An undrained machine is what the flow checks
    convict, so the placement is refused rather than shipped short.
    """
    placed = 0
    for m_idx in machines:
        m = canvas.buildings[m_idx]
        taken = claimed.setdefault(m_idx, set())
        # The port that drains TOWARDS the lane: its forward points the way a
        # drawing belt travels, and the lane is at the larger y.
        dock = next(
            (
                d
                for _k, d in sorted(slots.port_docks(m).items())
                if d.port not in taken
                and d.facing.delta[1] > 0
                and d.cell[1] < lane_y
            ),
            None,
        )
        if dock is None:
            continue
        gx = dock.cell[0]
        tail = next((i for i in out_lane if canvas.buildings[i].x == gx), None)
        if tail is None:
            continue
        taken.add(dock.port)
        column: list[int] = []
        for y in range(dock.cell[1], lane_y):
            column.append(
                canvas.add(
                    PlacedBuilding(
                        item_id=belt_id,
                        model_index=belt_model,
                        x=gx,
                        y=y,
                        width=1,
                        height=1,
                        # The direction of TRAVEL, which is the port's own
                        # forward: `Facing.NORTH.delta` is `(0, 1)` and this
                        # column climbs in y. Read off the corpus, where a belt
                        # drawing from a station's +z port at `dy = +2` carries
                        # yaw 0 and one at `dy = -2` carries 180.
                        yaw=Facing.NORTH.value,
                        carries_item=item,
                    )
                )
            )
        for a, b in zip(column, column[1:], strict=False):
            canvas.buildings[a] = _relink(canvas.buildings[a], output_obj=b)
        canvas.buildings[column[-1]] = _relink(
            canvas.buildings[column[-1]], output_obj=tail
        )
        canvas.buildings[column[0]] = replace(
            canvas.buildings[column[0]],
            input_obj=m_idx,
            input_from_slot=dock.port,
            input_to_slot=rules.BELT_PORT_DRAW_TO_SLOT,
        )
        placed += 1
    return placed


def _link_lane(
    canvas: _Canvas,
    lane: list[int],
    machines: list[int],
    lane_y: int,
    machine_y: int,
    tier: int,
    *,
    into_machine: bool,
    claimed: dict[int, set[int]],
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

    ``claimed`` is machine index -> the slot indices already spoken for on it,
    and it is what stops two sorters landing on one.  A MACHINE SLOT HOLDS
    EXACTLY ONE CONNECTION -- the game stores it as
    ``entityConnPool[objId * 16 + slot]``, and ``WriteObjectConn`` evicts the
    sitting tenant rather than refusing -- so a second sorter on one slot pastes
    with the first silently unwired and the two of them standing on each other.
    ``validate.game.slot_occupancy`` is the check; this is where it is honoured.

    ``column`` used to be a per-LANE index into ``usable``, and
    ``usable[min(column, len(usable) - 1)]`` clamped.  Both halves put two
    sorters on one slot: two stacked lanes each asked for column 0 and got the
    same one, and a lane with more items than the machine has reachable columns
    clamped its surplus onto the last.  Measured on a pristine tree before this
    change, at budget 4: 54 of 60 freeform corpus cells carried at least one
    shared slot, 1412 in all, and every one of the 60 validated CLEAN.

    ``column`` is now a PREFERENCE, not an index: the search starts there and
    rotates through the rest.  When every reachable column of a machine is
    already spoken for, this machine gets no sorter from this lane -- the same
    answer, and the same silence, that a machine with no reachable column at all
    has always got.  It is not a fallback that hides anything: an unfed machine
    is what ``machine.inputs_supplied`` and the flow checks convict, so the
    placement is refused rather than emitted.
    """
    model_index = catalog.building(tier).model_index
    facing = Facing.SOUTH.value if lane_y < machine_y else Facing.NORTH.value  # placeholder
    placed = 0
    for m_idx in machines:
        m = canvas.buildings[m_idx]
        # WHICH column, and WHERE on the machine, from the machine's own insert
        # poses. The near edge row is right for a 3x3 and wrong for most else: a
        # Chemical Plant's southern slots are a row inside its footprint, an Oil
        # Refinery has none at all on its north face, and a Matrix Lab offers
        # only its middle three columns. `column` still spreads successive
        # sorters across the machine, but only over columns that HAVE a pose --
        # clamping to `m.width - 1` picked column 0 of a Matrix Lab, which has
        # none, and left the machine unfed.
        reachable = slots.attachable_columns(m, lane_y)
        lane_xs = {canvas.buildings[i].x for i in lane}
        usable = sorted(c for c in reachable if c in lane_xs)
        if not usable:
            continue
        taken = claimed.setdefault(m_idx, set())
        start = min(column, len(usable) - 1)
        order = usable[start:] + usable[:start]
        x = next((c for c in order if reachable[c].slot not in taken), None)
        if x is None:
            continue
        belt_idx = next((i for i in lane if canvas.buildings[i].x == x), None)
        if belt_idx is None:
            continue
        taken.add(reachable[x].slot)
        anchor_y = reachable[x].cell[1]
        if into_machine:
            src, dst = belt_idx, m_idx
            ax, ay, bx, by = x, lane_y, x, anchor_y
        else:
            src, dst = m_idx, belt_idx
            ax, ay, bx, by = x, anchor_y, x, lane_y
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
                z2=Fraction(0),
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


class TransitionForm(Enum):
    """How a belt gets from one altitude to the next.

    The game has exactly two, and they are NOT interchangeable at our
    discretion -- see :func:`transition_form`.
    """

    #: ``+/-BELT_CLIMB_PER_TILE`` per ONE tile of horizontal run.
    RAMP = "ramp"
    #: ``+/-VERTICAL_STEP`` per ZERO tiles: the belt stacks at one ``(x, y)``.
    VERTICAL = "vertical"


def transition_form(from_z: Fraction, to_z: Fraction) -> TransitionForm:
    r"""Which form to use to get from ``from_z`` to ``to_z``.

    **The rule is now known, and it is not the two-form rule this once
    guessed at.**  The game has ONE test, on slope, in ``BuildTool_Path``::

        if (!history.beltVerticalConstruction && num25 > 0.8f)
            buildPreview2.condition = EBuildCondition.TooSteep;

    A ramp is any slope inside ``MAX_BELT_SLOPE``; the vertical form is simply
    the case where the run is zero, which is infinite slope and needs the
    ``beltVerticalConstruction`` unlock.  There is no height threshold
    selecting between them, and no cap on how high a ramp may climb -- the only
    ceiling is ``buildMaxHeight``, and ``catalog.belt_max_z`` carries it.

    So an earlier reading here -- that the game picks by height, from the user's
    "at lower heights it does a ramp" -- described a consequence, not the rule:
    at low heights a ramp is available and cheaper in materials, and above the
    slope limit only the vertical form remains.  Both readings predict the same
    blueprints; only the source distinguishes them.

    This router emits RAMP always.  A blueprint-z rise of
    ``BELT_CLIMB_PER_TILE`` over one tile is a world slope of ``2/3``, inside
    the ``4/5`` limit, at ANY altitude, so the ramp needs no unlock and is
    always available.

    .. note::
       **The vertical form is a real density lever and is deliberately NOT
       built.**  With ``beltVerticalConstruction`` a level change costs ZERO
       horizontal tiles instead of ``RAMP_TILES_PER_LEVEL``, and the user's own
       save has the tech -- their max-height blueprint climbs ``z = 0 -> 38`` in
       38 steps, none of which moves.  Every crossing this router makes
       currently spends two tiles going up and two coming down; on the vertical
       form that is four tiles returned per crossing, and there were 8 to 28
       level changes per generated blueprint.

       Not built here because it is a ROUTING change -- A\* would need a
       zero-run move, and the reservation and profile both assume a climb
       occupies tiles -- and this branch is already carrying the emission fix,
       the slope rule and the technology plumbing.  It also only applies to
       saves that have the tech, so it cannot replace the ramp, only beat it
       where available.  Measure it separately when the router work resumes.
    """
    del from_z, to_z  # slope, not height, decides -- and ours is always legal
    return TransitionForm.RAMP


def _altitude_profile(
    path: Sequence[tuple[int, int, int]], *, ramped: bool
) -> list[Fraction] | None:
    r"""World altitude for every cell of a routed path, ramps materialised.

    **This is the level-index -> world-altitude boundary.**  The router walks an
    integer lattice; :class:`PlacedBuilding` stores tiles of height.  Handing a
    lattice index straight to the encoder is what shipped belts the game drew
    red -- a chain that read ``0, 0, 1, 1`` climbed a whole tile of height in
    one tile of run, twice as fast as a belt can, with no tile at ``1/2`` where
    every real elevated run has one.

    A level change already costs the router two tiles: the A\* ramp edge
    reserves a *via* cell one step along, at the OLD level, before landing on
    the new level two steps along.  Both are already in ``path``, so
    materialising the ramp costs **no extra tiles** -- the via cell's altitude
    was wrong, not its existence.  The cell that needs the half value is the one
    whose successor sits on a different level, which is exactly that via cell::

        levels    0     0     0     0     1     1     1     0     0
        altitude  0     0     0    1/2    1     1    1/2    0     0
                              ^ via              ^ via

    Matching the corpus, where every elevated run reads
    ``0.0, 0.5, 1.0, ... 1.0, 0.5, 0.0``.  Per the user that shape is forced
    rather than stylistic: a belt at ``1/2`` still fouls one at ``0``, so a
    crossing has to be a full level up and the climb has to start two tiles out.

    ``1/2`` is a legal RESTING altitude too, not only a ramp tile -- the corpus
    has runs up to 23 tiles long at that height -- so a profile is not required
    to pass straight through it.

    Which form each change takes is :func:`transition_form`'s decision, never
    this function's.
    """
    levels = [lvl for _, _, lvl in path]
    if not ramped:
        # The slope limit is CONDITIONAL and this save is not under it, so a
        # level change needs no ramp: the belt simply steps up.  See `ramped`
        # in the docstring -- with `beltVerticalConstruction` the game skips
        # the `TooSteep` test entirely, so a whole tile of height across one
        # tile of run is legal, and spending a second tile on it would cost
        # routability for nothing.
        return [lvl * _LEVEL_HEIGHT for lvl in levels]
    out: list[Fraction] = []
    for j, lvl in enumerate(levels):
        nxt = levels[j + 1] if j + 1 < len(levels) else lvl
        if nxt == lvl:
            out.append(lvl * _LEVEL_HEIGHT)
            continue
        if abs(nxt - lvl) != 1:
            raise AssertionError(
                f"path step {j} jumps {abs(nxt - lvl)} levels at {path[j]} -> "
                f"{path[j + 1]}; the ramp table offers +/-1 only, and a wider "
                f"jump has no defined altitude profile"
            )
        form = transition_form(lvl * _LEVEL_HEIGHT, nxt * _LEVEL_HEIGHT)
        if form is not TransitionForm.RAMP:
            raise AssertionError(
                f"path step {j} wants the {form.value} form, which costs no "
                f"horizontal run -- but A* spent a tile on it, so the path and "
                f"the profile disagree about the shape of this climb"
            )
        # A ramp needs a FLAT cell to leave from, because the half-level this
        # cell sits at is measured from the level it is departing.  Two changes
        # back to back have none: levels `0, 1, 2` over three cells would read
        # `1/2, 3/2, 2`, and `1/2 -> 3/2` is a whole tile of height across one
        # tile of run -- the very step this module exists to stop emitting.
        # Caught in the wild as `geom.altitude_step` on `magnetic-ring`, 5
        # times over 12 layouts, after `LEVELS` rose to 3 and made consecutive
        # ramps reachable at all.
        #
        # There is no altitude assignment that rescues such a path: the cells
        # are already committed to their levels and the run between them is one
        # tile, so the climb cannot be spread.  Saying so returns it to the
        # router as an unrouted net, which is a failure it already knows how to
        # retry, rather than emitting something the game refuses.
        if j > 0 and levels[j - 1] != lvl:
            return None
        step = catalog.BELT_CLIMB_PER_TILE if nxt > lvl else -catalog.BELT_CLIMB_PER_TILE
        out.append(lvl * _LEVEL_HEIGHT + step)
    return out


def _legal_link(
    ax: int, ay: int, az: Fraction, bx: int, by: int, bz: Fraction, *, ramped: bool
) -> bool:
    """May a belt at ``a`` hand on to one at ``b``?

    The two ends of a routed path get joined to whatever lane belt they reach,
    and "close enough" is not the test -- the JOIN is a belt-to-belt link like
    any other, so it has to be one of the game's two altitude changes or no
    change at all.  The old test here was ``dxy <= 1 and |dz| <= 1``, which
    admits ``dz = 1`` across one tile: a ramp at twice the legal climb, the
    very step that shipped red.  ``geom.altitude_step`` now catches it, and
    this stops producing it.
    """
    dxy = abs(bx - ax) + abs(by - ay)
    dz = bz - az
    if not ramped:
        # No slope limit on this save, so the only question is adjacency.
        return dxy <= 1 and abs(dz) <= catalog.VERTICAL_STEP
    if dz == 0:
        return dxy <= 1
    # Only the form `transition_form` would choose for this climb.  The
    # VERTICAL form is legal in the game and the validator accepts it, but the
    # rule selecting between the two is not known and the user reports the game
    # picks on height -- so taking a vertical join here because it is free
    # would be choosing a form we have no evidence for at one level, which is
    # the same class of mistake as the step this branch exists to refuse.
    if transition_form(az, bz) is TransitionForm.RAMP:
        return abs(dz) == catalog.BELT_CLIMB_PER_TILE and dxy == 1
    return abs(dz) == catalog.VERTICAL_STEP and dxy == 0


def _lattice_cell(x: int, y: int, z: Fraction) -> tuple[int, int, int] | None:
    """The routing-lattice cell a building at world altitude ``z`` occupies.

    ``None`` when ``z`` is between levels, which means a ramp tile: it rests at
    ``1/2`` and reserves the level it climbs FROM (see :meth:`_Canvas.add`), so
    there is no single lattice cell that "is" it.  Callers looking a neighbour
    up by its world altitude want to skip those rather than round them, because
    rounding would claim a cell the ramp does not hold.

    This is the inverse of :func:`_altitude_profile` and the only other place
    the two coordinate systems meet.
    """
    return (x, y, int(z)) if z.denominator == 1 else None


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
    # `canvas.solid` is NOT punched out here, and must not be: the band a
    # machine really denies is already in `blocked` above, level by level, and
    # blanking the whole column would put this grid back in disagreement with
    # `_Canvas.free` -- in the other direction from the bug documented below,
    # but the same bug.
    for cx, cy in canvas.keep_out:
        if lo_x <= cx <= hi_x and lo_y <= cy <= hi_y:
            at = (cx - gx0) * xstep + (cy - gy0) * LEVELS
            occ[at : at + LEVELS] = holes
    # THE BAND OVER A BELT ADDON AND A JUNCTION'S COLLIDER, which this used to
    # leave out -- and leaving them out is not a missing optimisation, it is a
    # grid that DISAGREES WITH ``_Canvas.free``.
    #
    # `_Canvas.free` refuses both (see `belt_ban` and `guard`); the flat grid is
    # what A* actually searches, and it was built from `blocked`, `solid`,
    # `keep_out` and `reserved` only.  So the search happily returned paths
    # through a Spray Coater's 1.8975 band, `_commit_paths` asked `free` about
    # every cell it was about to build on, found one refused, and dropped the
    # WHOLE net -- counted in `unlinked`, which the sweep reads as "this pack
    # could not be wired" and discards.  Round after round, because nothing in
    # the search had learned anything: the next round produced the same path.
    #
    # Traced on `plastic/max-proliferation`, where every routing pass reported
    # `5 paths, 1 unlinked` and the one was always the same net, always refused
    # at the same cell -- `(6, 8)` at level 1, the tile a coater rides, banned
    # in `belt_ban` and passable in the grid.  The refusal named the PACKER.
    for (cx, cy), levels in canvas.belt_ban.items():
        if lo_x <= cx <= hi_x and lo_y <= cy <= hi_y:
            at = (cx - gx0) * xstep + (cy - gy0) * LEVELS
            for clvl in levels:
                if 0 <= clvl < LEVELS:
                    occ[at + clvl] = 0
    for cx, cy, clvl in canvas.guard:
        if lo_x <= cx <= hi_x and lo_y <= cy <= hi_y and 0 <= clvl < LEVELS:
            occ[(cx - gx0) * xstep + (cy - gy0) * LEVELS + clvl] = 0
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


@dataclass(frozen=True, slots=True)
class _PathSearchResult:
    path: tuple[Cell, ...] | None
    kind: RouteFailureKind | None
    wall: tuple[Cell, ...]
    expansions: int


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
) -> _PathSearchResult:
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
    Running out of clock reports :attr:`RouteFailureKind.BUDGET`, which is the
    route-failure path -- and a route failure is a REFUSAL, since ``_sweep``
    discards any pack with an unrouted net.  A deadline can therefore cost a
    placement but can never degrade one.

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
        return _PathSearchResult(None, RouteFailureKind.DYNAMIC_ACCESS, (), 0)
    has_live_start = False
    for start in starts:
        if canvas.free(start):
            has_live_start = True
            break
    if not has_live_start:
        return _PathSearchResult(None, RouteFailureKind.DYNAMIC_ACCESS, (), 0)
    if (budget is not None and budget["left"] <= 0) or _expired(deadline):
        return _PathSearchResult(None, RouteFailureKind.BUDGET, (), 0)

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

        def h(p: int) -> float:
            x, y = divmod(p, gh)
            dx = x - only_x
            dy = y - only_y
            return (dx if dx >= 0 else -dx) + (dy if dy >= 0 else -dy)

    elif len(goal_list) <= _EXACT_HEURISTIC_GOALS:
        # A LOOP, not `min` over a generator.  Same value, and the generator was
        # measured at 3.1s of a 15.8s routing pass for 996k calls -- 3.1us each,
        # against 0.9us for the composite that wraps it.  Building and draining
        # a generator frame per NODE is most of that; the goal set here is a
        # handful of cells and duplicates in x or y are pointless work, so the
        # list is deduplicated once instead.
        near = tuple({(c[0] - gx0, c[1] - gy0) for c in goal_list})

        def h(p: int) -> float:
            x, y = divmod(p, gh)
            best_d = 1 << 30
            for fx, fy in near:
                dx = x - fx
                dy = y - fy
                d = (dx if dx >= 0 else -dx) + (dy if dy >= 0 else -dy)
                if d < best_d:
                    best_d = d
            return best_d

    else:
        bx0 = min(c[0] for c in goal_list) - gx0
        bx1 = max(c[0] for c in goal_list) - gx0
        by0 = min(c[1] for c in goal_list) - gy0
        by1 = max(c[1] for c in goal_list) - gy0

        def h(p: int) -> float:
            x, y = divmod(p, gh)
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

    if bands and len(goal_list) == 1:
        # THE SINGLE-GOAL DISTANCE IS INLINED HERE, and only here.
        #
        # One goal is by far the commonest shape and it is the case the wrapper
        # cost the most, because the whole body it was calling is four
        # subtractions: a Python frame per node to save nothing.  Profiled on
        # `universe-matrix/no-proliferator` power=1 at h=185, the composite ran
        # 2.71M times in one routing pass.  Identical values -- this is the same
        # expression, not an approximation of it.
        def h(p: int) -> float:  # noqa: F811
            x, y = divmod(p, gh)
            dx = x - only_x
            dy = y - only_y
            far: float = (dx if dx >= 0 else -dx) + (dy if dy >= 0 else -dy)
            at = p
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

    elif bands:
        plain = h

        def h(p: int) -> float:  # noqa: F811
            far = plain(p)
            at = p
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

    # A BYTE PER CELL rather than a set of cell indices: the goal test is on the
    # expansion path, so it runs once per node popped, and a `bytearray(size)` is
    # a 1.4us calloc against the 290us a list of that length costs.  Every goal
    # index is inside the span -- the caller's grid was checked against it above,
    # and a one-off grid is built from `_span_for`, which covers the goals.
    goal_flag = bytearray(size)
    for c in goal_list:
        goal_flag[(c[0] - gx0) * xstep + (c[1] - gy0) * ystep + c[2]] = 1

    # (one-step cell offset, two-step cell offset, one-step column offset,
    # two-step column offset) -- the ramp's run cell is the plain step's target,
    # so one pass over the four directions does both, and the column offsets
    # index `hcache` without re-deriving a column from a cell.  ``dx`` and
    # ``dy`` are NOT carried: nothing in the loop wants them since `h` began
    # taking a column, and unpacking two dead names four times per expansion is
    # 5.6M unpackings in a `quantum-chip` pass.
    moves = tuple(
        (
            dx * xstep + dy * ystep,
            2 * (dx * xstep + dy * ystep),
            dx * gh + dy,
            2 * (dx * gh + dy),
        )
        for dx, dy in _STEPS
    )

    expansions = 0
    heappush = heapq.heappush
    heappop = heapq.heappop
    inf = math.inf
    level_toll = _LEVEL_TOLL
    ramp_table = _RAMPS

    # ONE COUNTER AND ONE COMPARE PER EXPANSION, where there were three guards
    # and two dict operations.
    #
    # The cap, the deadline check and the shared budget all fire at expansion
    # counts that are known in advance, so the soonest of the three is computed
    # once and re-derived only when it is reached.  `budget` is read into a
    # local and written back at every exit, because a `budget["left"] -= 1` is a
    # hash, a lookup and a store on the hottest line in this router -- 1.25M of
    # them in one `quantum-chip` routing pass.
    #
    # It is the same arithmetic, not an approximation of it.  The budget was
    # charged for an expansion only AFTER the cap and the deadline had let that
    # expansion through, so an exit on either of those has charged one fewer;
    # that is why the two write-backs differ by one.  Get it wrong and the pass
    # spends a different number of nodes on every later net.
    start_left = budget["left"] if budget is not None else 1 << 62
    checkpoint = _MAX_EXPANSIONS + 1
    if checkpoint > _DEADLINE_CHECK_EVERY:
        checkpoint = _DEADLINE_CHECK_EVERY
    if start_left < checkpoint:
        checkpoint = start_left

    # THE HEURISTIC IS A FUNCTION OF THE COLUMN, so it is computed once per
    # column and not once per push.
    #
    # `h` reads only `x` and `y`; the level never enters it.  A cell and the two
    # above it therefore share an answer, and so does every later push to a cell
    # whose cost improved.  Profiled on `quantum-chip` power=1, the four `h`
    # variants ran 2.63M times against 1.25M expansions -- roughly two calls per
    # node expanded, all but the first of them re-deriving a number already
    # known.
    #
    # `-1.0` is safe as "not yet computed" because `h` is a distance and cannot
    # be negative: the plain term is a Manhattan distance and the landmark bands
    # only ever raise it.  Cached by COLUMN index, which is `cur // LEVELS`, so
    # the table is a third the size of the search arrays.
    hcache = [-1.0] * (size // LEVELS)

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
        heappush(
            open_heap,
            (h((s[0] - gx0) * gh + (s[1] - gy0)), 0.0, si),
        )
    if not open_heap:
        return _PathSearchResult(None, RouteFailureKind.DYNAMIC_ACCESS, (), 0)

    while open_heap:
        _, g, cur = heappop(open_heap)
        if g > best[cur]:
            continue
        expansions += 1
        if expansions >= checkpoint:
            if expansions > _MAX_EXPANSIONS:
                if budget is not None:
                    budget["left"] = start_left - expansions + 1
                return _PathSearchResult(
                    None, RouteFailureKind.BUDGET, (), expansions
                )
            if expansions % _DEADLINE_CHECK_EVERY == 0 and _expired(deadline):
                if budget is not None:
                    budget["left"] = start_left - expansions + 1
                return _PathSearchResult(
                    None, RouteFailureKind.BUDGET, (), expansions
                )
            if expansions >= start_left:
                if budget is not None:
                    budget["left"] = start_left - expansions
                return _PathSearchResult(
                    None, RouteFailureKind.BUDGET, (), expansions
                )
            checkpoint = _MAX_EXPANSIONS + 1
            due = (expansions // _DEADLINE_CHECK_EVERY + 1) * _DEADLINE_CHECK_EVERY
            if due < checkpoint:
                checkpoint = due
            if start_left < checkpoint:
                checkpoint = start_left
        if goal_flag[cur]:
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
            if budget is not None:
                budget["left"] = start_left - expansions
            return _PathSearchResult(
                tuple(_cut_loops(list(reversed(path)))), None, (), expansions
            )
        q = cur // LEVELS
        lvl = cur - q * LEVELS
        # A plain step stays on `lvl`, so its toll is fixed for this expansion.
        step_toll = 1.0 + level_toll[lvl]
        # And so is the pair of ramps this cell may take, and the base of their
        # cost: `g + 3.0` is the same number for all eight ramp targets, and
        # adding it once rather than eight times keeps the association order
        # `g + 3.0 + toll` that the ramp cost has always used -- these are
        # floats, so re-bracketing them is not free of consequences.
        ramps = ramp_table[lvl]
        run_base = g + 3.0
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
        for one, two, colone, coltwo in moves:
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
                col = q + colone
                far = hcache[col]
                if far < 0.0:
                    far = hcache[col] = h(col)
                heappush(open_heap, (cost + far, cost, nxt))

            # A level change costs two tiles of run, because belts climb 0.5 per
            # tile.  Both are reserved so the ramp physically exists -- and the
            # lower one is `nxt`, already cleared above.
            run = cur + two
            for step, toll2 in ramps:
                top = run + step
                if not flags[top]:
                    continue
                cost = run_base + toll2
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
                    col = q + coltwo
                    far = hcache[col]
                    if far < 0.0:
                        far = hcache[col] = h(col)
                    heappush(open_heap, (cost + far, cost, top))

    # THE HEAP EMPTIED, which is the one ending that proves no path exists -- the
    # Budget exits above do not say the pocket is sealed. The cells with a finite
    # `best` are exactly the free space this net could reach and the blocked cells
    # touching it are its wall. Only tentative cells have a routing-net owner.
    if budget is not None:
        budget["left"] = start_left - expansions
    wall_cells: tuple[Cell, ...] = ()
    pocket = []
    for i, seen_at in enumerate(best):
        if seen_at != inf:
            pocket.append(i)
            if len(pocket) > _BLAME_MAX_POCKET:
                break
    if len(pocket) <= _BLAME_MAX_POCKET:
        blocked_get = canvas.blocked.get
        wall: set[Cell] = set()
        for i in pocket:
            q, blvl = divmod(i, LEVELS)
            bx, by = divmod(q, gh)
            bx += gx0
            by += gy0
            for dx, dy in _STEPS:
                cell = (bx + dx, by + dy, blvl)
                if (
                    blocked_get(cell) == _TENTATIVE
                    and not flags[flat.index(cell)]
                ):
                    wall.add(cell)
        if len(wall) <= _BLAME_MAX_WALL:
            wall_cells = tuple(sorted(wall))
            if blame is not None:
                for cell in wall_cells:
                    blame[cell] = blame.get(cell, 0.0) + 1.0
    return _PathSearchResult(
        None, RouteFailureKind.SEALED_POCKET, wall_cells, expansions
    )

@dataclass
class _Net:
    src: _Port | None
    dst: _Port
    item: str
    net_id: NetId | None = None
    boundary_goals: tuple[tuple[int, int, int], ...] = ()

    @property
    def source(self) -> _Port:
        if self.src is None:
            raise ValueError("external-input nets have no source port")
        return self.src


@dataclass(frozen=True, slots=True)
class _PreparedNet:
    net_id: NetId
    src: _PreparedPort | None
    dst: _PreparedPort
    item: str
    boundary_goals: tuple[tuple[int, int, int], ...] = ()


@dataclass(slots=True)
class _RoutingWorkspace:
    canvas: _Canvas
    buildings: list[PlacedBuilding]
    nets: list[_Net]


@dataclass(frozen=True, slots=True)
class _PreparedRoutingProblem:
    building_templates: tuple[PlacedBuilding, ...]
    blocked: tuple[tuple[tuple[int, int, int], int], ...]
    solid: frozenset[tuple[int, int]]
    reserved: tuple[
        tuple[tuple[int, int, int], tuple[int, int]],
        ...,
    ]
    keep_out: frozenset[tuple[int, int]]
    nets: tuple[_PreparedNet, ...]
    core: tuple[int, int, int, int]
    route_bounds: tuple[int, int, int, int]
    limit: tuple[int, int, int, int] | None
    power_sites: tuple[tuple[int, int], ...]
    sorters: int
    coaters: int
    direct_inserts: int

    def new_workspace(self) -> _RoutingWorkspace:
        buildings = deepcopy(list(self.building_templates))
        canvas = _Canvas(
            buildings=buildings,
            blocked=dict(self.blocked),
            solid=set(self.solid),
            reserved=dict(self.reserved),
            routing_ports=frozenset(),
            limit=self.limit,
            keep_out=set(self.keep_out),
        )
        nets = [_bind_prepared_net(net, buildings) for net in self.nets]
        return _RoutingWorkspace(canvas=canvas, buildings=buildings, nets=nets)


def _bind_prepared_net(
    net: _PreparedNet, buildings: list[PlacedBuilding]
) -> _Net:
    return _Net(
        src=(
            _bind_prepared_port(net.src, buildings)
            if net.src is not None
            else None
        ),
        dst=_bind_prepared_port(net.dst, buildings),
        item=net.item,
        net_id=net.net_id,
        boundary_goals=net.boundary_goals,
    )


def _merge_frontier(
    canvas: _Canvas,
    paths: Mapping[int, Sequence[Cell]],
    siblings: tuple[int, ...],
    junctionable: Callable[[int, int], bool] | None = None,
) -> set[tuple[int, int, int]]:
    """Free cells beside a sibling net's path -- somewhere to merge into.

    Two belts feeding one is a side merge, which the game allows and
    ``_build_runs`` already models (a tile with two predecessors heads its own
    run).  Reaching a sibling's belt is therefore as good as reaching the lane
    it feeds, and it is the ONLY option when the lane itself is walled in.

    The sibling's own cells are not offered as goals: they are occupied, so A*
    could never step onto them.  Their free neighbours are what a merging belt
    actually needs.

    ``junctionable`` IS THE SOURCE SIDE ONLY, and it is the difference between
    offering a merge point and offering a merge point that can be built.
    Leaving a sibling's path puts a SPLITTER on the cell left from, because that
    cell already flows onward; a splitter's cross collider needs three and a
    half tiles from an Assembling Machine's centre, and a path running beside a
    machine band offers plenty of cells at 2.83.  Without the filter A* takes
    the cheapest of those, ``_tap_source`` refuses the site at commit time, and
    the whole pack is discarded for a tap that was never legal -- with the
    router blamed for a route it was told to make.

    The DESTINATION side passes nothing, and that is not an oversight: arriving
    at a sibling's path builds no junction at all, only a link from this path's
    tail (see ``_sink_for``), so no site has to be clear.

    THE BELT HALF IS ASKED HERE TOO, and it is asked here rather than at commit
    time for the reason the backlog entry records: a site test inside
    ``_commit_paths`` cannot see a belt that has not been staked yet, and
    tightening it there only starves the router of taps.  A junction denies
    :func:`junction.keepout_cells` to any belt that is not on its own run, so a
    sibling's cell whose keep-out already holds a FOREIGN belt is not a merge
    point that can be built -- and withdrawing it costs the router one of the
    several cells a frontier offers, where refusing at commit time costs the
    whole pack.
    """
    out: set[tuple[int, int, int]] = set()
    for s in siblings:
        path = paths.get(s, ())
        for at, (x, y, lvl) in enumerate(path):
            if junctionable is not None and not junctionable(x, y):
                continue
            # The neighbours FIRST, and the belt half only for a cell that has
            # some. This is a routing pass's inner loop -- every sibling's every
            # cell, per net, per round -- and most cells of a settled path are
            # walled in by their own neighbours, so testing a keep-out nobody
            # could have used is the expensive half of a question already
            # answered.
            free = [
                cell
                for dx, dy in _STEPS
                if canvas.free(cell := (x + dx, y + dy, lvl))
            ]
            if not free:
                continue
            if junctionable is not None and not _junction_belt_clear(
                canvas, (x, y, lvl), path, at
            ):
                continue
            out.update(free)
    return out


def _junction_belt_clear(
    canvas: _Canvas,
    tap: tuple[int, int, int],
    path: Sequence[tuple[int, int, int]],
    at: int,
) -> bool:
    """Is a junction on ``tap`` clear of belts the game would not excuse?

    ``path`` is the run the junction would sit on and ``at`` where on it, so the
    cells the game DOES excuse are known: ``colliders.belt_chain_excuses`` lets
    a belt off when the junction is within three hops along its own run, which
    on a straight path is the three cells either side.  Two are taken here
    rather than three, because a run that doubles back can put its own fourth
    cell against the junction and this predicate should not have to know.

    Only cells the router can still see are consulted, so this is a ROUTING-TIME
    question: a cell held by a settled belt or by another net's staked path is
    foreign, and everything else -- machines, sorters, empty ground -- is not
    this rule's business.  ``junction.site_is_clear`` asks the machine half.
    """
    excused = set(path[max(0, at - 2) : at + 3])
    for cell in junction.keepout_cells(*tap):
        if cell in excused:
            continue
        who = canvas.blocked.get(cell)
        if who is None:
            continue
        if who == _TENTATIVE:
            return False
        if 0 <= who < len(canvas.buildings) and catalog.is_belt(
            canvas.buildings[who].item_id
        ):
            return False
    return True


def _route_all(
    canvas: _Canvas,
    nets: list[_Net],
    belt_id: int,
    belt_model: int,
    bounds: tuple[int, int, int, int],
    deadline: float | None = None,
    budget: dict[str, int] | None = None,
) -> DetailedRouteResult:
    """Route every net, negotiating congestion across iterations.

    Returns stable routed and stranded net identities plus the diagnostic from
    the selected best round. Failures are returned rather than raised: the
    caller decides whether to repair, and a silently swallowed failure is
    exactly the bug that made Strategy A ship a fallback wearing a solver's
    clothes.

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
    paths: dict[int, tuple[Cell, ...]] = {}
    owner: dict[Cell, int] = {}
    iterations = 0
    expansions = 0
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
    #: nothing left to search with, and `_astar` reports budget exhaustion for
    #: every net before expanding a node. Committing that round throws away a
    #: perfectly good routing and reports the pack unwireable.
    #:
    #: Measured on universe-matrix/max-proliferation: two of the five candidate
    #: heights reported `routed=0 failed=115` -- every net -- while their first
    #: round had routed roughly seventy of them. Rip-up-and-reroute is a search
    #: over rounds; keeping the incumbent is what makes it one.
    best_paths: dict[int, tuple[Cell, ...]] = {}
    best_failures: dict[int, NetFailure] = {}

    def _net_id(index: int) -> NetId:
        net_id = nets[index].net_id
        if net_id is None:
            raise ValueError("detailed routing requires stable net IDs")
        return net_id

    def _blocking_nets(wall: Sequence[Cell]) -> tuple[NetId, ...]:
        # Sort transient integer indices, which have a total order. NetId's
        # optional strip fields deliberately do not compare across None/int.
        blocker_indices = sorted(
            {
                blocker
                for cell in wall
                if (blocker := owner.get(cell)) is not None
            }
        )
        return tuple(_net_id(blocker) for blocker in blocker_indices)

    def _failure(
        index: int,
        search: _PathSearchResult,
        blocking_nets: tuple[NetId, ...],
    ) -> NetFailure:
        return NetFailure(
            net_id=_net_id(index),
            kind=search.kind or RouteFailureKind.DYNAMIC_ACCESS,
            wall=search.wall,
            blocking_nets=blocking_nets,
            expansions=search.expansions,
        )

    def _budget_result() -> DetailedRouteResult:
        return DetailedRouteResult(
            status=DetailedRouteStatus.BUDGET,
            routed=(),
            failures=tuple(
                NetFailure(_net_id(i), RouteFailureKind.BUDGET, (), (), 0)
                for i in range(len(nets))
            ),
            iterations=iterations,
            expansions=expansions,
        )

    def _finish(
        selected_paths: dict[int, tuple[Cell, ...]],
        selected_failures: dict[int, NetFailure],
        *,
        budget_exhausted: bool,
    ) -> DetailedRouteResult:
        unlinked = _commit_paths(
            canvas,
            nets,
            selected_paths,
            belt_id,
            belt_model,
            src_group,
            dst_group,
        )
        failures = dict(selected_failures)
        if budget_exhausted:
            for index in range(len(nets)):
                if index not in selected_paths:
                    previous = failures.get(index)
                    failures[index] = NetFailure(
                        _net_id(index),
                        RouteFailureKind.BUDGET,
                        (),
                        (),
                        previous.expansions if previous is not None else 0,
                    )
        for index in unlinked:
            failures[index] = NetFailure(
                _net_id(index), RouteFailureKind.COMMIT_LINK, (), (), 0
            )
        routed = tuple(
            _net_id(index)
            for index in range(len(nets))
            if index in selected_paths and index not in failures
        )
        ordered_failures = tuple(
            failures[index] for index in range(len(nets)) if index in failures
        )
        status = (
            DetailedRouteStatus.BUDGET
            if (
                budget_exhausted
                or any(
                    failure.kind is RouteFailureKind.BUDGET
                    for failure in ordered_failures
                )
            )
            else (
                DetailedRouteStatus.STRANDED
                if ordered_failures
                else DetailedRouteStatus.ROUTED
            )
        )
        return DetailedRouteResult(
            status=status,
            routed=routed,
            failures=ordered_failures,
            iterations=iterations,
            expansions=expansions,
        )

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
        same_src[net.source.y, net.source.x0].append(i)
    src_group = {
        i: tuple(g for g in same_src[net.source.y, net.source.x0] if g != i)
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

    #: (x, y) -> may a splitter stand there.  Memoised for the whole pass, which
    #: is exact rather than approximate: `canvas.buildings` does not change while
    #: rounds run -- belts are only ever added by `_commit_paths`, after the last
    #: round has already returned.
    junction_ok: dict[tuple[int, int], bool] = {}

    def _can_junction(x: int, y: int) -> bool:
        got = junction_ok.get((x, y))
        if got is None:
            got = junction.site_is_clear(canvas.buildings, x, y)
            junction_ok[x, y] = got
        return got

    def _stake(index: int, path: tuple[Cell, ...]) -> None:
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
            {(net.source.x, net.source.y), (net.dst.x, net.dst.y)}
        )
        # THE LANE TILE IS ONLY FREE FOR THE FIRST NET TO LEAVE IT.  Its port is
        # the lane's END, which has no onward link, so the first tap merely
        # points it at the branch. Every later one finds that link in place and
        # needs a SPLITTER on the lane tile -- and a lane runs directly beside
        # its machine band, where a splitter's cross collider never fits. Those
        # starts are withdrawn rather than offered and then refused at commit
        # time, which is the difference between the router picking its second
        # choice and the whole pack being discarded.
        siblings = src_group.get(index, ())
        needs_junction = any(s in paths for s in siblings) or (
            canvas.buildings[net.src.belt].output_obj is not None
        )
        starts = (
            []
            if needs_junction and not _can_junction(net.src.x, net.src.y)
            else [
                (net.src.x + dx, net.src.y + dy, net.src.z)
                for dx, dy in _STEPS
                if canvas.free((net.src.x + dx, net.src.y + dy, net.src.z))
            ]
        )
        # Leaving from a sibling's belt is as good as leaving from the lane,
        # and it is the only option when the lane is walled in. `_tap_source`
        # turns the attachment into a splitter on that belt, so only cells that
        # can CARRY a splitter are offered.
        starts.extend(
            sorted(
                _merge_frontier(canvas, paths, siblings, _can_junction) - set(starts)
            )
        )
        goals = {
            (net.dst.x + dx, net.dst.y + dy, net.dst.z)
            for dx, dy in _STEPS
            if canvas.free((net.dst.x + dx, net.dst.y + dy, net.dst.z))
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
        stranded: list[int],
        pressure: float,
        blame: dict[Cell, float],
        search_failures: dict[int, _PathSearchResult],
        search_blockers: dict[int, tuple[NetId, ...]],
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
            through: Sequence[Cell],
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
                (through[0], net.source, src_group, 0),
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

        nonlocal expansions
        still: list[int] = []
        for index in stranded:
            if _expired(deadline) or budget["left"] <= 0:
                still.append(index)
                continue
            starts, goals = _ends(index)
            through = _astar(
                canvas, starts, goals, history, 1.0, bounds, budget, deadline,
                None, open_grid,
            )
            canvas.routing_ports = frozenset()
            expansions += through.expansions
            if through.path is None:
                if through.kind is RouteFailureKind.BUDGET:
                    # A per-search cap is unknown even while the shared pass
                    # budget and deadline remain. It supersedes the primary
                    # pocket diagnosis and carries no hard blocker evidence.
                    search_failures[index] = through
                    search_blockers[index] = ()
                # A genuinely exhausted crossing search made settled paths
                # passable, so keep the primary wall/ownership snapshot rather
                # than reassigning historical blame from its empty census.
                still.append(index)
                continue
            through_path = through.path
            victims = _leaning(
                {owner[cell] for cell in through_path if cell in owner}
            )
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
            if _stands_on(index, through_path, victims):
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
            _stake(index, through_path)
            # The displaced go looking for a way round, longest first for the
            # same reason the round orders that way.
            moved: list[int] = []
            for hurt in sorted(
                victims,
                key=lambda i: -(
                    abs(nets[i].source.x - nets[i].dst.x)
                    + abs(nets[i].source.y - nets[i].dst.y)
                ),
            ):
                starts, goals = _ends(hurt)
                again = _astar(
                    canvas, starts, goals, history, pressure, bounds, budget,
                    deadline, blame, grid,
                )
                canvas.routing_ports = frozenset()
                expansions += again.expansions
                if again.path is None:
                    break
                _stake(hurt, again.path)
                moved.append(hurt)
            if len(moved) == len(victims):
                search_failures.pop(index, None)
                search_blockers.pop(index, None)
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
        search_failures: dict[int, _PathSearchResult] = {}
        search_blockers: dict[int, tuple[NetId, ...]] = {}
        #: Cells that CUT the board this round, and how many nets each cut off.
        #:
        #: Fresh every round, because a wall only exists while the path that
        #: built it does; `history` is where the charge accumulates.
        blame: dict[Cell, float] = {}
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
                abs(nets[i].source.x - nets[i].dst.x)
                + abs(nets[i].source.y - nets[i].dst.y)
            ),
        )
        stranded: list[int] = []
        for i in order:
            if _expired(deadline):
                return _budget_result()
            starts, goals = _ends(i)
            searched = _astar(
                canvas, starts, goals, history, pressure, bounds, budget, deadline,
                blame, grid,
            )
            canvas.routing_ports = frozenset()
            expansions += searched.expansions
            if searched.path is None:
                search_failures[i] = searched
                search_blockers[i] = _blocking_nets(searched.wall)
                stranded.append(i)
                continue
            _stake(i, searched.path)
        # AND THE REPAIR, before conceding the round.
        #
        # Repeated while it keeps placing nets, because a displaced net that
        # strands in turn is the same problem one step along and answers to the
        # same move. It stops the moment a pass places nobody, which is when the
        # contention has stopped being local and negotiation should price it.
        for _ in range(_REPAIR_PASSES):
            if not stranded or _expired(deadline):
                break
            after = _repair(
                stranded,
                pressure,
                blame,
                search_failures,
                search_blockers,
            )
            if len(after) >= len(stranded):
                stranded = after
                break
            stranded = after
        failed = len(stranded)
        if failed == 0:
            return _finish(paths, {}, budget_exhausted=False)
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
            best_failures = {
                index: _failure(
                    index,
                    search_failures[index],
                    search_blockers[index],
                )
                for index in stranded
            }
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
    return _finish(
        best_paths,
        best_failures,
        budget_exhausted=budget["left"] <= 0 or _expired(deadline),
    )


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
    level: dict[tuple[int, int], int] = {}
    for net in nets:
        for role, port in (("src", net.src), ("dst", net.dst)):
            if port is None:
                continue
            key = (port.x, port.y)
            ports[key] = max(ports.get(key, 0), len(port.columns()))
            roles[key].add(role)
            # A port's access is in the port's OWN plane. A coater drop sits one
            # level up, and looking for its free neighbour at level 0 finds the
            # lane belts underneath it and calls the port boxed in.
            level[key] = max(level.get(key, 0), port.z)

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
            for c in (
                (key[0] + dx, key[1] + dy, level.get(key, 0)) for dx, dy in _STEPS
            )
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
    paths: Mapping[int, Sequence[Cell]],
    belt_id: int,
    belt_model: int,
    src_group: Mapping[int, tuple[int, ...]] | None = None,
    dst_group: Mapping[int, tuple[int, ...]] | None = None,
) -> tuple[int, ...]:
    """Turn reserved cells into real belts, forward-linked source to sink.

    Returns the indices of routed nets that could not be linked at commit time.

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

    THE BELTS ALL GO DOWN BEFORE ANY TAP IS TAKEN, and that ordering is the
    whole reason this is two loops rather than one.  A junction's collider
    reaches a tile further than the tile it shares, so whether a site is legal
    depends on what stands beside it -- and walking the nets once, staking and
    tapping each in turn, made a splitter for net A before net B's belts existed
    to be seen.  A site test in that order cannot be right in principle: it is
    asked a question whose answer has not been decided yet.  Staking first makes
    ``_tap_source``'s test a question about a finished arrangement.
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
    unlinked: list[int] = []
    laid: dict[int, list[int]] = {}
    for i, path in paths.items():
        net = nets[i]
        indices: list[int] = []
        ok = True
        altitudes = _altitude_profile(path, ramped=canvas.ramped)
        if altitudes is None:
            unlinked += 1
            continue
        for (x, y, lvl), z in zip(path, altitudes, strict=True):
            if not canvas.free((x, y, lvl)) or not canvas.free_world(x, y, z):
                ok = False
                break
            indices.append(
                canvas.add(
                    PlacedBuilding(
                        item_id=belt_id,
                        model_index=belt_model,
                        x=x,
                        y=y,
                        z=z,
                        width=1,
                        height=1,
                        carries_item=net.item,
                    ),
                    level=lvl,
                )
            )
        if not ok or not indices:
            unlinked.append(i)
            continue
        for a, b in zip(indices, indices[1:], strict=False):
            canvas.buildings[a] = _relink(canvas.buildings[a], output_obj=b)
        laid[i] = indices

    # WHO FEEDS WHOM, now that every belt exists.  `into` is the reverse of
    # `output_obj`, which the junction site test needs to walk a run UPSTREAM;
    # it is built once here rather than per tap because a placement can hold
    # tens of thousands of buildings and a pack takes hundreds of taps.
    into: dict[int, list[int]] = defaultdict(list)
    for idx, built in enumerate(canvas.buildings):
        if built.output_obj is not None:
            into[built.output_obj].append(idx)

    for i, indices in laid.items():
        net = nets[i]
        kin = {
            cell
            for s in (src_group or {}).get(i, ())
            for cell in paths.get(s, ())
        }
        feeder = _source_for(canvas, indices[0], net, set(indices), kin)
        if feeder is None:
            unlinked.append(i)
            continue
        excused = _run_cells(canvas, into, feeder) | _run_cells(
            canvas, into, indices[0]
        )
        if not _tap_source(
            canvas, feeder, indices[0], belt_id, belt_model, excused
        ):
            unlinked.append(i)
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
            unlinked.append(i)
            continue
        canvas.buildings[indices[-1]] = _relink(
            canvas.buildings[indices[-1]], output_obj=sink
        )
    return tuple(unlinked)


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
    if _legal_link(
        src.x, src.y, src.z, head.x, head.y, head.z, ramped=canvas.ramped
    ):
        return net.src.belt
    # `head` rests on a level, so it has a lattice cell; a ramp tile would
    # not, and `_lattice_cell` says so rather than rounding it onto one.
    at = _lattice_cell(head.x, head.y, head.z)
    for dx, dy in _STEPS:
        if at is None:
            break
        cell = (at[0] + dx, at[1] + dy, at[2])
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
    if _legal_link(
        tail.x, tail.y, tail.z, dst.x, dst.y, dst.z, ramped=canvas.ramped
    ):
        return net.dst.belt
    # `tail` rests on a level, so it has a lattice cell; a ramp tile would
    # not, and `_lattice_cell` says so rather than rounding it onto one.
    at = _lattice_cell(tail.x, tail.y, tail.z)
    for dx, dy in _STEPS:
        if at is None:
            break
        cell = (at[0] + dx, at[1] + dy, at[2])
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


def _run_cells(
    canvas: _Canvas,
    into: Mapping[int, list[int]],
    start: int,
    hops: int = 3,
) -> set[tuple[int, int, int]]:
    """Routing cells of the belts within ``hops`` links of ``start``, both ways.

    The set the game excuses around a junction, in cells rather than in indices.
    ``colliders.belt_chain_excuses`` walks a belt's own run three hops in each
    direction and lets off anything it reaches, and a junction is one of those
    hops -- so a belt this close to the tap is a belt the paste will not convict,
    however near it stands.

    Followed through SPLITTERS as well as belts, for the same reason
    ``_leads_back`` does: a junction carries no ``output_obj`` of its own, so a
    walk that stops at one misses exactly the run a tap creates.  ``into`` is
    the reverse of ``output_obj``, which the caller builds once per commit.

    Deliberately generous.  Over-excusing here can only leave a site the game
    would refuse looking clear, which ``validate.certify`` still catches and
    which costs the sweep a candidate; under-excusing would refuse taps the game
    is perfectly happy with, which costs it a route.
    """
    seen = {start}
    frontier = [start]
    for _ in range(hops):
        nxt: list[int] = []
        for idx in frontier:
            b = canvas.buildings[idx]
            onward = b.output_obj
            if (
                onward is not None
                and 0 <= onward < len(canvas.buildings)
                and onward not in seen
            ):
                seen.add(onward)
                nxt.append(onward)
            for j in into.get(idx, ()):
                if j not in seen:
                    seen.add(j)
                    nxt.append(j)
        frontier = nxt
    out: set[tuple[int, int, int]] = set()
    for idx in seen:
        b = canvas.buildings[idx]
        # A ramp tile rests between levels and holds no single lattice cell, so
        # both are excused rather than one guessed at.
        out.add((b.x, b.y, math.floor(b.z)))
        out.add((b.x, b.y, math.ceil(b.z)))
    return out


def _belt_keepout_clear(
    canvas: _Canvas,
    x: int,
    y: int,
    level: int,
    excused: Set[tuple[int, int, int]],
) -> bool:
    """Would a junction here stand beside a belt the paste would not excuse?

    The commit-time twin of :func:`_junction_belt_clear`, asked of real
    buildings rather than of staked paths.  ``excused`` is the junction's own
    run, from :func:`_run_cells`.
    """
    for cell in junction.keepout_cells(x, y, level):
        if cell in excused:
            continue
        who = canvas.blocked.get(cell)
        if who is None or not 0 <= who < len(canvas.buildings):
            continue
        if catalog.is_belt(canvas.buildings[who].item_id):
            return False
    return True


def _tap_source(
    canvas: _Canvas,
    belt_idx: int,
    branch: int,
    belt_id: int,
    belt_model: int,
    excused: Set[tuple[int, int, int]] = frozenset(),
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
        # A junction's collider reaches further than the tile it shares, so a
        # site beside a machine is one the game refuses. The router has other
        # tiles; refusing here costs a tap, not a build.
        if not junction.site_is_clear(canvas.buildings, b.x, b.y):
            return False
        # And the same collider reaches a tile of BELT, which is the half this
        # could not ask until every belt was staked first -- see `_commit_paths`.
        # `_merge_frontier` steers the router away from these sites so that this
        # is the last word rather than the only one; when it does fire, the net
        # counts as unrouted and the sweep tries another pack, which is what it
        # does for every other kind of routing failure.
        level = math.floor(b.z)
        if not _belt_keepout_clear(canvas, b.x, b.y, level, excused):
            return False
        junction_idx = canvas.add(
            junction.make_splitter(b.x, b.y, b.z, carries_item=b.carries_item)
        )
        # Nothing routed later may take the collider's room either. The passes
        # after this one -- external input runs, coater spurs, the power lattice
        # -- all ask `canvas.free`, and until now none of them knew a junction
        # was there at all: it is belt-integrated and reports no occupied tile.
        canvas.guard.update(junction.keepout_cells(b.x, b.y, level))
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
    if attached >= rules.SPLITTER_MAX_PORTS:
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
    nets: Sequence[_Net],
    belt_id: int,
    belt_model: int,
    core: tuple[int, int, int, int],
    deadline: float | None = None,
    budget: dict[str, int] | None = None,
) -> DetailedRouteResult:
    """Run every outside input from the block edge to the lane that wants it.

    A lane the deadline or budget ran out on is a structured unknown, never a
    placement missing an entry run.

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
    # The fallback search may travel ALONG the entry ring, which the straight
    # runs already use; a cell on the outermost ring cannot wall anything in,
    # because outward of it is ground no pass can reach.
    astar_bounds = _grow(core, _ENTRY_RING)
    wanted = {net.dst.belt: net for net in nets}
    ordered = list(wanted.items())
    starts = list(
        dict.fromkeys(
            cell
            for net in nets
            for cell in net.boundary_goals
            if canvas.free(cell)
        )
    )
    history: dict[Cell, float] = defaultdict(float)
    if budget is None:
        budget = {"left": _ROUTING_BUDGET}
    routed: list[NetId] = []
    failures: list[NetFailure] = []
    expansions = 0

    def net_id(net: _Net) -> NetId:
        if net.net_id is None:
            raise ValueError("detailed routing requires stable net IDs")
        return net.net_id

    def failed(net: _Net, search: _PathSearchResult) -> NetFailure:
        return NetFailure(
            net_id(net),
            search.kind or RouteFailureKind.DYNAMIC_ACCESS,
            search.wall,
            (),
            search.expansions,
        )

    if not starts:
        failures.extend(
            NetFailure(
                net_id(net), RouteFailureKind.DYNAMIC_ACCESS, (), (), 0
            )
            for _belt, net in ordered
        )
    else:
        for done, (_belt, net) in enumerate(ordered):
            if _expired(deadline):
                failures.extend(
                    NetFailure(
                        net_id(pending), RouteFailureKind.BUDGET, (), (), 0
                    )
                    for _pending_belt, pending in ordered[done:]
                )
                break
            port = net.dst
            item = net.item
            # Spend exactly one of this lane's access reservations and leave the
            # rest held. A shared external/internal lane therefore keeps one
            # access cell for the later internal net.
            mine = next(
                (
                    cell
                    for cell, key in canvas.reserved.items()
                    if key == (port.x, port.y)
                ),
                None,
            )
            if mine is not None:
                del canvas.reserved[mine]

            # Straight runs keep parallel input lanes independent. Only a
            # blocked straight run pays for A* along the entry ring.
            path: Sequence[Cell] | None = _straight_to_edge(canvas, port, bounds)
            if path is None:
                goals = {
                    (port.x + dx, port.y + dy, 0)
                    for dx, dy in _STEPS
                    if canvas.free((port.x + dx, port.y + dy, 0))
                }
                if not goals:
                    failures.append(
                        NetFailure(
                            net_id(net),
                            RouteFailureKind.DYNAMIC_ACCESS,
                            (),
                            (),
                            0,
                        )
                    )
                    continue
                live = [cell for cell in starts if canvas.free(cell)]
                searched = _astar(
                    canvas,
                    live,
                    goals,
                    history,
                    1.0,
                    astar_bounds,
                    budget,
                    deadline,
                )
                expansions += searched.expansions
                path = searched.path
                if path is None:
                    failures.append(failed(net, searched))
                    continue

            profile = _altitude_profile(path, ramped=canvas.ramped)
            if profile is None:
                failures.append(
                    NetFailure(
                        net_id(net), RouteFailureKind.COMMIT_LINK, (), (), 0
                    )
                )
                continue
            indices: list[int] = []
            for (x, y, lvl), z in zip(path, profile, strict=True):
                if not canvas.free((x, y, lvl)) or not canvas.free_world(x, y, z):
                    break
                indices.append(
                    canvas.add(
                        PlacedBuilding(
                            item_id=belt_id,
                            model_index=belt_model,
                            x=x,
                            y=y,
                            z=z,
                            width=1,
                            height=1,
                            carries_item=item,
                        ),
                        level=lvl,
                    )
                )
            if not indices:
                failures.append(
                    NetFailure(
                        net_id(net), RouteFailureKind.COMMIT_LINK, (), (), 0
                    )
                )
                continue
            for a, b in zip(indices, indices[1:], strict=False):
                canvas.buildings[a] = _relink(canvas.buildings[a], output_obj=b)
            canvas.buildings[indices[-1]] = _relink(
                canvas.buildings[indices[-1]], output_obj=port.belt
            )
            routed.append(net_id(net))

    status = (
        DetailedRouteStatus.BUDGET
        if any(failure.kind is RouteFailureKind.BUDGET for failure in failures)
        else (
            DetailedRouteStatus.STRANDED
            if failures
            else DetailedRouteStatus.ROUTED
        )
    )
    return DetailedRouteResult(
        status=status,
        routed=tuple(routed),
        failures=tuple(failures),
        iterations=0,
        expansions=expansions,
    )


class _Unseatable(NoValidLayout):
    """A sprayed lane could not be given a Spray Coater, so this pack is not one.

    :func:`_place_coaters` used to ``continue`` past each of these -- a lane with
    no port, a lane too short to offer a straight seat, a drop cell already
    taken -- and the pack went on to route, validate and ship with one fewer
    coater than the spec asked for.  Nothing downstream noticed:
    ``prolif.coaters_are_supplied`` iterates the coaters that exist, and a
    coater that was never placed is not one of them.  The blueprint pastes, the
    machines run, and every recipe on that lane quietly runs unproliferated --
    the same silent class as a coater at the tail of its own lane and as two
    sorters on one machine slot, both of which shipped.

    A :class:`NoValidLayout` rather than a bare exception because that is what
    it is: this height cannot build what the spec asked for.  The sweep discards
    it and tries the next, exactly as it does for :class:`_Unpowerable`; if no
    height can seat the coaters the spec is refused, which is the honest answer
    and not the quiet one.
    """


class _Unpowerable(Exception):
    """This pack cannot be powered, so it is not a feasible pack.

    Raised by :func:`_power_plan` before anything routes, and by
    :func:`_place_power` if a held site was taken anyway.  The sweep discards
    the height and moves on, exactly as it does for a pack that cannot be
    wired: coverage is not a nice-to-have that a build can ship without, so a
    placement that cannot have it is not a placement.
    """


def _power_plan(canvas: _Canvas, core: tuple[int, int, int, int]) -> list[tuple[int, int]]:
    """Where every tower goes, decided BEFORE anything routes.

    Raises :class:`_Unpowerable` when this pack cannot be powered at all, which
    is a property of the PACK and makes it infeasible.  Otherwise it returns a
    placement that covers every powered tile and is connected, and the cells are
    held in ``canvas.keep_out`` so the router paths around them.

    WHY THIS IS A PLAN AND NOT A LATTICE WITH A REPAIR BEHIND IT
    ------------------------------------------------------------
    This used to lay a fixed square lattice of spacing ``TOWER_SPACING``, drag
    each point to the nearest free cell, and then, after routing, hunt for
    somewhere to stand for every tile the result had left dark.  That last pass
    is the problem, and it cannot be fixed where it stands: a dark tile is
    repairable only if some cell of its radius is still free, and by then the
    packing and the routing have both had the ground.  When they have taken all
    of it the repair searches its 346 cells, finds none, and silently gives up
    -- the placement then fails ``power.coverage`` and the whole candidate is
    thrown away, having paid for a pack AND a full routing pass first.

    A solution that cannot be powered is not feasible, so the question is asked
    HERE, where the answer is still cheap and still true:

    * **Feasibility is a test, not a hope.**  A cover exists if and only if
      every powered tile has at least one free cell within the radius.  That is
      checked directly, first, and a pack that fails it is refused before a
      single belt is routed.
    * **Greedy attains it whenever it holds.**  Every round places a tower on
      the free cell that covers the most still-dark tiles, so every round makes
      progress, and the loop ends only when nothing is dark.  There is no case
      where it stops early with work left over, which is precisely the case the
      repair pass existed to mop up.
    * **Connectivity is built in.**  After the first tower every candidate must
      lie within ``connect_distance`` of one already placed, so the network is
      connected at every step rather than stitched together afterwards.  When
      nothing in range covers anything new, a RELAY is placed -- the in-range
      cell closest to what is still dark.  That is the network walking to the
      far side of the block, not a repair of a network that failed.

    It is also much smaller than the lattice it replaces, which is a density
    win rather than a tidiness one.  A lattice point every nine tiles ignores
    that a tower reaches 10.5 in every direction; covering by need instead of by
    grid measured 75 towers against 350 on ``universe-matrix``
    /free-proliferation, 106 against 407 on its ``no-proliferator``, and 16-27
    against 32-72 across five ``casimir-crystal`` packs.  Every tower deleted is
    a building the player does not paste AND a cell the router gets back.

    The tie-break is deliberate and it points AWAY from the router's corridors:
    among cells that cover equally many dark tiles, the one with the MOST free
    neighbours wins, because a cell in the middle of a wide field can be taken
    without disconnecting anything while a cell in a one-row channel cannot.
    It used to point the other way, which is measured at three corpus cells --
    see the tie-break itself, where the numbers are.
    """
    tower = catalog.building(catalog.TESLA_TOWER_ID)
    reach2 = math.floor((2 * tower.cover_radius) ** 2)
    link2 = math.floor((2 * tower.connect_distance) ** 2)
    core_x0, core_y0, core_x1, core_y1 = core
    # A TOWER MAY STAND OUTSIDE THE CORE. WHAT IT COVERS MAY NOT.
    #
    # Standing ground is the whole canvas, the entry ring included, because on a
    # small dense build the core is packed SOLID -- every cell a machine or a
    # lane -- and a tower restricted to it would have nowhere at all to go. The
    # old lattice was restricted to the core and its repair pass was not
    # (`try_place` never checked), so towers in the ring are what that build was
    # relying on all along, without anybody saying so.
    #
    # It is a second choice, not a free one: the ring is where the external
    # input runs come in, and a tower in one breaks the straight run out to it.
    # So the core is searched first and the ring is reached into only for tiles
    # the core cannot cover -- see `in_core` at the placement loop.
    min_x, min_y, max_x, max_y = canvas.limit or core
    min_x, min_y = min(min_x, core_x0), min(min_y, core_y0)
    max_x, max_y = max(max_x, core_x1), max(max_y, core_y1)
    width, height = max_x - min_x + 1, max_y - min_y + 1
    if core_x1 < core_x0 or core_y1 < core_y0:
        return []

    # Padded so a disc or link stamp near an edge needs no clipping. The stamps
    # reach `link` and are read `reach` further out, so the margin covers both.
    reach = int(tower.cover_radius) + 1
    link = int(tower.connect_distance) + 1
    pad = link + reach + 1
    shape = (width + 2 * pad, height + 2 * pad)

    free = np.zeros(shape, dtype=bool)
    for x in range(min_x, max_x + 1):
        for y in range(min_y, max_y + 1):
            if not canvas.free((x, y, 0)) or (x, y) in canvas.solid:
                continue
            if any((x, y, lvl) in canvas.blocked for lvl in range(LEVELS)):
                continue
            free[x - min_x + pad, y - min_y + pad] = True

    in_core = np.zeros(shape, dtype=bool)
    in_core[
        core_x0 - min_x + pad : core_x1 - min_x + pad + 1,
        core_y0 - min_y + pad : core_y1 - min_y + pad + 1,
    ] = True

    # WHAT HAS TO BE COVERED IS THE CORE, NOT THE BUILDINGS STANDING IN IT.
    #
    # This runs BEFORE routing, and routing is what places the sorters and the
    # spray coaters -- both of which draw power. Covering the buildings that
    # exist right now leaves every one of those dark, and the placement then
    # fails `power.coverage` at certify having looked perfectly correct here.
    # Measured, and it is not a corner case: covering only the machines refused
    # `universe-matrix` at free-proliferation and max-proliferation on every
    # height, in three audits out of four.
    #
    # The core is the region powered buildings are allowed to occupy -- the
    # entry ring outside it holds belts, which are unpowered -- so covering all
    # of it is the condition that does not depend on what has been placed yet.
    # It is still need-based rather than a grid: a tower covers a 346-tile disc
    # and the core is covered by discs, not by a point every nine tiles.
    dark = in_core.copy()
    for b in canvas.buildings:
        if catalog.is_belt(b.item_id) or b.item_id == catalog.TESLA_TOWER_ID:
            continue
        for tx, ty, _ in b.tiles():
            gx, gy = tx - min_x + pad, ty - min_y + pad
            # A powered building the core does not contain still has to be
            # covered -- refusing here would call a build unpowerable for
            # standing somewhere the core happens not to reach.
            if 0 <= gx < shape[0] and 0 <= gy < shape[1]:
                dark[gx, gy] = True

    #: Offsets a tower covers, and the offsets that can link to one. Both are
    #: DOUBLED-integer comparisons -- see :func:`_place_power` for why that is
    #: exact rather than a tolerance.
    disc = [
        (dx, dy)
        for dx in range(-reach, reach + 1)
        for dy in range(-reach, reach + 1)
        if (2 * dx) ** 2 + (2 * dy) ** 2 <= reach2
    ]
    disc_stamp = np.zeros((2 * reach + 1, 2 * reach + 1), dtype=bool)
    for dx, dy in disc:
        disc_stamp[dx + reach, dy + reach] = True
    link_stamp = np.zeros((2 * link + 1, 2 * link + 1), dtype=bool)
    for dx in range(-link, link + 1):
        for dy in range(-link, link + 1):
            if (2 * dx) ** 2 + (2 * dy) ** 2 <= link2:
                link_stamp[dx + link, dy + link] = True

    # WHERE A TOWER MAY NOT STAND BECAUSE ANOTHER TOWER IS ALREADY THERE.
    #
    # `EBuildCondition.PowerTooClose`: two power nodes closer than 3.5 WORLD
    # units are refused by the paste, and a Tesla Tower has no build collider,
    # so nothing else in this file or in the validator's geometry could see it.
    # A blueprint this greedy produced was pasted into a real game and had two
    # of its six towers reddened -- `tests/fixtures/ours/power-too-close-
    # freeform.txt`, and `dsp.rules.power_node_keepout_offsets` is the rule.
    #
    # Consulted, not restated: the offsets come from the rule, so the greedy and
    # `validate.game.power_too_close` cannot disagree about the radius.  On the
    # ground it is 21 cells -- every `dx**2 + dy**2 <= 7` -- against a coverage
    # disc of 346, so the greedy loses about one site in sixteen of the ground
    # it could otherwise stand on, and only next to a tower it has just placed.
    spacing = [
        (dx, dy)
        for dx, dy, dz in rules.power_node_keepout_offsets(tower.power_node, tower.power_node)
        if dz == 0
    ]
    spacing_reach = max(max(abs(dx), abs(dy)) for dx, dy in spacing)
    spacing_stamp = np.zeros((2 * spacing_reach + 1, 2 * spacing_reach + 1), dtype=bool)
    for dx, dy in spacing:
        spacing_stamp[dx + spacing_reach, dy + spacing_reach] = True
    if spacing_reach > pad:  # pragma: no cover - the pad is link + reach + 1
        raise AssertionError("the tower-spacing stamp does not fit inside the pad")

    # AND THE POWER NODES THAT ARE ALREADY HERE, which are not all towers.  A Ray
    # Receiver and an Energy Exchanger are mode-driven MACHINES that join the
    # network and are subject to the same rule; the pack has already placed them
    # and `free` knows only that their own tiles are taken.  Their spacing is
    # keyed on their own flags, so a node on a wider tier keeps its own distance.
    for b in canvas.buildings:
        try:
            peer = catalog.building(b.item_id).power_node
        except KeyError:
            continue
        if not peer.is_power_node:
            continue
        cx = b.x + b.width // 2 - min_x + pad
        cy = b.y + b.height // 2 - min_y + pad
        for dx, dy, dz in rules.power_node_keepout_offsets(peer, tower.power_node):
            if dz:
                continue
            gx, gy = cx + dx, cy + dy
            if 0 <= gx < shape[0] and 0 <= gy < shape[1]:
                free[gx, gy] = False

    def spread(mask: np.ndarray) -> np.ndarray:
        """Cells within tower reach of anything in ``mask``."""
        out = np.zeros(shape, dtype=bool)
        for dx, dy in disc:
            out[
                max(0, dx) : shape[0] + min(0, dx), max(0, dy) : shape[1] + min(0, dy)
            ] |= mask[
                max(0, -dx) : shape[0] + min(0, -dx), max(0, -dy) : shape[1] + min(0, -dy)
            ]
        return out

    # FEASIBILITY, asked first and answered exactly: a powered tile with no free
    # cell in reach can never be covered, by this or any other placement.
    orphans = int(np.count_nonzero(dark & ~spread(free)))
    if orphans:
        raise _Unpowerable(f"{orphans} powered tiles have no free cell within tower reach")

    # How many free neighbours each cell has, for the tie-break. Taken once, on
    # the ground as packed: a tie-break does not need to track its own effects.
    openness = np.zeros(shape, dtype=np.int32)
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        openness[
            max(0, dx) : shape[0] + min(0, dx), max(0, dy) : shape[1] + min(0, dy)
        ] += free[
            max(0, -dx) : shape[0] + min(0, -dx), max(0, -dy) : shape[1] + min(0, -dy)
        ]

    remaining = dark.copy()
    # `score` is maintained incrementally. Rebuilding it every round is the same
    # answer and was measured at 0.9s on `universe-matrix`, which is real money
    # against a 15s deadline; only the cells within two radii of a new tower can
    # change, so only those are touched.
    score = np.zeros(shape, dtype=np.int32)
    for dx, dy in disc:
        score[
            max(0, dx) : shape[0] + min(0, dx), max(0, dy) : shape[1] + min(0, dy)
        ] += remaining[
            max(0, -dx) : shape[0] + min(0, -dx), max(0, -dy) : shape[1] + min(0, -dy)
        ]

    linked = np.zeros(shape, dtype=bool)
    sites: list[tuple[int, int]] = []
    # A cap, not a schedule: every round consumes one free cell, so a placement
    # that has not finished by then is not converging and says so.
    for _ in range(int(np.count_nonzero(free)) + 1):
        if not remaining.any():
            break
        # WHERE a tower stands costs the router, because a tower cell is held in
        # `keep_out` for the whole of routing.  Among cells that cover equally
        # many dark tiles, take the one with the MOST free neighbours.
        #
        # THIS TIE-BREAK POINTED THE WRONG WAY AND IT COST THREE CORPUS CELLS.
        #
        # It used to be `4 - openness`, on the argument that coverage alone
        # likes "open ground, and open ground is exactly the corridor a belt
        # wanted".  That sentence conflates two opposite things.  The scarce
        # routing resource here is the ONE-ROW CHANNEL on a strip's south face
        # -- a strip's machine band denies the bottom three levels, so that row
        # is nearly the only way past it (see `_sweep`, and `WEST_CHANNEL`).
        # Not because a machine is solid to the sky -- it is not, see
        # `_crossing_ban_levels` -- but because the lowest level that clears a
        # production machine's collider is 3.  A cell in such a
        # channel has free neighbours east and west and blocked ones north and
        # south: `openness == 2`.  A cell in the middle of a wide field has
        # `openness == 4` and cutting it out disconnects nothing.  Preferring
        # enclosure therefore aimed the towers straight at the channels, and
        # every cell it plugged was a passage with no alternative.
        #
        # Measured on the SAME pack -- `universe-matrix`/free-proliferation,
        # h=164 w=177, 133 nets, a 15s ceiling:
        #
        #   master's lattice, 351 towers held   routed 133/133 in  7.0s
        #   `4 - openness`,   176 towers held   routed   0/133, wall at 14.2s
        #   `openness`,       172 towers held   routed 133/133 in  8.0s
        #
        # Half as many held cells routing twice as slowly is not congestion, it
        # is placement: the greedy was choosing the cells the router could least
        # afford, and the lattice's virtue was never its uniformity but that a
        # blind 9-grid plugs a channel only by accident.
        #
        # Corpus at `--budget 4 --jobs 16`, clean cells out of 72, one figure
        # per audit run, because these are nondeterministic:
        #
        #   master (lattice + repair)  n=12  mean 70.75
        #     69,70,70,70,70,70,71,71,72,72,72,72
        #   `4 - openness`             n=4   mean 67.75
        #     67,67,68,69
        #   `openness`                 n=17  mean 71.0
        #     70,70,70,70,70,71,71,71,71,71,71,71,72,72,72,72,72
        #
        # `INVALID 0` in every one of those runs, on every variant, and no
        # `power.coverage` refusal anywhere: the tie-break moves which cells the
        # router has to path around, never whether the block ends up powered.
        #
        # THREE OTHER DIRECTIONS WERE BUILT AND MEASURED AND NONE BEATS IT.
        # All of them fix the regression -- the sign was the whole of it -- and
        # none is worth the extra code:
        #
        #   no tie-break at all (`argmax` falls to the lowest index)  n=3   70.67
        #   penalise only 1-wide channel cells (free on exactly one
        #     axis, both sides -- the cells whose removal cuts a run)  n=8   70.5
        #   penalise local articulation points (8-ring crossing
        #     number >= 2, so bends as well as straight runs)          n=4   70.0
        #   ...and that same articulation test with `openness` under
        #     it as a second key                                       n=13  71.0
        #
        # The last one ties `openness` exactly and needs eight shifted masks and
        # a crossing number to do it, so the plain neighbour count stays.
        #
        # PREFERRING enclosure OUTRIGHT was measured too, and is worse still. As
        # tiers on `openness <= 1, 2, 4`, taking the best-covering cell in the
        # tightest non-empty tier, the corpus went 67/67/68/67 to 66/63/64: it
        # is the wrong direction pushed harder, and it also costs towers, since
        # an enclosed cell covers fewer tiles and so more of them are needed.
        key = score * 5 + openness
        reachable_now = free if not sites else (free & linked)
        # The core first, and the ring only for what the core cannot reach.
        # Widening is per ROUND rather than once and for all, so a build that
        # needs one ring cell takes one, not a placement's worth.
        gx = gy = -1
        for allowed in (reachable_now & in_core, reachable_now):
            flat = int(np.where(allowed, key, -1).argmax())
            cx, cy = divmod(flat, shape[1])
            if allowed[cx, cy] and score[cx, cy] > 0:
                gx, gy = cx, cy
                break
        if gx < 0:
            # Nothing in range covers anything new, so walk: the in-range free
            # cell closest to a tile still dark.
            cand = np.argwhere(reachable_now)
            if not len(cand):
                raise _Unpowerable("the tower network cannot reach the rest of the block")
            target = np.argwhere(remaining)[0]
            gx, gy = cand[np.argmin(((cand - target) ** 2).sum(axis=1))].tolist()
        sites.append((gx - pad + min_x, gy - pad + min_y))
        # The cell itself AND every cell inside the paste's power-node spacing
        # rule.  Marking only the cell is what shipped a blueprint the game
        # refused; the halo is what makes this greedy incapable of producing one.
        free[
            gx - spacing_reach : gx + spacing_reach + 1,
            gy - spacing_reach : gy + spacing_reach + 1,
        ] &= ~spacing_stamp
        linked[
            gx - link : gx + link + 1, gy - link : gy + link + 1
        ] |= link_stamp
        win = (slice(gx - reach, gx + reach + 1), slice(gy - reach, gy + reach + 1))
        newly = remaining[win] & disc_stamp
        if newly.any():
            remaining[win] &= ~disc_stamp
            covered = np.zeros(shape, dtype=bool)
            covered[win] = newly
            lo_x, hi_x = gx - 2 * reach, gx + 2 * reach + 1
            lo_y, hi_y = gy - 2 * reach, gy + 2 * reach + 1
            for dx, dy in disc:
                score[lo_x:hi_x, lo_y:hi_y] -= covered[
                    lo_x + dx : hi_x + dx, lo_y + dy : hi_y + dy
                ]
    else:
        raise _Unpowerable("tower placement did not converge")

    for site in sites:
        canvas.keep_out.add(site)
    return sites


def _place_power(canvas: _Canvas, sites: Sequence[tuple[int, int]]) -> int:
    """Stand a tower on every cell :func:`_power_plan` chose.

    There is no repair here any more, and that is the point rather than a
    simplification.  Coverage and connectivity were decided before routing, on
    ground that was still free, and the cells have been held in
    ``canvas.keep_out`` ever since; a pass that went looking for somewhere to
    stand AFTER the router had the ground was working with whatever was left,
    which on a dense block is nothing.

    COORDINATES ARE DOUBLED INTEGERS WHEREVER A DISTANCE IS TESTED.

    A tower's centre falls on a half tile, which is why this used ``Fraction``.
    It is the same predicate written twice the size: multiply both sides of
    ``dx**2 + dy**2 <= r**2`` by four and every term is an integer, so the
    comparison is ``dx2**2 + dy2**2 <= floor((2r)**2)`` -- exact, because the
    left side cannot land between ``floor((2r)**2)`` and ``(2r)**2``.  This is
    not a tolerance and there is no float anywhere near it.

    A site that is no longer free is a ``keep_out`` that did not hold, which is
    a bug in the reservation rather than a tile to be covered from somewhere
    else, so it takes the pack down instead of being quietly skipped.
    """
    if not canvas.buildings:
        return 0
    tower = catalog.building(catalog.TESLA_TOWER_ID)
    placed = 0
    for cx, cy in sites:
        if not canvas.free((cx, cy, 0)) or (cx, cy) in canvas.solid:
            raise _Unpowerable(f"planned tower site {(cx, cy)} was taken during routing")
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
        placed += 1
    return placed


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


def _prepare_routing_problem(
    spec: BuildSpec,
    strips: list[Strip],
    pack: _Pack,
    *,
    power: bool,
    _reserve_ports: bool = True,
) -> _PreparedRoutingProblem:
    """Build immutable exact geometry shared by both routing engines."""
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
    strip_of_belt: dict[int, int] = {}
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
            sprayed=frozenset(spec.spray_lanes),
        )
        sorters += placed
        strip_in_ports.append(ins)
        for port in (*ins.values(), *outs.values()):
            strip_of_belt[port.belt] = i
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
    # Every sorter already standing, as the PASTE will test it.  Built once and
    # extended by each bridge that lands: `_bridge` is asked once per lane pair
    # and rebuilding this inside it is quadratic in the sorter count, which on a
    # stress spec is thousands.
    standing = slots.sorter_seat_boxes(canvas.buildings)
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
                    canvas, port, sink, rates, item, standing
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
        net_ports = {
            (p.x, p.y)
            for n in nets
            for p in (n.src, n.dst)
            if p is not None
        }
        shared_feed = {
            (port.x, port.y)
            for ports in strip_in_ports
            for item, port in ports.items()
            if item in spec.external_inputs
        } & net_ports
        _reserve_port_access(canvas, nets, twice=shared_feed)

    if _reserve_ports:
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
    for coater in coater_list:
        strip_of_belt[coater.drop] = next(
            i
            for i, ports in enumerate(strip_in_ports)
            if any(
                port.y == coater.y and port.x1 + 1 == coater.x
                for port in ports.values()
            )
        )

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
    internal_net_count = len(nets)
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
    if _reserve_ports:
        hold_ports()

    # Power is decided AFTER the ports have claimed their ground, and before
    # anything routes.
    #
    # Both halves of that matter and they used to be one. Power claimed first,
    # on the argument that it is otherwise handed whatever a dense block has
    # left, which is nothing -- that argument is right and the claim stays ahead
    # of the router. But it also ran ahead of the SECOND `hold_ports`, which is
    # the one that sees the coater drops and the proliferator entry, and
    # `_reserve_port_access` clears and re-stakes every reservation when it
    # runs. So a tower cell could sit on a port's one open side and the re-stake
    # would find it gone.
    #
    # Measured on `casimir-crystal/max-proliferation`: twelve ports boxed in,
    # every one of them by a machine, two lane belts and a tower keep-out cell.
    # The two claims are not symmetric -- a tower has a whole radius of ground
    # to stand in and `_power_plan` picks from all of it, while a port with no
    # free neighbour has no second option at all and takes its net down with it.
    #
    # `_power_plan` RAISES when the pack cannot be powered, which is the whole
    # of the change: an unpowerable pack is infeasible, so it is refused here --
    # before a single belt is routed -- rather than emerging as a coverage
    # failure once the pack and the routing have both spent the ground.
    power_sites = _power_plan(canvas, core) if power else []

    # External-input nets retain the existing lane-deduplication and item
    # precedence, while exposing their shared boundary cells immutably.
    wanted: dict[int, tuple[_Port, int]] = {}
    carried: dict[int, str] = {}
    for strip_index, ports in enumerate(strip_in_ports):
        for item, port in sorted(ports.items()):
            if item in spec.external_inputs:
                wanted.setdefault(port.belt, (port, strip_index))
        for item, port in sorted(ports.items(), reverse=True):
            if item in spec.external_inputs:
                carried[port.belt] = item

    min_x, min_y, max_x, max_y = _grow(core, _ENTRY_RING - 1)
    boundary = tuple(
        cell
        for cell in (
            [
                (x, y, 0)
                for x in range(min_x - 1, max_x + 2)
                for y in (min_y - 1, max_y + 1)
            ]
            + [
                (x, y, 0)
                for y in range(min_y, max_y + 1)
                for x in (min_x - 1, max_x + 1)
            ]
        )
        if canvas.free(cell)
    )

    tagged_nets = [
        (
            net,
            NetRole.INTERNAL if i < internal_net_count else NetRole.PROLIFERATOR,
        )
        for i, net in enumerate(nets)
    ]
    tagged_nets.extend(
        (
            _Net(src=None, dst=port, item=carried[belt]),
            NetRole.EXTERNAL,
        )
        for belt, (port, _strip_index) in wanted.items()
    )

    ordinals: dict[tuple[int | None, int | None, str, NetRole], int] = (
        defaultdict(int)
    )
    prepared_nets: list[_PreparedNet] = []
    for net, role in tagged_nets:
        source_strip = (
            strip_of_belt.get(net.src.belt) if net.src is not None else None
        )
        destination_strip = strip_of_belt.get(net.dst.belt)
        identity = (source_strip, destination_strip, net.item, role)
        net_id = NetId(*identity, ordinal=ordinals[identity])
        ordinals[identity] += 1
        prepared_nets.append(
            _PreparedNet(
                net_id=net_id,
                src=_prepare_port(net.src) if net.src is not None else None,
                dst=_prepare_port(net.dst),
                item=net.item,
                boundary_goals=boundary if role is NetRole.EXTERNAL else (),
            )
        )

    return _PreparedRoutingProblem(
        building_templates=tuple(deepcopy(canvas.buildings)),
        blocked=tuple(sorted(canvas.blocked.items())),
        solid=frozenset(canvas.solid),
        reserved=tuple(sorted(canvas.reserved.items())),
        keep_out=frozenset(canvas.keep_out),
        nets=tuple(prepared_nets),
        core=core,
        route_bounds=route_bounds,
        limit=canvas.limit,
        power_sites=tuple(power_sites),
        sorters=sorters,
        coaters=coaters,
        direct_inserts=direct_placed,
    )


@dataclass(slots=True)
class _BuildResult:
    placement: Placement
    routing: DetailedRouteResult
    towers: tuple[PlacedBuilding, ...]


def _build(
    spec: BuildSpec,
    strips: list[Strip],
    pack: _Pack,
    *,
    power: bool,
    route: bool,
    deadline: float | None = None,
    budget: dict[str, int] | None = None,
) -> _BuildResult:
    """Emit, wire and power one pack from a fresh prepared workspace."""
    prepared = _prepare_routing_problem(
        spec,
        strips,
        pack,
        power=power,
        _reserve_ports=route,
    )
    workspace = prepared.new_workspace()
    canvas = workspace.canvas
    belt_id = BELT_ITEM_IDS.get(spec.belt_item_id, 2001)
    belt_model = catalog.building(belt_id).model_index
    external_nets = [
        net
        for net in workspace.nets
        if net.net_id is not None and net.net_id.role is NetRole.EXTERNAL
    ]
    route_nets = [
        net
        for net in workspace.nets
        if net.net_id is not None and net.net_id.role is not NetRole.EXTERNAL
    ]

    empty_routing = DetailedRouteResult(
        DetailedRouteStatus.ROUTED, (), (), 0, 0
    )
    external_routing = empty_routing
    internal_routing = empty_routing

    # External inputs retain first claim on routing space.
    if route:
        external_routing = _route_external_inputs(
            canvas,
            external_nets,
            belt_id,
            belt_model,
            prepared.core,
            deadline,
            budget,
        )

    if route and route_nets:
        internal_routing = _route_all(
            canvas,
            route_nets,
            belt_id,
            belt_model,
            prepared.route_bounds,
            deadline,
            budget,
        )

    failures = external_routing.failures + internal_routing.failures
    routing_status = (
        DetailedRouteStatus.BUDGET
        if (
            external_routing.status is DetailedRouteStatus.BUDGET
            or internal_routing.status is DetailedRouteStatus.BUDGET
        )
        else (
            DetailedRouteStatus.STRANDED
            if failures
            else DetailedRouteStatus.ROUTED
        )
    )
    routing = DetailedRouteResult(
        status=routing_status,
        routed=external_routing.routed + internal_routing.routed,
        failures=failures,
        iterations=internal_routing.iterations,
        expansions=external_routing.expansions + internal_routing.expansions,
    )

    # Reservations and tentative markers are attempt-local and are spent before
    # the held power sites become buildings.
    canvas.reserved.clear()
    for cell in [c for c, owner in canvas.blocked.items() if owner == _TENTATIVE]:
        del canvas.blocked[cell]
    canvas.keep_out.clear()
    tower_start = len(canvas.buildings)
    if power and not routing.failed_count:
        _place_power(canvas, prepared.power_sites)
    towers = tuple(canvas.buildings[tower_start:])

    # Slot indices are geometry, so they are derived here once rather than at
    # each of the several places a sorter gets created. Every sorter this
    # strategy emitted before carried a defaulted zero in all four fields, which
    # the game rejects outright.
    #
    # A sorter whose slot cannot be derived is a REFUSAL, not a crash and not a
    # guess. The one case that reaches this today is a Spray Coater: it ships
    # zero slot poses, and `BuildTool_Inserter` will not even let a sorter
    # target a building with none, so the connection this strategy wants does
    # not exist in the game. Refusing says so; emitting an index the game never
    # writes would not.
    try:
        wired = assign_sorter_slots(canvas.buildings)
    except SlotUndetermined as exc:
        raise NoValidLayout(f"a sorter's slot could not be derived: {exc}") from exc

    placement = Placement(
        buildings=wired,
        description=f"flab2bp freeform layout ({spec.label or 'default'})",
        short_desc=spec.label or "flab2bp",
        stats={
            "machines": float(spec.machine_count),
            "strips": float(len(strips)),
            "sorters": float(prepared.sorters),
            "towers": float(len(towers)),
            "spray_coaters": float(prepared.coaters),
            "nets": float(len(route_nets)),
            "routed": float(len(internal_routing.routed)),
            "route_failures": float(routing.failed_count),
            "repair_iterations": float(routing.iterations),
            "belt_tiles": float(
                sum(1 for b in canvas.buildings if catalog.is_belt(b.item_id))
            ),
            "direct_inserts": float(prepared.direct_inserts),
        },
    )
    return _BuildResult(placement, routing, towers)


def _bridge(
    canvas: _Canvas,
    src: _Port,
    dst: _Port,
    rates: dict[str, Fraction],
    item: str,
    standing: list[colliders.Box],
) -> bool:
    """Span two lane ends with one sorter, replacing a whole belt route.

    Returns ``False`` rather than placing an illegal sorter if the packed
    geometry did not actually come out within reach.  The packer's reification
    should guarantee it does, but a sorter that cannot exist would produce a
    blueprint that pastes and then does not run -- the worst failure mode -- so
    this is checked rather than assumed.

    **NOT ANY SHARED COLUMN WILL DO**, and this used to take the westmost one.
    A bridge is a BELT-TO-BELT sorter, so the game grows its collider by
    ``colliders.SORTER_END_EXTENSION`` past BOTH ends -- 0.7 units, more than
    half a tile, at each end -- while a sorter serving a machine grows at one
    end only.  Drop a bridge onto a column where a strip's own sorter already
    meets one of the two lanes and the two boxes intersect, which the game
    refuses with ``EBuildCondition.Collide``: sorter against sorter is the one
    pairing its excusal does not forgive.  That is the defect this argument
    exists for, reported from the game on a blueprint whose bridge landed on the
    same belt tile a smelter's output sorter was already using; see
    ``validate.game.sorter_collide``.

    ``standing`` is that answer prepared: the seated box of every sorter already
    placed, which the caller builds once and this extends.  Every shared column
    is tried, west to east, and the first one whose seated box clears them all
    is the one taken.  When none
    does, ``False`` -- and the caller routes a belt instead, which is the same
    thing it does when the lanes are out of reach.  That is not a fallback: a
    belt route is the general case and a bridge is the optimisation.
    """
    span = dst.y - src.y
    if span < 1 or span > catalog.SORTER_MAX_REACH:
        return False

    tier, _ = _pick_sorter(rates.get(item, Fraction(1)), span, 1)
    for column in range(max(src.x0, dst.x0), min(src.x1, dst.x1) + 1):
        if (column, src.y, 0) not in canvas.blocked:
            continue
        if (column, dst.y, 0) not in canvas.blocked:
            continue
        src_belt = canvas.blocked[column, src.y, 0]
        dst_belt = canvas.blocked[column, dst.y, 0]
        if src_belt == dst_belt:
            continue
        bridge = PlacedBuilding(
            item_id=tier,
            model_index=catalog.building(tier).model_index,
            x=column,
            y=src.y,
            width=1,
            height=1,
            x2=column,
            y2=dst.y,
            z2=Fraction(0),
            yaw=Facing.SOUTH.value,
            yaw2=Facing.SOUTH.value,
            input_obj=src_belt,
            output_obj=dst_belt,
        )
        if not slots.sorter_seat_is_clear(bridge, canvas.buildings, standing):
            continue
        canvas.buildings.append(bridge)
        seat = slots.seated_sorter(bridge, canvas.buildings)
        if seat is not None:
            standing.append(colliders.sorter_box(seat))
        return True
    return False


@dataclass(frozen=True, slots=True)
class _Coater:
    """A placed Spray Coater and the belt tile that will feed it proliferator."""

    coater: int
    #: A one-tile belt in the strip's east margin, the sink of a proliferator net.
    drop: int
    x: int
    y: int


def _coater_seat(canvas: _Canvas, port: _Port) -> tuple[int, int] | None:
    """The lane tile a Spray Coater rides: its SECOND, one east of the head.

    THE SECOND TILE IS THE FIRST ONE WITH A LANE TILE ON BOTH SIDES, and that is
    the whole of why it is not the first.  A sprayed lane is emitted starting one
    column west of the strip (see ``_emit_strip``), so its head is the tile the
    router sinks into and its second tile is column 0 of the strip -- upstream of
    every sorter, exactly where the head used to be, and with a predecessor that
    is a lane tile running east rather than whatever direction the router
    happened to arrive from.

    The predecessor is the half that was missing.  The game reads BOTH ends of
    the belt an addon rides -- ``GetBeltInputBeltPose`` and
    ``GetBeltOutputBeltPose``, each tested against the addon's axis -- and
    refuses the addon when either disagrees.  Six of the twenty coaters on the
    blueprint the user pasted arrived from the south and left to the east on the
    coater's own tile.  See :func:`flab2bp.dsp.rules.addon_ride_is_straight`.

    ``None`` when the lane is too short to offer such a tile, which a caller
    must treat as "no coater here" rather than seating one anyway.

    **A coater sprays what passes THROUGH it, so everything a machine takes has
    to reach the coater first.**  An input lane is emitted west to east and
    linked the same way -- ``_emit_strip`` chains ``indices[k].output_obj =
    indices[k + 1]`` -- and the feeding net sinks into ``lane_idx[row][0]``,
    which is why ``_Port.x`` is the lane's WEST end.  So an input lane flows
    west to east, its head is ``port.x``, and every sorter on it draws from a
    tile at or after the head.

    This used to seat the coater at ``port.x1``, the lane's east end, on the
    reasoning that it is nearest the east margin the drop belt lived in.  That
    is the DOWNSTREAM end: the last belt of the chain, with no ``output_obj``
    and nothing after it.  Measured over five clean proliferated freeform
    placements (``energy-matrix``, ``graphene``, ``plastic``, ``processor``,
    ``magnetic-coil``), **all 12 coaters were the last belt of their own chain
    and all 12 had zero pickups anywhere downstream of them** -- every sorter on
    every sprayed lane drew from a tile the cargo reached before the coater.
    The spray was applied to cargo dead-ended at the end of a belt.  Spine on
    the same five specs seats 0 of 12 at the tail.  So the blueprint pasted, the
    coaters were supplied, ``prolif.coaters_are_supplied`` passed -- and not one
    proliferated recipe would have run proliferated.

    The routing follows the correctness.  At ``Facing.EAST`` the drop belt is
    one tile BEHIND the coater, so a tail seat put the drop *inside* the lane,
    hemmed between the machine band and the neighbouring lanes' coater bans; a
    head seat puts it one tile west of the strip, in the ``WEST_CHANNEL``
    column, which is reserved corridor at level 0 and empty at level 1.  The
    second-tile seat keeps that cell exactly.  The coater has not moved at all
    -- it still rides column 0 of the strip; what moved is the lane's HEAD,
    west into the channel -- so the drop cell is the same tile it always was,
    one level above the new head.
    """
    if len(port.tiles) < 2:
        return None
    b = canvas.buildings[port.tiles[1]]
    return b.x, b.y


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
      belt one tile behind it, which a proliferator net is routed to.
    * **It must sit at the lane's HEAD, where the items arrive.**  See
      :func:`_coater_seat`.

    **A LANE THE SPEC WANTS SPRAYED EITHER GETS A COATER OR THIS RAISES.**  Each
    of the four ways a seat can fail used to be a ``continue``: no port for the
    item, a lane too short to offer a straight seat, no belt on the seat tile, a
    drop cell already taken -- and a fifth, an item no strip carries on a lane,
    which the loop never reaches at all.  Any one of them left the pack one
    coater short and nothing downstream could tell: ``game.addon_supply`` and
    ``prolif.coaters_are_supplied`` both iterate the coaters that EXIST.  Each
    raises :class:`_Unseatable` now, the sweep discards that height, and a spec
    where no height can seat them is refused.  The validator says the same thing
    about the finished placement from the other end --
    ``prolif.sprayed_cargo_reaches_machines`` -- so neither this nor a future
    strategy can put the miss back.
    """
    coater = catalog.building(catalog.SPRAY_COATER_ID)
    wanted = set(spec.spray_lanes)
    seen: set[str] = set()
    out: list[_Coater] = []

    belt_at: dict[tuple[int, int, int], int] = {
        (b.x, b.y, int(b.z)): i
        for i, b in enumerate(canvas.buildings)
        if catalog.is_belt(b.item_id) and b.z.denominator == 1
    }

    for s, in_ports in zip(strips, ports, strict=True):
        for item in s.in_lanes:
            if item not in wanted:
                continue
            port = in_ports.get(item)
            if port is None:
                raise _Unseatable(
                    f"the strip feeding {item} has no input port for it, so its "
                    f"Spray Coater has no lane to ride"
                )
            seat = _coater_seat(canvas, port)
            if seat is None:
                raise _Unseatable(
                    f"the {item} lane at ({port.x}, {port.y}) is "
                    f"{len(port.tiles)} tile(s) long, and a coater needs a tile "
                    f"with a lane tile on both sides of it to ride straight"
                )
            cx, cy = seat
            host = belt_at.get((cx, cy, 0))
            # WHERE the proliferator belt has to be, from the coater's own addon
            # area rather than from convenience. The game attaches an addon's
            # belts positionally: area 0 is the cargo belt it rides, area 1 the
            # proliferator supply, and for a coater that is `(0, -1.25, 1)` --
            # a tile and a quarter BEHIND it and exactly one altitude level UP.
            # A belt beside it at ground level, which is what this used to build
            # and then run a sorter from, is in neither area and the game
            # attaches nothing to it.
            adx, ady, adz = catalog.building(catalog.SPRAY_COATER_ID).addon_areas[1]
            wx, wy = slots.to_world((adx, ady), Facing.EAST.value)
            drop_cell = (cx + round(wx), cy + round(wy), round(adz))
            if host is None:
                raise _Unseatable(
                    f"the {item} lane's seat ({cx}, {cy}) carries no belt at "
                    f"ground level, so there is nothing for a coater to ride"
                )
            if not canvas.free(drop_cell):
                raise _Unseatable(
                    f"the {item} coater at ({cx}, {cy}) cannot have its "
                    f"proliferator drop at {drop_cell}: that cell is taken, and "
                    f"the game supplies an addon from its area and nowhere else"
                )

            drop = canvas.add(
                PlacedBuilding(
                    item_id=belt_id,
                    model_index=belt_model,
                    x=drop_cell[0],
                    y=drop_cell[1],
                    z=Fraction(drop_cell[2]),
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
            # NO sorter drop -> coater. That connection does not exist in the
            # game: a coater ships zero insert poses, `BuildTool_Inserter` will
            # not target a building with none, and all eight coaters in the
            # fixture corpus carry no connection at all. The game attaches the
            # belts positionally instead, from `PrefabDesc.addonAreaPoses` --
            # area 1, the proliferator supply, sits at `(0, -1.25, 1)`: a tile
            # and a quarter behind the coater and one altitude level UP. The
            # drop belt above is at the right x and the wrong LEVEL, so
            # `game.addon_supply` reports the coater unsupplied and the
            # candidate is refused rather than shipped looking fed.
            # PRICE THE COATER FOR EVERY ROUTE THAT COMES AFTER IT.  A coater
            # reserves no tile -- it rides its belt -- so nothing in `solid` or
            # `blocked` keeps a later route off it, and its collider is 1.8975
            # high and three tiles long.  The proliferator chain used to cross
            # at level 1 and paste as `EBuildCondition.Collide` on the crossing
            # BELT; confirmed in game on a cut-down blueprint carrying one
            # coater, its tower and no machines at all.  `game.belt_crossing`
            # is the check; this is where it is honoured.
            #
            # The drop cell is left out on purpose: that is the addon's raised
            # area, a belt is REQUIRED there one level up, and it is already
            # placed above.
            # EXACT, from the collider, not from the footprint.  The oriented
            # footprint is three tiles and the two boxes do not fill it: box A
            # is 0.9 high and stops at +1.51 tiles along the coater's axis, box
            # B reaches 2.7 high and stops at +0.32.  Banning the whole
            # footprint at level 1 walled off the MARGIN tile the proliferator
            # chain enters through, and the chain then had no way in at all --
            # 22 corpus cells refused for a cell the game does not object to.
            # So each candidate cell is asked of the real boxes, which is the
            # same question `validate.game.belt_crossing` asks of the result.
            pose = colliders.Placed(
                coater.model_index,
                *codec.tile_to_local_offset(cx, cy, Fraction(0), 1, 1),
                Facing.EAST.value,
            )
            need = colliders.belt_crossing_height(coater.model_index)
            span = (catalog.oriented_footprint(
                catalog.SPRAY_COATER_ID, Facing.EAST.value
            )[0] - 1) // 2 + 1
            for dx in range(-span, span + 1):
                for dy in range(-span, span + 1):
                    tile = (cx + dx, cy + dy)
                    if tile == (drop_cell[0], drop_cell[1]):
                        continue
                    for level in range(1, math.floor(need) + 1):
                        probe = colliders.Placed(
                            belt_model,
                            *codec.tile_to_local_offset(
                                tile[0], tile[1], Fraction(level), 1, 1
                            ),
                            0.0,
                        )
                        if colliders.belt_crossings(
                            [probe], [pose], directly_over_only=True
                        ):
                            canvas.belt_ban.setdefault(tile, set()).add(level)
            out.append(_Coater(coater=idx, drop=drop, x=drop_cell[0], y=drop_cell[1]))
            seen.add(item)

    # EVERY drop is exempt from EVERY ban, not just its own coater's.  Coaters
    # two tiles apart on one row overlap footprints, so coater A's band covered
    # coater B's drop cell -- the belt was already standing there, but the
    # router could no longer reach it and the net came back unrouted with no
    # explanation.  A drop cell carries a required connection whichever coater
    # is standing over it.
    for c in out:
        canvas.belt_ban.pop((c.x, c.y), None)

    # AND EVERY SPRAYED ITEM GOT ONE SOMEWHERE.  The loop above walks the lanes
    # the strips carry, so an item the spec wants sprayed that no strip carries
    # on a lane is not refused by any of the clauses inside it -- it is simply
    # never visited.  That is the same silent miss with the loop skipped
    # entirely, and it is what a direct-inserted sprayed ingredient looks like
    # from here.
    missing = wanted - seen
    if missing:
        raise _Unseatable(
            f"the spec sprays {sorted(missing)}, and no strip carries "
            f"{'them' if len(missing) > 1 else 'it'} on an input lane, so no "
            f"Spray Coater was placed for {'any' if len(missing) > 1 else 'it'}"
        )
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
        # The drop is one altitude LEVEL up -- see `_Port.z`. Saying so here is
        # what lets the reservation and the router look for its access cell in
        # the plane the drop is actually in.
        dst = _Port(
            nxt.drop, nxt.x, nxt.y, nxt.x, nxt.x, (), 1, int(canvas.buildings[nxt.drop].z)
        )
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


def _drainable_by_port(s: Strip) -> bool:
    """Does one of this strip's machines offer a port facing its output lane?

    Asked of a PROBE rather than of a placed machine, because this runs in
    planning where nothing is placed yet -- and the answer cannot depend on
    where the strip lands: a port's side is fixed by the machine's yaw, and the
    output lane is always the row directly under the band.
    """
    probe = slots.probe_building(s.item_id, s.yaw)
    return any(d.facing.delta[1] > 0 for d in slots.port_docks(probe).values())


def _machines_without_poses(strips: list[Strip]) -> list[str]:
    """Lanes seated where no sorter of any tier can join them to their machine.

    Two shapes, and they are worth telling apart in the message because they
    call for different fixes.

    THE MACHINE HAS NO INSERT POSE AT ALL.  ``slots.attachment`` reads the
    game's own ``PrefabDesc.slotPoses``, and for a Ray Receiver and an Energy
    Exchanger that array has LENGTH ZERO.  ``BuildTool_Inserter`` will not
    target a building with no pose, so no sorter can attach to one on any face
    at any distance.  ``Strip.input_lane_tiles`` correctly returns 0 for such a
    machine, ``_emit_strip`` then built that row as an empty lane, and ``feed``
    indexed its head -- ``IndexError: list index out of range``.  The OUTPUT
    side did not even crash: ``_link_lane`` finds no usable column, places
    nothing and returns 0, so the machine shipped joined to nothing at either
    end.  That is the shape spine measured on the mode-driven spec -- two Energy
    Exchangers and ZERO sorters in the whole placement, which `validate` called
    ok.

    THE LANE IS SIMPLY TOO FAR from the nearest pose.  A machine's poses are not
    on its footprint edge in general, so a lane that looks two rows clear can be
    three or four tiles from anything a sorter can anchor on, and every tier
    reaches exactly ``SORTER_MAX_REACH``.  Over the 36 corpus specs this is 31
    lanes; the old edge-row arithmetic charged 24 of them a span of 3 -- legal,
    so a sorter was emitted that could not reach -- and the other 7 a span of 4,
    which is `ValueError: span 4 outside 1..3` and is the crash every
    `universe-matrix` stress cell reported.

    THE MESSAGE NEVER QUOTES A DISTANCE, because it has none to quote.
    ``sorter_span`` reads the slot table through ``slots.attachment``, which has
    already rejected anything outside ``1..SORTER_MAX_REACH``, so the only
    failing value it can return is 0 -- meaning nothing anchorable was found at
    all, not a measured four tiles.  Printing that 0 as a distance is what made
    the ``organic-crystal`` refusal read "0 tile(s) ... past the 3-tile reach".
    ``_side_lane_caps`` now keeps seating inside what the poses reach, so this
    is a guard against a future seating bug rather than a routine outcome.

    BOTH ARE REFUSALS RATHER THAN REPAIRS, and deliberately so.

    THIS DOCSTRING USED TO ARGUE FROM A FALSE PREMISE, and the message it
    justified sent readers to the wrong place: *"a Ray Receiver IS fed in game,
    so it either carries its slots in an array the extractor does not read or
    takes items by some other mechanism -- a question for the extractor"*.  It
    is not a question for the extractor.  Settled from the prefabs and from the
    IL, and recorded in ``docs/BACKLOG.md``: ``ray-receiver`` and
    ``energy-exchanger`` each carry exactly one ``SlotConfig`` whose
    ``insertPoses`` has LENGTH ZERO and whose ``portPoses`` has two and four
    entries respectively, ``PrefabDesc.slotPoses`` IS ``SlotConfig.insertPoses``,
    and ``BuildTool_Inserter`` drops any target with none.  There is no array to
    miss.  A Ray Receiver is also fed NOTHING -- it is a pure source, and the
    lane it wants is its critical-photon OUTPUT.

    What these buildings take is a BELT DOCKED INTO A PORT, which neither
    strategy can emit; that work is the open item, and it is blocked in turn on
    a port being INSIDE the footprint while our occupancy is a tile grid.  So
    the message names the port count as well as the missing poses, exactly as
    spine's :func:`_sorterless_groups` does, and a blueprint that pastes idle
    machines stays worse than a refusal that names the prefab.

    Returns one description per distinct offending (building, lane kind), empty
    when every lane in the plan can be joined to its machine.
    """
    reach = catalog.SORTER_MAX_REACH
    seen: set[tuple[int, str, int]] = set()
    out: list[str] = []
    for s in strips:
        rows: list[tuple[int, str]] = [(j, "ingredient") for j in range(len(s.in_above))]
        rows += [(s.row_of_output(k), "output") for k in range(len(s.out_lanes))]
        rows += [(s.row_of_input(lane[0]), "ingredient") for lane in s.in_below]
        for row, kind in rows:
            span = s.sorter_span(row)
            if 1 <= span <= reach:
                continue
            if s.takes_belt_ports and kind == "output" and _drainable_by_port(s):
                # `_dock_lane` wires this one, and a sorter span is the wrong
                # question to ask about it.
                continue
            key = (s.item_id, kind, span)
            if key in seen:
                continue
            seen.add(key)
            building = catalog.building(s.item_id)
            name = building.name
            if s.takes_belt_ports and kind == "ingredient":
                out.append(
                    f"{name} ({s.recipe_id}): the game's prefab gives it no "
                    f"insert pose on any face, so its {kind} lane can only be "
                    f"joined to it by a belt docked into one of its "
                    f"{len(building.port_poses)} belt port(s) -- and only the "
                    f"OUTPUT side docks today, because an ingredient would have "
                    f"to SPLIT one lane into a belt per machine and the "
                    f"no-splitter invariant is what buys the lane-per-"
                    f"destination design"
                )
            elif s.takes_belt_ports:
                out.append(
                    f"{name} ({s.recipe_id}): none of its "
                    f"{len(building.port_poses)} belt port(s) faces the output "
                    f"lane below the machine band, and it has no insert pose on "
                    f"any face either, so nothing can carry the product away"
                )
            elif not s.attachable_columns:
                out.append(
                    f"{name} ({s.recipe_id}): the game's prefab gives it no "
                    f"insert pose on any face and {len(building.slots)} belt "
                    f"port(s), so its {kind} lane cannot be joined to it by a "
                    f"sorter -- it takes a belt docked into a port, which "
                    f"neither strategy emits"
                )
            else:
                out.append(
                    f"{name} ({s.recipe_id}): its {kind} lane is seated on row "
                    f"{row}, which has no insert pose within the {reach}-tile "
                    "reach of any sorter tier on any column of the machine"
                )
    return out


def fallback_placement(
    spec: BuildSpec, *, power: bool = True, ramped: bool = False
) -> Placement:
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
    result = _build(
        spec, strips, pack, power=power, route=False, ramped=ramped
    )
    placement = result.placement
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
        arrangements: int | None = None,
        belt_vertical_construction: bool = True,
    ) -> None:
        self.power = power
        #: Whether ramps are REQUIRED.  The game's slope limit is conditional --
        #: ``!history.beltVerticalConstruction && num25 > 0.8f`` -- so a save
        #: WITH the tech has no slope limit and a belt may gain a whole level in
        #: one tile.  Defaults to having it, because an absent technology set in
        #: the URL means every technology researched.
        #:
        #: Treating the limit as unconditional cost 19 of 72 audit cells against
        #: master's 2, and made the one test class built from a real corpus URL
        #: fail 2 runs in 3: every net paid two tiles per level change and a
        #: stricter join rule, under a constraint these saves do not carry.
        self.ramped = not belt_vertical_construction
        self.strip_len = strip_len
        #: CP-SAT search workers. ``None`` takes the module default (all
        #: cores); the bake-off pins ``DETERMINISTIC_WORKERS``.
        self.workers = DEFAULT_SEARCH_WORKERS if workers is None else workers
        #: Off only for A/B measurement -- the feature is worth having, but
        #: proving it works means comparing against its own absence.
        self.direct_insert = direct_insert
        #: Arrangements per candidate height. ``None`` takes
        #: :data:`_ARRANGEMENTS`, which is the measured default; ``1`` is the
        #: search as it stood before arrangements existed, and is what the A/B
        #: compares against.
        self.arrangements = _ARRANGEMENTS if arrangements is None else arrangements

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
        # A machine no sorter can attach to is refused FIRST, because it is not
        # a question about the packing at all: `_emit_strip` crashes on the
        # empty lane it implies, so every later stage would be reporting a
        # symptom of this one.
        unreachable = _machines_without_poses(strips)
        if unreachable:
            raise NoValidLayout(
                "a machine in this spec has lanes to wire and no insert pose to "
                "wire them to, so it would paste joined to nothing. "
                + "; ".join(unreachable[:3]),
                spec_label=spec.label,
                budget_s=0.0,
            )

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
        #: The unrouted-net count of every pack the sweep actually ROUTED.
        #: Empty means no pack got that far.  It is what turns "the deadline
        #: passed" from an assertion into a measurement -- see the refusal
        #: below.
        attempts: list[int] = []
        for sweep_s in budgets:
            if _expired(deadline):
                break
            best = self._sweep(
                spec, strips, sweep_s, deadline, budget, rejected, attempts
            )
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
            # AND IT HAS TO SAY HOW CLOSE THE PACKS CAME, because the clock
            # expiring is not evidence that the clock is what was missing.
            #
            # This message used to assert that the sweep "ran out of clock
            # rather than out of candidates", and it asserted that on no
            # evidence beyond `_expired(deadline)` -- so EVERY refusal whose
            # ceiling elapsed read as a routing-throughput failure, whatever the
            # packs had been doing.  That reading is what a whole line of work
            # was aimed at, and it is not what the numbers say.
            #
            # `universe-matrix/no-proliferator` power=1 under the sequence-pair
            # packer, given 240 seconds -- sixteen times its ceiling -- routed
            # EIGHT packs in 7.0 to 28.4 seconds each and every one of them left
            # between 39 and 138 of its nets unrouted.  Not one was a near miss.
            # The same cell under freeform reaches a pack that wires with zero
            # failures, but only as its FOURTH height, about eighty seconds in.
            # Those two are opposite defects and the old message called them the
            # same thing.
            #
            # So the counts go in the refusal.  A reader can then tell "the
            # sweep never got to the candidate that works" from "every candidate
            # it tried was nowhere near", and aim at the right half of the
            # program.
            tried = (
                "1 pack was" if len(attempts) == 1 else f"{len(attempts)} packs were"
            )
            if not attempts:
                note = "no pack finished routing inside it"
            elif min(attempts) == 0:
                note = (
                    f"{tried} routed in that time and at least one wired every "
                    "net, so the clock is what was missing"
                )
            else:
                note = (
                    f"{tried} routed in that time and the best of them still "
                    f"left {min(attempts)} nets unrouted (worst "
                    f"{max(attempts)}), so a longer clock alone would not have "
                    "wired this spec"
                )
            raise NoValidLayout(
                f"the {ceiling:g}s deadline passed with no wired packing of "
                f"{len(strips)} strips; {note}. This is a REFUSAL and not a "
                "verdict on the spec",
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
        attempts: list[int] | None = None,
    ) -> Placement | None:
        """Try every candidate height, returning the best FULLY ROUTED placement.

        ``attempts`` collects the unrouted-net count of every pack this ROUTES,
        so a caller that has to refuse can say how close the candidates came
        rather than only that its clock expired.  See :meth:`lay_out`'s deadline
        refusal, which used to assert the difference and now reports it.

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
        # strip's machine band blocks the bottom three levels, so the only way
        # past a strip is the one-row channel on its south face, and a wide pack
        # asks its nets to cross the whole width through those. That is not what
        # the failures are. Flooding from the start cells of failing searches
        # says the median reachable region is ONE CELL -- see
        # `_reserve_port_access`, which now holds the way out of it. Nothing is
        # crossing anything; the source port cannot leave its own access cell. A
        # one-row corridor also carries several belts, not one, since only a
        # machine denies the whole band -- and since `LEVELS` rose to 4 a net
        # can go OVER the strip as well as around it.
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
        # AND A CANDIDATE IS A (HEIGHT, ARRANGEMENT) PAIR, NOT A HEIGHT.
        #
        # The note above ends "the lever is the packer's arrangement, not the
        # stopwatch", and this is that lever. The sweep used to try each height
        # once, and when none of them wired, `lay_out`'s retry packed the SAME
        # heights again -- more solver time on the same five arrangements, which
        # the note above `per_solve` shows is actively counterproductive, since a
        # longer solve returns a tighter pack and tighter is harder to wire.
        #
        # Measured instead: at ONE height and ONE WIDTH, two CP-SAT seeds give
        # arrangements that differ in whether the router can wire them, on 21 of
        # 50 height-groups. See `_ARRANGEMENTS` for that measurement, and the
        # note at the top of the loop for what it is and is not worth.
        #
        # ARRANGEMENT-OUTER, so the first pass is exactly what shipped before it:
        # every height at arrangement 0, in the same order, and only then a
        # second arrangement of each. That ordering is what lets the loop stop
        # dead at the first pair of arrangement 1 when nothing has wired -- every
        # pair after it is also arrangement 1, so there is nothing to skip past.
        candidate_packs = [
            (height, arrangement)
            for arrangement in range(max(1, self.arrangements))
            for height in heights
        ]
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
        #: The dearest candidate this sweep has COMPLETED, pack through validate.
        #: What `_room_for_another` charges the next improvement arrangement.
        dearest_candidate_s = 0.0
        started_at: float | None = None
        for height, arrangement in candidate_packs:
            # Charge the PREVIOUS candidate here, at the one place every path
            # through the body reaches. The body leaves by five different
            # routes -- no pack, unpowerable, unrouted, rejected, kept -- and a
            # cost recorded at only some of them would systematically
            # UNDER-estimate, since the expensive exits are the failures that run
            # a full routing pass into the wall.
            if started_at is not None:
                dearest_candidate_s = max(
                    dearest_candidate_s, time.monotonic() - started_at
                )
            # A SECOND ARRANGEMENT IMPROVES; IT NEVER SEARCHES FOR THE FIRST.
            #
            # This is the whole shape of the feature and it was measured into
            # existence rather than designed. Extra arrangements were tried
            # unconditionally first, and on a spec that has not wired anything
            # they buy NOTHING: every refusal on the stress specs reads "the 15s
            # deadline passed", 36 of 36 across ten runs, so the binding
            # constraint there is the clock and another arrangement spends it
            # rather than buying it. Paired, five rounds, `universe-matrix` and
            # `quantum-chip` at budget 4: 8.4 of 12 clean either way, difference
            # exactly 0.00.
            #
            # AND THE EARLIER NUMBER FOR THIS DID NOT SURVIVE THE POWER REWRITE,
            # which is why the gate exists at all. Before `_power_plan` decided
            # coverage in the solve, ungated arrangements measured +1.17 clean
            # cells on the corpus (paired, six rounds, t = +3.80). Re-measured
            # after it: -0.33 (t = -0.79). The rewrite lifted the baseline from
            # 70.0 to 71.8 of 72 and took the headroom with it, so what was a
            # routability lever is now purely a density one.
            #
            # Where they DO pay is on a spec that has already wired and has clock
            # left, because the sweep keeps the best `(area, belt_tiles)` it has
            # seen and a further arrangement is another draw at a denser one.
            # Tier `large` at budget 60, six paired rounds, 60 of 60 clean in
            # every run of both arms: -1.51% AREA, paired t = -5.26, denser in
            # SIX OF SIX rounds, and per cell denser on 24 of 60 against larger
            # on 1. That costs 2.6x the cell-seconds, which is the trade being
            # made knowingly: `time_budget_s` is an allowance the caller has
            # already agreed to spend, the sweep used to hand most of it back,
            # and density is the objective it is spent on.
            #
            # So the first pass over the heights is exactly what shipped before,
            # and arrangements past it are gated TWICE: on having something to
            # improve, and on being able to afford the improvement.
            #
            # `best is None` alone was not enough, and the number that says so
            # was measured at the DEFAULT budget rather than at the budget the
            # density win came from. Nine paired rounds at `--budget 4
            # --jobs 16`, arrangements 3 against 1: -4, 0, 0, 0, 0, -1, +1, 0,
            # -2, a mean of -0.67 cells. The -1.51% area is real and it is a
            # `tier large --budget 60` number; shipping it unconditionally
            # charges budget-4 cells for a budget-60 gain, which is the wrong way
            # round because budget 4 is what the audit runs and what a user gets.
            #
            # THE AFFORDABILITY RULE, and it carries no tuned constant: an
            # improvement arrangement may start only if as much clock remains as
            # the most expensive candidate so far actually took. By the time
            # `best` exists at least one candidate has been packed, routed,
            # powered and validated, so its cost is MEASURED for this spec on
            # this machine rather than guessed -- which is the only honest
            # estimate of what the next one costs, and it self-calibrates across
            # a corpus spanning 1 to 955 machines instead of asking a threshold
            # to span it.
            #
            # It reads on both ends the way the diagnosis says it should. At
            # budget 4 a `universe-matrix` candidate costs ten seconds or more
            # against a sweep share of four, so no improvement arrangement ever
            # starts and the stress cells get back the search they had. At budget
            # 60 a tier-`large` candidate costs a second or two against a share
            # of sixty, so they all run and the density win stands.
            #
            # Measured on both ends after the rule went in, paired and
            # interleaved:
            #
            #   budget 4, jobs 16, full corpus, TWELVE rounds
            #     -3 +1 0 +1 0 0 -1 +2 -4 +2 -1 0
            #     mean -0.25 cells, 95% CI [-1.40, +0.90], median 0, and the
            #     rounds split 4 better / 4 worse / 4 level. INVALID 0 over all
            #     1728 cells. The two specs that carry every refusal are where
            #     the rule has to work and it does: `universe-matrix` refuses 11
            #     times against 10, and `quantum-chip` measured alone at jobs 6,
            #     away from the audit's own CPU contention, is identical on six
            #     of seven rounds.
            #
            #   tier large, budget 60, four rounds
            #     -1.98% AREA, paired t = -5.41, denser in FOUR OF FOUR rounds,
            #     60 of 60 clean in every run of both arms, per cell denser on 21
            #     and larger on 2.
            #
            # So the default is the one both ends support, which is the thing the
            # unconditional version got wrong: it was measured at budget 60 and
            # shipped to budget 4.
            if arrangement and best is None:
                break
            if arrangement and not _room_for_another(
                deadline, soft, dearest_candidate_s
            ):
                break
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
            started_at = time.monotonic()
            pack = _pack(
                strips,
                height=height,
                width_bound=max(bound * 2, 8),
                time_budget_s=per_solve,
                direct_candidates=net_candidates,
                workers=self.workers,
                seed=seeds[height],
                arrangement=arrangement,
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
            # A pack that cannot be POWERED is discarded exactly like a pack
            # that cannot be WIRED, and for the same reason: it is not a
            # feasible packing, so there is nothing here to rescue.
            #
            # There is no `claim_power=False` retry, and there is no coverage
            # repair behind this either. The retry gave the whole power claim up
            # as soon as a pack left one to three nets unrouted, on the
            # reasoning that a build which cannot be wired is worth nothing
            # while coverage still had a repair pass to fall back on. The second
            # half of that never held: the repair needed free ground and a pack
            # tight enough to strand a net has none, so what came back was a
            # wired blueprint with buildings outside every tower's radius --
            # `power.coverage`, an INVALID, in place of a refusal that would
            # have emitted nothing.
            #
            # `_power_plan` now decides coverage before routing and says so when
            # it cannot, which costs a pack rather than a pack plus a full
            # routing pass. If no height survives, the spec is REFUSED. Trading
            # coverage for the last net or two, like trading density for it, is
            # buying a green cell with something the build needed.
            try:
                result = _build(
                    spec,
                    strips,
                    pack,
                    power=self.power,
                    route=True,
                    ramped=self.ramped,
                    deadline=deadline,
                    budget=budget,
                )
            except _Unpowerable:
                if rejected is not None:
                    rejected.add("power.coverage")
                continue
            except _Unseatable:
                # A pack that cannot seat one of its Spray Coaters is not a
                # pack, for the same reason one that cannot be powered is not:
                # the spec asked for proliferation and this height cannot
                # deliver it. Discarding the height is the search doing its job;
                # what is NOT allowed is emitting the pack with the coater left
                # out, which is what this replaced.
                if rejected is not None:
                    rejected.add("prolif.sprayed_cargo_reaches_machines")
                continue
            failed = result.routing.failed_count
            if attempts is not None:
                attempts.append(failed)
            if failed:
                continue
            placement = result.placement
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


def _room_for_another(deadline: float | None, soft: float, candidate_s: float) -> bool:
    """Is there clock left to pack, route, power and validate one more candidate?

    Both clocks have to allow it and they say different things.  ``soft`` is the
    sweep's own share and is what stops it improving; ``deadline`` is the call's
    wall and is what stops it entirely.  A candidate started against either one
    with no room to finish is a candidate whose whole cost is wasted -- the sweep
    already holds a routed placement, so an abandoned improvement buys nothing
    and spends the clock a later spec-critical pass might have used.

    ``candidate_s`` is the dearest candidate this sweep has actually completed,
    which makes this a measurement rather than a threshold: see the note in
    :meth:`FreeformLayout._sweep` for why a tuned constant could not span a
    corpus running from 1 to 955 machines.

    A ``deadline`` of ``None`` means a caller with no wall -- a test or a probe
    -- and only the soft clock then applies.
    """
    now = time.monotonic()
    if soft - now < candidate_s:
        return False
    return deadline is None or deadline - now >= candidate_s


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
