"""Strategy-side witnesses for R4.

The plan's two worked examples are both of this shape: *"bump ``SLOT_REACH`` to
0.4 and ``slots.attachment`` must start refusing"*, *"bump
``colliders.BELT_PROBE_RADIUS`` and freeform's ``belt_ban`` must widen."*  Not
"a test file goes red" -- a named piece of SEARCH code must compute a different
answer.  That is what a probe is here.

Direct calls rather than ``lay_out``, for two reasons.  Every test in
``test_spine.py`` and ``test_freeform.py`` takes a fixture, so none is callable
without a pytest session; and a full solve costs a CP-SAT budget per constant,
which fifty-four constants cannot afford inside a 300-second limit.  A probe
costs microseconds, so R4 can run the WHOLE set against every constant instead
of guessing which one matters -- which is the property that keeps the mechanism
honest.  A probe suite that is too narrow reports "the search ignores this
rule" when the truth is "I did not ask the right question".

A probe returns anything comparable.  It may raise: a rule perturbed hard
enough to make search code throw has demonstrably been consulted, so
:func:`snapshot` records the exception rather than letting it escape.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from fractions import Fraction
from typing import Any

from flab2bp.dsp import catalog, rules
from flab2bp.layout import freeform, geometry, junction, slots, spine
from flab2bp.layout.base import PlacedBuilding

#: Item ids with real colliders, slot poses and footprints, picked once so the
#: probe scene never depends on what a solver happened to choose.
ASSEMBLER = 2303
SMELTER = 2302
CHEMICAL_PLANT = 2309
BELT = 2001
SORTER = 2012


def _b(item_id: int, x: int, y: int, *, z: int = 0, yaw: float = 0.0) -> PlacedBuilding:
    w, h = catalog.footprint(item_id)
    return PlacedBuilding(
        item_id=item_id,
        model_index=catalog.building(item_id).model_index,
        x=x,
        y=y,
        z=Fraction(z),
        width=w,
        height=h,
        yaw=yaw,
    )


def scene() -> tuple[PlacedBuilding, ...]:
    """A small fixed arrangement: two machines, a linked belt lane, a sorter.

    The sorter's anchors come from ``slots.attachment`` rather than from a
    guess, so the scene is one the search itself would have produced -- a probe
    scene that no strategy would ever build proves nothing about a strategy.
    """
    machine = _b(ASSEMBLER, 0, 0)
    lane_y = 3
    seat = slots.attachment(machine, (0, lane_y))
    assert seat is not None, "the probe scene's own geometry has stopped working"
    # Indices 2..5 once the two machines are in front, so the lane links up.
    first = 2
    belts = [
        replace(
            _b(BELT, x, lane_y),
            output_obj=first + x + 1 if x < 3 else None,
            input_obj=first + x - 1 if x else None,
        )
        for x in range(4)
    ]
    sorter = PlacedBuilding(
        item_id=SORTER,
        model_index=catalog.building(SORTER).model_index,
        x=0,
        y=lane_y,
        z=Fraction(0),
        x2=seat.cell[0],
        y2=seat.cell[1],
        z2=Fraction(0),
    )
    return (machine, _b(SMELTER, 6, 0), *belts, sorter)


def _attachment() -> Any:
    machine = slots.probe_building(ASSEMBLER, 0.0)
    return [(d, str(slots.attachment(machine, (0, d)))) for d in range(2, 7)]


def _attachable_columns() -> Any:
    machine = slots.probe_building(ASSEMBLER, 0.0)
    return {y: sorted(slots.attachable_columns(machine, y)) for y in (3, 4, 5, 6)}


def _machine_slots() -> Any:
    out: list[Any] = []
    for item_id in (ASSEMBLER, SMELTER, CHEMICAL_PLANT):
        for yaw in (0.0, 90.0):
            for offset in ((0.0, -1.5), (1.5, 0.0), (0.0, 1.5)):
                try:
                    out.append(slots.machine_slot(item_id, yaw, offset, (0.0, 1.0)))
                except Exception as exc:  # noqa: BLE001 - a refusal IS the signal
                    out.append(type(exc).__name__)
    return out


def _slot_poses() -> Any:
    return [
        slots.slot_offset(item_id, yaw, slot)
        for item_id in (ASSEMBLER, SMELTER)
        for yaw in (0.0, 90.0)
        for slot in (0, 1, 2)
    ]


def _slot_forwards() -> Any:
    return [slots.slot_forward(ASSEMBLER, yaw, slot) for yaw in (0.0, 90.0) for slot in (0, 1)]


def _lane_facing() -> Any:
    return [slots.lane_facing(i, yaw) for i in (ASSEMBLER, SMELTER) for yaw in (0.0, 90.0, 180.0)]


def _junction_keepout() -> Any:
    return [junction.keepout_cells(0, 0, lvl) for lvl in (0, 1, 2)]


def _belt_floor_over() -> Any:
    return [str(spine._belt_floor_over(b)) for b in scene()]


def _tower_reach() -> Any:
    radius = Fraction(catalog.TESLA_COVER_RADIUS)
    return (
        geometry.reach_table(radius),
        geometry.greedy_tower_xs(x0=0, width=40, hr=3, tower_w=1),
        geometry.covered_by([(0, 0), (8, 0), (12, 0)], [(0.0, 0.0)], radius),
    )


def _addon_area_step() -> Any:
    return [spine._addon_area_step(yaw) for yaw in (0.0, 90.0, 180.0, 270.0)]


def _legal_links() -> Any:
    """Freeform's own step-legality table, which is what routes belts.

    The only probe that reaches the router.  Plan step 2.2 wants
    ``_RAMPS``/``_legal_link``/``_altitude_profile`` rebuilt as a projection of
    ``MAX_BELT_SLOPE`` and ``BELT_Z_PER_WORLD_UNIT``; until then this is where
    R4 can see whether the search consults the slope rule or restates it.
    """
    steps = [Fraction(n, 2) for n in range(-4, 5)]
    return [
        (str(dz), dx, ramped, freeform._legal_link(0, 0, Fraction(0), dx, 0, dz, ramped=ramped))
        for ramped in (True, False)
        for dx in (0, 1, 2)
        for dz in steps
    ]


def _altitude_profiles() -> Any:
    paths = [
        [(0, 0, 0), (1, 0, 0), (2, 0, 1), (3, 0, 1), (4, 0, 0)],
        [(0, 0, 0), (1, 0, 1), (2, 0, 2)],
        [(0, 0, 2), (1, 0, 2), (2, 0, 1), (3, 0, 0)],
    ]
    out: list[Any] = []
    for path in paths:
        for ramped in (True, False):
            got = freeform._altitude_profile(path, ramped=ramped)
            out.append(None if got is None else [str(z) for z in got])
    return out


def _sorter_seats() -> Any:
    buildings = scene()
    return [str(b) for b in slots.sorter_seat_boxes(buildings)]


def _assigned_sorter_slots() -> Any:
    return [
        (b.output_obj, b.output_to_slot, b.input_obj, b.input_from_slot)
        for b in slots.assign_sorter_slots(scene())
    ]


def _assigned_belt_slots() -> Any:
    return [
        (b.output_obj, b.output_to_slot, b.input_obj, b.input_from_slot)
        for b in slots.assign_belt_slots(scene())
    ]


def _splitter_ports() -> Any:
    j = junction.make_splitter(2, 9, Fraction(0))
    out: list[Any] = [
        (j.item_id, j.x, j.y, str(j.z), j.input_to_slot, j.output_from_slot),
    ]
    belts = [_b(BELT, x, 8) for x in range(int(rules.SPLITTER_MAX_PORTS) + 2)]
    for belt in belts:
        try:
            wired = junction.attach_input(belt, 99)
            out.append((wired.output_obj, wired.output_to_slot, wired.input_to_slot))
        except Exception as exc:  # noqa: BLE001 - a refusal IS the signal
            out.append(type(exc).__name__)
    try:
        junction.check_ports([j, *(replace(b, output_obj=0) for b in belts)])
        out.append("ports-ok")
    except Exception as exc:  # noqa: BLE001 - a refusal IS the signal
        out.append(type(exc).__name__)
    return out


def _footprints_and_clearance() -> Any:
    return [
        (catalog.footprint(i), catalog.clearance(i, yaw))
        for i in (ASSEMBLER, SMELTER, CHEMICAL_PLANT, BELT)
        for yaw in (0.0, 90.0)
    ]


def _belt_rates() -> Any:
    return [
        (i, str(catalog.BELT_RATE[i]), str(catalog.sorter_rate(SORTER, span)))
        for i in catalog.BELT_RATE
        for span in (1, 2)
    ]


def _belt_ceiling() -> Any:
    return [str(catalog.belt_max_z(level)) for level in (3, 9, 13, 15)]


#: Every probe, run against every perturbation.  Adding one can only make R4
#: stricter, so it is always the right move when a rule reports as ignored.
PROBES: dict[str, Callable[[], Any]] = {
    "slots.attachment": _attachment,
    "slots.attachable_columns": _attachable_columns,
    "slots.machine_slot": _machine_slots,
    "slots.slot_offset": _slot_poses,
    "slots.slot_forward": _slot_forwards,
    "slots.lane_facing": _lane_facing,
    "slots.sorter_seat_boxes": _sorter_seats,
    "slots.assign_sorter_slots": _assigned_sorter_slots,
    "slots.assign_belt_slots": _assigned_belt_slots,
    "junction.keepout_cells": _junction_keepout,
    "junction.attach_input": _splitter_ports,
    "spine._belt_floor_over": _belt_floor_over,
    "geometry.tower_reach": _tower_reach,
    "spine._addon_area_step": _addon_area_step,
    "freeform._legal_link": _legal_links,
    "freeform._altitude_profile": _altitude_profiles,
    "catalog.footprint/clearance": _footprints_and_clearance,
    "catalog.belt_rate/sorter_rate": _belt_rates,
    "catalog.belt_max_z": _belt_ceiling,
}


def snapshot() -> dict[str, str]:
    """Every probe's answer, as text.  An exception is an answer."""
    out: dict[str, str] = {}
    for name, probe in PROBES.items():
        try:
            out[name] = repr(probe())
        except Exception as exc:  # noqa: BLE001 - a refusal IS the signal
            out[name] = f"<raised {type(exc).__name__}: {exc}>"
    return out


def changed(before: dict[str, str], after: dict[str, str]) -> tuple[str, ...]:
    return tuple(sorted(k for k in before if before[k] != after.get(k)))
