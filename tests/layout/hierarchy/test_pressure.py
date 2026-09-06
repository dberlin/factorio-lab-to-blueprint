from fractions import Fraction

from flab2bp.layout.hierarchy import pressure
from flab2bp.layout.hierarchy.partition import Unit
from flab2bp.spec import BuildSpec, MachineGroup


def _chain() -> BuildSpec:
    """ore -> ingot -> gear, one machine each; ingot also feeds a second consumer."""
    g = [
        MachineGroup(
            recipe_id="ingot",
            machine_item_id="arc-smelter",
            count=2,
            inputs_per_machine={"ore": Fraction(1)},
            outputs_per_machine={"ingot": Fraction(1)},
        ),
        MachineGroup(
            recipe_id="gear",
            machine_item_id="assembling-machine-1",
            count=1,
            inputs_per_machine={"ingot": Fraction(1)},
            outputs_per_machine={"gear": Fraction(1)},
        ),
        MachineGroup(
            recipe_id="plate",
            machine_item_id="assembling-machine-1",
            count=1,
            inputs_per_machine={"ingot": Fraction(1)},
            outputs_per_machine={"plate": Fraction(1)},
        ),
    ]
    return BuildSpec(
        groups=tuple(g),
        external_inputs={"ore": Fraction(2)},
        outputs={"gear": Fraction(1), "plate": Fraction(1)},
        surplus_outputs={},
        belt_item_id="conveyor-belt-1",
        belt_items_per_second=Fraction(6),
        belt_upgrades=(),
        sorter_item_ids=("sorter-1",),
        belt_stack=1,
        sorter_pick_stacks=(1,),
        sorter_place_stacks=(1,),
        piler_unlocked=False,
        label="chain",
    )


def _chain_with_external(item: str) -> BuildSpec:
    """``_chain()``, with ``item`` ALSO belted in by the parent from outside.

    Same graph and the same rates as :func:`_chain` -- ``item`` is both
    produced inside the build and declared in ``external_inputs`` at 1/s, so a
    block short of ``item`` can be left to the player instead of raising
    ``ContractError``.
    """
    spec = _chain()
    return spec.model_copy(update={"external_inputs": {**spec.external_inputs, item: Fraction(1)}})


def test_recipe_depths_are_longest_paths_from_the_inputs():
    assert pressure.recipe_depths(_chain()) == {"ingot": 0, "gear": 1, "plate": 1}


def test_depth_profile_counts_items_and_lanes_crossing_each_cut():
    rows = pressure.depth_profile(_chain())
    assert [r["cut_after_depth"] for r in rows] == [0]
    assert rows[0]["item_pressure"] == 1  # ingot is the only crossing item
    assert rows[0]["lane_pressure"] == 1  # 2/s on a 6/s belt is one lane


def test_lanes_for_prices_a_lane_at_capacity_times_stack():
    spec = _chain()
    assert pressure.lanes_for(spec, "ingot", Fraction(6), external=False) == 1
    assert pressure.lanes_for(spec, "ingot", Fraction(7), external=False) == 2
    assert pressure.lanes_for(spec, "ingot", Fraction(0), external=False) == 0


def test_depth_pressure_blocks_cut_at_local_minima_and_keep_regions_whole():
    blocks, cut_after, profile = pressure.depth_pressure_blocks(_chain())
    assert cut_after == [0]
    assert sorted(len(b) for b in blocks) == [1, 2]
    assert all(isinstance(u, Unit) for b in blocks for u in b)
