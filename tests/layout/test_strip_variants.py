"""Pose-aware logical strip families and physical variants."""

from __future__ import annotations

from dataclasses import fields, replace
from fractions import Fraction

import pytest

from flab2bp.dsp import catalog
from flab2bp.layout import slots
from flab2bp.layout.base import PlacedBuilding, Placement
from flab2bp.layout.finalize import ProjectionFailure
from flab2bp.layout.freeform import plan_strips
from flab2bp.layout.strip_variants import (
    LogicalLane,
    StripFamily,
    StripFamilyId,
    StripInstance,
    StripVariant,
    _variants,
    default_strip_variant,
    generate_strip_families,
    lane_reach_profiles,
    merge_strip_instances,
    partition_strip_family,
    partition_strip_variant,
    placement_geometry,
    projection_pitch_requirement,
    split_strip_instance,
    strip_pose_id,
    validate_instance_partition,
    variants_for_count,
    variant_with_minimum_pitch,
)
from flab2bp.spec import BuildSpec, MachineGroup


def _group(
    recipe: str,
    machine: str,
    count: int,
    inputs: dict[str, Fraction],
    outputs: dict[str, Fraction],
) -> MachineGroup:
    return MachineGroup(
        recipe_id=recipe,
        machine_item_id=machine,
        count=count,
        inputs_per_machine=inputs,
        outputs_per_machine=outputs,
    )


def _single_machine_spec(
    machine: str,
    *,
    count: int = 1,
    inputs: tuple[str, ...] = ("feed",),
    outputs: tuple[str, ...] = ("product",),
) -> BuildSpec:
    one = Fraction(1)
    return BuildSpec(
        groups=(
            _group(
                f"{machine}-recipe",
                machine,
                count,
                {item: one for item in inputs},
                {item: one for item in outputs},
            ),
        ),
        external_inputs={item: count * one for item in inputs},
        outputs={item: count * one for item in outputs},
    )


def _family(spec: BuildSpec) -> StripFamily:
    families = generate_strip_families(spec)
    assert len(families) == 1
    return families[0]


def test_sequence_families_keep_same_group_feedback_destination(
    refined_oil_feedback_spec: BuildSpec,
) -> None:
    families = generate_strip_families(refined_oil_feedback_spec)
    feedback = [
        lane
        for family in families
        for lane in family.output_lanes
        if lane.items == ("refined-oil",)
        and family.group_key in lane.destination_group_keys
    ]
    assert feedback


def _at_yaw(family: StripFamily, yaw: float) -> tuple[StripVariant, ...]:
    return tuple(variant for variant in family.variants if variant.yaw == yaw)


def test_upright_refinery_variant_cannot_serve_required_north_lane() -> None:
    family = _family(_single_machine_spec("oil-refinery"))

    assert not _at_yaw(family, 0.0)


def test_rotated_refinery_variant_serves_both_lane_sides() -> None:
    family = _family(_single_machine_spec("oil-refinery"))
    rotated = _at_yaw(family, 90.0)

    assert rotated
    assert all(
        variant.footprint_width == 7 and variant.footprint_height == 3 for variant in rotated
    )
    assert all(
        {plan.lane.side for plan in variant.attachment_plan} == {"north", "south"}
        for variant in rotated
    )


def test_equal_footprints_can_require_different_machine_pitch() -> None:
    smelter = placement_geometry("arc-smelter", yaw=0.0)
    assembler = placement_geometry("assembling-machine-1", yaw=0.0)

    assert (smelter.footprint_width, assembler.footprint_width) == (3, 3)
    assert smelter.pitch_x == 3
    assert assembler.pitch_x == 4


def test_variant_with_minimum_pitch_regenerates_physical_identity() -> None:
    family = _family(_single_machine_spec("chemical-plant", count=2))
    ordinary = default_strip_variant(family)

    padded = variant_with_minimum_pitch(ordinary, ordinary.pitch_x + 1)

    assert padded.pitch_x == ordinary.pitch_x + 1
    assert padded.pitch_y == ordinary.pitch_y
    assert padded.footprint_width == ordinary.footprint_width
    assert padded.machine_origins_x == (0, padded.pitch_x)
    assert padded.box_width == 2 * padded.pitch_x
    assert padded.variant_id != ordinary.variant_id
    assert strip_pose_id(padded) == strip_pose_id(ordinary)
    assert padded.attachment_plan == ordinary.attachment_plan
    assert padded.lane_plan == ordinary.lane_plan


def test_variant_with_minimum_pitch_is_idempotent_at_or_below_current_pitch() -> None:
    ordinary = default_strip_variant(
        _family(_single_machine_spec("chemical-plant", count=2))
    )

    assert variant_with_minimum_pitch(ordinary, ordinary.pitch_x) is ordinary
    assert variant_with_minimum_pitch(ordinary, ordinary.pitch_x - 1) is ordinary


@pytest.mark.parametrize("required_pitch_x", [0, -1, True, 1.5])
def test_variant_with_minimum_pitch_rejects_non_positive_or_non_integer_requirements(
    required_pitch_x: object,
) -> None:
    ordinary = default_strip_variant(
        _family(_single_machine_spec("chemical-plant", count=2))
    )

    with pytest.raises(ValueError, match="positive integer"):
        variant_with_minimum_pitch(ordinary, required_pitch_x)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "control",
    [
        "different-owner-strips",
        "non-adjacent-machines",
        "different-item",
        "different-model",
        "different-yaw",
        "belts",
        "sorters",
        "towers",
        "missing-owner",
        "malformed-indices",
        "unequal-origin-separation",
        "missing-owner-table",
        "misaligned-owner-tables",
        "different-check",
    ],
)
def test_projection_pitch_requirement_rejects_unmapped_controls(control: str) -> None:
    family = _family(_single_machine_spec("chemical-plant", count=6))
    instances = partition_strip_family(family, max_machine_count=3)
    instance_ids = tuple(instance.instance_id for instance in instances)
    variants = tuple(instance.variant for instance in instances)
    ordinary = variants[0]
    machine_y = 11 + ordinary.lane_plan.machine_row
    buildings = [
        PlacedBuilding(
            item_id=2309,
            model_index=64,
            x=3 + origin,
            y=machine_y,
            width=ordinary.footprint_width,
            height=ordinary.footprint_height,
            yaw=ordinary.yaw,
            owner_strip=0,
        )
        for origin in ordinary.machine_origins_x
    ]
    failure = ProjectionFailure(
        "geom.collide",
        (0, 1),
        "build colliders intersect",
        160,
    )

    if control == "different-owner-strips":
        other = variants[1]
        buildings[1] = replace(
            buildings[1],
            x=40 + other.machine_origins_x[0],
            y=11 + other.lane_plan.machine_row,
            owner_strip=1,
        )
    elif control == "non-adjacent-machines":
        failure = replace(failure, buildings=(0, 2))
    elif control == "different-item":
        buildings[1] = replace(
            buildings[1],
            item_id=catalog.item_id("assembling-machine-1"),
        )
    elif control == "different-model":
        buildings[1] = replace(buildings[1], model_index=65)
    elif control == "different-yaw":
        buildings[1] = replace(buildings[1], yaw=(ordinary.yaw + 90.0) % 360.0)
    elif control in {"belts", "sorters", "towers"}:
        if control == "belts":
            item_id = min(catalog.BELT_IDS)
        elif control == "sorters":
            item_id = min(catalog.SORTER_IDS)
        else:
            item_id = catalog.TESLA_TOWER_ID
        model_index = catalog.building(item_id).model_index
        buildings[0] = replace(buildings[0], item_id=item_id, model_index=model_index)
        buildings[1] = replace(buildings[1], item_id=item_id, model_index=model_index)
    elif control == "missing-owner":
        buildings[1] = replace(buildings[1], owner_strip=None)
    elif control == "malformed-indices":
        failure = replace(failure, buildings=(0, len(buildings)))
    elif control == "unequal-origin-separation":
        buildings[1] = replace(buildings[1], x=buildings[1].x + 1)
    elif control == "missing-owner-table":
        buildings[0] = replace(buildings[0], owner_strip=2)
        buildings[1] = replace(buildings[1], owner_strip=2)
    elif control == "misaligned-owner-tables":
        variants = variants[:1]
    elif control == "different-check":
        failure = replace(failure, check="game.power_too_close")

    assert (
        projection_pitch_requirement(
            Placement(buildings=tuple(buildings)),
            instance_ids=instance_ids,
            variants=variants,
            failure=failure,
        )
        is None
    )


@pytest.mark.parametrize(
    "indices",
    [
        (),
        (0,),
        (0, 1, 2),
        (-1, 1),
        (0, 0),
        (True, 1),
        ("0", 1),
    ],
)
def test_projection_pitch_requirement_rejects_every_malformed_index_shape(
    indices: tuple[object, ...],
) -> None:
    family = _family(_single_machine_spec("chemical-plant", count=2))
    (instance,) = partition_strip_family(family, max_machine_count=2)
    ordinary = instance.variant
    placement = Placement(
        buildings=tuple(
            PlacedBuilding(
                item_id=2309,
                model_index=64,
                x=3 + origin,
                y=11 + ordinary.lane_plan.machine_row,
                width=ordinary.footprint_width,
                height=ordinary.footprint_height,
                yaw=ordinary.yaw,
                owner_strip=0,
            )
            for origin in ordinary.machine_origins_x
        )
    )

    assert (
        projection_pitch_requirement(
            placement,
            instance_ids=(instance.instance_id,),
            variants=(ordinary,),
            failure=ProjectionFailure(
                "geom.collide",
                indices,  # type: ignore[arg-type]
                "build colliders intersect",
                160,
            ),
        )
        is None
    )


def test_lane_profiles_exclude_collider_halo_rows() -> None:
    geometry = placement_geometry("assembling-machine-1", yaw=0.0)
    profiles = lane_reach_profiles("assembling-machine-1", yaw=0.0)

    excluded = range(
        -geometry.north_halo,
        geometry.footprint_height + geometry.south_halo,
    )
    assert geometry.footprint_height in excluded, "fixture needs a south collider halo"
    assert all(profile.lane_y not in excluded for profile in profiles)
    assert geometry.footprint_height + geometry.south_halo in {
        profile.lane_y for profile in profiles
    }


def test_variants_expand_one_pose_into_exact_alternative_seatings() -> None:
    family = _family(_single_machine_spec("assembling-machine-1"))
    upright = _at_yaw(family, 0.0)

    assert len(upright) > 1
    assert len({variant.lane_plan.lane_rows for variant in upright}) == len(upright)
    for variant in upright:
        geometry = variant.placement_geometry
        assert all(
            plan.lane_y < -geometry.north_halo
            or plan.lane_y >= geometry.footprint_height + geometry.south_halo
            for plan in variant.attachment_plan
        )


def test_shared_lane_items_receive_distinct_authoritative_columns() -> None:
    family = _family(
        _single_machine_spec(
            "chemical-plant",
            inputs=tuple(f"ingredient-{index}" for index in range(7)),
        )
    )
    shared = tuple(
        plan
        for variant in family.variants
        for plan in variant.attachment_plan
        if len(plan.lane.items) > 1
    )

    assert shared
    for plan in shared:
        assert len(plan.attachments) == len(plan.lane.items)
        assert len({attachment.column for attachment in plan.attachments}) == len(plan.attachments)


def test_multi_lane_assembler_uses_globally_unique_slots_deterministically() -> None:
    spec = _single_machine_spec(
        "assembling-machine-2",
        inputs=("iron-ingot", "copper-ingot"),
        outputs=("gear", "magnet"),
    )

    first = _family(spec)
    second = _family(spec)

    assert first == second
    assert first.variants
    for variant in first.variants:
        by_row = {
            profile.lane_y: profile
            for profile in lane_reach_profiles(first.machine_item_id, variant.yaw)
        }
        independent_first_choices = tuple(
            by_row[plan.lane_y].attachments[0][1].slot
            for plan in variant.attachment_plan
            for _item in plan.lane.items
        )
        assigned = tuple(
            attachment.slot for plan in variant.attachment_plan for attachment in plan.attachments
        )

        assert len(set(independent_first_choices)) < len(independent_first_choices)
        assert len(set(assigned)) == len(assigned)


def test_impossible_global_slot_matching_produces_no_variant() -> None:
    lanes = (
        LogicalLane("input:south:0", "input", ("a", "b"), (), "south", 0),
        LogicalLane("input:south:1", "input", ("c", "d"), (), "south", 1),
    )

    assert (
        _variants(
            StripFamilyId("impossible", 0),
            catalog.item_id("assembling-machine-2"),
            1,
            lanes,
            0.0,
        )
        == ()
    )


def test_machine_row_origins_advance_by_pitch_and_reserve_edge_halo() -> None:
    variant = default_strip_variant(_family(_single_machine_spec("assembling-machine-1", count=3)))

    assert variant.machine_origins_x == (0, 4, 8)
    assert variant.box_width >= 12
    envelopes = tuple(
        (
            origin - variant.placement_geometry.west_halo,
            origin + variant.footprint_width + variant.placement_geometry.east_halo,
        )
        for origin in variant.machine_origins_x
    )
    assert all(left[1] <= right[0] for left, right in zip(envelopes, envelopes[1:], strict=False))


def test_every_variant_attachment_is_exact_for_its_yaw_and_current_lane_row() -> None:
    family = _family(
        _single_machine_spec(
            "oil-refinery",
            inputs=("crude-oil",),
            outputs=("hydrogen", "refined-oil"),
        )
    )

    for variant in family.variants:
        probe = slots.probe_building(family.machine_item_id, variant.yaw)
        assert variant.lane_plan.machine_row >= 0
        assert variant.machine_origins_x == tuple(
            range(0, family.total_machine_count * variant.pitch_x, variant.pitch_x)
        )
        for plan in variant.attachment_plan:
            reachable = slots.attachable_columns(probe, plan.lane_y)
            assert len(plan.attachments) == len(plan.lane.items)
            assert len({attachment.column for attachment in plan.attachments}) == len(
                plan.attachments
            )
            for attachment in plan.attachments:
                exact = reachable[attachment.column]
                assert (exact.cell, exact.slot, exact.span) == (
                    attachment.cell,
                    attachment.slot,
                    attachment.span,
                )


def test_variant_generation_is_deduplicated_and_deterministic() -> None:
    spec = _single_machine_spec("assembling-machine-1", count=2)

    first = generate_strip_families(spec)
    second = generate_strip_families(spec)

    assert first == second
    for family in first:
        assert len({variant.variant_id for variant in family.variants}) == len(family.variants)
        sort_keys = [variant.sort_key for variant in family.variants]
        assert sort_keys == sorted(sort_keys)


def test_instance_ranges_must_partition_the_logical_family_exactly() -> None:
    family = _family(_single_machine_spec("arc-smelter", count=5))
    instances = partition_strip_family(family, max_machine_count=2)

    assert [(instance.machine_start, instance.machine_stop) for instance in instances] == [
        (0, 2),
        (2, 4),
        (4, 5),
    ]
    validate_instance_partition(family, instances)

    with pytest.raises(ValueError, match="partition"):
        validate_instance_partition(family, instances[1:])
    with pytest.raises(ValueError, match="partition"):
        validate_instance_partition(family, instances + (instances[-1],))


def test_partition_realizes_each_instance_variant_at_its_exact_machine_count() -> None:
    family = _family(_single_machine_spec("assembling-machine-1", count=3))
    template = default_strip_variant(family)
    first, second = partition_strip_family(family, max_machine_count=2)

    assert (first.machine_count, second.machine_count) == (2, 1)
    assert first.variant.machine_origins_x == (0, 4)
    assert first.variant.box_width == 8
    assert second.variant.machine_origins_x == (0,)
    assert second.variant.box_width == 4
    assert first.variant.template_key == second.variant.template_key == template.template_key

    per_machine = sum(len(plan.attachments) for plan in template.attachment_plan)
    for instance in (first, second):
        repeated = tuple(
            (
                machine_ordinal,
                plan.lane.lane_id,
                attachment.item,
                origin + attachment.cell[0],
                attachment.cell[1],
            )
            for machine_ordinal, origin in enumerate(
                instance.variant.machine_origins_x,
                start=instance.machine_start,
            )
            for plan in instance.variant.attachment_plan
            for attachment in plan.attachments
        )
        assert len(repeated) == instance.machine_count * per_machine
        assert {ordinal for ordinal, *_rest in repeated} == set(
            range(instance.machine_start, instance.machine_stop)
        )
    validate_instance_partition(family, (first, second))


def test_explicit_padded_variant_instance_partition_conserves_family_ranges() -> None:
    family = _family(_single_machine_spec("chemical-plant", count=5))
    ordinary = default_strip_variant(family)
    padded = variant_with_minimum_pitch(ordinary, ordinary.pitch_x + 1)

    instances = partition_strip_variant(
        family,
        padded,
        max_machine_count=2,
    )

    assert all(variant.variant_id != padded.variant_id for variant in family.variants)
    assert [
        (instance.machine_start, instance.machine_stop) for instance in instances
    ] == [(0, 2), (2, 4), (4, 5)]
    assert all(instance.family_id == family.family_id for instance in instances)
    assert all(instance.variant.pitch_x == padded.pitch_x for instance in instances)
    assert all(
        strip_pose_id(instance.variant) == strip_pose_id(ordinary)
        for instance in instances
    )
    assert tuple(
        machine_ordinal
        for instance in instances
        for machine_ordinal, _origin in enumerate(
            instance.variant.machine_origins_x,
            start=instance.machine_start,
        )
    ) == tuple(range(family.total_machine_count))
    validate_instance_partition(family, instances)

    with pytest.raises(ValueError, match="does not belong"):
        partition_strip_family(
            family,
            max_machine_count=2,
            variant_id=padded.variant_id,
        )


def test_contracted_same_pose_variant_is_rejected_by_partition_and_validation() -> None:
    generated_family = _family(_single_machine_spec("chemical-plant", count=2))
    contracted = default_strip_variant(generated_family)
    ordinary = variant_with_minimum_pitch(contracted, contracted.pitch_x + 1)
    family = replace(generated_family, variants=(ordinary,))

    assert contracted.pitch_x == 7
    assert ordinary.pitch_x == 8
    assert strip_pose_id(contracted) == strip_pose_id(ordinary)
    with pytest.raises(ValueError, match="below the ordinary family pose"):
        partition_strip_variant(
            family,
            contracted,
            max_machine_count=2,
        )

    (ordinary_instance,) = partition_strip_family(family, max_machine_count=2)
    with pytest.raises(ValueError, match="below the ordinary family pose"):
        validate_instance_partition(
            family,
            (replace(ordinary_instance, variant=contracted),),
        )



def test_realized_variant_order_and_geometry_are_stable_for_every_count() -> None:
    family = _family(_single_machine_spec("assembling-machine-1", count=7))
    template_keys = tuple(variant.template_key for variant in family.variants)

    for machine_count in range(1, family.total_machine_count + 1):
        variants = variants_for_count(family, machine_count)
        assert tuple(variant.template_key for variant in variants) == template_keys
        assert len({variant.variant_id for variant in variants}) == len(variants)
        assert all(
            variant.machine_origins_x
            == tuple(range(0, machine_count * variant.pitch_x, variant.pitch_x))
            and variant.box_width == machine_count * variant.pitch_x
            for variant in variants
        )

    for max_machine_count in range(1, family.total_machine_count + 1):
        instances = partition_strip_family(
            family,
            max_machine_count=max_machine_count,
        )
        validate_instance_partition(family, instances)
        assert sum(instance.machine_count for instance in instances) == 7
        assert all(
            len(instance.variant.machine_origins_x) == instance.machine_count
            and instance.variant.box_width == instance.machine_count * instance.variant.pitch_x
            for instance in instances
        )


def test_ranges_live_only_on_instances_and_variants_have_no_direct_targets() -> None:
    family_fields = {field.name for field in fields(StripFamily)}
    instance_fields = {field.name for field in fields(StripInstance)}
    variant = _family(_single_machine_spec("arc-smelter")).variants[0]
    variant_fields = {field.name for field in fields(type(variant))}

    assert {"machine_start", "machine_count"}.isdisjoint(family_fields)
    assert {"machine_start", "machine_count"} <= instance_fields
    assert "machine_count" not in variant_fields
    assert "direct_targets" not in variant_fields


def test_freeform_compatibility_selects_the_pose_default_deterministically() -> None:
    spec = _single_machine_spec("oil-refinery", count=3)
    family = _family(spec)
    default = default_strip_variant(family)

    first = plan_strips(spec, strip_len=2)
    second = plan_strips(spec, strip_len=2)

    assert first == second
    assert [strip.machines for strip in first] == [2, 1]
    assert all(strip.yaw == default.yaw for strip in first)
    assert all((strip.mw, strip.mh) == (7, 3) for strip in first)


@pytest.mark.parametrize("machine_count", range(1, 13))
def test_repeated_stage_boundary_splits_conserve_every_machine_and_lane(
    machine_count: int,
) -> None:
    family = _family(_single_machine_spec("assembling-machine-1", count=machine_count))
    instances = list(partition_strip_family(family, max_machine_count=machine_count))
    original_lane_ids = tuple(lane.lane_id for lane in family.input_lanes + family.output_lanes)

    while (
        parent_index := next(
            (index for index, instance in enumerate(instances) if instance.machine_count > 1),
            -1,
        )
    ) >= 0:
        parent = instances[parent_index]
        instances[parent_index : parent_index + 1] = split_strip_instance(
            family,
            parent,
        )
        validate_instance_partition(family, tuple(instances))

    ordinals = [
        ordinal
        for instance in instances
        for ordinal in range(instance.machine_start, instance.machine_stop)
    ]
    assert ordinals == list(range(machine_count))
    assert len(instances) <= machine_count
    assert sum(instance.machine_count for instance in instances) == machine_count
    assert all(
        tuple(plan.lane.lane_id for plan in instance.variant.attachment_plan) == original_lane_ids
        for instance in instances
    )

    while len(instances) > 1:
        merged = merge_strip_instances(family, instances[0], instances[1])
        assert merged is not None
        instances[:2] = [merged]
        validate_instance_partition(family, tuple(instances))

    assert (instances[0].machine_start, instances[0].machine_count) == (
        0,
        machine_count,
    )


def test_three_machine_split_is_two_plus_one_and_merge_is_its_exact_inverse() -> None:
    family = _family(_single_machine_spec("assembling-machine-1", count=3))
    (parent,) = partition_strip_family(family, max_machine_count=3)

    left, right = split_strip_instance(family, parent)

    assert (left.machine_start, left.machine_count) == (0, 2)
    assert (right.machine_start, right.machine_count) == (2, 1)
    assert merge_strip_instances(family, left, right) == parent


def test_merge_rejects_non_adjacent_or_pose_incompatible_ranges() -> None:
    family = _family(_single_machine_spec("assembling-machine-1", count=4))
    (parent,) = partition_strip_family(family, max_machine_count=4)
    left, right = split_strip_instance(family, parent)
    alternate = variants_for_count(family, right.machine_count)[1]
    incompatible = StripInstance(
        instance_id=right.instance_id,
        machine_start=right.machine_start,
        machine_count=right.machine_count,
        variant=alternate,
    )
    displaced = StripInstance(
        instance_id=replace(
            right.instance_id,
            machine_start=right.machine_start + 1,
        ),
        machine_start=right.machine_start + 1,
        machine_count=right.machine_count,
        variant=right.variant,
    )

    assert merge_strip_instances(family, left, incompatible) is None
    assert merge_strip_instances(family, left, displaced) is None
