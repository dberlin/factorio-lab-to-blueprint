from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import replace

import pytest

from flab2bp import spec
from flab2bp.layout import validate
from flab2bp.layout.base import PlacedBuilding
from flab2bp.layout.freeform import (
    LEVELS,
    _PreparedNet,
    _PreparedPort,
    _PreparedRoutingProblem,
    _with_sibling_groups,
)
from flab2bp.layout.global_router import (
    GlobalRouteResult,
    route_global,
    route_global_once,
)
from flab2bp.layout.route_feedback import Cell, FeedbackState, NetId, NetRole

NetSpec = tuple[
    NetId,
    tuple[int, int] | None,
    tuple[int, int],
    tuple[Cell, ...],
    tuple[NetId, ...],
    tuple[NetId, ...],
]


def _problem(
    net_specs: Iterable[NetSpec],
    *,
    bounds: tuple[int, int, int, int],
    blocked: Iterable[Cell] = (),
    reserved: Iterable[tuple[Cell, tuple[int, int, int]]] = (),
    keep_out: Iterable[tuple[int, int]] = (),
) -> _PreparedRoutingProblem:
    specs = tuple(net_specs)
    coordinates = sorted(
        {
            coordinate
            for _net_id, source, destination, _boundary, _src_group, _dst_group in specs
            for coordinate in (source, destination)
            if coordinate is not None
        }
    )
    index_of = {coordinate: index for index, coordinate in enumerate(coordinates)}
    buildings = tuple(PlacedBuilding(2001, 35, x, y) for x, y in coordinates)

    def port(coordinate: tuple[int, int]) -> _PreparedPort:
        index = index_of[coordinate]
        x, y = coordinate
        return _PreparedPort(index, x, y, x, x, (index,), 1)

    nets = tuple(
        _PreparedNet(
            net_id=net_id,
            src=port(source) if source is not None else None,
            dst=port(destination),
            item=net_id.item,
            boundary_goals=boundary,
            src_group=src_group,
            dst_group=dst_group,
        )
        for net_id, source, destination, boundary, src_group, dst_group in specs
    )
    blocked_cells = {cell: -1 for cell in blocked}
    blocked_cells.update(
        {
            (building.x, building.y, math.floor(building.z)): index
            for index, building in enumerate(buildings)
        }
    )
    return _PreparedRoutingProblem(
        building_templates=buildings,
        blocked=tuple(sorted(blocked_cells.items())),
        solid=frozenset(),
        reserved=tuple(sorted(reserved)),
        keep_out=frozenset(keep_out),
        nets=nets,
        core=bounds,
        route_bounds=bounds,
        limit=bounds,
        power_sites=(),
        sorters=0,
        coaters=0,
        direct_inserts=0,
    )


def _feedback(
    problem: _PreparedRoutingProblem, history: dict[Cell, float] | None = None
) -> FeedbackState:
    _x0, _y0, x1, y1 = problem.route_bounds
    return FeedbackState((x1 + 1, y1 + 1), {}, history or {})


def _one_net_problem() -> tuple[_PreparedRoutingProblem, NetId]:
    net_id = NetId(0, 1, "iron", NetRole.INTERNAL, 0)
    return (
        _problem(
            ((net_id, (0, 1), (4, 1), (), (), ()),),
            bounds=(0, 0, 4, 2),
        ),
        net_id,
    )


def test_global_route_terminates_at_elevated_prepared_port() -> None:
    problem, net_id = _one_net_problem()
    net = problem.nets[0]
    elevated = replace(net, dst=replace(net.dst, z=1))
    elevated_problem = replace(problem, nets=(elevated,))

    result = route_global_once(
        elevated_problem,
        _feedback(elevated_problem),
        budget=20_000,
    )

    path = result.paths[net_id]
    assert path[0][2] == 0
    assert path[-1][2] == 1


def _detour_problem() -> tuple[_PreparedRoutingProblem, NetId, NetId]:
    short = NetId(None, 1, "iron", NetRole.EXTERNAL, 0)
    long = NetId(2, 3, "iron", NetRole.INTERNAL, 0)
    open_cells = {
        (1, 2),
        (3, 2),
        (2, 0),
        (2, 4),
        (2, 1),
        (2, 2),
        (2, 3),
        (1, 1),
        (1, 3),
    }
    return (
        _problem(
            (
                (short, None, (3, 2), ((2, 2, 0),), (), ()),
                (long, (2, 0), (2, 4), (), (), ()),
            ),
            bounds=(0, 0, 4, 4),
            keep_out={(x, y) for x in range(5) for y in range(5) if (x, y) not in open_cells},
        ),
        short,
        long,
    )


def _impossible_overflow_problem() -> _PreparedRoutingProblem:
    first = NetId(0, 1, "iron", NetRole.INTERNAL, 0)
    second = NetId(2, 3, "iron", NetRole.INTERNAL, 0)
    return _problem(
        (
            (first, (0, 1), (4, 1), (), (), ()),
            (second, (0, 1), (4, 1), (), (), ()),
        ),
        bounds=(0, 0, 4, 2),
        keep_out={(x, y) for x in range(5) for y in (0, 2)},
    )


def _assert_current_detailed_legal_walk(path: tuple[Cell, ...]) -> None:
    for index, (before, after) in enumerate(zip(path, path[1:], strict=False)):
        dx = after[0] - before[0]
        dy = after[1] - before[1]
        level_change = after[2] - before[2]
        assert abs(dx) + abs(dy) == 1
        assert abs(level_change) <= 1
        if level_change:
            assert index > 0
            previous = path[index - 1]
            assert before[2] == previous[2]
            assert (before[0] - previous[0], before[1] - previous[1]) == (dx, dy)


def test_global_router_uses_current_detailed_moves_deterministically() -> None:
    net_id = NetId(0, 1, "iron", NetRole.INTERNAL, 0)
    problem = _problem(
        ((net_id, (0, 3), (13, 3), (), (), ()),),
        bounds=(0, 0, 13, 6),
        blocked=((6, y, 0) for y in range(7)),
    )

    first = route_global_once(problem, _feedback(problem), budget=20_000)
    second = route_global_once(problem, _feedback(problem), budget=20_000)

    path = first.paths[net_id]
    assert max(level for _x, _y, level in path) > 0
    _assert_current_detailed_legal_walk(path)
    assert second.paths == first.paths
    assert second.net_results == first.net_results
    assert second.expansions == first.expansions


def test_prepared_blocked_cells_and_foreign_reserved_ports_remain_impassable() -> None:
    net_id = NetId(0, 1, "iron", NetRole.INTERNAL, 0)
    reserved = ((4, 2, 0), (99, 99, 0))
    blocked = tuple((3, 2, level) for level in range(LEVELS))
    problem = _problem(
        ((net_id, (0, 2), (7, 2), (), (), ()),),
        bounds=(0, 0, 7, 4),
        blocked=blocked,
        reserved=(reserved,),
    )

    result = route_global_once(problem, _feedback(problem), budget=20_000)

    hard_cells = set(blocked) | {reserved[0]}
    path = result.paths[net_id]
    assert set(path).isdisjoint(hard_cells)
    _assert_current_detailed_legal_walk(path)


def test_one_pass_records_one_cell_overflow_instead_of_blocking() -> None:
    horizontal = NetId(0, 1, "iron", NetRole.INTERNAL, 0)
    vertical = NetId(2, 3, "iron", NetRole.INTERNAL, 0)
    ports = {(0, 2), (4, 2), (2, 0), (2, 4)}
    open_cells = ports | {(1, 2), (2, 2), (3, 2), (2, 1), (2, 3)}
    keep_out = {(x, y) for x in range(5) for y in range(5) if (x, y) not in open_cells}
    problem = _problem(
        (
            (horizontal, (0, 2), (4, 2), (), (), ()),
            (vertical, (2, 0), (2, 4), (), (), ()),
        ),
        bounds=(0, 0, 4, 4),
        keep_out=keep_out,
    )

    result = route_global_once(problem, _feedback(problem), budget=20_000)

    assert result.overflow_cells == 1
    assert result.total_overflow == 1
    assert result.max_overflow == 1
    assert result.hot_cells == ((2, 2, 0),)
    assert len(result.paths) == 2
    assert sum(net.overflow for net in result.net_results) == 1


def test_prepared_sibling_group_shares_one_logical_capacity_unit() -> None:
    first = NetId(0, 1, "iron", NetRole.INTERNAL, 0)
    sibling = NetId(0, 2, "iron", NetRole.INTERNAL, 1)
    problem = _problem(
        (
            (first, (0, 1), (4, 1), (), (sibling,), ()),
            (sibling, (0, 1), (4, 1), (), (first,), ()),
        ),
        bounds=(0, 0, 4, 2),
    )

    result = route_global_once(problem, _feedback(problem), budget=20_000)

    assert result.paths[first] == result.paths[sibling]
    assert result.total_overflow == 0
    assert result.overflow_cells == 0


def test_capacity_sharing_does_not_merge_transitive_sibling_groups() -> None:
    first = NetId(0, 1, "iron", NetRole.INTERNAL, 0)
    bridge = NetId(0, 2, "iron", NetRole.INTERNAL, 0)
    stranger = NetId(3, 2, "iron", NetRole.INTERNAL, 0)
    problem = _problem(
        (
            (first, (0, 1), (4, 1), (), (bridge,), ()),
            (bridge, (0, 1), (4, 1), (), (first,), (stranger,)),
            (stranger, (0, 1), (4, 1), (), (), (bridge,)),
        ),
        bounds=(0, 0, 4, 2),
        keep_out={(x, y) for x in range(5) for y in (0, 2)},
    )

    result = route_global_once(problem, _feedback(problem), budget=20_000)

    assert result.paths[first] == result.paths[bridge] == result.paths[stranger]
    assert result.total_overflow == len(result.paths[first])
    assert result.overflow_cells == len(result.paths[first])


def test_same_item_strangers_do_not_share_capacity() -> None:
    first = NetId(0, 1, "iron", NetRole.INTERNAL, 0)
    stranger = NetId(2, 3, "iron", NetRole.INTERNAL, 0)
    problem = _problem(
        (
            (first, (0, 1), (4, 1), (), (), ()),
            (stranger, (0, 1), (4, 1), (), (), ()),
        ),
        bounds=(0, 0, 4, 2),
        keep_out={(x, y) for x in range(5) for y in (0, 2)},
    )

    result = route_global_once(problem, _feedback(problem), budget=20_000)

    assert result.total_overflow == len(result.paths[first])
    assert result.overflow_cells == len(result.paths[first])


def test_preparation_groups_internal_siblings_but_never_external_nets() -> None:
    first_id = NetId(0, 1, "iron", NetRole.INTERNAL, 0)
    sibling_id = NetId(0, 2, "iron", NetRole.PROLIFERATOR, 0)
    stranger_id = NetId(3, 1, "iron", NetRole.INTERNAL, 0)
    external_id = NetId(None, 1, "iron", NetRole.EXTERNAL, 0)
    first = _PreparedNet(
        first_id,
        _PreparedPort(0, 1, 1, 0, 3, (0,), 1),
        _PreparedPort(1, 8, 1, 8, 8, (1,), 1),
        "iron",
    )
    sibling = _PreparedNet(
        sibling_id,
        _PreparedPort(2, 2, 1, 0, 3, (2,), 1),
        _PreparedPort(3, 9, 1, 9, 9, (3,), 1),
        "iron",
    )
    stranger = _PreparedNet(
        stranger_id,
        _PreparedPort(4, 1, 2, 0, 3, (4,), 1),
        _PreparedPort(5, 8, 1, 8, 8, (5,), 1),
        "iron",
    )
    external = _PreparedNet(
        external_id,
        None,
        first.dst,
        "iron",
        ((0, 1, 0),),
        (first_id,),
        (stranger_id,),
    )

    grouped = _with_sibling_groups((first, sibling, stranger, external))

    assert grouped[0].src_group == (sibling_id,)
    assert grouped[0].dst_group == (stranger_id,)
    assert grouped[1].src_group == (first_id,)
    assert grouped[2].src_group == ()
    assert grouped[3].src_group == grouped[3].dst_group == ()


def test_external_net_routes_inward_from_prepared_boundary_goals() -> None:
    external = NetId(None, 1, "ore", NetRole.EXTERNAL, 0)
    access = (3, 1, 0)
    problem = _problem(
        ((external, None, (4, 1), ((0, 1, 0),), (), ()),),
        bounds=(0, 0, 4, 2),
        reserved=((access, (4, 1, 0)),),
    )

    result = route_global_once(problem, _feedback(problem), budget=20_000)

    assert result.paths[external][0] == (0, 1, 0)
    assert result.paths[external][-1] == access


def test_feedback_history_prices_legal_cells_without_blocking_them() -> None:
    net_id = NetId(0, 1, "iron", NetRole.INTERNAL, 0)
    priced_cell = (2, 1, 0)
    problem = _problem(
        ((net_id, (0, 1), (4, 1), (), (), ()),),
        bounds=(0, 0, 4, 2),
        keep_out={(x, y) for x in range(5) for y in (0, 2)},
    )

    result = route_global_once(
        problem,
        _feedback(problem, {priced_cell: 10.0}),
        budget=20_000,
    )

    path = result.paths[net_id]
    assert priced_cell in path
    _assert_current_detailed_legal_walk(path)


def test_expansion_budget_is_exact_and_returns_partial_metrics() -> None:
    problem, net_id = _one_net_problem()

    exhausted = route_global_once(problem, _feedback(problem), budget=2)
    exact = route_global_once(problem, _feedback(problem), budget=3)

    assert exhausted.expansions == 2
    assert exhausted.unreachable_ports == 1
    assert net_id not in exhausted.paths
    assert exact.expansions == 3
    assert exact.unreachable_ports == 0
    assert net_id in exact.paths


def test_zero_budget_expands_nothing() -> None:
    problem, _net_id = _one_net_problem()

    result = route_global_once(problem, _feedback(problem), budget=0)

    assert result.expansions == 0
    assert result.unreachable_ports == 1
    assert result.paths == {}
    assert result.rounds == 1


@pytest.mark.parametrize("budget", [-1, 1.5, True])
def test_budget_requires_a_non_negative_plain_integer(budget: object) -> None:
    problem, _net_id = _one_net_problem()
    with pytest.raises(ValueError, match="budget"):
        route_global_once(problem, _feedback(problem), budget=budget)  # type: ignore[arg-type]


def test_results_are_immutable_metrics_without_acceptance_or_placement_surface() -> None:
    problem, _net_id = _one_net_problem()

    result = route_global_once(problem, _feedback(problem), budget=20_000)

    assert isinstance(result, GlobalRouteResult)
    assert not hasattr(result, "valid")
    assert not hasattr(result, "placement")
    with pytest.raises(TypeError):
        result.paths[NetId(8, 9, "fake", NetRole.INTERNAL, 0)] = ()  # type: ignore[index]


def test_negotiation_moves_the_long_net_onto_the_available_detour() -> None:
    problem, short, long = _detour_problem()

    result = route_global(problem, _feedback(problem), budget=100_000)

    assert result.total_overflow == 0
    assert result.rounds >= 2
    assert (2, 2, 0) in result.paths[short]
    assert (2, 2, 0) not in result.paths[long]


def test_impossible_overflow_reports_five_rounds_of_metrics() -> None:
    result = route_global(
        _impossible_overflow_problem(),
        FeedbackState.empty((5, 3)),
        budget=100_000,
    )

    assert result.rounds == 5
    assert not result.exhausted_budget
    assert result.overflow_cells > 0
    assert result.total_overflow > 0
    assert result.max_overflow > 0


def test_global_routing_stops_when_the_hard_deadline_is_cancelled() -> None:
    problem, _net_id = _one_net_problem()
    checks = 0

    def cancelled() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 3

    result = route_global(
        problem,
        _feedback(problem),
        budget=100_000,
        cancelled=cancelled,
    )

    assert result.cancelled
    assert result.rounds == 1
    assert result.expansions < 3


def test_global_negotiation_honours_configured_round_count() -> None:
    problem = _impossible_overflow_problem()
    feedback = FeedbackState.empty((5, 3))

    once = route_global(problem, feedback, budget=100_000, max_rounds=1)
    multi = route_global(problem, feedback, budget=100_000, max_rounds=3)

    assert once.rounds == 1
    assert multi.rounds == 3
    assert once.total_overflow > 0
    assert multi.total_overflow > 0


def test_negotiation_spends_one_exact_shared_expansion_budget() -> None:
    problem = _impossible_overflow_problem()
    first_round = route_global_once(problem, _feedback(problem), budget=100_000)
    shared_budget = first_round.expansions + 1

    result = route_global(problem, _feedback(problem), budget=shared_budget)

    assert result.rounds == 2
    assert result.exhausted_budget
    assert result.expansions == shared_budget


def test_global_route_is_deterministic_and_longest_first() -> None:
    problem, short, long = _detour_problem()

    first = route_global(problem, _feedback(problem), budget=100_000)
    second = route_global(problem, _feedback(problem), budget=100_000)

    assert first == second
    assert tuple(result.net_id for result in first.net_results) == (long, short)
    assert tuple(first.paths) == (long, short)


def test_external_length_order_uses_its_closest_boundary_goal() -> None:
    external = NetId(None, 1, "ore", NetRole.EXTERNAL, 0)
    internal = NetId(2, 3, "iron", NetRole.INTERNAL, 0)
    problem = _problem(
        (
            (external, None, (8, 1), ((0, 1, 0), (7, 1, 0)), (), ()),
            (internal, (0, 3), (6, 3), (), (), ()),
        ),
        bounds=(0, 0, 8, 4),
    )

    result = route_global(problem, _feedback(problem), budget=20_000)

    assert tuple(net.net_id for net in result.net_results) == (internal, external)


def test_detailed_feedback_history_changes_the_global_route_choice() -> None:
    net_id = NetId(0, 1, "iron", NetRole.INTERNAL, 0)
    blocked = tuple((2, 2, level) for level in range(LEVELS))
    problem = _problem(
        ((net_id, (0, 2), (4, 2), (), (), ()),),
        bounds=(0, 0, 4, 4),
        blocked=blocked,
    )

    baseline = route_global(problem, _feedback(problem), budget=20_000)
    baseline_path = baseline.paths[net_id]
    priced = {cell: 10.0 for cell in baseline_path[1:-1]}
    changed = route_global(problem, _feedback(problem, priced), budget=20_000)
    changed_path = changed.paths[net_id]

    assert priced
    assert changed_path != baseline_path
    assert any(cell not in changed_path for cell in priced)
    assert set(baseline_path).isdisjoint(blocked)
    assert set(changed_path).isdisjoint(blocked)
    _assert_current_detailed_legal_walk(baseline_path)
    _assert_current_detailed_legal_walk(changed_path)


def test_hot_cells_are_history_ordered_bounded_and_boxed_deterministically() -> None:
    problem = _problem((), bounds=(0, 0, 19, 19))
    history = {(x, y, 0): 1.0 for x in range(15) for y in range(20)}
    history[(14, 19, 0)] = 2.0

    first = route_global(problem, _feedback(problem, history), budget=0)
    second = route_global(problem, _feedback(problem, history), budget=0)

    assert first.hot_cells == second.hot_cells
    assert first.hot_regions == second.hot_regions
    assert len(first.hot_cells) == 256
    assert first.hot_cells[0] == (14, 19, 0)
    assert first.hot_regions == ((0, 0, 13, 20), (14, 19, 15, 20))


def test_hot_regions_merge_projected_adjacent_cells_across_levels() -> None:
    problem = _problem((), bounds=(0, 0, 9, 9))
    history = {
        (5, 5, 0): 3.0,
        (1, 1, 0): 2.0,
        (1, 2, 0): 2.0,
        (1, 2, 1): 2.0,
        (8, 8, 0): 2.0,
    }

    result = route_global(problem, _feedback(problem, history), budget=0)

    assert result.hot_cells == (
        (5, 5, 0),
        (1, 1, 0),
        (1, 2, 0),
        (1, 2, 1),
        (8, 8, 0),
    )
    assert result.hot_regions == (
        (1, 1, 2, 3),
        (5, 5, 6, 6),
        (8, 8, 9, 9),
    )


def test_zero_overflow_proxy_cannot_be_certified_as_a_placement() -> None:
    problem, _net_id = _one_net_problem()
    result = route_global(problem, _feedback(problem), budget=20_000)

    assert result.total_overflow == 0
    assert not hasattr(result, "valid")
    assert not hasattr(result, "placement")
    with pytest.raises(AttributeError):
        validate.certify(
            result,  # type: ignore[arg-type]
            spec.BuildSpec(groups=()),
            expect_power=False,
        )
