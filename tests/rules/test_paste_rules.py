"""Positive and boundary controls for paste-only game predicates."""

from __future__ import annotations

from fractions import Fraction

from flab2bp.dsp import catalog, colliders, planet, registry, rules


def test_paste_slope_uses_the_three_quarters_tangent() -> None:
    all_technologies = {catalog.BELT_SLOPE_UNLOCK_TECH}
    locked = catalog.belt_rules_for_technologies(set(), all_technologies)
    unlocked = catalog.belt_rules_for_technologies(None, all_technologies)

    assert not locked.vertical_construction
    assert unlocked.vertical_construction
    assert catalog.belt_slope_allowed(3, 4, unlocked=locked.vertical_construction)
    assert not catalog.belt_slope_allowed(
        Fraction(7501, 10_000), 1, unlocked=locked.vertical_construction
    )
    assert catalog.belt_slope_allowed(10, 0, unlocked=unlocked.vertical_construction)


def test_blueprint_limit_is_selected_by_mass_construction_level() -> None:
    all_technologies = {f"mass-construction-{level}" for level in range(1, 6)}
    assert catalog.blueprint_limit_for_technologies(set(), all_technologies) == 0
    assert (
        catalog.blueprint_limit_for_technologies({"mass-construction-1"}, all_technologies) == 150
    )
    assert (
        catalog.blueprint_limit_for_technologies({"mass-construction-3"}, all_technologies) == 900
    )
    assert (
        catalog.blueprint_limit_for_technologies({"mass-construction-4"}, all_technologies) == 3600
    )
    assert (
        catalog.blueprint_limit_for_technologies({"mass-construction-5"}, all_technologies) is None
    )
    assert catalog.blueprint_limit_for_technologies(None, all_technologies) is None


def test_vertical_rules_keep_splitter_and_lab_boundaries_tech_aware() -> None:
    all_technologies = {
        catalog.BELT_SLOPE_UNLOCK_TECH,
        *(f"vertical-construction-{level}" for level in range(1, 7)),
    }
    fresh = catalog.belt_rules_for_technologies(set(), all_technologies)
    upgraded = catalog.belt_rules_for_technologies(all_technologies, all_technologies)
    implicit = catalog.belt_rules_for_technologies(None, all_technologies)

    assert fresh.from_url
    assert not fresh.vertical_construction
    assert fresh.storage_level == 2
    assert fresh.lab_level == 3
    assert catalog.vertical_construction_allowed(catalog.SPLITTER_ID, 2, fresh)
    assert not catalog.vertical_construction_allowed(catalog.SPLITTER_ID, 3, fresh)
    assert catalog.vertical_construction_allowed(catalog.MATRIX_LAB_IDS[0], 7, fresh)
    assert not catalog.vertical_construction_allowed(catalog.MATRIX_LAB_IDS[0], 8, fresh)
    # A prefab carrying stackHeight but not one of the paste guard flags is not
    # accidentally treated as storage.
    assert catalog.vertical_construction_allowed(3009, 100, fresh)

    assert upgraded.vertical_construction
    assert upgraded.storage_level == 8
    assert upgraded.lab_level == 9
    assert catalog.vertical_construction_allowed(catalog.SPLITTER_ID, 14, upgraded)
    assert not catalog.vertical_construction_allowed(catalog.SPLITTER_ID, 15, upgraded)
    assert catalog.vertical_construction_allowed(catalog.MATRIX_LAB_IDS[0], 25, upgraded)
    assert not catalog.vertical_construction_allowed(catalog.MATRIX_LAB_IDS[0], 26, upgraded)
    assert not implicit.from_url
    assert implicit == catalog.BeltAltitudeRules(
        max_z=upgraded.max_z,
        vertical_construction=True,
        storage_level=8,
        lab_level=9,
        from_url=False,
    )


def test_stack_pitch_comes_from_the_catalog_data() -> None:
    assert catalog.building(catalog.SPLITTER_ID).stack_height == Fraction(8, 3)
    assert catalog.stack_pitch_z(catalog.SPLITTER_ID) == Fraction(2)
    assert catalog.stack_pitch_z(catalog.MATRIX_LAB_IDS[0]) == Fraction(3)


def test_belt_link_distance_and_coater_reshape_have_positive_controls() -> None:
    assert not rules.belt_link_too_far(5.3)
    assert rules.belt_link_too_far(5.300_001)
    assert rules.coater_reshape_allowed(0.265, -0.265)
    assert not rules.coater_reshape_allowed(0.265_001, 0.0)


def test_belt_port_own_slots_match_game_authored_records() -> None:
    from dataclasses import replace

    from flab2bp.layout.base import Placement
    from flab2bp.layout.validate import validate
    from tests.layout.test_validate import docked, receiver

    drawing = replace(docked(3, 4, 0, 0), input_to_slot=1)
    feeding = replace(docked(3, 4, 0, 0, draws=False), output_from_slot=0)
    for belt in (drawing, feeding):
        report = validate(
            Placement(buildings=(receiver(0, 0), belt)),
            only={"belt.port_dock"},
        )
        assert not report.by_check("belt.port_dock")


def test_collider_latitude_lookup_delegates_to_the_exact_band_rule() -> None:
    step = planet.latitude_rad_per_grid(colliders.PLANET_SEGMENT)
    for row in range(-250, 251):
        assert colliders._longitude_segment_count(
            row * step, colliders.PLANET_SEGMENT
        ) == planet.longitude_segment_count(row, colliders.PLANET_SEGMENT)


def _projection() -> planet.Projection:
    return planet.Projection(
        band=planet.bands()[0],
        anchor_row=0,
        segment=colliders.PLANET_SEGMENT,
        radius=colliders.PLANET_RADIUS,
    )


def _sorter(**changes: float | bool) -> planet.Sorter:
    values: dict[str, float | bool] = {
        "x": 0.0,
        "y": 0.0,
        "z": 0.0,
        "x2": 0.0,
        "y2": 0.0,
        "z2": 0.0,
        "yaw": 0.0,
        "yaw2": 0.0,
        "input_belt": False,
        "output_belt": False,
        "ref_x": 0.0,
        "ref_y": 0.0,
        "ref_z": 0.0,
    }
    values.update(changes)
    return planet.Sorter(**values)  # type: ignore[arg-type]


def test_sorter_segment_ceiling_has_a_boundary_control() -> None:
    projection = _projection()
    assert planet.sorter_condition(_sorter(y2=4.0, ref_y=2.0), projection) == "TooFar"
    assert planet.sorter_condition(_sorter(y2=3.0, ref_y=1.5), projection) is None


def test_sorter_combined_floor_and_altitude_unit_have_boundary_controls() -> None:
    projection = _projection()
    flat = _sorter(y2=1.4, ref_y=0.7)
    lifted = _sorter(y2=1.4, z2=0.06, ref_y=0.7, ref_z=0.03)
    clear = _sorter(y2=1.5, ref_y=0.75)

    assert planet.sorter_condition(flat, projection) == "TooClose"
    assert planet.sorter_condition(lifted, projection) is None
    assert planet.sorter_condition(clear, projection) is None


def test_sorter_parameter_bias_is_part_of_the_parameter_projection() -> None:
    sorter = _sorter(
        x2=2.6,
        yaw=90.0,
        yaw2=90.0,
        ref_x=1.3,
    )
    projection = _projection()

    assert planet.sorter_parameter(sorter, projection) == 2
    assert planet.sorter_parameter(sorter, projection, bias={0: 0.0, 1: 0.0, 2: 0.0}) == 3


SORTER_CONTROLS = {
    "planet.SORTER_SEGMENTS_MAX": (test_sorter_segment_ceiling_has_a_boundary_control),
    "planet.SORTER_COMBINED_MIN": (
        test_sorter_combined_floor_and_altitude_unit_have_boundary_controls
    ),
    "planet.SORTER_ALTITUDE_UNIT": (
        test_sorter_combined_floor_and_altitude_unit_have_boundary_controls
    ),
    "planet.SORTER_PARAM_BIAS": (test_sorter_parameter_bias_is_part_of_the_parameter_projection),
    "planet.sorter_parameter": (test_sorter_parameter_bias_is_part_of_the_parameter_projection),
}


def test_all_five_sorter_rules_have_real_controls() -> None:
    declared = {
        entry.symbol
        for entry in registry.rules()
        if entry.symbol.startswith("planet.SORTER_") or entry.symbol == "planet.sorter_parameter"
    }
    assert declared == set(SORTER_CONTROLS)


# R4 imports only these independent numeric controls.  Interactive MatchInserter
# and turret rules are intentionally absent: emitted blueprints cannot reach
# them, and pretending a direct constant assertion is an emitted-paste witness
# would inflate the mutation number without defending behavior.
MUTATION_WITNESSES = {
    "catalog.MAX_BELT_SLOPE": (test_paste_slope_uses_the_three_quarters_tangent,),
    "catalog.DEFAULT_LAB_LEVEL": (test_vertical_rules_keep_splitter_and_lab_boundaries_tech_aware,),
    "rules.BELT_PORT_FEED_FROM_SLOT": (test_belt_port_own_slots_match_game_authored_records,),
    "rules.BELT_PORT_DRAW_TO_SLOT": (test_belt_port_own_slots_match_game_authored_records,),
    "catalog.belt_slope_allowed": (test_paste_slope_uses_the_three_quarters_tangent,),
    "catalog.blueprint_limit_for_technologies": (
        test_blueprint_limit_is_selected_by_mass_construction_level,
    ),
    "catalog.stack_pitch_z": (test_stack_pitch_comes_from_the_catalog_data,),
    "catalog.vertical_construction_allowed": (
        test_vertical_rules_keep_splitter_and_lab_boundaries_tech_aware,
    ),
    "planet.SORTER_SEGMENTS_MAX": (test_sorter_segment_ceiling_has_a_boundary_control,),
    "planet.SORTER_COMBINED_MIN": (
        test_sorter_combined_floor_and_altitude_unit_have_boundary_controls,
    ),
    "planet.SORTER_ALTITUDE_UNIT": (
        test_sorter_combined_floor_and_altitude_unit_have_boundary_controls,
    ),
    "rules.PASTE_BELT_LINK_MAX_SQR": (
        test_belt_link_distance_and_coater_reshape_have_positive_controls,
    ),
    "rules.belt_link_too_far": (test_belt_link_distance_and_coater_reshape_have_positive_controls,),
    "rules.COATER_RESHAPE_MAX": (
        test_belt_link_distance_and_coater_reshape_have_positive_controls,
    ),
    "rules.coater_reshape_allowed": (
        test_belt_link_distance_and_coater_reshape_have_positive_controls,
    ),
}
