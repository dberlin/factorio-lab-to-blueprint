# tests/layout/test_last_mile.py
from __future__ import annotations

from flab2bp.layout import last_mile

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
