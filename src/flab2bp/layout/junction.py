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
from dataclasses import dataclass, replace
from fractions import Fraction
from functools import lru_cache

from flab2bp.dsp import catalog
from flab2bp.dsp import colliders as dsp_colliders
from flab2bp.dsp.rules import (
    SPLITTER_INPUT_FROM_SLOT,
    SPLITTER_INPUT_TO_SLOT,
    SPLITTER_MAX_PORTS,
    SPLITTER_OUTPUT_FROM_SLOT,
    SPLITTER_OUTPUT_TO_SLOT,
)
from flab2bp.layout import slots
from flab2bp.layout.base import PlacedBuilding

# The splitter's slot indices and its port count are the GAME's rules, stated
# with their provenance in `flab2bp.dsp.rules`.  They were named
# `INPUT_TO_SLOT`/`OUTPUT_FROM_SLOT` here -- the same two names `layout.slots`
# uses for a SORTER's own ends, holding different values -- and carry the
# `SPLITTER_` prefix now so the two can never be confused again.


class TooManyPorts(ValueError):
    """More belts attached to one junction than a splitter has sides."""


_MIXED_HEIGHT_SPLITTER_MODEL = 40
_CARDINAL_YAW: dict[tuple[int, int], float] = {
    (0, 1): 0.0,
    (1, 0): 90.0,
    (0, -1): 180.0,
    (-1, 0): 270.0,
}


@lru_cache(maxsize=16)
def _keepout(model_index: int, yaw: float) -> tuple[tuple[int, int, int], ...]:
    return tuple(sorted(dsp_colliders.belt_keepout_offsets(model_index, yaw)))


@lru_cache(maxsize=4096, typed=True)
def keepout_cells(
    x: int,
    y: int,
    level: int,
    *,
    model_index: int | None = None,
    yaw: float = 0.0,
) -> tuple[tuple[int, int, int], ...]:
    """Routing cells one real stack member denies to a FOREIGN belt.

    ``level`` is the member's blueprint anchor, not necessarily the carry
    level.  Model 40 carries its straight run on ports one level above that
    anchor and its orthogonal branch on the anchor plane.

    Only immutable translated geometry is retained. Selection, reservations,
    ownership, and whether a cell is currently admissible remain caller state.
    """
    model = (
        catalog.building(catalog.SPLITTER_ID).model_index if model_index is None else model_index
    )
    return tuple((x + dx, y + dy, level + dz) for dx, dy, dz in _keepout(model, yaw))


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
    x: int,
    y: int,
    z: Fraction = Fraction(0),
    *,
    model_index: int | None = None,
    yaw: float = 0.0,
    carries_item: str | None = None,
) -> PlacedBuilding:
    """A junction at ``(x, y, z)``, ready for belts to attach to it.

    The item selects model 38 by default.  ``model_index`` also selects model
    39's parallel two-height ports or model 40's elevated opposite ports with
    two lower orthogonal ports.
    """
    model = (
        catalog.building(catalog.SPLITTER_ID).model_index if model_index is None else model_index
    )
    if model not in catalog.SPLITTER_MODEL_INDICES:
        raise ValueError(f"model {model} is not a DSP Splitter model")
    return PlacedBuilding(
        item_id=catalog.SPLITTER_ID,
        model_index=model,
        x=x,
        y=y,
        z=z,
        width=1,
        height=1,
        yaw=yaw,
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


def make_piler(
    x: int,
    y: int,
    z: Fraction = Fraction(0),
    *,
    yaw: float = 0.0,
) -> PlacedBuilding:
    """An Automatic Piler at ``(x, y, z)`` facing ``yaw``.

    The piler names neither neighbouring belt.  The belt before it names piler
    port 1 as its output, and the belt after it names piler port 0 as its input;
    that wiring makes ``CargoTraffic.RematchPilerConnection`` select Pile mode.
    Its catalog row has ``multiLevel = 1``, so the game generator assigns the
    same ``14, 15, 15, 14`` multilevel sentinels used by a Splitter.

    There is no stack argument or parameter block.  A piler doubles the stack
    arriving on its input belt, capped at :data:`catalog.PILER_MAX_STACK`; lane
    planning decides how many pilers a belt traverses.
    """
    info = catalog.building(catalog.PILER_ID)
    width, height = catalog.oriented_footprint(catalog.PILER_ID, yaw)
    return PlacedBuilding(
        item_id=catalog.PILER_ID,
        model_index=info.model_index,
        x=x,
        y=y,
        z=z,
        width=width,
        height=height,
        yaw=yaw,
        output_to_slot=SPLITTER_OUTPUT_TO_SLOT,
        input_from_slot=SPLITTER_INPUT_FROM_SLOT,
        input_to_slot=SPLITTER_INPUT_TO_SLOT,
        output_from_slot=SPLITTER_OUTPUT_FROM_SLOT,
    )


def splitter_stack_levels(level: int) -> tuple[int, ...]:
    """Blueprint anchors needed for a junction carrying routing ``level``.

    Even carry levels use model 38 on that plane.  Odd carry levels use model
    40 anchored one level lower: its N/S pair is elevated and its E/W pair is
    on the anchor plane.  Every member below the top remains model 38 at the
    prefab's proven two-level support pitch.
    """
    pitch = catalog.stack_pitch_z(catalog.SPLITTER_ID)
    if pitch is None or pitch.denominator != 1:
        raise RuntimeError("DSP Splitter prefab defines no integral stack pitch")
    step = int(pitch)
    if level < 0:
        raise ValueError(f"Splitter routing level {level} is below ground")
    top_anchor = level - (level % step)
    return tuple(range(0, top_anchor + 1, step))


def make_splitter_stack(
    x: int,
    y: int,
    level: int,
    *,
    first_index: int,
    carries_item: str | None = None,
    carry_direction: tuple[int, int] | None = None,
) -> tuple[PlacedBuilding, ...]:
    """Materialize a legal ground-supported junction stack.

    Model 38 serves even carry levels.  Model 40 serves odd carry levels from
    one level below, with model yaw chosen so physical port 0 faces the actual
    carry direction.  Higher members name the member immediately below through
    the Splitter's slot-15 support connection; only the top carries items.
    """
    if first_index < 0:
        raise ValueError("Splitter stack first index must be non-negative")
    levels = splitter_stack_levels(level)
    mixed_height = bool(level % 2)
    if mixed_height:
        if carry_direction is None:
            raise ValueError("odd-level Splitter stack requires a carry direction")
        try:
            top_yaw = _CARDINAL_YAW[carry_direction]
        except KeyError as exc:
            raise ValueError(
                f"Splitter carry direction {carry_direction!r} is not cardinal"
            ) from exc
    else:
        top_yaw = 0.0

    buildings: list[PlacedBuilding] = []
    for offset, z in enumerate(levels):
        top = offset == len(levels) - 1
        splitter = make_splitter(
            x,
            y,
            Fraction(z),
            model_index=_MIXED_HEIGHT_SPLITTER_MODEL if top and mixed_height else None,
            yaw=top_yaw if top else 0.0,
            carries_item=carries_item if top else None,
        )
        if offset:
            splitter = replace(splitter, input_obj=first_index + offset - 1)
        buildings.append(splitter)
    return tuple(buildings)


@dataclass(frozen=True, slots=True)
class SplitterRoutePort:
    """A physical attachment and the lattice belt immediately outside it.

    ``physical_pose`` is the exact prefab pose rotated into layout axes, still
    in WORLD units relative to the top member's anchor.  It is not a blueprint
    coordinate: final spherical projection belongs to the existing encoder.
    ``dock`` is the adjoining integer belt cell at the port's carry altitude.
    The attachment belt itself retains the top member's integer x/y until
    emission moves it to this physical port.
    """

    slot: int
    dock: tuple[int, int, int]
    physical_pose: catalog.SlotPose


@dataclass(frozen=True, slots=True)
class SplitterRouteCandidate:
    """One cargo stream traversing two distinct ports of one supported top.

    The support members carry no cargo.  Their ``input_obj`` values use the
    ``first_index`` supplied to :func:`splitter_route_candidates`; a candidate
    built with zero must be rebased before appending it to another placement.
    ``foreign_keepout`` reserves the WHOLE stack against unrelated belts, not
    just the two selected ports.  A four-port Splitter is not two independent
    crossing channels.
    """

    stack_members: tuple[PlacedBuilding, ...]
    entry: SplitterRoutePort
    exit: SplitterRoutePort
    foreign_keepout: frozenset[tuple[int, int, int]]


@lru_cache(maxsize=12)
def _route_ports(model_index: int, yaw: float) -> tuple[SplitterRoutePort, ...]:
    """Local integer docks and unrounded rotated physical poses."""
    ports: list[SplitterRoutePort] = []
    for slot, pose in enumerate(catalog.port_poses_for_model(model_index)):
        dx, dy = slots.to_world((pose.dx, pose.dy), yaw)
        fx, fy = slots.to_world((pose.fx, pose.fy), yaw)
        # Asset port heights are rounded Unity values (1.3333 world units for
        # one level).  The lattice dock is integral; the physical pose is not
        # rounded, so final emission retains the exact game-backed attachment.
        height = pose.dz * float(catalog.BELT_Z_PER_WORLD_UNIT)
        level = round(height)
        outward = (round(fx), round(fy))
        if abs(height - level) > 1e-4 or outward not in _CARDINAL_YAW:
            raise RuntimeError(f"Splitter model {model_index} has a non-lattice port")
        ports.append(
            SplitterRoutePort(
                slot,
                (*outward, level),
                catalog.SlotPose(dx, dy, pose.dz, fx, fy, pose.fz),
            )
        )
    return tuple(ports)


def splitter_route_candidates(
    x: int,
    y: int,
    level: int,
    *,
    yaw: float,
    altitude_rules: catalog.BeltAltitudeRules,
    carries_item: str,
    first_index: int = 0,
) -> tuple[SplitterRouteCandidate, ...]:
    """Enumerate legal single-stream routes touching carry altitude ``level``.

    All three game models are considered at the ground-supported top anchor.
    Model 38 has four coplanar cardinal ports; model 39 has parallel N/S pairs
    at two heights; model 40 has upper N/S and lower E/W pairs.  Rotation uses
    their actual poses, not a shared guessed cardinal-port order.

    Only a selected port is subject to the belt ceiling; stack anchors are
    independently admitted by the save's storage-stack technology.  Internal
    Splitter height changes do not require the vertical BELT slope unlock.
    Cargo never moves through a slot-15 support link to another stack member.

    Emit separate co-located input/output attachment belts, at entry/exit
    dock z respectively.  The input names the top in ``output_obj`` and entry
    slot in ``output_to_slot``.  The output names the top in ``input_obj`` and
    exit slot in ``input_from_slot``, with ``BELT_PORT_DRAW_TO_SLOT`` on its
    own ``input_to_slot``.  Their outside neighbours occupy the two docks.
    Never coalesce the attachment records even when their lattice cells match.
    """
    if not math.isfinite(yaw) or yaw % 90.0:
        raise ValueError(f"Splitter route yaw {yaw} is not cardinal")
    if first_index < 0:
        raise ValueError("Splitter stack first index must be non-negative")
    levels = splitter_stack_levels(level)
    if level > altitude_rules.max_z:
        return ()
    top_anchor = levels[-1]
    if not catalog.vertical_construction_allowed(catalog.SPLITTER_ID, top_anchor, altitude_rules):
        return ()
    yaw %= 360.0
    supported = make_splitter_stack(
        x, y, top_anchor, first_index=first_index, carries_item=carries_item
    )
    candidates: list[SplitterRouteCandidate] = []
    for model_index in sorted(catalog.SPLITTER_MODEL_INDICES):
        ports = tuple(
            SplitterRoutePort(
                port.slot,
                (x + port.dock[0], y + port.dock[1], top_anchor + port.dock[2]),
                port.physical_pose,
            )
            for port in _route_ports(model_index, yaw)
            if 0 <= top_anchor + port.dock[2] <= altitude_rules.max_z
        )
        if not any(port.dock[2] == level for port in ports):
            continue
        members = (
            *supported[:-1],
            replace(supported[-1], model_index=model_index, yaw=yaw),
        )
        footprint = frozenset(
            cell
            for member in members
            for cell in keepout_cells(
                x, y, int(member.z), model_index=member.model_index, yaw=member.yaw
            )
        )
        candidates.extend(
            SplitterRouteCandidate(members, entry, exit, footprint)
            for entry in ports
            for exit in ports
            if entry.slot != exit.slot and level in (entry.dock[2], exit.dock[2])
        )
    return tuple(candidates)


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
