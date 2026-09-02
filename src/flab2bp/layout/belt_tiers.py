"""Give each belt run the cheapest belt tier that carries what it measures.

The URL's belt is the floor and the fastest researched belt is the ceiling
(``BuildSpec.belt_tiers``).  Routing lays every belt at the floor; this pass
runs once on the emitted placement, measures every run with the validator's
own flow propagation, and raises a run to the cheapest tier that fits.  Runs
that fit the floor keep it, so faster belts appear only where a lane needs
them.  A run above the ceiling is set to the ceiling and left for
``flow.belt_capacity`` to refuse: splitting such a lane is the subject of the
multiple-belts design, not this pass.

Nothing here touches geometry.  Belt tiers share footprint, slope and
altitude rules, so the router has no reason to know the tier and the pass has
no reason to move anything.
"""

from __future__ import annotations

import dataclasses
from fractions import Fraction

from flab2bp.dsp import catalog
from flab2bp.layout.base import Placement, PlacementStats
from flab2bp.layout.validate import belt_run_demands
from flab2bp.spec import BuildSpec

__all__ = ["retier_belts"]


def retier_belts(placement: Placement, spec: BuildSpec) -> Placement:
    """Return ``placement`` with every belt run on the cheapest tier that fits."""
    tiers = [
        (catalog.get_item_id(tier.item_id), tier.item_id, tier.items_per_second)
        for tier in spec.belt_tiers
    ]
    if len(tiers) < 2:
        return placement
    floor_numeric = tiers[0][0]
    if floor_numeric is None:
        return placement

    runs, demands = belt_run_demands(placement, spec)
    buildings = list(placement.buildings)
    upgraded = 0
    used: set[str] = set()
    for index, run in enumerate(runs):
        demand = sum(demands.get(index, {}).values(), Fraction(0))
        chosen_numeric, chosen_id = floor_numeric, tiers[0][1]
        for numeric, item_id, speed in tiers:
            if numeric is None:
                continue
            chosen_numeric, chosen_id = numeric, item_id
            if speed >= demand:
                break
        if chosen_numeric == floor_numeric:
            continue
        model_index = catalog.building(chosen_numeric).model_index
        for i in run.indices:
            buildings[i] = dataclasses.replace(
                buildings[i], item_id=chosen_numeric, model_index=model_index
            )
        upgraded += 1
        used.add(chosen_id)

    stats: PlacementStats = {
        **placement.stats,
        "belt_runs_upgraded": float(upgraded),
        "belt_upgrade_tiers": sorted(used),
    }
    return dataclasses.replace(placement, buildings=tuple(buildings), stats=stats)
