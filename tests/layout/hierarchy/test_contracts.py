from dataclasses import replace
from fractions import Fraction

import pytest

from flab2bp.dsp import catalog
from flab2bp.layout.base import PlacedBuilding, Placement
from flab2bp.layout.hierarchy.contracts import (
    ContractError,
    LaneEnd,
    allocate_cuts,
    assign_lanes,
    boundary_lanes,
)
from flab2bp.layout.hierarchy.partition import Cut
from flab2bp.spec import BuildSpec
from tests.layout.hierarchy.test_pressure import _chain, _chain_with_external
from tests.layout.test_markers import _piler_output_placement

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


def test_two_cuts_for_one_item_pool_supply_and_demand():
    # derive_cuts emits one Cut per (surplus block, deficit block) pair, so an
    # item crossing from two producing blocks into two consuming blocks shows
    # up as two Cuts here -- the assignment must pool both sides, not solve
    # each cut in isolation, or a head fed by the "wrong" cut's tail is missed.
    cuts = [Cut("x", 0, 2, Fraction(5)), Cut("x", 1, 3, Fraction(5))]
    tails = {0: [_end(0, 10, "x", 5)], 1: [_end(1, 11, "x", 5)]}
    heads = {2: [_end(2, 20, "x", 7)], 3: [_end(3, 21, "x", 3)]}
    flows = assign_lanes(cuts, tails, heads)
    assert all(f.src.block in {0, 1} for f in flows)
    assert all(f.dst.block in {2, 3} for f in flows)
    assert sum(f.rate for f in flows if f.dst.building == 20) == 7
    assert sum(f.rate for f in flows if f.dst.building == 21) == 3


def test_a_both_fed_item_leaves_the_unserved_block_to_the_player():
    spec = _chain_with_external("ingot")  # ingot both produced inside and in external_inputs
    cuts = [Cut("ingot", 0, 1, Fraction(2)), Cut("ingot", 0, 2, Fraction(2))]
    tails = {0: [_end(0, 10, "ingot", 2)]}
    heads = {1: [_end(1, 20, "ingot", 2)], 2: [_end(2, 30, "ingot", 2)]}
    got = allocate_cuts(spec, cuts, tails, heads)
    assert [(f.src.building, f.dst.building, f.rate) for f in got.flows] == [(10, 20, Fraction(2))]
    assert got.player_fed == {(2, "ingot")}


def test_an_internal_item_short_of_supply_is_a_contract_error():
    spec = _chain()  # ingot NOT in external_inputs
    cuts = [Cut("ingot", 0, 1, Fraction(2)), Cut("ingot", 0, 2, Fraction(2))]
    tails = {0: [_end(0, 10, "ingot", 2)]}
    heads = {1: [_end(1, 20, "ingot", 2)], 2: [_end(2, 30, "ingot", 2)]}
    with pytest.raises(ContractError, match=r"ingot.*block 2.*does not belt it in"):
        allocate_cuts(spec, cuts, tails, heads)


def test_a_block_is_wired_entirely_or_not_at_all():
    spec = _chain_with_external("ingot")
    cuts = [Cut("ingot", 0, 1, Fraction(3))]
    tails = {0: [_end(0, 10, "ingot", 3)]}
    heads = {1: [_end(1, 20, "ingot", 2), _end(1, 21, "ingot", 2)]}  # wants 4, has 3
    got = allocate_cuts(spec, cuts, tails, heads)
    assert got.flows == [] and got.player_fed == {(1, "ingot")}


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


def test_piler_transit_preserves_rated_producer_boundary():
    placement = _piler_output_placement()
    spec = BuildSpec(groups=(), outputs={"gear": Fraction(1)})
    tails, heads = boundary_lanes(placement, spec, 0)
    assert [(lane.building, lane.rate) for lane in tails] == [(4, Fraction(1))]
    assert all(lane.building != 4 for lane in heads)


def test_shared_piled_tail_is_counted_once_and_keeps_exact_machine_weight():
    buildings = list(_piler_output_placement().buildings)
    buildings.extend(
        (
            replace(buildings[0], x=5),
            replace(buildings[1], x=6, input_obj=5, output_obj=7),
            replace(buildings[2], x=7, output_obj=2),  # ordinary belt merge before Piler
            replace(buildings[0], x=8),
            replace(buildings[1], x=9, input_obj=8, output_obj=10),
            replace(buildings[2], x=10, output_obj=None),
        )
    )
    spec = BuildSpec(groups=(), outputs={"gear": Fraction(1)})
    tails, heads = boundary_lanes(Placement(buildings=tuple(buildings)), spec, 0)
    assert [(lane.building, lane.rate) for lane in tails] == [
        (4, Fraction(2, 3)),
        (10, Fraction(1, 3)),
    ]
    assert heads == []


def _spec_with_output(item: str, rate: Fraction) -> BuildSpec:
    return BuildSpec(
        groups=(),
        external_inputs={},
        outputs={item: rate},
        surplus_outputs={},
        belt_item_id="conveyor-belt-1",
        belt_items_per_second=Fraction(6),
        belt_upgrades=(),
        sorter_item_ids=("sorter-1",),
        belt_stack=1,
        sorter_pick_stacks=(1,),
        sorter_place_stacks=(1,),
        piler_unlocked=False,
        label="provenance-test",
    )


def _two_tail_placement(*, strip_b: int | None) -> Placement:
    """Two output tails for ``ingredientA``: tail A's strip (0) always has two
    machines behind it, tail B's strip is ``strip_b`` (``1`` with one machine
    behind it, or ``None`` to simulate lost strip provenance).
    """
    b = PlacedBuilding
    buildings = [
        b(item_id=SORTER, model_index=0, x=0, y=0, output_obj=1),  # 0: feeds tail A
        b(
            item_id=BELT,
            model_index=0,
            x=1,
            y=0,
            input_obj=0,
            carries_item="ingredientA",
            owner_strip=0,
        ),  # 1: tail A
        b(item_id=9999, model_index=0, x=2, y=0, owner_strip=0, recipe_id=100),  # 2: machine
        b(item_id=9999, model_index=0, x=3, y=0, owner_strip=0, recipe_id=100),  # 3: machine
        b(item_id=SORTER, model_index=0, x=4, y=0, output_obj=5),  # 4: feeds tail B
        b(
            item_id=BELT,
            model_index=0,
            x=5,
            y=0,
            input_obj=4,
            carries_item="ingredientA",
            owner_strip=strip_b,
        ),  # 5: tail B
    ]
    if strip_b is not None:
        buildings.append(
            b(item_id=9999, model_index=0, x=6, y=0, owner_strip=strip_b, recipe_id=100)
        )  # 6: machine behind tail B's strip
    return Placement(buildings=tuple(buildings))


def test_boundary_lanes_weights_tails_by_machines_behind_when_every_lane_has_a_strip():
    placement = _two_tail_placement(strip_b=1)  # strip 0: 2 machines, strip 1: 1 machine
    sub = _spec_with_output("ingredientA", Fraction(9))
    tails, _heads = boundary_lanes(placement, sub, block=0)
    assert tails == [
        LaneEnd(block=0, building=1, item="ingredientA", rate=Fraction(6)),
        LaneEnd(block=0, building=5, item="ingredientA", rate=Fraction(3)),
    ]
    assert sum(t.rate for t in tails) == Fraction(9)


def test_boundary_lanes_falls_back_to_even_split_when_any_tail_lacks_a_strip():
    # Tail A's strip still carries two machines behind it -- a weighted split
    # would favour it 2:1 over tail B -- but tail B lost its strip provenance,
    # and no sorter in this fixture names a machine, so there is nothing left
    # to weight by and the WHOLE side falls back to an even split.
    placement = _two_tail_placement(strip_b=None)
    sub = _spec_with_output("ingredientA", Fraction(8))
    tails, _heads = boundary_lanes(placement, sub, block=0)
    assert tails == [
        LaneEnd(block=0, building=1, item="ingredientA", rate=Fraction(4)),
        LaneEnd(block=0, building=5, item="ingredientA", rate=Fraction(4)),
    ]
    assert sum(t.rate for t in tails) == Fraction(8)


def _stripless_docked_placement() -> Placement:
    """Two strip-less output tails, docked by two and by one machine.

    This is the shape a solved FREEFORM block actually hands the contract: its
    boundary belts are router trunks, so ``owner_strip`` is ``None`` on every
    one of them, and the only surviving record of what stands behind a lane is
    which machines' sorters put onto it.
    """
    b = PlacedBuilding
    belt = dict(item_id=BELT, model_index=0, carries_item="ingredientA")
    machine = dict(item_id=9999, model_index=0, recipe_id=100)
    return Placement(
        buildings=(
            b(**machine, x=0, y=1),  # 0
            b(**machine, x=1, y=1),  # 1
            b(**machine, x=4, y=1),  # 2
            b(item_id=SORTER, model_index=0, x=0, y=0, input_obj=0, output_obj=6),  # 3
            b(item_id=SORTER, model_index=0, x=1, y=0, input_obj=1, output_obj=6),  # 4
            b(item_id=SORTER, model_index=0, x=4, y=0, input_obj=2, output_obj=8),  # 5
            b(**belt, x=0, y=0, output_obj=7),  # 6: tail A's run, head tile
            b(**belt, x=1, y=0),  # 7: tail A
            b(**belt, x=4, y=0, output_obj=9),  # 8: tail B's run, head tile
            b(**belt, x=5, y=0),  # 9: tail B
        )
    )


def test_boundary_lanes_weights_stripless_tails_by_the_machines_docked_on_them():
    # Two machines put onto tail A's run and one onto tail B's, so tail A
    # carries two thirds of the block's output.  Splitting this evenly is what
    # `flow.conservation` convicts on the composed canvas: the assignment then
    # promises tail B more than the one machine behind it can make.
    placement = _stripless_docked_placement()
    sub = _spec_with_output("ingredientA", Fraction(9))
    tails, _heads = boundary_lanes(placement, sub, block=0)
    assert tails == [
        LaneEnd(block=0, building=7, item="ingredientA", rate=Fraction(6)),
        LaneEnd(block=0, building=9, item="ingredientA", rate=Fraction(3)),
    ]
    assert sum(t.rate for t in tails) == Fraction(9)


def _stripless_head_placement() -> Placement:
    """Two strip-less entry heads, drawn by two machines and by one."""
    b = PlacedBuilding
    belt = dict(item_id=BELT, model_index=0, carries_item="ingredientB")
    machine = dict(item_id=9999, model_index=0, recipe_id=100)
    return Placement(
        buildings=(
            b(**machine, x=0, y=1),  # 0
            b(**machine, x=1, y=1),  # 1
            b(**machine, x=4, y=1),  # 2
            b(item_id=SORTER, model_index=0, x=0, y=0, input_obj=7, output_obj=0),  # 3
            b(item_id=SORTER, model_index=0, x=1, y=0, input_obj=7, output_obj=1),  # 4
            b(item_id=SORTER, model_index=0, x=4, y=0, input_obj=9, output_obj=2),  # 5
            b(**belt, x=0, y=0, output_obj=7),  # 6: head A
            b(**belt, x=1, y=0),  # 7: tail of head A's run
            b(**belt, x=4, y=0, output_obj=9),  # 8: head B
            b(**belt, x=5, y=0),  # 9: tail of head B's run
        )
    )


def _spec_with_external(item: str, rate: Fraction) -> BuildSpec:
    return BuildSpec(
        groups=(),
        external_inputs={item: rate},
        outputs={},
        surplus_outputs={},
        belt_item_id="conveyor-belt-1",
        belt_items_per_second=Fraction(6),
        belt_upgrades=(),
        sorter_item_ids=("sorter-1",),
        belt_stack=1,
        sorter_pick_stacks=(1,),
        sorter_place_stacks=(1,),
        piler_unlocked=False,
        label="provenance-test",
    )


def test_boundary_lanes_weights_stripless_heads_by_the_machines_drawing_from_them():
    placement = _stripless_head_placement()
    sub = _spec_with_external("ingredientB", Fraction(9))
    _tails, heads = boundary_lanes(placement, sub, block=0)
    assert heads == [
        LaneEnd(block=0, building=6, item="ingredientB", rate=Fraction(6)),
        LaneEnd(block=0, building=8, item="ingredientB", rate=Fraction(3)),
    ]
    assert sum(h.rate for h in heads) == Fraction(9)


def test_port_host_boundary_lane_receives_its_share_of_assigned_supply():
    """A host's output-side consumer must still back its ownerless entry lane."""
    host = catalog.building(catalog.ENERGY_EXCHANGER_ID)
    assembler = catalog.building(2303)
    belt = catalog.building(BELT)
    sorter = catalog.building(SORTER)
    b = PlacedBuilding
    placement = Placement(
        buildings=(
            b(
                item_id=BELT,
                model_index=belt.model_index,
                x=0,
                y=0,
                output_obj=1,
                carries_item="ingredientB",
            ),
            b(
                item_id=host.item_id,
                model_index=host.model_index,
                x=1,
                y=0,
                width=host.width,
                height=host.height,
            ),
            b(item_id=BELT, model_index=belt.model_index, x=10, y=0, input_obj=1),
            b(item_id=SORTER, model_index=sorter.model_index, x=10, y=0, input_obj=2, output_obj=4),
            b(item_id=2303, model_index=assembler.model_index, x=10, y=2, recipe_id=100),
            b(item_id=BELT, model_index=belt.model_index, x=20, y=0, carries_item="ingredientB"),
            b(item_id=SORTER, model_index=sorter.model_index, x=20, y=0, input_obj=5, output_obj=7),
            b(item_id=2303, model_index=assembler.model_index, x=20, y=2, recipe_id=100),
        )
    )
    _tails, heads = boundary_lanes(
        placement, _spec_with_external("ingredientB", Fraction(6)), block=1
    )
    assert heads == [
        LaneEnd(block=1, building=0, item="ingredientB", rate=Fraction(3)),
        LaneEnd(block=1, building=5, item="ingredientB", rate=Fraction(3)),
    ]
    flows = assign_lanes(
        [Cut("ingredientB", 0, 1, Fraction(6))],
        {0: [_end(0, 0, "ingredientB", 6)]},
        {1: heads},
    )
    assert {flow.dst.building: flow.rate for flow in flows} == {
        0: Fraction(3),
        5: Fraction(3),
    }
