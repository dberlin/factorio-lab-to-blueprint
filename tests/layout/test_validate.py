"""Tests for the layout validator.

Every check gets two tests: one minimal ``Placement`` that trips exactly that
check, and one that passes it.  A validator whose checks cannot fail is worse
than no validator at all, so the "trips it" half is the load-bearing one.
"""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import pytest

from flab2bp.dsp.catalog import GEOMETRY_SAFE_FIXTURES, TESLA_COVER_RADIUS
from flab2bp.dsp.catalog import building as catalog_building
from flab2bp.layout import junction
from flab2bp.layout.base import PlacedBuilding, Placement
from flab2bp.layout.validate import CHECKS, IdMap, Report, Severity, validate
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
    x: int, y: int, *, item_id: int = ASSEMBLER, recipe_id: int = 1, z: int = 0
) -> PlacedBuilding:
    b = catalog_building(item_id)
    return PlacedBuilding(
        item_id=item_id,
        model_index=b.model_index,
        x=x,
        y=y,
        z=z,
        width=b.width,
        height=b.height,
        recipe_id=recipe_id,
    )


def belt(
    x: int,
    y: int,
    z: int = 0,
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
        z=z,
        output_obj=out,
        input_obj=inp,
        carries_item=carries,
    )


def splitter(x: int, y: int, z: int = 0, *, carries: str | None = None) -> PlacedBuilding:
    return junction.make_splitter(x, y, z, carries_item=carries)


def sorter(
    x: int,
    y: int,
    x2: int,
    y2: int,
    *,
    inp: int | None = None,
    out: int | None = None,
    item_id: int = SORTER3,
    z: int = 0,
    z2: int = 0,
    filter_id: int = 0,
) -> PlacedBuilding:
    return PlacedBuilding(
        item_id=item_id,
        model_index=43,
        x=x,
        y=y,
        z=z,
        x2=x2,
        y2=y2,
        z2=z2,
        input_obj=inp,
        output_obj=out,
        filter_id=filter_id,
    )


def tower(x: int, y: int) -> PlacedBuilding:
    return PlacedBuilding(item_id=TOWER, model_index=44, x=x, y=y)


def place(*buildings: PlacedBuilding) -> Placement:
    return Placement(buildings=tuple(buildings))


def fired(report: Report, check: str) -> bool:
    return bool(report.by_check(check))


def errors(report: Report) -> list[str]:
    return [f.check for f in report.findings if f.severity is Severity.ERROR]


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


def test_geom_belt_single_occupancy_fires_on_two_belts_in_one_cell() -> None:
    r = validate(place(belt(0, 0), belt(0, 0)))
    assert fired(r, "geom.belt_single_occupancy")


def test_geom_machine_ground_fires_on_elevated_machine() -> None:
    m = machine(0, 0)
    elevated = PlacedBuilding(
        item_id=m.item_id, model_index=m.model_index, x=0, y=0, z=1, width=4, height=4, recipe_id=1
    )
    r = validate(place(elevated))
    assert fired(r, "geom.machine_ground")


def test_geom_machine_ground_clean_at_z_zero() -> None:
    assert not fired(validate(place(machine(0, 0))), "geom.machine_ground")


def test_geom_altitude_range_fires_above_max_stack() -> None:
    r = validate(place(belt(0, 0, 9)))
    assert fired(r, "geom.altitude_range")


def test_geom_altitude_step_fires_on_two_level_jump() -> None:
    # belt 0 at z=0 links to belt 1 at z=2 -- a vertical teleport
    r = validate(place(belt(0, 0, 0, out=1), belt(1, 0, 2)))
    assert fired(r, "geom.altitude_step")


def test_geom_altitude_step_clean_on_single_level_ramp() -> None:
    r = validate(place(belt(0, 0, 0, out=1), belt(1, 0, 1)))
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
    # a Chemical Plant (9x5) rather than a 3x3 assembler -- at 3x3 the two
    # readings barely differ and the test would pass without discriminating.
    #
    # Tower centre (0.5, 0.5), radius 10.5.  Plant at (2,2) spans x 2..10,
    # y 2..6, so its centre is (6.5, 4.5) at distance 7.21 -- comfortably
    # inside -- while its far tile centre (10.5, 6.5) is 11.66 away, outside.
    # A centre-only check would pass this and leave the far end dark.
    r = validate(place(tower(0, 0), machine(2, 2, item_id=CHEM_PLANT)))
    assert fired(r, "power.coverage")


def test_power_coverage_centre_only_would_not_catch_that_case() -> None:
    """Guards the guard: the case above must actually distinguish the two rules.

    If the geometry ever drifts so the plant's centre also falls outside the
    radius, the test above would still pass -- but for the wrong reason, and it
    would no longer be testing what it claims to.
    """
    plant = machine(2, 2, item_id=CHEM_PLANT)
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
                z=round(b.z * 2),
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
