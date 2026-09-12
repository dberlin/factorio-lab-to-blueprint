from __future__ import annotations

from array import array
from dataclasses import replace
from fractions import Fraction

import pytest

from flab2bp.lab.techs import belt_rules_for_url
from flab2bp.layout import routing_domain
from flab2bp.layout.geometric_router import GeometricQuery, route
from flab2bp.layout.geometric_world import GeometricWorld
from flab2bp.layout.route_feedback import RouteFailureKind

_BELT_RULES = belt_rules_for_url("https://factoriolab.github.io/dsp/list?o=iron-ingot*60&v=11")


def test_ramp_via_alias_does_not_lower_the_route_start() -> None:
    bounds = (0, 0, 2, 0)
    canvas = routing_domain._Canvas(
        limit=bounds, belt_rules=replace(_BELT_RULES, vertical_construction=False)
    )
    start, goal = (1, 0, 1), (0, 0, 0)
    free = {start, (2, 0, 1), goal}
    canvas.guard.update(
        (x, 0, level)
        for x in range(3)
        for level in range(canvas.levels)
        if (x, 0, level) not in free
    )

    result = routing_domain._astar(canvas, [start], {goal}, {}, 1.0, bounds)

    assert result.path is not None
    profile = routing_domain._altitude_profile(result.path, ramped=canvas.ramped)
    assert profile is not None
    assert profile[0] == start[2] * routing_domain._LEVEL_HEIGHT
    assert profile[-1] == goal[2] * routing_domain._LEVEL_HEIGHT
    assert all(
        routing_domain._legal_link(*a[:2], za, *b[:2], zb, ramped=canvas.ramped)
        for a, b, za, zb in zip(result.path, result.path[1:], profile, profile[1:], strict=False)
    )


def test_unavoidable_goal_history_keeps_a_short_route_within_budget() -> None:
    world = GeometricWorld(
        nx=4,
        ny=1,
        nz=1,
        gx0=0,
        gy0=0,
        flags=bytearray([1] * 4),
        history=array("d", (0.0, 0.0, 0.0, 80.0)),
        transitions=(((1, 0, 0, False, 1.0), (-1, 0, 0, False, 1.0)),),
    )

    result = route(GeometricQuery(world, (0,), (3,), 1.0, 16))

    assert result.kind == "routed"
    assert result.path == (0, 1, 2, 3)
    assert result.cost == 83.0
    assert result.metrics["charged_work"] <= 16


def test_interval_search_keeps_interior_optimum_when_occupancy_changes() -> None:
    # The cheap path changes levels at x=4 inside an affine arrival interval.
    # Considering only its endpoints and the goal's x chooses the 7.5 bypass.
    world = GeometricWorld(
        nx=9,
        ny=1,
        nz=3,
        gx0=0,
        gy0=0,
        flags=bytearray([1] * 27),
        history=None,
        transitions=(
            ((1, 0, 0, False, 1.25), (-1, 0, 0, False, 1.25), (2, 0, 1, True, 3.0)),
            ((1, 0, 0, False, 1.25), (-1, 0, 0, False, 1.25)),
            (
                (1, 0, 0, False, 0.5),
                (-1, 0, 0, False, 0.5),
                (0, 0, -2, False, 2.0),
                (6, 0, -1, False, 7.5),
            ),
        ),
    )
    query = GeometricQuery(world, (2,), (19,), 1.0, 10_000)

    assert route(query).cost == 7.0

    # Reusing the movement topology must not retain the now-blocked ramp via.
    world.flags[15] = 0
    assert route(query).cost == 7.5

    world.flags[15] = 1
    assert route(query).cost == 7.0


@pytest.mark.parametrize("shared_destination", [False, True])
def test_affine_incumbent_rounding_does_not_discard_a_cheaper_connector(
    shared_destination: bool,
) -> None:
    flags = bytearray(38)
    history = array("d", [0.0] * 38)
    for x in range(18):
        flags[2 * x] = 1
        if x:
            history[2 * x] = 0.1
    flags[1] = flags[37] = 1
    world = GeometricWorld(
        nx=19,
        ny=2,
        nz=1,
        gx0=0,
        gy0=0,
        flags=flags,
        history=history,
        transitions=(
            (
                (1, 0, 0, False, 1.0),
                (-1, 0, 0, False, 1.0),
                (0, 1, 0, False, 1.0),
                (0, -1, 0, False, 1.0),
            ),
        ),
    )
    # Seventeen independently priced landings are genuinely more expensive
    # than the connector, even though rounding the incumbent to double ties them.
    goals = (37,) if shared_destination else (34, 37)
    extras = {1: ((37, 18.7),)}
    if shared_destination:
        extras[34] = ((37, 0.0),)
    result = route(GeometricQuery(world, (0, 1), goals, 1.0, 10_000, extra_edges=extras))

    assert result.path == (1, 37)
    assert result.cost == 18.7


@pytest.mark.parametrize("occupied", [False, True])
def test_blocked_starts_keep_their_original_occupied_price_policy(occupied: bool) -> None:
    world = GeometricWorld(
        nx=3,
        ny=1,
        nz=1,
        gx0=0,
        gy0=0,
        flags=bytearray([0, 1, 0]),
        history=array("d", [1e30, 0.125, 5.0]),
        transitions=(((1, 0, 0, False, 1.0), (-1, 0, 0, False, 2.0)),),
    )
    result = route(GeometricQuery(world, (0, 2), (1,), 1.0, 100, charge_occupied_cells=occupied))

    assert result.path == ((2, 1) if occupied else (0, 1))
    assert result.cost == (7.125 if occupied else 1.125)


def test_reverse_weighted_ramp_keeps_the_original_via_plane_and_toll() -> None:
    world = GeometricWorld(
        nx=3,
        ny=1,
        nz=2,
        gx0=0,
        gy0=0,
        flags=bytearray([0, 1, 1, 0, 0, 1]),
        history=array("d", [4.0, 0.0, 2.0, 0.0, 0.0, 0.7]),
        transitions=(((2, 0, 1, True, 3.01),), ()),
    )
    query = GeometricQuery(world, (0, 1), (5,), 1.0, 100, charge_occupied_cells=True)
    result = route(query)

    assert result.path == (0, 2, 5)
    assert result.cost == pytest.approx(9.71)

    world.flags[2] = 0
    blocked = route(query)
    assert blocked.path is None
    assert blocked.co_reachable == ((0, 1, 2, 2),)


def test_goal_pocket_reports_incoming_ramp_via_owner_within_budget() -> None:
    bounds = (0, 0, 100, 100)
    canvas = routing_domain._Canvas(
        limit=bounds,
        belt_rules=replace(_BELT_RULES, max_z=Fraction(1), vertical_construction=False),
    )
    start, goal, via = (48, 50, 0), (50, 50, 1), (49, 50, 0)
    canvas.guard.update((x, y, 1) for x in range(101) for y in range(101) if (x, y, 1) != goal)
    canvas.guard.update({(51, 50, 0), (50, 49, 0), (50, 51, 0)})
    canvas.blocked[via] = routing_domain._TENTATIVE
    budget = {"left": 1024}

    result = routing_domain._astar(
        canvas, [start], {goal}, {}, 1.0, bounds, budget, blocking_owners={via: 7}
    )

    assert result.kind is RouteFailureKind.SEALED_POCKET
    assert result.wall == (via,)
    assert 0 < result.expansions < 1024
    assert budget["left"] == 1024 - result.expansions

    del canvas.blocked[via]
    opened = routing_domain._astar(canvas, [start], {goal}, {}, 1.0, bounds)
    assert opened.path is not None
    assert opened.path[0] == start
    assert opened.path[-1] == goal


def test_unequal_goal_history_preserves_the_cheapest_destination() -> None:
    bounds = (-10, -10, 10, 10)
    canvas = routing_domain._Canvas(limit=bounds)
    near, cheap = (0, 1, 0), (4, 0, 0)
    history = {near: 100.0, cheap: 4.0}
    grid = routing_domain._make_grid(canvas, bounds, bounds, history)

    result = routing_domain._astar(
        canvas, [(0, 0, 0)], {near, cheap}, history, 1.0, bounds, grid=grid
    )

    assert result.path == tuple((x, 0, 0) for x in range(5))


def test_detailed_search_charges_shared_budget_without_exceeding_its_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bounds = (0, 0, 7, 0)
    canvas = routing_domain._Canvas(
        limit=bounds, belt_rules=replace(_BELT_RULES, max_z=Fraction(0))
    )
    budget = {"left": 3}
    exhausted = routing_domain._astar(canvas, [(0, 0, 0)], {(7, 0, 0)}, {}, 1.0, bounds, budget)
    assert exhausted.path is None
    assert exhausted.kind is RouteFailureKind.BUDGET
    assert 0 < exhausted.expansions <= 3
    assert budget["left"] == 3 - exhausted.expansions

    monkeypatch.setattr(routing_domain, "_MAX_EXPANSIONS", 2)
    shared = {"left": 1000}
    capped = routing_domain._astar(canvas, [(0, 0, 0)], {(7, 0, 0)}, {}, 1.0, bounds, shared)
    assert capped.path is None
    assert capped.kind is RouteFailureKind.BUDGET
    assert 0 < capped.expansions <= 2
    assert shared["left"] == 1000 - capped.expansions


def test_expired_detailed_search_does_not_spend_shared_budget() -> None:
    bounds = (0, 0, 7, 0)
    canvas = routing_domain._Canvas(limit=bounds)
    budget = {"left": 1000}

    result = routing_domain._astar(
        canvas, [(0, 0, 0)], {(7, 0, 0)}, {}, 1.0, bounds, budget, deadline=0.0
    )

    assert result.path is None
    assert result.kind is RouteFailureKind.BUDGET
    assert result.expansions == 0
    assert budget["left"] == 1000


def test_search_from_unpadded_corner_does_not_wrap_into_other_columns() -> None:
    canvas = routing_domain._Canvas(
        belt_rules=replace(routing_domain._DEFAULT_BELT_RULES, max_z=Fraction(0))
    )
    canvas.blocked[(0, 1, 0)] = 0
    canvas.blocked[(1, 0, 0)] = 0
    box = (0, 0, 1, 1)
    grid = routing_domain._make_grid(canvas, box, box, {})

    result = routing_domain._astar(canvas, [(0, 0, 0)], {(1, 1, 0)}, {}, 1.0, box, grid=grid)

    assert result.path is None
    assert result.kind is RouteFailureKind.SEALED_POCKET


def test_returned_cost_is_certified_in_original_path_order() -> None:
    world = GeometricWorld(
        nx=3,
        ny=2,
        nz=1,
        gx0=0,
        gy0=0,
        flags=bytearray([1, 0, 1, 0, 1, 1]),
        history=array("d", [0.0, 0.0, 0.1, 0.0, 0.7, 0.0]),
        transitions=(((1, 0, 0, False, 1.0),),),
    )
    result = route(GeometricQuery(world, (0, 5), (4,), 1.0, 1000))

    assert result.path == (0, 2, 4)
    assert result.cost == 2.8


def test_overlapping_endpoints_need_no_work_to_certify_a_zero_edge_route() -> None:
    world = GeometricWorld(
        nx=6,
        ny=1,
        nz=1,
        gx0=0,
        gy0=0,
        flags=bytearray([1] * 6),
        history=None,
        transitions=(((1, 0, 0, False, 1.0), (-1, 0, 0, False, 1.0)),),
    )
    result = route(GeometricQuery(world, (2, 3, 4, 5), (0, 1, 2), 0.0, 1))

    assert result.path == (2,)
    assert result.cost == 0.0
    assert result.metrics["charged_work"] == 0
