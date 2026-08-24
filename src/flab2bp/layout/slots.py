"""Which slot a sorter names on the building it touches.

Every sorter we emitted before this module existed carried ``(0, 0, 0, 0)`` in
its four slot fields.  Pasted into the game that produced four errors and drew
**every** sorter red -- the first time anything we built was tried in game.  The
validator passed the same build with ``INVALID 0``, because nothing in it looked
at these fields at all.

Everything below is read off the 1288 sorters in ``tests/fixtures/*.txt``, all
of which the game itself wrote, and is re-derived from their geometry by
``tests/layout/test_sorter_slots.py`` on every run.

THE THREE CONSTANTS
-------------------
``output_from_slot == 0`` and ``input_to_slot == 1`` on all 1288, without a
single exception.  These are the sorter's *own* ends and never vary.  The BELT
side of a connection is always ``-1`` (849 belt inputs, 391 belt outputs, no
other value).  Only the MACHINE side carries a real index.

THE MACHINE-SIDE RING
---------------------
A building's insert slots form a ring of **twelve**, three per side, whatever
its footprint.  That is not an assumption: the Matrix Lab is 5x5 and its west
side is slots 3/4/5, so its south side holds three and not five.  Measured slot
poses, in the machine's own frame, in tiles from its centre:

    Assembling Machine Mk.I  0:(-0.81,+0.86) 1:(0,+0.86) 2:(+0.81,+0.86)
                             3:(+0.89,+0.81) 4:(+0.89, 0) 5:(+0.89,-0.81)
                             6:(+0.81,-0.86) 7:(0,-0.86) 8:(-0.81,-0.86)
                             9:(-0.89,-0.81) 10:(-0.89,0) 11:(-0.89,+0.81)

The three slots on a side sit ~0.8 apart regardless of how long that side is,
so on a wide building they occupy only its middle three columns; the side's
*offset* from the centre is what scales with the footprint.  Rounded to tiles
that gives an offset in ``{-1, 0, +1}`` along the side, which is what
:func:`machine_slot` computes.

At a corner tile the offset alone is ambiguous -- eight perimeter tiles, twelve
slots -- and the sorter's approach direction disambiguates it: a vertical
approach means the north/south side, a horizontal one the east/west side.  All
343 corner records in the corpus agree, with no ties.

Machine yaw rotates the ring with the building: the offset and the approach are
both un-rotated into the machine's frame first.  Verified at yaw 0, 90, 180
and 270.

HANDEDNESS, AND WHAT COULD NOT BE DERIVED
-----------------------------------------
Two families exist, mirrored in the machine's local x axis:

* **Not mirrored** -- south side runs west->east.  Observed on Assembling
  Machine Mk.I and Mk.III, Arc Smelter, Negentropy Smelter, Depot Mk.I.
* **Mirrored** -- south side runs east->west.  Observed on Matrix Lab and Oil
  Refinery.

Both appear in the *same* fixture (``12-s-purple-science`` has assemblers of one
handedness and Matrix Labs of the other), so this is not a coordinate artifact
of one blueprint; it is authored per prefab, and DSP ships no slot poses for any
of these buildings for us to read.  **The rule that predicts handedness from
building data was not derived.**  Every one of the five un-mirrored buildings is
3x3 and both mirrored ones are larger, so :data:`_MIRRORED` records what was
observed and :func:`ring_is_mirrored` extends it by footprint -- an inference
from n=2 on the mirrored side, and the weakest link in this module.
:func:`handedness_is_observed` reports which buildings that inference covers so
the validator can say so out loud.

Getting the handedness wrong moves a slot to its mirror image on the same side
(0 <-> 2, 3 <-> 11, ...); the middle of the north and south sides (7 and 1) is
the same either way.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from flab2bp.dsp import catalog as cat
from flab2bp.layout.base import PlacedBuilding

__all__ = [
    "BELT_SLOT",
    "INPUT_TO_SLOT",
    "OUTPUT_FROM_SLOT",
    "SLOTS_PER_SIDE",
    "SLOT_COUNT",
    "SlotUndetermined",
    "assign_sorter_slots",
    "handedness_is_observed",
    "machine_slot",
    "ring_is_mirrored",
    "side_offset",
]

#: The sorter's own ends.  Constant on all 1288 real sorters.
OUTPUT_FROM_SLOT = 0
INPUT_TO_SLOT = 1

#: What the belt side of a connection carries.  Also constant on all 1288.
BELT_SLOT = -1

#: Slots per side, and therefore per building.  Independent of footprint.
SLOTS_PER_SIDE = 3
SLOT_COUNT = 4 * SLOTS_PER_SIDE


class SlotUndetermined(ValueError):
    """A sorter's slot could not be derived from geometry.

    Raised rather than defaulted.  A guessed ``0`` is exactly what made every
    sorter in the first in-game paste invalid, so there is no fallback here.
    """


#: Handedness as read off the corpus, keyed by DSP item id.  ``True`` means the
#: ring is mirrored in the machine's local x axis (south side runs east->west).
#:
#: Only buildings with corpus evidence appear.  Nothing may be added here on a
#: hunch -- ``test_slot_handedness_matches_corpus`` re-derives every entry.
_MIRRORED: dict[int, bool] = {
    2101: False,  # Depot Mk.I           99 records
    2302: False,  # Arc Smelter          20
    2303: False,  # Assembling Mk.I     197
    2305: False,  # Assembling Mk.III   648
    2319: False,  # Negentropy Smelter  200
    2308: True,  # Oil Refinery          36
    2901: True,  # Matrix Lab            47
}


def handedness_is_observed(item_id: int) -> bool:
    """Is this building's ring handedness read from the corpus, or inferred?"""
    return item_id in _MIRRORED


def ring_is_mirrored(item_id: int) -> bool:
    """Whether ``item_id``'s slot ring is mirrored in the machine's local x.

    Observed values win.  For everything else this falls back to the only
    predicate consistent with the corpus -- 3x3 is un-mirrored, larger is
    mirrored -- which is an inference, not a measurement.  See the module
    docstring.
    """
    observed = _MIRRORED.get(item_id)
    if observed is not None:
        return observed
    b = cat.building(item_id)
    return (b.width, b.height) != (3, 3)


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


def _along(t: float) -> int:
    """Which of a side's three slots sits nearest offset ``t`` along it.

    The slots are ~0.8 apart whatever the side's length, so on anything wider
    than three tiles they cover only the middle three columns and an anchor
    further out has no slot directly beside it.  Clamping picks the nearest,
    which is what the game does when it snaps a sorter end onto a slot pose.
    """
    return max(-1, min(1, int(round(t))))


def machine_slot(
    item_id: int,
    yaw: float,
    offset: tuple[float, float],
    approach: tuple[float, float],
) -> int:
    """The slot index a sorter names on the machine it touches.

    ``offset`` is the sorter's machine-side end minus the machine's centre, in
    world tiles.  ``approach`` is that same end minus the sorter's *other* end,
    so it points into the machine -- which is what tells a corner tile's two
    candidate slots apart.

    Raises :class:`SlotUndetermined` when the approach is exactly diagonal, in
    which case neither side is the one the sorter came through.
    """
    lx, ly = _unrotate(offset[0], offset[1], yaw)
    ax, ay = _unrotate(approach[0], approach[1], yaw)

    mirrored = ring_is_mirrored(item_id)
    if abs(ax) == abs(ay):
        raise SlotUndetermined(
            f"sorter approaches building {item_id} diagonally by "
            f"({approach[0]}, {approach[1]}); no side is the one it entered"
        )

    if abs(ay) > abs(ax):
        # Vertical approach: it came through the north or south side, whichever
        # faces the direction it travelled from.
        south = ay < 0
        step = _along(lx)
        if mirrored:
            return (1 - step) if south else 6 + (step + 1)
        return (step + 1) if south else 6 + (1 - step)

    east = ax < 0
    step = _along(ly)
    if mirrored:
        return 9 + (step + 1) if east else 3 + (1 - step)
    return 3 + (1 - step) if east else 9 + (step + 1)


def side_offset(
    item_id: int,
    yaw: float,
    offset: tuple[float, float],
    approach: tuple[float, float],
) -> float | None:
    """How far along its side a sorter's machine end sits, in tiles from centre.

    The three slots on a side span roughly ``[-1, +1]`` about its centre, so an
    ``abs()`` above 1 means the end is beside no slot at all and
    :func:`machine_slot` clamped to the nearest.  ``None`` when the side cannot
    be identified, which is the same condition :func:`machine_slot` refuses on.
    """
    ax, ay = _unrotate(approach[0], approach[1], yaw)
    if abs(ax) == abs(ay):
        return None
    lx, ly = _unrotate(offset[0], offset[1], yaw)
    return lx if abs(ay) > abs(ax) else ly


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


def assign_sorter_slots(
    buildings: Sequence[PlacedBuilding],
) -> tuple[PlacedBuilding, ...]:
    """Fill in every sorter's four slot fields from the geometry around it.

    A strategy places sorters; it does not have to know this convention.  Both
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
        out.append(
            replace(
                b,
                output_to_slot=output_to,
                input_from_slot=input_from,
                output_from_slot=OUTPUT_FROM_SLOT,
                input_to_slot=INPUT_TO_SLOT,
            )
        )
    return tuple(out)
