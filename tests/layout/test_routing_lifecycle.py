from __future__ import annotations

from collections.abc import Callable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass, replace
from fractions import Fraction
from typing import Concatenate, Never

import pytest

from flab2bp.indexed import StakedPaths
from flab2bp.layout import last_mile
from flab2bp.layout import routing_domain as routing
from flab2bp.layout.band_policy import BandPolicy
from flab2bp.layout.base import PlacedBuilding
from flab2bp.layout.route_feedback import (
    Cell,
    DetailedRouteResult,
    DetailedRouteStatus,
    NetId,
    NetRole,
    RouteFailureKind,
    RouteSettlement,
    RouteSettlementCancelled,
)
from flab2bp.layout.route_primitives import RouteOwnership, RoutePrimitives


def _scene(*, partial: bool = False) -> tuple[routing._Canvas, list[routing._Net]]:
    canvas = routing._Canvas(limit=(-2, -2, 8, 8))
    nets: list[routing._Net] = []
    for ordinal, y in enumerate((0, 6) if partial else (0,)):
        source = canvas.add(PlacedBuilding(2001, 35, 0, y, carries_item="iron-ore"))
        sink = canvas.add(PlacedBuilding(2001, 35, 6, y, carries_item="iron-ore"))
        nets.append(
            routing._Net(
                routing._Port(source, 0, y, 0, 0),
                routing._Port(sink, 6, y, 6, 6),
                "iron-ore",
                net_id=NetId(2 * ordinal, 2 * ordinal + 1, "iron-ore", NetRole.INTERNAL, ordinal),
            )
        )
    return canvas, nets


def _run(
    canvas: routing._Canvas,
    nets: list[routing._Net],
    *,
    budget: dict[str, int] | None = None,
    settle: Callable[[routing._Canvas, tuple[frozenset[NetId], ...]], RouteSettlement]
    | None = None,
) -> DetailedRouteResult:
    assert canvas.limit is not None
    return routing._route_all(canvas, nets, 2001, 35, canvas.limit, budget=budget, settle=settle)


def _linked_cells(canvas: routing._Canvas, net: routing._Net) -> list[tuple[int, int, Fraction]]:
    current = net.source.belt
    seen: set[int] = set()
    cells: list[tuple[int, int, Fraction]] = []
    while current != net.dst.belt:
        assert current not in seen
        seen.add(current)
        building = canvas.buildings[current]
        cells.append((building.x, building.y, building.z))
        following = building.output_obj
        assert following is not None
        assert current in canvas.buildings.belts_into(following)
        current = following
    return cells


def _intercept_canvas[**P, R](
    operation: Callable[Concatenate[routing._Canvas, P], R],
    intercept: Callable[[routing._Canvas, Callable[[], R]], R],
) -> Callable[Concatenate[routing._Canvas, P], R]:
    def wrapped(canvas: routing._Canvas, /, *args: P.args, **kwargs: P.kwargs) -> R:
        return intercept(canvas, lambda: operation(canvas, *args, **kwargs))

    return wrapped


@dataclass
class _CommitCall:
    workspace: routing._Canvas
    paths: Mapping[int, Sequence[Cell]]
    source_hints: Mapping[int, Cell] | None
    sink_hints: Mapping[int, Cell] | None
    source_taps: Mapping[int, Cell] | None
    primitives: RoutePrimitives | None
    proceed: Callable[[], tuple[int, ...]]


def _observe_commit(
    monkeypatch: pytest.MonkeyPatch,
    observer: Callable[[_CommitCall], tuple[int, ...]],
) -> None:
    original = routing._commit_paths

    def commit(
        workspace: routing._Canvas,
        nets: list[routing._Net],
        paths: Mapping[int, Sequence[Cell]],
        belt_id: int,
        belt_model: int,
        src_group: Mapping[int, tuple[int, ...]] | None = None,
        dst_group: Mapping[int, tuple[int, ...]] | None = None,
        *,
        source_hints: Mapping[int, Cell] | None = None,
        sink_hints: Mapping[int, Cell] | None = None,
        failure_details: dict[int, routing._CommitFailure] | None = None,
        primitives: RoutePrimitives | None = None,
        source_taps: Mapping[int, Cell] | None = None,
        deadline: float | None = None,
        ownership: RouteOwnership | None = None,
    ) -> tuple[int, ...]:
        def proceed() -> tuple[int, ...]:
            return original(
                workspace,
                nets,
                paths,
                belt_id,
                belt_model,
                src_group,
                dst_group,
                source_hints=source_hints,
                sink_hints=sink_hints,
                failure_details=failure_details,
                primitives=primitives,
                source_taps=source_taps,
                deadline=deadline,
                ownership=ownership,
            )

        return observer(
            _CommitCall(
                workspace, paths, source_hints, sink_hints, source_taps, primitives, proceed
            )
        )

    monkeypatch.setattr(routing, "_commit_paths", commit)


def _only_first_net(monkeypatch: pytest.MonkeyPatch) -> None:
    def search(
        canvas: routing._Canvas, proceed: Callable[[], routing._PathSearchResult]
    ) -> routing._PathSearchResult:
        if (0, 6, 0) in canvas.routing_ports:
            return routing._PathSearchResult(None, RouteFailureKind.DYNAMIC_ACCESS, (), 0)
        return proceed()

    monkeypatch.setattr(routing, "_astar", _intercept_canvas(routing._astar, search))
    monkeypatch.setattr(routing, "_REPAIR_PASSES", 0)
    monkeypatch.setattr(routing, "RRR_MAX", 1)
    monkeypatch.setattr(last_mile, "B_MAX_STRANDED", 0)


def test_warm_projection_cancellation_is_unknown_not_a_collider() -> None:
    canvas, _nets = _scene()
    assert canvas.limit is not None
    cancelled = False
    canvas.junction_projection = routing._CompositionProjection(
        tuple(canvas.buildings), canvas.limit, BandPolicy("160"), cancelled=lambda: cancelled
    )
    selection = routing._splitter_stack_geometry(3, 3, 0)
    assert canvas.projected_buildings_are_clear(selection)
    assert canvas.projected_buildings_are_clear(selection)
    cancelled = True
    with pytest.raises(routing._PreparationDeadline):
        canvas.projected_buildings_are_clear(selection)
    cancelled = False
    assert canvas.projected_buildings_are_clear(selection)


def test_candidate_projection_cancellation_returns_budget_with_search_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canvas, nets = _scene()
    assert canvas.limit is not None
    before = tuple(canvas.buildings)
    canvas.junction_projection = routing._CompositionProjection(
        before, canvas.limit, BandPolicy("160")
    )
    observed: list[int] = []

    def searched(
        _canvas: routing._Canvas, proceed: Callable[[], routing._PathSearchResult]
    ) -> routing._PathSearchResult:
        result = proceed()
        observed.append(result.expansions)
        return result

    def interrupt(*_args: object, **_kwargs: object) -> Never:
        raise routing._PreparationDeadline

    monkeypatch.setattr(routing, "_astar", _intercept_canvas(routing._astar, searched))
    monkeypatch.setattr(canvas.junction_projection, "allows_buildings", interrupt)
    result = _run(canvas, nets, budget={"left": 20_000})
    assert result.status is DetailedRouteStatus.BUDGET
    assert result.expansions == sum(observed) > 0
    assert all(failure.kind is RouteFailureKind.BUDGET for failure in result.failures)
    assert not result.exhaustive
    assert tuple(canvas.buildings) == before


@pytest.mark.parametrize("phase", ("selection", "link", "settlement"))
def test_interrupted_physical_attempt_never_publishes_partial_canvas(
    monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    canvas, nets = _scene()
    before = canvas.clone()

    def commit(call: _CommitCall) -> tuple[int, ...]:
        if phase == "selection":
            call.workspace.add(PlacedBuilding(2001, 35, 8, 8, carries_item="interrupted"))
            raise routing._PreparationDeadline
        return call.proceed()

    def tap(workspace: routing._Canvas, proceed: Callable[[], bool]) -> bool:
        result = proceed()
        if phase == "link":
            assert result
            assert workspace.buildings[nets[0].source.belt].output_obj is not None
            raise routing._PreparationDeadline
        return result

    def settle(
        workspace: routing._Canvas, _owners: tuple[frozenset[NetId], ...]
    ) -> RouteSettlement:
        _linked_cells(workspace, nets[0])
        workspace.add(PlacedBuilding(2001, 35, 8, 8, carries_item="interrupted"))
        return RouteSettlementCancelled("final-projection")

    _observe_commit(monkeypatch, commit)
    monkeypatch.setattr(routing, "_tap_source", _intercept_canvas(routing._tap_source, tap))
    result = _run(canvas, nets, settle=settle, budget={"left": 20_000})
    assert result.status is DetailedRouteStatus.BUDGET
    assert not result.exhaustive
    assert all(failure.kind is not RouteFailureKind.COMMIT_LINK for failure in result.failures)
    assert tuple(canvas.buildings) == tuple(before.buildings)
    assert canvas.blocked == before.blocked
    assert canvas.world_taken == before.world_taken
    assert canvas.solid == before.solid
    assert canvas.reserved == before.reserved
    assert canvas.port_corridors == before.port_corridors
    assert canvas.routing_ports == before.routing_ports
    assert canvas.keep_out == before.keep_out
    assert canvas.guard == before.guard
    assert canvas.belt_ban == before.belt_ban
    assert canvas.junction_ban == before.junction_ban


def test_exact_partial_commit_transfers_links_indexes_and_reservations_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canvas, nets = _scene(partial=True)
    _only_first_net(monkeypatch)
    accepted: list[routing._Canvas] = []

    def commit(call: _CommitCall) -> tuple[int, ...]:
        failed = call.proceed()
        if not failed:
            workspace = call.workspace
            _linked_cells(workspace, nets[0])
            workspace.reserved[(8, 8, 0)] = (8, 7, 0)
            workspace.belt_ban[(8, 8)] = {1}
            accepted.append(workspace)
        return failed

    def settle(_workspace: routing._Canvas, _owners: tuple[frozenset[NetId], ...]) -> Never:
        pytest.fail("a partial commit is not a complete factory")

    _observe_commit(monkeypatch, commit)
    result = _run(canvas, nets, settle=settle, budget={"left": 20_000})
    assert result.routed == (nets[0].net_id,)
    assert result.stranded == (nets[1].net_id,)
    assert result.settlement is None
    assert len(accepted) == 1
    assert canvas.buildings is accepted[0].buildings
    _linked_cells(canvas, nets[0])
    assert canvas.reserved.first_for((8, 7, 0)) == (8, 8, 0)
    assert canvas.belt_ban[(8, 8)] == {1}
    for building in canvas.buildings:
        assert (building.x, building.y, building.z) in canvas.world_taken
    del canvas.reserved[(8, 8, 0)]
    assert canvas.reserved.first_for((8, 7, 0)) is None


@pytest.mark.parametrize("changed", ("path", "source", "sink", "tap", "primitive", "guard"))
def test_changed_selection_cannot_adopt_earlier_success(
    monkeypatch: pytest.MonkeyPatch, changed: str
) -> None:
    canvas, nets = _scene()
    search_canvases: list[routing._Canvas] = []
    commits = 0
    alternate: tuple[Cell, ...] = (
        (0, 1, 0),
        (1, 1, 0),
        (2, 1, 0),
        (3, 1, 0),
        (4, 1, 0),
        (5, 1, 0),
        (6, 1, 0),
    )

    def searched(
        search_canvas: routing._Canvas, proceed: Callable[[], routing._PathSearchResult]
    ) -> routing._PathSearchResult:
        search_canvases.append(search_canvas)
        return proceed()

    def commit(call: _CommitCall) -> tuple[int, ...]:
        nonlocal commits
        failed = call.proceed()
        commits += 1
        if commits == 1:
            assert not failed
            call.workspace.add(PlacedBuilding(2001, 35, 8, 8, carries_item="stale-marker"))
            if changed == "path":
                assert isinstance(call.paths, StakedPaths)
                call.paths.stake(0, alternate)
            elif changed == "guard":
                search_canvases[0].guard.add((8, 7, 0))
            elif changed == "primitive":
                assert call.primitives is not None
                call.primitives.rules = replace(call.primitives.rules, max_z=Fraction(0))
            else:
                hints = {
                    "source": call.source_hints,
                    "sink": call.sink_hints,
                    "tap": call.source_taps,
                }[changed]
                assert isinstance(hints, MutableMapping)
                hints[0] = (7, 7, 0)
        return failed

    monkeypatch.setattr(routing, "_astar", _intercept_canvas(routing._astar, searched))
    _observe_commit(monkeypatch, commit)
    result = _run(canvas, nets, budget={"left": 20_000})
    assert commits == 2
    assert all(building.carries_item != "stale-marker" for building in canvas.buildings)
    if changed == "path":
        assert result.status is DetailedRouteStatus.ROUTED
        expected = {(x, y, Fraction(z)) for x, y, z in alternate}
        assert expected <= set(_linked_cells(canvas, nets[0]))


def test_real_commit_collider_failure_keeps_attribution(monkeypatch: pytest.MonkeyPatch) -> None:
    canvas, nets = _scene()
    monkeypatch.setattr(routing, "_COMMIT_REPAIR_PASSES", 0)
    monkeypatch.setattr(routing, "RRR_MAX", 1)
    monkeypatch.setattr(last_mile, "B_MAX_STRANDED", 0)
    failed_cell: list[Cell] = []

    def collide(call: _CommitCall) -> tuple[int, ...]:
        if call.paths:
            cell = call.paths[0][0]
            failed_cell.append(cell)
            call.workspace.world_taken.add((cell[0], cell[1], Fraction(cell[2])))
        return call.proceed()

    _observe_commit(monkeypatch, collide)
    result = _run(canvas, nets, budget={"left": 20_000})
    assert result.status is DetailedRouteStatus.STRANDED
    assert result.failures[0].kind is RouteFailureKind.COMMIT_LINK
    assert result.failures[0].wall == (failed_cell[0],)
    assert canvas.buildings[nets[0].source.belt].output_obj is None


def test_real_commit_failure_before_cancellation_retains_only_proved_blame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canvas, nets = _scene(partial=True)
    before = tuple(canvas.buildings)
    collision: list[Cell] = []

    def commit(call: _CommitCall) -> tuple[int, ...]:
        assert set(call.paths) == {0, 1}
        cell = call.paths[0][0]
        collision.append(cell)
        call.workspace.world_taken.add((cell[0], cell[1], Fraction(cell[2])))
        return call.proceed()

    def tap(_workspace: routing._Canvas, proceed: Callable[[], bool]) -> Never:
        assert proceed()
        raise routing._PreparationDeadline

    _observe_commit(monkeypatch, commit)
    monkeypatch.setattr(routing, "_tap_source", _intercept_canvas(routing._tap_source, tap))
    result = _run(canvas, nets, budget={"left": 20_000})
    assert result.status is DetailedRouteStatus.BUDGET
    failures = {failure.net_id: failure for failure in result.failures}
    first_id, second_id = nets[0].net_id, nets[1].net_id
    assert first_id is not None and second_id is not None
    assert failures[first_id].kind is RouteFailureKind.COMMIT_LINK
    assert failures[first_id].wall == (collision[0],)
    assert second_id not in failures or failures[second_id].kind is RouteFailureKind.BUDGET
    assert tuple(canvas.buildings) == before


def test_cancelled_fallback_commit_cannot_publish_its_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canvas, nets = _scene()
    before = tuple(canvas.buildings)
    commits = 0

    def commit(call: _CommitCall) -> tuple[int, ...]:
        nonlocal commits
        commits += 1
        if commits == 2:
            call.workspace.add(PlacedBuilding(2001, 35, 8, 8, carries_item="interrupted"))
            raise routing._PreparationDeadline
        failed = call.proceed()
        assert not failed
        assert isinstance(call.source_hints, MutableMapping)
        call.source_hints[0] = (7, 7, 0)
        return failed

    _observe_commit(monkeypatch, commit)
    result = _run(canvas, nets, budget={"left": 20_000})
    assert result.status is DetailedRouteStatus.BUDGET
    assert commits == 2
    assert all(failure.kind is not RouteFailureKind.COMMIT_LINK for failure in result.failures)
    assert tuple(canvas.buildings) == before


def test_cluster_projection_cancellation_debits_private_work_and_retains_prior_searches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canvas, nets = _scene(partial=True)
    assert canvas.limit is not None
    canvas.junction_projection = routing._CompositionProjection(
        tuple(canvas.buildings), canvas.limit, BandPolicy("160")
    )
    budget = {"left": 20_000}
    cluster_started = False
    cancelled = False
    entry_budget = 0
    observed: list[int] = []
    original_solver = last_mile.solve_cluster
    original_projection = canvas.junction_projection.allows_buildings

    def search(
        workspace: routing._Canvas, proceed: Callable[[], routing._PathSearchResult]
    ) -> routing._PathSearchResult:
        nonlocal cancelled
        second_net = (0, 6, 0) in workspace.routing_ports
        if not cluster_started and second_net:
            return routing._PathSearchResult(None, RouteFailureKind.DYNAMIC_ACCESS, (), 0)
        found = proceed()
        if cluster_started:
            observed.append(found.expansions)
            if second_net:
                assert found.path is not None
                cancelled = True
        return found

    def project(
        candidates: tuple[PlacedBuilding, ...],
        *,
        committed: tuple[PlacedBuilding, ...] = (),
        deadline: float | None = None,
    ) -> bool:
        if cancelled:
            raise routing._PreparationDeadline
        return original_projection(candidates, committed=committed, deadline=deadline)

    def problem(*_args: object, **_kwargs: object) -> last_mile.ClusterProblem:
        return last_mile.ClusterProblem(
            nets=(0, 1), stranded=(1,), truncated=False, sibling_closed=True
        )

    def solve(
        problem: last_mile.ClusterProblem, environment: last_mile.ClusterEnvironment
    ) -> last_mile.ClusterResult:
        nonlocal cluster_started, entry_budget
        cluster_started = True
        entry_budget = budget["left"]
        return original_solver(problem, environment)

    monkeypatch.setattr(routing, "_astar", _intercept_canvas(routing._astar, search))
    monkeypatch.setattr(canvas.junction_projection, "allows_buildings", project)
    monkeypatch.setattr(routing, "_REPAIR_PASSES", 0)
    monkeypatch.setattr(routing, "RRR_MAX", 1)
    monkeypatch.setattr(last_mile, "build_cluster", problem)
    monkeypatch.setattr(last_mile, "solve_cluster", solve)
    result = _run(canvas, nets, budget=budget)
    assert cancelled and len(observed) == 2
    assert all(expansions > 0 for expansions in observed)
    assert result.status is DetailedRouteStatus.BUDGET
    assert entry_budget - budget["left"] == sum(observed)
    assert result.last_mile is not None
    assert result.last_mile.expansions == sum(observed)
    assert result.last_mile.bounded == 1
    assert not result.exhaustive
    assert all(failure.kind is not RouteFailureKind.COMMIT_LINK for failure in result.failures)
