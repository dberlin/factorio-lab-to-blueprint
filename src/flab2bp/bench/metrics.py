"""Measure a ``Placement`` independently of whatever produced it.

Deliberately does not read ``Placement.stats``.  Both strategies populate stats
with their own accounting, and a comparison built on self-reported numbers is
not a comparison.  Everything here is derived from the buildings themselves.
"""

from __future__ import annotations

from flab2bp.bench.types import Metrics
from flab2bp.dsp import catalog
from flab2bp.layout.base import PlacedBuilding, Placement


def _is_machine(b: PlacedBuilding) -> bool:
    if catalog.is_belt(b.item_id) or catalog.is_sorter(b.item_id):
        return False
    if b.item_id in (catalog.SPLITTER_ID, catalog.TESLA_TOWER_ID):
        return False
    try:
        return catalog.building(b.item_id).occupies_tiles
    except KeyError:
        return False


def _occupies_tiles(b: PlacedBuilding) -> bool:
    """Whether this building reserves grid cells of its own.

    Belt-integrated buildings (sorters, splitters) share the tile of the belt
    they serve rather than reserving one -- a sorter straddles its two endpoints
    and a splitter sits exactly on the belt line.  Belt addons like the Spray
    Coater reserve nothing either.  Counting any of them as occupancy would
    report overlaps in blueprints the game itself produced.

    Belts themselves *do* occupy their tile, so they are excluded from the
    belt-integrated exemption here.
    """
    if catalog.is_sorter(b.item_id) or b.item_id == catalog.SPLITTER_ID:
        return False
    try:
        return catalog.building(b.item_id).occupies_tiles
    except KeyError:
        return True


def measure(placement: Placement) -> Metrics:
    buildings = placement.buildings
    if not buildings:
        return Metrics(0, 0, 0, 0, 0, 0, 0, 0, 0, 0)

    min_x, min_y, max_x, max_y = placement.bounds
    width = max_x - min_x + 1
    height = max_y - min_y + 1

    occupied: set[tuple[int, int]] = set()
    for b in buildings:
        if not _occupies_tiles(b):
            continue
        for x, y, _z in b.tiles():
            occupied.add((x, y))

    machines = sum(1 for b in buildings if _is_machine(b))
    belt_tiles = sum(1 for b in buildings if catalog.is_belt(b.item_id))
    sorters = sum(1 for b in buildings if catalog.is_sorter(b.item_id))
    towers = sum(1 for b in buildings if b.item_id == catalog.TESLA_TOWER_ID)

    machine_indices = {i for i, b in enumerate(buildings) if _is_machine(b)}
    direct_inserts = sum(
        1
        for b in buildings
        if catalog.is_sorter(b.item_id)
        and b.input_obj in machine_indices
        and b.output_obj in machine_indices
    )

    altitude_levels = len({b.z for b in buildings})

    return Metrics(
        area=width * height,
        used_tiles=len(occupied),
        width=width,
        height=height,
        machines=machines,
        belt_tiles=belt_tiles,
        sorters=sorters,
        direct_inserts=direct_inserts,
        towers=towers,
        altitude_levels=altitude_levels,
    )
