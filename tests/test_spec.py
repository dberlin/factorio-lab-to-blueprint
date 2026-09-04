"""The rates/geometry boundary's own invariants."""

from __future__ import annotations

from fractions import Fraction

import pytest

from flab2bp.dsp import catalog
from flab2bp.spec import MAX_CARGO_STACK, BeltTier, BuildSpec, MachineGroup


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


def test_planning_stack_is_one_for_every_item_until_stacked_lanes_land() -> None:
    spec = BuildSpec(groups=(), belt_item_id="conveyor-belt-3", belt_items_per_second=Fraction(30))
    assert spec.planning_stack("hydrogen") == 1


# --- the cargo stack (multiple-belts design, section 5.2) -------------------


def test_the_stack_ceiling_is_the_games_own() -> None:
    """``spec`` spells the number out to stay free of DSP imports; this is the
    guard that keeps the copy honest."""
    assert MAX_CARGO_STACK == catalog.PILER_MAX_STACK


def test_belt_stack_defaults_to_one_and_is_capped_at_four() -> None:
    assert BuildSpec(groups=()).belt_stack == 1
    with pytest.raises(ValueError, match="belt_stack"):
        BuildSpec(groups=(), belt_stack=5)


def test_stack_tuples_align_with_sorter_tiers() -> None:
    """The match is on the validator's own wording, not just the field name:
    pydantic rejects an unknown field with the field name in the message too,
    so a looser regex would pass before the field existed."""
    with pytest.raises(ValueError, match="sorter_pick_stacks has 2 entries"):
        BuildSpec(groups=(), sorter_item_ids=("sorter-1",), sorter_pick_stacks=(1, 1))
    with pytest.raises(ValueError, match="sorter_place_stacks has 2 entries"):
        BuildSpec(
            groups=(),
            sorter_item_ids=("sorter-1",),
            sorter_pick_stacks=(1,),
            sorter_place_stacks=(1, 1),
        )


def test_a_stack_outside_the_games_range_is_refused() -> None:
    """1..4 is the whole domain: ``PILER_MAX_STACK`` is 4 and a cargo of 0 is
    not a cargo.  Caught here because a 0 would divide a lane's capacity by
    zero downstream, and a 5 would plan a belt the game cannot carry."""
    with pytest.raises(ValueError, match="sorter_place_stacks entry 5 is outside"):
        BuildSpec(groups=(), sorter_place_stacks=(1, 1, 1, 5))
    with pytest.raises(ValueError, match="sorter_pick_stacks entry 0 is outside"):
        BuildSpec(groups=(), sorter_pick_stacks=(1, 1, 1, 0))


def test_max_stack_is_four_with_the_piler_else_the_largest_place_stack() -> None:
    assert BuildSpec(groups=(), piler_unlocked=True).max_stack == 4
    assert BuildSpec(groups=(), sorter_place_stacks=(1, 1, 1, 4)).max_stack == 4
    assert BuildSpec(groups=(), sorter_item_ids=("sorter-1",), sorter_pick_stacks=(1,),
                     sorter_place_stacks=(2,)).max_stack == 2


def test_the_defaults_are_the_level_zero_row_of_the_pinned_table() -> None:
    # Only the Pile Sorter stacks, and unresearched it picks 2 and places 1.
    spec = BuildSpec(groups=())
    assert spec.sorter_pick_stacks == (1, 1, 1, 2)
    assert spec.sorter_place_stacks == (1, 1, 1, 1)
    assert spec.sorter_pick_stacks[-1] == catalog.sorter_pick_stack(2014, 0)
    assert spec.sorter_place_stacks[-1] == catalog.sorter_place_stack(2014, 0)
    assert spec.piler_unlocked is False


def test_planning_stack_is_still_one_for_every_item() -> None:
    """Task 8 gives it its rule; until then a lane is one item per cargo."""
    spec = BuildSpec(groups=(), belt_stack=4, piler_unlocked=True)
    assert spec.planning_stack("hydrogen") == 1
