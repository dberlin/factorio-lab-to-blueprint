"""The hierarchy block precedence graph, ordered without re-sorting the frontier.

`_topo_order` (`layout/hierarchy/partition.py:199`) re-derives a round's block
order with `ready = sorted(set(ready) - seen)` after EVERY dequeue: an O(n)
set-difference and an O(n log n) sort per node, so O(n^2 log n) total for a
walk that is O(n log n). It is re-derived every round of
`HierarchicalLayout.lay_out` by design -- the block graph genuinely changes
each round -- and only the internals move here.

`topological_order` replaces that resorted list with two min-heaps: `ready`,
holding nodes whose in-degree has hit zero, and a second heap seeded with
every node id up front and lazily popped-and-discarded of anything already
`seen` when the cycle-breaking fallback needs the lowest unseen id. Both are
genuinely O(n log n) in total, not O(n^2 log n), because every node's
successor-loop fires exactly once (each node is appended to `order` exactly
once): no node's in-degree ever reaches zero twice, so `ready` never takes a
duplicate push, and the fallback heap is only ever popped from -- never
re-heapified -- so every id leaves it at most once across the whole walk.
Neither heap branches on whether the graph has a cycle; one code path
handles both, and it is verified against a verbatim transcription of
`_topo_order` as an oracle (`tests/indexed/test_block_graph.py`) rather than
trusted by inspection.

Byte-identical output to master is the point of this branch, and using two
heaps instead of a resorted list changes nothing about WHAT is returned, only
how fast the frontier is found. Three things `_topo_order` does that a naive
Kahn's-algorithm transcription silently changes:

1. It skips self-loops (`if s == d: continue`) before building adjacency or
   in-degree, so a self-loop never blocks or appears for its own node.
2. It guards `peer not in seen` before re-queuing a node whose in-degree hit
   zero -- reproduced here as the same guard before pushing onto `ready`.
3. Its main loop is `while len(order) < n`, not `while ready`, with a
   cycle-breaking fallback: when the frontier runs dry before every block is
   placed, it forces in the lowest-index unseen block and carries on. That
   means it ALWAYS returns all `n` nodes, including nodes inside a cycle --
   there is no "acyclic prefix" behaviour to fall back on, and a hierarchy
   round with a cyclic block graph must not silently lose blocks.

Backend: networkx (Ruling 4's default) for the graph itself -- `in_degree`
and `successors` feed the two heaps above, and `has_cycle` is a genuine use
of `nx.is_directed_acyclic_graph`. Whether the per-round `DiGraph` build pays
for itself at the real block counts is Task 20's measurement to make behind
this same abstraction, not this module's to pre-empt.
"""

from __future__ import annotations

import heapq
from collections.abc import Iterable

import networkx as nx


class BlockGraph:
    """A block precedence graph with a deterministic topological order.

    Self-loops carry no precedence information and are dropped at
    construction -- never stored, never returned by `successors`, never
    counted in `has_cycle` -- mirroring `_topo_order`'s own skip.
    """

    __slots__ = ("_digraph", "_node_count")

    def __init__(self, node_count: int, edges: Iterable[tuple[int, int]]) -> None:
        digraph: nx.DiGraph = nx.DiGraph()
        digraph.add_nodes_from(range(node_count))
        digraph.add_edges_from((src, dst) for src, dst in edges if src != dst)
        self._digraph = digraph
        self._node_count = node_count

    @classmethod
    def of(cls, node_count: int, edges: Iterable[tuple[int, int]]) -> BlockGraph:
        """Build one round's block graph."""
        return cls(node_count, edges)

    def successors(self, node: int) -> tuple[int, ...]:
        """Blocks that must follow ``node``, ascending and deduplicated."""
        return tuple(sorted(self._digraph.successors(node)))

    def has_cycle(self) -> bool:
        """Whether any block precedence cycle exists (self-loops excluded)."""
        return not nx.is_directed_acyclic_graph(self._digraph)

    def topological_order(self) -> tuple[int, ...]:
        """Blocks in dependency order, exactly as master's `_topo_order` returns them.

        Kahn's algorithm on two min-heaps, ties broken by ascending block id.
        `ready` holds every node whose in-degree has hit zero; `fallback`
        starts seeded with every node id and is lazily drained of anything
        already `seen`, so when `ready` runs dry -- only possible on a cycle
        -- popping `fallback` yields the lowest-index unseen block, exactly
        what master's `sorted(i for i in range(n) if i not in seen)[0]`
        forces in. The walk then continues from that block normally, so this
        always returns all `node_count` blocks, in-cycle ones included. See
        the module docstring for why two heaps reproduce master's list-based
        walk exactly, in O(n log n) instead of O(n^2 log n).
        """
        indegree: dict[int, int] = dict(self._digraph.in_degree())
        ready = [node for node in range(self._node_count) if indegree[node] == 0]
        heapq.heapify(ready)
        fallback = list(range(self._node_count))  # already ascending: a valid heap as-is
        seen: set[int] = set()
        order: list[int] = []
        while len(order) < self._node_count:
            if ready:
                node = heapq.heappop(ready)
            else:
                while fallback and fallback[0] in seen:
                    heapq.heappop(fallback)
                node = heapq.heappop(fallback)
            if node in seen:
                continue
            seen.add(node)
            order.append(node)
            for peer in self._digraph.successors(node):
                indegree[peer] -= 1
                if indegree[peer] == 0 and peer not in seen:
                    heapq.heappush(ready, peer)
        return tuple(order)
