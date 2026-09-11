"""The lane contract between two solved blocks.

A ``Cut`` (``hierarchy.partition``) names an item and a net rate crossing from
one block to another, but that is not enough to wire a belt: each block sizes
its own lanes independently from its own rates, and they do not agree in count
or in per-lane rate (README ``2026-09-06-exp-hierarchical`` section 1, "The
block interface is a LANE CONTRACT, not an item name" -- on ``zurl2``, ten of
eleven point-to-point cuts fail on lane-count mismatch alone).

This module turns a cut into the thing a router actually needs: an exact
transportation assignment from the producing block's rated output tails to the
consuming block's rated entry heads. Fan-out (one tail feeding several heads)
and fan-in (several tails filling one head) are both legal -- the composer
(``hierarchy.compose``, Task 5) treats a shared source port as one family of
taps and merges a second feed into an existing lane, so a ``LaneFlow`` is
simply one edge of the assignment, not a claim that one tail wires one head.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from fractions import Fraction

from flab2bp.dsp import catalog, params
from flab2bp.indexed.cargo_flow import BoundaryRateFlow, CargoDestination, SprayedCargoFlow
from flab2bp.layout import markers
from flab2bp.layout.base import Placement
from flab2bp.layout.buildings import Buildings
from flab2bp.layout.hierarchy.partition import Cut
from flab2bp.spec import BuildSpec, MachineGroup


@dataclass(frozen=True)
class LaneEnd:
    """One rated lane at a block's boundary."""

    block: int  # block index in the composed order
    building: int  # belt index INSIDE the block's own placement
    item: str
    rate: Fraction  # what this lane carries (tail) or wants (head)


@dataclass(frozen=True)
class LaneFlow:
    """One edge of the transportation assignment between two blocks' lanes."""

    item: str
    src: LaneEnd  # a tail on the producing block
    dst: LaneEnd  # a head on the consuming block
    rate: Fraction


class ContractError(ValueError):
    """A consuming block's entry lane cannot be filled from what is offered."""


def _machine_groups(buildings: Buildings, sub: BuildSpec) -> dict[int, MachineGroup]:
    """Resolve only recipe/building/mode identity, without a validation context."""
    identities: dict[tuple[int, int, tuple[int, ...]], MachineGroup] = {}
    ambiguous: set[tuple[int, int, tuple[int, ...]]] = set()
    mode_items = {entry.machine_item_id for entry in catalog.MODE_DRIVEN_MACHINE.values()}
    known = catalog.known_recipe_ids()
    for group in sub.groups:
        machine = catalog.get_item_id(group.machine_item_id)
        mode = catalog.MODE_DRIVEN_MACHINE.get(group.recipe_id)
        if machine is None or (mode is None and group.recipe_id not in known):
            continue
        key = (
            machine,
            0 if mode is not None else catalog.recipe_id(group.recipe_id),
            params.parameters_for(group.recipe_id) if mode is not None else (),
        )
        previous = identities.get(key)
        if previous is not None and (
            previous.inputs_per_machine != group.inputs_per_machine
            or previous.outputs_per_machine != group.outputs_per_machine
        ):
            ambiguous.add(key)
        identities[key] = group
    groups: dict[int, MachineGroup] = {}
    for i, building in enumerate(buildings.all()):
        is_mode = building.item_id in mode_items
        if not building.recipe_id and not is_mode:
            continue
        key = (
            building.item_id,
            0 if is_mode else building.recipe_id,
            building.parameters if is_mode else (),
        )
        if key not in identities or key in ambiguous:
            raise ContractError(f"machine {i}: boundary rates require an unambiguous spec group")
        groups[i] = identities[key]
    return groups


def _lane_belts(buildings: Buildings, index: int, item: str, *, puts_on: bool) -> set[int]:
    """Follow directed runs and compatible transfer sorters, once per belt."""
    records = buildings.all()
    item_id = catalog.get_item_id(item)
    pending = [index]
    seen: set[int] = set()
    while pending:
        start = pending.pop()
        if start in seen:
            continue
        run = buildings.belt_run(start, forward=not puts_on, through_any_host=True)
        for belt in run:
            if belt in seen:
                continue
            seen.add(belt)
            sorters = buildings.sorters_into(belt) if puts_on else buildings.sorters_out_of(belt)
            for sorter_index in sorters:
                sorter = records[sorter_index]
                if sorter.carries_item not in (None, item) or sorter.filter_id not in (0, item_id):
                    continue
                target = sorter.input_obj if puts_on else sorter.output_obj
                if (
                    target is not None
                    and target not in seen
                    and buildings.by_index(target) is not None
                    and catalog.is_belt(records[target].item_id)
                    and records[target].carries_item in (None, item)
                ):
                    pending.append(target)
    return seen


def _machines_on_lane(buildings: Buildings, index: int, item: str, *, puts_on: bool) -> set[int]:
    """Machine endpoints reached through directed transport and sorter transfers."""
    run = _lane_belts(buildings, index, item, puts_on=puts_on)
    records = buildings.all()
    item_id = catalog.get_item_id(item)
    machines: set[int] = set()
    for belt in run:
        sorters = buildings.sorters_into(belt) if puts_on else buildings.sorters_out_of(belt)
        for sorter_index in sorters:
            sorter = records[sorter_index]
            if sorter.carries_item not in (None, item) or sorter.filter_id not in (0, item_id):
                continue
            machine = sorter.input_obj if puts_on else sorter.output_obj
            if machine is not None and buildings.by_index(machine) is not None:
                machines.add(machine)
        port = records[belt].input_obj if puts_on else records[belt].output_obj
        if port is not None and buildings.by_index(port) is not None:
            machines.add(port)
    return machines


def _net_apportion(
    total: Fraction,
    buildings: Buildings,
    indices: list[int],
    item: str,
    groups: dict[int, MachineGroup],
    lane_machines: list[set[int]],
    *,
    puts_on: bool,
) -> list[Fraction]:
    """Reserve internal consumers before offering surplus or requesting deficits.

    The bipartite graph is directed reachability, not undirected components.
    Each producer/consumer owns one rate edge even if several lanes reach it.
    Exact rational flow chooses a feasible share at overlapping branches rather
    than charging an internal consumer equally to unrelated output lanes.
    """
    supply = {
        i: g.outputs_per_machine[item] for i, g in groups.items() if item in g.outputs_per_machine
    }
    demand = {
        i: g.inputs_per_machine[item] for i, g in groups.items() if item in g.inputs_per_machine
    }
    allocation = BoundaryRateFlow(supply, demand, puts_on=puts_on)
    for lane, machines in zip(indices, lane_machines, strict=True):
        if puts_on:
            allocation.connect_lane(lane, machines & supply.keys())
        else:
            allocation.connect_lane(lane, machines & demand.keys())
    allocation.set_boundary_rate(total)
    records = buildings.all()
    item_id = catalog.get_item_id(item)
    for machine in supply:
        reached: set[int] = set()
        starts = {
            i
            for i in buildings.by_input_obj(machine)
            if catalog.is_belt(records[i].item_id) and records[i].carries_item in (None, item)
        }
        for sorter_index in buildings.sorters_out_of(machine):
            sorter = records[sorter_index]
            if sorter.carries_item not in (None, item) or (
                sorter.filter_id and sorter.filter_id != item_id
            ):
                continue
            target = sorter.output_obj
            if target is None or buildings.by_index(target) is None:
                continue
            if catalog.is_belt(records[target].item_id):
                if records[target].carries_item in (None, item):
                    starts.add(target)
            else:
                reached.add(target)
        for start in starts:
            reached.update(_machines_on_lane(buildings, start, item, puts_on=False))
        allocation.connect_internal(machine, reached & demand.keys())
    required = sum(demand.values(), Fraction(0)) + (total if puts_on else Fraction(0))
    delivered, rates = allocation.allocate(indices)
    if delivered != required:
        raise ContractError(
            f"{item}: connected machines cannot meet internal demand and boundary rate {total}"
        )
    if sum(rates, Fraction(0)) != total:
        raise ContractError(f"{item}: boundary rate {total} exceeds connected deficit")
    return rates


def _apportion(
    total: Fraction,
    buildings: Buildings,
    indices: list[int],
    item: str,
    groups: dict[int, MachineGroup],
    *,
    puts_on: bool = True,
) -> list[Fraction]:
    """Exact connected rates; count a shared machine only once across its lanes.

    Strip ownership is placement provenance, not a rate or connectivity proof.
    For pure boundary items each machine shares its rate across the endpoints
    that reach it. Mixed internal/boundary items instead reserve internal demand
    on directed paths before the requested exact boundary total is distributed.
    """
    if not total:
        return [Fraction(0) for _ in indices]
    lane_machines = [
        _machines_on_lane(buildings, i, item, puts_on=puts_on) & groups.keys() for i in indices
    ]
    if any(
        item in (g.inputs_per_machine if puts_on else g.outputs_per_machine)
        for g in groups.values()
    ):
        return _net_apportion(
            total, buildings, indices, item, groups, lane_machines, puts_on=puts_on
        )
    memberships: dict[int, int] = defaultdict(int)
    for machines in lane_machines:
        for machine in machines:
            memberships[machine] += 1
    shares = {
        machine: (
            groups[machine].outputs_per_machine if puts_on else groups[machine].inputs_per_machine
        ).get(item, Fraction(0))
        / count
        for machine, count in memberships.items()
    }
    weights = [sum((shares[m] for m in machines), Fraction(0)) for machines in lane_machines]
    available = sum(weights, Fraction(0))
    if not available or total > available or (not puts_on and total != available):
        raise ContractError(
            f"{item}: boundary rate {total} does not match connected machine rate {available}"
        )
    return [total * weight / available for weight in weights]


def _spray_cargo_weights(
    cargo: str,
    buildings: Buildings,
    sub: BuildSpec,
    groups: dict[int, MachineGroup],
    rides: dict[int, int],
    heads: list[int],
    tails: list[int],
) -> dict[int, Fraction]:
    """Route cargo through its first coater, retaining source-rate constraints.

    Once a path reaches a coater, later coaters do not consume another spray.
    A fresh branch joining between two coaters still reaches the second as its
    first. Condensing those paths to source/coater/consumer edges avoids a
    per-belt flow graph without losing directed reachability or exact rates.
    """
    records = buildings.all()
    cargo_id = catalog.get_item_id(cargo)
    coats_by_ride: dict[int, list[int]] = defaultdict(list)
    for coater, ride in rides.items():
        if records[ride].carries_item == cargo:
            coats_by_ride[ride].append(coater)
    requested = {
        machine
        for machine, group in groups.items()
        if group.is_proliferated and cargo in group.inputs_per_machine
    }
    tail_set = set(tails)

    def sorter_targets(index: int) -> list[int]:
        return [
            sorter.output_obj
            for i in buildings.sorters_out_of(index)
            if (sorter := records[i]).output_obj is not None
            and sorter.carries_item in (None, cargo)
            and sorter.filter_id in (0, cargo_id)
        ]

    def reached(starts: list[int], *, raw: bool) -> set[CargoDestination]:
        pending = list(starts)
        seen: set[int] = set()
        destinations: set[CargoDestination] = set()
        while pending:
            index = pending.pop()
            if index in seen or buildings.by_index(index) is None:
                continue
            seen.add(index)
            if index in groups:
                if cargo in groups[index].inputs_per_machine:
                    destinations.add(("consumer", index))
                continue
            building = records[index]
            if catalog.is_belt(building.item_id) and building.carries_item not in (None, cargo):
                continue
            if raw and index in coats_by_ride:
                destinations.update(("coater", i) for i in coats_by_ride[index])
                continue
            if index in tail_set:
                destinations.add(("tail", index))
            pending.extend(buildings.transport_successors(index))
            pending.extend(sorter_targets(index))
            if building.output_obj in groups:
                assert building.output_obj is not None
                pending.append(building.output_obj)
        return destinations

    allocation = SprayedCargoFlow()

    def destinations(starts: list[int], *, raw: bool) -> Iterator[CargoDestination]:
        for destination in sorted(reached(starts, raw=raw)):
            if raw and destination[0] == "consumer" and destination[1] in requested:
                continue
            yield destination

    required = Fraction(0)
    for machine, group in groups.items():
        if cargo in group.inputs_per_machine:
            rate = group.inputs_per_machine[cargo]
            allocation.require_consumer(machine, rate)
            required += rate
        if cargo in group.outputs_per_machine:
            starts = sorter_targets(machine)
            starts.extend(
                i for i in buildings.by_input_obj(machine) if catalog.is_belt(records[i].item_id)
            )
            allocation.offer_producer(
                machine, group.outputs_per_machine[cargo], destinations(starts, raw=True)
            )
    if heads:
        head_rates = _apportion(
            sub.external_inputs.get(cargo, Fraction(0)),
            buildings,
            heads,
            cargo,
            groups,
            puts_on=False,
        )
        for head, rate in zip(heads, head_rates, strict=True):
            allocation.offer_head(head, rate, destinations([head], raw=True))
    if tails:
        tail_rates = _apportion(
            sub.outputs.get(cargo, Fraction(0)),
            buildings,
            tails,
            cargo,
            groups,
        )
        for tail, rate in zip(tails, tail_rates, strict=True):
            allocation.require_tail(tail, rate)
            required += rate
    for ride, coaters in coats_by_ride.items():
        for coater in coaters:
            allocation.connect_coater(coater, destinations([ride], raw=False))
    delivered, weights = allocation.allocate(
        (coater for coaters in coats_by_ride.values() for coater in coaters), requested
    )
    if delivered != required:
        raise ContractError(
            f"{cargo}: connected source rates cannot meet sprayed cargo obligations"
        )
    return weights


def _spray_apportion(
    total: Fraction,
    placement: Placement,
    sub: BuildSpec,
    indices: list[int],
    item: str,
    groups: dict[int, MachineGroup],
    heads_by_item: dict[str, list[int]],
    tails_by_item: dict[str, list[int]],
) -> list[Fraction]:
    """Attribute coater supply through actual addon areas and sprayed cargo.

    A coater consumes one spray per cargo item (rates.adjust). Its selected
    tier's divisor cancels when splitting the exact sub-spec supply total.
    First-coater flow attributes cargo once; shared supply heads split that cost.

    Only sprayed boundaries pay for the validation context's indexed geometry
    and transport graph. No validation checks run; the context is used solely
    for the existing nearest-addon-belt authority, whose query does not read
    the unrelated width/altitude validation limits supplied below.
    """
    if not total:
        return [Fraction(0) for _ in indices]
    from flab2bp.layout import validate

    buildings = Buildings.of(placement)
    records = buildings.all()
    ctx = validate._context(placement, sub, None, 0, Fraction(0), False)
    cargo_items = {
        cargo
        for group in groups.values()
        if group.is_proliferated
        for cargo in group.inputs_per_machine
        if cargo in sub.spray_lanes
    }
    supplies: dict[int, int] = {}
    rides: dict[int, int] = {}
    for coater in buildings.by_item(catalog.SPRAY_COATER_ID):
        supply = validate._belt_in_addon_area(ctx, records[coater], area=1)
        ride = validate._belt_in_addon_area(ctx, records[coater], area=0)
        if supply is None or records[supply].carries_item != item or ride is None:
            continue
        cargo = records[ride].carries_item
        if cargo not in sub.spray_lanes:
            continue
        assert cargo is not None
        supplies[coater] = supply
        rides[coater] = ride
    weights: dict[int, Fraction] = defaultdict(Fraction)
    for cargo in sorted(cargo_items):
        for coater, weight in _spray_cargo_weights(
            cargo,
            buildings,
            sub,
            groups,
            rides,
            heads_by_item.get(cargo, []),
            tails_by_item.get(cargo, []),
        ).items():
            weights[coater] += weight
    heads_for: dict[int, list[int]] = defaultdict(list)
    for position, head in enumerate(indices):
        run = _lane_belts(buildings, head, item, puts_on=False)
        for coater, supply in supplies.items():
            if supply in run:
                heads_for[coater].append(position)
    cargo_total = sum(weights.values(), Fraction(0))
    if not cargo_total or any(coater not in heads_for for coater in weights):
        raise ContractError(f"{item}: coater demand has no connected boundary supply")
    rates = [Fraction(0) for _ in indices]
    for coater, weight in weights.items():
        heads = heads_for[coater]
        share = total * weight / cargo_total / len(heads)
        for position in heads:
            rates[position] += share
    return rates


def boundary_lanes(
    placement: Placement, sub: BuildSpec, block: int
) -> tuple[list[LaneEnd], list[LaneEnd]]:
    """(output tails, entry heads) of one solved block, rated.

    ``markers.output_belt_tails`` owns exposed producer-fed output terminals,
    including surplus branches beyond Splitters and excluding consumer-drawn
    tails. Input marker heads can still be fed by a producer sorter, so exclude
    those internal lanes here before rating the remaining boundary entries.

    A HEAD IS RATED AT THE BLOCK'S WHOLE DEFICIT, WHICH OVERSTATES WHAT THE CUTS
    OWE IT.  ``sub.external_inputs[item]`` is everything the block is short of,
    and for an item that is ALSO in the PARENT's ``external_inputs`` part of
    that share is belted in by the player at the parent level rather than by any
    cut.  ``partition.derive_cuts`` knows the difference -- it sizes each cut at
    ``min(surplus, deficit)`` -- but the heads rated here do not, so a naive
    assignment would ask the internal tails to cover the player's share too and
    raise :class:`ContractError` when they cannot.  That was the
    ``zurl2/all-products`` hydrogen refusal (``hydrogen: block 0 supply
    exhausted; block 7 entry lane 1042 short by 4319/1875 items/s``), reached
    only after every block placed.  :func:`allocate_cuts` is what now stands
    between these heads and :func:`assign_lanes`: it leaves a block's WHOLE
    demand for that item to the player -- not a remainder of it; a (block,
    item) is wired entirely or not at all -- instead of demanding the internal
    tails cover it too, exactly when the parent's ``external_inputs`` already
    promises the item from outside.
    """
    buildings = placement.buildings
    building_index = Buildings.of(placement)
    sorter_fed = {
        buildings[i].output_obj
        for i in building_index.sorters()
        if buildings[i].output_obj is not None
    }

    tail_indices: dict[str, list[int]] = defaultdict(list)
    for i in markers.output_belt_tails(placement):
        item = buildings[i].carries_item
        if item is not None:
            tail_indices[item].append(i)

    head_indices: dict[str, list[int]] = defaultdict(list)
    for i in markers.input_belt_heads(placement):
        item = buildings[i].carries_item
        if item is not None and i not in sorter_fed:
            head_indices[item].append(i)

    groups = _machine_groups(building_index, sub)

    tails = [
        LaneEnd(block=block, building=i, item=item, rate=rate)
        for item, indices in sorted(tail_indices.items())
        for i, rate in zip(
            indices,
            _apportion(
                sub.outputs.get(item, Fraction(0)),
                building_index,
                indices,
                item,
                groups,
                puts_on=True,
            ),
            strict=True,
        )
    ]
    heads = [
        LaneEnd(block=block, building=i, item=item, rate=rate)
        for item, indices in sorted(head_indices.items())
        for i, rate in zip(
            indices,
            (
                _spray_apportion(
                    sub.external_inputs.get(item, Fraction(0)),
                    placement,
                    sub,
                    indices,
                    item,
                    groups,
                    head_indices,
                    tail_indices,
                )
                if item.startswith("proliferator") and sub.spray_lanes
                else _apportion(
                    sub.external_inputs.get(item, Fraction(0)),
                    building_index,
                    indices,
                    item,
                    groups,
                    puts_on=False,
                )
            ),
            strict=True,
        )
    ]
    return tails, heads


def assign_lanes(
    cuts: list[Cut], tails: dict[int, list[LaneEnd]], heads: dict[int, list[LaneEnd]]
) -> list[LaneFlow]:
    """Exact transportation assignment from producer tails to consumer heads.

    Per item, tails are sorted by rate descending and heads by demand
    descending; the two lists are walked north-west-corner style, emitting one
    ``LaneFlow`` per positive amount assigned (at most ``n + m - 1`` flows per
    item across all its cuts). Raises :class:`ContractError` naming the item
    and the two blocks when a head cannot be filled from what its cuts' source
    blocks offer.
    """
    flows: list[LaneFlow] = []
    by_item: dict[str, list[Cut]] = defaultdict(list)
    for cut in cuts:
        by_item[cut.item].append(cut)
    for item, item_cuts in sorted(by_item.items()):
        # Pooled across every cut of this item, not solved cut-by-cut: `derive_cuts`
        # emits one `Cut` per (surplus block, deficit block) PAIR, so an item with
        # several producing or consuming blocks has several cuts here, and their
        # tails/heads must be assigned together for fan-out/fan-in to work at all.
        supply = sorted(
            (t for src in {c.src for c in item_cuts} for t in tails.get(src, ()) if t.item == item),
            key=lambda t: (-t.rate, t.block, t.building),
        )
        demand = sorted(
            (h for dst in {c.dst for c in item_cuts} for h in heads.get(dst, ()) if h.item == item),
            key=lambda h: (-h.rate, h.block, h.building),
        )
        left: dict[LaneEnd, Fraction] = {t: t.rate for t in supply}
        i = 0
        for head in demand:
            want = head.rate
            while want > 0 and i < len(supply):
                tail = supply[i]
                take = min(want, left[tail])
                if take > 0:
                    flows.append(LaneFlow(item=item, src=tail, dst=head, rate=take))
                    left[tail] -= take
                    want -= take
                if left[tail] == 0:
                    i += 1
            if want > 0:
                srcs = sorted({c.src for c in item_cuts})
                src_label = ", ".join(str(s) for s in srcs) if len(srcs) > 1 else str(srcs[0])
                raise ContractError(
                    f"{item}: block {src_label} supply exhausted; "
                    f"block {head.block} entry lane {head.building} short by {want} items/s"
                )
    return flows


@dataclass(frozen=True)
class CutAllocation:
    """A wired assignment, plus what was left for the player instead."""

    flows: list[LaneFlow]
    #: (block index, item) pairs whose entry heads are left to the player.
    player_fed: frozenset[tuple[int, str]]


def allocate_cuts(
    spec: BuildSpec,
    cuts: list[Cut],
    tails: dict[int, list[LaneEnd]],
    heads: dict[int, list[LaneEnd]],
) -> CutAllocation:
    """Wire what the internal supply covers; leave a both-fed block's whole
    demand to the player instead of demanding the tails stretch to cover it.

    Per item, ``S`` is the total internal supply -- the tails of every block
    the cuts name as a producer.  Consumer blocks are visited IN BLOCK-INDEX
    ORDER and served WHOLE OR NOT AT ALL: a block is served only while what is
    left of ``S`` still covers its whole deficit ``D_b``.  That makes which
    blocks get served DETERMINISTIC AND ORDER-STABLE rather than dependent on
    whichever one a less careful pass happened to reach first -- but it is
    FIRST-FIT, not a suffix rule: the pass does not stop at the first block it
    cannot serve, so a later SMALL block is still served out of what a skipped
    earlier LARGE one left behind.  A block that cannot be served is handed to
    the player -- its heads are simply never offered to :func:`assign_lanes` --
    exactly when ``item`` is one the parent spec already belts in
    (``spec.external_inputs``).  Otherwise nothing supplies that head at all,
    and that is a genuine :class:`ContractError`.
    """
    by_item: dict[str, list[Cut]] = defaultdict(list)
    for cut in cuts:
        by_item[cut.item].append(cut)

    player_fed: set[tuple[int, str]] = set()
    served_heads: dict[int, list[LaneEnd]] = defaultdict(list)
    for item, item_cuts in sorted(by_item.items()):
        supply_blocks = sorted({c.src for c in item_cuts})
        supply = sum(
            (t.rate for src in supply_blocks for t in tails.get(src, ()) if t.item == item),
            Fraction(0),
        )
        consumer_blocks = sorted({c.dst for c in item_cuts})
        remaining = supply
        for block in consumer_blocks:
            block_heads = [h for h in heads.get(block, ()) if h.item == item]
            deficit = sum((h.rate for h in block_heads), Fraction(0))
            # THE THRESHOLD IS MEASURED AGAINST AN OVERSTATED DEMAND, KNOWINGLY.
            # `boundary_lanes` rates a head at the block's WHOLE deficit (see
            # its docstring), and for an item the PARENT also belts in, part of
            # that share arrives from outside rather than from any cut --
            # `derive_cuts` knows the difference and sizes each cut at
            # `min(surplus, deficit)`.  So `deficit` here can exceed what the
            # cuts actually owe this block, and a block short of 100/s with 1/s
            # belted in by the parent and 99/s available internally is handed
            # ENTIRELY to the player while the producer's 99/s tail dead-ends.
            # The alternative would be to compare `remaining` against what
            # `derive_cuts` sized for this (src, dst) pair instead of against
            # the head sum.  It is deliberately NOT taken here: the plan
            # mandates whole-or-nothing per (block, item), so this is not a
            # contract violation but a coarser threshold, and changing it
            # changes WHICH builds become player-fed -- with no measurement on
            # this branch that could validate the change, the gate having seen
            # exactly one player-fed pair.  Controller Ruling R16.
            if remaining >= deficit:
                remaining -= deficit
                served_heads[block].extend(block_heads)
            elif item in spec.external_inputs:
                player_fed.add((block, item))
            else:
                raise ContractError(
                    f"{item}: internal supply {supply} cannot cover block {block}'s "
                    f"{deficit}; the parent does not belt it in"
                )

    flows = assign_lanes(cuts, tails, served_heads)
    return CutAllocation(flows=flows, player_fed=frozenset(player_fed))
