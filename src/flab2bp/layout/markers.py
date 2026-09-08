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

    Belt chains are forward-linked (``output_obj`` names the next tile), so a
    head has no belt predecessor. A belt whose other link names a Splitter is
    anchored at that Splitter's port, not at the factory boundary.
    """
    fed = {
        b.output_obj
        for b in placement.buildings
        if b.output_obj is not None and catalog.is_belt(b.item_id)
    }
    return [
        i
        for i, b in enumerate(placement.buildings)
        if catalog.is_belt(b.item_id)
        and i not in fed
        and not _links_splitter(placement.buildings, b)
    ]


def output_belt_tails(placement: Placement) -> list[int]:
    """Terminal belts of lanes fed directly by a producer sorter.

    A target item can also feed internal consumers. Those branch lanes carry the
    same item, so ``carries_item`` alone cannot distinguish them from the output
    port. The producer-fed trunk is the boundary lane; consumer branches begin
    at splitters and have no producer sorter of their own.
    """
    buildings = placement.buildings
    starts = {
        b.output_obj
        for b in buildings
        if catalog.is_sorter(b.item_id)
        and b.output_obj is not None
        and 0 <= b.output_obj < len(buildings)
        and catalog.is_belt(buildings[b.output_obj].item_id)
    }
    tails: set[int] = set()
    for start in starts:
        cursor = start
        seen: set[int] = set()
        while cursor not in seen:
            seen.add(cursor)
            if _links_splitter(buildings, buildings[cursor]):
                break
            following = buildings[cursor].output_obj
            if following is None:
                tails.add(cursor)
                break
            if not 0 <= following < len(buildings):
                break
            if not catalog.is_belt(buildings[following].item_id):
                break
            cursor = following
    return sorted(tails)


def self_loop_prime_heads(placement: Placement, spec: BuildSpec) -> dict[str, int]:
    """Loop-lane head belt index per self-loop item, for the prime icon.

    The loop lane is the run that both RECEIVES the item from a group's output
    sorter and DELIVERS it to that same group's input sorters.  Its head is
    where a hand or a temporary belt puts the seed in, so that is the tile that
    gets the icon -- and unlike an external input it is not in
    ``spec.external_inputs``, which is exactly why nothing marked it before.

    Identified purely from the placement's own sorter graph, never from the
    item name alone: the same item can also arrive on an unrelated external
    run feeding the very same group (``BuildSpec.planning_stack``'s docstring
    names ``universe-matrix``'s hydrogen as exactly that corpus case -- fed
    both externally and internally), and that run must not be mistaken for the
    loop.  A self-loop's group is every building whose ``recipe_id`` is the
    seed's DSP recipe id (belts and sorters never carry a real recipe id, so
    this alone selects machines); the loop's OUTPUT sorter is one fed directly
    from a group machine (``input_obj`` is a group machine) and the loop's
    INPUT sorter feeds directly into one (``output_obj`` is a group machine).
    Only a belt run that starts right after the former and, walking forward
    tile by tile, reaches the latter is the loop; a same-item run that starts
    anywhere else (an external head, another group's output) is passed over
    even though it carries an identical ``carries_item``.

    "Reaches the latter" covers TWO physical shapes, not one.  A single-machine
    loop's run is short enough that the belt's own forward chain
    (``output_obj``) terminates right at the input sorter -- the run ends
    there because nothing is downstream of it.  A multi-machine group's run
    does not: design section 1.2 decodes the real corpus case as ONE shared
    belt collecting from every machine's own output sorter and feeding every
    machine's own input sorter IN SERIES, each input sorter TAPPING the run at
    an interior tile (its ``input_obj`` names a belt mid-run) while the run's
    own forward chain carries on past that tap toward the boundary surplus
    tail.  A walk that only checked the chain's own terminal ``output_obj``
    missed every multi-machine loop outright -- measured against the real
    ``reforming-refine`` corpus case (20 machines): every one of its 20 input
    sorters taps an interior tile of a chain led by one of the group's own
    output sorters, so the loop demonstrably closes, and the untapped walk
    returned no head for it at all.  So the walk also checks, at every tile it
    visits, whether that tile is one of the group's own input sorters' source
    -- an interior tap closes the loop exactly as a terminal one does.
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
        taps = {buildings[i].input_obj for i in input_sorters} - {None}
        for start in output_sorters:
            head = buildings[start].output_obj
            if head is None or not 0 <= head < len(buildings):
                continue
            if not catalog.is_belt(buildings[head].item_id):
                continue
            cursor = head
            seen: set[int] = set()
            closes_loop = False
            while cursor not in seen:
                seen.add(cursor)
                if cursor in taps:
                    closes_loop = True
                    break
                following = buildings[cursor].output_obj
                if following is None or not 0 <= following < len(buildings):
                    break
                if catalog.is_belt(buildings[following].item_id):
                    cursor = following
                    continue
                closes_loop = following in input_sorters
                break
            if closes_loop:
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
