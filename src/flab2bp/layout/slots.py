"""Which slot a sorter names on the building it touches.

Every sorter we emitted before this module existed carried ``(0, 0, 0, 0)`` in
its four slot fields.  Pasted into the game that produced four errors and drew
**every** sorter red -- the first time anything we built was tried in game.  The
validator passed the same build with ``INVALID 0``, because nothing in it looked
at these fields at all.

THE THREE CONSTANTS
-------------------
``output_from_slot == 0`` and ``input_to_slot == 1`` on all 1288 sorters in
``tests/fixtures/*.txt``, without a single exception.  These are the sorter's
*own* ends and never vary; the game requires exactly this ordering, and rejects
the sorter outright when it is reversed (``CheckInserterDataLegal``, first two
tests).  The BELT side of a connection is always ``-1`` (849 belt inputs, 391
belt outputs, no other value).  Only the MACHINE side carries a real index.

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

WHAT "NEAREST" MEANS, AND WHY 0.8
---------------------------------
The game's own tolerance.  ``BuildTool_BlueprintCopy.CheckInserterDataLegal``
rejects a sorter whose end lands more than ``0.8`` from the pose it names, and
the paste path (``BlueprintData``, ``EBuildCondition.ErrorInserterData``) snaps
the end onto the pose and rejects the same distance with a wider allowance for a
purely radial offset.  Both are ported in ``layout.validate``; this module uses
the ``0.8`` figure so that what we emit and what we check agree.

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
from dataclasses import replace

from flab2bp.dsp import catalog as cat
from flab2bp.layout.base import PlacedBuilding

__all__ = [
    "BELT_SLOT",
    "INPUT_TO_SLOT",
    "OUTPUT_FROM_SLOT",
    "SLOT_REACH",
    "SlotUndetermined",
    "assign_sorter_slots",
    "machine_slot",
    "slot_forward",
    "slot_offset",
    "sorter_yaw",
    "to_local",
    "to_world",
]

#: The sorter's own ends.  Constant on all 1288 real sorters.
OUTPUT_FROM_SLOT = 0
INPUT_TO_SLOT = 1

#: What the belt side of a connection carries.  Also constant on all 1288.
BELT_SLOT = -1

#: How far a sorter end may sit from the slot pose it names, in tiles.
#:
#: ``0.8f`` in ``BuildTool_BlueprintCopy.CheckInserterDataLegal`` and again in
#: the blueprint-paste path.  A game constant, not one of ours.
SLOT_REACH = 0.8

#: How far off a slot's facing a sorter may run, in degrees, and the cosine of
#: it.  ``24f`` in ``BuildTool_BlueprintPaste``, where exceeding it is
#: ``EBuildCondition.TooSkew``.
SLOT_ALIGN_DEG = 24.0
SLOT_ALIGN_COS = math.cos(math.radians(SLOT_ALIGN_DEG))


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
    """Slot ``slot``'s position relative to the building's centre, in world tiles.

    This is the game's ``slotPoses[slot].GetTransformedBy(objectPose)``, minus
    the building's own position: the pose is rotated by the building's yaw and
    left where the caller can add the centre to it.  ``z`` is the pose's own
    height above the build plane and is not affected by yaw.
    """
    p = _pose(item_id, slot)
    wx, wy = to_world((p.dx, p.dy), yaw)
    return (wx, wy, p.dz)


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


def _centre(b: PlacedBuilding) -> tuple[float, float]:
    """A placed building's footprint centre, in tiles.

    ``PlacedBuilding.x`` is the minimum corner.  Every catalog footprint is odd
    (``test_no_catalog_footprint_is_even`` keeps it that way), so this is exact.
    """
    return (b.x + (b.width - 1) / 2, b.y + (b.height - 1) / 2)


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
    """Fill in every sorter's four slot fields and its yaw from its geometry.

    A strategy places sorters; it does not have to know these conventions.  Both
    strategies run their finished building list through here, which is why there
    is one place to be right rather than four call sites to keep in step.

    Raises :class:`SlotUndetermined` if any sorter's slot cannot be derived.
    Emitting a guess instead is what this module exists to stop.
    """
    out: list[PlacedBuilding] = []
    for b in buildings:
        if not cat.is_sorter(b.item_id):
            out.append(b)
            continue
        if b.x2 is None or b.y2 is None:
            raise SlotUndetermined(
                "sorter is missing its second anchor, so neither end can be "
                "attributed to a building"
            )
        head = (b.x, b.y)
        tail = (b.x2, b.y2)
        # `input_obj` is what the sorter draws from and sits under the first
        # anchor; `output_obj` is what it feeds and sits under the second.
        input_from = (
            b.input_from_slot
            if b.input_obj is None
            else _peer_slot(buildings[b.input_obj], head, tail)
        )
        output_to = (
            b.output_to_slot
            if b.output_obj is None
            else _peer_slot(buildings[b.output_obj], tail, head)
        )
        yaw = sorter_yaw(head, tail)
        out.append(
            replace(
                b,
                output_to_slot=output_to,
                input_from_slot=input_from,
                output_from_slot=OUTPUT_FROM_SLOT,
                input_to_slot=INPUT_TO_SLOT,
                yaw=yaw,
                yaw2=yaw,
            )
        )
    return tuple(out)
