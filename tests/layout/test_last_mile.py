# tests/layout/test_last_mile.py
from __future__ import annotations

import flab2bp.layout.freeform as freeform_module
from flab2bp.layout import last_mile
from flab2bp.layout.freeform import _astar, _Canvas, _PathSearchResult
from flab2bp.layout.route_feedback import RouteFailureKind

Cell = tuple[int, int, int]


def _endpoints(count: int) -> dict[int, tuple[Cell | None, Cell]]:
    return {index: ((index, 0, 0), (index, 9, 0)) for index in range(count)}


def test_a_wall_names_its_owners_as_cluster_members() -> None:
    problem = last_mile.build_cluster(
        [0],
        walls={0: ((5, 5, 0), (5, 6, 0))},
        blockers={0: ()},
        owner={(5, 5, 0): 2, (5, 6, 0): 3},
        paths={2: ((5, 5, 0),), 3: ((5, 6, 0),)},
        endpoints=_endpoints(4),
        src_group={},
        dst_group={},
    )

    assert problem.nets == (0, 2, 3)
    assert problem.stranded == (0,)
    assert problem.truncated is False


def test_blockers_are_added_even_when_the_wall_is_empty() -> None:
    problem = last_mile.build_cluster(
        [1],
        walls={1: ()},
        blockers={1: (4,)},
        owner={},
        paths={},
        endpoints=_endpoints(5),
        src_group={},
        dst_group={},
    )

    assert problem.nets == (1, 4)


def test_a_stranded_net_with_no_evidence_clusters_alone() -> None:
    problem = last_mile.build_cluster(
        [2],
        walls={2: ()},
        blockers={2: ()},
        owner={},
        paths={},
        endpoints=_endpoints(3),
        src_group={},
        dst_group={},
    )

    assert problem.nets == (2,)
    assert problem.truncated is False


def test_growth_is_transitive_until_the_cap_then_truncates_by_distance() -> None:
    problem = last_mile.build_cluster(
        [0],
        walls={0: ((1, 0, 0), (2, 0, 0), (3, 0, 0))},
        blockers={0: ()},
        owner={(1, 0, 0): 1, (2, 0, 0): 2, (3, 0, 0): 3},
        paths={1: ((1, 0, 0),), 2: ((2, 0, 0),), 3: ((3, 0, 0),)},
        endpoints=_endpoints(4),
        src_group={},
        dst_group={},
        max_cluster=3,
    )

    # Net 0's endpoints are (0, 0, 0) and (0, 9, 0); the two nearest owners win.
    assert problem.nets == (0, 1, 2)
    assert problem.truncated is True


def test_a_sibling_outside_the_cluster_makes_it_not_sibling_closed() -> None:
    closed = last_mile.build_cluster(
        [0],
        walls={0: ((1, 0, 0),)},
        blockers={0: ()},
        owner={(1, 0, 0): 1},
        paths={1: ((1, 0, 0),)},
        endpoints=_endpoints(3),
        src_group={0: (1,), 1: (0,)},
        dst_group={},
    )
    leaking = last_mile.build_cluster(
        [0],
        walls={0: ((1, 0, 0),)},
        blockers={0: ()},
        owner={(1, 0, 0): 1},
        paths={1: ((1, 0, 0),)},
        endpoints=_endpoints(3),
        src_group={0: (2,)},
        dst_group={},
    )

    assert closed.sibling_closed is True
    assert leaking.sibling_closed is False


def test_cluster_strips_are_ascending_and_drop_missing_owners() -> None:
    problem = last_mile.build_cluster(
        [0],
        walls={0: ()},
        blockers={0: (1,)},
        owner={},
        paths={},
        endpoints=_endpoints(2),
        src_group={},
        dst_group={},
    )

    strips = last_mile.cluster_strips(problem, {0: (3, None), 1: (1, 3)})

    assert strips == (1, 3)


def test_an_empty_stranded_list_is_refused() -> None:
    try:
        last_mile.build_cluster(
            [],
            walls={},
            blockers={},
            owner={},
            paths={},
            endpoints={},
            src_group={},
            dst_group={},
        )
    except ValueError as exc:
        assert "stranded" in str(exc)
    else:  # pragma: no cover - the call must raise
        raise AssertionError("an empty cluster must be refused")


def _offers_stub(_index: int) -> last_mile._Offers:
    return ({}, {}, {})


def _grid_environment(
    canvas: _Canvas,
    bounds: tuple[int, int, int, int],
    ends: dict[int, tuple[list[Cell], set[Cell]]],
    *,
    budget: dict[str, int] | None = None,
    max_nodes: int = last_mile.B_MAX_CBS_NODES,
) -> last_mile.ClusterEnvironment:
    """A CBS environment whose low level is the real router's A*."""
    left = {"left": 1 << 30} if budget is None else budget

    def search(index: int, constraints: frozenset[Cell]) -> _PathSearchResult:
        starts, goals = ends[index]
        return _astar(
            canvas,
            list(starts),
            set(goals),
            {},
            1.0,
            bounds,
            left,
            None,
            None,
            None,
            (),
            (),
            constraints,
            None,
        )

    return last_mile.ClusterEnvironment(
        search=search,
        offers=_offers_stub,
        budget_left=lambda: left["left"],
        budget_floor=0,
        expired=lambda: False,
        max_nodes=max_nodes,
    )


def _crossing_canvas() -> tuple[_Canvas, tuple[int, int, int, int]]:
    """An empty 5x5 box, so the two nets' shortest paths cross at (2, 2, 0)."""
    bounds = (0, 0, 4, 4)
    return _Canvas(limit=bounds), bounds


#: The two nets of `_crossing_canvas`: one along row 2, one down column 2.
_CROSSING_ENDS: dict[int, tuple[list[Cell], set[Cell]]] = {
    0: ([(0, 2, 0)], {(4, 2, 0)}),
    1: ([(2, 0, 0)], {(2, 4, 0)}),
}


def test_two_crossing_nets_are_solved_jointly() -> None:
    canvas, bounds = _crossing_canvas()
    problem = last_mile.ClusterProblem(
        nets=(0, 1), stranded=(0,), truncated=False, sibling_closed=True
    )

    result = last_mile.solve_cluster(
        problem, _grid_environment(canvas, bounds, _CROSSING_ENDS)
    )

    assert result.outcome is last_mile.ClusterOutcome.SOLVED
    assert set(result.paths) == {0, 1}
    assert not set(result.paths[0]) & set(result.paths[1])
    assert result.nodes <= last_mile.B_MAX_CBS_NODES


def test_a_gap_that_cannot_hold_two_nets_is_proved_infeasible() -> None:
    """Both nets must cross x=2, and the only opening is one cell on level 0."""
    bounds = (0, 0, 4, 2)
    canvas = _Canvas(limit=bounds)
    for y in range(3):
        for level in range(freeform_module.LEVELS):
            if (y, level) == (1, 0):
                continue
            canvas.blocked[2, y, level] = 0
    problem = last_mile.ClusterProblem(
        nets=(0, 1), stranded=(0, 1), truncated=False, sibling_closed=True
    )
    ends = {
        0: ([(0, 0, 0)], {(4, 0, 0)}),
        1: ([(0, 2, 0)], {(4, 2, 0)}),
    }

    result = last_mile.solve_cluster(problem, _grid_environment(canvas, bounds, ends))

    assert result.outcome is last_mile.ClusterOutcome.PROVED
    assert result.paths == {}
    assert result.nodes < last_mile.B_MAX_CBS_NODES


def test_a_node_bound_reports_bounded_and_never_proved() -> None:
    bounds = (0, 0, 4, 2)
    canvas = _Canvas(limit=bounds)
    for y in range(3):
        for level in range(freeform_module.LEVELS):
            if (y, level) == (1, 0):
                continue
            canvas.blocked[2, y, level] = 0
    problem = last_mile.ClusterProblem(
        nets=(0, 1), stranded=(0, 1), truncated=False, sibling_closed=True
    )
    ends = {
        0: ([(0, 0, 0)], {(4, 0, 0)}),
        1: ([(0, 2, 0)], {(4, 2, 0)}),
    }

    result = last_mile.solve_cluster(
        problem,
        _grid_environment(canvas, bounds, ends, max_nodes=1),
    )

    assert result.outcome is last_mile.ClusterOutcome.BOUNDED
    assert result.paths == {}
    assert result.bound is last_mile.ClusterBound.NODES


def test_a_cut_low_level_search_is_never_a_proof() -> None:
    """H1: a tree that empties only because a search was capped proves nothing."""
    problem = last_mile.ClusterProblem(
        nets=(0, 1), stranded=(0, 1), truncated=False, sibling_closed=True
    )
    cut = _PathSearchResult(None, RouteFailureKind.BUDGET, (), 0)

    def search(index: int, constraints: frozenset[Cell]) -> _PathSearchResult:
        return cut

    environment = last_mile.ClusterEnvironment(
        search=search,
        offers=_offers_stub,
        budget_left=lambda: 1 << 30,
        budget_floor=0,
        expired=lambda: False,
    )

    result = last_mile.solve_cluster(problem, environment)

    assert result.outcome is last_mile.ClusterOutcome.BOUNDED
    assert result.bound is last_mile.ClusterBound.BUDGET
    assert result.paths == {}


def test_an_exhausted_expansion_floor_reports_bounded() -> None:
    canvas, bounds = _crossing_canvas()
    problem = last_mile.ClusterProblem(
        nets=(0, 1), stranded=(0,), truncated=False, sibling_closed=True
    )
    environment = _grid_environment(
        canvas, bounds, _CROSSING_ENDS, budget={"left": 0}
    )

    result = last_mile.solve_cluster(problem, environment)

    assert result.outcome is last_mile.ClusterOutcome.BOUNDED
    assert result.bound is last_mile.ClusterBound.BUDGET


def test_constraints_keep_a_net_off_the_cell_it_was_split_on() -> None:
    canvas, bounds = _crossing_canvas()
    problem = last_mile.ClusterProblem(
        nets=(0, 1), stranded=(0,), truncated=False, sibling_closed=True
    )

    result = last_mile.solve_cluster(
        problem, _grid_environment(canvas, bounds, _CROSSING_ENDS)
    )

    assert result.outcome is last_mile.ClusterOutcome.SOLVED
    crossing = (2, 2, 0)
    assert sum(crossing in path for path in result.paths.values()) <= 1


def test_the_same_cluster_solves_identically_twice() -> None:
    problem = last_mile.ClusterProblem(
        nets=(0, 1), stranded=(0,), truncated=False, sibling_closed=True
    )
    first_canvas, bounds = _crossing_canvas()
    second_canvas, _bounds = _crossing_canvas()

    first = last_mile.solve_cluster(
        problem, _grid_environment(first_canvas, bounds, _CROSSING_ENDS)
    )
    second = last_mile.solve_cluster(
        problem, _grid_environment(second_canvas, bounds, _CROSSING_ENDS)
    )

    assert first.paths == second.paths
    assert first.nodes == second.nodes
    assert first.expansions == second.expansions


def test_paths_on_different_levels_over_one_column_do_not_conflict() -> None:
    problem = last_mile.ClusterProblem(
        nets=(0, 1), stranded=(0,), truncated=False, sibling_closed=True
    )
    conflict = last_mile._first_conflict(
        problem,
        {0: ((1, 0, 0), (2, 0, 0)), 1: ((1, 0, 2), (2, 0, 2))},
    )
    shared = last_mile._first_conflict(
        problem,
        {0: ((1, 0, 0), (2, 0, 0)), 1: ((2, 0, 0), (3, 0, 0))},
    )

    assert conflict is None
    assert shared == (0, 1, (2, 0, 0))
