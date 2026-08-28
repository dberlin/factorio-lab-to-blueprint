"""Pose-aware logical strip families and physical variants."""

from __future__ import annotations

from dataclasses import fields, replace
from fractions import Fraction

import pytest

from flab2bp.dsp import catalog
from flab2bp.layout import slots
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
    placement_geometry,
    split_strip_instance,
    validate_instance_partition,
    variants_for_count,
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
