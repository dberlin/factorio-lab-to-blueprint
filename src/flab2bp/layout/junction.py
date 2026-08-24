"""Splitters: the primitive that lets one belt serve more than one destination.

Both layout strategies needed this and neither had it.  A belt tile carries a
single ``output_obj``, so a lane feeding two consumers could only ever be linked
to one of them; freeform laid the losing paths down anyway as belts nothing fed,
and spine never joined an item's corridor copies at all.

The convention below is not invented.  It is read off the 25 splitters in the
fixture corpus, every one of which agrees:

* The splitter records **no links of its own** -- ``output_obj`` and
  ``input_obj`` are both ``-1``.  It is a passive junction; the belts around it
  do the naming.
* ``input_to_slot = 14`` and ``output_from_slot = 15`` on all 25, with both
  offsets ``0``.  These are constants, not geometry.
* Every belt attached to it sits at **exactly the same tile**: ``dx = dy = 0``.
  A belt that runs *through* a splitter is recorded as two belt buildings on
  that tile, one ending at the junction and one starting from it.
* A belt feeding the junction names it as that belt's ``output_obj``; a belt
  drawing from it names it as that belt's ``input_obj``.
* Observed fan-in was 1 or 2 belts.  The game's splitter has four ports, so up
  to four attachments on a tile is legal; :data:`MAX_PORTS` records that and
  :func:`check_ports` enforces it, because exceeding it would paste as a
  splitter quietly dropping connections rather than as an error.

Because attachments share a tile, any occupancy check must treat splitters and
belts as overlays -- which ``catalog.BELT_INTEGRATED_IDS`` already does.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from fractions import Fraction

from flab2bp.dsp import catalog
from flab2bp.layout.base import PlacedBuilding

#: Slot indices every splitter in the corpus uses, without exception.
INPUT_TO_SLOT = 14
OUTPUT_FROM_SLOT = 15

#: Ports on a DSP splitter.  Four sides, so at most four belts may attach to one
#: junction tile -- counting both the ones feeding it and the ones drawing from
#: it, since each occupies a side.
MAX_PORTS = 4


class TooManyPorts(ValueError):
    """More belts attached to one junction than a splitter has sides."""


def site_is_clear(buildings: Sequence[PlacedBuilding], x: int, y: int) -> bool:
    """May a junction stand at ``(x, y)`` without its collider hitting anything?

    A splitter is belt-integrated and reports no occupied tile, so nothing in
    the packer or the router knows it is there -- but its collider is a CROSS
    whose arms reach 1.19 world units, and a tile is 1.2566.  Against an
    Assembling Machine reaching 1.91 that is 2.47 units of separation required,
    which is THREE tiles centre to centre.  A lane runs directly beside a
    machine band by design, so a junction taken on such a lane sits two tiles
    from the machine's centre and intersects it: 21 of the 25 collisions left on
    our output were exactly this.

    Refusing the site is what a caller wants here -- routing has other tiles to
    try, and a tap that cannot be made is one the router works around rather
    than a build that fails.

    BELTS, SPLITTERS AND SORTERS ARE NOT OBSTACLES, AND COUNTING THEM MADE THIS
    PREDICATE REFUSE EVERY SITE A JUNCTION HAS.
    -------------------------------------------------------------------------
    This module's own docstring says it: "Because attachments share a tile, any
    occupancy check must treat splitters and belts as overlays".  A junction is
    CO-LOCATED with the belt it splits -- that is the corpus convention, a belt
    running through a splitter recorded as two belts on the tile -- so the belt
    at distance 0.0 was always there, and against a belt's clearance of 1 the
    requirement is 2.0 tiles.  A junction could therefore never be built on a
    belt, nor within two tiles of the next belt along the same lane, which is
    every lane tile there is.  Sorters are the same story one tile out: one
    stands between every lane and its machine, clearance 1, requirement 2.0.

    MEASURED, and the control is the shipped predicate on the same specs in the
    same process: with belts and sorters counted, `universe-matrix`'s
    `no-proliferator` candidate refused at every candidate height -- 10 packs
    routed, each losing exactly one or two nets, and every one of those losses
    was `_tap_source` returning False here.  Without them it lays out and
    validates clean.  Nothing else changed.

    The scope now matches ``geom.collide``, which is the check this placement
    will actually be judged by: it tests neither belts nor sorters, because the
    game excuses a sorter against anything that is not a sorter and our belt
    model over-reports on blueprints the game itself wrote.  A gate stricter
    than the verdict it guards is not caution; it is a refusal the verdict
    would never have made.
    """
    sw, sh = catalog.clearance(catalog.SPLITTER_ID, 0.0)
    mine = max(sw, sh)
    for b in buildings:
        if catalog.is_belt_integrated(b.item_id) or catalog.is_sorter(b.item_id):
            continue
        try:
            info = catalog.building(b.item_id)
        except KeyError:
            continue
        if not info.occupies_tiles:
            continue
        need = (mine + max(catalog.clearance(b.item_id, b.yaw))) / 2.0
        for dx in range(b.width):
            for dy in range(b.height):
                if math.hypot(x - (b.x + dx), y - (b.y + dy)) < need:
                    return False
    return True


def make_splitter(
    x: int, y: int, z: Fraction = Fraction(0), *, carries_item: str | None = None
) -> PlacedBuilding:
    """A junction at ``(x, y, z)``, ready for belts to attach to it.

    ``width``/``height`` are 1 rather than the catalog's derived ``3x1``.  The
    derived figure comes from the model's bounding box, but a splitter is
    belt-integrated: it shares the tile of the belts it joins and excludes
    nothing, so a 3-tile footprint would make the occupancy check reject
    layouts the game accepts.

    ``carries_item`` is layout bookkeeping, matching the belts it joins, so the
    validator can attribute a junction to a lane.
    """
    return PlacedBuilding(
        item_id=catalog.SPLITTER_ID,
        model_index=catalog.building(catalog.SPLITTER_ID).model_index,
        x=x,
        y=y,
        z=z,
        width=1,
        height=1,
        # Deliberately unlinked. The corpus is unanimous: the junction names
        # nobody, and the belts around it name it.
        input_obj=None,
        output_obj=None,
        input_to_slot=INPUT_TO_SLOT,
        output_from_slot=OUTPUT_FROM_SLOT,
        carries_item=carries_item,
    )


def check_ports(buildings: list[PlacedBuilding] | tuple[PlacedBuilding, ...]) -> None:
    """Raise if any splitter has more belts attached than it has sides.

    Checked at emission rather than left to the validator because the failure is
    silent in game: a splitter with five attachments pastes cleanly and drops
    one of them, which is precisely the class of bug splitters were introduced
    to fix.
    """
    junctions = {
        i for i, b in enumerate(buildings) if b.item_id == catalog.SPLITTER_ID
    }
    if not junctions:
        return
    ports: dict[int, int] = dict.fromkeys(junctions, 0)
    for b in buildings:
        for link in (b.output_obj, b.input_obj):
            if link is not None and link in ports:
                ports[link] += 1
    over = {i: n for i, n in ports.items() if n > MAX_PORTS}
    if over:
        first = next(iter(over))
        raise TooManyPorts(
            f"splitter {first} at ({buildings[first].x}, {buildings[first].y}) has "
            f"{over[first]} belts attached but a splitter has {MAX_PORTS} sides; "
            f"{len(over)} junction(s) over the limit"
        )


def attach_input(belt: PlacedBuilding, junction: int) -> PlacedBuilding:
    """``belt`` now feeds ``junction``."""
    return _replace_links(belt, output_obj=junction)


def attach_output(belt: PlacedBuilding, junction: int) -> PlacedBuilding:
    """``belt`` now draws from ``junction``."""
    return _replace_links(belt, input_obj=junction)


def _replace_links(
    belt: PlacedBuilding, *, output_obj: int | None = None, input_obj: int | None = None
) -> PlacedBuilding:
    from dataclasses import replace

    changes: dict[str, int] = {}
    if output_obj is not None:
        changes["output_obj"] = output_obj
    if input_obj is not None:
        changes["input_obj"] = input_obj
    return replace(belt, **changes)  # type: ignore[arg-type]
