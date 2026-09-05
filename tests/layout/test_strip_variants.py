"""Pose-aware logical strip families and physical variants."""

from __future__ import annotations

import random
from collections.abc import Iterator
from dataclasses import fields, replace
from fractions import Fraction
from itertools import combinations_with_replacement
from typing import ClassVar

import pytest

import flab2bp.layout.strip_variants as strip_variants_module
from flab2bp.dsp import catalog
from flab2bp.layout import freeform, slots
from flab2bp.layout.base import NoValidLayout, PlacedBuilding, Placement
from flab2bp.layout.finalize import ProjectionFailure
from flab2bp.layout.freeform import plan_strips
from flab2bp.layout.strip_variants import (
    CargoDomain,
    LogicalLane,
    ProjectionPitchRequirement,
    StripFamily,
    StripFamilyId,
    StripInstance,
    StripInstanceId,
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
    variant_with_minimum_pitch,
    variants_for_count,
)
from flab2bp.rates.candidates import CandidatePolicy
from flab2bp.spec import BuildSpec, MachineGroup, ProliferatorMode


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


def _rated_spec(rate: Fraction, *, count: int = 8, capacity: Fraction = Fraction(30)) -> BuildSpec:
    """One collider-like group drawing ``rate`` of hydrogen per machine."""
    return BuildSpec(
        groups=(
            MachineGroup(
                recipe_id="deuterium",
                machine_item_id="miniature-particle-collider",
                count=count,
                inputs_per_machine={"hydrogen": rate},
                outputs_per_machine={"deuterium": Fraction(1, 2)},
            ),
        ),
        external_inputs={"hydrogen": rate * count},
        outputs={"deuterium": Fraction(count, 2)},
        belt_item_id="conveyor-belt-3",
        belt_items_per_second=capacity,
    )


def _both_fed_hydrogen_spec() -> BuildSpec:
    """`universe-matrix*90` in miniature: hydrogen is belted in AND produced.

    Group ORDER is load-bearing -- `freeform._adapt` keys a group
    ``f"{recipe_id}#{index}"`` -- so `casimir-crystal` sits at index 1 and
    `deuterium` at index 2, and those are the destination keys the shared
    hydrogen lane carries.
    """
    return BuildSpec(
        groups=(
            MachineGroup(
                recipe_id="mass-energy-storage",
                machine_item_id="miniature-particle-collider",
                count=2,
                inputs_per_machine={"critical-photon": Fraction(3, 4)},
                outputs_per_machine={
                    "hydrogen": Fraction(3, 4),
                    "antimatter": Fraction(3, 4),
                },
            ),
            MachineGroup(
                recipe_id="casimir-crystal",
                machine_item_id="assembling-machine-1",
                count=4,
                inputs_per_machine={"hydrogen": Fraction(9, 2)},
                outputs_per_machine={"casimir-crystal": Fraction(1)},
            ),
            MachineGroup(
                recipe_id="deuterium",
                machine_item_id="miniature-particle-collider",
                count=4,
                inputs_per_machine={"hydrogen": Fraction(15, 4)},
                outputs_per_machine={"deuterium": Fraction(1, 2)},
            ),
            MachineGroup(
                recipe_id="energy-matrix",
                machine_item_id="assembling-machine-1",
                count=1,
                inputs_per_machine={"hydrogen": Fraction(3)},
                outputs_per_machine={"energy-matrix": Fraction(1)},
            ),
        ),
        external_inputs={
            "hydrogen": Fraction(33),
            "critical-photon": Fraction(3, 2),
        },
        outputs={
            "antimatter": Fraction(3, 2),
            "casimir-crystal": Fraction(4),
            "deuterium": Fraction(2),
            "energy-matrix": Fraction(1),
        },
        belt_item_id="conveyor-belt-3",
        belt_items_per_second=Fraction(30),
    )


def test_a_both_fed_product_whose_consumers_draw_more_than_a_belt_still_plans() -> None:
    """mass-energy-storage: 2 machines emit 0.75/s hydrogen each into three
    consumers whose combined draw (18 + 15 + 3 = 36/s) is served mostly by a
    33/s bus entry.  The producer's shared hydrogen lane carries 1.5/s and
    must plan; before 2026-09-05 it was refused for "carrying" 33/s.

    The hydrogen ledger is deliberately left 1.5/s short of the draw (33 on the
    bus plus 1.5 produced against 36 consumed): `BuildSpec` checks that every
    consumed item is SUPPLIED by something, not that the rates balance, and
    rounding the bus entry up to 34.5 would hide the very number -- 33 -- the
    old verdict quoted.
    """
    spec = _both_fed_hydrogen_spec()
    families = generate_strip_families(spec)
    mes = [family for family in families if family.recipe_id == "mass-energy-storage"]
    assert mes, [family.recipe_id for family in families]
    hydrogen_lanes = [
        lane for family in mes for lane in family.output_lanes if lane.items == ("hydrogen",)
    ]
    assert hydrogen_lanes
    destinations = {key for lane in hydrogen_lanes for key in lane.destination_group_keys}
    assert {"casimir-crystal#1", "deuterium#2"} <= destinations


def test_machine_cap_is_the_floor_of_capacity_over_the_largest_single_item_rate() -> None:
    (family,) = generate_strip_families(_rated_spec(Fraction(4)))
    assert family.machine_cap == 7  # floor(30 / 4)


def test_machine_cap_uses_the_fastest_allowed_belt() -> None:
    (family,) = generate_strip_families(_rated_spec(Fraction(4), capacity=Fraction(12)))
    assert family.machine_cap == 3  # floor(12 / 4)


def test_machine_cap_is_at_least_one_and_a_literal_family_defaults_to_uncapped() -> None:
    (family,) = generate_strip_families(_rated_spec(Fraction(29)))
    assert family.machine_cap == 1
    # `_family(...)` goes through `generate_strip_families`, so it is always
    # capped (the module's default spec gives 6 at 6/s and 1 per machine);
    # only a literal `StripFamily(...)` keeps the 0 default.
    generated = _family(_single_machine_spec("assembling-machine-1", count=3))
    assert generated.machine_cap == 6
    assert replace(generated, machine_cap=0).machine_cap == 0


def test_a_single_machine_over_the_ceiling_is_refused_early_with_the_rate() -> None:
    with pytest.raises(NoValidLayout, match=r"31.*hydrogen.*30"):
        generate_strip_families(_rated_spec(Fraction(31)))


def test_an_unplannable_shard_is_a_refusal_not_a_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    """`_logical_strip_plans` speaks ValueError; every caller of
    `generate_strip_families` speaks NoValidLayout.  The boundary is here."""

    def unplannable(*_args: object, **_kwargs: object) -> tuple[()]:
        raise ValueError("hydrogen: destinations ['a', 'b'] have to share one output lane")

    monkeypatch.setattr(strip_variants_module, "_logical_strip_plans", unplannable)
    with pytest.raises(NoValidLayout, match=r"cannot be planned into strips.*hydrogen") as caught:
        generate_strip_families(_rated_spec(Fraction(4)))
    assert caught.value.spec_label == _rated_spec(Fraction(4)).label
    assert isinstance(caught.value.__cause__, ValueError)


def test_sequence_families_keep_same_group_feedback_destination(
    refined_oil_feedback_spec: BuildSpec,
) -> None:
    families = generate_strip_families(refined_oil_feedback_spec)
    feedback = [
        lane
        for family in families
        for lane in family.output_lanes
        if lane.items == ("refined-oil",) and family.group_key in lane.destination_group_keys
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


@pytest.mark.parametrize(
    ("machine", "count", "expected_pitch"),
    (("chemical-plant", 2, 8), ("matrix-lab", 3, 6)),
)
def test_repeated_machine_variants_reserve_projection_safe_pitch(
    machine: str,
    count: int,
    expected_pitch: int,
) -> None:
    family = _family(_single_machine_spec(machine, count=count))

    assert family.variants
    assert {variant.pitch_x for variant in family.variants} == {expected_pitch}
    assert all(
        variant.machine_origins_x == tuple(range(0, count * expected_pitch, expected_pitch))
        and variant.box_width == count * expected_pitch
        for variant in family.variants
    )


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
    ordinary = default_strip_variant(_family(_single_machine_spec("chemical-plant", count=2)))

    assert variant_with_minimum_pitch(ordinary, ordinary.pitch_x) is ordinary
    assert variant_with_minimum_pitch(ordinary, ordinary.pitch_x - 1) is ordinary


@pytest.mark.parametrize("required_pitch_x", [0, -1, True, 1.5])
def test_variant_with_minimum_pitch_rejects_non_positive_or_non_integer_requirements(
    required_pitch_x: object,
) -> None:
    ordinary = default_strip_variant(_family(_single_machine_spec("chemical-plant", count=2)))

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


def _brute_force_projection_origin_ordinals(
    local_origins_x: tuple[int, ...],
    owned_positions: set[tuple[int, int]],
    *,
    anchor: tuple[int, int],
    machine_row: int,
) -> dict[tuple[int, int], int] | None:
    """Quadratic pre-optimization matcher retained only as a parity oracle."""
    if len(owned_positions) != len(local_origins_x):
        return None
    for local_x in local_origins_x:
        box_x = anchor[0] - local_x
        box_y = anchor[1] - machine_row
        expected = {(box_x + origin_x, box_y + machine_row) for origin_x in local_origins_x}
        if expected == owned_positions:
            return {
                (box_x + origin_x, box_y + machine_row): ordinal
                for ordinal, origin_x in enumerate(local_origins_x)
            }
    return None


def _projection_machine(
    variant: StripVariant,
    *,
    x: int,
    y: int,
    owner: int = 0,
    machine: str = "chemical-plant",
) -> PlacedBuilding:
    item_id = catalog.item_id(machine)
    return PlacedBuilding(
        item_id=item_id,
        model_index=catalog.building(item_id).model_index,
        x=x,
        y=y,
        width=variant.footprint_width,
        height=variant.footprint_height,
        yaw=variant.yaw,
        owner_strip=owner,
    )


@pytest.mark.parametrize(
    ("machine", "yaw"),
    [("chemical-plant", 0.0), ("oil-refinery", 90.0)],
)
@pytest.mark.parametrize("machine_count", [2, 3, 4])
def test_projection_pitch_requirement_matches_brute_force_origin_oracle_exhaustively(
    machine: str,
    yaw: float,
    machine_count: int,
) -> None:
    family = _family(_single_machine_spec(machine, count=machine_count))
    variant = _at_yaw(family, yaw)[0]
    (instance,) = partition_strip_family(
        family,
        max_machine_count=machine_count,
        variant_id=variant.variant_id,
    )
    base_x = 13
    machine_y = 17 + variant.lane_plan.machine_row
    candidates = tuple(
        (base_x + offset * variant.pitch_x, machine_y + row_offset)
        for offset in range(-1, machine_count + 1)
        for row_offset in (0, 1)
    )
    checked = 0
    equivalent = 0

    for positions in combinations_with_replacement(candidates, machine_count):
        placement = Placement(
            buildings=tuple(
                _projection_machine(variant, x=x, y=y, machine=machine) for x, y in positions
            )
        )
        owned_positions = set(positions)
        for left_index in range(machine_count):
            for right_index in range(machine_count):
                if left_index == right_index:
                    continue
                failure = ProjectionFailure(
                    "geom.collide",
                    (left_index, right_index),
                    "build colliders intersect",
                    160,
                )
                left_position = positions[left_index]
                right_position = positions[right_index]
                ordinals = _brute_force_projection_origin_ordinals(
                    variant.machine_origins_x,
                    owned_positions,
                    anchor=left_position,
                    machine_row=variant.lane_plan.machine_row,
                )
                oracle_matches = (
                    ordinals is not None
                    and abs(left_position[0] - right_position[0]) == variant.pitch_x
                    and left_position in ordinals
                    and right_position in ordinals
                    and abs(ordinals[left_position] - ordinals[right_position]) == 1
                )

                requirement = projection_pitch_requirement(
                    placement,
                    instance_ids=(instance.instance_id,),
                    variants=(variant,),
                    failure=failure,
                )

                assert (requirement is not None) is oracle_matches
                if requirement is not None:
                    equivalent += 1
                    assert requirement.rejected_pitch == variant.pitch_x
                    assert requirement.required_pitch == variant.pitch_x + 1
                checked += 1

    assert checked == {2: 72, 3: 1_320, 4: 16_380}[machine_count]
    assert equivalent > 0


@pytest.mark.parametrize(
    ("machine_count", "origin_ordinals", "failure_indices"),
    [
        pytest.param(1, (), (0, 1), id="empty"),
        pytest.param(1, (0,), (0, 0), id="singleton"),
        pytest.param(2, (0, 0), (0, 1), id="duplicate"),
    ],
)
def test_projection_pitch_requirement_rejects_degenerate_origin_collections(
    machine_count: int,
    origin_ordinals: tuple[int, ...],
    failure_indices: tuple[int, int],
) -> None:
    family = _family(_single_machine_spec("chemical-plant", count=machine_count))
    variant = default_strip_variant(family)
    (instance,) = partition_strip_family(family, max_machine_count=machine_count)
    machine_y = 17 + variant.lane_plan.machine_row
    placement = Placement(
        buildings=tuple(
            _projection_machine(
                variant,
                x=13 + ordinal * variant.pitch_x,
                y=machine_y,
            )
            for ordinal in origin_ordinals
        )
    )

    assert (
        projection_pitch_requirement(
            placement,
            instance_ids=(instance.instance_id,),
            variants=(variant,),
            failure=ProjectionFailure(
                "geom.collide",
                failure_indices,
                "build colliders intersect",
                160,
            ),
        )
        is None
    )


def test_projection_pitch_requirement_maps_exact_rotated_shard() -> None:
    family = _family(_single_machine_spec("oil-refinery", count=4))
    rotated = _at_yaw(family, 90.0)[0]
    instances = partition_strip_family(
        family,
        max_machine_count=2,
        variant_id=rotated.variant_id,
    )
    buildings: list[PlacedBuilding] = []
    for owner, instance in enumerate(instances):
        machine_y = 20 + owner * 10 + instance.variant.lane_plan.machine_row
        buildings.extend(
            _projection_machine(
                instance.variant,
                x=30 + owner * 20 + origin_x,
                y=machine_y,
                owner=owner,
                machine="oil-refinery",
            )
            for origin_x in instance.variant.machine_origins_x
        )
    failure = ProjectionFailure(
        "geom.collide",
        (2, 3),
        "build colliders intersect",
        160,
    )

    requirement = projection_pitch_requirement(
        Placement(buildings=tuple(buildings)),
        instance_ids=tuple(instance.instance_id for instance in instances),
        variants=tuple(instance.variant for instance in instances),
        failure=failure,
    )

    assert requirement == ProjectionPitchRequirement(
        family_id=instances[1].family_id,
        instance_id=instances[1].instance_id,
        variant_id=instances[1].variant_id,
        axis="x",
        rejected_pitch=instances[1].variant.pitch_x,
        required_pitch=instances[1].variant.pitch_x + 1,
        failure=failure,
    )


class _OriginArithmeticCounter(int):
    operations: ClassVar[int] = 0

    def __add__(self, other: int) -> _OriginArithmeticCounter:
        type(self).operations += 1
        return type(self)(int(self) + int(other))

    def __sub__(self, other: int) -> _OriginArithmeticCounter:
        type(self).operations += 1
        return type(self)(int(self) - int(other))

    def __hash__(self) -> int:
        type(self).operations += 1
        return int.__hash__(self)

    def __eq__(self, other: object) -> bool:
        type(self).operations += 1
        return int(self) == other

    def __lt__(self, other: int) -> bool:
        type(self).operations += 1
        return int(self) < int(other)


def _adversarial_projection_fixture(
    machine_count: int,
) -> tuple[StripInstance, tuple[tuple[_OriginArithmeticCounter, int], ...]]:
    # This is about projection-pitch arithmetic growth, not capacity: lift
    # the family's machine cap so one big adversarial strip still forms.
    family = replace(
        _family(_single_machine_spec("chemical-plant", count=machine_count)),
        machine_cap=0,
    )
    (instance,) = partition_strip_family(family, max_machine_count=machine_count)
    variant = instance.variant
    adversarial_origins = (
        *variant.machine_origins_x[:-1],
        variant.machine_origins_x[-1] + variant.pitch_x,
    )
    machine_y = 17 + variant.lane_plan.machine_row
    positions = tuple(
        (_OriginArithmeticCounter(13 + origin_x), machine_y) for origin_x in adversarial_origins
    )
    return instance, positions


def _adversarial_projection_origin_operations(machine_count: int) -> int:
    instance, positions = _adversarial_projection_fixture(machine_count)
    variant = instance.variant
    placement = Placement(
        buildings=tuple(_projection_machine(variant, x=x, y=y) for x, y in positions)
    )
    failure = ProjectionFailure(
        "geom.collide",
        (0, 1),
        "build colliders intersect",
        160,
    )
    _OriginArithmeticCounter.operations = 0

    requirement = projection_pitch_requirement(
        placement,
        instance_ids=(instance.instance_id,),
        variants=(variant,),
        failure=failure,
    )

    assert requirement is None
    return _OriginArithmeticCounter.operations


def _adversarial_brute_force_origin_operations(machine_count: int) -> int:
    instance, positions = _adversarial_projection_fixture(machine_count)
    variant = instance.variant
    _OriginArithmeticCounter.operations = 0
    ordinals = _brute_force_projection_origin_ordinals(
        variant.machine_origins_x,
        set(positions),
        anchor=positions[0],
        machine_row=variant.lane_plan.machine_row,
    )

    assert ordinals is None
    return _OriginArithmeticCounter.operations


def test_projection_pitch_origin_matching_has_linear_structural_growth() -> None:
    small_count = _adversarial_projection_origin_operations(32)
    large_count = _adversarial_projection_origin_operations(128)
    brute_small_count = _adversarial_brute_force_origin_operations(32)
    brute_large_count = _adversarial_brute_force_origin_operations(128)

    assert large_count <= small_count * 5
    assert large_count <= 128 * 10
    assert brute_large_count >= brute_small_count * 12
    assert brute_large_count >= 2 * 128**2


class _VariantScanCounter(tuple[StripVariant, ...]):
    scans: ClassVar[int] = 0

    def __iter__(self) -> Iterator[StripVariant]:
        for variant in super().__iter__():
            type(self).scans += 1
            yield variant


def _batch_projection_requirements(
    placement: Placement,
    instance_ids: tuple[StripInstanceId, ...],
    variants: tuple[StripVariant, ...],
    failures: tuple[ProjectionFailure, ...],
) -> tuple[ProjectionPitchRequirement | None, ...]:
    return strip_variants_module.projection_pitch_requirements(
        placement,
        instance_ids=instance_ids,
        variants=variants,
        failures=failures,
    )


def _projection_batch_scan_counts(
    monkeypatch: pytest.MonkeyPatch,
    *,
    failure_count: int,
) -> tuple[int, int, int, int]:
    family = _family(_single_machine_spec("chemical-plant", count=32))
    instances = partition_strip_family(family, max_machine_count=2)
    variants = _VariantScanCounter(instance.variant for instance in instances)
    buildings = tuple(
        _projection_machine(
            instance.variant,
            x=13 + owner * 30 + origin_x,
            y=17 + owner * 10 + instance.variant.lane_plan.machine_row,
            owner=owner,
        )
        for owner, instance in enumerate(instances)
        for origin_x in instance.variant.machine_origins_x
    )
    failures = tuple(
        ProjectionFailure(
            "geom.collide",
            (index % 2, 1 - index % 2),
            "build colliders intersect",
            160,
        )
        for index in range(failure_count)
    )
    machine_checks = 0
    original_is_machine = strip_variants_module._is_machine_building

    def count_machine(building: PlacedBuilding) -> bool:
        nonlocal machine_checks
        machine_checks += 1
        return original_is_machine(building)

    monkeypatch.setattr(
        strip_variants_module,
        "_is_machine_building",
        count_machine,
    )
    _VariantScanCounter.scans = 0
    requirements = _batch_projection_requirements(
        Placement(buildings=buildings),
        tuple(instance.instance_id for instance in instances),
        variants,
        failures,
    )

    assert tuple(requirement.failure for requirement in requirements if requirement) == failures
    return len(instances), len(buildings), _VariantScanCounter.scans, machine_checks


def test_projection_failure_batch_indexes_variants_and_buildings_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    small = _projection_batch_scan_counts(monkeypatch, failure_count=8)
    large = _projection_batch_scan_counts(monkeypatch, failure_count=16)

    small_strips, small_buildings, small_variant_scans, small_machine_checks = small
    large_strips, large_buildings, large_variant_scans, large_machine_checks = large
    assert (small_strips, small_buildings) == (large_strips, large_buildings)
    assert (small_variant_scans, large_variant_scans) == (
        small_strips,
        large_strips,
    )
    assert (small_machine_checks, large_machine_checks) == (
        small_buildings,
        large_buildings,
    )


def test_projection_failure_batch_preserves_duplicate_reversed_and_unrelated_order() -> None:
    family = _family(_single_machine_spec("chemical-plant", count=4))
    instances = partition_strip_family(family, max_machine_count=2)
    buildings = tuple(
        _projection_machine(
            instance.variant,
            x=13 + owner * 30 + origin_x,
            y=17 + owner * 10 + instance.variant.lane_plan.machine_row,
            owner=owner,
        )
        for owner, instance in enumerate(instances)
        for origin_x in instance.variant.machine_origins_x
    )
    forward = ProjectionFailure(
        "geom.collide",
        (0, 1),
        "build colliders intersect",
        160,
    )
    duplicate = replace(forward)
    reversed_pair = replace(forward, buildings=(1, 0))
    cross_strip = replace(forward, buildings=(1, 2))
    unrelated = replace(forward, check="game.power_too_close")
    other_strip = replace(forward, buildings=(2, 3))
    failures = (
        forward,
        duplicate,
        reversed_pair,
        cross_strip,
        unrelated,
        other_strip,
    )

    requirements = _batch_projection_requirements(
        Placement(buildings=buildings),
        tuple(instance.instance_id for instance in instances),
        tuple(instance.variant for instance in instances),
        failures,
    )

    assert tuple(
        None
        if requirement is None
        else (
            requirement.instance_id,
            requirement.variant_id,
            requirement.failure,
        )
        for requirement in requirements
    ) == (
        (instances[0].instance_id, instances[0].variant_id, forward),
        (instances[0].instance_id, instances[0].variant_id, duplicate),
        (instances[0].instance_id, instances[0].variant_id, reversed_pair),
        None,
        None,
        (instances[1].instance_id, instances[1].variant_id, other_strip),
    )


def test_projection_failure_batch_matches_randomized_small_scanning_oracle() -> None:
    rng = random.Random(0xF1AB2)
    for machine_count in range(2, 6):
        family = _family(_single_machine_spec("chemical-plant", count=machine_count))
        variant = default_strip_variant(family)
        (instance,) = partition_strip_family(
            family,
            max_machine_count=machine_count,
        )
        candidates = tuple(
            (
                13 + offset * variant.pitch_x,
                17 + row_offset + variant.lane_plan.machine_row,
            )
            for offset in range(-1, machine_count + 1)
            for row_offset in (0, 1)
        )
        for _case in range(32):
            positions = tuple(rng.choice(candidates) for _ in range(machine_count))
            placement = Placement(
                buildings=tuple(_projection_machine(variant, x=x, y=y) for x, y in positions)
            )
            pairs = tuple(
                (rng.randrange(machine_count), rng.randrange(machine_count)) for _ in range(8)
            )
            first = ProjectionFailure(
                "geom.collide",
                pairs[0],
                "build colliders intersect",
                160,
            )
            failures = (
                first,
                replace(first),
                replace(first, buildings=tuple(reversed(pairs[0]))),
                replace(first, check="game.power_too_close"),
                *(replace(first, buildings=pair) for pair in pairs[1:]),
            )
            owned_positions = set(positions)
            expected: list[ProjectionPitchRequirement | None] = []
            for failure in failures:
                indices = failure.buildings
                ordinals = (
                    _brute_force_projection_origin_ordinals(
                        variant.machine_origins_x,
                        owned_positions,
                        anchor=positions[indices[0]],
                        machine_row=variant.lane_plan.machine_row,
                    )
                    if failure.check == "geom.collide"
                    and len(indices) == 2
                    and indices[0] != indices[1]
                    else None
                )
                matches = (
                    ordinals is not None
                    and abs(positions[indices[0]][0] - positions[indices[1]][0]) == variant.pitch_x
                    and positions[indices[0]] in ordinals
                    and positions[indices[1]] in ordinals
                    and abs(ordinals[positions[indices[0]]] - ordinals[positions[indices[1]]]) == 1
                )
                expected.append(
                    ProjectionPitchRequirement(
                        family_id=instance.family_id,
                        instance_id=instance.instance_id,
                        variant_id=variant.variant_id,
                        axis="x",
                        rejected_pitch=variant.pitch_x,
                        required_pitch=variant.pitch_x + 1,
                        failure=failure,
                    )
                    if matches
                    else None
                )

            assert _batch_projection_requirements(
                placement,
                (instance.instance_id,),
                (variant,),
                failures,
            ) == tuple(expected)


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


def test_collider_coproduct_domains_use_both_faces_with_exact_unique_slots() -> None:
    """One machine may drain distinct cargo domains across both reachable faces.

    ``mass-energy-storage`` in the all-products universe-matrix candidate has
    one critical-photon input and four non-interchangeable outputs: sprayed and
    unsprayed antimatter, plus sprayed and unsprayed hydrogen.  The miniature
    particle collider has six distinct north/south attachment slots, so those
    five connections are legal even though no one face can carry four lanes.
    """
    one = Fraction(1)
    sprayed = ProliferatorMode.PRODUCTS
    spec = BuildSpec(
        groups=(
            MachineGroup(
                recipe_id="mass-energy-storage",
                machine_item_id="miniature-particle-collider",
                count=1,
                inputs_per_machine={"critical-photon": one},
                outputs_per_machine={"antimatter": 2 * one, "hydrogen": 2 * one},
            ),
            MachineGroup(
                recipe_id="universe-matrix",
                machine_item_id="matrix-lab",
                count=1,
                proliferator_mode=sprayed,
                inputs_per_machine={"antimatter": one},
                outputs_per_machine={"universe-matrix": one},
            ),
            MachineGroup(
                recipe_id="deuterium",
                machine_item_id="miniature-particle-collider",
                count=1,
                inputs_per_machine={"hydrogen": one},
                outputs_per_machine={"deuterium": one},
            ),
            MachineGroup(
                recipe_id="energy-matrix",
                machine_item_id="matrix-lab",
                count=1,
                proliferator_mode=sprayed,
                inputs_per_machine={"hydrogen": one},
                outputs_per_machine={"energy-matrix": one},
            ),
        ),
        external_inputs={"critical-photon": one},
        outputs={
            "universe-matrix": one,
            "deuterium": one,
            "energy-matrix": one,
        },
        surplus_outputs={"antimatter": one},
        belt_item_id="conveyor-belt-3",
        belt_items_per_second=Fraction(30),
        label="four-cargo-domains",
    )

    family = next(
        family
        for family in generate_strip_families(spec)
        if family.recipe_id == "mass-energy-storage"
    )
    variant = default_strip_variant(family)
    cargo = {(lane.items[0], lane.cargo_domain) for lane in family.output_lanes}
    attachments = tuple(
        attachment for plan in variant.attachment_plan for attachment in plan.attachments
    )

    assert cargo == {
        ("antimatter", CargoDomain.REQUIRES_SPRAY),
        ("antimatter", CargoDomain.UNSPRAYED),
        ("hydrogen", CargoDomain.REQUIRES_SPRAY),
        ("hydrogen", CargoDomain.UNSPRAYED),
    }
    assert {lane.side for lane in family.output_lanes} == {"north", "south"}
    profile_side = {
        profile.lane_y: profile.side
        for profile in lane_reach_profiles(family.machine_item_id, variant.yaw)
    }
    assert all(profile_side[plan.lane_y] == plan.lane.side for plan in variant.attachment_plan)
    assert len(attachments) == 5
    assert len({attachment.slot for attachment in attachments}) == 5
    assert all(attachment.span <= catalog.SORTER_MAX_REACH for attachment in attachments)


def test_impossible_global_slot_matching_produces_no_variant() -> None:
    lanes = (
        LogicalLane(
            "input:south:0",
            "input",
            ("a", "b"),
            (),
            CargoDomain.UNSPRAYED,
            "south",
            0,
        ),
        LogicalLane(
            "input:south:1",
            "input",
            ("c", "d"),
            (),
            CargoDomain.UNSPRAYED,
            "south",
            1,
        ),
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
    assert [(instance.machine_start, instance.machine_stop) for instance in instances] == [
        (0, 2),
        (2, 4),
        (4, 5),
    ]
    assert all(instance.family_id == family.family_id for instance in instances)
    assert all(instance.variant.pitch_x == padded.pitch_x for instance in instances)
    assert all(strip_pose_id(instance.variant) == strip_pose_id(ordinary) for instance in instances)
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

    assert contracted.pitch_x == 8
    assert ordinary.pitch_x == 9
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

    # This test is about conservation, not capacity: lift the family's cap
    # before merging instances back up past it.
    family = replace(family, machine_cap=0)
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


def _corpus_spec(url_id: str, policy: CandidatePolicy) -> BuildSpec:
    from flab2bp.bench.corpus import URL_CORPUS
    from flab2bp.lab.data import load_vendored
    from flab2bp.lab.url import parse_url
    from flab2bp.rates.candidates import build_candidates

    entry = next(e for e in URL_CORPUS if e.url_id == url_id)
    return build_candidates(
        load_vendored(),
        parse_url(entry.url),
        candidate_policies=(policy,),
    ).candidates[0]


def test_an_ingredient_fed_from_outside_and_inside_takes_the_outermost_lane_row() -> None:
    """The `hydrogen` lane head must have a second free 4-neighbour.

    R4 §1.2 measured both failing ports as the WEST HEAD TILE of the MIDDLE
    input lane: east is its own lane's second tile, north is the sibling lane
    above, south is the sibling lane below or its own machine band, and only the
    `WEST_CHANNEL` tile is free.  `_reserve_port_access` then reports
    `wants=2 held=1`.  The outermost `in_above` row is the one whose north
    neighbour is the free margin row `_box` charges (`height + MARGIN`,
    MARGIN = 1) and `_greedy_pack` leaves above every strip.

    `universe-matrix` is the only corpus spec where `hydrogen` is BOTH an
    external input and internally produced (R4 §4), which is why the same two
    strips wire cleanly in `casimir-crystal`, `energy-matrix` and `quantum-chip`.
    """
    from flab2bp.rates.candidates import CandidatePolicy

    spec = _corpus_spec("universe-matrix", CandidatePolicy.NO_PROLIFERATOR)
    strips = {strip.group_key: strip for strip in plan_strips(spec)}

    for group_key in ("casimir-crystal#1", "energy-matrix#12"):
        strip = strips[group_key]
        assert strip.in_above[0] == ("hydrogen",), group_key
        assert strip.row_of_input("hydrogen") == 0, group_key


def test_two_both_fed_ingredients_take_opposite_true_outer_rows() -> None:
    """Two independent two-approach lanes use north-first and south-last."""
    from flab2bp.layout.strip_variants import _logical_strip_plans

    one = Fraction(1)
    spec = BuildSpec(
        groups=(
            _group("make-alpha", "assembling-machine-1", 1, {}, {"alpha": one}),
            _group("make-beta", "assembling-machine-1", 1, {}, {"beta": one}),
            _group(
                "consume-both",
                "matrix-lab",
                1,
                {"alpha": one, "beta": one},
                {"product": one},
            ),
        ),
        external_inputs={"alpha": one, "beta": one},
        outputs={"product": one},
    )
    target = next(
        plan
        for plan in _logical_strip_plans(spec)
        if {"alpha", "beta"} == {item for lane in (*plan.in_above, *plan.in_below) for item in lane}
    )
    both_fed = {"alpha", "beta"}

    assert target.in_above and both_fed & set(target.in_above[0])
    assert target.in_below and both_fed & set(target.in_below[-1])
    assert sum(bool(both_fed & set(lane)) for lane in target.in_above) == 1
    assert sum(bool(both_fed & set(lane)) for lane in target.in_below) == 1


def test_three_separately_seated_both_fed_lanes_are_refused() -> None:
    """A strip has only the north-first and south-last true outer rows."""
    from flab2bp.layout.strip_variants import _seat_both_fed_outermost

    with pytest.raises(ValueError, match="only two"):
        _seat_both_fed_outermost(
            (("alpha",), ("beta",), ("gamma",)),
            (),
            frozenset({"alpha", "beta", "gamma"}),
        )


def test_the_seating_rule_changes_no_strip_dimension() -> None:
    """R4 §6 E6 measured `box_height` and `width` unchanged on both strips."""
    from flab2bp.rates.candidates import CandidatePolicy

    spec = _corpus_spec("universe-matrix", CandidatePolicy.NO_PROLIFERATOR)
    strips = {strip.group_key: strip for strip in plan_strips(spec)}

    assert (strips["casimir-crystal#1"].box_height, strips["casimir-crystal#1"].width) == (8, 12)
    assert (strips["energy-matrix#12"].box_height, strips["energy-matrix#12"].width) == (8, 36)


def test_every_both_fed_ingredient_is_seated_on_its_side_s_outermost_row() -> None:
    """The invariant, over every corpus spec.

    Stated as geometry: a lane head must have at least as many free
    4-neighbours as the number of independent feeds the lane accepts.  The strip
    builder's only lever is row order, so it can guarantee this for at most two
    lanes per strip -- `in_above`'s first row and `in_below`'s last.  A recipe
    with three both-fed ingredients would refuse again; R4 §8(B)'s staircase is
    the recorded answer and is out of this phase.

    Runs the LOGICAL planner rather than `plan_strips`: it owns the rule, it is
    pure, and it costs no physical variant enumeration.
    """
    from flab2bp.bench.corpus import URL_CORPUS
    from flab2bp.lab.data import load_vendored
    from flab2bp.lab.url import parse_url
    from flab2bp.layout.freeform import _adapt
    from flab2bp.layout.strip_variants import _logical_strip_plans
    from flab2bp.rates.candidates import DEFAULT_CANDIDATE_POLICIES, build_candidates

    vendored = load_vendored()
    checked = 0
    for entry in URL_CORPUS:
        candidates = build_candidates(
            vendored,
            parse_url(entry.url),
            candidate_policies=DEFAULT_CANDIDATE_POLICIES,
        ).candidates
        for spec in candidates:
            groups = _adapt(spec)
            internally_produced = {item for group in groups.values() for item in group.outputs}
            both_fed = frozenset(spec.external_inputs) & internally_produced
            if not both_fed:
                continue
            for plan in _logical_strip_plans(spec):
                for index, lane in enumerate(plan.in_above):
                    if both_fed & frozenset(lane):
                        assert index == 0, f"{entry.url_id} {plan.group_key} above {lane}"
                        checked += 1
                for index, lane in enumerate(plan.in_below):
                    if both_fed & frozenset(lane):
                        assert index == len(plan.in_below) - 1, (
                            f"{entry.url_id} {plan.group_key} below {lane}"
                        )
                        checked += 1
    assert checked, "no corpus spec exercised the rule; the invariant proved nothing"


def test_a_spec_with_no_both_fed_ingredient_keeps_its_alphabetical_lane_order() -> None:
    """The surgical/broad mutant guard, stated where the mutants live.

    Two mutants of `_logical_strip_plans`' sort key, and this test plus the
    `hydrogen` test above pin one each:

    * WIDENING the key to `(item not in spec.external_inputs, item)` is R4's
      broad `LANEORDER=1` rule.  `quantum-chip` has ten external inputs and an
      EMPTY both-fed set, so under the broad rule its lanes move and THIS test
      goes red; under the surgical rule they cannot move at all.  R4 §7 measured
      the broad rule at +27.2% area on `sequence-pair|quantum-chip|2`,
      reproduced across arms, and that is the one regression risk to the 66
      clean cells this phase carries.
    * DROPPING the `not in both_fed` term leaves `key=lambda item: item`, plain
      alphabetical order -- today's behaviour.  That leaves this test green and
      turns
      `test_an_ingredient_fed_from_outside_and_inside_takes_the_outermost_lane_row`
      red, which is exactly the pair spec section 5.1 test 4 asks for.
    """
    from flab2bp.layout.freeform import _adapt
    from flab2bp.layout.strip_variants import _logical_strip_plans
    from flab2bp.rates.candidates import CandidatePolicy

    spec = _corpus_spec("quantum-chip", CandidatePolicy.NO_PROLIFERATOR)
    groups = _adapt(spec)
    produced = {item for group in groups.values() for item in group.outputs}
    assert not (frozenset(spec.external_inputs) & produced), "pick a spec with no both-fed item"

    for plan in _logical_strip_plans(spec):
        items = [item for lane in (*plan.in_above, *plan.in_below) for item in lane]
        assert items == sorted(items), plan.group_key


def test_a_side_with_no_both_fed_lane_is_returned_unchanged() -> None:
    """The helper is a stable no-op wherever the rule does not apply."""
    from flab2bp.layout.strip_variants import _seat_both_fed_outermost

    in_above = (("alpha",), ("beta",))
    in_below = (("gamma",), ("delta",))

    assert _seat_both_fed_outermost(in_above, in_below, frozenset()) == (in_above, in_below)
    assert _seat_both_fed_outermost(in_above, in_below, frozenset({"zeta"})) == (
        in_above,
        in_below,
    )


def test_a_both_fed_ingredient_seated_below_takes_the_LAST_below_row() -> None:
    """The case no corpus spec exercises, pinned because the indices differ.

    `Strip.row_of_input` counts `in_above` from the strip's top (index 0 is
    outermost) and `in_below` downward from the band (the LAST index is
    outermost).  Ordering `input_items` alone puts a both-fed item at
    `in_below[0]` -- the row nearest the machine band, the worst one available --
    whenever `_seat_inputs` seats lane 0 below.
    """
    from flab2bp.layout.strip_variants import _seat_both_fed_outermost

    above, below = _seat_both_fed_outermost(
        (),
        (("hydrogen",), ("graphene",), ("titanium-crystal",)),
        frozenset({"hydrogen"}),
    )

    assert above == ()
    assert below == (("graphene",), ("titanium-crystal",), ("hydrogen",))


def test_partition_never_exceeds_the_family_machine_cap() -> None:
    family = replace(_family(_single_machine_spec("assembling-machine-1", count=7)), machine_cap=2)
    instances = partition_strip_family(family, max_machine_count=6)
    assert [instance.machine_count for instance in instances] == [2, 2, 2, 1]
    validate_instance_partition(family, instances)


def test_a_zero_cap_leaves_the_requested_length_alone() -> None:
    family = replace(_family(_single_machine_spec("assembling-machine-1", count=7)), machine_cap=0)
    instances = partition_strip_family(family, max_machine_count=6)
    assert [instance.machine_count for instance in instances] == [4, 3]


def test_a_stage_boundary_merge_refuses_to_exceed_the_cap() -> None:
    family = replace(_family(_single_machine_spec("assembling-machine-1", count=6)), machine_cap=4)
    left, right = partition_strip_family(family, max_machine_count=3)
    assert merge_strip_instances(family, left, right) is None  # 3 + 3 > 4
    uncapped = replace(family, machine_cap=0)
    left, right = partition_strip_family(uncapped, max_machine_count=3)
    assert merge_strip_instances(uncapped, left, right) is not None


@pytest.mark.parametrize("requested", [1, 3, 12, 40])
def test_every_strip_length_heuristic_survives_the_cap(requested: int) -> None:
    family = replace(_family(_single_machine_spec("assembling-machine-1", count=9)), machine_cap=3)
    instances = partition_strip_family(family, max_machine_count=requested)
    assert max(instance.machine_count for instance in instances) <= 3
    assert sum(instance.machine_count for instance in instances) == 9


# --- lanes carry a stack (multiple-belts design, section 5.3) ---------------


def _stacked_rated_spec(
    rate: Fraction = Fraction(4),
    *,
    count: int = 8,
    belt_stack: int = 2,
    pick: tuple[int, ...] = (1, 1, 1, 2),
    place: tuple[int, ...] = (1, 1, 1, 1),
) -> BuildSpec:
    """``_rated_spec`` on a save whose bus stacks.  Level 0 of the real table."""
    base = _rated_spec(rate, count=count)
    return BuildSpec(
        groups=base.groups,
        external_inputs=dict(base.external_inputs),
        outputs=dict(base.outputs),
        belt_item_id=base.belt_item_id,
        belt_items_per_second=base.belt_items_per_second,
        belt_stack=belt_stack,
        sorter_pick_stacks=pick,
        sorter_place_stacks=place,
    )


def test_an_unstacked_spec_plans_every_lane_at_one() -> None:
    """Design rule 1: an `ist=1` save is planned exactly as it was."""
    (family,) = generate_strip_families(_rated_spec(Fraction(4)))
    assert {lane.stack for lane in family.input_lanes + family.output_lanes} == {1}
    assert family.machine_cap == 7  # floor(30 / 4), unchanged


def test_a_stacked_spec_plans_its_entry_lane_at_the_bus_stack() -> None:
    """Hydrogen arrives on the player's stack-2 bus; deuterium leaves at what
    an unresearched Pile Sorter places, which is 1."""
    (family,) = generate_strip_families(_stacked_rated_spec())
    hydrogen = [lane for lane in family.input_lanes if "hydrogen" in lane.items]
    assert hydrogen and {lane.stack for lane in hydrogen} == {2}
    assert {lane.stack for lane in family.output_lanes} == {1}
    # 30/s of belt carrying 2 items per cargo is 60 items/s, and one machine
    # draws 4: floor(30 * 2 / 4).
    assert family.machine_cap == 15


def test_a_stacked_output_lane_follows_the_place_stack() -> None:
    (family,) = generate_strip_families(_stacked_rated_spec(pick=(1, 1, 1, 4), place=(1, 1, 1, 4)))
    assert {lane.stack for lane in family.output_lanes} == {4}


def test_a_logical_lane_stack_outside_the_games_range_is_refused() -> None:
    lane = LogicalLane(
        lane_id="input:south:0",
        kind="input",
        items=("hydrogen",),
        destination_group_keys=(),
        cargo_domain=CargoDomain.UNSPRAYED,
        side="south",
        side_index=0,
    )
    assert lane.stack == 1
    for bad in (0, 5):
        with pytest.raises(ValueError, match="lane stack"):
            replace(lane, stack=bad)


# --- a belt-port host is planned one output lane per drain port -------------


def _plans_for(spec: BuildSpec) -> tuple[strip_variants_module._LogicalStripPlan, ...]:
    return strip_variants_module._logical_strip_plans(spec)


def _two_sink_exchanger_spec(count: int = 3) -> BuildSpec:
    """Charge exchangers whose product has an internal consumer AND an output.

    ``count`` selects the shape the planner produces: 1 folds both sinks onto
    ONE lane with DEST_SEP (no second shard to give), 2 or more shards them
    across two strips of one lane each.  Only ``count >= 2`` routes -- one
    charge machine cannot feed a discharge machine AND the external output --
    so ``count=1`` is a planner fixture and never reaches `lay_out`.
    """
    return BuildSpec(
        groups=(
            _group(
                "accumulator-full",
                "energy-exchanger",
                count,
                {"accumulator": Fraction(1)},
                {"accumulator-full": Fraction(1)},
            ),
            _group(
                "accumulator-discharge",
                "energy-exchanger",
                1,
                {"accumulator-full": Fraction(1)},
                {"accumulator": Fraction(1)},
            ),
        ),
        external_inputs={"accumulator": Fraction(2)},
        outputs={"accumulator-full": Fraction(2)},
        belt_item_id="conveyor-belt-2",
        belt_items_per_second=Fraction(12),
        label=f"two-sink-{count}",
    )


def _two_sink_assembler_spec() -> BuildSpec:
    """An ordinary sorter-seated producer with two distinct output destinations.

    Not a belt-port host (``assembling-machine-2`` has slot poses, no port
    poses), so this task's cap must never fire for it: ``out_capacity`` still
    comes from the sorter reach and the south face, exactly as before.
    """
    return BuildSpec(
        groups=(
            _group(
                "gear",
                "assembling-machine-2",
                1,
                {"iron-ingot": Fraction(2)},
                {"gear": Fraction(1)},
            ),
            _group(
                "gear-to-motor",
                "assembling-machine-2",
                1,
                {"gear": Fraction(1)},
                {"motor": Fraction(1)},
            ),
            _group(
                "gear-to-frame",
                "assembling-machine-2",
                1,
                {"gear": Fraction(1)},
                {"frame": Fraction(1)},
            ),
        ),
        external_inputs={"iron-ingot": Fraction(2)},
        outputs={"motor": Fraction(1), "frame": Fraction(1)},
    )


def test_a_single_machine_belt_port_host_folds_its_sinks_onto_one_lane() -> None:
    """2209 has ONE north-facing dock, so it may be planned one output lane.

    Two accumulator-full sinks -- an internal discharge machine and the
    external output -- used to become two lane rows, which one port cannot
    drain, and the strip refused before any search.  With ONE machine there is
    no second shard to give, so the other axis moves: they become one lane
    whose destination field names both groups, which is what DEST_SEP is for.
    """
    plans = _plans_for(_two_sink_exchanger_spec(count=1))
    charge = [p for p in plans if p.recipe_id == "accumulator-full"]
    assert len(charge) == 1, charge
    assert len(charge[0].out_lanes) == 1, charge[0].out_lanes
    item, dest, _domain = charge[0].out_lanes[0]
    assert item == "accumulator-full"
    assert dest == "|accumulator-discharge#1"
    assert freeform._dests(dest) == ("", "accumulator-discharge#1")


def test_several_machines_shard_instead_of_folding_and_still_take_one_lane() -> None:
    """The cap is 'one lane per PLAN', which sharding satisfies too.

    With machines to spare the planner splits the destinations across STRIPS
    rather than folding them onto one lane -- `_shard_sinks` runs before
    `_merge_lanes`.  Either shape honours the cap; what must never come back is
    a single plan carrying two lanes for a host with one drain port.
    """
    plans = _plans_for(_two_sink_exchanger_spec(count=3))
    charge = [p for p in plans if p.recipe_id == "accumulator-full"]
    assert len(charge) == 2, charge
    assert {p.shard_index for p in charge} == {0, 1}
    assert all(len(p.out_lanes) == 1 for p in charge), charge
    assert {dest for p in charge for _i, dest, _c in p.out_lanes} == {
        "accumulator-discharge#1",
        "",
    }


def test_an_ordinary_producer_keeps_its_sorter_derived_lane_capacity() -> None:
    """The cap is asked only of a host that drains through PORTS.

    An assembler has no port poses at all, so its out_capacity must still come
    from the south face and the sorter reach -- otherwise every strip in the
    corpus loses lanes.
    """
    plans = _plans_for(_two_sink_assembler_spec())
    producer = next(p for p in plans if p.recipe_id == "gear")
    assert len(producer.out_lanes) == 2


def test_a_multi_dock_belt_port_host_keeps_its_full_drain_capacity() -> None:
    """2316 has THREE north-facing docks at its lane-orientation yaw -- not one.

    The cap's guard (`takes_belt_ports and not slot_poses`) covers every
    belt-port host, not only the Energy Exchanger -- measured: all twelve such
    buildings have falsy `slot_poses`.  A cap that assumed 'one dock' (the
    Energy Exchanger's own shape) would flatten a two-destination producer onto
    one DEST_SEP-joined lane the way a one-dock host is folded.  2316
    (Advanced Mining Machine) has `slots.drain_dock_count(2316, 0.0) == 3`
    (measured), so two destinations must stay two separate lanes -- capacity
    to spare, no fold needed.
    """
    assert slots.drain_dock_count(2316, 0.0) == 3
    plans = _plans_for(
        BuildSpec(
            groups=(
                _group(
                    "ore",
                    "advanced-mining-machine",
                    1,
                    {},
                    {"ore": Fraction(1)},
                ),
                _group(
                    "ore-to-a",
                    "assembling-machine-1",
                    1,
                    {"ore": Fraction(1)},
                    {"a": Fraction(1)},
                ),
                _group(
                    "ore-to-b",
                    "assembling-machine-1",
                    1,
                    {"ore": Fraction(1)},
                    {"b": Fraction(1)},
                ),
            ),
            external_inputs={},
            outputs={"a": Fraction(1), "b": Fraction(1)},
        )
    )
    miner = [p for p in plans if p.recipe_id == "ore"]
    assert len(miner) == 1, miner
    assert len(miner[0].out_lanes) == 2, miner[0].out_lanes
    assert {dest for _item, dest, _domain in miner[0].out_lanes} == {
        "ore-to-a#1",
        "ore-to-b#2",
    }
