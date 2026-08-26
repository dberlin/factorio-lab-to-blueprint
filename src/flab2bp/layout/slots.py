"""Which slot a sorter names on the building it touches.

Every sorter we emitted before this module existed carried ``(0, 0, 0, 0)`` in
its four slot fields.  Pasted into the game that produced four errors and drew
**every** sorter red -- the first time anything we built was tried in game.  The
validator passed the same build with ``INVALID 0``, because nothing in it looked
at these fields at all.

THE THREE CONSTANTS
-------------------
``output_from_slot == 0`` and ``input_to_slot == 1`` on all 1288 sorters in
``tests/fixtures/*.txt``, without a single exception.  The BELT side of a
connection is always ``-1``.  Only the MACHINE side carries a real index.

Those three, the ``0.8`` reach and the ``24``-degree alignment are the GAME's
rules rather than this module's, and they are stated with their provenance in
:mod:`flab2bp.dsp.rules`.  This module imports them from there so that what we
EMIT and what ``layout.validate`` CHECKS can never drift apart.

THE MACHINE SIDE IS NOW READ FROM THE GAME, NOT INFERRED
--------------------------------------------------------
A slot index is a subscript into ``PrefabDesc.slotPoses``, and those poses are
shipped in the prefabs.  ``scripts/extract_dsp_slot_poses.py`` pulls them out;
:attr:`flab2bp.dsp.catalog.Building.slot_poses` serves them; :func:`machine_slot`
picks the one the game would pick -- the nearest pose whose forward agrees with
the direction the sorter arrives from.

This module used to guess instead, from a ring re-derived out of seven observed
buildings: twelve slots, three per side, handedness extrapolated by footprint
from a sample of two.  The real table says the ring is real but the
extrapolation was not:

* an **Assembling Machine** has 12, three per side, un-mirrored -- as derived;
* a **Matrix Lab** has 12, mirrored -- also as derived;
* an **Oil Refinery** has **9**, and not as a ring: 0-2 east, 3-5 west, 6-8 on
  the south face at ``z = -3.6``.  Its north face takes no sorter at all;
* a **Chemical Plant** has **8**, in two rows -- 0,1,2,7 along the north face
  at ``x in {-1, 0, 1, 2}``, and 3-6 along ``z = -0.9``, which is one row INSIDE
  a footprint five deep.  Four of the nine columns of a nine-wide building, and
  neither of the two long sides, will take a sorter anywhere.

The Chemical Plant is why a three-building blueprint containing one pasted with
"Sorter data error" while the same shape built from 3x3 Assembling Machines
pasted clean.  No ring rule could have produced that; only the table does.

WHAT "NEAREST" MEANS
--------------------
The game's own tolerance, :data:`flab2bp.dsp.rules.SLOT_REACH`.
``BuildTool_BlueprintCopy.CheckInserterDataLegal`` rejects a sorter whose end
lands more than that from the pose it names, and the paste path
(``BlueprintData``, ``EBuildCondition.ErrorInserterData``) snaps the end onto
the pose and rejects a comparable distance with a wider allowance for a purely
radial offset.  Both are ported in ``layout.validate``; this module uses the
same figure so that what we emit and what we check agree.

:func:`machine_slot` returns the nearest slot even when the nearest is further
than that, rather than raising.  A sorter whose end is nowhere near any slot is
a LAYOUT defect, and the validator names it as one -- refusing to encode it here
would only convert a reported error into a crash, and the nearest real slot is
the one the game would have snapped to.  It raises only when there is no slot to
name at all.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, replace

from flab2bp.dsp import catalog as cat
from flab2bp.dsp import colliders
from flab2bp.dsp.rules import (
    ADDON_FROM_SLOT,
    ADDON_TO_SLOT,
    BELT_INPUT_SLOTS,
    BELT_SLOT,
    INPUT_TO_SLOT,
    OUTPUT_FROM_SLOT,
    SLOT_ALIGN_COS,
    SLOT_REACH,
    SPLITTER_MAX_PORTS,
    WORLD_UNITS_PER_LEVEL,
    world_gap,
)
from flab2bp.layout.base import PlacedBuilding

__all__ = [
    "ADDON_FROM_SLOT",
    "ADDON_TO_SLOT",
    "BELT_SLOT",
    "INPUT_TO_SLOT",
    "OUTPUT_FROM_SLOT",
    "SLOT_REACH",
    "Attachment",
    "SlotUndetermined",
    "assign_belt_slots",
    "assign_sorter_slots",
    "attachable_columns",
    "attachable_rows",
    "attachment",
    "lane_facing",
    "lane_orientation",
    "machine_slot",
    "probe_building",
    "emitted_sorter",
    "seated_sorter",
    "sorter_seat_is_clear",
    "sorter_seat_boxes",
    "slot_forward",
    "slot_offset",
    "sorter_yaw",
    "world_gap",
    "to_local",
    "to_world",
]

# Every constant below is the GAME's, stated with its provenance in
# `flab2bp.dsp.rules`.  They are imported rather than restated so that this
# module and `layout.validate` can never hold two different readings of the
# same rule -- which is exactly what happened when the 24-degree skew limit was
# written here as `SLOT_ALIGN_DEG` and again there as `_SKEW_AXIS_DEG`.


class SlotUndetermined(ValueError):
    """A sorter's slot could not be derived from geometry.

    Raised rather than defaulted.  A guessed ``0`` is exactly what made every
    sorter in the first in-game paste invalid, so there is no fallback here.
    """


def _unrotate(dx: float, dy: float, yaw: float) -> tuple[float, float]:
    """``(dx, dy)`` expressed in the frame of a building turned by ``yaw``.

    World is ``R(yaw)`` applied to local, where ``R(90)`` maps local ``(x, y)``
    to world ``(y, -x)``.  Buildings are axis-aligned, so the yaw is snapped to
    a quarter turn rather than run through trigonometry: real blueprints record
    yaws like ``355.5`` and ``-6.7e-07`` for what is plainly 0, and a cosine of
    those introduces drift into what is exactly a permutation of two integers.
    """
    q = int(round(yaw / 90.0)) % 4
    if q == 0:
        return (dx, dy)
    if q == 1:
        return (-dy, dx)
    if q == 2:
        return (-dx, -dy)
    return (dy, -dx)


def to_local(offset: tuple[float, float], yaw: float) -> tuple[float, float]:
    """A world-tile offset expressed in the frame of a building turned by ``yaw``."""
    return _unrotate(offset[0], offset[1], yaw)


def to_world(local: tuple[float, float], yaw: float) -> tuple[float, float]:
    """The inverse of :func:`to_local`: a building-local offset, turned into world."""
    return _unrotate(local[0], local[1], -yaw)


def slot_offset(item_id: int, yaw: float, slot: int) -> tuple[float, float, float]:
    """Slot ``slot``'s position relative to the building's centre.

    ``(tiles east, tiles north, altitude LEVELS)`` -- the grid frame the rest of
    this project counts in, NOT the world units the prefab stores.  The pose
    comes out of Unity in world units; a tile is ``GRID_ARC`` = 1.2566 of them
    and a level is ``WORLD_UNITS_PER_LEVEL`` = 4/3, so both are divided out
    here, once, rather than at each of the several places that add this to a
    tile coordinate.

    This is the game's ``slotPoses[slot].GetTransformedBy(objectPose)`` minus
    the building's own position, rotated by its yaw.  Height is not affected by
    yaw.
    """
    p = _pose(item_id, slot)
    wx, wy = to_world((p.dx, p.dy), yaw)
    return (
        wx / colliders.GRID_ARC,
        wy / colliders.GRID_ARC,
        p.dz / WORLD_UNITS_PER_LEVEL,
    )


def slot_forward(item_id: int, yaw: float, slot: int) -> tuple[float, float, float]:
    """Slot ``slot``'s ``Pose.forward``, in world axes.

    Points out of the building, along the direction a sorter attached there must
    run.  The game dots this against the sorter's own axis in two separate
    checks, so the sign matters and is preserved.
    """
    p = _pose(item_id, slot)
    fx, fy = to_world((p.fx, p.fy), yaw)
    return (fx, fy, p.fz)


def _pose(item_id: int, slot: int) -> cat.SlotPose:
    poses = cat.building(item_id).slot_poses
    if not 0 <= slot < len(poses):
        raise SlotUndetermined(
            f"building {item_id} ({cat.building(item_id).name}) defines "
            f"{len(poses)} sorter slots, so slot {slot} does not exist on it"
        )
    return poses[slot]


def machine_slot(
    item_id: int,
    yaw: float,
    offset: tuple[float, float],
    approach: tuple[float, float],
) -> int:
    """The slot index a sorter names on the machine it touches.

    ``offset`` is the sorter's machine-side end minus the machine's centre, in
    world tiles.  ``approach`` is that same end minus the sorter's *other* end,
    so it points into the machine.

    ANGLE FIRST, THEN DISTANCE.  That is the game's own order of preference.
    ``BuildTool_Inserter`` scores every candidate pose pair by::

        bias = Max(Angle(axis, endPose.forward), Angle(-axis, startPose.forward))
        bias = Max(bias, 180f - Angle(startPose.forward, endPose.forward))

    and keeps the smallest -- an angular figure with no distance term in it.
    Here the angular term is reduced to a yes/no at the game's own 24-degree
    ``TooSkew`` threshold, and distance decides among the slots that pass; a
    whole face of a building passes together, so the nearest slot along it wins.

    Ordering by distance first would be wrong at a corner, where two slots sit
    the same 0.1 tiles from the same tile centre and only their facing tells
    them apart -- a sorter arriving along the machine's west side would be given
    the south-facing slot on an index tie and paste as "deflection too much".

    Raises :class:`SlotUndetermined` only when the building defines no slot the
    sorter could name.  Distance is NOT a reason to raise: see the module
    docstring.
    """
    poses = cat.building(item_id).slot_poses
    if not poses:
        raise SlotUndetermined(
            f"building {item_id} ({cat.building(item_id).name}) defines no sorter "
            f"slots at all, so no sorter can attach to it"
        )
    lx, ly = _unrotate(offset[0], offset[1], yaw)
    # The game dots against the direction from this end towards the other one,
    # which is the negation of the approach.
    ax, ay = -approach[0], -approach[1]
    span = (ax * ax + ay * ay) ** 0.5
    if span == 0:
        raise SlotUndetermined(
            f"sorter has both ends on the same tile, so it approaches building "
            f"{item_id} from no direction at all"
        )
    ax, ay = _unrotate(ax / span, ay / span, yaw)

    # Ranked, never filtered: a slot the sorter runs squarely away from sorts
    # behind every one it runs towards, but it is still preferred to naming
    # nothing.  A building whose every slot faces the wrong way is a layout
    # defect that `game.inserter_data` reports by name; dropping the sorter here
    # would replace a reported error with a crash.
    #
    # Aligned-or-not, at the game's own 24-degree threshold, rather than the raw
    # cosine.  The slots on one face do NOT share a bit-identical forward -- each
    # is its own prefab Transform and they differ in the sixth decimal -- so
    # ordering by the raw cosine would let numerical noise outrank a whole tile
    # of distance.  Bucketing at a threshold the game itself uses restores the
    # tie the geometry intends, and 13 of the corpus's 1206 records turn on it.
    #
    # Distance is measured in the build plane.  Every slot on a building sits
    # within 0.04 of the same height, so the vertical term is common to all of
    # them and cannot move the winner.
    def rank(k: int) -> tuple[int, float, int]:
        p = poses[k]
        aligned = 0 if p.fx * ax + p.fy * ay >= SLOT_ALIGN_COS else 1
        return (aligned, (p.dx - lx) ** 2 + (p.dy - ly) ** 2, k)

    return min(range(len(poses)), key=rank)


@dataclass(frozen=True, slots=True)
class Attachment:
    """Where a sorter may meet a machine, and what the game will read there.

    ``cell`` is the grid tile the sorter's machine-side end must occupy -- NOT
    necessarily a tile on the machine's outer edge.  A Chemical Plant's southern
    slots sit at ``z = -0.9`` in a footprint five deep, so their anchor is one
    row INSIDE the building and the sorter is two tiles long instead of one.
    ``slot`` is what :func:`machine_slot` will derive for that geometry, so a
    caller that anchors here and lets :func:`assign_sorter_slots` fill the
    fields in gets this index by construction.
    """

    cell: tuple[int, int]
    slot: int
    span: int


def attachment(machine: PlacedBuilding, far: tuple[int, int]) -> Attachment | None:
    """Where a straight sorter between ``far`` and ``machine`` must anchor.

    ``None`` means the game allows no such sorter, and the caller's only honest
    responses are to try another column or to refuse.  There is no nearest-legal
    answer to fall back on: a sorter anchored where no insert pose is within
    reach is rejected on paste, which is the whole class of defect this exists
    to stop.

    What is checked, and where each rule comes from:

    * the run is axis-aligned and ``far`` is off the footprint -- ours, and what
      ``sorter.reach`` already requires;
    * the anchor is a tile of ``machine``, so the end lands on the building it
      names (``sorter.endpoint_pair``);
    * the end is within :data:`SLOT_REACH` of the pose -- the game's
      ``CheckInserterDataLegal``, and the paste path's ladder with it;
    * the slot faces back along the run to within
      :data:`flab2bp.dsp.rules.SKEW_AXIS_DEG` -- the
      game's ``TooSkew``, and the sign half of ``CheckInserterDataLegal``;
    * the span is within ``catalog.SORTER_MAX_REACH``.

    The game's LENGTH window is deliberately not applied.  Its loosest floor is
    0.9 and its tightest ceiling 5.0, while an axis-aligned sorter on a tile
    grid is 1, 2 or 3 tiles long -- it cannot bind on anything expressible here,
    and ``game.inserter_skew`` covers the case a hand-built fixture reaches.

    Ties are broken by the shortest span, then by the closest pose, then by the
    lowest slot index, so the result is deterministic.
    """
    if not cat.building(machine.item_id).slot_poses:
        # A building that takes no sorter anywhere answers "nowhere" rather than
        # raising. `machine_slot` still raises for one that has been wired up
        # regardless -- that is a sorter already built on a false premise, and a
        # different thing from a planner asking whether it could be.
        return None
    fx, fy = far
    cx, cy = _centre(machine)
    xs = range(machine.x, machine.x + machine.width)
    ys = range(machine.y, machine.y + machine.height)

    cells: list[tuple[int, int]] = []
    if fx in xs and fy not in ys:
        cells = [(fx, y) for y in ys]
    elif fy in ys and fx not in xs:
        cells = [(x, fy) for x in xs]
    if not cells:
        return None

    best: Attachment | None = None
    best_key: tuple[int, float, int] | None = None
    for cell in cells:
        span = max(abs(cell[0] - fx), abs(cell[1] - fy))
        if not 1 <= span <= cat.SORTER_MAX_REACH:
            continue
        slot = machine_slot(
            machine.item_id,
            machine.yaw,
            (cell[0] - cx, cell[1] - cy),
            (cell[0] - fx, cell[1] - fy),
        )
        sx, sy, sz = slot_offset(machine.item_id, machine.yaw, slot)
        pose = (cx + sx, cy + sy)
        reach = world_gap(pose[0] - cell[0], pose[1] - cell[1], sz)
        if reach > SLOT_REACH:
            continue
        wx, wy, _wz = slot_forward(machine.item_id, machine.yaw, slot)
        ax, ay = fx - pose[0], fy - pose[1]
        n = (ax * ax + ay * ay) ** 0.5
        if n == 0.0 or (wx * ax + wy * ay) / n < SLOT_ALIGN_COS:
            continue
        key = (span, reach, slot)
        if best_key is None or key < best_key:
            best_key, best = key, Attachment(cell, slot, span)
    return best


def probe_building(item_id: int, yaw: float) -> PlacedBuilding:
    """One machine of this type at the origin, for asking geometric questions.

    :func:`attachment` and :func:`attachable_columns` answer about a PLACED
    building, which is right for wiring but awkward for a planner that wants to
    know what a type will offer before it has placed one.  This is the type-level
    stand-in, with the footprint already oriented so its extents and its poses
    agree.
    """
    w, h = cat.oriented_footprint(item_id, yaw)
    return PlacedBuilding(
        item_id=item_id,
        model_index=cat.building(item_id).model_index,
        x=0,
        y=0,
        width=w,
        height=h,
        yaw=yaw,
    )


def direct_anchors(
    src: PlacedBuilding, dst: PlacedBuilding, column: int
) -> tuple[Attachment, Attachment] | None:
    """Both ends of a machine-to-machine sorter on ``column``, or ``None``.

    A direct insert has no belt to anchor against, so each end has to be found
    against the OTHER machine's anchor rather than against a fixed tile -- and
    those two answers depend on each other.  Two passes settle it: the producer
    is placed against the consumer's near edge, the consumer against that, and
    the producer re-checked against the consumer's final cell.  A third pass
    cannot move anything, because the second already fixed the only tile the
    first was approximating.

    ``None`` is a refusal.  Direct insertion is an optimisation -- the same
    connection can go by belt -- so a caller that cannot get an answer here has
    somewhere to go, unlike one wiring a lane.
    """
    near = dst.y if dst.y > src.y else dst.y + dst.height - 1
    first = attachment(src, (column, near))
    if first is None:
        return None
    second = attachment(dst, (column, first.cell[1]))
    if second is None:
        return None
    settled = attachment(src, (column, second.cell[1]))
    if settled is None:
        return None
    return (settled, second)


def lane_facing(item_id: int, yaw: float) -> tuple[bool, bool]:
    """Can a building at ``yaw`` be served from the north, and from the south?

    Read off the poses: a lane can serve a face only if some pose there points
    back at it.  Both strategies run their belts east-west, so these two are the
    only directions that decide whether a machine can be wired at all.
    """
    north = south = False
    for k in range(len(cat.building(item_id).slot_poses)):
        _fx, fy, _fz = slot_forward(item_id, yaw, k)
        north = north or fy >= SLOT_ALIGN_COS
        south = south or fy <= -SLOT_ALIGN_COS
    return (north, south)


def lane_orientation(item_id: int) -> float:
    """The yaw to build ``item_id`` at, for a layout whose lanes run east-west.

    An Oil Refinery has nine poses and NOT ONE of them faces north, so upright
    it can only ever be fed from below -- which is why every Refinery spec
    refused.  Turned a quarter it presents three poses to each side, and its
    3x7 becomes a 7x3 that suits a row band better as well.

    The rule is read from the table, not tabulated per building: prefer an
    orientation reachable from BOTH sides, then one reachable from either, and
    break ties toward upright so nothing rotates without cause.  Only 0 and 90
    are considered -- 180 and 270 are those two mirrored, and a face that has a
    pose still has one after mirroring, so they can differ from the pair only in
    which columns are offered and never in whether a side works at all.

    Returns ``0.0`` for a building with no poses at all.  Nothing can be wired to
    one, so no rotation improves it, and ``game.addon_supply`` or the caller's
    own refusal is what reports that.
    """
    if not cat.building(item_id).slot_poses:
        return 0.0
    scored = []
    for yaw in (0.0, 90.0):
        north, south = lane_facing(item_id, yaw)
        scored.append((-(north and south), -(north or south), yaw))
    scored.sort()
    return scored[0][2]


def attachable_columns(
    machine: PlacedBuilding, lane_y: int
) -> dict[int, Attachment]:
    """Every column of ``machine`` a sorter from a lane at ``lane_y`` can use.

    Empty is a real answer and a common one.  An Oil Refinery has no insert pose
    on its northern face at all, so a lane above it can serve none of its
    columns however close it sits; a Matrix Lab is five wide and offers three.
    """
    out: dict[int, Attachment] = {}
    for x in range(machine.x, machine.x + machine.width):
        got = attachment(machine, (x, lane_y))
        if got is not None:
            out[x] = got
    return out


def attachable_rows(machine: PlacedBuilding, lane_x: int) -> dict[int, Attachment]:
    """Every row of ``machine`` a sorter from a lane at column ``lane_x`` can use.

    The EAST/WEST twin of :func:`attachable_columns`, and it exists because the
    east and west faces are not a special case in the game: a Matrix Lab defines
    twelve poses, three per side, and a layout that reads only two of those
    sides is reading two thirds of the building.  ``attachment`` has always
    handled a lane beside a machine -- its first branch takes ``far`` on a shared
    column, its second ``far`` on a shared ROW -- so nothing new is decided here.
    What was missing was a way to ASK, in the same shape the planner already asks
    about the north and south faces.

    Empty is a real answer.  An Oil Refinery turned a quarter offers nothing on
    its east side and a Chemical Plant nothing on either.
    """
    out: dict[int, Attachment] = {}
    for y in range(machine.y, machine.y + machine.height):
        got = attachment(machine, (lane_x, y))
        if got is not None:
            out[y] = got
    return out


def _centre(b: PlacedBuilding) -> tuple[float, float]:
    """A placed building's footprint centre, in tiles.

    ``PlacedBuilding.x`` is the minimum corner.  Every catalog footprint is odd
    (``test_no_catalog_footprint_is_even`` keeps it that way), so this is exact.
    """
    return (b.x + (b.width - 1) / 2, b.y + (b.height - 1) / 2)


def seated_sorter(
    sorter: PlacedBuilding, buildings: Sequence[PlacedBuilding]
) -> colliders.SorterPreview | None:
    """One sorter where the PASTE will put it, not where we wrote it.

    ``BlueprintUtils.RefreshBuildPreview`` (2090-2190 of the decompiled
    ``BlueprintUtils``) moves a sorter's end onto the slot pose it names before
    any build condition is evaluated::

        Pose pose = buildPreview2.input.desc.slotPoses[buildPreview2.inputFromSlot];
        Pose transformedBy = pose.GetTransformedBy(
            new Pose(buildPreview2.input.lpos, buildPreview2.input.lrot));
        buildPreview2.lpos = transformedBy.position;

    -- guarded by ``!buildPreview2.input.desc.isBelt``, and the same again for
    ``lpos2`` against ``outputToSlot``.  So the machine end of every sorter we
    emit is MOVED, typically by a tenth of a tile off the tile centre we chose,
    and the slot INDEX is what decides where it lands.  Any geometry question
    about a sorter -- reach, skew, collision -- has to be asked about the seated
    sorter or it is a question about a building the game will not create.

    ``None`` when the sorter has no second anchor, which
    ``sorter.anchors_present`` reports by name.

    THE OTHER END COMES WITH IT.  Seating a machine end does not stretch the
    sorter: three lines later the paste slides the BELT end sideways by the same
    delta, so the sorter stays straight (``RefreshBuildPreview`` 2100-2107, and
    the mirror image at 2151-2158)::

        if (buildPreview2.output != null && buildPreview2.output.desc.isBelt)
        {
            if (Mathf.Abs(Vector3.Dot((buildPreview2.lpos2 - buildPreview2.lpos)
                    .normalized, buildPreview2.output.lrot.Forward())) < 0.5f)
            {
                Vector3 vector6 = buildPreview2.lrot2.Forward();
                float num39 = Vector3.Dot(zero, vector6);
                buildPreview2.lpos2 += zero - vector6 * num39;
            }
        }

    ``zero`` is the seating delta of the end just moved, and what is added back
    is its component ACROSS the sorter's own axis, so the lateral part of the
    seat carries and the along-axis part does not.  It is not a small term: it
    is what puts the belt end 0.605 tiles off the tile we wrote for it on the
    blueprint this was built for.

    :data:`DRAG_MAX_ALIGNMENT` is the branch's own threshold, and the direction
    it is measured against is the belt's RECORDED yaw -- the pose the paste
    reads out of the blueprint, not the direction the belt turns out to run.
    The two differ on one of the 33 sorters the game built, and the recorded
    yaw is the one that predicts where it landed.

    HOW EXACT THIS IS, on the only sample that can say.  The user force-built a
    refused paste and blueprinted the result back out; the game built 33 of our
    38 sorters, and every one of those 66 ends is where this function says it
    is, to 2e-5 of a tile.  That comparison has to undo one thing first, and it
    is not a fitted correction: the copy was taken at 45 degrees of latitude,
    where a column is ``area_segments / 200 / cos(lat)`` of a tile rather than a
    tile, which is the same fixed-longitude-step effect ``geom.collide``
    documents.  ``area_segments`` is in the blueprint; the latitude is one
    unknown recovered from the 32 machine ends, and it lands inside the band the
    recorded ``area_segments`` requires.  A wrong seat model would not have
    admitted any latitude at all.
    """
    x2, y2, z2 = sorter.x2, sorter.y2, sorter.z2
    if x2 is None or y2 is None or z2 is None:
        return None
    # THE SLOT INDEX IS THE SEAT, so it is derived rather than read: a strategy
    # asking this about a sorter it has just built carries the dataclass default
    # of zero in all four fields until `assign_sorter_slots` runs.  After that
    # pass the derivation returns what is already recorded, so this costs
    # nothing and cannot disagree with what is emitted.
    sorter = emitted_sorter(sorter, buildings)
    ends = [
        [float(sorter.x), float(sorter.y), float(sorter.z)],
        [float(x2), float(y2), float(z2)],
    ]
    yaws = (sorter.yaw, sorter.yaw if sorter.yaw2 is None else sorter.yaw2)
    links = (
        (sorter.input_obj, sorter.input_from_slot),
        (sorter.output_obj, sorter.output_to_slot),
    )
    peers = [
        buildings[link] if link is not None and 0 <= link < len(buildings) else None
        for link, _slot in links
    ]
    # True where the game's own branch is true: the end meets a belt, or meets
    # nothing.  Both grow the collider; a machine end does not.
    open_end = [True, True]
    for k, (peer, (_link, slot)) in enumerate(zip(peers, links, strict=True)):
        if peer is None or cat.is_belt(peer.item_id):
            continue
        open_end[k] = False
        poses = cat.building(peer.item_id).slot_poses
        if not 0 <= slot < len(poses):
            # ``slotPoses.Length > otherSlot`` -- the game skips the seat too,
            # and leaves the end on the record.  `game.inserter_data` is what
            # reports a slot the peer does not define.
            continue
        dx, dy, dz = slot_offset(peer.item_id, peer.yaw, slot)
        cx, cy = _centre(peer)
        seated = [cx + dx, cy + dy, float(peer.z) + dz]
        zero = (
            seated[0] - ends[k][0],
            seated[1] - ends[k][1],
            seated[2] - ends[k][2],
        )
        ends[k] = seated
        _drag_belt_end(ends, zero, k, peers, yaws)
    return colliders.SorterPreview(
        sorter.model_index,
        ends[0][0],
        ends[0][1],
        ends[0][2],
        ends[1][0],
        ends[1][1],
        ends[1][2],
        open_end[0],
        open_end[1],
    )


def sorter_seat_boxes(
    buildings: Sequence[PlacedBuilding], *, skip: int | None = None
) -> list[colliders.Box]:
    """The build collider of every sorter already standing, seated.

    The list a strategy tests a candidate sorter against.  Building it once per
    placement pass rather than once per candidate is the whole reason it is a
    separate function: seating and boxing are quaternion arithmetic, and a
    strategy that rebuilt this inside its column loop would be cubic in the
    sorter count.

    ``skip`` leaves one index out, for a caller re-testing a sorter it has
    already appended.
    """
    out = []
    for i, b in enumerate(buildings):
        if i == skip or not cat.is_sorter(b.item_id):
            continue
        seat = seated_sorter(b, buildings)
        if seat is not None:
            out.append(colliders.sorter_box(seat))
    return out


def sorter_seat_is_clear(
    candidate: PlacedBuilding,
    buildings: Sequence[PlacedBuilding],
    standing: Sequence[colliders.Box],
) -> bool:
    """May ``candidate`` be added without the paste refusing it as ``Collide``?

    THE ONE PAIRING THE PASTE DOES NOT EXCUSE is sorter against sorter -- the
    excusal in ``CheckBuildConditions`` is an exclusive OR on ``isInserter``, so
    a sorter is forgiven against every other kind of building and against
    nothing else.  :func:`flab2bp.dsp.colliders.sorter_collisions` carries the
    C# for that and for the box, which is not the prefab box at the record's
    position but one stretched between the sorter's two SEATED ends and grown
    past any end that meets a belt or meets nothing.

    Two ends that meet at the same belt tile are the shape that trips it: both
    grow :data:`~flab2bp.dsp.colliders.SORTER_END_EXTENSION` past that tile, so
    they overlap by twice it however short the sorters are.  A strategy that
    places a sorter without asking this emits a blueprint the game draws red,
    which is what ``game.sorter_collide`` then refuses -- and a refusal after
    the fact costs a whole packing, so every site that appends a sorter asks
    here first.

    ``standing`` comes from :func:`sorter_seat_boxes`; the candidate must
    already carry its links, because they are what decides where its ends sit.
    """
    seat = seated_sorter(candidate, buildings)
    if seat is None:
        return True
    box = colliders.sorter_box(seat)
    return not any(colliders.obb_overlap(box, other) for other in standing)


#: ``RefreshBuildPreview`` 2102 and 2153 -- the belt end follows the seat only
#: when the belt lies ACROSS the sorter rather than along it.  A belt running
#: with the sorter is left where the record put it.
DRAG_MAX_ALIGNMENT = 0.5


def _forward(yaw: float) -> tuple[float, float]:
    """``Quaternion.Euler(0, yaw, 0).Forward()``, in ``(east, north)`` tiles.

    Unity's ``Vector3.forward`` is local ``+z``, which is north on our grid, so
    a yaw of 0 points north and a yaw of 90 points east.
    """
    r = math.radians(yaw)
    return (math.sin(r), math.cos(r))


def _drag_belt_end(
    ends: list[list[float]],
    zero: tuple[float, float, float],
    seated: int,
    peers: Sequence[PlacedBuilding | None],
    yaws: tuple[float, float],
) -> None:
    """Slide the belt end of a sorter whose other end has just been seated.

    ``RefreshBuildPreview`` 2100-2107, and its mirror at 2151-2158.  ``zero`` is
    the delta the seat just applied to end ``seated``; the belt end gains the
    part of it that is ACROSS the sorter's own axis.  The vertical part of
    ``zero`` carries whole, because the axis the game projects onto is the
    tangent forward and has no radial component to remove.

    Nothing happens unless the other end really is a belt.  The ``else if
    (buildPreview2.output == null)`` arm three lines down does something else
    entirely -- it rebuilds the far end out of the sorter's own length -- and is
    not ported, because neither strategy emits a sorter with an end attached to
    nothing: 0 of the 4076 sorters over 96 corpus cells of both strategies.
    """
    other = 1 - seated
    belt = peers[other]
    if belt is None or not cat.is_belt(belt.item_id):
        return
    # ``(lpos2 - lpos).normalized`` -- in world units, so the height difference
    # counts at its own scale rather than at the tile pitch.
    axis = (
        (ends[1][0] - ends[0][0]) * colliders.GRID_ARC,
        (ends[1][1] - ends[0][1]) * colliders.GRID_ARC,
        (ends[1][2] - ends[0][2]) * WORLD_UNITS_PER_LEVEL,
    )
    length = math.sqrt(axis[0] ** 2 + axis[1] ** 2 + axis[2] ** 2)
    if length < 1e-9:
        return
    bfx, bfy = _forward(belt.yaw)
    if abs((axis[0] * bfx + axis[1] * bfy) / length) >= DRAG_MAX_ALIGNMENT:
        return
    vfx, vfy = _forward(yaws[other])
    along = zero[0] * vfx + zero[1] * vfy
    ends[other][0] += zero[0] - vfx * along
    ends[other][1] += zero[1] - vfy * along
    ends[other][2] += zero[2]


def _peer_slot(
    peer: PlacedBuilding,
    end: tuple[int, int],
    other_end: tuple[int, int],
) -> int:
    """The slot ``sorter`` names on ``peer``, whichever kind of thing that is."""
    if cat.is_belt(peer.item_id):
        return BELT_SLOT
    if peer.item_id == cat.SPLITTER_ID or cat.is_sorter(peer.item_id):
        raise SlotUndetermined(
            f"sorter names a {'splitter' if peer.item_id == cat.SPLITTER_ID else 'sorter'} "
            f"(item {peer.item_id}) as a connection; the corpus has no such record "
            f"to derive a slot from"
        )
    cx, cy = _centre(peer)
    return machine_slot(
        peer.item_id,
        peer.yaw,
        (end[0] - cx, end[1] - cy),
        (end[0] - other_end[0], end[1] - other_end[1]),
    )


def sorter_yaw(head: tuple[int, int], tail: tuple[int, int]) -> float:
    """The yaw a sorter running ``head`` -> ``tail`` carries, in degrees.

    A sorter's yaw points from the end it draws FROM to the end it feeds INTO --
    from ``(x, y)`` to ``(x2, y2)``.  All 1250 real sorters in the corpus with a
    measurable span do this, with no exception and with ``yaw2 == yaw`` on every
    one of them.

    It matters because the game reconstructs the ends' rotations on paste: a
    machine end is re-rotated to the slot's own pose, the other end keeps the
    yaw the blueprint carries, and ``Quaternion.Angle`` between the two over 30
    degrees is ``EBuildCondition.TooSkew``.  A yaw that points the other way is
    exactly 180 degrees out, so it is not a cosmetic field.

    A zero-length sorter yields 0.0 rather than raising; ``sorter.reach`` is
    where a sorter with both ends on one tile gets reported, and raising here
    would replace that report with a crash.
    """
    return math.degrees(math.atan2(tail[0] - head[0], tail[1] - head[1])) % 360.0


def assign_sorter_slots(
    buildings: Sequence[PlacedBuilding],
) -> tuple[PlacedBuilding, ...]:
    """Fill in every LINK's slot fields, and every sorter's yaw, from geometry.

    A strategy places sorters; it does not have to know these conventions.  Both
    strategies run their finished building list through here, which is why there
    is one place to be right rather than four call sites to keep in step.  The
    name is narrower than the job -- :func:`assign_belt_slots` runs from here
    too -- and it is kept because being the ONE post-pass both strategies
    already call is the property that matters.

    Raises :class:`SlotUndetermined` if any sorter's slot cannot be derived.
    Emitting a guess instead is what this module exists to stop.
    """
    return assign_belt_slots(_assign_sorter_slots_only(buildings))


def assign_belt_slots(
    buildings: Sequence[PlacedBuilding],
) -> tuple[PlacedBuilding, ...]:
    """Give every belt-authored link its own slot on the peer it names.

    A SLOT HOLDS ONE CONNECTION.  The game stores connections as
    ``entityConnPool[objId * 16 + slot]``, and ``WriteObjectConn`` evicts
    whatever is already in the cell rather than refusing -- see
    :data:`~flab2bp.dsp.rules.CONN_SLOTS_PER_OBJECT`.  Every belt here used to
    leave ``output_to_slot`` at the dataclass default of ``0``, which is wrong
    twice: it is not a value the game ever writes for a belt-to-belt link, and
    where two belts merge into a third the two links landed in the same cell and
    one of them was dropped on paste.

    WHAT THE GAME WRITES, counted over the fixture corpus rather than guessed:

    * belt -> belt, ``output_to_slot``: **1** (7169 records), **2** (95),
      **3** (38).  Never 0, never above 3.  Those are the three INPUT slots of
      the receiving belt; slot 0 is where its own output link lives, so writing
      0 puts a predecessor's back-link in the cell the successor link needs.
    * belt <-> splitter: **0..3**, one per side, in both directions.
    * and across all ~10,000 connection records in the corpus, **no
      ``(object, slot)`` cell is named twice.**

    The assignment mirrors the game's own scan -- ``WriteObjectConn`` resolving
    an unspecified peer slot walks upward from the first legal index and takes
    the first free one.  Belts are visited in index order so the result is
    deterministic.

    Raises :class:`SlotUndetermined` when a receiving belt is out of input slots.
    A fourth belt feeding one belt tile has nowhere to go: the game would drop
    the link silently, and a dropped link is a blueprint that pastes and then
    starves.
    """
    taken: dict[int, set[int]] = {}
    out: list[PlacedBuilding] = []
    for i, b in enumerate(buildings):
        if not cat.is_belt(b.item_id):
            out.append(b)
            continue
        changes: dict[str, int] = {}
        for field, link in (("output_to_slot", b.output_obj), ("input_from_slot", b.input_obj)):
            if link is None or not 0 <= link < len(buildings):
                continue
            peer = buildings[link]
            if cat.is_belt(peer.item_id):
                if field != "output_to_slot":
                    # A belt never names another belt as `input_obj`: runs chain
                    # forward only, and `input_obj` on a belt names the SPLITTER
                    # it draws from. Leaving it alone rather than inventing a
                    # slot for a link the corpus does not contain.
                    continue
                legal = range(BELT_INPUT_SLOTS[0], BELT_INPUT_SLOTS[1])
            elif peer.item_id == cat.SPLITTER_ID:
                legal = range(0, SPLITTER_MAX_PORTS)
            else:
                # A machine, a station, an addon: the slot is the peer's own
                # perimeter index and is not this function's to choose.
                continue
            used = taken.setdefault(link, set())
            slot = next((s for s in legal if s not in used), None)
            if slot is None:
                raise SlotUndetermined(
                    f"belt {i} at ({b.x}, {b.y}) is the "
                    f"{len(used) + 1}th link into building {link} at "
                    f"({peer.x}, {peer.y}), which has only {len(legal)} slots for "
                    f"them; the game would drop the surplus without an error"
                )
            used.add(slot)
            changes[field] = slot
        out.append(replace(b, **changes) if changes else b)  # type: ignore[arg-type]
    return tuple(out)


def _assign_sorter_slots_only(
    buildings: Sequence[PlacedBuilding],
) -> tuple[PlacedBuilding, ...]:
    """The sorter and addon half of :func:`assign_sorter_slots`."""
    out: list[PlacedBuilding] = []
    for b in buildings:
        if cat.building(b.item_id).is_belt_addon:
            # A belt addon carries the same constant pair on all four fields and
            # is wired to nothing. Setting it here rather than at the one place
            # a coater is created keeps every "what does the game read in these
            # fields" answer in this module.
            if b.input_obj is not None or b.output_obj is not None:
                raise SlotUndetermined(
                    f"belt addon (item {b.item_id}) has a connection; the game "
                    f"wires addons to nothing and will not let a sorter target one"
                )
            out.append(
                replace(
                    b,
                    output_to_slot=ADDON_TO_SLOT,
                    input_from_slot=ADDON_FROM_SLOT,
                    output_from_slot=ADDON_FROM_SLOT,
                    input_to_slot=ADDON_TO_SLOT,
                )
            )
            continue
        if not cat.is_sorter(b.item_id):
            out.append(b)
            continue
        if b.x2 is None or b.y2 is None:
            raise SlotUndetermined(
                "sorter is missing its second anchor, so neither end can be "
                "attributed to a building"
            )
        out.append(emitted_sorter(b, buildings, strict=True))
    return tuple(out)


def emitted_sorter(
    sorter: PlacedBuilding,
    buildings: Sequence[PlacedBuilding],
    *,
    strict: bool = False,
) -> PlacedBuilding:
    """One sorter with the slot indices and yaw EMISSION will give it.

    A strategy builds a sorter out of two anchors and two links and leaves the
    four slot fields at the dataclass default of zero; the yaw it sets is a
    placeholder.  :func:`assign_sorter_slots` fills all of them in from geometry
    as the last pass before emission, so what the game finally reads is derived
    here and nowhere else.

    WHICH MATTERS BEFORE THAT PASS, and that is why this is public.  A slot
    index is not decoration: it is WHERE the paste seats the sorter's machine
    end (:func:`seated_sorter`), so a strategy asking a geometry question about
    a sorter it has just built would otherwise be asking it about slot 0 of
    every machine -- one arbitrary corner -- and get an answer with no bearing
    on the sorter it is about to emit.  Measured on the corpus: freeform's
    bridge guard ran on those defaults and passed bridges that
    ``game.sorter_collide`` then convicted on 15 of 96 mid cells.

    ``strict`` raises :class:`SlotUndetermined` for a link whose slot cannot be
    derived, which is what the emission pass wants -- a guess there is a
    connection the game will not write.  Lenient is what a geometry question
    wants: it keeps the recorded value and lets the check that owns that failure
    report it by name.
    """
    if sorter.x2 is None or sorter.y2 is None:
        return sorter
    head = (sorter.x, sorter.y)
    tail = (sorter.x2, sorter.y2)
    yaw = sorter_yaw(head, tail)

    def derive(
        link: int | None,
        end: tuple[int, int],
        other: tuple[int, int],
        fallback: int,
    ) -> int:
        if link is None:
            return fallback
        if not 0 <= link < len(buildings):
            if strict:
                raise SlotUndetermined(f"sorter names building {link}, which does not exist")
            return fallback
        try:
            return _peer_slot(buildings[link], end, other)
        except SlotUndetermined:
            if strict:
                raise
            return fallback

    # `input_obj` is what the sorter draws from and sits under the first
    # anchor; `output_obj` is what it feeds and sits under the second.
    return replace(
        sorter,
        input_from_slot=derive(sorter.input_obj, head, tail, sorter.input_from_slot),
        output_to_slot=derive(sorter.output_obj, tail, head, sorter.output_to_slot),
        output_from_slot=OUTPUT_FROM_SLOT,
        input_to_slot=INPUT_TO_SLOT,
        yaw=yaw,
        yaw2=yaw,
    )
