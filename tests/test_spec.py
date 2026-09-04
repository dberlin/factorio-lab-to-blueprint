"""The rates/geometry boundary's own invariants."""

from __future__ import annotations

from fractions import Fraction

import pytest

from flab2bp.dsp import catalog
from flab2bp.layout.base import NoValidLayout
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


def test_planning_stack_is_one_for_a_spec_that_does_not_stack() -> None:
    """Design rule 1, from the field that decides it: no `ist`, no stacking,
    whatever the save's sorters and pilers could do."""
    assert BuildSpec(groups=(), piler_unlocked=True).planning_stack("hydrogen") == 1


# --- planning_stack (multiple-belts design, section 5.3) --------------------
#
# Every `pick`/`place` pair below is a real row of design section 5.1's table:
# Mk.I to Mk.III are 1 at EVERY level and only the last entry (the Pile Sorter)
# moves.
#   level 0: pick (1,1,1,2) place (1,1,1,1)    level 4: pick (1,1,1,4) place (1,1,1,3)
#   level 1: pick (1,1,1,2) place (1,1,1,2)    level 5: pick (1,1,1,4) place (1,1,1,4)
#   level 2: pick (1,1,1,3) place (1,1,1,2)    level 6: pick (1,1,1,4) place (1,1,1,4)
#   level 3: pick (1,1,1,3) place (1,1,1,3)    no Pile Sorter: three-entry tuples of 1
# There is no row like (2, 2, 2, 4): DSP grants no Mk.II a stack.  `ids` stays
# aligned with `pick`/`place` because `BuildSpec._stacks_align` requires one
# entry per tier, so a save without the Pile Sorter is THREE ids and
# three-entry tuples.


def _stacked(
    *,
    belt_stack: int = 1,
    pick: tuple[int, ...] = (1, 1, 1, 4),
    place: tuple[int, ...] = (1, 1, 1, 4),
    piler: bool = False,
    ids: tuple[str, ...] = ("sorter-1", "sorter-2", "sorter-3", "sorter-4"),
) -> BuildSpec:
    return BuildSpec(
        groups=(
            MachineGroup(
                recipe_id="deuterium",
                machine_item_id="miniature-particle-collider",
                count=1,
                inputs_per_machine={"hydrogen": Fraction(4)},
                outputs_per_machine={"deuterium": Fraction(1, 2)},
            ),
        ),
        external_inputs={"hydrogen": Fraction(4)},
        outputs={"deuterium": Fraction(1, 2)},
        belt_item_id="conveyor-belt-3",
        belt_items_per_second=Fraction(30),
        sorter_item_ids=ids,
        belt_stack=belt_stack,
        sorter_pick_stacks=pick,
        sorter_place_stacks=place,
        piler_unlocked=piler,
    )


def _both_fed(spec: BuildSpec) -> BuildSpec:
    """``spec`` with hydrogen ALSO produced inside, the universe-matrix shape.

    ``model_copy`` is the module's own idiom for deriving a spec from a
    finished one (``_to_build_spec`` uses it for ``lanes_requiring_split``);
    the refinery's own input is declared external so the derived spec is
    complete rather than merely unvalidated.
    """
    return spec.model_copy(
        update={
            "groups": (
                *spec.groups,
                MachineGroup(
                    recipe_id="hydrogen-cracking",
                    machine_item_id="oil-refinery",
                    count=1,
                    inputs_per_machine={"refined-oil": Fraction(1)},
                    outputs_per_machine={"hydrogen": Fraction(3)},
                ),
            ),
            "external_inputs": {**spec.external_inputs, "refined-oil": Fraction(1)},
        }
    )


def test_planning_stack_is_one_when_the_url_does_not_stack() -> None:
    assert _stacked(pick=(1, 1, 1, 4), place=(1, 1, 1, 4)).planning_stack("hydrogen") == 1
    assert _stacked(pick=(1, 1, 1, 4), place=(1, 1, 1, 4)).planning_stack("deuterium") == 1


def test_an_external_input_is_planned_at_the_bus_stack() -> None:
    level_0 = _stacked(belt_stack=2, pick=(1, 1, 1, 2), place=(1, 1, 1, 1))
    level_4 = _stacked(belt_stack=4, pick=(1, 1, 1, 4), place=(1, 1, 1, 3))
    assert level_0.planning_stack("hydrogen") == 2
    assert level_4.planning_stack("hydrogen") == 4


def test_a_bus_without_a_pile_sorter_is_refused_not_capped() -> None:
    # Mk.I to Mk.III pick 1 at EVERY level, so any ist > 1 on such a save is a
    # refusal.  This is the whole of the "unpickable bus" class in practice.
    spec = _stacked(belt_stack=2, pick=(1, 1, 1), place=(1, 1, 1),
                    ids=("sorter-1", "sorter-2", "sorter-3"))
    with pytest.raises(NoValidLayout, match=r"stack 2.*pick only 1.*Integrated Logistics System"):
        spec.planning_stack("hydrogen")


def test_a_bus_above_the_researched_pick_stack_is_refused() -> None:
    spec = _stacked(belt_stack=4, pick=(1, 1, 1, 3), place=(1, 1, 1, 2))   # level 2
    with pytest.raises(NoValidLayout, match=r"stack 4.*pick only 3.*Pile Sorter Upgrade"):
        spec.planning_stack("hydrogen")


def test_a_produced_item_is_planned_at_the_place_stack() -> None:
    for place, pick, expected in (
        ((1, 1, 1, 4), (1, 1, 1, 4), 4),
        ((1, 1, 1, 2), (1, 1, 1, 2), 2),
        ((1, 1, 1, 1), (1, 1, 1, 2), 1),
    ):
        spec = _stacked(belt_stack=2, place=place, pick=pick)
        assert spec.planning_stack("deuterium") == expected, (place, pick)


def test_the_piler_raises_a_produced_lane_along_the_doubling_ladder() -> None:
    # A piler DOUBLES, so the reachable targets are 1, 2 and 4 -- never 3 --
    # and piling is elective, so it stops at what the sink can pick.
    for place, pick, expected in (
        ((1, 1, 1, 1), (1, 1, 1, 2), 2),
        ((1, 1, 1, 2), (1, 1, 1, 3), 2),
        ((1, 1, 1, 3), (1, 1, 1, 4), 4),
        ((1, 1, 1, 4), (1, 1, 1, 4), 4),
    ):
        spec = _stacked(belt_stack=2, piler=True, place=place, pick=pick)
        assert spec.planning_stack("deuterium") == expected, (place, pick)


def test_the_piler_never_lowers_a_lane_it_cannot_raise() -> None:
    """3 is not on the ladder, so a lane already at 3 keeps 3 rather than
    dropping to the largest reachable rung below it."""
    spec = _stacked(belt_stack=2, piler=True, place=(1, 1, 1, 3), pick=(1, 1, 1, 3))
    assert spec.planning_stack("deuterium") == 3


def test_the_piler_does_not_touch_an_external_lane() -> None:
    """The bus arrives as the player built it; a piler inside the block cannot
    change what the boundary belt already carries."""
    spec = _stacked(belt_stack=2, piler=True, pick=(1, 1, 1, 4), place=(1, 1, 1, 4))
    assert spec.planning_stack("hydrogen") == 2


def test_a_place_stack_the_consumer_cannot_pick_is_refused_not_capped() -> None:
    # Unreachable with the real table (pick >= place at every level), so this
    # guards hand-built specs; it must stay a refusal, because a sorter cannot
    # be told to place less.
    with pytest.raises(NoValidLayout, match=r"stack 4.*pick"):
        _stacked(belt_stack=2, place=(1, 1, 1, 4), pick=(1, 1, 1, 2)).planning_stack("deuterium")


def test_an_item_fed_from_the_bus_and_from_inside_is_planned_at_the_smaller_stack() -> None:
    # Level 4: the Pile Sorter picks 4 and places 3.  The bus arrives at 4, the
    # internal producer's sorter places 3, and a merge is judged at its minimum.
    spec = _stacked(belt_stack=4, place=(1, 1, 1, 3), pick=(1, 1, 1, 4))
    assert _both_fed(spec).planning_stack("hydrogen") == 3
    assert spec.planning_stack("hydrogen") == 4


def test_the_external_override_beats_the_specs_own_classification() -> None:
    """The override replaces the spec's classification and nothing else.

    Forcing "produced" on a belted-in item gives what its sorter places;
    forcing "external" on a produced one gives the bus stack, still through
    the both-fed rule, because that item IS also produced.  The planner only
    ever makes the first call (a boundary output lane for an item the spec
    also belts in); the second is here to pin that the both-fed rule is not
    skipped just because the caller named the side."""
    spec = _stacked(belt_stack=2, place=(1, 1, 1, 3), pick=(1, 1, 1, 4))
    # hydrogen is external by classification: the bus stack, 2.
    assert spec.planning_stack("hydrogen") == 2
    assert spec.planning_stack("hydrogen", external=False) == 3
    # deuterium is produced by classification: what the sorter places, 3.
    assert spec.planning_stack("deuterium") == 3
    assert spec.planning_stack("deuterium", external=True) == 2
