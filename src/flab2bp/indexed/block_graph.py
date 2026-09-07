"""The hierarchy block precedence graph, ordered without re-sorting the frontier.

`_topo_order` (`layout/hierarchy/partition.py:199`) re-derives a round's block
order with `ready = sorted(set(ready) - seen)` after EVERY dequeue: an O(n)
set-difference and an O(n log n) sort per node, so O(n^2 log n) total for a
walk that is O(n log n). It is re-derived every round of
`HierarchicalLayout.lay_out` by design -- the block graph genuinely changes
each round -- and only the internals move here.

Byte-identical output to master is the point of this branch, and a naive
Kahn's-algorithm transcription silently changes it in three places that
`_topo_order` does not:

1. It skips self-loops (`if s == d: continue`) before building adjacency or
   in-degree, so a self-loop never blocks or appears for its own node.
2. It guards `peer not in seen` before re-queuing a node whose in-degree hit
   zero, alongside the unconditional `ready = sorted(set(ready) - seen)` that
   follows every dequeue.
3. Its main loop is `while len(order) < n`, not `while ready`, with a
   cycle-breaking fallback: when the frontier runs dry before every block is
   placed, it forces in the lowest-index unseen block and carries on. That
   means it ALWAYS returns all `n` nodes, including nodes inside a cycle --
   there is no "acyclic prefix" behaviour to fall back on, and a hierarchy
   round with a cyclic block graph must not silently lose blocks.

`topological_order` reproduces master's walk exactly rather than delegating to
`nx.lexicographical_topological_sort` (which raises on a cycle and would need
a second, separately-verified code path for the fallback); the two networkx
calls it does use -- `in_degree` and `successors` -- only replace the
hand-rolled `indeg`/`adj` tables, not the walk itself. Backend: networkx
(Ruling 4's default). The measurement task for the hierarchy conversion
decides whether the per-round `DiGraph` build pays for itself at the real
block counts.
"""

from __future__ import annotations

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

        Kahn's algorithm, ties broken by ascending block id. When the ready
        frontier runs dry before every block is placed -- only possible on a
        cycle -- the lowest-index unseen block is forced in and the walk
        continues, so this always returns all `node_count` blocks, in-cycle
        ones included. See the module docstring for why this is transcribed
        rather than composed from `nx.lexicographical_topological_sort`.
        """
        indegree: dict[int, int] = dict(self._digraph.in_degree())
        ready = sorted(node for node in range(self._node_count) if indegree[node] == 0)
        seen: set[int] = set()
        order: list[int] = []
        while len(order) < self._node_count:
            if not ready:
                leftover = sorted(node for node in range(self._node_count) if node not in seen)
                ready = [leftover[0]]
            node = ready.pop(0)
            if node in seen:
                continue
            seen.add(node)
            order.append(node)
            for peer in self._digraph.successors(node):
                indegree[peer] -= 1
                if indegree[peer] == 0 and peer not in seen:
                    ready.append(peer)
            ready = sorted(set(ready) - seen)
        return tuple(order)
