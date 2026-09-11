"""Exact bounded transportation candidates with physical boundary resources."""

from __future__ import annotations

import json
from collections import defaultdict, deque
from dataclasses import replace
from fractions import Fraction
from typing import Literal

from flab2bp.layout import routing_domain as rd
from flab2bp.spec import BuildSpec

from .budget import TransportRefusal, WorkBudget
from .inventory import Inventory, TransportDemand
from .topology import SelectedTopology, verify_rates

Order = Literal["captured", "nearest-bank", "reverse"]

ORDERS: tuple[Order, ...] = ("captured", "nearest-bank", "reverse")

Node = tuple[str, int, str]


def external_roots(inventory: Inventory) -> dict[int, int]:
    membership = {
        (item, domain, belt): index
        for index, (item, domain, belts) in enumerate(inventory.shared_groups)
        for belt in belts
    }
    roots: dict[int, int] = {}
    for demand in inventory.demands:
        if demand.source is None:
            assert demand.sink is not None
            roots[demand.ordinal] = membership.get(
                (demand.item, demand.domain, demand.sink.belt),
                len(inventory.shared_groups) + demand.sink.belt,
            )
    return roots


def allocate(spec: BuildSpec, inventory: Inventory, budget: WorkBudget) -> dict[int, Fraction]:
    graph: dict[Node, dict[Node, Fraction]] = defaultdict(dict)
    capacities: dict[tuple[Node, Node], Fraction] = {}
    source: Node = ("source", 0, "")
    target: Node = ("target", 0, "")
    stacks = rd._lane_stacks_for(spec)
    groups = rd._adapt(spec)
    boundary = external_roots(inventory)
    counts: dict[str, int] = defaultdict(int)
    for strip in inventory.strips:
        counts[strip.group_key] += strip.machines
    if any(counts[key] != group.count for key, group in groups.items()):
        raise TransportRefusal("FROZEN_IDENTITY_MISMATCH", "physical strip machine counts differ")

    def add(left: Node, right: Node, capacity: Fraction) -> None:
        budget.check()
        if (left, right) in capacities:
            assert capacities[left, right] == capacity
            return
        assert capacity >= 0 and left not in graph[right]
        capacities[left, right] = capacity
        graph[left][right] = capacity
        graph[right][left] = Fraction()

    supplied = required = Fraction()
    for index, strip in enumerate(inventory.strips):
        group = groups[strip.group_key]
        for item, rate in group.outputs.items():
            amount = rate * strip.machines
            add(source, ("producer", index, item), amount)
            supplied += amount
        for item, rate in group.inputs.items():
            amount = rate * strip.machines
            add(("consumer", index, item), target, amount)
            required += amount
    coater_imports: dict[str, Fraction] = defaultdict(Fraction)
    for coating in inventory.coatings:
        coater_imports[coating.proliferator] += coating.supply_rate
    for item, rate in sorted(spec.external_inputs.items()):
        rate -= coater_imports[item]
        add(source, ("import", 0, item), rate)
        supplied += rate
    for item in sorted(set(spec.outputs) | set(spec.surplus_outputs)):
        rate = spec.outputs.get(item, Fraction()) + spec.surplus_outputs.get(item, Fraction())
        add(("export", 0, item), target, rate)
        required += rate
    assert supplied == required
    arcs: dict[int, tuple[Node, Node]] = {}
    for demand in inventory.demands:
        budget.check()
        if demand.source is None:
            left = ("external-root", boundary[demand.ordinal], demand.item)
            capacity = spec.lane_capacity * spec.planning_stack(demand.item, external=True)
            add(("import", 0, demand.item), left, capacity)
        else:
            left = ("source-port", demand.source.belt, demand.item)
            capacity = spec.lane_capacity * stacks.produced[demand.item]
            add(("producer", demand.source.strip, demand.item), left, capacity)
        if demand.sink is None:
            right = ("export", 0, demand.item)
        else:
            right = ("sink-port", demand.sink.belt, demand.item)
            add(
                right,
                ("consumer", demand.sink.strip, demand.item),
                spec.lane_capacity * stacks.consumed[demand.item],
            )
        arc: Node = ("arc", demand.ordinal, demand.item)
        add(left, arc, capacity)
        add(arc, right, capacity)
        arcs[demand.ordinal] = left, arc
    delivered = Fraction()
    reachable: dict[Node, Node | None] = {}
    while True:
        budget.check()
        reachable = {source: None}
        queue: deque[Node] = deque([source])
        while queue and target not in reachable:
            budget.check()
            current = queue.popleft()
            for neighbour, remaining in graph[current].items():
                budget.check()
                if remaining > 0 and neighbour not in reachable:
                    reachable[neighbour] = current
                    queue.append(neighbour)
        if target not in reachable:
            break
        budget.charge("augmentations")
        path: list[tuple[Node, Node]] = []
        current = target
        while current != source:
            previous = reachable[current]
            assert previous is not None
            path.append((previous, current))
            current = previous
        amount = min(graph[left][right] for left, right in path)
        for left, right in path:
            graph[left][right] -= amount
            graph[right][left] += amount
        delivered += amount
    if delivered != required:
        cut = [
            (left, right, value)
            for (left, right), value in capacities.items()
            if left in reachable and right not in reachable
        ]
        assert sum((value for _, _, value in cut), Fraction()) == delivered < required
        witness = {
            "delivered": str(delivered),
            "required": str(required),
            "reachable": sorted(reachable),
            "cut": [(left, right, str(value)) for left, right, value in cut],
        }
        raise TransportRefusal("CAPACITY_CUT", json.dumps(witness))
    return {ordinal: capacities[edge] - graph[edge[0]][edge[1]] for ordinal, edge in arcs.items()}


def select_topology(
    spec: BuildSpec, inventory: Inventory, order: Order, budget: WorkBudget
) -> SelectedTopology:
    budget.check()
    if inventory.prelinked:
        raise TransportRefusal("UNSUPPORTED_INTERFACE", "prelinked interfaces are not compiled")
    original = {(d.item, d.domain, d.source, d.sink) for d in inventory.demands}
    candidates = list(inventory.demands)
    budget.charge("arcs", len(candidates))
    sources = {d.source for d in candidates if d.source is not None}
    sinks = {d.sink for d in candidates if d.sink is not None}
    source_items = {d.source: (d.item, d.domain) for d in candidates if d.source is not None}
    sink_items = {d.sink: (d.item, d.domain) for d in candidates if d.sink is not None}
    for left in sorted(sources, key=lambda p: (p.strip, p.belt)):
        for right in sorted(sinks, key=lambda p: (p.strip, p.belt)):
            budget.check()
            item, domain = source_items[left]
            if (
                (item, domain) == sink_items[right]
                and left.strip != right.strip
                and (item, domain, left, right) not in original
            ):
                budget.charge("arcs")
                candidates.append(
                    TransportDemand(len(candidates), item, domain, left, right, "internal")
                )
    # Seeded recipes have a net-positive return stream, not a recurring external
    # input. Preserve that physical recurrence when reallocating captured arcs:
    # another producer carrying the same item cannot replace the recipe's return.
    seeded = {(seed.recipe_id, seed.item_id) for seed in spec.self_loop_seeds}
    if seeded:
        candidates = [
            demand
            for demand in candidates
            if demand.sink is None
            or (inventory.strips[demand.sink.strip].recipe_id, demand.item) not in seeded
            or (
                demand.source is not None
                and inventory.strips[demand.source.strip].recipe_id
                == inventory.strips[demand.sink.strip].recipe_id
            )
        ]
    candidates.sort(
        key=lambda d: (
            (d.item, d.domain, d.source, d.sink) not in original,
            d.item,
            d.source.strip if d.source else -1,
            d.source.belt if d.source else -1,
            d.sink.strip if d.sink else -1,
            d.sink.belt if d.sink else -1,
            d.ordinal,
        )
    )
    if order == "nearest-bank":
        candidates.sort(
            key=lambda d: (
                abs(d.source.strip // 5 - d.sink.strip // 5) if d.source and d.sink else 0,
                d.item,
                d.source.belt if d.source else -1,
                d.sink.belt if d.sink else -1,
                d.ordinal,
            )
        )
    elif order == "reverse":
        candidates.reverse()
    elif order != "captured":
        raise ValueError(order)
    candidate_inventory = replace(inventory, demands=tuple(candidates))
    allocated = allocate(spec, candidate_inventory, budget)
    demands: list[TransportDemand] = []
    rates: dict[int, Fraction] = {}
    for demand in candidates:
        if allocated[demand.ordinal] > 0:
            ordinal = len(demands)
            demands.append(replace(demand, ordinal=ordinal))
            rates[ordinal] = allocated[demand.ordinal]
    chosen = replace(inventory, demands=tuple(demands))
    verify_rates(spec, chosen, rates)
    roots = external_roots(chosen)
    loads: dict[tuple[int, str], Fraction] = defaultdict(Fraction)
    for demand in chosen.demands:
        if demand.source is None:
            loads[roots[demand.ordinal], demand.item] += rates[demand.ordinal]
    for (_, item), load in loads.items():
        assert load <= spec.lane_capacity * spec.planning_stack(item, external=True)
    selected = {(d.item, d.domain, d.source, d.sink) for d in demands}
    return SelectedTopology(
        chosen, rates, len(candidates), len(selected - original), len(original - selected)
    )
