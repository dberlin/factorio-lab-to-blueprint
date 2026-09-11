"""Label belts that cross the factory boundary with item icons.

A generated block is useless if you cannot tell which belt wants iron ore or
which output carries gears.  DSP lets a belt carry an icon, so every external
input head and output tail gets one.

Strategy-independent by construction: it reads only the ``Placement`` graph plus
the ``BuildSpec`` boundary items, so it works for any layout backend and is
applied once in the pipeline rather than in each strategy's emitter.

The icon encoding is measured, not guessed -- all 109 belt parameter blocks in
the real fixture corpus are exactly ``(item_id, 0)``, and every first word
resolves to a real item.  Icon ids are banded and the item band is below 12000,
so an item id is its own icon id.
"""

from __future__ import annotations

from dataclasses import replace

from flab2bp.dsp import catalog
from flab2bp.layout.base import PlacedBuilding, Placement
from flab2bp.layout.buildings import Buildings
from flab2bp.spec import BuildSpec


def _links_splitter(buildings: tuple[PlacedBuilding, ...], belt: PlacedBuilding) -> bool:
    """Whether either belt end is anchored to a Splitter port."""
    for peer in (belt.input_obj, belt.output_obj):
        if (
            peer is not None
            and 0 <= peer < len(buildings)
            and buildings[peer].item_id == catalog.SPLITTER_ID
        ):
            return True
    return False


def input_belt_heads(placement: Placement) -> list[int]:
    """Indices of genuinely exposed belt entry points.

    Heads have neither an incoming transport edge nor a native machine-port
    source named by ``input_obj``. Splitter port belts remain internal boundaries.
    """
    buildings = Buildings.of(placement)
    return [
        i
        for i in buildings.belts()
        if not buildings.transport_predecessors(i)
        and buildings.by_index(placement.buildings[i].input_obj) is None
        and not _links_splitter(placement.buildings, placement.buildings[i])
    ]


def output_belt_tails(placement: Placement) -> list[int]:
    """Exposed producer-fed terminals across Splitter and Piler transport.

    A surplus can leave the producer's trunk through a Splitter. Follow the
    directed belt run, then exclude consumer-drawn terminals and host-port
    tiles rather than treating every branch as an internal consumer lane.
    """
    buildings = placement.buildings
    building_index = Buildings.of(placement)
    reached: set[int] = set()
    sorter_drawn: set[int] = set()
    for machine in building_index.machines():
        for port_belt in building_index.by_input_obj(machine):
            if port_belt not in reached and catalog.is_belt(buildings[port_belt].item_id):
                reached.update(building_index.belt_run(port_belt, forward=True))
    for i in building_index.sorters():
        sorter = buildings[i]
        if sorter.input_obj is not None:
            sorter_drawn.add(sorter.input_obj)
        start = sorter.output_obj
        if (
            start is None
            or start in reached
            or building_index.by_index(start) is None
            or not catalog.is_belt(buildings[start].item_id)
        ):
            continue
        reached.update(building_index.belt_run(start, forward=True))
    return sorted(
        i
        for i in reached
        if buildings[i].output_obj is None
        and i not in sorter_drawn
        and not _links_splitter(buildings, buildings[i])
    )


def self_loop_prime_heads(placement: Placement, spec: BuildSpec) -> dict[str, int]:
    """Find a seed head reached from the same recipe group's own output.

    The directed transport walk crosses splitters, pilers and compatible
    transfer sorters, and accepts input sorters tapping interior belt tiles.
    Starting only at a group's own output excludes unrelated external lanes
    carrying the same item. Reachability locates the marker; it does not
    replace the independent steady-state flow certificate.
    """
    buildings = placement.buildings
    heads: dict[str, int] = {}
    if not spec.self_loop_seeds:
        return heads
    indexed = Buildings.of(placement)
    for seed in spec.self_loop_seeds:
        try:
            dsp_recipe = catalog.recipe_id(seed.recipe_id)
        except KeyError:
            continue
        group_machines = indexed.machines_for_recipe(dsp_recipe)
        if not group_machines:
            continue
        output_sorters = sorted(
            i
            for machine in group_machines
            for i in indexed.sorters_out_of(machine)
            if buildings[i].carries_item == seed.item_id
        )
        input_sorters = {
            i
            for machine in group_machines
            for i in indexed.sorters_into(machine)
            if buildings[i].carries_item == seed.item_id
        }
        if not output_sorters or not input_sorters:
            continue
        # Tiles an input sorter draws from directly -- an interior tap on a
        # shared multi-machine run closes the loop there, not only where the
        # run's own forward chain happens to terminate.
        taps = {source for i in input_sorters if (source := buildings[i].input_obj) is not None}
        for start in output_sorters:
            head = buildings[start].output_obj
            if head is None or not 0 <= head < len(buildings):
                continue
            if not catalog.is_belt(buildings[head].item_id):
                continue
            if indexed.transport_reaches_any(head, taps, seed.item_id):
                heads[seed.item_id] = head
                break
    return heads


def mark_external_belts(placement: Placement, spec: BuildSpec) -> Placement:
    """Return ``placement`` with item icons on its external belt endpoints.

    Input lanes are marked at their heads and target or surplus output lanes at
    their tails. A self-loop item's lane head (:func:`self_loop_prime_heads`)
    is marked too -- it is not an "external" belt at all, but the tile the
    player has to find is exactly the same problem, and leaving it bare is
    what made the reported blueprint's loop lane look like a forgotten input.
    Internal lanes are otherwise left bare, since labelling every belt would
    bury the boundary signal.

    A belt whose ``carries_item`` is unknown, whose item has no DSP id, or which
    already has parameters is left untouched rather than given a guessed or
    destructive marker.
    """
    inputs = set(spec.external_inputs)
    outputs = set(spec.outputs) | set(spec.surplus_outputs)
    prime_heads = self_loop_prime_heads(placement, spec)
    if not inputs and not outputs and not prime_heads:
        return placement

    buildings = list(placement.buildings)
    input_markers = 0
    if inputs:
        for i in input_belt_heads(placement):
            b = buildings[i]
            item = b.carries_item
            if item is None or item not in inputs or b.parameters:
                continue
            dsp_id = catalog.get_item_id(item)
            if dsp_id is None:
                continue
            buildings[i] = replace(b, parameters=catalog.belt_marker(dsp_id))
            input_markers += 1

    if outputs:
        for i in output_belt_tails(placement):
            b = buildings[i]
            item = b.carries_item
            if item is None or item not in outputs or b.parameters:
                continue
            dsp_id = catalog.get_item_id(item)
            if dsp_id is None:
                continue
            buildings[i] = replace(b, parameters=catalog.belt_marker(dsp_id))

    prime_markers = 0
    for item, i in prime_heads.items():
        b = buildings[i]
        if b.parameters:
            continue
        dsp_id = catalog.get_item_id(item)
        if dsp_id is None:
            continue
        buildings[i] = replace(b, parameters=catalog.belt_marker(dsp_id))
        prime_markers += 1

    if tuple(buildings) == placement.buildings:
        return placement

    stats = placement.stats.copy()
    if input_markers:
        stats["input_markers"] = input_markers
    if prime_markers:
        stats["self_loop_prime_markers"] = prime_markers
    return replace(placement, buildings=tuple(buildings), stats=stats)


def unmarked_external_inputs(placement: Placement, spec: BuildSpec) -> set[str]:
    """External inputs that ended up with no marked entry belt.

    Surfaced so a missing label is visible rather than silently absent: if this
    is non-empty, some input belt is unlabelled and whoever pastes the blueprint
    has to work out what it wants.
    """
    marked: set[str] = set()
    for i in input_belt_heads(placement):
        b: PlacedBuilding = placement.buildings[i]
        if b.parameters and b.carries_item:
            marked.add(b.carries_item)
    return set(spec.external_inputs) - marked
