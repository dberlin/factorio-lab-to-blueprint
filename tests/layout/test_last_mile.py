# tests/layout/test_last_mile.py
from __future__ import annotations

from dataclasses import replace

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


def test_one_stranded_net_per_un_tappable_source_enters_the_cluster() -> None:
    """Siblings on a lane no splitter fits keep exactly one seat, the lowest.

    Both nets are released before the search, so ``_ends`` offers each the same
    direct access cells as though it were the first to leave the lane.  CBS then
    hands each a different one and calls them disjoint -- and the committer
    refuses the second with ``junction-collider``, because that lane can be left
    directly by one net and no more.  ``universe-matrix/output-products``
    cluster ``(36, 37)``, source ``(172, 18, 0)``.
    """
    problem = last_mile.build_cluster(
        [3, 5, 7],
        walls={3: (), 5: (), 7: ()},
        blockers={3: (), 5: (), 7: ()},
        owner={},
        paths={},
        endpoints=_endpoints(8),
        # 3 and 5 share a blocked lane; 7 has a lane of its own.
        src_group={3: (5,), 5: (3,), 7: ()},
        dst_group={},
        source_junctionable=lambda index: index == 7,
    )

    assert problem.nets == (3, 7)
    assert problem.stranded == (3, 7)
    assert problem.same_source_dropped == 1


def test_siblings_on_a_tappable_source_all_keep_their_seats() -> None:
    """The drop is about the SPLITTER SITE, not about sharing a lane.

    A lane whose junction site is usable can hand a second branch to a second
    net, which is the ordinary case and the one the whole merge machinery
    exists for.  Without this, "share a source" alone would gut every cluster
    on a producer lane.
    """
    problem = last_mile.build_cluster(
        [3, 5],
        walls={3: (), 5: ()},
        blockers={3: (), 5: ()},
        owner={},
        paths={},
        endpoints=_endpoints(6),
        src_group={3: (5,), 5: (3,)},
        dst_group={},
        source_junctionable=lambda _index: True,
    )

    assert problem.nets == (3, 5)
    assert problem.same_source_dropped == 0


def test_without_a_junction_predicate_the_cluster_is_unchanged() -> None:
    """The parameter is optional and its absence is today's behaviour exactly."""
    problem = last_mile.build_cluster(
        [3, 5],
        walls={3: (), 5: ()},
        blockers={3: (), 5: ()},
        owner={},
        paths={},
        endpoints=_endpoints(6),
        src_group={3: (5,), 5: (3,)},
        dst_group={},
    )

    assert problem.nets == (3, 5)
    assert problem.same_source_dropped == 0


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


def _gap_canvas() -> tuple[_Canvas, tuple[int, int, int, int]]:
    """A wall at x=2 with ONE opening, at ``(2, 1, 0)``.

    Both nets must cross the wall and only one of them can hold the opening, so
    the cluster is infeasible and a closed tree is the honest answer.
    """
    bounds = (0, 0, 4, 2)
    canvas = _Canvas(limit=bounds)
    for y in range(3):
        for level in range(freeform_module.LEVELS):
            if (y, level) == (1, 0):
                continue
            canvas.blocked[2, y, level] = 0
    return canvas, bounds


#: The two nets of `_gap_canvas`: one along row 0, one along row 2.
_GAP_ENDS: dict[int, tuple[list[Cell], set[Cell]]] = {
    0: ([(0, 0, 0)], {(4, 0, 0)}),
    1: ([(0, 2, 0)], {(4, 2, 0)}),
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
    # The root pair CROSSES, so the root node cannot be the answer: a fixture
    # whose nets stopped conflicting would make this test vacuous.
    assert result.nodes >= 2


def test_a_gap_that_cannot_hold_two_nets_is_proved_infeasible() -> None:
    """Both nets must cross x=2, and the only opening is one cell on level 0."""
    canvas, bounds = _gap_canvas()
    problem = last_mile.ClusterProblem(
        nets=(0, 1), stranded=(0, 1), truncated=False, sibling_closed=True
    )

    result = last_mile.solve_cluster(
        problem, _grid_environment(canvas, bounds, _GAP_ENDS)
    )

    assert result.outcome is last_mile.ClusterOutcome.PROVED
    assert result.paths == {}
    assert result.nodes < last_mile.B_MAX_CBS_NODES


def test_a_node_bound_reports_bounded_and_never_proved() -> None:
    canvas, bounds = _gap_canvas()
    problem = last_mile.ClusterProblem(
        nets=(0, 1), stranded=(0, 1), truncated=False, sibling_closed=True
    )

    result = last_mile.solve_cluster(
        problem,
        _grid_environment(canvas, bounds, _GAP_ENDS, max_nodes=1),
    )

    assert result.outcome is last_mile.ClusterOutcome.BOUNDED
    assert result.paths == {}
    assert result.bound is last_mile.ClusterBound.NODES


def test_a_cut_low_level_search_is_never_a_proof() -> None:
    """H1: a tree that empties only because a search was capped proves nothing.

    The grid is the infeasible one-gap cluster, which closes as PROVED when
    every search concludes honestly.  The cut is planted on the SECOND net's
    FIRST constrained re-plan, so both root searches still reach real
    conclusions and only the in-tree check can catch it: without that check
    the capped child is priced as "this net has no path", the tree empties,
    and the run claims a proof it did not earn.
    """
    canvas, bounds = _gap_canvas()
    problem = last_mile.ClusterProblem(
        nets=(0, 1), stranded=(0, 1), truncated=False, sibling_closed=True
    )
    environment = _grid_environment(canvas, bounds, _GAP_ENDS)
    planned = environment.search
    cut = _PathSearchResult(None, RouteFailureKind.BUDGET, (), 0)
    replans = 0

    def search(index: int, constraints: frozenset[Cell]) -> _PathSearchResult:
        nonlocal replans
        if index == 1 and constraints:
            replans += 1
            if replans == 1:
                return cut
        return planned(index, constraints)

    result = last_mile.solve_cluster(problem, replace(environment, search=search))

    assert result.outcome is last_mile.ClusterOutcome.BOUNDED
    assert result.bound is last_mile.ClusterBound.BUDGET
    assert result.paths == {}
    # The cut landed INSIDE the tree, after the root pair was expanded.
    assert result.nodes >= 1


def test_an_exhausted_expansion_floor_reports_bounded() -> None:
    """The floor is checked BETWEEN nodes, not only on the way in."""
    canvas, bounds = _crossing_canvas()
    problem = last_mile.ClusterProblem(
        nets=(0, 1), stranded=(0,), truncated=False, sibling_closed=True
    )
    budget = {"left": 1 << 30}
    environment = _grid_environment(canvas, bounds, _CROSSING_ENDS, budget=budget)
    planned = environment.search
    replans = 0

    def draining(index: int, constraints: frozenset[Cell]) -> _PathSearchResult:
        nonlocal replans
        found = planned(index, constraints)
        if constraints:
            replans += 1
            if replans == 2:
                # The root pair and the first node's two children are paid for;
                # the pass has nothing left for the node now on the heap.
                budget["left"] = 0
        return found

    result = last_mile.solve_cluster(problem, replace(environment, search=draining))

    assert result.outcome is last_mile.ClusterOutcome.BOUNDED
    assert result.bound is last_mile.ClusterBound.BUDGET
    assert result.paths == {}
    assert result.nodes >= 1


def test_a_budget_already_at_the_floor_never_starts() -> None:
    canvas, bounds = _crossing_canvas()
    problem = last_mile.ClusterProblem(
        nets=(0, 1), stranded=(0,), truncated=False, sibling_closed=True
    )

    result = last_mile.solve_cluster(
        problem,
        _grid_environment(canvas, bounds, _CROSSING_ENDS, budget={"left": 0}),
    )

    assert result.outcome is last_mile.ClusterOutcome.BOUNDED
    assert result.bound is last_mile.ClusterBound.BUDGET
    assert result.nodes == 0


def test_constraints_keep_a_net_off_the_cell_it_was_split_on() -> None:
    """A winning path came from a constrained re-plan and honours it exactly."""
    canvas, bounds = _crossing_canvas()
    problem = last_mile.ClusterProblem(
        nets=(0, 1), stranded=(0,), truncated=False, sibling_closed=True
    )
    environment = _grid_environment(canvas, bounds, _CROSSING_ENDS)
    planned = environment.search
    replans: list[tuple[int, frozenset[Cell], tuple[Cell, ...] | None]] = []

    def recording(index: int, constraints: frozenset[Cell]) -> _PathSearchResult:
        found = planned(index, constraints)
        if constraints:
            replans.append((index, constraints, found.path))
        return found

    result = last_mile.solve_cluster(problem, replace(environment, search=recording))

    assert result.outcome is last_mile.ClusterOutcome.SOLVED
    assert replans, "two crossing nets must force at least one split"
    winners = [
        (index, constraints)
        for index, constraints, path in replans
        if path is not None and result.paths[index] == path
    ]
    assert winners, "the answer must come from a constrained re-plan, not the root"
    for index, constraints in winners:
        for cell in constraints:
            assert result.paths[index].count(cell) == 0, (
                f"net {index} was split off {cell} and still stands on it"
            )


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


def test_relation_no_good_records_offsets_from_the_anchor() -> None:
    no_good = last_mile.relation_no_good(
        strips=(1, 3),
        origins=((0, 0), (10, 4), (0, 0), (22, 9)),
        outline=((2, 2), (3, 3), (2, 2), (4, 4)),
        height=20,
        evidence="cluster: nets=(4, 7)",
    )

    assert no_good is not None
    assert no_good.strips == (1, 3)
    assert no_good.deltas == ((0, 0), (12, 5))
    assert no_good.height == 20
    assert no_good.evidence == ("cluster: nets=(4, 7)",)


def test_relation_no_good_needs_two_strip_instances() -> None:
    assert (
        last_mile.relation_no_good(
            strips=(2,),
            origins=((0, 0), (1, 1), (2, 2)),
            outline=((1, 1), (1, 1), (1, 1)),
            height=4,
            evidence="x",
        )
        is None
    )


def test_relation_no_good_drops_a_strip_outside_the_pack() -> None:
    no_good = last_mile.relation_no_good(
        strips=(0, 1, 99),
        origins=((0, 0), (5, 0)),
        outline=((1, 1), (1, 1)),
        height=3,
        evidence="x",
    )

    assert no_good is not None
    assert no_good.strips == (0, 1)
