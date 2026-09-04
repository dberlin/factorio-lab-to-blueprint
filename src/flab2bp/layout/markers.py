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


def mark_external_belts(placement: Placement, spec: BuildSpec) -> Placement:
    """Return ``placement`` with item icons on its external belt endpoints.

    Input lanes are marked at their heads and target or surplus output lanes at
    their tails. Internal lanes are left bare, since labelling every belt would
    bury the boundary signal.

    A belt whose ``carries_item`` is unknown, whose item has no DSP id, or which
    already has parameters is left untouched rather than given a guessed or
    destructive marker.
    """
    inputs = set(spec.external_inputs)
    outputs = set(spec.outputs) | set(spec.surplus_outputs)
    if not inputs and not outputs:
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

    if tuple(buildings) == placement.buildings:
        return placement

    stats = placement.stats.copy()
    if input_markers:
        stats["input_markers"] = input_markers
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
