"""Splitters: the primitive that lets one belt serve more than one destination.

Both layout strategies needed this and neither had it.  A belt tile carries a
single ``output_obj``, so a lane feeding two consumers could only ever be linked
to one of them, so this shared junction primitive provides explicit fan-in and
fan-out.

The connection convention is read from the game and its blueprints:

* The splitter records **no ordinary links of its own** -- ``output_obj`` and
  ``input_obj`` are both ``-1``.  The belts around it do the naming.
* Its four multilevel sentinel fields are ``14, 15, 15, 14``.
* A belt feeding the junction names it as that belt's ``output_obj``; a belt
  drawing from it names it as that belt's ``input_obj``.
* In the integer layout lattice an attachment shares the splitter tile.  At
  blueprint emission the belt anchor moves to the exact transformed
  ``PrefabDesc.portPoses`` entry.  Keeping the emitted anchor at the tile centre
  makes the paste collider test mark both the belt and splitter broken.
* The game exposes four physical ports, so at most four belts may attach.

Integer occupancy therefore treats splitters and belts as overlays.  Emission
materializes the distinct physical port anchors.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import replace
from fractions import Fraction

from flab2bp.dsp import catalog
from flab2bp.dsp import colliders as dsp_colliders
from flab2bp.dsp.rules import (
    SPLITTER_INPUT_FROM_SLOT,
    SPLITTER_INPUT_TO_SLOT,
    SPLITTER_MAX_PORTS,
    SPLITTER_OUTPUT_FROM_SLOT,
    SPLITTER_OUTPUT_TO_SLOT,
)
from flab2bp.layout.base import PlacedBuilding

# The splitter's slot indices and its port count are the GAME's rules, stated
# with their provenance in `flab2bp.dsp.rules`.  They were named
# `INPUT_TO_SLOT`/`OUTPUT_FROM_SLOT` here -- the same two names `layout.slots`
# uses for a SORTER's own ends, holding different values -- and carry the
# `SPLITTER_` prefix now so the two can never be confused again.


class TooManyPorts(ValueError):
    """More belts attached to one junction than a splitter has sides."""


def _keepout() -> frozenset[tuple[int, int, int]]:
    return dsp_colliders.belt_keepout_offsets(catalog.building(catalog.SPLITTER_ID).model_index)


def keepout_cells(x: int, y: int, level: int) -> tuple[tuple[int, int, int], ...]:
    """Routing cells a junction at ``(x, y, level)`` denies to a FOREIGN belt.

    The lateral half of the game's belt rule, which
    :func:`flab2bp.dsp.colliders.belt_keepout_offsets` measures rather than
    asserts: the four orthogonal neighbours and the tile itself, at this level
    and at the one above it.  Two levels up clears -- the collider stands 2.30
    world units and a level is 4/3 -- and so does every diagonal.

    A belt on the junction's own run is EXCUSED by the game
    (``colliders.belt_chain_excuses``), so these cells are denied only to belts
    that are not part of it.  The caller knows which those are; this function
    knows only the geometry.

    ``level`` is a ROUTING LEVEL, and it is the same integer as the junction's
    blueprint ``z`` because a junction always rests on a level.
    """
    return tuple((x + dx, y + dy, level + dz) for dx, dy, dz in _KEEPOUT)


#: The offsets, resolved once. :func:`keepout_cells` is in a routing inner loop.
_KEEPOUT: tuple[tuple[int, int, int], ...] = tuple(sorted(_keepout()))


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
    mine = max(catalog.collider_span(catalog.SPLITTER_ID, 0.0))
    for b in buildings:
        if catalog.is_belt_integrated(b.item_id) or catalog.is_sorter(b.item_id):
            continue
        try:
            info = catalog.building(b.item_id)
        except KeyError:
            continue
        if not info.occupies_tiles:
            continue
        need = (mine + max(catalog.collider_span(b.item_id, b.yaw))) / 2.0
        centre_x = b.x + (b.width - 1) / 2.0
        centre_y = b.y + (b.height - 1) / 2.0
        if math.hypot(x - centre_x, y - centre_y) < need:
            return False
    return True


def make_splitter(
    x: int, y: int, z: Fraction = Fraction(0), *, carries_item: str | None = None
) -> PlacedBuilding:
    """A junction at ``(x, y, z)``, ready for belts to attach to it.

    ``width``/``height`` are 1, which the catalog now agrees with: a splitter's
    arms reach 1.19 world units and a tile is 1.2566, so it covers exactly one
    tile centre.  This used to disagree with a catalog that derived ``3x1`` by
    treating a tile as one world unit, and was forced by hand for the reason
    that reading was wrong -- a splitter is belt-integrated, it shares the tile
    of the belts it joins and excludes nothing, and a 3-tile footprint made the
    occupancy check reject layouts the game accepts.  The hand-forcing stays as
    the statement of intent; it is no longer a correction.

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
        # Ordinary links live on the belts.  The four sentinel fields are still
        # initialized exactly as BlueprintUtils initializes every Splitter.
        input_obj=None,
        output_obj=None,
        output_to_slot=SPLITTER_OUTPUT_TO_SLOT,
        input_from_slot=SPLITTER_INPUT_FROM_SLOT,
        input_to_slot=SPLITTER_INPUT_TO_SLOT,
        output_from_slot=SPLITTER_OUTPUT_FROM_SLOT,
        carries_item=carries_item,
    )


def splitter_stack_levels(level: int) -> tuple[int, ...]:
    """Blueprint heights needed to support a Splitter at routing ``level``.

    DSP Splitters stack at the prefab's two-level pitch.  A one-level offset
    intersects the lower Splitter collider, and an elevated Splitter without
    the linked chain below it fails the paste foundation check.
    """
    pitch = catalog.stack_pitch_z(catalog.SPLITTER_ID)
    if pitch is None or pitch.denominator != 1:
        raise RuntimeError("DSP Splitter prefab defines no integral stack pitch")
    step = int(pitch)
    if level < 0 or level % step:
        raise ValueError(
            f"Splitter routing level {level} does not align to stack pitch {step}"
        )
    return tuple(range(0, level + 1, step))


def make_splitter_stack(
    x: int,
    y: int,
    level: int,
    *,
    first_index: int,
    carries_item: str | None = None,
) -> tuple[PlacedBuilding, ...]:
    """Materialize a legal ground-supported Splitter stack.

    ``first_index`` is the placement index the bottom support will receive.
    Every higher member names the member immediately below through the
    Splitter's slot-15 support connection.  Only the top member participates in
    belt flow bookkeeping.
    """
    if first_index < 0:
        raise ValueError("Splitter stack first index must be non-negative")
    levels = splitter_stack_levels(level)
    buildings: list[PlacedBuilding] = []
    for offset, z in enumerate(levels):
        splitter = make_splitter(
            x,
            y,
            Fraction(z),
            carries_item=carries_item if z == level else None,
        )
        if offset:
            splitter = replace(splitter, input_obj=first_index + offset - 1)
        buildings.append(splitter)
    return tuple(buildings)


def check_ports(buildings: list[PlacedBuilding] | tuple[PlacedBuilding, ...]) -> None:
    """Raise if any splitter has more belts attached than it has sides.

    Checked at emission rather than left to the validator because the failure is
    silent in game: a splitter with five attachments pastes cleanly and drops
    one of them, which is precisely the class of bug splitters were introduced
    to fix.
    """
    junctions = {i for i, b in enumerate(buildings) if b.item_id == catalog.SPLITTER_ID}
    if not junctions:
        return
    ports: dict[int, int] = dict.fromkeys(junctions, 0)
    for b in buildings:
        if not catalog.is_belt(b.item_id):
            continue
        for link in (b.output_obj, b.input_obj):
            if link is not None and link in ports:
                ports[link] += 1
    over = {i: n for i, n in ports.items() if n > SPLITTER_MAX_PORTS}
    if over:
        first = next(iter(over))
        raise TooManyPorts(
            f"splitter {first} at ({buildings[first].x}, {buildings[first].y}) has "
            f"{over[first]} belts attached but a splitter has {SPLITTER_MAX_PORTS} sides; "
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

    changes: dict[str, int] = {}
    if output_obj is not None:
        changes["output_obj"] = output_obj
    if input_obj is not None:
        changes["input_obj"] = input_obj
    return replace(belt, **changes)  # type: ignore[arg-type]
