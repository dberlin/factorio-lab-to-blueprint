"""Shared prepared routing geometry and attempt-local physical routing.

Search strategies supply selected strip geometry or a canvas of placed blocks.
This owner prepares immutable compatibility facts and fresh mutation workspaces;
relaxed capacity negotiation and placement/search selection stay with consumers.
"""

from __future__ import annotations

import heapq
import math
import os
import sys
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
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from enum import Enum
from fractions import Fraction
from functools import cache, lru_cache
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal, NamedTuple, cast

import numpy as np
from ortools.linear_solver import pywraplp
from ortools.sat.python import cp_model

from flab2bp.dsp import catalog, codec, colliders, params, planet, rules, splitter_ports
from flab2bp.indexed import Nets, PortReservations, StakedPaths, UnionFind
from flab2bp.indexed.staked_paths import StakedPathSnapshot
from flab2bp.layout import (
    finalize,
    geometric_router,
    junction,
    last_mile,
    physical_flow,
    projection_world,
    slots,
)
from flab2bp.layout.band_policy import BandPolicy
from flab2bp.layout.base import Facing, NoValidLayout, PlacedBuilding, Placement
from flab2bp.layout.buildings import Buildings, MutableBuildings, bounds_of
from flab2bp.layout.buildings import Kind as BuildingKind
from flab2bp.layout.coater_mode import coater_mode
from flab2bp.layout.geometric_world import GeometricWorld
from flab2bp.layout.piling import LaneLoad, MergePlan, PilerPlan, plan_merges
from flab2bp.layout.projection_world import FlatScreen
from flab2bp.layout.route_feedback import (
    Cell,
    DetailedRouteResult,
    DetailedRouteStatus,
    LastMileReport,
    LogicalNetId,
    NetFailure,
    NetId,
    NetRole,
    RouteFailureKind,
    RouteSettlement,
    RouteSettlementCancelled,
    RouteSettlementCompleted,
    RouteSettlementCrashed,
    RouteSettlementRefused,
)
from flab2bp.layout.route_primitives import RouteOwnership, RoutePrimitives
from flab2bp.layout.routing_proposals import Deadline as _GeometricDeadline
from flab2bp.layout.routing_proposals import inside as _inside_route_box
from flab2bp.layout.routing_proposals import overhead_path
from flab2bp.layout.strip_variants import CargoDomain, StripFamilyId, StripInstanceId
from flab2bp.spec import BuildSpec

if TYPE_CHECKING:
    from flab2bp.layout.geometry_memo import MemoStats
    from flab2bp.layout.strip_variants import (
        LaneAttachmentPlan,
        LanePlan,
        LanePortDockPlan,
        LaneSorterAttachment,
        StripVariant,
        StripVariantId,
    )

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

#: Explicit synthetic-save defaults. Production callers pass their complete
#: URL-derived rules instead of inheriting an independent routing height cap.
_DEFAULT_BELT_RULES = catalog.BeltAltitudeRules(
    max_z=catalog.belt_max_z(catalog.DEFAULT_LAB_LEVEL),
    vertical_construction=True,
    storage_level=catalog.DEFAULT_STORAGE_LEVEL,
    lab_level=catalog.DEFAULT_LAB_LEVEL,
    from_url=False,
)


@lru_cache(maxsize=128)
def spherical_overflight_limit(model_index: int, z: Fraction) -> int:
    """First lattice plane above every projected collider corner.

    A flat top is insufficient near an integer plane: a corner has greater
    planetary radius than the collider's centre. Radial extent is invariant
    under latitude and yaw, so this sufficient clearance needs no frame guess
    or arbitrary padding. Target colliders inherit the preview rotation and
    ignore their stored local quaternion, exactly as `target_boxes` does.
    """
    boxes = colliders.build_colliders(model_index)
    if not boxes:
        return math.floor(z) + 1
    position, _ = colliders.preview_pose(0.0, 0.0, float(z), 0.0)
    base_radius = math.hypot(*position)
    outer_radius = max(
        math.hypot(
            abs(centre[0]) + half[0],
            abs(base_radius + centre[1]) + half[1],
            abs(centre[2]) + half[2],
        )
        for centre, half, _ in boxes
    )
    bound = float(z) + (
        outer_radius - base_radius + colliders.BELT_PROBE_RADIUS - colliders.BELT_PROBE_LIFT
    ) * float(catalog.BELT_Z_PER_WORLD_UNIT)
    return math.floor(bound) + 1


def _crossing_ban_levels(b: PlacedBuilding) -> tuple[int, ...]:
    """Reserve the band below a building's spherical collider envelope.

    A flat top can clear the belt probe while a projected corner still hits
    it. Use the shared radial clearance, which is independent of latitude and
    yaw. Higher levels remain available when the save's belt rules permit them.
    """
    return tuple(range(max(0, spherical_overflight_limit(b.model_index, b.z))))


#: Rip-up-and-reroute iterations before a placement is declared unroutable.
RRR_MAX = 8

#: Large prepared problems first share ordinary work across all nets. Callers
#: that can repack return after one round; final composition cannot repack.
_SINGLE_ROUND_NETS = 64

#: Exact commit validation can expose a different static collision after a
#: rejected route takes its next-best path. Keep that local convergence bounded;
#: unlike a full RRR round, each pass touches only paths with new exact evidence.
_COMMIT_REPAIR_PASSES = 3
#: The smallest cluster that describes a RELATIVE placement.  One strip has no
#: relation to forbid, so a relaxed proof over it excludes nothing; `_pack`'s
#: cluster cut anchors on the first strip and constrains the rest against it.
_RELATION_STRIP_PAIR = 2


#: Deterministic work allowed only for choosing among already rank-optimal port
#: access assignments. The ranked solution remains the safe fallback; this
#: bounded polish must never turn a preparation step into an unbounded search.
_ACCESS_TIE_DETERMINISTIC_WORK = 0.05

#: Deterministic work allowed to each per-rank `maximize` in the corridor
#: matcher.  The rank solves decide which claims are served, so they get
#: far more than the tie-break; on the mall profile (2026-09-05) the
#: uncapped solves were 71 of 100 s and the candidate was then discarded
#: at the deadline.
_ACCESS_RANK_DETERMINISTIC_WORK = 2.0
#: Validate/cut rounds the matcher runs before returning no assignment.
_ACCESS_CUT_ROUNDS = 8

#: Initial reachable options retained by a goal-driven probe. This is a cheap
#: first pass, not exhaustion: missing claims expand the unprobed alternatives
#: of their local cell-conflict closure before reservation validation. Boundary
#: probes retain their existing exhaustive enumeration.
_PORT_ACCESS_PROBE_KEEP = 2


#: Rip-up rounds with no improvement in the failure count before giving up.
#:
#: Three, not one: pressure grows geometrically (``0.5 * 1.6**it``), so a round
#: that buys nothing at low pressure can still break a deadlock two rounds
#: later. Measured on the magnetic-ring chain, where routing a pack that cannot
#: be wired was the strategy's single largest cost.
_RRR_STALE_ROUNDS = 3

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


#: Per-query work cap: newly prepared cells plus processed active intervals.
#: Exhaustion refuses the route; it never relaxes physical admission.
_MAX_EXPANSIONS = 200_000

#: Total A* expansions across ALL nets and ALL rip-up rounds of one routing
#: pass.  `_MAX_EXPANSIONS` bounds a single search; this bounds their product,
#: which is what actually runs away at scale.
_ROUTING_BUDGET = 2_000_000

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
    #: Has the flanked output's drain lane been pushed to the OUTERMOST south
    #: row, past sorter reach, because the south INPUT lanes filled every
    #: sorter-reachable row?
    #:
    #: True moves the drain to ``first_row_below_band + len(in_below)`` and
    #: starts the south inputs at offset 0; False keeps the pre-2026-09-07 map
    #: exactly -- drain innermost, inputs pushed out by ``len(out_lanes)``.
    #:
    #: The drain may have that row because it carries NO SORTER: ``_flank_lane``
    #: puts the only sorter on the machine's east face and runs a gap belt south
    #: into the lane.  ``_side_lane_caps`` counts a CONTIGUOUS run outward from
    #: the band, so the row past ``below_cap`` has no ``attachable_columns`` at
    #: all -- fine for a drain, useless to an input.  ``sorter_span`` therefore
    #: returns 0 for it BY DESIGN, and ``_machines_without_poses`` already skips
    #: flanked strips.
    #:
    #: Derived once, in ``_logical_strip_plans``, by
    #: ``strip_variants._drain_moves_outermost``: flanked, ``below_cap > 0``,
    #: and ``len(in_below) == below_cap``.  A spec that never needed the freed
    #: row keeps today's seating and today's area, which is the user's ruling in
    #: spec §9 R2.  A side with NO reachable row is not "filled" -- ``0 == 0``
    #: would say it was, and there is nothing to push the drain past.
    #:
    #: IT ALSO CAPS THE FAMILY AT ONE MACHINE PER STRIP, in
    #: ``generate_strip_families``, and the reason is a belt column rather than
    #: a rate: ``_flank_lane``'s gap belt runs down the column east of its OWN
    #: machine, so with the drain outermost it crosses every south input lane
    #: and ``geom.belt_single_occupancy`` convicts the result.  Only the last
    #: machine in a strip has a clear gap column.  That cap turns
    #: ``universe-matrix#37`` into 15 one-machine strips.  It used
    #: to refuse there, on ``_fanout_shortfall``'s theory that each consumer taps
    #: a different TILE of the producer lane; that theory was measured wrong --
    #: nets sharing a source lane branch off each other's committed paths
    #: (``_route``'s ``same_src``), and a 10-tile lane wired all twelve of its
    #: consumers.  See ``docs/superpowers/specs/2026-09-07-lane-fanout-design.md``
    #: section 2, and section 4 for the two blockers behind it.
    drain_outermost: bool = False
    family_id: StripFamilyId | None = None
    machine_start: int = 0
    west_channel: int = WEST_CHANNEL
    #: Output-side tiles reserved for inline Automatic Pilers.
    tail_extension: int = 0
    #: Per-output-lane Automatic Piler plans owned by this strip.
    pilers: tuple[PilerPlan, ...] = ()

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

    @property
    def _south_input_offset(self) -> int:
        """Rows between the band and the first south INPUT lane.

        The output lanes sit between the two unless :attr:`drain_outermost` has
        moved the flanked drain past them, in which case the inputs start
        against the band and the drain takes the row after the last of them.
        The two halves of that swap are here and in :meth:`row_of_output`, and
        they must move together or a sorter is drawn to a row the belt is not
        on.
        """
        return 0 if self.drain_outermost else len(self.out_lanes)

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
            row = self.first_row_below_band + self._south_input_offset + index
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
            return self.first_row_below_band + self._south_input_offset + self.in_below.index(lane)
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
            # `drain_outermost` is set only on a FLANKED strip, so a belt-port
            # host keeps `first_row_below_band + k` whatever its lane counts:
            # its dock run is drawn from the machine's own port and does not get
            # to sit past a sorter's reach.
            drain_offset = len(self.in_below) if self.drain_outermost else 0
            return self.first_row_below_band + drain_offset + k
        return self.machine_row + self._output_attachment_plan(k).lane_y

    @property
    def output_lane_start(self) -> int:
        """First drain column carrying product from the selected attachment geometry."""
        # Flanked product enters at the first machine's east gap. Everything
        # west of that inlet is unused and would add a spurious second feeder.
        return self.pw - 1 if self.flank_outputs else 0

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


#: strip clearance geometry -> the W3 machine/Coater relations it materializes.
#:
#: ``_selected_strips`` asks this for every sprayed strip in every anneal state
#: (76k calls, 14.9 s of a 93 s ``mall`` run) and the answer is a pure function
#: of the values read below, so nearly every ask repeats an earlier one.  The
#: key holds those values DIRECTLY -- ``machine_row`` and ``row_of_input`` are
#: derived properties whose own inputs span ``lane_plan``, ``flank_outputs``,
#: ``in_above``, ``in_below``, ``out_lanes``, ``ph`` and ``attachment_plan``, so
#: caching the two cheap derived numbers is both exact and narrower than
#: re-deriving that whole closure.  What it buys is the ``machines * lanes``
#: ``StagedStaticClearanceKey`` constructions, which is the actual cost.
#:
#: ``cargo_domain`` and ``physical_variant`` are absent because they gate the
#: memo rather than feed it: an unsprayed or unrealized strip returns the empty
#: set without ever reaching a key.  Bounded like the geometry memo above:
#: clearing on overflow costs recomputation and keeps the answer exact.
_STAGED_CLEARANCE_KEYS_MEMO: dict[tuple[object, ...], frozenset[StagedStaticClearanceKey]] = {}
_STAGED_CLEARANCE_KEYS_MEMO_LIMIT = 65536


def _staged_static_clearance_keys(
    strip: Strip,
) -> frozenset[StagedStaticClearanceKey]:
    """Physical W3 machine/Coater relations this strip can materialize.

    Memoized on :data:`_STAGED_CLEARANCE_KEYS_MEMO`.
    """
    if coater_mode().is_node:
        # No addon rides this strip's channel under a node arm, so there is no
        # machine/Coater relation for the channel to clear.
        #
        # This empty return is also what keeps `_COATER_WEST_CHANNEL` and the
        # freeform channel lift below INERT under `placed` without a further
        # guard: the lift maxes over these relations and there are none.  Both
        # stay, because `off` is the retained A/B control for one release and
        # is the only arm that reaches them.
        return frozenset()
    if strip.cargo_domain is not CargoDomain.REQUIRES_SPRAY or strip.physical_variant is None:
        return frozenset()
    if not strip.in_lanes or strip.machines <= 0:
        # The comprehension below never evaluates its element expression here,
        # so ``machine_row`` is never consulted -- and a strip with no legal
        # slot pose would raise if the key computation consulted it eagerly.
        return frozenset()
    input_rows = tuple(strip.row_of_input(item) for item in strip.in_lanes)
    memo_key = (
        strip.item_id,
        strip.model_index,
        strip.mw,
        strip.mh,
        strip.yaw,
        strip.pw,
        strip.machines,
        strip.west_channel,
        strip.machine_row,
        strip.in_lanes,
        input_rows,
    )
    cached = _STAGED_CLEARANCE_KEYS_MEMO.get(memo_key)
    if cached is not None:
        return cached
    keys = _staged_static_clearance_keys_uncached(strip)
    if len(_STAGED_CLEARANCE_KEYS_MEMO) >= _STAGED_CLEARANCE_KEYS_MEMO_LIMIT:
        _STAGED_CLEARANCE_KEYS_MEMO.clear()
    _STAGED_CLEARANCE_KEYS_MEMO[memo_key] = keys
    return keys


def _staged_static_clearance_keys_uncached(
    strip: Strip,
) -> frozenset[StagedStaticClearanceKey]:
    """Physical W3 machine/Coater relations this strip can materialize."""
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
    indices: Collection[int] | None = None,
) -> tuple[tuple[int, PlacedBuilding], ...]:
    """Retain every unknown pair and omit only proved-clean same-strip pairs."""
    return tuple(
        (index, peer)
        for index in (range(len(buildings)) if indices is None else sorted(indices))
        for peer in (buildings[index],)
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


def _strip_output_lane_id(strip: Strip, lane_index: int) -> str:
    """Return the selected logical id for one output lane."""
    planned = next(
        (
            plan.lane
            for plan in strip.attachment_plan
            if plan.lane.kind == "output" and plan.lane.side_index == lane_index
        ),
        None,
    )
    if planned is None:
        planned = next(
            (
                plan.lane
                for plan in strip.port_dock_plan
                if plan.lane.kind == "output" and plan.lane.side_index == lane_index
            ),
            None,
        )
    return planned.lane_id if planned is not None else f"output:{lane_index}"


def _producer_output_stack(
    strip: Strip,
    lane_index: int,
    item: str,
    rate: Fraction,
    sorter_tiers: tuple[int, ...],
    sorter_stacks: _SorterStacks,
    lane_stacks: _LaneStacks,
) -> int:
    """Return the stack the selected producer mechanism puts on one lane."""
    if strip.takes_belt_ports:
        return 1

    if strip.flank_outputs:
        probe = slots.probe_building(strip.item_id, strip.yaw)
        attachments = slots.attachable_rows(probe, strip.pw - 1)
        claimed = {
            attachment.slot
            for lane in strip.in_above
            for attachment in strip._input_attachment_plan(lane[0]).attachments
        }
        selected: slots.Attachment | None = None
        for _ in range(lane_index + 1):
            selected = next(
                (
                    attachments[row]
                    for row in sorted(attachments, reverse=True)
                    if attachments[row].slot not in claimed
                ),
                None,
            )
            if selected is None:
                return 1
            claimed.add(selected.slot)
        assert selected is not None
        span = selected.span
    else:
        span = strip._output_attachment_plan(lane_index).attachments[0].span

    tier, _count = _pick_sorter(
        rate,
        span,
        1,
        sorter_tiers,
        stacks=sorter_stacks,
        min_place_stack=lane_stacks.out_of(item),
    )
    return sorter_stacks.place(tier)


def _strip_merge_plans(
    spec: BuildSpec,
    groups: Mapping[str, _Group],
    strips: Sequence[Strip],
) -> tuple[
    dict[str, tuple[int, int]],
    dict[tuple[str, str, CargoDomain], MergePlan],
]:
    """Rebuild deterministic per-sink merge plans from physical strip order."""
    if not spec.piler_unlocked or spec.belt_stack <= 1:
        return {}, {}

    lane_owners: dict[str, tuple[int, int]] = {}
    loads_by_sink: dict[tuple[str, str, CargoDomain], list[LaneLoad]] = defaultdict(list)
    sorter_tiers = _sorter_tiers_for(spec)
    sorter_stacks = _sorter_stacks_for(spec)
    lane_stacks = _lane_stacks_for(spec)
    for strip_ordinal, strip in enumerate(strips):
        made = groups[strip.group_key].outputs
        for lane_index, (item, destinations, cargo_domain) in enumerate(strip.out_lanes):
            demand = strip.machines * made.get(item, Fraction(0))
            if demand <= 0:
                continue
            pre_piler_stack = _producer_output_stack(
                strip,
                lane_index,
                item,
                made[item],
                sorter_tiers,
                sorter_stacks,
                lane_stacks,
            )
            lane_id = f"{strip_ordinal}:{_strip_output_lane_id(strip, lane_index)}"
            lane_owners[lane_id] = (strip_ordinal, lane_index)
            for sink in _dests(destinations) or ("",):
                loads_by_sink[item, sink, cargo_domain].append(
                    LaneLoad(
                        lane_id=lane_id,
                        strip_ordinal=strip_ordinal,
                        demand=demand,
                        stack=pre_piler_stack,
                    )
                )

    plans = {
        key: plan_merges(
            loads,
            lane_capacity=spec.lane_capacity,
            max_stack=spec.max_stack,
            sink_pick_stack=spec.max_stack if not key[1] else spec.sorter_pick_stacks[-1],
        )
        for key, loads in sorted(
            loads_by_sink.items(),
            key=lambda entry: (entry[0][0], entry[0][1], entry[0][2].value),
        )
    }
    return lane_owners, plans


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


def _relative_rigid_frame_pose(
    building: colliders.Placed,
    origin: colliders.Placed,
    materialized_origin: colliders.Placed,
    *,
    rotated: bool,
) -> colliders.Placed:
    """Apply one finalizer frame to a pose relative to its materialized origin."""
    delta_x = building.x - origin.x
    delta_y = building.y - origin.y
    if rotated:
        delta_x, delta_y = -delta_y, delta_x
    return replace(
        building,
        x=materialized_origin.x + delta_x,
        y=materialized_origin.y + delta_y,
        z=materialized_origin.z + building.z - origin.z,
        yaw=(building.yaw - 90.0) % 360.0 if rotated else building.yaw,
    )


def _static_collider_span(building: PlacedBuilding) -> float:
    try:
        return max(catalog.collider_span(building.item_id, building.yaw))
    except KeyError, ValueError:
        return max(building.width, building.height) * colliders.GRID_ARC


class _ColliderGeometry(NamedTuple):
    pose: colliders.Placed
    queries: tuple[colliders.Box, ...]
    targets: tuple[colliders.Box, ...]


def _collider_geometry(pose: colliders.Placed) -> _ColliderGeometry:
    frame = colliders.flat_pose(pose.x, pose.y, pose.z, pose.yaw)
    return _ColliderGeometry(
        pose,
        tuple(colliders._query_boxes(pose, *frame)),
        tuple(colliders.target_boxes(pose, *frame)),
    )


def _building_collider_hits(
    buildings: Sequence[PlacedBuilding],
    candidate: PlacedBuilding,
    *,
    indices: Sequence[int] | None = None,
    geometry: dict[int, _ColliderGeometry] | None = None,
) -> tuple[int, ...]:
    """Exact static build-collider hits for one proposed non-belt object."""
    candidate_span = _static_collider_span(candidate)
    candidate_x = candidate.x + (candidate.width - 1) / 2.0
    candidate_y = candidate.y + (candidate.height - 1) / 2.0
    candidate_geometry: _ColliderGeometry | None = None
    hits: set[int] = set()
    candidates = indices
    if candidates is None:
        candidates = (
            sorted((*buildings.machines(), *buildings.by_kind(BuildingKind.OTHER)))
            if isinstance(buildings, MutableBuildings)
            else range(len(buildings))
        )
    for index in candidates:
        building = buildings[index]
        if catalog.is_belt(building.item_id) or catalog.is_sorter(building.item_id):
            continue
        obstacle_span = _static_collider_span(building)
        radius = (candidate_span + obstacle_span) / (2.0 * colliders.GRID_ARC) + 3.0
        obstacle_x = building.x + (building.width - 1) / 2.0
        obstacle_y = building.y + (building.height - 1) / 2.0
        if not math.hypot(candidate_x - obstacle_x, candidate_y - obstacle_y) <= radius:
            continue
        if candidate_geometry is None:
            candidate_geometry = _collider_geometry(_collision_pose(candidate))
        pose = _collision_pose(building)
        obstacle_geometry = None if geometry is None else geometry.get(index)
        if obstacle_geometry is None or obstacle_geometry.pose != pose:
            obstacle_geometry = _collider_geometry(pose)
            if geometry is not None:
                geometry[index] = obstacle_geometry
        # Only pairs involving the proposed building affect this answer. The
        # all-pairs collider grid also tested every obstacle against every
        # other obstacle, then discarded those results. Keep both directions:
        # a prefab's query rotation need not match its target-box rotation.
        if colliders.any_box_overlap(
            candidate_geometry.queries, obstacle_geometry.targets
        ) or colliders.any_box_overlap(obstacle_geometry.queries, candidate_geometry.targets):
            hits.add(index)
    return tuple(sorted(hits))


def _coater_keepout_hits(
    buildings: Sequence[PlacedBuilding],
    candidate: PlacedBuilding,
    *,
    max_obstacle_span: float | None = None,
) -> tuple[int, ...]:
    """Objects intersecting the coater body or its observed lateral keepout.

    A user-reported game paste rejects a coater at ``(13, 7)`` beside an
    Assembling Machine whose 3x3 tile box begins at ``(13, 8)``.  The flat OBB
    lower bound leaves a narrow gap, but the full coater preview visibly clips
    the machine and the paste reports ``Collide with other object``.  Reserve
    the one-cell lateral row around the coater's real oriented 3x1 body; do not
    inflate its long axis, where its predecessor and successor must stand.

    STAYS under a node arm, and is asked TWICE: once from
    :func:`_coater_node_site_is_clear`, to reject a site whose addon body would
    clip a machine, and once from :func:`_place_coaters` on the seat it finally
    commits.  A belt addon's collider reaches machines a belt does not, so
    "the run has free belt ground" is not the same question.
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

    candidate_span = _static_collider_span(candidate)
    candidate_x = candidate.x + (candidate.width - 1) / 2.0
    candidate_y = candidate.y + (candidate.height - 1) / 2.0
    hits: set[int] = set()
    collider_candidates: list[tuple[int, PlacedBuilding]] = []
    candidates: Sequence[int]
    if isinstance(buildings, MutableBuildings) and max_obstacle_span is not None:
        # Every old circular broad-phase hit has its footprint centre inside
        # this square. Union the independent lateral keepout, then retain all
        # old exact predicates below. The maximum is computed once per seating
        # pass and includes every coater that can be appended during that pass.
        radius = (candidate_span + max_obstacle_span) / (2.0 * colliders.GRID_ARC) + 3.0
        candidates = buildings.in_box(
            min(x0, math.floor(candidate_x - radius)),
            min(y0, math.floor(candidate_y - radius)),
            max(x1, math.ceil(candidate_x + radius)),
            max(y1, math.ceil(candidate_y + radius)),
        )
    else:
        candidates = (
            sorted((*buildings.machines(), *buildings.by_kind(BuildingKind.OTHER)))
            if isinstance(buildings, MutableBuildings)
            else range(len(buildings))
        )
    for index in candidates:
        building = buildings[index]
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


@lru_cache(maxsize=4096)
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
    *,
    tower: catalog.Building | None = None,
) -> tuple[tuple[int, int, int], ...]:
    """Exact doubled-coordinate power discs available during detailed routing.

    ``tower`` is the build's chosen power building -- ``canvas.power_building``
    at every caller inside a layout run.  It defaults to the Tesla Tower so a
    caller that has no canvas reads exactly the radius it always read.
    """
    if tower is None:
        tower = catalog.power_tower_building(catalog.DEFAULT_POWER_TOWER)
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


JunctionOffsetKey = tuple[int, int, int, int, float, Fraction, int]

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
    levels: int,
) -> frozenset[Cell]:
    """Exact relative Splitter bans for one immutable obstacle pose."""
    return _cancellable_junction_ban_offsets(
        item_id, model_index, width, height, yaw, z, levels, None
    )


def _cancellable_junction_ban_offsets(
    item_id: int,
    model_index: int,
    width: int,
    height: int,
    yaw: float,
    z: Fraction,
    levels: int,
    cancelled: Callable[[], bool] | None,
) -> frozenset[Cell]:
    """Compute one uncached complete offset set while polling its caller."""
    key: JunctionOffsetKey = (item_id, model_index, width, height, yaw, z, levels)
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
    obstacles = (obstacle,)
    even_top = _splitter_stack_geometry(0, 0, 0)[-1]
    odd_top = _splitter_stack_geometry(0, 0, 1)[-1]
    for x in range(
        math.floor(centre_x - radius),
        math.ceil(centre_x + radius) + 1,
    ):
        if cancelled is not None and cancelled():
            raise _PreparationDeadline
        for y in range(
            math.floor(centre_y - radius),
            math.ceil(centre_y + radius) + 1,
        ):
            if cancelled is not None and cancelled():
                raise _PreparationDeadline
            for anchor in range(0, levels, 2):
                if cancelled is not None and cancelled():
                    raise _PreparationDeadline
                # Every higher stack reuses this model-38 support. Test each
                # distinct member once, retaining model 40's different top.
                even_hit = bool(
                    _building_collider_hits(
                        obstacles, replace(even_top, x=x, y=y, z=Fraction(anchor))
                    )
                )
                if even_hit:
                    banned.add((x, y, anchor))
                if anchor + 1 < levels and _building_collider_hits(
                    obstacles, replace(odd_top, x=x, y=y, z=Fraction(anchor))
                ):
                    banned.add((x, y, anchor + 1))
                if even_hit:
                    banned.update((x, y, level) for level in range(anchor + 2, levels))
                    break
    if cancelled is not None and cancelled():
        raise _PreparationDeadline
    result = frozenset(banned)
    _JUNCTION_BAN_OFFSET_CACHE[key] = result
    return result


def _prepared_junction_ban(
    buildings: Sequence[PlacedBuilding],
    power_sites: Sequence[tuple[int, int]],
    *,
    belt_rules: catalog.BeltAltitudeRules = _DEFAULT_BELT_RULES,
    projection_frames: Sequence[_JunctionProjectionFrame] = (),
    junction_bounds: tuple[int, int, int, int] | None = None,
    cancelled: Callable[[], bool] | None = None,
    cache: _StagedStaticCache | None = None,
    tower: catalog.Building | None = None,
) -> frozenset[Cell]:
    """Precompute exact flat and projected Splitter refusals.

    ``tower`` is the build's chosen power building, so the reserved sites are
    given the footprint that will actually stand on them.  It defaults to the
    Tesla Tower for callers outside a layout run.
    """
    if tower is None:
        tower = catalog.power_tower_building(catalog.DEFAULT_POWER_TOWER)
    if cancelled is not None and cancelled():
        raise _PreparationDeadline
    indexed = buildings if isinstance(buildings, MutableBuildings) else Buildings(buildings)
    obstacles: list[PlacedBuilding] = []
    for index in sorted((*indexed.machines(), *indexed.by_kind(BuildingKind.OTHER))):
        if cancelled is not None and cancelled():
            raise _PreparationDeadline
        obstacles.append(buildings[index])
    for x, y in power_sites:
        if cancelled is not None and cancelled():
            raise _PreparationDeadline
        obstacles.append(
            PlacedBuilding(
                item_id=tower.item_id,
                model_index=tower.model_index,
                x=x,
                y=y,
                width=tower.width,
                height=tower.height,
            )
        )

    banned: set[Cell] = set()
    levels = math.floor(belt_rules.max_z) + 1
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
            levels,
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
    for index in indexed.by_item(catalog.SPRAY_COATER_ID):
        if cancelled is not None and cancelled():
            raise _PreparationDeadline
        coaters.append((index, buildings[index]))
    if coaters and projection_frames:
        if junction_bounds is None:
            raise ValueError("projected junction bans require fixed junction bounds")
        for frame_ban in _projected_coater_junction_bans_by_frame(
            coaters,
            projection_frames,
            junction_bounds,
            belt_rules=belt_rules,
            already_banned=banned,
            splitter_index=len(buildings),
            cancelled=cancelled,
        ):
            banned.update(frame_ban)
    if cancelled is not None and cancelled():
        raise _PreparationDeadline
    return frozenset(banned)


@dataclass(frozen=True, slots=True)
class _SorterStacks:
    """What each sorter tier promises about cargo stacks, by catalog item id.

    Built from the spec's per-tier rows, so it survives whatever order the
    spec listed its tiers in; an absent tier promises 1, which is what every
    tier promises on a save that does not stack.
    """

    pick_by_tier: Mapping[int, int] = field(default_factory=dict)
    place_by_tier: Mapping[int, int] = field(default_factory=dict)

    def pick(self, tier: int) -> int:
        return self.pick_by_tier.get(tier, 1)

    def place(self, tier: int) -> int:
        return self.place_by_tier.get(tier, 1)


#: Every tier at stack 1: the answer for an unstacked save, and the default.
_NO_SORTER_STACKS = _SorterStacks()


@dataclass(frozen=True, slots=True)
class _LaneStacks:
    """The stack each item's lanes are planned at, one map per SIDE of a strip.

    Two maps rather than one, because one number per item cannot describe both
    lanes of an item that is BOTH belted in and produced (universe-matrix's
    hydrogen is the corpus shape).  Its entry lane carries ``min(bus, place)``
    -- a merge is judged at its minimum -- while its output lane carries
    ``place``, because a lane leaving a machine on a sorter is produced
    whatever the bus also does.  Ask the producer's sorter for the entry
    lane's number and a tier that places 2 is accepted for a lane that
    promises 3, which is a lane built a tier too small for what it carries.

    An absent item is unstacked, which is every item on a save without `ist`.
    """

    #: Item -> the stack of the lane a CONSUMER picks from.
    consumed: Mapping[str, int] = field(default_factory=dict)
    #: Item -> the stack of the lane a PRODUCER places onto.
    produced: Mapping[str, int] = field(default_factory=dict)

    def into(self, item: str) -> int:
        """The lane a sorter picks off, feeding a machine or a junction."""
        return self.consumed.get(item, 1)

    def out_of(self, item: str) -> int:
        """The lane a sorter places onto, leaving a machine."""
        return self.produced.get(item, 1)


#: Every lane unstacked: the answer for a save without `ist`, and the default.
_NO_LANE_STACKS = _LaneStacks()


@dataclass
class _Canvas:
    """Buildings under construction, plus what occupies each cell."""

    #: Complete save technology: ceiling, slope unlock and stack admission.
    belt_rules: catalog.BeltAltitudeRules = _DEFAULT_BELT_RULES
    #: Integer lattice planes at or below the save's exact ceiling.
    levels: int = field(init=False)
    #: Sorter tiers this save can build, slowest first.  Every sorter the
    #: emitter picks comes from this tuple; see :func:`_pick_sorter`.
    sorter_tiers: tuple[int, ...] = catalog.SORTER_TIERS
    #: What each of those tiers may promise about cargo stacks.
    sorter_stacks: _SorterStacks = _NO_SORTER_STACKS
    #: The stack each item's lanes are planned at, so an emitter can ask for a
    #: sorter that keeps the promise the plan made (design 5.3).
    lane_stacks: _LaneStacks = _NO_LANE_STACKS
    #: The power building this build stands on every planned power site.
    #:
    #: One record, resolved once from ``BuildSpec.power_tower_item_id`` in
    #: :func:`_prepare_routing_problem`, carries everything the power passes
    #: ask: item id, model index, footprint, ``cover_radius`` and
    #: ``connect_distance``.  The planner's arithmetic was already generic over
    #: those; only WHICH record it read was fixed.  The default is the Tesla
    #: Tower, so a canvas built without a spec -- every synthetic test canvas,
    #: and the hierarchy composer's -- behaves exactly as it did before the
    #: choice existed.
    power_building: catalog.Building = field(
        default_factory=lambda: catalog.power_tower_building(catalog.DEFAULT_POWER_TOWER)
    )
    #: Pose-checked flat geometry only; clones own independent caches.
    collider_geometry: dict[int, _ColliderGeometry] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )

    buildings: MutableBuildings = field(default_factory=MutableBuildings)
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
    reserved: PortReservations = field(default_factory=PortReservations)
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
    #: Prepared prospective static geometry, shared safely by clones: queries
    #: carry their complete selection and never mutate the fixed input.
    junction_projection: _CompositionProjection | None = None

    def __post_init__(self) -> None:
        self.levels = math.floor(self.belt_rules.max_z) + 1
        if self.levels <= 0:
            raise ValueError("belt altitude ceiling must include ground")
        # Construction accepts existing sequences; all live mutations belong
        # to this canvas's maintained index from this point onward.
        if not isinstance(self.buildings, MutableBuildings):
            self.buildings = MutableBuildings(self.buildings)

    @property
    def ramped(self) -> bool:
        """Whether this save requires horizontal run when changing altitude."""
        return not self.belt_rules.vertical_construction

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
                    if lvl >= 0:
                        self.blocked[x, y, lvl] = idx
        if catalog.is_belt(b.item_id):
            for x, y, _ in b.tiles():
                self.world_taken.add((x, y, b.z))
        return idx

    def junction_is_clear(
        self,
        x: int,
        y: int,
        level: int,
        *,
        selected: tuple[PlacedBuilding, ...] = (),
        deadline: float | None = None,
    ) -> bool:
        """Apply exact legality to every real member of a junction stack."""
        return self._junction_geometry_is_clear(x, y, level) and self.projected_buildings_are_clear(
            _splitter_stack_geometry(x, y, level), selected=selected, deadline=deadline
        )

    def _junction_geometry_is_clear(
        self, x: int, y: int, level: int, *, obstacle_span: float | None = None
    ) -> bool:
        """Check technology and placed colliders independently of selected paths."""
        if not 0 <= level < self.levels:
            return False
        if (x, y, level) in self.junction_ban:
            return False
        stack = _splitter_stack_geometry(x, y, level)
        top = stack[-1]
        if not catalog.vertical_construction_allowed(top.item_id, top.z, self.belt_rules):
            return False
        if self.junction_geometry_prepared and not self.buildings.count_by_item(
            catalog.SPLITTER_ID
        ):
            # Prepared bans already cover every non-Splitter static obstacle.
            # Ask the maintained item index on every call, so a newly committed
            # Splitter (including on a clone) immediately takes the exact path.
            return True
        member_boxes: list[tuple[int, int, int, int]] = []
        nearby_indices: tuple[int, ...] | None = None
        query_box: tuple[int, int, int, int] | None = None
        if self.junction_geometry_prepared or obstacle_span is not None:
            span = (
                math.hypot(*catalog.collider_span(catalog.SPLITTER_ID, 0.0))
                if self.junction_geometry_prepared
                else obstacle_span
            )
            assert span is not None
            for stack_member in stack:
                radius = (_static_collider_span(stack_member) + span) / (
                    2.0 * colliders.GRID_ARC
                ) + 3.0
                centre_x = stack_member.x + (stack_member.width - 1) / 2.0
                centre_y = stack_member.y + (stack_member.height - 1) / 2.0
                member_boxes.append(
                    (
                        math.floor(centre_x - radius),
                        math.floor(centre_y - radius),
                        math.ceil(centre_x + radius),
                        math.ceil(centre_y + radius),
                    )
                )
            # Odd model-40 stacks can shift a member's anchor and span. Union
            # the actual member boxes, not a box centred on the logical tap.
            query_box = (
                min(box[0] for box in member_boxes),
                min(box[1] for box in member_boxes),
                max(box[2] for box in member_boxes),
                max(box[3] for box in member_boxes),
            )
            nearby_indices = tuple(
                index
                for index in self.buildings.in_box(*query_box)
                if not self.junction_geometry_prepared
                or self.buildings[index].item_id == catalog.SPLITTER_ID
            )
        for offset, stack_member in enumerate(stack):
            indices = nearby_indices
            if nearby_indices is not None and member_boxes[offset] != query_box:
                # Preserve each original in_box domain before its unchanged
                # centre-distance and exact collider tests. Common horizontal
                # boxes reuse the union result directly across stack heights.
                x0, y0, x1, y1 = member_boxes[offset]
                indices = tuple(
                    index
                    for index in nearby_indices
                    if (building := self.buildings[index]).x <= x1
                    and building.x + building.width - 1 >= x0
                    and building.y <= y1
                    and building.y + building.height - 1 >= y0
                )
            if _building_collider_hits(
                self.buildings, stack_member, indices=indices, geometry=self.collider_geometry
            ):
                return False
        return True

    def projected_buildings_are_clear(
        self,
        candidates: tuple[PlacedBuilding, ...],
        *,
        selected: tuple[PlacedBuilding, ...] = (),
        deadline: float | None = None,
    ) -> bool:
        """Admit one complete source/connector selection, including prior commits."""
        projection = self.junction_projection
        if projection is None:
            return True
        if self.limit is not None:
            x0, y0, x1, y1 = self.limit
            for additions in (candidates, selected):
                for building in additions:
                    if not (
                        x0 <= building.x
                        and y0 <= building.y
                        and building.x + building.width - 1 <= x1
                        and building.y + building.height - 1 <= y1
                    ):
                        return False
        committed_indices = sorted(
            index
            for kind in (BuildingKind.MACHINE, BuildingKind.OTHER)
            for index in self.buildings.by_kind(kind)
            if index >= projection.canvas_prefix_count
        )
        committed = tuple(
            building
            for index in committed_indices
            if (building := self.buildings[index]) not in projection.reserved_buildings
        )
        return projection.allows_buildings(
            candidates, committed=committed + selected, deadline=deadline
        )

    def free_world(self, x: int, y: int, z: Fraction) -> bool:
        """Is the real cell at this altitude clear of belts?

        ``free`` asks the LATTICE, which cannot answer for a ramp: an ascent and
        a descent through one tile take different lattice cells and stand at the
        same height.
        """
        return 0 <= z <= self.belt_rules.max_z and (x, y, z) not in self.world_taken

    def free(self, cell: tuple[int, int, int]) -> bool:
        x, y, z = cell
        if not 0 <= z < self.levels:
            return False
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

    def fits(self, x: int, y: int, width: int, height: int) -> bool:
        """Is EVERY tile of the footprint anchored at ``(x, y)`` free ground?

        The canvas's own occupancy model asked about a RECTANGLE instead of a
        cell.  It is not a second model and it is not a new question: it is
        exactly the pair every ground-standing placer has always asked about
        its anchor -- ``free`` for the lattice cell and ``solid`` for the tile
        -- quantified over the tiles ``add`` will actually mark.

        Both terms are needed and neither implies the other.  ``free``
        deliberately ignores ``solid``, because a machine sells the levels
        above its collider and a belt may cross it; a building standing ON the
        ground may not.

        A 1x1 tower makes this the single-cell test it replaces, tile for
        tile, which is why the default arm cannot move.
        """
        return all(
            self.free((tx, ty, 0)) and (tx, ty) not in self.solid
            for tx in range(x, x + width)
            for ty in range(y, y + height)
        )

    def free_owned_guard(self, cell: Cell) -> bool:
        """Is ``cell`` blocked only by a junction guard this route owns?

        A selected future Splitter reserves its branch docks before sibling
        nets route.  Those siblings may start on one exact dock; every other
        guard remains a wall.  Keep this separate from :meth:`free` so ordinary
        routing can never accidentally weaken junction collision protection.
        """
        x, y, z = cell
        if not 0 <= z < self.levels:
            return False
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

    def clone(self) -> _Canvas:
        """A disposable copy for proving a commit without touching this canvas.

        ``deepcopy`` used to do this and was 0.7-1.2 s of every attempt: it
        re-created every frozen ``PlacedBuilding`` (800k ``deepcopy`` calls on
        ``universe-matrix``) although nothing ever mutates one -- links are
        re-pointed with ``replace``.  Only the containers need to be fresh.
        ``belt_ban`` holds mutable sets, so those are copied one level down;
        building records remain shared, but live query buckets and both
        directions of port reservations belong to the clone.
        """
        return _Canvas(
            belt_rules=self.belt_rules,
            sorter_tiers=self.sorter_tiers,
            sorter_stacks=self.sorter_stacks,
            lane_stacks=self.lane_stacks,
            power_building=self.power_building,
            buildings=MutableBuildings(self.buildings),
            blocked=dict(self.blocked),
            world_taken=set(self.world_taken),
            solid=set(self.solid),
            reserved=PortReservations(self.reserved),
            routing_ports=self.routing_ports,
            port_corridors=dict(self.port_corridors),
            limit=self.limit,
            keep_out=set(self.keep_out),
            guard=set(self.guard),
            belt_ban={column: set(levels) for column, levels in self.belt_ban.items()},
            junction_ban=set(self.junction_ban),
            junction_geometry_prepared=self.junction_geometry_prepared,
            junction_projection=self.junction_projection,
        )


def _core_bounds(canvas: _Canvas) -> tuple[int, int, int, int]:
    """The INCLUSIVE tile box the packed block occupies.

    Tile extents, not origins.  ``_build`` used to take ``max(b.x)`` and add the
    pack width to it, which over-estimated the east face by a whole block and
    under-estimated it by a machine's width -- so the router had a field to roam
    in on one side and none on the other, and "the edge" meant something
    different depending on which pass asked.
    """
    return canvas.buildings.bounds()


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


def _sorter_stacks_for(spec: BuildSpec) -> _SorterStacks:
    """The spec's per-tier stack rows, re-keyed by catalog item id.

    Positional rows are aligned with ``spec.sorter_item_ids``, which is not
    the order ``_sorter_tiers_for`` hands the picker; keying by id removes the
    chance of reading one tier's promise off another's row.
    """
    pick: dict[int, int] = {}
    place: dict[int, int] = {}
    for item_id, pick_stack, place_stack in zip(
        spec.sorter_item_ids, spec.sorter_pick_stacks, spec.sorter_place_stacks, strict=True
    ):
        tier = catalog.get_item_id(item_id)
        if tier is None:
            continue  # a dataset mismatch, already tolerated by _sorter_tiers_for
        pick[tier] = pick_stack
        place[tier] = place_stack
    return _SorterStacks(pick_by_tier=pick, place_by_tier=place)


def _lane_stacks_for(spec: BuildSpec) -> _LaneStacks:
    """The stack each item's lanes are planned at, per side (design 5.3)."""
    items = (
        {item for group in spec.groups for item in group.inputs_per_machine}
        | {item for group in spec.groups for item in group.outputs_per_machine}
        | set(spec.external_inputs)
        | set(spec.outputs)
        | set(spec.surplus_outputs)
    )
    return _LaneStacks(
        consumed={item: spec.planning_stack(item) for item in sorted(items)},
        produced={item: spec.planning_stack(item, external=False) for item in sorted(items)},
    )


def _pick_sorter(
    rate: Fraction,
    span: int,
    machines: int,
    tiers: tuple[int, ...] = catalog.SORTER_TIERS,
    *,
    stacks: _SorterStacks | None = None,
    min_place_stack: int = 1,
    min_pick_stack: int = 1,
) -> tuple[int, int]:
    """Cheapest allowed sorter tier and count carrying ``rate`` across ``span``.

    Reach is three tiles for every tier, so tiers differ only in throughput --
    there is never a reason to pay for a higher tier than the rate needs.
    ``tiers`` is what the save can build, slowest first; when none carries the
    rate the fastest allowed one is returned and ``flow.sorter_capacity``
    refuses the placement, rather than emitting a tier the save cannot build.

    A lane planned at a stack adds a second requirement (design 5.3): a
    low-rate producer lane planned at stack 4 must not be built with a
    ``sorter-1`` that places 1, or the lane would carry a quarter of what the
    plan promised and the validator would judge it at 1.  ``min_place_stack``
    and ``min_pick_stack`` are the lane's stack on the producer and consumer
    side; a tier that cannot keep them is skipped exactly as a tier too slow
    for the rate is, and the same fastest-allowed fallback applies.  Both
    default to 1, so on an unstacked save nothing here changes.
    """
    per_machine = rate / machines if machines else rate
    promises = stacks or _NO_SORTER_STACKS
    for tier in tiers:
        if promises.place(tier) < min_place_stack or promises.pick(tier) < min_pick_stack:
            continue
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
    #: Physical root of one capacity-allocated external supply trunk.
    #: This identifies shared supply without changing the fixed attachment tile.
    supply_root_belt: int | None = None

    def columns(self) -> range:
        return range(self.x0, self.x1 + 1)

    def at_tile(self, k: int) -> _Port:
        """This port moved to the ``k``-th tile of its own lane.

        Out-of-range or an unknown tile list leaves the port alone, so a caller
        that asks for more taps than the lane has tiles degrades to sharing.
        Test-only: no production caller (see tests/layout/test_freeform.py).
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
            self.supply_root_belt,
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
    supply_root_belt: int | None = None


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
                    (role_by_index.get(source.input_obj) if source.input_obj is not None else None),
                    (
                        role_by_index.get(source.output_obj)
                        if source.output_obj is not None
                        else None
                    ),
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
        supply_root_belt=port.supply_root_belt,
    )


def _bind_prepared_port(port: _PreparedPort, buildings: Sequence[PlacedBuilding]) -> _Port:
    # Validate every index against this attempt's fresh building list.  _Port
    # stores indices rather than objects, so no mutable template can leak in.
    buildings[port.belt_index]
    for tile_index in port.tiles:
        buildings[tile_index]
    if port.supply_root_belt is not None:
        buildings[port.supply_root_belt]
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
        supply_root_belt=port.supply_root_belt,
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


def _piler_plan_for_output(strip: Strip, lane_index: int) -> PilerPlan | None:
    """Return the piler plan belonging to one selected output lane."""
    lane_id = _strip_output_lane_id(strip, lane_index)
    return next(
        (
            plan
            for plan in strip.pilers
            if plan.lane_id == lane_id or plan.lane_id.endswith(f":{lane_id}")
        ),
        None,
    )


def _piled_output_tail_column(strip: Strip, lane_index: int) -> int | None:
    """Return the local x-coordinate emitted after this lane's last piler."""
    plan = _piler_plan_for_output(strip, lane_index)
    if plan is None:
        return None
    piler_tiles = catalog.building(catalog.PILER_ID).height
    return strip.width + piler_tiles * plan.count + plan.count - 1


def _emit_piler_tail(
    canvas: _Canvas,
    strip: Strip,
    lane_index: int,
    lane: list[int],
    *,
    x: int,
    y: int,
    item: str,
    cargo_domain: CargoDomain,
    belt_id: int,
    belt_model: int,
    owner_strip: int | None,
) -> tuple[_Port, tuple[_Net, ...]]:
    """Extend one output lane through its serial inline pilers."""
    plan = _piler_plan_for_output(strip, lane_index)
    if plan is None:
        tail = canvas.buildings[lane[-1]]
        return (
            _Port(
                lane[-1],
                tail.x,
                y,
                tail.x - len(lane) + 1,
                tail.x,
                tuple(lane),
                strip.machines,
                cargo_domain=cargo_domain,
            ),
            (),
        )

    previous = lane[-1]
    cursor = x
    transitions: list[_Net] = []
    for _ in range(plan.count):
        piler_index = canvas.add(
            replace(
                junction.make_piler(cursor, y, yaw=Facing.EAST.value),
                owner_strip=owner_strip,
            )
        )
        canvas.buildings[previous] = replace(
            canvas.buildings[previous],
            output_obj=piler_index,
            output_to_slot=1,
        )
        piler = canvas.buildings[piler_index]
        after_index = canvas.add(
            PlacedBuilding(
                item_id=belt_id,
                model_index=belt_model,
                x=cursor + piler.width,
                y=y,
                width=1,
                height=1,
                yaw=Facing.EAST.value,
                input_obj=piler_index,
                input_from_slot=0,
                carries_item=item,
                owner_strip=owner_strip,
            )
        )
        before = canvas.buildings[previous]
        after = canvas.buildings[after_index]
        transitions.append(
            _Net(
                src=_Port(
                    previous,
                    before.x,
                    before.y,
                    before.x,
                    before.x,
                    (previous,),
                    strip.machines,
                    cargo_domain=cargo_domain,
                ),
                dst=_Port(
                    after_index,
                    after.x,
                    after.y,
                    after.x,
                    after.x,
                    (after_index,),
                    strip.machines,
                    cargo_domain=cargo_domain,
                ),
                item=item,
                cargo_domain=cargo_domain,
                prelinked=True,
            )
        )
        previous = after_index
        cursor = after.x + 1

    tail = canvas.buildings[previous]
    return (
        _Port(
            previous,
            tail.x,
            tail.y,
            tail.x,
            tail.x,
            (previous,),
            strip.machines,
            cargo_domain=cargo_domain,
        ),
        tuple(transitions),
    )


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
) -> tuple[dict[str, _Port], dict[_CargoSink, _Port], int, tuple[_Net, ...]]:
    """Place one strip's lanes, machines and sorters.

    Returns the west end of each input lane, the east end of each output lane,
    the sorter count, and the already-linked piler transitions.

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
    piler_nets: list[_Net] = []
    width = s.width
    machine_row = s.machine_row

    # Row -> the item that row's belt is labelled with. On a shared lane this is
    # the FIRST item; the authoritative set is the sorters' filters, which is
    # what the validator keys on. Building it up front removes the
    # branch-per-row this used to need, and it is what lets the marker pass
    # label external input belts later: the knowledge is unrecoverable once
    # emission drops it.
    lane_item_of: dict[int, str] = {}
    #: Row -> exclusive east end of the lane's emitted belt span.
    lane_tiles_of: dict[int, int] = {}
    #: Inputs may prepend a coater approach; flanked drains start at their inlet.
    lane_starts: dict[int, int] = {}
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
        # EXPERIMENT: under a node arm nothing rides this lane, so it is an
        # ORDINARY lane geometrically -- no prepended head, no two-tile floor,
        # no widened channel.  That is the point of the arm: normal collision
        # rules seat the coater on its own object instead.
        if need and s.cargo_domain is CargoDomain.REQUIRES_SPRAY and not coater_mode().is_node:
            need = min(max(need, 2), width)
            lane_starts[row] = -s.west_channel
        lane_tiles_of[row] = need
    for k, (item, _dest, _cargo_domain) in enumerate(s.out_lanes):
        lane_item_of[s.row_of_output(k)] = item
        lane_tiles_of[s.row_of_output(k)] = width
        lane_starts[s.row_of_output(k)] = s.output_lane_start

    lane_idx: dict[int, list[int]] = {}
    for row in range(s.height):
        y = oy + row
        if machine_row <= row < machine_row + s.mh:
            continue  # machine band
        if row not in lane_tiles_of:
            continue  # collider-pitch padding is reserved, not a belt lane
        indices = []
        start = lane_starts.get(row, 0)
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
        output_port, transitions = _emit_piler_tail(
            canvas,
            s,
            j,
            lane_idx[row],
            x=ox + width,
            y=oy + row,
            item=item,
            cargo_domain=cargo_domain,
            belt_id=belt_id,
            belt_model=belt_model,
            owner_strip=owner_strip,
        )
        out_ports[item, dest, cargo_domain] = output_port
        piler_nets.extend(transitions)
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

    return in_ports, out_ports, sorters, tuple(piler_nets)


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
    tails_by_x: dict[int, int] = {}
    for index in out_lane:
        tails_by_x.setdefault(canvas.buildings[index].x, index)
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
        tail = tails_by_x.get(gx)
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
        # Producer side: this sorter PLACES onto an OUTPUT lane, so it is the
        # produced-side stack it has to keep -- not the entry lane's, which for
        # an item that is also belted in is the smaller of the two.
        tier, _count = _pick_sorter(
            rate,
            got.span,
            1,
            canvas.sorter_tiers,
            stacks=canvas.sorter_stacks,
            min_place_stack=canvas.lane_stacks.out_of(item),
        )
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
    tails_by_x: dict[int, int] = {}
    for index in out_lane:
        tails_by_x.setdefault(canvas.buildings[index].x, index)
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
        lane_tail = tails_by_x.get(dock.cell[0])
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
        # `into_machine` says which end of the lane this sorter is on: it
        # PICKS the lane's cargo on the way in and PLACES it on the way out.
        tier, _count = _pick_sorter(
            rate,
            planned.span,
            1,
            canvas.sorter_tiers,
            stacks=canvas.sorter_stacks,
            min_pick_stack=canvas.lane_stacks.into(planned.item) if into_machine else 1,
            min_place_stack=1 if into_machine else canvas.lane_stacks.out_of(planned.item),
        )
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


@lru_cache(maxsize=32)
def _routing_transitions(
    xstep: int,
    levels: int,
    vertical_construction: bool,
    reverse: bool = False,
) -> tuple[tuple[_RoutingTransition, ...], ...]:
    """The authoritative ordinary movement graph, grouped by source level.

    Rows are ``(target offset, via offset, dx, dy, base cost)``. Zero via
    denotes a direct edge, including an unlocked same-XY unit climb.
    Construction and height costs are nonnegative; XY Manhattan remains a
    lower bound even when the save admits many otherwise unnecessary levels.
    """
    tolls = tuple(_GROUND_TOLL if level == 0 else 0.01 * level for level in range(levels))
    by_level: list[tuple[_RoutingTransition, ...]] = []
    for level in range(levels):
        transitions: list[_RoutingTransition] = []
        for dx, dy in _STEPS:
            one = dx * xstep + dy * levels
            for_level = 1.0 + tolls[level]
            transitions.append((one, 0, dx, dy, for_level))
            for level_step in (1, -1):
                next_level = level + level_step
                if 0 <= next_level < levels:
                    transitions.append(
                        (2 * one + level_step, one, 2 * dx, 2 * dy, 3.0 + tolls[next_level])
                    )
        if vertical_construction:
            for level_step in (1, -1):
                next_level = level + level_step
                if 0 <= next_level < levels:
                    transitions.append((level_step, 0, 0, 0, 2.0 + tolls[next_level]))
        by_level.append(tuple(transitions))
    if reverse:
        predecessors: list[list[_RoutingTransition]] = [[] for _ in range(levels)]
        for level, moves in enumerate(by_level):
            for target, via, dx, dy, cost in moves:
                destination = level + target - dx * xstep - dy * levels
                predecessors[destination].append(
                    (-target, via - target if via else 0, -dx, -dy, cost)
                )
        return tuple(tuple(moves) for moves in predecessors)
    return tuple(by_level)


def _cut_loops(path: list[Cell], *, ramped: bool) -> list[Cell]:
    """Remove loops without changing the surviving cells' physical altitudes.

    A ramp's via uses the departing lattice level but is emitted half a level
    away. Equal lattice cells are therefore not necessarily equal physical
    cells. The successor level distinguishes their ramp contexts; a splice
    must preserve that context as well as the cell itself.
    """
    first: dict[Cell | tuple[Cell, int], int] = {}
    keys: list[Cell | tuple[Cell, int]] = []
    out: list[Cell] = []
    for index, cell in enumerate(path):
        key: Cell | tuple[Cell, int] = (
            (cell, path[index + 1][2] if index + 1 < len(path) else cell[2]) if ramped else cell
        )
        seen_at = first.get(key)
        if seen_at is not None:
            for dropped in keys[seen_at + 1 :]:
                first.pop(dropped, None)
            del keys[seen_at + 1 :]
            del out[seen_at + 1 :]
            continue
        first[key] = len(out)
        keys.append(key)
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
    profile = _altitude_profile_cached(tuple(path), ramped)
    return None if profile is None else list(profile)


@lru_cache(maxsize=16384)
def _altitude_profile_cached(path: tuple[Cell, ...], ramped: bool) -> tuple[Fraction, ...] | None:
    levels = [lvl for _, _, lvl in path]
    if not ramped:
        # The slope limit is CONDITIONAL and this save is not under it, so a
        # level change needs no ramp: the belt simply steps up.  See `ramped`
        # in the docstring -- with `beltVerticalConstruction` the game skips
        # the `TooSteep` test entirely, so a whole tile of height across one
        # tile of run is legal, and spending a second tile on it would cost
        # routability for nothing.
        return tuple(lvl * _LEVEL_HEIGHT for lvl in levels)
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
    return tuple(out)


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

    A cell is ``(x - gx0) * gh * levels + (y - gy0) * levels + lvl`` -- an int,
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
    levels: int
    vertical_construction: bool
    xstep: int
    size: int
    base: bytes
    occ: bytearray
    #: Per-search passability scratch, exactly refreshed by :func:`_routing_flags`.
    routing_flags: bytearray
    #: ``(index, port)`` for every reserved cell inside the box.
    reserved: tuple[tuple[int, tuple[int, int, int]], ...]
    #: Congestion history as a flat array, or ``None`` on a round that has none.
    #: Array-backed negotiated histories and list-backed crossing histories are
    #: both borrowed by the geometric query without copying.
    hist: array[float] | list[float] | None

    def index(self, cell: tuple[int, int, int]) -> int:
        x, y, lvl = cell
        x0, y0, x1, y1 = self.span
        if not (x0 <= x <= x1 and y0 <= y <= y1 and 0 <= lvl < self.levels):
            raise IndexError(f"routing cell outside indexed domain: {cell}")
        return (x - self.gx0) * self.xstep + (y - self.gy0) * self.levels + lvl

    def block(self, cell: tuple[int, int, int]) -> None:
        """Mark a committed path cell impassable."""
        self.occ[self.index(cell)] = 0

    def restore(self, cell: tuple[int, int, int]) -> None:
        """Undo :meth:`block` -- back to whatever the cell was before routing."""
        at = self.index(cell)
        self.occ[at] = self.base[at]

    def refresh_history(self, history: Mapping[tuple[int, int, int], float]) -> None:
        """Re-flatten ``history``, which changes once per rip-up round."""
        if not history:
            self.hist = None
            return
        lo_x, lo_y, hi_x, hi_y = self.box
        flat = array("d", bytes(8 * self.size))
        gx0, gy0, xstep = self.gx0, self.gy0, self.xstep
        for (cx, cy, clvl), used in history.items():
            if lo_x <= cx <= hi_x and lo_y <= cy <= hi_y and 0 <= clvl < self.levels:
                flat[(cx - gx0) * xstep + (cy - gy0) * self.levels + clvl] = used
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
    levels = canvas.levels
    xstep = gh * levels
    size = (gx1 - gx0 + 1) * xstep

    occ = bytearray(size)
    if lo_x <= hi_x and lo_y <= hi_y:
        run = b"\x01" * ((hi_y - lo_y + 1) * levels)
        head = (lo_y - gy0) * levels
        width = len(run)
        for gx in range(lo_x - gx0, hi_x - gx0 + 1):
            at = gx * xstep + head
            occ[at : at + width] = run
    holes = bytes(levels)
    for cx, cy, clvl in canvas.blocked:
        if lo_x <= cx <= hi_x and lo_y <= cy <= hi_y and 0 <= clvl < levels:
            occ[(cx - gx0) * xstep + (cy - gy0) * levels + clvl] = 0
    # `canvas.solid` is NOT punched out here, and must not be: the band a
    # machine really denies is already in `blocked` above, level by level, and
    # blanking the whole column would put this grid back in disagreement with
    # `_Canvas.free` -- in the other direction from the bug documented below,
    # but the same bug.
    for cx, cy in canvas.keep_out:
        if lo_x <= cx <= hi_x and lo_y <= cy <= hi_y:
            at = (cx - gx0) * xstep + (cy - gy0) * levels
            occ[at : at + levels] = holes
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
    for (cx, cy), banned_levels in canvas.belt_ban.items():
        if lo_x <= cx <= hi_x and lo_y <= cy <= hi_y:
            at = (cx - gx0) * xstep + (cy - gy0) * levels
            for clvl in banned_levels:
                if 0 <= clvl < levels:
                    occ[at + clvl] = 0
    for cx, cy, clvl in canvas.guard:
        if lo_x <= cx <= hi_x and lo_y <= cy <= hi_y and 0 <= clvl < levels:
            occ[(cx - gx0) * xstep + (cy - gy0) * levels + clvl] = 0
    reserved = tuple(
        ((cx - gx0) * xstep + (cy - gy0) * levels + clvl, port)
        for (cx, cy, clvl), port in canvas.reserved.items()
        if lo_x <= cx <= hi_x and lo_y <= cy <= hi_y and 0 <= clvl < levels
    )
    grid = _Grid(
        box=box,
        span=span,
        gx0=gx0,
        gy0=gy0,
        gh=gh,
        levels=levels,
        vertical_construction=canvas.belt_rules.vertical_construction,
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
    """Detailed result; ``expansions`` records charged geometric work units."""

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
    owned_starts: Collection[Cell] = (),
    released_starts: Collection[Cell] = (),
    forbidden: Collection[Cell] = (),
    blocking_owners: Mapping[Cell, int] | None = None,
    *,
    extra_edges: dict[int, tuple[tuple[int, float], ...]] | None = None,
) -> _PathSearchResult:
    """Cheapest admitted directed interval path with landing congestion cost.

    Starts may lie outside ``bounds`` on the external entry ring. Exact owned
    junction guards and released tentative starts are the only admission
    exceptions; forbidden cells stay closed. The caller's matching grid and
    history are borrowed only for this query.

    Work charges newly prepared cells plus processed active intervals against
    both the per-query cap and shared ledger. Only complete exhaustion supplies
    wall evidence. Budget or deadline termination never proves infeasibility.
    """
    forbidden_cells = frozenset(forbidden)
    goals = {goal for goal in goals if 0 <= goal[2] < canvas.levels}
    starts = [start for start in starts if 0 <= start[2] < canvas.levels]
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
    flat = (
        grid
        if grid is not None
        and grid.box == box
        and grid.levels == canvas.levels
        and grid.vertical_construction == canvas.belt_rules.vertical_construction
        else None
    )
    if flat is not None:
        sx0, sy0, sx1, sy1 = flat.span
        for cx, cy, clvl in starts:
            if not (sx0 <= cx <= sx1 and sy0 <= cy <= sy1 and 0 <= clvl < flat.levels):
                flat = None
                break
    if flat is not None:
        sx0, sy0, sx1, sy1 = flat.span
        for cx, cy, clvl in goal_list:
            if not (sx0 <= cx <= sx1 and sy0 <= cy <= sy1 and 0 <= clvl < flat.levels):
                flat = None
                break
    if flat is None:
        if extra_edges:
            raise ValueError("extra edges require the caller's matching routing grid")
        flat = _make_grid(canvas, box, _span_for(box, starts, goal_list), history)

    gx0, gy0, gh, xstep, size = flat.gx0, flat.gy0, flat.gh, flat.xstep, flat.size
    levels = flat.levels
    ystep = levels
    transitions = _routing_transitions(xstep, levels, flat.vertical_construction)
    admitted_edges = {} if extra_edges is None else extra_edges
    for source, edges in admitted_edges.items():
        if not 0 <= source < size:
            raise ValueError("extra edge source index is outside the grid")
        source_x, source_y = divmod(source // levels, gh)
        for target, cost in edges:
            if not 0 <= target < size:
                raise ValueError("extra edge landing index is outside the grid")
            target_x, target_y = divmod(target // levels, gh)
            if not math.isfinite(cost) or cost < abs(target_x - source_x) + abs(
                target_y - source_y
            ):
                raise ValueError("extra edge cost must dominate XY Manhattan displacement")

    # A private copy, because the reservations a net may use are its own and
    # `routing_ports` is rebound per net. Copying is a memcpy; rebuilding it
    # from the canvas obstacle containers is not.
    flags = _routing_flags(flat, routing_ports=canvas.routing_ports)
    for start in owned:
        flags[flat.index(start)] = 1
    sx0, sy0, sx1, sy1 = flat.span
    for cell in forbidden_cells:
        if sx0 <= cell[0] <= sx1 and sy0 <= cell[1] <= sy1 and 0 <= cell[2] < levels:
            flags[flat.index(cell)] = 0

    # Admit starts once using the same source exceptions as the physical caller.
    start_indices = [
        (s[0] - gx0) * xstep + (s[1] - gy0) * ystep + s[2]
        for s in starts
        if not (
            s in forbidden_cells or (not canvas.free(s) and s not in owned and s not in released)
        )
    ]
    if not start_indices:
        return _PathSearchResult(None, RouteFailureKind.DYNAMIC_ACCESS, (), 0)

    # The kernel returns its exact charge on every normal exit.
    start_left = budget["left"] if budget is not None else 1 << 62

    world = GeometricWorld.from_grid(flat, flags, transitions)
    result = geometric_router.route(
        geometric_router.GeometricQuery(
            world=world,
            starts=tuple(start_indices),
            goals=tuple(flat.index(cell) for cell in goal_list),
            pressure=pressure,
            max_work=min(_MAX_EXPANSIONS, start_left),
            deadline=deadline,
            extra_edges=admitted_edges,
        )
    )
    expansions = result.metrics["charged_work"]
    if budget is not None:
        budget["left"] = start_left - expansions
    if result.kind in ("budget", "cancelled"):
        return _PathSearchResult(None, RouteFailureKind.BUDGET, (), expansions)
    path_indices = result.path
    if result.kind == "routed":
        assert path_indices is not None
        cells = []
        for index in path_indices:
            q, lvl = divmod(index, levels)
            px, py = divmod(q, gh)
            cells.append((px + gx0, py + gy0, lvl))
        return _PathSearchResult(
            tuple(_cut_loops(cells, ramped=canvas.ramped)), None, (), expansions
        )

    # Forward exhaustion keeps its existing cardinal ownership frontier.
    # Reverse exhaustion instead exposes predecessors of the goal component;
    # a directed ramp's via remains on its original source level.
    reached = result.reachable if result.co_reachable is None else result.co_reachable

    def boundary_cells() -> Iterator[Cell]:
        settled = (
            (x * world.ny + y) * world.nz + z for y, z, lo, hi in reached for x in range(lo, hi + 1)
        )
        if result.co_reachable is None:
            for index in settled:
                x, y, level = world.cell(index)
                for dx, dy in _STEPS:
                    cell = (x + dx, y + dy, level)
                    if (
                        sx0 <= cell[0] <= sx1
                        and sy0 <= cell[1] <= sy1
                        and not flags[flat.index(cell)]
                    ):
                        yield cell
            return
        incoming: list[list[tuple[int, int, int, bool]]] = [[] for _ in range(levels)]
        for source_level, row in enumerate(world.transitions):
            for dx, dy, dz, via, _cost in row:
                target_level = source_level + dz
                if 0 <= target_level < levels:
                    incoming[target_level].append((dx, dy, source_level, via))
        goal_component = frozenset(settled)
        for index in goal_component:
            x, y, level = world.cell(index)
            for dx, dy, source_level, via in incoming[level]:
                source = (x - dx, y - dy, source_level)
                if not (sx0 <= source[0] <= sx1 and sy0 <= source[1] <= sy1):
                    continue
                if not flags[flat.index(source)]:
                    yield source
                ramp_via = (x - dx // 2, y - dy // 2, source_level)
                if via and not flags[flat.index(ramp_via)]:
                    yield ramp_via
        for goal in goal_list:
            if not flags[flat.index(goal)]:
                yield goal
        for source_index, edges in admitted_edges.items():
            if not flags[source_index] and any(target in goal_component for target, _cost in edges):
                yield world.cell(source_index)

    if blocking_owners is not None:
        owner_get = blocking_owners.get
        wall_by_owner: dict[int, Cell] = {}
        too_diffuse = False
        for cell in boundary_cells():
            blocker = owner_get(cell)
            if blocker is None:
                continue
            wall_by_owner.setdefault(blocker, cell)
            if len(wall_by_owner) > _BLAME_MAX_WALL:
                too_diffuse = True
                break
        owner_wall_cells = () if too_diffuse else tuple(sorted(wall_by_owner.values()))
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
    if sum(hi - lo + 1 for _, _, lo, hi in reached) <= _BLAME_MAX_POCKET:
        blocked_get = canvas.blocked.get
        wall: set[Cell] = set()
        for cell in boundary_cells():
            if blocked_get(cell) == _TENTATIVE:
                wall.add(cell)
        if len(wall) <= _BLAME_MAX_WALL:
            wall_cells = tuple(sorted(wall))
            if blame is not None:
                for cell in wall_cells:
                    blame[cell] = blame.get(cell, 0.0) + 1.0
    return _PathSearchResult(None, RouteFailureKind.SEALED_POCKET, wall_cells, expansions)


@dataclass(frozen=True, slots=True)
class _Net:
    """A detailed query phase's immutable endpoints and identity-bearing fields."""

    src: _Port | None
    dst: _Port
    item: str
    cargo_domain: CargoDomain = CargoDomain.UNSPRAYED
    net_id: NetId | None = None
    boundary_goals: tuple[tuple[int, int, int], ...] = ()
    #: This segment is already linked through an inline piler and is recorded
    #: for routing topology only; path search must not build a bypass around it.
    prelinked: bool = False

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
    prelinked: bool = False

    def __post_init__(self) -> None:
        ports = (self.dst,) if self.src is None else (self.src, self.dst)
        if any(port.cargo_domain is not self.cargo_domain for port in ports):
            raise ValueError("prepared net ports must share one cargo domain")


type _SourceGroupKey = tuple[str, CargoDomain, int] | tuple[str, CargoDomain, int, int, int]


def _source_group_key(
    item: str, cargo_domain: CargoDomain, port: _Port | _PreparedPort
) -> _SourceGroupKey:
    if port.supply_root_belt is not None:
        return item, cargo_domain, port.supply_root_belt
    return item, cargo_domain, port.y, port.x0, port.z


def _with_sibling_groups(
    nets: Sequence[_PreparedNet],
) -> tuple[_PreparedNet, ...]:
    """Freeze the detailed router's exact branch/merge groups onto each net."""
    same_src: dict[_SourceGroupKey, list[NetId]] = defaultdict(list)
    same_dst: dict[tuple[CargoDomain, int, int, int], list[NetId]] = defaultdict(list)
    for net in nets:
        if net.net_id.role is NetRole.EXTERNAL:
            continue
        if net.src is None:
            raise ValueError("non-external prepared nets require source ports")
        same_src[_source_group_key(net.item, net.cargo_domain, net.src)].append(net.net_id)
        same_dst[net.cargo_domain, net.dst.x, net.dst.y, net.dst.z].append(net.net_id)
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
                    for sibling in same_src[_source_group_key(net.item, net.cargo_domain, net.src)]
                    if sibling != net.net_id
                ),
                dst_group=tuple(
                    sibling
                    for sibling in same_dst[
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
    buildings: MutableBuildings
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
    belt_rules: catalog.BeltAltitudeRules = _DEFAULT_BELT_RULES
    world_taken: frozenset[tuple[int, int, Fraction]] = frozenset()
    belt_ban: tuple[tuple[tuple[int, int], frozenset[int]], ...] = ()
    junction_ban: frozenset[Cell] = frozenset()
    junction_frame_bans: tuple[frozenset[Cell], ...] = ()
    preparation_failures: tuple[NetFailure, ...] = ()
    stranded_ports: tuple[StrandedPort, ...] = ()
    preparation_exhaustive: bool = False
    external_output_nets: tuple[_PreparedNet, ...] = ()
    port_access_demands: tuple[PortAccessDemand, ...] = ()
    late_output_net_ids: frozenset[NetId] = frozenset()
    sorter_tiers: tuple[int, ...] = catalog.SORTER_TIERS
    sorter_stacks: _SorterStacks = _NO_SORTER_STACKS
    lane_stacks: _LaneStacks = _NO_LANE_STACKS
    #: The power building the spec chose, carried so every workspace canvas --
    #: and so :func:`_place_power`, which runs on one -- stands the same
    #: building the plan reserved ground for.
    power_building: catalog.Building = field(
        default_factory=lambda: catalog.power_tower_building(catalog.DEFAULT_POWER_TOWER)
    )
    projection_policy: BandPolicy = field(default_factory=lambda: BandPolicy("portable"))
    junction_projection: _CompositionProjection | None = field(
        default=None, repr=False, compare=False
    )
    buildings_index: Buildings | None = field(default=None, init=False, repr=False, compare=False)

    @property
    def levels(self) -> int:
        return math.floor(self.belt_rules.max_z) + 1

    @property
    def ramped(self) -> bool:
        return not self.belt_rules.vertical_construction

    def indexed_templates(self) -> Buildings:
        cached = self.buildings_index
        if cached is None:
            cached = Buildings(self.building_templates)
            object.__setattr__(self, "buildings_index", cached)
        return cached

    def new_workspace(self) -> _RoutingWorkspace:
        projection = self.junction_projection
        if projection is None:
            projection = _CompositionProjection(
                self.building_templates,
                self.limit or self.route_bounds,
                self.projection_policy,
                belt_rules=self.belt_rules,
                power_sites=self.power_sites,
                tower=self.power_building,
            )
            object.__setattr__(self, "junction_projection", projection)
        buildings = MutableBuildings(self.building_templates)
        canvas = _Canvas(
            belt_rules=self.belt_rules,
            sorter_tiers=self.sorter_tiers,
            sorter_stacks=self.sorter_stacks,
            lane_stacks=self.lane_stacks,
            power_building=self.power_building,
            buildings=buildings,
            blocked=dict(self.blocked),
            world_taken=set(self.world_taken),
            solid=set(self.solid),
            reserved=PortReservations(self.reserved),
            routing_ports=frozenset(),
            port_corridors=dict(self.port_corridors),
            limit=self.limit,
            keep_out=set(self.keep_out),
            belt_ban={cell: set(levels) for cell, levels in self.belt_ban},
            guard=set(self.guard),
            junction_ban=set(self.junction_ban),
            junction_geometry_prepared=True,
            junction_projection=projection,
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

    def routing_problem(self) -> _PreparedRoutingProblem:
        """Return the path-search view without already-linked piler transitions."""
        routed = tuple(net for net in self.nets if not net.prelinked)
        return self if len(routed) == len(self.nets) else replace(self, nets=routed)


def _protected_template_belt_indices(
    problem: _PreparedRoutingProblem,
) -> frozenset[int]:
    """Return fixed belts that validator-clean boundary cleanup cannot delete."""
    templates = problem.building_templates
    indexed = problem.indexed_templates()
    belt_indices = set(indexed.belts())
    return frozenset(
        target
        for index in sorted(
            (*indexed.machines(), *indexed.sorters(), *indexed.by_kind(BuildingKind.OTHER))
        )
        for building in (templates[index],)
        for target in (building.input_obj, building.output_obj)
        if target in belt_indices
    )


def _prepared_candidate_area_lower_bound(problem: _PreparedRoutingProblem) -> int:
    """Lower-bound finalized area by the candidate's cleanup-invariant skeleton.

    Boundary cleanup removes only belts.  Non-belt templates and belts named by
    their input/output references must therefore survive every validator-clean
    completion of this prepared candidate.  Routing and final-frame padding can
    enlarge, but cannot shrink, the axis-aligned extent of that skeleton.
    """
    indexed = problem.indexed_templates()
    protected = _protected_template_belt_indices(problem)
    survivors = tuple(
        problem.building_templates[index]
        for index in sorted(
            (
                *protected,
                *indexed.machines(),
                *indexed.sorters(),
                *indexed.by_kind(BuildingKind.OTHER),
            )
        )
    )
    if not survivors:
        return 0
    left, bottom, right, top = bounds_of(survivors)
    return (right - left + 1) * (top - bottom + 1)


@dataclass(frozen=True, slots=True)
class PreparedRoutingLowerBound:
    """Immutable belt-tile floor for one concrete prepared routing problem."""

    protected_template_belts: int
    route_floor: int
    component_count: int
    total: int


def _prepared_routing_lower_bound(
    problem: _PreparedRoutingProblem,
) -> PreparedRoutingLowerBound:
    """Prove a belt-tile floor conditional on this prepared candidate.

    The fixed term contains only distinct template belts named by a non-belt
    template's input or output reference.  A validator-clean completion cannot
    remove such a belt during boundary cleanup without leaving that reference
    invalid.  The route term is computed from the actual prepared nets: direct
    insertions are already absent, and prelinked piler transitions are ignored.

    Each net pays the unobstructed planar Manhattan distance between every
    access cell its prepared source-sharing group may legally use and every
    access cell its destination-sharing group may legally use, including both
    endpoint cells.  External nets use their prepared boundary goals.  Altitude,
    obstacles, ramps, and access restrictions are deliberately ignored, so they
    can only make an accepted route longer.  Nets joined by ``src_group`` or
    ``dst_group`` form one legal-sharing component and pay only that component's
    maximum floor; unrelated components add because the detailed router forbids
    their route cells from being reused.

    Thus ``total <= finalized belt_tiles`` for every validator-clean placement
    emitted from ``problem``.  This says nothing about unprepared placements,
    minimum-cost routing, or whole-search optimality.
    """
    protected = _protected_template_belt_indices(problem)

    nets = tuple(net for net in (*problem.nets, *problem.external_output_nets) if not net.prelinked)
    net_index = Nets.of(
        (net.net_id, net.net_id.item, "", (net.dst.x, net.dst.y, net.dst.z), "", net)
        for net in nets
    )
    components = UnionFind()
    for net_id in net_index.ids():
        components.find(net_id)

    for net in nets:
        for sibling in (*net.src_group, *net.dst_group):
            if net_index.by_id(sibling) is not None:
                components.union(net.net_id, sibling)

    def adjacent(port: _PreparedPort) -> tuple[tuple[int, int], ...]:
        return tuple((port.x + dx, port.y + dy) for dx, dy in _STEPS)

    def starts(net: _PreparedNet) -> tuple[tuple[int, int], ...]:
        if net.net_id.role is NetRole.EXTERNAL:
            return tuple((x, y) for x, y, _level in net.boundary_goals)
        return () if net.src is None else adjacent(net.src)

    def goals(net: _PreparedNet) -> tuple[tuple[int, int], ...]:
        if net.net_id.role is NetRole.EXTERNAL_OUTPUT:
            return tuple((x, y) for x, y, _level in net.boundary_goals)
        return adjacent(net.dst)

    def route_floor(net: _PreparedNet) -> int:
        legal_starts = tuple(
            cell
            for net_id in (net.net_id, *net.src_group)
            if (sibling := net_index.by_id(net_id)) is not None
            for cell in starts(sibling)
        )
        legal_goals = tuple(
            cell
            for net_id in (net.net_id, *net.dst_group)
            if (sibling := net_index.by_id(net_id)) is not None
            for cell in goals(sibling)
        )
        return min(
            (abs(sx - gx) + abs(sy - gy) + 1 for sx, sy in legal_starts for gx, gy in legal_goals),
            default=0,
        )

    component_floors: dict[NetId, int] = {}
    for net in nets:
        root = cast(NetId, components.find(net.net_id))
        component_floors[root] = max(component_floors.get(root, 0), route_floor(net))
    route_total = sum(component_floors.values())
    return PreparedRoutingLowerBound(
        protected_template_belts=len(protected),
        route_floor=route_total,
        component_count=len(component_floors),
        total=len(protected) + route_total,
    )


def _bind_prepared_net(net: _PreparedNet, buildings: Sequence[PlacedBuilding]) -> _Net:
    return _Net(
        src=(_bind_prepared_port(net.src, buildings) if net.src is not None else None),
        dst=_bind_prepared_port(net.dst, buildings),
        item=net.item,
        cargo_domain=net.cargo_domain,
        net_id=net.net_id,
        boundary_goals=net.boundary_goals,
        prelinked=net.prelinked,
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


@lru_cache(maxsize=1024)
def _source_branch_directions(
    belt_prefab: tuple[int, int],
    altitude: Fraction,
    actual_level: int,
    branch_level: int,
    carry_direction: tuple[int, int] | None,
    neighbours: tuple[tuple[int, int], ...],
) -> frozenset[tuple[int, int]]:
    """Translation-invariant physical ports; no occupancy or frame verdicts."""
    attachment = PlacedBuilding(
        item_id=belt_prefab[0], model_index=belt_prefab[1], x=0, y=0, z=altitude
    )
    splitter = _splitter_stack_geometry(0, 0, actual_level, carry_direction=carry_direction)[-1]
    used: set[int] = set()
    for dx, dy in neighbours:
        port = splitter_ports.expected_path_port(
            splitter, attachment, replace(attachment, x=dx, y=dy)
        )
        if port is None or port in used:
            return frozenset()
        used.add(port)
    branch = replace(attachment, z=Fraction(branch_level))
    available: set[tuple[int, int]] = set()
    for dx, dy in _STEPS:
        port = splitter_ports.expected_path_port(splitter, branch, replace(branch, x=dx, y=dy))
        if port is not None and port not in used:
            available.add((dx, dy))
    return frozenset(available)


def _protected_merge_cells(
    paths: Mapping[int, Sequence[Cell]],
    siblings: tuple[int, ...],
    source_taps: Mapping[int, Cell],
) -> set[Cell]:
    """Keep a later side merge from invalidating a selected Splitter's run.

    An upstream belt still reaches the Splitter through its forward link. A
    downstream merge acquires a second reverse feeder and loses that exemption.
    Protect only the selected tap and its near downstream belts inside the
    top member's exact keepout; other merge-before-fork arrangements stay legal.
    """
    if not source_taps:
        return set()
    taps = frozenset(source_taps.values())
    keepouts: dict[Cell, frozenset[Cell]] = {}
    protected: set[Cell] = set()

    def protect(tap: Cell, cells: Sequence[Cell]) -> None:
        keepout = keepouts.get(tap)
        if keepout is None:
            top = _splitter_stack_geometry(*tap)[-1]
            keepout = frozenset(
                junction.keepout_cells(
                    tap[0], tap[1], int(top.z), model_index=top.model_index, yaw=top.yaw
                )
            )
            keepouts[tap] = keepout
        protected.update(cell for cell in cells if cell in keepout)

    for sibling in siblings:
        path = paths.get(sibling, ())
        if (tap := source_taps.get(sibling)) is not None:
            protect(tap, path[:2])
        for at, cell in enumerate(path):
            if cell in taps:
                protect(cell, path[at : at + 3])
    return protected


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
    primitives: RoutePrimitives | None = None,
    source_choices: dict[Cell, set[Cell]] | None = None,
    witness: Callable[[Cell, Cell], bool] | None = None,
    deadline: float | None = None,
    path_ranges: Mapping[int, tuple[int, int]] | None = None,
    merged_cells: Collection[Cell] = frozenset(),
    protected_sinks: Collection[Cell] = frozenset(),
    source_feeds: Mapping[int, int] | None = None,
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

    ``source_choices`` retains competing tap identities until the endpoint
    owner can certify them before collapsing provenance. Unambiguous offers
    may defer projected-frame admission to the chosen-path search.
    """
    out: set[Cell] = set()
    for sibling in siblings:
        path = paths.get(sibling, ())
        source_feed = None if source_feeds is None else source_feeds.get(sibling)
        first, last = (0, len(path)) if path_ranges is None else path_ranges.get(sibling, (0, 0))
        altitudes = (
            _altitude_profile(path, ramped=canvas.ramped)
            if primitives is None
            else primitives.altitudes(path, ramped=canvas.ramped)
        )
        if altitudes is None:
            continue
        path_cells = frozenset(path) if junctionable is not None else None
        for at, ((x, y, lvl), altitude) in enumerate(zip(path, altitudes, strict=True)):
            if at >= last:
                break
            if at < first:
                continue
            if junctionable is None and (x, y, lvl) in protected_sinks:
                continue
            if witness is not None and _expired(deadline):
                return out
            # A source-side junction requires an integer carry plane.  Model 40
            # serves odd planes from one level lower and exposes only its
            # orthogonal lower ports to the new branch.
            if junctionable is not None and altitude.denominator != 1:
                continue
            actual_level = int(altitude) if altitude.denominator == 1 else lvl
            if junctionable is not None and not junctionable(x, y, actual_level):
                continue
            feed = canvas.buildings[source_feed] if at == 0 and source_feed is not None else None
            carry_direction = (
                _straight_path_direction(path, at)
                if junctionable is not None and actual_level % 2
                else None
            )
            if junctionable is not None and actual_level % 2 and feed is not None:
                carry_direction = _straight_path_direction(
                    ((feed.x, feed.y, int(feed.z)), *path[:2]), 1
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
                directions = _source_branch_directions(
                    belt_prefab,
                    altitude,
                    actual_level,
                    branch_level,
                    carry_direction,
                    (
                        (() if feed is None else ((feed.x - x, feed.y - y),))
                        + tuple(
                            (path[neighbour][0] - x, path[neighbour][1] - y)
                            for neighbour in (at - 1, at + 1)
                            if 0 <= neighbour < len(path)
                        )
                    ),
                )
                free = [cell for cell in free if (cell[0] - x, cell[1] - y) in directions]
            if not free:
                continue
            if junctionable is not None and not _junction_belt_clear(
                canvas,
                (x, y, actual_level),
                path,
                at,
                tentative_ok=tentative_ok,
                path_cells=path_cells,
                merged_cells=merged_cells,
                source_feed=source_feed,
            ):
                continue
            if witness is not None:
                free = [cell for cell in free if witness(cell, (x, y, lvl))]
                if not free:
                    continue
            out.update(free)
            if provenance is not None:
                tap = (x, y, lvl)
                for cell in free:
                    provenance.setdefault(cell, tap)
                    if source_choices is not None:
                        source_choices.setdefault(cell, set()).add(tap)
            if witness is not None:
                return out
    return out


@dataclass(frozen=True, slots=True)
class RoutingFlowLimits:
    """Exact assigned rates, in query order, and the routed belt's capacity."""

    rates: tuple[Fraction, ...]
    capacity: Fraction


def _flow_frontier_ranges(
    index: int,
    paths: Mapping[int, Sequence[Cell]],
    owner: Mapping[Cell, int],
    source_hints: Mapping[int, Cell],
    sink_hints: Mapping[int, Cell],
    limits: RoutingFlowLimits,
) -> tuple[dict[int, tuple[int, int]], dict[int, tuple[int, int]]]:
    """Reserve each routed flow along its complete inherited prefix and suffix.

    Path ownership is not flow ownership: a later fork uses its ancestor's
    prefix, and a later merge uses its ancestor's suffix. Account for both
    transitively before offering another flow those same physical segments.
    Sparse interval events avoid allocating one rational load per belt cell.
    These are assignment reservations, not a substitute for final physical LP
    certification, which can also reallocate interchangeable item flows.
    """
    anchors: dict[Cell, tuple[int, int]] = {}
    for hints in (source_hints, sink_hints):
        for current, tap in hints.items():
            if current in paths and tap in owner and tap not in anchors:
                parent = owner[tap]
                anchors[tap] = (parent, paths[parent].index(tap))
    events = {
        current: {0: limits.rates[current], len(path): -limits.rates[current]}
        for current, path in paths.items()
    }
    for current in paths:
        rate = limits.rates[current]
        for upstream, hints in ((True, source_hints), (False, sink_hints)):
            visited = {current}
            parent = current
            while (parent_tap := hints.get(parent)) is not None and parent_tap in anchors:
                parent, at = anchors[parent_tap]
                if parent in visited:
                    # A cyclic dependency cannot certify an inherited path.
                    denied = {member: (0, 0) for member in paths}
                    return denied, denied
                visited.add(parent)
                first, last = (0, at + 1) if upstream else (at, len(paths[parent]))
                changes = events[parent]
                changes[first] = changes.get(first, Fraction(0)) + rate
                changes[last] = changes.get(last, Fraction(0)) - rate
    remaining = limits.capacity - limits.rates[index]
    saturated: dict[int, tuple[int, int]] = {}
    for current, changes in events.items():
        points = sorted(changes)
        load = Fraction(0)
        first, last = len(paths[current]), 0
        for position, at in enumerate(points[:-1]):
            load += changes[at]
            if load > remaining:
                first = min(first, at)
                last = points[position + 1]
        saturated[current] = first, last
    source_ranges: dict[int, tuple[int, int]] = {}
    sink_ranges: dict[int, tuple[int, int]] = {}
    for current, path in paths.items():
        first, last = saturated[current]
        for upstream, hints in ((True, source_hints), (False, sink_hints)):
            parent = current
            while (parent_tap := hints.get(parent)) is not None and parent_tap in anchors:
                parent, at = anchors[parent_tap]
                before, after = saturated[parent]
                if (upstream and before <= at) or (not upstream and after > at):
                    if upstream:
                        first = 0
                    else:
                        last = len(path)
                    break
        source_ranges[current] = (0, first)
        sink_ranges[current] = (last, len(path))
    return source_ranges, sink_ranges


def _junction_belt_clear(
    canvas: _Canvas,
    tap: tuple[int, int, int],
    path: Sequence[tuple[int, int, int]],
    at: int,
    *,
    tentative_ok: bool = False,
    path_cells: Collection[Cell] | None = None,
    merged_cells: Collection[Cell] = frozenset(),
    source_feed: int | None = None,
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
    if path_cells is None:
        path_cells = frozenset(path)
    excused = set(path[max(0, at - 2) : at + 3])
    if source_feed is not None and at < 2:
        # The selected prebuilt feeder is already connected to this path.
        # Account for the head-to-tap distance before walking its real links;
        # nearby same-item belts without that connection remain foreign.
        excused.update(_run_cells(canvas, canvas.buildings.belts_into, source_feed, hops=1 - at))
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
                    if cell in merged_cells and cell in path[at : at + 3]:
                        return False
                    continue
                return False
            if top and cell in excused:
                continue
            who = canvas.blocked.get(cell)
            if who is None:
                continue
            if who == _TENTATIVE:
                if tentative_ok:
                    continue
                return False
            building = canvas.buildings.by_index(who)
            if building is not None and catalog.is_belt(building.item_id):
                return False
    return True


@dataclass(frozen=True, slots=True)
class _CommitFailure:
    """A physical attachment failure or a contextual settlement proposal."""

    cell: Cell
    side: Literal["source", "sink", "path", "contextual"]
    blocking_indices: tuple[int, ...] = ()
    tap: Cell | None = None
    blocking_cells: tuple[Cell, ...] = ()
    reason: str = ""
    interior_detour: frozenset[Cell] = frozenset()


@dataclass(slots=True)
class _CommittedAttempt:
    workspace: _Canvas
    ownership: tuple[frozenset[NetId], ...]
    unlinked: tuple[int, ...]
    details: dict[int, _CommitFailure]
    selection: tuple[object, ...] = ()
    settlement: RouteSettlement | None = None


type _RouteProposalChoice = (
    tuple[Literal["source"], tuple[Cell | None, Cell | None]]
    | tuple[Literal["sink"], Cell | None]
    | tuple[Literal["interior"], frozenset[Cell]]
)


@dataclass(slots=True)
class _RouteProposal:
    source: tuple[Cell | None, Cell | None]
    sink: Cell | None
    detours: dict[frozenset[Cell], None] = field(default_factory=dict)
    attempted: dict[tuple[object, ...], set[_RouteProposalChoice]] = field(default_factory=dict)

    def restrict(
        self,
        starts: list[Cell],
        goals: set[Cell],
        offers: tuple[Mapping[Cell, Cell], Mapping[Cell, Cell], Mapping[Cell, Cell]],
        *,
        construction: tuple[object, ...],
    ) -> tuple[list[Cell], set[Cell], frozenset[Cell], bool]:
        # Progress belongs to actual descriptors in this frozen construction,
        # not positions in an offer list that upstream restaking can replace.
        # These are positive branch attempts, never negative geometry evidence.
        context = (
            construction,
            tuple(starts),
            frozenset(goals),
            *(frozenset(offer.items()) for offer in offers),
        )
        attempted = self.attempted.setdefault(context, set())
        for detour in self.detours:
            # Never turn an interior proposal into an endpoint exclusion when
            # changed offers expose one of the old support cells as access.
            interior = detour.difference(starts, goals)
            choice: _RouteProposalChoice = ("interior", interior)
            if not interior or choice in attempted:
                continue
            attempted.add(choice)
            return starts, goals, interior, True
        sources = dict.fromkeys((offers[0].get(cell), offers[2].get(cell)) for cell in starts)
        for source in sources:
            choice = ("source", source)
            if source == self.source or choice in attempted:
                continue
            attempted.add(choice)
            return (
                [cell for cell in starts if (offers[0].get(cell), offers[2].get(cell)) == source],
                goals,
                frozenset(),
                True,
            )
        destinations = dict.fromkeys(offers[1].get(cell) for cell in sorted(goals))
        for sink in destinations:
            choice = ("sink", sink)
            if sink == self.sink or choice in attempted:
                continue
            attempted.add(choice)
            return (
                starts,
                {cell for cell in goals if offers[1].get(cell) == sink},
                frozenset(),
                True,
            )
        # Exhausting attachment groups says nothing about other legal paths.
        # The caller retains normal search within its existing bounded slots.
        return starts, goals, frozenset(), False


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


def _dependency_order(
    preferred: Sequence[int], dependents: Mapping[int, Collection[int]]
) -> tuple[int, ...] | None:
    """Order a reconstruction by provider readiness, then heuristic priority.

    Providers outside ``preferred`` remain staked. A cycle refuses the entire
    transaction before withdrawal, rather than returning a usable-looking prefix.
    """
    rank = {index: position for position, index in enumerate(preferred)}
    waiting = dict.fromkeys(preferred, 0)
    for provider in preferred:
        for dependent in dependents.get(provider, ()):
            if dependent in waiting:
                waiting[dependent] += 1
    ready = [rank[index] for index, count in waiting.items() if count == 0]
    heapq.heapify(ready)
    ordered: list[int] = []
    while ready:
        index = preferred[heapq.heappop(ready)]
        ordered.append(index)
        for dependent in dependents.get(index, ()):
            if dependent in waiting:
                waiting[dependent] -= 1
                if waiting[dependent] == 0:
                    heapq.heappush(ready, rank[dependent])
    return tuple(ordered) if len(ordered) == len(preferred) else None


def _band_route_bounds(
    base: tuple[int, int, int, int],
    bounds: tuple[int, int, int, int],
    policy: BandPolicy,
    deadline: float | None,
) -> tuple[int, int, int, int] | None:
    """Choose one legal routing frame containing the unmodified canvas.

    Cleanup has not been certified yet, so its hypothetical smaller extent
    cannot provide room for ordinary paths or connector footprints.
    """
    capacity = (
        min(base[0], bounds[0]),
        min(base[1], bounds[1]),
        max(base[2], bounds[2]),
        max(base[3], bounds[3]),
    )
    envelope = finalize.band_policy_search_envelope(policy, perimeter=0)
    base_width, base_height = base[2] - base[0] + 1, base[3] - base[1] + 1
    width = capacity[2] - capacity[0] + 1
    while width >= base_width and not envelope.frame_candidates(width, base_height):
        if _expired(deadline):
            raise _PreparationDeadline
        width -= 1
    height = capacity[3] - capacity[1] + 1
    while height >= base_height and not envelope.frame_candidates(width, height):
        if _expired(deadline):
            raise _PreparationDeadline
        height -= 1
    if width < base_width or height < base_height:
        return None
    x0 = max(capacity[0], min(base[0] - (width - base_width) // 2, capacity[2] - width + 1))
    y0 = max(capacity[1], min(base[1] - (height - base_height) // 2, capacity[3] - height + 1))
    limited = (
        max(bounds[0], x0),
        max(bounds[1], y0),
        min(bounds[2], x0 + width - 1),
        min(bounds[3], y0 + height - 1),
    )
    return limited if limited[0] <= limited[2] and limited[1] <= limited[3] else None


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
    prioritize_source_families: bool = True,
    settle: Callable[[_Canvas, tuple[frozenset[NetId], ...]], RouteSettlement] | None = None,
    flow_limits: RoutingFlowLimits | None = None,
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
    # Search reservations and failed physical transactions are private. Only a
    # successfully linked, exactly selected workspace may replace the caller.
    destination_canvas = canvas
    canvas = canvas.clone()
    junction_obstacle_span = max(
        (
            _static_collider_span(canvas.buildings[index])
            for index in (
                *canvas.buildings.machines(),
                *canvas.buildings.by_kind(BuildingKind.OTHER),
            )
        ),
        default=0.0,
    )
    power_discs = (
        None
        if planned_power_sites is None
        else _power_coverage_discs(
            canvas.buildings,
            planned_power_sites,
            tower=canvas.power_building,
        )
    )

    def connector_is_powered(building: PlacedBuilding) -> bool:
        return power_discs is None or _buildings_are_powered((building,), power_discs)

    history: dict[tuple[int, int, int], float] = defaultdict(float)
    primitives = RoutePrimitives(canvas.belt_rules)
    geometry_world: projection_world.GeometricWorld | None = None
    geometry_screen: FlatScreen | None = None
    #: The live routing -- net index to path -- and the same cells the other way
    #: round.  ``owner`` is what makes a TARGETED rip-up possible: a repair
    #: search that crosses a belt has to be able to say WHOSE belt it crossed.
    #: They are staked and unstaked together, always through `_stake`/`_unstake`,
    #: because `canvas.blocked`, `grid.occ` and `owner` disagreeing is a router
    #: that quietly routes through a committed belt.
    paths = StakedPaths(_STEPS)
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
    best_paths: Mapping[int, tuple[Cell, ...]] = MappingProxyType({})
    best_failures: dict[int, NetFailure] = {}
    best_source_hints: dict[int, Cell] = {}
    best_path_taps: dict[int, Cell] = {}
    best_sink_hints: dict[int, Cell] = {}
    round_expansions: dict[int, int] = {}
    contextual_seen = False
    proposals: dict[int, _RouteProposal] = {}
    proposal_used = False
    commit_attempt: _CommittedAttempt | None = None
    best_attempt: _CommittedAttempt | None = None

    def _net_id(index: int) -> NetId:
        net_id = nets[index].net_id
        if net_id is None:
            raise ValueError("detailed routing requires stable net IDs")
        return net_id

    def _endpoint_cells(net: _Net) -> tuple[Cell | None, Cell]:
        source = None if net.src is None else (net.src.x, net.src.y, net.src.z)
        return source, (net.dst.x, net.dst.y, net.dst.z)

    def role_rows() -> Iterator[tuple[NetId, str, str, Cell, str, tuple[int, _Net]]]:
        for index, net in enumerate(nets):
            net_id = _net_id(index)
            payload = (index, net)
            if net.src is not None:
                yield (net_id, net.item, "", (net.src.x, net.src.y, net.src.z), "src", payload)
            yield net_id, net.item, "", (net.dst.x, net.dst.y, net.dst.z), "dst", payload

    net_index = Nets.of(role_rows())

    def _blocking_endpoint_cells(
        blocking_nets: tuple[NetId, ...],
    ) -> tuple[tuple[Cell | None, Cell | None], ...]:
        return tuple(
            _endpoint_cells(record[1])
            if (record := net_index.by_id(blocker)) is not None
            else (None, None)
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
        *,
        interrupted: bool = False,
    ) -> DetailedRouteResult:
        # No further search or settlement is allowed. Hierarchy still needs its
        # selected diagnostic incumbent physically linked; standalone routing
        # retains its existing evidence-only BUDGET contract.
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
        if settle is not None and not interrupted:
            selected_best = selected_paths is best_paths
            return _finish(
                selected_paths,
                failures,
                best_source_hints if selected_best else source_hint,
                best_sink_hints if selected_best else sink_hint,
                best_path_taps if selected_best else path_tap,
                budget_exhausted=True,
                attempt=best_attempt if selected_best else commit_attempt,
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

    def _selection_key(
        selected_paths: Mapping[int, tuple[Cell, ...]],
        selected_source_hints: Mapping[int, Cell],
        selected_sink_hints: Mapping[int, Cell],
        selected_taps: Mapping[int, Cell],
    ) -> tuple[object, ...]:
        # Paths are immutable; retain their order and the actual physical
        # witnesses, not a mutable mapping or just the projected stack bodies.
        return (
            tuple(
                (
                    index,
                    path,
                    selected_source_hints.get(index),
                    selected_sink_hints.get(index),
                    selected_taps.get(index),
                    primitives.on_path(path),
                )
                for index, path in selected_paths.items()
            ),
            frozenset(canvas.guard),
            primitives.rules,
            canvas.belt_rules,
        )

    def _commit_selection(
        selected_paths: Mapping[int, tuple[Cell, ...]],
        selected_source_hints: Mapping[int, Cell],
        selected_sink_hints: Mapping[int, Cell],
        selected_taps: Mapping[int, Cell],
        *,
        settle_complete: bool = True,
    ) -> _CommittedAttempt:
        selection = _selection_key(
            selected_paths, selected_source_hints, selected_sink_hints, selected_taps
        )
        workspace = canvas.clone()
        workspace.guard.intersection_update(permanent_guard)
        details: dict[int, _CommitFailure] = {}
        ownership = RouteOwnership(len(workspace.buildings))
        try:
            unlinked = _commit_paths(
                workspace,
                nets,
                selected_paths,
                belt_id,
                belt_model,
                src_group=src_group,
                dst_group=dst_group,
                source_hints=selected_source_hints,
                sink_hints=selected_sink_hints,
                failure_details=details,
                primitives=primitives,
                source_taps=selected_taps,
                deadline=deadline,
                ownership=ownership,
            )
        except _PreparationDeadline as error:
            error.failures.update(
                (
                    index,
                    _failure(
                        index,
                        _PathSearchResult(
                            None,
                            RouteFailureKind.COMMIT_LINK,
                            ()
                            if detail.side == "contextual"
                            else (detail.cell, *detail.blocking_cells),
                            0,
                        ),
                        tuple(_net_id(blocker) for blocker in detail.blocking_indices),
                    ),
                )
                for index, detail in details.items()
            )
            raise
        attempt = _CommittedAttempt(
            workspace, ownership.snapshot(), unlinked, details, selection=selection
        )
        if (
            not unlinked
            and len(selected_paths) == len(nets)
            and settle_complete
            and settle is not None
        ):
            try:
                attempt.settlement = (
                    RouteSettlementCancelled("routing-settlement")
                    if _expired(deadline)
                    else settle(workspace, attempt.ownership)
                )
                if not isinstance(
                    attempt.settlement,
                    (
                        RouteSettlementCompleted,
                        RouteSettlementRefused,
                        RouteSettlementCancelled,
                        RouteSettlementCrashed,
                    ),
                ):
                    raise TypeError("settlement callback returned an unknown outcome")
            except _PreparationDeadline:
                attempt.settlement = RouteSettlementCancelled("routing-settlement")
            except Exception as error:
                attempt.settlement = RouteSettlementCrashed(error, error.__traceback__)
            if isinstance(attempt.settlement, RouteSettlementRefused):
                owners = attempt.settlement.owners
                detours = {
                    index: frozenset(
                        cell
                        for hint in attempt.settlement.interior_detours
                        if _net_id(index) in hint.owners
                        for cell in hint.cells
                    ).intersection(path[1:-1])
                    for index, path in selected_paths.items()
                    if any(
                        _net_id(index) in hint.owners
                        for hint in attempt.settlement.interior_detours
                    )
                }
                implicated = tuple(
                    index
                    for index in selected_paths
                    if (owners is not None and _net_id(index) in owners) or detours.get(index)
                )
                attempt.unlinked = implicated
                attempt.details = {
                    index: _CommitFailure(
                        selected_paths[index][0],
                        "contextual",
                        blocking_indices=tuple(other for other in implicated if other != index),
                        reason=attempt.settlement.reason,
                        interior_detour=detours.get(index, frozenset()),
                    )
                    for index in implicated
                }
        return attempt

    def _finish(
        selected_paths: Mapping[int, tuple[Cell, ...]],
        selected_failures: dict[int, NetFailure],
        selected_source_hints: Mapping[int, Cell],
        selected_sink_hints: Mapping[int, Cell],
        selected_taps: Mapping[int, Cell],
        *,
        budget_exhausted: bool,
        exhaustive_claim: bool = False,
        attempt: _CommittedAttempt | None = None,
    ) -> DetailedRouteResult:
        # `selected_paths` may be an incumbent from an earlier RRR round, while
        # `canvas.guard` describes only the last round. Conditional junction
        # guards are search state, not physical buildings; committing an older
        # topology against newer guards creates false lattice collisions.
        # Permanent pre-existing Splitter guards remain authoritative.
        if junction_frame_bans and canvas.junction_projection is None:
            selected_tap_cells = frozenset(selected_taps.values())
            assert any(
                all(tap not in frame_ban for tap in selected_tap_cells)
                for frame_ban in junction_frame_bans
            ), "the selected routing incumbent has no shared projection frame"
        if attempt is None or attempt.selection != _selection_key(
            selected_paths, selected_source_hints, selected_sink_hints, selected_taps
        ):
            attempt = _commit_selection(
                selected_paths,
                selected_source_hints,
                selected_sink_hints,
                selected_taps,
                settle_complete=not budget_exhausted,
            )
        # Transfer every owned mutable index/reservation together. Refused or
        # cancelled callbacks may have mutated their workspace; never publish it.
        if not attempt.unlinked and (
            attempt.settlement is None or isinstance(attempt.settlement, RouteSettlementCompleted)
        ):
            destination_canvas.__dict__.update(attempt.workspace.__dict__)
        details, unlinked = attempt.details, attempt.unlinked
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
        if attempt is not None:
            if isinstance(attempt.settlement, RouteSettlementCancelled):
                status = DetailedRouteStatus.BUDGET
            elif isinstance(attempt.settlement, (RouteSettlementRefused, RouteSettlementCrashed)):
                status = DetailedRouteStatus.STRANDED
        # A claim is only about the routing being RETURNED.  The cluster search
        # closed its tree over one round's stranded set; if the incumbent that
        # survives strands anything else -- or strands the same nets for a
        # reason a budget cut off -- the proof does not describe it.
        exhaustive = (
            exhaustive_claim
            and status is DetailedRouteStatus.STRANDED
            and not contextual_seen
            and set(failures) == proved_stranded
            and not any(failure.kind is RouteFailureKind.BUDGET for failure in ordered_failures)
        )
        return DetailedRouteResult(
            status=status,
            routed=routed,
            failures=ordered_failures,
            iterations=iterations,
            expansions=expansions,
            exhaustive=exhaustive,
            last_mile=_last_mile_report(),
            settlement=None if attempt is None else attempt.settlement,
        )

    if canvas.junction_projection is not None:
        try:
            frame_bounds = _band_route_bounds(
                _core_bounds(canvas),
                canvas.limit or canvas.junction_projection.capacity,
                canvas.junction_projection.policy,
                deadline,
            )
        except _PreparationDeadline:
            frame_bounds = None
        if frame_bounds is None:
            missing = _PathSearchResult(None, RouteFailureKind.BUDGET, (), 0)
            return DetailedRouteResult(
                status=DetailedRouteStatus.BUDGET,
                routed=(),
                failures=tuple(_failure(index, missing, ()) for index in range(len(nets))),
                iterations=0,
                expansions=0,
                settlement=(
                    None
                    if _expired(deadline)
                    else RouteSettlementRefused(
                        "no legal requested-band envelope contains the unmodified routing canvas",
                        None,
                    )
                ),
            )
        # Preserve the entry ring for later boundary outputs; the internal
        # search box is narrower than the complete canvas capacity.
        canvas.limit = frame_bounds
        bounds = _route_box(canvas, bounds)

    if not canvas.port_corridors:
        _reserve_port_access(canvas, _port_access_inventory(nets).demands)

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
    corridor_reservations = _CorridorReservations(canvas, grid, owner)

    # Nets that end at the same physical lane share destination topology even
    # when they carry different items.  Entry lanes are deliberately mixed:
    # the sorters select each recipe input from that one belt.  Including
    # ``item`` here prevented the third material from merging after two routes
    # had occupied the only direct approaches to a shared lane head.
    same_dst: dict[tuple[CargoDomain, int, int, int], list[int]] = defaultdict(list)
    for i, net in enumerate(nets):
        same_dst[net.cargo_domain, net.dst.x, net.dst.y, net.dst.z].append(i)
    dst_group = {
        i: tuple(g for g in same_dst[net.cargo_domain, net.dst.x, net.dst.y, net.dst.z] if g != i)
        for i, net in enumerate(nets)
    }
    # The same story on the producer side, and it needs the same answer. An
    # out-lane sandwiched between its neighbours is only reachable at its ends,
    # so walking it tile by tile hands the later nets a walled-in start. They
    # BRANCH instead: leave from a sibling's path, which becomes a splitter on
    # that path at commit time. Keyed by ITEM, DOMAIN, and declared physical
    # supply, or the ordinary lane (row, west edge, level), not the fixed tap.
    same_src: dict[_SourceGroupKey, list[int]] = defaultdict(list)
    for i, net in enumerate(nets):
        same_src[_source_group_key(net.item, net.cargo_domain, net.source)].append(i)
    src_group = {
        i: tuple(
            g for g in same_src[_source_group_key(net.item, net.cargo_domain, net.source)] if g != i
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
    junction_reservation_blockers: set[int] = set()

    @cache
    def _junction_stacks_collide(existing: Cell, candidate: Cell) -> bool:
        """Cache a shape pair, independent of whether either tap is selected."""
        nearby = _splitter_stack_geometry(*existing)
        return any(
            _building_collider_hits(nearby, member)
            for member in _splitter_stack_geometry(*candidate)
        )

    def _can_junction(x: int, y: int, level: int, *, project: bool = True) -> bool:
        cell = (x, y, level)
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
        if any(
            (tx, ty, tz) != cell
            and abs(tx - x) <= 3
            and abs(ty - y) <= 3
            and abs(tz - level) <= 3
            and _junction_stacks_collide((tx, ty, tz), cell)
            for tx, ty, tz in planned_taps
        ):
            return False
        got = junction_ok.get(cell)
        if got is None:
            stack = _splitter_stack_geometry(x, y, level)
            got = canvas._junction_geometry_is_clear(
                x, y, level, obstacle_span=junction_obstacle_span
            ) and (power_discs is None or _buildings_are_powered(stack, power_discs))
            junction_ok[cell] = got
        if not got:
            return False
        # Endpoint offers defer the whole-selection proof until _search knows
        # the chosen path and tap. Future-tap and cluster promises still ask it
        # here; speculative offers are not construction certificates.
        if project and canvas.junction_projection is not None:
            selected = primitives.selection(paths, (*planned_taps, cell))
            if not canvas.projected_buildings_are_clear(selected, deadline=deadline):
                return False
        elif (
            canvas.junction_projection is None
            and junction_frame_bans
            and not any(
                cell not in frame_ban and all(tap not in frame_ban for tap in planned_taps)
                for frame_ban in junction_frame_bans
            )
        ):
            return False
        # Reservations change with the active endpoints and rip-up; unlike
        # physical clearance, ownership cannot be cached in junction_ok.
        denied = False
        for member in _splitter_stack_geometry(x, y, level):
            for guard_cell in junction.keepout_cells(
                x, y, int(member.z), model_index=member.model_index, yaw=member.yaw
            ):
                key = canvas.reserved.get(guard_cell)
                if key is None or key in canvas.routing_ports:
                    continue
                denied = True
                for corridor in canvas.port_corridors.get(key, ()):
                    if guard_cell not in (corridor.access, corridor.exit):
                        continue
                    for role, kind in (
                        ("src", PortAccessKind.INTERNAL_DEPARTURE),
                        ("dst", PortAccessKind.INTERNAL_ARRIVAL),
                    ):
                        if corridor.kind in (None, kind):
                            junction_reservation_blockers.update(
                                member for member, _net in net_index.payloads_in_role(key, role)
                            )
        return not denied

    def _direct_tap_clear(
        source: _Port, siblings: tuple[int, ...], *, tentative_ok: bool = False
    ) -> bool:
        tap = (source.x, source.y, source.z)
        # Splitter legality excuses the actual connected run around the tap,
        # not only the source port's declared horizontal lane. A prebuilt
        # proliferator trunk is vertical, and treating its predecessor and
        # successor as foreign belts makes every root falsely unavailable.
        excused = _run_cells(canvas, canvas.buildings.belts_into, source.belt)
        # Connected branches share this source's keep-out even before it is
        # upgraded to a Splitter. Same-family paths passing nearby remain foreign.
        for sibling in siblings:
            sibling_source = nets[sibling].source
            if (
                source_hint.get(sibling, (sibling_source.x, sibling_source.y, sibling_source.z))
                == tap
            ):
                excused.update(paths.get(sibling, ())[:2])
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
                building = canvas.buildings.by_index(who)
                if building is not None and catalog.is_belt(building.item_id):
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
        return x0 <= x <= x1 and y0 <= y <= y1 and 0 <= level < grid.levels

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
        paths.stake(index, path, linked_head=selected[2] is not None or index in path_tap)
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
        primitive_guard = primitives.guards(path).difference(path)
        for cell in primitive_guard:
            guard_claims[cell].add(index)
            canvas.guard.add(cell)
            if _inside_grid(cell) and cell not in owner:
                grid.block(cell)
        if primitive_guard:
            path_guards.setdefault(index, set()).update(primitive_guard)
        corridor_reservations.retire_served_roles(net_index.roles_of(_net_id(index)), path)

    def _unstake(index: int) -> None:
        """Take a path, its exact endpoint, and its conditional guard up."""
        corridor_reservations.restore_unserved_roles(
            (key, role)
            for key, role in net_index.roles_of(_net_id(index))
            if not any(
                member != index and member in paths
                for member, _net in net_index.payloads_in_role(key, role)
            )
        )
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
            # Reservations belong to per-query flags, not hard occupancy.
            # A foreign reservation must not keep a withdrawn guard blocked.
            if (
                cell not in owner
                and cell not in canvas.guard
                and cell not in canvas.blocked
                and _inside_grid(cell)
            ):
                grid.restore(cell)
        source_hint.pop(index, None)
        sink_hint.pop(index, None)
        path = paths[index]
        paths.unstake(index)
        for cell in path:
            if canvas.blocked.get(cell, -1) == _TENTATIVE:
                del canvas.blocked[cell]
                # An owned branch dock can still be guarded by its provider
                # after this path's own claims have been withdrawn.
                if cell in canvas.guard:
                    grid.block(cell)
                else:
                    grid.restore(cell)
            if owner.get(cell) == index:
                del owner[cell]

    _prebuilt_path_port = lru_cache(maxsize=None)(splitter_ports.expected_path_port)

    @cache
    def _prebuilt_branch_port(
        splitter: PlacedBuilding, source_belt: PlacedBuilding, outward: Cell
    ) -> int | None:
        """Reuse only immutable physical shape, never a live admission verdict."""
        attachment = replace(source_belt, z=Fraction(outward[2]))
        return _prebuilt_path_port(
            splitter, attachment, replace(attachment, x=outward[0], y=outward[1])
        )

    def _prebuilt_source_starts(
        index: int,
        source: _Port,
        siblings: tuple[int, ...],
        owned_guard: Mapping[Cell, Cell],
        *,
        needs_junction: bool,
        project: bool = False,
        tentative_ok: bool = False,
    ) -> tuple[list[Cell], list[Cell]]:
        """Admit docks on a declared source with the exact live tap gates."""
        starts: list[Cell] = []
        tap = (source.x, source.y, source.z)
        direct_ports: set[int] = set()
        direct_ports_valid = True
        source_belt = canvas.buildings[source.belt]
        incoming = canvas.buildings.belts_into(source.belt)
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
                feed_port = _prebuilt_path_port(
                    prospective_splitter,
                    source_belt,
                    canvas.buildings[incoming[0]],
                )
                if feed_port is None:
                    direct_ports_valid = False
                else:
                    direct_ports.add(feed_port)
            if source_belt.output_obj is not None:
                carry_port = _prebuilt_path_port(
                    prospective_splitter,
                    source_belt,
                    canvas.buildings[source_belt.output_obj],
                )
                if carry_port is None or carry_port in direct_ports:
                    direct_ports_valid = False
                else:
                    direct_ports.add(carry_port)
            for sibling in sorted(set(siblings) | planned_taps.get(tap, set())):
                sibling_path = paths.get(sibling)
                if not sibling_path:
                    continue
                sibling_source = nets[sibling].source
                selected_tap = source_hint.get(
                    sibling, (sibling_source.x, sibling_source.y, sibling_source.z)
                )
                if selected_tap != tap:
                    continue
                first = sibling_path[0]
                port = _prebuilt_branch_port(prospective_splitter, source_belt, first)
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
                    _can_junction(source.x, source.y, source.z, project=project)
                    and _direct_tap_clear(source, siblings, tentative_ok=tentative_ok)
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
                    port = _prebuilt_branch_port(prospective_splitter, source_belt, cell)
                    if port is None or port in direct_ports:
                        continue
                if (
                    canvas.free(cell)
                    or (owned_guard.get(cell) == tap and canvas.free_owned_guard(cell))
                    or (tentative_ok and canvas.blocked.get(cell) == _TENTATIVE)
                ):
                    starts.append(cell)
                elif cell in owner:
                    occupied_source_access.append(cell)
        return starts, occupied_source_access

    def _ends(
        index: int,
        *,
        tentative_ok: bool = False,
        project_taps: frozenset[Cell] = frozenset(),
        witnessed_taps: dict[Cell, bool] | None = None,
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
        junction_reservation_blockers.clear()
        net = nets[index]
        source_ranges = sink_ranges = None
        if flow_limits is not None:
            if flow_limits.rates[index] > flow_limits.capacity:
                return [], set(), ({}, {}, {})
            source_ranges, sink_ranges = _flow_frontier_ranges(
                index, paths, owner, source_hint, sink_hint, flow_limits
            )
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
        starts, occupied_source_access = _prebuilt_source_starts(
            index,
            source,
            siblings,
            owned_guard,
            needs_junction=needs_junction,
            project=(source.x, source.y, source.z) in project_taps,
            tentative_ok=tentative_ok,
        )
        source_choices = {cell: {(source.x, source.y, source.z)} for cell in starts}
        existing_sink_targets = frozenset(sink_hint.values())
        guard_provenance = dict(source_provenance)
        if needs_junction:
            direct_tap = (source.x, source.y, source.z)
            for cell in starts:
                guard_provenance.setdefault(cell, direct_tap)
        witness: Callable[[Cell, Cell], bool] | None = None
        if witnessed_taps is not None:
            checked_taps = witnessed_taps
            selected_primitives = primitives.selection(paths, planned_taps)

            def admit_witness(cell: Cell, tap: Cell) -> bool:
                if (
                    cell in rejected_starts[index]
                    or cell in existing_sink_targets
                    or tap in rejected_source_hints[index]
                    or _expired(deadline)
                ):
                    return False
                admitted = checked_taps.get(tap)
                if admitted is None:
                    admitted = canvas.projected_buildings_are_clear(
                        () if tap in planned_taps else _splitter_stack_geometry(*tap),
                        selected=selected_primitives,
                        deadline=deadline,
                    )
                    checked_taps[tap] = admitted
                return admitted

            witness = admit_witness
            direct_tap = (source.x, source.y, source.z)
            for cell in starts:
                if witness(cell, direct_tap):
                    return [cell], set(), ({}, {}, {cell: direct_tap})
        source_feeds: dict[int, int] = {}
        for sibling in siblings:
            if sibling not in paths:
                continue
            sibling_source = nets[sibling].source
            tap = source_hint.get(sibling, (sibling_source.x, sibling_source.y, sibling_source.z))
            feeder = canvas.blocked.get(tap)
            if (
                feeder is not None
                and feeder >= 0
                and catalog.is_belt(canvas.buildings[feeder].item_id)
            ):
                source_feeds[sibling] = feeder
        frontier = _merge_frontier(
            canvas,
            paths,
            siblings,
            lambda x, y, level: _can_junction(x, y, level, project=(x, y, level) in project_taps),
            provenance=source_provenance,
            belt_prefab=(belt_id, belt_model),
            tentative_ok=tentative_ok,
            owned_guard=owned_guard,
            primitives=primitives,
            source_choices=source_choices,
            witness=witness,
            deadline=deadline,
            path_ranges=source_ranges,
            merged_cells=existing_sink_targets,
            source_feeds=source_feeds,
        )
        if witness is not None and frontier:
            cell = min(frontier)
            return [cell], set(), ({}, {}, {cell: source_provenance[cell]})
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
        # A sibling may leave a prebuilt source absent from every routed path.
        # Offer its spare docks whether already split or still an ordinary
        # branch, using the same direct-source and physical-port proof.
        selected_sources: set[Cell] = set()
        for sibling in siblings:
            sibling_source = nets[sibling].source
            tap = (sibling_source.x, sibling_source.y, sibling_source.z)
            if (
                tap in selected_sources
                or tap == (source.x, source.y, source.z)
                or tap in rejected_source_hints[index]
                or (tap in planned_taps and not planned_taps[tap] <= sibling_set)
            ):
                continue
            selected_sources.add(tap)
            docks, occupied = _prebuilt_source_starts(
                index,
                sibling_source,
                siblings,
                owned_guard,
                needs_junction=True,
                project=tap in project_taps,
                tentative_ok=tentative_ok,
            )
            occupied_source_access.extend(occupied)
            for cell in docks:
                if witness is not None and witness(cell, tap):
                    return [cell], set(), ({}, {}, {cell: tap})
                source_choices.setdefault(cell, set()).add(tap)
                if cell in starts:
                    continue
                starts.append(cell)
                source_provenance[cell] = tap
                guard_provenance[cell] = tap
        # First-wins provenance is safe only after competing source taps have
        # been certified. Include direct/frontier and prebuilt/frontier clashes,
        # not just alternatives found along one sibling path.
        if witnessed_taps is not None:
            # Every admissible source candidate was checked during generation.
            return [], set(), ({}, {}, {})
        competing = frozenset(
            tap for cell in starts if len(source_choices[cell]) > 1 for tap in source_choices[cell]
        )
        if not competing <= project_taps:
            return _ends(index, tentative_ok=tentative_ok, project_taps=project_taps | competing)
        source_access_walls[index] = tuple(occupied_source_access) if not starts else ()
        # A shared source can become unusable without an occupied access cell:
        # an earlier sibling may consume the only legal branch topology. That
        # sibling is concrete blocking ownership even though the failed A*
        # search has an empty wall.
        source_access_blockers[index] = (
            tuple(
                _net_id(blocker)
                for blocker in sorted(
                    {sibling for sibling in siblings if sibling in paths}
                    | (junction_reservation_blockers - {index})
                )
            )
            if not starts
            else ()
        )
        owned_source_starts[index] = frozenset(set(starts) & owned_guard.keys())
        reverse_link_guard = paths.linked_heads() | _selected_source_heads(
            nets, paths, source_hint, planned_taps
        )

        destination_access = tuple((net.dst.x + dx, net.dst.y + dy, net.dst.z) for dx, dy in _STEPS)
        sink_provenance: dict[Cell, Cell] = {}
        goals = {
            cell
            for cell in destination_access
            if canvas.free(cell) and cell not in rejected_goals[index]
        }
        # Filter tap identities before first-wins provenance: rejecting one
        # target must not discard a dock that can reach another legal target.
        frontier = _merge_frontier(
            canvas,
            paths,
            dst_group.get(index, ()),
            provenance=sink_provenance,
            primitives=primitives,
            path_ranges=sink_ranges,
            protected_sinks=_protected_merge_cells(paths, dst_group.get(index, ()), path_tap)
            | reverse_link_guard
            | rejected_sink_hints[index],
        )
        # The committer prefers a direct destination link over a sibling hint.
        # Freeze the same choice so transit reservations do not charge a
        # sibling suffix the emitted flow never traverses.
        for cell in goals:
            sink_provenance.pop(cell, None)
        goals.update(cell for cell in frontier if cell not in rejected_goals[index])
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

    def _future_source_offers(
        index: int,
        path: tuple[Cell, ...],
        offers: tuple[Mapping[Cell, Cell], Mapping[Cell, Cell], Mapping[Cell, Cell]],
        *,
        tentative_ok: bool = False,
    ) -> dict[Cell, Cell]:
        """Find future taps; tentative mode only discovers repair blockers."""
        routing_ports = canvas.routing_ports
        reservations = corridor_reservations.snapshot()
        _stake(index, path, hints=_selected_hints(path, offers))
        try:
            future: dict[Cell, Cell] = {}
            checked: dict[Cell, bool] = {}
            path_cells = frozenset(path)
            for sibling in src_group.get(index, ()):
                if sibling in paths:
                    continue
                starts, _goals, sibling_offers = _ends(
                    sibling, witnessed_taps=checked, tentative_ok=tentative_ok
                )
                witnessed = False
                for start in starts:
                    source = nets[sibling].source
                    tap = sibling_offers[2].get(start, (source.x, source.y, source.z))
                    assert checked[tap]
                    witnessed = True
                    if tap in path_cells or not future:
                        future = {start: tap}
                    break
                if not witnessed:
                    return {}
            return future
        finally:
            _unstake(index)
            corridor_reservations.restore(reservations)
            canvas.routing_ports = routing_ports

    def _analytic_ordinary(
        starts: list[Cell],
        goals: set[Cell],
        search_history: dict[Cell, float],
        pressure: float,
        query_deadline: float | None,
        *,
        forbidden: Collection[Cell],
        owned_starts: Collection[Cell],
        released_starts: Collection[Cell],
        admit_proposal: Callable[[tuple[Cell, ...], float | None], bool] | None,
    ) -> tuple[Cell, ...] | None:
        """Try complete overhead constructions inside the ordinary query's clock."""
        nonlocal geometry_world, geometry_screen
        try:
            if geometry_world is None:
                geometry_world = projection_world.GeometricWorld(canvas, deadline=query_deadline)
            world = geometry_world
            world.history = search_history
            world.pressure = pressure
            world.forbidden = frozenset(forbidden)
            world.owned_starts = frozenset(owned_starts)
            world.released_starts = frozenset(released_starts)
            if geometry_screen is None:
                geometry_screen = FlatScreen((), query_deadline, world)
            prepared = time.monotonic()
            # The staged proposal slice is part of, never additional to, the
            # existing ordinary allowance. A miss still takes the original A*.
            proposal_deadline = prepared + 0.05
            if query_deadline is not None:
                proposal_deadline = min(proposal_deadline, query_deadline)
            return overhead_path(
                world,
                [cell for cell in starts if _inside_route_box(cell, bounds)],
                {cell for cell in goals if _inside_route_box(cell, bounds)},
                bounds,
                proposal_deadline,
                blocked=tuple(cell for cell in owner if cell in canvas.blocked),
                screen=geometry_screen,
                admit_proposal=admit_proposal,
            )
        except _GeometricDeadline:
            # This proposal family is not an exhaustive geometric search.
            return None

    def _search(
        starts: list[Cell],
        goals: set[Cell],
        junction_offers: Mapping[Cell, Cell],
        search_history: dict[Cell, float],
        pressure: float,
        search_budget: dict[str, int],
        blame: dict[Cell, float] | None,
        search_grid: _Grid,
        *,
        owned_starts: Collection[Cell] = (),
        released_starts: Collection[Cell] = (),
        forbidden: Collection[Cell] = (),
        ordinary_only: bool = False,
        admit_proposal: Callable[[tuple[Cell, ...], float | None], bool] | None = None,
    ) -> _PathSearchResult:
        """Admit source geometry for every normal, repair and cluster search.

        A path may leave a prospective Splitter legally and later return through
        its keepout. Retry that source locally; its geometry must never poison
        another source's cells or a later endpoint query.
        """
        search_starts = starts
        source_choices = {junction_offers.get(cell) for cell in starts}
        search_tap = next(iter(source_choices)) if len(source_choices) == 1 else None
        rejected: set[Cell] | None = None
        rejected_edges: set[tuple[Cell, Cell]] = set()
        total_expansions = 0
        connector_reserve = (
            0 if ordinary_only else min(_MAX_EXPANSIONS + 1, max(0, search_budget["left"]) // 2)
        )
        allowance = min(_MAX_EXPANSIONS + 1, max(0, search_budget["left"] - connector_reserve))
        ordinary_deadline = None
        if deadline is not None:
            now = time.monotonic()
            if now >= deadline:
                return _PathSearchResult(None, RouteFailureKind.BUDGET, (), 0)
            ordinary_deadline = now + (deadline - now) / 8
        ordinary = None
        capped_ordinary = None
        ordinary_remaining = allowance
        ordinary_starts = starts
        ordinary_rejected: dict[Cell, set[Cell]] = {}

        def probe_ordinary(
            candidates: list[Cell], blocked: Collection[Cell]
        ) -> _PathSearchResult | None:
            nonlocal ordinary_remaining, total_expansions, capped_ordinary
            if (
                ordinary_remaining < 2
                or _expired(ordinary_deadline)
                or not candidates
                or all(goal in blocked for goal in goals)
            ):
                return None
            if flow_limits is not None:
                proposed = _analytic_ordinary(
                    candidates,
                    goals,
                    search_history,
                    pressure,
                    ordinary_deadline,
                    forbidden=blocked,
                    owned_starts=owned_starts,
                    released_starts=released_starts,
                    admit_proposal=admit_proposal,
                )
                if proposed is not None:
                    return _PathSearchResult(proposed, None, (), 0)
            private = {"left": ordinary_remaining}
            result = _astar(
                canvas,
                candidates,
                goals,
                search_history,
                pressure,
                bounds,
                budget=private,
                deadline=ordinary_deadline,
                blame=None,
                grid=search_grid,
                owned_starts=owned_starts,
                released_starts=released_starts,
                forbidden=blocked,
                blocking_owners=owner,
                extra_edges=None,
            )
            search_budget["left"] -= ordinary_remaining - private["left"]
            ordinary_remaining = private["left"]
            total_expansions += result.expansions
            if result.path is not None:
                return result
            if result.kind is RouteFailureKind.BUDGET and (
                result.expansions >= _MAX_EXPANSIONS or ordinary_remaining <= 0
            ):
                capped_ordinary = result
            return None

        try:
            ordinary = probe_ordinary(starts, forbidden)
            # Large first passes spend only their ordinary share. Optional physical
            # enrichment belongs to repair, after every net has had an opportunity.
            for retry in range(5):
                if ordinary_only and ordinary is None:
                    return _PathSearchResult(None, RouteFailureKind.BUDGET, (), total_expansions)
                ordinary_attempt = ordinary is not None
                if ordinary_attempt:
                    assert ordinary is not None
                    found = ordinary
                    ordinary = None
                else:
                    if _expired(deadline) or search_budget["left"] <= 0:
                        return _PathSearchResult(
                            None, RouteFailureKind.BUDGET, (), total_expansions
                        )
                    connector_edges = primitives.edges(
                        canvas,
                        search_grid,
                        search_starts,
                        goals,
                        forbidden=forbidden if rejected is None else rejected,
                        excluded_edges=rejected_edges,
                        active_paths=paths,
                        active_taps=(
                            planned_taps if search_tap is None else (*planned_taps, search_tap)
                        ),
                        deadline=deadline,
                        power_allows=connector_is_powered if power_discs is not None else None,
                    )
                    if retry == 0 and not connector_edges and capped_ordinary is not None:
                        # No graph inputs changed. The fallback has no larger
                        # expansion allowance than the exhausted ordinary search.
                        # Repeating its bounded prefix cannot find a new path;
                        # retain the shared quota for other nets, still refusing.
                        return replace(capped_ordinary, expansions=total_expansions)
                    found = _astar(
                        canvas,
                        search_starts,
                        goals,
                        search_history,
                        pressure,
                        bounds,
                        search_budget,
                        deadline,
                        blame,
                        search_grid,
                        owned_starts=owned_starts,
                        released_starts=released_starts,
                        forbidden=forbidden if rejected is None else rejected,
                        blocking_owners=owner,
                        extra_edges=connector_edges,
                    )
                    total_expansions += found.expansions
                if found.path is None:
                    # Connector siting is bounded and keeps one physical witness
                    # per directed edge. Exhausting this subset cannot prove the
                    # complete physical routing problem impossible.
                    return replace(found, kind=RouteFailureKind.BUDGET, expansions=total_expansions)
                if not primitives.path_is_clear(found.path):
                    if retry == 4:
                        return _PathSearchResult(
                            None, RouteFailureKind.BUDGET, (), total_expansions
                        )
                    if ordinary_attempt:
                        continue
                    rejected_edges.update(
                        edge
                        for edge in zip(found.path, found.path[1:], strict=False)
                        if edge in primitives.witnesses
                    )
                    continue
                tap = junction_offers.get(found.path[0])
                proposed_taps = () if tap is None or tap in planned_taps else (tap,)
                if not canvas.projected_buildings_are_clear(
                    primitives.selection({0: found.path}, proposed_taps),
                    selected=primitives.selection(paths, planned_taps),
                    deadline=deadline,
                ):
                    if retry == 4 or _expired(deadline):
                        return _PathSearchResult(
                            None, RouteFailureKind.BUDGET, (), total_expansions
                        )
                    if ordinary_attempt:
                        # Try another ordinary source inside the same allocation.
                        # Keep original offers untouched for enriched fallback:
                        # connector members may admit a different final frame.
                        ordinary_starts = [
                            cell for cell in ordinary_starts if junction_offers.get(cell) != tap
                        ]
                        ordinary = probe_ordinary(ordinary_starts, forbidden)
                        continue
                    macro_edges = {
                        edge
                        for edge in zip(found.path, found.path[1:], strict=False)
                        if edge in primitives.witnesses
                    }
                    if macro_edges:
                        # The rejection belongs to this source selection, not to
                        # another source that might use the same connector legally.
                        search_tap = tap
                        search_starts = [
                            cell for cell in search_starts if junction_offers.get(cell) == tap
                        ]
                        rejected_edges.update(macro_edges)
                    else:
                        search_starts = [
                            cell for cell in search_starts if junction_offers.get(cell) != tap
                        ]
                    continue
                if tap is None:
                    return replace(found, expansions=total_expansions)
                stack = _splitter_stack_geometry(*tap)
                illegal: set[Cell] = set()
                path_cells = set(found.path)
                attached_cells = found.path[:2]
                for offset, member in enumerate(stack):
                    for cell in junction.keepout_cells(
                        tap[0],
                        tap[1],
                        int(member.z),
                        model_index=member.model_index,
                        yaw=member.yaw,
                    ):
                        if cell in path_cells and (
                            offset != len(stack) - 1 or cell not in attached_cells
                        ):
                            illegal.add(cell)
                attachment = (tap[0], tap[1], tap[2] - 1 if tap[2] % 2 else tap[2])
                if attachment in path_cells:
                    illegal.add(attachment)
                if not illegal:
                    return replace(found, expansions=total_expansions)
                if retry == 4:
                    return _PathSearchResult(None, RouteFailureKind.BUDGET, (), total_expansions)
                if ordinary_attempt:
                    # Only this source owns these body constraints. Retrying it
                    # must not ban the same cells for another source or enrichment.
                    source_blocked = ordinary_rejected.setdefault(tap, set(forbidden))
                    source_blocked.update(illegal)
                    ordinary = probe_ordinary(
                        [cell for cell in starts if junction_offers.get(cell) == tap],
                        source_blocked,
                    )
                    if ordinary is None:
                        # A failed detour around this tap's body says nothing
                        # about the other source taps. Keep their original
                        # geometry and spend the remaining ordinary allowance
                        # there, rather than discarding all ordinary sources.
                        ordinary_starts = [
                            cell for cell in ordinary_starts if junction_offers.get(cell) != tap
                        ]
                        ordinary = probe_ordinary(ordinary_starts, forbidden)
                    continue
                if rejected is None:
                    rejected = set(forbidden)
                    search_starts = [cell for cell in starts if junction_offers.get(cell) == tap]
                    search_tap = tap
                rejected.update(illegal)
            raise AssertionError("source admission retry must return")
        except _PreparationDeadline as error:
            error.expansions += total_expansions
            raise

    def _preserves_source_frontier(
        index: int,
        path: tuple[Cell, ...],
        offers: tuple[dict[Cell, Cell], dict[Cell, Cell], dict[Cell, Cell]],
        *,
        proved_future: Mapping[Cell, Cell] | None = None,
    ) -> bool:
        if not any(sibling not in paths for sibling in src_group.get(index, ())):
            return True
        if _expired(deadline):
            raise _PreparationDeadline
        future = (
            _future_source_offers(index, path, offers) if proved_future is None else proved_future
        )
        if not future:
            return False
        for tap in future.values():
            if tap in path:
                offers[2].setdefault(path[0], tap)
                break
        return True

    def _search_route(
        index: int,
        starts: list[Cell],
        goals: set[Cell],
        offers: tuple[dict[Cell, Cell], dict[Cell, Cell], dict[Cell, Cell]],
        pressure: float,
        search_budget: dict[str, int],
        blame: dict[Cell, float],
        *,
        ordinary_only: bool = False,
        constraints: Collection[Cell] = (),
    ) -> _PathSearchResult:
        """Search and admit the same source obligations in every reconstruction."""
        total = 0
        admit_proposal: Callable[[tuple[Cell, ...], float | None], bool] | None = None
        admitted_path: tuple[Cell, ...] | None = None
        admitted_future: dict[Cell, Cell] | None = None
        if any(sibling not in paths for sibling in src_group.get(index, ())):

            def admit_source_family(
                path: tuple[Cell, ...], proposal_deadline: float | None
            ) -> bool:
                nonlocal deadline, admitted_path, admitted_future
                # All synchronous witness helpers share this route-local clock.
                # Narrow it only for the proposal; outer admission keeps its clock.
                route_deadline = deadline
                if proposal_deadline is not None:
                    deadline = (
                        proposal_deadline if deadline is None else min(deadline, proposal_deadline)
                    )
                try:
                    future = _future_source_offers(index, path, offers)
                    if future:
                        admitted_path, admitted_future = path, future
                    return bool(future)
                except _PreparationDeadline as error:
                    raise _GeometricDeadline from error
                finally:
                    deadline = route_deadline

            admit_proposal = admit_source_family

        try:
            for retry in range(5):
                found = _search(
                    starts,
                    goals,
                    offers[2],
                    history,
                    pressure,
                    search_budget,
                    blame,
                    grid,
                    owned_starts=owned_source_starts.get(index, ()),
                    forbidden=frozenset(rejected_path_cells.get(index, ()))
                    | frozenset(constraints),
                    ordinary_only=ordinary_only,
                    admit_proposal=admit_proposal,
                )
                total += found.expansions
                # No routing state changes between proposal admission and this
                # return. Reuse only the exact immutable path's witness; A* and
                # other proposals still receive their own family proof.
                if found.path is None or _preserves_source_frontier(
                    index,
                    found.path,
                    offers,
                    proved_future=admitted_future if found.path is admitted_path else None,
                ):
                    return replace(found, expansions=total)
                if retry == 4 or _expired(deadline) or search_budget["left"] <= 0:
                    break
                for cell in found.path:
                    history[cell] += _BLAME_WEIGHT
                grid.refresh_history(history)
            # Bounded alternatives did not preserve the family. This is not an
            # exhausted geometric search and cannot establish an impossibility.
            return _PathSearchResult(None, RouteFailureKind.BUDGET, (), total)
        except _PreparationDeadline as error:
            error.expansions += total
            error.net_index = index
            raise

    def _route_order(
        indices: Collection[int], dependents: Mapping[int, Collection[int]]
    ) -> tuple[int, ...] | None:
        preferred = sorted(
            indices,
            key=lambda i: (
                not any(member in priority for member in source_family[i]),
                _net_id(i).role is not NetRole.PROLIFERATOR,
                -len(source_family[i]) if prioritize_source_families else 0,
                -source_family_distance[i],
                source_family[i][0],
                -route_distance[i],
                i,
            ),
        )
        return _dependency_order(preferred, dependents)

    def _endpoint_dependents() -> dict[int, set[int]]:
        """Resolve frozen endpoint promises before any provider is withdrawn."""
        dependents: dict[int, set[int]] = defaultdict(set)
        for index in paths:
            for hint in (source_hint.get(index), sink_hint.get(index), path_tap.get(index)):
                provider = owner.get(hint) if hint is not None else None
                if provider is not None and provider != index:
                    dependents[provider].add(index)
        return dependents

    def _dependency_closure(indices: Collection[int]) -> set[int]:
        dependents = _endpoint_dependents()
        closure = set(indices)
        pending = list(indices)
        while pending:
            for index in dependents.get(pending.pop(), ()):
                if index not in closure:
                    closure.add(index)
                    pending.append(index)
        return closure

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
        repair_guards = set(guard_claims)
        for guarded in repair_guards:
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

        def _tap_guard_victims(tap: Cell, excused: Collection[Cell]) -> set[int]:
            victims: set[int] = set()
            stack = _splitter_stack_geometry(*tap)
            for offset, stack_member in enumerate(stack):
                victims.update(
                    _junction_guard_victims(
                        owner,
                        junction.keepout_cells(
                            tap[0],
                            tap[1],
                            int(stack_member.z),
                            model_index=stack_member.model_index,
                            yaw=stack_member.yaw,
                        ),
                        excused=excused if offset == len(stack) - 1 else (),
                    )
                )
            return victims

        def _refresh_repair_guards() -> None:
            nonlocal repair_guards
            for cell in repair_guards - guard_claims.keys():
                if _inside_grid(cell):
                    open_grid.restore(cell)
            for cell in guard_claims.keys() - repair_guards:
                if _inside_grid(cell):
                    open_grid.block(cell)
            repair_guards = set(guard_claims)

        nonlocal expansions

        still: list[int] = []
        for index in stranded:
            victims: set[int] = set()
            repaired = False
            while not _expired(deadline) and budget["left"] > 0:
                if len(victims) > _REPAIR_MAX_VICTIMS:
                    break
                rebuild_order = _route_order(victims, _endpoint_dependents())
                if rebuild_order is None:
                    break
                staked_before = paths.snapshot()
                saved_hints = {
                    hurt: (source_hint.get(hurt), sink_hint.get(hurt), path_tap.get(hurt))
                    for hurt in victims
                }
                discovered: set[int] = set()
                with corridor_reservations.temporarily_released({}) as release:
                    try:
                        for hurt in reversed(rebuild_order):
                            _unstake(hurt)
                        _refresh_repair_guards()
                        # Removing a provider changes both endpoint offers and
                        # their provenance. Never reuse its old attachment.
                        starts, goals, through_offers = _ends(index, tentative_ok=True)
                        starts.extend(source_access_walls.get(index, ()))
                        goals.update(destination_access_walls.get(index, ()))
                        if not starts:
                            blocked_sources = set(source_access_blockers.get(index, ()))
                            discovered.update(
                                sibling for sibling in paths if _net_id(sibling) in blocked_sources
                            )
                        else:
                            through = _search(
                                starts,
                                goals,
                                through_offers[2],
                                history,
                                1.0,
                                budget,
                                None,
                                open_grid,
                                owned_starts=owned_source_starts.get(index, ()),
                                released_starts=source_access_walls.get(index, ()),
                                forbidden=rejected_path_cells.get(index, ()),
                            )
                            canvas.routing_ports = frozenset()
                            expansions += through.expansions
                            round_expansions[index] = (
                                round_expansions.get(index, 0) + through.expansions
                            )
                            if through.path is None:
                                if through.kind is RouteFailureKind.BUDGET:
                                    search_failures[index] = through
                                    search_blockers[index] = ()
                            else:
                                through_path = through.path
                                discovered.update(
                                    owner[cell] for cell in through_path if cell in owner
                                )
                                selected_tap = through_offers[2].get(through_path[0])
                                if selected_tap is not None:
                                    tapped = next(
                                        (
                                            (sibling, position)
                                            for sibling in src_group.get(index, ())
                                            if (
                                                position := paths.position_in(sibling, selected_tap)
                                            )
                                            is not None
                                        ),
                                        None,
                                    )
                                    excused: set[Cell] = set()
                                    if tapped is not None:
                                        sibling, tap_at = tapped
                                        sibling_path = paths[sibling]
                                        excused.update(
                                            sibling_path[max(0, tap_at - 2) : tap_at + 3]
                                        )
                                    discovered.update(_tap_guard_victims(selected_tap, excused))
                                discovered.discard(index)
                                if not discovered:
                                    if _preserves_source_frontier(
                                        index, through_path, through_offers
                                    ):
                                        _stake(
                                            index,
                                            through_path,
                                            hints=_selected_hints(through_path, through_offers),
                                        )
                                        moved = 0
                                        for hurt in rebuild_order:
                                            starts, goals, again_offers = _ends(hurt)
                                            again = _search_route(
                                                hurt,
                                                starts,
                                                goals,
                                                again_offers,
                                                pressure,
                                                budget,
                                                blame,
                                            )
                                            canvas.routing_ports = frozenset()
                                            expansions += again.expansions
                                            round_expansions[hurt] = (
                                                round_expansions.get(hurt, 0) + again.expansions
                                            )
                                            if again.path is None:
                                                if again.kind is RouteFailureKind.BUDGET:
                                                    search_failures[index] = again
                                                    search_blockers[index] = ()
                                                break
                                            _stake(
                                                hurt,
                                                again.path,
                                                hints=_selected_hints(again.path, again_offers),
                                            )
                                            moved += 1
                                        if moved == len(victims):
                                            release.commit()
                                            repaired = True
                                    else:
                                        # A future sibling's Splitter may hit an
                                        # owner that this path never crosses.
                                        future = _future_source_offers(
                                            index,
                                            through_path,
                                            through_offers,
                                            tentative_ok=True,
                                        )
                                        for tap in future.values():
                                            tap_path: Sequence[Cell] = through_path
                                            try:
                                                at = tap_path.index(tap)
                                            except ValueError:
                                                tap_path = paths.get(owner.get(tap, -1), ())
                                                try:
                                                    at = tap_path.index(tap)
                                                except ValueError:
                                                    at = -1
                                            future_excused = (
                                                () if at < 0 else tap_path[max(0, at - 2) : at + 3]
                                            )
                                            discovered.update(
                                                _tap_guard_victims(tap, future_excused)
                                            )
                    finally:
                        if not release.finished:
                            canvas.routing_ports = frozenset()
                            for hurt in (index, *victims):
                                if hurt in paths:
                                    _unstake(hurt)
                            for hurt, path, _linked_head in staked_before:
                                if hurt in saved_hints:
                                    _stake(hurt, path, hints=saved_hints[hurt])
                            paths.restore(staked_before)
                _refresh_repair_guards()
                if repaired:
                    search_failures.pop(index, None)
                    search_blockers.pop(index, None)
                    break
                # Close dependencies only after restoring the original hints.
                # Every retry withdraws at least one newly discovered owner.
                additional = _dependency_closure(discovered) - victims - {index}
                if not additional:
                    break
                victims.update(additional)
            if not repaired:
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

    def _restrict_proposal(
        index: int,
        starts: list[Cell],
        goals: set[Cell],
        offers: tuple[Mapping[Cell, Cell], Mapping[Cell, Cell], Mapping[Cell, Cell]],
        *,
        constraints: Collection[Cell] = (),
    ) -> tuple[list[Cell], set[Cell], frozenset[Cell]]:
        nonlocal proposal_used
        proposal = proposals.get(index)
        if proposal is None or proposal_used:
            return starts, goals, frozenset(constraints)
        # Freeze only when spending an implicated route's positive proposal.
        # The packed buildings, grid base/domain, rules, power policy and spec
        # are immutable owners of this routing call, not per-proposal copies.
        # Preserve selected-path and reservation order, but compare occupancy
        # and ownership maps by content so identical restaking keeps progress.
        reservations = corridor_reservations.snapshot()
        construction = (
            paths.snapshot(),
            frozenset(source_hint.items()),
            frozenset(sink_hint.items()),
            frozenset(path_tap.items()),
            frozenset(primitives.witnesses.items()),
            bytes(grid.occ),
            frozenset(canvas.blocked.items()),
            frozenset(canvas.guard),
            frozenset(owner.items()),
            frozenset((cell, frozenset(claims)) for cell, claims in guard_claims.items()),
            frozenset((member, frozenset(cells)) for member, cells in path_guards.items()),
            frozenset((tap, frozenset(members)) for tap, members in planned_taps.items()),
            reservations.reserved,
            reservations.corridors,
            reservations.grid_reserved,
            reservations.retired_roles,
            canvas.routing_ports,
            owned_source_starts.get(index, frozenset()),
            frozenset(rejected_path_cells.get(index, ())) | frozenset(constraints),
        )
        starts, goals, detour, proposal_used = proposal.restrict(
            starts,
            goals,
            offers,
            construction=construction,
        )
        return starts, goals, frozenset(constraints) | detour

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
        starts, goals, constraints = _restrict_proposal(
            index, starts, goals, _offers, constraints=constraints
        )
        assert all(
            span_x0 <= cell[0] <= span_x1
            and span_y0 <= cell[1] <= span_y1
            and 0 <= cell[2] < grid.levels
            for cell in constraints
        ), "a cluster constraint left the routing grid's indexed extent"
        allowance = min(
            last_mile.B_LOW_LEVEL_EXPANSIONS,
            max(0, budget["left"] - last_mile_floor),
        )
        private = {"left": allowance}
        try:
            return _search_route(
                index, starts, goals, _offers, pressure, private, {}, constraints=constraints
            )
        finally:
            canvas.routing_ports = frozenset()
            budget["left"] -= allowance - private["left"]

    def _cluster_environment() -> last_mile.ClusterEnvironment:
        return last_mile.ClusterEnvironment(
            search=_cluster_search,
            offers=_cluster_offers,
            budget_left=lambda: budget["left"],
            budget_floor=last_mile_floor,
            expired=lambda: _expired(deadline),
            extra_occupancy=primitives.guards,
        )

    def _source_is_junctionable(index: int) -> bool:
        """Whether this net's own source lane could take a splitter.

        `build_cluster` needs it because a cluster is built out of UNSTAKED
        nets, and unstaking is exactly what makes two stranded nets on one
        source lane look independent of each other.  A net with no source port
        has no lane to share, so it never constrains a sibling.
        """
        source = nets[index].src
        if source is None:
            return True
        # Cluster admission runs outside an active endpoint search. Claim only
        # this source, never foreign corridors, and restore the caller context.
        routing_ports = canvas.routing_ports
        canvas.routing_ports = frozenset({(source.x, source.y, source.z)})
        try:
            return _can_junction(source.x, source.y, source.z)
        finally:
            canvas.routing_ports = routing_ports

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
                deadline_remaining=(None if deadline is None else deadline - time.monotonic()),
                owned_starts={
                    index: frozenset(owned_source_starts.get(index, ())) for index in problem.nets
                },
                rejected={
                    index: frozenset(rejected_path_cells.get(index, ())) for index in problem.nets
                },
                blocking_owners=dict(owner),
            )
        )

    def _round_state() -> tuple[object, ...]:
        """Borrowed state, including observable path/reservation insertion order.

        Endpoint walls/blockers and owned starts are deliberately excluded:
        each `_ends` call derives and overwrites them for its next consumer.
        """
        return (
            paths.snapshot(),
            dict(owner),
            bytes(grid.occ),
            set(canvas.guard),
            {cell for cell, holder in canvas.blocked.items() if holder == _TENTATIVE},
            dict(path_tap),
            dict(source_hint),
            dict(sink_hint),
            {tap: set(members) for tap, members in planned_taps.items()},
            {index: set(cells) for index, cells in path_guards.items()},
            {cell: set(claims) for cell, claims in guard_claims.items()},
            corridor_reservations.snapshot(),
        )

    def _restore_staked(
        staked: StakedPathSnapshot,
        held: Mapping[int, tuple[Cell | None, Cell | None, Cell | None]],
        before: tuple[object, ...],
        release: _CorridorRelease,
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
        for index, path, _linked_head in staked:
            if index not in paths:
                _stake(index, path, hints=held[index])
        paths.restore(staked)
        corridor_reservations.restore(release)
        if before == _round_state():
            return True
        last_mile_counts["restore_mismatch"] += 1
        return False

    def _tally(result: last_mile.ClusterResult) -> None:
        nonlocal last_mile_seconds
        last_mile_counts["nodes"] += result.nodes
        last_mile_counts["expansions"] += result.expansions
        last_mile_seconds += result.seconds

    def _solve_cluster(
        problem: last_mile.ClusterProblem,
        environment: last_mile.ClusterEnvironment,
    ) -> last_mile.ClusterResult:
        nonlocal last_mile_seconds
        entry_budget = budget["left"]
        started = time.perf_counter()
        try:
            return last_mile.solve_cluster(problem, environment)
        except _PreparationDeadline:
            # No ClusterResult reaches _tally on interruption. The debited
            # allowance includes earlier completed CBS searches and the stopped
            # query; retain that work without inventing a closed tree or nodes.
            last_mile_counts["expansions"] += entry_budget - budget["left"]
            last_mile_counts["bounded"] += 1
            last_mile_seconds += time.perf_counter() - started
            raise

    def _cluster_is_sibling_free(problem: last_mile.ClusterProblem) -> bool:
        """Whether unstaking the pack can take nothing away from this cluster.

        `_ends` offers merge points onto SIBLING paths, and for a walled-in
        lane that is the only way in.  A net with no siblings had no merge
        frontier to lose, so for such a cluster -- and only such a cluster --
        "every other net removed" is a relaxation rather than a mutilation.
        """
        return not any(
            src_group.get(index, ()) or dst_group.get(index, ()) for index in problem.nets
        )

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
        staked = paths.snapshot()
        # Saved so the round gets its own table back whatever run 2 does to it;
        # `_restore_staked` rebuilds the same content from the paths, and this
        # is the belt to that braces.
        taps_before = {cell: set(members) for cell, members in planned_taps.items()}
        before_all = _round_state()
        with corridor_reservations.temporarily_released({}) as original:
            try:
                for table in rejections:
                    for index in problem.nets:
                        table[index].clear()
                for index in every:
                    _unstake(index)
                # Removing paths re-holds their roles. Release every corridor
                # as well so this world cannot be tighter than the strict run.
                with corridor_reservations.temporarily_released():
                    planned_taps.clear()
                    relaxed_junctions = True
                    _capture(2, problem)
                    return _solve_cluster(problem, _cluster_environment())
            finally:
                relaxed_junctions = False
                planned_taps.clear()
                planned_taps.update(taps_before)
                _restore_staked(staked, held_all, before_all, original)
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

    def _complete_source_dependents(stranded: list[int], providers: Collection[int]) -> list[int]:
        """Consume source taps established by a solved, thinned cluster."""
        nonlocal commit_attempt, expansions
        remaining = list(stranded)
        for index in stranded:
            if not any(sibling in providers for sibling in src_group.get(index, ())):
                continue
            if _expired(deadline) or budget["left"] <= 0:
                break
            before = _round_state()
            staked = paths.snapshot()
            held = {
                member: (source_hint.get(member), sink_hint.get(member), path_tap.get(member))
                for member in paths
            }
            restored = True
            with corridor_reservations.temporarily_released({}) as release:
                try:
                    starts, goals, offers = _ends(index)
                    searched = _search_route(index, starts, goals, offers, pressure, budget, blame)
                    canvas.routing_ports = frozenset()
                    expansions += searched.expansions
                    round_expansions[index] = round_expansions.get(index, 0) + searched.expansions
                    if searched.path is None:
                        search_failures[index] = searched
                        search_blockers[index] = _blocking_nets(
                            searched.wall, source_access_blockers.get(index, ())
                        )
                        round_failures[index] = _failure(index, searched, search_blockers[index])
                    else:
                        _stake(index, searched.path, hints=_selected_hints(searched.path, offers))
                        candidate = commit_once()
                        if terminal_attempt(candidate) or not candidate.unlinked:
                            commit_attempt = candidate
                            release.commit()
                            remaining.remove(index)
                            round_failures.pop(index, None)
                        else:
                            retain_commit_failures(
                                (index,),
                                {
                                    index: candidate.details.get(
                                        index, _CommitFailure(searched.path[0], "contextual")
                                    )
                                },
                            )
                finally:
                    canvas.routing_ports = frozenset()
                    if not release.finished:
                        if index in paths:
                            _unstake(index)
                        restored = _restore_staked(staked, held, before, release)
            if not restored or (commit_attempt is not None and terminal_attempt(commit_attempt)):
                break
        return remaining

    def _last_mile(round_stranded: list[int], round_index: int) -> list[int]:
        """Search the conflict cluster once per pass; see the Phase B spec 5.6."""
        nonlocal last_mile_done, last_mile_floor, proved_round
        nonlocal commit_attempt, proposal_used
        if (
            last_mile_done
            or not round_stranded
            or len(round_stranded) > last_mile.B_MAX_STRANDED
            or budget["left"] <= 0
            or _expired(deadline)
            or (deadline is not None and deadline - time.monotonic() < last_mile.B_MIN_SECONDS)
        ):
            return round_stranded
        last_mile_done = True
        last_mile_counts["invocations"] += 1
        last_mile_floor = budget["left"] - int(last_mile.B_CBS_EXPANSION_SHARE * budget["left"])
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
            endpoints={index: _endpoint_cells(nets[index]) for index in range(len(nets))},
            src_group=src_group,
            dst_group=dst_group,
            source_junctionable=_source_is_junctionable,
        )
        members = set(problem.nets)
        if not _dependency_closure(members) <= members:
            last_mile_counts["bounded"] += 1
            return round_stranded
        staging_order = _route_order(members, _endpoint_dependents())
        if staging_order is None:
            last_mile_counts["bounded"] += 1
            return round_stranded
        last_mile_counts["same_source_dropped"] += problem.same_source_dropped
        # A stranded net the cluster refused is still stranded when the cluster
        # is solved and committed: it was never in the problem, so nothing
        # routed it.  Reporting an empty round for it would tell the caller the
        # pack is finished when one net has no path at all.
        left_out = [index for index in round_stranded if index not in set(problem.stranded)]
        # `paths` is insertion-ordered and only `_stake` writes it, so
        # `list(paths)` IS the stake order -- which the restore has to replay,
        # because `_claim_junction_guard` computes its `excused` set from the
        # sibling paths already down.
        order = [index for index in paths if index in set(problem.nets)]
        released = paths.snapshot()
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

        restored = False
        joint_refused = False
        with corridor_reservations.temporarily_released({}) as release:
            try:
                for index in order:
                    _unstake(index)
                _capture(1, problem)
                for _ in range(_COMMIT_REPAIR_PASSES + 1):
                    proposal_used = False
                    result = _solve_cluster(problem, environment)
                    _tally(result)
                    if result.outcome is not last_mile.ClusterOutcome.SOLVED:
                        if (
                            proposal_used
                            and budget["left"] > last_mile_floor
                            and not _expired(deadline)
                        ):
                            # A positive branch cannot exhaust ordinary routes.
                            # Keep the existing cluster slots and shared quota.
                            continue
                        break
                    # Re-query offers after each stake: preceding cluster paths
                    # may have consumed an endpoint or the only common frame.
                    # A short solved mapping is a refused commit, not a proof.
                    if not all(index in result.paths for index in problem.nets):
                        joint_refused = True
                        last_mile_counts["commit_rejected"] += 1
                        break
                    admitted = True
                    for index in staging_order:
                        path = result.paths[index]
                        starts, goals, offers = _ends(index)
                        if (
                            path[0] not in starts
                            or path[-1] not in goals
                            or not _preserves_source_frontier(index, path, offers)
                        ):
                            admitted = False
                            break
                        _stake(index, path, hints=_selected_hints(path, offers))
                    canvas.routing_ports = frozenset()
                    if not admitted:
                        joint_refused = True
                        last_mile_counts["commit_rejected"] += 1
                        break
                    commit_attempt = commit_once()
                    unlinked_now, details_now = commit_attempt.unlinked, commit_attempt.details
                    if terminal_attempt(commit_attempt) or not unlinked_now:
                        release.commit()
                        if not terminal_attempt(commit_attempt):
                            last_mile_counts["solved"] += 1
                            # Thinning protects the cluster's independent-root
                            # search. Its accepted provider can now offer the
                            # dropped sibling a dock that did not exist before.
                            return _complete_source_dependents(left_out, problem.stranded)
                        return left_out
                    joint_refused = True
                    last_mile_counts["commit_rejected"] += 1
                    retain_commit_failures(unlinked_now, details_now)
                    for index in problem.nets:
                        if index in paths:
                            _unstake(index)
            finally:
                if not release.finished:
                    for index in problem.nets:
                        if index in paths:
                            _unstake(index)
                    restored = _restore_staked(released, held, before, release)

        if (
            result.outcome is last_mile.ClusterOutcome.PROVED
            and restored
            and not joint_refused
            and not contextual_seen
        ):
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
        index: tuple(sorted((index, *src_group.get(index, ())))) for index in range(len(nets))
    }
    source_family_distance = {
        index: max(route_distance[member] for member in source_family[index])
        for index in range(len(nets))
    }

    priority: set[int] = set()
    coverage_first = len(nets) >= _SINGLE_ROUND_NETS
    round_limit = 1 if coverage_first else RRR_MAX
    search_failures: dict[int, _PathSearchResult] = {}
    search_blockers: dict[int, tuple[NetId, ...]] = {}
    round_failures: dict[int, NetFailure] = {}
    try:
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
            search_failures = {}
            search_blockers = {}
            round_failures = {}
            #: Cells that CUT the board this round, and how many nets each cut off.
            #:
            #: Fresh every round, because a wall only exists while the path that
            #: built it does; `history` is where the charge accumulates.
            blame: dict[Cell, float] = {}
            order = _route_order(range(len(nets)), {})
            assert order is not None
            stranded: list[int] = []
            for position, i in enumerate(order):
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
                allowance = budget["left"] // (len(order) - position)
                net_budget = {"left": allowance} if coverage_first else budget
                try:
                    searched = _search_route(
                        i,
                        starts,
                        goals,
                        route_offers,
                        pressure,
                        net_budget,
                        blame,
                        ordinary_only=coverage_first,
                    )
                finally:
                    if coverage_first:
                        budget["left"] -= allowance - net_budget["left"]
                search_expansions = searched.expansions
                if searched.path is None and not searched.wall:
                    access_wall = source_access_walls.get(i, ()) + destination_access_walls.get(
                        i, ()
                    )
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
            def commit_once() -> _CommittedAttempt:
                return _commit_selection(paths, source_hint, sink_hint, path_tap)

            def terminal_attempt(attempt: _CommittedAttempt) -> bool:
                return isinstance(
                    attempt.settlement, (RouteSettlementCancelled, RouteSettlementCrashed)
                ) or (
                    isinstance(attempt.settlement, RouteSettlementRefused) and not attempt.unlinked
                )

            def retain_commit_failures(
                unlinked: Collection[int],
                details: Mapping[int, _CommitFailure],
                *,
                retained_failures: dict[int, NetFailure] = round_failures,
                retained_blockers: dict[int, tuple[NetId, ...]] = search_blockers,
            ) -> None:
                nonlocal contextual_seen
                for index in unlinked:
                    detail = details.get(
                        index,
                        _CommitFailure(paths[index][0], "path"),
                    )
                    if detail.side == "contextual":
                        contextual_seen = True
                        if index not in proposals:
                            proposals[index] = _RouteProposal(
                                (source_hint.get(index), path_tap.get(index)),
                                sink_hint.get(index),
                            )
                        if detail.interior_detour:
                            proposals[index].detours.setdefault(detail.interior_detour, None)
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
                    elif detail.side == "path":
                        rejected_path_cells[index].add(detail.cell)
                    if detail.side != "contextual":
                        history[detail.cell] += _BLAME_WEIGHT
                        for blocking_cell in detail.blocking_cells:
                            history[blocking_cell] += _BLAME_WEIGHT
                    endpoint_source, endpoint_destination = _endpoint_cells(nets[index])
                    blockers = tuple(_net_id(blocker) for blocker in detail.blocking_indices)
                    retained_failures[index] = NetFailure(
                        _net_id(index),
                        RouteFailureKind.COMMIT_LINK,
                        ()
                        if detail.side == "contextual"
                        else (detail.cell, *detail.blocking_cells),
                        blockers,
                        0,
                        source=endpoint_source,
                        destination=endpoint_destination,
                        blocking_endpoints=_blocking_endpoint_cells(blockers),
                    )
                    if detail.side == "contextual":
                        retained_blockers[index] = blockers

            commit_attempt = commit_once()
            if terminal_attempt(commit_attempt):
                return _finish(
                    paths,
                    round_failures,
                    source_hint,
                    sink_hint,
                    path_tap,
                    budget_exhausted=False,
                    attempt=commit_attempt,
                )
            unlinked, details = commit_attempt.unlinked, commit_attempt.details
            if not unlinked:
                if failed == 0:
                    return _finish(
                        paths,
                        {},
                        source_hint,
                        sink_hint,
                        path_tap,
                        budget_exhausted=False,
                        attempt=commit_attempt,
                    )
            else:
                retain_commit_failures(unlinked, details)

                # Move only rejected paths and the exact endpoint promises that
                # depend on them. A failed transaction must not withdraw valid
                # siblings merely because they share a supply or destination.
                pending = tuple(unlinked)
                stalled_commit: list[int] = []
                for _ in range(_COMMIT_REPAIR_PASSES):
                    if _expired(deadline) or budget["left"] <= 0:
                        break
                    rejected_now = set(pending)
                    participants = _dependency_closure(pending)
                    order = _route_order(participants, _endpoint_dependents())
                    if order is None:
                        break
                    proposal_used = False
                    staked_before = paths.snapshot()
                    held_before = {
                        index: (source_hint.get(index), sink_hint.get(index), path_tap.get(index))
                        for index in paths
                    }
                    state_before = _round_state()
                    release_before = corridor_reservations.snapshot()
                    for index in reversed(order):
                        _unstake(index)
                    stalled_now: list[int] = []
                    for index in order:
                        if _expired(deadline) or budget["left"] <= 0:
                            stalled_now.append(index)
                            break
                        starts, goals, reroute_offers = _ends(index)
                        starts, goals, constraints = _restrict_proposal(
                            index, starts, goals, reroute_offers
                        )
                        searched = _search_route(
                            index,
                            starts,
                            goals,
                            reroute_offers,
                            pressure,
                            budget,
                            blame,
                            constraints=constraints,
                        )
                        canvas.routing_ports = frozenset()
                        expansions += searched.expansions
                        round_expansions[index] = (
                            round_expansions.get(index, 0) + searched.expansions
                        )
                        if searched.path is None:
                            stalled_now.append(index)
                            break
                        _stake(
                            index,
                            searched.path,
                            hints=_selected_hints(searched.path, reroute_offers),
                        )

                    candidate_attempt = None if stalled_now else commit_once()
                    if candidate_attempt is None or (
                        not terminal_attempt(candidate_attempt)
                        and not set(candidate_attempt.unlinked) <= rejected_now
                    ):
                        canvas.routing_ports = frozenset()
                        for index in order:
                            if index in paths:
                                _unstake(index)
                        if not _restore_staked(
                            staked_before, held_before, state_before, release_before
                        ):
                            return _budget_result(paths, round_failures)
                        if candidate_attempt is None and proposal_used:
                            # A spent positive branch cannot rule out ordinary
                            # routing or the remaining endpoint alternatives.
                            # Use only the repair slots already allocated.
                            continue
                        break
                    commit_attempt = candidate_attempt
                    if terminal_attempt(commit_attempt):
                        return _finish(
                            paths,
                            round_failures,
                            source_hint,
                            sink_hint,
                            path_tap,
                            budget_exhausted=False,
                            attempt=commit_attempt,
                        )
                    pending, details = commit_attempt.unlinked, commit_attempt.details
                    if pending:
                        retain_commit_failures(pending, details)
                    failed_now = set(stalled_now) | set(pending)
                    for resolved in rejected_now - failed_now:
                        round_failures.pop(resolved, None)
                    if not pending:
                        break

                # Remove only actual failures and their transitive dependents, then
                # prove the retained subset again. Removal can change physical
                # attachment choices, so an earlier workspace is not its proof.
                while pending:
                    withdrawn = _dependency_closure(pending)
                    # Preserve feedback for dependents too, while their selected
                    # provider coordinates still resolve in the live ownership map.
                    for index in withdrawn - round_failures.keys():
                        providers = {
                            owner[hint]
                            for hint in (
                                source_hint.get(index),
                                sink_hint.get(index),
                                path_tap.get(index),
                            )
                            if hint is not None and hint in owner and owner[hint] in withdrawn
                        }
                        round_failures[index] = _failure(
                            index,
                            _PathSearchResult(None, RouteFailureKind.COMMIT_LINK, (), 0),
                            tuple(_net_id(provider) for provider in sorted(providers)),
                        )
                    for index in withdrawn:
                        if index in paths:
                            _unstake(index)
                    stalled_commit.extend(withdrawn)
                    if _expired(deadline):
                        return _budget_result(paths, round_failures)
                    commit_attempt = commit_once()
                    pending, details = commit_attempt.unlinked, commit_attempt.details
                    if pending:
                        retain_commit_failures(pending, details)
                stranded = list(dict.fromkeys((*stranded, *stalled_commit)))
                failed = len(stranded)
                if failed == 0:
                    return _finish(
                        paths,
                        {},
                        source_hint,
                        sink_hint,
                        path_tap,
                        budget_exhausted=False,
                        attempt=commit_attempt,
                    )
            if failed:
                stranded = _last_mile(stranded, it)
                failed = len(stranded)
                round_failures = {
                    index: round_failures[index] for index in stranded if index in round_failures
                }
                if failed == 0:
                    return _finish(
                        paths,
                        {},
                        source_hint,
                        sink_hint,
                        path_tap,
                        budget_exhausted=False,
                        attempt=commit_attempt,
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
                fewest_failed, stale, best_paths = failed, 0, MappingProxyType(dict(paths))
                best_round = it
                best_failures = dict(round_failures)
                best_source_hints = {
                    index: hint for index, hint in source_hint.items() if index in best_paths
                }
                best_sink_hints = {
                    index: hint for index, hint in sink_hint.items() if index in best_paths
                }
                best_path_taps = {
                    index: tap for index, tap in path_tap.items() if index in best_paths
                }
                best_attempt = commit_attempt
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
            attempt=best_attempt,
        )
    except _PreparationDeadline as error:
        # Interrupted exact projection/linking provides no geometry verdict.
        # Preserve only completed searches and failures recorded before it.
        expansions += error.expansions
        if error.net_index is not None:
            round_expansions[error.net_index] = (
                round_expansions.get(error.net_index, 0) + error.expansions
            )
        current_failures = {
            index: _failure(index, failed_search, search_blockers.get(index, ()))
            for index, failed_search in search_failures.items()
            if index not in paths
        }
        current_failures.update(round_failures)
        current_failures.update(error.failures)
        return _budget_result(paths, current_failures, interrupted=True)


class PortAccessKind(Enum):
    """One physical use of the free cells beside a lane head."""

    INTERNAL_ARRIVAL = "internal-arrival"
    INTERNAL_DEPARTURE = "internal-departure"
    BOUNDARY_ARRIVAL = "boundary-arrival"
    EARLY_BOUNDARY_DEPARTURE = "early-boundary-departure"

    @property
    def reaches_boundary(self) -> bool:
        return self in {
            PortAccessKind.BOUNDARY_ARRIVAL,
            PortAccessKind.EARLY_BOUNDARY_DEPARTURE,
        }


@dataclass(frozen=True, slots=True)
class PortAccessDemand:
    """One cell-disjoint physical approach claim at a lane head."""

    cell: Cell
    kind: PortAccessKind
    item: str
    belt: int
    strip_index: int | None
    columns: int

    def __post_init__(self) -> None:
        if self.columns <= 0:
            raise ValueError("port access demand requires a positive lane width")


@dataclass(frozen=True, slots=True)
class PortAccessInventory:
    """Authoritative physical claims plus late-output routing metadata."""

    demands: tuple[PortAccessDemand, ...]
    late_output_belts: frozenset[int] = frozenset()


def _port_access_inventory(
    nets: Sequence[_Net],
    *,
    boundary_inputs: Sequence[tuple[str, _Port, int | None]] = (),
    boundary_outputs: Sequence[tuple[str, _Port]] = (),
    late_output_belts: Collection[int] = (),
    shared_boundary_root_belts: Collection[int] = (),
    strip_of_belt: Mapping[int, int] = MappingProxyType({}),
) -> PortAccessInventory:
    """Collapse representational nets into their distinct physical approaches."""

    late = frozenset(late_output_belts)
    shared_roots = frozenset(shared_boundary_root_belts)
    demands: dict[tuple[Cell, PortAccessKind], PortAccessDemand] = {}

    def add(port: _Port, item: str, kind: PortAccessKind, strip_index: int | None = None) -> None:
        cell = (port.x, port.y, port.z)
        demand = PortAccessDemand(
            cell=cell,
            kind=kind,
            item=item,
            belt=port.belt,
            strip_index=strip_of_belt.get(port.belt, strip_index),
            columns=max(1, len(port.columns())),
        )
        demands.setdefault((cell, kind), demand)

    for net in nets:
        if net.prelinked:
            continue
        if net.src is not None and net.src.belt not in shared_roots:
            add(net.src, net.item, PortAccessKind.INTERNAL_DEPARTURE)
        add(net.dst, net.item, PortAccessKind.INTERNAL_ARRIVAL)
    for item, port, strip_index in boundary_inputs:
        add(port, item, PortAccessKind.BOUNDARY_ARRIVAL, strip_index)
    for item, port in boundary_outputs:
        if port.belt not in late:
            add(port, item, PortAccessKind.EARLY_BOUNDARY_DEPARTURE)

    kind_order = {kind: ordinal for ordinal, kind in enumerate(PortAccessKind)}
    return PortAccessInventory(
        demands=tuple(
            sorted(
                demands.values(),
                key=lambda demand: (
                    demand.columns,
                    demand.cell,
                    kind_order[demand.kind],
                    demand.belt,
                ),
            )
        ),
        late_output_belts=late,
    )


@dataclass(frozen=True, slots=True)
class PortAccessEvidence:
    """Complete candidate-enumeration evidence for one unmatched claim."""

    demand: PortAccessDemand
    held: int
    wanted: int
    local_options: int
    reachable_options: int
    exhaustive: bool
    frontier: tuple[Cell, ...] = ()


@dataclass(frozen=True, slots=True)
class PortAccessReservation:
    """The committed result of one joint corridor assignment."""

    assigned: tuple[tuple[PortAccessDemand, PortAccessCorridor], ...]
    missing: tuple[PortAccessDemand, ...]
    evidence: tuple[PortAccessEvidence, ...]
    #: Whether the joint matcher reached a fixed point, or handed back what it
    #: had.  `missing` on a NON-converged reservation is "what the survey
    #: convicted plus whatever was never assigned", which is a weaker claim
    #: than "the ground will not serve these".  A caller that reads
    #: `complete`/`missing` as a verdict MUST read this too.
    converged: bool = True

    @property
    def complete(self) -> bool:
        return not self.missing


@dataclass(frozen=True, slots=True)
class PortAccessCorridor:
    """Two cells reserved atomically for one port approach."""

    access: Cell
    exit: Cell
    kind: PortAccessKind | None = None


@dataclass(slots=True)
class _CorridorRelease:
    """Ordered entry state and only the occupancy cells this release opened."""

    reserved: tuple[tuple[Cell, Cell], ...]
    corridors: tuple[tuple[Cell, tuple[PortAccessCorridor, ...]], ...]
    grid_reserved: tuple[tuple[int, Cell], ...]
    retired_roles: tuple[tuple[tuple[Cell, str], PortAccessCorridor], ...]
    opened: tuple[Cell, ...] = ()
    finished: bool = False

    def commit(self) -> None:
        """Explicitly keep this operation's reservation changes."""
        self.finished = True


class _CorridorReservations:
    """One call's coordinated canvas/grid reservations, never demand selection."""

    def __init__(
        self,
        canvas: _Canvas,
        grid: _Grid | None = None,
        owner: Mapping[Cell, int] = MappingProxyType({}),
    ) -> None:
        self.canvas = canvas
        self.grid = grid
        self.owner = owner
        self._retired_roles: dict[tuple[Cell, str], PortAccessCorridor] = {}

    def snapshot(self) -> _CorridorRelease:
        return _CorridorRelease(
            tuple(self.canvas.reserved.items()),
            tuple(self.canvas.port_corridors.items()),
            () if self.grid is None else self.grid.reserved,
            tuple(self._retired_roles.items()),
        )

    def restore(self, release: _CorridorRelease) -> None:
        if release.finished:
            return
        if self.grid is not None:
            for cell in release.opened:
                # A newly claimed route is not the reservation owner's to undo.
                if cell not in self.owner:
                    self.grid.block(cell)
            self.grid.reserved = release.grid_reserved
        self.canvas.reserved.clear()
        self.canvas.reserved.update(release.reserved)
        self.canvas.port_corridors.clear()
        self.canvas.port_corridors.update(release.corridors)
        self._retired_roles.clear()
        self._retired_roles.update(release.retired_roles)
        release.finished = True

    def finish(self) -> None:
        """Spend the attempt-local reservation stores before physical publication."""
        self.canvas.reserved.clear()
        self.canvas.port_corridors.clear()
        self._retired_roles.clear()
        if self.grid is not None:
            self.grid.reserved = ()

    def _open_cells(self, cells: Iterable[Cell]) -> tuple[Cell, ...]:
        if self.grid is None:
            return ()
        opened = tuple(
            cell
            for cell in cells
            if cell not in self.owner
            and cell not in self.canvas.reserved
            and self.canvas.free(cell)
            and self.grid.occ[self.grid.index(cell)] != self.grid.base[self.grid.index(cell)]
        )
        for cell in opened:
            self.grid.restore(cell)
        return opened

    def _remove(self, key: Cell, selected: Collection[PortAccessCorridor]) -> tuple[Cell, ...]:
        remaining = tuple(
            corridor
            for corridor in self.canvas.port_corridors.get(key, ())
            if corridor not in selected
        )
        self.canvas.port_corridors[key] = remaining
        retained = {cell for corridor in remaining for cell in (corridor.access, corridor.exit)}
        removed: list[Cell] = []
        for corridor in selected:
            for cell in (corridor.access, corridor.exit):
                if cell not in retained and self.canvas.reserved.get(cell) == key:
                    del self.canvas.reserved[cell]
                    removed.append(cell)
        if self.grid is not None:
            indices = {self.grid.index(cell) for cell in removed}
            self.grid.reserved = tuple(row for row in self.grid.reserved if row[0] not in indices)
        return self._open_cells(removed)

    @contextmanager
    def temporarily_released(
        self,
        selected: Mapping[Cell, tuple[PortAccessCorridor, ...]] | None = None,
    ) -> Iterator[_CorridorRelease]:
        """Release caller-selected corridors, or all holdings when omitted.

        An empty selection snapshots without releasing: the enclosed route may
        retire/reinsert roles, but rollback still restores exact entry order.
        Ordinary return restores too; only an explicit commit retains changes.
        """
        release = self.snapshot()
        try:
            if selected is None:
                self.canvas.reserved.clear()
                self.canvas.port_corridors.clear()
                if self.grid is not None:
                    self.grid.reserved = ()
                release.opened = self._open_cells(cell for cell, _port in release.reserved)
            else:
                opened: list[Cell] = []
                for key, corridors in selected.items():
                    opened.extend(self._remove(key, corridors))
                    release.opened = tuple(opened)
            yield release
        finally:
            self.restore(release)

    def retire(
        self,
        key: Cell,
        endpoint_cells: Collection[Cell],
        kind: PortAccessKind | None = None,
    ) -> PortAccessCorridor | None:
        """Retire one eligible role, preferring the endpoint the path selected."""
        eligible = tuple(
            corridor
            for corridor in self.canvas.port_corridors.get(key, ())
            if kind is None or corridor.kind in (None, kind)
        )
        if not eligible:
            return None
        endpoint_set = set(endpoint_cells)
        selected = min(
            eligible,
            key=lambda corridor: (
                not bool(endpoint_set & {corridor.access, corridor.exit}),
                corridor.access,
                corridor.exit,
            ),
        )
        self._remove(key, (selected,))
        return selected

    def retire_first(self, key: Cell) -> None:
        """Spend the legacy single-cell reservation when no corridor exists."""
        cell = self.canvas.reserved.first_for(key)
        if cell is None:
            return
        del self.canvas.reserved[cell]
        if self.grid is not None:
            at = self.grid.index(cell)
            self.grid.reserved = tuple(row for row in self.grid.reserved if row[0] != at)
        self._open_cells((cell,))

    def restore_role(self, key: Cell, corridor: PortAccessCorridor) -> None:
        """Ordinary role reinsertion, distinct from exact transaction rollback."""
        self.canvas.port_corridors[key] = tuple(
            sorted(
                (*self.canvas.port_corridors.get(key, ()), corridor),
                key=lambda candidate: (candidate.access, candidate.exit),
            )
        )
        added: list[tuple[int, Cell]] = []
        for cell in (corridor.access, corridor.exit):
            fresh = cell not in self.canvas.reserved
            self.canvas.reserved[cell] = key
            if self.grid is not None and fresh:
                added.append((self.grid.index(cell), key))
        if self.grid is not None:
            self.grid.reserved = tuple(sorted((*self.grid.reserved, *added)))

    def retire_served_roles(
        self, roles: Iterable[tuple[Cell, str]], path: tuple[Cell, ...]
    ) -> None:
        for key, role in roles:
            token = (key, role)
            if token in self._retired_roles:
                continue
            source = role == "src"
            retired = self.retire(
                key,
                path[:2] if source else path[-2:],
                PortAccessKind.INTERNAL_DEPARTURE if source else PortAccessKind.INTERNAL_ARRIVAL,
            )
            if retired is not None:
                self._retired_roles[token] = retired

    def restore_unserved_roles(self, roles: Iterable[tuple[Cell, str]]) -> None:
        for token in roles:
            retired = self._retired_roles.pop(token, None)
            if retired is not None:
                self.restore_role(token[0], retired)

    def hold(self, assignments: Mapping[PortAccessDemand, PortAccessCorridor]) -> None:
        """Publish caller-selected assignments, retaining existing cell precedence."""
        assigned_by_port: dict[Cell, list[PortAccessCorridor]] = defaultdict(list)
        for demand, corridor in assignments.items():
            self.canvas.reserved[corridor.access] = demand.cell
            self.canvas.reserved[corridor.exit] = demand.cell
            assigned_by_port[demand.cell].append(corridor)
        kind_order = {kind: ordinal for ordinal, kind in enumerate(PortAccessKind)}
        self.canvas.port_corridors.clear()
        self.canvas.port_corridors.update(
            (
                key,
                tuple(
                    sorted(
                        corridors,
                        key=lambda corridor: (
                            len(kind_order) if corridor.kind is None else kind_order[corridor.kind],
                            corridor.access,
                            corridor.exit,
                        ),
                    )
                ),
            )
            for key, corridors in assigned_by_port.items()
        )
        if self.grid is not None:
            self.grid.reserved = tuple(
                (self.grid.index(cell), key) for cell, key in self.canvas.reserved.items()
            )


class _CorridorMatch(NamedTuple):
    """What the joint matcher decided, and whether the decision is a verdict.

    ``converged`` is True ONLY when the validate/cut loop reached a fixed point
    -- every assigned corridor still reaching its own goal with every other
    corridor's cells forbidden -- or when there was no validator at all.  Every
    give-up is False, INCLUDING the ones that now hand back a partial, because
    a partial is ground the router can use and NOT an answer to the question
    the ladder asked.  `compose` must be able to tell those apart: see
    `hierarchy/compose.pack_with_access`, where a partial increments
    `degraded` precisely so that `reservation_degraded == 0` keeps meaning
    "the oracle answered, completely".
    """

    assigned: dict[PortAccessDemand, PortAccessCorridor]
    converged: bool


def _match_access_corridors(
    demands: Sequence[PortAccessDemand],
    corridors: Mapping[PortAccessDemand, Sequence[tuple[Cell, Cell]]],
    *,
    validate: (
        Callable[
            [Mapping[PortAccessDemand, PortAccessCorridor]],
            Collection[PortAccessDemand] | None,
        ]
        | None
    ) = None,
    survey: (
        Callable[
            [Mapping[PortAccessDemand, PortAccessCorridor]],
            Collection[PortAccessDemand],
        ]
        | None
    ) = None,
    cancelled: Callable[[], bool] | None = None,
    deadline: float | None = None,
) -> _CorridorMatch:
    """Assign cell-disjoint corridors, giving every port its first claim first.

    Every solve carries a deterministic work cap, so it is bounded in the work
    it does regardless of load -- but `solve_model` also arms the wall-clock
    backstop (`solver.parameters.max_time_in_seconds = remaining`) alongside
    it, and that one is real wall time.  Under load, a tie-break solve can
    therefore hit the wall-clock deadline before its deterministic cap and
    come back `UNKNOWN` rather than `OPTIMAL`/`FEASIBLE`, which takes the
    fallback-value branch below: the rank-optimal assignment already proved
    feasible is used instead of the tie-optimal one the polish was after.  An
    exhausted deadline (`_expired`) or a cancellation still raises
    `_PreparationDeadline` as before.  A validation cut invalidates that
    fallback, so the next capped tie-break without an incumbent re-establishes
    one by solving the cut model for feasibility alone, under the same cap the
    rank solves use.  Rematching rounds are bounded by `_ACCESS_CUT_ROUNDS`.

    WHEN THE CUT LOOP RUNS OUT OF ROUNDS, THE ASSIGNMENT IS NOT DISCARDED.
    ``validate`` names ONE witness per round, so ``_ACCESS_CUT_ROUNDS`` rounds
    can convict at most that many demands out of however many there are -- and
    a composed canvas raises 91 or 144 (v3 gate §5 lever 1).  Returning ``{}``
    there threw away a complete cell-disjoint assignment because a handful of
    its corridors failed a probe STRICTER than the router that follows: the
    probe forbids every other corridor's cells outright, while ``_route_all``
    negotiates and rips up.  So on give-up, ``survey`` -- which reports EVERY
    failing demand rather than the first -- is asked once, and what survives it
    is committed with ``converged=False``.  Dropping the failures can only free
    ground, so a corridor that reached its goal against the FULL selection
    still reaches it against the smaller one; the survivors need no re-check.
    Without a ``survey`` there is no way to know which corridors are safe, and
    the wholesale give-up is kept.
    """

    def solve_model(work: float) -> cp_model.CpSolverStatus:
        if (cancelled is not None and cancelled()) or _expired(deadline):
            raise _PreparationDeadline
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _PreparationDeadline
            solver.parameters.max_time_in_seconds = remaining
        solver.parameters.max_deterministic_time = work
        status = solver.solve(model)
        if (cancelled is not None and cancelled()) or _expired(deadline):
            raise _PreparationDeadline
        return status

    by_port: dict[Cell, list[PortAccessDemand]] = defaultdict(list)
    widths: dict[Cell, int] = {}
    kind_order = {kind: ordinal for ordinal, kind in enumerate(PortAccessKind)}
    for demand in demands:
        by_port[demand.cell].append(demand)
        widths[demand.cell] = max(widths.get(demand.cell, 0), demand.columns)
    ports = sorted(by_port, key=lambda cell: (widths[cell], cell))
    for claims in by_port.values():
        claims.sort(key=lambda demand: (kind_order[demand.kind], demand.belt))
    ranked_claims = [
        (demand, rank)
        for rank in range(max((len(by_port[cell]) for cell in ports), default=0))
        for cell in ports
        for demand in by_port[cell][rank : rank + 1]
    ]

    model = cp_model.CpModel()
    choices: dict[tuple[PortAccessDemand, Cell, Cell], cp_model.IntVar] = {}
    by_claim: dict[PortAccessDemand, list[cp_model.IntVar]] = defaultdict(list)
    by_rank: dict[int, list[cp_model.IntVar]] = defaultdict(list)
    by_cell: dict[Cell, list[cp_model.IntVar]] = defaultdict(list)
    for demand, rank in ranked_claims:
        for access, exit_cell in corridors.get(demand, ()):
            variable = model.new_bool_var(
                f"corridor_{demand.cell}_{demand.kind.value}_{access}_{exit_cell}"
            )
            choices[demand, access, exit_cell] = variable
            by_claim[demand].append(variable)
            by_rank[rank].append(variable)
            by_cell[access].append(variable)
            by_cell[exit_cell].append(variable)

    for demand, _rank in ranked_claims:
        model.add(sum(by_claim[demand]) <= 1)
    for variables in by_cell.values():
        model.add(sum(variables) <= 1)

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    for rank in range(max((rank for _demand, rank in ranked_claims), default=-1) + 1):
        rank_vars = by_rank[rank]
        if not rank_vars:
            continue
        model.maximize(sum(rank_vars))
        status = solve_model(_ACCESS_RANK_DETERMINISTIC_WORK)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return _CorridorMatch({}, False)
        model.add(sum(rank_vars) == round(solver.objective_value))

    ordered_choices = tuple(choices)
    if not ordered_choices:
        # No demand had a single free option -- or there were no demands.  The
        # second is a COMPLETE answer to an empty question and must not make a
        # caller degrade; the first is a give-up.
        return _CorridorMatch({}, not demands)

    def solution_values() -> dict[tuple[PortAccessDemand, Cell, Cell], bool]:
        return {choice: solver.boolean_value(variable) for choice, variable in choices.items()}

    ranked_values = solution_values()
    fallback_values: dict[tuple[PortAccessDemand, Cell, Cell], bool] | None = ranked_values
    for choice, variable in choices.items():
        model.add_hint(variable, int(ranked_values[choice]))
    tie_objective = sum(
        ordinal * choices[choice] for ordinal, choice in enumerate(ordered_choices, start=1)
    )
    model.minimize(tie_objective)
    best_partial: dict[PortAccessDemand, PortAccessCorridor] = {}

    def surrender() -> _CorridorMatch:
        """The largest assignment seen, minus everything the survey convicts.

        An incomplete survey -- caught here as `_PreparationDeadline` -- cannot
        say which of the untested corridors would have failed, so it is
        treated as if there had been no partial at all: the wholesale
        give-up, exactly what the old code returned on any give-up, and never
        a propagating exception.  The deadline is still real and still stops
        the caller -- `_reserve_port_access`'s own checks catch it again on
        the very next real probe -- this just stops IT from being the thing
        that turns a give-up into an abandoned rung.
        """
        if not best_partial or survey is None:
            return _CorridorMatch({}, False)
        try:
            failing = set(survey(best_partial))
        except _PreparationDeadline:
            return _CorridorMatch({}, False)
        return _CorridorMatch(
            {
                demand: corridor
                for demand, corridor in best_partial.items()
                if demand not in failing
            },
            False,
        )

    for _round in range(_ACCESS_CUT_ROUNDS):
        status = solve_model(_ACCESS_TIE_DETERMINISTIC_WORK)
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            selected_values = solution_values()
        elif status == cp_model.INFEASIBLE:
            if validate is not None or fallback_values is None:
                return surrender()
            selected_values = fallback_values
        elif fallback_values is not None:
            selected_values = fallback_values
        else:
            # The bounded tie polish found no incumbent after a validation cut.
            # Re-establish a model-valid fallback without the polish objective;
            # the previous ranked solution is forbidden by the new cut.  The
            # feasibility solve carries the rank cap, so no solve here runs
            # unbounded; a cap that expires first leaves the candidate unmatched.
            model.clear_objective()  # type: ignore[no-untyped-call]
            try:
                fallback_status = solve_model(_ACCESS_RANK_DETERMINISTIC_WORK)
            finally:
                model.minimize(tie_objective)
            if fallback_status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                return surrender()
            fallback_values = solution_values()
            model.clear_hints()  # type: ignore[no-untyped-call]
            for choice, variable in choices.items():
                model.add_hint(variable, int(fallback_values[choice]))
            selected_values = fallback_values
        assigned: dict[PortAccessDemand, PortAccessCorridor] = {}
        selected_by_demand: dict[PortAccessDemand, cp_model.IntVar] = {}
        for choice in ordered_choices:
            if not selected_values[choice]:
                continue
            demand, access, exit_cell = choice
            assigned[demand] = PortAccessCorridor(access, exit_cell, demand.kind)
            selected_by_demand[demand] = choices[choice]
        witness = None if validate is None else validate(assigned)
        if (cancelled is not None and cancelled()) or _expired(deadline):
            raise _PreparationDeadline
        if validate is None or witness is None:
            return _CorridorMatch(assigned, True)
        # STRICTLY larger, so the FIRST round to reach a given size keeps it:
        # the rank solves already fixed each rank's total, so later rounds are
        # tie-break re-arrangements of the same size and re-surveying one buys
        # nothing but A* probes.
        if len(assigned) > len(best_partial):
            best_partial = assigned
        cut_variables = [
            selected_by_demand[demand] for demand in witness if demand in selected_by_demand
        ]
        if not cut_variables:
            return surrender()
        model.add(sum(cut_variables) <= len(cut_variables) - 1)
        fallback_values = None
    return surrender()


def _reserve_port_access(
    canvas: _Canvas,
    demands: Sequence[PortAccessDemand],
    *,
    boundary: Sequence[Cell] | None = None,
    bounds: tuple[int, int, int, int] | None = None,
    cancelled: Callable[[], bool] | None = None,
    deadline: float | None = None,
    goals: Mapping[PortAccessDemand, frozenset[Cell]] | None = None,
    partners: Mapping[PortAccessDemand, frozenset[PortAccessDemand]] | None = None,
    held: Mapping[PortAccessDemand, PortAccessCorridor] | None = None,
) -> PortAccessReservation:
    """Enumerate and jointly hold one complete corridor per physical claim.

    The final pass filters claims through a static ground component towards
    THEIR OWN goal: ``boundary`` for a true boundary claim, and a ``goals``
    entry for anything else.  A ``goals`` entry wins over ``boundary`` and is
    honoured whatever the claim's kind says, so a composed canvas can aim a cut
    lane's probe at its trunk partner's doorstep; a claim in neither is not
    probed at all.  Reservations are cleared before enumeration, so provisional
    choices cannot veto an alternate candidate; nothing is committed until the
    joint matcher has selected every compatible corridor.

    ``partners`` names real net endpoints, never owners inferred from goal-cell
    overlap. Their reservations, and every role at this demand's own endpoint,
    are open during probes just as they are during detailed routing. Held
    corridors remain unavailable for assignment even when a probe can cross them.

    ``held`` names corridors from an earlier reservation, making this call a
    top-up rather than a replacement. They are held before enumeration, cannot
    be reassigned, and survive every returning path, including ordinary matcher
    give-up. The owner restores exact entry order on every raising path.
    `hierarchy.compose._top_up_partial` still owns the authoritative assignment
    union and recomputes its preferred order from its partial.

    PASSING ``held`` CHANGES ``assigned``'S ORDER: held pairs come first and the
    newly assigned follow in ``demands`` order, where with no ``held`` the tuple
    has always followed ``demands`` order alone.  Harmless today because the one
    caller that passes ``held`` re-derives the order it wants; a future caller
    that reads position out of this tuple must not assume otherwise.
    """

    if (cancelled is not None and cancelled()) or _expired(deadline):
        raise _PreparationDeadline
    reservations = _CorridorReservations(canvas)
    with reservations.temporarily_released() as release:
        held_by_demand = dict(held or {})
        reservations.hold(held_by_demand)

        def check_cancelled() -> None:
            if not ((cancelled is not None and cancelled()) or _expired(deadline)):
                return
            raise _PreparationDeadline

        bounds = bounds or canvas.limit
        local_options: dict[PortAccessDemand, tuple[tuple[Cell, Cell], ...]] = {}
        reachable_options: dict[PortAccessDemand, tuple[tuple[Cell, Cell], ...]] = {}
        exhaustive: dict[PortAccessDemand, bool] = {}
        probed_options: dict[PortAccessDemand, int] = {}
        inconclusive: set[PortAccessDemand] = set()
        frontiers: dict[PortAccessDemand, set[Cell]] = defaultdict(set)
        boundary_set = set(boundary or ())
        # AN EMPTY GOAL SET IS NO GOAL, dropped here rather than handled at each
        # use, so that "has an explicit goal" has ONE spelling.  `_goal_for` asks
        # whether the lookup returned a set and the probe cap below asks whether
        # the demand is a key; leaving an empty set in would make those two
        # disagree, and the demand would be probed towards nowhere -- every option
        # failing `DYNAMIC_ACCESS`, the cap firing on the wreckage.
        goal_by_demand = {demand: goal for demand, goal in (goals or {}).items() if goal}
        partner_by_demand = partners or {}
        endpoint_ports = {
            demand: frozenset(
                {demand.cell, *(partner.cell for partner in partner_by_demand.get(demand, ()))}
            )
            for demand in demands
        }
        # WHETHER ANY PROBE RUNS AT ALL.  With neither a boundary nor a goal this
        # function is the purely LOCAL oracle it has always been: every free
        # (access, exit) pair is admitted unprobed, `exhaustive` is False, and no
        # grid is built.
        #
        # Which caller takes which path, because the answer is NOT "all of them
        # take the local one" and a reader who assumes it is will conclude the
        # boundary probe is dead code and cap it.  Named by SYMBOL, never by line:
        # this file is 22k lines and a line citation here was already stale one
        # commit after it was written.
        #
        #   `_route_all`                       passes neither -- local only.
        #   `_prepare_routing_problem`         passes `boundary=boundary_cells`
        #     (in its nested `hold_ports`)     and IS probed.  This is freeform's
        #                                      OWN default path.
        #   `hierarchy.compose.pack_with_access`  passes a `boundary` that it
        #                                      computes as `None` today.
        probed = boundary is not None or bool(goal_by_demand)

        def _goal_for(demand: PortAccessDemand) -> set[Cell] | None:
            """Where this demand's corridor must be able to reach, or None.

            An explicit goal WINS over the boundary and is honoured whatever the
            demand's kind says.  A composed canvas's cut lanes are all
            `INTERNAL_*` -- `reaches_boundary` False -- and their trunks run to
            another BLOCK's port rather than to the rim, so the kind flag is the
            wrong question for them; see
            `docs/superpowers/evidence/2026-09-07-hierarchical-v2/gate.md` §6.
            """
            explicit = goal_by_demand.get(demand)
            if explicit is not None:
                return set(explicit)
            if boundary is not None and demand.kind.reaches_boundary:
                return boundary_set
            return None

        # ONE GRID PER RESERVATION INSTEAD OF ONE PER PROBE, because every
        # reachability probe below -- and every re-probe the matcher's validate
        # callback runs -- searches the same box towards the same boundary, and a
        # mall-sized reservation flattened the canvas 872 times for 3.9s.
        #
        # The canvas is NOT WRITTEN between this build and the last probe: the
        # reservations and corridors were cleared just above, and the assignments
        # are only written after the matcher returns -- so the shared grid carries
        # exactly the state a per-probe build would have derived.  `probe_cells`
        # names every cell two steps from a demand, which is every exit cell any
        # probe can start from; `_astar` falls back to a private grid for a start
        # or goal outside the span, so a miss costs a build and never a result.
        shared_grid: _Grid | None = None
        if bounds is not None and probed:
            probe_box = _route_box(canvas, bounds)
            probe_cells = [
                (key[0] + dx + ex, key[1] + dy + ey, key[2])
                for demand in demands
                for key in (demand.cell,)
                for dx, dy in _STEPS
                for ex, ey in _STEPS
            ]
            # EVERY goal cell has to be inside the span, not just the boundary's:
            # `_astar` falls back to a private grid for a goal outside it, which
            # would cost a fresh flatten per probe -- the 872 rebuilds and 3.9s
            # this shared grid exists to avoid.
            goal_cells = sorted(
                boundary_set.union(*goal_by_demand.values()) if goal_by_demand else boundary_set
            )
            shared_grid = _make_grid(
                canvas, probe_box, _span_for(probe_box, probe_cells, goal_cells), {}
            )

        def probe(
            demand: PortAccessDemand,
            exit_cell: Cell,
            *,
            forbidden: Collection[Cell] = (),
            blocking_owners: Mapping[Cell, int] | None = None,
        ) -> _PathSearchResult:
            goal = _goal_for(demand)
            assert goal is not None and bounds is not None
            routing_ports = canvas.routing_ports
            canvas.routing_ports = endpoint_ports[demand]
            try:
                result = _astar(
                    canvas,
                    [exit_cell],
                    goal,
                    {},
                    0.0,
                    bounds,
                    deadline=deadline,
                    grid=shared_grid,
                    forbidden=forbidden,
                    blocking_owners=blocking_owners,
                )
                check_cancelled()
                return result
            finally:
                canvas.routing_ports = routing_ports

        def probe_options(demand: PortAccessDemand, cap: int | None = None) -> None:
            options = local_options[demand]
            candidates = list(reachable_options[demand])
            index = probed_options[demand]
            while index < len(options) and (cap is None or len(candidates) < cap):
                check_cancelled()
                access, exit_cell = options[index]
                result = probe(demand, exit_cell)
                index += 1
                if result.path is not None:
                    candidates.append((access, exit_cell))
                elif result.kind is RouteFailureKind.SEALED_POCKET:
                    frontiers[demand].update(result.wall)
                else:
                    inconclusive.add(demand)
                    candidates.append((access, exit_cell))
            probed_options[demand] = index
            reachable_options[demand] = tuple(candidates)
            exhaustive[demand] = index == len(options) and demand not in inconclusive

        for demand in demands:
            check_cancelled()
            key = demand.cell
            access_cells = tuple(
                cell
                for cell in ((key[0] + dx, key[1] + dy, key[2]) for dx, dy in _STEPS)
                if canvas.free(cell)
            )
            options = tuple(
                (access, exit_cell)
                for access in access_cells
                for exit_cell in ((access[0] + dx, access[1] + dy, access[2]) for dx, dy in _STEPS)
                if exit_cell != key and canvas.free(exit_cell)
            )
            local_options[demand] = options
            probed_options[demand] = len(options)
            goal = _goal_for(demand)
            if goal is None:
                reachable_options[demand] = options
                exhaustive[demand] = probed
                continue
            if bounds is None:
                reachable_options[demand] = options
                exhaustive[demand] = False
                continue
            reachable_options[demand] = ()
            probed_options[demand] = 0
            probe_options(demand, _PORT_ACCESS_PROBE_KEEP if demand in goal_by_demand else None)

        def pending_expansion(
            assigned: Mapping[PortAccessDemand, PortAccessCorridor],
        ) -> tuple[PortAccessDemand, ...]:
            """Follow local cell conflicts from missing claims to selected owners."""
            if not any(probed_options[demand] < len(local_options[demand]) for demand in demands):
                return ()
            owners = {
                cell: demand
                for demand, corridor in assigned.items()
                for cell in (corridor.access, corridor.exit)
            }
            closure = {
                demand
                for demand in demands
                if demand not in assigned and demand not in held_by_demand
            }
            frontier = list(closure)
            while frontier:
                check_cancelled()
                for option in local_options[frontier.pop()]:
                    for cell in option:
                        owner = owners.get(cell)
                        if owner is not None and owner not in closure:
                            closure.add(owner)
                            frontier.append(owner)
            return tuple(
                demand
                for demand in demands
                if demand in closure and probed_options[demand] < len(local_options[demand])
            )

        def _selection(
            assigned: Mapping[PortAccessDemand, PortAccessCorridor],
        ) -> tuple[
            dict[Cell, PortAccessDemand], dict[PortAccessDemand, int], dict[int, PortAccessDemand]
        ]:
            selected_cells: dict[Cell, PortAccessDemand] = {
                cell: owner
                for owner, selected in assigned.items()
                for cell in (selected.access, selected.exit)
            }
            ordered_owners = tuple(assigned)
            owner_index = {owner: index for index, owner in enumerate(ordered_owners)}
            return selected_cells, owner_index, dict(enumerate(ordered_owners))

        def _wall_between(
            demand: PortAccessDemand,
            corridor: PortAccessCorridor,
            selected_cells: Mapping[Cell, PortAccessDemand],
            owner_index: Mapping[PortAccessDemand, int],
        ) -> tuple[Cell, ...] | None:
            """The wall between this corridor and its goal, or None if it reaches.

            A ``BUDGET`` refusal is NOT a wall: the A* ran out of expansions, which
            says nothing about the ground, and convicting on it would drop
            corridors for the searcher's clock rather than for geometry.
            """
            goal = _goal_for(demand)
            if goal is None or bounds is None:
                return None
            allowed_ports = endpoint_ports[demand]
            blocking_owners = {
                cell: owner_index[owner]
                for cell, owner in selected_cells.items()
                if owner.cell not in allowed_ports
            }
            result = probe(
                demand,
                corridor.exit,
                forbidden=blocking_owners.keys(),
                blocking_owners=blocking_owners,
            )
            if result.path is not None or result.kind is RouteFailureKind.BUDGET:
                return None
            frontiers[demand].update(result.wall)
            return tuple(result.wall)

        def assignment_boundary_cut(
            assigned: Mapping[PortAccessDemand, PortAccessCorridor],
        ) -> Collection[PortAccessDemand] | None:
            if not probed or bounds is None:
                return None
            # Do not spend validation probes on a knowingly truncated assignment.
            # The outer loop expands it before accepting any matcher verdict.
            if pending_expansion(assigned):
                return None
            selected_cells, owner_index, owner_by_index = _selection(assigned)
            cell_owner_index = {cell: owner_index[owner] for cell, owner in selected_cells.items()}
            for demand, corridor in assigned.items():
                wall = _wall_between(demand, corridor, selected_cells, owner_index)
                if wall is None:
                    continue
                blocking_demands = {
                    owner_by_index[index]
                    for cell in wall
                    for index in (cell_owner_index.get(cell),)
                    if index is not None
                }
                return (demand, *sorted(blocking_demands, key=lambda blocked: blocked.cell))
            return None

        def assignment_survey(
            assigned: Mapping[PortAccessDemand, PortAccessCorridor],
        ) -> Collection[PortAccessDemand]:
            """Survey every claim; the matcher may catch expiry as ordinary give-up."""
            if not probed or bounds is None:
                return ()
            selected_cells, owner_index, _ = _selection(assigned)
            return tuple(
                demand
                for demand, corridor in assigned.items()
                if _wall_between(demand, corridor, selected_cells, owner_index) is not None
            )

        while True:
            match = _match_access_corridors(
                demands,
                reachable_options,
                validate=assignment_boundary_cut if probed else None,
                survey=assignment_survey if probed else None,
                cancelled=cancelled,
                deadline=deadline,
            )
            # Preserve ordinary empty give-up, including an expired surrender
            # survey. It supplies no assignment whose conflict closure to follow.
            if not match.assigned and not match.converged:
                break
            pending = pending_expansion(match.assigned)
            if not pending:
                break
            for demand in pending:
                probe_options(demand)
        # An empty MATCH stakes nothing new below, so there is nothing for this
        # check to protect -- and `surrender`'s survey may have just spent the
        # remaining deadline finding that out, which would make this re-detect the
        # SAME expiry and turn a give-up `_reserve_port_access` was meant to hand
        # back normally into a raise anyway.  Skip it precisely where staking is a
        # no-op; a non-empty match still gets checked before being staked.  It is
        # the MATCH and not `assignments` that is asked, so a top-up whose own
        # matcher came back empty still returns `held` normally rather than raising
        # and costing the caller the partial this call was completing.
        if match.assigned:
            check_cancelled()
        assignments = dict(match.assigned)
        # HELD WINS: a demand an earlier reservation already served is never
        # re-assigned or overwritten.  Its cells were denied above, so this can only
        # fire for a caller that put a held demand back into `demands`.
        assignments.update(held_by_demand)
        reservations.hold(assignments)
        missing = tuple(demand for demand in demands if demand not in assignments)
        reservation = PortAccessReservation(
            assigned=(
                *held_by_demand.items(),
                *(
                    (demand, assignments[demand])
                    for demand in demands
                    if demand in assignments and demand not in held_by_demand
                ),
            ),
            missing=missing,
            evidence=tuple(
                PortAccessEvidence(
                    demand=demand,
                    held=0,
                    wanted=1,
                    local_options=len(local_options[demand]),
                    reachable_options=len(reachable_options[demand]),
                    exhaustive=exhaustive[demand],
                    frontier=tuple(sorted(frontiers[demand])),
                )
                for demand in missing
            ),
            converged=match.converged,
        )
        release.commit()
        return reservation


def _selected_source_heads(
    nets: Sequence[_Net],
    paths: Mapping[int, Sequence[Cell]],
    source_hints: Mapping[int, Cell],
    selected_taps: Collection[Cell],
) -> frozenset[Cell]:
    """Protect both new branches and direct carries of selected source taps."""
    heads: set[Cell] = set()
    for index, path in paths.items():
        source = nets[index].src
        if path and (
            index in source_hints
            or (source is not None and (source.x, source.y, source.z) in selected_taps)
        ):
            heads.add(path[0])
    return frozenset(heads)


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
    primitives: RoutePrimitives | None = None,
    source_taps: Mapping[int, Cell] | None = None,
    deadline: float | None = None,
    ownership: RouteOwnership | None = None,
) -> tuple[int, ...]:
    """Turn reserved cells into real belts, forward-linked source to sink.

    Returns the indices of routed nets that could not be linked at commit time.

    ``src_group`` is the router's own record of which nets share each net's
    SOURCE LANE, and it is the only thing that can tell a legitimate branch from
    a mis-link. A path may leave a sibling's routed path or an already-selected
    prebuilt source tap in that same physical supply group. :func:`_source_for`
    is handed only those owned cells to attach to. Omitting that ownership
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
    the later nets branch off a sibling's committed path (``_route``'s
    ``same_src``) rather than off a further lane tile, and that branch point is
    a JUNCTION: the lane has to keep flowing east *and* hand items to the
    branch.  ``_tap_source`` builds that as a splitter, which is what the game
    uses and what the fixture corpus shows.

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
    _CorridorReservations(canvas).finish()
    canvas.routing_ports = frozenset()
    unlinked: list[int] = []
    laid: dict[int, list[int]] = {}
    path_owner = {cell: index for index, path in paths.items() for cell in path}

    def record(
        index: int,
        cell: Cell,
        side: Literal["source", "sink", "path", "contextual"],
        blockers: Collection[Cell] = (),
        *,
        tap: Cell | None = None,
        reason: str = "",
    ) -> None:
        if failure_details is None:
            return
        blocking_cells = tuple(sorted(set(blockers)))
        blocking_owners = {
            owner for blocker in blocking_cells if (owner := path_owner.get(blocker)) is not None
        }
        if reason == "belt-keepout":
            # A side merge changes the existing belt's reverse-walk exemption.
            # Its incoming route is causal even though the colliding cell
            # itself still belongs to the original carrying route.
            for blocker in blocking_cells:
                belt_index = canvas.blocked.get(blocker)
                if belt_index is None:
                    continue
                incoming = canvas.buildings.by_output_obj(belt_index)
                if len(incoming) < 2:
                    continue
                for predecessor in incoming:
                    building = canvas.buildings[predecessor]
                    predecessor_cell = _lattice_cell(building.x, building.y, building.z)
                    if predecessor_cell is not None:
                        owner = path_owner.get(predecessor_cell)
                        if owner is not None:
                            blocking_owners.add(owner)
        blocking_owners.discard(index)
        failure_details[index] = _CommitFailure(
            cell=cell,
            side=side,
            blocking_indices=tuple(sorted(blocking_owners)),
            tap=tap,
            blocking_cells=blocking_cells,
            reason=reason,
        )

    # CBS proves cell resources, not that the entire selection shares an exact
    # projected frame. Check the same combined source/connector geometry before
    # emitting any member; an invalid preview remains repairable routing failure.
    selected_taps = dict(source_hints or {})
    selected_taps.update(source_taps or {})
    selected = (
        primitives.selection(paths, tuple(selected_taps.values()))
        if primitives is not None
        else tuple(
            member
            for tap in sorted(set(selected_taps.values()))
            for member in _splitter_stack_geometry(*tap)
        )
    )
    if not canvas.projected_buildings_are_clear(selected, deadline=deadline):
        for index, path in paths.items():
            tap = selected_taps.get(index)
            connectors = primitives.on_path(path) if primitives is not None else ()
            record(
                index,
                connectors[0].entry.dock if connectors else path[0],
                "contextual",
                tap=tap,
                reason="projected-selection",
            )
        return tuple(paths)

    for i, path in paths.items():
        net = nets[i]
        indices: list[int] = []
        ok = True
        altitudes = (
            _altitude_profile(path, ramped=canvas.ramped)
            if primitives is None
            else primitives.altitudes(path, ramped=canvas.ramped)
        )
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
        if ownership is not None:
            assert net.net_id is not None
            ownership.attribute(len(canvas.buildings), indices, net.net_id)

    if primitives is not None:
        for index, indices in laid.items():
            path = paths[index]
            for at, edge in enumerate(zip(path, path[1:], strict=False)):
                candidate = primitives.witnesses.get(edge)
                if candidate is not None:
                    first = len(canvas.buildings)
                    primitives.emit(
                        canvas,
                        candidate,
                        indices[at],
                        indices[at + 1],
                        belt_id,
                        belt_model,
                        nets[index].item,
                    )
                    if ownership is not None:
                        net_id = nets[index].net_id
                        assert net_id is not None
                        endpoints = (indices[at], indices[at + 1])
                        ownership.attribute(
                            len(canvas.buildings),
                            (*endpoints, *range(first, len(canvas.buildings))),
                            net_id,
                            dependencies=endpoints,
                        )

    # The live index maintains reverse links as sinks and taps are relinked.
    into = canvas.buildings.by_output_obj

    # Fix every sink before certifying any source Splitter. A sink link adds a
    # predecessor to its destination belt. Building a Splitter first made its
    # collider check depend on path iteration order: a later sink could turn an
    # excused one-predecessor feeder into an unstable merge after the check.
    source_branch_heads = _selected_source_heads(
        nets, paths, source_hints or {}, frozenset(selected_taps.values())
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
        canvas.buildings[indices[-1]] = _relink(
            canvas.buildings[indices[-1]],
            output_obj=sink,
        )
        if ownership is not None:
            assert net.net_id is not None
            ownership.attribute(
                len(canvas.buildings),
                (sink, indices[-1]),
                net.net_id,
                dependencies=(sink, indices[-1]),
            )

    splitter_owner: dict[int, tuple[int, int]] = {}

    for i, indices in laid.items():
        if i in unlinked:
            continue
        net = nets[i]
        source_key = _source_group_key(net.item, net.cargo_domain, net.source)
        siblings = tuple(
            sibling
            for sibling in (src_group or {}).get(i, ())
            if _source_group_key(
                nets[sibling].item, nets[sibling].cargo_domain, nets[sibling].source
            )
            == source_key
        )
        kin = {cell for sibling in siblings for cell in paths.get(sibling, ())}
        selected_group_taps = {
            selected_taps[member]
            for member in (i, *siblings)
            if member in paths and member in selected_taps
        }
        prebuilt_sources: dict[Cell, int] = {
            tap: nets[sibling].source.belt
            for sibling in siblings
            if (
                tap := (
                    nets[sibling].source.x,
                    nets[sibling].source.y,
                    nets[sibling].source.z,
                )
            )
            in selected_group_taps
        }
        kin.update(prebuilt_sources)
        feeder = _source_for(
            canvas,
            indices[0],
            net,
            set(indices),
            kin,
            hint=(source_hints or {}).get(i),
            prebuilt_sources=prebuilt_sources,
        )
        if feeder is None:
            unlinked.append(i)
            hint = (source_hints or {}).get(i)
            record(i, paths[i][0], "source", (hint,) if hint is not None else ())
            continue
        excused = _run_cells(canvas, into, feeder) | _run_cells(canvas, into, indices[0])
        feeder_building = canvas.buildings[feeder]
        feeder_cell = _lattice_cell(feeder_building.x, feeder_building.y, feeder_building.z)
        # All paths are laid before the first Splitter is emitted. Its other
        # selected branches therefore exist but do not yet lead back to the
        # feeder. Excuse only branches whose exact selected source is this tap;
        # sharing a supply group alone never excuses a nearby belt.
        for sibling in siblings:
            sibling_indices = laid.get(sibling)
            if not sibling_indices or sibling in unlinked:
                continue
            sibling_source = nets[sibling].source
            sibling_tap = (source_hints or {}).get(
                sibling, (sibling_source.x, sibling_source.y, sibling_source.z)
            )
            if sibling_tap != feeder_cell or selected_taps.get(sibling, sibling_tap) != feeder_cell:
                continue
            sibling_head = canvas.buildings[sibling_indices[0]]
            if abs(sibling_head.x - feeder_building.x) + abs(
                sibling_head.y - feeder_building.y
            ) == 1 and (
                _legal_link(
                    feeder_building.x,
                    feeder_building.y,
                    feeder_building.z,
                    sibling_head.x,
                    sibling_head.y,
                    sibling_head.z,
                    ramped=canvas.ramped,
                )
                or _mixed_height_branch_endpoint(sibling_tap, sibling_head)
            ):
                excused.update(_run_cells(canvas, into, sibling_indices[0]))
        tap_blockers: set[Cell] = set()
        tap_reason: list[str] = []
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
            ownership=ownership,
            net_id=net.net_id,
        )
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
    for i, indices in laid.items():
        if i in unlinked or not _committed_path_closes_cycle(canvas, indices):
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
    prebuilt_sources: Mapping[Cell, int] | None = None,
) -> int | None:
    """What this path actually left from: the lane tap, or a sibling to branch off.

    The mirror of :func:`_sink_for`.  A path that could not start beside its own
    lane was routed from a sibling's belt instead, and feeding it from
    ``net.src.belt`` regardless would name a building it is nowhere near.

    ``kin`` IS THE SIBLING SET THE ROUTER ACTUALLY OFFERED -- the cells of the
    paths in this net's ``src_group`` and selected prebuilt source taps in that
    same cargo/supply group. Honouring it keeps this branch on THIS net's source.
    ``prebuilt_sources`` preserves the declared feeder's building identity at
    those selected taps: emitting a Splitter adds co-located output stubs that
    overwrite the canvas cell owner but are not replacement source feeders.

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
        who = (prebuilt_sources or {}).get(hint, canvas.blocked.get(hint))
        other = canvas.buildings.by_index(who)
        if (
            hint in kin
            and who is not None
            and other is not None
            and who not in own
            and who != net.dst.belt
        ) and (
            catalog.is_belt(other.item_id)
            and other.carries_item == net.item
            and _lattice_cell(other.x, other.y, other.z) == hint
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
        other = canvas.buildings.by_index(who)
        if who is None or other is None or who in own:
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
        if catalog.is_belt(other.item_id) and other.carries_item == net.item:
            return who
    # Nothing adjacent belongs to a net leaving where we leave, so this path
    # leaves from nobody.
    return None


def _output_tail_nets(canvas: _Canvas, nets: Sequence[_Net]) -> list[_Net]:
    """Move shared output taps past their internal consumers.

    A producer lane that also feeds an internal recipe has one physical exit.
    Routing an exterior branch from that exit first either seals the internal
    net or forces both branches onto a Splitter beside the machine row. Route
    the internal graph first, then continue from its open downstream tail: every
    upstream source reaches that tail through the committed merges, and one
    exterior belt carries the actual surplus left after the consumers draw.
    """
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
            building = canvas.buildings.by_index(index)
            if index in seen or building is None:
                continue
            seen.add(index)
            if building.item_id in (catalog.SPLITTER_ID, catalog.PILER_ID):
                stack.extend(canvas.buildings.transport_successors(index))
                continue
            if not catalog.is_belt(building.item_id) or building.carries_item != net.item:
                continue
            if building.output_obj is None:
                if building.z.denominator == 1:
                    tails.append(index)
                continue
            stack.extend(canvas.buildings.transport_successors(index))

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
) -> bool:
    """Does flow leaving ``start`` come back to this path?

    Merging into a neighbouring belt is only legal when that belt runs AWAY from
    us.  Two nets that share a source lane and a destination lane end up beside
    each other twice -- the second branches off the first to leave, and then
    finds the first again at the far end -- and merging both ways closes the
    loop.  The validator reports it as ``belt.acyclic``, and it is a real fault:
    the game would run items round it forever.

    Splitters and Pilers are followed through the shared transport adjacency,
    just as the validator follows them; cargo and endpoint policy stay with
    their respective consumers.
    """
    seen: set[int] = set()
    stack = [start]
    while stack:
        i = stack.pop()
        if i in own:
            return True
        b = canvas.buildings.by_index(i)
        if i in seen or b is None:
            continue
        seen.add(i)
        stack.extend(canvas.buildings.transport_successors(i))
    return False


def _committed_path_closes_cycle(
    canvas: _Canvas,
    indices: Sequence[int],
) -> bool:
    """Whether flow from any committed belt can return to that same belt.

    A belt is on a loop iff it sits in a strongly connected component with
    more than one member, or feeds itself.  One Tarjan pass over the part of
    the belt graph reachable from ``indices`` answers that for every index at
    once; the per-index walk it replaces re-traversed the same graph once per
    committed cell (30k walks and 3.4M visits on ``universe-matrix``) and was
    the largest single cost of ``_commit_paths``. Edges are the shared directed
    transport edges that ``_leads_back`` and the validator also follow.
    """
    buildings = canvas.buildings
    n = len(buildings)
    wanted = {i for i in indices if 0 <= i < n}
    if not wanted:
        return False

    successors = buildings.transport_successors

    order = [-1] * n
    low = [0] * n
    on_stack = [False] * n
    stack: list[int] = []
    counter = 0
    for root in wanted:
        if order[root] != -1:
            continue
        order[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack[root] = True
        work = [(root, iter(successors(root)))]
        while work:
            v, it = work[-1]
            descended = False
            for w in it:
                if not 0 <= w < n:
                    continue
                if order[w] == -1:
                    order[w] = low[w] = counter
                    counter += 1
                    stack.append(w)
                    on_stack[w] = True
                    work.append((w, iter(successors(w))))
                    descended = True
                    break
                if on_stack[w] and order[w] < low[v]:
                    low[v] = order[w]
            if descended:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                if low[v] < low[parent]:
                    low[parent] = low[v]
            if low[v] == order[v]:
                component = []
                while True:
                    w = stack.pop()
                    on_stack[w] = False
                    component.append(w)
                    if w == v:
                        break
                if len(component) > 1:
                    if any(c in wanted for c in component):
                        return True
                elif component[0] in wanted and component[0] in successors(component[0]):
                    return True
    return False


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
    if _legal_link(
        tail.x, tail.y, tail.z, dst.x, dst.y, dst.z, ramped=canvas.ramped
    ) and not _leads_back(canvas, net.dst.belt, own):
        return net.dst.belt
    if hint is not None:
        if hint in protected_targets:
            return None
        who = canvas.blocked.get(hint)
        other = canvas.buildings.by_index(who)
        if (
            hint in kin
            and who is not None
            and other is not None
            and who not in own
            and (
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
            )
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
        other = canvas.buildings.by_index(who)
        if who is None or other is None or who in own:
            # Never attach to a belt of THIS path. The cell before the one we
            # are linking is adjacent and carries the same item, so it always
            # matches -- and pointing at it makes a two-belt cycle, which
            # `belt.acyclic` then reports.
            continue
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
    into: Callable[[int], Sequence[int]],
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
    walk that stops at one misses exactly the run a tap creates. ``into`` queries
    the maintained reverse links, either all records or only belts.

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
                and canvas.buildings.by_index(onward) is not None
                and onward not in seen
            ):
                seen.add(onward)
                nxt.append(onward)
            for j in into(idx):
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
        building = canvas.buildings.by_index(who)
        if building is not None and catalog.is_belt(building.item_id):
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
    predecessor_choices: Callable[[int], Sequence[int]] | None = None,
    *,
    ownership: RouteOwnership | None = None,
    net_id: NetId | None = None,
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
    first = len(canvas.buildings)
    read_indices = {belt_idx, branch}

    def attribute(indices: Collection[int]) -> None:
        if ownership is not None:
            assert net_id is not None
            ownership.attribute(
                len(canvas.buildings),
                indices,
                net_id,
                dependencies=read_indices,
            )

    if predecessor_choices is None:
        predecessor_choices = canvas.buildings.belts_into
    if onward is None:
        canvas.buildings[belt_idx] = _relink(b, output_obj=branch)
        attribute((belt_idx, branch))
        return True

    if canvas.buildings[onward].item_id == catalog.SPLITTER_ID:
        junction_idx = onward
        read_indices.add(junction_idx)
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
        for index in canvas.buildings.attached_to(junction_idx):
            read_indices.add(index)
            candidate = canvas.buildings[index]
            outward_idx: int | None
            if candidate.output_obj == junction_idx:
                attached += 1
                incoming = predecessor_choices(index)
                read_indices.update(incoming)
                outward_idx = incoming[0] if len(incoming) == 1 else None
            elif candidate.input_obj == junction_idx:
                attached += 1
                outward_idx = candidate.output_obj
                if outward_idx is not None:
                    read_indices.add(outward_idx)
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
        incoming = canvas.buildings.belts_into(belt_idx)
        read_indices.update((onward, *incoming))
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
                candidate = canvas.buildings.by_index(current)
                if candidate is None:
                    return False
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
                        or len(predecessor_choices(who)) <= 1
                    )
                ):
                    continue
                who = canvas.blocked.get(cell)
                building = canvas.buildings.by_index(who)
                if building is not None and catalog.is_belt(building.item_id):
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
    canvas.add(
        replace(
            branch_attachment,
            yaw=canvas.buildings[branch].yaw,
            input_obj=junction_idx,
            output_obj=branch,
        )
    )
    # Shared junctions and every earlier attachment read to choose a spare
    # port are causal participants, including co-located distinct records.
    attribute((*read_indices, *range(first, len(canvas.buildings))))
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
    reservations = _CorridorReservations(canvas)

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
                source=((port_of(net).x, port_of(net).y, port_of(net).z) if outward else None),
                destination=(None if outward else (port_of(net).x, port_of(net).y, port_of(net).z)),
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
            retired = reservations.retire(
                port_key,
                (),
                (
                    PortAccessKind.EARLY_BOUNDARY_DEPARTURE
                    if outward
                    else PortAccessKind.BOUNDARY_ARRIVAL
                ),
            )
            if retired is None:
                reservations.retire_first(port_key)

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
                            destination=(None if outward else (port.x, port.y, port.z)),
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

    def __init__(self) -> None:
        super().__init__()
        # A routing owner retains work and real refusals completed before the
        # interrupted query, without interpreting that query as a failed one.
        self.expansions = 0
        self.net_index: int | None = None
        self.failures: dict[int, NetFailure] = {}


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

    STAYS under a node arm, and gains a NEW raise site: "no free ground for the
    ... Spray Coater node near the lane head", when `_coater_node_site` finds
    no clear node ring within its radius. A pack that cannot site a node is not
    a pack, for exactly the reason a pack that cannot seat a coater is not.
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
        if os.environ.get("FLAB2BP_COATER_TRACE"):
            # EXPERIMENT: the sweep swallows this and reports only the check
            # name, so an arm comparison cannot see WHICH lane refused or why.
            print(f"UNSEATABLE {message}", file=sys.stderr, flush=True)
        super().__init__(message)


class _Unpowerable(Exception):
    """This pack cannot be powered, so it is not a feasible pack.

    Raised by :func:`_power_plan` before routing, by :func:`plan_power_infill`
    for unjoinable composed networks, and by :func:`_place_power` if a held
    site was taken anyway. Projected refusals
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


def _power_projection_contexts(
    projections: Sequence[planet.Projection],
) -> tuple[tuple[int, bool, float], ...]:
    """Distinct curvature contexts the power broad phase has to consider.

    Two projections that share a band's column count, an orientation and a
    grid scale bound the same node pair identically, so the broad phase reads
    each such context once however many anchors produced it.
    """
    return tuple(
        dict.fromkeys(
            (
                projection.band.columns,
                projection.rotated,
                _minimum_projection_grid_scale((projection.band,)),
            )
            for projection in projections
        )
    )


def _projected_power_peer_possible(
    candidate: tuple[int, PlacedBuilding, rules.PowerNode],
    peer: tuple[int, PlacedBuilding, rules.PowerNode],
    projection_contexts: Sequence[tuple[int, bool, float]],
    *,
    cancelled: Callable[[], bool] | None = None,
    candidate_centre: tuple[float, float, float] | None = None,
    peer_centre: tuple[float, float, float] | None = None,
) -> bool:
    """Whether curvature could bring this node pair inside either paste gate.

    ``candidate_centre`` and ``peer_centre`` are pure caches of the local
    offset each side would be given here; a caller that already holds one
    passes it so the same node's centre is not recomputed once per pairing.
    """
    if cancelled is not None and cancelled():
        raise _PreparationDeadline
    _candidate_index, candidate_building, candidate_node = candidate
    _peer_index, peer_building, peer_node = peer
    if candidate_centre is None:
        candidate_centre = codec.tile_to_local_offset(
            candidate_building.x,
            candidate_building.y,
            candidate_building.z,
            candidate_building.width,
            candidate_building.height,
        )
    if peer_centre is None:
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
    canonical_frames: dict[_JunctionProjectionFrame, _JunctionProjectionFrame] = field(
        default_factory=dict
    )
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
        JunctionOffsetKey,
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
                "canonical_frames": len(self.canonical_frames),
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
        generated = _junction_projection_frames(
            occupied,
            limit,
            policy,
            cancelled=cancelled,
        )
        # Equal frames from different extents must not repeat deep comparisons
        # in every downstream member/pair verdict lookup.
        canonical: list[_JunctionProjectionFrame] = []
        for frame in generated:
            if cancelled is not None and cancelled():
                raise _PreparationDeadline
            canonical.append(cache.canonical_frames.setdefault(frame, frame))
        if cancelled is not None and cancelled():
            raise _PreparationDeadline
        frames = tuple(canonical)
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


@dataclass(slots=True)
class _CoaterJunctionCache:
    """Pure geometry shared by one composition's coater preparations."""

    stacks: dict[Cell, tuple[colliders.Placed, ...]] = field(default_factory=dict)
    materialized_stacks: dict[
        tuple[Cell, tuple[int, int, int, int], finalize.FrameCandidate],
        tuple[colliders.Placed, ...],
    ] = field(default_factory=dict)
    materialized_coaters: dict[
        tuple[PlacedBuilding, tuple[int, int, int, int], finalize.FrameCandidate],
        PlacedBuilding,
    ] = field(default_factory=dict)
    splitter_boxes: dict[tuple[colliders.Placed, planet.Projection], list[colliders.Box]] = field(
        default_factory=dict
    )
    relation_overlaps: dict[tuple[object, ...], bool] = field(default_factory=dict)
    context_states: dict[
        tuple[object, ...],
        tuple[planet.Projection, colliders.Placed, tuple[colliders.Box, ...]],
    ] = field(default_factory=dict)
    steps: dict[tuple[planet.Band, int, float], tuple[float, float]] = field(default_factory=dict)
    pole_states: dict[planet.Projection, dict[tuple[float, float], bool]] = field(
        default_factory=dict
    )

    def pole_forward(self, placed: colliders.Placed, projection: planet.Projection) -> bool:
        states = self.pole_states.get(projection)
        if states is None:
            states = {}
            self.pole_states[projection] = states
        # direction() depends on exact x/y and projection, not model, z or yaw.
        key = (placed.x, placed.y)
        pole = states.get(key)
        if pole is None:
            # Match spherical_rotation's actual fixed-global-forward branch.
            # That branch is not equivariant under a longitude translation.
            direction = planet._norm(projection.direction(placed.x, placed.y))
            tangent = planet._cross(direction, (0.0, 1.0, 0.0))
            pole = planet._dot3(tangent, tangent) < 1e-4
            states[key] = pole
        return pole

    def coater_context(
        self,
        coater: colliders.Placed,
        projection: planet.Projection,
        *,
        absolute_longitude: bool = False,
    ) -> tuple[
        tuple[object, ...],
        tuple[planet.Projection, colliders.Placed, tuple[colliders.Box, ...]],
    ]:
        longitude, latitude = (coater.y, coater.x) if projection.rotated else (coater.x, coater.y)
        context = (
            projection.band,
            projection.segment,
            projection.radius,
            projection.quadrant,
            projection.anchor_row + latitude,
            coater.z,
            coater.yaw,
            longitude if absolute_longitude or self.pole_forward(coater, projection) else None,
        )
        state = self.context_states.get(context)
        if state is None:
            state = (
                projection,
                coater,
                finalize.projected_coater_keepout_boxes(coater, projection),
            )
            self.context_states[context] = state
        return context, state


def _projected_coater_junction_bans_by_frame(
    coaters: Sequence[tuple[int, PlacedBuilding]],
    frames: Sequence[_JunctionProjectionFrame],
    junction_bounds: tuple[int, int, int, int],
    *,
    belt_rules: catalog.BeltAltitudeRules = _DEFAULT_BELT_RULES,
    already_banned: Set[Cell],
    splitter_index: int,
    cancelled: Callable[[], bool] | None = None,
    cache: _CoaterJunctionCache | None = None,
) -> tuple[frozenset[Cell], ...]:
    """Exact Splitter bans retained separately for each finalizer frame.

    STAYS under a node arm.  Splitter-versus-coater clearance is a pack-level
    fact about a COMMITTED coater, and `placed` commits coaters -- it moves
    where they sit, not whether they exist.  Measured on the small proliferated
    fixture: six calls under `placed`.
    """
    if cancelled is not None and cancelled():
        raise _PreparationDeadline
    levels = math.floor(belt_rules.max_z) + 1
    min_x, min_y, max_x, max_y = junction_bounds
    splitter_span = catalog.collider_span(catalog.SPLITTER_ID, 0.0)
    banned_by_frame: list[set[Cell]] = [set() for _frame in frames]
    if cache is None:
        cache = _CoaterJunctionCache()
    projected_splitter_boxes = cache.splitter_boxes
    projected_relation_overlaps = cache.relation_overlaps

    for coater_index, coater_building in coaters:
        if cancelled is not None and cancelled():
            raise _PreparationDeadline
        coater_pose = _collision_pose(coater_building)
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
                        planet.Projection,
                        dict[tuple[float, float], bool],
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
            materialized_key = (coater_building, frame.bounds, frame.candidate)
            materialized_building = cache.materialized_coaters.get(materialized_key)
            if materialized_building is None:
                materialized_building = finalize.materialize_frame_building(
                    coater_building,
                    bounds=frame.bounds,
                    candidate=frame.candidate,
                )
                cache.materialized_coaters[materialized_key] = materialized_building
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
                    planet.Projection,
                    dict[tuple[float, float], bool],
                ]
            ] = []
            materialized_reach_x = 0
            materialized_reach_y = 0
            for projection in frame.projections:
                if cancelled is not None and cancelled():
                    raise _PreparationDeadline
                projection_context, context_state = cache.coater_context(
                    materialized_coater[1], projection
                )
                if projection_context in seen_projection_contexts:
                    continue
                seen_projection_contexts.add(projection_context)
                step_key = (projection.band, projection.segment, projection.radius)
                steps = cache.steps.get(step_key)
                if steps is None:
                    latitude_step = (
                        projection.radius * planet.latitude_rad_per_grid(projection.segment) * 0.9
                    )
                    longitude_step = (
                        projection.radius
                        * min(
                            math.cos(
                                min(abs(grid), planet.pole_grid_idx(projection.segment))
                                * planet.latitude_rad_per_grid(projection.segment)
                            )
                            for grid in (projection.band.grid_lo, projection.band.grid_hi)
                        )
                        * planet.longitude_rad_per_grid(projection.band.area_segments)
                        * 0.9
                    )
                    steps = (longitude_step, latitude_step)
                    cache.steps[step_key] = steps
                longitude_step, latitude_step = steps
                materialized_reach_x = max(
                    materialized_reach_x,
                    math.ceil(tangent_reach_x / longitude_step),
                )
                materialized_reach_y = max(
                    materialized_reach_y,
                    math.ceil(tangent_reach_y / latitude_step),
                )
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
                        projection,
                        cache.pole_states[projection],
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
                for level in range(levels):
                    cell = (x, y, level)
                    if cell in already_banned:
                        continue
                    splitter_stack = cache.stacks.get(cell)
                    if splitter_stack is None:
                        splitter_stack = tuple(
                            _collision_pose(building)
                            for building in _splitter_stack_geometry(x, y, level)
                        )
                        cache.stacks[cell] = splitter_stack
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
                        stack_key = (cell, frame.bounds, frame.candidate)
                        materialized_stack = cache.materialized_stacks.get(stack_key)
                        if materialized_stack is None:
                            materialized_stack = tuple(
                                _relative_rigid_frame_pose(
                                    splitter,
                                    coater_pose,
                                    materialized_coater[1],
                                    rotated=frame.candidate.frame.rotated,
                                )
                                for splitter in splitter_stack
                            )
                            cache.materialized_stacks[stack_key] = materialized_stack
                        for materialized_splitter in materialized_stack:
                            splitter_xy = (materialized_splitter.x, materialized_splitter.y)
                            cell_dx = abs(materialized_splitter.x - materialized_coater[1].x)
                            cell_dy = abs(materialized_splitter.y - materialized_coater[1].y)
                            for (
                                candidate_projection,
                                x_step,
                                y_step,
                                coater_boxes,
                                canonical_coater,
                                candidate_projection_context,
                                actual_projection,
                                pole_states,
                            ) in frame_projection_states:
                                if (
                                    cell_dx * x_step > tangent_reach_x
                                    or cell_dy * y_step > tangent_reach_y
                                ):
                                    continue
                                delta_x = materialized_splitter.x - materialized_coater[1].x
                                delta_y = materialized_splitter.y - materialized_coater[1].y
                                delta_z = materialized_splitter.z - materialized_coater[1].z
                                if candidate_projection_context[-1] is None:
                                    splitter_pole = pole_states.get(splitter_xy)
                                    if splitter_pole is None:
                                        splitter_pole = cache.pole_forward(
                                            materialized_splitter, actual_projection
                                        )
                                    if splitter_pole:
                                        # A tangent Coater can have a pole-branch
                                        # Splitter peer. Keep absolute geometry for
                                        # the pair, not just pole Coater contexts.
                                        candidate_projection_context, absolute_state = (
                                            cache.coater_context(
                                                materialized_coater[1],
                                                actual_projection,
                                                absolute_longitude=True,
                                            )
                                        )
                                        candidate_projection, canonical_coater, coater_boxes = (
                                            absolute_state
                                        )
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


_JUNCTION_QUERY_DEADLINE: ContextVar[float | None] = ContextVar(
    "junction_query_deadline", default=None
)


@dataclass(slots=True)
class _SelectionExtent:
    parent: _SelectionExtent | None
    member: PlacedBuilding | None
    bounds: tuple[int, int, int, int]
    children: dict[PlacedBuilding, _SelectionExtent] = field(default_factory=dict)


@dataclass(slots=True)
class _SelectionPrefix:
    parent: _SelectionPrefix | None
    member: PlacedBuilding | None
    extent: _SelectionExtent
    children: dict[PlacedBuilding, _SelectionPrefix] = field(default_factory=dict)
    verdict: bool | None = None


@dataclass(slots=True)
class _FramePairChecks:
    """Frame-local identities and exact ordered-pair compatibility proofs."""

    indices: dict[PlacedBuilding, int] = field(default_factory=dict)
    members: list[PlacedBuilding] = field(default_factory=list)
    compatible: list[int] = field(default_factory=list)
    incompatible: list[int] = field(default_factory=list)


class _CompositionProjection:
    """Prospective composition objects must share one reachable physical frame.

    The fixed canvas is immutable input. Every query includes ALL selected new
    objects, so rip-up can restore a frame and a later extent expansion cannot
    reuse a frame verdict established for a smaller selection.
    """

    def __init__(
        self,
        buildings: Sequence[PlacedBuilding],
        capacity: tuple[int, int, int, int],
        policy: BandPolicy,
        *,
        belt_rules: catalog.BeltAltitudeRules = _DEFAULT_BELT_RULES,
        cancelled: Callable[[], bool] | None = None,
        power_sites: Sequence[tuple[int, int]] = (),
        tower: catalog.Building | None = None,
    ) -> None:
        self.canvas_prefix_count = len(buildings)
        if tower is None:
            tower = catalog.power_tower_building(catalog.DEFAULT_POWER_TOWER)
        self.reserved_buildings = frozenset(
            PlacedBuilding(
                tower.item_id, tower.model_index, x, y, width=tower.width, height=tower.height
            )
            for x, y in power_sites
        )
        self.buildings = (*buildings, *sorted(self.reserved_buildings, key=lambda b: (b.x, b.y)))
        self.capacity = capacity
        self.policy = policy
        self.belt_rules = belt_rules
        self.levels = math.floor(belt_rules.max_z) + 1
        self.cancelled: Callable[[], bool] = lambda: (
            (cancelled is not None and cancelled()) or _expired(_JUNCTION_QUERY_DEADLINE.get())
        )
        self._cache = _StagedStaticCache()
        self._coater_cache = _CoaterJunctionCache()
        self._projection_cache = finalize._ProjectionCache(
            finalize._ProjectionCounters(), cancelled=self.cancelled
        )
        try:
            self._obstacles = _ProjectedObstacleIndex.build(
                tuple(enumerate(self.buildings)), cancelled=cancelled
            )
            self._cleanup = finalize._CleanupSurvivorGraph(
                Placement(buildings=self.buildings), cancelled=cancelled
            )
            self._bounds = self._cleanup.snapshot_bounds()
            self._power = finalize._power_nodes(
                Placement(buildings=self.buildings), cancelled=cancelled
            )
        except finalize.ProjectionCancelled:
            raise _PreparationDeadline from None
        self._coaters = tuple(
            (index, building)
            for index, building in enumerate(self.buildings)
            if building.item_id == catalog.SPRAY_COATER_ID
        )
        self._materialized_coaters: dict[
            tuple[tuple[int, int, int, int], finalize.FrameCandidate],
            tuple[tuple[int, colliders.Placed], ...],
        ] = {}
        self._peers: dict[tuple[PlacedBuilding, tuple[planet.Band, ...]], tuple[int, ...]] = {}
        self._base_verdicts: dict[_JunctionProjectionFrame, bool] = {}
        self._base_static_contexts: set[tuple[planet.Band, int, float, int, bool, float, float]] = (
            set()
        )
        self._base_addon_verdicts: dict[
            tuple[planet.Band, int, float, int, bool, float, float | None], bool
        ] = {}
        self._base_power_verdicts: dict[
            tuple[planet.Band, int, float, int, bool, float, float], bool
        ] = {}
        self._selection_root = _SelectionPrefix(
            None, None, _SelectionExtent(None, None, self._bounds)
        )
        self._member_verdicts: dict[tuple[PlacedBuilding, _JunctionProjectionFrame], bool] = {}
        self._frame_pair_checks: dict[_JunctionProjectionFrame, _FramePairChecks] = {}
        self._coater_context_verdicts: dict[
            tuple[PlacedBuilding, tuple[planet.Band, int, float, int, bool, float, float]], bool
        ] = {}
        self._addition_obstacles: dict[PlacedBuilding, _ProjectedObstacleIndex] = {}
        self._frame_bands: dict[_JunctionProjectionFrame, tuple[planet.Band, ...]] = {}
        self._static = tuple(
            (index, building)
            for index, building in enumerate(self.buildings)
            if not catalog.is_belt(building.item_id) and not catalog.is_sorter(building.item_id)
        )

    def allows_buildings(
        self,
        candidates: tuple[PlacedBuilding, ...],
        *,
        committed: tuple[PlacedBuilding, ...] = (),
        deadline: float | None = None,
    ) -> bool:
        """Judge actual model/yaw stack members in the shared exact frame engine."""
        token = _JUNCTION_QUERY_DEADLINE.set(deadline)
        try:
            return self.allows(committed + candidates)
        finally:
            _JUNCTION_QUERY_DEADLINE.reset(token)

    def allows(self, additions: tuple[PlacedBuilding, ...]) -> bool:
        if self.cancelled():
            raise _PreparationDeadline
        if not additions:
            return True
        try:
            nodes = self._selection_nodes(additions)
            selection = nodes[-1]
            if self.cancelled():
                raise _PreparationDeadline
            if selection.verdict is not None:
                return selection.verdict
            bounds = selection.extent.bounds
            if not (
                self.capacity[0] <= bounds[0] <= bounds[2] <= self.capacity[2]
                and self.capacity[1] <= bounds[1] <= bounds[3] <= self.capacity[3]
            ):
                return False
            frames = _cached_junction_projection_frames(
                self._cache, bounds, self.capacity, self.policy, cancelled=self.cancelled
            )
        except finalize.ProjectionCancelled:
            raise _PreparationDeadline from None
        try:
            verdict = any(self._frame_clear(additions, frame) for frame in frames)
            if self.cancelled():
                raise _PreparationDeadline
            selection.verdict = verdict
            return verdict
        except finalize.ProjectionCancelled:
            raise _PreparationDeadline from None

    def _selection_nodes(self, additions: tuple[PlacedBuilding, ...]) -> list[_SelectionPrefix]:
        nodes: list[_SelectionPrefix] = []
        parent = self._selection_root
        for building in additions:
            if self.cancelled():
                raise _PreparationDeadline
            node = parent.children.get(building)
            if node is None:
                extent = parent.extent
                bounds = extent.bounds
                if not (
                    bounds[0] <= building.x
                    and bounds[1] <= building.y
                    and building.x + building.width - 1 <= bounds[2]
                    and building.y + building.height - 1 <= bounds[3]
                ):
                    member = (
                        building
                        if building.input_obj is None and building.output_obj is None
                        else replace(building, input_obj=None, output_obj=None)
                    )
                    grown = extent.children.get(member)
                    if grown is None:
                        chain: list[PlacedBuilding] = []
                        prior = extent
                        while prior.member is not None:
                            if self.cancelled():
                                raise _PreparationDeadline
                            chain.append(prior.member)
                            assert prior.parent is not None
                            prior = prior.parent
                        chain.reverse()
                        if self.cancelled():
                            raise _PreparationDeadline
                        # Rebuild the exact appended-member chain, never a
                        # union of survivor rectangles or a retained base fork.
                        prefix = (
                            self._cleanup.extended(chain, cancelled=self.cancelled)
                            if chain
                            else self._cleanup
                        )
                        snapshot, grown_bounds = _cleanup_snapshot_with_linkless_static(
                            prefix, bounds, member, cancelled=self.cancelled
                        )
                        del snapshot, prefix
                        if self.cancelled():
                            raise _PreparationDeadline
                        grown = _SelectionExtent(extent, member, grown_bounds)
                        extent.children[member] = grown
                    extent = grown
                if self.cancelled():
                    raise _PreparationDeadline
                node = _SelectionPrefix(parent, building, extent)
                parent.children[building] = node
            nodes.append(node)
            parent = node
        return nodes

    def _materialize(
        self, building: PlacedBuilding, frame: _JunctionProjectionFrame
    ) -> PlacedBuilding:
        key = (building, frame.bounds, frame.candidate)
        materialized = self._cache.materialized.get(key)
        if materialized is None:
            materialized = finalize.materialize_frame_building(
                building, bounds=frame.bounds, candidate=frame.candidate
            )
            self._cache.materialized[key] = materialized
        return materialized

    def _coaters_for(
        self, frame: _JunctionProjectionFrame
    ) -> tuple[tuple[int, colliders.Placed], ...]:
        key = (frame.bounds, frame.candidate)
        coaters = self._materialized_coaters.get(key)
        if coaters is None:
            coaters = tuple(
                (index, _collision_pose(self._materialize(building, frame)))
                for index, building in self._coaters
            )
            self._materialized_coaters[key] = coaters
        return coaters

    @staticmethod
    def _base_projection_key(
        origin: tuple[float, float, float],
        frame: _JunctionProjectionFrame,
        projection: planet.Projection,
    ) -> tuple[planet.Band, int, float, int, bool, float, float]:
        # The immutable inventory fixes models, heights and relative centres;
        # frame rotation fixes materialized dimensions and every model's yaw.
        # Raw effective latitude and absolute longitude then fix exact poses.
        # Do not clamp latitude or normalize longitude: strict geometry/power
        # gates can observe roundoff between merely congruent configurations.
        x, y, _z = origin
        return (
            projection.band,
            projection.segment,
            projection.radius,
            projection.quadrant,
            frame.candidate.frame.rotated,
            projection.anchor_row + (x if projection.rotated else y),
            y if projection.rotated else x,
        )

    def _base_clear(self, frame: _JunctionProjectionFrame) -> bool:
        verdict = self._base_verdicts.get(frame)
        if verdict is not None:
            return verdict
        static = tuple(
            (index, self._materialize(building, frame)) for index, building in self._static
        )
        if self.cancelled():
            raise _PreparationDeadline
        if static:
            static_origin = finalize._building_centre(static[0][1])
            pending_projections: dict[
                tuple[planet.Band, int, float, int, bool, float, float],
                planet.Projection,
            ] = {}
            for projection in frame.projections:
                if self.cancelled():
                    raise _PreparationDeadline
                static_key = self._base_projection_key(static_origin, frame, projection)
                if static_key not in self._base_static_contexts:
                    pending_projections[static_key] = projection
            if pending_projections:
                # The exact checker owns a per-band broad phase. Keep all
                # uncached anchors together instead of rebuilding the same
                # candidate pairs for each anchor of this immutable inventory.
                failure = finalize.first_projected_static_failure(
                    static,
                    tuple(pending_projections.values()),
                    _clean_contexts=self._cache.clean_contexts,
                    _box_cache=self._cache.boxes,
                    _placed_cache=self._cache.placed,
                    cancelled=self.cancelled,
                )
                if self.cancelled():
                    raise _PreparationDeadline
                if failure is not None:
                    self._base_verdicts[frame] = False
                    return False
                self._base_static_contexts.update(pending_projections)
        nodes = tuple(
            (index, self._materialize(building, frame), properties)
            for index, building, properties in self._power
        )
        power_origin = finalize._building_centre(nodes[0][1]) if nodes else None
        coaters = self._coaters_for(frame)
        splitters = tuple(
            (index, _collision_pose(building))
            for index, building in static
            if building.item_id == catalog.SPLITTER_ID
        )
        for projection in frame.projections:
            if self.cancelled():
                raise _PreparationDeadline
            if power_origin is not None:
                power_key = self._base_projection_key(power_origin, frame, projection)
                power_clear = self._base_power_verdicts.get(power_key)
                if power_clear is None:
                    power_clear = self._projection_cache.power_failure(nodes, projection) is None
                    self._base_power_verdicts[power_key] = power_clear
                if not power_clear:
                    self._base_verdicts[frame] = False
                    return False
            if not coaters or not splitters:
                continue
            # The owner fixes every relative pose. Frame rotation plus one
            # exact effective latitude fixes the whole body's configuration;
            # only a uniform longitude rotation remains. This is the same
            # invariant used by the finalizer's normalized static contexts.
            origin = coaters[0][1]
            pole_affected = any(
                self._coater_cache.pole_forward(placed, projection)
                for group in (coaters, splitters)
                for _index, placed in group
            )
            addon_key = (
                projection.band,
                projection.segment,
                projection.radius,
                projection.quadrant,
                frame.candidate.frame.rotated,
                projection.anchor_row + (origin.x if projection.rotated else origin.y),
                (origin.y if projection.rotated else origin.x) if pole_affected else None,
            )
            addon_clear = self._base_addon_verdicts.get(addon_key)
            if addon_clear is None:
                addon_clear = (
                    self._projection_cache.addon_splitter_failure(coaters, splitters, projection)
                    is None
                )
                self._base_addon_verdicts[addon_key] = addon_clear
            if not addon_clear:
                self._base_verdicts[frame] = False
                return False
        self._base_verdicts[frame] = True
        return True

    def _member_clear(self, building: PlacedBuilding, frame: _JunctionProjectionFrame) -> bool:
        key = (building, frame)
        verdict = self._member_verdicts.get(key)
        if verdict is not None:
            return verdict
        index = len(self.buildings)
        bands = self._frame_bands.get(frame)
        if bands is None:
            bands = tuple(
                sorted(
                    {projection.band for projection in frame.projections},
                    key=lambda band: band.area_segments,
                )
            )
            self._frame_bands[frame] = bands
        peers_key = (building, bands)
        peers = self._peers.get(peers_key)
        if peers is None:
            peers = _prospective_static_broad_phase_for_bands(
                self._obstacles, building, bands, self._cache, cancelled=self.cancelled
            )
            self._peers[peers_key] = peers
        if (
            peers
            and _prospective_static_failure(
                (*((peer, self.buildings[peer]) for peer in peers), (index, building)),
                (frame,),
                candidate_index=index,
                cache=self._cache,
                cancelled=self.cancelled,
            )
            is not None
        ):
            self._member_verdicts[key] = False
            return False
        materialized = self._materialize(building, frame)
        if building.item_id == catalog.SPLITTER_ID and self._coaters:
            coaters = self._coaters_for(frame)
            origin = coaters[0][1]
            splitters = ((index, _collision_pose(materialized)),)
            for projection in frame.projections:
                if self.cancelled():
                    raise _PreparationDeadline
                context_key = (
                    building,
                    self._base_projection_key((origin.x, origin.y, origin.z), frame, projection),
                )
                coater_clear = self._coater_context_verdicts.get(context_key)
                if coater_clear is None:
                    coater_clear = (
                        self._projection_cache.addon_splitter_failure(
                            coaters, splitters, projection
                        )
                        is None
                    )
                    if self.cancelled():
                        raise _PreparationDeadline
                    self._coater_context_verdicts[context_key] = coater_clear
                if not coater_clear:
                    self._member_verdicts[key] = False
                    return False
        info = catalog.building(building.item_id)
        if info.power_node.is_power_node:
            candidate = (index, materialized, info.power_node)
            for projection in frame.projections:
                for peer, node, properties in self._power:
                    if (
                        self._projection_cache.power_failure(
                            ((peer, self._materialize(node, frame), properties), candidate),
                            projection,
                        )
                        is not None
                    ):
                        self._member_verdicts[key] = False
                        return False
        self._member_verdicts[key] = True
        return True

    def _pair_clear(
        self, left: PlacedBuilding, right: PlacedBuilding, frame: _JunctionProjectionFrame
    ) -> bool:
        index = self._addition_obstacles.get(left)
        if index is None:
            index = _ProjectedObstacleIndex.build(((0, left),), cancelled=self.cancelled)
            self._addition_obstacles[left] = index
        if (
            _prospective_static_broad_phase_for_bands(
                index, right, self._frame_bands[frame], self._cache, cancelled=self.cancelled
            )
            and _prospective_static_failure(
                ((0, left), (1, right)),
                (frame,),
                candidate_index=1,
                cache=self._cache,
                cancelled=self.cancelled,
            )
            is not None
        ):
            return False
        left_power = catalog.building(left.item_id).power_node
        right_power = catalog.building(right.item_id).power_node
        if left_power.is_power_node and right_power.is_power_node:
            nodes = (
                (0, self._materialize(left, frame), left_power),
                (1, self._materialize(right, frame), right_power),
            )
            for projection in frame.projections:
                if self._projection_cache.power_failure(nodes, projection) is not None:
                    return False
        return True

    def _frame_clear(
        self, additions: tuple[PlacedBuilding, ...], frame: _JunctionProjectionFrame
    ) -> bool:
        # Frame-local proofs survive selection changes, never an extent change.
        if not self._base_clear(frame):
            return False
        checks = self._frame_pair_checks.get(frame)
        if checks is None:
            checks = _FramePairChecks()
            self._frame_pair_checks[frame] = checks
        prior = 0
        for building in additions:
            if self.cancelled():
                raise _PreparationDeadline
            position = checks.indices.get(building)
            if position is None:
                if not self._member_clear(building, frame):
                    return False
                position = len(checks.members)
                checks.indices[building] = position
                checks.members.append(building)
                checks.compatible.append(0)
                checks.incompatible.append(0)
            if prior & checks.incompatible[position]:
                return False
            unchecked = prior & ~checks.compatible[position]
            while unchecked:
                bit = unchecked & -unchecked
                previous = checks.members[bit.bit_length() - 1]
                if not self._pair_clear(previous, building, frame):
                    checks.incompatible[position] |= bit
                    return False
                checks.compatible[position] |= bit
                unchecked ^= bit
            prior |= 1 << position
        return True


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


def _power_reservation(tower: catalog.Building) -> tuple[int, int, int, int]:
    """Cell offsets enclosing the collider clearance about the real footprint.

    Round half-cell halos outwards on BOTH sides. A 6x6 clearance centred on a
    5x5 substation therefore holds 7x7 cells; shifting a 6x6 rectangle east would
    leave its west collider edge unprotected. Tesla retains its 1x1 reservation.
    """
    if tower.item_id == catalog.TESLA_TOWER_ID:
        return 0, 0, tower.width, tower.height
    width, height = catalog.clearance(tower.item_id, 0)
    halo_x = max(0, (width - tower.width + 1) // 2)
    halo_y = max(0, (height - tower.height + 1) // 2)
    return -halo_x, -halo_y, tower.width + halo_x, tower.height + halo_y


def _power_plan(
    canvas: _Canvas,
    demand: tuple[int, int, int, int],
    *,
    policy: BandPolicy,
    additional_demand: Collection[tuple[int, int]] = (),
    complete_plan_failure: Callable[[tuple[PlacedBuilding, ...]], finalize.ProjectionFailure | None]
    | None = None,
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
    tower = canvas.power_building
    reserve_x0, reserve_y0, reserve_x1, reserve_y1 = _power_reservation(tower)
    reserve_width = reserve_x1 - reserve_x0
    reserve_height = reserve_y1 - reserve_y0
    centre_dx = (tower.width - 1) // 2
    centre_dy = (tower.height - 1) // 2
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
    # Incremental removal reads a two-radius score window one disc further
    # out. Its source tiles are offset from anchors by the footprint centre.
    pad = max(pad, 3 * reach + max(centre_dx, centre_dy), reserve_width, reserve_height)
    shape = (width + 2 * pad, height + 2 * pad)

    # A column is out if ANY level of it is blocked, so the level walk below
    # asked `canvas.blocked` up to LEVELS times per tile.  The set of blocked
    # columns answers the same question once, for the whole fill.
    blocked_columns = {(bx, by) for (bx, by, _level) in canvas.blocked}

    open_ground = np.zeros(shape, dtype=bool)
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
            if (x, y) in blocked_columns:
                continue
            open_ground[x - min_x + pad, y - min_y + pad] = True

    # Erode open ground by the collider-clearance reservation, not merely the
    # visible footprint. Low-confidence substation collider findings may be
    # suppressed by certification, so routing must never borrow this halo.
    # The Tesla offsets are still only (0, 0), preserving its default mask.
    free = open_ground.copy()
    for footprint_dx in range(reserve_x0, reserve_x1):
        for footprint_dy in range(reserve_y0, reserve_y1):
            if not footprint_dx and not footprint_dy:
                continue
            shifted = np.zeros(shape, dtype=bool)
            shifted[
                max(0, -footprint_dx) : shape[0] - max(0, footprint_dx),
                max(0, -footprint_dy) : shape[1] - max(0, footprint_dy),
            ] = open_ground[
                max(0, footprint_dx) : shape[0] - max(0, -footprint_dx),
                max(0, footprint_dy) : shape[1] - max(0, -footprint_dy),
            ]
            free &= shifted

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
    for index in sorted(
        (
            *canvas.buildings.machines(),
            *canvas.buildings.sorters(),
            *canvas.buildings.by_kind(BuildingKind.OTHER),
        )
    ):
        b = canvas.buildings[index]
        if cancelled is not None and cancelled():
            raise _PreparationDeadline
        # The chosen tower's id, NOT "any power node": a recipe set may legitimately
        # build other power buildings, and treating one of those as a site this
        # planner already placed would leave its tiles uncovered.
        if catalog.is_belt(b.item_id) or b.item_id == tower.item_id:
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
        for dx in range(centre_dx - reach, centre_dx + reach + 1)
        for dy in range(centre_dy - reach, centre_dy + reach + 1)
        if (2 * dx + 1 - tower.width) ** 2 + (2 * dy + 1 - tower.height) ** 2 <= reach2
    ]
    disc_stamp = np.zeros((2 * reach + 1, 2 * reach + 1), dtype=bool)
    for dx, dy in disc:
        disc_stamp[dx - centre_dx + reach, dy - centre_dy + reach] = True
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
    # Kept in lockstep with `power_nodes`: the local offset of each node's
    # building, which the broad-phase peer gate below would otherwise recompute
    # once per candidate per peer.  `zip(..., strict=True)` makes a missed
    # append fail loudly instead of silently pairing the wrong centre.
    peer_centres: list[tuple[float, float, float]] = []
    for index in sorted(
        (*canvas.buildings.machines(), *canvas.buildings.by_kind(BuildingKind.OTHER))
    ):
        b = canvas.buildings[index]
        if cancelled is not None and cancelled():
            raise _PreparationDeadline
        try:
            peer = catalog.building(b.item_id).power_node
        except KeyError:
            continue
        if not peer.is_power_node:
            continue
        power_nodes.append((index, b, peer))
        peer_centres.append(codec.tile_to_local_offset(b.x, b.y, b.z, b.width, b.height))
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

    if cancelled is not None and cancelled():
        raise _PreparationDeadline
    static_buildings = list(enumerate(canvas.buildings))
    cleanup_prefix = finalize._CleanupSurvivorGraph(
        Placement(buildings=tuple(building for _, building in static_buildings)),
        cancelled=cancelled,
        _operations=staged_static_cache.cleanup_operations,
    )
    cleanup_bounds = cleanup_prefix.snapshot_bounds()
    projections = _projection_envelope(
        cleanup_bounds,
        canvas.limit or _core_bounds(canvas),
        policy,
        cancelled=cancelled,
    )
    projection_bands = tuple(
        sorted(
            {projection.band for projection in projections},
            key=lambda band: band.area_segments,
        )
    )
    static_by_index = dict(static_buildings)
    obstacle_index = _ProjectedObstacleIndex.build(
        static_buildings,
        cancelled=cancelled,
    )
    static_frames_by_bounds: dict[
        tuple[int, int, int, int],
        tuple[_JunctionProjectionFrame, ...],
    ] = {}
    #: Per-candidate narrowing of ``projections``, keyed on the cleanup-survivor
    #: rectangle the candidate itself forces.  See the placement loop.
    reachable_by_bounds: dict[
        tuple[int, int, int, int],
        tuple[tuple[planet.Projection, ...], tuple[tuple[int, bool, float], ...]],
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
    #
    # `free`, deliberately, and NOT `open_ground`.  Reading the ground instead
    # was tried and reverted: `free` is not `open_ground` even on the 1x1
    # default, because the existing-power-node keepout loop above punches a halo
    # into `free` before this runs.  On a canvas carrying one 3x3 power node
    # that is 36 cells of differing openness, 16 of them legal candidates, and
    # `key = score * 5 + openness` turns any score tie among them into a
    # different site.  The corpus cannot currently reach it -- of the twelve
    # power-node items only 2201/2202 and 2203/2205 have a halo escaping their
    # own footprint and none of those is generator-placed -- but "unreachable
    # today" is not a reason to move a tie-break inside a footprint fix.
    openness = np.zeros(shape, dtype=np.int32)
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        openness[max(0, dx) : shape[0] + min(0, dx), max(0, dy) : shape[1] + min(0, dy)] += free[
            max(0, -dx) : shape[0] + min(0, -dx), max(0, -dy) : shape[1] + min(0, -dy)
        ]

    remaining = dark.copy()
    remaining_count = int(np.count_nonzero(remaining)) if complete_plan_failure is not None else 0
    deferred_sites: list[tuple[int, int]] = []
    # `score` is maintained incrementally. Rebuilding it every round is the same
    # answer and was measured at 0.9s on `universe-matrix`, which is real money
    # against a 15s deadline; only the cells within two radii of a new tower can
    # change, so only those are touched.
    score = np.zeros(shape, dtype=np.int32)
    # Coverage spreads anchors to tiles; scores gather those tiles back to
    # anchors. These shifts are opposites once the footprint is wider than 1.
    for dx, dy in disc:
        score[max(0, -dx) : shape[0] + min(0, -dx), max(0, -dy) : shape[1] + min(0, -dy)] += (
            remaining[max(0, dx) : shape[0] + min(0, dx), max(0, dy) : shape[1] + min(0, dy)]
        )

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
                item_id=tower.item_id,
                model_index=tower.model_index,
                x=site[0],
                y=site[1],
                width=tower.width,
                height=tower.height,
            ),
            tower.power_node,
        )
        candidate_centre = codec.tile_to_local_offset(
            candidate[1].x,
            candidate[1].y,
            candidate[1].z,
            candidate[1].width,
            candidate[1].height,
        )
        # A TOWER IS A BUILDING, SO IT NARROWS THE BLUEPRINT'S OWN PROJECTIONS.
        #
        # `projections` is the union over every rectangle the finished build
        # could still shrink to, taken before a single tower existed. Standing
        # one here makes the build at least as large as `candidate_bounds`, and
        # a band whose frame cannot hold that rectangle is a paste this
        # candidate can never be part of -- so a paste rule tested there
        # rejects a site on the geometry of a blueprint that would not contain
        # it.
        #
        # That is not a corner case, it is the five-machine hole. A one-strip
        # block's survivors are four rows tall, so the whole 5-row half of the
        # planet is still in the envelope; a tower one row outside them makes
        # the build six rows tall and rules every one of those bands out. Left
        # unnarrowed, `game.power_too_close` in band 4 -- where a longitude
        # collapses to a point, so ANY two nodes are zero units apart -- vetoed
        # nearly every free cell, the greedy ran out of ground with the block's
        # west corner still dark, and both placers refused specs of exactly 5
        # and 6 machines while 4 and 7 laid out.
        #
        # The static-collision check below has always narrowed to exactly this
        # rectangle. The power-node check now does too, from the same bounds.
        #
        # "NARROWING" HOLDS ONLY WHEN `canvas.limit` IS SET.  The per-candidate
        # envelope below is `_projection_envelope(candidate_bounds,
        # canvas.limit or candidate_bounds, ...)`, and `projections` was taken
        # as `_projection_envelope(cleanup_inner, canvas.limit or occupied,
        # ...)`. With a limit the two share that outer box and the candidate's
        # inner rectangle only grew, so the candidate set is a SUBSET of
        # `projections`. Production always has one: `_prepare_routing_problem`
        # assigns `canvas.limit = capacity` (~16740) before it plans power.
        # With `limit=None` -- which only a caller that builds its own canvas
        # reaches, such as the `_power_plan` tests -- the outer box collapses to
        # the inner one on both sides, so the candidate envelope is the
        # projections of the SINGLE rectangle `candidate_bounds` and is not a
        # subset of `projections` at all: `candidate_bounds` can extend past
        # `occupied`, and the extents in between are never enumerated.
        #
        # A linkless tower already inside the certified rectangle cannot change
        # cleanup survivors. Extending any side can revive a linked belt that
        # the old boundary pruned, including one that expands the orthogonal
        # axis, so that case must advance the exact prefix.
        candidate_cleanup, candidate_bounds = _cleanup_snapshot_with_linkless_static(
            cleanup_prefix,
            cleanup_bounds,
            candidate[1],
            cancelled=cancelled,
        )
        reachable = reachable_by_bounds.get(candidate_bounds)
        if reachable is None:
            candidate_projections = _projection_envelope(
                candidate_bounds,
                canvas.limit or candidate_bounds,
                policy,
                cancelled=cancelled,
            )
            reachable = (
                candidate_projections,
                _power_projection_contexts(candidate_projections),
            )
            reachable_by_bounds[candidate_bounds] = reachable
        candidate_projections, candidate_contexts = reachable
        projected_power_peers = tuple(
            peer
            for peer, peer_centre in zip(power_nodes, peer_centres, strict=True)
            if _projected_power_peer_possible(
                candidate,
                peer,
                candidate_contexts,
                cancelled=cancelled,
                candidate_centre=candidate_centre,
                peer_centre=peer_centre,
            )
        )
        candidate_failure: finalize.ProjectionFailure | None = None
        for projection in candidate_projections:
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
        if (
            candidate_failure is None
            and complete_plan_failure is not None
            and int(score[gx, gy]) == remaining_count
        ):
            candidate_failure = complete_plan_failure(
                (
                    *(
                        building
                        for index, building, _ in power_nodes
                        if index >= len(canvas.buildings)
                    ),
                    candidate[1],
                )
            )
            if candidate_failure is not None:
                # Complete geometry can change its primary frame when a later
                # required tower changes the bounds. Revisit only after that
                # prefix changes, not repeatedly against the same placement.
                deferred_sites.append((gx, gy))
                if projected_refusal is None:
                    projected_refusal = candidate_failure
                free[gx, gy] = False
                continue
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
        peer_centres.append(candidate_centre)
        cleanup_bounds = candidate_bounds
        cleanup_prefix = candidate_cleanup
        if complete_plan_failure is not None:
            remaining_count -= int(score[gx, gy])
            for deferred_x, deferred_y in deferred_sites:
                free[deferred_x, deferred_y] = True
            deferred_sites.clear()

        # The cell itself AND every cell inside the paste's power-node spacing
        # rule.  Marking only the cell is what shipped a blueprint the game
        # refused; the halo is what makes this greedy incapable of producing one.
        free[
            gx - spacing_reach : gx + spacing_reach + 1,
            gy - spacing_reach : gy + spacing_reach + 1,
        ] &= ~spacing_stamp
        # Exclude anchors whose clearance reservations overlap the new tower.
        # On Tesla this remains the one cell already cleared by spacing.
        free[
            gx - (reserve_width - 1) : gx + reserve_width,
            gy - (reserve_height - 1) : gy + reserve_height,
        ] = False
        linked[gx - link : gx + link + 1, gy - link : gy + link + 1] |= link_stamp
        win = (
            slice(gx + centre_dx - reach, gx + centre_dx + reach + 1),
            slice(gy + centre_dy - reach, gy + centre_dy + reach + 1),
        )
        newly = remaining[win] & disc_stamp
        if newly.any():
            remaining[win] &= ~disc_stamp
            covered = np.zeros(shape, dtype=bool)
            covered[win] = newly
            # The centre offsets cancel between the placed and scored anchors;
            # the covered source window below still reads the shifted disc.
            lo_x, hi_x = gx - 2 * reach, gx + 2 * reach + 1
            lo_y, hi_y = gy - 2 * reach, gy + 2 * reach + 1
            for dx, dy in disc:
                score[lo_x:hi_x, lo_y:hi_y] -= covered[lo_x + dx : hi_x + dx, lo_y + dy : hi_y + dy]
        if complete_plan_failure is not None and remaining_count == 0:
            break
    else:
        raise _Unpowerable(
            "tower placement did not converge",
            failure=projected_refusal,
            exact_retry_evidence=projected_retry_evidence,
        )

    # Hold the same clearance rectangle through every routing level.
    for site_x, site_y in sites:
        for footprint_dx in range(reserve_x0, reserve_x1):
            for footprint_dy in range(reserve_y0, reserve_y1):
                canvas.keep_out.add((site_x + footprint_dx, site_y + footprint_dy))
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
    tower = canvas.power_building
    reserve_x0, reserve_y0, reserve_x1, reserve_y1 = _power_reservation(tower)
    placed = 0
    for cx, cy in sites:
        # Routing must leave the collider halo free as well as the footprint.
        if not canvas.fits(
            cx + reserve_x0,
            cy + reserve_y0,
            reserve_x1 - reserve_x0,
            reserve_y1 - reserve_y0,
        ):
            raise _Unpowerable(f"planned tower site {(cx, cy)} was taken during routing")
        canvas.add(
            PlacedBuilding(
                item_id=tower.item_id,
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


_DEFAULT_BAND_POLICY = BandPolicy("portable")


def plan_power_infill(
    canvas: _Canvas,
    *,
    policy: BandPolicy = _DEFAULT_BAND_POLICY,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[list[tuple[int, int]], tuple[tuple[int, int], ...]]:
    """Cover actual powered tiles and connect the networks of composed blocks.

    :func:`_power_plan` decides a whole block's network BEFORE routing, from an
    envelope, and that is the right shape for a block: the pack is known, the
    ground is free, and a tower planned there is held in ``keep_out`` until it
    is stood.  A COMPOSED canvas cannot be planned that way, and the reason is
    not tidiness.  Each block arrives with its own network already built and
    sized for its own footprint; what the composition ADDS is belts (unpowered)
    and the Splitters :func:`_commit_paths` creates at taps -- and where a tap
    lands is decided by the router, on ground that only exists once the blocks
    are packed.  Planning the composed envelope before routing would either
    re-plan 61 towers that are already correct or blanket the gap with towers
    for tiles nothing will ever occupy.

    Coverage is planned after ``_route_all`` from what is actually there, not
    from the empty space between blocks. Existing covering nodes may belong to
    separate networks even when no tile is dark. After coverage, legal relays
    grow the first component toward the nearest stranded component, using the
    same finite greedy walk as :func:`_power_plan`. The canvas and the caller's
    cancellation clock bound that walk; no existing building is moved.

    Legality rules, all consulted rather than restated:

    * **Coverage** uses the doubled-integer predicate ``validate._coverage``
      and :func:`_place_power` use, so this pass and the validator cannot
      disagree about a radius.
    * **``game.power_too_close``** -- no site inside
      ``rules.power_node_keepout_offsets`` of any node already present, tower
      or mode-driven machine.
    * **``power.connectivity``** -- covering-node components and every new
      link use doubled centres and the maximum of the two link distances,
      exactly as ``validate._connectivity`` does.
    * **Projected geometry** -- the candidate and all previously chosen sites
      must share a legal reachable frame with the routed static objects,
      including exact power-pair spacing and Coater/Splitter clearances.

    Returns ``(sites, uncovered)``: ground coordinates for
    :func:`_place_power`, and the tiles no legal site could reach. If coverage
    succeeds but the networks cannot be joined, raises :class:`_Unpowerable`
    naming ``power.connectivity`` rather than inventing uncovered tiles.
    """
    tower = canvas.power_building
    reserve_x0, reserve_y0, reserve_x1, reserve_y1 = _power_reservation(tower)
    reserve_width = reserve_x1 - reserve_x0
    reserve_height = reserve_y1 - reserve_y0
    centre_dx = (tower.width - 1) // 2
    centre_dy = (tower.height - 1) // 2
    reach2 = math.floor((2 * tower.cover_radius) ** 2)
    link2 = math.floor((2 * tower.connect_distance) ** 2)

    #: (doubled centre x, doubled centre y, doubled cover radius squared,
    #: doubled connect distance squared) for every node already standing.
    nodes: list[tuple[int, int, int, int]] = []
    keepout: set[tuple[int, int]] = set()
    for b in canvas.buildings:
        if cancelled is not None and cancelled():
            raise _PreparationDeadline
        try:
            info = catalog.building(b.item_id)
        except KeyError:
            continue
        if info.cover_radius > 0:
            nodes.append(
                (
                    2 * b.x + b.width,
                    2 * b.y + b.height,
                    math.floor((2 * info.cover_radius) ** 2),
                    math.floor((2 * info.connect_distance) ** 2),
                )
            )
        if info.power_node.is_power_node:
            cx = b.x + b.width // 2 - centre_dx
            cy = b.y + b.height // 2 - centre_dy
            for dx, dy, dz in rules.power_node_keepout_offsets(info.power_node, tower.power_node):
                if not dz:
                    keepout.add((cx + dx, cy + dy))

    components = UnionFind()

    def join_node(index: int) -> None:
        components.find(index)
        ox, oy, _cover, own_link = nodes[index]
        for peer in range(index):
            if cancelled is not None and cancelled():
                raise _PreparationDeadline
            px, py, _peer_cover, peer_link = nodes[peer]
            if (ox - px) ** 2 + (oy - py) ** 2 <= max(own_link, peer_link):
                components.union(index, peer)

    for index in range(len(nodes)):
        join_node(index)

    def covered(tx: int, ty: int) -> bool:
        dx, dy = 2 * tx + 1, 2 * ty + 1
        return any(
            (dx - ox) * (dx - ox) + (dy - oy) * (dy - oy) <= lim for ox, oy, lim, _link in nodes
        )

    # EVERY NON-BELT BUILDING, INCLUDING THE SUPPLIERS.  `validate`'s `_POWERED`
    # is {MACHINE, SORTER, SPLITTER, PILER, ADDON} and a mode-driven machine
    # that also supplies power is a MACHINE, so it is checked for coverage
    # there too -- and it covers itself, so including it here costs nothing and
    # keeps the two sets from drifting.  Altitude is not in the predicate: a
    # stack of belts over one ground cell is one question, not three.
    dark: set[tuple[int, int]] = set()
    for b in canvas.buildings:
        if cancelled is not None and cancelled():
            raise _PreparationDeadline
        if catalog.is_belt(b.item_id):
            continue
        for tx, ty, _tz in b.tiles():
            if (tx, ty) not in dark and not covered(tx, ty):
                dark.add((tx, ty))
    if not dark and len(components.groups()) < 2:
        return [], ()

    limit = canvas.limit
    if limit is None:  # pragma: no cover - `canvas_for` always sets it
        if len(components.groups()) > 1:
            raise _Unpowerable("power.connectivity: no bounded ground for composed relays")
        return [], tuple(sorted(dark))
    min_x, min_y, max_x, max_y = limit
    blocked_columns = {(bx, by) for (bx, by, _level) in canvas.blocked}
    projection = _CompositionProjection(
        canvas.buildings, limit, policy, belt_rules=canvas.belt_rules, cancelled=cancelled
    )

    def free_site(x: int, y: int) -> bool:
        return (
            min_x <= x <= max_x
            and min_y <= y <= max_y
            and (x, y) not in keepout
            and canvas.fits(x + reserve_x0, y + reserve_y0, reserve_width, reserve_height)
            and all(
                (tx, ty) not in blocked_columns
                for tx in range(x + reserve_x0, x + reserve_x1)
                for ty in range(y + reserve_y0, y + reserve_y1)
            )
        )

    reach = int(tower.cover_radius) + 1
    sites: list[tuple[int, int]] = []
    selected: tuple[PlacedBuilding, ...] = ()

    def select_site(site: tuple[int, int]) -> None:
        nonlocal selected
        sites.append(site)
        selected = (
            *selected,
            PlacedBuilding(
                item_id=tower.item_id,
                model_index=tower.model_index,
                x=site[0],
                y=site[1],
                width=tower.width,
                height=tower.height,
            ),
        )
        nodes.append((2 * site[0] + tower.width, 2 * site[1] + tower.height, reach2, link2))
        join_node(len(nodes) - 1)
        for dx, dy, dz in rules.power_node_keepout_offsets(tower.power_node, tower.power_node):
            if not dz:
                keepout.add((site[0] + dx, site[1] + dy))
        # Spacing alone does not keep two wide clearance reservations apart.
        keepout.update(
            (site[0] + dx, site[1] + dy)
            for dx in range(1 - reserve_width, reserve_width)
            for dy in range(1 - reserve_height, reserve_height)
        )

    # The coverage relation is translation invariant. Dark tiles only disappear,
    # so prepare the initial domain once and maintain exact integer counts.
    # Keep the original dilation bounds, including its doubled-centre offsets.
    coverage_offsets = [
        (dx, dy)
        for dx in range(-reach - centre_dx, reach - centre_dx + 1)
        for dy in range(-reach - centre_dy, reach - centre_dy + 1)
        if (2 * dx + tower.width - 1) ** 2 + (2 * dy + tower.height - 1) ** 2 <= reach2
    ]
    candidate_domain: set[tuple[int, int]] = set()
    for tx, ty in dark:
        if cancelled is not None and cancelled():
            raise _PreparationDeadline
        candidate_domain.update((tx + dx, ty + dy) for dx, dy in coverage_offsets)
    scores: dict[tuple[int, int], int] = {}
    for cx, cy in sorted(candidate_domain):
        if cancelled is not None and cancelled():
            raise _PreparationDeadline
        if free_site(cx, cy):
            scores[cx, cy] = 0
    del candidate_domain
    for tx, ty in dark:
        if cancelled is not None and cancelled():
            raise _PreparationDeadline
        for dx, dy in coverage_offsets:
            site = (tx + dx, ty + dy)
            score = scores.get(site)
            if score is not None:
                scores[site] = score + 1

    while dark:
        if cancelled is not None and cancelled():
            raise _PreparationDeadline
        best_score = 0
        best_site: tuple[int, int] | None = None
        for (cx, cy), score in scores.items():
            if cancelled is not None and cancelled():
                raise _PreparationDeadline
            # Strict improvement preserves the first lexicographic winner.
            # Only keepout changes free-site legality: the canvas is not
            # mutated until the caller emits this plan.
            if score <= best_score or (cx, cy) in keepout:
                continue
            ox, oy = 2 * cx + tower.width, 2 * cy + tower.height
            if not any(
                (ox - px) * (ox - px) + (oy - py) * (oy - py) <= (link2 if link2 > plink else plink)
                for px, py, _cover, plink in nodes
            ):
                continue
            candidate = PlacedBuilding(
                item_id=tower.item_id,
                model_index=tower.model_index,
                x=cx,
                y=cy,
                width=tower.width,
                height=tower.height,
            )
            if projection.allows((*selected, candidate)):
                best_site, best_score = (cx, cy), score
        if best_site is None:
            break
        select_site(best_site)
        cx, cy = best_site
        best_cover = {
            (cx - dx, cy - dy) for dx, dy in coverage_offsets if (cx - dx, cy - dy) in dark
        }
        dark -= best_cover
        for tx, ty in best_cover:
            if cancelled is not None and cancelled():
                raise _PreparationDeadline
            for dx, dy in coverage_offsets:
                site = (tx + dx, ty + dy)
                score = scores.get(site)
                if score is not None:
                    scores[site] = score - 1
        # Link and projected-frame refusals are never cached: another selected
        # site may make a previously refused candidate admissible next round.
    if dark or len(components.groups()) < 2:
        return sites, tuple(sorted(dark))
    del scores, coverage_offsets

    # Evaluate the exact per-tile predicate behind fits once, then intersect
    # shifted views for its rectangular reservation. This keeps canvas.free
    # authoritative for guards, reservations, routing ports and height bans.
    # A false padded boundary is equivalent to free rejecting out-of-bounds
    # footprint tiles; the anchor itself still ranges over the full canvas.
    ground_width = max(0, max_x - min_x + 1)
    ground_height = max(0, max_y - min_y + 1)
    tile_free = np.empty((ground_width, ground_height), dtype=bool)
    for x in range(min_x, max_x + 1):
        if cancelled is not None and cancelled():
            raise _PreparationDeadline
        tile_free[x - min_x] = np.fromiter(
            (
                canvas.free((x, y, 0))
                and (x, y) not in canvas.solid
                and (x, y) not in blocked_columns
                for y in range(min_y, max_y + 1)
            ),
            dtype=bool,
            count=ground_height,
        )
    anchor_free = np.zeros_like(tile_free)
    anchor_x0 = max(0, -reserve_x0)
    anchor_y0 = max(0, -reserve_y0)
    anchor_x1 = min(ground_width, ground_width - reserve_x1 + 1)
    anchor_y1 = min(ground_height, ground_height - reserve_y1 + 1)
    if anchor_x0 < anchor_x1 and anchor_y0 < anchor_y1:
        anchor_free[anchor_x0:anchor_x1, anchor_y0:anchor_y1] = True
        for dx in range(reserve_x0, reserve_x1):
            if cancelled is not None and cancelled():
                raise _PreparationDeadline
            for dy in range(reserve_y0, reserve_y1):
                anchor_free[anchor_x0:anchor_x1, anchor_y0:anchor_y1] &= tile_free[
                    anchor_x0 + dx : anchor_x1 + dx,
                    anchor_y0 + dy : anchor_y1 + dy,
                ]
    del tile_free

    # Chosen-node keepouts and exact projected selection remain dynamic gates.
    # Row-major mask enumeration has the original lexicographic anchor order.
    ground: list[tuple[int, int]] = []
    for x in range(min_x, max_x + 1):
        if cancelled is not None and cancelled():
            raise _PreparationDeadline
        for offset_y in np.flatnonzero(anchor_free[x - min_x]):
            y = min_y + int(offset_y)
            if (x, y) not in keepout:
                ground.append((x, y))
    del anchor_free
    if not ground:
        raise _Unpowerable("power.connectivity: no legal ground for composed relays")
    ground_index = {site: index for index, site in enumerate(ground)}
    centres = 2 * np.asarray(ground, dtype=np.int64) + (tower.width, tower.height)
    available = np.ones(len(ground), dtype=bool)
    linked = np.zeros(len(ground), dtype=bool)
    reached: set[int] = set()
    while True:
        if cancelled is not None and cancelled():
            raise _PreparationDeadline
        stranded: list[int] = []
        for index, (ox, oy, _cover, peer_link) in enumerate(nodes):
            if cancelled is not None and cancelled():
                raise _PreparationDeadline
            if not components.connected(0, index):
                stranded.append(index)
            elif index not in reached:
                linked |= ((centres[:, 0] - ox) ** 2 + (centres[:, 1] - oy) ** 2) <= max(
                    link2, peer_link
                )
                reached.add(index)
        if not stranded:
            break
        for site in keepout:
            occupied_index = ground_index.get(site)
            if occupied_index is not None:
                available[occupied_index] = False

        # Walk to the closest outstanding component. Every accepted relay
        # consumes free ground and joins the first network, so even a blocked
        # detour cannot loop or emit disconnected towers.
        target = min(
            stranded,
            key=lambda peer: min(
                (nodes[peer][0] - nodes[index][0]) ** 2 + (nodes[peer][1] - nodes[index][1]) ** 2
                for index in reached
            ),
        )
        tx, ty, _cover, _target_link = nodes[target]
        distance = (centres[:, 0] - tx) ** 2 + (centres[:, 1] - ty) ** 2
        eligible_relays = available & linked
        while eligible_relays.any():
            if cancelled is not None and cancelled():
                raise _PreparationDeadline
            index = int(np.where(eligible_relays, distance, np.iinfo(np.int64).max).argmin())
            cx, cy = ground[index]
            candidate = PlacedBuilding(
                item_id=tower.item_id,
                model_index=tower.model_index,
                x=cx,
                y=cy,
                width=tower.width,
                height=tower.height,
            )
            if projection.allows((*selected, candidate)):
                select_site((cx, cy))
                available[index] = False
                break
            # A larger selection can expose a different reachable frame.
            # Reject only for this selection, not for the rest of the walk.
            eligible_relays[index] = False
        else:
            raise _Unpowerable(
                "power.connectivity: no legal linked relay joins the remaining "
                f"{len(components.groups()) - 1} composed networks"
            )
    return sites, tuple(sorted(dark))


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

    components = UnionFind()

    for i in range(len(srcs)):
        components.find(("s", i))
    for j in range(len(sinks)):
        components.find(("d", j))
    for i, j in pairs:
        components.union(("s", i), ("d", j), keep_right=True)

    islands: dict[tuple[str, int], tuple[list[int], list[int]]] = defaultdict(lambda: ([], []))
    for i in range(len(srcs)):
        islands[cast(tuple[str, int], components.find(("s", i)))][0].append(i)
    for j in range(len(sinks)):
        islands[cast(tuple[str, int], components.find(("d", j)))][1].append(j)

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


def _exact_shard_flows(
    arcs: Sequence[physical_flow.Arc],
    variables: Sequence[pywraplp.Variable],
    nodes: int,
) -> tuple[Fraction, ...] | None:
    """Reconstruct the native network basis without rounding cargo rates.

    A basic incidence matrix is a forest. Nonbasic arcs sit at an original
    rational bound; leaf conservation determines each basic arc exactly.
    This certifies the native allocation, not its floating-point status.
    """
    flows = [Fraction(0)] * len(arcs)
    balance = [Fraction(0)] * nodes
    basic: list[set[int]] = [set() for _ in range(nodes)]
    for index, (arc, variable) in enumerate(zip(arcs, variables, strict=True)):
        status = variable.basis_status()
        if status == pywraplp.Solver.BASIC and arc.source != arc.sink:
            basic[arc.source].add(index)
            basic[arc.sink].add(index)
            continue
        value = arc.capacity if status == pywraplp.Solver.AT_UPPER_BOUND else arc.lower
        flows[index] = value
        balance[arc.source] += value
        balance[arc.sink] -= value
    leaves = [node for node, edges in enumerate(basic) if len(edges) == 1]
    while leaves:
        node = leaves.pop()
        if len(basic[node]) != 1:
            continue
        index = basic[node].pop()
        arc = arcs[index]
        value = -balance[node] if node == arc.source else balance[node]
        if not arc.lower <= value <= arc.capacity:
            return None
        flows[index] = value
        balance[arc.source] += value
        balance[arc.sink] -= value
        other = arc.sink if node == arc.source else arc.source
        basic[other].remove(index)
        if len(basic[other]) == 1:
            leaves.append(other)
    if any(basic) or any(balance):
        return None
    return tuple(flows)


def _join_shard_islands(
    pairs: Sequence[tuple[int, int]],
    supply: Mapping[int, Fraction],
    demand: Mapping[int, Fraction],
    external: Fraction,
    *,
    shared_sources: Sequence[tuple[int, int]] = (),
    lane_domains: Mapping[int, CargoDomain] | None = None,
) -> list[tuple[int, int]]:
    """Buy directed producer-to-consumer links only for unmet allocation.

    Sibling output lanes share one producer budget, but are not transport
    edges. In particular A->X, B->X, B->Y cannot send A's surplus backwards
    through X to Y. A native minimum-cost allocation proposes the additional
    links; exact rational certification checks their simultaneous delivery.
    Physical belt/sorter capacities remain the final validator's obligation.
    Shared production and external input are allocated across treatment domains;
    only physical links, never those shared budgets, are domain-restricted.
    """
    total = sum(demand.values(), Fraction(0))
    if total == 0:
        return []
    lanes = sorted(set(supply) | set(demand) | {lane for pair in pairs for lane in pair})
    nodes = {lane: index + 1 for index, lane in enumerate(lanes)}
    groups = UnionFind()
    for a, b in shared_sources:
        groups.union(a, b)
    sources: dict[int, list[int]] = defaultdict(list)
    for lane in sorted(supply):
        sources[cast(int, groups.find(lane))].append(lane)
    arcs: list[physical_flow.Arc] = []
    next_node = len(nodes) + 1
    for members in sources.values():
        amount = sum((supply[lane] for lane in members), Fraction(0))
        if amount <= 0:
            continue
        gate = next_node
        next_node += 1
        arcs.append(physical_flow.Arc(0, gate, amount, "cargo"))
        arcs.extend(physical_flow.Arc(gate, nodes[lane], amount, "cargo") for lane in members)
    if external > 0:
        gate = next_node
        next_node += 1
        arcs.append(physical_flow.Arc(0, gate, external, "cargo"))
        arcs.extend(
            physical_flow.Arc(gate, nodes[lane], rate, "cargo")
            for lane, rate in demand.items()
            if rate > 0
        )
    linked = set(pairs)
    arcs.extend(physical_flow.Arc(nodes[a], nodes[b], total, "cargo") for a, b in sorted(linked))
    arcs.extend(
        physical_flow.Arc(nodes[lane], 0, rate, "cargo", rate) for lane, rate in demand.items()
    )
    fixed_count = len(arcs)
    taps: dict[int, int] = defaultdict(int)
    for a, b in pairs:
        taps[a] += 1
        taps[b] += 1
    candidates = [
        (a, b)
        for a in sorted(supply)
        for b in sorted(demand)
        if demand[b] > 0
        and a != b
        and (a, b) not in linked
        and (lane_domains is None or lane_domains[a] is lane_domains[b])
    ]
    arcs.extend(
        physical_flow.Arc(nodes[a], nodes[b], min(total, demand[b]), "cargo") for a, b in candidates
    )
    solver = pywraplp.Solver.CreateSolver("GLOP")
    if solver is None:
        raise RuntimeError("OR-Tools GLOP backend is unavailable")
    rows = [solver.Constraint(0, 0) for _ in range(next_node)]
    objective = solver.Objective()
    variables = []
    for index, arc in enumerate(arcs):
        variable = solver.NumVar(float(arc.lower), float(arc.capacity), "")
        variables.append(variable)
        if arc.source != arc.sink:
            rows[arc.source].SetCoefficient(variable, -1)
            rows[arc.sink].SetCoefficient(variable, 1)
        if index >= fixed_count:
            a, b = candidates[index - fixed_count]
            objective.SetCoefficient(variable, 1 + (taps[a] + taps[b]) / (1 + 4 * len(pairs)))
    objective.SetMinimization()
    if solver.Solve() != pywraplp.Solver.OPTIMAL:
        raise NoValidLayout(
            "native directed shard allocation did not produce a certifiable solution",
            stats={"termination_cause": "allocation-unproved"},
        )
    flows = _exact_shard_flows(arcs, variables, next_node)
    if flows is None:
        raise NoValidLayout(
            "directed shard allocation has no exact delivery certificate",
            stats={"termination_cause": "allocation-unproved"},
        )
    return [pair for index, pair in enumerate(candidates, fixed_count) if flows[index] > 0]


def _plan_shared_external_inputs(
    spec: BuildSpec,
    strips: Sequence[Strip],
    strip_in_ports: Sequence[Mapping[str, _Port]],
    per_item: Mapping[str, tuple[Mapping[str, Fraction], Mapping[str, Fraction]]],
) -> tuple[
    dict[int, tuple[_Port, int]],
    dict[int, str],
    tuple[tuple[str, CargoDomain, tuple[_Port, ...]], ...],
]:
    """Plan capacity-bounded boundary roots for otherwise identical bus lanes.

    Every consumer strip still owns its physical input lane.  When the URL's
    bus is stacked, identical external lanes may share one perimeter trunk while
    their combined item demand fits that feed.  Stack one deliberately keeps
    the historical one-boundary-feed-per-lane path byte-for-byte in shape.
    """
    lane_ports: dict[int, tuple[_Port, int]] = {}
    lane_items: dict[int, list[str]] = defaultdict(list)
    for strip_index, ports in enumerate(strip_in_ports):
        for item, port in sorted(ports.items()):
            if item not in spec.external_inputs:
                continue
            lane_ports.setdefault(port.belt, (port, strip_index))
            lane_items[port.belt].append(item)

    carried_by_belt = {belt: min(items) for belt, items in lane_items.items()}
    if spec.belt_stack == 1:
        return lane_ports, carried_by_belt, ()

    produced_items = {item for group in spec.groups for item in group.outputs_per_machine}
    by_signature: dict[
        tuple[tuple[str, ...], CargoDomain],
        list[tuple[_Port, int]],
    ] = defaultdict(list)
    for belt, (port, strip_index) in lane_ports.items():
        items = tuple(sorted(set(lane_items[belt])))
        by_signature[items, port.cargo_domain].append((port, strip_index))

    roots: dict[int, tuple[_Port, int]] = {}
    carried: dict[int, str] = {}
    sharing: list[tuple[str, CargoDomain, tuple[_Port, ...]]] = []

    def commit_group(
        lanes: Sequence[tuple[_Port, int]],
        items: tuple[str, ...],
        cargo_domain: CargoDomain,
    ) -> None:
        if len(lanes) == 1:
            root, root_strip = lanes[0]
            roots[root.belt] = (root, root_strip)
            carried[root.belt] = items[0]
            return
        sharing.append(
            (
                items[0],
                cargo_domain,
                tuple(port for port, _strip_index in lanes),
            )
        )

    def commit_capacity_group(
        lanes: Sequence[tuple[_Port, int]],
        load: Fraction,
        items: tuple[str, ...],
        cargo_domain: CargoDomain,
    ) -> None:
        # Deliverable B changes only lanes whose multiplicity came from the
        # unstacked belt ceiling.  A pair that already fit at stack one was
        # seated separately for geometry, so stacking must not merge it as a
        # side effect (super-magnetic-ring in the deuteron build is the guard).
        if load <= spec.lane_capacity:
            for lane in lanes:
                commit_group((lane,), items, cargo_domain)
            return
        commit_group(lanes, items, cargo_domain)

    for (items, cargo_domain), lanes in sorted(
        by_signature.items(),
        key=lambda entry: (entry[0][0], entry[0][1].value),
    ):
        ordered = sorted(lanes, key=lambda lane: lane[0].belt)
        # A bus-plus-producer lane has two independent sources.  Its sharing
        # topology is governed by the internal producer allocation, not solely
        # by external capacity, so retain the established per-lane roots.
        if any(item in produced_items for item in items):
            for lane in ordered:
                commit_group((lane,), items, cargo_domain)
            continue

        capacity = spec.lane_capacity * min(
            spec.planning_stack(item, external=True) for item in items
        )
        group: list[tuple[_Port, int]] = []
        load = Fraction(0)
        for lane in ordered:
            port, strip_index = lane
            strip = strips[strip_index]
            input_rates = per_item.get(strip.group_key, ({}, {}))[0]
            demand = strip.machines * sum(
                (input_rates.get(item, Fraction(0)) for item in items),
                Fraction(0),
            )
            if group and load + demand > capacity:
                commit_capacity_group(group, load, items, cargo_domain)
                group = []
                load = Fraction(0)
            group.append((port, strip_index))
            load += demand
        if group:
            commit_capacity_group(group, load, items, cargo_domain)

    return roots, carried, tuple(sharing)


# Ground-level taps use model 38 at yaw 0.  Its exact collider overlaps another
# model 38 one plan tile away and clears it at two; the three-destination commit
# regression checks both predicates through ``junction_is_clear``.
_SHARED_EXTERNAL_TAP_SPACING = 2


def _place_shared_external_input_trunks(
    canvas: _Canvas,
    groups: Sequence[tuple[str, CargoDomain, tuple[_Port, ...]]],
    *,
    belt_id: int,
    belt_model: int,
    bounds: tuple[int, int, int, int],
) -> tuple[tuple[_Net, ...], tuple[tuple[str, _Port], ...]]:
    """Place one perimeter distribution run for each shared bus group."""
    min_x, min_y, max_x, max_y = bounds
    sides = (
        tuple((x, min_y, 0) for x in range(min_x, max_x + 1)),
        tuple((max_x, y, 0) for y in range(min_y + 1, max_y + 1)),
        tuple((x, max_y, 0) for x in range(max_x - 1, min_x - 1, -1)),
        tuple((min_x, y, 0) for y in range(max_y - 1, min_y, -1)),
    )
    nets: list[_Net] = []
    roots: list[tuple[str, _Port]] = []
    for item, cargo_domain, destinations in groups:
        tap_span = 1 + (len(destinations) - 1) * _SHARED_EXTERNAL_TAP_SPACING
        segment = next(
            (
                side[start : start + tap_span]
                for side in sides
                for start in range(len(side) - tap_span + 1)
                if all(canvas.free(cell) for cell in side[start : start + tap_span])
            ),
            None,
        )
        if segment is None:
            raise _Unseatable(
                f"no {tap_span}-tile perimeter trunk fits the shared external input {item!r}"
            )

        indices = [
            canvas.add(
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
            for x, y, level in segment
        ]
        for source_index, destination_index in zip(indices, indices[1:], strict=False):
            canvas.buildings[source_index] = _relink(
                canvas.buildings[source_index],
                output_obj=destination_index,
            )
        ports = tuple(
            _Port(
                index,
                x,
                y,
                x,
                x,
                (index,),
                cargo_domain=cargo_domain,
                supply_root_belt=indices[0],
            )
            for index, (x, y, _level) in zip(
                indices[::_SHARED_EXTERNAL_TAP_SPACING],
                segment[::_SHARED_EXTERNAL_TAP_SPACING],
                strict=True,
            )
        )
        roots.append((item, ports[0]))
        for source, destination in zip(ports, destinations, strict=True):
            nets.append(
                _Net(
                    src=source,
                    dst=destination,
                    item=item,
                    cargo_domain=cargo_domain,
                )
            )
    return tuple(nets), tuple(roots)


@dataclass(frozen=True, slots=True)
class _RoutingInventory:
    """Fixed geometry and exact material obligations before access admission."""

    belt_id: int
    belt_model: int
    canvas: _Canvas
    sorters: int
    strip_in_ports: list[dict[str, _Port]]
    strip_of_belt: dict[int, int]
    nets: list[_Net]
    piler_nets: list[_Net]
    wanted: dict[int, tuple[_Port, int]]
    carried: dict[int, str]
    shared_external_groups: tuple[tuple[str, CargoDomain, tuple[_Port, ...]], ...]
    wanted_outputs: dict[int, tuple[str, _Port]]
    promised_direct: frozenset[DirectInsertId]
    realized_direct: set[DirectInsertId]


def _prepare_transport_inventory(
    spec: BuildSpec,
    strips: list[Strip],
    pack: _Pack,
    *,
    belt_rules: catalog.BeltAltitudeRules = _DEFAULT_BELT_RULES,
    cancelled: Callable[[], bool] | None = None,
    coater_node_sites: Mapping[tuple[int, str], tuple[int, int]] | None = None,
    coater_envelope: finalize.BandPolicySearchEnvelope | None = None,
) -> _RoutingInventory:
    """Share physical emission and directed producer allocation across routers.

    A real packed scene supplies ``coater_envelope`` before automatic node
    placement. Native template inventories instead supply explicit node sites
    on a disjoint capture canvas; their final frame is chosen at composition.
    """
    belt_id = catalog.get_item_id(spec.belt_item_id) or 2001
    belt_model = catalog.building(belt_id).model_index
    power_building = catalog.power_tower_building(spec.power_tower_item_id)
    canvas = _Canvas(
        belt_rules=belt_rules,
        sorter_tiers=_sorter_tiers_for(spec),
        sorter_stacks=_sorter_stacks_for(spec),
        lane_stacks=_lane_stacks_for(spec),
        power_building=power_building,
    )
    if cancelled is not None and cancelled():
        raise _PreparationDeadline

    groups = _adapt(spec)
    lane_owners, merge_plans = _strip_merge_plans(spec, groups, strips)
    piled_lane_ids = {
        lane_id
        for lane_id, (strip_ordinal, lane_index) in lane_owners.items()
        if _piler_plan_for_output(strips[strip_ordinal], lane_index) is not None
    }
    merge_plans = {
        key: plan
        for key, plan in merge_plans.items()
        if any(lane_id in piled_lane_ids for group in plan.groups for lane_id in group)
    }
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
    # One physical producer budget per item, shared by all its output lanes.
    # Cargo domains constrain transport links, not how that producer's output
    # is allocated. Splitting its rate by downstream demand before allocation
    # can strand surplus in one domain while another domain starves.
    lane_of: dict[int, _Port] = {}
    lane_supply: dict[str, dict[int, Fraction]] = defaultdict(dict)
    lane_demand: dict[str, dict[int, Fraction]] = defaultdict(dict)
    sibling_lanes: dict[str, list[tuple[int, int]]] = defaultdict(list)
    strip_of_belt: dict[int, int] = {}
    output_lane_id_by_belt: dict[int, str] = {}
    piler_nets: list[_Net] = []
    sorters = 0
    for i, s in enumerate(strips):
        if cancelled is not None and cancelled():
            raise _PreparationDeadline
        ox, oy = pack.at[i]
        ins, outs, placed, strip_piler_nets = _emit_strip(
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
        piler_nets.extend(strip_piler_nets)
        sorters += placed
        strip_in_ports.append(ins)
        for port in (*ins.values(), *outs.values()):
            for belt in port.tiles:
                strip_of_belt[belt] = i
        for net in strip_piler_nets:
            strip_of_belt[net.source.belt] = i
            strip_of_belt[net.dst.belt] = i
        for item, port in ins.items():
            in_ports[s.group_key, item, port.cargo_domain].append(port)
        for lane_index, (item, destination, cargo_domain) in enumerate(s.out_lanes):
            port = outs[item, destination, cargo_domain]
            output_lane_id_by_belt[port.belt] = f"{i}:{_strip_output_lane_id(s, lane_index)}"
        made = per_item.get(s.group_key, ({}, {}))[1]
        by_item: dict[str, list[int]] = defaultdict(list)
        for (item, dest, cargo_domain), port in outs.items():
            out_ports[s.group_key, item, dest, cargo_domain].append(port)
            lane_of[port.belt] = port
            by_item[item].append(port.belt)
        for item, item_belts in by_item.items():
            belts = sorted(item_belts)
            lane_supply[item][belts[0]] = s.machines * made.get(item, Fraction(0))
            for belt in belts[1:]:
                lane_supply[item][belt] = Fraction(0)
                sibling_lanes[item].append((belts[0], belt))
    if cancelled is not None and cancelled():
        raise _PreparationDeadline

    # The Spray Coater as a real node (``FLAB2BP_COATER_NODE=placed``, the
    # default; ``off`` is the one-release A/B control).
    #
    # One node per sprayed input lane -- a five-tile belt run with the addon on
    # its third tile (see `_COATER_NODE_TILES`) -- emitted here and then seated
    # by the ORDINARY `_place_coaters` machinery below, which is the whole
    # reason the node is shaped like a lane: every keepout, projected-static,
    # addon-supply and splitter check that governs a coater on a strip channel
    # governs it here unchanged.
    #
    # Two rewirings make it a node rather than a decoration:
    #
    #   * every producer net and every external-input run that used to sink
    #     into the CONSUMER lane's head now sinks into the node's IN-PORT --
    #     which is where merges belong, and where they now land by
    #     construction rather than by a seat-index argument;
    #   * one new net carries the node's OUT-PORT to the consumer lane head,
    #     which is an ordinary unsprayed lane geometrically: no widened
    #     channel, no prepended head, no coater keep-out, no west-channel lift.
    #
    # `placed` searches free ground beside the lane head after the pack, so the
    # packer is untouched and only the router sees the extra net.
    coater_node_links: list[tuple[str, _Port, _Port]] = []
    if coater_mode().is_node:
        node_core = _core_bounds(canvas)
        for strip_index, s in enumerate(strips):
            if s.cargo_domain is not CargoDomain.REQUIRES_SPRAY:
                continue
            for item in dict.fromkeys(s.in_lanes):
                consumer_port = strip_in_ports[strip_index].get(item)
                if consumer_port is None:
                    continue
                site = (
                    _coater_node_site(
                        canvas,
                        (consumer_port.x, consumer_port.y),
                        core=node_core,
                        envelope=coater_envelope,
                    )
                    if coater_node_sites is None
                    else coater_node_sites.get((strip_index, item))
                )
                if (
                    site is not None
                    and coater_node_sites is not None
                    and not _coater_node_site_is_clear(canvas, *site)
                ):
                    site = None
                if site is None:
                    raise _Unseatable(
                        f"no free ground for the {item} Spray Coater node near "
                        f"the lane head at ({consumer_port.x}, {consumer_port.y})"
                    )
                node_in, node_out = _emit_coater_node(
                    canvas,
                    site[0],
                    site[1],
                    item=item,
                    belt_id=belt_id,
                    belt_model=belt_model,
                    machines=consumer_port.machines,
                    owner_strip=strip_index,
                )
                node_core = (
                    min(node_core[0], site[0]),
                    min(node_core[1], site[1] - 1),
                    max(node_core[2], site[0] + _COATER_NODE_TILES - 1),
                    max(node_core[3], site[1]),
                )
                for belt in node_in.tiles:
                    strip_of_belt[belt] = strip_index
                # The node becomes the sink every producer and every external
                # run aims at.  The consumer's own head keeps its role as the
                # lane the sorters draw from, and is fed by the node.
                strip_in_ports[strip_index][item] = node_in
                for key, ports in list(in_ports.items()):
                    if key[0] != s.group_key or key[1] != item:
                        continue
                    in_ports[key] = [
                        node_in if port.belt == consumer_port.belt else port for port in ports
                    ]
                coater_node_links.append((item, node_out, consumer_port))
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
    joined: dict[str, list[tuple[int, int]]] = defaultdict(list)
    # Every sorter already standing, as the PASTE will test it.  Built once and
    # extended by each bridge that lands: `_bridge` is asked once per lane pair
    # and rebuilding this inside it is quadratic in the sorter count, which on a
    # stress spec is thousands.
    standing = slots.sorter_seat_boxes(canvas.buildings)

    def connect_lanes(
        port: _Port,
        sink: _Port,
        item: str,
        cargo_domain: CargoDomain,
        in_rate: Fraction,
    ) -> None:
        """Record one physical producer-to-consumer connection."""
        joined[item].append((port.belt, sink.belt))
        lane_of[sink.belt] = sink
        required_rate = sink.machines * in_rate
        lane_demand[item][sink.belt] = required_rate
        direct_id = DirectInsertId(
            source_strip=strip_of_belt[port.belt],
            destination_strip=strip_of_belt[sink.belt],
            item=item,
            cargo_domain=cargo_domain,
        )
        if direct_id in promised_direct:
            source_strip = strips[direct_id.source_strip]
            source_rate = per_item.get(source_strip.group_key, ({}, {}))[1].get(
                item,
                Fraction(0),
            )
            realized = _bridge(
                canvas,
                port,
                sink,
                rates,
                item,
                standing,
                direct_id,
                source_rate=source_rate,
                required_rate=required_rate,
            )
            if realized is not None:
                realized_direct.add(realized)
            # A failed rewarded bridge is a failed attempt, not a licence
            # to restore the net the objective was paid to delete.
            return
        nets.append(
            _Net(
                src=port,
                dst=sink,
                item=item,
                cargo_domain=cargo_domain,
            )
        )

    for (src_key, item, dest_group, cargo_domain), srcs in out_ports.items():
        if cancelled is not None and cancelled():
            raise _PreparationDeadline
        # One output lane may serve SEVERAL destination groups -- see
        # `_merge_lanes` -- and each of them is its own set of consumer strips to
        # pair against. Domain is part of the key, so a clean and a sprayed lane
        # can never become siblings merely because they carry the same item.
        out_rate = per_item.get(src_key, ({}, {}))[1].get(item, Fraction(0))
        for dest in _dests(dest_group):
            if (item, dest, cargo_domain) in merge_plans:
                continue
            sinks = in_ports.get((dest, item, cargo_domain), [])
            if not srcs or not sinks:
                continue
            in_rate = per_item.get(dest, ({}, {}))[0].get(item, Fraction(0))
            for port, sink in _pair_lanes(srcs, sinks, out_rate=out_rate, in_rate=in_rate):
                connect_lanes(port, sink, item, cargo_domain, in_rate)

    # Piler planning is global to one (item, sink, domain), while ``out_ports``
    # is partitioned by producer group. Rebuild the same plan from these exact
    # physical strips and consume its contiguous groups before choosing sink
    # lanes; pairing each producer independently would turn {0,1,2}/{3} into
    # the old cyclic {0,2}/{1,3}.
    merge_sources: dict[tuple[str, CargoDomain], list[tuple[str, list[_Port]]]] = defaultdict(list)
    for (_src_key, item, destinations, cargo_domain), sources in out_ports.items():
        merge_sources[item, cargo_domain].append((destinations, sources))

    boundary_output_belts: set[int] = set()
    for (item, dest, cargo_domain), merge_plan in merge_plans.items():
        sources_by_lane: dict[str, _Port] = {}
        for destinations, sources in merge_sources.get((item, cargo_domain), ()):
            if dest not in (_dests(destinations) or ("",)):
                continue
            for source in sources:
                sources_by_lane[output_lane_id_by_belt[source.belt]] = source

        source_groups = tuple(
            tuple(sources_by_lane[lane_id] for lane_id in lane_ids)
            for lane_ids in merge_plan.groups
        )
        if not dest:
            for source_group in source_groups:
                root = source_group[0]
                boundary_output_belts.add(root.belt)
                for tributary in source_group[1:]:
                    joined[item].append((tributary.belt, root.belt))
                    nets.append(
                        _Net(
                            src=tributary,
                            dst=root,
                            item=item,
                            cargo_domain=cargo_domain,
                        )
                    )
            continue

        sinks = in_ports.get((dest, item, cargo_domain), [])
        if not sinks:
            continue
        in_rate = per_item.get(dest, ({}, {}))[0].get(item, Fraction(0))
        pairs = [
            (source, sinks[group_index % len(sinks)])
            for group_index, source_group in enumerate(source_groups)
            for source in source_group
        ]
        # A consumer may be sharded more finely than the capacity-safe producer
        # groups. Keep every group intact, then reuse one representative only
        # for otherwise-unfed sink lanes.
        for sink_index in range(len(source_groups), len(sinks)):
            source_group = source_groups[sink_index % len(source_groups)]
            source = source_group[(sink_index // len(source_groups)) % len(source_group)]
            pairs.append((source, sinks[sink_index]))
        for port, sink in pairs:
            connect_lanes(port, sink, item, cargo_domain, in_rate)
    if cancelled is not None and cancelled():
        raise _PreparationDeadline

    lane_domains = {belt: port.cargo_domain for belt, port in lane_of.items()}
    for item in sorted(set(joined) | set(sibling_lanes)):
        if cancelled is not None and cancelled():
            raise _PreparationDeadline
        for a, b in _join_shard_islands(
            joined[item],
            lane_supply[item],
            lane_demand[item],
            spec.external_inputs.get(item, Fraction(0)),
            shared_sources=sibling_lanes[item],
            lane_domains=lane_domains,
        ):
            nets.append(
                _Net(
                    src=lane_of[a],
                    dst=lane_of[b],
                    item=item,
                    cargo_domain=lane_domains[a],
                )
            )
    # EXPERIMENT: the node's own out-net.  Appended AFTER `_join_shard_islands`
    # so the island analysis keeps seeing the flow graph it was built for: the
    # node is transparent to supply and demand, which are still credited to the
    # in-port (it carries the consumer's `machines`) and the producer lanes.
    for node_item, node_out, node_sink in coater_node_links:
        nets.append(
            _Net(
                src=node_out,
                dst=node_sink,
                item=node_item,
                cargo_domain=CargoDomain.REQUIRES_SPRAY,
            )
        )
    wanted, carried, shared_external_groups = _plan_shared_external_inputs(
        spec,
        strips,
        strip_in_ports,
        per_item,
    )
    if cancelled is not None and cancelled():
        raise _PreparationDeadline
    requested_outputs = set(spec.outputs) | set(spec.surplus_outputs)
    wanted_outputs: dict[int, tuple[str, _Port]] = {}
    for (
        _group_key,
        output_item,
        destination,
        cargo_domain,
    ), output_ports in out_ports.items():
        output_destinations = _dests(destination)
        if output_item not in requested_outputs or (destination and "" not in output_destinations):
            continue
        boundary_plan = merge_plans.get((output_item, "", cargo_domain))
        for output_port in output_ports:
            if boundary_plan is not None and output_port.belt not in boundary_output_belts:
                continue
            wanted_outputs.setdefault(
                output_port.belt,
                (output_item, output_port),
            )
    if cancelled is not None and cancelled():
        raise _PreparationDeadline
    return _RoutingInventory(
        belt_id=belt_id,
        belt_model=belt_model,
        canvas=canvas,
        sorters=sorters,
        strip_in_ports=strip_in_ports,
        strip_of_belt=strip_of_belt,
        nets=nets,
        piler_nets=piler_nets,
        wanted=wanted,
        carried=carried,
        shared_external_groups=shared_external_groups,
        wanted_outputs=wanted_outputs,
        promised_direct=promised_direct,
        realized_direct=realized_direct,
    )


def _prepare_routing_problem(
    spec: BuildSpec,
    strips: list[Strip],
    pack: _Pack,
    *,
    power: bool,
    policy: BandPolicy,
    belt_rules: catalog.BeltAltitudeRules = _DEFAULT_BELT_RULES,
    _reserve_ports: bool = True,
    staged_static_cache: _StagedStaticCache | None = None,
    cancelled: Callable[[], bool] | None = None,
    deadline: float | None = None,
) -> _PreparedRoutingProblem:
    """Build immutable exact geometry shared by both routing engines."""
    if staged_static_cache is None:
        staged_static_cache = _StagedStaticCache()
    envelope = finalize.band_policy_search_envelope(policy, perimeter=_ENTRY_RING)
    inventory = _prepare_transport_inventory(
        spec,
        strips,
        pack,
        belt_rules=belt_rules,
        cancelled=cancelled,
        coater_envelope=envelope,
    )
    belt_id = inventory.belt_id
    belt_model = inventory.belt_model
    canvas = inventory.canvas
    sorters = inventory.sorters
    strip_in_ports = inventory.strip_in_ports
    strip_of_belt = inventory.strip_of_belt
    nets = inventory.nets
    piler_nets = inventory.piler_nets
    wanted = inventory.wanted
    carried = inventory.carried
    shared_external_groups = inventory.shared_external_groups
    wanted_outputs = inventory.wanted_outputs
    promised_direct = inventory.promised_direct
    realized_direct = inventory.realized_direct

    # Hold one cell beside every port BEFORE anything else can take it.
    #
    # Coater drop belts and external input runs are placed onto a canvas that is
    # otherwise empty, so they take whatever cell suits them -- and a lane head's
    # only free neighbour is exactly the sort of cell that suits them. The net
    # that needed it is then handed an EMPTY goal set: A* returns None having
    # expanded nothing, and no amount of rip-up can negotiate for a cell that is
    # occupied by a building rather than contested by another path.
    #
    internal_source_belts = {
        net.source.belt for net in (*nets, *piler_nets) if net.src is not None and not net.prelinked
    }
    late_output_belts = frozenset(wanted_outputs) & internal_source_belts
    provisional_boundary_inputs: list[tuple[str, _Port, int | None]] = [
        (carried[belt], port, strip_index) for belt, (port, strip_index) in wanted.items()
    ]
    provisional_boundary_inputs.extend(
        (item, port, strip_of_belt.get(port.belt))
        for item, _cargo_domain, ports in shared_external_groups
        for port in ports
    )
    port_access_inventory = _port_access_inventory(
        (*nets, *piler_nets),
        boundary_inputs=tuple(provisional_boundary_inputs),
        boundary_outputs=tuple(wanted_outputs.values()),
        late_output_belts=late_output_belts,
        strip_of_belt=strip_of_belt,
    )
    stranded_ports: list[StrandedPort] = []
    access_reservation = PortAccessReservation((), (), ())

    def hold_ports(
        inventory: PortAccessInventory,
        *,
        boundary_cells: Sequence[Cell] | None = None,
        routing_bounds: tuple[int, int, int, int] | None = None,
    ) -> PortAccessReservation:
        reservation = _reserve_port_access(
            canvas,
            inventory.demands,
            boundary=boundary_cells,
            bounds=routing_bounds,
            cancelled=cancelled,
            deadline=deadline,
        )
        stranded_ports.clear()
        for evidence in reservation.evidence:
            demand = evidence.demand
            strip_index = demand.strip_index
            if strip_index is None or not 0 <= strip_index < len(strips):
                strip_label = "?"
                instance_id = StripInstanceId(StripFamilyId("?", 0), 0, 1)
            else:
                strip = strips[strip_index]
                strip_label = strip.sid
                family_id = strip.family_id or StripFamilyId(strip.group_key, 0)
                instance_id = StripInstanceId(
                    family_id,
                    strip.machine_start,
                    strip.machines,
                )
            lane_id = "?"
            if strip_index is not None and 0 <= strip_index < len(strip_in_ports):
                strip = strips[strip_index]
                for item, port in strip_in_ports[strip_index].items():
                    if port.belt != demand.belt:
                        continue
                    lane_id = next(
                        (
                            plan.lane.lane_id
                            for plan in strip.attachment_plan
                            if plan.lane.kind == "input" and item in plan.lane.items
                        ),
                        "?",
                    )
                    break
            stranded_ports.append(
                StrandedPort(
                    cell=demand.cell,
                    item=demand.item,
                    strip_label=strip_label,
                    instance_id=instance_id,
                    lane_id=lane_id,
                    held=evidence.held,
                    wants=evidence.wanted,
                    options=evidence.local_options,
                )
            )
        return reservation

    if _reserve_ports:
        access_reservation = hold_ports(port_access_inventory)
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

    # Build proliferator sources on the fixed perimeter, then reserve their
    # access before shared external trunks can occupy an inward approach.
    net_roles = [NetRole.INTERNAL] * len(nets)
    if coater_list and prolif_item is not None:
        entry = _place_proliferator_entry(canvas, prolif_item, belt_id, belt_model, core)
        if entry is not None:
            proliferator_nets = _proliferator_supply_tree(
                canvas,
                entry,
                coater_list,
                prolif_item,
                belt_id=belt_id,
                belt_model=belt_model,
                core=core,
            )
            nets.extend(proliferator_nets)
            net_roles.extend([NetRole.PROLIFERATOR] * len(proliferator_nets))

    if _reserve_ports and shared_external_groups:
        port_access_inventory = _port_access_inventory(
            (*nets, *piler_nets),
            boundary_inputs=tuple(provisional_boundary_inputs),
            boundary_outputs=tuple(wanted_outputs.values()),
            late_output_belts=late_output_belts,
            strip_of_belt=strip_of_belt,
        )
        access_reservation = hold_ports(port_access_inventory, routing_bounds=capacity)

    shared_external_nets, shared_external_roots = _place_shared_external_input_trunks(
        canvas,
        shared_external_groups,
        belt_id=belt_id,
        belt_model=belt_model,
        bounds=route_bounds,
    )
    nets.extend(shared_external_nets)
    net_roles.extend([NetRole.INTERNAL] * len(shared_external_nets))
    for item, port in shared_external_roots:
        wanted[port.belt] = (port, -1)
        carried[port.belt] = item
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

    nets.extend(piler_nets)
    net_roles.extend([NetRole.INTERNAL] * len(piler_nets))
    shared_boundary_root_belts = frozenset(port.belt for _item, port in shared_external_roots)
    port_access_inventory = _port_access_inventory(
        nets,
        boundary_inputs=tuple(
            (carried[belt], port, strip_index) for belt, (port, strip_index) in wanted.items()
        ),
        boundary_outputs=tuple(wanted_outputs.values()),
        late_output_belts=late_output_belts,
        shared_boundary_root_belts=shared_boundary_root_belts,
        strip_of_belt=strip_of_belt,
    )
    # Again, now that every port exists -- strip lanes, coater drops,
    # proliferator trunks, and shared external-input trunks alike.
    if _reserve_ports:
        access_reservation = hold_ports(
            port_access_inventory,
            boundary_cells=boundary,
            routing_bounds=capacity,
        )
    if cancelled is not None and cancelled():
        raise _PreparationDeadline

    # The stack-aware sharing plan has reduced ``wanted`` to unshared roots;
    # shared groups already have one zero-predecessor perimeter trunk each.

    # ``boundary`` was frozen before the final access rematch so both
    # preparation and the boundary router prove reachability to the same cells.

    tagged_nets = list(zip(nets, net_roles, strict=True))
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
    late_output_net_ids: set[NetId] = set()
    for net, role in tagged_nets:
        if cancelled is not None and cancelled():
            raise _PreparationDeadline
        source_strip = strip_of_belt.get(net.src.belt) if net.src is not None else None
        destination_strip = (
            None if role is NetRole.EXTERNAL_OUTPUT else strip_of_belt.get(net.dst.belt)
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
                boundary if role in (NetRole.EXTERNAL, NetRole.EXTERNAL_OUTPUT) else ()
            ),
            prelinked=net.prelinked,
        )
        if role is NetRole.EXTERNAL_OUTPUT:
            prepared_output_nets.append(prepared)
            if net.source.belt in port_access_inventory.late_output_belts:
                late_output_net_ids.add(net_id)
        else:
            prepared_nets.append(prepared)
    if cancelled is not None and cancelled():
        raise _PreparationDeadline

    def prepared_endpoints(
        prepared: _PreparedNet,
    ) -> tuple[Cell | None, Cell]:
        source = None if prepared.src is None else (prepared.src.x, prepared.src.y, prepared.src.z)
        return source, (prepared.dst.x, prepared.dst.y, prepared.dst.z)

    all_prepared_nets = tuple(
        prepared for prepared in (*prepared_nets, *prepared_output_nets) if not prepared.prelinked
    )

    def demand_rows() -> Iterator[tuple[NetId, str, str, Cell, str, _PreparedNet]]:
        for prepared in all_prepared_nets:
            source, destination = prepared_endpoints(prepared)
            net_id = prepared.net_id
            if net_id.role is NetRole.EXTERNAL:
                yield (
                    net_id,
                    net_id.item,
                    PortAccessKind.BOUNDARY_ARRIVAL.value,
                    destination,
                    "dst",
                    prepared,
                )
            elif net_id.role is NetRole.EXTERNAL_OUTPUT:
                yield (
                    net_id,
                    net_id.item,
                    PortAccessKind.EARLY_BOUNDARY_DEPARTURE.value if source is not None else "",
                    source if source is not None else destination,
                    "src",
                    prepared,
                )
            else:
                if source is not None:
                    yield (
                        net_id,
                        net_id.item,
                        PortAccessKind.INTERNAL_DEPARTURE.value,
                        source,
                        "src",
                        prepared,
                    )
                yield (
                    net_id,
                    net_id.item,
                    PortAccessKind.INTERNAL_ARRIVAL.value,
                    destination,
                    "dst",
                    prepared,
                )

    net_index = Nets.of(demand_rows())

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
                prepared_endpoints(cast(_PreparedNet, net_index.by_id(blocker)))
                for blocker in blocking_nets
            ),
        )

    preparation_failures = tuple(
        static_access_failure(prepared, demand.cell)
        for demand in access_reservation.missing
        for prepared in (
            next(
                iter(net_index.matching_demand(demand.item, demand.kind.value, demand.cell)), None
            ),
        )
        if prepared is not None
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
                if not net.prelinked
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
    routed_prepared_nets = tuple(net for net in prepared_nets if not net.prelinked)
    grouped_routed_nets = _with_sibling_groups(routed_prepared_nets)
    grouped_nets = (
        *grouped_routed_nets,
        *(net for net in prepared_nets if net.prelinked),
    )
    # Retain the reusable flat source-stack bans for branching lanes and
    # reserved power sites. Every workspace also gets the lazy model/yaw-aware
    # projection owner below: singleton nets can still introduce connectors,
    # and their geometry must include the same reserved towers and coaters.
    output_source_belts = {
        net.src.belt_index for net in prepared_output_nets if net.src is not None
    }
    shared_boundary_output = any(
        net.src is not None and net.src.belt_index in output_source_belts
        for net in grouped_routed_nets
    )
    junction_possible = not preparation_failures and (
        _junction_geometry_required(grouped_routed_nets, canvas.buildings) or shared_boundary_output
    )
    if cancelled is not None and cancelled():
        raise _PreparationDeadline
    junction_ban = (
        _prepared_junction_ban(
            canvas.buildings,
            power_sites,
            cancelled=cancelled,
            cache=staged_static_cache,
            tower=canvas.power_building,
            belt_rules=canvas.belt_rules,
        )
        if junction_possible or power_sites
        else frozenset()
    )
    projection = _CompositionProjection(
        canvas.buildings,
        capacity,
        policy,
        belt_rules=canvas.belt_rules,
        power_sites=power_sites,
        tower=canvas.power_building,
        cancelled=cancelled,
    )
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
        port_access_demands=port_access_inventory.demands,
        late_output_net_ids=frozenset(late_output_net_ids),
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
        belt_rules=canvas.belt_rules,
        sorter_tiers=canvas.sorter_tiers,
        sorter_stacks=canvas.sorter_stacks,
        lane_stacks=canvas.lane_stacks,
        power_building=canvas.power_building,
        world_taken=frozenset(canvas.world_taken),
        belt_ban=tuple(
            sorted((cell, frozenset(levels)) for cell, levels in canvas.belt_ban.items())
        ),
        preparation_exhaustive=(
            bool(access_reservation.missing)
            and not (promised_direct - realized_direct)
            and all(evidence.exhaustive for evidence in access_reservation.evidence)
        ),
        junction_ban=junction_ban,
        projection_policy=policy,
        junction_projection=projection,
        preparation_failures=preparation_failures,
        stranded_ports=tuple(stranded_ports),
    )


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
    #: Stable physical strip range; unlike coordinates it survives repacking.
    instance_id: StripInstanceId
    #: Placement-independent lane identity within ``instance_id``.
    lane_id: str
    #: Corridors the matching actually reserved for this port.
    held: int
    #: Corridors it needed: one per role, plus one when the port is in ``twice``.
    wants: int
    #: Free 4-neighbours the port had to build a corridor from.  ``1`` is the
    #: signature of a middle lane head and is not a matching failure -- there is
    #: nothing to match.
    options: int


def _bridge(
    canvas: _Canvas,
    src: _Port,
    dst: _Port,
    rates: dict[str, Fraction],
    item: str,
    standing: list[colliders.Box],
    direct_id: DirectInsertId,
    *,
    source_rate: Fraction,
    required_rate: Fraction,
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

    Flow order is the independent precondition.  The bridge must draw strictly
    after enough emitted source injections to cover ``required_rate`` and land
    strictly before every emitted pickup from its destination lane.  Waiting
    for later source surplus needlessly destroys compact valid alignments.
    Candidate geometry proves the same rate bound from the strip plan; repeating
    it from the emitted object links keeps a stale plan or emission drift from
    turning a rewarded bridge into starvation.
    """
    if (
        src.cargo_domain is not CargoDomain.UNSPRAYED
        or dst.cargo_domain is not CargoDomain.UNSPRAYED
    ):
        return None
    span = dst.y - src.y
    if span < 1 or span > catalog.SORTER_MAX_REACH:
        return None

    buildings = canvas.buildings
    source_tiles = set(src.tiles)
    destination_tiles = set(dst.tiles)

    def is_machine(index: int) -> bool:
        building = buildings.by_index(index)
        if building is None:
            return False
        return (
            building.owner_strip is not None
            and not catalog.is_belt(building.item_id)
            and not catalog.is_sorter(building.item_id)
            and (building.recipe_id not in (None, 0) or bool(building.parameters))
        )

    source_injections = [
        buildings[target].x
        for target in source_tiles
        for sorter_index in buildings.sorters_into(target)
        if (origin := buildings[sorter_index].input_obj) is not None and is_machine(origin)
    ]
    destination_pickups = [
        buildings[source].x
        for source in destination_tiles
        for sorter_index in buildings.sorters_out_of(source)
        if (target := buildings[sorter_index].output_obj) is not None and is_machine(target)
    ]
    # Port-driven machines attach directly to a belt rather than through a
    # sorter.  Direct candidates currently exclude port-driven sources, but
    # reading both shapes here makes the emission guard describe the placement
    # rather than that candidate-filter convention.
    source_injections.extend(
        buildings[index].x
        for index in source_tiles
        if (peer := buildings[index].input_obj) is not None and is_machine(peer)
    )
    destination_pickups.extend(
        buildings[index].x
        for index in destination_tiles
        if (peer := buildings[index].output_obj) is not None and is_machine(peer)
    )
    if source_rate <= 0 or required_rate <= 0:
        return None
    source_machines_needed = math.ceil(required_rate / source_rate)
    source_injections.sort()
    if len(source_injections) < source_machines_needed:
        return None
    last_source_injection = source_injections[source_machines_needed - 1]
    first_destination_pickup = min(destination_pickups, default=None)

    # A bridge is belt-to-belt: it picks the source lane's cargo and places it
    # on the destination lane, so it keeps a promise at BOTH ends -- the entry
    # lane's on the way in and the output lane's on the way out.
    tier, _ = _pick_sorter(
        rates.get(item, Fraction(1)),
        span,
        1,
        canvas.sorter_tiers,
        stacks=canvas.sorter_stacks,
        min_pick_stack=canvas.lane_stacks.into(item),
        min_place_stack=canvas.lane_stacks.out_of(item),
    )
    for column in range(max(src.x0, dst.x0), min(src.x1, dst.x1) + 1):
        if column <= last_source_injection:
            continue
        if first_destination_pickup is not None and column >= first_destination_pickup:
            continue
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


#: Five belt tiles, west to east: input, rear body, seat, front body, output.
#: BOTH routing ports must be outside the three-tile body. The game checks the
#: neighbors of every overlapping existing belt, not just the belt at the seat
#: (BuildTool_BlueprintPaste.cs:145813-145853). Ending at the front body tile
#: lets the router put a corner under the coater.
_COATER_NODE_TILES = 5


def _emit_coater_node(
    canvas: _Canvas,
    ox: int,
    oy: int,
    *,
    item: str,
    belt_id: int,
    belt_model: int,
    machines: int,
    owner_strip: int | None,
) -> tuple[_Port, _Port]:
    """Lay one packed Spray Coater node's belt run and return its two ports.

    The coater itself is NOT placed here: ``_place_coaters`` does that, from
    the in-port, using exactly the seat search, keepout, projected-static,
    addon-supply and splitter certification it already runs for a strip lane.
    That is the point of the node being a five-tile lane -- every rule that
    governs a coater on a strip's channel governs it here unchanged.
    """
    indices: list[int] = []
    for k in range(_COATER_NODE_TILES):
        indices.append(
            canvas.add(
                PlacedBuilding(
                    item_id=belt_id,
                    model_index=belt_model,
                    x=ox + k,
                    y=oy,
                    width=1,
                    height=1,
                    yaw=Facing.EAST.value,
                    carries_item=item,
                    owner_strip=owner_strip,
                )
            )
        )
    for a, b in zip(indices, indices[1:], strict=False):
        canvas.buildings[a] = _relink(canvas.buildings[a], output_obj=b)
    tiles = tuple(indices)
    x1 = ox + _COATER_NODE_TILES - 1
    node_in = _Port(
        indices[0],
        ox,
        oy,
        ox,
        x1,
        tiles,
        machines,
        cargo_domain=CargoDomain.REQUIRES_SPRAY,
    )
    node_out = _Port(
        indices[-1],
        x1,
        oy,
        ox,
        x1,
        tiles,
        machines,
        cargo_domain=CargoDomain.REQUIRES_SPRAY,
    )
    return node_in, node_out


def _coater_node_site_is_clear(canvas: _Canvas, ox: int, oy: int) -> bool:
    """Can a five-tile node with its drop and approach stand at ``(ox, oy)``?

    Ordinary collision rules and nothing else -- which is the user's whole
    point about a packed object: the seat does not need a bespoke keep-out
    zone if the object is a real object.  The coater's own body keepout is
    still asked, because a belt addon's collider reaches machines a belt does
    not.
    """
    # The node's belt tiles with
    # one free cell on every side.  That ring is what `_coater_keepout_hits`
    # reserves, and -- measured -- it is also what keeps the node's belts far
    # enough from a machine for the spherical projection not to convict them:
    # without it `information-matrix/all-products` refused on `geom.collide`
    # at bands 160 and 200 with the node belts sitting against a machine
    # (evidence README section 5.2).  DO NOT NARROW THE RING: the first
    # `placed` implementation demanded only the four belt tiles and the two
    # level-1 cells, and that is the version those refusals came from.
    for k in range(-1, _COATER_NODE_TILES + 1):
        for dy in (-1, 0, 1):
            if not canvas.free((ox + k, oy + dy, 0)):
                return False
    # Area 1 is transverse to the sprayed run (SlotConfig's local yaw is 90).
    # Reserve the drop over tile 1 and its same-height sideways approach.
    if not canvas.free((ox + 1, oy, 1)) or not canvas.free((ox + 1, oy - 1, 1)):
        return False
    seat_x = ox + 1 + _coater_body_half_span(Facing.EAST.value)
    probe = PlacedBuilding(
        item_id=catalog.SPRAY_COATER_ID,
        model_index=catalog.building(catalog.SPRAY_COATER_ID).model_index,
        x=seat_x,
        y=oy,
        z=Fraction(0),
        width=1,
        height=1,
        yaw=Facing.EAST.value,
    )
    return not _coater_keepout_hits(canvas.buildings, probe)


def _coater_node_site(
    canvas: _Canvas,
    near: tuple[int, int],
    *,
    core: tuple[int, int, int, int],
    envelope: finalize.BandPolicySearchEnvelope | None,
    radius: int = 48,
) -> tuple[int, int] | None:
    """Free ground for one node, nearest the lane head it feeds.

    Variant C's whole placement rule.  Candidates are ordered by Chebyshev
    ring and, within a ring, by how far the node's OUT port ends up from the
    lane head it must reach -- a node whose east end is beside its consumer is
    a short net. The full node, including its transverse supply approach, must
    keep the shared routing envelope within an allowed latitude frame.
    Explicit template inventories have no final frame yet and pass no envelope.
    """
    hx, hy = near
    best: tuple[int, int, int] | None = None
    fitting_extents: dict[tuple[int, int], bool] = {}
    for ring in range(0, radius + 1):
        found: list[tuple[int, int, int]] = []
        if ring == 0:
            offsets: Iterable[tuple[int, int]] = ((0, 0),)
        else:
            offsets = (
                [(dx, -ring) for dx in range(-ring, ring + 1)]
                + [(dx, ring) for dx in range(-ring, ring + 1)]
                + [(-ring, dy) for dy in range(-ring + 1, ring)]
                + [(ring, dy) for dy in range(-ring + 1, ring)]
            )
        for dx, dy in offsets:
            # The node's east tile is the one that has to reach the head.
            ox = hx + dx - _COATER_NODE_TILES
            oy = hy + dy
            if envelope is not None:
                extent = (
                    max(core[2], ox + _COATER_NODE_TILES - 1) - min(core[0], ox) + 1,
                    max(core[3], oy) - min(core[1], oy - 1) + 1,
                )
                fits = fitting_extents.get(extent)
                if fits is None:
                    fits = bool(envelope.frame_candidates(*extent))
                    fitting_extents[extent] = fits
                if not fits:
                    continue
            if not _coater_node_site_is_clear(canvas, ox, oy):
                continue
            out_x = ox + _COATER_NODE_TILES - 1
            cost = abs(out_x - hx) + abs(oy - hy)
            found.append((cost, ox, oy))
        if found:
            best = min(found)
            break
    if best is None:
        return None
    return best[1], best[2]


def _coater_body_half_span(yaw: float) -> int:
    """Tiles the 1x3 body reaches either side of its seat ALONG the lane.

    At yaw 90 the oriented footprint is ``(3, 1)`` and this is 1; at yaw 0 it is
    ``(1, 3)`` and this is 0, correctly, because the body then does not extend
    along an east-west lane at all.  Derived rather than written as ``1`` so the
    seat rule below is exercised for both, and so a future rotated coater cannot
    silently keep the old arithmetic.
    """
    return (catalog.oriented_footprint(catalog.SPRAY_COATER_ID, yaw)[0] - 1) // 2


def _coater_seat_candidate_indices(
    port: _Port, west_channel: int, *, start: int = 1
) -> tuple[int, ...]:
    """The straight interior tiles a coater could ride, BEFORE any predicate.

    Split out of :func:`_coater_seats` so the refusal it feeds can tell the two
    reasons for an empty seat list apart: a lane too short to hold a straight
    seat at all (this returns nothing) versus a perfectly long lane every one of
    whose candidates a predicate skipped (this returns tiles and
    ``_coater_seats`` still returns none).  Duplicating the arithmetic at the
    call site instead is how those two drift apart.

    ``start`` is the first candidate index: 1 in production, ``1 + half_span``
    under the ``FLAB2BP_COATER_NODE`` narrow-seat experiment (see
    :func:`_coater_seats`).
    """
    stop = min(len(port.tiles) - 1, west_channel)
    return tuple(port.tiles[start:stop])


def _coater_seats(
    canvas: _Canvas,
    port: _Port,
    *,
    west_channel: int,
    yaw: float = Facing.EAST.value,
) -> tuple[tuple[int, int], ...]:
    """Straight seats before the first possible machine pickup, in flow order.

    Sprayed input lanes start ``west_channel`` cells west of the strip.  The
    machine-facing lane begins at index ``west_channel``, so that tile and every
    later one may already feed a machine.  Seating there would let that consumer
    take unsprayed cargo before it reaches the Coater.  Index zero is the routing
    turn and the last tile has no successor; only the bounded interior channel
    offsets between them are candidates.

    Under a node arm the first candidate index is ``1 + half_span`` rather than
    ``1``: index 0 is the lane HEAD, the one cell of the lane a router path can
    reach and therefore the cell every many-to-one merge lands on, and a seat at
    index ``half_span`` or less puts the 3x1 body over it.  That is the reported
    defect (``belt#0 (53,20,0) pred=[817, 1872]`` on coater#771's body).  At
    ``west_channel = 3`` this leaves exactly one candidate, ``ox - 1``; the
    staged-static clearance lift to 4 leaves two.

    **This is the path production seats coaters from** -- ``_place_coaters``
    calls this, not :func:`_coater_seat` (spec section 9 R7: a predicate added
    only to ``_coater_seat`` is dead code, since nothing in ``src/`` calls it).

    **Only ONE of ``prolif.coater_rides_one_run``'s two clauses is actually
    enforced here** (spec section 9 R9).  A candidate is skipped when it would
    have an ambiguous addon-area-1 supply
    (:func:`_coater_candidate_has_ambiguous_supply`, the validator's second
    clause) -- and that predicate is STRICTER than the validator, so it can
    only cost seats, never miss one.  :func:`_coater_candidate_rides_a_merge`,
    the first clause, is called but **filters nothing**: ``_place_coaters``
    runs BEFORE routing, and the merges that clause convicts are made by the
    ROUTER afterwards.  At seat time no candidate body tile carries a belt with
    two predecessors, so it returns ``False`` every time.  Filtering before
    routing can never catch a merge routing has not created yet; the validator
    stays the only thing that catches clause 1, and it catches it after a whole
    build has been spent.  The next lever is named in section 9 R9.

    ``_place_coaters`` treats an empty result exactly as it treats a lane with
    no legal seat at all: an :class:`_Unseatable` refusal, never a silently
    skipped coater.

    Index zero is excluded for a second reason as well: the game reads BOTH
    ends of the belt an addon rides and refuses the addon when either
    disagrees with its axis, so a seat needs a lane tile either side of it.
    See :func:`flab2bp.dsp.rules.addon_ride_is_straight`.

    **Why the seat is upstream of every sorter.**  A coater sprays what passes
    THROUGH it, so everything a machine takes has to reach the coater first.
    An input lane is emitted west to east and linked the same way --
    ``_emit_strip`` chains ``indices[k].output_obj = indices[k + 1]`` -- and
    the feeding net sinks into ``lane_idx[row][0]``, which is why ``_Port.x``
    is the lane's WEST end.  So an input lane flows west to east, its head is
    ``port.x``, and every sorter on it draws from a tile at or after the head.
    A seat after the first machine-facing tile would let that consumer take
    unsprayed cargo, which is why ``stop`` is ``west_channel``.

    **The measurement that made this rule.**  The seat used to be ``port.x1``,
    the lane's east end, on the reasoning that it is nearest the east margin
    the drop belt lived in.  That is the DOWNSTREAM end: the last belt of the
    chain, with no ``output_obj`` and nothing after it.  Measured over five
    clean proliferated freeform placements (``energy-matrix``, ``graphene``,
    ``plastic``, ``processor``, ``magnetic-coil``), **all 12 coaters were the
    last belt of their own chain and all 12 had zero pickups anywhere
    downstream of them** -- every sorter on every sprayed lane drew from a tile
    the cargo reached before the coater.  The spray was applied to cargo
    dead-ended at the end of a belt.  Spine on the same five specs seats 0 of
    12 at the tail.  So the blueprint pasted, the coaters were supplied,
    ``prolif.coaters_are_supplied`` passed -- and not one proliferated recipe
    would have run proliferated.  That is the failure this ordering prevents,
    and it is the reason the rule is not a matter of taste.
    """
    half_span = _coater_body_half_span(yaw) if coater_mode().is_node else 0
    start = 1 + half_span
    # Leave the full downstream body before the routing output port too.
    west_channel = min(west_channel, len(port.tiles) - 1 - half_span)
    seats: list[tuple[int, int]] = []
    for index in _coater_seat_candidate_indices(port, west_channel, start=start):
        x, y = canvas.buildings[index].x, canvas.buildings[index].y
        if _coater_candidate_rides_a_merge(canvas, x, y, port.z):
            continue
        if _coater_candidate_has_ambiguous_supply(canvas, x, y, port.z):
            continue
        seats.append((x, y))
    return tuple(seats)


def _coater_candidate_rides_a_merge(canvas: _Canvas, x: int, y: int, z: int) -> bool:
    """Would a coater seated at ``(x, y, z)`` ride a belt merge under its body?

    Mirrors ``validate._coater_body_tiles`` and
    ``validate._coater_belt_predecessor_counts``, for a coater not yet placed:
    a belt on a tile the coater's ``Facing.EAST`` 1x3 body would cover is a
    merge when two or more BELT buildings feed it via ``output_obj``.

    **In production this returns ``False`` for every candidate, and therefore
    filters nothing** (spec section 9 R9).  ``_place_coaters`` seats coaters
    BEFORE routing -- it has to, because each coater needs a proliferator net
    routed to its drop belt -- and a belt merge is something the ROUTER makes
    afterwards.  At seat time no candidate's body tiles carry a belt with two
    belt predecessors, so the ``any(...)`` below is never satisfied.  The
    reported URL's decode shows it directly: the merge point is ``belt#0`` --
    index 0, laid down with the strips -- and its two predecessors are ``817``
    and ``1872``, neither of which existed when its seat was picked
    (``evidence/2026-09-06-selfloop/gate/coater-amm-master.txt:12``).

    It is kept, not deleted, because it is the honest statement of what clause
    1 means and it costs only local indexed lookups; it would start biting
    the moment seating moves after routing. Do not read a passing candidate as evidence
    that clause 1 holds.

    Separately, and even if it did run late enough to bite, it is LOOSER than
    ``prolif.coater_rides_one_run``'s first clause, by controller ruling (fix
    round 1, task 2): that check also convicts a body spanning two DISTINCT
    ``ctx.run_of`` values with no single merged tile among them, which needs
    the validator's whole-graph run assignment.  The canvas has no such map at
    seat-selection time, and building one here was ruled out rather than
    invented for one candidate at a time.

    The validator is the ONLY thing that enforces clause 1, and it does so
    after a whole build has been spent.  The next lever -- enforcing it where
    the merge is created -- is named in spec section 9 R9.
    """
    width, height = catalog.oriented_footprint(catalog.SPRAY_COATER_ID, Facing.EAST.value)
    body_tiles = {
        (x + dx, y + dy)
        for dx in range(-(width // 2), width // 2 + 1)
        for dy in range(-(height // 2), height // 2 + 1)
    }
    bs = canvas.buildings
    return any(
        bs.kind_of(i) is BuildingKind.BELT
        and (bs[i].x, bs[i].y) == tile
        and len(bs.belts_into(i)) >= 2
        for tile in body_tiles
        for i in bs.at_tile(*tile, z=z)
    )


def _coater_candidate_has_ambiguous_supply(canvas: _Canvas, x: int, y: int, z: int) -> bool:
    """Would a coater seated at ``(x, y, z)`` have >1 belt near its addon area 1?

    Mirrors ``validate._coater_supply_area_candidates`` for a coater not yet
    placed: every belt within :data:`~flab2bp.dsp.rules.ADDON_AREA_RADIUS` of
    the addon area 1 position, at ``Facing.EAST``.

    STRICTER than ``prolif.coater_rides_one_run``'s second clause, which
    convicts only when those belts span two or more DISTINCT ``ctx.run_of``
    values (spec section 9 R6) -- the same whole-graph run map this module
    does not build at seat-selection time (see
    :func:`_coater_candidate_rides_a_merge`).  This candidate never sees the
    coater's own future ``approach``/``supply`` pair -- ``_place_coaters``
    creates those belts AFTER a seat is chosen, so R6's fix does not need
    reproducing here at all -- but a pre-existing belt pair that happens to be
    one clean run (which the validator would clear) is still refused as a
    seat here.  The safe direction: never offers a seat the validator would
    convict, at the cost of occasionally declining one it would accept.  R7's
    own cost note is this exact trade; the gate counts it.
    """
    want = slots.addon_supply_position(
        catalog.SPRAY_COATER_ID,
        x=x,
        y=y,
        z=Fraction(z),
        yaw=Facing.EAST.value,
        area=1,
    )
    reach = math.ceil(rules.ADDON_AREA_RADIUS / colliders.GRID_ARC)
    anchor_x = math.floor(float(want[0]))
    anchor_y = math.floor(float(want[1]))
    candidates = 0
    for b in canvas.buildings:
        if not catalog.is_belt(b.item_id):
            continue
        if not (anchor_x - reach <= b.x <= anchor_x + reach):
            continue
        if not (anchor_y - reach <= b.y <= anchor_y + reach):
            continue
        distance = rules.world_gap(float(want[0] - b.x), float(want[1] - b.y), float(want[2] - b.z))
        if distance < rules.ADDON_AREA_RADIUS:
            candidates += 1
            if candidates > 1:
                return True
    return False


def _coater_belt_ban_cells(
    coater: PlacedBuilding,
    belt_model: int,
) -> Iterator[Cell]:
    """Cells excluded by a Coater's collider and positional supply area."""
    cx, cy = coater.x, coater.y
    supply = slots.addon_supply_cell(coater.item_id, x=cx, y=cy, z=coater.z, yaw=coater.yaw, area=1)
    drop = supply[:2]
    pose = _collision_pose(coater)
    need = colliders.belt_crossing_height(coater.model_index)
    body_half = _coater_body_half_span(coater.yaw)
    span = body_half + 1
    if coater_mode().is_node:
        # The area-1 rival cell -- and only that.  DO NOT delete this along
        # with the body-level clause that used to stand beside it: the rival is
        # a LEVEL-1 cell that is not part of the node at all, so nothing about
        # the node being a free-standing run makes it structural.  It is the
        # cell mirroring the drop across the seat, at the drop's own level, and
        # it is exactly the reported area-1 ambiguity: coater#768 with the drop
        # at (53,20,1) and a cargo lane at (55,20,1), both inside the 1.0
        # radius on opposite sides of the seat at (54,20,0).
        #
        # The body's OWN level was banned here too, to stop `_merge_frontier`
        # OFFERING a body tile as a merge goal -- the one path by which a
        # second predecessor could reach a cell the coater covers, since A*
        # cannot step onto an occupied belt.  The frontier offers only cells
        # `_Canvas.free` accepts, so that ban could only bite on a body cell
        # that was free when it was written.  Measured over three proliferated
        # specs and 60 committed body cells: 0 were free and 60 carried the
        # node's own belt, already on the canvas by staging time.  The clause
        # could not change a routing decision, so it is gone.  See
        # `test_a_node_body_tile_is_always_an_occupied_belt_so_no_merge_can_be_offered_there`.
        rival = (2 * cx - supply[0], 2 * cy - supply[1])
        yield rival[0], rival[1], supply[2]
    for dx in range(-span, span + 1):
        for dy in range(-span, span + 1):
            tile = (cx + dx, cy + dy)
            if tile == drop:
                continue
            for level in range(math.floor(coater.z) + 1, math.floor(coater.z + need) + 1):
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
                    [pose],
                    directly_over_only=True,
                ):
                    yield tile[0], tile[1], level


def _reserve_coater_belt_ban(
    canvas: _Canvas,
    coater: PlacedBuilding,
    belt_model: int,
) -> None:
    """Price the committed Coater's exact collider for later belt routes."""
    for x, y, level in _coater_belt_ban_cells(coater, belt_model):
        canvas.belt_ban.setdefault((x, y), set()).add(level)


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
      :func:`_coater_seats`, whose docstring carries the measurement that made
      that rule.
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
    staged_belt_bans: set[Cell] = set()
    prospective = MutableBuildings(canvas.buildings)
    # Staging adds only belts and Spray Coaters. Bound all possible coater
    # rotations now, alongside every existing non-belt/non-sorter obstacle.
    max_obstacle_span = math.hypot(*catalog.collider_span(catalog.SPRAY_COATER_ID, 0.0))
    for index in (*prospective.machines(), *prospective.by_kind(BuildingKind.OTHER)):
        if cancelled is not None and cancelled():
            raise _PreparationDeadline
        max_obstacle_span = max(max_obstacle_span, _static_collider_span(prospective[index]))
    obstacle_index = _ProjectedObstacleIndex.build(
        tuple(enumerate(prospective)),
        cancelled=cancelled,
    )
    splitter_buildings = tuple(
        (index, canvas.buildings[index]) for index in canvas.buildings.by_item(catalog.SPLITTER_ID)
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
        for index in canvas.buildings.belts()
        for building in (canvas.buildings[index],)
        if building.z.denominator == 1
    }

    for strip_index, (strip, in_ports) in enumerate(zip(strips, ports, strict=True)):
        if cancelled is not None and cancelled():
            raise _PreparationDeadline
        if strip.cargo_domain is not CargoDomain.REQUIRES_SPRAY:
            continue
        items = strip.in_lanes
        next_options = [0] * len(items)
        checkpoints: list[
            tuple[
                int,
                finalize._CleanupSurvivorGraph,
                tuple[int, int, int, int],
                float,
                set[Cell],
            ]
        ] = []
        first_refusal: _Unseatable | None = None
        lane_position = 0
        # A supply approach can occupy the next lane's only legal drop.
        # Search this strip's finite seat domain without revisiting prior strips
        # or mutating the canvas before the complete staged set is accepted.
        while lane_position < len(items):
            if cancelled is not None and cancelled():
                raise _PreparationDeadline
            item = items[lane_position]
            lane_staged_start = len(staged)
            lane_cleanup_prefix = cleanup_prefix
            lane_cleanup_bounds = cleanup_bounds
            lane_obstacle_radius = obstacle_index.max_horizontal_radius
            introduced_bans: set[Cell] = set()
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
            # The node's ports bound its full body; _coater_seats excludes both
            # end regions while preserving the strip's machine-pickup bound.
            seat_channel = len(port.tiles) - 1 if coater_mode().is_node else strip.west_channel
            seats = _coater_seats(
                canvas,
                port,
                west_channel=seat_channel,
            )
            if not seats:
                # An empty seat list has TWO causes and they want different
                # fixes, so the refusal must not blame the wrong one.  Before
                # the seat predicates existed only the first was possible.
                offered = _coater_seat_candidate_indices(port, strip.west_channel)
                if not offered:
                    raise _Unseatable(
                        f"the {item} lane at ({port.x}, {port.y}) is "
                        f"{len(port.tiles)} tile(s) long, and a coater needs a "
                        f"tile with a lane tile on both sides of it to ride "
                        f"straight"
                    )
                raise _Unseatable(
                    f"the {item} lane at ({port.x}, {port.y}) is "
                    f"{len(port.tiles)} tile(s) long and offers {len(offered)} "
                    f"straight seat(s), but a coater at every one of them would "
                    f"have more than one belt near its addon area 1 or ride a "
                    f"belt merge under its body -- the two things "
                    f"prolif.coater_rides_one_run convicts, so seating one here "
                    f"would build a layout our own validator rejects"
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
            seat_option_count = 2 * len(seats)
            for option_index, (cx, cy, approach_sign) in enumerate(
                (x, y, sign) for x, y in seats for sign in (1, -1)
            ):
                if cancelled is not None and cancelled():
                    raise _PreparationDeadline
                if option_index < next_options[lane_position]:
                    continue
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
                # SlotConfig's raised area is transverse to this radial offset.
                # Feeding a terminal along the sprayed run fails AddonPass.
                # AddonPass compares the absolute axis dot product: either
                # transverse direction is legal. Prefer the original side,
                # then its reverse before moving the coater farther inward.
                approach_cell = (
                    drop_cell[0] - approach_sign * approach_dy,
                    drop_cell[1] + approach_sign * approach_dx,
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
                    max_obstacle_span=max_obstacle_span,
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
                    or drop_cell in staged_belt_bans
                    or approach_cell in staged_belt_bans
                    or not canvas.free(drop_cell)
                    or not canvas.free(approach_cell)
                ):
                    failure_reasons.append(
                        f"the {item} coater at ({cx}, {cy}) cannot have its "
                        f"straight proliferator drop at {drop_cell} through "
                        f"approach {approach_cell}: one of those cells is taken"
                    )
                    continue
                candidate_belt_bans = set(_coater_belt_ban_cells(proposed_coater, belt_model))
                if any(
                    cell in belt_at or cell in staged_supply_cells for cell in candidate_belt_bans
                ):
                    failure_reasons.append(
                        f"the {item} coater at ({cx}, {cy}, z={host_z}) "
                        "would obstruct an existing or staged belt"
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
                    potential_peers = tuple(
                        index
                        for index, _peer in _staged_static_projection_peers(
                            prospective,
                            proposed_coater,
                            owner_strip=strip_index,
                            policy=policy,
                            indices=potential_peers,
                        )
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
                # Publish the staged collider only after this seat passes every
                # check. Later supply terminals must clear it before commit.
                introduced_bans = candidate_belt_bans - staged_belt_bans
                staged_belt_bans.update(candidate_belt_bans)
                seated = True
                break

            if not seated:
                if first_refusal is None:
                    first_failure = projected_failures[0][0] if projected_failures else None
                    first_relation = projected_failures[0][2] if projected_failures else None
                    first_exact_retry_evidence = (
                        projected_failures[0][3] if projected_failures else None
                    )
                    all_projected = len(projected_failures) == seat_option_count
                    same_strip = (
                        first_failure is not None and same_strip_static_seats == seat_option_count
                    )
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
                    first_refusal = _Unseatable(
                        failure_reasons[0],
                        failure=first_failure,
                        clearance_requirement=clearance_requirement,
                        exact_retry_evidence=(
                            first_exact_retry_evidence if all_projected and not same_strip else None
                        ),
                    )
                if lane_position == 0:
                    raise first_refusal
                # The first branch's collider witness remains useful evidence,
                # but it does not prove a clearance lift or a hard no-good for
                # every other assignment explored by this local transaction.
                first_refusal.clearance_requirement = None
                first_refusal.exact_retry_evidence = None
                next_options[lane_position] = 0
                lane_position -= 1
                (
                    staged_start,
                    cleanup_prefix,
                    cleanup_bounds,
                    obstacle_radius,
                    added_bans,
                ) = checkpoints.pop()
                while len(staged) > staged_start:
                    removed = staged.pop()
                    for _ in range(3):
                        prospective.pop()
                    for position, obstacle in enumerate(obstacle_index.obstacles):
                        if obstacle[0] == removed.port.coater:
                            del obstacle_index.obstacles[position]
                            del obstacle_index.xs[position]
                            break
                    staged_hosts.remove(removed.port.host_belt)
                    staged_supply_cells.difference_update(
                        (
                            (removed.approach.x, removed.approach.y, removed.port.z),
                            (removed.supply.x, removed.supply.y, removed.port.z),
                        )
                    )
                obstacle_index.max_horizontal_radius = obstacle_radius
                staged_belt_bans.difference_update(added_bans)
                continue
            next_options[lane_position] = option_index + 1
            checkpoints.append(
                (
                    lane_staged_start,
                    lane_cleanup_prefix,
                    lane_cleanup_bounds,
                    lane_obstacle_radius,
                    introduced_bans,
                )
            )
            lane_position += 1
        seen.update(items)

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
    final_addon_failure: finalize.ProjectionFailure | None = None
    failed_candidate: _StagedCoater | None = None
    viable_addon_frames: list[_JunctionProjectionFrame] = []
    for frame in final_frames:
        if cancelled is not None and cancelled():
            raise _PreparationDeadline
        final_frame_failure: finalize.ProjectionFailure | None = None
        frame_failed_candidate: _StagedCoater | None = None
        for candidate in staged:
            candidate_host = prospective[candidate.port.host_belt]
            context_key = _projected_coater_supply_context_key(
                candidate,
                candidate_host,
                frame,
            )
            if context_key in staged_static_cache.coater_supply_failures:
                final_frame_failure = staged_static_cache.coater_supply_failures[context_key]
            else:
                final_frame_failure = _projected_coater_supply_frame_failure(
                    candidate,
                    candidate_host,
                    frame,
                    cancelled=cancelled,
                )
                staged_static_cache.coater_supply_failures[context_key] = final_frame_failure
            if final_frame_failure is not None:
                frame_failed_candidate = candidate
                break
        if final_frame_failure is None:
            viable_addon_frames.append(frame)
            final_addon_failure = None
            failed_candidate = None
            if projected_capacity is None:
                break
        elif final_addon_failure is None:
            final_addon_failure = final_frame_failure
            failed_candidate = frame_failed_candidate
    if not viable_addon_frames and final_addon_failure is not None:
        candidate = failed_candidate or staged[0]
        raise _Unseatable(
            f"the {candidate.port.item} coater at "
            f"({candidate.port.host_x}, {candidate.port.host_y}, "
            f"z={candidate.port.host_z}) loses a projected supply belt after "
            "the complete coater set fixes the final frame",
            failure=final_addon_failure,
            exact_retry_evidence=_exact_retry_evidence(
                "seating",
                final_addon_failure,
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
            splitter_frame_failure: finalize.ProjectionFailure | None = None
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
                        splitter_frame_failure = finalize.projected_coater_splitter_failure(
                            framed_staged_pairs[candidate_position],
                            splitter,
                            projection,
                            cancelled=cancelled,
                        )
                        if splitter_frame_failure is not None:
                            break
                    if splitter_frame_failure is not None:
                        break
                if splitter_frame_failure is not None:
                    if splitter_failure is None:
                        splitter_failure = splitter_frame_failure
                        failed_splitter_candidate = candidate
                    break
            if splitter_frame_failure is None:
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
        out.append(candidate.port)

    for x, y, level in staged_belt_bans:
        canvas.belt_ban.setdefault((x, y), set()).add(level)
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
    north-west input. Balanced groups prefer spaced trunk taps. All taps retain
    that common supply-root identity, so detailed routing can share an admitted
    leaf branch when a designated tap is congested. The trunk itself is already
    emitted and does not need to be rediscovered by A*.
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
    # Spend spare taps on the opposite trunk before assigning two leaves to one
    # tap. Distinct taps avoid mandatory shared-stem dependencies; the common
    # physical supply identity still permits sharing when routing needs it.
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
                supply_root_belt=entry.belt,
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
