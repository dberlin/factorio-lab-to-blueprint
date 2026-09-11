from collections.abc import Callable
from dataclasses import replace
from fractions import Fraction

import pytest

from flab2bp.dsp import catalog, params
from flab2bp.layout.base import PlacedBuilding, Placement
from flab2bp.layout.hierarchy.contracts import ContractError, boundary_lanes
from flab2bp.spec import BuildSpec, MachineGroup


def mixed_case() -> tuple[Placement, BuildSpec]:
    groups = tuple(
        MachineGroup(
            recipe_id=recipe,
            machine_item_id="assembling-machine-1",
            count=count,
            inputs_per_machine={"processor": Fraction(rate)},
        )
        for recipe, count, rate in [("ray-receiver", 1, 1), ("sorter-4", 2, 3)]
    )
    machine = catalog.get_item_id("assembling-machine-1")
    assert machine is not None
    belt = next(iter(catalog.BELT_IDS))
    sorter = next(iter(catalog.SORTER_IDS))
    b = PlacedBuilding
    placement = Placement(
        buildings=(
            b(
                item_id=machine,
                model_index=0,
                recipe_id=catalog.recipe_id("ray-receiver"),
                x=0,
                y=0,
            ),
            b(item_id=machine, model_index=0, recipe_id=catalog.recipe_id("sorter-4"), x=1, y=0),
            b(item_id=machine, model_index=0, recipe_id=catalog.recipe_id("sorter-4"), x=2, y=0),
            b(item_id=belt, model_index=0, carries_item="processor", x=0, y=2),
            b(item_id=belt, model_index=0, carries_item="processor", x=2, y=2),
            b(item_id=sorter, model_index=0, input_obj=3, output_obj=0, x=0, y=1),
            b(item_id=sorter, model_index=0, input_obj=4, output_obj=1, x=1, y=1),
            b(item_id=sorter, model_index=0, input_obj=4, output_obj=2, x=2, y=1),
        )
    )
    return placement, BuildSpec(groups=groups, external_inputs={"processor": Fraction(7)})


class Fixture:
    def __init__(self) -> None:
        self.records: list[PlacedBuilding] = []
        self.groups: list[MachineGroup] = []

    def add(
        self,
        *,
        item_id: int,
        recipe_id: int = 0,
        parameters: tuple[int, ...] = (),
        carries_item: str | None = None,
        input_obj: int | None = None,
        output_obj: int | None = None,
    ) -> int:
        index = len(self.records)
        self.records.append(
            PlacedBuilding(
                model_index=0,
                x=index,
                y=0,
                item_id=item_id,
                recipe_id=recipe_id,
                parameters=parameters,
                carries_item=carries_item,
                input_obj=input_obj,
                output_obj=output_obj,
            )
        )
        return index

    def machine(self, recipe: str, *, takes: int = 0, makes: int = 0) -> int:
        group = MachineGroup(
            recipe_id=recipe,
            machine_item_id="assembling-machine-1",
            count=1,
            inputs_per_machine={"processor": Fraction(takes)} if takes else {},
            outputs_per_machine={"processor": Fraction(makes)} if makes else {},
        )
        self.groups.append(group)
        machine_id = catalog.get_item_id(group.machine_item_id)
        assert machine_id is not None
        return self.add(item_id=machine_id, recipe_id=catalog.recipe_id(recipe))

    def belt(self, *, input_obj: int | None = None) -> int:
        return self.add(
            item_id=next(iter(catalog.BELT_IDS)), carries_item="processor", input_obj=input_obj
        )

    def sorter(self, source: int, target: int) -> None:
        self.add(item_id=next(iter(catalog.SORTER_IDS)), input_obj=source, output_obj=target)

    def spec(self, *, takes: int = 0, makes: int = 0) -> BuildSpec:
        return BuildSpec(
            groups=tuple(self.groups),
            external_inputs={"processor": Fraction(takes)} if takes else {},
            outputs={"processor": Fraction(makes)} if makes else {},
        )

    def placement(self) -> Placement:
        return Placement(buildings=tuple(self.records))


def partial_overlap(*, output: bool) -> tuple[Placement, BuildSpec, list[int]]:
    f = Fixture()
    machines = [
        f.machine(recipe, **({"makes": rate} if output else {"takes": rate}))
        for recipe, rate in [("ray-receiver", 6), ("sorter-4", 2), ("logistics-distributor", 8)]
    ]
    lanes = [f.belt() for _ in range(3)]
    for lane, machine in [(0, 0), (1, 0), (0, 1), (2, 2)]:
        f.sorter(machines[machine], lanes[lane]) if output else f.sorter(
            lanes[lane], machines[machine]
        )
    return f.placement(), f.spec(**({"makes": 16} if output else {"takes": 16})), lanes


def internal_surplus() -> tuple[Placement, BuildSpec, list[int]]:
    f = Fixture()
    first = f.machine("ray-receiver", makes=10)
    second = f.machine("sorter-4", makes=3)
    consumer = f.machine("logistics-distributor", takes=9)
    first_tail, second_tail = f.belt(), f.belt()
    f.sorter(first, first_tail)
    f.sorter(first, consumer)
    f.sorter(second, second_tail)
    return f.placement(), f.spec(makes=4), [first_tail, second_tail]


def internally_supplied_head() -> tuple[Placement, BuildSpec, list[int]]:
    f = Fixture()
    producer = f.machine("ray-receiver", makes=4)
    shared = f.machine("sorter-4", takes=6)
    exclusive = f.machine("logistics-distributor", takes=3)
    lane_a, lane_b = f.belt(), f.belt()
    f.sorter(producer, shared)
    f.sorter(lane_a, shared)
    f.sorter(lane_b, exclusive)
    return f.placement(), f.spec(takes=5), [lane_a, lane_b]


def splitter_surplus() -> tuple[Placement, BuildSpec, list[int]]:
    f = Fixture()
    producer = f.machine("ray-receiver", makes=10)
    consumer = f.machine("sorter-4", takes=7)
    start = f.belt()
    splitter = f.add(item_id=catalog.SPLITTER_ID)
    f.records[start] = replace(f.records[start], output_obj=splitter)
    consumed = f.belt(input_obj=splitter)
    branch = f.belt(input_obj=splitter)
    tail = f.belt()
    f.records[branch] = replace(f.records[branch], output_obj=tail)
    f.sorter(producer, start)
    f.sorter(consumed, consumer)
    return f.placement(), f.spec(makes=3), [tail]


def rates(
    placement: Placement, spec: BuildSpec, lanes: list[int], *, output: bool
) -> list[Fraction]:
    tails, heads = boundary_lanes(placement, spec, 0)
    by_lane = {end.building: end.rate for end in (tails if output else heads)}
    return [by_lane[lane] for lane in lanes]


def test_mixed_recipe_inputs_use_exact_per_machine_rates() -> None:
    placement, spec = mixed_case()
    assert rates(placement, spec, [3, 4], output=False) == [1, 6]


def test_owner_strip_does_not_override_heterogeneous_connected_rates() -> None:
    placement, spec = mixed_case()
    placement = replace(
        placement, buildings=tuple(replace(b, owner_strip=0) for b in placement.buildings)
    )
    assert rates(placement, spec, [3, 4], output=False) == [1, 6]


def test_partial_overlap_consumers_do_not_steal_disjoint_head_supply() -> None:
    assert rates(*partial_overlap(output=False), output=False) == [5, 3, 8]


def test_partial_overlap_producers_are_not_counted_twice() -> None:
    assert rates(*partial_overlap(output=True), output=True) == [5, 3, 8]


def test_output_rates_reserve_the_connected_internal_consumers() -> None:
    assert rates(*internal_surplus(), output=True) == [1, 3]


def test_input_rates_subtract_only_reachable_internal_production() -> None:
    assert rates(*internally_supplied_head(), output=False) == [2, 3]


def test_splitter_surplus_excludes_consumer_drawn_and_sorter_fed_lanes() -> None:
    placement, spec, lanes = splitter_surplus()
    tails, heads = boundary_lanes(placement, spec, 0)
    assert [(end.building, end.rate) for end in tails] == [(lanes[0], Fraction(3))]
    assert heads == []


def test_output_target_scales_feasible_surplus_without_inflation() -> None:
    placement, spec, lanes = partial_overlap(output=True)
    spec = spec.model_copy(update={"outputs": {"processor": Fraction(8)}})
    assert rates(placement, spec, lanes, output=True) == [Fraction(5, 2), Fraction(3, 2), 4]


def test_missing_rate_identity_is_a_contract_error_not_machine_count_fallback() -> None:
    placement, spec = mixed_case()
    with pytest.raises(ContractError):
        boundary_lanes(placement, spec.model_copy(update={"groups": ()}), 0)


def test_understated_input_total_is_refused_not_spread_over_consumers() -> None:
    placement, spec = mixed_case()
    with pytest.raises(ContractError):
        boundary_lanes(
            placement, spec.model_copy(update={"external_inputs": {"processor": Fraction(5)}}), 0
        )


def shared_internal_surplus() -> tuple[Placement, BuildSpec, list[int]]:
    f = Fixture()
    shared = f.machine("ray-receiver", makes=6)
    independent = f.machine("sorter-4", makes=8)
    consumer = f.machine("logistics-distributor", takes=5)
    lanes = [f.belt() for _ in range(3)]
    f.sorter(shared, lanes[0])
    f.sorter(shared, lanes[1])
    f.sorter(shared, consumer)
    f.sorter(independent, lanes[2])
    return f.placement(), f.spec(makes=9), lanes


def upstream_consumer() -> tuple[Placement, BuildSpec, list[int]]:
    f = Fixture()
    producer = f.machine("ray-receiver", makes=6)
    consumer = f.machine("sorter-4", takes=5)
    early, late = f.belt(), f.belt()
    f.records[early] = replace(f.records[early], output_obj=late)
    f.sorter(producer, late)
    f.sorter(early, consumer)
    return f.placement(), f.spec(makes=1), [late]


def test_shared_outputs_reserve_internal_demand_before_splitting_surplus() -> None:
    got = rates(*shared_internal_surplus(), output=True)
    assert got[0] + got[1] == 1
    assert got[2] == 8


def test_internal_demand_upstream_of_production_cannot_back_output_contract() -> None:
    placement, spec, _ = upstream_consumer()
    with pytest.raises(ContractError):
        boundary_lanes(placement, spec, 0)


def test_ambiguous_machine_rates_are_refused() -> None:
    placement, spec = mixed_case()
    conflicting = spec.groups[0].model_copy(
        update={"inputs_per_machine": {"processor": Fraction(2)}}
    )
    spec = spec.model_copy(update={"groups": (*spec.groups, conflicting)})
    with pytest.raises(ContractError):
        boundary_lanes(placement, spec, 0)


def mode_case() -> tuple[Placement, BuildSpec, list[int]]:
    mode_recipe = next(
        name
        for name, entry in catalog.MODE_DRIVEN_MACHINE.items()
        if entry.machine_item_id == catalog.ENERGY_EXCHANGER_ID
    )
    f = Fixture()
    group = MachineGroup(
        recipe_id=mode_recipe,
        machine_item_id="energy-exchanger",
        count=1,
        inputs_per_machine={"processor": Fraction(3)},
    )
    f.groups.append(group)
    machine = f.add(
        item_id=catalog.ENERGY_EXCHANGER_ID, parameters=params.parameters_for(mode_recipe)
    )
    lane = f.belt()
    f.sorter(lane, machine)
    return f.placement(), f.spec(takes=3), [lane]


def test_mode_driven_inputs_are_resolved_by_building_and_parameter_mode() -> None:
    assert rates(*mode_case(), output=False) == [3]


def spray_case() -> tuple[Placement, BuildSpec, list[int]]:
    from flab2bp.layout import slots
    from flab2bp.spec import ProliferatorMode

    f = Fixture()
    heads: list[int] = []
    for number, (recipe, cargo_rate) in enumerate([("ray-receiver", 1), ("sorter-4", 3)]):
        machine = f.machine(recipe, takes=cargo_rate)
        f.groups[-1] = f.groups[-1].model_copy(update={"proliferator_mode": ProliferatorMode.SPEED})
        x, y = 20 + number * 20, 10
        cargo = f.belt()
        f.records[cargo] = replace(f.records[cargo], x=x, y=y)
        f.sorter(cargo, machine)
        drop = slots.addon_supply_cell(catalog.SPRAY_COATER_ID, x=x, y=y, z=0, yaw=0, area=1)
        approach = f.belt()
        supply = f.belt()
        f.records[approach] = replace(
            f.records[approach],
            x=drop[0] - 1,
            y=drop[1],
            z=Fraction(drop[2]),
            carries_item="proliferator-1",
            output_obj=supply,
        )
        f.records[supply] = replace(
            f.records[supply],
            x=drop[0],
            y=drop[1],
            z=Fraction(drop[2]),
            carries_item="proliferator-1",
        )
        coater = f.add(item_id=catalog.SPRAY_COATER_ID)
        f.records[coater] = replace(f.records[coater], x=x, y=y)
        heads.append(approach)
    spec = BuildSpec(
        groups=tuple(f.groups),
        external_inputs={"processor": Fraction(4), "proliferator-1": Fraction(1, 4)},
        spray_lanes={"processor": True},
    )
    return f.placement(), spec, heads


def test_spray_supply_heads_follow_unequal_cargo_throughput_not_coater_count() -> None:
    assert rates(*spray_case(), output=False) == [Fraction(1, 16), Fraction(3, 16)]


def test_spray_sub_specs_follow_input_throughput_not_machine_count() -> None:
    from flab2bp.layout.hierarchy.partition import Unit, sub_spec

    _, spec, _ = spray_case()
    blocks = [[Unit(i, group, 1)] for i, group in enumerate(spec.groups)]
    got = [
        sub_spec(spec, block, i).external_inputs["proliferator-1"] for i, block in enumerate(blocks)
    ]
    assert got == [Fraction(1, 16), Fraction(3, 16)]
    assert sum(got) == spec.external_inputs["proliferator-1"]


def shared_spray_supply() -> tuple[Placement, BuildSpec, list[int]]:
    placement, spec, heads = spray_case()
    records = list(placement.buildings)
    extra = len(records)
    records.append(replace(records[heads[0]], x=records[heads[0]].x - 1))
    return replace(placement, buildings=tuple(records)), spec, [*heads, extra]


def test_shared_proliferator_heads_divide_only_the_coaters_they_supply() -> None:
    assert rates(*shared_spray_supply(), output=False) == [
        Fraction(1, 32),
        Fraction(3, 16),
        Fraction(1, 32),
    ]


def test_spray_block_clones_preserve_the_global_exact_input_contract() -> None:
    from flab2bp.layout.hierarchy.partition import Unit, sub_spec

    _, spec, _ = spray_case()
    groups = (
        spec.groups[0].model_copy(update={"count": 3}),
        spec.groups[1].model_copy(update={"count": 2}),
    )
    spec = spec.model_copy(
        update={
            "groups": groups,
            "external_inputs": {"processor": Fraction(9), "proliferator-1": Fraction(9, 16)},
        }
    )
    blocks = [[Unit(0, groups[0], 2)], [Unit(1, groups[0], 1)], [Unit(2, groups[1], 2)]]
    got = [
        sub_spec(spec, block, i).external_inputs["proliferator-1"] for i, block in enumerate(blocks)
    ]
    assert got == [Fraction(1, 8), Fraction(1, 16), Fraction(3, 8)]
    assert sum(got) == spec.external_inputs["proliferator-1"]


def serial_spray_case(*, fresh_merge: bool = False) -> tuple[Placement, BuildSpec, list[int]]:
    placement, spec, heads = spray_case()
    records = list(placement.buildings)
    first, second = [i for i, b in enumerate(records) if b.carries_item == "processor"]
    records[first] = replace(records[first], output_obj=second)
    if fresh_merge:
        records.append(replace(records[second], x=records[second].x - 1, output_obj=second))
    return replace(placement, buildings=tuple(records)), spec, heads


def test_serial_coater_receives_no_duplicate_spray_obligation() -> None:
    assert rates(*serial_spray_case(), output=False) == [Fraction(1, 4), 0]


def test_downstream_coater_still_sprays_fresh_cargo_merging_after_first_coater() -> None:
    assert rates(*serial_spray_case(fresh_merge=True), output=False) == [
        Fraction(5, 32),
        Fraction(3, 32),
    ]


@pytest.mark.parametrize("output", [False, True])
def test_lane_obligation_follows_belt_to_belt_sorter_transfers(output: bool) -> None:
    f = Fixture()
    machine = f.machine("gear", makes=3 if output else 0, takes=0 if output else 3)
    trunk, branch = f.belt(), f.belt()
    f.sorter(trunk, branch)
    if output:
        f.sorter(machine, trunk)
        spec = f.spec(makes=3)
    else:
        f.sorter(branch, machine)
        spec = f.spec(takes=3)
    assert rates(f.placement(), spec, [branch if output else trunk], output=output) == [3]


def test_internal_transfer_consumption_is_reserved_before_boundary_surplus() -> None:
    f = Fixture()
    producer = f.machine("gear", makes=10)
    independent = f.machine("circuit-board", makes=3)
    consumer = f.machine("electric-motor", takes=9)
    trunk, branch, tail, independent_tail = [f.belt() for _ in range(4)]
    f.records[trunk] = replace(f.records[trunk], output_obj=tail)
    f.sorter(producer, trunk)
    f.sorter(trunk, branch)
    f.sorter(branch, consumer)
    f.sorter(independent, independent_tail)
    assert rates(f.placement(), f.spec(makes=4), [tail, independent_tail], output=True) == [1, 3]


def test_transfer_filter_cannot_back_a_different_cargo_obligation() -> None:
    f = Fixture()
    consumer = f.machine("gear", takes=3)
    trunk, branch = f.belt(), f.belt()
    f.sorter(trunk, branch)
    magnet = catalog.get_item_id("magnet")
    assert magnet is not None
    f.records[-1] = replace(f.records[-1], filter_id=magnet)
    f.sorter(branch, consumer)
    with pytest.raises(ContractError):
        boundary_lanes(f.placement(), f.spec(takes=3), 0)


def test_spray_supply_head_can_feed_its_coater_through_a_transfer_sorter() -> None:
    placement, spec, heads = spray_case()
    records = list(placement.buildings)
    for head in heads:
        supply = records[head].output_obj
        assert supply is not None
        records[head] = replace(records[head], output_obj=None)
        records.append(
            PlacedBuilding(
                item_id=next(iter(catalog.SORTER_IDS)),
                model_index=0,
                x=records[head].x,
                y=records[head].y,
                input_obj=head,
                output_obj=supply,
                carries_item="proliferator-1",
            )
        )
    assert rates(replace(placement, buildings=tuple(records)), spec, heads, output=False) == [
        Fraction(1, 16),
        Fraction(3, 16),
    ]


@pytest.mark.parametrize(
    ("case", "output", "expected"),
    [
        (internal_surplus, True, [Fraction(1, 7), Fraction(3, 7)]),
        (internally_supplied_head, False, [Fraction(2, 7), Fraction(3, 7)]),
        (spray_case, False, [Fraction(1, 112), Fraction(3, 112)]),
    ],
)
def test_internal_and_sprayed_cargo_flows_keep_nonintegral_rates_exact(
    case: Callable[[], tuple[Placement, BuildSpec, list[int]]],
    output: bool,
    expected: list[Fraction],
) -> None:
    placement, spec, lanes = case()
    groups = tuple(
        group.model_copy(
            update={
                "inputs_per_machine": {
                    item: rate / 7 for item, rate in group.inputs_per_machine.items()
                },
                "outputs_per_machine": {
                    item: rate / 7 for item, rate in group.outputs_per_machine.items()
                },
            }
        )
        for group in spec.groups
    )
    spec = spec.model_copy(
        update={
            "groups": groups,
            "external_inputs": {item: rate / 7 for item, rate in spec.external_inputs.items()},
            "outputs": {item: rate / 7 for item, rate in spec.outputs.items()},
        }
    )
    assert rates(placement, spec, lanes, output=output) == expected
