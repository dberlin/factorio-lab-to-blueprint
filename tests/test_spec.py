"""The rates/geometry boundary's own invariants."""

from __future__ import annotations

from fractions import Fraction

import pytest

from flab2bp.spec import BeltTier, BuildSpec, MachineGroup


def _group() -> MachineGroup:
    return MachineGroup(
        recipe_id="magnetic-coil",
        machine_item_id="assembling-machine-2",
        count=1,
        inputs_per_machine={"copper-ingot": Fraction(1)},
        outputs_per_machine={"magnetic-coil": Fraction(1)},
    )


def test_no_upgrades_means_the_floor_is_the_ceiling() -> None:
    spec = BuildSpec(
        groups=(_group(),), belt_item_id="conveyor-belt-2", belt_items_per_second=Fraction(12)
    )
    assert spec.belt_tiers == (BeltTier(item_id="conveyor-belt-2", items_per_second=Fraction(12)),)
    assert spec.lane_capacity == Fraction(12)
    assert spec.sorter_item_ids == ("sorter-1", "sorter-2", "sorter-3", "sorter-4")


def test_upgrades_follow_the_floor_and_raise_the_capacity() -> None:
    spec = BuildSpec(
        groups=(_group(),),
        belt_item_id="conveyor-belt-1",
        belt_items_per_second=Fraction(6),
        belt_upgrades=(
            BeltTier(item_id="conveyor-belt-2", items_per_second=Fraction(12)),
            BeltTier(item_id="conveyor-belt-3", items_per_second=Fraction(30)),
        ),
    )
    assert [tier.item_id for tier in spec.belt_tiers] == [
        "conveyor-belt-1",
        "conveyor-belt-2",
        "conveyor-belt-3",
    ]
    assert spec.lane_capacity == Fraction(30)


def test_an_upgrade_no_faster_than_the_floor_is_refused() -> None:
    with pytest.raises(ValueError, match="faster"):
        BuildSpec(
            groups=(_group(),),
            belt_item_id="conveyor-belt-2",
            belt_items_per_second=Fraction(12),
            belt_upgrades=(BeltTier(item_id="conveyor-belt-1", items_per_second=Fraction(6)),),
        )


def test_upgrades_out_of_order_are_refused() -> None:
    with pytest.raises(ValueError, match="faster"):
        BuildSpec(
            groups=(_group(),),
            belt_upgrades=(
                BeltTier(item_id="conveyor-belt-3", items_per_second=Fraction(30)),
                BeltTier(item_id="conveyor-belt-2", items_per_second=Fraction(12)),
            ),
        )


def test_sorter_tiers_may_not_be_empty() -> None:
    with pytest.raises(ValueError, match="sorter"):
        BuildSpec(groups=(_group(),), sorter_item_ids=())
