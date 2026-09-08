from __future__ import annotations

from dataclasses import replace
from fractions import Fraction

import pytest

from flab2bp.layout import global_router, junction, route_kernel, routing_domain
from flab2bp.layout.route_feedback import FeedbackState, NetId, NetRole, RouteFailureKind
from tests.layout.test_route_kernel import _require_both_backends

Cell = tuple[int, int, int]


def _canvas(ceiling: int, unlocked: bool) -> routing_domain._Canvas:
    return routing_domain._Canvas(
        belt_rules=replace(
            routing_domain._DEFAULT_BELT_RULES,
            max_z=Fraction(ceiling),
            vertical_construction=unlocked,
        )
    )


@pytest.fixture(params=[False, True], ids=["python", "native"])
def backend(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    compiled = _require_both_backends() if request.param else None
    monkeypatch.setattr(route_kernel, "_compiled_astar", compiled)


def test_wall_above_old_ceiling_is_crossed_at_level_four(backend: None) -> None:
    canvas = _canvas(4, True)
    for y in range(3):
        for level in range(4):
            canvas.blocked[(2, y, level)] = 0
    result = routing_domain._astar(canvas, [(0, 1, 0)], {(4, 1, 0)}, {}, 1.0, (0, 0, 4, 2))
    assert result.path is not None
    assert (2, 1, 4) in result.path
    assert all(0 <= cell[2] <= 4 for cell in result.path)


def test_empty_xy_shaft_requires_vertical_unlock(backend: None) -> None:
    unlocked = routing_domain._astar(
        _canvas(4, True), [(0, 0, 0)], {(0, 0, 4)}, {}, 1.0, (0, 0, 0, 0)
    )
    assert unlocked.path == tuple((0, 0, level) for level in range(5))
    locked = routing_domain._astar(
        _canvas(4, False), [(0, 0, 0)], {(0, 0, 4)}, {}, 1.0, (0, 0, 0, 0)
    )
    assert locked.path is None
    assert locked.kind is RouteFailureKind.SEALED_POCKET


def test_locked_technology_keeps_two_tile_ramps(backend: None) -> None:
    result = routing_domain._astar(
        _canvas(1, False), [(0, 0, 0)], {(2, 0, 1)}, {}, 1.0, (0, 0, 2, 0)
    )
    assert result.path == ((0, 0, 0), (1, 0, 0), (2, 0, 1))


@pytest.mark.parametrize("goal", [(0, 0, -1), (0, 0, 5)])
def test_goal_outside_save_ceiling_never_wraps(goal: Cell, backend: None) -> None:
    result = routing_domain._astar(_canvas(4, True), [(0, 0, 0)], {goal}, {}, 1.0, (0, 0, 1, 1))
    assert result.path is None
    assert result.expansions == 0


def test_sparse_connector_is_direct_and_landing_still_must_be_free(backend: None) -> None:
    canvas = _canvas(0, False)
    canvas.blocked[(1, 0, 0)] = 0
    box = (0, 0, 2, 0)
    grid = routing_domain._make_grid(canvas, box, (-2, -2, 4, 2), {})
    start, goal = (0, 0, 0), (2, 0, 0)
    edges = {grid.index(start): ((grid.index(goal), 2.0),)}
    result = routing_domain._astar(
        canvas, [start], {goal}, {}, 1.0, box, grid=grid, extra_edges=edges
    )
    assert result.path == (start, goal)
    blocked = routing_domain._astar(
        canvas, [start], {goal}, {}, 1.0, box, grid=grid, forbidden=(goal,), extra_edges=edges
    )
    assert blocked.path is None


def test_sparse_edges_preserve_native_python_path_and_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compiled = _require_both_backends()
    canvas = _canvas(4, True)
    box = (0, 0, 2, 0)
    grid = routing_domain._make_grid(canvas, box, (-2, -2, 4, 2), {})
    start, goal = (0, 0, 0), (2, 0, 4)
    edges = {grid.index(start): ((grid.index(goal), 2.0),)}
    for allowance in (1, 2, 20):
        native_budget, python_budget = {"left": allowance}, {"left": allowance}
        monkeypatch.setattr(route_kernel, "_compiled_astar", compiled)
        native = routing_domain._astar(
            canvas, [start], {goal}, {}, 1.0, box, native_budget, grid=grid, extra_edges=edges
        )
        monkeypatch.setattr(route_kernel, "_compiled_astar", None)
        python = routing_domain._astar(
            canvas, [start], {goal}, {}, 1.0, box, python_budget, grid=grid, extra_edges=edges
        )
        assert native == python
        assert native_budget == python_budget
        if allowance == 20:
            assert native.path == (start, goal)
        else:
            assert native.kind is RouteFailureKind.BUDGET


def test_relaxed_search_cannot_miss_physical_splitter_height_transfer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _require_both_backends()
    compiled = route_kernel._compiled_relaxed
    assert compiled is not None
    canvas = _canvas(2, False)
    candidate = next(
        candidate
        for candidate in junction.splitter_route_candidates(
            0, 0, 0, yaw=0.0, altitude_rules=canvas.belt_rules, carries_item="iron"
        )
        if candidate.entry.dock[2] != candidate.exit.dock[2]
    )
    box = (-2, -2, 2, 2)
    grid = routing_domain._make_grid(canvas, box, (-4, -4, 4, 4), {})
    start, goal = grid.index(candidate.entry.dock), grid.index(candidate.exit.dock)
    flags = bytearray(grid.size)
    flags[start] = flags[goal] = 1
    movement = global_router._relaxed_transitions(
        grid.xstep, grid.levels, grid.vertical_construction, canvas.belt_rules
    )
    net_id = NetId(0, 1, "iron", NetRole.INTERNAL, 0)
    results = []
    for backend in (compiled, None):
        monkeypatch.setattr(route_kernel, "_compiled_relaxed", backend)
        result = global_router._search_relaxed(
            grid,
            flags,
            (start,),
            (goal,),
            global_router._CapacityLedger(grid.size),
            frozenset(),
            FeedbackState((5, 5), {}, {}),
            net_id,
            100,
            None,
            movement=movement,
        )
        assert result.path == (candidate.entry.dock, candidate.exit.dock)
        results.append(result)
    assert results[0] == results[1]
