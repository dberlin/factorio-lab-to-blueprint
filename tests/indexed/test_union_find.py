"""One path-compressed union-find, replacing three hand-rolled ones.

freeform.py writes the same structure from scratch at
`_prepared_routing_lower_bound`'s net-role grouping (around :8955-9017),
`_connect_short_cuts` (around :16008-16113) and `_join_shard_islands`
(around :16115-16233). This is a duplication defect, not a complexity
defect, and it is kept under Ruling I-5 for exactly that reason.
"""

from __future__ import annotations

import random

from flab2bp.indexed import UnionFind


def _brute_groups(nodes: list[int], pairs: list[tuple[int, int]]) -> set[frozenset[int]]:
    groups = [{n} for n in nodes]
    for left, right in pairs:
        hit = [g for g in groups if left in g or right in g]
        merged: set[int] = {left, right}
        for g in hit:
            merged |= g
            groups.remove(g)
        groups.append(merged)
    return {frozenset(g) for g in groups}


def test_groups_equal_a_brute_force_merge_on_random_pairs() -> None:
    rng = random.Random(71)
    for _ in range(50):
        nodes = list(range(30))
        pairs = [(rng.randrange(30), rng.randrange(30)) for _ in range(25)]
        uf = UnionFind()
        for node in nodes:
            uf.find(node)
        for left, right in pairs:
            uf.union(left, right)
        got = {frozenset(g) for g in uf.groups()}
        assert got == _brute_groups(nodes, pairs)


def test_union_reports_whether_it_actually_merged() -> None:
    uf = UnionFind()
    assert uf.union("a", "b")
    assert not uf.union("a", "b")
    assert not uf.union("b", "a")


def test_connected_is_reflexive_symmetric_and_transitive() -> None:
    uf = UnionFind()
    uf.union(1, 2)
    uf.union(2, 3)
    assert uf.connected(1, 1)
    assert uf.connected(1, 3) and uf.connected(3, 1)
    assert not uf.connected(1, 9)


def test_groups_are_in_first_insertion_order_and_sorted_within() -> None:
    uf = UnionFind()
    for node in (5, 3, 9, 1):
        uf.find(node)
    uf.union(9, 3)
    assert uf.groups() == ((5,), (3, 9), (1,))


def test_an_untouched_node_is_its_own_group() -> None:
    uf = UnionFind()
    assert uf.find("x") == "x"
    assert uf.groups() == (("x",),)
