"""Pose-aware logical strip families and physical variants."""

from __future__ import annotations

from dataclasses import fields
from fractions import Fraction

import pytest

from flab2bp.layout import slots
from flab2bp.layout.freeform import plan_strips
from flab2bp.layout.strip_variants import (
    StripFamily,
    StripInstance,
    StripVariant,
    default_strip_variant,
    generate_strip_families,
    partition_strip_family,
    placement_geometry,
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
        variant.footprint_width == 7 and variant.footprint_height == 3
        for variant in rotated
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


def test_machine_row_origins_advance_by_pitch_and_reserve_edge_halo() -> None:
    variant = default_strip_variant(
        _family(_single_machine_spec("assembling-machine-1", count=3))
    )

    assert variant.machine_origins_x == (0, 4, 8)
    assert variant.box_width >= 12
    envelopes = tuple(
        (
            origin - variant.placement_geometry.west_halo,
            origin
            + variant.footprint_width
            + variant.placement_geometry.east_halo,
        )
        for origin in variant.machine_origins_x
    )
    assert all(
        left[1] <= right[0]
        for left, right in zip(envelopes, envelopes[1:], strict=False)
    )


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
        assert len({variant.variant_id for variant in family.variants}) == len(
            family.variants
        )
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
            and instance.variant.box_width
            == instance.machine_count * instance.variant.pitch_x
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
