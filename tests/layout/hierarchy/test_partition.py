from fractions import Fraction

from flab2bp.layout.freeform import plan_strips
from flab2bp.layout.hierarchy import partition
from flab2bp.layout.strip_variants import _logical_strip_plans
from flab2bp.spec import MachineMoveRecord
from tests.layout.hierarchy.test_pressure import _chain, _chain_with_external


def test_initial_partition_covers_every_machine_exactly_once():
    part = partition.initial_partition(_chain(), strip_cap=12)
    counted = {}
    for block in part.blocks:
        for u in block:
            counted[u.recipe] = counted.get(u.recipe, 0) + u.count
    assert counted == {"ingot": 2, "gear": 1, "plate": 1}


def test_cuts_are_read_off_net_balances_and_are_topological():
    part = partition.initial_partition(_chain(), strip_cap=12)
    assert {c.item for c in part.cuts} == {"ingot"}
    for c in part.cuts:
        assert c.src < c.dst  # producer block precedes consumer block
    # The two consumers share one block after the pressure cut, so there is one
    # cut carrying the whole 2/s ingot rate rather than one cut of 1/s each.
    assert sum(c.rate for c in part.cuts) == Fraction(2)


def test_sub_spec_declares_boundary_items_and_recomputes_flags():
    spec = _chain()
    part = partition.initial_partition(spec, strip_cap=12)
    consumer = next(b for b in part.blocks if any(u.recipe == "gear" for u in b))
    sub = partition.sub_spec(spec, consumer, 1)
    assert sub.external_inputs["ingot"] == sum(u.consumes("ingot") for u in consumer)
    assert "ore" not in sub.external_inputs
    assert sub.spray_lanes == {}
    assert sub.belt_required_edges == frozenset()


def test_composed_spec_matches_the_original_machine_counts():
    spec = _chain()
    part = partition.initial_partition(spec, strip_cap=12)
    built = partition.composed_spec(spec, part.blocks)
    assert built.machine_count == spec.machine_count
    assert built.external_inputs == spec.external_inputs


def test_partitioned_specs_preserve_machine_rank_provenance():
    move = MachineMoveRecord(
        recipe_id="ingot",
        from_machine="assembling-machine-2",
        to_machine="assembling-machine-1",
        count_before=2,
        count_after=2,
    )
    spec = _chain().model_copy(update={"machine_rank": "up-to", "machine_moves": (move,)})
    part = partition.initial_partition(spec, strip_cap=12)

    for block_index, block in enumerate(part.blocks):
        sub = partition.sub_spec(spec, block, block_index)
        assert sub.machine_rank == "up-to"
        assert sub.machine_moves == (move,)
    composed = partition.composed_spec(spec, part.blocks)
    assert composed.machine_rank == "up-to"
    assert composed.machine_moves == (move,)


def test_composed_spec_declares_player_fed_block_deficits():
    spec = _chain_with_external("ingot")
    part = partition.initial_partition(spec, strip_cap=2)
    built = partition.composed_spec(spec, part.blocks, player_fed={(1, "ingot")})
    consumer_deficit = sum(u.consumes("ingot") for u in part.blocks[1])
    assert built.external_inputs["ingot"] >= consumer_deficit


def test_a_block_over_the_strip_cap_is_split_by_agglomeration():
    spec = _chain()
    whole = [partition.Unit(i, g, g.count) for i, g in enumerate(spec.groups)]
    assert partition.strip_count(spec, whole) >= 3
    part = partition.initial_partition(spec, strip_cap=2)
    assert all(partition.strip_count(spec, b) <= 2 for b in part.blocks)


def test_split_block_varies_the_cut_between_attempts():
    spec = _chain()
    block = [partition.Unit(i, g, g.count) for i, g in enumerate(spec.groups)]
    first = partition.split_block(block, attempt=0)
    second = partition.split_block(block, attempt=1)
    assert len(first) >= 2 and len(second) >= 2
    assert [sorted(u.recipe for u in b) for b in first] != [
        sorted(u.recipe for u in b) for b in second
    ]


def test_strip_count_is_the_packed_count_not_the_logical_plan_count(mall_all_products):
    spec, _vertical = mall_all_products
    part = partition.initial_partition(spec, strip_cap=10_000)  # no cap: seed blocks only
    block = max(part.blocks, key=lambda b: sum(u.count for u in b))
    logical = len(_logical_strip_plans(partition.sub_spec(spec, block, 0)))
    packed = partition.strip_count(spec, block)
    assert packed >= logical
    assert packed == len(plan_strips(partition.sub_spec(spec, block, 0)))


def test_split_block_of_one_unit_splits_the_count():
    spec = _chain()
    ingot = next(g for g in spec.groups if g.recipe_id == "ingot")
    children = partition.split_block([partition.Unit(0, ingot, 6)], attempt=0)
    assert sorted(sum(u.count for u in b) for b in children) == [3, 3]
    # agglomerate merges only on positive rate coupling; two shards of the same
    # recipe with no other units around them have none, so cap=2 yields three
    # untouched shards of 2 rather than a [2, 4] merge.
    children = partition.split_block([partition.Unit(0, ingot, 6)], attempt=1)
    assert sorted(sum(u.count for u in b) for b in children) == [2, 2, 2]
