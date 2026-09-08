from __future__ import annotations

from dataclasses import replace
from fractions import Fraction

from flab2bp.dsp import catalog
from flab2bp.layout import junction, routing_domain
from flab2bp.layout.route_primitives import RoutePrimitives


def test_connector_witness_preserves_flat_sibling_merge_and_branch_docks() -> None:
    canvas = routing_domain._Canvas(
        belt_rules=replace(
            routing_domain._DEFAULT_BELT_RULES,
            max_z=Fraction(3),
            vertical_construction=False,
        )
    )
    path = (
        (0, 3, 1),
        (0, 2, 1),
        (0, 1, 2),
        (0, 1, 3),
        (0, 2, 3),
        (0, 3, 3),
        (0, 4, 3),
    )
    connector = next(
        candidate
        for candidate in junction.splitter_route_candidates(
            0, 0, 2, yaw=0.0, altitude_rules=canvas.belt_rules, carries_item="iron-ore"
        )
        if candidate.entry.dock == path[2] and candidate.exit.dock == path[3]
    )
    primitives = RoutePrimitives(canvas.belt_rules)
    primitives.witnesses[path[2], path[3]] = connector
    canvas.guard.update(path)
    canvas.guard.update(primitives.guards(path))

    merges = routing_domain._merge_frontier(canvas, {0: path}, (0,), primitives=primitives)
    # Extend the same flat suffix beyond the approach below it: a source tap
    # at y=3 would collide with the incoming level-1 belt through its support.
    branch_path = (*path, (0, 5, 3), (0, 6, 3))
    canvas.guard.update(branch_path)
    branches = routing_domain._merge_frontier(
        canvas,
        {0: branch_path},
        (0,),
        lambda x, y, _level: junction.site_is_clear(canvas.buildings, x, y),
        belt_prefab=(2002, catalog.building(2002).model_index),
        primitives=primitives,
    )

    # The ramp before the physical transfer must not erase the far flat carry
    # run. Merges attach on plane 3; model 40 source branches use plane 2.
    assert {(-1, 3, 3), (1, 3, 3)} <= merges
    assert {(-1, 5, 2), (1, 5, 2)} <= branches
