"""Label the blueprint's external input belts with item icons.

A generated block is useless if you cannot tell which belt wants iron ore and
which wants coal.  DSP lets a belt carry an icon, so the entry point of every
externally-fed lane gets one.

Strategy-independent by construction: it reads only the ``Placement`` graph plus
the ``BuildSpec``'s external inputs, so it works for any layout backend and is
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


def input_belt_heads(placement: Placement) -> list[int]:
    """Indices of belts that nothing upstream feeds -- the block's entry points.

    Belt chains are forward-linked (``output_obj`` names the next tile), so a
    head is simply a belt no other belt points at.
    """
    fed = {
        b.output_obj
        for b in placement.buildings
        if b.output_obj is not None and catalog.is_belt(b.item_id)
    }
    return [
        i
        for i, b in enumerate(placement.buildings)
        if catalog.is_belt(b.item_id) and i not in fed
    ]


def mark_external_inputs(placement: Placement, spec: BuildSpec) -> Placement:
    """Return ``placement`` with an item icon on each external input belt head.

    Only lanes carrying something in ``spec.external_inputs`` are marked: those
    are the belts you must actually connect to something. Internal lanes are
    left bare, since labelling every belt would bury the signal.

    A belt whose ``carries_item`` is unknown, or whose item has no DSP id, is
    left untouched rather than given a guessed icon -- a plausible but wrong
    marker is worse than none, because it tells you to feed the wrong thing.
    """
    external = set(spec.external_inputs)
    if not external:
        return placement

    heads = set(input_belt_heads(placement))
    if not heads:
        return placement

    buildings = list(placement.buildings)
    marked = 0
    for i in heads:
        b = buildings[i]
        item = b.carries_item
        if item is None or item not in external or b.parameters:
            continue
        dsp_id = catalog.get_item_id(item)
        if dsp_id is None:
            continue
        buildings[i] = replace(b, parameters=catalog.belt_marker(dsp_id))
        marked += 1

    if not marked:
        return placement

    stats = placement.stats.copy()
    stats["input_markers"] = marked
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
