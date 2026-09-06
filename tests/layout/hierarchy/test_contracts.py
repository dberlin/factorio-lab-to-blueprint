from fractions import Fraction

import pytest

from flab2bp.dsp import catalog
from flab2bp.layout.base import PlacedBuilding, Placement
from flab2bp.layout.hierarchy.contracts import ContractError, LaneEnd, assign_lanes, boundary_lanes
from flab2bp.layout.hierarchy.partition import Cut
from flab2bp.spec import BuildSpec

BELT = next(iter(catalog.BELT_IDS))
SORTER = next(iter(catalog.SORTER_IDS))


def _end(block, building, item, rate):
    return LaneEnd(block=block, building=building, item=item, rate=Fraction(rate))


def test_one_tail_feeds_two_heads_as_two_flows_from_the_same_tail():
    cuts = [Cut("magnet", 0, 1, Fraction(6))]
    tails = {0: [_end(0, 10, "magnet", 6)]}
    heads = {1: [_end(1, 20, "magnet", 4), _end(1, 21, "magnet", 2)]}
    flows = assign_lanes(cuts, tails, heads)
    assert [(f.src.building, f.dst.building, f.rate) for f in flows] == [(10, 20, 4), (10, 21, 2)]


def test_two_tails_fill_one_head_largest_first():
    cuts = [Cut("magnet", 0, 1, Fraction(5))]
    tails = {0: [_end(0, 10, "magnet", 2), _end(0, 11, "magnet", 3)]}
    heads = {1: [_end(1, 20, "magnet", 5)]}
    flows = assign_lanes(cuts, tails, heads)
    assert [(f.src.building, f.rate) for f in flows] == [(11, 3), (10, 2)]


def test_six_out_four_in_needs_at_most_nine_flows_and_meets_every_head():
    cuts = [Cut("magnet", 0, 1, Fraction(12))]
    tails = {0: [_end(0, i, "magnet", 2) for i in range(6)]}
    heads = {1: [_end(1, 20 + j, "magnet", 3) for j in range(4)]}
    flows = assign_lanes(cuts, tails, heads)
    assert len(flows) <= 9
    for j in range(4):
        assert sum(f.rate for f in flows if f.dst.building == 20 + j) == 3


def test_short_supply_is_a_contract_error_naming_the_item_and_blocks():
    cuts = [Cut("processor", 0, 1, Fraction(15))]
    tails = {0: [_end(0, 10, "processor", 15)]}
    heads = {1: [_end(1, 20, "processor", 28)]}
    with pytest.raises(ContractError, match=r"processor.*block 0.*block 1"):
        assign_lanes(cuts, tails, heads)


def test_flows_are_exact_fractions():
    cuts = [Cut("x", 0, 1, Fraction(1, 3))]
    tails = {0: [_end(0, 1, "x", Fraction(1, 3))]}
    heads = {1: [_end(1, 2, "x", Fraction(1, 3))]}
    (flow,) = assign_lanes(cuts, tails, heads)
    assert flow.rate == Fraction(1, 3)


def _boundary_spec() -> BuildSpec:
    return BuildSpec(
        groups=(),
        external_inputs={"ingredientB": Fraction(5)},
        outputs={"ingredientA": Fraction(6)},
        surplus_outputs={},
        belt_item_id="conveyor-belt-1",
        belt_items_per_second=Fraction(6),
        belt_upgrades=(),
        sorter_item_ids=("sorter-1",),
        belt_stack=1,
        sorter_pick_stacks=(1,),
        sorter_place_stacks=(1,),
        piler_unlocked=False,
        label="boundary-test",
    )


def _boundary_placement() -> Placement:
    """A hand-made block: two output tails, one entry head, and one INTERNAL
    lane -- fed by a producer sorter and drawn by a consumer sorter, so it
    would satisfy ``markers.output_belt_tails``/``input_belt_heads`` on its
    own but must be excluded from both by the sorter-fed/sorter-drawn filter.
    """
    b = PlacedBuilding
    buildings = (
        b(item_id=SORTER, model_index=0, x=0, y=0, output_obj=1),  # 0: feeds tail1
        b(
            item_id=BELT,
            model_index=0,
            x=1,
            y=0,
            input_obj=0,
            carries_item="ingredientA",
        ),  # 1: tail1
        b(item_id=SORTER, model_index=0, x=2, y=0, output_obj=3),  # 2: feeds tail2
        b(
            item_id=BELT,
            model_index=0,
            x=3,
            y=0,
            input_obj=2,
            carries_item="ingredientA",
        ),  # 3: tail2
        b(
            item_id=BELT,
            model_index=0,
            x=4,
            y=0,
            output_obj=5,
            carries_item="ingredientB",
        ),  # 4: head
        b(item_id=SORTER, model_index=0, x=5, y=0, input_obj=4),  # 5: draws head in
        b(item_id=SORTER, model_index=0, x=6, y=0, output_obj=7),  # 6: feeds internal lane
        b(
            item_id=BELT,
            model_index=0,
            x=7,
            y=0,
            input_obj=6,
            carries_item="ingredientC",
        ),  # 7: internal, excluded from both sides
        b(item_id=SORTER, model_index=0, x=8, y=0, input_obj=7),  # 8: draws internal lane in
    )
    return Placement(buildings=buildings)


def test_boundary_lanes_rates_tails_and_heads_and_excludes_the_internal_lane():
    placement = _boundary_placement()
    sub = _boundary_spec()
    tails, heads = boundary_lanes(placement, sub, block=0)
    # Both tails lack an owner_strip, so the block's output splits evenly.
    assert tails == [
        LaneEnd(block=0, building=1, item="ingredientA", rate=Fraction(3)),
        LaneEnd(block=0, building=3, item="ingredientA", rate=Fraction(3)),
    ]
    assert heads == [LaneEnd(block=0, building=4, item="ingredientB", rate=Fraction(5))]
    assert all(end.item != "ingredientC" for end in (*tails, *heads))
