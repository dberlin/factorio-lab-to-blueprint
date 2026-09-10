"""Physical edge cases for constructive transport routing."""

from __future__ import annotations

import math
from fractions import Fraction

from flab2bp.dsp import catalog, colliders
from flab2bp.layout import validate
from flab2bp.layout.band_policy import BandPolicy
from flab2bp.layout.markers import self_loop_prime_heads
from flab2bp.layout.transport_routing.construction import spherical_overflight_limit
from flab2bp.layout.transport_routing.runtime import TransportRoutingKernel
from flab2bp.spec import BeltTier, BuildSpec, MachineGroup, SelfLoopSeed

_BELT_RULES = catalog.BeltAltitudeRules(
    max_z=catalog.belt_max_z(catalog.DEFAULT_LAB_LEVEL),
    vertical_construction=True,
    storage_level=catalog.DEFAULT_STORAGE_LEVEL,
    lab_level=catalog.DEFAULT_LAB_LEVEL,
    from_url=False,
)


def test_overflight_clears_projected_corner_that_flat_height_misses() -> None:
    machine = colliders.Placed(376, 0.0, 0.0, 0.0, 0.0)
    boxes = colliders.target_boxes(machine, *colliders.preview_pose(0.0, 0.0, 0.0, 0.0))

    def overlaps(level: int) -> bool:
        position, _ = colliders.preview_pose(-3.0, -1.0, level, 0.0)
        scale = 1 + colliders.BELT_PROBE_LIFT / math.hypot(*position)
        probe = (position[0] * scale, position[1] * scale, position[2] * scale)
        return any(
            colliders.sphere_box_overlap(probe, colliders.BELT_PROBE_RADIUS, box) for box in boxes
        )

    flat_level = math.floor(colliders.belt_crossing_height(machine.model_index)) + 1
    assert overlaps(flat_level)
    assert not overlaps(spherical_overflight_limit(machine.model_index, Fraction(0)))


def test_seeded_return_survives_competing_import_of_the_same_item() -> None:
    # X-ray cracking must recycle 1/2 hydrogen/s and export its 1/4 surplus.
    # Supplying its input from the unrelated import instead balances the global
    # rates but removes the physical return that the hand-prime contract needs.
    spec = BuildSpec(
        groups=(
            MachineGroup(
                recipe_id="x-ray-cracking",
                machine_item_id="oil-refinery",
                count=1,
                inputs_per_machine={"hydrogen": Fraction(1, 2), "refined-oil": Fraction(1, 2)},
                outputs_per_machine={
                    "hydrogen": Fraction(3, 4),
                    "energetic-graphite": Fraction(1, 4),
                },
            ),
            MachineGroup(
                recipe_id="deuterium",
                machine_item_id="miniature-particle-collider",
                count=1,
                inputs_per_machine={"hydrogen": Fraction(5, 2)},
                outputs_per_machine={"deuterium": Fraction(5, 4)},
            ),
        ),
        external_inputs={"hydrogen": Fraction(9, 4), "refined-oil": Fraction(1, 2)},
        outputs={"deuterium": Fraction(5, 4), "energetic-graphite": Fraction(1, 4)},
        self_loop_seeds=(
            SelfLoopSeed(
                item_id="hydrogen",
                recipe_id="x-ray-cracking",
                machine_item_id="oil-refinery",
                machines=1,
                consumed_per_craft=Fraction(2),
                produced_per_craft=Fraction(3),
                net_per_craft=Fraction(1),
                seed_items=2,
            ),
        ),
    )
    placement = TransportRoutingKernel(
        belt_rules=_BELT_RULES, band_policy=BandPolicy("portable")
    ).lay_out(spec, time_budget_s=15)
    report = validate.certify(placement, spec, belt_rules=_BELT_RULES, expect_power=True)
    assert report.ok, report.errors
    assert not report.skipped
    assert set(self_loop_prime_heads(placement, spec)) == {"hydrogen"}


def test_native_routes_upgrade_above_floor_without_exceeding_allowed_ceiling() -> None:
    # One 7/s lane fits the allowed Mk.II ceiling, but not its emitted Mk.I floor.
    # Omitting canonical retiering makes the physical capacity certificate fail.
    spec = BuildSpec(
        groups=(
            MachineGroup(
                recipe_id="iron-ingot",
                machine_item_id="arc-smelter",
                count=7,
                inputs_per_machine={"iron-ore": Fraction(1)},
                outputs_per_machine={"iron-ingot": Fraction(1)},
            ),
        ),
        external_inputs={"iron-ore": Fraction(7)},
        outputs={"iron-ingot": Fraction(7)},
        belt_item_id="conveyor-belt-1",
        belt_items_per_second=Fraction(6),
        belt_upgrades=(BeltTier(item_id="conveyor-belt-2", items_per_second=Fraction(12)),),
    )
    placement = TransportRoutingKernel(
        belt_rules=_BELT_RULES, band_policy=BandPolicy("portable")
    ).lay_out(spec, time_budget_s=15)
    report = validate.certify(placement, spec, belt_rules=_BELT_RULES, expect_power=True)
    assert report.ok, report.errors
    assert not report.skipped
    belt_items = {
        building.item_id for building in placement.buildings if catalog.is_belt(building.item_id)
    }
    assert 2002 in belt_items
    assert belt_items <= {2001, 2002}
