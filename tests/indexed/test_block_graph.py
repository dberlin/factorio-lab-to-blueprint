"""`BlockGraph.topological_order` equals master's `_topo_order` exactly.

`_topo_order` (`layout/hierarchy/partition.py:199`) re-sorts its ready
frontier on EVERY dequeue (`ready = sorted(set(ready) - seen)`), which is
O(n^2 log n). It is re-derived every round of `HierarchicalLayout.lay_out`
(`hierarchy/strategy.py`), by design, because the block graph genuinely
changes each round.

The order is BYTE-VISIBLE -- it decides which cut a round takes -- so equality
with the real walk on randomised graphs is the whole proof. Per Ruling P-7,
that walk (a) skips self-loops, (b) guards `peer not in seen` before
re-queuing, and (c) never stops early on a cycle: `while len(order) < n` with
a lowest-index fallback means it always returns all `n` nodes, cyclic ones
included. The equality tests below cover DAGs, cyclic graphs and
self-looping graphs so a divergence in any of the three would fail here.
"""

from __future__ import annotations

import random
from collections import defaultdict

from flab2bp.indexed import BlockGraph

# --- Frozen oracle -----------------------------------------------------------
#
# Verbatim transcription of `_topo_order` at `layout/hierarchy/partition.py:199`
# (this worktree's HEAD, commit 8d441bd2). Per Ruling P-10 this is the one and
# only copy on the branch; Task 20 imports it from here rather than
# re-transcribing. Do NOT "clean up" or simplify this function -- its exact
# shape, including the guards and the fallback, is the thing under test.


def _topo_order_oracle(n: int, edges: set[tuple[int, int]]) -> list[int]:
    """Kahn order; any cycle is broken by lowest index so this always returns."""
    indeg = dict.fromkeys(range(n), 0)
    adj: dict[int, list[int]] = defaultdict(list)
    for s, d in edges:
        if s == d:
            continue
        adj[s].append(d)
        indeg[d] += 1
    order: list[int] = []
    ready = sorted(i for i in range(n) if indeg[i] == 0)
    seen: set[int] = set()
    while len(order) < n:
        if not ready:
            leftover = sorted(i for i in range(n) if i not in seen)
            ready = [leftover[0]]
        node = ready.pop(0)
        if node in seen:
            continue
        seen.add(node)
        order.append(node)
        for peer in adj[node]:
            indeg[peer] -= 1
            if indeg[peer] == 0 and peer not in seen:
                ready.append(peer)
        ready = sorted(set(ready) - seen)
    return order


# --- Random graph generators --------------------------------------------------


def _random_dag(rng: random.Random, node_count: int) -> list[tuple[int, int]]:
    order = list(range(node_count))
    rng.shuffle(order)
    edges: list[tuple[int, int]] = []
    for i, src in enumerate(order):
        for dst in order[i + 1 :]:
            if rng.random() < 0.12:
                edges.append((src, dst))
    return edges


def _random_graph_with_cycles(rng: random.Random, node_count: int) -> set[tuple[int, int]]:
    """Any directed graph over `node_count` nodes -- cycles and self-loops allowed."""
    edges: set[tuple[int, int]] = set()
    if node_count == 0:
        return edges
    for src in range(node_count):
        for dst in range(node_count):
            if rng.random() < 0.08:
                edges.add((src, dst))
    return edges


def _random_self_looping_dag(rng: random.Random, node_count: int) -> set[tuple[int, int]]:
    """A random DAG with a self-loop stapled onto some nodes."""
    edges: set[tuple[int, int]] = set(_random_dag(rng, node_count))
    for node in range(node_count):
        if rng.random() < 0.3:
            edges.add((node, node))
    return edges


# --- Equality tests ------------------------------------------------------------


def test_topological_order_equals_the_oracle_on_random_dags() -> None:
    rng = random.Random(61)
    for node_count in (1, 2, 5, 12, 40, 120):
        for _ in range(20):
            edges = _random_dag(rng, node_count)
            got = BlockGraph.of(node_count, edges).topological_order()
            assert got == tuple(_topo_order_oracle(node_count, set(edges))), (node_count, edges)


def test_topological_order_equals_the_oracle_on_random_cyclic_graphs() -> None:
    rng = random.Random(1729)
    for node_count in (0, 1, 2, 5, 12, 40):
        for _ in range(30):
            edges = _random_graph_with_cycles(rng, node_count)
            got = BlockGraph.of(node_count, edges).topological_order()
            assert got == tuple(_topo_order_oracle(node_count, edges)), (node_count, edges)
            assert len(got) == node_count


def test_topological_order_equals_the_oracle_on_self_looping_dags() -> None:
    rng = random.Random(2026)
    for node_count in (1, 2, 5, 12, 40):
        for _ in range(20):
            edges = _random_self_looping_dag(rng, node_count)
            got = BlockGraph.of(node_count, edges).topological_order()
            assert got == tuple(_topo_order_oracle(node_count, edges)), (node_count, edges)


def test_a_graph_with_no_edges_orders_by_node_id() -> None:
    assert BlockGraph.of(5, []).topological_order() == (0, 1, 2, 3, 4)


def test_has_cycle_is_true_for_a_cycle_and_false_for_a_dag() -> None:
    assert BlockGraph.of(3, [(0, 1), (1, 2), (2, 0)]).has_cycle()
    assert not BlockGraph.of(3, [(0, 1), (1, 2)]).has_cycle()


def test_a_self_loop_alone_is_not_a_cycle() -> None:
    """A self-loop carries no precedence and must not register as a cycle.

    `_topo_order` skips `s == d` before building its adjacency or in-degree
    tables, so a lone self-loop never blocks anything; `has_cycle` mirrors
    that by excluding self-loops from the graph entirely.
    """
    assert not BlockGraph.of(1, [(0, 0)]).has_cycle()


def test_a_cyclic_block_graph_still_orders_all_blocks() -> None:
    """Regression for Ruling P-7: the fallback returns every node, not a prefix.

    `_topo_order`'s main loop is `while len(order) < n`, not `while ready`: on
    a cycle the frontier can run dry before every block is placed, and the
    lowest-index unseen block is forced in rather than the walk stopping. A
    version that instead emitted only the acyclic prefix would silently drop
    the in-cycle blocks from a hierarchy round.
    """
    edges = [(0, 1), (1, 2), (2, 1), (0, 3)]
    got = BlockGraph.of(4, edges).topological_order()
    assert len(got) == 4
    assert sorted(got) == [0, 1, 2, 3]
    assert got == tuple(_topo_order_oracle(4, set(edges)))


def test_a_self_loop_does_not_block_its_own_node() -> None:
    """A node whose only in-edge is its own self-loop still gets ordered.

    A naive Kahn transcription that counts the self-loop into in-degree would
    never see this node's in-degree reach zero and would drop it from the
    frontier -- and thus from the output -- entirely.
    """
    got = BlockGraph.of(1, [(0, 0)]).topological_order()
    assert got == (0,)


def test_successors_are_ascending_and_deduplicated() -> None:
    graph = BlockGraph.of(4, [(0, 2), (0, 1), (0, 2)])
    assert graph.successors(0) == (1, 2)
    assert graph.successors(3) == ()


def test_successors_excludes_a_self_loop() -> None:
    assert BlockGraph.of(2, [(0, 0), (0, 1)]).successors(0) == (1,)


def test_graph_queries_and_repeated_ordering_preserve_cycle_breaking() -> None:
    graph = BlockGraph.of(4, iter(((0, 2), (2, 1), (1, 2), (0, 2), (3, 3))))
    assert graph.topological_order() == (0, 3, 1, 2)
    assert graph.has_cycle()
    assert graph.successors(0) == (2,)
    assert graph.successors(3) == ()
    assert graph.topological_order() == (0, 3, 1, 2)
