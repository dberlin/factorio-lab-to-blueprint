from __future__ import annotations

import sys
from dataclasses import replace
from fractions import Fraction

import pytest

from flab2bp.dsp import catalog, splitter_ports
from flab2bp.layout import global_router, junction, route_kernel, routing_domain
from flab2bp.layout.base import PlacedBuilding
from flab2bp.layout.route_feedback import FeedbackState, NetId, NetRole, RouteFailureKind
from flab2bp.layout.route_primitives import RoutePrimitives
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


@pytest.mark.parametrize("blocked_via", [False, True])
def test_reverse_search_preserves_forward_ramp_clearance(backend: None, blocked_via: bool) -> None:
    canvas = _canvas(1, False)
    canvas.blocked[(1, 0, 1)] = 0
    if blocked_via:
        canvas.blocked[(1, 0, 0)] = 0
    result = routing_domain._astar(
        canvas, [(0, 0, 0)], {(2, 0, 1)}, {}, 1.0, (0, 0, 2, 0), reverse=True
    )
    if blocked_via:
        assert result.path is None
        assert result.kind is RouteFailureKind.BUDGET
    else:
        assert result.path == ((0, 0, 0), (1, 0, 0), (2, 0, 1))


def test_reverse_search_keeps_entry_ring_exception_at_source_only(backend: None) -> None:
    canvas = _canvas(1, False)
    canvas.limit = (-1, 0, 1, 0)
    canvas.blocked[(0, 0, 1)] = 0
    result = routing_domain._astar(
        canvas, [(-1, 0, 0)], {(1, 0, 1)}, {}, 1.0, (0, 0, 1, 0), reverse=True
    )
    assert result.path == ((-1, 0, 0), (0, 0, 0), (1, 0, 1))
    canvas.blocked[(-1, 0, 0)] = 0
    refused = routing_domain._astar(
        canvas, [(-1, 0, 0)], {(1, 0, 1)}, {}, 1.0, (0, 0, 1, 0), reverse=True
    )
    assert refused.path is None


def test_reverse_search_cannot_use_another_seed_as_a_forbidden_ramp_via(backend: None) -> None:
    canvas = _canvas(1, False)
    canvas.limit = (0, 0, 2, 0)
    result = routing_domain._astar(
        canvas,
        [(0, 0, 0), (1, 0, 0)],
        {(2, 0, 1)},
        {},
        1.0,
        (2, 0, 2, 0),
        reverse=True,
    )
    assert result.path is None
    assert result.kind is RouteFailureKind.BUDGET


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


def _scheduler(canvas, bounds, *, deadline=None, outer_budget=None):
    """Capture the real callable with the routing pass's initialized context."""
    captured = {}
    previous_profile = sys.getprofile()
    if previous_profile is not None and not callable(previous_profile):
        raise RuntimeError("scheduler capture cannot chain an active native profiler")

    def capture(frame, event, arg):
        if previous_profile is not None:
            previous_profile(frame, event, arg)
        if (
            event == "return"
            and frame.f_code is routing_domain._route_all.__code__
            and "_search" in frame.f_locals
        ):
            captured.update(
                search=frame.f_locals["_search"], primitives=frame.f_locals["primitives"]
            )

    try:
        sys.setprofile(capture)
        routing_domain._route_all(
            canvas,
            [],
            2002,
            catalog.building(2002).model_index,
            bounds,
            deadline=deadline,
            budget=outer_budget,
        )
    finally:
        sys.setprofile(previous_profile)
    return captured["search"], captured["primitives"]


@pytest.mark.parametrize("allowance", [20, 200_002, 400_002])
def test_scheduler_preserves_real_connector_only_capability(backend, allowance):
    canvas = _canvas(1, False)
    start, goal = (0, 1, 0), (0, 1, 1)
    bounds = (0, 1, 0, 1)
    grid = routing_domain._make_grid(canvas, bounds, (-3, -3, 3, 3), {})
    search, primitives = _scheduler(canvas, bounds)
    ledger = {"left": allowance}
    blame = {}
    result = search([start], {goal}, {}, {}, 1.0, ledger, blame, grid)
    assert result.path == (start, goal)
    assert ledger["left"] == allowance - result.expansions
    assert blame == {}
    (candidate,) = primitives.on_path(result.path)
    assert candidate.stack_members[-1].model_index == 39
    model = catalog.building(2002).model_index
    source = canvas.add(PlacedBuilding(2002, model, *start[:2], Fraction(start[2])))
    target = canvas.add(PlacedBuilding(2002, model, *goal[:2], Fraction(goal[2])))
    primitives.emit(canvas, candidate, source, target, 2002, model, "iron-ore")
    assert splitter_ports.placement_issues(canvas.buildings) == ()
    assert not canvas.free_world(0, 0, Fraction(0))
    assert not canvas.free_world(0, 0, Fraction(1))


def test_scheduler_restores_source_after_contextual_ordinary_refusal(monkeypatch, backend):
    canvas = _canvas(1, False)
    bounds = (0, 1, 2, 1)
    history = {(1, 1, 0): 100.0, (1, 1, 1): 100.0}
    grid = routing_domain._make_grid(canvas, bounds, (-3, -3, 5, 3), history)
    start, goal = (0, 1, 0), (0, 1, 1)
    tap = (-3, 1, 0)
    search, primitives = _scheduler(canvas, bounds)
    ordinary = routing_domain._astar(canvas, [start], {goal}, history, 1.0, bounds, grid=grid)
    assert ordinary.path is not None
    checked = []
    original = routing_domain._Canvas.projected_buildings_are_clear

    def changed_frame(self, candidates, *, selected=(), deadline=None):
        # Isolate the contextual frame oracle, not search or connector geometry.
        # An actual connector changes this otherwise identical source selection.
        allowed = any(building.model_index == 39 for building in (*selected, *candidates))
        checked.append(allowed)
        return allowed and original(self, candidates, selected=selected, deadline=deadline)

    monkeypatch.setattr(routing_domain._Canvas, "projected_buildings_are_clear", changed_frame)
    ledger = {"left": 400_002}
    result = search([start], {goal}, {start: tap}, history, 1.0, ledger, {}, grid)
    assert result.path == (start, goal)
    assert result.expansions == ordinary.expansions + 2
    assert ledger["left"] == 400_002 - result.expansions
    assert checked[0] is False
    assert checked[-1] is True
    (candidate,) = primitives.on_path(result.path)
    assert candidate.stack_members[-1].model_index == 39


@pytest.mark.parametrize("allowance", [100, 133], ids=["shared-quota-cap", "per-search-cap"])
def test_capped_empty_graph_retry_preserves_quota_for_next_net(monkeypatch, backend, allowance):
    monkeypatch.setattr(routing_domain, "_MAX_EXPANSIONS", 65)
    canvas = _canvas(0, False)
    bounds = (0, 0, 70, 0)
    canvas.limit = bounds
    grid = routing_domain._make_grid(canvas, bounds, (-3, -3, 73, 3), {})
    search, _primitives = _scheduler(canvas, bounds)
    ledger = {"left": allowance}
    capped = search([(0, 0, 0)], {(70, 0, 0)}, {}, {}, 1.0, ledger, {}, grid)
    assert capped.kind is RouteFailureKind.BUDGET
    assert capped.expansions >= allowance - ledger["left"]
    following = search([(0, 0, 0)], {(4, 0, 0)}, {}, {}, 1.0, ledger, {}, grid)
    assert following.path == tuple((x, 0, 0) for x in range(5))


def test_capped_ordinary_search_still_uses_new_connector_edges(monkeypatch, backend):
    monkeypatch.setattr(routing_domain, "_MAX_EXPANSIONS", 2)
    canvas = _canvas(1, False)
    bounds = (-2, -2, 2, 2)
    history = {
        (x, y, z): 100.0
        for x in range(-2, 3)
        for y in range(-2, 3)
        for z in range(2)
        if (x, y) != (0, 1)
    }
    grid = routing_domain._make_grid(canvas, bounds, (-4, -4, 4, 4), history)
    search, primitives = _scheduler(canvas, bounds)
    start, goal = (0, 1, 0), (0, 1, 1)
    ordinary = routing_domain._astar(canvas, [start], {goal}, history, 1.0, bounds, grid=grid)
    assert ordinary.kind is RouteFailureKind.BUDGET
    assert ordinary.expansions == 3
    result = search([start], {goal}, {}, history, 1.0, {"left": 20}, {}, grid)
    assert result.path == (start, goal)
    (connector,) = primitives.on_path(result.path)
    assert connector.stack_members[-1].model_index == 39


def test_scheduler_charges_only_its_immediate_private_ledger(monkeypatch, backend):
    monkeypatch.setattr(routing_domain, "_MAX_EXPANSIONS", 200)
    canvas = _canvas(0, False)
    bounds = (0, 0, 70, 0)
    grid = routing_domain._make_grid(canvas, bounds, (-3, -3, 73, 3), {})
    outer = {"left": 1_000_000}
    search, _primitives = _scheduler(canvas, bounds, outer_budget=outer)
    private = {"left": 204}
    result = search([(0, 0, 0)], {(70, 0, 0)}, {}, {}, 1.0, private, {}, grid)
    assert private["left"] == 204 - result.expansions
    assert outer["left"] == 1_000_000
    assert result.path == tuple((x, 0, 0) for x in range(71))


def test_scheduler_subdeadline_returns_to_live_parent(monkeypatch, backend):
    canvas = _canvas(0, False)
    bounds = (0, 0, 70, 0)
    grid = routing_domain._make_grid(canvas, bounds, (-3, -3, 73, 3), {})
    search, _primitives = _scheduler(canvas, bounds, deadline=80.0)
    ticks = iter((0.0, 0.0, 11.0))
    monkeypatch.setattr(routing_domain.time, "monotonic", lambda: next(ticks, 11.0))
    ledger = {"left": 400_002}
    result = search([(0, 0, 0)], {(70, 0, 0)}, {}, {}, 1.0, ledger, {}, grid)
    assert result.path == tuple((x, 0, 0) for x in range(71))


def test_scheduler_expired_parent_does_no_probe_or_enumeration(monkeypatch, backend):
    canvas = _canvas(1, False)
    bounds = (0, 1, 0, 1)
    grid = routing_domain._make_grid(canvas, bounds, (-3, -3, 3, 3), {})
    search, _primitives = _scheduler(canvas, bounds, deadline=0.0)

    def expired_work(*args, **kwargs):
        pytest.fail("an expired parent must not begin connector generation")

    monkeypatch.setattr(RoutePrimitives, "edges", expired_work)
    ledger = {"left": 400_002}
    result = search([(0, 1, 0)], {(0, 1, 1)}, {}, {}, 1.0, ledger, {}, grid)
    assert result.kind is RouteFailureKind.BUDGET
    assert result.expansions == 0
    assert ledger["left"] == 400_002


def test_ordinary_source_retry_routes_around_its_own_splitter(backend):
    canvas = _canvas(0, False)
    bounds = (-3, -4, 5, 3)
    canvas.blocked[1, -1, 0] = routing_domain._TENTATIVE
    grid = routing_domain._make_grid(canvas, bounds, bounds, {})
    search, _primitives = _scheduler(canvas, bounds)
    start, goal, tap = (1, 0, 0), (2, -2, 0), (2, 0, 1)
    ledger = {"left": 2000}
    result = search([start], {goal}, {start: tap}, {}, 1.0, ledger, {}, grid, ordinary_only=True)
    assert result.path is not None
    assert result.path[0] == start and result.path[-1] == goal
    assert (2, 0, 0) not in result.path
    assert ledger["left"] == 2000 - result.expansions


def test_coverage_pass_defers_but_does_not_remove_connector_capability(backend):
    canvas = _canvas(1, False)
    bounds = (0, 1, 0, 1)
    grid = routing_domain._make_grid(canvas, bounds, (-3, -3, 3, 3), {})
    search, primitives = _scheduler(canvas, bounds)
    start, goal = (0, 1, 0), (0, 1, 1)
    ledger = {"left": 20}
    deferred = search([start], {goal}, {}, {}, 1.0, ledger, {}, grid, ordinary_only=True)
    assert deferred.kind is RouteFailureKind.BUDGET
    repaired = search([start], {goal}, {}, {}, 1.0, ledger, {}, grid)
    assert repaired.path == (start, goal)
    (connector,) = primitives.on_path(repaired.path)
    assert connector.stack_members[-1].model_index == 39


def test_small_remaining_quota_routes_before_connector_work_expires(monkeypatch, backend):
    canvas = _canvas(0, False)
    bounds = (0, 0, 2, 0)
    grid = routing_domain._make_grid(canvas, bounds, (-3, -3, 5, 3), {})
    clock = [0.0]
    original = RoutePrimitives.edges

    def charged(self, *args, **kwargs):
        clock[0] += 2.0
        return original(self, *args, **kwargs)

    monkeypatch.setattr(routing_domain.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(RoutePrimitives, "edges", charged)
    search, _primitives = _scheduler(canvas, bounds, deadline=1.0)
    ledger = {"left": 128}
    result = search([(0, 0, 0)], {(2, 0, 0)}, {}, {}, 1.0, ledger, {}, grid)
    assert result.path == ((0, 0, 0), (1, 0, 0), (2, 0, 0))
    assert 128 - ledger["left"] == result.expansions


def test_cost_plateau_reaches_goal_before_shared_quota_exhaustion(backend):
    canvas = _canvas(0, False)
    bounds = (0, 0, 100, 80)
    grid = routing_domain._make_grid(canvas, bounds, (-3, -3, 103, 83), {})
    result = routing_domain._astar(
        canvas, [(0, 0, 0)], {(100, 80, 0)}, {}, 1.0, bounds, {"left": 1000}, grid=grid
    )
    assert result.path is not None
    assert result.path[0] == (0, 0, 0)
    assert result.path[-1] == (100, 80, 0)
    assert len(result.path) == 181
