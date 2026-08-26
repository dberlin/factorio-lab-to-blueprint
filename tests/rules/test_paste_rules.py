"""Positive and boundary controls for paste-only game predicates."""

from __future__ import annotations

from fractions import Fraction

from flab2bp.dsp import catalog, colliders, planet, rules


def test_paste_slope_uses_the_three_quarters_tangent() -> None:
    assert catalog.MAX_BELT_SLOPE == Fraction(3, 4)
    assert catalog.belt_slope_allowed(Fraction(3), Fraction(4), unlocked=False)
    assert not catalog.belt_slope_allowed(
        Fraction(3, 4) + Fraction(1, 10_000), 1, unlocked=False
    )
    assert catalog.belt_slope_allowed(10, 0, unlocked=True)


def test_blueprint_limit_is_selected_by_mass_construction_level() -> None:
    all_technologies = {f"mass-construction-{level}" for level in range(1, 6)}
    assert catalog.blueprint_limit_for_technologies(set(), all_technologies) == 0
    assert (
        catalog.blueprint_limit_for_technologies(
            {"mass-construction-1"}, all_technologies
        )
        == 150
    )
    assert (
        catalog.blueprint_limit_for_technologies(
            {"mass-construction-3"}, all_technologies
        )
        == 900
    )
    assert (
        catalog.blueprint_limit_for_technologies(
            {"mass-construction-4"}, all_technologies
        )
        == 3600
    )
    assert (
        catalog.blueprint_limit_for_technologies(
            {"mass-construction-5"}, all_technologies
        )
        is None
    )
    assert catalog.blueprint_limit_for_technologies(None, all_technologies) is None


def test_vertical_rules_keep_splitter_and_lab_boundaries_tech_aware() -> None:
    all_technologies = {"vertical-construction-1", "vertical-construction-2"}
    fresh = catalog.belt_rules_for_technologies(set(), all_technologies)
    upgraded = catalog.belt_rules_for_technologies(all_technologies, all_technologies)

    assert fresh.storage_level == 2
    assert fresh.lab_level == 3
    assert catalog.vertical_construction_allowed(
        catalog.SPLITTER_ID, Fraction(2), fresh
    )
    assert not catalog.vertical_construction_allowed(
        catalog.SPLITTER_ID, Fraction(3), fresh
    )
    assert catalog.vertical_construction_allowed(
        catalog.MATRIX_LAB_IDS[0], Fraction(7), fresh
    )
    assert not catalog.vertical_construction_allowed(
        catalog.MATRIX_LAB_IDS[0], Fraction(8), fresh
    )
    # A prefab carrying stackHeight but not one of the paste guard flags is not
    # accidentally treated as storage.
    assert catalog.vertical_construction_allowed(3009, Fraction(100), fresh)

    assert upgraded.storage_level == 4
    assert upgraded.lab_level == 5
    assert catalog.vertical_construction_allowed(
        catalog.SPLITTER_ID, Fraction(3), upgraded
    )


def test_stack_pitch_comes_from_the_catalog_data() -> None:
    assert catalog.building(catalog.SPLITTER_ID).stack_height == Fraction(8, 3)
    assert catalog.stack_pitch_z(catalog.SPLITTER_ID) == Fraction(2)
    assert catalog.stack_pitch_z(catalog.MATRIX_LAB_IDS[0]) == Fraction(3)


def test_belt_link_distance_and_coater_reshape_have_positive_controls() -> None:
    assert not rules.belt_link_too_far(rules.PASTE_BELT_LINK_MAX_SQR)
    assert rules.belt_link_too_far(rules.PASTE_BELT_LINK_MAX_SQR + 1e-9)
    assert rules.coater_reshape_allowed(
        rules.COATER_RESHAPE_MAX, -rules.COATER_RESHAPE_MAX
    )
    assert not rules.coater_reshape_allowed(
        rules.COATER_RESHAPE_MAX + 1e-9, 0.0
    )


def test_collider_latitude_lookup_delegates_to_the_exact_band_rule() -> None:
    step = planet.latitude_rad_per_grid(colliders.PLANET_SEGMENT)
    for row in range(-250, 251):
        assert colliders._longitude_segment_count(
            row * step, colliders.PLANET_SEGMENT
        ) == planet.longitude_segment_count(row, colliders.PLANET_SEGMENT)


def test_sorter_parameter_bias_is_part_of_the_parameter_projection() -> None:
    band = planet.bands()[0]
    projection = planet.Projection(
        band=band,
        anchor_row=0,
        segment=200,
        radius=200.0,
    )
    sorter = planet.Sorter(
        x=0,
        y=0,
        z=0,
        x2=2.6,
        y2=0,
        z2=0,
        yaw=90,
        yaw2=90,
        input_belt=False,
        output_belt=False,
        ref_x=1.3,
        ref_y=0,
        ref_z=0,
    )
    unbiased = planet.sorter_parameter(
        sorter, projection, bias={0: 0.0, 1: 0.0, 2: 0.0}
    )
    assert planet.sorter_parameter(sorter, projection) != unbiased
