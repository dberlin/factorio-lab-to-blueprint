"""Lay every solved block on one canvas and route the cuts with the real router.

The prototype
(``docs/superpowers/evidence/2026-09-06-exp-hierarchical/proto/compose.py``)
wired the cuts with its own corridor Dijkstra, on the reading that
``freeform._route_all`` "is not callable standalone".  That reading is wrong:
``_route_all`` takes a prepared :class:`~flab2bp.layout.routing_domain._Canvas` and a
list of :class:`~flab2bp.layout.routing_domain._Net`, and ``tests/layout/
test_freeform.py`` already calls it that way. Internal cuts use the router's
port-access reservations and physical crossing bands, not prototype collider
halos, soft moats or altitude tolls. Composition also holds complete player-entry
approaches: a cut's immediate access cells cannot preserve outside connectivity.

The packing does survive, verbatim: ``_normalize``, :func:`pack_blocks` (the
prototype's ``_shelf`` without its single-row mode), :func:`_skyline` and
``_translate``. The two-tile gap floor remains because ``game.belt_collide``
prices a belt against a neighbour's build collider. Candidate admission uses
the finalizer's exact requested band envelope, not a second latitude ceiling.
"""

from __future__ import annotations

import bisect
import math
import time
from collections import deque
from collections.abc import Collection, Sequence
from dataclasses import dataclass, replace
from fractions import Fraction
from functools import partial
from typing import NamedTuple

from flab2bp.dsp import catalog
from flab2bp.layout import finalize, junction, physical_flow, slots, validate
from flab2bp.layout.band_policy import BandPolicy
from flab2bp.layout.base import PlacedBuilding, Placement
from flab2bp.layout.buildings import Buildings
from flab2bp.layout.finalize import BandPolicySearchEnvelope, band_policy_search_envelope
from flab2bp.layout.hierarchy.contracts import LaneFlow
from flab2bp.layout.route_feedback import (
    Cell,
    DetailedRouteStatus,
    NetId,
    NetRole,
    RouteInteriorDetour,
    RouteSettlement,
    RouteSettlementCancelled,
    RouteSettlementCompleted,
    RouteSettlementCrashed,
    RouteSettlementRefused,
)
from flab2bp.layout.routing_domain import (
    PortAccessDemand,
    PortAccessEvidence,
    PortAccessReservation,
    RoutingFlowLimits,
    _Canvas,
    _CompositionProjection,
    _lane_stacks_for,
    _Net,
    _place_power,
    _Port,
    _port_access_inventory,
    _power_reservation,
    _PreparationDeadline,
    _reserve_coater_belt_ban,
    _reserve_port_access,
    _route_all,
    _sorter_stacks_for,
    _sorter_tiers_for,
    _Unpowerable,
    plan_power_infill,
)
from flab2bp.layout.strip_variants import CargoDomain
from flab2bp.spec import BuildSpec

_PORTABLE_POLICY = BandPolicy("portable")

#: The narrowest gap a packing may leave between two blocks.
#:
#: ``game.belt_collide`` prices a belt against a neighbour's build collider and
#: a Splitter's reaches beyond its 2x2 footprint, so blocks laid flush against
#: each other convict on contact alone.
MIN_GAP = 2

#: The gaps a packing may be tried at, narrowest first.
#:
#: A block solved on its own owns every tile of its own box, so the ONLY ground
#: an inter-block cut can run on is the gap the packing left between the boxes.
#: At :data:`MIN_GAP` that ground is two tiles wide and already carries the
#: neighbours' belt colliders, which is why the v1 gate measured the router
#: refusing 8-50 lanes on belt3 dominated by ``DYNAMIC_ACCESS`` -- and why
#: DOUBLING the routing budget to 120 s did not change the class.  A router that
#: refuses the same way with twice the wall is not short of time; it is being
#: handed a canvas with nowhere to run, and the fix is more ground rather than
#: more clock.
#:
#: The rungs double and then step, because the cost of a rung is a whole
#: re-pack plus a whole reservation: a fine ladder would spend the composition's
#: budget proving that 3 is as hopeless as 2. The measured ladder stops at 16;
#: widening it is a separate search-policy decision, not band admission.
GAP_LADDER = (2, 4, 6, 8, 12, 16)

#: The share of the wall left on entry that rungs BEYOND THE FIRST may spend.
#:
#: The first rung is not speculative -- it is the composition that would have
#: been committed before there was a ladder -- so it runs on the caller's own
#: clock, exactly as it did.  Every further rung is a bet, and a bet has to be
#: funded out of something.  Handed the whole clock the ladder can pay for six
#: packs, six canvases and six reservations, hand ``_route_all`` a deadline that
#: has already passed, and refuse under ``BUDGET`` on cuts the first rung would
#: have wired -- a wider canvas nobody has the wall left to route on is not an
#: improvement, it is a regression wearing one's clothes.
#:
#: The majority stays with the router because the router is the stage that
#: actually produces belts; the ladder only decides which ground it produces
#: them on.
LADDER_WALL_SHARE = 0.4

#: The share of the wall on entry that rung 0's RESERVATION may spend.
#:
#: Rung 0 used to run on the caller's own clock because its reservation was
#: the local-only oracle and cost almost nothing.  With trunk goals it runs
#: an A* per option per demand, so an unbounded rung 0 could spend the wall
#: `_route_all` needs and refuse on BUDGET the cuts a cheaper oracle would
#: have wired -- the same trade `LADDER_WALL_SHARE` exists for one rung up.
#: On its own expiry rung 0 is RE-JUDGED with the local-only oracle
#: (`goals=None`) on the caller's full clock, so the degradation is to v2's
#: behaviour rather than to a refusal.
RESERVE_WALL_SHARE = 0.25


@dataclass
class BlockPlaced:
    """One solved block, and where it landed on the composed canvas."""

    index: int
    #: The block's own NORMALIZED placement -- shifted to the origin, links
    #: still block-local. ``base`` indexes the raw routing canvas, not a cleaned
    #: or framed accepted placement.
    placement: Placement
    base: int
    offset: tuple[int, int]
    width: int
    height: int


@dataclass
class ComposeResult:
    """The composed placement plus an honest account of every cut."""

    placement: Placement
    blocks: list[BlockPlaced]
    routed: int
    #: One line per unrouted flow: item, source block, destination block, and
    #: the router's own failure kind.  A cut that did not wire is REPORTED, not
    #: quietly dropped -- an unwired entry lane is a block that starves, and the
    #: validator convicts it several errors later with no way back to the cause.
    failures: tuple[str, ...]
    #: The `GAP_LADDER` rung the composition committed.
    gap: int = 0
    #: Port-access demands the committed rung raised, and how many of them the
    #: reservation could not give a corridor to.  Both describe the reservation
    #: the composer ACTED ON, degraded or not -- see `reservation_degraded`.
    port_demands: int = 0
    reservation_missing: int = 0
    #: Ladder rungs whose trunk-goal reservation was discarded as unusable.
    reservation_degraded: int = 0
    #: Of `reservation_degraded`, how many rungs committed a surveyed partial
    #: rather than falling back to the local-only oracle.
    reservation_partial: int = 0
    #: Towers the composition stood for powered tiles no block's plan reached,
    #: and tiles it could not cover at all.  A non-zero `power_uncovered` is
    #: always accompanied by one `failures` entry per tile.
    power_infill: int = 0
    power_uncovered: int = 0
    #: Cuts the ROUTER (or the port-access reservation) could not wire -- the
    #: prefix of `failures` recorded before power infill runs.  `strategy.py`'s
    #: `unrouted_cuts` reads THIS, not `len(failures)`, so the per-tile power
    #: infill findings above never inflate a number Task 9 compares across
    #: gates: those tiles are already counted in `power_uncovered`.
    unrouted_cuts: int = 0
    settlement: RouteSettlement | None = None
    route_expansions: int = 0
    settlement_attempts: int = 0
    settlement_refusals: int = 0
    settlement_reuses: int = 0
    settlement_wall_s: float = 0.0


class _Packing(NamedTuple):
    """One gap's committed geometry, before any reservation has judged it.

    A tuple rather than a dataclass so that a judged rung is spelled
    ``PackedCanvas(*packing, reservation=..., gap=...)``: these are
    :class:`PackedCanvas`'s own leading four fields in its own order, and
    keeping the two shapes in step is what stops a verdict being attached to a
    different packing than the one it judged.
    """

    buildings: list[PlacedBuilding]
    blocks: list[BlockPlaced]
    canvas: _Canvas
    nets: list[_Net]


@dataclass(frozen=True)
class PackedCanvas:
    """A packing, and the corridor verdict that let it be committed.

    ``reservation`` is STAKED ON ``canvas``: ``_reserve_port_access`` writes its
    assignments into ``canvas.reserved`` and ``canvas.port_corridors`` before it
    returns, so a caller routes on this canvas and must not reserve again.  The
    corollary is that a rejected rung cannot be un-staked and is simply thrown
    away, canvas and all -- which is why each rung packs from scratch.
    """

    buildings: list[PlacedBuilding]
    blocks: list[BlockPlaced]
    canvas: _Canvas
    nets: list[_Net]
    reservation: PortAccessReservation
    gap: int
    #: How many rungs of the ladder -- this one included -- had their
    #: trunk-goal reservation discarded as unusable and re-asked local-only.
    #: A LADDER TOTAL rather than a property of this rung, because it is the
    #: ladder's whole answer that the gate has to be able to read: a committed
    #: rung with `reservation.missing` empty means "every port is satisfiable"
    #: only when this is 0.  See :func:`pack_with_access`.
    degraded: int = 0
    #: How many rungs committed a SURVEYED PARTIAL from the trunk-goal oracle
    #: -- an assignment the matcher handed back without converging, with the
    #: demands its own survey convicted already removed.  A ladder total, like
    #: `degraded`, and always <= it: every partial is also degraded, because
    #: `reservation_degraded == 0` has exactly one meaning and it is "the
    #: matcher converged".  This counter is what separates "the oracle was
    #: thrown away and v2's local question re-asked" (degraded, not partial)
    #: from "the oracle answered for most lane heads and named the rest"
    #: (both).  See v3 gate.md §6's open residual.
    partial: int = 0
    #: Actual same-plane player approaches, held for the lifetime of this canvas.
    #: Unlike cut corridors these are never retired when an internal net routes.
    external_access: frozenset[Cell] = frozenset()


class _PackingDeadline(Exception):
    """The clock ran out before any rung of the ladder returned a verdict.

    Carries the packing it died on, because the caller still owes its own
    caller a REFUSAL THAT NAMES EVERY CUT -- and the net list it has to name
    them from only exists inside the rung that was being judged.
    """

    def __init__(self, packing: _Packing) -> None:
        super().__init__("no gap could be judged before the deadline")
        self.packing = packing


class _ExternalAccessRefused(RuntimeError):
    """No outside-connected approach exists in this packed search domain."""

    def __init__(self, packing: _Packing, failures: tuple[str, ...]) -> None:
        super().__init__("; ".join(failures))
        self.packing = packing
        self.failures = failures


def _normalize(placement: Placement) -> tuple[Placement, int, int]:
    min_x, min_y, max_x, max_y = placement.bounds
    shifted = tuple(
        replace(
            b,
            x=b.x - min_x,
            y=b.y - min_y,
            x2=None if b.x2 is None else b.x2 - min_x,
            y2=None if b.y2 is None else b.y2 - min_y,
        )
        for b in placement.buildings
    )
    return (
        replace(placement, buildings=shifted, frame=None, completion=None),
        max_x - min_x + 1,
        max_y - min_y + 1,
    )


def pack_blocks(
    sizes: list[tuple[int, int]], gap: int, *, envelope: BandPolicySearchEnvelope
) -> tuple[list[tuple[int, int]], int, int]:
    """Pack the blocks bottom-left, preferring a band-legal shape to a small one.

    Shelves are packed tallest-first (best-fit decreasing height), which trades
    strict topological order along the bus for much less shelf waste.  The
    router searches the whole canvas, so the order only decides how far a trunk
    has to travel.

    WHAT A SHELF PACK COSTS, from the prototype's ``_shelf``:
    ``finalize.finalize_placement`` projects tile rows onto LATITUDE rows, and a
    block certified at one latitude is not certified at another, so moving a
    block DOWN re-prices every east-west gap inside it.  Anchoring every block
    at ``y = 0`` preserves each one's own rows and its power-pole spacings; a
    shelf pack does not, and refuses on ``game.power_too_close``.  The single
    row is not offered here because it cannot meet the band ceiling below at any
    real scale, but a caller that finalizes a composition has to expect that
    refusal and cannot read a block's own certification as still holding.

    Preserve the blocks' axes when the exact envelope permits it, then minimize
    span before area: a slightly smaller footprint can require much longer
    inter-block routes. If none fits, retain the smallest diagnostic fallback.
    """
    gap = max(gap, MIN_GAP)
    best: tuple[int, list[tuple[int, int]], int, int] | None = None
    best_score: tuple[bool, int, int] | None = None
    fallback: tuple[int, list[tuple[int, int]], int, int] | None = None
    widest = max(w for w, _ in sizes) + gap
    total = sum((w + gap) * (h + gap) for w, h in sizes)
    for scale in (0.85, 1.0, 1.15, 1.3, 1.5, 1.8, 2.2, 2.8, 3.6):
        target = max(widest, int((total**0.5) * scale))
        packed = _skyline(sizes, gap, target)
        if packed is None:
            continue
        offsets, width, height = packed
        candidate = (width * height, offsets, width, height)
        if fallback is None or candidate[0] < fallback[0]:
            fallback = candidate
        frames = envelope.frame_candidates(width, height)
        if not frames:
            continue
        score = all(frame.frame.rotated for frame in frames), width + height, width * height
        if best_score is None or score < best_score:
            best = candidate
            best_score = score
    chosen = best or fallback
    assert chosen is not None
    return chosen[1], chosen[2], chosen[3]


def _skyline(
    sizes: list[tuple[int, int]], gap: int, target: int
) -> tuple[list[tuple[int, int]], int, int] | None:
    """Bottom-left skyline packing, tallest first, into a ``target`` wide strip.

    Shelf packing wasted 40 % of the composed canvas on belt3 because block
    heights differ by 3x.  A skyline keeps the same left-to-right sweep and
    fills the notches, which is what brings the composition overhead down to
    something a decision can be made on.
    """
    if any(w > target for w, _ in sizes):
        return None
    order = sorted(range(len(sizes)), key=lambda i: (-sizes[i][1], -sizes[i][0], i))
    heights = [0] * target
    offsets: list[tuple[int, int]] = [(0, 0)] * len(sizes)
    used_w = used_h = 0
    for i in order:
        w, h = sizes[i]
        span = min(target, w + gap)
        best_spot: tuple[int, int] | None = None
        for x in range(target - w + 1):
            top = max(heights[x : min(target, x + span)])
            if best_spot is None or (top, x) < best_spot:
                best_spot = (top, x)
        assert best_spot is not None
        top, x = best_spot
        offsets[i] = (x, top)
        used_w = max(used_w, x + w)
        used_h = max(used_h, top + h)
        for k in range(x, min(target, x + span)):
            heights[k] = top + h + gap
    return offsets, used_w, used_h


def _translate(placement: Placement, base: int, ox: int, oy: int) -> list[PlacedBuilding]:
    """``placement`` moved to ``(ox, oy)`` with its links rebased onto ``base``."""
    out: list[PlacedBuilding] = []
    for b in placement.buildings:
        out.append(
            replace(
                b,
                x=b.x + ox,
                y=b.y + oy,
                x2=None if b.x2 is None else b.x2 + ox,
                y2=None if b.y2 is None else b.y2 + oy,
                output_obj=None if b.output_obj is None else b.output_obj + base,
                input_obj=None if b.input_obj is None else b.input_obj + base,
            )
        )
    return out


#: Belt-integrated kinds that hold their own routing level and nothing more.
#:
#: ``_place_junctions`` adds a Splitter with `canvas.add(stack_member)` and
#: ``_emit_piler_chain`` adds a Piler the same way, both at the default
#: ``solid=False``: they share the tile of the belts they join, so a crossing
#: band over them is a ban the game never asked for.
_BELT_INTEGRATED = frozenset({catalog.SPLITTER_ID, catalog.PILER_ID})


def _belt_id_for(spec: BuildSpec) -> int:
    """The spec's belt as a catalog id, defaulting the way freeform does."""
    return catalog.get_item_id(spec.belt_item_id) or 2001


def _belt_model_for(spec: BuildSpec) -> int:
    return catalog.building(_belt_id_for(spec)).model_index


def canvas_for(
    spec: BuildSpec,
    buildings: list[PlacedBuilding],
    *,
    belt_rules: catalog.BeltAltitudeRules,
    margin: int,
) -> _Canvas:
    """The composed buildings as a routing canvas, sized to their own extent.

    Each kind is registered the way the pass that BUILDS it registers it, and
    the differences are not cosmetic:

    * machines and power buildings are ``solid=True`` (``_emit_strip`` ~6575,
      ``_place_power`` ~15705), so ``_crossing_ban_levels`` writes the band
      from the ground to their collider's top into ``blocked``;
    * non-Tesla power buildings retain their planned collider-clearance halo,
      so cut routes cannot occupy ground outside the copied footprint;
    * belts, Splitters and Pilers are ``solid=False``, holding only their own
      level -- but a Splitter ALSO stakes ``canvas.guard`` with its collider
      cross (``_place_junctions`` ~13269), which ``_Canvas.free`` treats as a
      hard wall; a Piler stakes none, and freeform stakes none for it either;
    * SORTERS are appended with NO lattice reservation at all, exactly as
      ``_emit_sorter`` (~7170) does -- every collision sweep skips them, and
      banning their band here would cost the router paths the game allows;
    * Spray Coaters reserve their actual collider through
      ``_reserve_coater_belt_ban``. Their projected Splitter clearances are
      prepared once on the selected packing, before cut routing.

    Index order is the composed buildings list's own, because every ``_Port``
    and ``_Net`` indexes into ``canvas.buildings``.
    """
    tower = catalog.power_tower_building(spec.power_tower_item_id)
    canvas = _Canvas(
        belt_rules=belt_rules,
        sorter_tiers=_sorter_tiers_for(spec),
        sorter_stacks=_sorter_stacks_for(spec),
        lane_stacks=_lane_stacks_for(spec),
        power_building=tower,
    )
    power_halo = _power_reservation(tower) if tower.item_id != catalog.TESLA_TOWER_ID else None
    coaters: list[int] = []
    for b in buildings:
        if catalog.is_sorter(b.item_id):
            canvas.buildings.append(b)
        elif b.item_id == catalog.SPRAY_COATER_ID:
            coaters.append(len(canvas.buildings))
            canvas.buildings.append(b)
        elif catalog.is_belt(b.item_id) or b.item_id in _BELT_INTEGRATED:
            canvas.add(b)
            if b.item_id == catalog.SPLITTER_ID:
                # `_place_junctions` (~13269) stakes this beside every
                # `canvas.add`, and `_Canvas.free` treats `guard` as a hard
                # wall.  A Splitter reports no occupied tile -- `add` marks
                # nothing for it -- so without the guard a cut route runs
                # straight through its 2.38-unit collider cross.  Every member
                # of a stack stands on the host belt's own tile, which is why
                # freeform passes the belt's `(x, y)` with each member's own
                # `z`, model and yaw; here each composed member IS that member.
                canvas.guard.update(
                    junction.keepout_cells(b.x, b.y, int(b.z), model_index=b.model_index, yaw=b.yaw)
                )
        else:
            canvas.add(b, solid=True)
            if power_halo is not None and b.item_id == tower.item_id:
                x0, y0, x1, y1 = power_halo
                canvas.keep_out.update(
                    (b.x + dx, b.y + dy) for dx in range(x0, x1) for dy in range(y0, y1)
                )
    if coaters:
        belt_model = _belt_model_for(spec)
        for index in coaters:
            _reserve_coater_belt_ban(canvas, canvas.buildings[index], belt_model)
        # Every drop is exempt from every overlapping Coater ban: it is a
        # required positional addon connection whichever Coater owns the ban.
        for index in coaters:
            coater = canvas.buildings[index]
            drop = slots.addon_supply_cell(
                catalog.SPRAY_COATER_ID, x=coater.x, y=coater.y, z=coater.z, yaw=coater.yaw, area=1
            )
            canvas.belt_ban.pop((drop[0], drop[1]), None)
    min_x, min_y, max_x, max_y = Placement(buildings=tuple(buildings)).bounds
    canvas.limit = (min_x - margin, min_y - margin, max_x + margin, max_y + margin)
    return canvas


def _lane(buildings: Buildings, index: int) -> tuple[int, ...]:
    """The maximal contiguous x-run at ``index``'s own row, west to east.

    NOT the whole belt run reached through ``output_obj``: that run also takes
    in the north-south sorter drop columns spliced into it, and it can leave the
    row and come back.  What comes back here is one east-west segment -- the one
    ``index``'s own tile stands in.
    """
    records = buildings.all()
    head = index
    while True:
        predecessors = buildings.by_output_obj(head)
        if not predecessors:
            break
        predecessor = predecessors[-1]
        if not catalog.is_belt(records[predecessor].item_id):
            break
        head = predecessor
    run = [head]
    while True:
        onward = records[run[-1]].output_obj
        if onward is None or not catalog.is_belt(records[onward].item_id):
            break
        run.append(onward)
    # ONE CONTIGUOUS ROW of that run, the one the port's own tile stands in.
    # A run that leaves the row and comes back contributes two disjoint
    # east-west segments at the same y; the port belongs only to the segment
    # containing its own tile.
    row = records[index].y
    on_row = sorted((i for i in run if records[i].y == row), key=lambda i: records[i].x)
    at = on_row.index(index)
    low = at
    while low > 0 and records[on_row[low - 1]].x == records[on_row[low]].x - 1:
        low -= 1
    high = at
    while high + 1 < len(on_row) and records[on_row[high + 1]].x == records[on_row[high]].x + 1:
        high += 1
    return tuple(on_row[low : high + 1])


def _port(buildings: Buildings, index: int, machines: int) -> _Port:
    """The router's view of one boundary lane, attached at ``index``."""
    tiles = _lane(buildings, index)
    records = buildings.all()
    b = records[index]
    x0 = records[tiles[0]].x
    x1 = records[tiles[-1]].x
    # `_Port.at_tile` reads the k-th tap off as `x0 + k`, so the column span and
    # the tile list have to be the same lane.
    assert x1 - x0 + 1 == len(tiles), f"lane at {index} is not one contiguous row"
    return _Port(
        belt=index,
        x=b.x,
        y=b.y,
        x0=x0,
        x1=x1,
        tiles=tiles,
        machines=machines,
        z=int(b.z),
        cargo_domain=CargoDomain.UNSPRAYED,
    )


def _machines_behind(
    buildings: Buildings, block: BlockPlaced, index: int, fallback_count: int
) -> int:
    """Production machines behind one lane, for :attr:`_Port.machines`.

    Keep the exact ``recipe_id != 0`` predicate: the Buildings machine kind is
    deliberately coarser and also contains power nodes and belt addons.
    """
    records = buildings.all()
    strip = records[index].owner_strip
    stop = block.base + len(block.placement.buildings)
    if strip is None:
        return max(1, fallback_count)
    candidates = buildings.by_owner_strip(strip)
    return max(
        1,
        sum(
            1
            for candidate in candidates
            if block.base <= candidate < stop and records[candidate].recipe_id != 0
        ),
    )


def _block_of(blocks: list[BlockPlaced], index: int) -> int:
    """Which block a composed building index belongs to.

    ``blocks`` is built in packing order and each ``base`` is the running length
    of the composed list, so the bases ascend and the owning block is the last
    one that starts at or before ``index``.
    """
    return max(0, bisect.bisect_right([block.base for block in blocks], index) - 1)


def _corridor_evidence(evidence: PortAccessEvidence | None) -> str:
    """The counts that explain one unserved port claim, in one clause.

    ``options == 1`` is the signature of a middle lane head and is not a
    matching failure at all -- there was nothing to match; the same reading
    ``StrandedPort.options`` documents.  An unmatched demand can also carry no
    evidence, when nothing about it was enumerated.
    """
    if evidence is None:
        return "no candidate corridor"
    return f"held={evidence.held} wants={evidence.wanted} options={evidence.local_options}"


def _spent(deadline: float | None) -> bool:
    """Whether ``deadline`` has already passed; ``None`` never has."""
    return deadline is not None and time.monotonic() >= deadline


def _outer_ring(bounds: tuple[int, int, int, int]) -> list[Cell]:
    """Every ground cell on the rim of ``bounds``, as the reservation's boundary.

    This is the composition's answer to "where does a corridor LEAD?".  Inside a
    freeform block the boundary is the strip field's own rim, and a port that
    cannot reach it is a port whose belt can never be joined; here the rim of
    ``canvas.limit`` is the open ground outside every packed box, so a lane head
    that cannot reach it is walled in by the packing and by nothing else.

    Ground level only.  ``canvas.limit`` bounds x and y and says nothing about
    altitude, and a ramp up to a raised rim cell is a corridor the packing did
    not actually provide -- claiming it would let a walled-in port pass.
    """
    x0, y0, x1, y1 = bounds
    ring: list[Cell] = [(x, y, 0) for x in range(x0, x1 + 1) for y in (y0, y1)]
    ring.extend((x, y, 0) for y in range(y0 + 1, y1) for x in (x0, x1))
    return ring


#: The four von Neumann neighbours, spelled here rather than imported from
#: `freeform._STEPS`: this module already imports eleven freeform privates and
#: a two-line constant is not worth a twelfth.
_NEIGHBOURS = ((1, 0), (-1, 0), (0, 1), (0, -1))


def _protect_external_access(
    packing: _Packing, spec: BuildSpec, *, deadline: float | None
) -> frozenset[Cell]:
    """Keep a complete outside approach for each physical player-fed root.

    The validator owns the entry census: labels alone do not make internally
    sourced runs, junction branches or merge successors into player entries.
    Pending LaneFlow arrivals are also internal incidence, although their
    interblock belts have not yet been emitted. No item is inferred as an import.

    Search the actual packed canvas, at the integral planes occupied by each
    entry run, using both validator occupancy and the router's physical bans.
    One breadth-first forest per plane shares work between roots. Only selected
    paths to the rim are held, never a whole block perimeter or all free ground.
    A missing path refuses this packing; cancellation is not a geometric verdict.
    """
    if _spent(deadline):
        raise _PackingDeadline(packing)
    if not spec.external_inputs:
        return frozenset()
    canvas = packing.canvas
    placement = Placement(buildings=tuple(canvas.buildings))
    ctx = validate._context(
        placement,
        spec,
        validate.id_map(spec),
        256,
        canvas.belt_rules.max_z,
        canvas.belt_rules.vertical_construction,
    )
    occupancy: Collection[tuple[int, int, Fraction | int]] = ctx.occupancy
    if _spent(deadline):
        raise _PackingDeadline(packing)
    arrivals = {
        ctx.run_of[net.dst.belt]
        for net in packing.nets
        if net.src is not None and net.dst.belt in ctx.run_of
    }
    entries = {
        run: item
        for item, runs in validate._entry_runs(ctx).items()
        for run in runs
        if run not in arrivals
    }
    if _spent(deadline):
        raise _PackingDeadline(packing)
    if not entries:
        return frozenset()

    goals: dict[int, dict[Cell, set[int]]] = {}
    representable: set[int] = set()
    for run in entries:
        for index in ctx.runs[run].indices:
            if _spent(deadline):
                raise _PackingDeadline(packing)
            belt = placement.buildings[index]
            level = int(belt.z)
            if belt.z != level or not 0 <= level < canvas.levels:
                continue
            representable.add(run)
            for dx, dy in _NEIGHBOURS:
                cell = (belt.x + dx, belt.y + dy, level)
                if cell not in occupancy and canvas.free(cell):
                    goals.setdefault(level, {}).setdefault(cell, set()).add(run)

    bounds = canvas.limit
    assert bounds is not None
    pending = set(entries)
    protected: set[Cell] = set()
    for level, plane_goals in sorted(goals.items()):
        wanted = {cell: runs & pending for cell, runs in plane_goals.items() if runs & pending}
        if not wanted:
            continue
        parents: dict[Cell, Cell | None] = {}
        queue: deque[Cell] = deque()
        for x, y, _ in _outer_ring(bounds):
            if _spent(deadline):
                raise _PackingDeadline(packing)
            cell = (x, y, level)
            if cell not in occupancy and canvas.free(cell):
                parents[cell] = None
                queue.append(cell)
        while queue and wanted:
            if _spent(deadline):
                raise _PackingDeadline(packing)
            cell = queue.popleft()
            reached = wanted.pop(cell, None)
            if reached:
                pending.difference_update(reached)
                cursor: Cell | None = cell
                while cursor is not None and cursor not in protected:
                    if _spent(deadline):
                        raise _PackingDeadline(packing)
                    protected.add(cursor)
                    cursor = parents[cursor]
                # Other doorsteps of a served root need no independent path.
                wanted = {goal: runs - reached for goal, runs in wanted.items() if runs - reached}
            x, y, z = cell
            for dx, dy in _NEIGHBOURS:
                neighbour = (x + dx, y + dy, z)
                if (
                    neighbour not in parents
                    and neighbour not in occupancy
                    and canvas.free(neighbour)
                ):
                    parents[neighbour] = cell
                    queue.append(neighbour)
        if not pending:
            break
    if pending:
        raise _ExternalAccessRefused(
            packing,
            tuple(
                f"flow.external_entry_reachable: external input {entries[run]!r}: "
                f"block {_block_of(packing.blocks, ctx.runs[run].head)} "
                f"lane head {ctx.runs[run].head}: "
                + (
                    "no legal integral same-plane approach from outside this packed canvas"
                    if run in representable
                    else "external approach is unrepresentable: no integral belt tile "
                    "within the routing technology's altitude range"
                )
                for run in sorted(pending)
            ),
        )

    # A future Splitter must not put its collider across the player's reserved
    # belt path. Invert the existing stack keepout, not an invented moat.
    junction_bans: set[Cell] = set()
    for level in range(canvas.levels):
        if _spent(deadline):
            raise _PackingDeadline(packing)
        offsets = {
            offset
            for member in junction.make_splitter_stack(
                0, 0, level, first_index=0, carry_direction=(0, 1)
            )
            for offset in junction.keepout_cells(
                0, 0, int(member.z), model_index=member.model_index, yaw=member.yaw
            )
        }
        by_plane: dict[int, list[tuple[int, int]]] = {}
        for dx, dy, z in offsets:
            by_plane.setdefault(z, []).append((dx, dy))
        for x, y, z in protected:
            if _spent(deadline):
                raise _PackingDeadline(packing)
            junction_bans.update((x - dx, y - dy, level) for dx, dy in by_plane.get(z, ()))
    if _spent(deadline):
        raise _PackingDeadline(packing)
    # Publish only a complete proof. belt_ban also prevents a junction-owned
    # start exception from treating this permanent guard as its own branch dock.
    canvas.guard.update(protected)
    for x, y, z in protected:
        canvas.belt_ban.setdefault((x, y), set()).add(z)
    canvas.junction_ban.update(junction_bans)
    return frozenset(protected)


def _free_doorstep(canvas: _Canvas, cell: Cell) -> frozenset[Cell]:
    """The free cells a belt can stand on beside ``cell``.

    The lane head's OWN tile is occupied -- it is a belt -- so a goal set
    naming it would be a goal no search can settle.  What a trunk actually has
    to reach is a free cell touching it, which is exactly the `access_cells`
    set `_reserve_port_access` enumerates for that demand.

    Filtering through :meth:`_Canvas.free` is also what keeps every goal inside
    the reservation's ``bounds``: `free` refuses any cell outside
    ``canvas.limit``, and `pack_with_access` passes that same ``canvas.limit``
    as ``bounds``.  `_astar` exempts only its START cells from the box, so a
    goal outside it would be silently unreachable and would convict a demand
    for geometry it does not have.
    """
    return frozenset(
        neighbour
        for dx, dy in _NEIGHBOURS
        for neighbour in ((cell[0] + dx, cell[1] + dy, cell[2]),)
        if canvas.free(neighbour)
    )


def _trunk_goals(
    packing: _Packing, demands: Sequence[PortAccessDemand]
) -> tuple[
    dict[PortAccessDemand, frozenset[Cell]],
    dict[PortAccessDemand, frozenset[PortAccessDemand]],
]:
    """Each cut lane's demand, pointed at the doorstep of its own partners.

    ``demands`` is the caller's own `_port_access_inventory(packing.nets)`
    output rather than a second derivation of it: the inventory walks and sorts
    every net, and the caller already needs the tuple to hand to
    `_reserve_port_access`.  It is pure, so the two agreed -- but agreeing
    twice costs the wall :data:`RESERVE_WALL_SHARE` exists to protect.

    THIS IS WHAT MAKES THE ORACLE ABLE TO SAY NO.  Every demand
    `_port_access_inventory` builds from a composed packing is an
    `INTERNAL_DEPARTURE` or an `INTERNAL_ARRIVAL`, both `reaches_boundary`
    False, so `_reserve_port_access` admits every local option unprobed and
    `assignment_boundary_cut` returns `None` on every assignment -- the v2
    gate committed rung 0 with `missing` 0 on all five composing cells while
    the router refused up to 28 cut lanes on the same canvas
    (`docs/superpowers/evidence/2026-09-07-hierarchical-v2/gate.md` §6).

    The question this asks instead is the one the router answers: can this
    lane head's corridor reach the far end of the trunk it is an end of.

    WHAT IS DELIBERATELY WEAKER THAN ROUTING.  A demand is deduplicated by
    `(cell, kind)`, so one lane head can be the end of several nets; the goal
    is the UNION of its partners' doorsteps, which asks "can it reach AT LEAST
    ONE of them" rather than all of them.  That is a necessary condition, not
    a sufficient one: it can still admit a rung the router then refuses, but
    it can no longer admit a rung on which a lane head is sealed away from
    every partner it has.  Probing per partner would multiply the A* count by
    the fan-out for a claim the router re-checks anyway.

    Return endpoint ownership alongside geometry. A goal touching another
    corridor never makes that corridor a partner; only these packing nets do.
    """
    by_cell: dict[Cell, list[PortAccessDemand]] = {}
    for demand in demands:
        by_cell.setdefault(demand.cell, []).append(demand)
    goals: dict[PortAccessDemand, set[Cell]] = {demand: set() for demand in demands}
    partners: dict[PortAccessDemand, set[PortAccessDemand]] = {demand: set() for demand in demands}
    for net in packing.nets:
        if net.prelinked or net.src is None:
            continue
        src_cell = (net.src.x, net.src.y, net.src.z)
        dst_cell = (net.dst.x, net.dst.y, net.dst.z)
        src_door = _free_doorstep(packing.canvas, src_cell)
        dst_door = _free_doorstep(packing.canvas, dst_cell)
        for demand in by_cell.get(src_cell, ()):
            goals[demand].update(dst_door)
            partners[demand].update(by_cell.get(dst_cell, ()))
        for demand in by_cell.get(dst_cell, ()):
            goals[demand].update(src_door)
            partners[demand].update(by_cell.get(src_cell, ()))
    # A demand whose every partner is walled in raises no goal rather than an
    # EMPTY one: an empty goal set is a search that can never settle, which
    # would convict the demand for its PARTNER's pocket.  The router names
    # that lane itself, with the class that actually stopped it.
    return (
        {demand: frozenset(cells) for demand, cells in goals.items() if cells},
        {demand: frozenset(owners) for demand, owners in partners.items() if owners},
    )


def _pack_at(
    placements: list[Placement],
    flows: list[LaneFlow],
    spec: BuildSpec,
    *,
    gap: int,
    belt_rules: catalog.BeltAltitudeRules,
    margin: int,
    envelope: BandPolicySearchEnvelope,
) -> _Packing:
    """Lay the blocks out at one ``gap`` and build the router's view of them.

    Every rung of the ladder starts here, from the original placements, because
    a packing cannot be widened in place: the offsets, the canvas and every
    ``_Net``'s port tiles are all derived from the gap.
    """
    normalized = [_normalize(p) for p in placements]
    offsets, _width, _height = pack_blocks(
        [(w, h) for _, w, h in normalized], gap, envelope=envelope
    )

    buildings: list[PlacedBuilding] = []
    blocks: list[BlockPlaced] = []
    for i, ((placement, w, h), (ox, oy)) in enumerate(zip(normalized, offsets, strict=True)):
        base = len(buildings)
        buildings.extend(_translate(placement, base, ox, oy))
        blocks.append(BlockPlaced(i, placement, base, (ox, oy), w, h))

    building_index = Buildings(buildings)

    fallback_machine_counts = [
        sum(building.recipe_id != 0 for building in block.placement.buildings) for block in blocks
    ]
    canvas = canvas_for(spec, buildings, belt_rules=belt_rules, margin=margin)

    nets: list[_Net] = []
    for ordinal, flow in enumerate(flows):
        src_block = blocks[flow.src.block]
        dst_block = blocks[flow.dst.block]
        src_index = flow.src.building + src_block.base
        dst_index = flow.dst.building + dst_block.base
        nets.append(
            _Net(
                src=_port(
                    building_index,
                    src_index,
                    _machines_behind(
                        building_index,
                        src_block,
                        src_index,
                        fallback_machine_counts[flow.src.block],
                    ),
                ),
                dst=_port(
                    building_index,
                    dst_index,
                    _machines_behind(
                        building_index,
                        dst_block,
                        dst_index,
                        fallback_machine_counts[flow.dst.block],
                    ),
                ),
                item=flow.item,
                # The strip fields carry the BLOCK indices here: they are the
                # router's stable identity for a net, and the only thing a
                # returned `NetFailure` can be read back through to say which
                # cut failed.
                net_id=NetId(
                    source_strip=flow.src.block,
                    destination_strip=flow.dst.block,
                    item=flow.item,
                    role=NetRole.INTERNAL,
                    ordinal=ordinal,
                ),
            )
        )
    return _Packing(buildings, blocks, canvas, nets)


def _merge_access_evidence(
    goal_driven: Sequence[PortAccessEvidence],
    topped: Sequence[PortAccessEvidence],
) -> tuple[PortAccessEvidence, ...]:
    """One entry per demand, each FIELD taken from the call that can answer it.

    `_reserve_port_access` emits exactly one `PortAccessEvidence` per demand in
    its own `missing`, so the top-up's demand set is a strict SUBSET of the
    goal-driven call's -- and a plain dict union would therefore resolve to ONE
    call's entry for every key and drop the other's wholesale, whichever way it
    is ordered.  The two calls are authoritative about different fields:

    * ``local_options`` / ``reachable_options`` are the TOP-UP's.  It enumerated
      on the ground as it now stands, with the partial's corridors staked; the
      goal-driven call counted on a canvas cleared of every corridor, which is a
      canvas that no longer exists.  This is also the only field that reaches a
      reader: `_corridor_evidence` prints `options=<local_options>`.
    * ``frontier`` / ``exhaustive`` are the GOAL-DRIVEN call's.  They are the
      trunk probe's findings and the local-only top-up cannot produce them: it
      runs unprobed, so it reports an empty wall and ``exhaustive=False``, which
      would read as "nobody looked" rather than "we looked and it is sealed".

    ``held``/``wanted`` are the same constants in both.  An entry only the
    goal-driven call raised is kept verbatim: that demand is one the top-up
    SERVED, so there is no fresher count to take and nothing to merge.
    """
    fresh = {evidence.demand: evidence for evidence in topped}
    merged = [
        replace(
            entry,
            local_options=fresh[entry.demand].local_options,
            reachable_options=fresh[entry.demand].reachable_options,
        )
        if entry.demand in fresh
        else entry
        for entry in goal_driven
    ]
    raised = {entry.demand for entry in goal_driven}
    merged.extend(entry for entry in topped if entry.demand not in raised)
    return tuple(merged)


def _top_up_partial(
    canvas: _Canvas,
    committed: PortAccessReservation,
    *,
    boundary: Sequence[Cell] | None,
    bounds: tuple[int, int, int, int] | None,
    deadline: float | None,
) -> PortAccessReservation:
    """Give the demands a partial left missing the local-only oracle's corridor.

    THE PARTIAL IS BETTER GROUND WHERE IT SPEAKS AND STRICTLY WORSE WHERE IT IS
    SILENT.  Before the matcher committed partials it gave up wholesale, and
    `pack_with_access` re-asked `_reserve_port_access` WITHOUT `goals` for every
    demand -- the local-only oracle -- which staked a corridor for each one.
    Committing a partial deleted that fallback for exactly the demands the
    partial's own survey convicted, and `_route_all` then met each of them as
    `no port access corridor (held=0 wants=1)`: one unroutable cut per missing
    demand, which is how `titanium-glass/all-products` went from wiring all 26
    of its cut lanes to refusing at the router with 4 unrouted cuts.

    So the partial's corridors are KEPT and the demands it left missing are
    asked again locally.  Three things this must not do:

    * It must not re-assign a demand the partial already served -- `held` says
      so, and the union below prefers the partial's own pair either way.
    * It must not report a VERDICT.  `converged` stays False however complete
      the merged answer looks, so `reservation_degraded == 0` keeps its single
      meaning ("the matcher converged") and the rung still counts as both
      partial and degraded.
    * It must not cost the caller the partial.  A top-up that runs out of the
      rung's clock degrades to the partial as it stood: `_reserve_port_access`
      restores the canvas to its entry snapshot on every raising path, and that
      snapshot IS the partial, so both the object and the canvas fall back
      together.

    The canvas union is `_reserve_port_access`'s own `held` contract; see its
    docstring for why a second call without it would wipe the first's corridors
    off the canvas the router reads.

    THE `assigned` UNION BELOW IS THE AUTHORITATIVE ONE.  `_reserve_port_access`
    computes its own -- it has to, because the canvas union and the `missing`
    it derives both depend on it -- but this one is recomputed from
    `committed.assigned` rather than read off `topped`, so a future change to
    `held`'s ordering or merge semantics in freeform cannot silently change what
    the rung commits.  The two are belt and braces, and THIS is the belt.

    A TOPPED-UP RUNG COMPLETES, AND THEREFORE ENDS THE GAP LADDER, at
    `pack_with_access`'s `if reservation.complete: return candidate`.  That is
    inherent in the property this function exists for -- an empty `missing` --
    and it is the pre-Task-1 shape restored: the wholesale local-only fallback
    also produced a complete reservation and also short-circuited, which is how
    v3's titanium-glass committed at gap 2 and wired all 26 cut lanes.  The
    consequence for a reader of the stats line is that `reservation_degraded`
    and `reservation_partial` are ladder totals over FEWER rungs than before, so
    a fall from 5 to 1 is the ladder stopping sooner and NOT the matcher
    converging more often.

    THE TOP-UP IS THE LOCAL-ONLY ORACLE ONLY WHILE `boundary` IS None.
    `boundary` is forwarded exactly as the wholesale `else` branch forwards it,
    which is the consistency worth having, and `pack_with_access` computes it as
    None today because no composed demand answers `reaches_boundary`.  The day
    the v2 gate's lever 1 gives the composer real boundary ports, `probed`
    becomes True here too: this call would build a grid and run an A* per
    option, and it would stop being the cheap unprobed pass the wall budget
    assumes.  Re-measure the rung cost on that day.
    """
    if not committed.missing:
        return committed
    staked = dict(committed.assigned)
    try:
        topped = _reserve_port_access(
            canvas,
            committed.missing,
            boundary=boundary,
            bounds=bounds,
            cancelled=partial(_spent, deadline),
            deadline=deadline,
            held=staked,
        )
    except _PreparationDeadline:
        return committed
    return PortAccessReservation(
        assigned=(
            *committed.assigned,
            *((demand, corridor) for demand, corridor in topped.assigned if demand not in staked),
        ),
        missing=topped.missing,
        evidence=_merge_access_evidence(committed.evidence, topped.evidence),
        converged=False,
    )


def pack_with_access(
    placements: list[Placement],
    flows: list[LaneFlow],
    spec: BuildSpec,
    *,
    belt_rules: catalog.BeltAltitudeRules,
    deadline: float | None,
    margin: int,
    envelope: BandPolicySearchEnvelope,
    gap: int = MIN_GAP,
    external_spec: BuildSpec | None = None,
) -> PackedCanvas:
    """Pack at widening gaps until every port has a corridor, and commit that one.

    ``external_spec`` supplies settled machine incidence and declared player
    inputs when those differ from the packing spec. First reserve the actual
    internal port corridors, then find complete external paths to the canvas rim
    without taking those corridors. External protection never degrades to a
    local doorstep check.
    If every attempted packing lacks such a path, raise _ExternalAccessRefused.

    THE GAP IS A SEARCHED QUANTITY, not a constant.  Every rung of
    :data:`GAP_LADDER` at or above ``gap`` is packed, and the reservation is
    asked whether every lane head can still be given a corridor of its own.
    The first rung it answers yes for is committed.  The canvas rim goes with
    the question only when some demand's kind could actually be probed against
    it -- see the comment at the call.

    Stake every port's approach before any path commits, the way
    `_prepare_routing_problem` does.  A boundary lane's end tile has at most
    three free neighbours and often one; without the reservation an earlier
    net's path takes the last one and every later net using that port is handed
    an empty start set -- a search that expands nothing and so registers no
    congestion for the negotiation to price.

    UNDER A BOUNDED SHARE OF THE ROUTE'S CLOCK.  The reservation enumerates
    every candidate corridor of every demand and then solves a JOINT MATCHING
    over them, so its cost grows with the interface rather than being a fixed
    preamble; a ladder multiplies that by its rungs.  The FIRST rung is what a
    ladderless composer would have done and runs on ``deadline`` itself -- all
    but its RESERVATION, which is capped at :data:`RESERVE_WALL_SHARE` because
    the trunk goals turned that reservation into an A* per option per demand,
    and which degrades to the local-only oracle on the caller's full clock
    rather than refusing when that cap bites.  Every rung after the first is
    speculative and is funded out of :data:`LADDER_WALL_SHARE` of the wall left
    on entry, so that ``_route_all`` is never handed a clock the search for a
    wider canvas has already spent.  The ladder stops the moment that share
    runs out:

    * with a rung already judged, the best one in hand is returned -- it is a
      real packing with a real verdict, and spending the router's wall to find
      a wider canvas nobody can then route on helps nobody;
    * with NO rung judged, :class:`_PackingDeadline` carries the packing out to
      the caller, which owes its own caller a refusal naming every cut.

    AND DEGRADING TO v2's ORACLE RATHER THAN ACTING ON AN UNUSABLE ANSWER.  A
    rung whose trunk-goal reservation either outran rung 0's share or came back
    having assigned NOTHING AT ALL is re-asked LOCAL-ONLY on that rung's own
    clock, and it is the local answer the rung is judged by.  Both triggers
    take one path so there is a single behaviour to reason about, and
    :attr:`PackedCanvas.degraded` counts how often it fired -- without which a
    committed rung reporting no missing corridors cannot be told apart from one
    whose oracle was thrown away.

    ``gap`` is a FLOOR, not the gap: a caller that knows two blocks cannot be
    laid closer than 8 passes 8 and the ladder starts there.  When the floor is
    above every rung the floor itself is the only rung, since a ladder must
    always try at least once.
    """
    # `pack_blocks` clamps to MIN_GAP, so no rung can collide even if a caller
    # asks for a floor below it.
    rungs = tuple(rung for rung in GAP_LADDER if rung >= gap) or (max(gap, MIN_GAP),)
    entered = time.monotonic()
    ladder_deadline = (
        None if deadline is None else entered + (deadline - entered) * LADDER_WALL_SHARE
    )
    best: PackedCanvas | None = None
    external_refusal: _ExternalAccessRefused | None = None
    degraded = 0
    partial_rungs = 0
    for position, rung in enumerate(rungs):
        # The FIRST rung is unconditional and runs on the caller's own clock:
        # it is what a ladderless composer would have done, and a caller that
        # entered with a spent clock is still owed a packing to name its cuts
        # from.  Only the rungs after it are bet on `LADDER_WALL_SHARE`.
        first = position == 0
        if not first and _spent(ladder_deadline):
            break
        rung_deadline = deadline if first else ladder_deadline
        packing = _pack_at(
            placements,
            flows,
            spec,
            gap=rung,
            belt_rules=belt_rules,
            margin=margin,
            envelope=envelope,
        )
        bounds = packing.canvas.limit
        assert bounds is not None  # canvas_for always sets it
        demands = _port_access_inventory(packing.nets).demands
        # The cut inventory still describes internal departures/arrivals.
        # Composition ALSO owes player-facing entries, protected after this
        # matching by complete paths that avoid its reserved internal corridors.
        # Internal demands keep their partner goals rather than being redirected
        # to the outer rim. A future boundary-aware demand still receives it.
        boundary = _outer_ring(bounds) if any(d.kind.reaches_boundary for d in demands) else None
        goals, partners = _trunk_goals(packing, demands)
        # Rung 0's reservation is funded out of `RESERVE_WALL_SHARE` and
        # DEGRADES rather than refusing: see the constant's docstring.
        reserve_deadline = (
            rung_deadline
            if not first or rung_deadline is None
            else min(
                rung_deadline,
                entered + (rung_deadline - entered) * RESERVE_WALL_SHARE,
            )
        )
        goal_driven: PortAccessReservation | None
        try:
            goal_driven = _reserve_port_access(
                packing.canvas,
                demands,
                boundary=boundary,
                bounds=bounds,
                # `partial` rather than a lambda: `reserve_deadline` is a loop
                # variable, and a closure over it would read whichever rung ran
                # last rather than the one that asked.
                cancelled=partial(_spent, reserve_deadline),
                deadline=reserve_deadline,
                goals=goals,
                partners=partners,
            )
        except _PreparationDeadline:
            if not first:
                if best is None:
                    raise _PackingDeadline(packing) from None
                break
            # RUNG 0 ONLY: the trunk probe outran its own share.  Fall through
            # to the degradation below, which is the same one an unusable
            # answer takes -- one behaviour to reason about, not two.
            goal_driven = None
        # TWO WAYS FOR THE TRUNK QUESTION TO COME BACK UNUSABLE, ONE FALLBACK.
        # The second is an assignment of NOTHING AT ALL while there were
        # demands to assign, which is not a geometric verdict: a canvas that
        # really walls in every lane head still leaves the ones it does not.
        # `_match_access_corridors` no longer returns `{}` wholesale merely
        # because its validate/cut loop runs out of rounds (`_ACCESS_CUT_ROUNDS`)
        # -- since Task 1 it COMMITS the partial its own survey left unconvicted
        # instead.  Only TWO sites return `{}` DIRECTLY: the initial rank solve
        # coming back neither OPTIMAL nor FEASIBLE, and no demand having a
        # single free option AT ALL while demands were raised (the SAME site
        # with NO demands is the CONVERGED empty answer to an empty question,
        # not a give-up -- see the `not demands` guard below).  Every other
        # give-up -- an infeasible tie solve, a failed fallback rank re-solve,
        # an empty cut-variable set, or the cut loop running out of rounds --
        # calls `surrender()`, and reaching `surrender()` is NECESSARY but NOT
        # SUFFICIENT for `{}`: it hands back the largest partial it saw, minus
        # what its own survey convicts, and is `{}` only when no partial was
        # ever recorded, no `survey` callback was passed at all, the survey is
        # cut short by ITS OWN deadline, or the survey convicts every demand
        # that partial held (see `surrender` in freeform.py).  Otherwise it
        # hands back a non-empty, `converged=False` partial.  See the paragraph
        # below for what a partial commit means here.  `assignment_boundary_cut`
        # -- live for the first
        # time here, because the goals set `probed` -- asks that EVERY
        # corridor stay reachable with every OTHER corridor's cells forbidden,
        # which is strictly stronger than what `_route_all` then does with
        # rip-up and negotiation; the belt3 measurement had it discard all 102
        # demands on a canvas the router still wired 65 of 89 cuts on.  An
        # empty reservation stakes NO corridors, so acting on it would leave
        # the router worse off than v2's local-only oracle -- and the whole
        # contract of this lever (see `RESERVE_WALL_SHARE`) is that its worst
        # case is v2's behaviour.  The trigger is deliberately the narrow,
        # obviously-correct one rather than a tuned threshold.
        #
        # A PARTIAL IS GROUND, NOT A VERDICT.  Since the matcher stopped giving
        # up wholesale it hands back the corridors its own survey did not
        # convict, and those are strictly better ground for `_route_all` than
        # the local-only answer -- the corridors are staked where the trunk
        # probe said they reach.  It is better ground only WHERE IT SPEAKS,
        # though: the demands its survey convicted got no corridor from either
        # oracle and the router met them as `held=0 wants=1`, so
        # `_top_up_partial` asks the local-only oracle for exactly those and
        # merges both answers.  What a partial is NOT is an answer to the
        # ladder's question, so it counts as degraded as well as partial, and
        # `reservation_degraded == 0` keeps its one meaning.  An assignment of
        # NOTHING AT ALL while there were demands is still the wholesale
        # give-up Ruling R7 discards: it stakes no corridors, so acting on it
        # would leave the router worse off than v2's local-only oracle.
        if (
            goal_driven is not None
            and goal_driven.converged
            and (goal_driven.assigned or not demands)
        ):
            reservation = goal_driven
        elif goal_driven is not None and goal_driven.assigned:
            partial_rungs += 1
            degraded += 1
            reservation = _top_up_partial(
                packing.canvas,
                goal_driven,
                boundary=boundary,
                bounds=bounds,
                deadline=rung_deadline,
            )
        else:
            degraded += 1
            try:
                reservation = _reserve_port_access(
                    packing.canvas,
                    demands,
                    boundary=boundary,
                    bounds=bounds,
                    cancelled=partial(_spent, rung_deadline),
                    deadline=rung_deadline,
                )
            except _PreparationDeadline:
                if best is None:
                    raise _PackingDeadline(packing) from None
                break
        # The actual internal matcher owns scarce departure/arrival cells.
        # _Canvas.free makes their selected corridors hard obstacles to the
        # external forest; an external root must take a longer escape rather
        # than consume the only approach an internal port can use.
        try:
            external_access = _protect_external_access(
                packing,
                spec if external_spec is None else external_spec,
                deadline=rung_deadline,
            )
        except _ExternalAccessRefused as refusal:
            external_refusal = refusal
            continue
        except _PackingDeadline:
            if best is None:
                raise
            break
        candidate = PackedCanvas(
            *packing,
            reservation=reservation,
            gap=rung,
            degraded=degraded,
            partial=partial_rungs,
            external_access=external_access,
        )
        # A TOPPED-UP PARTIAL REACHES HERE COMPLETE, so a rung that committed
        # one ENDS THE LADDER.  That is the pre-Task-1 shape: the wholesale
        # local-only fallback was complete too and short-circuited the same way.
        # It does mean `degraded`/`partial_rungs` are totals over fewer rungs
        # than they were between Task 1 and Task 4b -- a fall in
        # `reservation_partial` is the ladder stopping sooner, not the matcher
        # converging more often.  See `_top_up_partial`.
        if reservation.complete:
            return candidate
        # STRICTLY fewer, so the NARROWEST of the equally-bad rungs wins: a
        # wider packing that serves no more ports only spends physical extent.
        if best is None or len(reservation.missing) < len(best.reservation.missing):
            best = candidate
    if best is None:
        assert external_refusal is not None
        raise external_refusal
    # `best` may be an EARLIER rung than the last one the ladder judged, and
    # `degraded` is the ladder's total rather than that rung's own -- so it is
    # stamped on here rather than read off the candidate.
    return replace(best, degraded=degraded, partial=partial_rungs)


def _budget_refusal(packing: _Packing) -> ComposeResult:
    """Every cut of ``packing`` reported unwired under the router's budget word.

    `_reserve_port_access` puts back the reservations and corridors it cleared
    and raises `_PreparationDeadline` when the deadline is caught outside a
    survey; `_prepare_routing_problem` lets that unwind to whoever owns the
    budget.  A deadline caught MID-SURVEY instead returns NORMALLY, with both
    canvas dicts left cleared (never restored) and the reservation as the
    ordinary wholesale give-up -- `assigned` empty, `missing` every demand,
    `converged` False.  Here the caller wants a REFUSAL, so the cuts are named
    instead -- an unwired entry lane the composer swallowed is a block that
    starves, convicted many stages later with no way back.
    """
    budget_failures = tuple(
        f"{net.item}: block {net.net_id.source_strip} -> "
        f"block {net.net_id.destination_strip}: {DetailedRouteStatus.BUDGET.name}"
        for net in packing.nets
        if net.net_id is not None
    )
    return ComposeResult(
        Placement(
            buildings=tuple(packing.canvas.buildings), description="hierarchical composition"
        ),
        packing.blocks,
        0,
        budget_failures or ("composition preparation: BUDGET",),
        # Power infill never runs on this path -- the ladder expired before
        # `_route_all` did -- so every one of these IS an unrouted cut.
        unrouted_cuts=len(packing.nets),
    )


class _CompositionSettlement:
    """Settle disposable complete candidates under the original hierarchy clocks."""

    def __init__(
        self,
        spec: BuildSpec,
        policy: BandPolicy,
        belt_rules: catalog.BeltAltitudeRules,
        deadline: float | None,
        *,
        external_access: frozenset[Cell] = frozenset(),
    ) -> None:
        self.spec = spec
        self.policy = policy
        self.belt_rules = belt_rules
        self.deadline = deadline
        self.external_access = external_access
        self.attempts = 0
        self.refusals = 0
        self.reuses = 0
        self.wall_s = 0.0
        self._refused: list[
            tuple[Placement, tuple[frozenset[NetId] | None, ...], RouteSettlementRefused]
        ] = []

    def __call__(
        self, canvas: _Canvas, owners: tuple[frozenset[NetId] | None, ...]
    ) -> RouteSettlement:
        started = time.monotonic()
        self.attempts += 1
        try:
            with physical_flow.reuse_certificates():
                return self._settle(canvas, owners)
        except Exception as error:
            return RouteSettlementCrashed(error, error.__traceback__)
        finally:
            self.wall_s += time.monotonic() - started

    def _settle(
        self, canvas: _Canvas, owners: tuple[frozenset[NetId] | None, ...]
    ) -> RouteSettlement:
        if _spent(self.deadline):
            return RouteSettlementCancelled("routing admission")
        # These checks judge the fully emitted topology, before power or cleanup
        # changes its aligned building identities. Passing is not certification.
        raw = Placement(buildings=tuple(canvas.buildings))
        admission = validate.routing_admission(
            raw,
            self.spec,
            belt_rules=self.belt_rules,
            cancelled=partial(_spent, self.deadline),
        )
        if admission is None or _spent(self.deadline):
            return RouteSettlementCancelled("routing admission")
        if admission:
            # Cleanup may remove a sealing wall or change a capacity estimate's
            # topology. Reuse its exact initial eligibility gate: when no leaf
            # is prunable, completion returns the raw topology unchanged.
            # Otherwise defer to accepted cleanup and final certification rather
            # than assuming every raw finding survives an arbitrary removal.
            cancelled = partial(_spent, self.deadline)
            try:
                protected = finalize._required_external_input_belts(
                    raw, self.spec, cancelled=cancelled
                )
                if finalize._prunable_open_belts(
                    raw, protected_roots=protected, cancelled=cancelled
                ):
                    admission = ()
            except finalize.ProjectionCancelled:
                return RouteSettlementCancelled("routing admission")
            if _spent(self.deadline):
                return RouteSettlementCancelled("routing admission")
        if admission:
            self.refusals += 1
            return RouteSettlementRefused(
                "composed placement failed routing admission: "
                + "; ".join(
                    f"{failure.finding.check}: {failure.finding.message}" for failure in admission
                ),
                _failure_support_owners(tuple(failure.support for failure in admission), owners),
            )
        if _spent(self.deadline):
            return RouteSettlementCancelled("power infill")
        # A tower's ground footprint cannot consume even an elevated player
        # approach. Add this only after routing, so ground belts remain free
        # to pass underneath elevated access while they are being selected.
        canvas.guard.update((x, y, 0) for x, y, _ in self.external_access)
        try:
            infill_sites, unpowered = plan_power_infill(
                canvas, policy=self.policy, cancelled=partial(_spent, self.deadline)
            )
        except _PreparationDeadline:
            return RouteSettlementCancelled("power infill")
        except _Unpowerable as error:
            self.refusals += 1
            return RouteSettlementRefused(f"composition power infill: {error}", None)
        if unpowered:
            self.refusals += 1
            return RouteSettlementRefused(
                "power.coverage: no legal linked infill covers composed tiles "
                + ", ".join(f"({x},{y})" for x, y in unpowered),
                None,
                power_uncovered=len(unpowered),
            )
        try:
            _place_power(canvas, infill_sites)
        except _Unpowerable as error:
            self.refusals += 1
            return RouteSettlementRefused(f"composition power infill: {error}", None)
        # Infill siting depends on global free space/connectivity. Until that
        # dependency is available explicitly, its cause is unknown, not empty.
        owners = (*owners, *(None for _ in range(len(canvas.buildings) - len(owners))))
        if _spent(self.deadline):
            return RouteSettlementCancelled("global slots")
        try:
            placement = Placement(
                buildings=slots.assign_sorter_slots(tuple(canvas.buildings)),
                description="hierarchical composition",
            )
        except slots.SlotUndetermined as error:
            self.refusals += 1
            return RouteSettlementRefused(
                f"a composed link's slot could not be derived: {error}",
                None,
                power_infill=len(infill_sites),
            )
        if _spent(self.deadline):
            return RouteSettlementCancelled("cleanup")
        for previous, previous_owners, refusal in self._refused:
            if placement == previous and owners == previous_owners:
                self.reuses += 1
                return refusal
        prepared = finalize.prepare_placement_completion(
            placement,
            self.spec,
            self.policy,
            belt_rules=self.belt_rules,
            expect_power=True,
            deadlines=finalize.PlacementCompletionDeadlines(self.deadline, self.deadline, None),
        )
        if isinstance(prepared, finalize.PlacementCompletionCancelled):
            return RouteSettlementCancelled(prepared.phase)
        if isinstance(prepared, finalize.PlacementProjectionRefused):
            witnesses = prepared.refusal.witnesses
            implicated = _projection_failure_owners(prepared, owners)
            refused = RouteSettlementRefused(
                f"composed placement refused finalization: {prepared.refusal}",
                implicated,
                witnesses,
                len(infill_sites),
                interior_detours=_projection_interior_detours(prepared, placement, owners),
            )
        elif isinstance(prepared, finalize.PlacementProjectionReady):
            completed = finalize.complete_placement(prepared)
            if isinstance(completed, finalize.PlacementCompleted):
                return RouteSettlementCompleted(completed, len(infill_sites))
            if isinstance(completed, finalize.PlacementCertificationExpired):
                return RouteSettlementCancelled("certification")
            if not isinstance(completed, finalize.PlacementInvalid):
                raise AssertionError("unknown placement completion result")
            # Cleanup can legitimately defer raw admission. The final rejection
            # still belongs to its physical route context, not an unknown cause.
            admission = validate.routing_admission(
                completed.candidate,
                self.spec,
                belt_rules=self.belt_rules,
                cancelled=partial(_spent, self.deadline),
            )
            if admission is None:
                return RouteSettlementCancelled("routing feedback")
            supported = tuple(failure.finding for failure in admission)
            implicated = (
                _failure_support_owners(
                    tuple(failure.support for failure in admission),
                    owners,
                    completed.survivor_indices,
                    completed.link_dependencies,
                )
                if all(failure in supported for failure in completed.report.errors)
                else None
            )
            if _spent(self.deadline):
                return RouteSettlementCancelled("routing feedback")
            refused = RouteSettlementRefused(
                "composed placement failed validation: "
                + "; ".join(
                    f"{failure.check}: {failure.message}" for failure in completed.report.errors[:3]
                ),
                implicated,
                power_infill=len(infill_sites),
            )
        else:
            raise AssertionError("unknown placement preparation result")
        self.refusals += 1
        self._refused.append((placement, owners, refused))
        return refused


def _projection_interior_detours(
    prepared: finalize.PlacementProjectionRefused,
    placement: Placement,
    owners: tuple[frozenset[NetId] | None, ...],
) -> tuple[RouteInteriorDetour, ...]:
    """Recover owned raw belt support, without inverting a projected frame."""
    indices = {
        index if prepared.survivor_indices is None else prepared.survivor_indices[index]
        for witness in prepared.refusal.witnesses
        for index in witness.failure.buildings
    }
    for dependency in prepared.link_dependencies:
        if dependency.survivor_index in indices:
            indices.update(dependency.traversed_indices)
    detours = []
    for index in sorted(indices):
        building = placement.buildings[index]
        contributors = owners[index]
        if not contributors or not catalog.is_belt(building.item_id):
            continue
        # A fractional ramp is between lattice levels. Both are merely useful
        # positive alternatives; neither is an unconditional collision fact.
        detours.append(
            RouteInteriorDetour(
                contributors,
                frozenset(
                    (building.x, building.y, level)
                    for level in (math.floor(building.z), math.ceil(building.z))
                ),
            )
        )
    return tuple(detours)


def _projection_failure_owners(
    prepared: finalize.PlacementProjectionRefused,
    owners: tuple[frozenset[NetId] | None, ...],
) -> frozenset[NetId] | None:
    """Translate accepted cleanup survivors and bypass causes, never coordinates."""
    if not prepared.refusal.witnesses:
        return None
    return _failure_support_owners(
        tuple(
            frozenset(witness.failure.buildings) if witness.failure.buildings else None
            for witness in prepared.refusal.witnesses
        ),
        owners,
        prepared.survivor_indices,
        prepared.link_dependencies,
    )


def _failure_support_owners(
    supports: tuple[frozenset[int] | None, ...],
    owners: tuple[frozenset[NetId] | None, ...],
    survivor_indices: tuple[int, ...] | None = None,
    link_dependencies: tuple[finalize.CleanupLinkDependency, ...] = (),
) -> frozenset[NetId] | None:
    """Translate complete physical support through accepted cleanup lineage."""
    indices: set[int] = set()
    for support in supports:
        if support is None:
            return None
        for index in support:
            indices.add(index if survivor_indices is None else survivor_indices[index])
    for dependency in link_dependencies:
        if dependency.survivor_index in indices:
            indices.update(dependency.traversed_indices)
    causal: set[NetId] = set()
    for index in indices:
        contributors = owners[index]
        if contributors is None:
            return None
        causal.update(contributors)
    return frozenset(causal)


def compose(
    placements: list[Placement],
    flows: list[LaneFlow],
    spec: BuildSpec,
    *,
    settlement_spec: BuildSpec,
    gap: int,
    belt_rules: catalog.BeltAltitudeRules,
    deadline: float | None,
    policy: BandPolicy = _PORTABLE_POLICY,
    _limit_margin: int = 8,
) -> ComposeResult:
    """Pack the solved blocks side by side and wire every ``LaneFlow`` between them.

    ``gap`` is the FLOOR of :func:`pack_with_access`'s ladder, not the gap the
    packing gets: the composition commits whichever rung first gives every port
    a corridor out to open ground.  ``_limit_margin`` is how much free ground
    outside the packed boxes the router may use; it exists so a test can wall
    the composition in at 0 and see the router NAME the cut it cannot make.
    """
    # These are complete physical block boxes. Optional routing margin is free
    # canvas, not a guaranteed emitted rim; later routed geometry is finalized.
    envelope = band_policy_search_envelope(policy, perimeter=0)
    # Composed machine counts/rates belong to settlement_spec, but an original
    # player obligation must not disappear merely because its net deficit is
    # zero after composition. Cleanup uses this same declaration to retain its
    # connected external belts via _required_external_input_belts.
    missing_inputs = spec.external_inputs.keys() - settlement_spec.external_inputs.keys()
    if missing_inputs:
        settlement_spec = settlement_spec.model_copy(
            update={
                "external_inputs": {
                    **settlement_spec.external_inputs,
                    **{item: spec.external_inputs[item] for item in missing_inputs},
                }
            }
        )
    try:
        packed = pack_with_access(
            placements,
            flows,
            spec,
            belt_rules=belt_rules,
            deadline=deadline,
            margin=_limit_margin,
            gap=gap,
            envelope=envelope,
            external_spec=settlement_spec,
        )
    except _PackingDeadline as expired:
        return _budget_refusal(expired.packing)
    except _ExternalAccessRefused as refused:
        packing = refused.packing
        return ComposeResult(
            Placement(
                buildings=tuple(packing.canvas.buildings),
                description="hierarchical composition",
            ),
            packing.blocks,
            0,
            refused.failures,
            unrouted_cuts=len(packing.nets),
            settlement=RouteSettlementRefused(str(refused), None),
        )

    canvas = packed.canvas
    blocks = packed.blocks
    nets = packed.nets
    reservation = packed.reservation
    bounds = canvas.limit
    assert bounds is not None  # canvas_for always sets it

    # A PORT THE MATCHER COULD NOT SERVE IS A REPORTED CUT, not a discarded
    # verdict.  `_prepare_routing_problem` turns the same evidence into
    # `StrandedPort` so a refusal can name the LANE HEAD rather than the nets
    # that happened to end on it (freeform ~16608); the composer has no strips
    # to name, so it names the block the lane head sits in and carries the same
    # `held`/`wants`/`options` counts, which are the whole story of why the
    # matching failed.  The router still runs: a missing corridor makes some
    # nets unroutable, and its own failures are better evidence than nothing.
    evidence_by_demand = {evidence.demand: evidence for evidence in reservation.evidence}
    failures = [
        f"{demand.item}: block {_block_of(blocks, demand.belt)} lane head {demand.belt}: "
        f"no port access corridor ({_corridor_evidence(evidence_by_demand.get(demand))})"
        for demand in reservation.missing
    ]

    belt_id = _belt_id_for(spec)
    belt_model = _belt_model_for(spec)
    try:
        projection = _CompositionProjection(
            canvas.buildings,
            bounds,
            policy,
            belt_rules=canvas.belt_rules,
            cancelled=partial(_spent, deadline),
        )
        canvas.junction_projection = projection
    except _PreparationDeadline:
        return _budget_refusal(_Packing(packed.buildings, blocks, canvas, nets))
    settlement = _CompositionSettlement(
        settlement_spec,
        policy,
        belt_rules,
        deadline,
        external_access=packed.external_access,
    )
    result = _route_all(
        canvas,
        nets,
        belt_id,
        belt_model,
        bounds,
        deadline=deadline,
        settle=settlement if not reservation.missing else None,
        flow_limits=RoutingFlowLimits(
            tuple(flow.rate for flow in flows), spec.lane_capacity * spec.max_stack
        ),
    )

    failures.extend(
        f"{failure.net_id.item}: block {failure.net_id.source_strip} -> "
        f"block {failure.net_id.destination_strip}: {failure.kind.name}"
        for failure in result.failures
    )
    # A net that neither routed nor failed is one the pass never reached -- a
    # deadline or a spent budget. It is still an unwired cut and is reported as
    # one, under the status that stopped the pass.
    accounted = set(result.routed) | {failure.net_id for failure in result.failures}
    failures.extend(
        f"{net.item}: block {net.net_id.source_strip} -> "
        f"block {net.net_id.destination_strip}: {result.status.name}"
        for net in nets
        if net.net_id is not None and net.net_id not in accounted
    )
    #: Cuts the ROUTER could not wire, counted before any power-infill entry
    #: is appended below.  `strategy.py`'s `unrouted_cuts` derives from this
    #: rather than from `len(failures)`, so a refusal naming four dark tiles
    #: does not inflate the number Task 9 compares across gates -- those
    #: tiles are already counted in `power_uncovered`.
    routing_failures = len(failures)

    # An unsettled partial still needs its original physical diagnostic infill.
    # Complete attempted candidates already ran infill on their owned workspace.
    outcome = result.settlement
    if outcome is None:
        canvas.guard.update((x, y, 0) for x, y, _ in packed.external_access)
        try:
            infill_sites, unpowered = plan_power_infill(
                canvas, policy=policy, cancelled=partial(_spent, deadline)
            )
        except _PreparationDeadline:
            infill_sites, unpowered = [], ()
            failures.append(
                "composition power infill: did not run, the composition's wall was "
                "already spent before it could start"
            )
        except _Unpowerable as error:
            infill_sites, unpowered = [], ()
            failures.append(f"composition power infill: {error}")
        else:
            try:
                _place_power(canvas, infill_sites)
            except _Unpowerable as exc:
                infill_sites = []
                failures.append(f"composition power infill: {exc}")
            failures.extend(
                f"power.coverage: composed tile ({tx},{ty}) is outside every tower's supply "
                "radius and no free, linked, legal site can cover it"
                for tx, ty in unpowered
            )
        power_infill, power_uncovered = len(infill_sites), len(unpowered)
    elif isinstance(outcome, (RouteSettlementCompleted, RouteSettlementRefused)):
        power_infill, power_uncovered = outcome.power_infill, outcome.power_uncovered
        if isinstance(outcome, RouteSettlementRefused):
            failures.append(outcome.reason)
    else:
        power_infill, power_uncovered = 0, 0
    placement = (
        outcome.completion.placement
        if isinstance(outcome, RouteSettlementCompleted)
        else Placement(buildings=tuple(canvas.buildings), description="hierarchical composition")
    )

    return ComposeResult(
        placement,
        blocks,
        len(result.routed),
        tuple(failures),
        gap=packed.gap,
        port_demands=len(reservation.assigned) + len(reservation.missing),
        reservation_missing=len(reservation.missing),
        reservation_degraded=packed.degraded,
        reservation_partial=packed.partial,
        power_infill=power_infill,
        power_uncovered=power_uncovered,
        unrouted_cuts=routing_failures,
        settlement=outcome,
        route_expansions=result.expansions,
        settlement_attempts=settlement.attempts,
        settlement_refusals=settlement.refusals,
        settlement_reuses=settlement.reuses,
        settlement_wall_s=settlement.wall_s,
    )


__all__ = [
    "GAP_LADDER",
    "LADDER_WALL_SHARE",
    "RESERVE_WALL_SHARE",
    "BlockPlaced",
    "ComposeResult",
    "PackedCanvas",
    "canvas_for",
    "compose",
    "pack_blocks",
    "pack_with_access",
]
