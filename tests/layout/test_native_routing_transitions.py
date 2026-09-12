from __future__ import annotations

from array import array
from dataclasses import replace
from fractions import Fraction

import pytest

from flab2bp.layout import global_router, routing_domain
from flab2bp.layout.geometric_router import GeometricQuery, GeometricResult, route
from flab2bp.layout.geometric_world import GeometricTransition, GeometricWorld
from flab2bp.layout.route_feedback import FeedbackState, NetId, NetRole

type Transitions = tuple[tuple[GeometricTransition, ...], ...]


def _search(
    transitions: Transitions,
    flags: bytearray,
    start: int,
    goal: int,
    *,
    gh: int = 1,
    levels: int = 6,
    extra_edges: dict[int, tuple[tuple[int, float], ...]] | None = None,
) -> GeometricResult:
    world = GeometricWorld(
        nx=len(flags) // (gh * levels),
        ny=gh,
        nz=levels,
        gx0=0,
        gy0=0,
        flags=flags,
        history=None,
        transitions=transitions,
    )
    return route(
        GeometricQuery(
            world,
            (start,),
            (goal,),
            0.0,
            20_000,
            extra_edges={} if extra_edges is None else extra_edges,
        )
    )


@pytest.mark.parametrize("levels", [6, 27])
def test_zero_run_climbs_cross_original_four_plane_ceiling(levels: int) -> None:
    transitions: Transitions = tuple(
        ((0, 0, 1, False, 1.0),) if level + 1 < levels else () for level in range(levels)
    )
    # An admitted start may be unavailable. A direct climb must not add an
    # intermediate occupancy requirement at that source cell.
    result = _search(transitions, bytearray([0] + [1] * (levels - 1)), 0, levels - 1, levels=levels)
    assert result.kind == "routed"
    assert result.path == tuple(range(levels))
    assert result.cost == levels - 1


def test_supplied_directed_graph_does_not_gain_implicit_flat_moves() -> None:
    result = _search(((),) * 6, bytearray([1] * 12), 0, 6)
    assert result.kind == "exhausted"
    assert result.path is None


@pytest.mark.parametrize("blocked_via", [False, True])
def test_exact_ramp_via_and_direct_vertical_parents_are_preserved(blocked_via: bool) -> None:
    transitions: Transitions = (
        ((2, 0, 1, True, 3.0),),
        ((0, 0, 1, False, 1.0),),
        (),
        (),
        (),
        (),
    )
    flags = bytearray([1] * 18)
    flags[6] = not blocked_via
    result = _search(transitions, flags, 0, 14)
    if blocked_via:
        assert result.kind == "exhausted"
        assert result.path is None
    else:
        assert result.kind == "routed"
        assert result.path == (0, 6, 13, 14)
        assert result.cost == 4.0


def test_y_move_cannot_wrap_without_a_padded_border() -> None:
    transitions: Transitions = (((0, 1, 0, False, 1.0),), (), (), (), (), ())
    result = _search(transitions, bytearray([1] * 24), 6, 12, gh=2)
    assert result.kind == "exhausted"
    assert result.path is None


def test_ramp_cannot_read_a_via_outside_the_grid() -> None:
    transitions: Transitions = (((2, 0, 1, True, 3.0),), (), (), (), (), ())
    result = _search(transitions, bytearray([1] * 6), 0, 1)
    assert result.kind == "exhausted"
    assert result.path is None


@pytest.mark.parametrize(("dz", "start", "goal"), [(-1, 6, 5), (6, 0, 6)])
def test_level_move_cannot_wrap_into_another_column(dz: int, start: int, goal: int) -> None:
    transitions: Transitions = (((0, 0, dz, False, 1.0),), (), (), (), (), ())
    result = _search(transitions, bytearray([1] * 12), start, goal)
    assert result.kind == "exhausted"
    assert result.path is None


def test_directed_graph_requires_one_transition_group_per_level() -> None:
    with pytest.raises(ValueError):
        _search(((),), bytearray([1] * 6), 0, 1)


def test_competing_vertical_and_ramp_routes_choose_the_lower_cost() -> None:
    levels, gh, width = 6, 3, 5
    transitions: Transitions = tuple(
        tuple(
            [(dx, dy, 0, False, 1.0 + level / 4) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))]
            + ([(0, 0, 1, False, 1.5), (2, 0, 1, True, 3.0)] if level + 1 < levels else [])
            + ([(0, 0, -1, False, 1.5)] if level else [])
        )
        for level in range(levels)
    )
    flags = bytearray([1] * (width * gh * levels))
    for y in range(gh):
        for level in range(5):
            flags[(2 * gh + y) * levels + level] = 0
    start, goal = levels, (4 * gh + 1) * levels

    result = _search(transitions, flags, start, goal, gh=gh)

    # Four direct climbs, one two-tile ramp over the wall, one high flat
    # step, five descents, and one ground step: 6 + 3 + 2.25 + 7.5 + 1.
    assert result.kind == "routed"
    assert result.cost == 19.75
    assert result.path is not None
    assert result.path[0] == start and result.path[-1] == goal
    assert all(flags[cell] for cell in result.path)
    assert (2 * gh + 1) * levels + 5 in result.path


def test_sparse_connector_competes_with_vertical_moves() -> None:
    transitions: Transitions = tuple(
        ((0, 0, 1, False, 1.0),) if level < 5 else () for level in range(6)
    )
    result = _search(
        transitions,
        bytearray([1] * 12),
        0,
        11,
        extra_edges={0: ((11, 10.0),), 2: ((11, 1.0),)},
    )
    assert result.kind == "routed"
    assert result.path == (0, 1, 2, 11)
    assert result.cost == 3.0


def test_sparse_connector_does_not_invent_intermediate_belt_cells() -> None:
    flags = bytearray(18)
    flags[0] = flags[17] = 1
    result = _search(((),) * 6, flags, 0, 17, extra_edges={0: ((17, 4.0),)})
    assert result.kind == "routed"
    assert result.path == (0, 17)
    assert result.cost == 4.0


def test_sparse_connector_requires_available_landing() -> None:
    result = _search(((),) * 6, bytearray((1, 0, 0, 0, 0, 0)), 0, 5, extra_edges={0: ((5, 1.0),)})
    assert result.kind == "exhausted"
    assert result.path is None


@pytest.mark.parametrize(
    "extra_edges",
    [{-1: ((1, 1.0),)}, {6: ((1, 1.0),)}, {0: ((-1, 1.0),)}, {0: ((6, 1.0),)}],
)
def test_sparse_connector_endpoints_must_be_inside_the_grid(
    extra_edges: dict[int, tuple[tuple[int, float], ...]],
) -> None:
    with pytest.raises(ValueError):
        _search(((),) * 6, bytearray([1] * 6), 0, 1, extra_edges=extra_edges)


@pytest.mark.parametrize(("occupied", "expected_cost"), [(False, 35.0), (True, 85.0)])
def test_relaxed_prices_start_and_ramp_via_while_detailed_prices_only_landing(
    occupied: bool,
    expected_cost: float,
) -> None:
    world = GeometricWorld(
        3,
        1,
        2,
        0,
        0,
        bytearray([1] * 6),
        array("d", (2.0, 0.0, 7.0, 0.0, 0.0, 3.0)),
        (((2, 0, 1, True, 3.0),), ()),
    )
    result = route(
        GeometricQuery(
            world,
            (0,),
            (5,),
            2.0,
            100,
            present=array("d", (5.0, 0.0, 11.0, 0.0, 0.0, 13.0)),
            charge_occupied_cells=occupied,
        )
    )
    assert result.kind == "routed"
    assert result.path == (0, 2, 5)
    assert result.cost == expected_cost


def test_relaxed_search_prices_history_across_27_levels() -> None:
    canvas = routing_domain._Canvas(
        belt_rules=replace(
            routing_domain._DEFAULT_BELT_RULES,
            max_z=Fraction(26),
            vertical_construction=True,
        )
    )
    grid = routing_domain._make_grid(canvas, (0, 0, 1, 0), (-2, -2, 3, 2), {})
    levels = grid.levels
    movement = tuple(
        tuple(
            [(grid.xstep, 0, 1, 0, 2.0)]
            + ([(1, 0, 0, 0, 1.0)] if level + 1 < levels else [])
            + ([(2, 0, 0, 0, 3.0)] if level + 2 < levels else [])
        )
        for level in range(levels)
    )
    flags = bytearray(grid.size)
    for level in range(levels):
        flags[grid.index((0, 0, level))] = 1
    start, goal = grid.index((0, 0, 0)), grid.index((1, 0, 26))
    flags[goal] = 1
    history = array("d", [0.0]) * grid.size
    history[grid.index((0, 0, 17))] = 2.0
    grid.hist = history
    net_id = NetId(0, 1, "iron", NetRole.INTERNAL, 0)

    result = global_router._search_relaxed(
        grid,
        flags,
        (start,),
        (goal,),
        global_router._CapacityLedger(grid.size),
        frozenset(),
        FeedbackState((2, 1), {}, {}),
        net_id,
        20_000,
        None,
        movement=movement,
    )

    expected = tuple((0, 0, level) for level in range(27) if level != 17) + ((1, 0, 26),)
    assert result.path == expected
    assert result.path is not None
    path_indices = tuple(grid.index(cell) for cell in result.path)
    cost = sum(
        next(
            base
            for offset, _via, _dx, _dy, base in movement[source % levels]
            if source + offset == target
        )
        + history[target]
        for source, target in zip(path_indices, path_indices[1:], strict=False)
    )
    assert cost == 29.0
