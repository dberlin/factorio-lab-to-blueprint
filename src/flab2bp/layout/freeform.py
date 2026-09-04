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
from array import array
from bisect import bisect_left, bisect_right
from collections import defaultdict
from collections.abc import (
    Callable,
    Collection,
    Container,
    Iterable,
    Iterator,
    Mapping,
    Sequence,
    Set,
)
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, field, replace
from enum import Enum
from fractions import Fraction
from functools import cache, lru_cache
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal, cast

import numpy as np
from ortools.sat.python import cp_model

from flab2bp.dsp import catalog, codec, colliders, params, planet, rules, splitter_ports
from flab2bp.layout import finalize, junction, last_mile, route_kernel, slots, validate
from flab2bp.layout.band_policy import BandPolicy
from flab2bp.layout.base import (
    ATOMIC_COMPLETION_GRACE_S,
    DEFAULT_SEARCH_WORKERS,
    Facing,
    NoValidLayout,
    PlacedBuilding,
    Placement,
    PlacementCompletion,
    PlacementStats,
    ProjectionFailureRecord,
)
from flab2bp.layout.belt_tiers import retier_belts
from flab2bp.layout.finalize import ProjectionNoGood
from flab2bp.layout.route_feedback import (
    Cell,
    ClusterRelationNoGood,
    DetailedRouteResult,
    DetailedRouteStatus,
    FeedbackState,
    LastMileReport,
    LogicalNetId,
    NetFailure,
    NetId,
    NetRole,
    RouteFailureKind,
    combine_last_mile_reports,
    update_feedback,
)
from flab2bp.layout.sequence_alns import (
    REWARD_RANKS,
    OperatorChoice,
    OperatorContext,
    OperatorMetrics,
    OperatorOutcome,
    OperatorSession,
    RepairOperator,
    destroy_strips,
    metrics_from_evaluation,
    operator_tally,
    remaining_fraction_bucket,
    reward_vector,
)
from flab2bp.layout.sequence_pair import (
    DecodedPlacement,
    DirectInsertTarget,
    GapProfile,
    PlacementProblem,
    SequencePair,
    encode_placement,
)
from flab2bp.layout.slots import SlotUndetermined, assign_sorter_slots
from flab2bp.layout.strip_variants import CargoDomain
from flab2bp.spec import BuildSpec

if TYPE_CHECKING:
    from flab2bp.layout.geometry_memo import MemoStats
    from flab2bp.layout.strip_variants import (
        LaneAttachmentPlan,
        LanePlan,
        LanePortDockPlan,
        LaneSorterAttachment,
        ProjectionPitchRequirement,
        StripFamily,
        StripFamilyId,
        StripInstanceId,
        StripPoseId,
        StripVariant,
        StripVariantId,
    )

_NO_PITCH_REQUIREMENTS: Mapping[StripPoseId, int] = MappingProxyType({})
_NO_STAGED_STATIC_CLEARANCE: Mapping[StagedStaticClearanceKey, int] = MappingProxyType({})
_DEFAULT_BAND_POLICY = BandPolicy("portable")

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
#: Sprayed lanes need two additional west cells so the 3x1 coater body clears
#: the machine footprint while retaining a straight predecessor and successor.
_COATER_WEST_CHANNEL = 3


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
#: 3/4), so the third level costs nothing in legality.
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

#: Large prepared problems spend the deadline more effectively on independent
#: pack arrangements than on replaying one greedy routing order.
_SINGLE_ROUND_NETS = 64

#: Exact commit validation can expose a different static collision after a
#: rejected route takes its next-best path. Keep that local convergence bounded;
#: unlike a full RRR round, each pass touches only paths with new exact evidence.
_COMMIT_REPAIR_PASSES = 3

#: At fifteen strips CP-SAT's multi-worker portfolio already changes whether the
#: fixed-seed packing can be routed: the same fifteen-strip plan repeatedly
#: wires with one worker and can exhaust every candidate with the default
#: portfolio.  Pin this structural size and larger so the seed actually names a
#: reproducible candidate, independent of audit job allocation.
_DETERMINISTIC_PACK_STRIPS = 15
#: The smallest cluster that describes a RELATIVE placement.  One strip has no
#: relation to forbid, so a relaxed proof over it excludes nothing; `_pack`'s
#: cluster cut anchors on the first strip and constrains the rest against it.
_RELATION_STRIP_PAIR = 2
#: Fixed CP-SAT work for reproducible large-pack incumbents.  A wall-clock
#: cutoff still raced at one worker: the authoritative fifteen-strip cell
#: alternated between a clean width-48 packing and a width-47 packing whose
#: routing failed exact validation.  0.02 deterministic units reaches the same
#: routable incumbent well inside its 0.6s wall allowance; 0.005 stopped before
#: that incumbent existed.  The wall limit remains armed as the hard deadline.
_DETERMINISTIC_PACK_WORK = 0.02

#: Deterministic work allowed only for choosing among already rank-optimal port
#: access assignments. The ranked solution remains the safe fallback; this
#: bounded polish must never turn a preparation step into an unbounded search.
_ACCESS_TIE_DETERMINISTIC_WORK = 0.05


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
    tuple((step, _LEVEL_TOLL[lvl + step]) for step in (1, -1) if 0 <= lvl + step < LEVELS)
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

    ``lay_out`` takes one search deadline at the top of the call and threads it
    through every speculative phase, because every phase used to be bounded on
    its own and nothing bounded their sum: the height sweep spent
    ``time_budget_s``, the escalated retry spent ``RETRY_BUDGET_S`` again, the
    loose sweep had a budget of its own, and the routing inside each of them was
    bounded by an expansion count rather than a clock. A nominal 4-second budget
    measured at 80 seconds on ``quantum-chip`` and over 400 on a refusing
    ``universe-matrix`` cell. Once every net is routed, the fixed five-second
    atomic completion grace covers compaction, projection, and certification;
    it never admits another speculative candidate.

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
type CargoKey = tuple[str, CargoDomain]
type _CargoSink = tuple[str, str, CargoDomain]


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


@dataclass(frozen=True, order=True, slots=True)
class StagedStaticVariantId:
    """One strip pose plus the physical west lane reserved for staged statics."""

    strip_variant_id: StripVariantId
    west_channel: int

    def __post_init__(self) -> None:
        if self.west_channel <= 0:
            raise ValueError("staged-static west channel must be positive")


@dataclass(frozen=True, order=True, slots=True)
class StagedStaticClearanceKey:
    """Translation-free identity of one staged-static/strip collider relation."""

    peer_item_id: int
    peer_model_index: int
    peer_width: int
    peer_height: int
    peer_yaw: float
    candidate_item_id: int
    candidate_model_index: int
    candidate_width: int
    candidate_height: int
    candidate_yaw: float
    delta_x: int
    delta_y: int
    delta_z: Fraction


@dataclass(frozen=True, slots=True)
class StagedStaticClearanceRequirement:
    """A same-strip staged static needs one physically longer attachment lane."""

    instance_id: StripInstanceId
    variant_id: StagedStaticVariantId
    owner_strip: int
    rejected_west_channel: int
    required_west_channel: int
    relation: StagedStaticClearanceKey
    evidence: tuple[finalize.ProjectionFailure, ...]

    def __post_init__(self) -> None:
        if self.required_west_channel != self.rejected_west_channel + 1:
            raise ValueError("staged-static clearance advances exactly one tile")
        if not self.evidence:
            raise ValueError("staged-static clearance requires projection evidence")


@dataclass(frozen=True, slots=True)
class Strip:
    """A run of machines of one recipe, with its lanes attached.

    The lanes are part of the unit, not something routing adds later.  That is
    what makes a strip individually routable and keeps phase 1 from producing a
    machine nothing can feed.

    ``in_above``, ``out_lanes``, and ``in_below`` preserve the logical routing
    roles and ordering.  Their physical rows do not come from those tuple
    lengths: ``lane_plan`` seats each row outside the selected pose's collider
    envelope, and ``attachment_plan`` fixes every legal column, machine anchor,
    slot, and span.  Emission must reproduce that plan or refuse the candidate;
    it may not clamp a column or choose another pose.

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
    cargo_domain: CargoDomain
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
    out_lanes: tuple[_CargoSink, ...]
    #: Lanes arriving on the south side, below ``out_lanes``.  Non-empty only
    #: when a recipe has more ingredients than one side can reach.
    in_below: tuple[tuple[str, ...], ...]
    #: The selected variant's exact lane rows and machine offset in this box.
    lane_plan: LanePlan | None
    #: The exact machine-side anchor, slot, and span for every lane item.
    attachment_plan: tuple[LaneAttachmentPlan, ...]
    #: Exact selected variant box height, including collider halos and lanes.
    box_height: int
    #: Exact count-realized physical pose; absent only for compatibility families.
    physical_variant: StripVariant | None = None
    #: The authoritative drawing port and relative dock cell for port-backed outputs.
    port_dock_plan: tuple[LanePortDockPlan, ...] = ()
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
    family_id: StripFamilyId | None = None
    machine_start: int = 0
    west_channel: int = WEST_CHANNEL

    @property
    def staged_static_variant_id(self) -> StagedStaticVariantId | None:
        """Identity of physical strip geometry that seats ownerless statics."""
        if self.physical_variant is None:
            return None
        return StagedStaticVariantId(
            self.physical_variant.variant_id,
            self.west_channel,
        )

    @property
    def in_lanes(self) -> tuple[str, ...]:
        """Every ingredient, regardless of which side or lane feeds it."""
        return tuple(item for lane in self.in_above + self.in_below for item in lane)

    @property
    def width(self) -> int:
        return self.machines * self.pw

    @property
    def height(self) -> int:
        return self.box_height

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
        if self.lane_plan is not None:
            return self.lane_plan.machine_row
        if self.flank_outputs:
            return len(self.in_above)
        if self.takes_belt_ports:
            # A splitter on an input lane has a real collider.  Keep one row
            # between that lane and the machine band rather than relying on the
            # belt-only overlap excusal that applies to the dock run itself.
            return len(self.in_above) + bool(self.in_above)
        name = catalog.building(self.item_id).name
        raise NoValidLayout(f"{name} has no legal slot pose for its lanes")

    @property
    def takes_belt_ports(self) -> bool:
        """Is this strip's machine connected through prefab belt ports?

        A port is authoritative only when the catalog says the building takes
        belt ports and exposes no sorter pose.  A strategy may choose geometry;
        it may not reinterpret a sorter-capable machine as a port host.
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

    def column_offset(self, lane: tuple[str, ...]) -> int:
        """Return the first face-local column available to this input lane."""
        seen = 0
        for other in self.in_above:
            if other is lane or other == lane:
                return seen
            seen += len(other)
        seen = 0 if self.flank_outputs else len(self.out_lanes)
        for other in self.in_below:
            if other is lane or other == lane:
                return seen
            seen += len(other)
        raise KeyError(f"{lane!r} is not an input lane of {self.recipe_id!r}")

    def input_is_shared(self, item: str) -> bool:
        """Does ``item`` ride a lane with other items?

        A sorter drawing from a shared lane MUST set a filter, or it takes
        whatever passes and starves the machine that wanted the other item.
        """
        return len(self.lane_of_input(item)) > 1

    def _input_attachment_plan(self, item: str) -> LaneAttachmentPlan:
        for plan in self.attachment_plan:
            if plan.lane.kind == "input" and item in plan.lane.items:
                return plan
        if not self.flank_outputs:
            raise KeyError(f"{item!r} is not an ingredient of {self.recipe_id!r}")

        from flab2bp.layout.strip_variants import (
            LaneAttachmentPlan,
            LaneSorterAttachment,
            LogicalLane,
        )

        lane = self.lane_of_input(item)
        if lane in self.in_above:
            index = self.in_above.index(lane)
            row = index
            side: Literal["north", "south"] = "south"
            side_index = index
        else:
            index = self.in_below.index(lane)
            row = self.first_row_below_band + len(self.out_lanes) + index
            side = "north"
            side_index = len(self.out_lanes) + index
        offset = self.column_offset(lane)
        lane_y = row - self.machine_row
        reachable = sorted(
            slots.attachable_columns(slots.probe_building(self.item_id, self.yaw), lane_y).items()
        )
        selected = reachable[offset : offset + len(lane)]
        if len(selected) != len(lane):
            name = catalog.building(self.item_id).name
            raise NoValidLayout(f"{name} has no legal slot pose for input lane {lane!r}")
        logical = LogicalLane(
            lane_id=f"input:{side}:{side_index}",
            kind="input",
            items=lane,
            destination_group_keys=(),
            cargo_domain=self.cargo_domain,
            side=side,
            side_index=side_index,
        )
        return LaneAttachmentPlan(
            lane=logical,
            lane_y=lane_y,
            attachments=tuple(
                LaneSorterAttachment(
                    item=lane_item,
                    column=column,
                    cell=attachment.cell,
                    slot=attachment.slot,
                    span=attachment.span,
                )
                for lane_item, (column, attachment) in zip(lane, selected, strict=True)
            ),
        )

    def _output_attachment_plan(self, k: int) -> LaneAttachmentPlan:
        for plan in self.attachment_plan:
            if plan.lane.kind == "output" and plan.lane.side_index == k:
                return plan
        raise IndexError(f"output lane {k} is not planned for {self.recipe_id!r}")

    def attachment_of_input(self, item: str) -> LaneSorterAttachment:
        """The selected exact attachment for one ingredient."""
        plan = self._input_attachment_plan(item)
        return next(attachment for attachment in plan.attachments if attachment.item == item)

    def slot_of_input(self, item: str) -> int:
        """Authoritative relative column selected for this ingredient."""
        return self.attachment_of_input(item).column

    def row_of_input(self, item: str) -> int:
        """Row index carrying ``item``, relative to the strip's top."""
        if self.takes_belt_ports:
            lane = self.lane_of_input(item)
            if lane in self.in_above:
                return self.in_above.index(lane)
            return self.first_row_below_band + len(self.out_lanes) + self.in_below.index(lane)
        return self.machine_row + self._input_attachment_plan(item).lane_y

    def row_of_output(self, k: int) -> int:
        """Row index of the ``k``-th output lane, relative to the strip's top."""
        planned = next(
            (
                plan
                for plan in self.port_dock_plan
                if plan.lane.kind == "output" and plan.lane.side_index == k
            ),
            None,
        )
        if planned is not None:
            return self.machine_row + planned.lane_y
        if self.flank_outputs or self.takes_belt_ports:
            return self.first_row_below_band + k
        return self.machine_row + self._output_attachment_plan(k).lane_y

    def input_lane_tiles(self, lane: tuple[str, ...]) -> int:
        """Belt tiles an input lane needs through its last planned attachment."""
        if self.takes_belt_ports:
            lanes = self.in_above + self.in_below
            lane_index = lanes.index(lane)
            docks = tuple(
                dock
                for _port, dock in sorted(
                    slots.port_docks(slots.probe_building(self.item_id, self.yaw)).items()
                )
                if dock.facing is Facing.EAST
            )
            if lane_index >= len(docks):
                return self.width
            # The lane must reach the column the approach will TAP, which is no
            # longer always dock+1: a host whose port sits inside its own
            # collider taps further east (see _port_approach).  Trimming to
            # dock+1 left the LAST machine in a strip with no legal tap, which
            # turns the collision this fix removes into a refusal instead.
            probe = slots.probe_building(self.item_id, self.yaw)
            offset = _port_approach_offset(probe, docks[lane_index], self.pw)
            if offset is None:
                return self.width
            last_tap = (self.machines - 1) * self.pw + docks[lane_index].cell[0] + offset
            return min(self.width, last_tap + 1)
        plan = self._input_attachment_plan(lane[0])
        if plan.lane.items != lane:
            raise ValueError("input lane does not match the selected attachment plan")
        last_column = max(attachment.column for attachment in plan.attachments)
        return (self.machines - 1) * self.pw + last_column + 1

    def east_of_input(self, item: str) -> int:
        """Offset from the strip's west edge to the last tile of ``item``'s lane."""
        return self.input_lane_tiles(self.lane_of_input(item)) - 1

    @property
    def sid(self) -> str:
        return f"{self.group_key}"


def _staged_static_clearance_key(
    peer: PlacedBuilding,
    candidate: PlacedBuilding,
) -> StagedStaticClearanceKey:
    """Normalize one exact same-strip pair without its packed translation."""
    return StagedStaticClearanceKey(
        peer_item_id=peer.item_id,
        peer_model_index=peer.model_index,
        peer_width=peer.width,
        peer_height=peer.height,
        peer_yaw=peer.yaw,
        candidate_item_id=candidate.item_id,
        candidate_model_index=candidate.model_index,
        candidate_width=candidate.width,
        candidate_height=candidate.height,
        candidate_yaw=candidate.yaw,
        delta_x=peer.x - candidate.x,
        delta_y=peer.y - candidate.y,
        delta_z=peer.z - candidate.z,
    )


def _staged_static_clearance_keys(
    strip: Strip,
) -> frozenset[StagedStaticClearanceKey]:
    """Physical W3 machine/Coater relations this strip can materialize."""
    if strip.cargo_domain is not CargoDomain.REQUIRES_SPRAY or strip.physical_variant is None:
        return frozenset()
    coater = catalog.building(catalog.SPRAY_COATER_ID)
    coater_x = 1 - strip.west_channel
    return frozenset(
        StagedStaticClearanceKey(
            peer_item_id=strip.item_id,
            peer_model_index=strip.model_index,
            peer_width=strip.mw,
            peer_height=strip.mh,
            peer_yaw=strip.yaw,
            candidate_item_id=catalog.SPRAY_COATER_ID,
            candidate_model_index=coater.model_index,
            candidate_width=1,
            candidate_height=1,
            candidate_yaw=Facing.EAST.value,
            delta_x=machine * strip.pw - coater_x,
            delta_y=strip.machine_row - strip.row_of_input(item),
            delta_z=Fraction(0),
        )
        for item in strip.in_lanes
        for machine in range(strip.machines)
    )


_STAGED_STATIC_PROOF_CANCELLED: ContextVar[Callable[[], bool] | None] = ContextVar(
    "_STAGED_STATIC_PROOF_CANCELLED",
    default=None,
)


def _poll_staged_static_proof_deadline() -> None:
    cancelled = _STAGED_STATIC_PROOF_CANCELLED.get()
    if cancelled is not None and cancelled():
        raise _PreparationDeadline


def _staged_static_effective_anchor_ranges(
    pair_height: int,
    band: planet.Band,
) -> tuple[range, ...]:
    """Exact pair latitudes without enumerating redundant empty frame padding.

    A reachable frame contains the pair plus ``_ENTRY_RING`` rows on each side.
    For any taller frame, moving the pair through its interior produces exactly
    the same absolute latitude interval as moving the tight frame itself through
    the band. ``Band.anchor_ranges`` already represents those contiguous
    intervals, so translating its tight-frame anchors by the south perimeter is
    the complete sorted witness set.
    """
    tight_height = pair_height + 2 * _ENTRY_RING
    return tuple(
        range(
            anchor_range.start + _ENTRY_RING,
            anchor_range.stop + _ENTRY_RING,
        )
        for anchor_range in band.anchor_ranges(tight_height)
    )


def _staged_static_relation_projection_risks_uncached(
    relations: Sequence[StagedStaticClearanceKey],
    policy: BandPolicy,
) -> tuple[bool, ...]:
    """Evaluate relations sharing a projected candidate in one exact predicate."""
    _poll_staged_static_proof_deadline()
    risks = [False] * len(relations)
    bands = (
        tuple(band for band in planet.bands() if band.area_segments == policy.explicit_segments)
        if policy.explicit_segments is not None
        else planet.bands()
    )
    groups: dict[
        tuple[planet.Band, PlacedBuilding],
        list[tuple[int, PlacedBuilding, tuple[range, ...]]],
    ] = {}
    for ordinal, relation in enumerate(relations):
        _poll_staged_static_proof_deadline()
        candidate = PlacedBuilding(
            item_id=relation.candidate_item_id,
            model_index=relation.candidate_model_index,
            x=0,
            y=0,
            z=Fraction(0),
            width=relation.candidate_width,
            height=relation.candidate_height,
            yaw=relation.candidate_yaw,
        )
        peer = PlacedBuilding(
            item_id=relation.peer_item_id,
            model_index=relation.peer_model_index,
            x=relation.delta_x,
            y=relation.delta_y,
            z=relation.delta_z,
            width=relation.peer_width,
            height=relation.peer_height,
            yaw=relation.peer_yaw,
        )
        for rotated in (False, True):
            _poll_staged_static_proof_deadline()
            oriented = tuple(
                (
                    replace(
                        building,
                        x=-(building.y + building.height),
                        y=building.x,
                        width=building.height,
                        height=building.width,
                        yaw=(building.yaw - 90.0) % 360.0,
                    )
                    if rotated
                    else building
                )
                for building in (peer, candidate)
            )
            min_x = min(building.x for building in oriented)
            min_y = min(building.y for building in oriented)
            normalized_peer, normalized_candidate = tuple(
                replace(
                    building,
                    x=building.x - min_x,
                    y=building.y - min_y,
                )
                for building in oriented
            )
            pair_width = max(
                building.x + building.width for building in (normalized_peer, normalized_candidate)
            )
            pair_height = max(
                building.y + building.height for building in (normalized_peer, normalized_candidate)
            )
            collision_pair = (
                _collision_pose(normalized_peer),
                _collision_pose(normalized_candidate),
            )
            for band in bands:
                _poll_staged_static_proof_deadline()
                if (
                    pair_width + 2 * _ENTRY_RING > band.columns
                    or pair_height + 2 * _ENTRY_RING > band.rows
                    or not planet.candidate_pairs(
                        collision_pair,
                        band,
                        colliders.PLANET_SEGMENT,
                        colliders.PLANET_RADIUS,
                    )
                ):
                    continue
                candidate_origin = replace(
                    normalized_candidate,
                    x=0,
                    y=0,
                )
                peer_relative = replace(
                    normalized_peer,
                    x=normalized_peer.x - normalized_candidate.x,
                    y=normalized_peer.y - normalized_candidate.y,
                )
                anchor_ranges = tuple(
                    range(
                        anchor_range.start + normalized_candidate.y,
                        anchor_range.stop + normalized_candidate.y,
                    )
                    for anchor_range in _staged_static_effective_anchor_ranges(
                        pair_height,
                        band,
                    )
                )
                groups.setdefault(
                    (band, candidate_origin),
                    [],
                ).append((ordinal, peer_relative, anchor_ranges))

    cancelled = _STAGED_STATIC_PROOF_CANCELLED.get()
    for (band, candidate), members in groups.items():
        collision_buildings = (
            _collision_pose(candidate),
            *(_collision_pose(peer) for _ordinal, peer, _ranges in members),
        )
        collider_radii = tuple(
            planet.collider_radius(building.model_index) for building in collision_buildings
        )
        positions_by_anchor: dict[int, list[int]] = {}
        for position, (_ordinal, _peer, anchor_ranges) in enumerate(
            members,
            start=1,
        ):
            _poll_staged_static_proof_deadline()
            for anchor_range in anchor_ranges:
                _poll_staged_static_proof_deadline()
                for anchor in anchor_range:
                    _poll_staged_static_proof_deadline()
                    positions_by_anchor.setdefault(anchor, []).append(position)
        for anchor, positions in sorted(positions_by_anchor.items()):
            _poll_staged_static_proof_deadline()
            projection = planet.Projection(
                band=band,
                anchor_row=anchor,
                segment=colliders.PLANET_SEGMENT,
                radius=colliders.PLANET_RADIUS,
            )
            candidate_position = projection.pose(
                candidate.x,
                candidate.y,
                float(candidate.z),
                candidate.yaw,
            )[0]
            active: list[tuple[int, int]] = []
            for position in positions:
                if risks[members[position - 1][0]]:
                    continue
                collision_peer = collision_buildings[position]
                peer_position = projection.pose(
                    collision_peer.x,
                    collision_peer.y,
                    float(collision_peer.z),
                    collision_peer.yaw,
                )[0]
                radius = collider_radii[0] + collider_radii[position]
                if (
                    sum(
                        (left - right) ** 2
                        for left, right in zip(
                            candidate_position,
                            peer_position,
                            strict=True,
                        )
                    )
                    <= radius * radius
                ):
                    active.append((0, position))
            if not active:
                continue
            try:
                hits = planet.collisions_at(
                    collision_buildings,
                    projection,
                    active,
                    cancelled=cancelled,
                )
            except finalize.ProjectionCancelled:
                raise _PreparationDeadline from None
            for _candidate_index, peer_index in hits:
                risks[members[peer_index - 1][0]] = True
    return tuple(risks)


def _staged_static_relation_projection_risk_uncached(
    relation: StagedStaticClearanceKey,
    policy: BandPolicy,
) -> bool:
    """Whether this exact planar relation collides in a reachable projection."""
    return _staged_static_relation_projection_risks_uncached(
        (relation,),
        policy,
    )[0]


_STAGED_STATIC_RELATION_RISK_CACHE: dict[
    tuple[StagedStaticClearanceKey, BandPolicy],
    bool,
] = {}


def _staged_static_relation_projection_risks(
    relations: Sequence[StagedStaticClearanceKey],
    policy: BandPolicy,
) -> tuple[bool, ...]:
    """Install a completed exact batch transactionally in the relation cache."""
    missing = tuple(
        dict.fromkeys(
            relation
            for relation in relations
            if (relation, policy) not in _STAGED_STATIC_RELATION_RISK_CACHE
        )
    )
    if missing:
        computed = _staged_static_relation_projection_risks_uncached(
            missing,
            policy,
        )
        _STAGED_STATIC_RELATION_RISK_CACHE.update(
            ((relation, policy), risk) for relation, risk in zip(missing, computed, strict=True)
        )
    return tuple(_STAGED_STATIC_RELATION_RISK_CACHE[(relation, policy)] for relation in relations)


def _staged_static_relation_projection_risk(
    relation: StagedStaticClearanceKey,
    policy: BandPolicy,
) -> bool:
    """Cache the finite exact witness search by physical relation and policy."""
    return _staged_static_relation_projection_risks((relation,), policy)[0]


def _staged_static_preclearance_proof_uncached(
    relation: StagedStaticClearanceKey,
    policy: BandPolicy,
) -> bool:
    """Prove W3 can collide and moving its Coater one tile west is always clean."""
    cleared = replace(relation, delta_x=relation.delta_x + 1)
    rejected_risk, cleared_risk = _staged_static_relation_projection_risks(
        (relation, cleared),
        policy,
    )
    return rejected_risk and not cleared_risk


@cache
def _cached_staged_static_preclearance_proved(
    relation: StagedStaticClearanceKey,
    policy: BandPolicy,
) -> bool:
    """Run the pair-local clearance proof once per exact relation and policy."""
    return _staged_static_preclearance_proof_uncached(relation, policy)


class _StagedStaticPreclearanceProof:
    """Deadline-aware facade over transactionally installed exact proofs."""

    def __call__(
        self,
        relation: StagedStaticClearanceKey,
        policy: BandPolicy,
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> bool:
        if cancelled is None:
            return _cached_staged_static_preclearance_proved(relation, policy)
        if cancelled():
            raise _PreparationDeadline
        token = _STAGED_STATIC_PROOF_CANCELLED.set(cancelled)
        try:
            return _cached_staged_static_preclearance_proved(relation, policy)
        finally:
            _STAGED_STATIC_PROOF_CANCELLED.reset(token)

    def cache_clear(self) -> None:
        _cached_staged_static_preclearance_proved.cache_clear()
        _STAGED_STATIC_RELATION_RISK_CACHE.clear()


_staged_static_preclearance_proved = _StagedStaticPreclearanceProof()


def _staged_static_projection_peers(
    buildings: Sequence[PlacedBuilding],
    candidate: PlacedBuilding,
    *,
    owner_strip: int,
    policy: BandPolicy,
) -> tuple[tuple[int, PlacedBuilding], ...]:
    """Retain every unknown pair and omit only proved-clean same-strip pairs."""
    return tuple(
        (index, peer)
        for index, peer in enumerate(buildings)
        if not catalog.is_belt(peer.item_id)
        and not catalog.is_sorter(peer.item_id)
        and (
            peer.owner_strip != owner_strip
            or _staged_static_relation_projection_risk(
                _staged_static_clearance_key(peer, candidate),
                policy,
            )
        )
    )


def _box(s: Strip) -> tuple[int, int]:
    """The footprint one strip occupies in a pack: its extent plus its channels.

    Stated once so the shelf seed, the CP-SAT model and the height sweep cannot
    drift apart about how much ground a strip costs -- they did, and a seed
    whose width is not measured the same way as the solver's is not an upper
    bound on anything.
    """
    return s.width + s.west_channel + MARGIN, s.height + MARGIN


def _sink_demand(
    groups: dict[str, _Group],
    spec: BuildSpec,
    item: str,
    dest_key: str,
    *,
    include_boundary: bool = True,
) -> Fraction:
    """Items/second one sink wants of ``item``.

    An empty ``dest_key`` is the build boundary. Lane-capacity accounting
    includes that drain; machine allocation treats it as residual so sibling
    lanes can move their excess to the open boundary lane.
    """
    if DEST_SEP in dest_key:
        return sum(
            (
                _sink_demand(
                    groups,
                    spec,
                    item,
                    destination,
                    include_boundary=include_boundary,
                )
                for destination in _dests(dest_key)
            ),
            Fraction(0),
        )
    if not dest_key:
        if not include_boundary:
            return Fraction(0)
        return spec.outputs.get(item, Fraction(0)) + spec.surplus_outputs.get(item, Fraction(0))
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
    sinks: Sequence[_CargoSink],
    *,
    cap: int | None = None,
    max_shards: int | None = None,
) -> list[list[_CargoSink]]:
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

    by_cargo: dict[CargoKey, list[str]] = {}
    for item, dest, cargo_domain in sinks:
        by_cargo.setdefault((item, cargo_domain), []).append(dest)
    if not by_cargo:
        return []
    if len(by_cargo) > reach:
        raise ValueError(
            f"a machine yields {len(by_cargo)} distinct cargo lanes but only {reach} "
            f"output lane(s) fit inside the {catalog.SORTER_MAX_REACH}-tile sorter "
            "reach, so one of them could never be drained"
        )

    n = 1
    while sum(max(1, math.ceil(len(d) / n)) for d in by_cargo.values()) > reach:
        if max_shards is not None and n >= max_shards:
            break
        n += 1

    out: list[list[_CargoSink]] = [[] for _ in range(n)]
    for (item, cargo_domain), dests in by_cargo.items():
        per = math.ceil(len(dests) / n)
        for s in range(n):
            chunk = dests[s * per : (s + 1) * per] or [dests[s % len(dests)]]
            out[s].extend((item, d, cargo_domain) for d in chunk)
    return out


def _merge_lanes(
    shard: Sequence[_CargoSink],
    reach: int,
    demand: Mapping[_CargoSink, Fraction],
    capacity: Fraction,
) -> list[_CargoSink]:
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

    by_cargo: dict[CargoKey, list[str]] = {}
    for item, dest, cargo_domain in shard:
        by_cargo.setdefault((item, cargo_domain), []).append(dest)
    if len(by_cargo) > reach:
        raise ValueError(
            f"a machine yields {len(by_cargo)} distinct cargo lanes but only {reach} "
            f"output lane(s) fit inside the {catalog.SORTER_MAX_REACH}-tile sorter "
            "reach, so one of them could never be drained"
        )

    alloc = dict.fromkeys(by_cargo, 1)
    for _ in range(reach - len(by_cargo)):
        room = [cargo for cargo in by_cargo if alloc[cargo] < len(by_cargo[cargo])]
        if not room:
            break
        chosen = max(
            room,
            key=lambda cargo: (
                Fraction(len(by_cargo[cargo]), alloc[cargo]),
                cargo[0],
                cargo[1].value,
            ),
        )
        alloc[chosen] += 1

    out: list[_CargoSink] = []
    for item, cargo_domain in sorted(
        by_cargo,
        key=lambda cargo: (cargo[0], cargo[1].value),
    ):
        cargo = (item, cargo_domain)
        k = alloc[cargo]
        bins: list[list[str]] = [[] for _ in range(k)]
        loads = [Fraction(0)] * k
        order = sorted(
            by_cargo[cargo],
            key=lambda dest: (
                -demand.get((item, dest, cargo_domain), Fraction(0)),
                dest,
            ),
        )
        for dest in order:
            b = min(range(k), key=lambda i: (loads[i], i))
            bins[b].append(dest)
            loads[b] += demand.get((item, dest, cargo_domain), Fraction(0))
        for b, group in enumerate(bins):
            if not group:
                continue
            if loads[b] > capacity:
                raise ValueError(
                    f"{item}: destinations {sorted(group)} have to share one "
                    f"output lane carrying {loads[b]} items/s, over the "
                    f"{capacity}/s the belt sustains"
                )
            out.append((item, DEST_SEP.join(sorted(group)), cargo_domain))
    return out


def _allocate_machines(
    count: int,
    shards: Sequence[Sequence[_CargoSink]],
    demand: Mapping[_CargoSink, Fraction],
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
    totals: dict[CargoKey, Fraction] = defaultdict(Fraction)
    for (item, _dest, cargo_domain), rate in demand.items():
        totals[item, cargo_domain] += rate

    weights: list[Fraction] = []
    for shard in shards:
        served: dict[CargoKey, Fraction] = defaultdict(Fraction)
        for item, dest, cargo_domain in shard:
            cargo = (item, cargo_domain)
            served[cargo] += demand.get((item, dest, cargo_domain), Fraction(0))
        weight = Fraction(0)
        for cargo, rate in served.items():
            total = totals.get(cargo, Fraction(0))
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
            resolved = catalog.get_item_id(mg.machine_item_id)
            if resolved is None:
                raise KeyError(f"no DSP building known for machine {mg.machine_item_id!r}")
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
    cap = spec.lane_capacity
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
                f"{cap}/s the fastest belt this save can build sustains; these ingredients "
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
    prefer_shared: bool = False,
    lane_fits: Callable[[tuple[str, ...]], bool] | None = None,
) -> tuple[tuple[tuple[str, ...], ...], tuple[tuple[str, ...], ...]]:
    """Seat ingredients into lanes above and below the machine band.

    Tries one item per lane first by default, preserving ordinary layouts.
    ``prefer_shared`` reverses that order for proliferation lanes whose caller
    supplies an exact throughput predicate: fewer lanes then mean fewer Coaters
    and avoid an unroutable wall of adjacent supply terminals.

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
    mix_sizes = range(max(1, max_per_lane), 0, -1) if prefer_shared else range(
        1, max(1, max_per_lane) + 1
    )
    for k in mix_sizes:
        lanes = [tuple(items[i : i + k]) for i in range(0, n, k)]
        if lane_fits is not None and any(not lane_fits(lane) for lane in lanes):
            continue
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


def plan_strips(
    spec: BuildSpec,
    *,
    strip_len: int = 6,
    band_policy: BandPolicy = _DEFAULT_BAND_POLICY,
    minimum_pitch_x: Mapping[StripPoseId, int] = _NO_PITCH_REQUIREMENTS,
    families: Sequence[StripFamily] | None = None,
    minimum_staged_static_clearance: Mapping[
        StagedStaticClearanceKey,
        int,
    ] = _NO_STAGED_STATIC_CLEARANCE,
    cancelled: Callable[[], bool] | None = None,
) -> list[Strip]:
    """Select each logical family's deterministic compatibility pose.

    The legacy Freeform planner remains strip-based until the later atomic
    variant cutover.  Logical rate/shard allocation and physical pose
    generation now happen once; this adapter partitions only machine ordinals
    and projects the selected pose back into the existing :class:`Strip`.
    """
    from flab2bp.layout.strip_variants import (
        default_strip_variant,
        generate_strip_families,
        partition_strip_variant,
        strip_pose_id,
        variant_with_minimum_pitch,
    )

    groups = _adapt(spec)
    selected_families = (
        tuple(generate_strip_families(spec)) if families is None else tuple(families)
    )
    templates: dict[StripFamilyId, StripVariant] = {}
    for family in selected_families:
        if not family.variants:
            continue
        template = default_strip_variant(family)
        required_pitch = minimum_pitch_x.get(strip_pose_id(template))
        if required_pitch is not None:
            template = variant_with_minimum_pitch(template, required_pitch)
        templates[family.family_id] = template

    strips: list[Strip] = []
    for family in selected_families:
        inputs_above = tuple(
            lane.items
            for lane in sorted(family.input_lanes, key=lambda lane: lane.side_index)
            if lane.side == "south"
        )
        inputs_below = tuple(
            lane.items
            for lane in sorted(family.input_lanes, key=lambda lane: lane.side_index)
            if lane.side == "north"
        )
        outputs = tuple(
            (
                lane.items[0],
                DEST_SEP.join(lane.destination_group_keys),
                lane.cargo_domain,
            )
            for lane in sorted(family.output_lanes, key=lambda lane: lane.side_index)
        )
        group = groups[family.group_key]
        needs_coater_keepout = any(
            lane.cargo_domain is CargoDomain.REQUIRES_SPRAY for lane in family.input_lanes
        )
        realized: tuple[tuple[int, int, StripVariant | None], ...]
        if family.variants:
            template = templates[family.family_id]
            instances = partition_strip_variant(
                family,
                template,
                max_machine_count=max(1, strip_len),
            )
            realized = tuple(
                (
                    instance.machine_start,
                    instance.machine_count,
                    instance.variant,
                )
                for instance in instances
            )
        else:
            # Compatibility only: a mode-driven building with no sorter poses
            # still reaches emission, which owns the established structured
            # refusal.  It has no physical StripVariant and must not be exposed
            # to projection feedback or sequence search as though it did.
            capped_len = max(1, strip_len)
            if family.machine_cap > 0:
                capped_len = min(capped_len, family.machine_cap)
            instance_count = max(1, math.ceil(family.total_machine_count / capped_len))
            base, extra = divmod(family.total_machine_count, instance_count)
            machine_counts = tuple(
                base + (1 if index < extra else 0) for index in range(instance_count)
            )
            machine_start = 0
            realized_list: list[tuple[int, int, StripVariant | None]] = []
            for machine_count in machine_counts:
                realized_list.append((machine_start, machine_count, None))
                machine_start += machine_count
            realized = tuple(realized_list)
        for machine_start, machine_count, physical_variant in realized:
            _check_shared_lane_capacity(
                group,
                inputs_above + inputs_below,
                machine_count,
                spec,
            )
            lane_plan: LanePlan | None
            attachment_plan: tuple[LaneAttachmentPlan, ...]
            port_dock_plan: tuple[LanePortDockPlan, ...]
            if physical_variant is None:
                footprint_width = group.width
                footprint_height = group.height
                yaw = group.yaw
                building = catalog.building(family.machine_item_id)
                port_inputs = bool(
                    (inputs_above or inputs_below)
                    and building.takes_belt_ports
                    and not building.slot_poses
                )
                # Port-input branches occupy the pitch column immediately east
                # of each machine.  Keep one more column so adjacent machine
                # colliders remain disjoint after spherical projection.
                pitch_width = group.pitch_w + int(family.flank_outputs or port_inputs)
                pitch_height = group.pitch_h
                lane_plan = None
                attachment_plan = ()
                port_dock_plan = ()
                box_height = (
                    len(inputs_above)
                    + int(bool(inputs_above) and port_inputs)
                    + pitch_height
                    + len(outputs)
                    + len(inputs_below)
                )
            else:
                footprint_width = physical_variant.footprint_width
                footprint_height = physical_variant.footprint_height
                yaw = physical_variant.yaw
                pitch_width = physical_variant.pitch_x
                pitch_height = physical_variant.pitch_y
                lane_plan = physical_variant.lane_plan
                attachment_plan = physical_variant.attachment_plan
                port_dock_plan = physical_variant.port_dock_plan
                box_height = physical_variant.box_height
            west_channel = _COATER_WEST_CHANNEL if needs_coater_keepout else WEST_CHANNEL
            selected = Strip(
                group_key=family.group_key,
                recipe_id=family.recipe_id,
                item_id=family.machine_item_id,
                model_index=family.model_index,
                cargo_domain=(
                    CargoDomain.REQUIRES_SPRAY if group.proliferated else CargoDomain.UNSPRAYED
                ),
                machines=machine_count,
                mw=footprint_width,
                mh=footprint_height,
                yaw=yaw,
                pw=pitch_width,
                ph=pitch_height,
                in_above=inputs_above,
                out_lanes=outputs,
                in_below=inputs_below,
                lane_plan=lane_plan,
                attachment_plan=attachment_plan,
                port_dock_plan=port_dock_plan,
                box_height=box_height,
                physical_variant=physical_variant,
                mode_params=family.mode_params,
                flank_outputs=family.flank_outputs,
                family_id=family.family_id,
                machine_start=machine_start,
                west_channel=west_channel,
            )
            strips.append(selected)
    clearance_keys = tuple(_staged_static_clearance_keys(strip) for strip in strips)
    unresolved = tuple(
        dict.fromkeys(
            relation
            for relations in clearance_keys
            for relation in relations
            if relation not in minimum_staged_static_clearance
        )
    )
    precleared: frozenset[StagedStaticClearanceKey] = frozenset()
    if unresolved:
        exact_relations = tuple(
            candidate
            for relation in unresolved
            for candidate in (
                relation,
                replace(relation, delta_x=relation.delta_x + 1),
            )
        )
        if cancelled is not None and cancelled():
            raise _PreparationDeadline
        token = _STAGED_STATIC_PROOF_CANCELLED.set(cancelled)
        try:
            exact_risks = _staged_static_relation_projection_risks(
                exact_relations,
                band_policy,
            )
        finally:
            _STAGED_STATIC_PROOF_CANCELLED.reset(token)
        precleared = frozenset(
            relation
            for ordinal, relation in enumerate(unresolved)
            if exact_risks[2 * ordinal] and not exact_risks[2 * ordinal + 1]
        )
    return [
        replace(
            strip,
            west_channel=max(
                (
                    minimum_staged_static_clearance[relation]
                    if relation in minimum_staged_static_clearance
                    else (
                        _COATER_WEST_CHANNEL + 1 if relation in precleared else _COATER_WEST_CHANNEL
                    )
                    for relation in relations
                ),
                default=strip.west_channel,
            ),
        )
        for strip, relations in zip(strips, clearance_keys, strict=True)
    ]


_COARSE_STRIP_THRESHOLD = 40


def _coarsen_saturated_strip_plan(
    spec: BuildSpec,
    strips: list[Strip],
    *,
    strip_len: int,
    band_policy: BandPolicy = _DEFAULT_BAND_POLICY,
    minimum_pitch_x: Mapping[StripPoseId, int] = _NO_PITCH_REQUIREMENTS,
    families: Sequence[StripFamily] | None = None,
    minimum_staged_static_clearance: Mapping[
        StagedStaticClearanceKey,
        int,
    ] = _NO_STAGED_STATIC_CLEARANCE,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[list[Strip], int]:
    """Repartition redundant stress strips before packing or routing."""
    if len(strips) < _COARSE_STRIP_THRESHOLD or strip_len >= spec.machine_count:
        return strips, strip_len
    coarse_len = max(strip_len, spec.machine_count)
    return (
        plan_strips(
            spec,
            strip_len=coarse_len,
            band_policy=band_policy,
            minimum_pitch_x=minimum_pitch_x,
            families=families,
            minimum_staged_static_clearance=minimum_staged_static_clearance,
            cancelled=cancelled,
        ),
        coarse_len,
    )


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


@dataclass(frozen=True, order=True, slots=True)
class DirectInsertId:
    """Exact strip net whose belt route the packer promised to replace."""

    source_strip: int
    destination_strip: int
    item: str
    cargo_domain: CargoDomain

    @property
    def net_id(self) -> NetId:
        """The corresponding detailed-router identity."""
        return NetId(
            source_strip=self.source_strip,
            destination_strip=self.destination_strip,
            item=self.item,
            role=NetRole.INTERNAL,
            ordinal=0,
            cargo_domain=self.cargo_domain,
        )


@dataclass(frozen=True, slots=True)
class _DirectCandidate:
    """A net a single sorter could replace, and its proved legal alignments.

    ``prod_row`` and ``cons_row`` are offsets from each strip's origin to the
    lane row the sorter would span. ``origin_deltas`` are consumer-minus-
    producer strip-origin x offsets with at least one occupied column that no
    sorter already seated on either lane meets.
    """

    item: str
    cargo_domain: CargoDomain
    prod_row: int
    cons_row: int
    #: Belt tiles each lane occupies, counted east from its strip's west edge.
    #: The sorter needs a column both lanes cover, and an input lane is trimmed
    #: to its last sorter, so the consumer's span is usually SHORTER than its
    #: strip.
    prod_span: int
    cons_span: int
    origin_deltas: tuple[int, ...]


def _direct_clear_columns(
    strip: Strip,
    plan: LaneAttachmentPlan,
    span: int,
) -> frozenset[int]:
    """Occupied lane columns clear of every sorter already seated on the lane.

    A bridge is vertical and a strip sorter leaves that same lane vertically in
    the opposite direction. Their seated colliders can intersect only when they
    share the lane column: sorter bodies are narrower than one tile, while the
    end extension is along their run. Excluding the exact planned attachment
    columns therefore proves the collider precondition before CP-SAT can reward
    the candidate.
    """
    occupied = set(range(span))
    occupied.difference_update(
        machine * strip.pw + attachment.column
        for machine in range(strip.machines)
        for attachment in plan.attachments
    )
    return frozenset(occupied)


def _packed_nonzero_digits(
    packed: Sequence[int],
    coefficient_bytes: int,
    digit_count: int,
) -> bytearray:
    """Mark non-zero fixed-width digits with one linear packed-byte scan."""
    present = bytearray(digit_count)
    for byte_offset, value in enumerate(packed):
        if value:
            present[byte_offset // coefficient_bytes] = 1
    return present


def _direct_column_deltas(
    source_columns: Sequence[int],
    destination_columns: Sequence[int],
) -> tuple[int, ...]:
    """Compose two sorted column sets into their exact difference set.

    The naïve run-pair formulation creates one interval for every source and
    destination run. Alternating occupied/attachment columns make both run
    counts linear in strip width, so that intermediate becomes quadratic even
    though every possible delta lies in one linear-size integer range.

    Treat each column set as a polynomial with a one at every occupied column,
    reverse the destination polynomial, and multiply them. A non-zero
    coefficient proves at least one exact source/destination pair for that
    delta. Coefficients are packed in base ``2 ** (8 * coefficient_bytes)``;
    choosing a base greater than the maximum pair count prevents carries, so
    Python's exact integer multiplication is also an exact convolution.
    """
    if not source_columns or not destination_columns:
        return ()

    source_min = source_columns[0]
    source_max = source_columns[-1]
    destination_min = destination_columns[0]
    destination_max = destination_columns[-1]
    source_degree = source_max - source_min
    destination_degree = destination_max - destination_min
    max_pair_count = min(len(source_columns), len(destination_columns))
    coefficient_bytes = max(1, (max_pair_count.bit_length() + 7) // 8)
    assert max_pair_count < 1 << (8 * coefficient_bytes)

    source_coefficients = bytearray((source_degree + 1) * coefficient_bytes)
    for column in source_columns:
        source_coefficients[(column - source_min) * coefficient_bytes] = 1

    destination_coefficients = bytearray((destination_degree + 1) * coefficient_bytes)
    for column in destination_columns:
        destination_coefficients[(destination_max - column) * coefficient_bytes] = 1

    product_digit_count = source_degree + destination_degree + 1
    product = int.from_bytes(source_coefficients, "little") * int.from_bytes(
        destination_coefficients, "little"
    )
    product_bytes = product.to_bytes(
        product_digit_count * coefficient_bytes,
        "little",
    )
    present = _packed_nonzero_digits(
        product_bytes,
        coefficient_bytes,
        product_digit_count,
    )

    delta_origin = source_min - destination_max
    return tuple(delta_origin + degree for degree, pair_count in enumerate(present) if pair_count)


def _direct_origin_deltas(
    source: Strip,
    destination: Strip,
    source_lane: int,
    item: str,
) -> tuple[int, ...]:
    """Consumer origin offsets with an occupied, sorter-clear shared column."""
    try:
        source_plan = source._output_attachment_plan(source_lane)
        destination_plan = destination._input_attachment_plan(item)
    except IndexError, KeyError:
        return ()
    source_columns = sorted(_direct_clear_columns(source, source_plan, source.width))
    destination_span = destination.input_lane_tiles(destination.lane_of_input(item))
    destination_columns = sorted(
        _direct_clear_columns(
            destination,
            destination_plan,
            destination_span,
        )
    )
    if not source_columns or not destination_columns:
        return ()

    return _direct_column_deltas(source_columns, destination_columns)


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
        if src.takes_belt_ports or (src.recipe_id, dst.recipe_id) not in eligible:
            continue
        lane = next(
            (
                (k, item)
                for k, (item, dest, cargo_domain) in enumerate(src.out_lanes)
                if cargo_domain is CargoDomain.UNSPRAYED and dst.group_key in _dests(dest)
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
        origin_deltas = _direct_origin_deltas(src, dst, k, item)
        if not origin_deltas:
            # With no occupied lane column clear of both strips' already seated
            # sorters, emission cannot prove a bridge. Do not create a Boolean:
            # an absent variable cannot earn the direct-insert reward.
            continue
        out[i, j] = _DirectCandidate(
            item=item,
            prod_row=src.row_of_output(k),
            cons_row=dst.row_of_input(item),
            prod_span=src.width,
            cons_span=dst.input_lane_tiles(dst.lane_of_input(item)),
            cargo_domain=CargoDomain.UNSPRAYED,
            origin_deltas=origin_deltas,
        )
    return out


@dataclass(frozen=True, slots=True, eq=False)
class _DirectCandidateSnapshot:
    """Immutable direct-net geometry owned by one exact strip plan."""

    strips: tuple[Strip, ...]
    candidates: Mapping[tuple[int, int], _DirectCandidate]

    def __post_init__(self) -> None:
        if not isinstance(self.strips, tuple):
            raise ValueError("direct candidates must retain an immutable strip plan")
        object.__setattr__(
            self,
            "candidates",
            MappingProxyType(dict(self.candidates)),
        )

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, _DirectCandidateSnapshot)
            and self.matches(other.strips)
            and self.candidates == other.candidates
        )

    def __hash__(self) -> int:
        return hash(
            (
                tuple(id(strip) for strip in self.strips),
                tuple(sorted(self.candidates.items())),
            )
        )

    def matches(self, strips: Sequence[Strip]) -> bool:
        """Whether ``strips`` contains the exact physical port owners retained."""
        return len(self.strips) == len(strips) and all(
            retained is current for retained, current in zip(self.strips, strips, strict=True)
        )


def _direct_candidate_snapshot(
    strips: list[Strip],
    spec: BuildSpec,
    *,
    enabled: bool,
) -> _DirectCandidateSnapshot:
    """Enumerate direct candidates once and bind them to their physical plan."""
    return _DirectCandidateSnapshot(
        tuple(strips),
        _direct_net_candidates(strips, spec) if enabled else {},
    )


def _direct_alignment_targets(
    candidates: Mapping[tuple[int, int], _DirectCandidate],
) -> tuple[DirectInsertTarget, ...]:
    """Expose candidate lane geometry as immutable placement-alignment inputs."""
    return tuple(
        DirectInsertTarget(
            key=key,
            producer=key[0],
            consumer=key[1],
            producer_row=candidate.prod_row,
            consumer_row=candidate.cons_row,
            producer_span=candidate.prod_span,
            consumer_span=candidate.cons_span,
            origin_deltas=candidate.origin_deltas,
        )
        for key, candidate in sorted(candidates.items())
    )


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


type _ExactRetrySource = Literal["power", "seating", "finalizer"]
type _ExactRetryBuildingSignature = tuple[
    int,
    int,
    Fraction,
    int,
    int,
    float,
    int | None,
]


@dataclass(frozen=True, slots=True)
class _ExactRetryEvidence:
    """Assignment-independent identity of one exact projected relation."""

    source: _ExactRetrySource
    check: str
    relation: tuple[tuple[int, _ExactRetryBuildingSignature], ...]


@dataclass(frozen=True, slots=True)
class _ExactRetryKey:
    """One proof-scoped retry token for a configured pack candidate."""

    height: int
    arrangement: int
    evidence: _ExactRetryEvidence


def _exact_retry_evidence(
    source: _ExactRetrySource,
    failure: finalize.ProjectionFailure,
    buildings: Mapping[int, PlacedBuilding],
) -> _ExactRetryEvidence | None:
    """Drop assignment coordinates while retaining the implicated exact relation."""
    relation: list[tuple[int, _ExactRetryBuildingSignature]] = []
    for index in failure.buildings:
        building = buildings.get(index)
        if building is None:
            return None
        relation.append(
            (
                index,
                (
                    building.item_id,
                    building.model_index,
                    building.z,
                    building.width,
                    building.height,
                    building.yaw,
                    building.owner_strip,
                ),
            )
        )
    if not relation:
        return None
    return _ExactRetryEvidence(
        source=source,
        check=failure.check,
        relation=tuple(relation),
    )


@dataclass(frozen=True, slots=True)
class ExactProjectionPair:
    """The two physical strips implicated by one exact projection refusal."""

    left_strip: int
    right_strip: int
    left_geometry: finalize.ProjectionGeometrySignature
    right_geometry: finalize.ProjectionGeometrySignature

    def __post_init__(self) -> None:
        if self.left_strip < 0 or self.left_strip >= self.right_strip:
            raise ValueError("exact projection pair requires two ordered strips")
        if not self.left_geometry or not self.right_geometry:
            raise ValueError("exact projection pair requires physical signatures")


@dataclass(frozen=True, slots=True)
class ExactPackNoGood:
    """One immutable full packed assignment rejected by exact evidence."""

    height: int
    outline: tuple[tuple[int, int], ...]
    width: int
    origins: tuple[tuple[int, int], ...]
    evidence: tuple[finalize.ProjectionFailure, ...]
    projection_pair: ExactProjectionPair | None = None

    def __post_init__(self) -> None:
        if self.height <= 0 or self.width <= 0:
            raise ValueError("exact pack dimensions must be positive")
        if len(self.outline) != len(self.origins):
            raise ValueError("exact pack outline and origins must cover every strip")
        if not self.evidence:
            raise ValueError("exact pack no-good requires structured evidence")


@dataclass(slots=True)
class _ExactPackNoGoodState:
    """Deduplicated exact cuts plus the bounded retry tokens they justified."""

    no_goods: list[ExactPackNoGood] = field(default_factory=list)
    no_good_keys: set[ExactPackNoGood] = field(default_factory=set)
    retry_keys: set[_ExactRetryKey] = field(default_factory=set)
    retried_candidates: set[tuple[int, int]] = field(default_factory=set)

    def remember(self, no_good: ExactPackNoGood) -> bool:
        if no_good in self.no_good_keys:
            return False
        self.no_good_keys.add(no_good)
        self.no_goods.append(no_good)
        return True

    def admit_retry(
        self,
        key: _ExactRetryKey,
        no_good: ExactPackNoGood,
        *,
        affordable: bool,
    ) -> bool:
        candidate = (key.height, key.arrangement)
        if (
            not affordable
            or candidate in self.retried_candidates
            or key in self.retry_keys
            or no_good in self.no_good_keys
        ):
            return False
        self.retried_candidates.add(candidate)
        self.retry_keys.add(key)
        self.no_good_keys.add(no_good)
        self.no_goods.append(no_good)
        return True


@dataclass(frozen=True, slots=True)
class _DirectRelationNoGood:
    """One proved-impossible direct promise at one endpoint relation."""

    direct_id: DirectInsertId
    delta_x: int
    delta_y: int


@dataclass
class _Pack:
    """Strip origins chosen by the packer."""

    at: dict[int, tuple[int, int]]
    width: int
    height: int
    status: str
    hit_budget: bool = False
    #: Exact nets the packer rewarded for replacing with one sorter.
    direct: frozenset[DirectInsertId] = frozenset()


def _strip_geometry_signature(
    strip: Strip,
) -> finalize.ProjectionGeometrySignature:
    """Return every immutable strip field that determines physical emission."""
    return (
        strip.item_id,
        strip.model_index,
        strip.cargo_domain,
        strip.machines,
        strip.mw,
        strip.mh,
        strip.yaw,
        strip.pw,
        strip.ph,
        strip.in_above,
        strip.out_lanes,
        strip.in_below,
        strip.lane_plan,
        strip.attachment_plan,
        strip.box_height,
        (strip.physical_variant.variant_id if strip.physical_variant is not None else None),
        strip.port_dock_plan,
        strip.mode_params,
        strip.flank_outputs,
        strip.family_id,
        strip.machine_start,
        strip.west_channel,
    )


def _projection_strip_pair(
    placement: Placement,
    failure: finalize.ProjectionFailure,
) -> tuple[int, int] | None:
    """Map exact static evidence to two distinct physical strip owners."""
    if failure.check != "geom.collide" or len(failure.buildings) != 2:
        return None
    left_building, right_building = failure.buildings
    if not 0 <= left_building < len(placement.buildings) or not 0 <= right_building < len(
        placement.buildings
    ):
        return None
    left_strip = placement.buildings[left_building].owner_strip
    right_strip = placement.buildings[right_building].owner_strip
    if type(left_strip) is not int or type(right_strip) is not int or left_strip == right_strip:
        return None
    return (left_strip, right_strip) if left_strip < right_strip else (right_strip, left_strip)


def _exact_projection_pair(
    strips: Sequence[Strip],
    strip_pair: tuple[int, int],
) -> ExactProjectionPair | None:
    """Retain an implicated pair only when both physical strips still exist."""
    left_strip, right_strip = strip_pair
    if not 0 <= left_strip < right_strip < len(strips):
        return None
    return ExactProjectionPair(
        left_strip=left_strip,
        right_strip=right_strip,
        left_geometry=_strip_geometry_signature(strips[left_strip]),
        right_geometry=_strip_geometry_signature(strips[right_strip]),
    )


def _projection_no_good(
    placement: Placement,
    pack: _Pack,
    strips: Sequence[Strip],
    failure: finalize.ProjectionFailure,
    policy: BandPolicy,
) -> ProjectionNoGood | None:
    """Map a pair-local universal static collision to two packed strips."""
    strip_pair = _projection_strip_pair(placement, failure)
    if strip_pair is None:
        return None
    left_strip, right_strip = strip_pair
    if (
        left_strip not in pack.at
        or right_strip not in pack.at
        or not 0 <= left_strip < len(strips)
        or not 0 <= right_strip < len(strips)
    ):
        return None
    left_building, right_building = failure.buildings
    proved = finalize.independent_projection_pair(
        (
            (left_building, placement.buildings[left_building]),
            (right_building, placement.buildings[right_building]),
        ),
        policy,
    )
    if proved is None:
        return None
    left_x, left_y = pack.at[left_strip]
    right_x, right_y = pack.at[right_strip]
    return ProjectionNoGood(
        left_strip=left_strip,
        right_strip=right_strip,
        delta_x=left_x - right_x,
        delta_y=left_y - right_y,
        pack_width=pack.width,
        pack_height=pack.height,
        left_origin=(left_x, left_y),
        right_origin=(right_x, right_y),
        left_geometry=_strip_geometry_signature(strips[left_strip]),
        right_geometry=_strip_geometry_signature(strips[right_strip]),
        failure=failure,
    )


def _projection_pitch_requirements(
    placement: Placement,
    strips: list[Strip],
    failures: tuple[finalize.ProjectionFailure, ...],
) -> tuple[ProjectionPitchRequirement | None, ...]:
    """Map ordered Freeform failures through one realized-strip placement index."""
    from flab2bp.layout.strip_variants import (
        StripInstanceId,
        projection_pitch_requirements,
    )

    instance_ids: list[StripInstanceId] = []
    variants: list[StripVariant] = []
    for strip in strips:
        if strip.family_id is None or strip.physical_variant is None:
            return (None,) * len(failures)
        instance_ids.append(
            StripInstanceId(
                strip.family_id,
                strip.machine_start,
                strip.machines,
            )
        )
        variants.append(strip.physical_variant)
    return projection_pitch_requirements(
        placement,
        instance_ids=tuple(instance_ids),
        variants=tuple(variants),
        failures=failures,
    )


def _staged_static_clearance_requirement(
    strip: Strip,
    owner_strip: int,
    failure: finalize.ProjectionFailure,
    relation: StagedStaticClearanceKey,
) -> StagedStaticClearanceRequirement | None:
    """Describe the next one-tile west attachment for one physical relation."""
    from flab2bp.layout.strip_variants import StripInstanceId

    variant_id = strip.staged_static_variant_id
    if (
        strip.family_id is None
        or variant_id is None
        or owner_strip < 0
        or failure.check != "geom.collide"
    ):
        return None
    return StagedStaticClearanceRequirement(
        instance_id=StripInstanceId(
            strip.family_id,
            strip.machine_start,
            strip.machines,
        ),
        variant_id=variant_id,
        owner_strip=owner_strip,
        rejected_west_channel=strip.west_channel,
        required_west_channel=strip.west_channel + 1,
        relation=relation,
        evidence=(failure,),
    )


def _nets_between(strips: list[Strip]) -> list[tuple[int, int]]:
    """Strip index pairs that will need a belt route."""
    by_group: dict[str, list[int]] = defaultdict(list)
    for i, s in enumerate(strips):
        by_group[s.group_key].append(i)
    nets: set[tuple[int, int]] = set()
    for i, strip in enumerate(strips):
        for _item, destination, _cargo_domain in strip.out_lanes:
            for group_key in _dests(destination):
                for j in by_group.get(group_key, []):
                    if i != j:
                        nets.add((i, j))
    return sorted(nets)


def _greedy_pack(strips: list[Strip], height: int) -> _Pack:
    """Shelf packing -- always succeeds, and seeds the solver's upper bound.

    A deterministic seed, not a loose fallback.  It bounds `_pack`'s width from
    above and hints its variables.  `_sweep` may route it in place of the first
    exact incumbent only after that incumbent proves the seed fits the existing
    width-slack cap; a failed solve can never return it.
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
        at[i] = (shelf_x + s.west_channel, shelf_y)
        shelf_y += h
        shelf_h = max(shelf_h, w)
        width = max(width, shelf_x + w)
    return _Pack(at=at, width=width, height=height, status="greedy")


def _add_exact_pack_no_good(
    model: cp_model.CpModel,
    width: cp_model.IntVar,
    xs: Sequence[cp_model.IntVar],
    ys: Sequence[cp_model.IntVar],
    strips: Sequence[Strip],
    no_good: ExactPackNoGood,
) -> None:
    """Forbid the one complete assignment named by ``no_good``."""
    if len(no_good.origins) != len(strips):
        raise ValueError("exact pack no-good must retain every strip origin")
    variables = [width]
    values = [no_good.width]
    for strip_index, origin in enumerate(no_good.origins):
        variables.extend((xs[strip_index], ys[strip_index]))
        values.extend(
            (
                origin[0] - strips[strip_index].west_channel,
                origin[1],
            )
        )
    model.add_forbidden_assignments(variables, [tuple(values)])


def _add_cluster_relation_no_good(
    model: cp_model.CpModel,
    xs: Sequence[cp_model.IntVar],
    ys: Sequence[cp_model.IntVar],
    strips: Sequence[Strip],
    height: int,
    width_bound: int,
    index: int,
    no_good: ClusterRelationNoGood,
) -> None:
    """Forbid one RELATIVE placement: at least one cluster strip must move.

    Unlike :func:`_add_exact_pack_no_good`, which removes a single point, this
    removes every translation of the proved relation -- which is exactly what
    the proof supports, because the CBS run behind it removed every other belt
    and so said nothing about where the cluster sits, only how its strips sit
    relative to one another.
    """
    anchor = no_good.strips[0]
    if any(strip >= len(strips) for strip in no_good.strips):
        return
    variables: list[cp_model.IntVar] = []
    values: list[int] = []
    for position, strip_index in enumerate(no_good.strips[1:], start=1):
        relation_x = model.new_int_var(
            -width_bound,
            width_bound,
            f"cluster_ng{index}_dx{position}",
        )
        relation_y = model.new_int_var(-height, height, f"cluster_ng{index}_dy{position}")
        model.add(
            relation_x
            == (xs[strip_index] + strips[strip_index].west_channel)
            - (xs[anchor] + strips[anchor].west_channel)
        )
        model.add(relation_y == ys[strip_index] - ys[anchor])
        variables.extend((relation_x, relation_y))
        values.extend(no_good.deltas[position])
    model.add_forbidden_assignments(variables, [tuple(values)])


def _add_projection_no_good(
    model: cp_model.CpModel,
    width: cp_model.IntVar,
    xs: Sequence[cp_model.IntVar],
    ys: Sequence[cp_model.IntVar],
    strips: Sequence[Strip],
    no_good: ProjectionNoGood,
) -> None:
    """Forbid one proved pair while preserving unrelated-strip freedom."""
    left = no_good.left_strip
    right = no_good.right_strip
    if (
        _strip_geometry_signature(strips[left]) != no_good.left_geometry
        or _strip_geometry_signature(strips[right]) != no_good.right_geometry
    ):
        return
    variables = [width, xs[left], ys[left], xs[right], ys[right]]
    values = [
        no_good.pack_width,
        no_good.left_origin[0] - strips[left].west_channel,
        no_good.left_origin[1],
        no_good.right_origin[0] - strips[right].west_channel,
        no_good.right_origin[1],
    ]
    model.add_forbidden_assignments(variables, [values])


@dataclass(frozen=True, slots=True)
class _FeedbackObjectiveEvidence:
    """One exact physical net and the route evidence that may move its endpoints."""

    net_id: NetId
    weight: int
    source_offset: Cell
    destination_offset: Cell
    hot_cells: tuple[tuple[Cell, int], ...]


def _feedback_objective_evidence(
    feedback: FeedbackState,
    *,
    strip_count: int,
) -> tuple[_FeedbackObjectiveEvidence, ...]:
    """Keep exact net identities separate when translating feedback to CP terms."""
    evidence: list[_FeedbackObjectiveEvidence] = []
    ordered = sorted(
        feedback.net_weight.items(),
        key=lambda pair: (
            -1 if pair[0].source_strip is None else pair[0].source_strip,
            -1 if pair[0].destination_strip is None else pair[0].destination_strip,
            pair[0].item,
            pair[0].cargo_domain.value,
            pair[0].role.value,
            pair[0].ordinal,
        ),
    )
    for net, weight in ordered:
        if (
            net.source_strip is None
            or net.destination_strip is None
            or not 0 <= net.source_strip < strip_count
            or not 0 <= net.destination_strip < strip_count
            or (offsets := feedback.endpoint_offsets.get(net)) is None
            or weight <= 0.0
        ):
            continue
        source_offset, destination_offset = offsets
        hot_cells = tuple(
            (cell, max(1, math.ceil(history)))
            for cell, history in sorted(feedback.net_cell_history.get(net, {}).items())
            if history > 0.0
        )
        evidence.append(
            _FeedbackObjectiveEvidence(
                net_id=net,
                weight=max(1, math.ceil(weight)),
                source_offset=source_offset,
                destination_offset=destination_offset,
                hot_cells=hot_cells,
            )
        )
    return tuple(evidence)


def _feedback_objective_score(
    evidence: tuple[_FeedbackObjectiveEvidence, ...],
    origins: tuple[tuple[int, int], ...],
    outline: tuple[int, int],
) -> int:
    """Evaluate the same exact-net evidence tier for one concrete assignment."""
    max_distance = outline[0] + outline[1]
    score = 0
    for term in evidence:
        source_strip = term.net_id.source_strip
        destination_strip = term.net_id.destination_strip
        if source_strip is None or destination_strip is None:
            continue
        source = (
            origins[source_strip][0] + term.source_offset[0],
            origins[source_strip][1] + term.source_offset[1],
        )
        destination = (
            origins[destination_strip][0] + term.destination_offset[0],
            origins[destination_strip][1] + term.destination_offset[1],
        )
        score += term.weight * (abs(source[0] - destination[0]) + abs(source[1] - destination[1]))
        for (wall_x, wall_y, _level), history in term.hot_cells:
            wall_distance = (
                abs(source[0] - wall_x)
                + abs(source[1] - wall_y)
                + abs(destination[0] - wall_x)
                + abs(destination[1] - wall_y)
            )
            score += term.weight * history * max(0, max_distance - wall_distance)
    return score


#: Wall limit of one fix-and-reoptimize window solve.  A window is affordable
#: exactly because it is not a full pack: the full solve on the largest cells
#: gets `share * _PACK_SHARE / len(heights)` and is followed by a 1.9-4.6 s
#: preparation, so a repair that costs more than a second buys nothing.
C_WINDOW_SECONDS = 1.0
#: Deterministic work bound for a window solve.  A full pack of fifteen or more
#: strips gets `_DETERMINISTIC_PACK_WORK` and is expected to stop at its first
#: incumbent from a shelf warm start; a window has at most twelve free strips
#: but no such guarantee, and is expected to close a small model, so it gets
#: twenty-five times that allowance.  On an idle box this is the limit that
#: fires; under `--jobs 16` the wall limit above fires first.
C_WINDOW_DETERMINISTIC_WORK = 25 * _DETERMINISTIC_PACK_WORK
#: One CP-SAT worker per window.  `pyproject.toml` records that a single solve
#: already runs at ~700% CPU; a window must not race the packer for cores.
C_WINDOW_WORKERS = 1
#: Margin a window solve keeps between itself and the run deadline.
C_WINDOW_DEADLINE_SAFETY_SECONDS = 0.05


@dataclass(frozen=True, slots=True)
class _PackModel:
    """One built packing model and the handles a caller needs to read it back."""

    model: cp_model.CpModel
    w_var: cp_model.IntVar
    xs: list[cp_model.IntVar]
    ys: list[cp_model.IntVar]
    direct_vars: dict[tuple[int, int], cp_model.IntVar]
    sizes: list[tuple[int, int]]
    #: No-goods dropped because a pinned strip contradicted them or because they
    #: named no free strip.  Adding either would constrain the sub-model for a
    #: reason outside the window.
    skipped_no_goods: int


def _pack_model(
    strips: list[Strip],
    *,
    height: int,
    width_bound: int,
    direct_candidates: Mapping[tuple[int, int], _DirectCandidate],
    fixed_at: Mapping[int, tuple[int, int]] = MappingProxyType({}),
    width_target: int | None = None,
    projection_no_goods: tuple[ProjectionNoGood, ...] = (),
    exact_pack_no_goods: tuple[ExactPackNoGood, ...] = (),
    direct_relation_no_goods: tuple[_DirectRelationNoGood, ...] = (),
    cluster_relation_no_goods: tuple[ClusterRelationNoGood, ...] = (),
    feedback: FeedbackState | None = None,
    seed: _Pack | None = None,
) -> _PackModel | None:
    """Build the packing model, optionally with some strips pinned in place.

    ``fixed_at`` maps a strip index to its CONTENT origin -- the same convention
    ``_Pack.at`` uses -- and pins that strip by giving its ``x``/``y`` variables a
    singleton domain.  A singleton domain rather than a constant expression is
    deliberate: every constraint below is then written by the SAME code for a
    pinned strip as for a free one, so the window model is provably the full
    model with fewer degrees of freedom rather than a second formulation that
    has to be kept in step.  With ``fixed_at`` empty this is exactly the model
    ``_pack`` has always built.
    """
    model = cp_model.CpModel()
    n = len(strips)
    skipped = 0
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
        pinned = fixed_at.get(i)
        if pinned is None:
            x = model.new_int_var(0, max(0, width_bound - w), f"x{i}")
            y = model.new_int_var(0, max(0, height - h), f"y{i}")
        else:
            bx = pinned[0] - strips[i].west_channel
            by = pinned[1]
            if not (0 <= bx <= max(0, width_bound - w)) or not (0 <= by <= max(0, height - h)):
                return None  # the pin is outside this outline; nothing to repair here
            x = model.new_int_var(bx, bx, f"x{i}")
            y = model.new_int_var(by, by, f"y{i}")
        xs.append(x)
        ys.append(y)
        x_iv.append(model.new_fixed_size_interval_var(x, w, f"xi{i}"))
        y_iv.append(model.new_fixed_size_interval_var(y, h, f"yi{i}"))
        model.add(x + w <= w_var)

    model.add_no_overlap_2d(x_iv, y_iv)

    def _no_good_is_live(named: Iterable[int], origins: Iterable[tuple[int, int]]) -> bool:
        """Is this no-good worth adding to a model with pinned strips?

        No, twice over.  If a pinned strip already sits somewhere else, the
        forbidden tuple is unreachable and the constraint is dead weight.  If
        every strip it names is pinned, its only free variable is ``w_var`` and
        it would forbid a WIDTH for no geometric reason.
        """
        named = tuple(named)
        origins = tuple(origins)
        if all(index in fixed_at for index in named):
            return False
        for index, origin in zip(named, origins, strict=True):
            current = fixed_at.get(index)
            if current is not None and current != origin:
                return False
        return True

    def _cluster_no_good_is_live(no_good: ClusterRelationNoGood) -> bool:
        """ONE rejection, and it is not the one :func:`_no_good_is_live` makes.

        A cluster no-good names offsets rather than origins, so it never names
        an absolute position on its own.  What it does fix is where the ANCHOR
        would have to sit for any one strip to satisfy it: subtract that strip's
        delta from its pinned content origin.  Two pinned strips that imply
        different anchors therefore contradict the relation outright, and no
        placement of the strips still free can complete it -- the constraint is
        dead weight whether or not the anchor itself is one of the pinned ones.
        That, and only that, is what this skips.

        There is deliberately NO "every named strip is pinned" rejection here,
        which is where this differs from its sibling.  That rejection exists so
        an exact-pack no-good cannot forbid a WIDTH for no geometric reason, and
        the reason does not carry over: :func:`_add_cluster_relation_no_good`
        never touches ``w_var``.  Its relation variables are differences of
        content origins, so a fully pinned cluster whose pins AGREE with the
        forbidden offsets is not a degenerate constraint -- it is the statement
        that this pack already sits in the relative placement Phase B proved
        unroutable, and CP-SAT should say INFEASIBLE.  "This window cannot
        repair the incumbent" is the truthful answer; silently dropping the cut
        would hand back the arrangement the proof rejected.
        """
        implied: tuple[int, int] | None = None
        for index, delta in zip(no_good.strips, no_good.deltas, strict=True):
            current = fixed_at.get(index)
            if current is None:
                continue
            anchor = (current[0] - delta[0], current[1] - delta[1])
            if implied is not None and anchor != implied:
                return False
            implied = anchor
        return True

    for exact_no_good in exact_pack_no_goods:
        if exact_no_good.height != height or exact_no_good.outline != tuple(sizes):
            continue
        if not _no_good_is_live(range(n), exact_no_good.origins):
            skipped += 1
            continue
        _add_exact_pack_no_good(model, w_var, xs, ys, strips, exact_no_good)

    for cluster_index, cluster_no_good in enumerate(cluster_relation_no_goods):
        if cluster_no_good.height != height or cluster_no_good.outline != tuple(sizes):
            continue
        if not _cluster_no_good_is_live(cluster_no_good):
            skipped += 1
            continue
        _add_cluster_relation_no_good(
            model,
            xs,
            ys,
            strips,
            height,
            width_bound,
            cluster_index,
            cluster_no_good,
        )

    for projection_no_good in projection_no_goods:
        if (
            projection_no_good.left_strip == projection_no_good.right_strip
            or not 0 <= projection_no_good.left_strip < n
            or not 0 <= projection_no_good.right_strip < n
        ):
            raise ValueError("projection no-good must name two distinct packed strips")
        if projection_no_good.pack_height != height:
            continue
        if not _no_good_is_live(
            (projection_no_good.left_strip, projection_no_good.right_strip),
            (projection_no_good.left_origin, projection_no_good.right_origin),
        ):
            skipped += 1
            continue
        _add_projection_no_good(model, w_var, xs, ys, strips, projection_no_good)

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
            if i in fixed_at or j in fixed_at:
                continue
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
        # Reward only exact x offsets with a witness column that is occupied by
        # both lanes and clear of every sorter already seated on either lane.
        # Encoding the witness set here keeps an unprovable candidate out of the
        # objective instead of letting emission discover the missing precondition
        # after the reward has already influenced the pack.
        origin_delta = (xs[j] + strips[j].west_channel) - (xs[i] + strips[i].west_channel)
        permitted_delta = model.new_int_var_from_domain(
            cp_model.Domain.from_values(cand.origin_deltas),
            f"direct_dx{i}_{j}",
        )
        model.add(origin_delta == permitted_delta).only_enforce_if(di)
        direct_vars[i, j] = di

    for no_good_index, relation_no_good in enumerate(direct_relation_no_goods):
        direct = relation_no_good.direct_id
        pair = (direct.source_strip, direct.destination_strip)
        candidate = direct_candidates.get(pair)
        direct_var = direct_vars.get(pair)
        if (
            candidate is None
            or direct_var is None
            or candidate.item != direct.item
            or candidate.cargo_domain is not direct.cargo_domain
        ):
            continue
        if pair[0] in fixed_at and pair[1] in fixed_at:
            skipped += 1
            continue
        relation_x = model.new_int_var(
            -width_bound,
            width_bound,
            f"direct_ng_dx{no_good_index}",
        )
        relation_y = model.new_int_var(
            -height,
            height,
            f"direct_ng_dy{no_good_index}",
        )
        model.add(
            relation_x
            == (xs[pair[1]] + strips[pair[1]].west_channel)
            - (xs[pair[0]] + strips[pair[0]].west_channel)
        )
        model.add(relation_y == ys[pair[1]] - ys[pair[0]])
        model.add_forbidden_assignments(
            [direct_var, relation_x, relation_y],
            [(1, relation_no_good.delta_x, relation_no_good.delta_y)],
        )

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
    base_tier = LAMBDA_HPWL * sum(terms) + MU_DIRECT * missed
    evidence = () if feedback is None else _feedback_objective_evidence(feedback, strip_count=n)
    evidence_terms: list[cp_model.LinearExpr] = []
    max_distance = width_bound + height
    for evidence_index, term in enumerate(evidence):
        source_strip = term.net_id.source_strip
        destination_strip = term.net_id.destination_strip
        if source_strip is None or destination_strip is None:
            continue
        source_x = xs[source_strip] + strips[source_strip].west_channel + term.source_offset[0]
        source_y = ys[source_strip] + term.source_offset[1]
        destination_x = (
            xs[destination_strip]
            + strips[destination_strip].west_channel
            + term.destination_offset[0]
        )
        destination_y = ys[destination_strip] + term.destination_offset[1]
        dx = model.new_int_var(0, width_bound, f"feedback_dx{evidence_index}")
        dy = model.new_int_var(0, height, f"feedback_dy{evidence_index}")
        model.add_abs_equality(dx, source_x - destination_x)
        model.add_abs_equality(dy, source_y - destination_y)
        evidence_terms.append(term.weight * (dx + dy))
        for wall_index, ((wall_x, wall_y, _level), history) in enumerate(term.hot_cells):
            distances: list[cp_model.IntVar] = []
            for label, coordinate, wall, upper in (
                ("sx", source_x, wall_x, width_bound),
                ("sy", source_y, wall_y, height),
                ("dx", destination_x, wall_x, width_bound),
                ("dy", destination_y, wall_y, height),
            ):
                distance = model.new_int_var(
                    0,
                    upper,
                    f"feedback_wall_{label}{evidence_index}_{wall_index}",
                )
                model.add_abs_equality(distance, coordinate - wall)
                distances.append(distance)
            proximity = model.new_int_var(
                0,
                max_distance,
                f"feedback_hot{evidence_index}_{wall_index}",
            )
            model.add_max_equality(
                proximity,
                [0, max_distance - sum(distances)],
            )
            evidence_terms.append(term.weight * history * proximity)
    if not evidence_terms:
        model.minimize(w_var * cap + base_tier)
    else:
        evidence_cap = (width_bound + 1) * cap
        model.minimize(sum(evidence_terms) * evidence_cap + w_var * cap + base_tier)

    # Warm start.  The seed is feasible at this height by construction, so its
    # width bounds `w_var` from above and its positions give the search an
    # incumbent to improve on rather than one to find.  Values are clamped into
    # each variable's domain: an out-of-domain hint is not a tighter hint, it is
    # a discarded one.
    if seed is not None:
        if feedback is None:
            model.add(w_var <= min(seed.width, width_bound))
        for i, (hx, hy) in seed.at.items():
            if i >= n or i in fixed_at:
                continue
            w, h = sizes[i]
            # `seed.at` is a CONTENT origin and `xs` is a BOX origin, so the
            # west channel comes back off before the hint is offered. An
            # out-by-one hint is not a weaker hint, it is a hint for a packing
            # that overlaps.
            model.add_hint(
                xs[i],
                min(
                    max(hx - strips[i].west_channel, 0),
                    max(0, width_bound - w),
                ),
            )
            model.add_hint(ys[i], min(max(hy, 0), max(0, height - h)))

    if width_target is not None:
        if all(
            fixed_at[index][0] - strips[index].west_channel + sizes[index][0] <= width_target
            for index in fixed_at
        ):
            model.add(w_var <= width_target)
        else:
            # A pinned strip already reaches past the target, so the bound cannot
            # be added without making the sub-model infeasible for a reason
            # outside the window.  Count it: a target that never applies is a
            # repair aimed at nothing, and the gate must be able to see that.
            skipped += 1

    return _PackModel(
        model=model,
        w_var=w_var,
        xs=xs,
        ys=ys,
        direct_vars=direct_vars,
        sizes=sizes,
        skipped_no_goods=skipped,
    )


def _pack_result(
    built: _PackModel,
    solver: cp_model.CpSolver,
    strips: Sequence[Strip],
    direct_candidates: Mapping[tuple[int, int], _DirectCandidate],
    height: int,
    admission: cp_model.CpSolverSolutionCallback | None,
) -> _Pack | None:
    """Solve one built model and read its assignment back as a `_Pack`."""
    status = solver.Solve(built.model, admission)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None
    return _Pack(
        at={
            i: (solver.Value(built.xs[i]) + strips[i].west_channel, solver.Value(built.ys[i]))
            for i in range(len(strips))
        },
        width=solver.Value(built.w_var),
        height=height,
        status=solver.StatusName(status),
        hit_budget=status == cp_model.FEASIBLE,
        direct=frozenset(
            DirectInsertId(
                i,
                j,
                direct_candidates[i, j].item,
                direct_candidates[i, j].cargo_domain,
            )
            for (i, j), di in built.direct_vars.items()
            if solver.Value(di)
        ),
    )


def _pack_window(
    strips: list[Strip],
    *,
    height: int,
    width_bound: int,
    direct_candidates: Mapping[tuple[int, int], _DirectCandidate],
    window: frozenset[int],
    fixed_at: Mapping[int, tuple[int, int]],
    seed: _Pack | None = None,
    width_target: int | None = None,
    arrangement: int = 0,
    projection_no_goods: tuple[ProjectionNoGood, ...] = (),
    exact_pack_no_goods: tuple[ExactPackNoGood, ...] = (),
    direct_relation_no_goods: tuple[_DirectRelationNoGood, ...] = (),
    cluster_relation_no_goods: tuple[ClusterRelationNoGood, ...] = (),
    feedback: FeedbackState | None = None,
    time_budget_s: float = C_WINDOW_SECONDS,
    deterministic_work: float = C_WINDOW_DETERMINISTIC_WORK,
    on_skipped: Callable[[int], None] | None = None,
) -> _Pack | None:
    """Re-solve `_pack`'s formulation for ``window`` with everything else pinned.

    This is a sub-model, not a re-solve: every strip, constraint, no-good and
    objective term of the full model is present, and only the pinned strips'
    domains are collapsed.  `test_pack_window_over_every_strip_reproduces_the_full_pack`
    pins that claim by asking for the whole problem as the window, with no seed
    on either side, and comparing against `_pack`.

    ``width_bound`` is the incumbent's width, so a window may NARROW the block
    and can never widen it.

    Returns ``None`` only when the sub-model is infeasible or the solve returns
    no incumbent.  An assignment identical to the seed's is returned as-is: the
    caller decides what that means, because "the window found nothing better" is
    a signal, not an error.
    """
    if not window:
        raise ValueError("a repair window must name at least one strip")
    if any(index in fixed_at for index in window):
        raise ValueError("window strips must not also be pinned")
    if set(fixed_at) | window != set(range(len(strips))):
        raise ValueError("window and pinned strips must cover every strip")
    if time_budget_s <= 0:
        return None
    built = _pack_model(
        strips,
        height=height,
        width_bound=width_bound,
        direct_candidates=direct_candidates,
        fixed_at=fixed_at,
        width_target=width_target,
        projection_no_goods=projection_no_goods,
        exact_pack_no_goods=exact_pack_no_goods,
        direct_relation_no_goods=direct_relation_no_goods,
        cluster_relation_no_goods=cluster_relation_no_goods,
        feedback=feedback,
        seed=seed,
    )
    if built is None:
        return None
    if on_skipped is not None and built.skipped_no_goods:
        on_skipped(built.skipped_no_goods)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_budget_s
    # One worker and a deterministic-work bound, always: a window runs BESIDE a
    # packer that already saturates the box, and its result must not depend on
    # wall time except through the wall limit above firing as a hard deadline.
    solver.parameters.num_search_workers = C_WINDOW_WORKERS
    solver.parameters.max_deterministic_time = min(time_budget_s, deterministic_work)
    # A function of `arrangement` and nothing else -- see `_pack`.
    solver.parameters.random_seed = _PACK_RANDOM_SEED + _ARRANGEMENT_STRIDE * arrangement
    return _pack_result(built, solver, strips, direct_candidates, height, None)


def _decoded_from_pack(pack: _Pack, strips: Sequence[Strip], height: int) -> DecodedPlacement:
    """View one packed assignment as a decoded placement for the destroy operators.

    `_Pack.at` holds CONTENT origins and a decoded placement holds BOX origins,
    so the west channel comes back off -- each strip's own, because channels
    differ from strip to strip and a single shared subtraction would move two
    thirds of a pack.  The coordinate windows are degenerate (each equals its
    coordinate) because a packed assignment has no slack left to describe:
    nothing downstream of a destroy operator reads them.

    `height` is the outline the pack was solved at.  It is carried for symmetry
    with the other two adapters and deliberately not used to clamp anything: a
    decoded placement reports the height its own boxes reach, not the one it was
    allowed.
    """
    sizes = [_box(strip) for strip in strips]
    xs = tuple(pack.at[index][0] - strips[index].west_channel for index in range(len(strips)))
    ys = tuple(pack.at[index][1] for index in range(len(strips)))
    return DecodedPlacement(
        x=xs,
        y=ys,
        width=pack.width,
        used_height=max((ys[index] + sizes[index][1] for index in range(len(strips))), default=0),
        x_windows=tuple((value, value) for value in xs),
        y_windows=tuple((value, value) for value in ys),
        gap_area=0,
    )


def _pack_relation_problem(pack: _Pack, strips: Sequence[Strip], height: int) -> PlacementProblem:
    """A placement problem carrying this pack's sizes and nets, for operator reuse.

    ``logical_net_ids`` is left empty on purpose.  No shipped destroy operator
    reads it, and `_nets_between` returns bare strip-index pairs with no item
    identity, so filling it would mean synthesizing `LogicalNetId`s nothing
    consumes.  The operator that would need them (RELATED_CARGO) is a follow-up,
    and populating this field belongs to that operator's task.

    `pack` is taken for the signature the spec declares and for the day an
    adapter needs the assignment; the problem itself is a property of the strips
    and the outline, not of where this particular solve put them.
    """
    sizes = tuple(_box(strip) for strip in strips)
    return PlacementProblem(
        sizes=sizes,
        nets=tuple(_nets_between(list(strips))),
        outline_height=height,
        area_lower_bound=sum(width * box_height for width, box_height in sizes),
    )


def _pack_relation_pair(pack: _Pack, strips: Sequence[Strip], height: int) -> SequencePair:
    """The sequence pair this pack encodes to, for the sequence-neighbour operator.

    Its gaps are zero by construction, so `select_lns_neighbourhood`'s
    gap-rectangle branch never fires on a freeform pack: the neighbourhood there
    is failure endpoints plus sequence neighbours only.

    Only the pair is returned, and only the pair is safe to use: `encode_placement`
    reports `exact=False` on most placements with slack, so its decode is a
    compaction of this pack and not this pack.  A caller that wants coordinates
    wants `_decoded_from_pack`, or must score the encoder's decode itself.
    """
    decoded = _decoded_from_pack(pack, strips, height)
    return encode_placement(
        tuple(_box(strip) for strip in strips),
        decoded.x,
        decoded.y,
        outline_height=height,
    ).pair


def _pack(
    strips: list[Strip],
    *,
    height: int,
    width_bound: int,
    time_budget_s: float,
    direct_candidates: Mapping[tuple[int, int], _DirectCandidate],
    workers: int,
    deterministic: bool = False,
    seed: _Pack | None = None,
    arrangement: int = 0,
    projection_no_goods: tuple[ProjectionNoGood, ...] = (),
    exact_pack_no_goods: tuple[ExactPackNoGood, ...] = (),
    direct_relation_no_goods: tuple[_DirectRelationNoGood, ...] = (),
    cluster_relation_no_goods: tuple[ClusterRelationNoGood, ...] = (),
    feedback: FeedbackState | None = None,
    stop_when_seed_admissible: bool = False,
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
    built = _pack_model(
        strips,
        height=height,
        width_bound=width_bound,
        direct_candidates=direct_candidates,
        projection_no_goods=projection_no_goods,
        exact_pack_no_goods=exact_pack_no_goods,
        direct_relation_no_goods=direct_relation_no_goods,
        cluster_relation_no_goods=cluster_relation_no_goods,
        feedback=feedback,
        seed=seed,
    )
    if built is None or time_budget_s <= 0:
        return None
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_budget_s
    # Determinism is load-bearing for the bake-off: multi-worker CP-SAT would
    # make the A-vs-B comparison noise rather than measurement.
    solver.parameters.num_search_workers = workers
    if deterministic:
        # A single CP-SAT worker removes portfolio races, but a wall-clock
        # cutoff can still return a different incumbent under CPU contention.
        # Deterministic time counts solver work instead, while the wall limit
        # above remains the hard deadline if the machine cannot finish it.
        solver.parameters.max_deterministic_time = min(
            time_budget_s,
            _DETERMINISTIC_PACK_WORK,
        )
    # A FUNCTION of `arrangement`, never a clock or a counter: two runs of the
    # same sweep must ask for the same arrangements in the same order, or the
    # bake-off is comparing samples rather than strategies.
    solver.parameters.random_seed = _PACK_RANDOM_SEED + _ARRANGEMENT_STRIDE * arrangement

    # Bound outside the callback: a closure over `built` would carry its
    # `| None` into the class body, where the narrowing above does not reach.
    w_var = built.w_var

    class SeedAdmission(cp_model.CpSolverSolutionCallback):
        """End this solve once its exact incumbent admits the routed seed."""

        def on_solution_callback(self) -> None:
            assert seed is not None
            if seed.width <= _width_slack_cap(self.Value(w_var)):
                self.StopSearch()

    admission = SeedAdmission() if stop_when_seed_admissible and seed is not None else None
    return _pack_result(built, solver, strips, direct_candidates, height, admission)


# --- emission --------------------------------------------------------------


def _collision_pose(building: PlacedBuilding) -> colliders.Placed:
    return colliders.Placed(
        building.model_index,
        *codec.tile_to_local_offset(
            building.x,
            building.y,
            building.z,
            building.width,
            building.height,
        ),
        building.yaw,
    )


def _building_collider_hits(
    buildings: Sequence[PlacedBuilding],
    candidate: PlacedBuilding,
) -> tuple[int, ...]:
    """Exact static build-collider hits for one proposed non-belt object."""
    try:
        candidate_span = max(catalog.collider_span(candidate.item_id, candidate.yaw))
    except KeyError, ValueError:
        candidate_span = max(candidate.width, candidate.height) * colliders.GRID_ARC
    candidate_x = candidate.x + (candidate.width - 1) / 2.0
    candidate_y = candidate.y + (candidate.height - 1) / 2.0
    obstacles: list[tuple[int, PlacedBuilding]] = []
    for index, building in enumerate(buildings):
        if catalog.is_belt(building.item_id) or catalog.is_sorter(building.item_id):
            continue
        try:
            obstacle_span = max(catalog.collider_span(building.item_id, building.yaw))
        except KeyError, ValueError:
            obstacle_span = max(building.width, building.height) * colliders.GRID_ARC
        radius = (candidate_span + obstacle_span) / (2.0 * colliders.GRID_ARC) + 3.0
        obstacle_x = building.x + (building.width - 1) / 2.0
        obstacle_y = building.y + (building.height - 1) / 2.0
        if (
            math.hypot(
                candidate_x - obstacle_x,
                candidate_y - obstacle_y,
            )
            <= radius
        ):
            obstacles.append((index, building))
    if not obstacles:
        return ()
    poses = [
        _collision_pose(candidate),
        *(_collision_pose(building) for _index, building in obstacles),
    ]
    hits: set[int] = set()
    for left, right in colliders.collisions(poses):
        if left == 0 and right:
            hits.add(obstacles[right - 1][0])
        elif right == 0 and left:
            hits.add(obstacles[left - 1][0])
    return tuple(sorted(hits))


def _coater_keepout_hits(
    buildings: Sequence[PlacedBuilding],
    candidate: PlacedBuilding,
) -> tuple[int, ...]:
    """Objects intersecting the coater body or its observed lateral keepout.

    A user-reported game paste rejects a coater at ``(13, 7)`` beside an
    Assembling Machine whose 3x3 tile box begins at ``(13, 8)``.  The flat OBB
    lower bound leaves a narrow gap, but the full coater preview visibly clips
    the machine and the paste reports ``Collide with other object``.  Reserve
    the one-cell lateral row around the coater's real oriented 3x1 body; do not
    inflate its long axis, where its predecessor and successor must stand.
    """
    width, height = catalog.oriented_footprint(
        catalog.SPRAY_COATER_ID,
        candidate.yaw,
    )
    x0 = candidate.x - (width - 1) // 2
    y0 = candidate.y - (height - 1) // 2
    x1 = x0 + width - 1
    y1 = y0 + height - 1
    if width >= height:
        y0 -= 1
        y1 += 1
    else:
        x0 -= 1
        x1 += 1

    try:
        candidate_span = max(catalog.collider_span(candidate.item_id, candidate.yaw))
    except KeyError, ValueError:
        candidate_span = max(candidate.width, candidate.height) * colliders.GRID_ARC
    candidate_x = candidate.x + (candidate.width - 1) / 2.0
    candidate_y = candidate.y + (candidate.height - 1) / 2.0
    hits: set[int] = set()
    collider_candidates: list[tuple[int, PlacedBuilding]] = []
    for index, building in enumerate(buildings):
        is_belt = catalog.is_belt(building.item_id)
        is_sorter = catalog.is_sorter(building.item_id)
        if is_belt or is_sorter:
            continue
        try:
            info = catalog.building(building.item_id)
        except KeyError:
            info = None
        if (
            building.z == candidate.z
            and info is not None
            and info.occupies_tiles
            and x0 <= building.x + building.width - 1
            and building.x <= x1
            and y0 <= building.y + building.height - 1
            and building.y <= y1
        ):
            hits.add(index)
            continue
        try:
            obstacle_span = max(catalog.collider_span(building.item_id, building.yaw))
        except KeyError, ValueError:
            obstacle_span = max(building.width, building.height) * colliders.GRID_ARC
        radius = (candidate_span + obstacle_span) / (2.0 * colliders.GRID_ARC) + 3.0
        obstacle_x = building.x + (building.width - 1) / 2.0
        obstacle_y = building.y + (building.height - 1) / 2.0
        if (
            math.hypot(
                candidate_x - obstacle_x,
                candidate_y - obstacle_y,
            )
            <= radius
        ):
            collider_candidates.append((index, building))
    if collider_candidates:
        poses = [
            _collision_pose(candidate),
            *(_collision_pose(building) for _index, building in collider_candidates),
        ]
        for left, right in colliders.collisions(poses):
            if left == 0 and right:
                hits.add(collider_candidates[right - 1][0])
            elif right == 0 and left:
                hits.add(collider_candidates[left - 1][0])
    return tuple(sorted(hits))


def _splitter_stack_geometry(
    x: int,
    y: int,
    level: int,
    *,
    carry_direction: tuple[int, int] | None = None,
) -> tuple[PlacedBuilding, ...]:
    """Exact members of the stack serving one routing carry level."""
    direction = carry_direction
    if level % 2 and direction is None:
        # Model 40's collider is a rotationally symmetric cross.  Static
        # preparation has no path direction yet, so use one cardinal yaw; the
        # materialized junction replaces it with the actual carry direction.
        direction = (0, 1)
    return junction.make_splitter_stack(
        x,
        y,
        level,
        first_index=0,
        carry_direction=direction,
    )


def _power_coverage_discs(
    buildings: Sequence[PlacedBuilding],
    tesla_sites: Sequence[tuple[int, int]],
) -> tuple[tuple[int, int, int], ...]:
    """Exact doubled-coordinate power discs available during detailed routing."""
    tower = catalog.building(catalog.TESLA_TOWER_ID)
    discs = [
        (
            2 * x + tower.width,
            2 * y + tower.height,
            math.floor((2 * tower.cover_radius) ** 2),
        )
        for x, y in tesla_sites
    ]
    for building in buildings:
        try:
            info = catalog.building(building.item_id)
        except KeyError:
            continue
        if info.cover_radius <= 0:
            continue
        discs.append(
            (
                2 * building.x + building.width,
                2 * building.y + building.height,
                math.floor((2 * info.cover_radius) ** 2),
            )
        )
    return tuple(discs)


def _buildings_are_powered(
    buildings: Sequence[PlacedBuilding],
    discs: Sequence[tuple[int, int, int]],
) -> bool:
    """Whether every tile of every powered candidate lies inside one supply disc."""
    return all(
        any((2 * tx + 1 - cx) ** 2 + (2 * ty + 1 - cy) ** 2 <= radius2 for cx, cy, radius2 in discs)
        for building in buildings
        for tx, ty, _tz in building.tiles()
    )


def _junction_site_is_clear(
    buildings: Sequence[PlacedBuilding],
    x: int,
    y: int,
    level: int,
) -> bool:
    """Does every real stack member clear every non-belt static object?"""
    return all(
        not _building_collider_hits(buildings, splitter)
        for splitter in _splitter_stack_geometry(x, y, level)
    )


JunctionOffsetKey = tuple[int, int, int, int, float, Fraction]

#: Relative Splitter bans per immutable obstacle pose, shared by every attempt
#: and both computation paths in this process.  An offset set is a pure
#: function of its key, so a value proved once under a deadline is exactly
#: the value the uncancellable path would return.
_JUNCTION_BAN_OFFSET_CACHE: dict[JunctionOffsetKey, frozenset[Cell]] = {}


@lru_cache(maxsize=256)
def _junction_ban_offsets(
    item_id: int,
    model_index: int,
    width: int,
    height: int,
    yaw: float,
    z: Fraction,
) -> frozenset[Cell]:
    """Exact relative Splitter bans for one immutable obstacle pose."""
    key: JunctionOffsetKey = (item_id, model_index, width, height, yaw, z)
    cached = _JUNCTION_BAN_OFFSET_CACHE.get(key)
    if cached is not None:
        return cached
    obstacle = PlacedBuilding(
        item_id=item_id,
        model_index=model_index,
        x=0,
        y=0,
        z=z,
        width=width,
        height=height,
        yaw=yaw,
    )
    splitter_span = max(catalog.collider_span(catalog.SPLITTER_ID, 0.0))
    try:
        obstacle_span = max(catalog.collider_span(item_id, yaw))
    except KeyError, ValueError:
        obstacle_span = max(width, height) * colliders.GRID_ARC
    radius = math.ceil((splitter_span + obstacle_span) / (2.0 * colliders.GRID_ARC)) + 2
    centre_x = (width - 1) / 2.0
    centre_y = (height - 1) / 2.0
    banned = frozenset(
        (x, y, level)
        for x in range(
            math.floor(centre_x - radius),
            math.ceil(centre_x + radius) + 1,
        )
        for y in range(
            math.floor(centre_y - radius),
            math.ceil(centre_y + radius) + 1,
        )
        for level in range(LEVELS)
        if not _junction_site_is_clear((obstacle,), x, y, level)
    )
    _JUNCTION_BAN_OFFSET_CACHE[key] = banned
    return banned


def _cancellable_junction_ban_offsets(
    item_id: int,
    model_index: int,
    width: int,
    height: int,
    yaw: float,
    z: Fraction,
    cancelled: Callable[[], bool],
) -> frozenset[Cell]:
    """Compute one uncached complete offset set while polling its caller."""
    key: JunctionOffsetKey = (item_id, model_index, width, height, yaw, z)
    cached = _JUNCTION_BAN_OFFSET_CACHE.get(key)
    if cached is not None:
        return cached
    obstacle = PlacedBuilding(
        item_id=item_id,
        model_index=model_index,
        x=0,
        y=0,
        z=z,
        width=width,
        height=height,
        yaw=yaw,
    )
    splitter_span = max(catalog.collider_span(catalog.SPLITTER_ID, 0.0))
    try:
        obstacle_span = max(catalog.collider_span(item_id, yaw))
    except KeyError, ValueError:
        obstacle_span = max(width, height) * colliders.GRID_ARC
    radius = math.ceil((splitter_span + obstacle_span) / (2.0 * colliders.GRID_ARC)) + 2
    centre_x = (width - 1) / 2.0
    centre_y = (height - 1) / 2.0
    banned: set[Cell] = set()
    for x in range(
        math.floor(centre_x - radius),
        math.ceil(centre_x + radius) + 1,
    ):
        if cancelled():
            raise _PreparationDeadline
        for y in range(
            math.floor(centre_y - radius),
            math.ceil(centre_y + radius) + 1,
        ):
            if cancelled():
                raise _PreparationDeadline
            for level in range(LEVELS):
                if cancelled():
                    raise _PreparationDeadline
                if not _junction_site_is_clear((obstacle,), x, y, level):
                    banned.add((x, y, level))
    if cancelled():
        raise _PreparationDeadline
    result = frozenset(banned)
    _JUNCTION_BAN_OFFSET_CACHE[key] = result
    return result


def _prepared_junction_ban(
    buildings: Sequence[PlacedBuilding],
    power_sites: Sequence[tuple[int, int]],
    *,
    projection_frames: Sequence[_JunctionProjectionFrame] = (),
    junction_bounds: tuple[int, int, int, int] | None = None,
    cancelled: Callable[[], bool] | None = None,
    cache: _StagedStaticCache | None = None,
) -> frozenset[Cell]:
    """Precompute exact flat and projected Splitter refusals."""
    obstacles: list[PlacedBuilding] = []
    for building in buildings:
        if cancelled is not None and cancelled():
            raise _PreparationDeadline
        if not catalog.is_belt(building.item_id) and not catalog.is_sorter(building.item_id):
            obstacles.append(building)
    tower = catalog.building(catalog.TESLA_TOWER_ID)
    for x, y in power_sites:
        if cancelled is not None and cancelled():
            raise _PreparationDeadline
        obstacles.append(
            PlacedBuilding(
                item_id=catalog.TESLA_TOWER_ID,
                model_index=tower.model_index,
                x=x,
                y=y,
                width=tower.width,
                height=tower.height,
            )
        )

    banned: set[Cell] = set()
    offset_cache = {} if cache is None else cache.junction_offsets
    for obstacle in obstacles:
        if cancelled is not None and cancelled():
            raise _PreparationDeadline
        offset_key = (
            obstacle.item_id,
            obstacle.model_index,
            obstacle.width,
            obstacle.height,
            obstacle.yaw,
            obstacle.z,
        )
        offsets = offset_cache.get(offset_key)
        if offsets is None:
            offsets = (
                _junction_ban_offsets(*offset_key)
                if cancelled is None
                else _cancellable_junction_ban_offsets(*offset_key, cancelled)
            )
            if cancelled is not None and cancelled():
                raise _PreparationDeadline
            offset_cache[offset_key] = offsets
        for dx, dy, level in offsets:
            if cancelled is not None and cancelled():
                raise _PreparationDeadline
            banned.add((obstacle.x + dx, obstacle.y + dy, level))

    coaters: list[tuple[int, PlacedBuilding]] = []
    for index, building in enumerate(buildings):
        if cancelled is not None and cancelled():
            raise _PreparationDeadline
        if building.item_id == catalog.SPRAY_COATER_ID:
            coaters.append((index, building))
    if coaters and projection_frames:
        if junction_bounds is None:
            raise ValueError("projected junction bans require fixed junction bounds")
        for frame_ban in _projected_coater_junction_bans_by_frame(
            coaters,
            projection_frames,
            junction_bounds,
            already_banned=banned,
            splitter_index=len(buildings),
            cancelled=cancelled,
        ):
            banned.update(frame_ban)
    if cancelled is not None and cancelled():
        raise _PreparationDeadline
    return frozenset(banned)


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
    #: Sorter tiers this save can build, slowest first.  Every sorter the
    #: emitter picks comes from this tuple; see :func:`_pick_sorter`.
    sorter_tiers: tuple[int, ...] = catalog.SORTER_TIERS

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

    #: ``cell -> port (x, y, level)``: one way in or out, held for that port's nets.
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
    reserved: dict[tuple[int, int, int], tuple[int, int, int]] = field(default_factory=dict)
    #: Ports the net currently being routed owns; it may use their reservations.
    routing_ports: frozenset[tuple[int, int, int]] = frozenset()
    #: Complete corridors still held for each port. Routing retires one corridor
    #: when its source or destination role acquires a path, and restores it if
    #: that role's last path is ripped up.
    port_corridors: dict[Cell, tuple[PortAccessCorridor, ...]] = field(default_factory=dict)
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
    #: Exact static Splitter collision refusals, cached by actual routing level.
    #: Reserved power nodes are included even though their buildings are emitted
    #: only after routing.
    junction_ban: set[Cell] = field(default_factory=set)
    junction_geometry_prepared: bool = False

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

    def junction_is_clear(self, x: int, y: int, level: int) -> bool:
        """Apply exact legality to every real member of a junction stack."""
        if (x, y, level) in self.junction_ban:
            return False
        buildings = (
            [building for building in self.buildings if building.item_id == catalog.SPLITTER_ID]
            if self.junction_geometry_prepared
            else self.buildings
        )
        return all(
            not _building_collider_hits(buildings, stack_member)
            for stack_member in _splitter_stack_geometry(x, y, level)
        )

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

    def free_owned_guard(self, cell: Cell) -> bool:
        """Is ``cell`` blocked only by a junction guard this route owns?

        A selected future Splitter reserves its branch docks before sibling
        nets route.  Those siblings may start on one exact dock; every other
        guard remains a wall.  Keep this separate from :meth:`free` so ordinary
        routing can never accidentally weaken junction collision protection.
        """
        x, y, z = cell
        if cell not in self.guard or cell in self.blocked or (x, y) in self.keep_out:
            return False
        if z in self.belt_ban.get((x, y), ()):
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


def _sorter_tiers_for(spec: BuildSpec) -> tuple[int, ...]:
    """The spec's allowed sorter tiers as catalog ids, slowest first.

    Catalog order rather than spec order, so the picker's "cheapest first"
    walk holds whatever order the spec listed them in.  A spec naming no
    sorter the catalog knows falls back to every tier: an unknown id is a
    dataset mismatch, not a save that can build nothing.
    """
    allowed = {catalog.get_item_id(item_id) for item_id in spec.sorter_item_ids}
    return tuple(tier for tier in catalog.SORTER_TIERS if tier in allowed) or catalog.SORTER_TIERS


def _pick_sorter(
    rate: Fraction,
    span: int,
    machines: int,
    tiers: tuple[int, ...] = catalog.SORTER_TIERS,
) -> tuple[int, int]:
    """Cheapest allowed sorter tier and count carrying ``rate`` across ``span``.

    Reach is three tiles for every tier, so tiers differ only in throughput --
    there is never a reason to pay for a higher tier than the rate needs.
    ``tiers`` is what the save can build, slowest first; when none carries the
    rate the fastest allowed one is returned and ``flow.sorter_capacity``
    refuses the placement, rather than emitting a tier the save cannot build.
    """
    per_machine = rate / machines if machines else rate
    for tier in tiers:
        if catalog.sorter_rate(tier, span) >= per_machine:
            return tier, machines
    return tiers[-1], machines


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
    cargo_domain: CargoDomain = CargoDomain.UNSPRAYED

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
            self.cargo_domain,
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
    z: int = 0
    cargo_domain: CargoDomain = CargoDomain.UNSPRAYED


@dataclass(frozen=True, slots=True)
class CoaterSupplyPort:
    """A coater's host belt and projection-safe proliferator terminal."""

    coater: int
    host_belt: int
    approach_belt: int
    supply_belt: int
    item: str
    yaw: float
    host_x: int
    host_y: int
    host_z: int
    x: int
    y: int
    z: int


@dataclass(frozen=True, slots=True)
class _StagedCoater:
    """One fully checked Coater/terminal triple awaiting an atomic commit."""

    approach: PlacedBuilding
    supply: PlacedBuilding
    coater: PlacedBuilding
    projected_pair: tuple[int, colliders.Placed]
    port: CoaterSupplyPort


def _projected_coater_supply_failure(
    candidate: _StagedCoater,
    host: PlacedBuilding,
    projections: Sequence[planet.Projection],
    *,
    cancelled: Callable[[], bool] | None = None,
) -> finalize.ProjectionFailure | None:
    """Check a staged coater's two required belt lines before routing starts."""

    areas = catalog.building(candidate.coater.item_id).addon_areas
    belts = (
        (candidate.port.host_belt, host),
        (candidate.port.approach_belt, candidate.approach),
        (candidate.port.supply_belt, candidate.supply),
    )
    addons = ((candidate.port.coater, candidate.coater, areas),)
    # The permanent approach-to-drop link fixes the supply belt's projected
    # line before routing. Evaluate the finalizer's exact predicate across every
    # candidate frame; the route may add a predecessor to the approach, but it
    # cannot change the approach-to-drop relation measured for the addon.
    try:
        context = finalize._addon_projection_context(
            belts,
            addons,
            cancelled=cancelled,
        )
    except finalize.ProjectionCancelled:
        raise _PreparationDeadline from None
    for projection in projections:
        if cancelled is not None and cancelled():
            raise _PreparationDeadline
        try:
            failure = finalize._projected_addon_failure_from_context(
                context,
                projection,
                cancelled=cancelled,
            )
        except finalize.ProjectionCancelled:
            raise _PreparationDeadline from None
        if failure is not None:
            return failure
    return None


def _projected_coater_supply_frame_failure(
    candidate: _StagedCoater,
    host: PlacedBuilding,
    frame: _JunctionProjectionFrame,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> finalize.ProjectionFailure | None:
    """Check one coater terminal in one complete finalizer frame."""

    def materialize(building: PlacedBuilding) -> PlacedBuilding:
        return finalize.materialize_frame_building(
            building,
            bounds=frame.bounds,
            candidate=frame.candidate,
        )

    framed_coater = materialize(candidate.coater)
    framed = replace(
        candidate,
        approach=materialize(candidate.approach),
        supply=materialize(candidate.supply),
        coater=framed_coater,
        projected_pair=(
            candidate.port.coater,
            _collision_pose(framed_coater),
        ),
    )
    return _projected_coater_supply_failure(
        framed,
        materialize(host),
        frame.projections,
        cancelled=cancelled,
    )


def _projected_coater_supply_context_key(
    candidate: _StagedCoater,
    host: PlacedBuilding,
    frame: _JunctionProjectionFrame,
) -> tuple[object, ...]:
    """Exact addon-supply geometry modulo rigid longitude translation."""

    def materialize(building: PlacedBuilding) -> PlacedBuilding:
        return finalize.materialize_frame_building(
            building,
            bounds=frame.bounds,
            candidate=frame.candidate,
        )

    sources = (host, candidate.approach, candidate.supply, candidate.coater)
    framed = tuple(materialize(building) for building in sources)
    role_by_index = {
        candidate.port.host_belt: 0,
        candidate.port.approach_belt: 1,
        candidate.port.supply_belt: 2,
        candidate.port.coater: 3,
    }
    orientations = tuple(dict.fromkeys(projection.rotated for projection in frame.projections))
    geometries: list[tuple[object, ...]] = []
    for rotated in orientations:
        coater = framed[3]
        longitude_origin = coater.y if rotated else coater.x
        buildings: list[tuple[object, ...]] = []
        for source, building in zip(sources, framed, strict=True):
            longitude, latitude = (building.y, building.x) if rotated else (building.x, building.y)
            buildings.append(
                (
                    building.item_id,
                    building.model_index,
                    longitude - longitude_origin,
                    latitude,
                    building.z,
                    building.yaw,
                    role_by_index.get(source.input_obj),
                    role_by_index.get(source.output_obj),
                )
            )
        geometries.append((rotated, *buildings))
    projection_signature = tuple(
        (
            projection.band.area_segments,
            projection.anchor_row,
            projection.segment,
            projection.radius,
            projection.quadrant,
            projection.rotated,
        )
        for projection in frame.projections
    )
    return projection_signature, tuple(geometries)


def _prepare_port(port: _Port) -> _PreparedPort:
    return _PreparedPort(
        belt_index=port.belt,
        x=port.x,
        y=port.y,
        x0=port.x0,
        x1=port.x1,
        tiles=port.tiles,
        machines=port.machines,
        z=port.z,
        cargo_domain=port.cargo_domain,
    )


def _bind_prepared_port(port: _PreparedPort, buildings: list[PlacedBuilding]) -> _Port:
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
        z=port.z,
        cargo_domain=port.cargo_domain,
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
    owner_strip: int | None = None,
) -> tuple[dict[str, _Port], dict[_CargoSink, _Port], int]:
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
    out_ports: dict[_CargoSink, _Port] = {}
    width = s.width
    machine_row = s.machine_row

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
        if need and s.cargo_domain is CargoDomain.REQUIRES_SPRAY:
            need = min(max(need, 2), width)
            lane_starts_west.add(row)
        lane_tiles_of[row] = need
    for k, (item, _dest, _cargo_domain) in enumerate(s.out_lanes):
        lane_item_of[s.row_of_output(k)] = item
        lane_tiles_of[s.row_of_output(k)] = width

    lane_idx: dict[int, list[int]] = {}
    for row in range(s.height):
        y = oy + row
        if machine_row <= row < machine_row + s.mh:
            continue  # machine band
        if row not in lane_tiles_of:
            continue  # collider-pitch padding is reserved, not a belt lane
        indices = []
        start = -s.west_channel if row in lane_starts_west else 0
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
                        owner_strip=owner_strip,
                    )
                )
            )
        for a, b in zip(indices, indices[1:], strict=False):
            canvas.buildings[a] = _relink(canvas.buildings[a], output_obj=b)
        lane_idx[row] = indices

    machine_y = oy + machine_row
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
                    owner_strip=owner_strip,
                ),
                solid=True,
            )
        )

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

    def feed(lane: tuple[str, ...]) -> int:
        """Connect every machine to one input lane by its authoritative mechanism."""
        row = s.row_of_input(lane[0])
        lane_indices = lane_idx[row]
        if not lane_indices:
            name = catalog.building(s.item_id).name
            raise NoValidLayout(f"{name} has no legal connection for input lane {lane!r}")
        head = canvas.buildings[lane_indices[0]]
        port = _Port(
            lane_indices[0],
            head.x,
            oy + row,
            head.x,
            head.x + len(lane_indices) - 1,
            tuple(lane_indices),
            s.machines,
            cargo_domain=s.cargo_domain,
        )
        for item in lane:
            in_ports[item] = port
        if s.takes_belt_ports:
            if len(lane) != 1:
                name = catalog.building(s.item_id).name
                raise NoValidLayout(f"{name} cannot filter shared belt-port input lane {lane!r}")
            _dock_input_lane(
                canvas,
                machines,
                lane_indices,
                oy + row,
                lane[0],
                belt_id,
                belt_model,
                claimed,
            )
            return 0

        plan = s._input_attachment_plan(lane[0])
        placed = 0
        shared = len(lane) > 1
        for attachment in plan.attachments:
            item = attachment.item
            placed += _link_lane(
                canvas,
                lane_indices,
                machines,
                oy + row,
                attachment,
                item_rate(item, in_rates),
                into_machine=True,
                claimed=claimed,
                filter_id=_lane_filter(item) if shared else 0,
            )
        return placed

    for lane in s.in_above:
        sorters += feed(lane)

    for j, (item, dest, cargo_domain) in enumerate(s.out_lanes):
        row = s.row_of_output(j)
        out_ports[item, dest, cargo_domain] = _Port(
            lane_idx[row][-1],
            ox + width - 1,
            oy + row,
            ox,
            ox + width - 1,
            tuple(lane_idx[row]),
            s.machines,
            cargo_domain=cargo_domain,
        )
        if s.takes_belt_ports:
            _dock_lane(
                canvas,
                machines,
                lane_idx[row],
                oy + row,
                item,
                belt_id,
                belt_model,
                claimed,
                next(
                    (
                        plan
                        for plan in s.port_dock_plan
                        if plan.lane.kind == "output" and plan.lane.side_index == j
                    ),
                    None,
                ),
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
        plan = s._output_attachment_plan(j)
        sorters += _link_lane(
            canvas,
            lane_idx[row],
            machines,
            oy + row,
            plan.attachments[0],
            item_rate(item, out_rates),
            into_machine=False,
            claimed=claimed,
        )

    for lane in s.in_below:
        sorters += feed(lane)

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
                        owner_strip=m.owner_strip,
                    )
                )
            )
        for a, b in zip(column, column[1:], strict=False):
            canvas.buildings[a] = _relink(canvas.buildings[a], output_obj=b)
        canvas.buildings[column[-1]] = _relink(canvas.buildings[column[-1]], output_obj=tail)
        tier, _count = _pick_sorter(rate, got.span, 1, canvas.sorter_tiers)
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
                carries_item=item,
                owner_strip=m.owner_strip,
            )
        )
        placed += 1
    return placed


def _port_approach(
    machine: PlacedBuilding,
    dock: slots.PortDock,
    lane_y: int,
    lane_columns: Container[int],
    max_offset: int,
) -> tuple[list[tuple[int, int]], int] | None:
    """The branch cells from the input lane to ``dock``, and the column it taps.

    An L: down or up the tap column, then west along the dock's row into the
    port.  The tap column used to be fixed at ``dock.cell[0] + 1``, which is
    right for every host whose port pose clears its own build collider and
    WRONG for one whose does not.  An Energy Exchanger's east port sits two
    tiles from its centre inside a collider that reaches three, so the fixed
    column stood inside the collider for its whole length -- five tiles, of
    which the paste rescues three and convicts the rest.  That is the red belt
    in every Energy Exchanger paste.

    So the column is CHOSEN, with the paste's own predicate.  Two conditions,
    and the second is not redundant: the hits must be the run's SUFFIX, because
    ``CheckBuildConditions`` 147443 rescues by HOP DISTANCE from the host, so
    three hits scattered along a run are three convictions.
    """
    for offset in range(1, max_offset + 1):
        tap_x = dock.cell[0] + offset
        if tap_x not in lane_columns:
            continue
        cells: list[tuple[int, int]] = []
        if dock.cell[1] != lane_y:
            step = 1 if dock.cell[1] > lane_y else -1
            cells += [(tap_x, y) for y in range(lane_y + step, dock.cell[1] + step, step)]
        cells += [(x, dock.cell[1]) for x in range(tap_x - 1, dock.cell[0] - 1, -1)]
        if not cells or cells[-1] != dock.cell:
            continue
        hits = [i for i, (x, y) in enumerate(cells) if slots.belt_tile_hits_collider(machine, x, y)]
        if hits and hits != list(range(len(cells) - len(hits), len(cells))):
            continue
        if len(hits) <= slots.MAX_RESCUED_COLLIDER_TILES:
            return cells, tap_x
    return None


def _port_approach_offset(probe: PlacedBuilding, dock: slots.PortDock, pitch_w: int) -> int | None:
    """How far east of ``dock`` a lane must reach, in the PROBE frame.

    ``Strip.input_lane_tiles`` and ``_feedable_by_port`` both need the answer
    before any machine is placed, so they ask it of ``probe_building``'s
    origin-anchored copy.  ``probe.height + 1`` is the first row below the
    machine band -- a real lane row, not a width.  That distinction matters:
    the vertical leg's LENGTH changes the in-collider count, so passing a width
    here would answer a different question from the one the emitter asks and
    could pass a strip the emitter then refuses.

    This probes with ``max_offset=pitch_w`` over ``range(-pitch_w, 2 * pitch_w)``
    -- a wider, pitch-derived search than the emitter's own
    ``_port_approach(machine, ..., machine.width + 2)`` over the strip's real
    lane columns.  The two must still AGREE on the answer for a real host, and
    ``test_the_reserved_pitch_contains_the_tap_column_for_every_belt_port_host``
    is the test that checks it: offset 1 or 2 for every belt-port host at
    every yaw, and stable for a reserved pitch anywhere in ``[w, w + 4]``.

    Always probed below the machine band (``probe.height + 1``), even for an
    ``in_above`` input lane -- symmetric today because nothing here has yet
    told the two apart, not a decision that an above-band lane needs no
    different geometry.  A future host with a genuinely asymmetric north/south
    port layout would need this to ask the row it was actually given.
    """
    got = _port_approach(probe, dock, probe.height + 1, range(-pitch_w, 2 * pitch_w), pitch_w)
    return None if got is None else got[1] - dock.cell[0]


def _dock_input_lane(
    canvas: _Canvas,
    machines: list[int],
    in_lane: list[int],
    lane_y: int,
    item: str,
    belt_id: int,
    belt_model: int,
    claimed: dict[int, set[int]],
) -> int:
    """Fan one east-running lane into each machine's exact prefab input port.

    A lane tile cannot both continue east and feed a branch.  Every intermediate
    tap therefore uses :func:`_tap_source`, which materializes the game's
    splitter representation; only the final tap may point straight at its branch.
    The branch approaches an east-facing port from its open pitch column, so the
    dock belt runs west exactly opposite the port's drawing direction.
    """
    lane_by_x = {canvas.buildings[index].x: index for index in in_lane}
    placed = 0
    for machine_index in machines:
        machine = canvas.buildings[machine_index]
        taken = claimed.setdefault(machine_index, set())
        dock = next(
            (
                candidate
                for _port, candidate in sorted(slots.port_docks(machine).items())
                if candidate.port not in taken
                and candidate.facing is Facing.EAST
                and _port_approach(machine, candidate, lane_y, lane_by_x, machine.width + 2)
                is not None
            ),
            None,
        )
        if dock is None:
            name = catalog.building(machine.item_id).name
            raise NoValidLayout(
                f"{name} cannot feed {item!r} from its east-running input lane "
                "through a distinct exact belt port whose approach stays inside "
                f"the paste's {slots.MAX_RESCUED_COLLIDER_TILES}-tile collider rescue"
            )

        approach = _port_approach(machine, dock, lane_y, lane_by_x, machine.width + 2)
        if approach is None:
            # The dock filter above already asked this exact question and
            # picked `dock` because it answered `is not None` -- an `assert`
            # here would vanish under `-O` and turn this into a `TypeError` on
            # the unpack below instead of naming what actually broke.
            name = catalog.building(machine.item_id).name
            raise RuntimeError(
                f"{name} (yaw={machine.yaw}) lost its port approach between the "
                "dock filter and this unpack; _port_approach must be deterministic "
                "for the same arguments"
            )
        branch_cells, tap_x = approach
        branch: list[int] = []
        for cell_index, (x, y) in enumerate(branch_cells):
            if cell_index + 1 < len(branch_cells):
                nx, ny = branch_cells[cell_index + 1]
                delta = (nx - x, ny - y)
                facing = next(candidate for candidate in Facing if candidate.delta == delta)
            else:
                facing = dock.facing.opposite()
            branch.append(
                canvas.add(
                    PlacedBuilding(
                        item_id=belt_id,
                        model_index=belt_model,
                        x=x,
                        y=y,
                        width=1,
                        height=1,
                        yaw=facing.value,
                        carries_item=item,
                        owner_strip=machine.owner_strip,
                    )
                )
            )
        for before, after in zip(branch, branch[1:], strict=False):
            canvas.buildings[before] = _relink(canvas.buildings[before], output_obj=after)
        canvas.buildings[branch[-1]] = replace(
            canvas.buildings[branch[-1]],
            output_obj=machine_index,
            output_to_slot=dock.port,
            output_from_slot=rules.BELT_PORT_FEED_FROM_SLOT,
        )

        excused = {
            (
                canvas.buildings[index].x,
                canvas.buildings[index].y,
                int(canvas.buildings[index].z),
            )
            for index in (*in_lane, *branch)
            if canvas.buildings[index].z.denominator == 1
        }
        rejected_reason: list[str] = []
        if not _tap_source(
            canvas,
            lane_by_x[tap_x],
            branch[0],
            belt_id,
            belt_model,
            excused,
            rejected_reason=rejected_reason,
        ):
            name = catalog.building(machine.item_id).name
            raise NoValidLayout(
                f"{name} cannot split {item!r} from its shared input lane at "
                f"({tap_x}, {lane_y}) without an illegal belt fan-out "
                f"({', '.join(rejected_reason) or 'unrepresentable tap'})"
            )
        taken.add(dock.port)
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
    planned: LanePortDockPlan | None = None,
) -> int:
    """Draw each machine's product through its authoritative belt port.

    A Ray Receiver exposes no insert pose, so a sorter is not an alternative.
    The drawing belt names the host and the prefab port index; the host records
    no reciprocal link.  ``slots.port_docks`` owns the pose-to-tile rounding and
    facing, keeping emission identical for every consumer of prepared geometry.
    """
    placed = 0
    for machine_index in machines:
        machine = canvas.buildings[machine_index]
        taken = claimed.setdefault(machine_index, set())
        available = slots.port_docks(machine)
        if planned is None:
            dock = next(
                (
                    candidate
                    for _port, candidate in sorted(available.items())
                    if candidate.port not in taken
                    and candidate.facing.delta[1] > 0
                    and candidate.cell[1] < lane_y
                ),
                None,
            )
        else:
            dock = available.get(planned.port)
            expected_cell = (
                machine.x + planned.cell[0],
                machine.y + planned.cell[1],
            )
            if (
                dock is None
                or dock.port in taken
                or dock.cell != expected_cell
                or dock.facing is not planned.facing
                or machine.y + planned.lane_y != lane_y
            ):
                dock = None
        if dock is None:
            continue
        lane_tail = next(
            (index for index in out_lane if canvas.buildings[index].x == dock.cell[0]),
            None,
        )
        if lane_tail is None:
            continue

        column = [
            canvas.add(
                PlacedBuilding(
                    item_id=belt_id,
                    model_index=belt_model,
                    x=dock.cell[0],
                    y=y,
                    width=1,
                    height=1,
                    yaw=dock.facing.value,
                    carries_item=item,
                    owner_strip=machine.owner_strip,
                )
            )
            for y in range(dock.cell[1], lane_y)
        ]
        if not column:
            continue
        taken.add(dock.port)
        for before, after in zip(column, column[1:], strict=False):
            canvas.buildings[before] = _relink(canvas.buildings[before], output_obj=after)
        canvas.buildings[column[-1]] = _relink(canvas.buildings[column[-1]], output_obj=lane_tail)
        canvas.buildings[column[0]] = replace(
            canvas.buildings[column[0]],
            input_obj=machine_index,
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
    planned: LaneSorterAttachment,
    rate: Fraction,
    *,
    into_machine: bool,
    claimed: dict[int, set[int]],
    filter_id: int = 0,
) -> int:
    """Emit one sorter per machine only at the exact precomputed attachment."""
    placed = 0
    lane_by_x = {canvas.buildings[index].x: index for index in lane}
    for machine_index in machines:
        machine = canvas.buildings[machine_index]
        column = machine.x + planned.column
        expected_cell = (
            machine.x + planned.cell[0],
            machine.y + planned.cell[1],
        )
        exact = slots.attachable_columns(machine, lane_y).get(column)
        if (
            exact is None
            or exact.cell != expected_cell
            or exact.slot != planned.slot
            or exact.span != planned.span
        ):
            name = catalog.building(machine.item_id).name
            raise NoValidLayout(
                f"{name} cannot reproduce precomputed attachment for "
                f"{planned.item!r} at lane row {lane_y}"
            )
        taken = claimed.setdefault(machine_index, set())
        if planned.slot in taken:
            name = catalog.building(machine.item_id).name
            raise NoValidLayout(f"{name} slot {planned.slot} is claimed by more than one sorter")
        taken.add(planned.slot)
        belt_index = lane_by_x.get(column)
        if belt_index is None:
            raise NoValidLayout(f"lane for {planned.item!r} omits precomputed column {column}")
        tier, _count = _pick_sorter(rate, planned.span, 1, canvas.sorter_tiers)
        model_index = catalog.building(tier).model_index
        facing = Facing.SOUTH.value if lane_y < expected_cell[1] else Facing.NORTH.value
        if into_machine:
            source, destination = belt_index, machine_index
            head, tail = (column, lane_y), expected_cell
        else:
            source, destination = machine_index, belt_index
            head, tail = expected_cell, (column, lane_y)
        canvas.buildings.append(
            PlacedBuilding(
                item_id=tier,
                model_index=model_index,
                x=head[0],
                y=head[1],
                width=1,
                height=1,
                x2=tail[0],
                y2=tail[1],
                z2=Fraction(0),
                yaw=facing,
                yaw2=facing,
                input_obj=source,
                output_obj=destination,
                filter_id=filter_id,
                carries_item=planned.item,
                owner_strip=machine.owner_strip,
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

_RoutingTransition = tuple[int, int, int, int, float]


@lru_cache(maxsize=16)
def _routing_transitions(
    xstep: int,
) -> tuple[tuple[_RoutingTransition, ...], ...]:
    """Compile the current modeled movement graph for each source level.

    A transition is ``(target offset, via offset, dx, dy, base cost)``.
    ``via offset`` is zero for a flat step and names the occupied ramp-run cell
    otherwise. Detailed and relaxed routing consume this same table so later
    movement-model corrections have one boundary to replace.
    """
    ystep = LEVELS
    by_level: list[tuple[_RoutingTransition, ...]] = []
    for level in range(LEVELS):
        transitions: list[_RoutingTransition] = []
        for dx, dy in _STEPS:
            one = dx * xstep + dy * ystep
            two = 2 * one
            transitions.append((one, 0, dx, dy, 1.0 + _LEVEL_TOLL[level]))
            for level_step in (1, -1):
                next_level = level + level_step
                if 0 <= next_level < LEVELS:
                    transitions.append(
                        (
                            two + level_step,
                            one,
                            2 * dx,
                            2 * dy,
                            3.0 + _LEVEL_TOLL[next_level],
                        )
                    )
        by_level.append(tuple(transitions))
    return tuple(by_level)


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
    the paste path's ``3/4`` limit, at ANY altitude, so the ramp needs no unlock
    and is always available.

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
    #: Per-search passability scratch, exactly refreshed by :func:`_routing_flags`.
    routing_flags: bytearray
    #: ``(index, port)`` for every reserved cell inside the box.
    reserved: tuple[tuple[int, tuple[int, int, int]], ...]
    #: Congestion history as a flat array, or ``None`` on a round that has none.
    #: An :class:`array.array` when :meth:`refresh_history` built it, so the
    #: compiled loop can take a buffer of it without a copy; ``_route_all``'s
    #: crossing-repair path assigns a plain list, which :func:`_astar` converts
    #: once per search.
    hist: array[float] | list[float] | None
    #: Landmark distance fields over the 2D projection, indexed
    #: ``(x - gx0) * gh + (y - gy0)``, with ``-1`` for a column the landmark
    #: cannot reach.  Empty until :meth:`build_landmarks` is called, which only
    #: :func:`_route_all` does -- see :data:`_ALT_LANDMARKS`.
    alt: tuple[list[int], ...] = ()
    #: ``alt`` concatenated band-major into one buffer, for the compiled loop.
    #: Kept in step with ``alt`` by :meth:`build_landmarks`, which is the only
    #: thing that sets either.
    alt_flat: array[int] = field(default_factory=lambda: array("q"))

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
        acc = int.from_bytes(bytes(mv[0::LEVELS]), "big")
        for lvl in range(1, LEVELS):
            acc |= int.from_bytes(bytes(mv[lvl::LEVELS]), "big")
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
        flat = array("q")
        for field_ in fields:
            flat.extend(field_)
        self.alt_flat = flat

    def refresh_history(self, history: Mapping[tuple[int, int, int], float]) -> None:
        """Re-flatten ``history``, which changes once per rip-up round."""
        if not history:
            self.hist = None
            return
        lo_x, lo_y, hi_x, hi_y = self.box
        flat = array("d", bytes(8 * self.size))
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


def _route_box(canvas: _Canvas, bounds: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
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
        routing_flags=bytearray(size),
        reserved=reserved,
        hist=None,
    )
    grid.refresh_history(history)
    return grid


def _routing_flags(
    grid: _Grid,
    *,
    routing_ports: Collection[tuple[int, int, int]] = (),
    released_reservations: Collection[int] = (),
) -> bytearray:
    """Return hard passability with only this search's reservations opened."""
    flags = grid.routing_flags
    flags[:] = grid.occ
    released = frozenset(released_reservations)
    for at, port in grid.reserved:
        if at not in released and port not in routing_ports:
            flags[at] = 0
    return flags


@dataclass(frozen=True, slots=True)
class _PathSearchResult:
    path: tuple[Cell, ...] | None
    kind: RouteFailureKind | None
    wall: tuple[Cell, ...]
    expansions: int


def _kernel_margin_holds(
    grid: _Grid,
    cells: Sequence[tuple[int, int, int]],
) -> bool:
    """Whether the compiled A* loop's index preconditions hold on ``grid``.

    THE TEST IS ``span`` MINUS THE TWO-CELL PAD, not ``span`` itself, and the
    margin is the point rather than the containment.  A ramp travels two cells
    and the loop indexes ``cur +- 2 * xstep +- 2 * LEVELS +- 1`` with no bounds
    check of its own -- see :class:`_Grid` on why the pad exists.  A cell
    sitting IN the pad is inside ``span`` and still one whose neighbour
    arithmetic leaves the array: the compiled loop would write ``best[si]``
    past its buffer or read ``flags[cur - 2 * xstep]`` below zero, which the
    Python loop merely wrapped around silently.

    Two facts together cover every index the kernel touches.  ``box`` two cells
    inside ``span`` covers the reached cells, because :func:`_routing_flags`
    only ever clears bytes of ``occ`` and ``occ`` is 1 only inside ``box``, so
    every cell the loop expands after passing ``flags[...]`` is inside the
    margin.  The explicit sweep covers the seeds and the goals, which are
    tested against ``goal_flag`` and pushed without a ``flags`` test.

    A grid that fails this DOES NOT lose its landmarks: the search falls
    through to :func:`_astar_python_loop`, which is memory-safe on any input
    and gives the same answer on the same grid.  Degrading the backend and
    degrading the grid are not the same thing -- rebuilding the grid would drop
    the landmark fields and move the expansion counts of BOTH backends.
    Nothing reaches here with such a cell today, because ``canvas.limit`` is
    set by the time anything routes and ``canvas.free`` refuses anything
    outside it, so this changes no digest; it makes the kernel's precondition
    the wrapper's job to enforce rather than an invariant held at a distance.
    """
    gx0, gy0, gx1, gy1 = grid.span
    lo_x, lo_y, hi_x, hi_y = grid.box
    if not (gx0 + 2 <= lo_x and hi_x <= gx1 - 2 and gy0 + 2 <= lo_y and hi_y <= gy1 - 2):
        return False
    for cx, cy, clvl in cells:
        if not (gx0 + 2 <= cx <= gx1 - 2 and gy0 + 2 <= cy <= gy1 - 2 and 0 <= clvl < LEVELS):
            return False
    return True


def _astar_python_loop(
    flags: bytearray,
    hist: Sequence[float] | None,
    pressure: float,
    goal_flag: bytearray,
    start_indices: Sequence[int],
    h: Callable[[int], float],
    size: int,
    gh: int,
    xstep: int,
    budget: dict[str, int] | None,
    start_left: int,
    deadline: float | None,
) -> tuple[list[int] | None, int, int, list[int]]:
    """The A* expansion loop, in Python.

    Returns ``(path indices oldest first, expansions, kind, settled)``, where
    ``kind`` is 0 found / 1 budget / 2 sealed and ``settled`` is the reachable
    pocket in index order -- populated only when the heap emptied, which is the
    one ending that proves the pocket is sealed.

    This is the reference implementation.  ``_route_kernel.astar_flat`` is a
    compiled transcription of it, and the two are held to the same replay digest
    by :mod:`scripts.route_bench`; a change here is a change there.
    """
    negotiating = hist is not None
    if hist is None:
        hist = []

    # (one-step cell offset, two-step cell offset, one-step column offset,
    # two-step column offset) -- the ramp's run cell is the plain step's target,
    # so one pass over the four directions does both, and the column offsets
    # index `hcache` without re-deriving a column from a cell.  ``dx`` and
    # ``dy`` are NOT carried: nothing in the loop wants them since `h` began
    # taking a column, and unpacking two dead names four times per expansion is
    # 5.6M unpackings in a `quantum-chip` pass.
    ystep = LEVELS
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
    for si in start_indices:
        best[si] = 0.0
        prev[si] = -1
        heappush(open_heap, (h(si // LEVELS), 0.0, si))

    while open_heap:
        _, g, cur = heappop(open_heap)
        if g > best[cur]:
            continue
        expansions += 1
        if expansions >= checkpoint:
            if expansions > _MAX_EXPANSIONS:
                if budget is not None:
                    budget["left"] = start_left - expansions + 1
                return None, expansions, 1, []
            if expansions % _DEADLINE_CHECK_EVERY == 0 and _expired(deadline):
                if budget is not None:
                    budget["left"] = start_left - expansions + 1
                return None, expansions, 1, []
            if expansions >= start_left:
                if budget is not None:
                    budget["left"] = start_left - expansions
                return None, expansions, 1, []
            checkpoint = _MAX_EXPANSIONS + 1
            due = (expansions // _DEADLINE_CHECK_EVERY + 1) * _DEADLINE_CHECK_EVERY
            if due < checkpoint:
                checkpoint = due
            if start_left < checkpoint:
                checkpoint = start_left
        if goal_flag[cur]:
            walk: list[int] = []
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
                        f"grid-local {(px, py, lvl)}; "
                        "a ramp move corrupted an existing predecessor"
                    )
                seen.add(node)
                walk.append(node)
                run = via_get(node, -1)
                if run != -1:
                    walk.append(run)
                node = prev[node]
            if budget is not None:
                budget["left"] = start_left - expansions
            walk.reverse()
            return walk, expansions, 0, []
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
    # Budget exits above do not say the pocket is sealed.
    if budget is not None:
        budget["left"] = start_left - expansions
    return None, expansions, 2, [i for i, seen_at in enumerate(best) if seen_at != inf]


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
    owned_starts: Collection[Cell] = (),
    released_starts: Collection[Cell] = (),
    forbidden: Collection[Cell] = (),
    blocking_owners: Mapping[Cell, int] | None = None,
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

    ``owned_starts`` names exact junction-guard cells reserved for this source
    sibling.  ``released_starts`` names exact tentative path cells a repair's
    open grid has deliberately made passable. ``forbidden`` names exact cells
    where this net's earlier path failed real-altitude commit. Only those
    initial exceptions are admitted; every guard, settled path, and rejected
    commit cell remains impassable.
    """
    forbidden_cells = frozenset(forbidden)
    if not goals:
        return _PathSearchResult(None, RouteFailureKind.DYNAMIC_ACCESS, (), 0)
    owned = frozenset(
        start for start in starts if start in owned_starts and canvas.free_owned_guard(start)
    )
    released = frozenset(
        start
        for start in starts
        if start in released_starts and canvas.blocked.get(start) == _TENTATIVE
    )
    if not any(
        start not in forbidden_cells and (canvas.free(start) or start in owned or start in released)
        for start in starts
    ):
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
    #
    # THIS TEST IS CONTAINMENT IN `span`, and it decides GRID REUSE ONLY.  The
    # compiled loop needs a stronger property -- two cells of margin, see
    # :func:`_kernel_margin_holds` -- but reuse is the wrong lever for it: a
    # rebuilt grid is a landmark-free grid, so refusing reuse here would weaken
    # the heuristic and move the expansion counts of both backends, including
    # the Python one, which must stay byte-identical to the pre-kernel router.
    # The margin decides which loop runs, and nothing else.
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
    # `routing_ports` is rebound per net. Copying is a memcpy; rebuilding it
    # from the canvas obstacle containers is not.
    flags = _routing_flags(flat, routing_ports=canvas.routing_ports)
    for start in owned:
        flags[flat.index(start)] = 1
    sx0, sy0, sx1, sy1 = flat.span
    for cell in forbidden_cells:
        if sx0 <= cell[0] <= sx1 and sy0 <= cell[1] <= sy1 and 0 <= cell[2] < LEVELS:
            flags[flat.index(cell)] = 0

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

    # The admitted starts, as flat indices, computed once: both loops seed the
    # heap from this list and neither re-derives it.
    start_indices = [
        (s[0] - gx0) * xstep + (s[1] - gy0) * ystep + s[2]
        for s in starts
        if not (
            s in forbidden_cells or (not canvas.free(s) and s not in owned and s not in released)
        )
    ]
    if not start_indices:
        return _PathSearchResult(None, RouteFailureKind.DYNAMIC_ACCESS, (), 0)

    # `budget` is read into a local and written back at every exit, because a
    # `budget["left"] -= 1` is a hash, a lookup and a store on the hottest line
    # in this router -- 1.25M of them in one `quantum-chip` routing pass.
    start_left = budget["left"] if budget is not None else 1 << 62

    path_indices: Sequence[int] | None
    settled: Sequence[int]
    if route_kernel._compiled_astar is not None and _kernel_margin_holds(
        flat, (*starts, *goal_list)
    ):
        # The compiled loop takes the heuristic apart rather than calling back
        # into `h`: which of the three plain terms applies, the deduplicated
        # goal columns the exact term needs, the bounding box the weak term
        # needs, and the landmark fields, all as buffers.  It re-derives the
        # same bands `h` closed over, from the same goal columns.
        near = tuple({(c[0] - gx0, c[1] - gy0) for c in goal_list})
        goal_columns = array("q", [v for pair in near for v in pair])
        goal_box = (
            min(c[0] for c in goal_list) - gx0,
            min(c[1] for c in goal_list) - gy0,
            max(c[0] for c in goal_list) - gx0,
            max(c[1] for c in goal_list) - gy0,
        )
        if not negotiating:
            hist_buffer = array("d")
        elif isinstance(hist, array):
            hist_buffer = hist
        else:
            hist_buffer = array("d", hist)
        # The extension is typed by `_route_kernel.pyi`, but the backend holds it
        # as a `Callable[..., object]` so a missing extension is a None rather
        # than an import error; the shape it returns is that stub's.
        path_indices, expansions, kind, settled, left = cast(
            "tuple[Sequence[int] | None, int, int, Sequence[int], int]",
            route_kernel._compiled_astar(
                flags, hist_buffer, pressure, flat.alt_flat, len(flat.alt), goal_flag,
                goal_columns, len(goal_list) <= _EXACT_HEURISTIC_GOALS, goal_box,
                array("q", start_indices), gh, xstep, LEVELS, array("d", _LEVEL_TOLL),
                _MAX_EXPANSIONS, start_left, _DEADLINE_CHECK_EVERY, deadline, _expired,
            ),
        )
        if budget is not None:
            budget["left"] = left
    else:
        path_indices, expansions, kind, settled = _astar_python_loop(
            flags, hist if negotiating else None, pressure, goal_flag, start_indices, h,
            size, gh, xstep, budget, start_left, deadline,
        )

    if kind == 1:
        return _PathSearchResult(None, RouteFailureKind.BUDGET, (), expansions)
    if kind == 0:
        assert path_indices is not None
        cells = []
        for index in path_indices:
            q, lvl = divmod(index, LEVELS)
            px, py = divmod(q, gh)
            cells.append((px + gx0, py + gy0, lvl))
        return _PathSearchResult(tuple(_cut_loops(cells)), None, (), expansions)

    # THE HEAP EMPTIED, which is the one ending that proves no path exists -- the
    # Budget exits above do not say the pocket is sealed. The settled cells are
    # exactly the free space this net could reach and the blocked cells touching
    # them are its wall. Only tentative cells have a routing-net owner.
    if blocking_owners is not None:
        owner_get = blocking_owners.get
        wall_by_owner: dict[int, Cell] = {}
        too_diffuse = False
        for index in settled:
            q, level = divmod(index, LEVELS)
            x, y = divmod(q, gh)
            x += gx0
            y += gy0
            for dx, dy in _STEPS:
                cell = (x + dx, y + dy, level)
                blocker = owner_get(cell)
                if blocker is None or flags[flat.index(cell)]:
                    continue
                wall_by_owner.setdefault(blocker, cell)
                if len(wall_by_owner) > _BLAME_MAX_WALL:
                    too_diffuse = True
                    break
            if too_diffuse:
                break
        owner_wall_cells = (
            () if too_diffuse else tuple(sorted(wall_by_owner.values()))
        )
        if blame is not None:
            for cell in owner_wall_cells:
                blame[cell] = blame.get(cell, 0.0) + 1.0
        return _PathSearchResult(
            None,
            RouteFailureKind.SEALED_POCKET,
            owner_wall_cells,
            expansions,
        )
    wall_cells: tuple[Cell, ...] = ()
    if len(settled) <= _BLAME_MAX_POCKET:
        blocked_get = canvas.blocked.get
        wall: set[Cell] = set()
        for i in settled:
            q, blvl = divmod(i, LEVELS)
            bx, by = divmod(q, gh)
            bx += gx0
            by += gy0
            for dx, dy in _STEPS:
                cell = (bx + dx, by + dy, blvl)
                if blocked_get(cell) == _TENTATIVE and not flags[flat.index(cell)]:
                    wall.add(cell)
        if len(wall) <= _BLAME_MAX_WALL:
            wall_cells = tuple(sorted(wall))
            if blame is not None:
                for cell in wall_cells:
                    blame[cell] = blame.get(cell, 0.0) + 1.0
    return _PathSearchResult(None, RouteFailureKind.SEALED_POCKET, wall_cells, expansions)


@dataclass
class _Net:
    src: _Port | None
    dst: _Port
    item: str
    cargo_domain: CargoDomain = CargoDomain.UNSPRAYED
    net_id: NetId | None = None
    boundary_goals: tuple[tuple[int, int, int], ...] = ()

    def __post_init__(self) -> None:
        ports = (self.dst,) if self.src is None else (self.src, self.dst)
        if any(port.cargo_domain is not self.cargo_domain for port in ports):
            raise ValueError("net ports must share one cargo domain")

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
    cargo_domain: CargoDomain = CargoDomain.UNSPRAYED
    boundary_goals: tuple[tuple[int, int, int], ...] = ()
    src_group: tuple[NetId, ...] = ()
    dst_group: tuple[NetId, ...] = ()

    def __post_init__(self) -> None:
        ports = (self.dst,) if self.src is None else (self.src, self.dst)
        if any(port.cargo_domain is not self.cargo_domain for port in ports):
            raise ValueError("prepared net ports must share one cargo domain")


def _with_sibling_groups(
    nets: Sequence[_PreparedNet],
) -> tuple[_PreparedNet, ...]:
    """Freeze the detailed router's exact branch/merge groups onto each net."""
    same_src: dict[tuple[str, CargoDomain, int, int, int], list[NetId]] = defaultdict(list)
    same_dst: dict[tuple[str, CargoDomain, int, int, int], list[NetId]] = defaultdict(list)
    for net in nets:
        if net.net_id.role is NetRole.EXTERNAL:
            continue
        if net.src is None:
            raise ValueError("non-external prepared nets require source ports")
        same_src[net.item, net.cargo_domain, net.src.y, net.src.x0, net.src.z].append(net.net_id)
        same_dst[net.item, net.cargo_domain, net.dst.x, net.dst.y, net.dst.z].append(net.net_id)
    grouped: list[_PreparedNet] = []
    for net in nets:
        if net.net_id.role is NetRole.EXTERNAL:
            grouped.append(replace(net, src_group=(), dst_group=()))
            continue
        if net.src is None:
            raise ValueError("non-external prepared nets require source ports")
        grouped.append(
            replace(
                net,
                src_group=tuple(
                    sibling
                    for sibling in same_src[
                        net.item,
                        net.cargo_domain,
                        net.src.y,
                        net.src.x0,
                        net.src.z,
                    ]
                    if sibling != net.net_id
                ),
                dst_group=tuple(
                    sibling
                    for sibling in same_dst[
                        net.item,
                        net.cargo_domain,
                        net.dst.x,
                        net.dst.y,
                        net.dst.z,
                    ]
                    if sibling != net.net_id
                ),
            )
        )
    return tuple(grouped)


def _junction_geometry_required(
    nets: Sequence[_PreparedNet],
    buildings: Sequence[PlacedBuilding],
) -> bool:
    """Whether the detailed router can introduce a Splitter for these nets."""
    return any(
        net.src_group
        or (net.src is not None and buildings[net.src.belt_index].output_obj is not None)
        for net in nets
    )


@dataclass(slots=True)
class _RoutingWorkspace:
    canvas: _Canvas
    buildings: list[PlacedBuilding]
    nets: list[_Net]
    external_output_nets: list[_Net]


@dataclass(frozen=True, slots=True)
class _PreparedRoutingProblem:
    building_templates: tuple[PlacedBuilding, ...]
    blocked: tuple[tuple[tuple[int, int, int], int], ...]
    solid: frozenset[tuple[int, int]]
    reserved: tuple[
        tuple[tuple[int, int, int], tuple[int, int, int]],
        ...,
    ]
    port_corridors: tuple[
        tuple[Cell, tuple[PortAccessCorridor, ...]],
        ...,
    ]
    keep_out: frozenset[tuple[int, int]]
    guard: frozenset[Cell]
    nets: tuple[_PreparedNet, ...]
    core: tuple[int, int, int, int]
    route_bounds: tuple[int, int, int, int]
    limit: tuple[int, int, int, int] | None
    power_sites: tuple[tuple[int, int], ...]
    sorters: int
    coaters: int
    direct_inserts: int
    promised_direct: frozenset[DirectInsertId] = frozenset()
    realized_direct: frozenset[DirectInsertId] = frozenset()
    coater_supply_ports: tuple[CoaterSupplyPort, ...] = ()
    ramped: bool = False
    world_taken: frozenset[tuple[int, int, Fraction]] = frozenset()
    belt_ban: tuple[tuple[tuple[int, int], frozenset[int]], ...] = ()
    junction_ban: frozenset[Cell] = frozenset()
    junction_frame_bans: tuple[frozenset[Cell], ...] = ()
    preparation_failures: tuple[NetFailure, ...] = ()
    stranded_ports: tuple[StrandedPort, ...] = ()
    external_output_nets: tuple[_PreparedNet, ...] = ()
    sorter_tiers: tuple[int, ...] = catalog.SORTER_TIERS

    def new_workspace(self) -> _RoutingWorkspace:
        buildings = list(self.building_templates)
        canvas = _Canvas(
            ramped=self.ramped,
            sorter_tiers=self.sorter_tiers,
            buildings=buildings,
            blocked=dict(self.blocked),
            world_taken=set(self.world_taken),
            solid=set(self.solid),
            reserved=dict(self.reserved),
            routing_ports=frozenset(),
            port_corridors=dict(self.port_corridors),
            limit=self.limit,
            keep_out=set(self.keep_out),
            belt_ban={cell: set(levels) for cell, levels in self.belt_ban},
            guard=set(self.guard),
            junction_ban=set(self.junction_ban),
            junction_geometry_prepared=True,
        )
        nets = [_bind_prepared_net(net, buildings) for net in self.nets]
        external_output_nets = [
            _bind_prepared_net(net, buildings) for net in self.external_output_nets
        ]
        return _RoutingWorkspace(
            canvas=canvas,
            buildings=buildings,
            nets=nets,
            external_output_nets=external_output_nets,
        )


def _bind_prepared_net(net: _PreparedNet, buildings: list[PlacedBuilding]) -> _Net:
    return _Net(
        src=(_bind_prepared_port(net.src, buildings) if net.src is not None else None),
        dst=_bind_prepared_port(net.dst, buildings),
        item=net.item,
        cargo_domain=net.cargo_domain,
        net_id=net.net_id,
        boundary_goals=net.boundary_goals,
    )


def _cardinal_direction(
    origin: PlacedBuilding,
    outward: PlacedBuilding,
) -> tuple[int, int] | None:
    direction = (outward.x - origin.x, outward.y - origin.y)
    return direction if abs(direction[0]) + abs(direction[1]) == 1 else None


def _straight_path_direction(
    path: Sequence[Cell],
    at: int,
) -> tuple[int, int] | None:
    """Flow direction through one straight, cardinal interior path cell."""
    if not 0 < at < len(path) - 1:
        return None
    x, y, _level = path[at]
    before = (path[at - 1][0] - x, path[at - 1][1] - y)
    after = (path[at + 1][0] - x, path[at + 1][1] - y)
    if (
        abs(before[0]) + abs(before[1]) != 1
        or abs(after[0]) + abs(after[1]) != 1
        or before != (-after[0], -after[1])
    ):
        return None
    return after


def _merge_frontier(
    canvas: _Canvas,
    paths: Mapping[int, Sequence[Cell]],
    siblings: tuple[int, ...],
    junctionable: Callable[[int, int, int], bool] | None = None,
    *,
    provenance: dict[Cell, Cell] | None = None,
    belt_prefab: tuple[int, int] | None = None,
    tentative_ok: bool = False,
    owned_guard: Mapping[Cell, Cell] | None = None,
) -> set[Cell]:
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

    ``belt_prefab`` makes that source-side proof include physical Splitter port
    identity.  A ramp and a branch may occupy different routing levels in the
    same compass direction, but they still name one port.  Such a neighbour is
    withheld here so A* can choose another side instead of discovering the
    duplicate only after every path has been committed.

    ``owned_guard`` maps an exact reserved branch dock to the sibling tap that
    owns it.  A selected future Splitter guards that dock from unrelated nets,
    but its own source siblings must be able to begin there.  Requiring both
    dock and tap identity prevents the exception from opening any other cell in
    the Splitter's keep-out.
    """
    out: set[Cell] = set()
    for sibling in siblings:
        path = paths.get(sibling, ())
        altitudes = _altitude_profile(path, ramped=canvas.ramped)
        if altitudes is None:
            continue
        for at, ((x, y, lvl), altitude) in enumerate(zip(path, altitudes, strict=True)):
            # A source-side junction requires an integer carry plane.  Model 40
            # serves odd planes from one level lower and exposes only its
            # orthogonal lower ports to the new branch.
            if junctionable is not None and altitude.denominator != 1:
                continue
            actual_level = int(altitude) if altitude.denominator == 1 else lvl
            if junctionable is not None and not junctionable(x, y, actual_level):
                continue
            carry_direction = (
                _straight_path_direction(path, at)
                if junctionable is not None and actual_level % 2
                else None
            )
            if junctionable is not None and actual_level % 2 and carry_direction is None:
                continue
            branch_level = actual_level - 1 if carry_direction is not None else lvl
            free = [
                cell
                for dx, dy in _STEPS
                if (
                    carry_direction is None
                    or dx * carry_direction[0] + dy * carry_direction[1] == 0
                )
                and (
                    canvas.free(cell := (x + dx, y + dy, branch_level))
                    or (
                        owned_guard is not None
                        and owned_guard.get(cell) == (x, y, lvl)
                        and canvas.free_owned_guard(cell)
                    )
                    or (tentative_ok and canvas.blocked.get(cell) == _TENTATIVE)
                )
            ]
            if not free:
                continue
            if junctionable is not None and belt_prefab is not None:
                belt_item, belt_model = belt_prefab
                attachment = PlacedBuilding(
                    item_id=belt_item,
                    model_index=belt_model,
                    x=x,
                    y=y,
                    z=altitude,
                    width=1,
                    height=1,
                )
                splitter = _splitter_stack_geometry(
                    x,
                    y,
                    actual_level,
                    carry_direction=carry_direction,
                )[-1]
                used_ports: set[int] = set()
                path_ports_valid = True
                for neighbour_index in (at - 1, at + 1):
                    if not 0 <= neighbour_index < len(path):
                        continue
                    neighbour_x, neighbour_y, _neighbour_level = path[neighbour_index]
                    port = splitter_ports.expected_path_port(
                        splitter,
                        attachment,
                        replace(
                            attachment,
                            x=neighbour_x,
                            y=neighbour_y,
                        ),
                    )
                    if port is None or port in used_ports:
                        path_ports_valid = False
                        break
                    used_ports.add(port)
                if not path_ports_valid:
                    continue
                available: list[Cell] = []
                for cell in free:
                    branch_attachment = replace(
                        attachment,
                        z=Fraction(cell[2]),
                    )
                    port = splitter_ports.expected_path_port(
                        splitter,
                        branch_attachment,
                        replace(
                            branch_attachment,
                            x=cell[0],
                            y=cell[1],
                        ),
                    )
                    if port is not None and port not in used_ports:
                        available.append(cell)
                free = available
            if not free:
                continue
            if junctionable is not None and not _junction_belt_clear(
                canvas,
                (x, y, actual_level),
                path,
                at,
                tentative_ok=tentative_ok,
            ):
                continue
            out.update(free)
            if provenance is not None:
                tap = (x, y, lvl)
                for cell in free:
                    provenance.setdefault(cell, tap)
    return out


def _junction_belt_clear(
    canvas: _Canvas,
    tap: tuple[int, int, int],
    path: Sequence[tuple[int, int, int]],
    at: int,
    *,
    tentative_ok: bool = False,
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
    path_cells = set(path)
    excused = set(path[max(0, at - 2) : at + 3])
    try:
        stack = _splitter_stack_geometry(tap[0], tap[1], tap[2])
    except ValueError:
        return False
    for offset, stack_member in enumerate(stack):
        top = offset == len(stack) - 1
        for cell in junction.keepout_cells(
            tap[0],
            tap[1],
            int(stack_member.z),
            model_index=stack_member.model_index,
            yaw=stack_member.yaw,
        ):
            if cell in path_cells:
                if top and cell in excused:
                    continue
                return False
            who = canvas.blocked.get(cell)
            if who is None:
                continue
            if who == _TENTATIVE:
                if tentative_ok:
                    continue
                return False
            if 0 <= who < len(canvas.buildings) and catalog.is_belt(canvas.buildings[who].item_id):
                return False
    return True


@dataclass(frozen=True, slots=True)
class _CommitFailure:
    """The exact endpoint a routed path could not attach at."""

    cell: Cell
    side: Literal["source", "sink", "path"]
    blocking_indices: tuple[int, ...] = ()
    tap: Cell | None = None
    blocking_cells: tuple[Cell, ...] = ()
    reason: str = ""


def _junction_guard_victims(
    owner: Mapping[Cell, int],
    guarded: Collection[Cell],
    *,
    excused: Collection[Cell],
) -> set[int]:
    """Return routed paths displaced by a prospective Splitter guard.

    A source sibling is not inherently safe inside the Splitter stack. Only the
    exact connected run cells explicitly excused for the top stack member may
    remain. A sibling crossing a lower member's keep-out must move like any
    other routed path or commit will reject that belt after routing succeeded.
    """
    return {
        blocker
        for cell in guarded
        if cell not in excused and (blocker := owner.get(cell)) is not None
    }


def _route_all(
    canvas: _Canvas,
    nets: list[_Net],
    belt_id: int,
    belt_model: int,
    bounds: tuple[int, int, int, int],
    deadline: float | None = None,
    budget: dict[str, int] | None = None,
    planned_power_sites: Sequence[tuple[int, int]] | None = None,
    junction_frame_bans: Sequence[frozenset[Cell]] = (),
    *,
    prioritize_source_families: bool = False,
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

    So ``deadline`` is checked between rounds AND between nets. Expiry never
    commits the live paths, but the result retains the best exact evidence
    already established: routed identities and geometric failures remain
    available to the caller's placement-repair stage, while untouched nets are
    reported as budget-unknown. The caller discards every budget result, so the
    evidence can guide another placement and can never emit a partial routing.
    """
    power_discs = (
        None
        if planned_power_sites is None
        else _power_coverage_discs(canvas.buildings, planned_power_sites)
    )
    history: dict[tuple[int, int, int], float] = defaultdict(float)
    #: The live routing -- net index to path -- and the same cells the other way
    #: round.  ``owner`` is what makes a TARGETED rip-up possible: a repair
    #: search that crosses a belt has to be able to say WHOSE belt it crossed.
    #: They are staked and unstaked together, always through `_stake`/`_unstake`,
    #: because `canvas.blocked`, `grid.occ` and `owner` disagreeing is a router
    #: that quietly routes through a committed belt.
    paths: dict[int, tuple[Cell, ...]] = {}
    owner: dict[Cell, int] = {}
    roles_by_net: dict[int, tuple[tuple[Cell, str, bool], ...]] = {}
    role_members: dict[tuple[Cell, str], set[int]] = defaultdict(set)
    for index, net in enumerate(nets):
        roles: list[tuple[Cell, str, bool]] = []
        if net.src is not None:
            roles.append(((net.src.x, net.src.y, net.src.z), "src", True))
        roles.append(((net.dst.x, net.dst.y, net.dst.z), "dst", False))
        roles_by_net[index] = tuple(roles)
        for key, role, _source in roles:
            role_members[key, role].add(index)
    retired_roles: dict[tuple[Cell, str], PortAccessCorridor] = {}
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
    #: The round `best_paths` was captured from, or ``-1`` before any round
    #: has.  Compared against `proved_round` at the final `_finish` call so a
    #: last-mile proof closed over an earlier round's stranded set can never
    #: be claimed exhaustive for an incumbent it never examined.
    best_round = -1
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
    best_source_hints: dict[int, Cell] = {}
    best_path_taps: dict[int, Cell] = {}
    best_sink_hints: dict[int, Cell] = {}
    round_expansions: dict[int, int] = {}

    def _net_id(index: int) -> NetId:
        net_id = nets[index].net_id
        if net_id is None:
            raise ValueError("detailed routing requires stable net IDs")
        return net_id

    def _endpoint_cells(net: _Net) -> tuple[Cell | None, Cell]:
        source = None if net.src is None else (net.src.x, net.src.y, net.src.z)
        return source, (net.dst.x, net.dst.y, net.dst.z)

    net_by_id = {_net_id(index): net for index, net in enumerate(nets)}

    def _blocking_endpoint_cells(
        blocking_nets: tuple[NetId, ...],
    ) -> tuple[tuple[Cell | None, Cell | None], ...]:
        return tuple(
            _endpoint_cells(net_by_id[blocker]) if blocker in net_by_id else (None, None)
            for blocker in blocking_nets
        )

    def _blocking_nets(
        wall: Sequence[Cell],
        source_blockers: Sequence[NetId] = (),
    ) -> tuple[NetId, ...]:
        # Sort transient integer indices, which have a total order. NetId's
        # optional strip fields deliberately do not compare across None/int.
        blocker_indices = sorted(
            {blocker for cell in wall if (blocker := owner.get(cell)) is not None}
        )
        return tuple(
            dict.fromkeys((*(_net_id(blocker) for blocker in blocker_indices), *source_blockers))
        )

    def _failure(
        index: int,
        search: _PathSearchResult,
        blocking_nets: tuple[NetId, ...],
    ) -> NetFailure:
        source, destination = _endpoint_cells(nets[index])
        return NetFailure(
            net_id=_net_id(index),
            kind=search.kind or RouteFailureKind.DYNAMIC_ACCESS,
            wall=search.wall,
            blocking_nets=blocking_nets,
            expansions=search.expansions,
            source=source,
            destination=destination,
            blocking_endpoints=_blocking_endpoint_cells(blocking_nets),
        )

    def _budget_result(
        current_paths: Mapping[int, tuple[Cell, ...]] | None = None,
        current_failures: Mapping[int, NetFailure] | None = None,
    ) -> DetailedRouteResult:
        # Deadline expiry invalidates future work, not facts already proved.
        # Retain the most complete incumbent without committing its paths to the
        # canvas. This is routing evidence for placement repair; the BUDGET
        # status remains the hard emission gate.
        candidates = [
            (best_paths, best_failures),
            (
                {} if current_paths is None else current_paths,
                {} if current_failures is None else current_failures,
            ),
        ]
        selected_paths, selected_failures = max(
            candidates,
            key=lambda candidate: (
                len(set(candidate[0]) | set(candidate[1])),
                len(candidate[0]),
                len(candidate[1]),
            ),
        )
        failures = dict(selected_failures)
        for index in range(len(nets)):
            if index in selected_paths or index in failures:
                continue
            previous = best_failures.get(index)
            failures[index] = NetFailure(
                _net_id(index),
                RouteFailureKind.BUDGET,
                (),
                (),
                round_expansions.get(
                    index,
                    previous.expansions if previous is not None else 0,
                ),
            )
        return DetailedRouteResult(
            status=DetailedRouteStatus.BUDGET,
            routed=tuple(
                _net_id(index)
                for index in range(len(nets))
                if index in selected_paths and index not in failures
            ),
            failures=tuple(failures[index] for index in range(len(nets)) if index in failures),
            iterations=iterations,
            expansions=expansions,
            last_mile=_last_mile_report(),
        )

    def _finish(
        selected_paths: dict[int, tuple[Cell, ...]],
        selected_failures: dict[int, NetFailure],
        selected_source_hints: Mapping[int, Cell],
        selected_sink_hints: Mapping[int, Cell],
        selected_taps: Mapping[int, Cell],
        *,
        budget_exhausted: bool,
        exhaustive_claim: bool = False,
    ) -> DetailedRouteResult:
        # `selected_paths` may be an incumbent from an earlier RRR round, while
        # `canvas.guard` describes only the last round. Conditional junction
        # guards are search state, not physical buildings; committing an older
        # topology against newer guards creates false lattice collisions.
        # Permanent pre-existing Splitter guards remain authoritative.
        canvas.guard.intersection_update(permanent_guard)
        if junction_frame_bans:
            selected_tap_cells = frozenset(selected_taps.values())
            assert any(
                all(tap not in frame_ban for tap in selected_tap_cells)
                for frame_ban in junction_frame_bans
            ), "the selected routing incumbent has no shared projection frame"
        details: dict[int, _CommitFailure] = {}
        unlinked = _commit_paths(
            canvas,
            nets,
            selected_paths,
            belt_id,
            belt_model,
            src_group=src_group,
            dst_group=dst_group,
            source_hints=selected_source_hints,
            sink_hints=selected_sink_hints,
            failure_details=details,
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
            detail = details.get(index)
            source, destination = _endpoint_cells(nets[index])
            blockers = tuple(
                _net_id(blocker)
                for blocker in (detail.blocking_indices if detail is not None else ())
            )
            failures[index] = NetFailure(
                _net_id(index),
                RouteFailureKind.COMMIT_LINK,
                ((detail.cell, *detail.blocking_cells) if detail is not None else ()),
                blockers,
                0,
                source=source,
                destination=destination,
                blocking_endpoints=_blocking_endpoint_cells(blockers),
            )
        routed = tuple(
            _net_id(index)
            for index in range(len(nets))
            if index in selected_paths and index not in failures
        )
        ordered_failures = tuple(failures[index] for index in range(len(nets)) if index in failures)
        status = (
            DetailedRouteStatus.BUDGET
            if (
                budget_exhausted
                or any(failure.kind is RouteFailureKind.BUDGET for failure in ordered_failures)
            )
            else (DetailedRouteStatus.STRANDED if ordered_failures else DetailedRouteStatus.ROUTED)
        )
        # A claim is only about the routing being RETURNED.  The cluster search
        # closed its tree over one round's stranded set; if the incumbent that
        # survives strands anything else -- or strands the same nets for a
        # reason a budget cut off -- the proof does not describe it.
        exhaustive = (
            exhaustive_claim
            and status is DetailedRouteStatus.STRANDED
            and set(failures) == proved_stranded
            and not any(
                failure.kind is RouteFailureKind.BUDGET for failure in ordered_failures
            )
        )
        return DetailedRouteResult(
            status=status,
            routed=routed,
            failures=ordered_failures,
            iterations=iterations,
            expansions=expansions,
            exhaustive=exhaustive,
            last_mile=_last_mile_report(),
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

    # Nets carrying the same item and cargo domain that end at the same lane.
    # Ordered, so "the ones before me" is well defined however the router
    # chooses to sequence a round.
    same_dst: dict[tuple[str, CargoDomain, int, int, int], list[int]] = defaultdict(list)
    for i, net in enumerate(nets):
        same_dst[net.item, net.cargo_domain, net.dst.x, net.dst.y, net.dst.z].append(i)
    dst_group = {
        i: tuple(
            g
            for g in same_dst[net.item, net.cargo_domain, net.dst.x, net.dst.y, net.dst.z]
            if g != i
        )
        for i, net in enumerate(nets)
    }
    # The same story on the producer side, and it needs the same answer. An
    # out-lane sandwiched between its neighbours is only reachable at its ends,
    # so walking it tile by tile hands the later nets a walled-in start. They
    # BRANCH instead: leave from a sibling's path, which becomes a splitter on
    # that path at commit time. Keyed by the ITEM, DOMAIN, and LANE (row and
    # west edge), not the port, because `at_tile` moves the port along the lane
    # it belongs to.
    same_src: dict[tuple[str, CargoDomain, int, int, int], list[int]] = defaultdict(list)
    for i, net in enumerate(nets):
        same_src[net.item, net.cargo_domain, net.source.y, net.source.x0, net.source.z].append(i)
    src_group = {
        i: tuple(
            g
            for g in same_src[
                net.item, net.cargo_domain, net.source.y, net.source.x0, net.source.z
            ]
            if g != i
        )
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

    #: Exact legality is keyed by all three routing coordinates.  The prepared
    #: cache includes machines and reserved towers; the canvas adds any dynamic
    #: Splitters already committed in this attempt. A dynamic stack is also
    #: admissible only when the power plan covers every physical member: model
    #: 40 can place a member one tile beyond the logical routing cell.
    junction_ok: dict[Cell, bool] = {}
    #: True only while the relaxed cluster run is searching.  It relaxes ONE
    #: refusal below -- the conditional-guard one -- because that refusal reads
    #: `planned_taps`, and run 2 has to start with an empty tap table (see
    #: `_relaxed_cluster_result`).  Set and cleared in that closure's
    #: `try`/`finally`, so it cannot survive the run even on an exception.
    relaxed_junctions = False

    def _can_junction(x: int, y: int, level: int) -> bool:
        cell = (x, y, level)
        got = junction_ok.get(cell)
        if got is None:
            stack = _splitter_stack_geometry(x, y, level)
            got = canvas.junction_is_clear(x, y, level) and (
                power_discs is None or _buildings_are_powered(stack, power_discs)
            )
            junction_ok[cell] = got
        if not got:
            return False
        if junction_frame_bans and not any(
            cell not in frame_ban and all(tap not in frame_ban for tap in planned_taps)
            for frame_ban in junction_frame_bans
        ):
            return False
        planned_here = planned_taps.get(cell, ())
        if len(planned_here) >= 2:
            return False
        # A conditional guard is the exact geometry a previously selected tap
        # needs against later paths and later Splitters. Reusing the same tap is
        # allowed up to the Splitter's remaining two branch ports.
        #
        # The relaxed cluster run is exempt, and only here.  Unstaking the pack
        # leaves `canvas.guard == permanent_guard` and `planned_taps` empty, so
        # this refusal would turn away every permanent-guard cell -- including
        # ones a realizable world DOES tap -- making run 2 tighter than a world
        # it is supposed to bound.  Run 2 treats every cell as already tapped
        # for this one check; the two checks that read `planned_taps` around it
        # stay as they are, now over the cluster's own taps alone.
        if cell in canvas.guard and not planned_here and not relaxed_junctions:
            return False
        nearby = [
            stack_member
            for tx, ty, tz in planned_taps
            if (tx, ty, tz) != cell
            and abs(tx - x) <= 3
            and abs(ty - y) <= 3
            and abs(tz - level) <= 3
            for stack_member in _splitter_stack_geometry(tx, ty, tz)
        ]
        return all(
            not _building_collider_hits(nearby, stack_member)
            for stack_member in _splitter_stack_geometry(x, y, level)
        )

    building_predecessors: dict[int, list[int]] = defaultdict(list)
    for building_index, building in enumerate(canvas.buildings):
        if catalog.is_belt(building.item_id) and building.output_obj is not None:
            building_predecessors[building.output_obj].append(building_index)

    def _direct_tap_clear(net: _Net, *, tentative_ok: bool = False) -> bool:
        tap = (net.source.x, net.source.y, net.source.z)
        # Splitter legality excuses the actual connected run around the tap,
        # not only the source port's declared horizontal lane. A prebuilt
        # proliferator trunk is vertical, and treating its predecessor and
        # successor as foreign belts makes every root falsely unavailable.
        excused = _run_cells(canvas, building_predecessors, net.source.belt)
        try:
            stack = _splitter_stack_geometry(tap[0], tap[1], tap[2])
        except ValueError:
            return False
        for offset, stack_member in enumerate(stack):
            top = offset == len(stack) - 1
            for cell in junction.keepout_cells(
                tap[0],
                tap[1],
                int(stack_member.z),
                model_index=stack_member.model_index,
                yaw=stack_member.yaw,
            ):
                if top and cell in excused:
                    continue
                who = canvas.blocked.get(cell)
                if who == _TENTATIVE:
                    if tentative_ok:
                        continue
                    return False
                if (
                    who is not None
                    and 0 <= who < len(canvas.buildings)
                    and catalog.is_belt(canvas.buildings[who].item_id)
                ):
                    return False
        return True

    owned_source_starts: dict[int, frozenset[Cell]] = {}
    source_hint: dict[int, Cell] = {}
    sink_hint: dict[int, Cell] = {}
    rejected_starts: dict[int, set[Cell]] = defaultdict(set)
    rejected_goals: dict[int, set[Cell]] = defaultdict(set)
    rejected_path_cells: dict[int, set[Cell]] = defaultdict(set)
    rejected_source_hints: dict[int, set[Cell]] = defaultdict(set)
    rejected_sink_hints: dict[int, set[Cell]] = defaultdict(set)
    guard_claims: dict[Cell, set[int]] = defaultdict(set)
    path_guards: dict[int, set[Cell]] = {}
    planned_taps: dict[Cell, set[int]] = defaultdict(set)
    source_access_walls: dict[int, tuple[Cell, ...]] = {}
    destination_access_walls: dict[int, tuple[Cell, ...]] = {}
    source_access_blockers: dict[int, tuple[NetId, ...]] = {}
    # Splitters emitted before detailed routing already own permanent keep-out
    # cells.  A speculative tap may overlap one of those cells; withdrawing the
    # tap must remove only its conditional claim, never the older Splitter's
    # guard.  Otherwise a later net can route a foreign belt through the cleared
    # cell and exact certification refuses the finished placement.
    permanent_guard = frozenset(canvas.guard)
    path_tap: dict[int, Cell] = {}

    def _inside_grid(cell: Cell) -> bool:
        x, y, level = cell
        x0, y0, x1, y1 = grid.span
        return x0 <= x <= x1 and y0 <= y <= y1 and 0 <= level < LEVELS

    def _claim_junction_guard(index: int, tap: Cell | None) -> None:
        if tap is None:
            return
        planned_taps[tap].add(index)
        path_tap[index] = tap
        excused = set(paths[index])
        for sibling in src_group.get(index, ()):
            sibling_path = paths.get(sibling, ())
            if tap in sibling_path:
                excused.update(sibling_path)
        claimed: set[Cell] = set()
        stack = _splitter_stack_geometry(tap[0], tap[1], tap[2])
        for offset, stack_member in enumerate(stack):
            top = offset == len(stack) - 1
            for cell in junction.keepout_cells(
                tap[0],
                tap[1],
                int(stack_member.z),
                model_index=stack_member.model_index,
                yaw=stack_member.yaw,
            ):
                if (top and cell in excused) or not _inside_grid(cell):
                    continue
                guard_claims[cell].add(index)
                canvas.guard.add(cell)
                if cell not in owner:
                    grid.block(cell)
                claimed.add(cell)
        if claimed:
            path_guards[index] = claimed

    def _retire_served_roles(index: int, path: tuple[Cell, ...]) -> None:
        for key, role, source in roles_by_net[index]:
            token = (key, role)
            if token in retired_roles:
                continue
            endpoint_cells = path[:2] if source else path[-2:]
            retired = _retire_port_corridor(canvas, key, endpoint_cells)
            if retired is None:
                continue
            retired_roles[token] = retired
            for cell in (retired.access, retired.exit):
                if cell not in owner and canvas.free(cell):
                    grid.restore(cell)
            retired_indices = {
                grid.index(retired.access),
                grid.index(retired.exit),
            }
            grid.reserved = tuple(
                reservation
                for reservation in grid.reserved
                if reservation[0] not in retired_indices
            )

    def _restore_unserved_roles(index: int) -> None:
        for key, role, _source in roles_by_net[index]:
            token = (key, role)
            retired = retired_roles.get(token)
            if retired is None:
                continue
            if any(member != index and member in paths for member in role_members[token]):
                continue
            _restore_port_corridor(canvas, key, retired)
            del retired_roles[token]
            grid.block(retired.access)
            grid.block(retired.exit)
            grid.reserved = tuple(
                sorted(
                    (
                        *grid.reserved,
                        (grid.index(retired.access), key),
                        (grid.index(retired.exit), key),
                    )
                )
            )


    def _selected_hints(
        path: Sequence[Cell],
        offers: tuple[Mapping[Cell, Cell], Mapping[Cell, Cell], Mapping[Cell, Cell]],
    ) -> tuple[Cell | None, Cell | None, Cell | None]:
        """Freeze the endpoint promises from the search that selected ``path``."""
        source_offers, sink_offers, guard_offers = offers
        return (
            source_offers.get(path[0]),
            sink_offers.get(path[-1]),
            guard_offers.get(path[0]),
        )

    def _stake(
        index: int,
        path: tuple[Cell, ...],
        *,
        hints: tuple[Cell | None, Cell | None, Cell | None],
    ) -> None:
        """Put a path down with the exact sibling endpoints it selected."""
        selected = hints
        paths[index] = path
        if selected[0] is not None:
            source_hint[index] = selected[0]
        else:
            source_hint.pop(index, None)
        if selected[1] is not None:
            sink_hint[index] = selected[1]
        else:
            sink_hint.pop(index, None)
        for cell in path:
            canvas.blocked[cell] = _TENTATIVE
            grid.block(cell)
            owner[cell] = index
        _claim_junction_guard(index, selected[2])
        _retire_served_roles(index, path)

    def _unstake(index: int) -> None:
        """Take a path, its exact endpoint, and its conditional guard up."""
        _restore_unserved_roles(index)
        tap = path_tap.pop(index, None)
        if tap is not None:
            planned = planned_taps[tap]
            planned.discard(index)
            if not planned:
                del planned_taps[tap]
        for cell in path_guards.pop(index, ()):
            claims = guard_claims[cell]
            claims.discard(index)
            if claims:
                continue
            del guard_claims[cell]
            if cell not in permanent_guard:
                canvas.guard.discard(cell)
            if cell not in owner and canvas.free(cell):
                grid.restore(cell)
        source_hint.pop(index, None)
        sink_hint.pop(index, None)
        for cell in paths.pop(index):
            if canvas.blocked.get(cell, -1) == _TENTATIVE:
                del canvas.blocked[cell]
                grid.restore(cell)
            if owner.get(cell) == index:
                del owner[cell]

    def _ends(
        index: int,
        *,
        tentative_ok: bool = False,
    ) -> tuple[
        list[Cell],
        set[Cell],
        tuple[dict[Cell, Cell], dict[Cell, Cell], dict[Cell, Cell]],
    ]:
        """This net's start and goal cells, and its port claim as a side effect.

        Factored out because the repair pass has to ask the SAME question the
        round asks.  A repair that built its ends differently would find a path
        the committer cannot attach at either end -- which is precisely the class
        of bug `3f04239` and `00d1f78` were.  The caller clears
        ``canvas.routing_ports`` once its search returns.
        """
        net = nets[index]
        source = net.source
        # Claim this net's port reservations for the duration of its search,
        # so its own way in and out reads as free while every other port's
        # stays held.
        canvas.routing_ports = frozenset(
            {
                (net.source.x, net.source.y, net.source.z),
                (net.dst.x, net.dst.y, net.dst.z),
            }
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
        sibling_set = set(siblings)
        owned_guard: dict[Cell, Cell] = {}
        ambiguous_guard: set[Cell] = set()
        for sibling in siblings:
            tap = path_tap.get(sibling)
            if tap is None:
                continue
            for cell in path_guards.get(sibling, ()):
                claims = guard_claims.get(cell, set())
                if not claims or not claims <= sibling_set or cell in permanent_guard:
                    continue
                previous = owned_guard.get(cell)
                if previous is None or previous == tap:
                    owned_guard[cell] = tap
                else:
                    ambiguous_guard.add(cell)
        for cell in ambiguous_guard:
            owned_guard.pop(cell, None)
        needs_junction = any(s in paths for s in siblings) or (
            canvas.buildings[source.belt].output_obj is not None
        )
        source_provenance: dict[Cell, Cell] = {}
        starts: list[Cell] = []
        direct_ports: set[int] = set()
        direct_ports_valid = True
        source_belt = canvas.buildings[source.belt]
        incoming = building_predecessors[source.belt]
        mixed_height = needs_junction and bool(source.z % 2)
        carry_direction: tuple[int, int] | None = None
        if mixed_height:
            if len(incoming) != 1 or source_belt.output_obj is None:
                direct_ports_valid = False
            else:
                feed_direction = _cardinal_direction(
                    source_belt,
                    canvas.buildings[incoming[0]],
                )
                carry_direction = _cardinal_direction(
                    source_belt,
                    canvas.buildings[source_belt.output_obj],
                )
                if (
                    feed_direction is None
                    or carry_direction is None
                    or feed_direction != (-carry_direction[0], -carry_direction[1])
                ):
                    direct_ports_valid = False
                    carry_direction = None
        prospective_splitter = _splitter_stack_geometry(
            source_belt.x,
            source_belt.y,
            source.z,
            carry_direction=carry_direction,
        )[-1]
        if needs_junction:
            if len(incoming) != 1:
                direct_ports_valid = False
            else:
                feed_port = splitter_ports.expected_path_port(
                    prospective_splitter,
                    source_belt,
                    canvas.buildings[incoming[0]],
                )
                if feed_port is None:
                    direct_ports_valid = False
                else:
                    direct_ports.add(feed_port)
            if source_belt.output_obj is not None:
                carry_port = splitter_ports.expected_path_port(
                    prospective_splitter,
                    source_belt,
                    canvas.buildings[source_belt.output_obj],
                )
                if carry_port is None or carry_port in direct_ports:
                    direct_ports_valid = False
                else:
                    direct_ports.add(carry_port)
            for sibling in siblings:
                sibling_path = paths.get(sibling)
                if not sibling_path:
                    continue
                first = sibling_path[0]
                if abs(first[0] - source.x) + abs(first[1] - source.y) != 1:
                    continue
                branch_attachment = replace(
                    source_belt,
                    z=Fraction(first[2]),
                )
                port = splitter_ports.expected_path_port(
                    prospective_splitter,
                    branch_attachment,
                    replace(branch_attachment, x=first[0], y=first[1]),
                )
                if port is None or port in direct_ports:
                    direct_ports_valid = False
                    break
                direct_ports.add(port)
        occupied_source_access: list[Cell] = []
        # A source Splitter adds its own stub as the branch head's sole reverse
        # predecessor.  Reusing a cell that an already-selected destination
        # merge targets would make that reverse link last-writer dependent.
        existing_sink_targets = frozenset(sink_hint.values())
        if not (
            needs_junction
            and (
                not direct_ports_valid
                or not (
                    _can_junction(source.x, source.y, source.z)
                    and _direct_tap_clear(net, tentative_ok=tentative_ok)
                )
            )
        ):
            branch_level = source.z - 1 if mixed_height else source.z
            for dx, dy in _STEPS:
                if (
                    mixed_height
                    and carry_direction is not None
                    and dx * carry_direction[0] + dy * carry_direction[1] != 0
                ):
                    continue
                cell = (source.x + dx, source.y + dy, branch_level)
                if cell in rejected_starts[index] or (
                    needs_junction and cell in existing_sink_targets
                ):
                    continue
                if needs_junction:
                    branch_attachment = replace(
                        source_belt,
                        z=Fraction(branch_level),
                    )
                    port = splitter_ports.expected_path_port(
                        prospective_splitter,
                        branch_attachment,
                        replace(branch_attachment, x=cell[0], y=cell[1]),
                    )
                    if port is None or port in direct_ports:
                        continue
                if (
                    canvas.free(cell)
                    or (cell in owned_guard and canvas.free_owned_guard(cell))
                    or (tentative_ok and canvas.blocked.get(cell) == _TENTATIVE)
                ):
                    starts.append(cell)
                elif cell in owner:
                    occupied_source_access.append(cell)
        guard_provenance = dict(source_provenance)
        if needs_junction:
            direct_tap = (source.x, source.y, source.z)
            for cell in starts:
                guard_provenance.setdefault(cell, direct_tap)
        frontier = _merge_frontier(
            canvas,
            paths,
            siblings,
            _can_junction,
            provenance=source_provenance,
            belt_prefab=(belt_id, belt_model),
            tentative_ok=tentative_ok,
            owned_guard=owned_guard,
        )
        guard_provenance.update(source_provenance)
        if existing_sink_targets:
            frontier.difference_update(existing_sink_targets)
            for cell in existing_sink_targets:
                source_provenance.pop(cell, None)
                guard_provenance.pop(cell, None)
        starts.extend(
            sorted(
                cell
                for cell in frontier - set(starts)
                if cell not in rejected_starts[index]
                and source_provenance.get(cell) not in rejected_source_hints[index]
            )
        )
        source_access_walls[index] = tuple(occupied_source_access) if not starts else ()
        # A shared source can become unusable without an occupied access cell:
        # an earlier sibling may consume the only legal branch topology. That
        # sibling is concrete blocking ownership even though the failed A*
        # search has an empty wall.
        source_access_blockers[index] = (
            tuple(_net_id(sibling) for sibling in siblings if sibling in paths)
            if not starts
            else ()
        )
        owned_source_starts[index] = frozenset(set(starts) & owned_guard.keys())
        reverse_link_guard = frozenset(
            paths[owner_index][0]
            for owner_index in path_tap
            if owner_index in paths
        )

        destination_access = tuple((net.dst.x + dx, net.dst.y + dy, net.dst.z) for dx, dy in _STEPS)
        sink_provenance: dict[Cell, Cell] = {}
        goals = {
            cell
            for cell in destination_access
            if canvas.free(cell) and cell not in rejected_goals[index]
        }
        frontier = _merge_frontier(
            canvas,
            paths,
            dst_group.get(index, ()),
            provenance=sink_provenance,
        )
        goals.update(
            cell
            for cell in frontier
            if cell not in rejected_goals[index]
            and sink_provenance.get(cell) not in rejected_sink_hints[index]
            and sink_provenance.get(cell) not in reverse_link_guard
        )
        # A zero-expansion access miss can still be congestion: earlier paths
        # may occupy every direct dock, leaving A* no start or goal and therefore
        # no explored wall to attribute. Retain those exact owners so repair can
        # rip up the paths that closed either endpoint instead of repeating the
        # same order with an anonymous dynamic-access failure.
        destination_access_walls[index] = (
            tuple(cell for cell in destination_access if cell in owner) if not goals else ()
        )
        # These maps belong to THIS endpoint query.  A path may be staked only
        # with the exact promises A* selected from, even if a later repair asks
        # `_ends` another question for the same net.
        offers = (
            dict(source_provenance),
            dict(sink_provenance),
            dict(guard_provenance),
        )
        return starts, goals, offers

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
        open_grid = replace(
            grid,
            occ=bytearray(grid.base),
            routing_flags=bytearray(grid.size),
            hist=None,
        )
        for guarded in guard_claims:
            if _inside_grid(guarded):
                open_grid.block(guarded)
        # The crossing charge rides on the history array, so the repair search
        # prices congestion exactly as the round does and adds a toll on top.
        # `pressure` is folded in here and the search is given 1.0, which keeps
        # the toll a fixed number of tiles rather than one that grows with the
        # round number.
        settled = grid.hist
        crossing = [0.0] * grid.size if settled is None else [v * pressure for v in settled]
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
                if abs(end[0] - port.x) + abs(end[1] - port.y) <= 1 and abs(end[2]) <= slack:
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
            starts, goals, through_offers = _ends(index, tentative_ok=True)
            # The repair grid deliberately makes settled paths passable. Let it
            # leave from or reach an endpoint dock those paths currently occupy
            # as well; the transaction below will move every owning victim
            # before this path is staked.
            starts.extend(source_access_walls.get(index, ()))
            goals.update(destination_access_walls.get(index, ()))
            through = _astar(
                canvas,
                starts,
                goals,
                history,
                1.0,
                bounds,
                budget,
                deadline,
                None,
                open_grid,
                owned_starts=owned_source_starts.get(index, ()),
                released_starts=source_access_walls.get(index, ()),
                forbidden=rejected_path_cells.get(index, ()),
                blocking_owners=owner,
            )
            canvas.routing_ports = frozenset()
            expansions += through.expansions
            round_expansions[index] = round_expansions.get(index, 0) + through.expansions
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
            junction_victims: set[int] = set()
            selected_tap = through_offers[2].get(through_path[0])
            if selected_tap is not None:
                tapped_sibling = next(
                    (
                        sibling
                        for sibling in src_group.get(index, ())
                        if selected_tap in paths.get(sibling, ())
                    ),
                    None,
                )
                excused: set[Cell] = set()
                if tapped_sibling is not None:
                    sibling_path = paths[tapped_sibling]
                    tap_at = sibling_path.index(selected_tap)
                    excused.update(sibling_path[max(0, tap_at - 2) : tap_at + 3])
                stack = _splitter_stack_geometry(*selected_tap)
                for offset, stack_member in enumerate(stack):
                    top = offset == len(stack) - 1
                    junction_victims.update(
                        _junction_guard_victims(
                            owner,
                            junction.keepout_cells(
                                selected_tap[0],
                                selected_tap[1],
                                int(stack_member.z),
                                model_index=stack_member.model_index,
                                yaw=stack_member.yaw,
                            ),
                            excused=excused if top else (),
                        )
                    )
            victims = _leaning(
                {owner[cell] for cell in through_path if cell in owner} | junction_victims
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
            saved = {
                hurt: (
                    paths[hurt],
                    source_hint.get(hurt),
                    sink_hint.get(hurt),
                    path_tap.get(hurt),
                )
                for hurt in victims
            }
            for hurt in victims:
                _unstake(hurt)
            _stake(
                index,
                through_path,
                hints=_selected_hints(through_path, through_offers),
            )
            # The displaced go looking for a way round, longest first for the
            # same reason the round orders that way.
            moved: list[int] = []
            for hurt in sorted(
                victims,
                key=lambda i: (
                    -(abs(nets[i].source.x - nets[i].dst.x) + abs(nets[i].source.y - nets[i].dst.y))
                ),
            ):
                starts, goals, again_offers = _ends(hurt)
                again = _astar(
                    canvas,
                    starts,
                    goals,
                    history,
                    pressure,
                    bounds,
                    budget,
                    deadline,
                    blame,
                    grid,
                    owned_starts=owned_source_starts.get(hurt, ()),
                    forbidden=rejected_path_cells.get(hurt, ()),
                    blocking_owners=owner,
                )
                canvas.routing_ports = frozenset()
                expansions += again.expansions
                round_expansions[hurt] = round_expansions.get(hurt, 0) + again.expansions
                if again.path is None:
                    if again.kind is RouteFailureKind.BUDGET:
                        # The transaction rolls back, so `index` remains the
                        # stranded net. Its outcome is still unknown when a
                        # displaced victim exhausted a per-search cap.
                        search_failures[index] = again
                        search_blockers[index] = ()
                    break
                _stake(
                    hurt,
                    again.path,
                    hints=_selected_hints(again.path, again_offers),
                )
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
            for hurt, (was, source_was, sink_was, tap_was) in saved.items():
                _stake(
                    hurt,
                    was,
                    hints=(source_was, sink_was, tap_was),
                )
            still.append(index)
        return still

    last_mile_counts = {
        "invocations": 0,
        "solved": 0,
        "proved": 0,
        "bounded": 0,
        "commit_rejected": 0,
        "restore_mismatch": 0,
        "relation_skipped_siblings": 0,
        "same_source_dropped": 0,
        "nodes": 0,
        "expansions": 0,
    }
    last_mile_seconds = 0.0
    last_mile_done = False
    #: One expansion allowance for the whole pass, shared by both runs.  Set
    #: once at pass entry so run 2 cannot re-derive a fresh quarter of whatever
    #: run 1 left behind.
    last_mile_floor = 0
    proved_stranded: set[int] = set()
    proved_round = -1
    relation_strips: tuple[int, ...] = ()
    relation_evidence = ""

    def _last_mile_report() -> LastMileReport:
        return LastMileReport(
            invocations=last_mile_counts["invocations"],
            solved=last_mile_counts["solved"],
            proved=last_mile_counts["proved"],
            bounded=last_mile_counts["bounded"],
            commit_rejected=last_mile_counts["commit_rejected"],
            restore_mismatch=last_mile_counts["restore_mismatch"],
            relation_skipped_siblings=last_mile_counts["relation_skipped_siblings"],
            same_source_dropped=last_mile_counts["same_source_dropped"],
            nodes=last_mile_counts["nodes"],
            expansions=last_mile_counts["expansions"],
            seconds=last_mile_seconds,
            relation_strips=relation_strips,
            relation_evidence=relation_evidence,
        )

    def _cluster_offers(
        index: int,
    ) -> tuple[dict[Cell, Cell], dict[Cell, Cell], dict[Cell, Cell]]:
        """This net's `_ends` offer maps, as of right now."""
        _starts, _goals, offers = _ends(index)
        canvas.routing_ports = frozenset()
        return offers

    def _cluster_search(index: int, constraints: frozenset[Cell]) -> _PathSearchResult:
        """One cluster net's search: the round's own call, capped and constrained.

        The private budget is the deadline discipline.  `_MAX_EXPANSIONS` lets
        one search run for a large fraction of a second, and this pass makes
        hundreds of them at the end of an attempt that is already near its
        budget, so a quarter of that cap bounds how far past the last bound
        check the pass can travel.  Exhausting it returns
        `RouteFailureKind.BUDGET`, which `solve_cluster` turns into BOUNDED --
        which is correct: a capped search decided nothing.

        A constraint cell OUTSIDE the search's indexed extent is dropped in
        silence, which degrades the run to a bound rather than proving anything
        false -- but it burns the node budget getting there.  Every constraint
        is a cell of a path this same pass routed on this same grid, so
        containment is an invariant rather than a hope, and checking it costs
        one comparison per constraint.
        """
        starts, goals, _offers = _ends(index)
        span_x0, span_y0, span_x1, span_y1 = grid.span
        assert all(
            span_x0 <= cell[0] <= span_x1
            and span_y0 <= cell[1] <= span_y1
            and 0 <= cell[2] < LEVELS
            for cell in constraints
        ), "a cluster constraint left the routing grid's indexed extent"
        allowance = min(
            last_mile.B_LOW_LEVEL_EXPANSIONS,
            max(0, budget["left"] - last_mile_floor),
        )
        private = {"left": allowance}
        found = _astar(
            canvas,
            starts,
            goals,
            history,
            pressure,
            bounds,
            private,
            deadline,
            {},
            grid,
            owned_starts=owned_source_starts.get(index, ()),
            forbidden=frozenset(rejected_path_cells.get(index, ())) | constraints,
            blocking_owners=owner,
        )
        canvas.routing_ports = frozenset()
        budget["left"] -= allowance - private["left"]
        return found

    def _cluster_environment() -> last_mile.ClusterEnvironment:
        return last_mile.ClusterEnvironment(
            search=_cluster_search,
            offers=_cluster_offers,
            budget_left=lambda: budget["left"],
            budget_floor=last_mile_floor,
            expired=lambda: _expired(deadline),
        )

    def _source_is_junctionable(index: int) -> bool:
        """Whether this net's own source lane could take a splitter.

        `build_cluster` needs it because a cluster is built out of UNSTAKED
        nets, and unstaking is exactly what makes two stranded nets on one
        source lane look independent of each other.  A net with no source port
        has no lane to share, so it never constrains a sibling.
        """
        source = nets[index].src
        return source is None or _can_junction(source.x, source.y, source.z)

    def _capture(run: int, problem: last_mile.ClusterProblem) -> None:
        """Hand a developer-tool hook everything needed to replay this run.

        Called AFTER the unstake that builds each run's environment -- the
        cluster release for run 1, the whole-pack sweep for run 2 -- so what
        the bench snapshots is the grid the search will actually see.
        """
        hook = last_mile.CAPTURE
        if hook is None:
            return
        ends: dict[int, tuple[list[Cell], set[Cell], frozenset[Cell]]] = {}
        for index in problem.nets:
            starts, goals, _offers = _ends(index)
            ends[index] = (list(starts), set(goals), canvas.routing_ports)
            canvas.routing_ports = frozenset()
        hook(
            last_mile.ClusterCapture(
                run=run,
                canvas=canvas,
                grid=grid,
                history=history,
                pressure=pressure,
                bounds=bounds,
                problem=problem,
                ends=ends,
                budget_left=budget["left"],
                budget_floor=last_mile_floor,
                deadline_remaining=(
                    None if deadline is None else deadline - time.monotonic()
                ),
                owned_starts={
                    index: frozenset(owned_source_starts.get(index, ()))
                    for index in problem.nets
                },
                rejected={
                    index: frozenset(rejected_path_cells.get(index, ()))
                    for index in problem.nets
                },
                blocking_owners=dict(owner),
            )
        )

    def _round_state() -> tuple[object, ...]:
        """Everything the pass borrows, in a form two snapshots can compare.

        `grid.reserved` is in here because it is NOT constant across a pass:
        `_retire_served_roles` filters it and `_restore_unserved_roles` rebuilds
        it.  A role that came back not at all is precisely the silent corruption
        this comparison exists to catch.

        It is compared SORTED, and that is not laziness.  The two writers
        disagree about order by construction: `_restore_unserved_roles`
        canonicalises the WHOLE tuple with `sorted`, while
        `_retire_served_roles` only filters it, order-preserving.  A pass whose
        entry tuple is unsorted -- it is built from `canvas.reserved` in port
        CONSTRUCTION order, not index order -- therefore fails an ordered
        comparison after a perfectly correct restore, because any restore
        sorts the tuple and no re-retire can un-sort it.  Order is not
        observable either: the tuple's only consumer in this router is
        `_routing_flags`, which iterates it writing `flags[at] = 0`, and
        `_open/_close_every_corridor` save and restore it verbatim.  Comparing
        it ordered reported a mismatch for a difference no reader can see, and
        cost `universe-matrix/output-products` both of its cluster proofs.

        FOUR tables are deliberately EXEMPT: `_ends` overwrites
        `source_access_walls`, `destination_access_walls`,
        `source_access_blockers` and `owned_source_starts` for whichever net it
        is called on, so the last cluster search to run leaves its own values
        behind.  They are
        derived-and-overwritten rather than borrowed -- every reader gets them
        from the `_ends` call that produced them, and the only consumer that
        outlives a search is `round_failures`, which is built before
        `_last_mile` is ever reached.  Comparing them would report a mismatch
        for a difference no later reader can observe.
        """
        return (
            dict(paths),
            dict(owner),
            bytes(grid.occ),
            tuple(sorted(grid.reserved)),
            set(canvas.guard),
            {cell for cell, holder in canvas.blocked.items() if holder == _TENTATIVE},
            dict(path_tap),
            {index: set(cells) for index, cells in path_guards.items()},
            {cell: set(claims) for cell, claims in guard_claims.items()},
            dict(canvas.reserved),
            dict(canvas.port_corridors),
        )

    def _restore_staked(
        order: Sequence[int],
        staked: Mapping[int, tuple[Cell, ...]],
        held: Mapping[int, tuple[Cell | None, Cell | None, Cell | None]],
        before: tuple[object, ...],
    ) -> bool:
        """Re-stake in the original order and report whether it worked.

        Used by BOTH releases -- the cluster release in `_last_mile` and the
        whole-pack sweep run 2 makes -- so run 2 cannot skip the check that run
        1 must pass.  The order matters because `_claim_junction_guard` computes
        its `excused` set from the sibling paths already down.

        It DEGRADES rather than asserts: an `AssertionError` inside
        `_route_all` becomes a CRASH row in `scripts/audit.py` and fails the
        corpus gate on the very condition the gate is measuring.
        """
        for index in order:
            if index not in paths:
                _stake(index, staked[index], hints=held[index])
        if before == _round_state():
            return True
        last_mile_counts["restore_mismatch"] += 1
        return False

    def _tally(result: last_mile.ClusterResult) -> None:
        nonlocal last_mile_seconds
        last_mile_counts["nodes"] += result.nodes
        last_mile_counts["expansions"] += result.expansions
        last_mile_seconds += result.seconds

    def _cluster_is_sibling_free(problem: last_mile.ClusterProblem) -> bool:
        """Whether unstaking the pack can take nothing away from this cluster.

        `_ends` offers merge points onto SIBLING paths, and for a walled-in
        lane that is the only way in.  A net with no siblings had no merge
        frontier to lose, so for such a cluster -- and only such a cluster --
        "every other net removed" is a relaxation rather than a mutilation.
        """
        return not any(
            src_group.get(index, ()) or dst_group.get(index, ())
            for index in problem.nets
        )

    def _open_every_corridor() -> _CorridorRelease:
        """Retire EVERY port's corridor, as if every role had been served.

        Unstaking the pack is not enough to make run 2's world loose.
        `_stake` -> `_retire_served_roles` DELETES a served port's corridor
        from `canvas.reserved`, `canvas.port_corridors` and `grid.reserved`,
        and `_unstake` -> `_restore_unserved_roles` puts it all back and
        `grid.block`s the two cells.  `_Canvas.free` refuses any reserved cell
        that is not the searching net's own, so a corridor a staked non-cluster
        net had retired is FREE to a cluster net in run 1 and RESERVED again in
        run 2 -- run 2 would be TIGHTER than run 1 in exactly those cells, and
        a closure there could forbid a placement a realizable world allows.

        Retirement is per served role and this has no served paths to choose
        corridors from, so it retires every corridor of every port at once,
        which is the loosest the reservation tables can be.
        """
        release = _CorridorRelease(
            reserved=dict(canvas.reserved),
            corridors=dict(canvas.port_corridors),
            grid_reserved=tuple(grid.reserved),
            opened=(),
        )
        canvas.reserved.clear()
        canvas.port_corridors.clear()
        grid.reserved = ()
        # Two guards, and the second one is the whole correctness of the
        # inverse.  `cell not in owner and canvas.free(cell)` is what
        # `_retire_served_roles` uses, for the same reason: a reserved cell can
        # also be blocked by a path or a guard, and that blocking is not this
        # release's to undo.  `occ != base` then keeps only the cells this
        # release actually FREES -- a corridor nobody ever served was never
        # `grid.block`ed, so re-blocking it on the way out would hand the round
        # back tighter than it was lent.
        #
        # `canvas.free` also consults `canvas.limit`, which is CONSTANT inside
        # one pass: it is a plain field with no setter, and the only two writes
        # in the module (`_prepare_routing_problem`, `_place_coaters`) both run
        # before `_route_all` is entered, so the filter cannot see a different
        # extent from the one that retired the corridor.
        opened = tuple(
            cell
            for cell in release.reserved
            if cell not in owner
            and canvas.free(cell)
            and grid.occ[grid.index(cell)] != grid.base[grid.index(cell)]
        )
        for cell in opened:
            grid.restore(cell)
        return replace(release, opened=opened)

    def _close_every_corridor(release: _CorridorRelease) -> None:
        """Undo `_open_every_corridor`, exactly and in the inverse order."""
        for cell in release.opened:
            grid.block(cell)
        canvas.reserved.clear()
        canvas.reserved.update(release.reserved)
        canvas.port_corridors.clear()
        canvas.port_corridors.update(release.corridors)
        grid.reserved = release.grid_reserved

    def _relaxed_cluster_result(
        problem: last_mile.ClusterProblem,
    ) -> last_mile.ClusterResult | None:
        """Re-run CBS in the LOOSEST world the cluster can face; see spec 5.2.

        Callers MUST have checked `_cluster_is_sibling_free` first.

        A relation no-good excludes a whole region, so it is sound only if run
        2's world is at least as loose as every world the packer could realise
        for these nets at this arrangement.  Looser than needed only weakens
        the cut; TIGHTER makes it forbid placements that work.  Three things
        are loosened, and each was a way for run 2 to come out tighter:

        - Every net is unstaked, so no path, `_TENTATIVE` cell, conditional
          guard or owner survives.
        - Every port corridor is retired (`_open_every_corridor`), because
          unstaking RE-RESERVES the corridors staked nets had retired.
        - `planned_taps` starts EMPTY and only the cluster's own taps
          accumulate, because those are the only taps every realizable world
          has.  Run 1's table is saved and put back afterwards.  Three of
          `_can_junction`'s four uses of that table get TIGHTER as it grows --
          the frame-ban scan, the `len(planned_here) >= 2` cap and the
          collider scan -- so keeping run 1's taps would over-constrain run 2.
          The fourth use, the conditional-guard refusal, gets tighter as the
          table SHRINKS, so `relaxed_junctions` exempts run 2 from that one.

        The relaxation also needs every routing-derived constraint gone: four
        of the five per-net rejection sets are read inside `_ends` and the
        fifth, `rejected_path_cells`, is the search's `forbidden` argument.
        All five are saved, emptied for the cluster's nets, and put back.

        Everything taken away is restored in the `finally` before
        `_restore_staked` re-stakes, so the `_round_state()` comparison sees
        the round it was handed.
        """
        nonlocal relaxed_junctions
        if budget["left"] <= 0 or _expired(deadline):
            return None
        rejections = (
            rejected_starts,
            rejected_goals,
            rejected_path_cells,
            rejected_source_hints,
            rejected_sink_hints,
        )
        saved = [
            {index: set(table[index]) for index in problem.nets if index in table}
            for table in rejections
        ]
        every = list(paths)
        held_all = {
            index: (
                source_hint.get(index),
                sink_hint.get(index),
                path_tap.get(index),
            )
            for index in every
        }
        staked = {index: paths[index] for index in every}
        # Saved so the round gets its own table back whatever run 2 does to it;
        # `_restore_staked` rebuilds the same content from the paths, and this
        # is the belt to that braces.
        taps_before = {cell: set(members) for cell, members in planned_taps.items()}
        before_all = _round_state()
        release: _CorridorRelease | None = None
        try:
            for table in rejections:
                for index in problem.nets:
                    table[index].clear()
            for index in every:
                _unstake(index)
            release = _open_every_corridor()
            # Empty, not run 1's: the cluster's own taps are the only ones
            # every realizable world has, and they accumulate as CBS stakes.
            planned_taps.clear()
            relaxed_junctions = True
            _capture(2, problem)
            return last_mile.solve_cluster(problem, _cluster_environment())
        finally:
            # Put the world back BEFORE re-staking, so `_stake` rebuilds the
            # taps and the retirements from the paths exactly as run 1's
            # restore does.  Then the SAME verified restore run 1 uses, so run
            # 2 cannot skip the check that run 1 must pass; its return value is
            # read by the caller through `restore_mismatch`.
            relaxed_junctions = False
            planned_taps.clear()
            planned_taps.update(taps_before)
            if release is not None:
                _close_every_corridor(release)
            _restore_staked(every, staked, held_all, before_all)
            for table, snapshot in zip(rejections, saved, strict=True):
                for index, cells in snapshot.items():
                    table[index].clear()
                    table[index].update(cells)

    def _record_cluster_relation(problem: last_mile.ClusterProblem) -> None:
        """Turn a closed run 1 into a relation no-good, or say why not.

        Called ONLY after run 1 closed and the round came back, and it never
        makes a claim of its own: the four ways out below either leave run 1's
        proof exactly as it was or, on a lost round, withdraw it.
        """
        nonlocal proved_round, relation_strips, relation_evidence
        if not _cluster_is_sibling_free(problem):
            last_mile_counts["relation_skipped_siblings"] += 1
            return
        mismatches = last_mile_counts["restore_mismatch"]
        relaxed = _relaxed_cluster_result(problem)
        if relaxed is None:
            return
        _tally(relaxed)
        if last_mile_counts["restore_mismatch"] != mismatches:
            # Run 2 did not put the round back.  The incumbent the run-1 claim
            # describes is no longer known to be the incumbent that was
            # proved, so BOTH claims go.
            last_mile_counts["proved"] -= 1
            last_mile_counts["bounded"] += 1
            proved_round = -1
            proved_stranded.clear()
            return
        if relaxed.outcome is not last_mile.ClusterOutcome.PROVED:
            return
        instances = last_mile.cluster_strips(
            problem,
            {
                index: (
                    _net_id(index).source_strip,
                    _net_id(index).destination_strip,
                )
                for index in problem.nets
            },
        )
        # A cluster on one strip has no relative placement to forbid, and
        # `LastMileReport` refuses to carry it.
        if len(instances) < _RELATION_STRIP_PAIR:
            return
        relation_strips = instances
        relation_evidence = (
            f"cluster: nets={tuple(problem.nets)!r} "
            f"truncated={problem.truncated} "
            f"sibling_closed={problem.sibling_closed}"
        )

    def _last_mile(round_stranded: list[int], round_index: int) -> list[int]:
        """Search the conflict cluster once per pass; see the Phase B spec 5.6."""
        nonlocal last_mile_done, last_mile_floor, proved_round
        if (
            last_mile_done
            or not round_stranded
            or len(round_stranded) > last_mile.B_MAX_STRANDED
            or budget["left"] <= 0
            or _expired(deadline)
            or (
                deadline is not None
                and deadline - time.monotonic() < last_mile.B_MIN_SECONDS
            )
        ):
            return round_stranded
        last_mile_done = True
        last_mile_counts["invocations"] += 1
        last_mile_floor = budget["left"] - int(
            last_mile.B_CBS_EXPANSION_SHARE * budget["left"]
        )
        index_by_id = {_net_id(index): index for index in range(len(nets))}
        problem = last_mile.build_cluster(
            sorted(round_stranded),
            walls={
                index: search_failures[index].wall
                for index in round_stranded
                if index in search_failures
            },
            blockers={
                index: tuple(
                    index_by_id[blocker]
                    for blocker in search_blockers.get(index, ())
                    if blocker in index_by_id
                )
                for index in round_stranded
            },
            owner=owner,
            paths=paths,
            endpoints={
                index: _endpoint_cells(nets[index]) for index in range(len(nets))
            },
            src_group=src_group,
            dst_group=dst_group,
            source_junctionable=_source_is_junctionable,
        )
        last_mile_counts["same_source_dropped"] += problem.same_source_dropped
        # A stranded net the cluster refused is still stranded when the cluster
        # is solved and committed: it was never in the problem, so nothing
        # routed it.  Reporting an empty round for it would tell the caller the
        # pack is finished when one net has no path at all.
        left_out = [
            index for index in round_stranded if index not in set(problem.stranded)
        ]
        # `paths` is insertion-ordered and only `_stake` writes it, so
        # `list(paths)` IS the stake order -- which the restore has to replay,
        # because `_claim_junction_guard` computes its `excused` set from the
        # sibling paths already down.
        order = [index for index in paths if index in set(problem.nets)]
        released = {index: paths[index] for index in order}
        held = {
            index: (
                source_hint.get(index),
                sink_hint.get(index),
                path_tap.get(index),
            )
            for index in order
        }
        before = _round_state()
        environment = _cluster_environment()

        for index in order:
            _unstake(index)
        _capture(1, problem)
        result = last_mile.solve_cluster(problem, environment)
        _tally(result)

        if result.outcome is last_mile.ClusterOutcome.SOLVED:
            # Stake in ascending index order, re-querying each net's offers
            # THROUGH THE ENVIRONMENT as we go: the offers CBS saw were
            # collected with NO cluster net staked, and every stake takes cells
            # the next net's offers were computed against.  A stale hint is
            # exactly the defect `_ends`' own docstring names.  Going through
            # `environment.offers` rather than the closure keeps the field a
            # live part of the contract the bench's stub also implements.
            #
            # A SOLVED result must carry a path for EVERY cluster net.
            # `solve_cluster` gates its return on exactly that, and
            # `ClusterResult` cannot re-check it because it does not carry the
            # net list -- so the one place that can is here, where the list is.
            # A short mapping is a broken solver rather than a fact about the
            # grid, and it degrades the way a refused commit does: nothing to
            # keep and nothing to claim.  A `KeyError` here would instead be a
            # CRASH row, which is a failure of the gate rather than a reading
            # from it.
            unlinked_now: tuple[int, ...] = problem.nets
            if all(index in result.paths for index in problem.nets):
                for index in problem.nets:
                    path = result.paths[index]
                    _stake(
                        index,
                        path,
                        hints=_selected_hints(path, environment.offers(index)),
                    )
                unlinked_now, _details_now = commit_once()
            if not unlinked_now:
                last_mile_counts["solved"] += 1
                return left_out
            # A commit-link rejection is exact static evidence about buildings,
            # not a routing proof.  Put the round back and report a bound.
            for index in problem.nets:
                if index in paths:
                    _unstake(index)
            _restore_staked(order, released, held, before)
            last_mile_counts["commit_rejected"] += 1
            last_mile_counts["bounded"] += 1
            return round_stranded

        restored = _restore_staked(order, released, held, before)
        if result.outcome is last_mile.ClusterOutcome.PROVED and restored:
            last_mile_counts["proved"] += 1
            proved_round = round_index
            proved_stranded.clear()
            proved_stranded.update(round_stranded)
            _record_cluster_relation(problem)
        else:
            last_mile_counts["bounded"] += 1
        return round_stranded

    route_distance = tuple(
        abs(net.source.x - net.dst.x) + abs(net.source.y - net.dst.y) for net in nets
    )
    source_family = {
        index: tuple(sorted((index, *src_group.get(index, ()))))
        for index in range(len(nets))
    }
    source_family_distance = {
        index: max(route_distance[member] for member in source_family[index])
        for index in range(len(nets))
    }

    priority: set[int] = set()
    round_limit = 1 if len(nets) >= _SINGLE_ROUND_NETS else RRR_MAX
    for it in range(round_limit):
        iterations = it + 1
        round_expansions.clear()
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
        # Keep each shared-source family contiguous. Compact callers can put
        # junction-dependent families ahead of singleton trunks; ordinary
        # packs retain established longest-first routing.
        order = sorted(
            range(len(nets)),
            key=lambda i: (
                not any(member in priority for member in source_family[i]),
                _net_id(i).role is not NetRole.PROLIFERATOR,
                -len(source_family[i]) if prioritize_source_families else 0,
                -source_family_distance[i],
                source_family[i][0],
                -route_distance[i],
            ),
        )
        stranded: list[int] = []
        for i in order:
            if _expired(deadline):
                current_failures = {
                    index: _failure(
                        index,
                        search_failures[index],
                        search_blockers[index],
                    )
                    for index in stranded
                }
                return _budget_result(paths, current_failures)
            starts, goals, route_offers = _ends(i)
            searched = _astar(
                canvas,
                starts,
                goals,
                history,
                pressure,
                bounds,
                budget,
                deadline,
                blame,
                grid,
                owned_starts=owned_source_starts.get(i, ()),
                forbidden=rejected_path_cells.get(i, ()),
                blocking_owners=owner,
            )
            search_expansions = searched.expansions
            # The first route from a shared producer defines every later
            # branch's source frontier. If its cheapest path contains no legal
            # Splitter site and the lane-end tap is statically impossible,
            # routing it unchanged guarantees a later zero-start failure. Price
            # each rejected candidate path and try a small fixed set of
            # alternatives, accepting only a path that carries a proved future
            # tap. This is a bounded focused search, not another RRR round.
            siblings = src_group.get(i, ())
            source = nets[i].source
            if (
                searched.path is not None
                and siblings
                and not any(sibling in paths for sibling in siblings)
            ):
                direct_tap = (source.x, source.y, source.z)
                direct_tap_available = _can_junction(*direct_tap) and _direct_tap_clear(nets[i])
                if not direct_tap_available:
                    future_provenance: dict[Cell, Cell] = {}
                    _merge_frontier(
                        canvas,
                        {i: searched.path},
                        (i,),
                        _can_junction,
                        provenance=future_provenance,
                        belt_prefab=(belt_id, belt_model),
                    )
                    if not future_provenance:
                        original = searched
                        candidate = searched
                        for _ in range(4):
                            assert candidate.path is not None
                            for cell in candidate.path:
                                history[cell] += _BLAME_WEIGHT
                            grid.refresh_history(history)
                            alternative = _astar(
                                canvas,
                                starts,
                                goals,
                                history,
                                pressure,
                                bounds,
                                budget,
                                deadline,
                                blame,
                                grid,
                                owned_starts=owned_source_starts.get(i, ()),
                                forbidden=rejected_path_cells.get(i, ()),
                                blocking_owners=owner,
                            )
                            search_expansions += alternative.expansions
                            if alternative.path is None:
                                break
                            alternative_provenance: dict[Cell, Cell] = {}
                            _merge_frontier(
                                canvas,
                                {i: alternative.path},
                                (i,),
                                _can_junction,
                                provenance=alternative_provenance,
                                belt_prefab=(belt_id, belt_model),
                            )
                            if alternative_provenance:
                                searched = alternative
                                route_offers[2][alternative.path[0]] = next(
                                    iter(alternative_provenance.values())
                                )
                                break
                            candidate = alternative
                        else:
                            searched = original
            # A selected Splitter owns more than its tap cell. Model 40's
            # odd-plane branch also emits a synthetic lower attachment on the
            # tap's x/y cell, and the game's collider exception reaches only
            # the first two routed belts beyond that attachment. A* sees neither
            # fact: without this exact post-path check it can revisit the
            # attachment cell or turn a third belt through the Splitter's
            # keep-out, producing duplicate/colliding belts at commit.
            for _ in range(4):
                if searched.path is None:
                    break
                selected_tap = route_offers[2].get(searched.path[0])
                if selected_tap is None:
                    break
                attachment_cell = (
                    selected_tap[0],
                    selected_tap[1],
                    selected_tap[2] - 1 if selected_tap[2] % 2 else selected_tap[2],
                )
                keepout = {
                    cell
                    for stack_member in _splitter_stack_geometry(*selected_tap)
                    for cell in junction.keepout_cells(
                        selected_tap[0],
                        selected_tap[1],
                        int(stack_member.z),
                        model_index=stack_member.model_index,
                        yaw=stack_member.yaw,
                    )
                }
                illegal = set(searched.path[2:]) & keepout
                if attachment_cell in searched.path:
                    illegal.add(attachment_cell)
                if not illegal:
                    break
                rejected_path_cells[i].update(illegal)
                searched = _astar(
                    canvas,
                    starts,
                    goals,
                    history,
                    pressure,
                    bounds,
                    budget,
                    deadline,
                    blame,
                    grid,
                    owned_starts=owned_source_starts.get(i, ()),
                    forbidden=rejected_path_cells[i],
                    blocking_owners=owner,
                )
                search_expansions += searched.expansions
            if searched.path is None and not searched.wall:
                access_wall = source_access_walls.get(i, ()) + destination_access_walls.get(i, ())
                if access_wall:
                    searched = replace(
                        searched,
                        kind=RouteFailureKind.SEALED_POCKET,
                        wall=access_wall,
                    )
            canvas.routing_ports = frozenset()
            expansions += search_expansions
            round_expansions[i] = round_expansions.get(i, 0) + search_expansions
            if searched.path is None:
                search_failures[i] = searched
                search_blockers[i] = _blocking_nets(
                    searched.wall,
                    source_access_blockers.get(i, ()),
                )
                stranded.append(i)
                continue
            _stake(
                i,
                searched.path,
                hints=_selected_hints(searched.path, route_offers),
            )
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
        round_failures = {
            index: _failure(
                index,
                search_failures[index],
                search_blockers[index],
            )
            for index in stranded
        }
        if _expired(deadline):
            return _budget_result(paths, round_failures)

        # Linking is part of routing feasibility, not terminal emission. Prove
        # every path already found on a disposable workspace even when another
        # net remains stranded: a hidden commit failure is independent new
        # evidence and belongs in the same focused repair transaction.
        def commit_once() -> tuple[tuple[int, ...], dict[int, _CommitFailure]]:
            if not paths:
                return (), {}
            details: dict[int, _CommitFailure] = {}
            unlinked = _commit_paths(
                deepcopy(canvas),
                nets,
                paths,
                belt_id,
                belt_model,
                src_group=src_group,
                dst_group=dst_group,
                source_hints=source_hint,
                sink_hints=sink_hint,
                failure_details=details,
            )
            return unlinked, details

        def retain_commit_failures(
            unlinked: Collection[int],
            details: Mapping[int, _CommitFailure],
            *,
            retained_failures: dict[int, NetFailure] = round_failures,
        ) -> None:
            for index in unlinked:
                detail = details.get(
                    index,
                    _CommitFailure(paths[index][0], "path"),
                )
                if detail.side == "source":
                    rejected_starts[index].add(paths[index][0])
                    if detail.tap is not None:
                        rejected_source_hints[index].add(detail.tap)
                    elif (hint := source_hint.get(index)) is not None:
                        rejected_source_hints[index].add(hint)
                elif detail.side == "sink":
                    rejected_goals[index].add(paths[index][-1])
                    if (hint := sink_hint.get(index)) is not None:
                        rejected_sink_hints[index].add(hint)
                else:
                    rejected_path_cells[index].add(detail.cell)
                history[detail.cell] += _BLAME_WEIGHT
                for blocking_cell in detail.blocking_cells:
                    history[blocking_cell] += _BLAME_WEIGHT
                endpoint_source, endpoint_destination = _endpoint_cells(nets[index])
                blockers = tuple(_net_id(blocker) for blocker in detail.blocking_indices)
                retained_failures[index] = NetFailure(
                    _net_id(index),
                    RouteFailureKind.COMMIT_LINK,
                    (detail.cell, *detail.blocking_cells),
                    blockers,
                    0,
                    source=endpoint_source,
                    destination=endpoint_destination,
                    blocking_endpoints=_blocking_endpoint_cells(blockers),
                )

        unlinked, details = commit_once()
        if not unlinked:
            if failed == 0:
                return _finish(
                    paths,
                    {},
                    source_hint,
                    sink_hint,
                    path_tap,
                    budget_exhausted=False,
                )
        else:
            retain_commit_failures(unlinked, details)

            # A commit collision is exact static/world evidence, not proof that
            # an unrelated settled route must move. Withdraw each rejected path
            # together with its source/destination siblings: their endpoint
            # hints name one another's paths and become stale if only one side
            # moves. Crossing repair is intentionally not used here because it
            # can trade one static miss for a large unrelated victim set.
            pending = tuple(unlinked)
            stalled_commit: list[int] = []
            for _ in range(_COMMIT_REPAIR_PASSES):
                rejected_now = set(pending)
                companions = {
                    sibling
                    for index in pending
                    for sibling in (
                        *src_group.get(index, ()),
                        *dst_group.get(index, ()),
                    )
                    if sibling in paths
                }
                order = [
                    *pending,
                    *sorted(
                        companions - rejected_now,
                        key=lambda index: (
                            -(
                                abs(nets[index].source.x - nets[index].dst.x)
                                + abs(nets[index].source.y - nets[index].dst.y)
                            )
                        ),
                    ),
                ]
                for index in order:
                    _unstake(index)
                stalled_now: list[int] = []
                for index in order:
                    if _expired(deadline) or budget["left"] <= 0:
                        stalled_now.append(index)
                        continue
                    starts, goals, reroute_offers = _ends(index)
                    searched = _astar(
                        canvas,
                        starts,
                        goals,
                        history,
                        pressure,
                        bounds,
                        budget,
                        deadline,
                        blame,
                        grid,
                        owned_starts=owned_source_starts.get(index, ()),
                        forbidden=rejected_path_cells.get(index, ()),
                        blocking_owners=owner,
                    )
                    canvas.routing_ports = frozenset()
                    expansions += searched.expansions
                    round_expansions[index] = round_expansions.get(index, 0) + searched.expansions
                    if searched.path is None:
                        stalled_now.append(index)
                        if index not in rejected_now:
                            blockers = _blocking_nets(
                                searched.wall,
                                source_access_blockers.get(index, ()),
                            )
                            search_failures[index] = searched
                            search_blockers[index] = blockers
                            round_failures[index] = _failure(
                                index,
                                searched,
                                blockers,
                            )
                        continue
                    _stake(
                        index,
                        searched.path,
                        hints=_selected_hints(searched.path, reroute_offers),
                    )

                # A changed branch may select a different legal junction.
                # Validate the complete selected topology and use each new
                # exact failure as the next bounded pass's evidence.
                pending, details = commit_once()
                if pending:
                    retain_commit_failures(pending, details)
                failed_now = set(stalled_now) | set(pending)
                for resolved in rejected_now - failed_now:
                    round_failures.pop(resolved, None)
                stalled_commit.extend(stalled_now)
                if not pending:
                    break

            # The last preflight's rejected paths are still staked. Withdraw
            # them before saving the round incumbent; every retained path has
            # passed the same exact commit predicate.
            for index in pending:
                _unstake(index)
            stranded = list(dict.fromkeys((*stranded, *stalled_commit, *pending)))
            failed = len(stranded)
            if failed == 0:
                return _finish(
                    paths,
                    {},
                    source_hint,
                    sink_hint,
                    path_tap,
                    budget_exhausted=False,
                )
        if failed:
            stranded = _last_mile(stranded, it)
            failed = len(stranded)
            round_failures = {
                index: round_failures[index]
                for index in stranded
                if index in round_failures
            }
            if failed == 0:
                return _finish(
                    paths,
                    {},
                    source_hint,
                    sink_hint,
                    path_tap,
                    budget_exhausted=False,
                )
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
        priority = set(stranded)
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
            best_round = it
            best_failures = dict(round_failures)
            best_source_hints = {
                index: hint for index, hint in source_hint.items() if index in best_paths
            }
            best_sink_hints = {
                index: hint for index, hint in sink_hint.items() if index in best_paths
            }
            best_path_taps = {index: tap for index, tap in path_tap.items() if index in best_paths}
        else:
            stale += 1
        # An exhausted expansion budget ends the search as surely as a stale
        # round does: every further round would re-run every net against a
        # budget of zero and fail all of them, and the counters would read as
        # congestion rather than as work nobody had left to do.
        if _expired(deadline):
            return _budget_result()
        if stale >= _RRR_STALE_ROUNDS or it == RRR_MAX - 1 or budget["left"] <= 0:
            break
    return _finish(
        best_paths,
        best_failures,
        best_source_hints,
        best_sink_hints,
        best_path_taps,
        budget_exhausted=budget["left"] <= 0,
        exhaustive_claim=proved_round >= 0 and proved_round == best_round,
    )


@dataclass(frozen=True, slots=True)
class PortAccessCorridor:
    """Two cells reserved atomically for one port approach."""

    access: Cell
    exit: Cell


@dataclass(frozen=True, slots=True)
class _CorridorRelease:
    """What the relaxed cluster run took away, so it can put it back exactly.

    ``opened`` is only the cells the release actually handed back to
    ``grid.occ``; a reserved cell that was blocked for some OTHER reason was
    left alone and must not be re-blocked, or the restore would tighten the
    round it is meant to reproduce.
    """

    reserved: dict[Cell, Cell]
    corridors: dict[Cell, tuple[PortAccessCorridor, ...]]
    grid_reserved: tuple[tuple[int, Cell], ...]
    opened: tuple[Cell, ...]


def _retire_port_corridor(
    canvas: _Canvas,
    key: Cell,
    endpoint_cells: Collection[Cell],
) -> PortAccessCorridor | None:
    """Release one served role's corridor, preferring the path it used."""
    corridors = canvas.port_corridors.get(key, ())
    if not corridors:
        return None
    endpoint_set = set(endpoint_cells)
    selected = min(
        corridors,
        key=lambda corridor: (
            not bool(endpoint_set & {corridor.access, corridor.exit}),
            corridor.access,
            corridor.exit,
        ),
    )
    canvas.port_corridors[key] = tuple(
        corridor for corridor in corridors if corridor != selected
    )
    for cell in (selected.access, selected.exit):
        if canvas.reserved.get(cell) == key:
            del canvas.reserved[cell]
    return selected


def _restore_port_corridor(
    canvas: _Canvas,
    key: Cell,
    corridor: PortAccessCorridor,
) -> None:
    """Restore a retired corridor before its role's last path is ripped up."""
    canvas.port_corridors[key] = tuple(
        sorted(
            (*canvas.port_corridors.get(key, ()), corridor),
            key=lambda candidate: (candidate.access, candidate.exit),
        )
    )
    canvas.reserved[corridor.access] = key
    canvas.reserved[corridor.exit] = key



def _match_access_corridors(
    order: Sequence[Cell],
    corridors: Mapping[Cell, Sequence[tuple[Cell, Cell]]],
    wants: Mapping[Cell, int],
) -> dict[tuple[Cell, int], PortAccessCorridor]:
    """Assign complete, cell-disjoint access corridors in claim priority order."""

    claims = [
        (key, rank)
        for rank in range(max(wants.values(), default=0))
        for key in order
        if wants[key] > rank
    ]
    model = cp_model.CpModel()
    choices: dict[tuple[Cell, int, Cell, Cell], cp_model.IntVar] = {}
    by_claim: dict[tuple[Cell, int], list[cp_model.IntVar]] = defaultdict(list)
    by_rank: dict[int, list[cp_model.IntVar]] = defaultdict(list)
    by_cell: dict[Cell, list[cp_model.IntVar]] = defaultdict(list)
    for key, rank in claims:
        for access, exit_cell in corridors[key]:
            variable = model.new_bool_var(f"corridor_{key}_{rank}_{access}_{exit_cell}")
            choices[key, rank, access, exit_cell] = variable
            by_claim[key, rank].append(variable)
            by_rank[rank].append(variable)
            by_cell[access].append(variable)
            by_cell[exit_cell].append(variable)

    for claim in claims:
        model.add(sum(by_claim[claim]) <= 1)
    for variables in by_cell.values():
        model.add(sum(variables) <= 1)

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    for rank in range(max(wants.values(), default=0)):
        rank_vars = by_rank[rank]
        if not rank_vars:
            continue
        model.maximize(sum(rank_vars))
        status = solver.solve(model)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return {}
        model.add(sum(rank_vars) == round(solver.objective_value))

    ordered_choices = tuple(choices)
    if not ordered_choices:
        return {}
    ranked_values = {choice: solver.boolean_value(variable) for choice, variable in choices.items()}
    for choice, variable in choices.items():
        model.add_hint(variable, int(ranked_values[choice]))
    model.minimize(
        sum(
            ordinal * choices[choice]
            for ordinal, choice in enumerate(ordered_choices, start=1)
        )
    )
    solver.parameters.max_deterministic_time = _ACCESS_TIE_DETERMINISTIC_WORK
    status = solver.solve(model)
    use_polished = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    assigned: dict[tuple[Cell, int], PortAccessCorridor] = {}
    for choice in ordered_choices:
        selected = solver.boolean_value(choices[choice]) if use_polished else ranked_values[choice]
        if not selected:
            continue
        key, rank, access, exit_cell = choice
        assigned[key, rank] = PortAccessCorridor(access, exit_cell)
    return assigned


def _reserve_port_access(
    canvas: _Canvas,
    nets: list[_Net],
    *,
    twice: Collection[tuple[int, int, int]] = (),
    failed_ports: set[Cell] | None = None,
    demands: dict[Cell, tuple[int, int, int]] | None = None,
) -> int:
    """Hold a complete two-cell corridor next to every port role.

    Returns the number of ports that could not retain any usable access
    corridor. An access cell without its selected onward witness is
    inaccessible, just like a port with no free neighbour.

    ``demands`` collects ``(held, wants, options)`` for every port that came up
    short, so a caller can say WHY without re-deriving the geometry.

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

    ``twice`` names ports that need one MORE approach on top of that: an input
    lane fed from BOTH the boundary and from a producer inside the block.  The
    external run and the internal net are two independent claims on the same lane
    head and they cannot share a cell, so both are staked.

    The lane need not be MIXED, and this docstring used to say it was.  Every
    port that has ever failed this demand carried ONE item (R4 §1.2:
    ``lane=('hydrogen',)``, ten distinct ports across three cells and five
    heights, all ``wants=2 held=1``).  Narrowing the predicate to mixed lanes was
    tried (R4 §6, E1) and the same ports failed again at ROUTE time with
    ``dynamic-access`` and ZERO expansions -- the external run had taken the one
    corridor and laid a belt on it, and the internal net was handed an empty goal
    set.  The demand is real; the answer is to seat such an ingredient on a lane
    head that has two free sides (``strip_variants._seat_both_fed_outermost``).

    Ports are served shortest-lane-first within a round, which is arbitrary and
    deliberately so: what decides whether a port gets an access cell at all is
    the ROUND, not the position in it, and every port has taken its first before
    any port asks for a second.
    """
    canvas.reserved.clear()
    canvas.port_corridors.clear()
    ports: dict[tuple[int, int, int], int] = {}
    roles: dict[tuple[int, int, int], set[str]] = defaultdict(set)
    for net in nets:
        for role, port in (("src", net.src), ("dst", net.dst)):
            if port is None:
                continue
            key = (port.x, port.y, port.z)
            ports[key] = max(ports.get(key, 0), len(port.columns()))
            roles[key].add(role)
            # A port's access is in the port's OWN plane. A coater drop sits one
            # level up, and looking for its free neighbour at level 0 finds the
            # lane belts underneath it and calls the port boxed in.

    order = sorted(ports, key=lambda k: (ports[k], k))
    wants = {k: len(roles[k]) + (1 if k in twice else 0) for k in order}
    held: dict[tuple[int, int, int], int] = defaultdict(int)

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
    # The assignment is joint over `(access, exit)` corridors. An access-only
    # maximum matching can consume another selected access as the first port's
    # sole exit; that is the zero-onward replay retained beside this code.
    # Rank-wise CP-SAT objectives preserve the old first-claim-before-second
    # priority, while a one-worker final solve fixes deterministic tie-breaking.
    options = {
        key: tuple(
            cell
            for cell in ((key[0] + dx, key[1] + dy, key[2]) for dx, dy in _STEPS)
            if canvas.free(cell)
        )
        for key in order
    }
    corridors = {
        key: tuple(
            (access, exit_cell)
            for access in options[key]
            for exit_cell in ((access[0] + dx, access[1] + dy, access[2]) for dx, dy in _STEPS)
            if exit_cell != key and canvas.free(exit_cell)
        )
        for key in order
    }
    assignments = _match_access_corridors(
        order,
        corridors,
        wants,
    )
    assigned_by_port: dict[Cell, list[PortAccessCorridor]] = defaultdict(list)
    for (key, _rank), corridor in assignments.items():
        canvas.reserved[corridor.access] = key
        canvas.reserved[corridor.exit] = key
        assigned_by_port[key].append(corridor)
        held[key] += 1
    canvas.port_corridors = {
        key: tuple(
            sorted(
                assigned,
                key=lambda corridor: (corridor.access, corridor.exit),
            )
        )
        for key, assigned in assigned_by_port.items()
    }
    missing = {key for key in order if held[key] < wants[key]}
    if failed_ports is not None:
        failed_ports.update(missing)
    if demands is not None:
        demands.update(
            (key, (held[key], wants[key], len(options.get(key, ()))))
            for key in missing
        )
    return len(missing)


def _commit_paths(
    canvas: _Canvas,
    nets: list[_Net],
    paths: Mapping[int, Sequence[Cell]],
    belt_id: int,
    belt_model: int,
    src_group: Mapping[int, tuple[int, ...]] | None = None,
    dst_group: Mapping[int, tuple[int, ...]] | None = None,
    *,
    source_hints: Mapping[int, Cell] | None = None,
    sink_hints: Mapping[int, Cell] | None = None,
    failure_details: dict[int, _CommitFailure] | None = None,
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
    path_owner = {cell: index for index, path in paths.items() for cell in path}

    def record(
        index: int,
        cell: Cell,
        side: Literal["source", "sink", "path"],
        blockers: Collection[Cell] = (),
        *,
        tap: Cell | None = None,
        reason: str = "",
    ) -> None:
        if failure_details is None:
            return
        blocking_cells = tuple(sorted(set(blockers)))
        failure_details[index] = _CommitFailure(
            cell=cell,
            side=side,
            blocking_indices=tuple(
                sorted(
                    {
                        owner
                        for blocker in blocking_cells
                        if (owner := path_owner.get(blocker)) is not None and owner != index
                    }
                )
            ),
            tap=tap,
            blocking_cells=blocking_cells,
            reason=reason,
        )

    for i, path in paths.items():
        net = nets[i]
        indices: list[int] = []
        ok = True
        altitudes = _altitude_profile(path, ramped=canvas.ramped)
        if altitudes is None:
            unlinked.append(i)
            record(i, path[0], "path", reason="altitude-profile")
            continue
        failed_cell: Cell | None = None
        failed_reason = ""

        def roll_back_prefix(
            *,
            added_indices: list[int] = indices,
            routed_path: Sequence[Cell] = path,
            routed_altitudes: Sequence[Fraction] = altitudes,
        ) -> None:
            """Remove belts added before this path's first rejected cell."""
            while added_indices:
                at = len(added_indices) - 1
                building_index = added_indices.pop()
                if building_index != len(canvas.buildings) - 1:
                    raise AssertionError("path prefix is no longer the canvas tail")
                canvas.buildings.pop()
                x, y, level = routed_path[at]
                if canvas.blocked.get((x, y, level)) == building_index:
                    del canvas.blocked[x, y, level]
                canvas.world_taken.discard((x, y, routed_altitudes[at]))

        source_tap = (source_hints or {}).get(i)
        for at, ((x, y, lvl), z) in enumerate(zip(path, altitudes, strict=True)):
            owns_guard = (
                at == 0
                and source_tap is not None
                and abs(x - source_tap[0]) + abs(y - source_tap[1]) == 1
                and lvl == (source_tap[2] - 1 if source_tap[2] % 2 else source_tap[2])
                and canvas.free_owned_guard((x, y, lvl))
            )
            lattice_clear = canvas.free((x, y, lvl)) or owns_guard
            world_clear = canvas.free_world(x, y, z)
            if not lattice_clear or not world_clear:
                ok = False
                failed_cell = (x, y, lvl)
                failed_reason = "lattice-occupied" if not lattice_clear else "world-occupied"
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
            roll_back_prefix()
            record(
                i,
                failed_cell or path[0],
                "path",
                reason=failed_reason or "empty-path",
            )
            continue
        for a, b in zip(indices, indices[1:], strict=False):
            canvas.buildings[a] = _relink(canvas.buildings[a], output_obj=b)
        laid[i] = indices

    # WHO FEEDS WHOM, now that every belt exists.  `into` is the reverse of
    # `output_obj`, which the junction site test needs to walk a run UPSTREAM.
    # Initialize it once, then maintain the few links each tap changes; rebuilding
    # it per tap would rescan tens of thousands of buildings hundreds of times.
    into: dict[int, list[int]] = defaultdict(list)
    for idx, built in enumerate(canvas.buildings):
        if built.output_obj is not None:
            into[built.output_obj].append(idx)

    def refresh_predecessor(index: int, previous_output: int | None) -> None:
        current_output = canvas.buildings[index].output_obj
        if previous_output == current_output:
            return
        if previous_output is not None:
            into[previous_output].remove(index)
        if current_output is not None:
            into[current_output].append(index)

    # Fix every sink before certifying any source Splitter. A sink link adds a
    # predecessor to its destination belt. Building a Splitter first made its
    # collider check depend on path iteration order: a later sink could turn an
    # excused one-predecessor feeder into an unstable merge after the check.
    source_branch_heads = frozenset(
        paths[index][0]
        for index in laid
        if (source_hints or {}).get(index) is not None
    )
    for i, indices in laid.items():
        net = nets[i]
        sink_kin = {cell for s in (dst_group or {}).get(i, ()) for cell in paths.get(s, ())}
        sink = _sink_for(
            canvas,
            indices[-1],
            net,
            set(indices),
            sink_kin,
            hint=(sink_hints or {}).get(i),
            protected_targets=source_branch_heads,
        )
        if sink is None:
            unlinked.append(i)
            hint = (sink_hints or {}).get(i)
            record(i, paths[i][-1], "sink", (hint,) if hint is not None else ())
            continue
        previous_sink_output = canvas.buildings[indices[-1]].output_obj
        canvas.buildings[indices[-1]] = _relink(
            canvas.buildings[indices[-1]],
            output_obj=sink,
        )
        refresh_predecessor(indices[-1], previous_sink_output)

    splitter_owner: dict[int, tuple[int, int]] = {}

    for i, indices in laid.items():
        if i in unlinked:
            continue
        net = nets[i]
        kin = {cell for s in (src_group or {}).get(i, ()) for cell in paths.get(s, ())}
        feeder = _source_for(
            canvas,
            indices[0],
            net,
            set(indices),
            kin,
            hint=(source_hints or {}).get(i),
        )
        if feeder is None:
            unlinked.append(i)
            hint = (source_hints or {}).get(i)
            record(i, paths[i][0], "source", (hint,) if hint is not None else ())
            continue
        excused = _run_cells(canvas, into, feeder) | _run_cells(canvas, into, indices[0])
        tap_blockers: set[Cell] = set()
        tap_reason: list[str] = []
        previous_feeder_output = canvas.buildings[feeder].output_obj
        previous_building_count = len(canvas.buildings)
        tap_succeeded = _tap_source(
            canvas,
            feeder,
            indices[0],
            belt_id,
            belt_model,
            excused,
            tap_blockers,
            tap_reason,
            predecessor_choices=into,
        )
        refresh_predecessor(feeder, previous_feeder_output)
        for added_index in range(previous_building_count, len(canvas.buildings)):
            added_output = canvas.buildings[added_index].output_obj
            if added_output is not None:
                into[added_output].append(added_index)
        if not tap_succeeded:
            unlinked.append(i)
            feeder_building = canvas.buildings[feeder]
            feeder_cell = _lattice_cell(
                feeder_building.x,
                feeder_building.y,
                feeder_building.z,
            )
            record(
                i,
                paths[i][0],
                "source",
                tap_blockers,
                tap=feeder_cell,
                reason=tap_reason[0] if tap_reason else "",
            )
            continue
        added_splitters = tuple(
            index
            for index in range(previous_building_count, len(canvas.buildings))
            if canvas.buildings[index].item_id == catalog.SPLITTER_ID
        )
        for splitter_index in added_splitters:
            splitter_owner[splitter_index] = (i, feeder)

    # Validate newly emitted Splitters against the exact preview graph after
    # every sink and source link is final. The local keep-out check runs before
    # later taps can add reverse feeders; DSP reconstructs those merge inputs in
    # preview order, so only universal collision rescue is safe.
    if splitter_owner:
        previews = tuple(
            colliders.Preview(
                building.model_index,
                *codec.tile_to_local_offset(
                    building.x,
                    building.y,
                    building.z,
                    building.width,
                    building.height,
                ),
                building.yaw,
                is_belt=catalog.is_belt(building.item_id),
                is_inserter=catalog.is_sorter(building.item_id),
                is_splitter=building.item_id == catalog.SPLITTER_ID,
                is_belt_addon=catalog.building(building.item_id).is_belt_addon,
                output=building.output_obj,
                input=building.input_obj,
            )
            for building in canvas.buildings
        )
        rejected_taps: set[int] = set()
        for collision in colliders.stable_belt_collisions(previews):
            owned = splitter_owner.get(collision.collider)
            if owned is None:
                continue
            i, feeder = owned
            if i in unlinked or i in rejected_taps:
                continue
            rejected_taps.add(i)
            unlinked.append(i)
            belt = canvas.buildings[collision.belt]
            blocker = _lattice_cell(belt.x, belt.y, belt.z)
            feeder_building = canvas.buildings[feeder]
            record(
                i,
                paths[i][0],
                "source",
                () if blocker is None else (blocker,),
                tap=_lattice_cell(
                    feeder_building.x,
                    feeder_building.y,
                    feeder_building.z,
                ),
                reason="unstable-belt-keepout",
            )
    splitter_successors = _splitter_successors(canvas)
    for i, indices in laid.items():
        if i in unlinked or not _committed_path_closes_cycle(
            canvas,
            indices,
            splitter_successors,
        ):
            continue
        unlinked.append(i)
        record(i, paths[i][-1], "sink", reason="belt-cycle")
    return tuple(unlinked)


def _mixed_height_branch_endpoint(
    tap: Cell,
    branch: PlacedBuilding,
) -> bool:
    """Whether model 40 can join this odd carry tap to its lower branch."""
    return (
        bool(tap[2] % 2)
        and branch.z == tap[2] - 1
        and abs(branch.x - tap[0]) + abs(branch.y - tap[1]) == 1
    )


def _source_for(
    canvas: _Canvas,
    first: int,
    net: _Net,
    own: set[int],
    kin: Set[tuple[int, int, int]],
    *,
    hint: Cell | None = None,
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
    source = net.source
    src = canvas.buildings[source.belt]
    # `head` rests on a level, so it has a lattice cell; a ramp tile would
    # not, and `_lattice_cell` says so rather than rounding it onto one.
    at = _lattice_cell(head.x, head.y, head.z)
    if hint is not None:
        who = canvas.blocked.get(hint)
        if (
            hint in kin
            and who is not None
            and 0 <= who < len(canvas.buildings)
            and who not in own
            and who != net.dst.belt
        ):
            other = canvas.buildings[who]
            if (
                catalog.is_belt(other.item_id)
                and other.carries_item == net.item
                and (
                    _legal_link(
                        other.x,
                        other.y,
                        other.z,
                        head.x,
                        head.y,
                        head.z,
                        ramped=canvas.ramped,
                    )
                    or _mixed_height_branch_endpoint(hint, head)
                )
            ):
                return who
        # A selected frontier hint may be overwritten with the committed
        # branch head when a path is restaked.  Ownership is not authoritative:
        # another co-located attachment may replace ``blocked[hint]`` before
        # source linking.  Recover only the exact head coordinate through the
        # sibling-restricted scan below; every non-self wrong hint still fails
        # closed instead of silently changing sources.
        if hint != at:
            return None
    elif _legal_link(src.x, src.y, src.z, head.x, head.y, head.z, ramped=canvas.ramped):
        return source.belt
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


def _splitter_successors(canvas: _Canvas) -> dict[int, tuple[int, ...]]:
    """Index every belt branch fed by a splitter."""
    successors: dict[int, list[int]] = defaultdict(list)
    for index, building in enumerate(canvas.buildings):
        feed = building.input_obj
        if (
            feed is not None
            and 0 <= feed < len(canvas.buildings)
            and canvas.buildings[feed].item_id == catalog.SPLITTER_ID
        ):
            successors[feed].append(index)
    return {splitter: tuple(branches) for splitter, branches in successors.items()}


def _output_tail_nets(canvas: _Canvas, nets: Sequence[_Net]) -> list[_Net]:
    """Move shared output taps past their internal consumers.

    A producer lane that also feeds an internal recipe has one physical exit.
    Routing an exterior branch from that exit first either seals the internal
    net or forces both branches onto a Splitter beside the machine row. Route
    the internal graph first, then continue from its open downstream tail: every
    upstream source reaches that tail through the committed merges, and one
    exterior belt carries the actual surplus left after the consumers draw.
    """
    successors = _splitter_successors(canvas)
    selected: dict[int, _Net] = {}
    limit = canvas.limit

    def boundary_distance(index: int) -> int:
        if limit is None:
            return 0
        building = canvas.buildings[index]
        min_x, min_y, max_x, max_y = limit
        return min(
            abs(building.x - min_x),
            abs(building.x - max_x),
            abs(building.y - min_y),
            abs(building.y - max_y),
        )

    for net in nets:
        if net.src is None:
            continue
        tails: list[int] = []
        seen: set[int] = set()
        stack = [net.src.belt]
        while stack:
            index = stack.pop()
            if index in seen or not 0 <= index < len(canvas.buildings):
                continue
            seen.add(index)
            building = canvas.buildings[index]
            if building.item_id == catalog.SPLITTER_ID:
                stack.extend(successors.get(index, ()))
                continue
            if not catalog.is_belt(building.item_id) or building.carries_item != net.item:
                continue
            if building.output_obj is None:
                if building.z.denominator == 1:
                    tails.append(index)
                continue
            stack.append(building.output_obj)

        if not tails:
            selected.setdefault(net.src.belt, net)
            continue
        tail_index = min(
            tails,
            key=lambda index: (
                not any(
                    canvas.free(
                        (
                            canvas.buildings[index].x + dx,
                            canvas.buildings[index].y + dy,
                            int(canvas.buildings[index].z),
                        )
                    )
                    for dx, dy in _STEPS
                ),
                boundary_distance(index),
                index,
            ),
        )
        tail = canvas.buildings[tail_index]
        port = _Port(
            tail_index,
            tail.x,
            tail.y,
            tail.x,
            tail.x,
            z=int(tail.z),
            cargo_domain=net.cargo_domain,
        )
        selected.setdefault(tail_index, replace(net, src=port, dst=port))
    return list(selected.values())


def _leads_back(
    canvas: _Canvas,
    start: int,
    own: set[int],
    splitter_successors: Mapping[int, Sequence[int]] | None = None,
) -> bool:
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
    if splitter_successors is None:
        splitter_successors = _splitter_successors(canvas)

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
            stack.extend(splitter_successors.get(i, ()))
        elif catalog.is_belt(b.item_id) and b.output_obj is not None:
            stack.append(b.output_obj)
    return False

def _committed_path_closes_cycle(
    canvas: _Canvas,
    indices: Sequence[int],
    splitter_successors: Mapping[int, Sequence[int]] | None = None,
) -> bool:
    """Whether flow from any committed belt can return to that same belt."""
    if splitter_successors is None:
        splitter_successors = _splitter_successors(canvas)
    return any(
        (onward := canvas.buildings[index].output_obj) is not None
        and _leads_back(canvas, onward, {index}, splitter_successors)
        for index in indices
    )


def _sink_for(
    canvas: _Canvas,
    last: int,
    net: _Net,
    own: set[int],
    kin: Set[tuple[int, int, int]],
    *,
    hint: Cell | None = None,
    protected_targets: Set[Cell] = frozenset(),
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
    ``protected_targets`` names source-Splitter branch heads whose emitted stub
    must remain their only predecessor. Adding a destination merge there would
    make the reverse input depend on last-writer ordering. Ordinary sibling
    merges are unaffected.
    """
    tail = canvas.buildings[last]
    dst = canvas.buildings[net.dst.belt]
    if (
        _legal_link(tail.x, tail.y, tail.z, dst.x, dst.y, dst.z, ramped=canvas.ramped)
        and not _leads_back(canvas, net.dst.belt, own)
    ):
        return net.dst.belt
    if hint is not None:
        if hint in protected_targets:
            return None
        who = canvas.blocked.get(hint)
        if hint in kin and who is not None and 0 <= who < len(canvas.buildings) and who not in own:
            other = canvas.buildings[who]
            if (
                catalog.is_belt(other.item_id)
                and _legal_link(
                    tail.x,
                    tail.y,
                    tail.z,
                    other.x,
                    other.y,
                    other.z,
                    ramped=canvas.ramped,
                )
                and not _leads_back(canvas, who, own)
            ):
                return who
        return None
    # `tail` rests on a level, so it has a lattice cell; a ramp tile would
    # not, and `_lattice_cell` says so rather than rounding it onto one.
    at = _lattice_cell(tail.x, tail.y, tail.z)
    for dx, dy in _STEPS:
        if at is None:
            break
        cell = (at[0] + dx, at[1] + dy, at[2])
        if cell in protected_targets:
            continue
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
            if onward is not None and 0 <= onward < len(canvas.buildings) and onward not in seen:
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


def _belt_keepout_blockers(
    canvas: _Canvas,
    x: int,
    y: int,
    level: int,
    excused: Set[Cell],
) -> tuple[Cell, ...]:
    """Foreign belt cells the game's Splitter probe would hit."""
    blocked: list[Cell] = []
    for cell in junction.keepout_cells(x, y, level):
        if cell in excused:
            continue
        who = canvas.blocked.get(cell)
        if (
            who is not None
            and 0 <= who < len(canvas.buildings)
            and catalog.is_belt(canvas.buildings[who].item_id)
        ):
            blocked.append(cell)
    return tuple(blocked)


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
    return not _belt_keepout_blockers(canvas, x, y, level, excused)


def _tap_source(
    canvas: _Canvas,
    belt_idx: int,
    branch: int,
    belt_id: int,
    belt_model: int,
    excused: Set[tuple[int, int, int]] = frozenset(),
    rejected_cells: set[Cell] | None = None,
    rejected_reason: list[str] | None = None,
    predecessor_choices: Mapping[int, Sequence[int]] | None = None,
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
    if predecessor_choices is None:
        built_predecessors: dict[int, list[int]] = defaultdict(list)
        for index, candidate in enumerate(canvas.buildings):
            if catalog.is_belt(candidate.item_id) and candidate.output_obj is not None:
                built_predecessors[candidate.output_obj].append(index)
        predecessor_choices = built_predecessors
    if onward is None:
        canvas.buildings[belt_idx] = _relink(b, output_obj=branch)
        return True

    if canvas.buildings[onward].item_id == catalog.SPLITTER_ID:
        junction_idx = onward
        splitter = canvas.buildings[junction_idx]
        branch_attachment = b
        if splitter.model_index == 40:
            if (
                b.z != splitter.z + 1
                or canvas.buildings[branch].z != splitter.z
                or _cardinal_direction(b, canvas.buildings[branch]) is None
            ):
                if rejected_reason is not None:
                    rejected_reason.append("splitter-port")
                return False
            branch_attachment = replace(b, z=splitter.z)

        used_ports: set[int] = set()
        attached = 0
        for index, candidate in enumerate(canvas.buildings):
            outward_idx: int | None
            if candidate.output_obj == junction_idx:
                attached += 1
                incoming = predecessor_choices.get(index, ())
                outward_idx = incoming[0] if len(incoming) == 1 else None
            elif candidate.input_obj == junction_idx:
                attached += 1
                outward_idx = candidate.output_obj
            else:
                continue
            port = (
                splitter_ports.expected_path_port(
                    splitter,
                    candidate,
                    canvas.buildings[outward_idx],
                )
                if outward_idx is not None
                else None
            )
            if port is None or port in used_ports:
                if rejected_reason is not None:
                    rejected_reason.append("splitter-port")
                return False
            used_ports.add(port)
    else:
        # A junction rests on a real routing level.  A ramp midpoint cannot host
        # one, and every real stack member is checked against the exact prepared
        # collider cache plus all dynamic belts.
        if b.z.denominator != 1:
            if rejected_reason is not None:
                rejected_reason.append("ramp")
            return False
        level = int(b.z)
        incoming = [
            index
            for index, candidate in enumerate(canvas.buildings)
            if catalog.is_belt(candidate.item_id) and candidate.output_obj == belt_idx
        ]
        if len(incoming) != 1:
            if rejected_reason is not None:
                rejected_reason.append("splitter-port")
            return False
        carry_direction: tuple[int, int] | None = None
        if level % 2:
            feed_direction = _cardinal_direction(
                b,
                canvas.buildings[incoming[0]],
            )
            carry_direction = _cardinal_direction(
                b,
                canvas.buildings[onward],
            )
            branch_direction = _cardinal_direction(
                b,
                canvas.buildings[branch],
            )
            if (
                feed_direction is None
                or carry_direction is None
                or feed_direction != (-carry_direction[0], -carry_direction[1])
                or branch_direction is None
                or branch_direction[0] * carry_direction[0]
                + branch_direction[1] * carry_direction[1]
                != 0
                or canvas.buildings[branch].z != level - 1
            ):
                if rejected_reason is not None:
                    rejected_reason.append("splitter-port")
                return False
        try:
            splitter_stack = junction.make_splitter_stack(
                b.x,
                b.y,
                level,
                first_index=len(canvas.buildings),
                carries_item=b.carries_item,
                carry_direction=carry_direction,
            )
        except ValueError:
            if rejected_reason is not None:
                rejected_reason.append("splitter-stack")
            return False
        if not canvas.junction_is_clear(b.x, b.y, level):
            if rejected_reason is not None:
                rejected_reason.append("junction-collider")
            return False

        splitter = splitter_stack[-1]
        branch_attachment = replace(b, z=splitter.z) if level % 2 else b
        feed_port = splitter_ports.expected_path_port(
            splitter,
            b,
            canvas.buildings[incoming[0]],
        )
        carry_port = splitter_ports.expected_path_port(
            splitter,
            b,
            canvas.buildings[onward],
        )
        branch_port = splitter_ports.expected_path_port(
            splitter,
            branch_attachment,
            canvas.buildings[branch],
        )
        if (
            feed_port is None
            or carry_port is None
            or branch_port is None
            or len({feed_port, carry_port, branch_port}) != 3
        ):
            if rejected_reason is not None:
                rejected_reason.append("splitter-port")
            return False

        def reaches_tap_downstream(index: int) -> bool:
            """Will this belt reach the new Splitter within DSP's three-hop walk?"""
            current = index
            for _hop in range(3):
                if current == belt_idx:
                    return True
                if not (0 <= current < len(canvas.buildings)):
                    return False
                candidate = canvas.buildings[current]
                if not catalog.is_belt(candidate.item_id) or candidate.output_obj is None:
                    return False
                current = candidate.output_obj
            return False

        # Only the top member owns this run.  Every lower support has no belt
        # attachments, so every belt in its exact model/yaw keepout is foreign.
        belt_blockers: set[Cell] = set()
        for offset, stack_member in enumerate(splitter_stack):
            top = offset == len(splitter_stack) - 1
            for cell in junction.keepout_cells(
                b.x,
                b.y,
                int(stack_member.z),
                model_index=stack_member.model_index,
                yaw=stack_member.yaw,
            ):
                who = canvas.blocked.get(cell)
                if (
                    top
                    and cell in excused
                    and (
                        who is None
                        or reaches_tap_downstream(who)
                        or len(predecessor_choices.get(who, ())) <= 1
                    )
                ):
                    continue
                who = canvas.blocked.get(cell)
                if (
                    who is not None
                    and 0 <= who < len(canvas.buildings)
                    and catalog.is_belt(canvas.buildings[who].item_id)
                ):
                    belt_blockers.add(cell)
        if belt_blockers:
            if rejected_cells is not None:
                rejected_cells.update(belt_blockers)
            if rejected_reason is not None:
                rejected_reason.append("belt-keepout")
            return False

        used_ports = {feed_port, carry_port}
        attached = 2
        junction_idx = -1
        for stack_member in splitter_stack:
            junction_idx = canvas.add(stack_member)
            canvas.guard.update(
                junction.keepout_cells(
                    b.x,
                    b.y,
                    int(stack_member.z),
                    model_index=stack_member.model_index,
                    yaw=stack_member.yaw,
                )
            )
        assert junction_idx >= 0
        canvas.buildings[belt_idx] = _relink(b, output_obj=junction_idx)
        # Carry the lane onward on the elevated model-40 pair (or the flat
        # model-38 plane), preserving every other belt field.
        carry = canvas.add(replace(b, input_obj=junction_idx, output_obj=onward))
        del carry

    if attached >= rules.SPLITTER_MAX_PORTS:
        if rejected_reason is not None:
            rejected_reason.append("splitter-ports")
        return False

    branch_port = splitter_ports.expected_path_port(
        splitter,
        branch_attachment,
        canvas.buildings[branch],
    )
    if branch_port is None or branch_port in used_ports:
        if rejected_reason is not None:
            rejected_reason.append("splitter-port")
        return False

    # The branch belt is ADJACENT to the junction, not on it, and every belt
    # attached to a splitter must be CO-LOCATED with it -- that is what the
    # corpus shows and what `junction.colocated` enforces. So the junction gets
    # a stub on its own tile which then runs out to the branch. This is exactly
    # the shape the game records: a splitter's port is a belt on the junction
    # tile, and the route starts from there.
    stub = canvas.add(
        replace(
            branch_attachment,
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
    clear = [cells for cells in options if cells and all(canvas.free(c) for c in cells)]
    if not clear:
        return None
    return min(clear, key=len)


def _route_boundary_nets(
    canvas: _Canvas,
    nets: Sequence[_Net],
    belt_id: int,
    belt_model: int,
    core: tuple[int, int, int, int],
    deadline: float | None = None,
    budget: dict[str, int] | None = None,
    *,
    outward: bool,
) -> DetailedRouteResult:
    """Run external input or output lanes between their ports and the block edge.

    Without explicit boundary routing, an external lane is just a lane wearing
    a marker icon. On a packed build that lane is frequently walled in, so the
    operator cannot connect it even though the blueprint claims it is usable.

    Input belts flow inward from the edge to their lane. Output belts flow
    outward from their lane to the edge. Both terminate on the ENTRY RING, the
    outermost ring anything may occupy, so their open ends remain on the
    finished bounding box after every later routing pass.
    """
    bounds = _grow(core, _ENTRY_RING - 1)
    # The fallback search may travel ALONG the entry ring, which the straight
    # runs already use; a cell on the outermost ring cannot wall anything in,
    # because outward of it is ground no pass can reach.
    astar_bounds = _grow(core, _ENTRY_RING)
    def port_of(net: _Net) -> _Port:
        return net.source if outward else net.dst

    wanted = {port_of(net).belt: net for net in nets}
    ordered = list(wanted.items())
    boundary = list(
        dict.fromkeys(cell for net in nets for cell in net.boundary_goals if canvas.free(cell))
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
        port = port_of(net)
        endpoint = (port.x, port.y, port.z)
        return NetFailure(
            net_id(net),
            search.kind or RouteFailureKind.DYNAMIC_ACCESS,
            search.wall,
            (),
            search.expansions,
            source=endpoint if outward else None,
            destination=None if outward else endpoint,
        )

    if not boundary:
        failures.extend(
            NetFailure(
                net_id(net),
                RouteFailureKind.DYNAMIC_ACCESS,
                (),
                (),
                0,
                source=(
                    (port_of(net).x, port_of(net).y, port_of(net).z) if outward else None
                ),
                destination=(
                    None
                    if outward
                    else (port_of(net).x, port_of(net).y, port_of(net).z)
                ),
            )
            for _belt, net in ordered
        )
    else:
        for done, (_belt, net) in enumerate(ordered):
            if _expired(deadline):
                failures.extend(
                    NetFailure(net_id(pending), RouteFailureKind.BUDGET, (), (), 0)
                    for _pending_belt, pending in ordered[done:]
                )
                break
            port = port_of(net)
            item = net.item
            # Spend exactly one complete access corridor. Reserving only its
            # first cell was sufficient before reservations gained a two-cell
            # onward witness; releasing just one cell now leaves that witness
            # blocking the straight path and seals the port behind its own
            # claim. Leave any other corridor held for the opposite role.
            port_key = (port.x, port.y, port.z)
            retired = _retire_port_corridor(canvas, port_key, ())
            if retired is None:
                mine = next(
                    (cell for cell, key in canvas.reserved.items() if key == port_key),
                    None,
                )
                if mine is not None:
                    del canvas.reserved[mine]

            # The straight fast path is ground-only. Elevated ports must use
            # the shared z-aware search so the level transition is explicit.
            path: Sequence[Cell] | None = (
                _straight_to_edge(canvas, port, bounds) if port.z == 0 else None
            )
            if path is not None and outward:
                path = tuple(reversed(path))
            if path is None:
                access = {
                    (port.x + dx, port.y + dy, port.z)
                    for dx, dy in _STEPS
                    if canvas.free((port.x + dx, port.y + dy, port.z))
                }
                live_boundary = [cell for cell in boundary if canvas.free(cell)]
                if not access or not live_boundary:
                    failures.append(
                        NetFailure(
                            net_id(net),
                            RouteFailureKind.DYNAMIC_ACCESS,
                            (),
                            (),
                            0,
                            source=(port.x, port.y, port.z) if outward else None,
                            destination=(
                                None if outward else (port.x, port.y, port.z)
                            ),
                        )
                    )
                    continue
                starts = sorted(access) if outward else live_boundary
                goals = set(live_boundary) if outward else access
                searched = _astar(
                    canvas,
                    starts,
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
                        net_id(net),
                        RouteFailureKind.COMMIT_LINK,
                        (),
                        (),
                        0,
                        source=(port.x, port.y, port.z) if outward else None,
                        destination=None if outward else (port.x, port.y, port.z),
                    )
                )
                continue
            route_cells = tuple(zip(path, profile, strict=True))
            if any(
                not canvas.free((x, y, level)) or not canvas.free_world(x, y, altitude)
                for (x, y, level), altitude in route_cells
            ):
                failures.append(
                    NetFailure(
                        net_id(net),
                        RouteFailureKind.COMMIT_LINK,
                        (),
                        (),
                        0,
                        source=(port.x, port.y, port.z) if outward else None,
                        destination=None if outward else (port.x, port.y, port.z),
                    )
                )
                continue
            if outward and canvas.buildings[port.belt].output_obj is not None:
                failures.append(
                    NetFailure(
                        net_id(net),
                        RouteFailureKind.COMMIT_LINK,
                        (),
                        (),
                        0,
                        source=(port.x, port.y, port.z),
                    )
                )
                continue

            indices = [
                canvas.add(
                    PlacedBuilding(
                        item_id=belt_id,
                        model_index=belt_model,
                        x=x,
                        y=y,
                        z=altitude,
                        width=1,
                        height=1,
                        carries_item=item,
                    ),
                    level=level,
                )
                for (x, y, level), altitude in route_cells
            ]
            for a, b in zip(indices, indices[1:], strict=False):
                canvas.buildings[a] = _relink(canvas.buildings[a], output_obj=b)
            if outward:
                canvas.buildings[port.belt] = _relink(
                    canvas.buildings[port.belt], output_obj=indices[0]
                )
            else:
                canvas.buildings[indices[-1]] = _relink(
                    canvas.buildings[indices[-1]], output_obj=port.belt
                )
            routed.append(net_id(net))

    status = (
        DetailedRouteStatus.BUDGET
        if any(failure.kind is RouteFailureKind.BUDGET for failure in failures)
        else (DetailedRouteStatus.STRANDED if failures else DetailedRouteStatus.ROUTED)
    )
    return DetailedRouteResult(
        status=status,
        routed=tuple(routed),
        failures=tuple(failures),
        iterations=0,
        expansions=expansions,
        # A result with no failure has nothing left unproved.  This is the same
        # vacuous claim `_build_prepared` already makes for `empty_routing`, and
        # `_build_prepared` conjoins all four sub-routings, so without it an
        # internal proof could never reach `_proof_scoped_no_goods`.
        exhaustive=not failures,
    )


def _route_external_inputs(
    canvas: _Canvas,
    nets: Sequence[_Net],
    belt_id: int,
    belt_model: int,
    core: tuple[int, int, int, int],
    deadline: float | None = None,
    budget: dict[str, int] | None = None,
) -> DetailedRouteResult:
    return _route_boundary_nets(
        canvas,
        nets,
        belt_id,
        belt_model,
        core,
        deadline,
        budget,
        outward=False,
    )


def _route_external_outputs(
    canvas: _Canvas,
    nets: Sequence[_Net],
    belt_id: int,
    belt_model: int,
    core: tuple[int, int, int, int],
    deadline: float | None = None,
    budget: dict[str, int] | None = None,
) -> DetailedRouteResult:
    return _route_boundary_nets(
        canvas,
        nets,
        belt_id,
        belt_model,
        core,
        deadline,
        budget,
        outward=True,
    )


class _PreparationDeadline(Exception):
    """Exact candidate preparation stopped before producing a reusable result."""


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

    def __init__(
        self,
        message: str,
        *,
        failure: finalize.ProjectionFailure | None = None,
        clearance_requirement: StagedStaticClearanceRequirement | None = None,
        exact_retry_evidence: _ExactRetryEvidence | None = None,
    ) -> None:
        self.failure = failure
        self.failures = () if failure is None else (failure,)
        self.clearance_requirement = clearance_requirement
        self.exact_retry_evidence = exact_retry_evidence
        if failure is not None:
            message = (
                f"{message}: band {failure.band} {failure.check} "
                f"{failure.buildings}: {failure.detail}"
            )
        super().__init__(message)


class _Unpowerable(Exception):
    """This pack cannot be powered, so it is not a feasible pack.

    Raised by :func:`_power_plan` before anything routes, and by
    :func:`_place_power` if a held site was taken anyway.  Projected refusals
    retain their structured finalizer evidence so a caller can report the
    authoritative band, check, and detail instead of calling every failure
    ``power.coverage``.
    """

    def __init__(
        self,
        message: str,
        *,
        failure: finalize.ProjectionFailure | None = None,
        exact_retry_evidence: _ExactRetryEvidence | None = None,
    ) -> None:
        self.failure = failure
        self.failures = () if failure is None else (failure,)
        self.exact_retry_evidence = exact_retry_evidence
        if failure is not None:
            message = (
                f"{message}: band {failure.band} {failure.check} "
                f"{failure.buildings}: {failure.detail}"
            )
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class _JunctionProjectionFrame:
    """One reachable frame materialization and its finalizer projections."""

    bounds: tuple[int, int, int, int]
    candidate: finalize.FrameCandidate
    projections: tuple[planet.Projection, ...]


type _FrameWitnessRank = tuple[int, int, int, int, int]


@dataclass(frozen=True, slots=True)
class _ReachableFrameInterval:
    """One extent/candidate over its contiguous physical latitude offsets."""

    rotated: bool
    offset_lo: int
    offset_hi: int
    width: int
    height: int
    min_x_lo: int
    min_y_lo: int
    candidate_index: int
    candidate: finalize.FrameCandidate

    def ordering_key(self) -> _FrameWitnessRank:
        """Legacy four-edge rank with the common offset term removed."""
        padding = self.candidate.south_padding
        if self.rotated:
            return (
                padding,
                self.min_y_lo,
                padding + self.width - 1,
                self.min_y_lo + self.height - 1,
                self.candidate_index,
            )
        return (
            self.min_x_lo,
            padding,
            self.min_x_lo + self.width - 1,
            padding + self.height - 1,
            self.candidate_index,
        )

    def witness(
        self,
        offset: int,
    ) -> tuple[tuple[int, int, int, int], _FrameWitnessRank]:
        min_x = self.candidate.south_padding - offset if self.rotated else self.min_x_lo
        min_y = self.min_y_lo if self.rotated else self.candidate.south_padding - offset
        bounds = (
            min_x,
            min_y,
            min_x + self.width - 1,
            min_y + self.height - 1,
        )
        return bounds, (*bounds, self.candidate_index)


@lru_cache
def _collider_broad_phase_bounds(
    model_index: int,
    yaw: float,
) -> tuple[float, float, float]:
    """Grid-axis and vertical radii containing every collider of one pose."""
    angle = math.radians(yaw)
    cosine = math.cos(angle)
    sine = math.sin(angle)
    radius_x = 0.0
    radius_y = 0.0
    vertical = 0.0
    for position, extent, _rotation in colliders.build_colliders(model_index):
        centre_x = cosine * position[0] + sine * position[2]
        centre_y = -sine * position[0] + cosine * position[2]
        extent_x = abs(cosine) * extent[0] + abs(sine) * extent[2]
        extent_y = abs(sine) * extent[0] + abs(cosine) * extent[2]
        radius_x = max(radius_x, abs(centre_x) + extent_x)
        radius_y = max(radius_y, abs(centre_y) + extent_y)
        vertical = max(vertical, abs(position[1]) + extent[1])
    return radius_x, radius_y, vertical


@lru_cache
def _minimum_projection_grid_scale(
    bands: tuple[planet.Band, ...],
) -> float:
    """Conservative world-unit scale for either grid axis in these bands."""
    latitude_step = planet.latitude_rad_per_grid(colliders.PLANET_SEGMENT)
    return min(
        min(
            colliders.PLANET_RADIUS
            * min(
                math.cos(
                    min(
                        abs(grid),
                        planet.pole_grid_idx(colliders.PLANET_SEGMENT),
                    )
                    * latitude_step
                )
                for grid in (band.grid_lo, band.grid_hi)
            )
            * planet.longitude_rad_per_grid(band.area_segments)
            * 0.9,
            colliders.PLANET_RADIUS * latitude_step * 0.9,
        )
        for band in bands
    )


def _projected_power_peer_possible(
    candidate: tuple[int, PlacedBuilding, rules.PowerNode],
    peer: tuple[int, PlacedBuilding, rules.PowerNode],
    projection_contexts: Sequence[tuple[int, bool, float]],
    *,
    cancelled: Callable[[], bool] | None = None,
) -> bool:
    """Whether curvature could bring this node pair inside either paste gate."""
    if cancelled is not None and cancelled():
        raise _PreparationDeadline
    _candidate_index, candidate_building, candidate_node = candidate
    _peer_index, peer_building, peer_node = peer
    candidate_centre = codec.tile_to_local_offset(
        candidate_building.x,
        candidate_building.y,
        candidate_building.z,
        candidate_building.width,
        candidate_building.height,
    )
    peer_centre = codec.tile_to_local_offset(
        peer_building.x,
        peer_building.y,
        peer_building.z,
        peer_building.width,
        peer_building.height,
    )
    delta_x = abs(candidate_centre[0] - peer_centre[0])
    delta_y = abs(candidate_centre[1] - peer_centre[1])
    vertical = (candidate_centre[2] - peer_centre[2]) * 4.0 / 3.0
    lo, hi = rules.PASTE_POWER_NODE_IDS
    gates = []
    if lo <= candidate_building.item_id < hi:
        gates.append(peer_node.gate_sqr)
    if lo <= peer_building.item_id < hi:
        gates.append(candidate_node.gate_sqr)
    if cancelled is not None and cancelled():
        raise _PreparationDeadline
    if not gates:
        return False
    gate_distance2 = max(gates)
    for columns, rotated, scale in projection_contexts:
        longitude_delta, latitude_delta = (delta_y, delta_x) if rotated else (delta_x, delta_y)
        longitude_delta %= columns
        longitude_delta = min(longitude_delta, columns - longitude_delta)
        lower_distance2 = (
            (longitude_delta * scale) ** 2 + (latitude_delta * scale) ** 2 + vertical * vertical
        )
        if lower_distance2 < gate_distance2:
            if cancelled is not None and cancelled():
                raise _PreparationDeadline
            return True
    if cancelled is not None and cancelled():
        raise _PreparationDeadline
    return False


@dataclass(slots=True)
class _ProjectedObstacleIndex:
    """Candidate-independent collider bounds for conservative exact gating."""

    xs: list[float] = field(default_factory=list)
    obstacles: list[tuple[int, PlacedBuilding, float, float, float]] = field(default_factory=list)
    max_horizontal_radius: float = 0.0

    @classmethod
    def build(
        cls,
        buildings: Sequence[tuple[int, PlacedBuilding]],
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> _ProjectedObstacleIndex:
        index = cls()
        for building_index, building in buildings:
            if cancelled is not None and cancelled():
                raise _PreparationDeadline
            index.add(building_index, building)
        return index

    def add(self, building_index: int, building: PlacedBuilding) -> None:
        if catalog.is_belt(building.item_id) or catalog.is_sorter(building.item_id):
            return
        radius_x, radius_y, vertical_radius = _collider_broad_phase_bounds(
            building.model_index,
            building.yaw,
        )
        if radius_x <= 0.0 or radius_y <= 0.0 or vertical_radius <= 0.0:
            return
        centre_x = codec.tile_to_local_offset(
            building.x,
            building.y,
            building.z,
            building.width,
            building.height,
        )[0]
        position = bisect_right(self.xs, centre_x)
        self.xs.insert(position, centre_x)
        self.obstacles.insert(
            position,
            (
                building_index,
                building,
                radius_x,
                radius_y,
                vertical_radius,
            ),
        )
        self.max_horizontal_radius = max(
            self.max_horizontal_radius,
            radius_x,
            radius_y,
        )

    def candidates(
        self,
        candidate: PlacedBuilding,
        frames: Sequence[_JunctionProjectionFrame],
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> tuple[int, ...]:
        """Over-include every peer the exact projected broad phase can retain."""
        bands = tuple(
            sorted(
                {projection.band for frame in frames for projection in frame.projections},
                key=lambda band: band.area_segments,
            )
        )
        return self.candidates_for_bands(
            candidate,
            bands,
            cancelled=cancelled,
        )

    def candidates_for_bands(
        self,
        candidate: PlacedBuilding,
        bands: tuple[planet.Band, ...],
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> tuple[int, ...]:
        """Over-include peers using only the finalizer-reachable band union."""
        if cancelled is not None and cancelled():
            raise _PreparationDeadline
        candidate_x, candidate_y, candidate_vertical = _collider_broad_phase_bounds(
            candidate.model_index,
            candidate.yaw,
        )
        candidate_centre = codec.tile_to_local_offset(
            candidate.x,
            candidate.y,
            candidate.z,
            candidate.width,
            candidate.height,
        )
        if candidate_x <= 0.0 or not self.obstacles or not bands:
            return ()
        scale = _minimum_projection_grid_scale(bands)
        if scale <= 1e-9:
            lo = 0
            hi = len(self.obstacles)
        else:
            reach = (max(candidate_x, candidate_y) + self.max_horizontal_radius) / scale
            lo = bisect_left(self.xs, candidate_centre[0] - reach)
            hi = bisect_right(self.xs, candidate_centre[0] + reach)
        candidates: list[int] = []
        for index, peer, peer_x, peer_y, peer_vertical in self.obstacles[lo:hi]:
            if cancelled is not None and cancelled():
                raise _PreparationDeadline
            peer_centre = codec.tile_to_local_offset(
                peer.x,
                peer.y,
                peer.z,
                peer.width,
                peer.height,
            )
            delta_x = abs(candidate_centre[0] - peer_centre[0]) * scale
            delta_y = abs(candidate_centre[1] - peer_centre[1]) * scale
            normal = delta_x <= candidate_x + peer_x and delta_y <= candidate_y + peer_y
            rotated = delta_x <= candidate_y + peer_y and delta_y <= candidate_x + peer_x
            vertical_gap = abs(candidate_centre[2] - peer_centre[2]) * 4.0 / 3.0
            if (normal or rotated) and vertical_gap <= candidate_vertical + peer_vertical:
                candidates.append(index)
        return tuple(sorted(candidates))


@dataclass(slots=True)
class _StagedStaticCache:
    """Spec-scoped memoization of pure finalizer projection inputs.

    Handed out by ``geometry_memo.for_spec`` and shared across every
    candidate and strategy for the same spec, so every entry must be a pure
    function of its key alone -- never of attempt state (search order,
    budget remaining, which candidate is running).
    """

    frames: dict[
        tuple[
            tuple[int, int, int, int],
            tuple[int, int, int, int],
            BandPolicy,
        ],
        tuple[_JunctionProjectionFrame, ...],
    ] = field(default_factory=dict)
    cleanup_bounds: dict[
        tuple[PlacedBuilding, ...],
        tuple[int, int, int, int],
    ] = field(default_factory=dict)
    materialized: dict[
        tuple[
            PlacedBuilding,
            tuple[int, int, int, int],
            finalize.FrameCandidate,
        ],
        PlacedBuilding,
    ] = field(default_factory=dict)
    materialized_bases: dict[
        tuple[
            tuple[tuple[int, PlacedBuilding], ...],
            tuple[int, int, int, int],
            finalize.FrameCandidate,
        ],
        tuple[tuple[int, PlacedBuilding], ...],
    ] = field(default_factory=dict)
    clean_contexts: set[tuple[object, ...]] = field(default_factory=set)
    coater_supply_failures: dict[
        tuple[object, ...],
        finalize.ProjectionFailure | None,
    ] = field(default_factory=dict)
    boxes: dict[
        tuple[colliders.Placed, planet.Projection],
        tuple[colliders.Box, ...],
    ] = field(default_factory=dict)
    placed: dict[PlacedBuilding, colliders.Placed] = field(default_factory=dict)
    junction_offsets: dict[
        tuple[int, int, int, int, float, Fraction],
        frozenset[Cell],
    ] = field(default_factory=dict)
    cleanup_operations: finalize._CleanupOperations = field(
        default_factory=finalize._CleanupOperations
    )
    broad_phase_queries: int = 0
    broad_phase_hits: int = 0
    exact_static_queries: int = 0

    def stats(self) -> MemoStats:
        from flab2bp.layout.geometry_memo import MemoStats as _MemoStats

        return _MemoStats(
            tables={
                "frames": len(self.frames),
                "cleanup_bounds": len(self.cleanup_bounds),
                "materialized": len(self.materialized),
                "materialized_bases": len(self.materialized_bases),
                "clean_contexts": len(self.clean_contexts),
                "coater_supply_failures": len(self.coater_supply_failures),
                "boxes": len(self.boxes),
                "placed": len(self.placed),
                "junction_offsets": len(self.junction_offsets),
            },
            broad_phase_queries=self.broad_phase_queries,
            broad_phase_hits=self.broad_phase_hits,
            exact_static_queries=self.exact_static_queries,
        )


def _prospective_static_broad_phase(
    index: _ProjectedObstacleIndex,
    candidate: PlacedBuilding,
    frames: Sequence[_JunctionProjectionFrame],
    cache: _StagedStaticCache,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[int, ...]:
    cache.broad_phase_queries += 1
    candidates = index.candidates(candidate, frames, cancelled=cancelled)
    if candidates:
        cache.broad_phase_hits += 1
    return candidates


def _prospective_static_broad_phase_for_bands(
    index: _ProjectedObstacleIndex,
    candidate: PlacedBuilding,
    bands: tuple[planet.Band, ...],
    cache: _StagedStaticCache,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[int, ...]:
    """Broad-phase a candidate before constructing its exact frame witnesses."""
    cache.broad_phase_queries += 1
    candidates = index.candidates_for_bands(
        candidate,
        bands,
        cancelled=cancelled,
    )
    if candidates:
        cache.broad_phase_hits += 1
    return candidates


def _cached_cleanup_survivor_bounds(
    cache: _StagedStaticCache,
    buildings: tuple[PlacedBuilding, ...],
    *,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[int, int, int, int]:
    """Cache only a complete candidate geometry, never a bounds-only proxy."""
    if cancelled is not None and cancelled():
        raise _PreparationDeadline
    bounds = cache.cleanup_bounds.get(buildings)
    if bounds is None:
        bounds = (
            finalize._cleanup_survivor_bounds(
                Placement(buildings=buildings),
            )
            if cancelled is None
            else finalize._cleanup_survivor_bounds(
                Placement(buildings=buildings),
                cancelled=cancelled,
            )
        )
        if cancelled is not None and cancelled():
            raise _PreparationDeadline
        cache.cleanup_bounds[buildings] = bounds
    return bounds


def _cleanup_snapshot_with_linkless_static(
    prefix: finalize._CleanupSurvivorGraph,
    bounds: tuple[int, int, int, int],
    candidate: PlacedBuilding,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[finalize._CleanupSurvivorGraph, tuple[int, int, int, int]]:
    """Reuse certified bounds only while a linkless static stays inside them."""
    if (
        bounds[0] <= candidate.x
        and bounds[1] <= candidate.y
        and candidate.x + candidate.width - 1 <= bounds[2]
        and candidate.y + candidate.height - 1 <= bounds[3]
    ):
        return prefix, bounds
    return prefix.extended_snapshot(
        (candidate,),
        bounds,
        cancelled=cancelled,
    )


def _cached_junction_projection_frames(
    cache: _StagedStaticCache,
    occupied: tuple[int, int, int, int],
    limit: tuple[int, int, int, int],
    policy: BandPolicy,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[_JunctionProjectionFrame, ...]:
    """Return exact reachable frames once per spec-scoped geometry signature."""
    if cancelled is not None and cancelled():
        raise _PreparationDeadline
    key = (occupied, limit, policy)
    frames = cache.frames.get(key)
    if frames is None:
        frames = _junction_projection_frames(
            occupied,
            limit,
            policy,
            cancelled=cancelled,
        )
        if cancelled is not None and cancelled():
            raise _PreparationDeadline
        cache.frames[key] = frames
    return frames


def _junction_projection_frames(
    occupied: tuple[int, int, int, int],
    limit: tuple[int, int, int, int],
    policy: BandPolicy,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[_JunctionProjectionFrame, ...]:
    """Distinct physical frames in exact legacy first-encounter order.

    A finalizer transform depends on orientation and latitude offset only:
    longitude translation is a rigid rotation of the planet.  For each
    orientation and latitude extent, primary-band thresholds partition the
    longitude extents into a handful of equivalent ranges.  Only the legacy
    first witness in each range can contribute a frame or projection, avoiding
    the Cartesian width/height grid while preserving exact ordering.
    """
    if cancelled is not None and cancelled():
        raise _PreparationDeadline
    occupied_min_x, occupied_min_y, occupied_max_x, occupied_max_y = occupied
    limit_min_x, limit_min_y, limit_max_x, limit_max_y = limit
    if not (
        limit_min_x <= occupied_min_x <= occupied_max_x <= limit_max_x
        and limit_min_y <= occupied_min_y <= occupied_max_y <= limit_max_y
    ):
        raise ValueError("occupied junction bounds must lie inside canvas.limit")

    occupied_width = occupied_max_x - occupied_min_x + 1
    occupied_height = occupied_max_y - occupied_min_y + 1
    limit_width = limit_max_x - limit_min_x + 1
    limit_height = limit_max_y - limit_min_y + 1
    by_segments = {band.area_segments: band for band in planet.bands()}
    ordered_bands = tuple(sorted(by_segments.values(), key=lambda band: band.area_segments))

    def primary_cross_ranges(
        rows: int,
        cross_min: int,
        cross_max: int,
    ) -> Iterator[tuple[planet.Band, int, int]]:
        """Primary band and inclusive cross-extent ranges for fixed rows."""
        explicit = policy.explicit_segments
        if explicit is not None:
            yield by_segments[explicit], cross_min, cross_max
            return

        previous_fit_hi = 0
        for band in ordered_bands:
            if cancelled is not None and cancelled():
                raise _PreparationDeadline
            fit_hi = 0
            if rows <= band.rows:
                fit_hi = band.columns
            if rows <= band.columns:
                fit_hi = max(fit_hi, band.rows)
            range_lo = max(cross_min, previous_fit_hi + 1)
            range_hi = min(cross_max, fit_hi)
            previous_fit_hi = max(previous_fit_hi, fit_hi)
            if range_lo <= range_hi:
                yield band, range_lo, range_hi

    intervals: list[_ReachableFrameInterval] = []
    projection_intervals: dict[
        tuple[bool, int, int, int, tuple[int, ...]],
        _ReachableFrameInterval,
    ] = {}

    for rotated in (False, True):
        if rotated:
            row_min, row_max = occupied_width, limit_width
            cross_min, cross_max = occupied_height, limit_height
            occupied_cross_max = occupied_max_y
            limit_cross_min = limit_min_y
        else:
            row_min, row_max = occupied_height, limit_height
            cross_min, cross_max = occupied_width, limit_width
            occupied_cross_max = occupied_max_x
            limit_cross_min = limit_min_x
        leftmost_cross_extent = occupied_cross_max - limit_cross_min + 1

        for rows in range(row_min, row_max + 1):
            if cancelled is not None and cancelled():
                raise _PreparationDeadline
            for primary, range_lo, range_hi in primary_cross_ranges(
                rows,
                cross_min,
                cross_max,
            ):
                if cancelled is not None and cancelled():
                    raise _PreparationDeadline
                range_hi = min(range_hi, primary.columns)
                if rows > primary.rows or range_lo > range_hi:
                    continue
                cross = min(
                    max(leftmost_cross_extent, range_lo),
                    range_hi,
                )
                width, height = (rows, cross) if rotated else (cross, rows)
                min_x_lo = max(limit_min_x, occupied_max_x - width + 1)
                min_x_hi = min(occupied_min_x, limit_max_x - width + 1)
                min_y_lo = max(limit_min_y, occupied_max_y - height + 1)
                min_y_hi = min(occupied_min_y, limit_max_y - height + 1)
                candidates = finalize._frame_candidates_for_extent(
                    width,
                    height,
                    policy,
                )
                for candidate_index, candidate in enumerate(candidates):
                    if candidate.frame.rotated is not rotated:
                        continue
                    if candidate.frame.primary_band != primary.area_segments:
                        continue
                    if cancelled is not None and cancelled():
                        raise _PreparationDeadline
                    coordinate_lo, coordinate_hi = (
                        (min_x_lo, min_x_hi) if rotated else (min_y_lo, min_y_hi)
                    )
                    interval = _ReachableFrameInterval(
                        rotated=rotated,
                        offset_lo=candidate.south_padding - coordinate_hi,
                        offset_hi=candidate.south_padding - coordinate_lo,
                        width=width,
                        height=height,
                        min_x_lo=min_x_lo,
                        min_y_lo=min_y_lo,
                        candidate_index=candidate_index,
                        candidate=candidate,
                    )
                    intervals.append(interval)
                    interval_projection_key = (
                        rotated,
                        interval.offset_lo,
                        interval.offset_hi,
                        candidate.frame.height,
                        candidate.frame.certified_bands,
                    )
                    prior = projection_intervals.get(interval_projection_key)
                    if prior is None or interval.ordering_key() < prior.ordering_key():
                        projection_intervals[interval_projection_key] = interval

    offset_ranges = {
        rotated: (
            min(interval.offset_lo for interval in intervals if interval.rotated is rotated),
            max(interval.offset_hi for interval in intervals if interval.rotated is rotated),
        )
        for rotated in (False, True)
        if any(interval.rotated is rotated for interval in intervals)
    }

    def first_unassigned(following: list[int], position: int) -> int:
        root = position
        while following[root] != root:
            if cancelled is not None and cancelled():
                raise _PreparationDeadline
            root = following[root]
        while following[position] != position:
            if cancelled is not None and cancelled():
                raise _PreparationDeadline
            parent = following[position]
            following[position] = root
            position = parent
        return root

    # Sorting by the offset-independent form of `(min_x, min_y, max_x,
    # max_y, candidate_index)` makes the first interval covering each offset
    # exactly the witness the old four nested edge loops encountered first.
    frame_specs: dict[
        tuple[bool, int],
        tuple[tuple[int, int, int, int], finalize.FrameCandidate],
    ] = {}
    frame_ranks: dict[tuple[bool, int], _FrameWitnessRank] = {}
    next_frame_offset = {
        rotated: list(range(upper - lower + 2)) for rotated, (lower, upper) in offset_ranges.items()
    }
    for interval in sorted(intervals, key=_ReachableFrameInterval.ordering_key):
        if cancelled is not None and cancelled():
            raise _PreparationDeadline
        base, _upper = offset_ranges[interval.rotated]
        following = next_frame_offset[interval.rotated]
        position = first_unassigned(following, interval.offset_lo - base)
        stop = interval.offset_hi - base
        while position <= stop:
            if cancelled is not None and cancelled():
                raise _PreparationDeadline
            offset = base + position
            bounds, rank = interval.witness(offset)
            key = (interval.rotated, offset)
            frame_specs[key] = (bounds, interval.candidate)
            frame_ranks[key] = rank
            following[position] = first_unassigned(following, position + 1)
            position = following[position]

    # A projection has its own first witness because different extent
    # signatures can contribute the same band/anchor.  Each projection-offset
    # pair is assigned once, so this work is proportional to the exact emitted
    # projection union rather than interval span times candidate count.
    projection_ranks: dict[
        tuple[bool, int],
        dict[tuple[int, int], tuple[int, ...]],
    ] = {key: {} for key in frame_specs}
    next_projection_offset: dict[
        tuple[bool, tuple[int, int]],
        list[int],
    ] = {}
    ordered_projection_intervals = sorted(
        projection_intervals.values(),
        key=_ReachableFrameInterval.ordering_key,
    )
    for interval in ordered_projection_intervals:
        if cancelled is not None and cancelled():
            raise _PreparationDeadline
        base, upper = offset_ranges[interval.rotated]
        for band_index, segments in enumerate(interval.candidate.frame.certified_bands):
            if cancelled is not None and cancelled():
                raise _PreparationDeadline
            band = by_segments[segments]
            for anchor_index, anchor in enumerate(band.anchors(interval.candidate.frame.height)):
                if cancelled is not None and cancelled():
                    raise _PreparationDeadline
                band_anchor = (segments, anchor)
                state_key = (interval.rotated, band_anchor)
                projection_following = next_projection_offset.get(state_key)
                if projection_following is None:
                    projection_following = list(range(upper - base + 2))
                    next_projection_offset[state_key] = projection_following
                position = first_unassigned(
                    projection_following,
                    interval.offset_lo - base,
                )
                stop = interval.offset_hi - base
                while position <= stop:
                    if cancelled is not None and cancelled():
                        raise _PreparationDeadline
                    offset = base + position
                    _bounds, rank = interval.witness(offset)
                    projection_ranks[(interval.rotated, offset)][band_anchor] = (
                        *rank,
                        band_index,
                        anchor_index,
                    )
                    projection_following[position] = first_unassigned(
                        projection_following,
                        position + 1,
                    )
                    position = projection_following[position]

    frames: list[_JunctionProjectionFrame] = []
    for key in sorted(frame_specs, key=frame_ranks.__getitem__):
        if cancelled is not None and cancelled():
            raise _PreparationDeadline
        bounds, candidate = frame_specs[key]
        ordered_projections = sorted(
            projection_ranks[key],
            key=projection_ranks[key].__getitem__,
        )
        projections: list[planet.Projection] = []
        for segments, anchor in ordered_projections:
            if cancelled is not None and cancelled():
                raise _PreparationDeadline
            projections.append(
                planet.Projection(
                    band=by_segments[segments],
                    anchor_row=anchor,
                    segment=colliders.PLANET_SEGMENT,
                    radius=colliders.PLANET_RADIUS,
                )
            )
        frames.append(
            _JunctionProjectionFrame(
                bounds=bounds,
                candidate=candidate,
                projections=tuple(projections),
            )
        )
    if cancelled is not None and cancelled():
        raise _PreparationDeadline
    return tuple(frames)


def _prospective_static_failure(
    buildings: Sequence[tuple[int, PlacedBuilding]],
    frames: Sequence[_JunctionProjectionFrame],
    *,
    candidate_index: int,
    cache: _StagedStaticCache | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> finalize.ProjectionFailure | None:
    """First exact candidate collision over finalizer-reachable materializations."""
    if cache is None:
        cache = _StagedStaticCache()
    if cancelled is not None and cancelled():
        raise _PreparationDeadline
    cache.exact_static_queries += 1
    retained = tuple(
        (index, building)
        for index, building in buildings
        if not catalog.is_belt(building.item_id) and not catalog.is_sorter(building.item_id)
    )
    try:
        candidate_position = next(
            position
            for position, (index, _building) in enumerate(retained)
            if index == candidate_index
        )
    except StopIteration:
        raise ValueError("prospective static candidate is not collision-tested") from None
    candidate = retained[candidate_position]
    base = retained[:candidate_position] + retained[candidate_position + 1 :]
    for frame in frames:
        if cancelled is not None and cancelled():
            raise _PreparationDeadline
        pending_materialized: dict[
            tuple[PlacedBuilding, tuple[int, int, int, int], finalize.FrameCandidate],
            PlacedBuilding,
        ] = {}
        base_key = (base, frame.bounds, frame.candidate)
        materialized_base = cache.materialized_bases.get(base_key)
        if materialized_base is None:
            pending_base: list[tuple[int, PlacedBuilding]] = []
            for index, building in base:
                if cancelled is not None and cancelled():
                    raise _PreparationDeadline
                materialized_key = (building, frame.bounds, frame.candidate)
                materialized = cache.materialized.get(
                    materialized_key,
                    pending_materialized.get(materialized_key),
                )
                if materialized is None:
                    materialized = finalize.materialize_frame_building(
                        building,
                        bounds=frame.bounds,
                        candidate=frame.candidate,
                    )
                    pending_materialized[materialized_key] = materialized
                pending_base.append((index, materialized))
            materialized_base = tuple(pending_base)
        if cancelled is not None and cancelled():
            raise _PreparationDeadline
        candidate_key = (candidate[1], frame.bounds, frame.candidate)
        materialized_candidate = cache.materialized.get(
            candidate_key,
            pending_materialized.get(candidate_key),
        )
        if materialized_candidate is None:
            materialized_candidate = finalize.materialize_frame_building(
                candidate[1],
                bounds=frame.bounds,
                candidate=frame.candidate,
            )
            pending_materialized[candidate_key] = materialized_candidate
        materialized_buildings = (
            materialized_base[:candidate_position]
            + ((candidate[0], materialized_candidate),)
            + materialized_base[candidate_position:]
        )
        failure = (
            finalize.first_projected_static_failure(
                materialized_buildings,
                frame.projections,
                _clean_contexts=cache.clean_contexts,
                _box_cache=cache.boxes,
                _placed_cache=cache.placed,
                candidate_index=candidate_index,
            )
            if cancelled is None
            else finalize.first_projected_static_failure(
                materialized_buildings,
                frame.projections,
                _clean_contexts=cache.clean_contexts,
                _box_cache=cache.boxes,
                _placed_cache=cache.placed,
                candidate_index=candidate_index,
                cancelled=cancelled,
            )
        )
        cache.materialized.update(pending_materialized)
        cache.materialized_bases.setdefault(base_key, materialized_base)
        if failure is not None:
            return failure
    return None


def _projected_coater_junction_bans_by_frame(
    coaters: Sequence[tuple[int, PlacedBuilding]],
    frames: Sequence[_JunctionProjectionFrame],
    junction_bounds: tuple[int, int, int, int],
    *,
    already_banned: Set[Cell],
    splitter_index: int,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[frozenset[Cell], ...]:
    """Exact Splitter bans retained separately for each finalizer frame."""
    if cancelled is not None and cancelled():
        raise _PreparationDeadline
    min_x, min_y, max_x, max_y = junction_bounds
    splitter_span = catalog.collider_span(catalog.SPLITTER_ID, 0.0)
    banned_by_frame: list[set[Cell]] = [set() for _frame in frames]
    materialized_splitters: dict[
        tuple[Cell, tuple[int, int, int, int], finalize.FrameCandidate],
        tuple[colliders.Placed, ...],
    ] = {}
    projected_splitter_boxes: dict[
        tuple[colliders.Placed, planet.Projection],
        list[colliders.Box],
    ] = {}
    projected_relation_overlaps: dict[tuple[object, ...], bool] = {}
    projected_context_states: dict[
        tuple[object, ...],
        tuple[
            planet.Projection,
            colliders.Placed,
            tuple[colliders.Box, ...],
        ],
    ] = {}

    for coater_index, coater_building in coaters:
        if cancelled is not None and cancelled():
            raise _PreparationDeadline
        prepared_frames: list[
            tuple[
                int,
                _JunctionProjectionFrame,
                tuple[int, colliders.Placed],
                float,
                float,
                tuple[
                    tuple[
                        planet.Projection,
                        float,
                        float,
                        tuple[colliders.Box, ...],
                        colliders.Placed,
                        tuple[object, ...],
                    ],
                    ...,
                ],
            ]
        ] = []
        scan_reach_x = 0
        scan_reach_y = 0
        for frame_index, frame in enumerate(frames):
            seen_projection_contexts: set[tuple[object, ...]] = set()
            if cancelled is not None and cancelled():
                raise _PreparationDeadline
            materialized_building = finalize.materialize_frame_building(
                coater_building,
                bounds=frame.bounds,
                candidate=frame.candidate,
            )
            materialized_coater = (
                coater_index,
                _collision_pose(materialized_building),
            )
            coater_span_x, coater_span_y = catalog.collider_span(
                catalog.SPRAY_COATER_ID,
                materialized_building.yaw,
            )
            lateral_x = round(materialized_building.yaw) % 180 == 0
            tangent_reach_x = (
                (coater_span_x + splitter_span[0]) / 2.0 + (1.0 if lateral_x else 0.0)
            ) * colliders.GRID_ARC
            tangent_reach_y = (
                (coater_span_y + splitter_span[1]) / 2.0 + (0.0 if lateral_x else 1.0)
            ) * colliders.GRID_ARC
            projection_states: list[
                tuple[
                    planet.Projection,
                    float,
                    float,
                    tuple[colliders.Box, ...],
                    colliders.Placed,
                    tuple[object, ...],
                ]
            ] = []
            materialized_reach_x = 0
            materialized_reach_y = 0
            for projection in frame.projections:
                if cancelled is not None and cancelled():
                    raise _PreparationDeadline
                latitude = (
                    materialized_coater[1].x if projection.rotated else materialized_coater[1].y
                )
                projection_context = (
                    projection.band,
                    projection.segment,
                    projection.radius,
                    projection.quadrant,
                    projection.anchor_row + latitude,
                    materialized_coater[1].z,
                    materialized_coater[1].yaw,
                )
                if projection_context in seen_projection_contexts:
                    continue
                seen_projection_contexts.add(projection_context)
                latitude_step = (
                    projection.radius * planet.latitude_rad_per_grid(projection.segment) * 0.9
                )
                longitude_step = (
                    projection.radius
                    * min(
                        math.cos(
                            min(
                                abs(grid),
                                planet.pole_grid_idx(projection.segment),
                            )
                            * planet.latitude_rad_per_grid(projection.segment)
                        )
                        for grid in (
                            projection.band.grid_lo,
                            projection.band.grid_hi,
                        )
                    )
                    * planet.longitude_rad_per_grid(projection.band.area_segments)
                    * 0.9
                )
                materialized_reach_x = max(
                    materialized_reach_x,
                    math.ceil(tangent_reach_x / longitude_step),
                )
                materialized_reach_y = max(
                    materialized_reach_y,
                    math.ceil(tangent_reach_y / latitude_step),
                )
                context_state = projected_context_states.get(projection_context)
                if context_state is None:
                    context_state = (
                        projection,
                        materialized_coater[1],
                        finalize.projected_coater_keepout_boxes(
                            materialized_coater[1],
                            projection,
                        ),
                    )
                    projected_context_states[projection_context] = context_state
                (
                    canonical_projection,
                    canonical_coater,
                    coater_boxes,
                ) = context_state
                projection_states.append(
                    (
                        canonical_projection,
                        longitude_step,
                        latitude_step,
                        coater_boxes,
                        canonical_coater,
                        projection_context,
                    )
                )
            if frame.candidate.frame.rotated:
                scan_reach_x = max(scan_reach_x, materialized_reach_y)
                scan_reach_y = max(scan_reach_y, materialized_reach_x)
            else:
                scan_reach_x = max(scan_reach_x, materialized_reach_x)
                scan_reach_y = max(scan_reach_y, materialized_reach_y)
            prepared_frames.append(
                (
                    frame_index,
                    frame,
                    materialized_coater,
                    tangent_reach_x,
                    tangent_reach_y,
                    tuple(projection_states),
                )
            )

        for x in range(
            max(min_x, coater_building.x - scan_reach_x),
            min(max_x, coater_building.x + scan_reach_x) + 1,
        ):
            if cancelled is not None and cancelled():
                raise _PreparationDeadline
            for y in range(
                max(min_y, coater_building.y - scan_reach_y),
                min(max_y, coater_building.y + scan_reach_y) + 1,
            ):
                if cancelled is not None and cancelled():
                    raise _PreparationDeadline
                for level in range(LEVELS):
                    cell = (x, y, level)
                    if cell in already_banned:
                        continue
                    splitter_stack = _splitter_stack_geometry(x, y, level)
                    for (
                        frame_index,
                        frame,
                        materialized_coater,
                        tangent_reach_x,
                        tangent_reach_y,
                        frame_projection_states,
                    ) in prepared_frames:
                        if cell in banned_by_frame[frame_index]:
                            continue
                        rejected = False
                        materialized_key = (
                            cell,
                            frame.bounds,
                            frame.candidate,
                        )
                        materialized_stack = materialized_splitters.get(materialized_key)
                        if materialized_stack is None:
                            materialized_stack = tuple(
                                _collision_pose(
                                    finalize.materialize_frame_building(
                                        stack_member,
                                        bounds=frame.bounds,
                                        candidate=frame.candidate,
                                    )
                                )
                                for stack_member in splitter_stack
                            )
                            materialized_splitters[materialized_key] = materialized_stack
                        for materialized_splitter in materialized_stack:
                            cell_dx = abs(materialized_splitter.x - materialized_coater[1].x)
                            cell_dy = abs(materialized_splitter.y - materialized_coater[1].y)
                            for (
                                candidate_projection,
                                x_step,
                                y_step,
                                coater_boxes,
                                canonical_coater,
                                candidate_projection_context,
                            ) in frame_projection_states:
                                if (
                                    cell_dx * x_step > tangent_reach_x
                                    or cell_dy * y_step > tangent_reach_y
                                ):
                                    continue
                                delta_x = materialized_splitter.x - materialized_coater[1].x
                                delta_y = materialized_splitter.y - materialized_coater[1].y
                                delta_z = materialized_splitter.z - materialized_coater[1].z
                                relation_key = (
                                    candidate_projection_context,
                                    materialized_splitter.model_index,
                                    delta_x,
                                    delta_y,
                                    delta_z,
                                    materialized_splitter.yaw,
                                )
                                overlap = projected_relation_overlaps.get(relation_key)
                                if overlap is None:
                                    canonical_splitter = replace(
                                        materialized_splitter,
                                        x=canonical_coater.x + delta_x,
                                        y=canonical_coater.y + delta_y,
                                        z=canonical_coater.z + delta_z,
                                    )
                                    boxes_key = (
                                        canonical_splitter,
                                        candidate_projection,
                                    )
                                    splitter_boxes = projected_splitter_boxes.get(boxes_key)
                                    if splitter_boxes is None:
                                        splitter_boxes = colliders.target_boxes(
                                            canonical_splitter,
                                            *candidate_projection.pose(
                                                canonical_splitter.x,
                                                canonical_splitter.y,
                                                canonical_splitter.z,
                                                canonical_splitter.yaw,
                                            ),
                                        )
                                        projected_splitter_boxes[boxes_key] = splitter_boxes
                                    overlap = False
                                    for coater_box in coater_boxes:
                                        if cancelled is not None and cancelled():
                                            raise _PreparationDeadline
                                        for splitter_box in splitter_boxes:
                                            if cancelled is not None and cancelled():
                                                raise _PreparationDeadline
                                            if colliders.obb_overlap(
                                                coater_box,
                                                splitter_box,
                                            ):
                                                overlap = True
                                                break
                                        if overlap:
                                            break
                                    projected_relation_overlaps[relation_key] = overlap
                                if overlap:
                                    banned_by_frame[frame_index].add(cell)
                                    rejected = True
                                    break
                            if rejected:
                                break
    if cancelled is not None and cancelled():
        raise _PreparationDeadline
    return tuple(frozenset(banned) for banned in banned_by_frame)


def _projection_envelope(
    occupied: tuple[int, int, int, int],
    limit: tuple[int, int, int, int],
    policy: BandPolicy,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[planet.Projection, ...]:
    """Every finalizer projection reachable inside one fixed capacity box."""
    if cancelled is not None and cancelled():
        raise _PreparationDeadline
    occupied_min_x, occupied_min_y, occupied_max_x, occupied_max_y = occupied
    limit_min_x, limit_min_y, limit_max_x, limit_max_y = limit
    if not (
        limit_min_x <= occupied_min_x <= occupied_max_x <= limit_max_x
        and limit_min_y <= occupied_min_y <= occupied_max_y <= limit_max_y
    ):
        raise ValueError("occupied power-planning bounds must lie inside canvas.limit")

    # A projection depends on the rectangle's EXTENT and on only one origin:
    # ``min_y`` normally, or ``min_x`` when the frame is rotated. Enumerating
    # all four rectangle edges repeated each projection once for every
    # irrelevant opposite edge. A modest 26x30 fan-out pack consequently
    # hashed more than 600,000 duplicate projections and spent several seconds
    # preparing power -- beyond its entire 0.5s layout budget.
    #
    # The edge loops deliberately retain their original min-x, min-y, max-x,
    # max-y order. First-seen projection order selects the structured failure
    # reported to the caller, so changing it changes evidence even when the
    # projection SET is identical. Candidate generation is reused by extent,
    # and an orientation is expanded only on the first rectangle with its
    # relevant origin; later rectangles would add no new projection.
    by_segments = {band.area_segments: band for band in planet.bands()}
    candidates_by_extent: dict[
        tuple[int, int],
        tuple[finalize.FrameCandidate, ...],
    ] = {}
    projection_keys: dict[tuple[int, int, int], None] = {}
    first_expansions: dict[tuple[int, int, int, int], int] = {}
    next_anchor: dict[tuple[int, int], dict[int, int]] = {}

    def first_unassigned(following: dict[int, int], anchor: int) -> int:
        path: list[int] = []
        while anchor in following:
            path.append(anchor)
            anchor = following[anchor]
        for prior in path:
            following[prior] = anchor
        return anchor

    occupied_width = occupied_max_x - occupied_min_x + 1
    occupied_height = occupied_max_y - occupied_min_y + 1
    limit_width = limit_max_x - limit_min_x + 1
    limit_height = limit_max_y - limit_min_y + 1
    for width in range(occupied_width, limit_width + 1):
        if cancelled is not None and cancelled():
            raise _PreparationDeadline
        min_x_lo = max(limit_min_x, occupied_max_x - width + 1)
        min_x_hi = min(occupied_min_x, limit_max_x - width + 1)
        for height in range(occupied_height, limit_height + 1):
            if cancelled is not None and cancelled():
                raise _PreparationDeadline
            min_y_lo = max(limit_min_y, occupied_max_y - height + 1)
            min_y_hi = min(occupied_min_y, limit_max_y - height + 1)
            for min_y in range(min_y_lo, min_y_hi + 1):
                key = (
                    min_x_lo,
                    min_y,
                    min_x_lo + width - 1,
                    min_y + height - 1,
                )
                first_expansions[key] = first_expansions.get(key, 0) | 1
            for min_x in range(min_x_lo, min_x_hi + 1):
                key = (
                    min_x,
                    min_y_lo,
                    min_x + width - 1,
                    min_y_lo + height - 1,
                )
                first_expansions[key] = first_expansions.get(key, 0) | 2

    # Sorting the first-witness rectangles is the exact legacy
    # min-x/min-y/max-x/max-y encounter order. At a witness shared by both
    for witness_index, (
        (min_x, min_y, max_x, max_y),
        witnessed,
    ) in enumerate(sorted(first_expansions.items())):
        if cancelled is not None and witness_index % 64 == 0 and cancelled():
            raise _PreparationDeadline
        width = max_x - min_x + 1
        height = max_y - min_y + 1
        extent = (width, height)
        candidates = candidates_by_extent.get(extent)
        if candidates is None:
            candidates = finalize._frame_candidates_for_extent(
                width,
                height,
                policy,
            )
            candidates_by_extent[extent] = candidates
        for candidate in candidates:
            rotated = candidate.frame.rotated
            if not witnessed & (2 if rotated else 1):
                continue
            origin = min_x if rotated else min_y
            row_origin = origin - candidate.south_padding
            quadrant = int(rotated)
            for segments in candidate.frame.certified_bands:
                band = by_segments[segments]
                following = next_anchor.setdefault((segments, quadrant), {})
                for anchor_range in band.anchor_ranges(candidate.frame.height):
                    anchor = first_unassigned(
                        following,
                        anchor_range.start - row_origin,
                    )
                    stop = anchor_range.stop - row_origin
                    while anchor < stop:
                        projection_keys[(segments, anchor, quadrant)] = None
                        following[anchor] = first_unassigned(
                            following,
                            anchor + 1,
                        )
                        anchor = following[anchor]
    projections: list[planet.Projection] = []
    for projection_index, (segments, anchor_row, quadrant) in enumerate(projection_keys):
        if cancelled is not None and projection_index % 64 == 0 and cancelled():
            raise _PreparationDeadline
        projections.append(
            planet.Projection(
                band=by_segments[segments],
                anchor_row=anchor_row,
                segment=colliders.PLANET_SEGMENT,
                radius=colliders.PLANET_RADIUS,
                quadrant=quadrant,
            )
        )
    if cancelled is not None and cancelled():
        raise _PreparationDeadline
    return tuple(projections)


def _power_projection_envelope(
    canvas: _Canvas,
    policy: BandPolicy,
    *,
    capacity: tuple[int, int, int, int] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[planet.Projection, ...]:
    """Projection union down to geometry no cleanup eligibility can remove."""
    if cancelled is not None and cancelled():
        raise _PreparationDeadline
    occupied = _core_bounds(canvas)
    cleanup_inner = (
        finalize._cleanup_survivor_bounds(
            Placement(buildings=tuple(canvas.buildings)),
        )
        if cancelled is None
        else finalize._cleanup_survivor_bounds(
            Placement(buildings=tuple(canvas.buildings)),
            cancelled=cancelled,
        )
    )
    return _projection_envelope(
        cleanup_inner,
        capacity if capacity is not None else canvas.limit or occupied,
        policy,
        cancelled=cancelled,
    )


def _power_plan(
    canvas: _Canvas,
    demand: tuple[int, int, int, int],
    *,
    policy: BandPolicy,
    additional_demand: Collection[tuple[int, int]] = (),
    staged_static_cache: _StagedStaticCache | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> list[tuple[int, int]]:
    """Where every tower goes, decided BEFORE anything routes.

    Raises :class:`_Unpowerable` when this pack cannot be powered at all, which
    is a property of the PACK and makes it infeasible.  Otherwise it returns a
    placement that covers every powered tile and is connected, and the cells are
    held in ``canvas.keep_out`` so the router paths around them.

    ``demand`` is the complete route-capable envelope. ``additional_demand``
    names known powered junctions outside that envelope without pessimistically
    powering the entire belt-only entry ring. ``canvas.limit`` is the boundary
    where towers may stand.

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
    if staged_static_cache is None:
        staged_static_cache = _StagedStaticCache()
    if cancelled is not None and cancelled():
        raise _PreparationDeadline
    tower = catalog.building(catalog.TESLA_TOWER_ID)
    reach2 = math.floor((2 * tower.cover_radius) ** 2)
    link2 = math.floor((2 * tower.connect_distance) ** 2)
    demand_x0, demand_y0, demand_x1, demand_y1 = demand
    # A TOWER MAY STAND OUTSIDE THE POWER DEMAND. WHAT IT COVERS MAY NOT.
    #
    # Standing ground is the whole canvas, the outer entry ring included,
    # because on a small dense build the powered demand is packed SOLID -- every
    # cell a machine or a lane -- and a tower restricted to it would have
    # nowhere at all to go. The old lattice was restricted to the core and its
    # repair pass was not (`try_place` never checked), so towers in the ring are
    # what that build was relying on all along, without anybody saying so.
    #
    # It is a second choice, not a free one: the outer ring is where the
    # external input runs come in, and a tower in one breaks the straight run
    # out to it. So the demand envelope is searched first and the outer ring is
    # reached into only for tiles the demand envelope cannot cover -- see
    # `in_demand` at the placement loop.
    min_x, min_y, max_x, max_y = canvas.limit or demand
    min_x, min_y = min(min_x, demand_x0), min(min_y, demand_y0)
    max_x, max_y = max(max_x, demand_x1), max(max_y, demand_y1)
    width, height = max_x - min_x + 1, max_y - min_y + 1
    if demand_x1 < demand_x0 or demand_y1 < demand_y0:
        return []

    # Padded so a disc or link stamp near an edge needs no clipping. The stamps
    # reach `link` and are read `reach` further out, so the margin covers both.
    reach = int(tower.cover_radius) + 1
    link = int(tower.connect_distance) + 1
    pad = link + reach + 1
    shape = (width + 2 * pad, height + 2 * pad)

    free = np.zeros(shape, dtype=bool)
    for x in range(min_x, max_x + 1):
        if cancelled is not None and cancelled():
            raise _PreparationDeadline
        for y in range(min_y, max_y + 1):
            if canvas.limit is not None and not (
                canvas.limit[0] <= x <= canvas.limit[2] and canvas.limit[1] <= y <= canvas.limit[3]
            ):
                continue
            if not canvas.free((x, y, 0)) or (x, y) in canvas.solid:
                continue
            if any((x, y, lvl) in canvas.blocked for lvl in range(LEVELS)):
                continue
            free[x - min_x + pad, y - min_y + pad] = True

    in_demand = np.zeros(shape, dtype=bool)
    in_demand[
        demand_x0 - min_x + pad : demand_x1 - min_x + pad + 1,
        demand_y0 - min_y + pad : demand_y1 - min_y + pad + 1,
    ] = True

    # WHAT HAS TO BE COVERED IS THE ROUTE-CAPABLE POWER DEMAND, NOT ONLY THE
    # BUILDINGS STANDING IN IT.
    #
    # This runs BEFORE routing, and routing is what places the sorters, spray
    # coaters and Splitters -- all of which draw power. Covering the buildings
    # that exist right now leaves those future receivers dark, and the placement
    # then fails `power.coverage` at certify having looked perfectly correct
    # here. Measured, and it is not a corner case: covering only the machines
    # refused `universe-matrix` at free-proliferation and max-proliferation on
    # every height, in three audits out of four.
    #
    # The demand envelope is the region routing may occupy with powered
    # buildings. The outer entry ring beyond it remains belt-only, so covering
    # the explicit demand is the condition that does not depend on what has been
    # placed yet. It is still need-based rather than a grid: a tower covers a
    # 346-tile disc and the demand is covered by discs, not by a point every nine
    # tiles.
    dark = in_demand.copy()
    for x, y in additional_demand:
        gx, gy = x - min_x + pad, y - min_y + pad
        if 0 <= gx < shape[0] and 0 <= gy < shape[1]:
            dark[gx, gy] = True
    for b in canvas.buildings:
        if cancelled is not None and cancelled():
            raise _PreparationDeadline
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
    power_nodes: list[tuple[int, PlacedBuilding, rules.PowerNode]] = []
    for index, b in enumerate(canvas.buildings):
        if cancelled is not None and cancelled():
            raise _PreparationDeadline
        try:
            peer = catalog.building(b.item_id).power_node
        except KeyError:
            continue
        if not peer.is_power_node:
            continue
        power_nodes.append((index, b, peer))
        cx = b.x + b.width // 2 - min_x + pad
        cy = b.y + b.height // 2 - min_y + pad
        for dx, dy, dz in rules.power_node_keepout_offsets(peer, tower.power_node):
            if cancelled is not None and cancelled():
                raise _PreparationDeadline
            if dz:
                continue
            gx, gy = cx + dx, cy + dy
            if 0 <= gx < shape[0] and 0 <= gy < shape[1]:
                free[gx, gy] = False

    projections = _power_projection_envelope(
        canvas,
        policy,
        cancelled=cancelled,
    )
    projection_bands = tuple(
        sorted(
            {projection.band for projection in projections},
            key=lambda band: band.area_segments,
        )
    )
    power_projection_contexts = tuple(
        dict.fromkeys(
            (
                projection.band.columns,
                projection.rotated,
                _minimum_projection_grid_scale((projection.band,)),
            )
            for projection in projections
        )
    )
    static_buildings = list(enumerate(canvas.buildings))
    static_by_index = dict(static_buildings)
    obstacle_index = _ProjectedObstacleIndex.build(
        static_buildings,
        cancelled=cancelled,
    )
    cleanup_prefix = finalize._CleanupSurvivorGraph(
        Placement(buildings=tuple(building for _, building in static_buildings)),
        cancelled=cancelled,
        _operations=staged_static_cache.cleanup_operations,
    )
    cleanup_bounds = cleanup_prefix.snapshot_bounds()
    static_frames_by_bounds: dict[
        tuple[int, int, int, int],
        tuple[_JunctionProjectionFrame, ...],
    ] = {}
    for projection in projections:
        if cancelled is not None and cancelled():
            raise _PreparationDeadline
        existing_failure = (
            finalize.projected_power_failure(
                power_nodes,
                projection,
            )
            if cancelled is None
            else finalize.projected_power_failure(
                power_nodes,
                projection,
                cancelled=cancelled,
            )
        )
        if existing_failure is not None:
            raise _Unpowerable(
                "existing power nodes are illegal in a required projection",
                failure=existing_failure,
            )

    def spread(mask: np.ndarray) -> np.ndarray:
        """Cells within tower reach of anything in ``mask``."""
        out = np.zeros(shape, dtype=bool)
        for dx, dy in disc:
            out[max(0, dx) : shape[0] + min(0, dx), max(0, dy) : shape[1] + min(0, dy)] |= mask[
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
        openness[max(0, dx) : shape[0] + min(0, dx), max(0, dy) : shape[1] + min(0, dy)] += free[
            max(0, -dx) : shape[0] + min(0, -dx), max(0, -dy) : shape[1] + min(0, -dy)
        ]

    remaining = dark.copy()
    # `score` is maintained incrementally. Rebuilding it every round is the same
    # answer and was measured at 0.9s on `universe-matrix`, which is real money
    # against a 15s deadline; only the cells within two radii of a new tower can
    # change, so only those are touched.
    score = np.zeros(shape, dtype=np.int32)
    for dx, dy in disc:
        score[max(0, dx) : shape[0] + min(0, dx), max(0, dy) : shape[1] + min(0, dy)] += remaining[
            max(0, -dx) : shape[0] + min(0, -dx), max(0, -dy) : shape[1] + min(0, -dy)
        ]

    linked = np.zeros(shape, dtype=bool)
    sites: list[tuple[int, int]] = []
    projected_refusal: finalize.ProjectionFailure | None = None
    projected_retry_evidence: _ExactRetryEvidence | None = None
    # A cap, not a schedule: every round either consumes or rejects one free
    # cell, so a placement that has not finished by then is not converging.
    for _ in range(int(np.count_nonzero(free)) + 1):
        if cancelled is not None and cancelled():
            raise _PreparationDeadline
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
        # The demand envelope first, and the outer entry ring only for what the
        # demand cannot reach. Widening is per ROUND rather than once and for
        # all, so a build that needs one outer-ring cell takes one, not a
        # placement's worth.
        gx = gy = -1
        for allowed in (reachable_now & in_demand, reachable_now):
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
                raise _Unpowerable(
                    "the tower network cannot reach the rest of the block",
                    failure=projected_refusal,
                    exact_retry_evidence=projected_retry_evidence,
                )
            target = np.argwhere(remaining)[0]
            gx, gy = cand[np.argmin(((cand - target) ** 2).sum(axis=1))].tolist()
        site = (gx - pad + min_x, gy - pad + min_y)
        candidate = (
            len(canvas.buildings) + len(sites),
            PlacedBuilding(
                item_id=catalog.TESLA_TOWER_ID,
                model_index=tower.model_index,
                x=site[0],
                y=site[1],
                width=tower.width,
                height=tower.height,
            ),
            tower.power_node,
        )
        projected_power_peers = tuple(
            peer
            for peer in power_nodes
            if _projected_power_peer_possible(
                candidate,
                peer,
                power_projection_contexts,
                cancelled=cancelled,
            )
        )
        candidate_failure: finalize.ProjectionFailure | None = None
        for projection in projections:
            if cancelled is not None and cancelled():
                raise _PreparationDeadline
            for projected_peer in projected_power_peers:
                if cancelled is not None and cancelled():
                    raise _PreparationDeadline
                candidate_failure = (
                    finalize.projected_power_failure(
                        (projected_peer, candidate),
                        projection,
                    )
                    if cancelled is None
                    else finalize.projected_power_failure(
                        (projected_peer, candidate),
                        projection,
                        cancelled=cancelled,
                    )
                )
                if candidate_failure is not None:
                    break
            if candidate_failure is not None:
                break
        if candidate_failure is None:
            potential_peers = _prospective_static_broad_phase_for_bands(
                obstacle_index,
                candidate[1],
                projection_bands,
                staged_static_cache,
                cancelled=cancelled,
            )
            # A linkless tower already inside the certified rectangle cannot
            # change cleanup survivors. Extending any side can revive a linked
            # belt that the old boundary pruned, including one that expands the
            # orthogonal axis, so that case must advance the exact prefix.
            candidate_cleanup, candidate_bounds = _cleanup_snapshot_with_linkless_static(
                cleanup_prefix,
                cleanup_bounds,
                candidate[1],
                cancelled=cancelled,
            )
            if potential_peers:
                static_frames = static_frames_by_bounds.get(candidate_bounds)
                if static_frames is None:
                    static_frames = _cached_junction_projection_frames(
                        staged_static_cache,
                        candidate_bounds,
                        canvas.limit or candidate_bounds,
                        policy,
                        cancelled=cancelled,
                    )
                    static_frames_by_bounds[candidate_bounds] = static_frames
                candidate_failure = _prospective_static_failure(
                    (
                        *((index, static_by_index[index]) for index in potential_peers),
                        (candidate[0], candidate[1]),
                    ),
                    static_frames,
                    candidate_index=candidate[0],
                    cache=staged_static_cache,
                    cancelled=cancelled,
                )
        if candidate_failure is not None:
            if projected_refusal is None:
                projected_refusal = candidate_failure
                if candidate_failure.check == "geom.collide":
                    projected_retry_evidence = _exact_retry_evidence(
                        "power",
                        candidate_failure,
                        dict((*static_buildings, (candidate[0], candidate[1]))),
                    )
            free[gx, gy] = False
            continue
        sites.append(site)
        power_nodes.append(candidate)
        cleanup_bounds = candidate_bounds
        cleanup_prefix = candidate_cleanup

        # The cell itself AND every cell inside the paste's power-node spacing
        # rule.  Marking only the cell is what shipped a blueprint the game
        # refused; the halo is what makes this greedy incapable of producing one.
        free[
            gx - spacing_reach : gx + spacing_reach + 1,
            gy - spacing_reach : gy + spacing_reach + 1,
        ] &= ~spacing_stamp
        linked[gx - link : gx + link + 1, gy - link : gy + link + 1] |= link_stamp
        win = (slice(gx - reach, gx + reach + 1), slice(gy - reach, gy + reach + 1))
        newly = remaining[win] & disc_stamp
        if newly.any():
            remaining[win] &= ~disc_stamp
            covered = np.zeros(shape, dtype=bool)
            covered[win] = newly
            lo_x, hi_x = gx - 2 * reach, gx + 2 * reach + 1
            lo_y, hi_y = gy - 2 * reach, gy + 2 * reach + 1
            for dx, dy in disc:
                score[lo_x:hi_x, lo_y:hi_y] -= covered[lo_x + dx : hi_x + dx, lo_y + dy : hi_y + dy]
    else:
        raise _Unpowerable(
            "tower placement did not converge",
            failure=projected_refusal,
            exact_retry_evidence=projected_retry_evidence,
        )

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
    domains = {port.cargo_domain for port in (*srcs, *sinks)}
    if len(domains) != 1:
        raise ValueError("lane pairing requires exactly one cargo domain")
    pairs = [(k % len(srcs), k % len(sinks)) for k in range(max(len(srcs), len(sinks)))]
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

    islands: dict[tuple[str, int], tuple[list[int], list[int]]] = defaultdict(lambda: ([], []))
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
    policy: BandPolicy,
    ramped: bool = False,
    _reserve_ports: bool = True,
    staged_static_cache: _StagedStaticCache | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> _PreparedRoutingProblem:
    """Build immutable exact geometry shared by both routing engines."""
    belt_id = catalog.get_item_id(spec.belt_item_id) or 2001
    belt_model = catalog.building(belt_id).model_index
    canvas = _Canvas(ramped=ramped, sorter_tiers=_sorter_tiers_for(spec))
    if staged_static_cache is None:
        staged_static_cache = _StagedStaticCache()
    if cancelled is not None and cancelled():
        raise _PreparationDeadline

    groups = _adapt(spec)
    rates: dict[str, Fraction] = {}
    for g in groups.values():
        for item, r in list(g.inputs.items()) + list(g.outputs.items()):
            rates[item] = max(rates.get(item, Fraction(0)), r * g.count)
    if cancelled is not None and cancelled():
        raise _PreparationDeadline

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
        key: (dict(g.inputs), dict(g.outputs)) for key, g in groups.items()
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
    in_ports: dict[tuple[str, str, CargoDomain], list[_Port]] = defaultdict(list)
    # The producer side collides the same way: sharding a producer gives several
    # strips the SAME destination set, so the key includes group, item, domain,
    # and destination.
    out_ports: dict[tuple[str, str, str, CargoDomain], list[_Port]] = defaultdict(list)
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
    lane_supply: dict[CargoKey, dict[int, Fraction]] = defaultdict(dict)
    lane_demand: dict[CargoKey, dict[int, Fraction]] = defaultdict(dict)
    sibling_lanes: dict[CargoKey, list[tuple[int, int]]] = defaultdict(list)
    strip_of_belt: dict[int, int] = {}
    sorters = 0
    for i, s in enumerate(strips):
        if cancelled is not None and cancelled():
            raise _PreparationDeadline
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
            owner_strip=i,
        )
        sorters += placed
        strip_in_ports.append(ins)
        for port in (*ins.values(), *outs.values()):
            for belt in port.tiles:
                strip_of_belt[belt] = i
        for item, port in ins.items():
            in_ports[s.group_key, item, port.cargo_domain].append(port)
        made = per_item.get(s.group_key, ({}, {}))[1]
        by_cargo: dict[CargoKey, list[int]] = defaultdict(list)
        cargo_weight: dict[CargoKey, Fraction] = defaultdict(Fraction)
        for (item, dest, cargo_domain), port in outs.items():
            cargo = (item, cargo_domain)
            out_ports[s.group_key, item, dest, cargo_domain].append(port)
            lane_of[port.belt] = port
            by_cargo[cargo].append(port.belt)
            cargo_weight[cargo] += _sink_demand(groups, spec, item, dest)
        by_item: dict[str, list[CargoKey]] = defaultdict(list)
        for cargo in by_cargo:
            by_item[cargo[0]].append(cargo)
        for item, item_cargo_keys in by_item.items():
            total_weight = sum(
                (cargo_weight[cargo] for cargo in item_cargo_keys),
                Fraction(0),
            )
            for cargo in item_cargo_keys:
                belts = sorted(by_cargo[cargo])
                share = (
                    cargo_weight[cargo] / total_weight
                    if total_weight > 0
                    else Fraction(1, len(item_cargo_keys))
                )
                lane_supply[cargo][belts[0]] = s.machines * made.get(item, Fraction(0)) * share
                for belt in belts[1:]:
                    lane_supply[cargo][belt] = Fraction(0)
                    sibling_lanes[cargo].append((belts[0], belt))
    if cancelled is not None and cancelled():
        raise _PreparationDeadline

    # Nets rewarded as direct inserts never silently fall back to an ordinary
    # route. The exact strip/item/domain promise is either emitted and recorded,
    # or retained below as STATIC_ACCESS evidence.
    promised_direct = pack.direct
    realized_direct: set[DirectInsertId] = set()

    nets: list[_Net] = []
    # Everything already joined for an item, so `_join_shard_islands` can see
    # the flow graph the whole build makes rather than one edge of it. Keyed by
    # BELT index, which is what makes a lane serving several destinations one
    # node instead of several.
    joined: dict[CargoKey, list[tuple[int, int]]] = defaultdict(list)
    # Every sorter already standing, as the PASTE will test it.  Built once and
    # extended by each bridge that lands: `_bridge` is asked once per lane pair
    # and rebuilding this inside it is quadratic in the sorter count, which on a
    # stress spec is thousands.
    standing = slots.sorter_seat_boxes(canvas.buildings)
    for (src_key, item, dest_group, cargo_domain), srcs in out_ports.items():
        if cancelled is not None and cancelled():
            raise _PreparationDeadline
        # One output lane may serve SEVERAL destination groups -- see
        # `_merge_lanes` -- and each of them is its own set of consumer strips to
        # pair against. Domain is part of the key, so a clean and a sprayed lane
        # can never become siblings merely because they carry the same item.
        cargo = (item, cargo_domain)
        out_rate = per_item.get(src_key, ({}, {}))[1].get(item, Fraction(0))
        for dest in _dests(dest_group):
            sinks = in_ports.get((dest, item, cargo_domain), [])
            if not srcs or not sinks:
                continue
            in_rate = per_item.get(dest, ({}, {}))[0].get(item, Fraction(0))
            for port, sink in _pair_lanes(srcs, sinks, out_rate=out_rate, in_rate=in_rate):
                joined[cargo].append((port.belt, sink.belt))
                lane_of[sink.belt] = sink
                lane_demand[cargo][sink.belt] = sink.machines * in_rate
                direct_id = DirectInsertId(
                    source_strip=strip_of_belt[port.belt],
                    destination_strip=strip_of_belt[sink.belt],
                    item=item,
                    cargo_domain=cargo_domain,
                )
                if direct_id in promised_direct:
                    realized = _bridge(
                        canvas,
                        port,
                        sink,
                        rates,
                        item,
                        standing,
                        direct_id,
                    )
                    if realized is not None:
                        realized_direct.add(realized)
                    # A failed rewarded bridge is a failed attempt, not a licence
                    # to restore the net the objective was paid to delete.
                    continue
                nets.append(
                    _Net(
                        src=port,
                        dst=sink,
                        item=item,
                        cargo_domain=cargo_domain,
                    )
                )
    if cancelled is not None and cancelled():
        raise _PreparationDeadline

    active_cargo = set(joined) | set(sibling_lanes)
    demand_by_item = {
        item: sum(
            (
                sum(lane_demand[cargo].values(), Fraction(0))
                for cargo in active_cargo
                if cargo[0] == item
            ),
            Fraction(0),
        )
        for item, _cargo_domain in active_cargo
    }
    for cargo in sorted(active_cargo, key=lambda key: (key[0], key[1].value)):
        if cancelled is not None and cancelled():
            raise _PreparationDeadline
        item, cargo_domain = cargo
        total_demand = demand_by_item[item]
        domain_demand = sum(lane_demand[cargo].values(), Fraction(0))
        external = spec.external_inputs.get(item, Fraction(0))
        domain_external = (
            external * domain_demand / total_demand if total_demand > 0 else Fraction(0)
        )
        for a, b in _join_shard_islands(
            joined[cargo] + sibling_lanes[cargo],
            lane_supply[cargo],
            lane_demand[cargo],
            domain_external,
        ):
            nets.append(
                _Net(
                    src=lane_of[a],
                    dst=lane_of[b],
                    item=item,
                    cargo_domain=cargo_domain,
                )
            )
    if cancelled is not None and cancelled():
        raise _PreparationDeadline

    # Hold one cell beside every port BEFORE anything else can take it.
    #
    # Coater drop belts and external input runs are placed onto a canvas that is
    # otherwise empty, so they take whatever cell suits them -- and a lane head's
    # only free neighbour is exactly the sort of cell that suits them. The net
    # that needed it is then handed an EMPTY goal set: A* returns None having
    # expanded nothing, and no amount of rip-up can negotiate for a cell that is
    # occupied by a building rather than contested by another path.
    #
    unreachable_ports: set[Cell] = set()
    stranded_ports: list[StrandedPort] = []

    # Measured across the trivial+small+mid corpus, before this: every boxed-in
    # port on the refusing candidates had a coater drop or an external belt on
    # its one open side, and the boxed-in count equalled the failure count
    # exactly. `_route_all` re-derives these once every path is laid, so this is
    # a claim staked early rather than a second source of truth.
    def hold_ports() -> None:
        # A lane fed from the boundary AND from a producer inside the block has
        # two feeds to accept, not one, so it needs two ways in.  Note this is a
        # property of the ITEM, not of the lane's cardinality: a single-item lane
        # is in this set whenever that item is both external and made internally.
        net_ports = {(p.x, p.y, p.z) for n in nets for p in (n.src, n.dst) if p is not None}
        shared_feed = {
            (port.x, port.y, port.z)
            for ports in strip_in_ports
            for item, port in ports.items()
            if item in spec.external_inputs
        } & net_ports
        unreachable_ports.clear()
        stranded_ports.clear()
        demands: dict[Cell, tuple[int, int, int]] = {}
        _reserve_port_access(
            canvas,
            nets,
            twice=shared_feed,
            failed_ports=unreachable_ports,
            demands=demands,
        )
        owner = {
            (port.x, port.y, port.z): (item, strips[strip_index].sid)
            for strip_index, ports in enumerate(strip_in_ports)
            for item, port in ports.items()
        }
        stranded_ports.extend(
            StrandedPort(
                cell=cell,
                item=owner.get(cell, ("?", "?"))[0],
                strip_label=owner.get(cell, ("?", "?"))[1],
                held=demands[cell][0],
                wants=demands[cell][1],
                options=demands[cell][2],
            )
            for cell in sorted(unreachable_ports)
        )

    if _reserve_ports:
        hold_ports()
    if cancelled is not None and cancelled():
        raise _PreparationDeadline

    # Coaters go in BEFORE routing, because each one needs a proliferator net
    # routed to its drop belt. Placing them afterwards -- as this used to --
    # leaves them mounted on belts with nothing feeding them, so every
    # proliferated recipe silently runs unproliferated.
    assert staged_static_cache is not None
    if cancelled is not None and cancelled():
        raise _PreparationDeadline
    coater_list: list[CoaterSupplyPort] = []
    prolif_item = _proliferator_item(spec)
    if spec.spray_lanes or any(
        port.cargo_domain is CargoDomain.REQUIRES_SPRAY
        for ports in strip_in_ports
        for port in ports.values()
    ):
        if cancelled is None:
            coater_list = _place_coaters(
                canvas,
                spec,
                strips,
                strip_in_ports,
                belt_id,
                belt_model,
                policy=policy,
            )
        else:
            coater_list = _place_coaters(
                canvas,
                spec,
                strips,
                strip_in_ports,
                belt_id,
                belt_model,
                policy=policy,
                staged_static_cache=staged_static_cache,
                cancelled=cancelled,
            )
    coaters = len(coater_list)
    for coater in coater_list:
        host_strip = strip_of_belt[coater.host_belt]
        strip_of_belt[coater.approach_belt] = host_strip
        strip_of_belt[coater.supply_belt] = host_strip
    if cancelled is not None and cancelled():
        raise _PreparationDeadline

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
    envelope = finalize.band_policy_search_envelope(
        policy,
        perimeter=_ENTRY_RING,
    )
    core = _extend_core_for_unique_proliferator_roots(
        core,
        coater_count=len(coater_list),
        boundary_core_height=envelope.boundary_core_height,
    )
    core_width = core[2] - core[0] + 1
    core_height = core[3] - core[1] + 1
    if not envelope.frame_candidates(core_width, core_height):
        raise finalize.ProjectionRefusal((envelope.extent_failure(core_width, core_height),))
    capacity = _grow(core, _ENTRY_RING)
    canvas.limit = capacity
    route_bounds = _grow(core, _ROUTE_RING)
    if cancelled is not None and cancelled():
        raise _PreparationDeadline

    # The proliferator entry and its shared trunk are staked BEFORE the ports
    # are held. Every coater drop is a sink-only leaf; the trunk is the one
    # externally reachable source from which the detailed router branches.
    internal_net_count = len(nets)
    if coater_list and prolif_item is not None:
        entry = _place_proliferator_entry(canvas, prolif_item, belt_id, belt_model, core)
        if entry is not None:
            nets.extend(
                _proliferator_supply_tree(
                    canvas,
                    entry,
                    coater_list,
                    prolif_item,
                    belt_id=belt_id,
                    belt_model=belt_model,
                    core=core,
                )
            )

    if cancelled is not None and cancelled():
        raise _PreparationDeadline
    # Again, now that every port exists -- strip lanes, coater drops and the
    # proliferator entry alike. A drop is a one-tile lane and the sink of a
    # proliferator net, so it is a port like any other, and it did not exist
    # when the first claim was staked.
    if _reserve_ports:
        hold_ports()
    if cancelled is not None and cancelled():
        raise _PreparationDeadline

    # External-input nets retain the existing lane-deduplication and item
    # precedence, while exposing their shared boundary cells immutably.
    wanted: dict[int, tuple[_Port, int]] = {}
    carried: dict[int, str] = {}
    for strip_index, ports in enumerate(strip_in_ports):
        if cancelled is not None and cancelled():
            raise _PreparationDeadline
        for item, port in sorted(ports.items()):
            if item in spec.external_inputs:
                wanted.setdefault(port.belt, (port, strip_index))
        for item, port in sorted(ports.items(), reverse=True):
            if item in spec.external_inputs:
                carried[port.belt] = item

    requested_outputs = set(spec.outputs) | set(spec.surplus_outputs)
    wanted_outputs: dict[int, tuple[str, _Port]] = {}
    for (
        _group_key,
        output_item,
        destination,
        _cargo_domain,
    ), output_ports in out_ports.items():
        destinations = _dests(destination)
        if (
            output_item not in requested_outputs
            or (destination and "" not in destinations)
        ):
            continue
        for output_port in output_ports:
            wanted_outputs.setdefault(
                output_port.belt,
                (output_item, output_port),
            )
    if cancelled is not None and cancelled():
        raise _PreparationDeadline
    min_x, min_y, max_x, max_y = _grow(core, _ENTRY_RING - 1)
    boundary = tuple(
        cell
        for cell in (
            [(x, y, 0) for x in range(min_x - 1, max_x + 2) for y in (min_y - 1, max_y + 1)]
            + [(x, y, 0) for y in range(min_y, max_y + 1) for x in (min_x - 1, max_x + 1)]
        )
        if canvas.free(cell)
    )
    if cancelled is not None and cancelled():
        raise _PreparationDeadline

    tagged_nets = [
        (
            net,
            NetRole.INTERNAL if i < internal_net_count else NetRole.PROLIFERATOR,
        )
        for i, net in enumerate(nets)
    ]
    tagged_nets.extend(
        (
            _Net(
                src=None,
                dst=port,
                item=carried[belt],
                cargo_domain=port.cargo_domain,
            ),
            NetRole.EXTERNAL,
        )
        for belt, (port, _strip_index) in wanted.items()
    )
    tagged_nets.extend(
        (
            _Net(
                src=port,
                dst=port,
                item=item,
                cargo_domain=port.cargo_domain,
            ),
            NetRole.EXTERNAL_OUTPUT,
        )
        for item, port in wanted_outputs.values()
    )
    if cancelled is not None and cancelled():
        raise _PreparationDeadline

    ordinals: dict[
        tuple[int | None, int | None, str, CargoDomain, NetRole],
        int,
    ] = defaultdict(int)
    prepared_nets: list[_PreparedNet] = []
    prepared_output_nets: list[_PreparedNet] = []
    for net, role in tagged_nets:
        if cancelled is not None and cancelled():
            raise _PreparationDeadline
        source_strip = strip_of_belt.get(net.src.belt) if net.src is not None else None
        destination_strip = (
            None
            if role is NetRole.EXTERNAL_OUTPUT
            else strip_of_belt.get(net.dst.belt)
        )
        identity = (
            source_strip,
            destination_strip,
            net.item,
            net.cargo_domain,
            role,
        )
        logical_id = LogicalNetId(
            source_family=(strips[source_strip].family_id if source_strip is not None else None),
            destination_family=(
                strips[destination_strip].family_id if destination_strip is not None else None
            ),
            item=net.item,
            role=role,
            cargo_domain=net.cargo_domain,
        )
        net_id = NetId(
            source_strip=source_strip,
            destination_strip=destination_strip,
            item=net.item,
            role=role,
            ordinal=ordinals[identity],
            cargo_domain=net.cargo_domain,
            logical_id=logical_id,
        )
        ordinals[identity] += 1
        prepared = _PreparedNet(
            net_id=net_id,
            src=_prepare_port(net.src) if net.src is not None else None,
            dst=_prepare_port(net.dst),
            item=net.item,
            cargo_domain=net.cargo_domain,
            boundary_goals=(
                boundary
                if role in (NetRole.EXTERNAL, NetRole.EXTERNAL_OUTPUT)
                else ()
            ),
        )
        if role is NetRole.EXTERNAL_OUTPUT:
            prepared_output_nets.append(prepared)
        else:
            prepared_nets.append(prepared)
    if cancelled is not None and cancelled():
        raise _PreparationDeadline

    def prepared_endpoints(
        prepared: _PreparedNet,
    ) -> tuple[Cell | None, Cell]:
        source = None if prepared.src is None else (prepared.src.x, prepared.src.y, prepared.src.z)
        return source, (prepared.dst.x, prepared.dst.y, prepared.dst.z)

    all_prepared_nets = (*prepared_nets, *prepared_output_nets)
    net_by_id = {prepared.net_id: prepared for prepared in all_prepared_nets}

    def static_access_failure(
        prepared: _PreparedNet,
        failed: Cell,
    ) -> NetFailure:
        nearby = {
            candidate
            for dx, dy in _STEPS
            for candidate in ((failed[0] + dx, failed[1] + dy, failed[2]),)
        }
        nearby.update(
            candidate
            for access in tuple(nearby)
            for dx, dy in _STEPS
            for candidate in ((access[0] + dx, access[1] + dy, access[2]),)
        )
        blocking_cells = tuple(sorted(cell for cell in nearby if cell in canvas.reserved))
        blocking_ports = {
            canvas.reserved[cell] for cell in blocking_cells if canvas.reserved[cell] != failed
        }
        blocking_nets = tuple(
            net_id
            for candidate in all_prepared_nets
            if candidate.net_id != prepared.net_id
            and any(
                endpoint in blocking_ports
                for endpoint in prepared_endpoints(candidate)
                if endpoint is not None
            )
            for net_id in (candidate.net_id,)
        )
        return NetFailure(
            prepared.net_id,
            RouteFailureKind.STATIC_ACCESS,
            (failed, *blocking_cells),
            blocking_nets,
            0,
            source=prepared_endpoints(prepared)[0],
            destination=prepared_endpoints(prepared)[1],
            blocking_endpoints=tuple(
                prepared_endpoints(net_by_id[blocker]) for blocker in blocking_nets
            ),
        )

    preparation_failures = tuple(
        static_access_failure(net, failed)
        for net in all_prepared_nets
        for failed in (
            next(
                (
                    cell
                    for cell in (
                        ((net.src.x, net.src.y, net.src.z) if net.src is not None else None),
                        (net.dst.x, net.dst.y, net.dst.z),
                    )
                    if cell is not None and cell in unreachable_ports
                ),
                None,
            ),
        )
        if failed is not None
    )
    preparation_failures += tuple(
        NetFailure(
            direct.net_id,
            RouteFailureKind.STATIC_ACCESS,
            (),
            (),
            0,
        )
        for direct in sorted(promised_direct - realized_direct)
    )

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
    # Every source is an already materialized belt tile.  Leaving it may require
    # a Splitter even when only one logical net uses that exact tile: a
    # proliferator trunk, for example, already continues past each branch.
    # Count-based fan-out therefore misses the boundary taps that actually need
    # power.  Cover only source tiles outside the route envelope; sources inside
    # it are already covered by ``demand``.
    additional_power_demand = tuple(
        sorted(
            {
                (source.x, source.y)
                for net in nets
                if net.src is not None
                for source in (net.source,)
                if not (
                    route_bounds[0] <= source.x <= route_bounds[2]
                    and route_bounds[1] <= source.y <= route_bounds[3]
                )
            }
        )
    )
    if preparation_failures or not power:
        power_sites = []
    elif cancelled is None:
        power_sites = _power_plan(
            canvas,
            route_bounds,
            policy=policy,
            additional_demand=additional_power_demand,
        )
    else:
        power_sites = _power_plan(
            canvas,
            route_bounds,
            policy=policy,
            additional_demand=additional_power_demand,
            staged_static_cache=staged_static_cache,
            cancelled=cancelled,
        )
    if cancelled is not None and cancelled():
        raise _PreparationDeadline
    grouped_nets = _with_sibling_groups(prepared_nets)
    # Projected coater legality is expensive and only matters when the detailed
    # router can introduce a Splitter. Reserved Tesla towers are different:
    # their elevated static geometry must be frozen with the prepared problem,
    # so power reservations retain exact machine-and-tower bans even when this
    # candidate's current net grouping cannot branch.
    output_source_belts = {
        net.src.belt_index
        for net in prepared_output_nets
        if net.src is not None
    }
    shared_boundary_output = any(
        net.src is not None and net.src.belt_index in output_source_belts
        for net in grouped_nets
    )
    junction_possible = not preparation_failures and (
        _junction_geometry_required(grouped_nets, canvas.buildings)
        or shared_boundary_output
    )
    if cancelled is not None and cancelled():
        raise _PreparationDeadline
    junction_frames = (
        _junction_projection_frames(
            finalize._cleanup_survivor_bounds(
                Placement(buildings=tuple(canvas.buildings)),
                cancelled=cancelled,
            ),
            capacity,
            policy,
            cancelled=cancelled,
        )
        if coater_list and junction_possible
        else ()
    )
    junction_ban = (
        _prepared_junction_ban(
            canvas.buildings,
            power_sites,
            cancelled=cancelled,
            cache=staged_static_cache,
        )
        if junction_possible or power_sites
        else frozenset()
    )
    projection_coaters = tuple(
        (index, building)
        for index, building in enumerate(canvas.buildings)
        if building.item_id == catalog.SPRAY_COATER_ID
    )
    junction_frame_bans = (
        _projected_coater_junction_bans_by_frame(
            projection_coaters,
            junction_frames,
            capacity,
            already_banned=set(junction_ban),
            splitter_index=len(canvas.buildings),
            cancelled=cancelled,
        )
        if projection_coaters and junction_frames
        else ()
    )
    if junction_frame_bans:
        universally_projected_ban = set(junction_frame_bans[0])
        for frame_ban in junction_frame_bans[1:]:
            universally_projected_ban.intersection_update(frame_ban)
        junction_ban = junction_ban | universally_projected_ban
    if cancelled is not None and cancelled():
        raise _PreparationDeadline

    return _PreparedRoutingProblem(
        # `PlacedBuilding` is frozen; the tuple is a fresh container and every
        # workspace copies the container again.  Deep-copying 300 frozen
        # dataclasses per candidate cost 0.38 s on `universe-matrix`.
        building_templates=tuple(canvas.buildings),
        blocked=tuple(sorted(canvas.blocked.items())),
        solid=frozenset(canvas.solid),
        reserved=tuple(sorted(canvas.reserved.items())),
        port_corridors=tuple(sorted(canvas.port_corridors.items())),
        keep_out=frozenset(canvas.keep_out),
        guard=frozenset(canvas.guard),
        nets=grouped_nets,
        external_output_nets=tuple(prepared_output_nets),
        core=core,
        route_bounds=route_bounds,
        limit=canvas.limit,
        power_sites=tuple(power_sites),
        sorters=sorters,
        coaters=coaters,
        coater_supply_ports=tuple(coater_list),
        direct_inserts=len(realized_direct),
        promised_direct=promised_direct,
        realized_direct=frozenset(realized_direct),
        ramped=canvas.ramped,
        sorter_tiers=canvas.sorter_tiers,
        world_taken=frozenset(canvas.world_taken),
        belt_ban=tuple(
            sorted((cell, frozenset(levels)) for cell, levels in canvas.belt_ban.items())
        ),
        junction_ban=junction_ban,
        junction_frame_bans=junction_frame_bans,
        preparation_failures=preparation_failures,
        stranded_ports=tuple(stranded_ports),
    )


class _BuildBudgetStage(Enum):
    """The phase whose shared deadline prevented a build attempt from finishing."""

    PREPARATION = "preparation"
    ROUTING = "routing"
    CERTIFICATION = "certification"
    FINALIZATION = "finalization"


@dataclass(frozen=True, slots=True)
class StrandedPort:
    """One lane head that could not obtain the belt approaches its feeds need.

    Carried out of preparation so a refusal can name the PORT rather than the
    nets that happened to end on it.  R2 §7 option 1 asked for exactly this: the
    old message named the packer, and the reader had to instrument
    `_reserve_port_access` to learn that `held=1 wants=2 options=1` on a
    `hydrogen` lane head was the whole story.
    """

    cell: tuple[int, int, int]
    item: str
    strip_label: str
    #: Corridors the matching actually reserved for this port.
    held: int
    #: Corridors it needed: one per role, plus one when the port is in ``twice``.
    wants: int
    #: Free 4-neighbours the port had to build a corridor from.  ``1`` is the
    #: signature of a middle lane head and is not a matching failure -- there is
    #: nothing to match.
    options: int


@dataclass(frozen=True, slots=True)
class PackAttempt:
    """Complete immutable evidence from one packed-and-routed assignment."""

    origins: tuple[tuple[int, int], ...]
    compact_width: int
    height: int
    outline: tuple[tuple[int, int], ...]
    routing: DetailedRouteResult
    budget_stage: _BuildBudgetStage | None
    static_access: tuple[NetFailure, ...]
    promised_direct: frozenset[DirectInsertId]
    realized_direct: frozenset[DirectInsertId]
    direct_candidates: _DirectCandidateSnapshot
    stranded_ports: tuple[StrandedPort, ...] = ()

    def __post_init__(self) -> None:
        if any(
            failure.kind is not RouteFailureKind.STATIC_ACCESS for failure in self.static_access
        ):
            raise ValueError("PackAttempt.static_access accepts only STATIC_ACCESS failures")
        if self.routing.status is DetailedRouteStatus.BUDGET:
            if self.budget_stage not in (
                _BuildBudgetStage.PREPARATION,
                _BuildBudgetStage.ROUTING,
            ):
                raise ValueError("a routing-budget attempt must name its routing stage")
        elif self.budget_stage in (
            _BuildBudgetStage.PREPARATION,
            _BuildBudgetStage.ROUTING,
        ):
            raise ValueError("only a routing-budget attempt may name a routing stage")
        if (
            self.budget_stage
            in (
                _BuildBudgetStage.CERTIFICATION,
                _BuildBudgetStage.FINALIZATION,
            )
            and self.routing.status is not DetailedRouteStatus.ROUTED
        ):
            raise ValueError("completion-stage evidence requires a fully routed attempt")
        if self.budget_stage is _BuildBudgetStage.PREPARATION and (
            self.routing.routed or self.routing.failures
        ):
            raise ValueError("preparation stopped before routing evidence existed")
        if not self.realized_direct <= self.promised_direct:
            raise ValueError("a realized direct insert must name a rewarded promise")


def _width_slack_cap(compact_width: int) -> int:
    """Return ``ceil(1.10 * compact_width)`` without floating-point drift."""
    if type(compact_width) is not int or compact_width <= 0:
        raise ValueError("compact width must be a positive integer")
    return (11 * compact_width + 9) // 10


def _seed_admission_preserves_best_band(
    seed: _Pack,
    minimum_width: int,
    envelope: finalize.BandPolicySearchEnvelope,
) -> bool:
    """Whether stopping at the warm seed cannot forfeit a narrower latitude band."""

    def primary_band(width: int) -> int | None:
        return min(
            (
                candidate.frame.primary_band
                for candidate in envelope.frame_candidates(width, seed.height)
            ),
            default=None,
        )

    seed_band = primary_band(seed.width)
    best_band = primary_band(minimum_width)
    return seed_band is not None and seed_band == best_band


def _proof_scoped_no_goods(
    attempt: PackAttempt,
    strips: list[Strip],
) -> tuple[
    tuple[_DirectRelationNoGood, ...],
    ExactPackNoGood | None,
    tuple[ClusterRelationNoGood, ...],
]:
    """Derive only relation or assignment exclusions proved by this attempt."""
    if not attempt.direct_candidates.matches(strips):
        raise ValueError("direct candidate evidence belongs to a different strip plan")
    direct_candidates = attempt.direct_candidates.candidates
    local: list[_DirectRelationNoGood] = []
    for direct in sorted(attempt.promised_direct - attempt.realized_direct):
        source = direct.source_strip
        destination = direct.destination_strip
        if not 0 <= source < len(attempt.origins) or not 0 <= destination < len(attempt.origins):
            continue
        candidate = direct_candidates.get((source, destination))
        source_origin = attempt.origins[source]
        destination_origin = attempt.origins[destination]
        delta_x = destination_origin[0] - source_origin[0]
        delta_y = destination_origin[1] - source_origin[1]
        structurally_impossible = (
            candidate is None
            or candidate.item != direct.item
            or candidate.cargo_domain is not direct.cargo_domain
            or delta_x not in candidate.origin_deltas
            or not (
                1 <= delta_y + candidate.cons_row - candidate.prod_row <= catalog.SORTER_MAX_REACH
            )
        )
        if structurally_impossible:
            local.append(
                _DirectRelationNoGood(
                    direct_id=direct,
                    delta_x=delta_x,
                    delta_y=delta_y,
                )
            )

    if local:
        return tuple(local), None, ()

    routing = attempt.routing
    if (
        not routing.exhaustive
        or routing.status is not DetailedRouteStatus.STRANDED
        or not routing.failures
        or any(failure.kind is RouteFailureKind.BUDGET for failure in routing.failures)
    ):
        return (), None, ()

    evidence = tuple(
        finalize.ProjectionFailure(
            check="route.exhaustive",
            buildings=(),
            detail=(
                f"{failure.kind.value}: net={failure.net_id!r}; "
                f"wall={failure.wall!r}; blockers={failure.blocking_nets!r}; "
                f"expansions={failure.expansions}"
            ),
            band=0,
        )
        for failure in routing.failures
    )
    # The relaxed cluster run's own proof, which the router could only hand
    # back through the routing report.  It is a REGION exclusion where the
    # exact no-good beside it is a point one, so it is built from the same
    # origins and stands or falls with the same attempt.
    report = routing.last_mile
    cluster_no_good = (
        None
        if report is None or not report.relation_strips
        else last_mile.relation_no_good(
            strips=report.relation_strips,
            origins=attempt.origins,
            outline=attempt.outline,
            height=attempt.height,
            evidence=report.relation_evidence,
        )
    )
    return (
        (),
        ExactPackNoGood(
            height=attempt.height,
            outline=attempt.outline,
            width=attempt.compact_width,
            origins=attempt.origins,
            evidence=evidence,
        ),
        () if cluster_no_good is None else (cluster_no_good,),
    )


def _attempt_feedback_state(
    attempt: PackAttempt,
    previous: FeedbackState | None,
) -> FeedbackState:
    """Accumulate immutable failed-net, blocker, and hot-wall evidence."""
    outline = (attempt.compact_width, attempt.height)
    state = FeedbackState.empty(outline) if previous is None else previous.for_outline(outline)
    return update_feedback(
        state,
        attempt.routing,
        origins=attempt.origins,
    )


def _feedback_retry_eligible(
    attempt: PackAttempt,
    feedback: FeedbackState,
) -> bool:
    """Whether this exact attempt earned one bounded evidence-driven retry."""
    routing = attempt.routing
    if (
        routing.exhaustive
        or routing.status is not DetailedRouteStatus.STRANDED
        or len(routing.failures) != 1
    ):
        return False
    failure = routing.failures[0]
    return failure.net_id in feedback.net_weight and failure.net_id in feedback.endpoint_offsets


@dataclass(slots=True)
class _BuildResult:
    placement: Placement | None
    routing: DetailedRouteResult
    budget_stage: _BuildBudgetStage | None
    towers: tuple[PlacedBuilding, ...]
    promised_direct: frozenset[DirectInsertId] = frozenset()
    realized_direct: frozenset[DirectInsertId] = frozenset()
    stranded_ports: tuple[StrandedPort, ...] = ()


def _build(
    spec: BuildSpec,
    strips: list[Strip],
    pack: _Pack,
    *,
    power: bool,
    route: bool,
    policy: BandPolicy,
    ramped: bool = False,
    deadline: float | None = None,
    budget: dict[str, int] | None = None,
    staged_static_cache: _StagedStaticCache | None = None,
) -> _BuildResult:
    """Prepare one pack, then emit it through the reusable detailed entry point."""
    cancelled = None if deadline is None else lambda: time.monotonic() >= deadline
    try:
        prepared = _prepare_routing_problem(
            spec,
            strips,
            pack,
            power=power,
            policy=policy,
            _reserve_ports=route,
            ramped=ramped,
            staged_static_cache=staged_static_cache,
            cancelled=cancelled,
        )
    except _PreparationDeadline, finalize.ProjectionCancelled:
        return _BuildResult(
            placement=None,
            routing=DetailedRouteResult(
                DetailedRouteStatus.BUDGET,
                (),
                (),
                0,
                0,
            ),
            towers=(),
            budget_stage=_BuildBudgetStage.PREPARATION,
        )
    if cancelled is not None and cancelled():
        return _BuildResult(
            placement=None,
            routing=DetailedRouteResult(
                DetailedRouteStatus.BUDGET,
                (),
                (),
                0,
                0,
            ),
            towers=(),
            budget_stage=_BuildBudgetStage.PREPARATION,
            stranded_ports=prepared.stranded_ports,
        )
    return _build_prepared(
        spec,
        strips,
        prepared,
        power=power,
        route=route,
        deadline=deadline,
        budget=budget,
    )


def _build_prepared(
    spec: BuildSpec,
    strips: list[Strip],
    prepared: _PreparedRoutingProblem,
    *,
    power: bool,
    route: bool,
    deadline: float | None = None,
    budget: dict[str, int] | None = None,
    prioritize_source_families: bool = False,
) -> _BuildResult:
    """Emit, route, and power one already-prepared immutable problem."""
    workspace = prepared.new_workspace()
    canvas = workspace.canvas
    belt_id = catalog.get_item_id(spec.belt_item_id) or 2001
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
    internal_source_belts = {
        net.source.belt for net in route_nets if net.src is not None
    }
    early_output_nets = [
        net
        for net in workspace.external_output_nets
        if net.source.belt not in internal_source_belts
    ]
    late_output_nets = [
        net for net in workspace.external_output_nets if net.source.belt in internal_source_belts
    ]

    empty_routing = DetailedRouteResult(
        DetailedRouteStatus.ROUTED,
        (),
        (),
        0,
        0,
        exhaustive=True,
    )
    external_routing = empty_routing
    early_output_routing = empty_routing
    internal_routing = empty_routing
    late_output_routing = empty_routing

    if route and prepared.preparation_failures:
        internal_routing = DetailedRouteResult(
            DetailedRouteStatus.STRANDED,
            (),
            prepared.preparation_failures,
            0,
            0,
        )
    else:
        # Inputs and pure outputs retain first claim on routing space. An
        # output lane that also feeds an internal consumer is continued only
        # after that internal graph exists, from its downstream surplus tail.
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
            early_output_routing = _route_external_outputs(
                canvas,
                early_output_nets,
                belt_id,
                belt_model,
                prepared.core,
                deadline,
                budget,
            )

    if route and route_nets and not prepared.preparation_failures:
        internal_routing = _route_all(
            canvas,
            route_nets,
            belt_id,
            belt_model,
            prepared.route_bounds,
            deadline,
            budget,
            prepared.power_sites if power else None,
            prepared.junction_frame_bans,
            prioritize_source_families=prioritize_source_families,
        )

    if (
        route
        and late_output_nets
        and not prepared.preparation_failures
        and external_routing.status is DetailedRouteStatus.ROUTED
        and early_output_routing.status is DetailedRouteStatus.ROUTED
        and internal_routing.status is DetailedRouteStatus.ROUTED
    ):
        late_output_routing = _route_external_outputs(
            canvas,
            _output_tail_nets(canvas, late_output_nets),
            belt_id,
            belt_model,
            prepared.core,
            deadline,
            budget,
        )

    failures = (
        external_routing.failures
        + early_output_routing.failures
        + internal_routing.failures
        + late_output_routing.failures
    )
    routing_status = (
        DetailedRouteStatus.BUDGET
        if any(
            result.status is DetailedRouteStatus.BUDGET
            for result in (
                external_routing,
                early_output_routing,
                internal_routing,
                late_output_routing,
            )
        )
        else (DetailedRouteStatus.STRANDED if failures else DetailedRouteStatus.ROUTED)
    )
    routing = DetailedRouteResult(
        status=routing_status,
        routed=(
            external_routing.routed
            + early_output_routing.routed
            + internal_routing.routed
            + late_output_routing.routed
        ),
        failures=failures,
        iterations=internal_routing.iterations,
        expansions=(
            external_routing.expansions
            + early_output_routing.expansions
            + internal_routing.expansions
            + late_output_routing.expansions
        ),
        exhaustive=(
            not prepared.preparation_failures
            and external_routing.exhaustive
            and early_output_routing.exhaustive
            and internal_routing.exhaustive
            and late_output_routing.exhaustive
        ),
        last_mile=combine_last_mile_reports(
            (
                external_routing.last_mile,
                early_output_routing.last_mile,
                internal_routing.last_mile,
                late_output_routing.last_mile,
            )
        ),
    )
    if routing.status is DetailedRouteStatus.BUDGET:
        return _BuildResult(
            placement=None,
            routing=routing,
            towers=(),
            budget_stage=_BuildBudgetStage.ROUTING,
            promised_direct=prepared.promised_direct,
            realized_direct=prepared.realized_direct,
            stranded_ports=prepared.stranded_ports,
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
            "belt_tiles": float(sum(1 for b in canvas.buildings if catalog.is_belt(b.item_id))),
            "direct_inserts": float(prepared.direct_inserts),
            # Combined across the four sub-routings, not just the interior
            # one: each of them runs a last-mile pass of its own, and reading
            # one makes every counter under-read by whatever the other three
            # did.  Identical today because only `_route_all` reports.
            **_last_mile_stats(routing.last_mile),
        },
    )
    placement = retier_belts(placement, spec)
    return _BuildResult(
        placement=placement,
        routing=routing,
        towers=towers,
        budget_stage=None,
        promised_direct=prepared.promised_direct,
        realized_direct=prepared.realized_direct,
        stranded_ports=prepared.stranded_ports,
    )


def _last_mile_stats(report: LastMileReport | None) -> PlacementStats:
    """Flatten the last-mile report so both strategies report it identically."""
    if report is None:
        return {
            "last_mile_invocations": 0.0,
            "last_mile_solved": 0.0,
            "last_mile_proved": 0.0,
            "last_mile_bounded": 0.0,
            "last_mile_commit_rejected": 0.0,
            "last_mile_restore_mismatch": 0.0,
            "last_mile_relation_skipped_siblings": 0.0,
            "last_mile_nodes": 0.0,
            "last_mile_expansions": 0.0,
            "last_mile_seconds": 0.0,
            "last_mile_relation_strips": 0.0,
        }
    return {
        "last_mile_invocations": float(report.invocations),
        "last_mile_solved": float(report.solved),
        "last_mile_proved": float(report.proved),
        "last_mile_bounded": float(report.bounded),
        "last_mile_commit_rejected": float(report.commit_rejected),
        "last_mile_restore_mismatch": float(report.restore_mismatch),
        "last_mile_relation_skipped_siblings": float(report.relation_skipped_siblings),
        "last_mile_nodes": float(report.nodes),
        "last_mile_expansions": float(report.expansions),
        "last_mile_seconds": report.seconds,
        "last_mile_relation_strips": float(len(report.relation_strips)),
    }


def _bridge(
    canvas: _Canvas,
    src: _Port,
    dst: _Port,
    rates: dict[str, Fraction],
    item: str,
    standing: list[colliders.Box],
    direct_id: DirectInsertId,
) -> DirectInsertId | None:
    """Span two lane ends with one sorter, replacing a whole belt route.

    Returns the exact promise only after emitting its sorter. ``None`` retains
    the unrealized promise as typed static-access evidence at the caller; it
    never restores the rewarded net as an ordinary belt route.

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
    is the one taken. When none does, the promise remains unrealized and the
    containing pack attempt fails with typed evidence.
    """
    if (
        src.cargo_domain is not CargoDomain.UNSPRAYED
        or dst.cargo_domain is not CargoDomain.UNSPRAYED
    ):
        return None
    span = dst.y - src.y
    if span < 1 or span > catalog.SORTER_MAX_REACH:
        return None

    tier, _ = _pick_sorter(rates.get(item, Fraction(1)), span, 1, canvas.sorter_tiers)
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
        return direct_id
    return None


def _coater_seats(
    canvas: _Canvas,
    port: _Port,
    *,
    west_channel: int,
) -> tuple[tuple[int, int], ...]:
    """Straight seats before the first possible machine pickup, in flow order.

    Sprayed input lanes start ``west_channel`` cells west of the strip.  The
    machine-facing lane begins at index ``west_channel``, so that tile and every
    later one may already feed a machine.  Seating there would let that consumer
    take unsprayed cargo before it reaches the Coater.  Index zero is the routing
    turn and the last tile has no successor; only the bounded interior channel
    offsets between them are candidates.
    """
    stop = min(len(port.tiles) - 1, west_channel)
    return tuple(
        (canvas.buildings[index].x, canvas.buildings[index].y) for index in port.tiles[1:stop]
    )


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
    seats = _coater_seats(
        canvas,
        port,
        west_channel=max(0, len(port.tiles) - 1),
    )
    return seats[0] if seats else None


def _reserve_staged_coater_belt_ban(
    canvas: _Canvas,
    staged: _StagedCoater,
    belt_model: int,
) -> None:
    """Price the committed Coater's exact collider for later belt routes."""
    cx, cy = staged.port.host_x, staged.port.host_y
    drop = (staged.port.x, staged.port.y)
    need = colliders.belt_crossing_height(staged.coater.model_index)
    span = (
        catalog.oriented_footprint(
            catalog.SPRAY_COATER_ID,
            staged.port.yaw,
        )[0]
        - 1
    ) // 2 + 1
    for dx in range(-span, span + 1):
        for dy in range(-span, span + 1):
            tile = (cx + dx, cy + dy)
            if tile == drop:
                continue
            for level in range(1, math.floor(need) + 1):
                probe = colliders.Placed(
                    belt_model,
                    *codec.tile_to_local_offset(
                        tile[0],
                        tile[1],
                        Fraction(level),
                        1,
                        1,
                    ),
                    0.0,
                )
                if colliders.belt_crossings(
                    [probe],
                    [staged.projected_pair[1]],
                    directly_over_only=True,
                ):
                    canvas.belt_ban.setdefault(tile, set()).add(level)


def _place_coaters(
    canvas: _Canvas,
    spec: BuildSpec,
    strips: list[Strip],
    ports: list[dict[str, _Port]],
    belt_id: int,
    belt_model: int,
    *,
    policy: BandPolicy,
    staged_static_cache: _StagedStaticCache | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> list[CoaterSupplyPort]:
    """Place one Spray Coater per sprayed input lane and its supply belt.

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
    * **Only ``REQUIRES_SPRAY`` lanes are coated.**  The destination-derived
      cargo domain is authoritative even for uniform sprayed demand; the
      item-level split set merely records coexistence.

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
    if staged_static_cache is None:
        staged_static_cache = _StagedStaticCache()
    if cancelled is not None and cancelled():
        raise _PreparationDeadline
    coater = catalog.building(catalog.SPRAY_COATER_ID)
    wanted = set(spec.spray_lanes)
    proliferator_item = _proliferator_item(spec)
    seen: set[str] = set()
    staged: list[_StagedCoater] = []
    staged_hosts: set[int] = set()
    staged_supply_cells: set[Cell] = set()
    prospective = list(canvas.buildings)
    obstacle_index = _ProjectedObstacleIndex.build(
        tuple(enumerate(prospective)),
        cancelled=cancelled,
    )
    splitter_buildings = tuple(
        (index, building)
        for index, building in enumerate(canvas.buildings)
        if building.item_id == catalog.SPLITTER_ID
    )
    projected_capacity = (
        canvas.limit or _grow(_core_bounds(canvas), _ENTRY_RING) if splitter_buildings else None
    )
    static_capacity = canvas.limit or _grow(_core_bounds(canvas), _ENTRY_RING)
    cleanup_prefix = finalize._CleanupSurvivorGraph(
        Placement(buildings=tuple(prospective)),
        cancelled=cancelled,
        _operations=staged_static_cache.cleanup_operations,
    )
    cleanup_bounds = cleanup_prefix.snapshot_bounds()

    belt_at: dict[tuple[int, int, int], int] = {
        (building.x, building.y, int(building.z)): index
        for index, building in enumerate(canvas.buildings)
        if catalog.is_belt(building.item_id) and building.z.denominator == 1
    }

    for strip_index, (strip, in_ports) in enumerate(zip(strips, ports, strict=True)):
        if cancelled is not None and cancelled():
            raise _PreparationDeadline
        for item in strip.in_lanes:
            if cancelled is not None and cancelled():
                raise _PreparationDeadline
            if strip.cargo_domain is not CargoDomain.REQUIRES_SPRAY:
                continue
            port = in_ports.get(item)
            if port is None:
                raise _Unseatable(
                    f"the strip feeding {item} has no input port for it, so its "
                    f"Spray Coater has no lane to ride"
                )
            if port.cargo_domain is not CargoDomain.REQUIRES_SPRAY:
                raise _Unseatable(
                    f"the {item} lane is marked {port.cargo_domain.value}, so "
                    "a Spray Coater cannot be placed on it"
                )
            seats = _coater_seats(
                canvas,
                port,
                west_channel=strip.west_channel,
            )
            if not seats:
                raise _Unseatable(
                    f"the {item} lane at ({port.x}, {port.y}) is "
                    f"{len(port.tiles)} tile(s) long, and a coater needs a tile "
                    f"with a lane tile on both sides of it to ride straight"
                )
            failure_reasons: list[str] = []
            projected_failures: list[
                tuple[
                    finalize.ProjectionFailure,
                    int | None,
                    StagedStaticClearanceKey | None,
                    _ExactRetryEvidence | None,
                ]
            ] = []
            same_strip_static_seats = 0
            seated = False
            for cx, cy in seats:
                if cancelled is not None and cancelled():
                    raise _PreparationDeadline
                host_z = port.z
                host = belt_at.get((cx, cy, host_z))
                yaw = Facing.EAST.value
                drop_cell = slots.addon_supply_cell(
                    catalog.SPRAY_COATER_ID,
                    x=cx,
                    y=cy,
                    z=Fraction(host_z),
                    yaw=yaw,
                    area=1,
                )
                approach_dx = drop_cell[0] - cx
                approach_dy = drop_cell[1] - cy
                if abs(approach_dx) + abs(approach_dy) != 1:
                    raise AssertionError("a Coater supply drop must be cardinally adjacent")
                approach_cell = (
                    drop_cell[0] + approach_dx,
                    drop_cell[1] + approach_dy,
                    drop_cell[2],
                )
                if host is None:
                    failure_reasons.append(
                        f"the {item} lane's seat ({cx}, {cy}) carries no belt at "
                        f"level {host_z}, so there is nothing for a coater to ride"
                    )
                    continue
                if host in staged_hosts:
                    seated = True
                    break

                proposed_coater = PlacedBuilding(
                    item_id=catalog.SPRAY_COATER_ID,
                    model_index=coater.model_index,
                    x=cx,
                    y=cy,
                    z=Fraction(host_z),
                    width=1,
                    height=1,
                    yaw=yaw,
                    owner_strip=strip_index,
                )
                collider_hits = _coater_keepout_hits(
                    prospective,
                    proposed_coater,
                )
                if collider_hits:
                    if all(
                        prospective[index].owner_strip == strip_index for index in collider_hits
                    ):
                        same_strip_static_seats += 1
                    obstacles = ", ".join(
                        f"{catalog.building(prospective[index].item_id).name} "
                        f"at ({prospective[index].x}, "
                        f"{prospective[index].y}, z={prospective[index].z})"
                        for index in collider_hits
                    )
                    failure_reasons.append(
                        f"the {item} coater at ({cx}, {cy}, z={host_z}) has a "
                        f"full-body keepout intersecting {obstacles}"
                    )
                    continue
                within_capacity = all(
                    static_capacity[0] <= cell[0] <= static_capacity[2]
                    and static_capacity[1] <= cell[1] <= static_capacity[3]
                    for cell in (drop_cell, approach_cell)
                )
                if (
                    not within_capacity
                    or drop_cell in staged_supply_cells
                    or approach_cell in staged_supply_cells
                    or not canvas.free(drop_cell)
                    or not canvas.free(approach_cell)
                ):
                    failure_reasons.append(
                        f"the {item} coater at ({cx}, {cy}) cannot have its "
                        f"straight proliferator drop at {drop_cell} through "
                        f"approach {approach_cell}: one of those cells is taken"
                    )
                    continue

                approach_index = len(prospective)
                supply_index = approach_index + 1
                coater_index = supply_index + 1
                approach = PlacedBuilding(
                    item_id=belt_id,
                    model_index=belt_model,
                    x=approach_cell[0],
                    y=approach_cell[1],
                    z=Fraction(approach_cell[2]),
                    width=1,
                    height=1,
                    output_obj=supply_index,
                    carries_item=proliferator_item,
                    owner_strip=strip_index,
                )
                supply = PlacedBuilding(
                    item_id=belt_id,
                    model_index=belt_model,
                    x=drop_cell[0],
                    y=drop_cell[1],
                    z=Fraction(drop_cell[2]),
                    width=1,
                    height=1,
                    carries_item=proliferator_item,
                    owner_strip=strip_index,
                )
                # The approach/drop link is permanent geometry: it fixes the
                # line the projected addon validator measures after routing.
                # Advance the exact survivor prefix with the same connected
                # terminal the finalizer will receive.
                candidate_cleanup, candidate_bounds = cleanup_prefix.extended_snapshot(
                    (approach, supply, proposed_coater),
                    cleanup_bounds,
                    cancelled=cancelled,
                )
                static_frames = _cached_junction_projection_frames(
                    staged_static_cache,
                    candidate_bounds,
                    static_capacity,
                    policy,
                    cancelled=cancelled,
                )
                projected_failure = None
                potential_peers = _prospective_static_broad_phase(
                    obstacle_index,
                    proposed_coater,
                    static_frames,
                    staged_static_cache,
                    cancelled=cancelled,
                )
                if potential_peers:
                    broad_phase_peers = frozenset(potential_peers)
                    potential_peers = tuple(
                        index
                        for index, _peer in _staged_static_projection_peers(
                            prospective,
                            proposed_coater,
                            owner_strip=strip_index,
                            policy=policy,
                        )
                        if index in broad_phase_peers
                    )
                if potential_peers:
                    projected_failure = _prospective_static_failure(
                        (
                            *((index, prospective[index]) for index in potential_peers),
                            (coater_index, proposed_coater),
                        ),
                        static_frames,
                        candidate_index=coater_index,
                        cache=staged_static_cache,
                        cancelled=cancelled,
                    )
                if projected_failure is not None:
                    peer_index = next(
                        (index for index in projected_failure.buildings if index != coater_index),
                        None,
                    )
                    peer = (
                        prospective[peer_index]
                        if peer_index is not None and 0 <= peer_index < len(prospective)
                        else None
                    )
                    peer_owner = peer.owner_strip if peer is not None else None
                    relation = (
                        _staged_static_clearance_key(peer, proposed_coater)
                        if peer is not None and peer_owner == strip_index
                        else None
                    )
                    projected_failures.append(
                        (
                            projected_failure,
                            peer_owner,
                            relation,
                            _exact_retry_evidence(
                                "seating",
                                projected_failure,
                                dict(
                                    enumerate(
                                        (
                                            *prospective,
                                            approach,
                                            supply,
                                            proposed_coater,
                                        )
                                    )
                                ),
                            ),
                        )
                    )
                    if peer_owner == strip_index:
                        same_strip_static_seats += 1
                    failure_reasons.append(
                        f"the {item} coater at ({cx}, {cy}, z={host_z}) enters "
                        "a projected static collider"
                    )
                    continue

                prepared_port = CoaterSupplyPort(
                    coater=coater_index,
                    host_belt=host,
                    approach_belt=approach_index,
                    supply_belt=supply_index,
                    item=item,
                    yaw=yaw,
                    host_x=cx,
                    host_y=cy,
                    host_z=host_z,
                    x=drop_cell[0],
                    y=drop_cell[1],
                    z=drop_cell[2],
                )
                staged_candidate = _StagedCoater(
                    approach=approach,
                    supply=supply,
                    coater=proposed_coater,
                    projected_pair=(
                        coater_index,
                        _collision_pose(proposed_coater),
                    ),
                    port=prepared_port,
                )
                if not static_frames:
                    raise _Unseatable("the coater candidate has no viable DSP frame")
                addon_failure: finalize.ProjectionFailure | None = None
                for frame in static_frames:
                    context_key = _projected_coater_supply_context_key(
                        staged_candidate,
                        prospective[host],
                        frame,
                    )
                    if context_key in staged_static_cache.coater_supply_failures:
                        frame_failure = staged_static_cache.coater_supply_failures[context_key]
                    else:
                        frame_failure = _projected_coater_supply_frame_failure(
                            staged_candidate,
                            prospective[host],
                            frame,
                            cancelled=cancelled,
                        )
                        staged_static_cache.coater_supply_failures[context_key] = frame_failure
                    if frame_failure is None:
                        addon_failure = None
                        break
                    if addon_failure is None:
                        addon_failure = frame_failure
                if addon_failure is not None:
                    projected_failures.append(
                        (
                            addon_failure,
                            None,
                            None,
                            _exact_retry_evidence(
                                "seating",
                                addon_failure,
                                dict(
                                    enumerate(
                                        (
                                            *prospective,
                                            approach,
                                            supply,
                                            proposed_coater,
                                        )
                                    )
                                ),
                            ),
                        )
                    )
                    failure_reasons.append(
                        f"the {item} coater at ({cx}, {cy}, z={host_z}) loses "
                        "a projected supply belt"
                    )
                    continue
                staged.append(staged_candidate)
                prospective.extend((approach, supply, proposed_coater))
                obstacle_index.add(coater_index, proposed_coater)
                cleanup_bounds = candidate_bounds
                cleanup_prefix = candidate_cleanup
                staged_hosts.add(host)
                staged_supply_cells.update((approach_cell, drop_cell))
                seated = True
                break

            if not seated:
                first_failure = projected_failures[0][0] if projected_failures else None
                first_relation = projected_failures[0][2] if projected_failures else None
                first_exact_retry_evidence = (
                    projected_failures[0][3] if projected_failures else None
                )
                all_projected = len(projected_failures) == len(seats)
                same_strip = first_failure is not None and same_strip_static_seats == len(seats)
                clearance_requirement = (
                    _staged_static_clearance_requirement(
                        strip,
                        strip_index,
                        first_failure,
                        first_relation,
                    )
                    if (same_strip and first_failure is not None and first_relation is not None)
                    else None
                )
                raise _Unseatable(
                    failure_reasons[0],
                    failure=first_failure,
                    clearance_requirement=clearance_requirement,
                    exact_retry_evidence=(
                        first_exact_retry_evidence if all_projected and not same_strip else None
                    ),
                )
            seen.add(item)

    # The loop walks only lanes that exist. Refuse a requested sprayed item that
    # no strip carries before committing any of the successfully staged lanes.
    missing = wanted - seen
    if missing:
        raise _Unseatable(
            f"the spec sprays {sorted(missing)}, and no strip carries "
            f"{'them' if len(missing) > 1 else 'it'} on an input lane, so no "
            f"Spray Coater was placed for {'any' if len(missing) > 1 else 'it'}"
        )

    # Every provisional seat was checked against the frame extent that existed
    # when it was chosen. Later coaters can enlarge the cleanup-survivor bounds,
    # changing the finalizer's latitude anchors and invalidating an earlier
    # addon's host or supply relation. Recheck the complete staged set against
    # the one final extent before any candidate is committed to the canvas.
    final_frames = _cached_junction_projection_frames(
        staged_static_cache,
        cleanup_bounds,
        static_capacity,
        policy,
        cancelled=cancelled,
    )
    addon_failure: finalize.ProjectionFailure | None = None
    failed_candidate: _StagedCoater | None = None
    viable_addon_frames: list[_JunctionProjectionFrame] = []
    for frame in final_frames:
        if cancelled is not None and cancelled():
            raise _PreparationDeadline
        frame_failure: finalize.ProjectionFailure | None = None
        frame_failed_candidate: _StagedCoater | None = None
        for candidate in staged:
            host = prospective[candidate.port.host_belt]
            context_key = _projected_coater_supply_context_key(
                candidate,
                host,
                frame,
            )
            if context_key in staged_static_cache.coater_supply_failures:
                frame_failure = staged_static_cache.coater_supply_failures[context_key]
            else:
                frame_failure = _projected_coater_supply_frame_failure(
                    candidate,
                    host,
                    frame,
                    cancelled=cancelled,
                )
                staged_static_cache.coater_supply_failures[context_key] = frame_failure
            if frame_failure is not None:
                frame_failed_candidate = candidate
                break
        if frame_failure is None:
            viable_addon_frames.append(frame)
            addon_failure = None
            failed_candidate = None
            if projected_capacity is None:
                break
        elif addon_failure is None:
            addon_failure = frame_failure
            failed_candidate = frame_failed_candidate
    if not viable_addon_frames and addon_failure is not None:
        candidate = failed_candidate or staged[0]
        raise _Unseatable(
            f"the {candidate.port.item} coater at "
            f"({candidate.port.host_x}, {candidate.port.host_y}, "
            f"z={candidate.port.host_z}) loses a projected supply belt after "
            "the complete coater set fixes the final frame",
            failure=addon_failure,
            exact_retry_evidence=_exact_retry_evidence(
                "seating",
                addon_failure,
                dict(enumerate(prospective)),
            ),
        )

    if projected_capacity is not None:
        splitter_failure: finalize.ProjectionFailure | None = None
        failed_splitter_candidate: _StagedCoater | None = None
        viable_splitter_frame = False
        for frame in viable_addon_frames:
            if cancelled is not None and cancelled():
                raise _PreparationDeadline
            framed_staged_pairs = tuple(
                (
                    candidate.port.coater,
                    _collision_pose(
                        finalize.materialize_frame_building(
                            candidate.coater,
                            bounds=frame.bounds,
                            candidate=frame.candidate,
                        )
                    ),
                )
                for candidate in staged
            )
            framed_splitters = tuple(
                (
                    index,
                    _collision_pose(
                        finalize.materialize_frame_building(
                            building,
                            bounds=frame.bounds,
                            candidate=frame.candidate,
                        )
                    ),
                )
                for index, building in splitter_buildings
            )
            try:
                splitter_candidates_by_projection = tuple(
                    finalize._projected_coater_splitter_candidates(
                        framed_staged_pairs,
                        framed_splitters,
                        projection,
                        cancelled=cancelled,
                    )
                    for projection in frame.projections
                )
            except finalize.ProjectionCancelled:
                raise _PreparationDeadline from None
            frame_failure: finalize.ProjectionFailure | None = None
            for candidate_position, candidate in enumerate(staged):
                if cancelled is not None and cancelled():
                    raise _PreparationDeadline
                for projection, candidates in zip(
                    frame.projections,
                    splitter_candidates_by_projection,
                    strict=True,
                ):
                    if cancelled is not None and cancelled():
                        raise _PreparationDeadline
                    for splitter in candidates[candidate_position]:
                        if cancelled is not None and cancelled():
                            raise _PreparationDeadline
                        frame_failure = finalize.projected_coater_splitter_failure(
                            framed_staged_pairs[candidate_position],
                            splitter,
                            projection,
                            cancelled=cancelled,
                        )
                        if frame_failure is not None:
                            break
                    if frame_failure is not None:
                        break
                if frame_failure is not None:
                    if splitter_failure is None:
                        splitter_failure = frame_failure
                        failed_splitter_candidate = candidate
                    break
            if frame_failure is None:
                viable_splitter_frame = True
                break
        if not viable_splitter_frame and splitter_failure is not None:
            candidate = failed_splitter_candidate or staged[0]
            raise _Unseatable(
                f"the {candidate.port.item} coater at "
                f"({candidate.port.host_x}, {candidate.port.host_y}, "
                f"z={candidate.port.host_z}) enters a Splitter projected "
                "lateral keepout in every viable frame",
                failure=splitter_failure,
            )

        # This is the same fixed capacity `_prepare_routing_problem` establishes
        # after Coater placement. Keep it local until every staged pair passes so
        # a refusal leaves an initially unbounded canvas unchanged.
        if canvas.limit is None:
            canvas.limit = projected_capacity

    out: list[CoaterSupplyPort] = []
    for candidate in staged:
        approach_index = canvas.add(
            candidate.approach,
            level=candidate.port.z,
        )
        assert approach_index == candidate.port.approach_belt
        supply_index = canvas.add(
            candidate.supply,
            level=candidate.port.z,
        )
        assert supply_index == candidate.port.supply_belt
        coater_index = len(canvas.buildings)
        assert coater_index == candidate.port.coater
        canvas.buildings.append(candidate.coater)
        _reserve_staged_coater_belt_ban(canvas, candidate, belt_model)
        out.append(candidate.port)

    # Every drop is exempt from every overlapping Coater ban: it is a required
    # positional addon connection whichever Coater owns the ban.
    for committed in out:
        canvas.belt_ban.pop((committed.x, committed.y), None)
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


def _extend_core_for_unique_proliferator_roots(
    core: tuple[int, int, int, int],
    *,
    coater_count: int,
    boundary_core_height: int | None,
) -> tuple[int, int, int, int]:
    """Spend legal empty latitude only when it removes shared trunk roots."""
    if coater_count < 2 or boundary_core_height is None:
        return core
    current_height = core[3] - core[1] + 1
    roots_per_side = (coater_count + 1) // 2
    required_height = 4 * (roots_per_side - 1) + 1
    if current_height >= required_height or current_height >= boundary_core_height:
        return core
    target_height = min(required_height, boundary_core_height)
    return (core[0], core[1], core[2], core[1] + target_height - 1)


def _proliferator_supply_tree(
    canvas: _Canvas,
    entry: _Port,
    coaters: list[CoaterSupplyPort],
    item: str,
    *,
    belt_id: int,
    belt_model: int,
    core: tuple[int, int, int, int],
) -> list[_Net]:
    """Feed every coater from one externally reachable belt tree.

    A coater supply drop is one-ended in several legal projected frames. The
    drop therefore has one permanent outward approach belt whose link fixes the
    line used by projected addon certification. Detailed routing terminates on
    that approach belt; it never chooses the drop's predecessor direction and
    never turns the drop into a pass-through node.

    Two ground-level trunks descend the west and east entry rings from one
    north-west input. Balanced groups share spaced trunk roots. Detailed routing
    grows leaf branches from those roots and emits Splitters at selected taps.
    Long cross-block supply paths are avoided without asking A* to rediscover or
    independently route the trunk.
    """
    if not coaters:
        return []

    west_x = core[0] - _ENTRY_RING
    east_x = core[2] + _ENTRY_RING
    trunk_top = core[1] - _ENTRY_RING
    trunk_bottom = core[3] + _ENTRY_RING
    junction_y = trunk_top + 1
    first_root = junction_y + 4
    last_root = trunk_bottom - 1
    root_capacity = max(1, (last_root - first_root) // 4 + 1)

    def supply_side(coater: CoaterSupplyPort) -> str:
        if coater.x < coater.host_x:
            return "west"
        if coater.x > coater.host_x:
            return "east"
        return "west" if coater.x - core[0] <= core[2] - coater.x else "east"

    terminal_roots = list(coaters)
    west = [coater for coater in terminal_roots if supply_side(coater) == "west"]
    east = [coater for coater in terminal_roots if supply_side(coater) == "east"]
    # Side choice is a distance preference, not a hard ownership boundary.
    # Spend spare roots on the opposite trunk before making two leaves share a
    # source: shared roots require commit-time Splitter dependencies, while a
    # cross-block leaf is longer but remains an ordinary independent route.
    while len(west) > root_capacity and len(east) < root_capacity:
        moved = max(west, key=lambda coater: (coater.x, -coater.y))
        west.remove(moved)
        east.append(moved)
    while len(east) > root_capacity and len(west) < root_capacity:
        moved = min(east, key=lambda coater: (coater.x, coater.y))
        east.remove(moved)
        west.append(moved)
    side_coaters = {side: members for side, members in (("west", west), ("east", east)) if members}
    root_target = min(
        sum(min(len(members), root_capacity) for members in side_coaters.values()),
        len(terminal_roots),
    )
    root_counts = {side: 1 for side in side_coaters}
    while sum(root_counts.values()) < root_target:
        choices = [
            side
            for side, members in side_coaters.items()
            if root_counts[side] < min(len(members), root_capacity)
        ]
        if not choices:
            break
        selected = max(
            choices,
            key=lambda side: (
                len(side_coaters[side]) / root_counts[side],
                side == "west",
            ),
        )
        root_counts[selected] += 1

    groups_by_side: dict[str, list[list[CoaterSupplyPort]]] = {}
    rows_by_side: dict[str, list[int]] = {}
    for side, members in side_coaters.items():
        ordered = sorted(
            members,
            key=lambda coater: (
                coater.y,
                coater.x,
                coater.z,
                coater.supply_belt,
            ),
        )
        count = root_counts[side]
        quotient, remainder = divmod(len(ordered), count)
        groups: list[list[CoaterSupplyPort]] = []
        start = 0
        for ordinal in range(count):
            size = quotient + (ordinal < remainder)
            groups.append(ordered[start : start + size])
            start += size
        rows: list[int] = []
        for ordinal, group in enumerate(groups):
            desired = group[len(group) // 2].y
            lower = first_root + 4 * ordinal
            upper = last_root - 4 * (count - ordinal - 1)
            row = min(max(desired, lower), upper)
            if rows:
                row = max(row, rows[-1] + 4)
            rows.append(row)
        groups_by_side[side] = groups
        rows_by_side[side] = rows

    west_end = rows_by_side["west"][-1] + 1 if "west" in rows_by_side else junction_y + 1
    west_cells = tuple((west_x, y, 0) for y in range(trunk_top + 1, west_end + 1))
    east_cells: tuple[Cell, ...] = ()
    if "east" in rows_by_side:
        east_end = rows_by_side["east"][-1] + 1
        east_cells = (
            *((x, junction_y, 0) for x in range(west_x + 1, east_x + 1)),
            *((east_x, y, 0) for y in range(junction_y + 1, east_end + 1)),
        )
    all_cells = (*west_cells, *east_cells)
    if any(not canvas.free(cell) for cell in all_cells):
        raise _Unseatable("the reserved proliferator perimeter trunk is occupied")

    trunk_indices: dict[tuple[str, int], int] = {}
    previous = entry.belt
    west_indices: dict[int, int] = {}
    for x, y, level in west_cells:
        index = canvas.add(
            PlacedBuilding(
                item_id=belt_id,
                model_index=belt_model,
                x=x,
                y=y,
                width=1,
                height=1,
                carries_item=item,
            ),
            level=level,
        )
        canvas.buildings[previous] = _relink(
            canvas.buildings[previous],
            output_obj=index,
        )
        previous = index
        west_indices[y] = index
        trunk_indices["west", y] = index

    if east_cells:
        east_indices: list[int] = []
        for x, y, level in east_cells:
            index = canvas.add(
                PlacedBuilding(
                    item_id=belt_id,
                    model_index=belt_model,
                    x=x,
                    y=y,
                    width=1,
                    height=1,
                    carries_item=item,
                ),
                level=level,
            )
            if east_indices:
                prior = east_indices[-1]
                canvas.buildings[prior] = _relink(
                    canvas.buildings[prior],
                    output_obj=index,
                )
            east_indices.append(index)
            if x == east_x:
                trunk_indices["east", y] = index
        trunk_run = {
            (entry.x, entry.y, entry.z),
            *west_cells,
            *east_cells,
        }
        if not _tap_source(
            canvas,
            west_indices[junction_y],
            east_indices[0],
            belt_id,
            belt_model,
            trunk_run,
        ):
            raise _Unseatable("the proliferator perimeter trunk cannot branch")

    # External inputs route before these leaf nets. Reserve each future
    # Splitter's exact keep-out now or an unrelated entry path can occupy a
    # neighbouring cell and make the root lose every start at routing time.
    trunk_run = {(entry.x, entry.y, entry.z), *all_cells}
    assert canvas.limit is not None
    limit_x0, limit_y0, limit_x1, limit_y1 = canvas.limit
    for side, rows in rows_by_side.items():
        trunk_x = west_x if side == "west" else east_x
        branch_dx = 1 if side == "west" else -1
        for row in rows:
            excused = trunk_run | {(trunk_x + branch_dx, row, 0)}
            for stack_member in _splitter_stack_geometry(trunk_x, row, 0):
                for cell in junction.keepout_cells(
                    trunk_x,
                    row,
                    int(stack_member.z),
                    model_index=stack_member.model_index,
                    yaw=stack_member.yaw,
                ):
                    if cell in excused:
                        continue
                    if limit_x0 <= cell[0] <= limit_x1 and limit_y0 <= cell[1] <= limit_y1:
                        canvas.guard.add(cell)

    nets: list[_Net] = []
    for side, groups in groups_by_side.items():
        trunk_x = west_x if side == "west" else east_x
        for row, group in zip(rows_by_side[side], groups, strict=True):
            source = _Port(
                trunk_indices[side, row],
                trunk_x,
                row,
                trunk_x,
                trunk_x,
                cargo_domain=CargoDomain.UNSPRAYED,
            )
            for coater in group:
                approach = canvas.buildings[coater.approach_belt]
                if approach.z.denominator != 1:
                    raise AssertionError("a Coater approach belt must use an integer level")
                nets.append(
                    _Net(
                        src=source,
                        dst=_Port(
                            coater.approach_belt,
                            approach.x,
                            approach.y,
                            approach.x,
                            approach.x,
                            z=int(approach.z),
                            cargo_domain=CargoDomain.UNSPRAYED,
                        ),
                        item=item,
                        cargo_domain=CargoDomain.UNSPRAYED,
                    )
                )
    return nets


def _place_proliferator_entry(
    canvas: _Canvas,
    item: str,
    belt_id: int,
    belt_model: int,
    core: tuple[int, int, int, int],
) -> _Port | None:
    """Place the externally reachable root of the proliferator supply tree.

    It sits on the north-west corner of the reserved entry ring. Nothing else
    can be placed farther out, and its connected trunk continues south on that
    same ring, so the one zero-predecessor belt remains reachable from outside
    the finished block.
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
    return _Port(
        idx,
        x,
        y,
        x,
        x,
        cargo_domain=CargoDomain.UNSPRAYED,
    )


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
    src_lanes: dict[tuple[str, str, str, CargoDomain], int] = defaultdict(int)
    src_tiles: dict[tuple[str, str, str, CargoDomain], int] = {}
    sink_lanes: dict[tuple[str, str, CargoDomain], int] = defaultdict(int)
    for s in strips:
        for item, dest, cargo_domain in s.out_lanes:
            for d in _dests(dest):
                key = (s.group_key, item, d, cargo_domain)
                src_lanes[key] += 1
                src_tiles[key] = min(src_tiles.get(key, s.width), s.width)
        for item in s.in_lanes:
            sink_lanes[s.group_key, item, s.cargo_domain] += 1

    out: list[str] = []
    for (src_key, item, dest, cargo_domain), n_src in sorted(
        src_lanes.items(),
        key=lambda entry: (
            entry[0][0],
            entry[0][1],
            entry[0][2],
            entry[0][3].value,
        ),
    ):
        n_sink = sink_lanes.get((dest, item, cargo_domain), 0)
        if n_sink <= n_src:
            continue
        # Taps land on the narrowest lane of the group, so that is the one that
        # can run out. Ceiling division: the reuse is spread round-robin.
        per_lane = -(-n_sink // n_src)
        tiles = src_tiles[src_key, item, dest, cargo_domain]
        if per_lane > tiles:
            out.append(
                f"{item}: {src_key} lane is {tiles} tile(s) wide but must tap "
                f"{per_lane} consumer lane(s) of {dest}"
            )
    return out


def _drainable_by_port(strip: Strip) -> bool:
    """Can every output lane claim a distinct port facing the lane band?

    The raw, unfloored count: unlike the planner's `_logical_strip_plans`,
    which floors a zero to "try one lane anyway" because it needs a strip to
    exist before anything can be refused, this is the refusal itself, so a
    true zero must stay zero -- flooring it would make `0 <= 0` read True.
    """
    capacity = slots.drain_dock_count(strip.item_id, strip.yaw)
    return bool(strip.out_lanes) and len(strip.out_lanes) <= capacity


def _feedable_by_port(strip: Strip) -> bool:
    """Can each input lane branch through a distinct east-facing prefab port?"""
    probe = slots.probe_building(strip.item_id, strip.yaw)
    docks = slots.port_docks(probe).values()
    capacity = sum(
        dock.facing is Facing.EAST and _port_approach_offset(probe, dock, strip.pw) is not None
        for dock in docks
    )
    lanes = strip.in_above + strip.in_below
    return (
        bool(lanes)
        and all(len(lane) == 1 for lane in lanes)
        and len(lanes) <= capacity
        and (not strip.out_lanes or _drainable_by_port(strip))
    )


def _machines_without_poses(strips: list[Strip]) -> list[str]:
    """Lanes seated where no sorter of any tier can join them to their machine.

    Three shapes, and they are worth telling apart in the message because they
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

    THE LANES HAVE POSES BUT NO COMPLETE DISTINCT-SLOT ASSIGNMENT.  Variant
    generation matches every logical item across all lane rows before accepting
    a pose.  If that matching fails, no physical variant exists: falling back to
    each row's first attachment would put multiple sorters in one machine slot,
    and the game would evict all but the last connection written there.

    THE MESSAGE NEVER QUOTES A DISTANCE, because it has none to quote.
    ``sorter_span`` reads the slot table through ``slots.attachment``, which has
    already rejected anything outside ``1..SORTER_MAX_REACH``, so the only
    failing value it can return is 0 -- meaning nothing anchorable was found at
    all, not a measured four tiles.  Printing that 0 as a distance is what made
    the ``organic-crystal`` refusal read "0 tile(s) ... past the 3-tile reach".
    ``_side_lane_caps`` now keeps seating inside what the poses reach, so this
    is a guard against a future seating bug rather than a routine outcome.

    A sorterless belt-port host is not a refusal when every lane can claim an
    authoritative dock.  Output docks merge into their lane; input docks branch
    from their shared lane through explicit splitters, because a belt tile has
    only one output link.

    Returns one description per distinct offending building and combined lane
    role, empty when every lane in the plan can be joined to its machine.
    """
    reach = catalog.SORTER_MAX_REACH
    seen: set[tuple[int, str, int]] = set()
    out: list[str] = []
    for s in strips:
        if s.port_dock_plan and not s.in_lanes and len(s.port_dock_plan) == len(s.out_lanes):
            continue
        if s.lane_plan is None:
            if s.flank_outputs:
                continue
            building = catalog.building(s.item_id)
            if s.takes_belt_ports and not s.in_lanes and s.out_lanes and _drainable_by_port(s):
                continue
            if s.takes_belt_ports and s.in_lanes and _feedable_by_port(s):
                continue
            kinds = tuple(
                kind
                for kind, present in (
                    ("ingredient", bool(s.in_lanes)),
                    ("output", bool(s.out_lanes)),
                )
                if present
            )
            if not kinds:
                continue
            kind_phrase = " and ".join(kinds)
            key = (s.item_id, kind_phrase, 0)
            if key in seen:
                continue
            seen.add(key)
            if s.takes_belt_ports and s.in_lanes and s.out_lanes and not _drainable_by_port(s):
                out.append(
                    f"{building.name} ({s.recipe_id}): its "
                    f"{len({(i, d) for i, _dest, d in s.out_lanes})} distinct output "
                    f"cargo(es) cannot claim distinct docks facing the lane band "
                    f"from its {len(building.port_poses)} belt port(s)"
                )
            elif s.takes_belt_ports and s.in_lanes:
                out.append(
                    f"{building.name} ({s.recipe_id}): its ingredient lanes cannot "
                    f"claim distinct east-facing input docks from its "
                    f"{len(building.port_poses)} belt port(s) while preserving one "
                    "legal splitter-backed fan-out per machine"
                )
            elif s.takes_belt_ports:
                out.append(
                    f"{building.name} ({s.recipe_id}): none of its "
                    f"{len(building.port_poses)} belt port(s) faces the output "
                    "lane below the machine band"
                )
            else:
                out.append(
                    f"{building.name} ({s.recipe_id}): its {kind_phrase} lanes "
                    "cannot be assigned distinct legal sorter slots across all "
                    "lanes; a machine slot holds one connection"
                )
            continue
        rows: list[tuple[int, str]] = [(j, "ingredient") for j in range(len(s.in_above))]
        rows += [(s.row_of_output(k), "output") for k in range(len(s.out_lanes))]
        rows += [(s.row_of_input(lane[0]), "ingredient") for lane in s.in_below]
        for row, kind in rows:
            span = s.sorter_span(row)
            if 1 <= span <= reach:
                continue
            key = (s.item_id, kind, span)
            if key in seen:
                continue
            seen.add(key)
            building = catalog.building(s.item_id)
            name = building.name
            if not building.slot_poses:
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
    spec: BuildSpec,
    *,
    band_policy: BandPolicy,
    power: bool = True,
    ramped: bool = False,
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
    strips = plan_strips(
        spec,
        strip_len=max(1, spec.machine_count),
        band_policy=band_policy,
    )
    at: dict[int, tuple[int, int]] = {}
    y = 0
    for i, s in enumerate(strips):
        at[i] = (0, y)
        y += s.height + MARGIN
    width = max((s.width for s in strips), default=1) + MARGIN
    pack = _Pack(at=at, width=width, height=y, status="fallback")
    result = _build(
        spec,
        strips,
        pack,
        power=power,
        route=False,
        policy=band_policy,
        ramped=ramped,
    )
    assert result.routing.status is DetailedRouteStatus.ROUTED
    placement = result.placement
    assert placement is not None
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


type _RefusalFinding = str | validate.Finding | finalize.ProjectionFailure


def _retain_refusal(
    rejected: list[_RefusalFinding],
    finding: _RefusalFinding,
) -> None:
    """Keep authoritative findings in first-seen order without duplicates."""
    if finding not in rejected:
        rejected.append(finding)


def _port_seating_refusal(attempts: Sequence[PackAttempt]) -> str | None:
    """The refusal for a sweep whose router never ran, or ``None``.

    Every retained attempt failed at PREPARATION with static access only and
    expanded zero A* nodes: `_build` substitutes a synthetic STRANDED result and
    skips routing entirely when `prepared.preparation_failures` is non-empty, so
    "the packer produced packs its own router cannot wire" is false twice over --
    nothing was routed and the packer is blameless.  Measured on all three
    freeform `universe-matrix` cells at `e0bf432` (R2 §3, R4 §1).
    """
    if not attempts:
        return None
    for attempt in attempts:
        if attempt.routing.expansions:
            return None
        if not attempt.routing.failures:
            return None
        if any(
            failure.kind is not RouteFailureKind.STATIC_ACCESS
            for failure in attempt.routing.failures
        ):
            return None
    ports = {port.cell: port for attempt in attempts for port in attempt.stranded_ports}
    if not ports:
        return None
    named = ", ".join(
        f"{port.item} into {port.strip_label} at {port.cell} "
        f"(wants {port.wants}, held {port.held}, {port.options} free side(s))"
        for port in sorted(ports.values(), key=lambda port: port.cell)[:3]
    )
    counts = {len(attempt.stranded_ports) for attempt in attempts}
    same = (
        f"every candidate height produced the same {next(iter(counts))} failures"
        if len(counts) == 1
        else "the failure count varied by candidate height"
    )
    return (
        f"no pack was ever routed: {len(ports)} lane heads could not obtain the "
        f"belt approaches they need ({named}); this is a PORT-SEATING defect "
        f"independent of the packing -- {same}"
    )


def _refusal_summary(rejected: Sequence[_RefusalFinding]) -> str:
    """List concise checks first, then the structured records that explain them."""
    checks: list[str] = []
    records: list[str] = []
    for finding in rejected:
        check = finding if isinstance(finding, str) else finding.check
        if check not in checks:
            checks.append(check)
        if isinstance(finding, finalize.ProjectionFailure):
            records.append(
                f"band {finding.band} {finding.check} {finding.buildings}: {finding.detail}"
            )
        elif isinstance(finding, validate.Finding):
            record = f"{finding.check} {finding.buildings}: {finding.message}"
            if finding.detail:
                record += f" ({dict(finding.detail)})"
            records.append(record)
    summary = ", ".join(checks)
    return summary + (f"; findings: {'; '.join(records)}" if records else "")


def _portfolio_soft_deadline(
    soft: float,
    external_key: tuple[int, int] | None,
    best_key: tuple[int, float] | None,
    now: float,
) -> float:
    """The IMPROVEMENT deadline, which is NEVER this sweep's own ``soft``.

    ``soft`` is the sweep's own share and is what stops it improving; the hard
    ``deadline`` is what stops it entirely.  The value returned here is bound to
    a SEPARATE name and read only at the four sites already guarded by ``best is
    not None`` -- never written back over ``soft``.  Several ``_room_for_another``
    sites have no such guard -- ``projection_retry_affordable``, the
    learned-retry promotion and the window launch -- and all of them are finding
    paths that the soft-deadline breaks deliberately exempt (``if not
    projection_retry and ...``).  Setting ``soft`` itself would refuse every
    retry for the rest of the sweep, and a spec that only routes after a retry
    would then refuse under racing where the unraced arm succeeds -- a refusal
    manufactured by another process.

    A bound WORSE than what this sweep already holds moves nothing: an incumbent
    we have already beaten is not a reason to stop polishing.  Both keys are
    ``(area, belt_tiles)`` in that order, so ``>`` is the same lexicographic rule
    ``best_key`` is selected by.
    """
    if external_key is None:
        return soft
    if best_key is not None and external_key > best_key:
        return soft
    return min(soft, now)


class FreeformLayout:
    """Free-form packing plus belt routing."""

    name = "freeform"

    def __init__(
        self,
        *,
        band_policy: BandPolicy,
        strip_len: int = 6,
        workers: int | None = None,
        direct_insert: bool = True,
        arrangements: int | None = None,
        belt_vertical_construction: bool = True,
        portfolio_incumbent: Callable[[], tuple[int, int] | None] | None = None,
        publish_incumbent: Callable[[Placement], None] | None = None,
    ) -> None:
        self.band_policy = band_policy
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
        #: The best ``(area, belt_tiles)`` another racing strategy has certified,
        #: or ``None``.  A SCHEDULING input only: it never enters ``best_key``,
        #: so it can never select or reject a placement.
        self.portfolio_incumbent = portfolio_incumbent
        #: Called with each placement this sweep certifies, so the other racer
        #: can use it as a bound.
        self.publish_incumbent = publish_incumbent

    def lay_out(
        self,
        spec: BuildSpec,
        *,
        time_budget_s: float = 15.0,
        absolute_deadline: float | None = None,
    ) -> Placement:
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
        to :func:`_pack` as a warm start.  It normally bounds the search; the
        first candidate may substitute it only after an exact incumbent proves
        that it fits the same evidence-bound width slack.  It is never used when
        the solve fails.

        ``time_budget_s`` is the wall-clock search deadline for the whole call.
        Every phase takes what is left of exactly the budget the caller asked
        for, and a phase that finds the clock already spent is not started.

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

        ceiling = time_budget_s
        started = time.monotonic()
        # A racing child starts the budget its PARENT started, so it must be
        # told the wall rather than compute one: spawn, interpreter start and
        # unpickling the spec all happen after the clock began.  Same expression
        # `sequence_solver._production_run` already uses for the same reason.
        deadline = started + ceiling if absolute_deadline is None else absolute_deadline
        # ONE routing budget for the call. `_MAX_EXPANSIONS` bounds a single
        # search and `_ROUTING_BUDGET` bounded one routing pass; nothing bounded
        # the ten to twenty passes a sweep makes, so the packer could spend it
        # over and over. The wall clock bounds them in seconds; this bounds them
        # deterministically, which is what keeps a re-run reproducible -- and it
        # is scaled to the ceiling so that it stays a backstop rather than
        # becoming the thing that ends the sweep. See
        # `_ROUTING_EXPANSIONS_PER_SECOND`.
        budget = {"left": max(_ROUTING_BUDGET, int(_ROUTING_EXPANSIONS_PER_SECOND * ceiling))}

        def planning_cancelled() -> bool:
            return _expired(deadline)

        from flab2bp.layout.strip_variants import generate_strip_families

        families = tuple(generate_strip_families(spec))

        try:
            strips = plan_strips(
                spec,
                strip_len=self.strip_len,
                band_policy=self.band_policy,
                families=families,
                cancelled=planning_cancelled,
            )
        except _PreparationDeadline as exc:
            raise NoValidLayout(
                "the requested deadline passed while proving strip projection clearance",
                spec_label=spec.label,
                budget_s=time_budget_s,
            ) from exc
        except (ValueError, KeyError) as exc:
            # One retry with every machine of a group on a single strip. That is
            # the coarsest legal strip plan, so if it also fails the spec cannot
            # be turned into strips at all and no budget will change that.
            try:
                strips = plan_strips(
                    spec,
                    strip_len=max(1, spec.machine_count),
                    band_policy=self.band_policy,
                    families=families,
                    cancelled=planning_cancelled,
                )
            except _PreparationDeadline as deadline_exc:
                raise NoValidLayout(
                    "the requested deadline passed while proving fallback strip "
                    "projection clearance",
                    spec_label=spec.label,
                    budget_s=time_budget_s,
                ) from deadline_exc
            except ValueError, KeyError:
                raise NoValidLayout(
                    f"the spec cannot be split into strips: {exc}",
                    spec_label=spec.label,
                    budget_s=time_budget_s,
                ) from exc
        # Forty or more physical strips makes preparation and detailed
        # negotiation scale the same logical lanes into hundreds of redundant
        # branch nets. On the stress families this was 40-76 strips and repeated
        # one-net/zero-expansion misses; the same authoritative families
        # partitioned coarsely are 27-46 strips and route in one round.
        # Choose that representation before packing, not as a rescue afterward.
        try:
            strips, _effective_strip_len = _coarsen_saturated_strip_plan(
                spec,
                strips,
                strip_len=self.strip_len,
                band_policy=self.band_policy,
                families=families,
                cancelled=planning_cancelled,
            )
        except _PreparationDeadline as exc:
            raise NoValidLayout(
                "the requested deadline passed while proving coarsened strip projection clearance",
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
        # The sweep used to retry at a hidden fifteen-second floor and report a
        # generic routing miss. Structural failures are named before the one
        # requested-budget sweep instead.
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
                "wire them to, so it would paste joined to nothing. " + "; ".join(unreachable[:3]),
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

        budgets = (time_budget_s,)

        #: Ordered authoritative findings from candidates rejected after packing.
        rejected: list[_RefusalFinding] = []
        #: Candidate heights whose greedy seed extent fits no band.  NOT a
        #: rejection: no pack existed to reject.
        skipped_heights: list[int] = []
        sweep_telemetry: dict[str, float | str] = {}
        #: Complete immutable evidence from every pack the sweep routed. Empty
        #: means no pack got that far. Refusal reporting reads counts from the
        #: detailed results without destroying identities Task 10 consumes.
        attempts: list[PackAttempt] = []
        # ONE session for the whole call, so operator credit survives a strip
        # replan and a second arrangement pass.  It dies with this call:
        # nothing here is process-wide, and two `lay_out` calls never share a
        # ledger.
        #
        # ONE REPAIR ARM, because freeform has exactly one repair: the window.
        # `_sweep` never reads `choice.repair` -- it runs `_pack_window`
        # unconditionally -- so a session armed with the shipped PAIR would
        # train its repair ledger on `sequence-reinsert`, an operator with no
        # dispatch here, and `alns_operators` would report `local-exact-pack:0`
        # on a run that did nothing but local exact packs.  The destroy arm is
        # still chosen (spec 5.7: "destroy set from the same selector"); it is
        # the repair that is fixed.
        alns_session = OperatorSession(repair_arms=(RepairOperator.LOCAL_EXACT_PACK,))
        for sweep_s in budgets:
            if _expired(deadline):
                break
            try:
                best = self._sweep(
                    spec,
                    strips,
                    sweep_s,
                    deadline,
                    budget,
                    rejected,
                    attempts,
                    skipped_heights=skipped_heights,
                    session=alns_session,
                    telemetry=sweep_telemetry,
                )
            except _PreparationDeadline as exc:
                raise NoValidLayout(
                    "candidate PREPARATION deadline passed while applying learned "
                    "projection geometry",
                    spec_label=spec.label,
                    budget_s=time_budget_s,
                ) from exc
            if best is not None:
                from flab2bp.layout import route_kernel
                best.stats["route_backend"] = route_kernel.selected_backend()
                return best

        deadline_expired = _expired(deadline)
        completion_expired = deadline_expired and any(
            attempt.budget_stage
            in (
                _BuildBudgetStage.CERTIFICATION,
                _BuildBudgetStage.FINALIZATION,
            )
            for attempt in attempts
        )
        projection_failures = tuple(
            ProjectionFailureRecord(
                finding.band,
                finding.check,
                finding.buildings,
                finding.detail,
            )
            for finding in rejected
            if isinstance(finding, finalize.ProjectionFailure)
        )
        over_band = (
            f"; {len(skipped_heights)} candidate heights were skipped as over-band"
            if skipped_heights
            else ""
        )
        refusal_stats: dict[str, float | str] = {
            **sweep_telemetry,
            "attempts": float(len(attempts)),
            "skipped_heights": float(len(skipped_heights)),
        }
        # A build that WIRED and then failed our own validator is a different
        # defect from one that could not be wired, and saying so is the whole
        # value of checking: "the packer produced packs its own router cannot
        # wire" would be false here and would send the next reader to the packer.
        if rejected and not completion_expired:
            raise NoValidLayout(
                "every packing that wired was rejected by our own validator ("
                + _refusal_summary(rejected)
                + "); a placement that fails validation is refused rather than "
                "returned, because an invalid blueprint pastes and then does not "
                "run"
                + over_band,
                spec_label=spec.label,
                budget_s=budgets[-1],
                projection_failures=projection_failures,
                stats=refusal_stats,
            )
        if deadline_expired:
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
            routing_attempts = [
                attempt
                for attempt in attempts
                if attempt.budget_stage is not _BuildBudgetStage.PREPARATION
            ]
            preparation_cancellations = len(attempts) - len(routing_attempts)
            completion_stages = tuple(
                dict.fromkeys(
                    attempt.budget_stage.value.upper()
                    for attempt in routing_attempts
                    if attempt.budget_stage
                    in (
                        _BuildBudgetStage.CERTIFICATION,
                        _BuildBudgetStage.FINALIZATION,
                    )
                )
            )
            failed_counts = [attempt.routing.failed_count for attempt in routing_attempts]
            tried = (
                "1 pack was"
                if len(routing_attempts) == 1
                else f"{len(routing_attempts)} packs were"
            )
            if not attempts:
                note = "no pack finished exact preparation inside it"
            elif not routing_attempts:
                noun = "pack" if preparation_cancellations == 1 else "packs"
                note = (
                    f"{preparation_cancellations} {noun} exhausted the deadline "
                    "during exact preparation, before a net set existed to route"
                )
            elif min(failed_counts) == 0:
                completed = " and ".join(completion_stages)
                note = f"{tried} routed in that time and at least one wired every net" + (
                    f", but the deadline passed during {completed}"
                    if completed
                    else ", so the clock is what was missing"
                )
            else:
                note = (
                    f"{tried} routed in that time and the best of them still "
                    f"left {min(failed_counts)} nets unrouted (worst "
                    f"{max(failed_counts)}), so a longer clock alone would not have "
                    "wired this spec"
                )
            if preparation_cancellations and routing_attempts:
                noun = "pack" if preparation_cancellations == 1 else "packs"
                note += (
                    f"; {preparation_cancellations} other {noun} stopped during exact preparation"
                )
            if rejected:
                note += (
                    "; earlier completed packs were also rejected by our own "
                    f"validator ({_refusal_summary(rejected)})"
                )
            # A sweep whose router never ran has a mechanism, and the deadline is
            # not it.  When every retained attempt is a preparation-time static
            # access with zero expansions, say so instead of counting packs that
            # were never routed.
            seating = _port_seating_refusal(attempts)
            if seating is not None:
                note = seating
            note += over_band
            raise NoValidLayout(
                f"the {ceiling:g}s deadline passed with no completed packing of "
                f"{len(strips)} strips; {note}. This is a REFUSAL and not a "
                "verdict on the spec",
                spec_label=spec.label,
                budget_s=ceiling,
                projection_failures=projection_failures,
                stats=refusal_stats,
            )
        # "every pack the sweep produced left nets unrouted" is false when no
        # pack was ever produced. `attempts` is empty whenever `_sweep` never
        # got as far as a routed-or-refused candidate, and that has more than
        # one cause: every candidate height's greedy seed skipped as over-band
        # (`skipped_heights`) is one, but `_pack` returning `None` or repeating
        # an already-seen assignment (both `continue`, recording nothing) is
        # another -- and that second kind is a packer failure the seed-gate
        # sentence would misname.  Only claim the seed gate when EVERY
        # candidate that reached it was skipped; otherwise stay neutral and let
        # `over_band` supply whatever skip count there was.
        if attempts:
            base = (
                f"no packing of {len(strips)} strips could be wired at any candidate "
                "height; every pack the sweep produced left nets unrouted. That is a "
                "PACKER defect -- it is producing packs its own router cannot wire -- "
                "and it is reported rather than papered over with a looser packing"
            )
        elif skipped_heights and len(skipped_heights) == len(
            _band_policy_candidate_heights(strips, self.band_policy)
        ):
            base = (
                f"no packing of {len(strips)} strips was ever attempted at any "
                "candidate height; every candidate's greedy seed was skipped before "
                "a pack could be produced"
            )
        else:
            base = f"no pack of {len(strips)} strips was ever produced at any candidate height"
        raise NoValidLayout(
            (_port_seating_refusal(attempts) or base) + over_band,
            spec_label=spec.label,
            budget_s=budgets[-1],
            stats=refusal_stats,
        )

    def _sweep(
        self,
        spec: BuildSpec,
        strips: list[Strip],
        time_budget_s: float,
        deadline: float | None = None,
        budget: dict[str, int] | None = None,
        rejected: list[_RefusalFinding] | None = None,
        attempts: list[PackAttempt] | None = None,
        skipped_heights: list[int] | None = None,
        *,
        session: OperatorSession,
        telemetry: dict[str, float | str] | None = None,
    ) -> Placement | None:
        """Try every candidate height, returning the best FULLY ROUTED placement.

        ``attempts`` collects immutable :class:`PackAttempt` records with the
        exact assignment, full detailed routing, static-access failures, and
        promised-versus-realized direct identities. Refusal reporting derives
        counts from those records rather than reducing evidence to an integer.

        ``None`` means no height produced one -- which is a refusal, not a
        degraded answer.  Packs with unrouted nets are discarded here rather than
        ranked below routed ones, so an unwireable pack can never be what this
        returns, and neither can one our own validator rejects.

        ``rejected`` collects ordered structured findings from placements thrown
        out by self-checks or projected geometry, so a terminal refusal can name
        the broken promise and retain the authoritative record that proved it.

        ``skipped_heights`` collects candidate heights whose GREEDY SEED extent
        fits no band.  They are kept apart from ``rejected`` deliberately: that
        gate fires before `_pack`, so no pack ever existed, and feeding it into
        ``rejected`` made `lay_out` report "every packing that wired was rejected
        by our own validator" for a cell where nothing wired (R1 §0).  The
        POST-pack gate still retains a real pack's rejection.

        ``telemetry`` receives this sweep's counters whatever the outcome, so a
        refusal can carry them.  `best.stats` is stamped only when a placement
        exists, and a refusing cell is precisely the one whose numbers a gate
        needs.

        ``time_budget_s`` bounds the WHOLE sweep, not just CP-SAT.  It used to
        bound only the packing: routing is limited by an expansion count, not a
        clock, so a 1s budget could spend 13.5s and a 4s budget 68.6s -- both on
        specs that then refused.  A caller who says one second and waits over a
        minute has not been given a budget, and the bake-off cannot sweep a
        parameter the code ignores.

        The deadline is polled between search phases and inside preparation,
        routing, compaction, and final projection. An interrupted candidate is
        discarded because a half-routed or half-certified pack is not a result.
        Certification is checked again after it returns, so a completed phase
        that crossed the wall can never install a late placement.
        """
        cancelled = None if deadline is None else lambda: _expired(deadline)
        candidates = _direct_insert_candidates(spec)
        greedy = _greedy_pack(strips, _height_seed(strips))
        bound = max(greedy.width, max((w for w, _h in map(_box, strips)), default=1))
        direct_candidate_snapshot = _direct_candidate_snapshot(
            strips,
            spec,
            enabled=self.direct_insert,
        )
        net_candidates = direct_candidate_snapshot.candidates

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
        # A fixed band first prefers the greedy envelope with the most exact
        # latitude-padding choices. A zero-headroom envelope can route and only
        # then fail projection; spending a short budget on it prevents a later
        # proved-fit height from running. Within equal projection headroom, and
        # for portable layouts, try the warm-start with the smallest LONGEST
        # AXIS first. The detailed router, boundary projection, and exact
        # validator all traverse a two-dimensional build; bounding the longer
        # realized axis is the deterministic model-derived proxy shared by all
        # three.
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
        # The greedy pack is already built per height as `_pack`'s seed, so the
        # order adds no model, solve, candidate, or work.
        heights = list(_band_policy_candidate_heights(strips, self.band_policy))
        seeds = {height: _greedy_pack(strips, height) for height in heights}
        original_height_ordinal = {height: ordinal for ordinal, height in enumerate(heights)}
        envelope = finalize.band_policy_search_envelope(
            self.band_policy,
            perimeter=_ENTRY_RING,
        )
        projection_headroom = {
            height: (
                max(
                    (
                        candidate.added_rows
                        for candidate in envelope.frame_candidates(
                            seeds[height].width,
                            seeds[height].height,
                        )
                    ),
                    default=-1,
                )
                if envelope.band is not None
                else 0
            )
            for height in heights
        }
        heights.sort(
            key=lambda height: (
                -projection_headroom[height],
                max(seeds[height].width, seeds[height].height),
                seeds[height].width,
                seeds[height].height,
                original_height_ordinal[height],
            )
        )
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
        # Arrangement-outer: every height gets one packing before density
        # alternatives begin.  A stress refusal must not spend the whole clock
        # redrawing one height while a later height is known to route cleanly.
        candidate_packs = [
            (height, arrangement, False)
            for arrangement in range(max(1, self.arrangements))
            for height in heights
        ]
        routed_assignments: set[
            tuple[
                int,
                int,
                tuple[tuple[int, int], ...],
                tuple[tuple[int, int], ...],
            ]
        ] = set()
        projection_no_goods: list[ProjectionNoGood] = []
        projection_no_good_keys: set[ProjectionNoGood] = set()
        minimum_pitch_x: dict[StripPoseId, int] = {}
        minimum_staged_static_clearance: dict[StagedStaticClearanceKey, int] = {}
        exact_no_good_state = _ExactPackNoGoodState()
        feedback_retry_no_goods: dict[tuple[int, int], ExactPackNoGood] = {}
        staged_static_exact_retries: set[tuple[int, int]] = set()
        direct_relation_no_goods: list[_DirectRelationNoGood] = []
        direct_relation_no_good_keys: set[_DirectRelationNoGood] = set()
        cluster_relation_no_goods: list[ClusterRelationNoGood] = []
        cluster_relation_no_good_keys: set[ClusterRelationNoGood] = set()
        feedback_by_height: dict[int, FeedbackState] = {}
        compact_width_by_height: dict[int, int] = {}
        # This sweep's own share, never more than the CALL has left. A sweep
        # asked for 15s when 3 remain must not spend 15.
        left = time_budget_s if deadline is None else deadline - time.monotonic()
        share = min(time_budget_s, max(left, 0.0))
        if share <= 0:
            return None
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
        per_solve = share * _PACK_SHARE / max(len(heights), 1)
        # This sweep's SOFT deadline, and the call's HARD one, and they are not
        # the same rule.
        soft = time.monotonic() + share

        best: Placement | None = None
        best_key: tuple[int, float] | None = None
        #: The dearest candidate this sweep has COMPLETED, pack through validate.
        #: What `_room_for_another` charges the next improvement arrangement.
        dearest_candidate_s = 0.0
        #: The dearest POST-PACK REMAINDER this sweep has completed: over the
        #: candidates that finished, the largest value of (that candidate's own
        #: total minus that SAME candidate's own `_pack` seconds).  A windowed
        #: retry is charged for what it actually replaces rather than for a
        #: whole candidate -- the window swaps out the pack and leaves routing,
        #: power, finalize and validate exactly where they were.
        #:
        #: RULING AD: it must be a per-candidate remainder, not
        #: `dearest_candidate_s - dearest_pack_s`.  Those two maxima can belong
        #: to DIFFERENT candidates -- one slow to pack and quick to route, one
        #: the other way round -- and their difference is then an upper bound on
        #: nothing, collapsing toward zero exactly when some candidate's own
        #: post-pack span is the largest thing the sweep has measured.
        dearest_remainder_s = 0.0
        #: This candidate's own `_pack` span, reset when its turn starts and
        #: left at zero for a queued repair, whose pack was already bought.
        candidate_pack_s = 0.0
        #: Window repairs waiting to be evaluated, and the queue that drains
        #: them.  `candidate_packs` is iterated by index and already mutated in
        #: four places; a separate queue adds no fifth mutation.
        window_packs: dict[tuple[int, int], _Pack] = {}
        window_queue: list[tuple[int, int]] = []
        #: The choice and the pre-repair metrics that produced each queued pack,
        #: so credit lands on the choice that earned it rather than on whatever
        #: the selector happened to pick last.
        window_choices: dict[tuple[int, int], tuple[OperatorChoice, OperatorMetrics]] = {}
        #: Asked-and-answered windows, so the same question is never put to
        #: CP-SAT twice inside one SWEEP.  `lay_out` runs exactly one sweep
        #: today, so "per sweep" is also "per `lay_out`": this set spans every
        #: replan the sweep makes rather than being scoped inside one.  What the
        #: key MEANS is strip indices, and `replan_strips_for_learned_geometry`
        #: renumbers the strips -- the same `(height, arrangement, window)`
        #: triple names a DIFFERENT question afterwards, so an entry recorded
        #: against the old numbering can refuse a window nobody has asked
        #: against the new one.  Left that way deliberately: refusing a window
        #: costs a repair the sweep might have made and can never produce a
        #: wrong pack, and it is the third thing to clear at the replan --
        #: beside `window_packs` and `window_queue` -- if that miss is measured.
        solved_windows: set[tuple[int, int, frozenset[int]]] = set()
        window_solves = 0
        window_accepted = 0
        window_seconds = 0.0
        window_skipped_no_goods = 0
        window_encode_errors = 0
        evaluations = 0
        #: Consecutive draws that added no new entry to `routed_assignments`.
        #: Task 11 makes it move; it is published from here so the refused-row
        #: schema does not change again a task later.
        stale_draws = 0
        started_at: float | None = None
        candidate_index = 0

        def _count_window_skips(count: int) -> None:
            nonlocal window_skipped_no_goods
            window_skipped_no_goods += count

        def settle_window_credit(
            height: int,
            arrangement: int,
            *,
            after: OperatorMetrics | None,
            routing_seconds: float,
        ) -> None:
            """Credit the choice that produced this candidate, if there was one.

            ``after`` carries the metrics of the routing pass this candidate
            ACTUALLY RAN, and its ``validator_clean`` is True only where
            `validate.certify` said so -- False for every candidate that never
            reached the certifier (spec 5.7).

            ``after=None`` means no routing evaluation of this candidate is in
            HAND: the wall arrived before its turn came round, or `_build`
            raised before returning a result.  That is a cost with no reward, so
            it is credited unapplied.  It is NOT what a repair that routed and
            was then refused downstream gets: that one was measured, and the
            measurement is what it is paid on.

            One of those raising exits did route.  `finalize.ProjectionRefusal`
            and `_Unseatable` are decided before any net is laid, but
            `_Unpowerable` from `_place_power` is raised AFTER `_build` has
            finished routing (it runs under `if power and not
            routing.failed_count`), and the handler that catches it sits above
            `route_seconds`, so no `DetailedRouteResult` is in scope to settle
            on and that candidate is drained here at zero.  Paying it correctly
            means changing what `_build` hands back on that path, not this call.
            """
            stored = window_choices.pop((height, arrangement), None)
            if stored is None:
                return
            choice, before = stored
            if after is None:
                session.observe(choice, (0.0,) * REWARD_RANKS, applied=False)
                return
            session.observe(
                choice,
                reward_vector(
                    OperatorOutcome(
                        choice=choice,
                        before=before,
                        after=after,
                        applied=True,
                    )
                ),
                applied=True,
                routing_seconds=routing_seconds,
            )
        from flab2bp.layout import geometry_memo

        staged_static_cache = geometry_memo.for_spec(spec)
        projection_envelope = finalize.band_policy_search_envelope(
            self.band_policy,
            perimeter=_ENTRY_RING,
        )

        def strip_outline(pack: _Pack) -> tuple[int, int]:
            left = min(origin[0] for origin in pack.at.values())
            bottom = min(origin[1] for origin in pack.at.values())
            right = max(pack.at[index][0] + _box(strip)[0] for index, strip in enumerate(strips))
            top = max(pack.at[index][1] + _box(strip)[1] for index, strip in enumerate(strips))
            return right - left, top - bottom

        compaction_reserve_s = 0.0
        finalize_reserve_s = 0.0
        validation_reserve_s = 0.0

        def projection_retry_affordable() -> bool:
            current_candidate_s = 0.0 if started_at is None else time.monotonic() - started_at
            return _room_for_another(
                deadline,
                soft,
                max(dearest_candidate_s, current_candidate_s),
            )

        def band_target_for(height: int, width: int) -> int:
            """Widest core this policy's bands still accept at ``height``, guarded.

            `finalize.band_target_width` raises `ValueError` above
            `finalize.C_BAND_SCAN_MAX` and for a non-positive height or width,
            and a pack's width is not bounded by either.  Neither caller here may
            raise over that: one is the window launch, where a repair attempt must
            never take the whole sweep down, and the other is the metrics closure,
            which runs inside a `finally` where a raise would REPLACE the
            exception already in flight.  Falling back to the input width makes
            the band term inert for that call, which is the same choice the
            sequence-pair arm's own `band_target_for` makes.
            """
            try:
                return finalize.band_target_width(
                    projection_envelope,
                    height=height,
                    width=width,
                )
            except ValueError:
                return width

        def replan_strips_for_learned_geometry() -> None:
            nonlocal strips, greedy, bound, direct_candidate_snapshot, net_candidates, seeds

            replan_strip_len = max(strip.machines for strip in strips)
            strips = plan_strips(
                spec,
                strip_len=replan_strip_len,
                band_policy=self.band_policy,
                minimum_pitch_x=minimum_pitch_x,
                minimum_staged_static_clearance=(minimum_staged_static_clearance),
                cancelled=cancelled,
            )
            greedy = _greedy_pack(strips, _height_seed(strips))
            bound = max(
                greedy.width,
                max((w for w, _h in map(_box, strips)), default=1),
            )
            direct_candidate_snapshot = _direct_candidate_snapshot(
                strips,
                spec,
                enabled=self.direct_insert,
            )
            net_candidates = direct_candidate_snapshot.candidates
            seeds = {
                candidate_height: _greedy_pack(strips, candidate_height)
                for candidate_height in heights
            }
            # These proofs carry offsets, widths, or relation rows from the old
            # strip geometry. Exact and projection cuts self-filter by outline or
            # geometry signature; these do not, so retaining them can forbid a
            # relation the widened strip just made feasible.
            feedback_by_height.clear()
            compact_width_by_height.clear()
            direct_relation_no_goods.clear()
            direct_relation_no_good_keys.clear()
            cluster_relation_no_goods.clear()
            cluster_relation_no_good_keys.clear()
            # AND SO DOES EVERY PENDING WINDOW.  A queued repair is a set of
            # origins keyed by STRIP INDEX, and the numbering it was solved
            # against is the numbering this function just replaced: installing
            # one afterwards would seat the new strips at the old strips' places,
            # and settling its credit reads `pack.at` at the new indices, which
            # raises `KeyError` the moment the strip count changes.
            #
            # The choice behind each one is settled FIRST, and unapplied: it
            # bought a CP-SAT solve, so the ledger has to see the cost, and the
            # routing pass it would have been paid on describes a pack that no
            # longer exists.  Settling here is also what keeps the settle to
            # ONE: `settle_window_credit` pops, so the `finally` below the
            # candidate body finds nothing left to pay, and neither does the
            # post-loop drain.
            for pending_height, pending_arrangement in list(window_choices):
                settle_window_credit(
                    pending_height,
                    pending_arrangement,
                    after=None,
                    routing_seconds=0.0,
                )
            window_choices.clear()
            window_packs.clear()
            window_queue.clear()

        try:
            while window_queue or candidate_index < len(candidate_packs):
                # A queued window repair is a candidate that has ALREADY been
                # packed, so it consumes a turn of this loop without consuming a
                # `candidate_packs` slot: the `pop` below is what removed it.
                queued = window_queue.pop(0) if window_queue else None
                if queued is not None:
                    height, arrangement = queued
                    projection_retry = False
                else:
                    height, arrangement, projection_retry = candidate_packs[candidate_index]
                    candidate_index += 1
                # A SECOND deadline, never a replacement for `soft`.  See
                # `_portfolio_soft_deadline` for why rebinding `soft` would let
                # another process refuse this one's retries.
                improvement_soft = _portfolio_soft_deadline(
                    soft,
                    None if self.portfolio_incumbent is None else self.portfolio_incumbent(),
                    best_key,
                    time.monotonic(),
                )
                # Charge the PREVIOUS candidate here, at the one place every path
                # through the body reaches. The body leaves by five different
                # routes -- no pack, unpowerable, unrouted, rejected, kept -- and a
                # cost recorded at only some of them would systematically
                # UNDER-estimate, since the expensive exits are the failures that run
                # a full routing pass into the wall.
                if started_at is not None:
                    candidate_total_s = time.monotonic() - started_at
                    dearest_candidate_s = max(dearest_candidate_s, candidate_total_s)
                    # The remainder is taken against THIS candidate's own pack,
                    # so it is a span one candidate really ran (Ruling AD) and
                    # never a difference between two different ones.
                    dearest_remainder_s = max(
                        dearest_remainder_s,
                        candidate_total_s - candidate_pack_s,
                    )
                # WHAT THIS TURN COSTS, and a queued repair does not cost a whole
                # candidate.  `_room_for_another` charges `dearest_candidate_s`,
                # which is pack THROUGH validate; a window has already bought this
                # candidate's pack, so what is left to spend on it is route, power,
                # finalize and validate -- the same measured remainder
                # `_window_candidate_seconds` charges on top of the window's own
                # wall.  Charging a queued repair for a whole candidate drops
                # repairs the sweep can plainly afford, and drops them AFTER paying
                # for the CP-SAT solve that produced them.
                turn_cost = dearest_remainder_s if queued is not None else dearest_candidate_s
                if best is not None and not _room_for_another(
                    deadline, improvement_soft, turn_cost
                ):
                    break
                # A SECOND ARRANGEMENT NORMALLY IMPROVES; ONE STRONG NEAR MISS MAY RESCUE.
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
                # routability lever is now primarily a density one.
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
                # and arrangements past it are normally gated TWICE: on having
                # something to improve, and on being able to afford the improvement.
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
                # One bounded exception lets a strong near miss look at the next
                # arrangement for that exact height. The candidate already exists in
                # `candidate_packs`: ordinary improvements still require the measured
                # cost above, while a complete one-net geometric near miss may use any
                # positive hard time left after the completion reserve. The marker
                # preserves that admission through this gate; the hard deadline still
                # applies. A failed admitted retry cannot unlock the height's later
                # arrangements.
                # Once a valid candidate exists, every later base height is an
                # improvement attempt too. Starting one without enough measured
                # clock for a complete candidate can only discard the valid result
                # at the hard deadline; it cannot improve it.
                if (
                    not projection_retry
                    and best is not None
                    and not _room_for_another(deadline, improvement_soft, turn_cost)
                ):
                    break
                if not projection_retry and arrangement and best is None:
                    break
                # `turn_cost` here is `dearest_candidate_s` under every reachable
                # state: a window launches only from `arrangement == 0`, so every
                # queued turn short-circuits on `and arrangement` before this
                # predicate runs.  It is written as `turn_cost` so the day a
                # window launches from a later arrangement the charge is already
                # right; no fixture can distinguish the two today.
                if (
                    not projection_retry
                    and arrangement
                    and not _room_for_another(deadline, improvement_soft, turn_cost)
                ):
                    break
                # The SOFT deadline stops us IMPROVING, never FINDING. A refusal
                # means the model could not lay the spec out; a sweep's own clock
                # must not be able to manufacture one. Breaking on time alone did
                # exactly that: heights are tried shortest-first and the
                # free-proliferation chain only wires at the tallest, so a 2s budget
                # refused a spec that routes every net cleanly given the chance to
                # reach it.
                if (
                    not projection_retry
                    and best is not None
                    and time.monotonic() >= improvement_soft
                ):
                    break
                # The HARD deadline is the call's, and it does stop us finding --
                # that is what makes `time_budget_s` a wall rather than a suggestion.
                # `lay_out` turns it into a refusal that names the deadline, so the
                # distinction between "cannot" and "ran out" survives into the error.
                completion_reserve_s = (
                    compaction_reserve_s + finalize_reserve_s + validation_reserve_s
                )
                if deadline is not None and deadline - time.monotonic() < completion_reserve_s:
                    break
                seed = seeds[height]
                seed_width, seed_height = strip_outline(seed)
                if not projection_envelope.frame_candidates(
                    seed_width,
                    seed_height,
                ):
                    if skipped_heights is not None and height not in skipped_heights:
                        skipped_heights.append(height)
                    continue
                started_at = time.monotonic()
                candidate_pack_s = 0.0
                remaining = (
                    per_solve if deadline is None else min(per_solve, deadline - time.monotonic())
                )
                if remaining <= 0:
                    break
                # CP-SAT's multi-worker portfolio changes the returned large-plan
                # arrangement with audit job allocation.  Those 24+ strip cells
                # route in one round from the deterministic seed; pin only their
                # packing solve so jobs=2 and a standalone call ask the same model.
                feedback = feedback_by_height.get(height)
                width_bound = max(bound * 2, 8)
                if feedback is not None and height in compact_width_by_height:
                    width_bound = min(
                        width_bound,
                        _width_slack_cap(compact_width_by_height[height]),
                    )
                retry_no_good = feedback_retry_no_goods.pop((height, arrangement), None)
                exact_pack_no_goods = tuple(exact_no_good_state.no_goods)
                if retry_no_good is not None:
                    exact_pack_no_goods += (retry_no_good,)
                # A window repair IS this candidate's pack.  Re-solving it here
                # would throw away the bounded solve that was just paid for and
                # hand routing the same assignment that stranded a net.
                pending_pack = window_packs.pop((height, arrangement), None)
                pack: _Pack | None
                if pending_pack is not None:
                    # THE INSTALL SITE, and where `alns_window_accepted` is
                    # counted -- mirroring the sequence-pair arm, so the gate
                    # can read one number across both.  A window that solved
                    # and produced a different pack has not been accepted by
                    # anything yet; it is accepted here, where the sweep hands
                    # it to the pipeline in place of a `_pack` call.
                    window_accepted += 1
                    pack = pending_pack
                else:
                    pack_started = time.monotonic()
                    pack = _pack(
                        strips,
                        height=height,
                        width_bound=width_bound,
                        time_budget_s=remaining,
                        direct_candidates=net_candidates,
                        workers=(1 if len(strips) >= _DETERMINISTIC_PACK_STRIPS else self.workers),
                        deterministic=len(strips) >= _DETERMINISTIC_PACK_STRIPS,
                        seed=seed,
                        arrangement=arrangement,
                        projection_no_goods=tuple(projection_no_goods),
                        exact_pack_no_goods=exact_pack_no_goods,
                        direct_relation_no_goods=tuple(direct_relation_no_goods),
                        cluster_relation_no_goods=tuple(cluster_relation_no_goods),
                        feedback=feedback,
                        stop_when_seed_admissible=(
                            candidate_index == 1
                            and arrangement == 0
                            and not projection_retry
                            and feedback is None
                            and _seed_admission_preserves_best_band(
                                seed,
                                _minimum_pack_width(strips, height),
                                projection_envelope,
                            )
                        ),
                    )
                    candidate_pack_s = time.monotonic() - pack_started
                if pack is None:
                    continue
                assignment = (
                    pack.height,
                    pack.width,
                    tuple(_box(strip) for strip in strips),
                    tuple(pack.at[index] for index in range(len(strips))),
                )
                # A retry is useful only when CP-SAT actually moved something.
                # Deterministic short solves can return the same incumbent for two
                # arrangement seeds; routing it again is the same deterministic
                # multi-second search and can consume the candidate that would wire.
                if assignment in routed_assignments:
                    continue
                routed_assignments.add(assignment)
                if (
                    deadline is not None
                    and deadline - time.monotonic()
                    < compaction_reserve_s + finalize_reserve_s + validation_reserve_s
                ):
                    break
                if feedback is None:
                    compact_width_by_height.setdefault(height, pack.width)
                # Route the deterministic warm-start once this exact solve has
                # produced a compact incumbent that admits it under the existing
                # evidence-bound width contract.  The width-36 warm-start routes on
                # the fourteen-strip calibration chain, while continuing to tighten
                # it can replace it with a width-35 arrangement that strands one net.
                #
                # The admission callback stops only this first optimisation once the
                # same exact width proof exists.  It does not add a solve, route,
                # arrangement, worker, or deadline, and the seed REPLACES the
                # candidate rather than acting as the deleted loose fallback.  If
                # the exact incumbent is too narrow to admit the seed, CP-SAT keeps
                # its normal bounded search and the final incumbent is routed.
                #
                # A WINDOW REPAIR IS NOT A FRESH SOLVE and must not be swapped out
                # for the seed.  A budget-stage failure takes no feedback snapshot,
                # so a queued repair can arrive here on the first candidate with
                # `feedback is None` still true -- and replacing it would discard
                # the bounded solve and route the greedy pack that already stranded.
                if (
                    pending_pack is None
                    and candidate_index == 1
                    and arrangement == 0
                    and not projection_retry
                    and feedback is None
                    and seed.width <= _width_slack_cap(pack.width)
                    and (
                        seed.at != pack.at
                        or seed.width != pack.width
                        or seed.height != pack.height
                    )
                ):
                    pack = replace(
                        seed,
                        status="WARM_START",
                        hit_budget=pack.hit_budget,
                    )
                # Reject a provably oversized strip outline before emitting coaters,
                # reserving power, and preparing exact routing geometry.  The
                # emitted core contains every packed strip, so an outline that fits
                # no legal frame cannot become feasible when later passes only add
                # buildings.  This is the same projection envelope `_prepare` asks,
                # moved to the first point where the exact solved origins exist.
                outline_width, outline_height = strip_outline(pack)
                if not projection_envelope.frame_candidates(
                    outline_width,
                    outline_height,
                ):
                    if rejected is not None:
                        _retain_refusal(
                            rejected,
                            projection_envelope.extent_failure(
                                outline_width,
                                outline_height,
                            ),
                        )
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
                evaluations += 1
                route_started = time.monotonic()
                try:
                    result = _build(
                        spec,
                        strips,
                        pack,
                        power=True,
                        route=True,
                        policy=self.band_policy,
                        ramped=self.ramped,
                        deadline=deadline,
                        budget=budget,
                        staged_static_cache=staged_static_cache,
                    )
                except finalize.ProjectionRefusal as exc:
                    if rejected is not None:
                        for failure in exc.failures:
                            _retain_refusal(rejected, failure)
                    continue
                except _Unpowerable as exc:
                    if rejected is not None:
                        _retain_refusal(rejected, exc.failure or "power.coverage")
                    evidence = exc.exact_retry_evidence
                    if evidence is not None and exc.failure is not None:
                        no_good = ExactPackNoGood(
                            height=pack.height,
                            outline=tuple(_box(strip) for strip in strips),
                            width=pack.width,
                            origins=tuple(pack.at[index] for index in range(len(strips))),
                            evidence=exc.failures,
                        )
                        retry_key = _ExactRetryKey(height, arrangement, evidence)
                        if exact_no_good_state.admit_retry(
                            retry_key,
                            no_good,
                            affordable=projection_retry_affordable(),
                        ):
                            candidate_packs.insert(
                                candidate_index,
                                (height, arrangement, True),
                            )
                    continue
                except _Unseatable as exc:
                    # A pack that cannot seat one of its Spray Coaters is not a
                    # pack, for the same reason one that cannot be powered is not:
                    # the spec asked for proliferation and this height cannot
                    # deliver it. Discarding the height is the search doing its job;
                    # what is NOT allowed is emitting the pack with the coater left
                    # out, which is what this replaced.
                    if rejected is not None:
                        _retain_refusal(
                            rejected,
                            exc.failure or "prolif.sprayed_cargo_reaches_machines",
                        )

                    retry_promoted = False
                    evidence = exc.exact_retry_evidence
                    if evidence is not None and exc.failure is not None:
                        no_good = ExactPackNoGood(
                            height=pack.height,
                            outline=tuple(_box(strip) for strip in strips),
                            width=pack.width,
                            origins=tuple(pack.at[index] for index in range(len(strips))),
                            evidence=exc.failures,
                        )
                        retry_key = _ExactRetryKey(height, arrangement, evidence)
                        retry_promoted = exact_no_good_state.admit_retry(
                            retry_key,
                            no_good,
                            affordable=projection_retry_affordable(),
                        )

                    pending_clearance: tuple[StagedStaticClearanceKey, int] | None = None

                    clearance_exhausted = False
                    requirement = exc.clearance_requirement
                    if requirement is not None:
                        selected_strip = next(
                            (
                                strip
                                for strip in strips
                                if strip.family_id == requirement.instance_id.family_id
                                and strip.machine_start == requirement.instance_id.machine_start
                                and strip.machines == requirement.instance_id.machine_count
                            ),
                            None,
                        )
                        if (
                            selected_strip is not None
                            and selected_strip.physical_variant is not None
                            and selected_strip.staged_static_variant_id == requirement.variant_id
                        ):
                            if requirement.required_west_channel > _COATER_WEST_CHANNEL + 1:
                                clearance_exhausted = True
                            else:
                                retained_clearance = minimum_staged_static_clearance.get(
                                    requirement.relation,
                                    selected_strip.west_channel,
                                )
                                if requirement.required_west_channel > retained_clearance:
                                    pending_clearance = (
                                        requirement.relation,
                                        requirement.required_west_channel,
                                    )

                    # The physical variant gets one bounded upstream seat first.
                    # If an extended pack still projects into its own machine, the
                    # absolute frame latitude remains pack-dependent: forbid this
                    # complete assignment once and let CP-SAT move it.  The bound
                    # belongs to the height/arrangement retry boundary, not to the
                    # assignment identity: every successful no-good necessarily
                    # produces a distinct assignment, so identity alone can never
                    # make a second W4 exhaustion terminal.
                    staged_retry_key = (height, arrangement)
                    if (
                        clearance_exhausted
                        and exc.failure is not None
                        and staged_retry_key not in staged_static_exact_retries
                        and projection_retry_affordable()
                    ):
                        no_good = ExactPackNoGood(
                            height=pack.height,
                            outline=tuple(_box(strip) for strip in strips),
                            width=pack.width,
                            origins=tuple(pack.at[index] for index in range(len(strips))),
                            evidence=exc.failures,
                        )
                        if exact_no_good_state.remember(no_good):
                            staged_static_exact_retries.add(staged_retry_key)
                            retry_promoted = True

                    if pending_clearance is not None:
                        relation, required_west_channel = pending_clearance
                        minimum_staged_static_clearance[relation] = required_west_channel
                        replan_strips_for_learned_geometry()
                    if retry_promoted:
                        candidate_packs.insert(
                            candidate_index,
                            (height, arrangement, True),
                        )
                    continue
                # The measured routing span of THIS evaluation, which is what an
                # operator choice is billed for when its repair is credited.
                route_seconds = time.monotonic() - route_started
                # THE CHOICE THIS CANDIDATE ARRIVED WITH, held by identity.  A
                # window launched further down stores a choice under this same
                # key, and that one belongs to the repair it queued -- a
                # candidate this turn has not evaluated and must not be paid
                # for.  Membership alone cannot tell the two apart, because a
                # queued repair that fails again settles its own credit and
                # then immediately stores a fresh choice under the key it just
                # cleared.
                inbound_choice = window_choices.get((height, arrangement))

                def window_metrics(
                    *,
                    validator_clean: bool,
                    current_pack: _Pack = pack,
                    current_height: int = height,
                    routing: DetailedRouteResult = result.routing,
                ) -> OperatorMetrics:
                    """This candidate's routing pass, as the operator ledger reads it.

                    The three places that settle a window's credit differ in one
                    field only -- `validator_clean`, which is True at exactly one
                    of them, the acceptance path that has a `validate.certify`
                    report to read.  The turn's `pack`, `height` and routing
                    result are bound at definition, as `retain_attempt` binds its
                    attempt, so the closure cannot describe a later candidate;
                    the feedback lookup stays late because the sweep writes to
                    `feedback_by_height` inside this turn.
                    """
                    return metrics_from_evaluation(
                        routing,
                        _decoded_from_pack(current_pack, strips, current_height),
                        feedback_by_height.get(
                            current_height,
                            FeedbackState.empty((current_pack.width, current_height)),
                        ),
                        outline_height=current_height,
                        band_target_width=band_target_for(
                            current_height,
                            current_pack.width,
                        ),
                        validator_clean=validator_clean,
                    )

                try:
                    failed = result.routing.failed_count
                    attempt = PackAttempt(
                        origins=tuple(pack.at[index] for index in range(len(pack.at))),
                        compact_width=pack.width,
                        height=pack.height,
                        outline=tuple(_box(strip) for strip in strips),
                        routing=result.routing,
                        budget_stage=result.budget_stage,
                        static_access=tuple(
                            failure
                            for failure in result.routing.failures
                            if failure.kind is RouteFailureKind.STATIC_ACCESS
                        ),
                        promised_direct=result.promised_direct,
                        realized_direct=result.realized_direct,
                        direct_candidates=direct_candidate_snapshot,
                        stranded_ports=result.stranded_ports,
                    )

                    def retain_attempt(
                        stage: _BuildBudgetStage | None = None,
                        *,
                        current: PackAttempt = attempt,
                    ) -> None:
                        if attempts is not None:
                            attempts.append(
                                current if stage is None else replace(current, budget_stage=stage)
                            )

                    if failed:
                        retain_attempt()
                    if failed:
                        local_no_goods, exact_no_good, cluster_no_goods = _proof_scoped_no_goods(
                            attempt,
                            strips,
                        )
                        learned = False
                        for relation_no_good in local_no_goods:
                            if relation_no_good in direct_relation_no_good_keys:
                                continue
                            direct_relation_no_good_keys.add(relation_no_good)
                            direct_relation_no_goods.append(relation_no_good)
                            learned = True
                        for cluster_no_good in cluster_no_goods:
                            if cluster_no_good in cluster_relation_no_good_keys:
                                continue
                            cluster_relation_no_good_keys.add(cluster_no_good)
                            cluster_relation_no_goods.append(cluster_no_good)
                            learned = True
                        if exact_no_good is not None and exact_no_good_state.remember(
                            exact_no_good
                        ):
                            learned = True

                        budget_failure = result.routing.status is DetailedRouteStatus.BUDGET or any(
                            failure.kind is RouteFailureKind.BUDGET
                            for failure in result.routing.failures
                        )
                        feedback_state: FeedbackState | None = None
                        if not budget_failure:
                            feedback_state = _attempt_feedback_state(
                                attempt,
                                feedback_by_height.get(height),
                            )
                            feedback_by_height[height] = feedback_state

                        feedback_retry = feedback_state is not None and _feedback_retry_eligible(
                            attempt, feedback_state
                        )
                        promote_retry = arrangement == 0 and (learned or feedback_retry)
                        #: A window launches where a retry was WANTED and refused, so
                        #: the two facts the block below already decides are recorded
                        #: rather than re-derived.
                        retry_slot_found = False
                        retry_admitted = False
                        if promote_retry:
                            retry_candidate = (height, arrangement + 1)
                            next_candidate = (*retry_candidate, False)
                            try:
                                next_index = candidate_packs.index(
                                    next_candidate,
                                    candidate_index,
                                )
                            except ValueError:
                                pass
                            else:
                                retry_slot_found = True
                                current_candidate_s = (
                                    0.0 if started_at is None else time.monotonic() - started_at
                                )
                                retry_cost = max(
                                    dearest_candidate_s,
                                    current_candidate_s,
                                )
                                if feedback_retry or _room_for_another(
                                    deadline,
                                    soft,
                                    retry_cost,
                                ):
                                    if feedback_retry:
                                        # This exact failed assignment is not proved
                                        # infeasible, so its cut belongs only to the
                                        # promoted feedback draw. Never remember it in
                                        # the sweep-wide exact no-good state.
                                        routing_failure = attempt.routing.failures[0]
                                        feedback_retry_no_goods[retry_candidate] = ExactPackNoGood(
                                            height=attempt.height,
                                            outline=attempt.outline,
                                            width=attempt.compact_width,
                                            origins=attempt.origins,
                                            evidence=(
                                                finalize.ProjectionFailure(
                                                    check="route.feedback_retry",
                                                    buildings=(),
                                                    detail=(
                                                        f"{routing_failure.kind.value}: "
                                                        f"net={routing_failure.net_id!r}; "
                                                        f"wall={routing_failure.wall!r}; "
                                                        "blockers="
                                                        f"{routing_failure.blocking_nets!r}; "
                                                        f"expansions={routing_failure.expansions}"
                                                    ),
                                                    band=0,
                                                ),
                                            ),
                                        )
                                    retry_admitted = True
                                    candidate_packs.pop(next_index)
                                    candidate_packs.insert(
                                        candidate_index,
                                        (height, arrangement + 1, True),
                                    )
                        # A queued repair that failed again settles its own credit
                        # here, on the outcome it actually produced, before this
                        # candidate is allowed to ask for another window.  The
                        # membership test only avoids ENCODING an outcome for the
                        # ordinary candidates that never had a choice behind them;
                        # `settle_window_credit` is a no-op for those anyway.
                        if (height, arrangement) in window_choices:
                            settle_window_credit(
                                height,
                                arrangement,
                                after=window_metrics(validator_clean=False),
                                routing_seconds=route_seconds,
                            )
                        # A WINDOW REPLACES A RETRY THAT WAS WANTED AND COULD NOT BE
                        # AFFORDED, and nothing else.  Alongside an admitted retry it
                        # would be redundant -- the retry re-solves the whole pack --
                        # and with no retry to promote there is no learned evidence to
                        # aim a window at either.
                        if promote_retry and retry_slot_found and not retry_admitted:
                            window_cost = _window_candidate_seconds(
                                dearest_remainder_s=dearest_remainder_s,
                            )
                            if (
                                (height, arrangement) not in window_packs
                                and (height, arrangement) not in window_choices
                                and _room_for_another(deadline, soft, window_cost)
                            ):
                                target = band_target_for(height, pack.width)
                                relation_problem = _pack_relation_problem(pack, strips, height)
                                relation_decoded = _decoded_from_pack(pack, strips, height)
                                feedback_state_now = feedback_by_height.get(
                                    height,
                                    FeedbackState.empty((pack.width, height)),
                                )
                                before_metrics = metrics_from_evaluation(
                                    attempt.routing,
                                    relation_decoded,
                                    feedback_state_now,
                                    outline_height=height,
                                    band_target_width=target,
                                    validator_clean=False,
                                )
                                choice = session.select(
                                    OperatorContext(
                                        strip_count=len(strips),
                                        stagnation=0,
                                        remaining_fraction=remaining_fraction_bucket(
                                            soft - time.monotonic(),
                                            max(time_budget_s, 1e-6),
                                        ),
                                    )
                                )
                                try:
                                    window = destroy_strips(
                                        choice.destroy,
                                        scale=choice.scale,
                                        result=attempt.routing,
                                        pair=_pack_relation_pair(pack, strips, height),
                                        gaps=GapProfile.zero(len(strips)),
                                        problem=relation_problem,
                                        decoded=relation_decoded,
                                        band_target_width=target,
                                    )
                                except ValueError:
                                    # The encoder refused this pack.  Impossible for a
                                    # `no_overlap_2d` result, so it is a bug detector.
                                    window_encode_errors += 1
                                    window = frozenset()
                                window_key = (height, arrangement, window)
                                if (
                                    not window
                                    or len(window) >= len(strips)
                                    or window_key in solved_windows
                                ):
                                    session.observe(choice, (0.0,) * REWARD_RANKS, applied=False)
                                else:
                                    solved_windows.add(window_key)
                                    window_solves += 1
                                    window_started = time.monotonic()
                                    repaired = _pack_window(
                                        strips,
                                        height=height,
                                        width_bound=pack.width,
                                        direct_candidates=net_candidates,
                                        window=window,
                                        fixed_at={
                                            index: origin
                                            for index, origin in pack.at.items()
                                            if index not in window
                                        },
                                        seed=pack,
                                        width_target=target,
                                        arrangement=arrangement,
                                        projection_no_goods=tuple(projection_no_goods),
                                        exact_pack_no_goods=exact_pack_no_goods,
                                        direct_relation_no_goods=tuple(direct_relation_no_goods),
                                        # THE SAME PROOFS `_pack` GETS.  A window
                                        # is a sub-model of the full formulation,
                                        # so a collection the packer is forbidden
                                        # to violate cannot be dropped here: the
                                        # window would hand back a pack the sweep
                                        # has already proved unroutable.
                                        cluster_relation_no_goods=tuple(cluster_relation_no_goods),
                                        feedback=feedback_by_height.get(height),
                                        on_skipped=_count_window_skips,
                                    )
                                    window_seconds += time.monotonic() - window_started
                                    if repaired is None or repaired.at == pack.at:
                                        session.observe(
                                            choice,
                                            (0.0,) * REWARD_RANKS,
                                            applied=False,
                                        )
                                    else:
                                        # NOT counted here.  `alns_window_accepted`
                                        # means INSTALLED into the candidate stream
                                        # -- the `_pack` site above, where the queue
                                        # drains -- and not "CP-SAT handed back a
                                        # different assignment".  A repair the sweep
                                        # never gets to is not an acceptance.  This
                                        # mirrors the sequence-pair arm so the gate
                                        # reads one number across both;
                                        # `alns_applied` counts a repair whose
                                        # routing pass was MEASURED, certified or
                                        # not, which is a wider set than this one.
                                        window_packs[height, arrangement] = repaired
                                        window_choices[height, arrangement] = (
                                            choice,
                                            before_metrics,
                                        )
                                        window_queue.append((height, arrangement))
                        continue
                    if result.routing.status is not DetailedRouteStatus.ROUTED:
                        retain_attempt()
                        continue
                    assert result.promised_direct == result.realized_direct, (
                        "a routed pack may not retain an unrealized rewarded direct insert"
                    )
                    placement = result.placement
                    assert placement is not None
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
                    # A fully routed incumbent still has to finish three exact completion
                    # transforms. Search stops at the caller's wall, but a wired candidate
                    # gets the fixed loaded-machine atomic grace: discarding a valid route
                    # halfway through projection makes load, rather than geometry, decide
                    # whether the same deterministic blueprint exists.
                    completion_deadline = (
                        None if deadline is None else deadline + ATOMIC_COMPLETION_GRACE_S
                    )
                    completion_cancelled = (
                        None
                        if completion_deadline is None
                        else lambda completion_deadline=completion_deadline: _expired(
                            completion_deadline
                        )
                    )
                    compaction_started = time.monotonic()
                    try:
                        compacted = finalize.compact_open_boundary_belts_certified(
                            placement,
                            spec,
                            expect_power=True,
                            cancelled=completion_cancelled,
                        )
                    except finalize.ProjectionCancelled:
                        retain_attempt(_BuildBudgetStage.CERTIFICATION)
                        break
                    if _expired(completion_deadline):
                        retain_attempt(_BuildBudgetStage.CERTIFICATION)
                        break
                    placement = compacted.placement
                    compaction_reserve_s = max(
                        compaction_reserve_s,
                        time.monotonic() - compaction_started,
                    )
                    finalize_started = time.monotonic()
                    try:
                        placement = finalize.finalize_placement(
                            placement,
                            self.band_policy,
                            cancelled=completion_cancelled,
                        )
                    except finalize.ProjectionCancelled:
                        retain_attempt(_BuildBudgetStage.FINALIZATION)
                        break
                    except finalize.ProjectionRefusal as exc:
                        retain_attempt()
                        learned = False
                        exact_projection_pair: ExactProjectionPair | None = None
                        geometry_learned = False
                        exact_retry_evidence: _ExactRetryEvidence | None = None
                        pitch_requirements = _projection_pitch_requirements(
                            placement,
                            strips,
                            exc.failures,
                        )
                        from flab2bp.layout.strip_variants import (
                            StripInstanceId,
                            strip_pose_id,
                        )

                        strips_by_instance: dict[StripInstanceId, Strip] = {}
                        for strip in strips:
                            if strip.family_id is None:
                                continue
                            strips_by_instance.setdefault(
                                StripInstanceId(
                                    strip.family_id,
                                    strip.machine_start,
                                    strip.machines,
                                ),
                                strip,
                            )
                        for failure, pitch_requirement in zip(
                            exc.failures,
                            pitch_requirements,
                            strict=True,
                        ):
                            if rejected is not None:
                                _retain_refusal(rejected, failure)

                            strip_pair = _projection_strip_pair(placement, failure)
                            projection_no_good = _projection_no_good(
                                placement,
                                pack,
                                strips,
                                failure,
                                self.band_policy,
                            )
                            if strip_pair is not None and projection_no_good is None:
                                if exact_projection_pair is None:
                                    exact_projection_pair = _exact_projection_pair(
                                        strips,
                                        strip_pair,
                                    )
                                if exact_retry_evidence is None:
                                    exact_retry_evidence = _exact_retry_evidence(
                                        "finalizer",
                                        failure,
                                        dict(enumerate(placement.buildings)),
                                    )
                            if projection_no_good is not None:
                                projection_no_good_key = projection_no_good
                                if projection_no_good_key not in projection_no_good_keys:
                                    projection_no_good_keys.add(projection_no_good_key)
                                    projection_no_goods.append(projection_no_good)
                                    learned = True

                            if pitch_requirement is None:
                                continue
                            selected_strip = strips_by_instance.get(pitch_requirement.instance_id)
                            if (
                                selected_strip is None
                                or selected_strip.physical_variant is None
                                or selected_strip.physical_variant.variant_id
                                != pitch_requirement.variant_id
                            ):
                                continue

                            pose_id = strip_pose_id(selected_strip.physical_variant)
                            retained_pitch = minimum_pitch_x.get(
                                pose_id,
                                selected_strip.physical_variant.pitch_x,
                            )
                            if pitch_requirement.required_pitch <= retained_pitch:
                                continue
                            minimum_pitch_x[pose_id] = pitch_requirement.required_pitch
                            learned = True
                            geometry_learned = True
                        retry_promoted = False
                        if exact_retry_evidence is not None:
                            exact_no_good = ExactPackNoGood(
                                height=pack.height,
                                outline=tuple(_box(strip) for strip in strips),
                                width=pack.width,
                                origins=tuple(pack.at[index] for index in range(len(strips))),
                                evidence=exc.failures,
                                projection_pair=exact_projection_pair,
                            )
                            retry_key = _ExactRetryKey(
                                height,
                                arrangement,
                                exact_retry_evidence,
                            )
                            retry_promoted = exact_no_good_state.admit_retry(
                                retry_key,
                                exact_no_good,
                                affordable=projection_retry_affordable(),
                            )
                        learned_retry_affordable = (
                            learned and not retry_promoted and projection_retry_affordable()
                        )
                        if geometry_learned:
                            replan_strips_for_learned_geometry()
                        if learned_retry_affordable:
                            retry_promoted = True
                        if retry_promoted:
                            candidate_packs.insert(
                                candidate_index,
                                (height, arrangement, True),
                            )
                        continue
                    if _expired(completion_deadline):
                        retain_attempt(_BuildBudgetStage.FINALIZATION)
                        break
                    finalize_reserve_s = max(
                        finalize_reserve_s,
                        time.monotonic() - finalize_started,
                    )
                    certify_started = time.monotonic()
                    report = validate.certify(placement, spec, expect_power=True)
                    if (
                        inbound_choice is not None
                        and window_choices.get((height, arrangement)) is inbound_choice
                    ):
                        settle_window_credit(
                            height,
                            arrangement,
                            after=window_metrics(validator_clean=not report.errors),
                            routing_seconds=route_seconds,
                        )
                    validation_reserve_s = max(
                        validation_reserve_s,
                        time.monotonic() - certify_started,
                    )
                    if report.errors and rejected is not None:
                        for finding in report.errors:
                            _retain_refusal(rejected, finding)
                    if _expired(completion_deadline):
                        retain_attempt(_BuildBudgetStage.CERTIFICATION)
                        break
                    if report.errors:
                        retain_attempt()
                        continue
                    if placement.frame is not None:
                        placement = replace(
                            placement,
                            completion=PlacementCompletion.COMPACTED_AND_FINALIZED,
                        )
                    retain_attempt()
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
                        if self.publish_incumbent is not None:
                            self.publish_incumbent(placement)
                finally:
                    # SPEC 5.7: a queued repair is paid on the metrics THIS
                    # routing pass measured, and `validator_clean` is False for
                    # any candidate that never reaches `validate.certify`.
                    # Every exit that HOLDS a routing result passes through here
                    # -- the unrouted `continue`, the two completion breaks, the
                    # projection/pitch refusal -- so none of them can fall
                    # through to the post-loop drain and be paid `after=None`,
                    # which is a zero reward for a repair that was measured.
                    # The one post-routing exit outside this block is
                    # `_Unpowerable`, raised from `_place_power` after routing
                    # but caught above `route_seconds`, where no result exists to
                    # settle on; `settle_window_credit`'s docstring names it.
                    # The two settles inside the body have already popped the
                    # choice by the time control reaches here: the failure block
                    # must settle BEFORE it is allowed to ask for another
                    # window, and the acceptance path is the only place a
                    # `validator_clean=True` outcome exists at all.
                    if (
                        inbound_choice is not None
                        and window_choices.get((height, arrangement)) is inbound_choice
                    ):
                        settle_window_credit(
                            height,
                            arrangement,
                            after=window_metrics(validator_clean=False),
                            routing_seconds=route_seconds,
                        )
        finally:
            # A choice whose candidate never produced a routing evaluation --
            # the wall arrived before its turn, or an exception took the sweep
            # out from under it -- is a cost with no reward, and the ledger has
            # to see it as one.  In a `finally` because an escaping exception
            # must not hand an operator a free turn: the session outlives this
            # call and the arm it credits is chosen from what the ledger holds.
            for outstanding_height, outstanding_arrangement in list(window_choices):
                settle_window_credit(
                    outstanding_height,
                    outstanding_arrangement,
                    after=None,
                    routing_seconds=0.0,
                )
        if telemetry is not None:
            telemetry["alns_choices"] = float(len(session.choices))
            telemetry["alns_applied"] = float(session.applied)
            telemetry["alns_evaluations"] = float(evaluations)
            telemetry["alns_routing_seconds"] = session.routing_seconds
            telemetry["alns_operators"] = operator_tally(session)
            telemetry["alns_window_solves"] = float(window_solves)
            telemetry["alns_window_accepted"] = float(window_accepted)
            telemetry["alns_window_seconds"] = window_seconds
            telemetry["alns_encode_errors"] = float(window_encode_errors)
            telemetry["alns_skipped_no_goods"] = float(window_skipped_no_goods)
            # The names spec 5.3.2 asks for on a REFUSED freeform row, beside the
            # `alns_*` names the CLEAN rows already use.
            telemetry["evaluations"] = float(evaluations)
            telemetry["distinct_assignments"] = float(len(routed_assignments))
            telemetry["stale_draws"] = float(stale_draws)
            telemetry["window_solves"] = float(window_solves)
            telemetry["window_accepted"] = float(window_accepted)
        # `stats["route_backend"]` is stamped in `lay_out`, where none of these
        # locals exist, so the operator telemetry is stamped here instead --
        # guarded, because a sweep that refuses has no placement to carry it.
        if best is not None:
            best.stats["alns_choices"] = float(len(session.choices))
            best.stats["alns_applied"] = float(session.applied)
            best.stats["alns_evaluations"] = float(evaluations)
            best.stats["alns_routing_seconds"] = session.routing_seconds
            best.stats["alns_operators"] = operator_tally(session)
            best.stats["alns_window_solves"] = float(window_solves)
            best.stats["alns_window_accepted"] = float(window_accepted)
            best.stats["alns_window_seconds"] = window_seconds
            best.stats["alns_encode_errors"] = float(window_encode_errors)
            best.stats["alns_skipped_no_goods"] = float(window_skipped_no_goods)
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


def _window_candidate_seconds(*, dearest_remainder_s: float) -> float:
    """What one windowed retry costs, measured rather than tuned.

    A full retry is charged the dearest completed candidate, pack included.  A
    window replaces the pack with a bounded solve and leaves everything after it
    -- preparation, routing, power, finalize, validate -- exactly where it was,
    so its charge is that bounded solve plus the measured remainder.  Like
    `_room_for_another`'s `candidate_s`, this is a measurement: a fixed constant
    cannot span a corpus running from one to 955 machines.

    ``dearest_remainder_s`` is the largest post-pack span ONE candidate really
    ran, not `dearest_candidate_s - dearest_pack_s` (Ruling AD).  That
    difference subtracts two maxima that need not belong to the same candidate,
    so a sweep holding one slow-to-pack candidate and one slow-to-route one
    collapses it toward zero and admits a repair that then overruns the wall.

    No clock is read here.  The charge is a pure function of a measurement the
    sweep already keeps, and `_room_for_another` is the one that compares it
    against the wall.
    """
    return C_WINDOW_SECONDS + max(0.0, dearest_remainder_s)


def _height_seed(strips: list[Strip]) -> int:
    area = sum(w * h for w, h in map(_box, strips))
    tall = max((h for _w, h in map(_box, strips)), default=1)
    return max(tall, int(math.isqrt(max(1, area))))


def _candidate_height_box(strip: Strip) -> tuple[int, int]:
    """Exclude lateral staged-static feedback from the fixed height schedule."""
    width, height = _box(strip)
    if strip.cargo_domain is CargoDomain.REQUIRES_SPRAY:
        width -= max(0, strip.west_channel - _COATER_WEST_CHANNEL)
    return width, height


def _candidate_heights(strips: list[Strip]) -> list[int]:
    """Heights to sweep, since ``W * H`` is too weak a form to minimise directly."""
    boxes = tuple(_candidate_height_box(strip) for strip in strips)
    area = sum(width * height for width, height in boxes)
    tall = max((height for _width, height in boxes), default=1)
    h0 = max(tall, int(math.isqrt(max(1, area))))
    out = {max(tall, int(h0 * f)) for f in (0.6, 0.8, 1.0, 1.25, 1.6)}
    return sorted(out)


def _minimum_pack_width(strips: list[Strip], height: int) -> int:
    """Return a proof-valid width floor for any packing at one height."""
    boxes = tuple(map(_box, strips))
    area = sum(width * box_height for width, box_height in boxes)
    widest = max((width for width, _box_height in boxes), default=1)
    return max(widest, (area + height - 1) // height)


def _band_policy_candidate_heights(
    strips: list[Strip],
    policy: BandPolicy,
) -> tuple[int, ...]:
    """Keep the measured order while reserving one proved fixed-band boundary.

    THE WITNESS IS THE GREEDY SEED'S WIDTH, not `_minimum_pack_width`'s.  The
    latter is a valid area-based LOWER bound and it is far below anything the
    packer builds: 92 against 258 on `universe-matrix/no-proliferator`, where a
    98x166 extent fits the 200-segment band rotated and a 264x162 extent fits
    nothing.  Height 160 therefore survived the filter, its greedy seed was
    rejected at the pre-pack gate, and one of five candidate slots was spent
    proving that (R1 §2).  With the seed's width the boundary height 154 replaces
    it, and its 258x154 pack packs and routes (R1 §3, E1).

    `max(...)` rather than the seed alone: `_minimum_pack_width` is still a proof
    and can exceed the seed for a height the shelf pack seats badly, and taking
    the larger of the two keeps the filter no weaker than it was.

    This is a WIDTH witness at the SCHEDULED height; the sweep's own seed gate
    filters on `strip_outline(seed)`, whose height is the shelf's realised one.
    The two are different questions and this function answers only the first.
    """
    seeds = {height: _greedy_pack(strips, height) for height in _candidate_heights(strips)}
    ordered = tuple(sorted(seeds, key=lambda height: (seeds[height].width, height)))
    envelope = finalize.band_policy_search_envelope(
        policy,
        perimeter=_ENTRY_RING,
    )
    return envelope.reserve_boundary_height(
        ordered,
        minimum_width_for_height={
            height: max(_minimum_pack_width(strips, height), seeds[height].width)
            for height in ordered
        },
    )
