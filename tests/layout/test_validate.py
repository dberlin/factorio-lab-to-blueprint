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
from flab2bp.layout.base import PlacedBuilding, Placement
from flab2bp.layout.validate import CHECKS, IdMap, Report, Severity, validate
from flab2bp.spec import BuildSpec, MachineGroup, ProliferatorMode

ASSEMBLER = 2304  # Assembling Machine Mk.II, 4x4
SMELTER = 2302  # Arc Smelter, 3x3
BELT2 = 2002  # Conveyor Belt Mk.II, 12/s
SORTER3 = 2013  # Sorter Mk.III, 6/s at one tile
SORTER1 = 2011  # Sorter Mk.I, 1.5/s at one tile
TOWER = 2201  # Tesla Tower, cover radius 10.5
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
    item_id: int = BELT2,
) -> PlacedBuilding:
    return PlacedBuilding(item_id=item_id, model_index=36, x=x, y=y, z=z, output_obj=out)


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
