"""Exact topology result and independent material-flow ledger."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from fractions import Fraction

from flab2bp.layout import routing_domain as rd
from flab2bp.spec import BuildSpec

from .inventory import Inventory


@dataclass(frozen=True)
class SelectedTopology:
    inventory: Inventory
    rates: dict[int, Fraction]
    candidates: int
    added: int
    removed: int


def verify_rates(spec: BuildSpec, inventory: Inventory, rates: dict[int, Fraction]) -> None:
    """Independent ledger: no residual-flow implementation is reused here."""
    supplied: dict[tuple[int, str], Fraction] = defaultdict(Fraction)
    consumed: dict[tuple[int, str], Fraction] = defaultdict(Fraction)
    imports: dict[str, Fraction] = defaultdict(Fraction)
    exports: dict[str, Fraction] = defaultdict(Fraction)
    out_lanes: dict[tuple[int, str], Fraction] = defaultdict(Fraction)
    in_lanes: dict[tuple[int, str], Fraction] = defaultdict(Fraction)
    for coating in inventory.coatings:
        assert coating.supply_rate > 0
        assert coating.supply_rate <= spec.lane_capacity * spec.planning_stack(
            coating.proliferator, external=True
        )
        imports[coating.proliferator] += coating.supply_rate
    for demand in inventory.demands:
        rate = rates[demand.ordinal]
        assert rate > 0
        if demand.source is None:
            imports[demand.item] += rate
        else:
            supplied[demand.source.strip, demand.item] += rate
            out_lanes[demand.source.belt, demand.item] += rate
        if demand.sink is None:
            exports[demand.item] += rate
        else:
            consumed[demand.sink.strip, demand.item] += rate
            in_lanes[demand.sink.belt, demand.item] += rate
    assert dict(imports) == dict(spec.external_inputs)
    expected_exports = {
        item: spec.outputs.get(item, Fraction()) + spec.surplus_outputs.get(item, Fraction())
        for item in set(spec.outputs) | set(spec.surplus_outputs)
    }
    assert dict(exports) == expected_exports
    adapted = rd._adapt(spec)
    for index, strip in enumerate(inventory.strips):
        group = adapted[strip.group_key]
        for item, rate in group.outputs.items():
            assert supplied[index, item] == rate * strip.machines
        for item, rate in group.inputs.items():
            assert consumed[index, item] == rate * strip.machines
    stacks = rd._lane_stacks_for(spec)
    for (_, item), rate in out_lanes.items():
        assert rate <= spec.lane_capacity * stacks.produced[item]
    for (_, item), rate in in_lanes.items():
        assert rate <= spec.lane_capacity * stacks.consumed[item]
