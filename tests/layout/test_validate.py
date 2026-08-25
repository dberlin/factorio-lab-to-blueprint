"""Tests for the layout validator.

Every check gets two tests: one minimal ``Placement`` that trips exactly that
check, and one that passes it.  A validator whose checks cannot fail is worse
than no validator at all, so the "trips it" half is the load-bearing one.
"""

from __future__ import annotations

import dataclasses
from fractions import Fraction
from pathlib import Path

import pytest

from flab2bp.dsp import params
from flab2bp.dsp.catalog import (
    DEFAULT_MAX_BELT_Z,
    ENERGY_EXCHANGER_ID,
    GEOMETRY_SAFE_FIXTURES,
    RAY_RECEIVER_ID,
    TESLA_COVER_RADIUS,
)
from flab2bp.dsp.catalog import building as catalog_building
from flab2bp.layout import junction
from flab2bp.layout.base import PlacedBuilding, Placement
from flab2bp.layout.slots import SlotUndetermined, assign_sorter_slots
from flab2bp.layout.validate import (
    CHECKS,
    NEEDS_GROUPS,
    Finding,
    IdMap,
    Kind,
    Report,
    Severity,
    _context,
    _kind,
    validate,
)
from flab2bp.spec import BuildSpec, MachineGroup, ProliferatorMode

ASSEMBLER = 2304  # Assembling Machine Mk.II, 4x4
SMELTER = 2302  # Arc Smelter, 3x3
BELT2 = 2002  # Conveyor Belt Mk.II, 12/s
SORTER3 = 2013  # Sorter Mk.III, 6/s at one tile
SORTER1 = 2011  # Sorter Mk.I, 1.5/s at one tile
TOWER = 2201  # Tesla Tower, cover radius 10.5, link distance 22.5
WIRELESS_TOWER = 2202  # Wireless Power Tower, the long-reach node: link 45.5
CHEM_PLANT = 2309  # Chemical Plant, 9x5 -- big enough to distinguish
                   # centre-based from tile-based power coverage
BELT_REQUIRED = "prolif.belt_required_edges_not_direct_inserted"


# --- builders --------------------------------------------------------------


def machine(
    x: int, y: int, *, item_id: int = ASSEMBLER, recipe_id: int = 1, z: Fraction | int = 0
) -> PlacedBuilding:
    b = catalog_building(item_id)
    return PlacedBuilding(
        item_id=item_id,
        model_index=b.model_index,
        x=x,
        y=y,
        z=Fraction(z),
        width=b.width,
        height=b.height,
        recipe_id=recipe_id,
    )


def belt(
    x: int,
    y: int,
    z: Fraction | int = 0,
    *,
    out: int | None = None,
    inp: int | None = None,
    item_id: int = BELT2,
    carries: str | None = None,
) -> PlacedBuilding:
    """A belt tile.

    ``out`` is the forward link belts chain with.  ``inp`` is used for exactly
    one thing: naming the splitter this belt DRAWS from.  Belts do not use it to
    chain -- a junction records no links of its own, so the belts around it do
    the naming, in both directions.
    """
    return PlacedBuilding(
        item_id=item_id,
        model_index=36,
        x=x,
        y=y,
        z=Fraction(z),
        output_obj=out,
        input_obj=inp,
        carries_item=carries,
    )


def splitter(
    x: int, y: int, z: Fraction | int = 0, *, carries: str | None = None
) -> PlacedBuilding:
    return junction.make_splitter(x, y, Fraction(z), carries_item=carries)


def sorter(
    x: int,
    y: int,
    x2: int,
    y2: int,
    *,
    inp: int | None = None,
    out: int | None = None,
    item_id: int = SORTER3,
    z: Fraction | int = 0,
    z2: Fraction | int = 0,
    filter_id: int = 0,
) -> PlacedBuilding:
    return PlacedBuilding(
        item_id=item_id,
        model_index=43,
        x=x,
        y=y,
        z=Fraction(z),
        x2=x2,
        y2=y2,
        z2=Fraction(z2),
        input_obj=inp,
        output_obj=out,
        filter_id=filter_id,
    )


def tower(x: int, y: int) -> PlacedBuilding:
    return PlacedBuilding(item_id=TOWER, model_index=44, x=x, y=y)


def place(*buildings: PlacedBuilding) -> Placement:
    """A placement with its sorter slots filled in, as a strategy would leave it.

    Hand-written fixtures set no slot fields, so without this every one of them
    would trip ``sorter.own_slots`` and ``sorter.peer_slots`` and drown the
    finding each test actually exists to make.  Deriving them here is exactly
    what both strategies do on the way out, so the fixtures stay faithful.

    Fixtures whose sorters are deliberately malformed -- diagonal, unanchored,
    pointing at nothing -- have no derivable slot, and those keep the bare
    defaults: the check under test in each of them is the geometric one, and it
    fires either way.
    """
    try:
        return Placement(buildings=assign_sorter_slots(buildings))
    except SlotUndetermined:
        return Placement(buildings=tuple(buildings))


def fired(report: Report, check: str) -> bool:
    return bool(report.by_check(check))


def errors(report: Report) -> list[str]:
    return [f.check for f in report.findings if f.severity is Severity.ERROR]


def measured(finding: Finding, key: str) -> float:
    """The MEASUREMENT a finding reported under ``key``.

    ``Finding.detail`` is ``Mapping[str, object]`` on purpose: one detail
    carries a slot index, an end label and a measured distance side by side, and
    there is no narrower type honest about all three.  So a test that wants to
    compare a distance has to say that it expects a distance.

    ``Fraction`` is accepted alongside the others because the module docstring
    promises it: rates in a detail are exact Fractions.  Narrowing this to
    ``float`` would fail a check that reported one, which is a real value and
    not a defect.

    Asserting rather than casting buys the diagnosis, not the catch.  Measured
    with `game.inserter_data` mutated to report its gap as ``f"{gap:.3f}"``: a
    ``cast`` leaves ``'3.263' > 1.6`` to raise ``TypeError`` from inside the
    comparison, while this fails as "reported gap='3.263' (str), which is not a
    measurement" and names the check that did it.
    """
    value = finding.detail[key]
    assert isinstance(value, int | float | Fraction), (
        f"{finding.check} reported {key}={value!r} ({type(value).__name__}), "
        f"which is not a measurement"
    )
    return float(value)


# --- registry --------------------------------------------------------------


def test_every_registered_check_has_a_dotted_id() -> None:
    assert CHECKS, "no checks registered"
    for cid in CHECKS:
        assert "." in cid, f"{cid} is not a dotted id"


def test_empty_placement_is_clean() -> None:
    assert validate(place()).ok


# --- geometry --------------------------------------------------------------


def test_geom_overlap_fires_on_stacked_machines() -> None:
    r = validate(place(machine(0, 0), machine(2, 2)))
    assert fired(r, "geom.overlap")
    assert not r.ok


def test_geom_overlap_clean_when_footprints_are_disjoint() -> None:
    r = validate(place(machine(0, 0), machine(4, 0)))
    assert not fired(r, "geom.overlap")


def test_geom_overlap_ignores_different_altitudes() -> None:
    r = validate(place(belt(0, 0, 0), belt(0, 0, 1)))
    assert not fired(r, "geom.overlap")


COLLIDE = {"geom.overlap", "geom.collide"}


def test_geom_collide_fires_where_geom_overlap_cannot() -> None:
    """Two assemblers on adjacent 3x3 footprints, and the game still refuses it.

    Their tiles are disjoint -- 0..2 and 3..5 -- so ``geom.overlap`` is clean.
    But the game does not test tiles: it tests build colliders, an Assembling
    Machine's is 3.82 world units across, and three tiles is 3 * 2 * pi / 5 =
    3.770.  The 0.05-unit intersection is ``EBuildCondition.Collide``.

    This is the pair that has to hold for the check to be worth having: if it
    ever passes, ``geom.collide`` has collapsed into ``geom.overlap``.
    """
    r = validate(place(machine(0, 0), machine(3, 0)), only=COLLIDE)
    assert not fired(r, "geom.overlap")
    assert fired(r, "geom.collide")
    assert not r.ok


def test_geom_collide_clean_at_the_spacing_the_corpus_uses() -> None:
    assert not fired(validate(place(machine(0, 0), machine(4, 0)), only=COLLIDE), "geom.collide")
    assert not fired(validate(place(machine(0, 0), machine(0, 4)), only=COLLIDE), "geom.collide")


def test_geom_collide_does_not_fire_on_a_tighter_building() -> None:
    """The rule is per-collider, not a blanket "add a tile".

    An Arc Smelter is 2.9 units across and three tiles is 3.770, so smelters at
    the same spacing that breaks assemblers are fine -- and the corpus places
    them exactly there.
    """
    r = validate(
        place(machine(0, 0, item_id=SMELTER), machine(3, 0, item_id=SMELTER)), only=COLLIDE
    )
    assert not fired(r, "geom.collide")


def test_geom_collide_runs_by_default_now_that_the_layout_passes_it() -> None:
    """The inverse of the test this replaces, which asked to be deleted.

    ``geom.collide`` was opt-in because it fired on almost everything we made --
    443 assembler-on-assembler pairs, one defect. Spacing fixed that and turning
    it on cost no coverage, so it is a normal check and a collision is a refusal.
    Nothing may go back into ``OPT_IN`` without a measurement of what leaving it
    on would cost.
    """
    from flab2bp.layout.validate import OPT_IN

    assert set() == OPT_IN
    r = validate(place(machine(0, 0), machine(3, 0)))
    assert "geom.collide" in r.checks_run
    assert "geom.collide" not in r.skipped
    assert fired(r, "geom.collide"), "three tiles apart is a collision"


def test_geom_belt_single_occupancy_fires_on_two_belts_in_one_cell() -> None:
    r = validate(place(belt(0, 0), belt(0, 0)))
    assert fired(r, "geom.belt_single_occupancy")


def test_geom_machine_ground_fires_on_elevated_machine() -> None:
    m = machine(0, 0)
    elevated = PlacedBuilding(
        item_id=m.item_id,
        model_index=m.model_index,
        x=0,
        y=0,
        z=Fraction(1),
        width=4,
        height=4,
        recipe_id=1,
    )
    r = validate(place(elevated))
    assert fired(r, "geom.machine_ground")


def test_geom_machine_ground_clean_at_z_zero() -> None:
    assert not fired(validate(place(machine(0, 0))), "geom.machine_ground")


def test_geom_altitude_range_fires_above_the_runs_ceiling() -> None:
    r = validate(place(belt(0, 0, 9)))
    assert fired(r, "geom.altitude_range")


def test_geom_altitude_range_allows_what_the_run_declares() -> None:
    """The ceiling is the SAVE's, not a constant: say so and it is allowed.

    The user's own save reaches z=38, so a fixed maximum here would reject
    blueprints the game accepts.
    """
    high = place(belt(0, 0, 9))
    assert fired(validate(high), "geom.altitude_range")
    assert not fired(validate(high, max_belt_z=Fraction(38)), "geom.altitude_range")


def test_geom_altitude_range_fires_between_quanta() -> None:
    r = validate(place(belt(0, 0, Fraction(1, 3))), )
    assert fired(r, "geom.altitude_range")


def test_geom_altitude_step_fires_on_a_full_level_across_one_tile() -> None:
    """The exact step that shipped red, refused by the game's own rule.

    A blueprint rise of 1 across one tile is a WORLD slope of 4/3 -- blueprint
    z is 3/4 of world height -- against the 4/5 the game allows.  It is
    `EBuildCondition.TooSteep`, and the old `dz > 1` test scored it exactly 1
    and let it pass.
    """
    r = validate(
        place(belt(0, 0, 0, out=1), belt(1, 0, 1)),
        belt_vertical_construction=False,
    )
    assert fired(r, "geom.altitude_step")


def test_geom_altitude_step_allows_the_ramp_we_emit() -> None:
    """1/2 across one tile is a world slope of 2/3, inside the 4/5 limit."""
    r = validate(place(belt(0, 0, 0, out=1), belt(1, 0, Fraction(1, 2))))
    assert not fired(r, "geom.altitude_step")


def test_geom_altitude_step_allows_a_ramp_at_any_height() -> None:
    """There is no one-level cap: the rule is on SLOPE, not on altitude.

    This is what the fixtures could not tell us and the game's source did.
    """
    r = validate(
        place(belt(0, 0, 7, out=1), belt(1, 0, Fraction(15, 2))),
        max_belt_z=Fraction(171, 20),
    )
    assert not fired(r, "geom.altitude_step")


def test_geom_altitude_step_fires_just_past_the_slope_limit() -> None:
    """3/5 of blueprint z per tile is exactly 4/5 world; 7/10 is over it."""
    ok = validate(
        place(belt(0, 0, 0, out=1), belt(1, 0, Fraction(3, 5))),
        belt_vertical_construction=False,
    )
    assert not fired(ok, "geom.altitude_step")
    over = validate(
        place(belt(0, 0, 0, out=1), belt(1, 0, Fraction(7, 10))),
        belt_vertical_construction=False,
    )
    assert fired(over, "geom.altitude_step")


def test_geom_altitude_step_refuses_a_vertical_climb_without_the_unlock() -> None:
    """Zero run is infinite slope, which only beltVerticalConstruction allows."""
    r = validate(
        place(belt(0, 0, 0, out=1), belt(0, 0, 1)),
        belt_vertical_construction=False,
    )
    assert fired(r, "geom.altitude_step")


def test_geom_altitude_step_allows_a_vertical_climb_with_the_unlock() -> None:
    """With the tech the game skips the slope test entirely."""
    r = validate(
        place(belt(0, 0, 0, out=1), belt(0, 0, 1)),
        belt_vertical_construction=True,
    )
    assert not fired(r, "geom.altitude_step")


def test_geom_bounds_warns_beyond_soft_width() -> None:
    r = validate(place(belt(0, 0), belt(400, 0)), soft_width=256)
    warns = [f for f in r.by_check("geom.bounds") if f.severity is Severity.WARNING]
    assert warns
    # a warning must not sink the build
    assert r.ok


def test_geom_bounds_clean_within_soft_width() -> None:
    r = validate(place(belt(0, 0), belt(10, 0)), soft_width=256)
    assert not fired(r, "geom.bounds")


# --- sorters ---------------------------------------------------------------


def test_sorter_anchors_present_fires_when_second_anchor_missing() -> None:
    bad = PlacedBuilding(item_id=SORTER3, model_index=43, x=0, y=0)
    r = validate(place(bad))
    assert fired(r, "sorter.anchors_present")


def test_sorter_reach_fires_beyond_three_tiles() -> None:
    # machine occupies x 0..3; belt at x=8 puts the span at 5
    r = validate(place(machine(0, 0), belt(8, 0), sorter(3, 0, 8, 0, inp=0, out=1)))
    assert fired(r, "sorter.reach")


def test_sorter_reach_clean_at_three_tiles() -> None:
    r = validate(place(machine(0, 0), belt(6, 0), sorter(3, 0, 6, 0, inp=0, out=1)))
    assert not fired(r, "sorter.reach")


def test_sorter_reach_fires_on_diagonal() -> None:
    r = validate(place(machine(0, 0), belt(4, 2), sorter(3, 0, 4, 2, inp=0, out=1)))
    assert fired(r, "sorter.reach")


def test_sorter_altitude_fires_when_spanning_levels() -> None:
    # sorters never change altitude: z2 - z is exactly 0 for all 1288 corpus sorters
    r = validate(place(machine(0, 0), belt(4, 0, 1), sorter(3, 0, 4, 0, z=0, z2=1, inp=0, out=1)))
    assert fired(r, "sorter.altitude")


def test_sorter_altitude_clean_when_level() -> None:
    r = validate(place(machine(0, 0), belt(4, 0), sorter(3, 0, 4, 0, inp=0, out=1)))
    assert not fired(r, "sorter.altitude")


def test_sorter_endpoints_fires_on_dangling_end() -> None:
    # second anchor sits on empty space
    r = validate(place(machine(0, 0), sorter(3, 0, 4, 0, inp=0)))
    assert fired(r, "sorter.endpoints")


def test_sorter_endpoints_clean_when_both_ends_occupied() -> None:
    # The assembler is 3x3, so it occupies x 0..2; the near anchor must sit on
    # the machine itself, not one tile past it.
    r = validate(place(machine(0, 0), belt(3, 0), sorter(2, 0, 3, 0, inp=0, out=1)))
    assert not fired(r, "sorter.endpoints")


def test_sorter_endpoint_pair_fires_when_links_disagree_with_anchors() -> None:
    # output_obj names the machine, but the far anchor sits on the belt
    r = validate(place(machine(0, 0), belt(4, 0), sorter(3, 0, 4, 0, inp=0, out=0)))
    assert fired(r, "sorter.endpoint_pair")


SPRAY_COATER = 2313  # a belt addon: no insert pose, fed by belt from its addon area
CHEMICAL_PLANT = 2309  # 9x5, and never a sorter peer anywhere in the corpus
MATRIX_LAB = 2901  # 5x5, and its slot ring runs the opposite way round
OIL_REFINERY = 2308  # 3x7, nine slots, and none at all on its north face


def _retagged(
    p: Placement,
    index: int,
    *,
    output_to_slot: int | None = None,
    input_from_slot: int | None = None,
    output_from_slot: int | None = None,
    input_to_slot: int | None = None,
    yaw: float | None = None,
) -> Placement:
    """``p`` with one sorter's slot fields or yaw overwritten, to mutate a good build."""
    b = p.buildings[index]
    bs = list(p.buildings)
    bs[index] = dataclasses.replace(
        b,
        output_to_slot=b.output_to_slot if output_to_slot is None else output_to_slot,
        input_from_slot=b.input_from_slot if input_from_slot is None else input_from_slot,
        output_from_slot=(
            b.output_from_slot if output_from_slot is None else output_from_slot
        ),
        input_to_slot=b.input_to_slot if input_to_slot is None else input_to_slot,
        yaw=b.yaw if yaw is None else yaw,
        yaw2=b.yaw2 if yaw is None else yaw,
    )
    return Placement(buildings=tuple(bs))


def _belt_to_machine() -> Placement:
    """Belt at (3,0) feeding a 3x3 assembler at (0,0) through its east side."""
    return place(machine(0, 0), belt(3, 0), sorter(3, 0, 2, 0, inp=1, out=0))


def test_sorter_own_slots_clean_on_a_derived_placement() -> None:
    assert not fired(validate(_belt_to_machine()), "sorter.own_slots")


def test_sorter_own_slots_fires_on_the_defaulted_zeros() -> None:
    """The exact shape of the bug: every field left at the dataclass default."""
    p = _retagged(_belt_to_machine(), 2, output_from_slot=0, input_to_slot=0)
    assert fired(validate(p), "sorter.own_slots")


def test_sorter_own_slots_fires_when_output_from_slot_moves() -> None:
    p = _retagged(_belt_to_machine(), 2, output_from_slot=1)
    assert fired(validate(p), "sorter.own_slots")


def test_sorter_peer_slots_clean_on_a_derived_placement() -> None:
    assert not fired(validate(_belt_to_machine()), "sorter.peer_slots")


def test_sorter_peer_slots_fires_when_the_belt_side_is_not_minus_one() -> None:
    p = _retagged(_belt_to_machine(), 2, input_from_slot=0)
    assert fired(validate(p), "sorter.peer_slots")


def test_sorter_peer_slots_fires_when_the_machine_side_is_zeroed() -> None:
    """A machine end of 0 is right only at one corner, and this is not it.

    The sorter enters the assembler's east side one tile north of its centre,
    which is slot 5.  Zero is what the strategies used to emit everywhere.
    """
    good = _belt_to_machine()
    assert good.buildings[2].output_to_slot == 5
    assert fired(validate(_retagged(good, 2, output_to_slot=0)), "sorter.peer_slots")


def test_sorter_peer_slots_fires_on_the_mirrored_slot() -> None:
    """Off by exactly the handedness mirror is still wrong, and is caught.

    Slot 5's mirror image is 9 -- same tile, opposite handedness -- which is
    what a wrong :data:`flab2bp.layout.slots._MIRRORED` entry would emit here.
    """
    good = _belt_to_machine()
    assert fired(validate(_retagged(good, 2, output_to_slot=9)), "sorter.peer_slots")


def test_sorter_slot_reach_clean_on_a_three_wide_machine() -> None:
    r = validate(place(machine(0, 0), belt(1, 3), sorter(1, 3, 1, 2, inp=1, out=0)))
    assert not fired(r, "sorter.slot_reach")


# --- the game's own build conditions ----------------------------------------


def test_game_inserter_data_clean_on_a_derived_placement() -> None:
    """The negative control for all three: a legal sorter fires nothing.

    Without this the checks below could pass by firing on everything.  The wider
    negative control is ``test_the_slot_poses_are_what_the_corpus_lands_on``,
    which runs the same predicate over 1142 sorters the game itself wrote.
    """
    r = validate(_belt_to_machine())
    assert not fired(r, "game.inserter_data")
    assert not fired(r, "game.inserter_paste")
    assert not fired(r, "game.inserter_skew")


def test_game_inserter_data_fires_when_the_machine_side_is_zeroed() -> None:
    """Slot 0 on a sorter entering from the east: the defect we shipped.

    Slot 0 of an assembler is the west end of its NORTH face, so an end on the
    east face lands 2.02 tiles from it -- over the 0.8 of
    ``CheckInserterDataLegal``, and over the 1.6 the paste path allows even a
    perfectly radial correction.  Measured in game at 1.87 on a real build with
    every machine-side slot forced to 0, against 0.24 with the right one.
    """
    p = _retagged(_belt_to_machine(), 2, output_to_slot=0)
    r = validate(p)
    assert fired(r, "game.inserter_data")
    assert fired(r, "game.inserter_paste")
    gap = measured(r.by_check("game.inserter_data")[0], "gap")
    assert gap > 1.6, gap


def test_game_inserter_data_fires_when_the_sorter_runs_into_the_slots_back() -> None:
    """Slot 10 is the assembler's west face; this sorter arrives from the east.

    The predicate has two halves and they catch different things, so the second
    one needs its own witness.  A slot square across the sorter is NOT caught
    here -- the game's test is ``< 0f``, and a right angle dots to zero -- which
    is why the corner case belongs to ``game.inserter_skew`` instead.
    """
    r = validate(_retagged(_belt_to_machine(), 2, output_to_slot=10))
    dots = [f for f in r.by_check("game.inserter_data") if "dot" in f.detail]
    assert dots, [f.message for f in r.by_check("game.inserter_data")]
    assert measured(dots[0], "dot") < 0


def test_game_inserter_data_fires_on_a_reversed_own_slot_pairing() -> None:
    """``ReadObjectConn(objId, 0)`` must be the output, ``1`` the input."""
    p = _retagged(_belt_to_machine(), 2, output_from_slot=1, input_to_slot=0)
    assert fired(validate(p), "game.inserter_data")


def test_game_inserter_paste_allows_a_purely_radial_stretch() -> None:
    """0.90 world units straight out of the face is legal on paste, not on copy.

    The paste ladder tolerates ``num40`` up to 1.6 when ``num41`` -- the sideways
    part -- is under 0.1, and caps everything else at 0.8.  This is the band
    where the two predicates genuinely disagree, and the port keeps them apart
    rather than averaging them.

    The numbers are WORLD units, and that distinction is the whole reason this
    test moved: a tile is 1.2566 of them.  Anchored on the Chemical Plant's
    south EDGE row the gap is 0.90 and lands in the band; on the row its pose
    actually sits over it is 0.357 and legal for both.  The earlier version of
    this test called that same edge-row case "1.1 tiles" and put it in the band
    by treating tiles as world units.
    """
    # The plant is anchored at x=1 so its 7x5 footprint spans columns 1..7 and
    # its centre lands on (4, 2) -- the geometry this pair of tests measures.
    # It used to be anchored at x=0 because the footprint used to read 9 wide.
    p = place(
        machine(1, 0, item_id=CHEMICAL_PLANT),
        belt(4, -1),
        sorter(4, -1, 4, 2, inp=1, out=0),
    )
    r = validate(p)
    assert not fired(r, "game.inserter_paste"), [
        f.message for f in r.by_check("game.inserter_paste")
    ]
    gaps = [measured(f, "gap") for f in r.by_check("game.inserter_data") if "gap" in f.detail]
    assert gaps and 0.8 < gaps[0] <= 1.6, gaps


def test_game_inserter_paste_stops_a_radial_stretch_at_1_6() -> None:
    """The plant's south EDGE row is 1.61 world units out and refused; 0.90 was not.

    Its poses sit over the row INSIDE that edge, so anchoring on the edge itself
    is further from the pose than anchoring a row deeper in -- which is exactly
    the shape that makes a wide machine want to be packed closer, not further.

    The pair with :func:`test_game_inserter_paste_allows_a_purely_radial_stretch`
    is what pins ``_PASTE_RADIAL``: one test on each side of the threshold, both
    with the sideways part at zero, so only that constant separates them.

    ``_PASTE_LATERAL`` has no such pair and cannot get one -- with ``snap``
    already over 0.8, a lateral of 0.1 or more is refused by the ladder's third
    branch whatever the first says, and a lateral under 0.1 never reaches the
    first.  The branch is unreachable for anything that is not a silo.  It is
    ported anyway, because a port that quietly drops a branch is not one.
    """
    r = validate(
        place(
            machine(1, 0, item_id=CHEMICAL_PLANT),  # centre (4, 2); see the pair above
            belt(4, -2),
            sorter(4, -2, 4, 0, inp=1, out=0),
        )
    )
    snaps = [f for f in r.by_check("game.inserter_paste") if "snap" in f.detail]
    assert snaps, [f.message for f in r.by_check("game.inserter_paste")]
    assert measured(snaps[0], "lateral") < 0.1
    assert measured(snaps[0], "snap") > 1.6


def test_two_assemblers_collide_at_pitch_3_and_clear_at_pitch_4() -> None:
    """The end-to-end statement of what spacing is for.

    `geom.collide` is the game's own test, on real collider boxes, and it
    reported 443 assembler-on-assembler pairs on our output before this. The
    footprint said 3 and the collider needs 4; both numbers are here so that
    changing either one has to break this.
    """
    tight = place(machine(0, 0), machine(3, 0))
    assert fired(validate(tight, only={"geom.collide"}), "geom.collide")

    clear = place(machine(0, 0), machine(4, 0))
    assert not fired(validate(clear, only={"geom.collide"}), "geom.collide")

    assert catalog_building(ASSEMBLER).width == 3, "covers three tiles"
    from flab2bp.dsp import catalog as _cat

    assert _cat.clearance(ASSEMBLER, 0.0)[0] == 4, "and needs a fourth"


def _coater(x: int, y: int, z: Fraction | int = 0) -> PlacedBuilding:
    """A Spray Coater on the belt at ``(x, y)``.

    ``z`` is converted the way ``belt`` and ``splitter`` above convert theirs.
    Handing ``PlacedBuilding`` a bare ``int`` was not merely a type error: this
    helper feeds ``game.addon_supply``, which measures a proliferator belt one
    altitude LEVEL up against a 1.0-unit area, and altitudes are Fractions
    because a level is not a whole tile.
    """
    b = catalog_building(SPRAY_COATER)
    return PlacedBuilding(
        item_id=SPRAY_COATER,
        model_index=b.model_index,
        x=x,
        y=y,
        z=Fraction(z),
        yaw=90.0,  # Facing.EAST
    )


def test_game_addon_supply_fires_when_a_coater_has_no_proliferator_belt() -> None:
    """A Spray Coater is fed from one place and it is not a sorter.

    The belt the coater rides is at its own tile; the proliferator belt has to
    be in addon area 1, a tile and a quarter behind it and one altitude level
    UP.  A belt beside it at ground level -- which is what both strategies used
    to build, with a sorter running from it -- is not in the area and the game
    attaches nothing.
    """
    r = validate(place(belt(0, 0), belt(1, 0), _coater(0, 0)))
    assert fired(r, "game.addon_supply")


def test_game_addon_supply_clean_when_the_belt_is_where_the_game_looks() -> None:
    """One level up and a tile behind: 0.25 from the area centre, well inside 1.0."""
    r = validate(place(belt(0, 0), belt(-1, 0, 1), _coater(0, 0)))
    assert not fired(r, "game.addon_supply"), [
        f.message for f in r.by_check("game.addon_supply")
    ]


def test_game_inserter_data_fires_on_a_far_column_of_a_wide_machine() -> None:
    """A Chemical Plant is nine wide and takes a sorter on four of its columns.

    The sorter lands on the plant's leftmost column, where the real slot table
    has nothing, and the nearest slot on that face is three tiles away.  This is
    the class of defect the old ``sorter.slot_reach`` warning could only guess
    at, and the game's own numbers make it an error.
    """
    r = validate(
        place(
            machine(0, 0, item_id=CHEMICAL_PLANT),
            belt(0, 5),
            sorter(0, 5, 0, 4, inp=1, out=0),
        )
    )
    assert fired(r, "game.inserter_data")
    assert fired(r, "game.inserter_paste")


def test_game_inserter_skew_fires_on_a_yaw_across_the_run() -> None:
    """A sorter facing across the line it runs along is "deflection too much".

    Turned a quarter, the axis test reads 90 degrees against a limit of 24.  A
    yaw turned a HALF is not caught -- the game takes an absolute value, and
    both ends carry the same blueprint yaw whichever way it points -- which is
    why `assign_sorter_slots` derives the yaw from the corpus rule rather than
    leaning on this check to notice.
    """
    r = validate(_retagged(_belt_to_machine(), 2, yaw=0.0))
    off = [f for f in r.by_check("game.inserter_skew") if "off_axis_deg" in f.detail]
    assert off, [f.message for f in r.by_check("game.inserter_skew")]
    assert measured(off[0], "off_axis_deg") > 24.0


def test_game_inserter_skew_fires_on_a_sorter_longer_than_the_game_allows() -> None:
    """Eight tiles between two machines, against a 7.5 ceiling.

    The ceiling is the only half of the length window an integer grid can reach.
    The FLOOR cannot bind on anything we could emit -- the loosest of the three
    is 0.9 and the shortest sorter on a tile grid is 1.0 -- so it is ported and
    left without a witness rather than given a fabricated one.  ``sorter.reach``
    fires here too; this asserts only on the game's own ladder.
    """
    r = validate(
        place(
            machine(0, 0),
            machine(0, 11),
            sorter(1, 2, 1, 10, inp=0, out=1),
        )
    )
    lengths = [f for f in r.by_check("game.inserter_skew") if "max" in f.detail]
    assert lengths, [f.message for f in r.by_check("game.inserter_skew")]
    assert measured(lengths[0], "length") > 7.5


# --- belts -----------------------------------------------------------------


def test_belt_link_adjacent_fires_on_distant_link() -> None:
    r = validate(place(belt(0, 0, out=1), belt(5, 0)))
    assert fired(r, "belt.link_adjacent")


def test_belt_link_adjacent_clean_when_orthogonal() -> None:
    r = validate(place(belt(0, 0, out=1), belt(1, 0)))
    assert not fired(r, "belt.link_adjacent")


def test_belt_continuity_fires_on_link_into_nothing() -> None:
    r = validate(place(belt(0, 0, out=7)))
    assert fired(r, "belt.continuity")


def test_belt_acyclic_fires_on_a_loop() -> None:
    r = validate(place(belt(0, 0, out=1), belt(1, 0, out=2), belt(2, 0, out=0)))
    assert fired(r, "belt.acyclic")


def test_belt_acyclic_clean_on_a_line() -> None:
    r = validate(place(belt(0, 0, out=1), belt(1, 0, out=2), belt(2, 0)))
    assert not fired(r, "belt.acyclic")


# --- power -----------------------------------------------------------------


def test_power_coverage_fires_when_machine_is_out_of_radius() -> None:
    r = validate(place(tower(0, 0), machine(40, 40)))
    assert fired(r, "power.coverage")


def test_power_coverage_clean_when_machine_is_inside_radius() -> None:
    r = validate(place(tower(0, 0), machine(2, 2)))
    assert not fired(r, "power.coverage")


def test_power_coverage_uses_every_tile_not_just_the_centre() -> None:
    # Needs a building big enough that centre and corner genuinely disagree, so
    # a Chemical Plant (7x5) rather than a 3x3 assembler -- at 3x3 the two
    # readings barely differ and the test would pass without discriminating.
    #
    # Tower centre (0.5, 0.5), radius 10.5.  Plant at (4,4) spans x 4..10,
    # y 4..8, so its centre is (7.5, 6.5) at distance 9.24 -- inside -- while
    # its far tile centre (10.5, 8.5) is 12.81 away, outside.  A centre-only
    # check would pass this and leave the far end dark.  The anchor moved from
    # (2,2) when the plant stopped reading two tiles wider than its collider.
    r = validate(place(tower(0, 0), machine(4, 4, item_id=CHEM_PLANT)))
    assert fired(r, "power.coverage")


def test_power_coverage_centre_only_would_not_catch_that_case() -> None:
    """Guards the guard: the case above must actually distinguish the two rules.

    If the geometry ever drifts so the plant's centre also falls outside the
    radius, the test above would still pass -- but for the wrong reason, and it
    would no longer be testing what it claims to.
    """
    plant = machine(4, 4, item_id=CHEM_PLANT)
    cx = Fraction(2 * plant.x + plant.width, 2)
    cy = Fraction(2 * plant.y + plant.height, 2)
    tx = ty = Fraction(1, 2)
    centre_dist_sq = (cx - tx) ** 2 + (cy - ty) ** 2
    assert centre_dist_sq <= TESLA_COVER_RADIUS**2, "centre must be INSIDE the radius"


def test_power_coverage_fires_when_there_is_no_tower_at_all() -> None:
    r = validate(place(machine(0, 0)))
    assert fired(r, "power.coverage")


def test_power_coverage_ignores_belts() -> None:
    # belts are unpowered in DSP
    r = validate(place(belt(40, 40)))
    assert not fired(r, "power.coverage")


def test_power_connectivity_fires_on_split_network() -> None:
    r = validate(place(tower(0, 0), tower(100, 0)))
    assert fired(r, "power.connectivity")


def test_power_connectivity_clean_when_towers_link() -> None:
    r = validate(place(tower(0, 0), tower(20, 0)))
    assert not fired(r, "power.connectivity")


def test_a_long_reach_node_pulls_a_short_reach_one_into_the_network() -> None:
    """The pair test is ``max`` of the two reaches, not ``min``.

    ``OnNodeAdded`` links when the separation is within
    ``max(a.connDistance2, b.connDistance2)``, so a Wireless Power Tower (45.5)
    reaches a Tesla Tower (22.5) at up to 45.5 -- read off Assembly-CSharp.dll
    and recorded on ``catalog.TESLA_LINK_DISTANCE``.

    This check used ``min`` and so under-reached.  It changed no verdict at the
    time -- our own layouts place Tesla Towers only, where the two agree, and it
    flips none of the four mixed-reach fixtures -- which is exactly why it
    needed pinning rather than leaving to be noticed.

    30 tiles is chosen to sit in the gap: beyond a Tesla pair's 22.5, inside the
    Wireless tower's 45.5. Under ``min`` these are two stranded networks.
    """
    wireless = PlacedBuilding(item_id=WIRELESS_TOWER, model_index=45, x=0, y=0)
    tesla = tower(30, 0)
    a = catalog_building(WIRELESS_TOWER).connect_distance
    b = catalog_building(TOWER).connect_distance
    assert b < 30 < a, "the separation must lie between the two reaches"

    r = validate(place(wireless, tesla))
    assert not fired(r, "power.connectivity")


def test_power_coverage_agrees_with_exact_rational_geometry_tile_by_tile() -> None:
    """The disc test decides in integers; the rule is written in Fractions.

    Both power checks compare a squared distance against a squared radius in
    DOUBLED integer coordinates, because the Fraction form was 22% of a certify.
    The two forms are the same predicate rather than an approximation of one:
    doubling clears the only halves in the comparison, so the squared distance
    is an integer, and an integer is ``<= (2r)**2`` exactly when it is
    ``<= floor((2r)**2)``.

    So this states the rule independently, in exact rationals, and checks it at
    every tile of a 26x26 quadrant at once.  A SORTER is the probe because it
    is the only powered building that occupies no cell: 676 of them can stand
    on 676 adjacent tiles without a single ``geom.overlap``, which makes the
    sweep exactly as fine as the lattice the rule is evaluated on.

    Being that fine is load-bearing, and I found that out by trying coarser.
    Substituting the tile CORNER for the tile CENTRE -- a real error, half a
    tile of drift -- survives a sweep on one axis (on-axis the drift is
    perpendicular to nothing and no tile changes side) and survives a 2D sweep
    of 3x3 machines on a 3-tile pitch (the flip needs a tile at (7,8), and that
    pitch never puts a machine's far corner there).  It does not survive this.

    What this deliberately does NOT claim to catch is slack finer than the
    lattice, and there is provably none to catch.  ``(2r)**2`` is 441 for a
    Tesla Tower, and 441 = odd + even as a sum of two squares only, while a
    doubled separation is either even in both axes (odd tower footprint) or odd
    in both (even footprint) -- so no placement of any building under any tower
    lands exactly ON the boundary.  Bounds of 441, 442 and 443 decide every
    placement that can exist identically, and so do ``<`` and ``<=``.  That is
    not a gap in the test; it is the same fact as the integer form being exact.

    Fault-injected before being believed: tile-corner-for-tile-centre, the disc
    a lattice step too big, and a lattice step too small each fail this test,
    and the corner substitution passes two coarser sweeps I tried first.
    """
    tw = tower(0, 0)
    probes = [sorter(x, y, x, y) for x in range(26) for y in range(26)]
    report = validate(place(tw, *probes))
    got = {i for f in report.by_check("power.coverage") for i in f.buildings}
    want = {
        i + 1
        for i, p in enumerate(probes)
        if (Fraction(2 * p.x + 1, 2) - Fraction(2 * tw.x + tw.width, 2)) ** 2
        + (Fraction(2 * p.y + 1, 2) - Fraction(2 * tw.y + tw.height, 2)) ** 2
        > TESLA_COVER_RADIUS**2
    }
    assert got == want
    assert want and len(want) < len(probes), "the sweep must straddle the edge"


def test_power_connectivity_agrees_with_exact_rational_geometry_around_its_edge() -> None:
    """Same claim for the tower-to-tower test, swept around its own edge.

    Pairwise rather than in one placement, because linking is transitive: a
    third tower in the middle would join two that do not reach each other, and
    the question here is only whether the pair test itself is exact.

    Restricted to a band around the boundary because that is where a wrong
    answer can hide and because 676 two-tower validations to re-establish that
    a tower two tiles away is linked would be spending the suite's budget on
    nothing.  ``max`` versus ``min`` on a mixed-reach pair is pinned separately,
    above; both towers here are Teslas, where the two agree.

    Fault-injected: a reach a lattice step too far and a lattice step too short
    both fail this.  A wrong CENTRE convention cannot be tested here at all --
    with two towers of the same footprint every such error is a uniform
    translation of both, which changes no separation.  The mixed-footprint case
    that would see it is the wireless-tower test above.
    """
    reach = catalog_building(TOWER).connect_distance
    seen = set()
    tested = 0
    for dx in range(26):
        for dy in range(26):
            if abs(dx * dx + dy * dy - int(reach**2)) > 60:
                continue
            a, b = tower(0, 0), tower(dx, dy)
            linked = (
                (Fraction(2 * a.x + a.width, 2) - Fraction(2 * b.x + b.width, 2)) ** 2
                + (Fraction(2 * a.y + a.height, 2) - Fraction(2 * b.y + b.height, 2)) ** 2
                <= reach**2
            )
            seen.add(linked)
            tested += 1
            assert fired(validate(place(a, b)), "power.connectivity") is not linked, (dx, dy)
    assert seen == {False, True}, "the band must straddle the edge"
    assert tested > 20, f"the band collapsed to {tested} pairs"


# --- spec conformance ------------------------------------------------------


def simple_spec() -> BuildSpec:
    return BuildSpec(
        groups=(
            MachineGroup(
                recipe_id="magnetic-coil",
                machine_item_id="assembling-machine-2",
                count=1,
                inputs_per_machine={"copper-ingot": Fraction(1)},
                outputs_per_machine={"magnetic-coil": Fraction(2)},
            ),
        ),
        external_inputs={"copper-ingot": Fraction(1)},
        outputs={"magnetic-coil": Fraction(2)},
        belt_item_id="conveyor-belt-2",
        belt_items_per_second=Fraction(12),
    )


def test_spec_checks_are_skipped_without_a_spec() -> None:
    r = validate(place(machine(0, 0)))
    assert "spec.machine_counts" in r.skipped
    assert not fired(r, "spec.machine_counts")


def test_spec_checks_run_when_a_spec_is_supplied() -> None:

    ids = IdMap(
        recipes={"magnetic-coil": 6},
        items={"assembling-machine-2": ASSEMBLER, "copper-ingot": 1104, "magnetic-coil": 1101},
    )
    r = validate(place(machine(0, 0, recipe_id=6)), simple_spec(), ids=ids)
    assert "spec.machine_counts" not in r.skipped


def test_spec_machine_counts_fires_when_a_machine_is_missing() -> None:

    ids = IdMap(
        recipes={"magnetic-coil": 6},
        items={"assembling-machine-2": ASSEMBLER, "copper-ingot": 1104, "magnetic-coil": 1101},
    )
    r = validate(place(), simple_spec(), ids=ids)
    assert fired(r, "spec.machine_counts")


def test_prolif_belt_required_edge_fires_when_direct_inserted() -> None:

    ids = IdMap(
        recipes={"copper-ingot": 5, "magnetic-coil": 6},
        items={"assembling-machine-2": ASSEMBLER, "arc-smelter": SMELTER},
    )
    spec = BuildSpec(
        groups=(
            MachineGroup(
                recipe_id="copper-ingot",
                machine_item_id="arc-smelter",
                count=1,
                outputs_per_machine={"copper-ingot": Fraction(1)},
            ),
            MachineGroup(
                recipe_id="magnetic-coil",
                machine_item_id="assembling-machine-2",
                count=1,
                proliferator_mode=ProliferatorMode.SPEED,
                inputs_per_machine={"copper-ingot": Fraction(1)},
            ),
        ),
        belt_required_edges=frozenset({("copper-ingot", "magnetic-coil")}),
    )
    # smelter at 0,0 (3x3, tiles x0..2) direct-inserts into the assembler at
    # 3,0 (4x4, tiles x3..6) -- one sorter, both ends on machines, no belt
    p = place(
        machine(0, 0, item_id=SMELTER, recipe_id=5),
        machine(3, 0, item_id=ASSEMBLER, recipe_id=6),
        sorter(2, 0, 3, 0, inp=0, out=1),
    )
    r = validate(p, spec, ids=ids)
    assert fired(r, "prolif.belt_required_edges_not_direct_inserted")
    sev = {f.severity for f in r.by_check(BELT_REQUIRED)}
    assert Severity.ERROR in sev


def test_prolif_belt_required_edge_clean_when_belted() -> None:

    ids = IdMap(
        recipes={"copper-ingot": 5, "magnetic-coil": 6},
        items={"assembling-machine-2": ASSEMBLER, "arc-smelter": SMELTER},
    )
    spec = BuildSpec(
        groups=(
            MachineGroup(
                recipe_id="copper-ingot",
                machine_item_id="arc-smelter",
                count=1,
                outputs_per_machine={"copper-ingot": Fraction(1)},
            ),
            MachineGroup(
                recipe_id="magnetic-coil",
                machine_item_id="assembling-machine-2",
                count=1,
                proliferator_mode=ProliferatorMode.SPEED,
                inputs_per_machine={"copper-ingot": Fraction(1)},
            ),
        ),
        belt_required_edges=frozenset({("copper-ingot", "magnetic-coil")}),
    )
    # smelter (x0..2) -> sorter -> belt (x3) -> sorter -> assembler (x4..7)
    p = place(
        machine(0, 0, item_id=SMELTER, recipe_id=5),
        machine(4, 0, item_id=ASSEMBLER, recipe_id=6),
        belt(3, 0),
        sorter(2, 0, 3, 0, inp=0, out=2),
        sorter(3, 0, 4, 0, inp=2, out=1),
    )
    r = validate(p, spec, ids=ids)
    assert not fired(r, "prolif.belt_required_edges_not_direct_inserted")


# --- machine conformance ---------------------------------------------------


def test_machine_recipe_valid_fires_on_unset_recipe() -> None:
    r = validate(place(machine(0, 0, recipe_id=0)))
    assert fired(r, "machine.recipe_valid")


def test_machine_recipe_valid_clean_when_set() -> None:
    assert not fired(validate(place(machine(0, 0, recipe_id=6))), "machine.recipe_valid")


# --- mode-driven machines --------------------------------------------------
#
# An Energy Exchanger and a Ray Receiver are configured by a MODE in their
# parameter block, with ``recipe_id`` left at zero, and DSP also gives both of
# them a power cover radius.  Those two facts between them made a whole class of
# machine invisible to this module: ``_kind`` sorted them as power nodes, so
# ``of_kind(Kind.MACHINE)`` never yielded them, and ``group_for`` could not have
# resolved them anyway because a mode has no DSP recipe id to look up.


EXCHANGER = ENERGY_EXCHANGER_ID  # 2209, 9x9, cover radius 7
ACCUMULATOR = 2206
ACCUMULATOR_FULL = 2207
CHARGE = params.parameters_for("accumulator-full")
DISCHARGE = params.parameters_for("accumulator-discharge")


def exchanger(
    x: int, y: int, *, parameters: tuple[int, ...] = CHARGE
) -> PlacedBuilding:
    """An Energy Exchanger exactly as a strategy emits one.

    ``recipe_id`` is zero and the mode rides in ``parameters``; see
    ``spine._machine_config``, which owns that contract.
    """
    b = catalog_building(EXCHANGER)
    return PlacedBuilding(
        item_id=EXCHANGER,
        model_index=b.model_index,
        x=x,
        y=y,
        width=b.width,
        height=b.height,
        recipe_id=0,
        parameters=parameters,
    )


#: What ``pipeline._id_map`` builds for a mode-driven spec.  ``recipes`` is
#: EMPTY, and that is not an oversight: ``catalog.recipe_id`` raises for a mode,
#: so there is no id for the map to carry and no id for the placement to hold.
MODE_DRIVEN_IDS = IdMap(
    recipes={},
    items={
        "energy-exchanger": EXCHANGER,
        "accumulator": ACCUMULATOR,
        "accumulator-full": ACCUMULATOR_FULL,
    },
)


def mode_driven_spec(recipe: str = "accumulator-full") -> BuildSpec:
    """Two Energy Exchangers charging accumulators belted in from outside."""
    return BuildSpec(
        groups=(
            MachineGroup(
                recipe_id=recipe,
                machine_item_id="energy-exchanger",
                count=2,
                inputs_per_machine={"accumulator": Fraction(1)},
                outputs_per_machine={"accumulator-full": Fraction(1)},
            ),
        ),
        external_inputs={"accumulator": Fraction(2)},
        outputs={"accumulator-full": Fraction(2)},
    )


def unwired_exchangers() -> Placement:
    """Two exchangers and NOT ONE SORTER anywhere in the build.

    This is the placement the backlog measured: 2 Energy Exchangers, 0 sorters,
    ``report.ok = True``, with ``machine.inputs_supplied`` and
    ``machine.output_removed`` listed in ``checks_run``.  They ran and said
    nothing, because neither machine was ever handed to them.
    """
    return place(exchanger(0, 0), exchanger(11, 0))


def test_a_mode_driven_machine_is_classified_as_a_machine() -> None:
    """The first of the two causes, asked of the function that decides it.

    DSP gives an Energy Exchanger a cover radius of 7 and a Ray Receiver one of
    10.5 -- they are power nodes as well as machines -- and ``_kind`` tested
    that before anything else, so both fell out as ``Kind.POWER``.  Nothing
    downstream that iterates ``Kind.MACHINE`` could see them, which is three
    ERROR checks and ``machine.recipe_valid`` besides.
    """
    assert _kind(exchanger(0, 0)) is Kind.MACHINE
    receiver = catalog_building(RAY_RECEIVER_ID)
    assert receiver.cover_radius > 0, "the premise: it is a power node too"
    assert (
        _kind(
            PlacedBuilding(
                item_id=RAY_RECEIVER_ID,
                model_index=receiver.model_index,
                x=0,
                y=0,
                width=receiver.width,
                height=receiver.height,
                recipe_id=0,
                parameters=params.parameters_for("critical-photon"),
            )
        )
        is Kind.MACHINE
    )


def test_the_exchanger_still_supplies_the_power_it_supplies_in_game() -> None:
    """Reclassifying it must not cost the power model what the game gives it.

    An Energy Exchanger IS a power node: it covers a radius of 7 around itself
    and links at 15.5.  So a lone exchanger powers its own 9x9 footprint --
    corner tile centre to building centre is sqrt(32) = 5.66 -- and needs no
    tower.  If the reclassification had dropped it out of ``_tower_centres``
    this placement would report every one of its 81 tiles unpowered.
    """
    r = validate(place(exchanger(0, 0)), expect_power=True)
    assert not fired(r, "power.coverage"), [f.message for f in r.findings]


def test_the_set_of_power_nodes_is_unchanged_by_the_reclassification() -> None:
    """The guard on the sentence above, stated over the whole catalog.

    ``_tower_centres`` used to select ``Kind.POWER``; it now selects on the
    catalog fact that made a building ``Kind.POWER`` in the first place, a
    positive cover radius.  Those two are the same set only while nothing
    ``_kind`` sorts EARLIER than the radius test -- a belt, a sorter, a
    splitter -- carries one, so this asserts exactly that over the whole
    catalog and fails if a future extraction gives one a radius.

    A belt tier with no building entry at all (2004 is one) is covered too:
    ``_supplies_power`` answers False for it, exactly as ``_kind`` answered
    ``Kind.OTHER``.
    """
    from flab2bp.dsp import catalog as _cat
    from flab2bp.layout.validate import _supplies_power

    checked = 0
    for item_id in (*_cat.BELT_IDS, *_cat.SORTER_IDS, _cat.SPLITTER_ID):
        assert not _supplies_power(
            PlacedBuilding(item_id=item_id, model_index=0, x=0, y=0)
        ), item_id
        checked += 1
    assert checked >= 7, f"only {checked} belt-integrated ids checked"


def test_two_exchangers_and_no_sorters_at_all_must_not_pass() -> None:
    """The headline.  A build with no sorters cannot supply anything.

    Both machines need one ingredient delivered and one product taken away, and
    there is not a sorter in the placement to do either.
    """
    r = validate(
        unwired_exchangers(), mode_driven_spec(), ids=MODE_DRIVEN_IDS, expect_power=False
    )
    assert not r.ok, "a build with zero sorters and two hungry machines passed"
    assert fired(r, "machine.inputs_supplied"), errors(r)
    assert fired(r, "machine.output_removed"), errors(r)


def test_group_for_resolves_a_mode_driven_machine_by_its_parameter_block() -> None:
    """Charge and discharge run on the same building and differ only in the block.

    Resolving by ``item_id`` alone would hand a charging exchanger the
    discharging group's item flow -- the two are opposites -- so the block is
    part of the key, not a tie-break.
    """
    spec = BuildSpec(
        groups=(
            MachineGroup(
                recipe_id="accumulator-full",
                machine_item_id="energy-exchanger",
                count=1,
                inputs_per_machine={"accumulator": Fraction(1)},
                outputs_per_machine={"accumulator-full": Fraction(1)},
            ),
            MachineGroup(
                recipe_id="accumulator-discharge",
                machine_item_id="energy-exchanger",
                count=1,
                inputs_per_machine={"accumulator-full": Fraction(1)},
                outputs_per_machine={"accumulator": Fraction(1)},
            ),
        ),
    )
    p = place(exchanger(0, 0, parameters=CHARGE), exchanger(11, 0, parameters=DISCHARGE))
    ctx = _context(p, spec, MODE_DRIVEN_IDS, 256, DEFAULT_MAX_BELT_Z, True)
    first, second = ctx.group_for(0), ctx.group_for(1)
    assert first is not None and first.recipe_id == "accumulator-full"
    assert second is not None and second.recipe_id == "accumulator-discharge"


def test_machine_recipe_valid_accepts_a_mode_block_instead_of_a_recipe() -> None:
    """It is configured, just not by a recipe id.  Firing here would be a lie."""
    r = validate(place(exchanger(0, 0)))
    assert not fired(r, "machine.recipe_valid"), [f.message for f in r.findings]


def test_spec_machine_counts_counts_a_mode_driven_machine() -> None:
    """Two demanded, two placed -- and the check has to be able to say so.

    It keyed on the raw ``(recipe_id, item_id)`` pair, which for a mode is
    ``(0, 2209)`` on the placement side and nothing at all on the spec side.
    The result was "recipe 0 on machine 2209: spec demands 0, placement has 2"
    for a spec demanding exactly 2.
    """
    r = validate(
        unwired_exchangers(), mode_driven_spec(), ids=MODE_DRIVEN_IDS, expect_power=False
    )
    assert not fired(r, "spec.machine_counts"), [
        f.message for f in r.by_check("spec.machine_counts")
    ]


def test_spec_machine_counts_still_fires_when_a_mode_driven_count_is_wrong() -> None:
    """The control: the check above must not pass by having stopped counting."""
    spec = BuildSpec(
        groups=(
            MachineGroup(
                recipe_id="accumulator-full",
                machine_item_id="energy-exchanger",
                count=3,
                inputs_per_machine={"accumulator": Fraction(1)},
                outputs_per_machine={"accumulator-full": Fraction(1)},
            ),
        ),
    )
    r = validate(unwired_exchangers(), spec, ids=MODE_DRIVEN_IDS, expect_power=False)
    assert fired(r, "spec.machine_counts")


def test_machine_recipe_valid_fires_on_a_mode_driven_machine_with_no_block() -> None:
    """Half-configured is the failure ``_machine_config`` exists to prevent.

    An exchanger with neither a recipe id nor a mode pastes and sits idle,
    which is the same defect the check already names for everything else.
    """
    r = validate(place(exchanger(0, 0, parameters=())))
    assert fired(r, "machine.recipe_valid")


# --- a check that could not evaluate must not report as having run ---------


def unresolvable_spec() -> BuildSpec:
    """A spec that cannot single out which group either exchanger realises.

    Charge and discharge both run on an Energy Exchanger; a placement whose
    exchanger carries neither block matches neither group, and there is no
    honest way to pick one.  This is the shape the two Ray Receiver photon
    recipes take in the wild -- both emit the same block, because the Graviton
    Lens that separates them is an item the receiver consumes.
    """
    return BuildSpec(
        groups=(
            MachineGroup(
                recipe_id="accumulator-full",
                machine_item_id="energy-exchanger",
                count=1,
                inputs_per_machine={"accumulator": Fraction(1)},
                outputs_per_machine={"accumulator-full": Fraction(1)},
            ),
        ),
    )


def ray_receiver(x: int, y: int) -> PlacedBuilding:
    b = catalog_building(RAY_RECEIVER_ID)
    return PlacedBuilding(
        item_id=RAY_RECEIVER_ID,
        model_index=b.model_index,
        x=x,
        y=y,
        width=b.width,
        height=b.height,
        recipe_id=0,
        parameters=params.parameters_for("critical-photon"),
    )


def test_an_unresolvable_machine_is_an_error_and_not_a_silence() -> None:
    """The mode block does not match the one group, so nothing knows what it is.

    ERROR and not a lesser severity: ``Report.ok`` reads severities, so anything
    softer lets a build nothing could validate ship as validated.
    """
    p = place(exchanger(0, 0, parameters=DISCHARGE))
    r = validate(p, unresolvable_spec(), ids=MODE_DRIVEN_IDS, expect_power=False)
    found = r.by_check("machine.group_resolved")
    assert found, "an unresolvable machine reported nothing at all"
    assert [f.severity for f in found] == [Severity.ERROR]
    assert found[0].buildings == (0,)


def test_two_groups_the_placement_cannot_tell_apart_do_not_get_guessed() -> None:
    """The real ambiguity, and the one the game actually produces.

    FactorioLab splits a Ray Receiver's photon production into two recipes --
    with and without a Graviton Lens -- but the lens is an ITEM the receiver
    consumes, not a different setting, so both emit the SAME parameter block.
    A placed receiver therefore carries nothing that says which group it
    realises, and their ingredient lists differ.  Picking the first is a
    fallback with a wrong answer in it; the honest result is "cannot tell",
    reported as such.
    """
    assert params.parameters_for("critical-photon") == params.parameters_for(
        "critical-photon-graviton"
    ), "the premise: the two modes are indistinguishable in the placement"
    spec = BuildSpec(
        groups=(
            MachineGroup(
                recipe_id="critical-photon",
                machine_item_id="ray-receiver",
                count=1,
                outputs_per_machine={"critical-photon": Fraction(1)},
            ),
            MachineGroup(
                recipe_id="critical-photon-graviton",
                machine_item_id="ray-receiver",
                count=1,
                inputs_per_machine={"graviton-lens": Fraction(1)},
                outputs_per_machine={"critical-photon": Fraction(1)},
            ),
        ),
    )
    ids = IdMap(recipes={}, items={"ray-receiver": RAY_RECEIVER_ID})
    p = place(ray_receiver(0, 0))
    ctx = _context(p, spec, ids, 256, DEFAULT_MAX_BELT_Z, True)
    assert ctx.group_for(0) is None, "guessed between two indistinguishable groups"
    r = validate(p, spec, ids=ids, expect_power=False)
    assert [f.severity for f in r.by_check("machine.group_resolved")] == [Severity.ERROR]


def test_a_check_that_could_not_evaluate_is_not_listed_as_having_run() -> None:
    """The invariant, stated directly.

    ``checks_run`` is a claim of coverage.  A check that met a machine it could
    not resolve did not cover it, so it belongs in ``skipped`` -- where a reader
    already knows silence means nothing -- and not in ``checks_run``, where
    silence reads as a pass.
    """
    p = place(exchanger(0, 0, parameters=DISCHARGE))
    r = validate(p, unresolvable_spec(), ids=MODE_DRIVEN_IDS, expect_power=False)
    for cid in NEEDS_GROUPS:
        assert cid not in r.checks_run, cid
        assert cid in r.skipped, cid
    assert "machine.group_resolved" in r.checks_run


def test_the_same_checks_do_run_when_every_machine_resolves() -> None:
    """The control, without which the assertion above is satisfied by nothing.

    If these checks were absent from ``checks_run`` on a resolvable placement
    too, the test above would pass for a reason that has nothing to do with
    resolution.
    """
    r = validate(
        unwired_exchangers(), mode_driven_spec(), ids=MODE_DRIVEN_IDS, expect_power=False
    )
    assert not r.by_check("machine.group_resolved")
    for cid in NEEDS_GROUPS:
        assert cid in r.checks_run, cid
        assert cid not in r.skipped, cid


def test_a_partly_evaluated_check_still_reports_what_it_did_find() -> None:
    """Skipped-in-part is a claim about coverage, not a reason to drop findings.

    Two machines, one resolvable and starving, one not resolvable at all.  The
    starving one must still be reported -- suppressing it to keep the verdict
    tidy would trade one silence for another.
    """
    spec = BuildSpec(
        groups=(
            MachineGroup(
                recipe_id="accumulator-full",
                machine_item_id="energy-exchanger",
                count=1,
                inputs_per_machine={"accumulator": Fraction(1)},
                outputs_per_machine={"accumulator-full": Fraction(1)},
            ),
        ),
    )
    p = place(exchanger(0, 0, parameters=CHARGE), exchanger(11, 0, parameters=DISCHARGE))
    r = validate(p, spec, ids=MODE_DRIVEN_IDS, expect_power=False)
    supplied = r.by_check("machine.inputs_supplied")
    assert supplied, "the resolvable machine starves and must still be reported"
    assert supplied[0].buildings == (0,)
    assert "machine.inputs_supplied" in r.skipped


def test_every_check_that_consults_group_for_declares_it() -> None:
    """``NEEDS_GROUPS`` is the transitive closure, recomputed, not a hand list.

    The defect report named three ERROR checks.  The call graph says TEN reach
    ``Context.group_for``: three call it directly, five arrive through
    ``_lane_balance``, ``_sorter_demand``, ``_run_demand`` or ``_sorter_item``
    -- a hand-maintained list would have missed exactly those -- and two,
    ``spec.machine_counts`` and
    ``prolif.belt_required_edges_not_direct_inserted``, reach the same
    resolution through ``Context.recipe_of``.

    Recomputed here from the module's own source so the set cannot drift: add a
    check that asks what a machine makes and forget to declare it, and this
    fails naming it.
    """
    import ast
    import collections
    import inspect

    from flab2bp.layout import validate as module

    tree = ast.parse(inspect.getsource(module))
    funcs: dict[str, ast.FunctionDef] = {}
    check_of: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            funcs[node.name] = node
            for dec in node.decorator_list:
                if isinstance(dec, ast.Call) and getattr(dec.func, "id", "") == "check":
                    first = dec.args[0]
                    assert isinstance(first, ast.Constant)
                    check_of[node.name] = str(first.value)
        elif isinstance(node, ast.ClassDef):
            for member in node.body:
                if isinstance(member, ast.FunctionDef):
                    funcs.setdefault(member.name, member)

    def calls(node: ast.AST) -> set[str]:
        out: set[str] = set()
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call):
                fn = sub.func
                if isinstance(fn, ast.Name):
                    out.add(fn.id)
                elif isinstance(fn, ast.Attribute):
                    out.add(fn.attr)
        return out & set(funcs)

    graph = {name: calls(node) for name, node in funcs.items()}

    def reaches(start: str, target: str) -> bool:
        seen: set[str] = set()
        queue = collections.deque([start])
        while queue:
            cur = queue.popleft()
            if cur in seen:
                continue
            seen.add(cur)
            for nxt in graph.get(cur, ()):
                if nxt == target:
                    return True
                queue.append(nxt)
        return False

    computed = {
        cid
        for fn, cid in check_of.items()
        if reaches(fn, "group_for") or reaches(fn, "recipe_of")
    }
    computed.discard("machine.group_resolved")  # it OWNS the inability
    assert computed == NEEDS_GROUPS, (
        f"declared {sorted(NEEDS_GROUPS)}, call graph says {sorted(computed)}"
    )
    assert len(computed) == 10, f"expected 10 dependent checks, found {len(computed)}"


# --- machine conformance, continued ----------------------------------------


def two_input_spec() -> BuildSpec:
    return BuildSpec(
        groups=(
            MachineGroup(
                recipe_id="magnetic-coil",
                machine_item_id="assembling-machine-2",
                count=1,
                inputs_per_machine={"copper-ingot": Fraction(1), "iron-ingot": Fraction(1)},
                outputs_per_machine={"magnetic-coil": Fraction(2)},
            ),
        ),
    )


TWO_INPUT_IDS = IdMap(
    recipes={"magnetic-coil": 6},
    items={"assembling-machine-2": ASSEMBLER},
)


def test_machine_inputs_supplied_fires_when_an_ingredient_has_no_sorter() -> None:
    # recipe needs two ingredients; only one sorter feeds the machine
    p = place(
        machine(0, 0, recipe_id=6),
        belt(4, 0),
        sorter(4, 0, 3, 0, inp=1, out=0),
    )
    r = validate(p, two_input_spec(), ids=TWO_INPUT_IDS)
    assert fired(r, "machine.inputs_supplied")


def test_machine_inputs_supplied_clean_with_a_sorter_per_ingredient() -> None:
    p = place(
        machine(0, 0, recipe_id=6),
        belt(4, 0),
        belt(4, 1),
        sorter(4, 0, 3, 0, inp=1, out=0),
        sorter(4, 1, 3, 1, inp=2, out=0),
    )
    r = validate(p, two_input_spec(), ids=TWO_INPUT_IDS)
    assert not fired(r, "machine.inputs_supplied")


def test_machine_output_removed_fires_when_nothing_drains_it() -> None:
    p = place(machine(0, 0, recipe_id=6))
    r = validate(p, two_input_spec(), ids=TWO_INPUT_IDS)
    assert fired(r, "machine.output_removed")


# --- throughput ------------------------------------------------------------


def hungry_spec(rate: Fraction) -> BuildSpec:
    return BuildSpec(
        groups=(
            MachineGroup(
                recipe_id="magnetic-coil",
                machine_item_id="assembling-machine-2",
                count=1,
                inputs_per_machine={"copper-ingot": rate},
                outputs_per_machine={"magnetic-coil": Fraction(1)},
            ),
        ),
        belt_item_id="conveyor-belt-2",
        belt_items_per_second=Fraction(12),
    )


def fed_machine() -> Placement:
    # belt(3,0) -> sorter -> assembler at (4,0)
    return place(belt(3, 0), machine(4, 0, recipe_id=6), sorter(3, 0, 4, 0, inp=0, out=1))


def test_flow_belt_capacity_fires_when_demand_exceeds_the_tier() -> None:
    # Mk.II belt sustains 12/s; this machine wants 20/s
    r = validate(fed_machine(), hungry_spec(Fraction(20)), ids=TWO_INPUT_IDS)
    assert fired(r, "flow.belt_capacity")


def test_flow_belt_capacity_clean_within_the_tier() -> None:
    r = validate(fed_machine(), hungry_spec(Fraction(5)), ids=TWO_INPUT_IDS)
    assert not fired(r, "flow.belt_capacity")


def test_flow_sorter_capacity_fires_beyond_the_sorter_rate() -> None:
    # Sorter Mk.III sustains 6/s at one tile; this machine wants 20/s
    r = validate(fed_machine(), hungry_spec(Fraction(20)), ids=TWO_INPUT_IDS)
    assert fired(r, "flow.sorter_capacity")


def test_flow_sorter_capacity_accounts_for_span() -> None:
    # Mk.III at three tiles sustains only 2/s, so 3/s must fail there while
    # passing at one tile.  This is the check that would silently pass if the
    # rate were treated as span-independent.
    far = place(belt(1, 0), machine(4, 0, recipe_id=6), sorter(1, 0, 4, 0, inp=0, out=1))
    near = fed_machine()
    spec = hungry_spec(Fraction(3))
    assert fired(validate(far, spec, ids=TWO_INPUT_IDS), "flow.sorter_capacity")
    assert not fired(validate(near, spec, ids=TWO_INPUT_IDS), "flow.sorter_capacity")


def test_flow_conservation_fires_when_demand_exceeds_supply() -> None:
    spec = BuildSpec(
        groups=(
            MachineGroup(
                recipe_id="magnetic-coil",
                machine_item_id="assembling-machine-2",
                count=1,
                outputs_per_machine={"magnetic-coil": Fraction(1)},
            ),
        ),
        outputs={"magnetic-coil": Fraction(5)},
    )
    r = validate(place(), spec, ids=TWO_INPUT_IDS)
    assert fired(r, "flow.conservation")
    assert "-4" in str(r.by_check("flow.conservation")[0].detail["net"])


def test_flow_headroom_is_informational_only() -> None:
    r = validate(fed_machine(), hungry_spec(Fraction(5)), ids=TWO_INPUT_IDS)
    hr = r.by_check("flow.headroom")
    assert hr
    assert all(f.severity is Severity.INFO for f in hr)


def test_flow_rates_are_reported_as_exact_fractions() -> None:
    r = validate(fed_machine(), hungry_spec(Fraction(50, 3)), ids=TWO_INPUT_IDS)
    f = r.by_check("flow.belt_capacity")[0]
    assert f.detail["required"] == "50/3"

# --- per-item demand attribution -------------------------------------------
#
# Demand used to be split EVENLY across the sorters feeding a machine, which
# hides an overloaded sorter behind an underloaded one whenever a recipe's
# ingredient rates differ -- which is most recipes.  `filter_id` says which item
# a sorter moves and was never consulted.

PILE = 2014  # Pile Sorter, 20/s at one tile -- lets belt limits be tested
             # without the sorter limit firing first and masking them
COPPER_ID = 1104
IRON_ID = 1101


def lopsided_spec() -> BuildSpec:
    """One machine, two ingredients at very different rates."""
    return BuildSpec(
        groups=(
            MachineGroup(
                recipe_id="magnetic-coil",
                machine_item_id="assembling-machine-2",
                count=1,
                inputs_per_machine={"copper-ingot": Fraction(2), "iron-ingot": Fraction(10)},
                outputs_per_machine={"magnetic-coil": Fraction(1)},
            ),
        ),
    )


LOPSIDED_IDS = IdMap(
    recipes={"magnetic-coil": 6},
    items={
        "assembling-machine-2": ASSEMBLER,
        "copper-ingot": COPPER_ID,
        "iron-ingot": IRON_ID,
    },
)


def lopsided_placement() -> Placement:
    """Copper 2/s and iron 10/s into one machine, one filtered sorter each."""
    return place(
        machine(4, 0, recipe_id=6),  # 0
        belt(3, 0),  # 1
        belt(3, 1),  # 2
        sorter(3, 0, 4, 0, inp=1, out=0, filter_id=COPPER_ID),  # 3 -- 2/s
        sorter(3, 1, 4, 1, inp=2, out=0, filter_id=IRON_ID),  # 4 -- 10/s
    )


def test_flow_sorter_capacity_attributes_demand_per_item() -> None:
    """The iron sorter moves 10/s; a Mk.III sustains 6/s at one tile.

    Splitting the machine's 12/s total evenly gives each sorter 6/s, which is
    exactly at capacity and reports clean -- so the genuinely overloaded sorter
    is hidden by the underloaded one.  This is the load-bearing test.
    """
    r = validate(lopsided_placement(), lopsided_spec(), ids=LOPSIDED_IDS)
    findings = r.by_check("flow.sorter_capacity")
    assert findings, "the iron sorter moves 10/s against a 6/s tier and must be reported"
    assert any("4" in str(f.detail.get("sorter")) for f in findings)


def test_flow_sorter_capacity_does_not_blame_the_light_sorter() -> None:
    """Attribution has to be right in both directions, not merely stricter."""
    r = validate(lopsided_placement(), lopsided_spec(), ids=LOPSIDED_IDS)
    blamed = {f.detail.get("sorter") for f in r.by_check("flow.sorter_capacity")}
    assert 3 not in blamed, "the copper sorter moves 2/s and is well inside its tier"


def test_flow_headroom_reports_the_attributed_rate_not_an_even_split() -> None:
    r = validate(lopsided_placement(), lopsided_spec(), ids=LOPSIDED_IDS)
    carried = sorted(str(f.detail["required"]) for f in r.by_check("flow.headroom"))
    assert carried == ["10", "2"], f"expected the real per-item rates, got {carried}"


# --- shared (mixed-item) lanes ---------------------------------------------
#
# One belt carrying several item types, with filtered sorters picking off what
# they need.  Measured in the corpus: 236 of 1,288 sorters set a filter, and
# falk-v7-mall-full sets one on all 196 of its sorters.


def two_consumer_spec(copper: Fraction, iron: Fraction) -> BuildSpec:
    return BuildSpec(
        groups=(
            MachineGroup(
                recipe_id="magnetic-coil",
                machine_item_id="assembling-machine-2",
                count=1,
                inputs_per_machine={"copper-ingot": copper},
                outputs_per_machine={"magnetic-coil": Fraction(1)},
            ),
            MachineGroup(
                recipe_id="iron-ingot",
                machine_item_id="arc-smelter",
                count=1,
                inputs_per_machine={"iron-ingot": iron},
                outputs_per_machine={"magnet": Fraction(1)},
            ),
        ),
    )


TWO_CONSUMER_IDS = IdMap(
    recipes={"magnetic-coil": 6, "iron-ingot": 1},
    items={
        "assembling-machine-2": ASSEMBLER,
        "arc-smelter": SMELTER,
        "copper-ingot": COPPER_ID,
        "iron-ingot": IRON_ID,
    },
)


def shared_lane(*, copper_filter: int = COPPER_ID, iron_filter: int = IRON_ID) -> Placement:
    """One belt run feeding two machines different items.

    Belts (3,0)->(3,1) form a single run.  The assembler sits east of it, the
    smelter west, each drawn from by its own filtered sorter.
    """
    return place(
        machine(4, 0, recipe_id=6),  # 0  assembler, x 4..7
        machine(0, 0, item_id=SMELTER, recipe_id=1),  # 1  smelter, x 0..2
        belt(3, 0, out=3),  # 2
        belt(3, 1),  # 3
        sorter(3, 0, 4, 0, inp=2, out=0, item_id=PILE, filter_id=copper_filter),  # 4
        sorter(3, 1, 2, 1, inp=3, out=1, item_id=PILE, filter_id=iron_filter),  # 5
    )


def test_flow_shared_lane_couples_items_against_one_capacity() -> None:
    """Each item fits alone; together they exceed the belt.

    7 + 7 = 14 on a Mk.II lane that sustains 12.  Judging the items
    independently accepts this, because neither 7 exceeds 12 on its own.  The
    lane is one pipe and the flows share it.
    """
    p = shared_lane()
    r = validate(p, two_consumer_spec(Fraction(7), Fraction(7)), ids=TWO_CONSUMER_IDS)
    assert fired(r, "flow.belt_capacity"), (
        "7/s copper plus 7/s iron on one 12/s lane must be rejected"
    )


def test_flow_shared_lane_clean_when_the_sum_fits() -> None:
    p = shared_lane()
    r = validate(p, two_consumer_spec(Fraction(5), Fraction(5)), ids=TWO_CONSUMER_IDS)
    assert not fired(r, "flow.belt_capacity")


def test_flow_shared_lane_reports_the_per_item_breakdown() -> None:
    """A bare total is not debuggable; the finding must name the contributors."""
    p = shared_lane()
    r = validate(p, two_consumer_spec(Fraction(7), Fraction(7)), ids=TWO_CONSUMER_IDS)
    detail = r.by_check("flow.belt_capacity")[0].detail
    assert "copper-ingot" in str(detail.get("per_item"))
    assert "iron-ingot" in str(detail.get("per_item"))


def test_flow_lane_attribution_fires_when_a_shared_lane_sorter_is_unfiltered() -> None:
    """Never silently pass.

    An unfiltered sorter on a shared lane takes whatever passes, so its share of
    the lane cannot be determined -- and a capacity verdict computed from a
    guess would be a verdict the build never earned.

    The consumer needs TWO ingredients for this to bite: with a single-input
    machine the item is inferable from the recipe alone, and inference is
    legitimate.  Ambiguity is what cannot be judged, not the missing filter.
    """
    ambiguous = BuildSpec(
        groups=(
            MachineGroup(
                recipe_id="magnetic-coil",
                machine_item_id="assembling-machine-2",
                count=1,
                inputs_per_machine={"copper-ingot": Fraction(5)},
                outputs_per_machine={"magnetic-coil": Fraction(1)},
            ),
            MachineGroup(
                recipe_id="iron-ingot",
                machine_item_id="arc-smelter",
                count=1,
                # Two ingredients, so an unfiltered sorter could be moving either.
                inputs_per_machine={"iron-ingot": Fraction(3), "copper-ingot": Fraction(2)},
                outputs_per_machine={"magnet": Fraction(1)},
            ),
        ),
    )
    p = shared_lane(iron_filter=0)
    r = validate(p, ambiguous, ids=TWO_CONSUMER_IDS)
    findings = r.by_check("flow.lane_attribution")
    assert findings
    assert 5 in findings[0].buildings  # the unfiltered sorter  # the unfiltered sorter


def test_flow_lane_attribution_clean_when_every_share_is_known() -> None:
    p = shared_lane()
    r = validate(p, two_consumer_spec(Fraction(5), Fraction(5)), ids=TWO_CONSUMER_IDS)
    assert not fired(r, "flow.lane_attribution")


def test_flow_lane_attribution_clean_on_single_item_lanes() -> None:
    """An unfiltered sorter is fine when its lane carries only one thing."""
    r = validate(fed_machine(), hungry_spec(Fraction(5)), ids=TWO_INPUT_IDS)
    assert not fired(r, "flow.lane_attribution")


# --- negative control against real game blueprints -------------------------
#
# Real blueprints are known-good, so any geometry finding against one is a bug
# in us -- in the validator, or more usefully in the footprint table.
#
# Only the fixtures in `catalog.GEOMETRY_SAFE_FIXTURES` are usable.  DSP planets
# are spheres, so `localOffset` is fractional across much of a real blueprint and
# rounding that into an integer tile grid is meaningless.  What disqualifies a
# fixture is non-cardinal yaw -- `heretical-smelter-block` is excluded on that
# basis (its machines *are* integer-centred), not on game version.


def decode_fixture_to_placement(name: str) -> Placement:
    """Round a real blueprint into tile space, dropping what has no footprint."""
    from flab2bp.dsp import catalog
    from flab2bp.dsp.codec import decode

    text = (Path("tests/fixtures") / f"{name}.txt").read_text()
    out: list[PlacedBuilding] = []
    for b in decode(text).buildings:
        try:
            info = catalog.building(b.item_id)
        except KeyError:
            continue
        if not info.occupies_tiles or catalog.is_sorter(b.item_id):
            continue
        out.append(
            PlacedBuilding(
                item_id=b.item_id,
                model_index=b.model_index,
                x=round(b.x - info.width / 2 + 0.5),
                y=round(b.y - info.height / 2 + 0.5),
                z=Fraction(round(b.z * 2)),
                width=info.width,
                height=info.height,
            )
        )
    return Placement(buildings=tuple(out))


@pytest.mark.parametrize("name", GEOMETRY_SAFE_FIXTURES)
def test_real_blueprint_has_no_overlaps(name: str) -> None:
    p = decode_fixture_to_placement(name)
    assert p.buildings, "fixture decoded to nothing"
    r = validate(p, only={"geom.overlap"})
    assert not r.by_check("geom.overlap"), [f.message for f in r.findings[:5]]


@pytest.mark.parametrize("name", GEOMETRY_SAFE_FIXTURES)
def test_real_blueprint_exercises_more_than_one_footprint_size(name: str) -> None:
    """Guards the guard: zero overlaps must mean something.

    A negative control that decoded to a handful of 1x1 belts would pass while
    testing nothing.  These fixtures must actually contain multi-tile buildings
    of differing sizes for "no overlaps" to be evidence about the footprint
    table.
    """
    p = decode_fixture_to_placement(name)
    sizes = {(b.width, b.height) for b in p.buildings if b.width > 1 or b.height > 1}
    assert len(sizes) >= 2, f"{name} exercises only {sizes}"


# --- findings carry exact numbers ------------------------------------------


def test_findings_never_render_rates_as_floats() -> None:
    r = validate(place(machine(0, 0), machine(2, 2)))
    for f in r.findings:
        for v in f.detail.values():
            assert not isinstance(v, float), f"{f.check} rendered {v!r} as a float"


def test_report_ok_is_false_only_for_errors() -> None:
    r = validate(place(belt(0, 0), belt(400, 0)), soft_width=256)
    assert not errors(r)
    assert r.ok


@pytest.mark.parametrize("cid", sorted(CHECKS))
def test_each_check_is_individually_selectable(cid: str) -> None:
    r = validate(place(machine(0, 0), machine(2, 2)), only={cid})
    assert all(f.check == cid for f in r.findings)


# --- flow.lane_sourced -----------------------------------------------------
#
# A build was measured with 119 nets, 0 routed, 119 route failures -- nothing
# connected to anything -- and the validator reported ONE error, because every
# machine had its sorters and every lane existed.  They were simply never filled.
# Such a build also scores as DENSER, since the missing nets are missing belts,
# so a strategy comparison blind to this actively rewards failing to route.

LANE_IDS = IdMap(
    recipes={"copper-ingot": 5, "magnetic-coil": 6},
    items={
        "arc-smelter": SMELTER,
        "assembling-machine-2": ASSEMBLER,
        "copper-ore": 1002,
        "copper-ingot": 1104,
        "magnetic-coil": 1101,
    },
)


def lane_spec() -> BuildSpec:
    """A smelter feeding an assembler, with only the ore belted in."""
    return BuildSpec(
        groups=(
            MachineGroup(
                recipe_id="copper-ingot",
                machine_item_id="arc-smelter",
                count=1,
                inputs_per_machine={"copper-ore": Fraction(1)},
                outputs_per_machine={"copper-ingot": Fraction(1)},
            ),
            MachineGroup(
                recipe_id="magnetic-coil",
                machine_item_id="assembling-machine-2",
                count=1,
                inputs_per_machine={"copper-ingot": Fraction(1)},
                outputs_per_machine={"magnetic-coil": Fraction(1)},
            ),
        ),
        external_inputs={"copper-ore": Fraction(1)},
        outputs={"magnetic-coil": Fraction(1)},
        belt_item_id="conveyor-belt-2",
        belt_items_per_second=Fraction(12),
    )


def orphaned_lane() -> tuple[PlacedBuilding, ...]:
    """A consumer, a lane it draws from, and nothing filling that lane.

    0 consumer machine   1..3 lane belts   4 sorter lane -> machine
    """
    return (
        machine(0, 0, recipe_id=6),
        belt(0, 4, out=2, carries="copper-ingot"),
        belt(1, 4, out=3, carries="copper-ingot"),
        belt(2, 4, carries="copper-ingot"),
        sorter(0, 4, 0, 2, inp=1, out=0),
    )


def test_flow_lane_sourced_fires_on_an_orphaned_lane() -> None:
    r = validate(place(*orphaned_lane()), lane_spec(), ids=LANE_IDS)
    assert fired(r, "flow.lane_sourced")


def test_flow_lane_sourced_clean_when_a_producer_fills_the_lane() -> None:
    """The same lane, with a smelter putting onto it. Nothing else changes."""
    p = place(
        *orphaned_lane(),
        machine(0, 6, item_id=SMELTER, recipe_id=5),  # 5
        sorter(0, 6, 0, 4, inp=5, out=1),  # 6: producer -> lane
    )
    r = validate(p, lane_spec(), ids=LANE_IDS)
    assert not fired(r, "flow.lane_sourced")


def test_flow_lane_sourced_clean_when_another_run_feeds_the_head() -> None:
    """A merge point heads its own run while being perfectly well fed.

    ``_build_runs`` starts a new run at any belt with more than one predecessor,
    so a merged lane's head belongs to a run nothing *within* that run fills.
    Reading ``input_obj`` to test this reported every merge as unsourced --
    belts chain forward via ``output_obj`` and do not use ``input_obj`` at all.
    """
    p = place(
        *orphaned_lane(),
        belt(-1, 4, out=1, carries="copper-ingot"),  # 5
        belt(0, 3, out=1, carries="copper-ingot"),  # 6: belt 1 now has two preds
    )
    r = validate(p, lane_spec(), ids=LANE_IDS)
    assert not fired(r, "flow.lane_sourced")


def test_flow_lane_sourced_clean_for_an_external_input_lane() -> None:
    """An ore belt is filled by the player, not by anything in the blueprint."""
    p = place(
        machine(0, 0, item_id=SMELTER, recipe_id=5),
        belt(0, 4, out=2, carries="copper-ore"),
        belt(1, 4, out=3, carries="copper-ore"),
        belt(2, 4, carries="copper-ore"),
        sorter(0, 4, 0, 2, inp=1, out=0),
    )
    r = validate(p, lane_spec(), ids=LANE_IDS)
    assert not fired(r, "flow.lane_sourced")


def test_flow_lane_sourced_ignores_a_lane_nothing_draws_from() -> None:
    """An unfed lane feeding nobody starves nobody; only drained lanes matter."""
    p = place(
        belt(0, 4, out=1, carries="copper-ingot"),
        belt(1, 4, carries="copper-ingot"),
    )
    r = validate(p, lane_spec(), ids=LANE_IDS)
    assert not fired(r, "flow.lane_sourced")


# --- junctions -------------------------------------------------------------
#
# A splitter is the primitive that lets one belt serve more than one
# destination, and it is a RUN BOUNDARY: `_build_runs` chains belt to belt, so
# every check that reasons per-run used to stop dead at one and read the far
# side as unconnected.  These tests are built around hand-made placements
# because no strategy emitted a splitter when they were written.
#
# The convention is read off the 25 splitters in the fixture corpus: the
# splitter records no links, every attached belt sits at exactly its tile, a
# belt feeding it names it as `output_obj` and a belt drawing from it names it
# as `input_obj`.


def severities(report: Report, check: str) -> list[Severity]:
    return [f.severity for f in report.by_check(check)]


def junction_pair() -> Placement:
    """The corpus shape: a lane into a splitter, two lanes out of it.

    Belts 0..1 run into the junction, belts 3 and 5 leave it.  All three of the
    belts touching the junction share its tile, which is how a belt running
    *through* a splitter is recorded -- two belt buildings on that tile, one
    ending at the junction and one starting from it.
    """
    return place(
        belt(0, 1, out=1),  # 0
        belt(0, 0, out=2),  # 1  feeds the junction
        splitter(0, 0),  # 2
        belt(0, 0, inp=2, out=4),  # 3  draws from it
        belt(1, 0),  # 4
        belt(0, 0, inp=2, out=6),  # 5  draws from it
        belt(0, -1),  # 6
    )


def test_junction_ports_clean_at_four_attachments() -> None:
    """Four is legal -- a splitter has four sides."""
    p = place(
        belt(0, 0, out=1),  # 0
        splitter(0, 0),  # 1
        belt(0, 0, inp=1),  # 2
        belt(0, 0, inp=1),  # 3
        belt(0, 0, inp=1),  # 4
    )
    assert not fired(validate(p), "junction.ports")


def test_junction_ports_fires_on_a_fifth_attachment() -> None:
    """A splitter with five attachments pastes cleanly and drops one.

    That silent drop is the exact failure splitters were introduced to fix, so a
    validator that lets it through is worse than useless here.
    """
    p = place(
        belt(0, 0, out=1),  # 0
        splitter(0, 0),  # 1
        belt(0, 0, inp=1),  # 2
        belt(0, 0, inp=1),  # 3
        belt(0, 0, inp=1),  # 4
        belt(0, 0, inp=1),  # 5
    )
    r = validate(p)
    assert fired(r, "junction.ports")
    assert r.by_check("junction.ports")[0].detail["attached"] == 5


def test_junction_colocated_clean_when_every_belt_shares_the_tile() -> None:
    assert not fired(validate(junction_pair()), "junction.colocated")


def test_junction_colocated_fires_on_an_adjacent_attachment() -> None:
    """A belt naming a splitter from the next tile over pastes UNCONNECTED.

    Nothing about the blueprint looks wrong -- the building exists, the link
    resolves, the geometry is plausible -- and everything downstream of that
    side silently receives nothing.  Measured on all 25 corpus splitters:
    dx = dy = 0, without exception.
    """
    p = place(
        belt(0, 0, out=1),  # 0
        splitter(0, 0),  # 1
        belt(1, 0, inp=1),  # 2  one tile east of the junction
    )
    r = validate(p)
    assert fired(r, "junction.colocated")
    f = r.by_check("junction.colocated")[0]
    assert f.detail["dx"] == 1
    assert f.detail["belt"] == 2


def test_junction_colocated_fires_across_altitudes_too() -> None:
    """Same tile, wrong level, is still a side that pastes unconnected."""
    p = place(belt(0, 0, out=1), splitter(0, 0), belt(0, 0, 1, inp=1))
    assert fired(validate(p), "junction.colocated")


def test_junction_records_no_links_fires_when_a_splitter_names_a_neighbour() -> None:
    """A junction names nobody; the belts around it name it.

    A link recorded on the splitter itself is invisible to every other check
    here, because `_context` reads a junction's attachments off the BELTS.  So
    the connection it claims is verified by nothing at all.
    """
    from dataclasses import replace

    p = place(belt(0, 0, out=1), replace(splitter(0, 0), output_obj=0), belt(0, 0, inp=1))
    r = validate(p)
    assert fired(r, "junction.records_no_links")


def test_junction_records_no_links_clean_on_the_corpus_shape() -> None:
    assert not fired(validate(junction_pair()), "junction.records_no_links")


def test_geom_belt_single_occupancy_allows_belts_stacked_on_a_junction() -> None:
    """Three belts on a splitter tile is what the game itself records.

    Splitter 140 in `factory-quick-start-step-3-red-cube` has exactly three
    co-located belts: one drawing from it and two feeding it.  Reporting that
    would flag a blueprint the game produced.
    """
    assert not fired(validate(junction_pair()), "geom.belt_single_occupancy")


def test_geom_belt_single_occupancy_still_fires_on_an_unattached_stack() -> None:
    """The exemption is for junction attachments, not for junction tiles.

    A belt that merely happens to share a splitter's tile without naming it is
    not part of the junction -- it is the ordinary collision this check exists to
    catch, wearing a splitter as cover.
    """
    p = place(
        belt(0, 0, out=1),  # 0  attached
        splitter(0, 0),  # 1
        belt(0, 0, inp=1),  # 2  attached
        belt(0, 0),  # 3  names nothing: a genuine collision
    )
    r = validate(p)
    assert fired(r, "geom.belt_single_occupancy")
    assert r.by_check("geom.belt_single_occupancy")[0].detail["unattached"] == 1


def test_geom_belt_single_occupancy_still_fires_without_any_junction() -> None:
    assert fired(validate(place(belt(0, 0), belt(0, 0))), "geom.belt_single_occupancy")


def test_belt_acyclic_follows_a_loop_through_a_junction() -> None:
    """A cycle that closes THROUGH a splitter.

    A splitter has no `output_obj` of its own, so a walk that follows links
    alone stops dead at one and never closes the loop.  This is the shape a
    fan-out router produces most easily -- tap a lane, run the branch around,
    and merge it back into its own source.
    """
    p = place(
        belt(0, 0, out=1),  # 0
        splitter(0, 0),  # 1
        belt(0, 0, inp=1, out=3),  # 2
        belt(1, 0, out=4),  # 3
        belt(1, 1, out=5),  # 4
        belt(0, 1, out=0),  # 5  back to belt 0
    )
    r = validate(p)
    assert fired(r, "belt.acyclic"), "a loop closing through a splitter is still a loop"


def test_belt_acyclic_clean_on_a_junction_that_merely_branches() -> None:
    assert not fired(validate(junction_pair()), "belt.acyclic")


def test_belt_termination_fires_on_a_junction_nothing_draws_from() -> None:
    """A run ending at a splitter with no taps is a hole items fall into.

    The run terminates, the link resolves, every building exists -- and the flow
    stops there.  An ERROR rather than the WARNING a bare belt end gets, because
    a dangling tail is wasted area while a dead junction means the items routed
    into it never arrive.
    """
    p = place(belt(0, 1, out=1), belt(0, 0, out=2), splitter(0, 0))
    r = validate(p)
    assert Severity.ERROR in severities(r, "belt.termination")


def test_belt_termination_clean_when_the_junction_has_taps() -> None:
    assert Severity.ERROR not in severities(validate(junction_pair()), "belt.termination")


def test_belt_continuity_fires_on_a_junction_nothing_feeds() -> None:
    """Belts drawing from a junction with no supply carry nothing.

    Detectable with no BuildSpec at all, which is why it lives here: it is a
    break in the belt path itself, visible from the placement alone.
    """
    p = place(splitter(0, 0), belt(0, 0, inp=0, out=2), belt(1, 0))
    r = validate(p)
    assert fired(r, "belt.continuity")
    assert r.by_check("belt.continuity")[0].detail["feeding"] == 0


def test_belt_continuity_fires_on_a_junction_with_nothing_attached() -> None:
    assert fired(validate(place(splitter(0, 0))), "belt.continuity")


def test_belt_continuity_clean_on_the_corpus_shape() -> None:
    assert not fired(validate(junction_pair()), "belt.continuity")


# --- junction-aware throughput ---------------------------------------------
#
# `flow.belt_capacity` is the check a splitter breaks hardest.  A splitter
# divides throughput among its outputs and merges it on its inputs, so a check
# that ignores junctions either misses a genuinely overloaded belt or invents a
# violation on a correctly split one.  Both directions are pinned below.

SPLIT_IDS = IdMap(
    recipes={"magnetic-coil": 6, "copper-ingot": 5},
    items={
        "assembling-machine-2": ASSEMBLER,
        "arc-smelter": SMELTER,
        "copper-ore": 1002,
        "copper-ingot": COPPER_ID,
        "magnetic-coil": 1101,
    },
)


def two_consumers_of_ore(rate: Fraction) -> BuildSpec:
    """Two identical machines, each drawing ``rate`` of a belted-in ore."""
    return BuildSpec(
        groups=(
            MachineGroup(
                recipe_id="magnetic-coil",
                machine_item_id="assembling-machine-2",
                count=2,
                inputs_per_machine={"copper-ore": rate},
                outputs_per_machine={"magnetic-coil": Fraction(1)},
            ),
        ),
        external_inputs={"copper-ore": rate * 2},
        outputs={"magnetic-coil": Fraction(2)},
        belt_item_id="conveyor-belt-2",
        belt_items_per_second=Fraction(12),
    )


def split_trunk() -> Placement:
    """One trunk, a junction, two branches, a machine on each branch.

    The trunk carries a belted-in ore, so NO sorter touches it: everything it
    must carry it must carry on behalf of consumers on the far side of the
    junction.  Summing only the sorters that touch a run charges this trunk
    zero.
    """
    return place(
        machine(3, 0, recipe_id=6),  # 0  x 3..6, y 0..3
        machine(1, -5, recipe_id=6),  # 1  x 1..4, y -5..-2
        belt(0, 3, out=3, carries="copper-ore"),  # 2  trunk
        belt(0, 2, out=4, carries="copper-ore"),  # 3
        belt(0, 1, out=5, carries="copper-ore"),  # 4
        belt(0, 0, out=6, carries="copper-ore"),  # 5  feeds the junction
        splitter(0, 0),  # 6
        belt(0, 0, inp=6, out=8, carries="copper-ore"),  # 7  branch east
        belt(1, 0, out=9, carries="copper-ore"),  # 8
        belt(2, 0, carries="copper-ore"),  # 9
        belt(0, 0, inp=6, out=11, carries="copper-ore"),  # 10 branch north
        belt(0, -1, out=12, carries="copper-ore"),  # 11
        belt(0, -2, carries="copper-ore"),  # 12
        sorter(2, 0, 3, 0, inp=9, out=0, item_id=PILE),  # 13
        sorter(0, -2, 1, -2, inp=12, out=1, item_id=PILE),  # 14
    )


def test_flow_belt_capacity_charges_a_trunk_for_what_its_branches_draw() -> None:
    """The load-bearing junction test.

    Two machines take 8/s each on the far side of a splitter, so the trunk
    feeding that splitter must carry 16/s on a lane that sustains 12.  No sorter
    touches the trunk at all, so a check that adds up the sorters on each run
    charges it ZERO and reports a clean build.  Neither branch is over on its
    own -- 8 is inside 12 -- so any finding here is necessarily the trunk.
    """
    r = validate(split_trunk(), two_consumers_of_ore(Fraction(8)), ids=SPLIT_IDS)
    findings = r.by_check("flow.belt_capacity")
    assert findings, "16/s pulled through a junction must be charged to the trunk"
    assert findings[0].detail["required"] == "16"
    assert 5 in findings[0].buildings, "the trunk belts are the ones to widen"


def test_flow_belt_capacity_clean_when_the_split_load_fits() -> None:
    r = validate(split_trunk(), two_consumers_of_ore(Fraction(5)), ids=SPLIT_IDS)
    assert not fired(r, "flow.belt_capacity")


def test_flow_headroom_reports_the_trunk_rate_as_an_exact_fraction() -> None:
    r = validate(split_trunk(), two_consumers_of_ore(Fraction(7, 3)), ids=SPLIT_IDS)
    carried = {str(f.detail["required"]) for f in r.by_check("flow.headroom")}
    assert "14/3" in carried, f"expected the exact summed trunk rate, got {carried}"


def merge_trunks() -> Placement:
    """Two trunks into one junction, two branches out of it.

    Four attachments, which is exactly what a splitter's four sides allow.  Each
    trunk supplies half of what the two branches draw; charging each of them the
    whole load is how a correctly split lane acquires an invented violation.
    """
    return place(
        machine(3, 0, recipe_id=6),  # 0  x 3..6, y 0..3
        machine(1, -5, recipe_id=6),  # 1  x 1..4, y -5..-2
        belt(0, 3, out=3, carries="copper-ore"),  # 2  trunk A
        belt(0, 2, out=4, carries="copper-ore"),  # 3
        belt(0, 1, out=5, carries="copper-ore"),  # 4
        belt(0, 0, out=10, carries="copper-ore"),  # 5  feeds the junction
        belt(-3, 0, out=7, carries="copper-ore"),  # 6  trunk B
        belt(-2, 0, out=8, carries="copper-ore"),  # 7
        belt(-1, 0, out=9, carries="copper-ore"),  # 8
        belt(0, 0, out=10, carries="copper-ore"),  # 9  feeds the junction
        splitter(0, 0),  # 10
        belt(0, 0, inp=10, out=12, carries="copper-ore"),  # 11 branch east
        belt(1, 0, out=13, carries="copper-ore"),  # 12
        belt(2, 0, carries="copper-ore"),  # 13
        belt(0, 0, inp=10, out=15, carries="copper-ore"),  # 14 branch north
        belt(0, -1, out=16, carries="copper-ore"),  # 15
        belt(0, -2, carries="copper-ore"),  # 16
        sorter(2, 0, 3, 0, inp=13, out=0, item_id=PILE),  # 17
        sorter(0, -2, 1, -2, inp=16, out=1, item_id=PILE),  # 18
    )


def test_flow_belt_capacity_does_not_invent_a_violation_on_a_merged_feed() -> None:
    """8/s per branch is 16/s through the junction, split over two trunks.

    Each trunk carries 8, which fits the 12/s tier, and so does each branch.
    Charging every input of a merge the merge's whole load would report both
    trunks as over capacity -- punishing a layout for splitting correctly, which
    is worse than missing an overload because it makes the tool refuse to emit.
    """
    r = validate(merge_trunks(), two_consumers_of_ore(Fraction(8)), ids=SPLIT_IDS)
    assert not fired(r, "flow.belt_capacity"), [
        f.message for f in r.by_check("flow.belt_capacity")
    ]


def test_flow_belt_capacity_still_fires_when_a_merged_feed_genuinely_overflows() -> None:
    """Guards the guard: halving the charge must not disable the check.

    7/s per branch is 14/s through the junction, so each trunk carries 7 and
    fits, but each BRANCH carries 14 against a 12/s tier and does not.
    """
    r = validate(merge_trunks(), two_consumers_of_ore(Fraction(14)), ids=SPLIT_IDS)
    assert fired(r, "flow.belt_capacity")


# --- a lane is not charged twice for the same items -------------------------


def producer_to_consumer_spec(rate: Fraction) -> BuildSpec:
    return BuildSpec(
        groups=(
            MachineGroup(
                recipe_id="copper-ingot",
                machine_item_id="arc-smelter",
                count=1,
                inputs_per_machine={"copper-ore": rate},
                outputs_per_machine={"copper-ingot": rate},
            ),
            MachineGroup(
                recipe_id="magnetic-coil",
                machine_item_id="assembling-machine-2",
                count=1,
                inputs_per_machine={"copper-ingot": rate},
                outputs_per_machine={"magnetic-coil": Fraction(1)},
            ),
        ),
        external_inputs={"copper-ore": rate},
        outputs={"magnetic-coil": Fraction(1)},
        belt_item_id="conveyor-belt-2",
        belt_items_per_second=Fraction(12),
    )


def one_lane_between_two_machines() -> Placement:
    """A smelter fills a lane; an assembler drains it.  One flow, one lane."""
    return place(
        machine(0, 0, item_id=SMELTER, recipe_id=5),  # 0  x 0..2, y 0..2
        machine(4, 0, recipe_id=6),  # 1  x 4..7, y 0..3
        belt(3, 0, out=3, carries="copper-ingot"),  # 2
        belt(3, 1, out=4, carries="copper-ingot"),  # 3
        belt(3, 2, carries="copper-ingot"),  # 4
        sorter(2, 1, 3, 1, inp=0, out=3, item_id=PILE),  # 5  producer -> lane
        sorter(3, 1, 4, 1, inp=3, out=1, item_id=PILE),  # 6  lane -> consumer
    )


def test_a_lane_carries_what_flows_through_it_not_twice_that() -> None:
    """Put 10/s on and take 10/s off, and the belt is carrying 10.

    Adding what producers put on to what consumers take off charged this lane
    20/s and reported a 12/s belt as over capacity -- a refusal to emit a layout
    that runs perfectly.  Measured on freeform's real output, five runs on
    `fan_out_spec` were being double-charged this way.
    """
    r = validate(
        one_lane_between_two_machines(), producer_to_consumer_spec(Fraction(10)), ids=SPLIT_IDS
    )
    assert not fired(r, "flow.belt_capacity"), [
        f.message for f in r.by_check("flow.belt_capacity")
    ]
    carried = {str(f.detail["required"]) for f in r.by_check("flow.headroom")}
    assert "10" in carried and "20" not in carried, carried


def test_a_lane_over_its_tier_is_still_reported() -> None:
    """Guards the guard: 14/s through a 12/s lane is still an error."""
    r = validate(
        one_lane_between_two_machines(), producer_to_consumer_spec(Fraction(14)), ids=SPLIT_IDS
    )
    assert fired(r, "flow.belt_capacity")


# --- orphan severity: "another source" is not the same as "enough" ----------
#
# A belt run nothing fills is graded a WARNING when every machine drawing from
# it has another source.  That is right for a genuinely redundant lane and wrong
# for the freeform fan-out case, where several nets left one lane end, only the
# last was linked, and the "other source" was the one net that won the race --
# carrying its share of the demand and no more.


def coil_spec(rate: Fraction) -> BuildSpec:
    """One assembler wanting ``rate`` of copper-ingot, and a smelter making it."""
    return BuildSpec(
        groups=(
            MachineGroup(
                recipe_id="copper-ingot",
                machine_item_id="arc-smelter",
                count=1,
                inputs_per_machine={"copper-ore": rate},
                outputs_per_machine={"copper-ingot": rate},
            ),
            MachineGroup(
                recipe_id="magnetic-coil",
                machine_item_id="assembling-machine-2",
                count=1,
                inputs_per_machine={"copper-ingot": rate},
                outputs_per_machine={"magnetic-coil": Fraction(1)},
            ),
        ),
        external_inputs={"copper-ore": rate},
        outputs={"magnetic-coil": Fraction(1)},
        belt_item_id="conveyor-belt-2",
        belt_items_per_second=Fraction(12),
    )


def half_fed_machine(*, fill_the_second_lane: bool) -> Placement:
    """One machine drawing the same item from two lanes; one of them is dry.

    Both sorters are Mk.III, which sustains 6/s at one tile, so the surviving
    lane can deliver at most 6/s however much the machine wants.
    """
    parts = [
        machine(4, 0, recipe_id=6),  # 0  x 4..7, y 0..3
        belt(3, 0, carries="copper-ingot"),  # 1  the dry lane
        belt(3, 1, carries="copper-ingot"),  # 2  the other lane
        sorter(3, 0, 4, 0, inp=1, out=0),  # 3  dry lane -> machine
        sorter(3, 1, 4, 1, inp=2, out=0),  # 4  other lane -> machine
    ]
    if fill_the_second_lane:
        parts += [
            machine(0, 0, item_id=SMELTER, recipe_id=5),  # 5  x 0..2, y 0..2
            sorter(2, 1, 3, 1, inp=5, out=2),  # 6  producer fills lane 2
        ]
    return place(*parts)


def test_orphan_lane_is_an_error_when_the_survivor_cannot_carry_the_load() -> None:
    """The machine wants 10/s and the one live sorter sustains 6/s.

    "Some other sorter also feeds it" is not the claim that matters.  A machine
    wanting 10/s from two lanes gets 6/s when one of them is dry, and
    under-produces for ever while the validator calls the dead lane wasted
    belts.  That is exactly the freeform fan-out miss.
    """
    p = half_fed_machine(fill_the_second_lane=True)
    r = validate(p, coil_spec(Fraction(10)), ids=SPLIT_IDS)
    assert Severity.ERROR in severities(r, "flow.lane_sourced"), [
        (f.severity, f.message) for f in r.by_check("flow.lane_sourced")
    ]


def test_orphan_lane_stays_a_warning_when_the_survivor_covers_the_demand() -> None:
    """A genuinely redundant lane: 5/s wanted, 6/s still deliverable.

    Nothing starves, so promoting this would make the tool refuse to emit a
    build that runs.  The lane is wasted belts and is reported as such.
    """
    p = half_fed_machine(fill_the_second_lane=True)
    r = validate(p, coil_spec(Fraction(5)), ids=SPLIT_IDS)
    found = severities(r, "flow.lane_sourced")
    assert found, "the dry lane must still be reported"
    assert Severity.ERROR not in found


def test_two_dry_lanes_cannot_excuse_each_other() -> None:
    """Neither lane is fed, and each used to count as the other's alternative.

    Excluding only the run being reported let a machine fed exclusively by lanes
    nothing filled read as clean, twice over.
    """
    p = half_fed_machine(fill_the_second_lane=False)
    r = validate(p, coil_spec(Fraction(5)), ids=SPLIT_IDS)
    assert Severity.ERROR in severities(r, "flow.lane_sourced")


# --- external inputs -------------------------------------------------------
#
# A run carrying an external input is exempt from `flow.lane_sourced`: the
# player fills it.  That exemption was briefly narrowed to runs touching the
# bounding box, which catches nothing in spine (every corridor copy runs to
# x=0) and invents errors in freeform (in-lanes sit where the strip lands).
# What separates a real second entry point from a lane copy nobody feeds is
# whether the player can REACH it.


def ore_spec() -> BuildSpec:
    return BuildSpec(
        groups=(
            MachineGroup(
                recipe_id="copper-ingot",
                machine_item_id="arc-smelter",
                count=1,
                inputs_per_machine={"copper-ore": Fraction(1)},
                outputs_per_machine={"copper-ingot": Fraction(1)},
            ),
        ),
        external_inputs={"copper-ore": Fraction(1)},
        outputs={"copper-ingot": Fraction(1)},
        belt_item_id="conveyor-belt-2",
        belt_items_per_second=Fraction(12),
    )


def inland_input_lane() -> Placement:
    """An external in-lane seated well inside the bounding box.

    Freeform does exactly this -- it seats each consumer strip's in-lane where
    the strip lands.  The player belts into it and it works, so it must not be
    reported.
    """
    return place(
        machine(6, 6, item_id=SMELTER, recipe_id=5),  # 0  x 6..8, y 6..8
        belt(5, 6, carries="copper-ore"),  # 1
        sorter(5, 6, 6, 6, inp=1, out=0),  # 2
        belt(0, 0),  # 3  pushes the bounding box well away from the lane
        belt(20, 20),  # 4
    )


def test_an_inland_external_lane_is_not_reported_as_unsourced() -> None:
    r = validate(inland_input_lane(), ore_spec(), ids=SPLIT_IDS)
    assert not fired(r, "flow.lane_sourced")


def test_an_inland_external_lane_is_reachable() -> None:
    """Inland is not the same as unreachable; there is free ground beside it."""
    r = validate(inland_input_lane(), ore_spec(), ids=SPLIT_IDS)
    assert not fired(r, "flow.external_entry_reachable")


def walled_in_input_lane(*, leave_a_gap: bool) -> Placement:
    """An external in-lane with every neighbouring tile built on.

    Measured on freeform's `proliferated_spec` output: the `iron-ore` lane at
    (7,0) was sealed in by the lane above it and the machine band below, so
    nothing could reach it -- not a router, and not the player.
    """
    ring = [(2, 2), (3, 2), (4, 2), (2, 3), (4, 3), (2, 4), (3, 4), (4, 4)]
    if leave_a_gap:
        ring.remove((2, 3))
    return place(
        belt(3, 3, carries="copper-ore"),  # 0  the lane the player must fill
        *(belt(x, y) for x, y in ring),
    )


def test_flow_external_entry_reachable_fires_on_a_walled_in_lane() -> None:
    """No belt can be run to it, so the item never arrives.

    An ERROR because nothing about the blueprint looks wrong: every building
    exists, every link resolves, and the machines downstream simply never get
    fed.
    """
    r = validate(walled_in_input_lane(leave_a_gap=False), ore_spec(), ids=SPLIT_IDS)
    findings = r.by_check("flow.external_entry_reachable")
    assert findings
    assert findings[0].detail["item"] == "copper-ore"
    assert findings[0].severity is Severity.ERROR


def test_flow_external_entry_reachable_clean_when_one_side_is_open() -> None:
    """Guards the guard: a single free neighbour is enough to feed the lane."""
    r = validate(walled_in_input_lane(leave_a_gap=True), ore_spec(), ids=SPLIT_IDS)
    assert not fired(r, "flow.external_entry_reachable")


def test_flow_external_entry_points_warns_on_several_lanes_for_one_item() -> None:
    """Spine's magnetic-ring output asks for `coal` at five separate lanes.

    Legitimate -- the player can belt an item in as many times as asked -- but a
    real cost that a bounding-box density comparison hides completely.
    """
    p = place(
        machine(6, 6, item_id=SMELTER, recipe_id=5),  # 0
        belt(5, 6, carries="copper-ore"),  # 1
        belt(5, 8, carries="copper-ore"),  # 2  a second, separate entry lane
        sorter(5, 6, 6, 6, inp=1, out=0),  # 3
        sorter(5, 8, 6, 8, inp=2, out=0),  # 4
    )
    r = validate(p, ore_spec(), ids=SPLIT_IDS)
    findings = r.by_check("flow.external_entry_points")
    assert findings
    assert findings[0].detail["entry_lanes"] == 2
    assert findings[0].severity is Severity.WARNING, "nothing starves; must not block emission"


def test_flow_external_entry_points_silent_on_a_single_entry() -> None:
    r = validate(inland_input_lane(), ore_spec(), ids=SPLIT_IDS)
    assert not fired(r, "flow.external_entry_points")


# --- item attribution crosses a junction -----------------------------------


def test_flow_lane_attribution_sees_items_arriving_through_a_junction() -> None:
    """A trunk carrying two items, split to a branch with an unfiltered sorter.

    The unfiltered sorter feeds a two-ingredient machine, so what it takes off
    the branch cannot be determined -- and the branch is a MIXED lane only if
    you follow the items across the junction that fills it.  Reading only the
    sorters that touch each run left the branch looking like a clean
    single-item lane, and a capacity verdict on it would be one the build never
    earned.
    """
    spec = BuildSpec(
        groups=(
            MachineGroup(
                recipe_id="copper-ingot",
                machine_item_id="arc-smelter",
                count=1,
                inputs_per_machine={"copper-ore": Fraction(1)},
                outputs_per_machine={"copper-ingot": Fraction(1)},
            ),
            MachineGroup(
                recipe_id="magnetic-coil",
                machine_item_id="assembling-machine-2",
                count=1,
                # Two ingredients, so an unfiltered sorter could be moving either.
                inputs_per_machine={"copper-ingot": Fraction(1), "copper-ore": Fraction(1)},
                outputs_per_machine={"magnetic-coil": Fraction(1)},
            ),
        ),
        external_inputs={"copper-ore": Fraction(2)},
        outputs={"magnetic-coil": Fraction(1)},
    )
    p = place(
        machine(3, 4, item_id=SMELTER, recipe_id=5),  # 0  x 3..5, y 4..6
        machine(3, -5, recipe_id=6),  # 1  x 3..6, y -5..-2
        belt(0, 1, out=2),  # 2  trunk head
        belt(0, 0, out=3),  # 3  feeds the junction
        splitter(0, 0),  # 4
        belt(0, 0, inp=4, out=6),  # 5  branch east -- filtered draw
        belt(1, 0, out=7),  # 6
        belt(2, 0),  # 7
        belt(0, 0, inp=4, out=9),  # 8  branch north -- unfiltered draw
        belt(0, -1, out=10),  # 9
        belt(0, -2),  # 10
        sorter(2, 0, 3, 0, inp=7, out=0, item_id=PILE, filter_id=1002),  # 11 copper-ore
        sorter(0, -2, 1, -2, inp=10, out=1, item_id=PILE),  # 12 unfiltered, ambiguous
    )
    r = validate(p, spec, ids=SPLIT_IDS)
    findings = r.by_check("flow.lane_attribution")
    assert findings, "the mixed lane is only visible by following items across the junction"
    assert 12 in findings[0].buildings


# --- dead belt -------------------------------------------------------------
#
# `belt.termination` used to ask whether the TAIL TILE was tapped, which is not
# the same question as whether the lane wastes anything: both strategies end a
# lane a couple of tiles past its last consumer, so a correct lane failed while
# wasting two tiles out of fifty.  Measured across both strategies' fixtures it
# warned on 95 of 130 runs, and on the twelve-URL bake-off corpus on 380 of 517.
# It now measures the SIZE of the overshoot, and those rates fall to 7% and 14%.


def tapped_lane(length: int) -> Placement:
    """A lane of ``length`` tiles whose FIRST tile feeds a machine."""
    belts = [belt(0, y, out=y + 1 if y + 1 < length else None) for y in range(length)]
    return place(
        *belts,
        machine(2, 0, recipe_id=6),
        sorter(0, 0, 2, 0, inp=0, out=length),
    )


def test_belt_termination_ignores_a_short_overshoot() -> None:
    """Two tiles past the last tap is the emitters' standard stub, not waste.

    This is the load-bearing half of the tightening: under the old tail-tile
    rule this lane warned, and so did nearly every correct lane either strategy
    emits, which is how the check came to fire on 73% of runs and be worth
    reading on none of them.
    """
    r = validate(tapped_lane(3))
    assert Severity.WARNING not in severities(r, "belt.termination")


def test_belt_termination_fires_on_a_long_dead_tail() -> None:
    r = validate(tapped_lane(10))
    findings = [f for f in r.by_check("belt.termination") if f.severity is Severity.WARNING]
    assert findings, "nine tiles past the last tap is lane nobody can ever use"
    assert findings[0].detail["dead"] == 9
    assert findings[0].detail["length"] == 10


def test_belt_termination_fires_on_a_lane_nothing_taps_at_all() -> None:
    """No tap anywhere is not an overshoot; it is a lane serving nothing.

    Reported however short it is, which is what catches spine's six 51-tile
    magnetic-ring lanes that no sorter touches.
    """
    r = validate(place(belt(0, 0, out=1), belt(0, 1)))
    findings = [f for f in r.by_check("belt.termination") if f.severity is Severity.WARNING]
    assert findings
    assert findings[0].detail["taps"] == 0
    assert findings[0].detail["dead"] == 2


# --- transfer sorters are edges, not dead ends -----------------------------
#
# A sorter with a belt on BOTH ends moves a lane's load onto another lane.  It
# was invisible to the flow graph and to `_sorter_flows` alike, so a trunk
# drained this way was charged ZERO and `flow.belt_capacity` could not see the
# load leaving it at all.


TRANSFER_IDS = IdMap(
    recipes={"magnetic-coil": 6},
    items={"assembling-machine-2": ASSEMBLER, "iron-ingot": IRON_ID, "magnetic-coil": 1101},
)


def transfer_spec() -> BuildSpec:
    return BuildSpec(
        groups=(
            MachineGroup(
                recipe_id="magnetic-coil",
                machine_item_id="assembling-machine-2",
                count=1,
                inputs_per_machine={"iron-ingot": Fraction(20)},
                outputs_per_machine={"magnetic-coil": Fraction(1)},
            ),
        ),
        external_inputs={"iron-ingot": Fraction(20)},
        outputs={"magnetic-coil": Fraction(1)},
        belt_item_id="conveyor-belt-2",
        belt_items_per_second=Fraction(12),
    )


def transferred_load() -> Placement:
    """A trunk whose whole load leaves it through a belt-to-belt sorter."""
    return place(
        belt(0, 0, out=1, carries="iron-ingot"),  # 0  trunk head
        belt(0, 1, carries="iron-ingot"),  # 1  trunk tail
        belt(2, 1, out=3, carries="iron-ingot"),  # 2  branch head
        belt(2, 0, carries="iron-ingot"),  # 3  branch tail
        machine(3, 0, recipe_id=6),  # 4  x 3..5, y 0..2
        sorter(0, 1, 2, 1, inp=1, out=2, item_id=PILE),  # 5  the transfer
        sorter(2, 0, 3, 0, inp=3, out=4, item_id=PILE),  # 6  branch -> machine
        belt(6, 0, carries="magnetic-coil"),  # 7
        sorter(5, 0, 6, 0, inp=4, out=7, item_id=PILE),  # 8  drain
    )


def test_flow_belt_capacity_follows_a_belt_to_belt_sorter() -> None:
    """20/s leaves the trunk through a sorter, so the trunk carries 20/s.

    The load-bearing test.  The trunk has no sorter of its own that a rate can
    be read off -- ``_sorter_demand`` returns ``None`` when neither end of a
    sorter is a machine -- so before the transfer was modelled as a graph edge
    the trunk was charged nothing and a Mk.II belt carrying 20/s reported clean.
    """
    r = validate(transferred_load(), transfer_spec(), ids=TRANSFER_IDS)
    charged = {b for f in r.by_check("flow.belt_capacity") for b in f.buildings}
    assert {0, 1} <= charged, (
        "the trunk carries the branch's whole load and must be judged against its tier"
    )


def test_flow_lane_sourced_clean_on_a_lane_fed_only_by_a_transfer() -> None:
    r = validate(transferred_load(), transfer_spec(), ids=TRANSFER_IDS)
    assert not fired(r, "flow.lane_sourced")


# --- reachability balance --------------------------------------------------
#
# `flow.conservation`'s placement half.  The spec arithmetic balances, every
# lane is sourced, every machine has its sorters, every belt is inside its tier
# -- and half the machines still starve, because the ingots that would feed
# them are on a lane with no path to them.


SPLIT_ISLAND_IDS = IdMap(
    recipes={"iron-ingot": 10, "gear": 20, "magnetic-coil": 6},
    items={
        "arc-smelter": SMELTER,
        "assembling-machine-2": ASSEMBLER,
        "iron-ore": 1001,
        "iron-ingot": IRON_ID,
        "gear": 1201,
        "magnetic-coil": 1101,
    },
)


def split_island_spec(gear_out: Fraction = Fraction(2)) -> BuildSpec:
    """Two smelters at 1/s feeding two gear assemblers at 1/s.  It balances."""
    return BuildSpec(
        groups=(
            MachineGroup(
                recipe_id="iron-ingot",
                machine_item_id="arc-smelter",
                count=2,
                inputs_per_machine={"iron-ore": Fraction(1)},
                outputs_per_machine={"iron-ingot": Fraction(1)},
            ),
            MachineGroup(
                recipe_id="gear",
                machine_item_id="assembling-machine-2",
                count=2,
                inputs_per_machine={"iron-ingot": Fraction(1)},
                outputs_per_machine={"gear": Fraction(1)},
            ),
        ),
        external_inputs={"iron-ore": Fraction(2)},
        outputs={"gear": gear_out},
        belt_item_id="conveyor-belt-2",
        belt_items_per_second=Fraction(12),
    )


def _split_island_common() -> list[PlacedBuilding]:
    return [
        # iron-ore belted in from the west, feeding both smelters
        belt(0, 0, out=1, carries="iron-ore"),  # 0
        belt(0, 1, out=2, carries="iron-ore"),  # 1
        belt(0, 2, out=3, carries="iron-ore"),  # 2
        belt(0, 3, out=4, carries="iron-ore"),  # 3
        belt(0, 4, carries="iron-ore"),  # 4
        machine(2, 0, item_id=SMELTER, recipe_id=10),  # 5  smelter A, x 2..4, y 0..2
        machine(2, 4, item_id=SMELTER, recipe_id=10),  # 6  smelter B, x 2..4, y 4..6
        sorter(0, 0, 2, 0, inp=0, out=5),  # 7
        sorter(0, 4, 2, 4, inp=4, out=6),  # 8
        # the iron-ingot lane both gear assemblers draw from
        belt(6, 0, out=10, carries="iron-ingot"),  # 9
        belt(6, 1, out=11, carries="iron-ingot"),  # 10
        belt(6, 2, out=12, carries="iron-ingot"),  # 11
        belt(6, 3, out=13, carries="iron-ingot"),  # 12
        belt(6, 4, carries="iron-ingot"),  # 13
        sorter(4, 0, 6, 0, inp=5, out=9),  # 14  smelter A onto the lane
        machine(8, 0, recipe_id=20),  # 15  gear 1, x 8..10, y 0..2
        machine(8, 4, recipe_id=20),  # 16  gear 2, x 8..10, y 4..6
        sorter(6, 0, 8, 0, inp=9, out=15),  # 17
        sorter(6, 4, 8, 4, inp=13, out=16),  # 18
        # gear belted out
        belt(12, 0, out=20, carries="gear"),  # 19
        belt(12, 1, out=21, carries="gear"),  # 20
        belt(12, 2, out=22, carries="gear"),  # 21
        belt(12, 3, out=23, carries="gear"),  # 22
        belt(12, 4, carries="gear"),  # 23
        sorter(10, 0, 12, 0, inp=15, out=19),  # 24
        sorter(10, 4, 12, 4, inp=16, out=23),  # 25
    ]


def split_island_placement() -> Placement:
    """Smelter B drains onto a lane with no path to either consumer.

    Everything a building-counting check looks at is in order.  Both smelters
    run, both are fed, both are drained; both assemblers have their one
    ingredient sorter and their one product sorter; every lane has something
    putting items onto it; no belt is near its tier.  The ingots smelter B makes
    simply cannot get to a gear assembler, so the two of them share the 1/s
    smelter A makes and the block produces half its rated gear for ever.
    """
    return place(
        *_split_island_common(),
        belt(2, 9, out=27, carries="iron-ingot"),  # 26
        belt(3, 9, out=28, carries="iron-ingot"),  # 27
        belt(4, 9, carries="iron-ingot"),  # 28
        sorter(2, 6, 2, 9, inp=6, out=26),  # 29  smelter B onto the stranded lane
    )


def joined_island_placement() -> Placement:
    """The same build with smelter B draining onto the lane that serves them."""
    return place(*_split_island_common(), sorter(4, 4, 6, 4, inp=6, out=13))


def test_flow_conservation_fires_when_a_producer_cannot_reach_its_consumers() -> None:
    r = validate(
        split_island_placement(), split_island_spec(), ids=SPLIT_ISLAND_IDS, expect_power=False
    )
    findings = [f for f in r.by_check("flow.conservation") if "net" not in f.detail]
    assert findings, "half the ingots are stranded and both assemblers run at half rate"
    (f,) = findings
    assert f.detail == {
        "item": "iron-ingot",
        "demand": "2",
        "supply": "1",
        "shortfall": "1",
        "starved": 2,
        "lanes": [1],
    }
    assert set(f.buildings) == {15, 16}


def test_nothing_else_catches_the_stranded_producer() -> None:
    """The whole point of the check: no other error fires on this placement.

    A build that under-produces for ever while every other check reports clean
    is the worst outcome this project has, and it is exactly what wins a density
    comparison -- the stranded lane is belts the winner did not have to route.
    """
    r = validate(
        split_island_placement(), split_island_spec(), ids=SPLIT_ISLAND_IDS, expect_power=False
    )
    assert errors(r) == ["flow.conservation"], f"expected only the balance error, got {errors(r)}"


def test_flow_conservation_clean_when_the_producer_can_reach_them() -> None:
    r = validate(
        joined_island_placement(), split_island_spec(), ids=SPLIT_ISLAND_IDS, expect_power=False
    )
    assert not r.errors, [f.message for f in r.errors]


def test_flow_conservation_placement_half_defers_to_the_spec_half() -> None:
    """One unbalanced recipe is one finding, not one per island.

    When the arithmetic itself is short every island carrying the item is short,
    and restating it per island says nothing new -- eight findings on the
    magnetic-ring fixture where the spec clause already gave four.
    """
    r = validate(
        split_island_placement(),
        split_island_spec(gear_out=Fraction(5)),
        ids=SPLIT_ISLAND_IDS,
        expect_power=False,
    )
    findings = r.by_check("flow.conservation")
    assert findings, "the spec clause must still fire"
    assert all("net" in f.detail for f in findings), "no per-island restatement"


# --- and it must not fire on the things that self-balance -------------------


FAN_OUT_IDS = IdMap(
    recipes={"iron-ingot": 10, "gear": 20, "magnetic-coil": 6},
    items={
        "arc-smelter": SMELTER,
        "assembling-machine-2": ASSEMBLER,
        "iron-ore": 1001,
        "iron-ingot": IRON_ID,
        "gear": 1201,
        "magnetic-coil": 1101,
    },
)


def fan_out_spec() -> BuildSpec:
    """One smelter at 2/s feeding two consumers wanting 3/2 and 1/2."""
    return BuildSpec(
        groups=(
            MachineGroup(
                recipe_id="iron-ingot",
                machine_item_id="arc-smelter",
                count=1,
                inputs_per_machine={"iron-ore": Fraction(2)},
                outputs_per_machine={"iron-ingot": Fraction(2)},
            ),
            MachineGroup(
                recipe_id="gear",
                machine_item_id="assembling-machine-2",
                count=1,
                inputs_per_machine={"iron-ingot": Fraction(3, 2)},
                outputs_per_machine={"gear": Fraction(1)},
            ),
            MachineGroup(
                recipe_id="magnetic-coil",
                machine_item_id="assembling-machine-2",
                count=1,
                inputs_per_machine={"iron-ingot": Fraction(1, 2)},
                outputs_per_machine={"magnetic-coil": Fraction(1)},
            ),
        ),
        external_inputs={"iron-ore": Fraction(2)},
        outputs={"gear": Fraction(1), "magnetic-coil": Fraction(1)},
        belt_item_id="conveyor-belt-2",
        belt_items_per_second=Fraction(12),
    )


def fan_out_placement() -> Placement:
    """One smelter, two output sorters, two lanes with very unequal demand."""
    return place(
        belt(0, 2, out=1, carries="iron-ore"),  # 0
        belt(0, 3, out=2, carries="iron-ore"),  # 1
        belt(0, 4, carries="iron-ore"),  # 2
        machine(2, 2, item_id=SMELTER, recipe_id=10),  # 3  x 2..4, y 2..4
        sorter(0, 2, 2, 2, inp=0, out=3),  # 4
        belt(6, 2, out=6, carries="iron-ingot"),  # 5  lane A, to the gear machine
        belt(6, 1, out=7, carries="iron-ingot"),  # 6
        belt(6, 0, carries="iron-ingot"),  # 7
        sorter(4, 2, 6, 2, inp=3, out=5),  # 8
        machine(8, 0, recipe_id=20),  # 9  gear, x 8..10, y 0..2
        sorter(6, 0, 8, 0, inp=7, out=9),  # 10
        belt(6, 4, out=12, carries="iron-ingot"),  # 11  lane B, to the coil machine
        belt(6, 5, out=13, carries="iron-ingot"),  # 12
        belt(6, 6, carries="iron-ingot"),  # 13
        sorter(4, 4, 6, 4, inp=3, out=11),  # 14
        machine(8, 5, recipe_id=6),  # 15  coil, x 8..10, y 5..7
        sorter(6, 5, 8, 5, inp=12, out=15),  # 16
        belt(12, 0, carries="gear"),  # 17
        sorter(10, 0, 12, 0, inp=9, out=17),  # 18
        belt(12, 5, carries="magnetic-coil"),  # 19
        sorter(10, 5, 12, 5, inp=15, out=19),  # 20
    )


def test_flow_conservation_does_not_invent_a_shortfall_at_a_fan_out() -> None:
    """A machine's two output sorters are not a fixed divider.

    Whichever lane is not backed up gets the ingots, so 3/2 down one and 1/2
    down the other is exactly what this build does.  A per-lane verdict computed
    from an even split charges each lane 1/s and reports lane A starving -- which
    is the shape that made the per-lane version report 15 lanes short across
    ``processor`` and ``super-magnetic-ring`` with not one of them real.  The
    same argument covers a splitter and a merge; all three self-balance, and the
    cut this check makes is the one that cannot.
    """
    r = validate(fan_out_placement(), fan_out_spec(), ids=FAN_OUT_IDS, expect_power=False)
    assert not r.errors, [f.message for f in r.errors]


# --- the driver, and the indexes it shares between checks -------------------


def test_a_check_alone_says_what_it_says_inside_a_whole_run() -> None:
    """Order independence, which is what the shared-index cache costs.

    Several checks want the same derived index -- what each sorter moves, what
    each run must carry, where the towers are -- and building each one per
    caller was 90% of ``certify`` on a large placement.  They are cached on the
    ``Context`` now, so they are built by whichever check asks first.

    That is only sound if no check can observe another having run.  A cache
    keyed wrongly, or one that hands out a structure a later check mutates,
    would show up exactly here: the check alone, on a fresh Context, disagreeing
    with the same check inside a full run.  ``only=`` gives each one a Context
    of its own, so this compares the two directly, finding for finding.

    What this catches, injected and confirmed: one ``_Cache`` shared by every
    Context instead of one each.

    What it does NOT catch, also injected and confirmed: a check mutating a set
    it was handed out of the cache.  These three placements are too simple for
    that to change an answer.  The wider form of exactly this comparison --
    eighteen real placements, each damaged eight ways, 5,258 isolated check
    runs -- does catch it, at 18 disagreements, and it ran clean against the
    code as committed.  That form costs minutes and the suite is at its ceiling,
    so it lives outside; this is the part cheap enough to keep, and the reason
    :class:`validate._Cache` carries a note that what it hands out is shared.
    """
    cases = (
        (fan_out_placement(), fan_out_spec(), FAN_OUT_IDS, False),
        (place(*orphaned_lane()), lane_spec(), LANE_IDS, True),
        (place(tower(0, 0), *orphaned_lane()), lane_spec(), LANE_IDS, True),
    )
    compared = 0
    for placement, spec, ids, power in cases:
        whole = validate(placement, spec, ids=ids, expect_power=power)
        for cid in whole.checks_run:
            alone = validate(placement, spec, ids=ids, expect_power=power, only={cid})
            assert list(alone.findings) == list(whole.by_check(cid)), cid
            compared += 1
    assert compared > 90, f"only {compared} checks compared"


# --- game.belt_crossing -----------------------------------------------------


def _belt_over_assembler(belt_z: Fraction) -> Placement:
    """One Assembling Machine Mk.II on the ground, one belt tile over its centre."""
    machine = catalog_building(2304)
    belt = catalog_building(2002)
    return Placement(
        buildings=(
            PlacedBuilding(
                item_id=machine.item_id,
                model_index=machine.model_index,
                x=0,
                y=0,
                z=Fraction(0),
                width=machine.width,
                height=machine.height,
            ),
            PlacedBuilding(
                item_id=belt.item_id,
                model_index=belt.model_index,
                x=machine.width // 2,
                y=machine.height // 2,
                z=belt_z,
                width=1,
                height=1,
            ),
        )
    )


def test_a_belt_may_cross_a_machine_but_only_above_its_collider() -> None:
    """The rule the three OPEN backlog entries were blocked on.

    A belt over an Assembling Machine is legal in the game -- the belt is probed
    with a 0.23 sphere, not its box, and a machine is excused against a belt but
    not the reverse.  The price is height: the collider tops out at 4.68 units,
    so the belt must stand above z = 3.5325, which on the belt's half-level grid
    is z = 4.  Three and a half is not enough.

    The sweep starts half a level up, not at zero: a belt LEVEL with a machine
    is the lateral question, which this check deliberately does not answer.
    """
    for z in (Fraction(1, 2), Fraction(1), Fraction(2), Fraction(3), Fraction(7, 2)):
        r = validate(_belt_over_assembler(z), only={"game.belt_crossing"})
        assert r.by_check("game.belt_crossing"), f"z={z} should collide"
    r = validate(_belt_over_assembler(Fraction(4)), only={"game.belt_crossing"})
    assert not r.by_check("game.belt_crossing"), [f.message for f in r.findings]


def test_belt_crossing_names_the_height_it_needs() -> None:
    """A refusal that does not say how high to go is not actionable."""
    r = validate(_belt_over_assembler(Fraction(1)), only={"game.belt_crossing"})
    (f,) = r.by_check("game.belt_crossing")
    assert f.detail["needs_z_above"] == "3.5325"


@pytest.mark.parametrize("name", GEOMETRY_SAFE_FIXTURES)
def test_real_blueprint_has_no_belt_crossing_findings(name: str) -> None:
    """Negative control: the game's own blueprints must survive the rule."""
    p = decode_fixture_to_placement(name)
    assert p.buildings, "fixture decoded to nothing"
    r = validate(p, only={"game.belt_crossing"})
    assert not r.by_check("game.belt_crossing"), [f.message for f in r.findings[:5]]
