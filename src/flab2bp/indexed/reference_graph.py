"""The import-reference graph, built once, queried many times.

`dsp.provenance` asks the same reachability question over and over and
hand-rolls a stack DFS for it every time (`Graph.closure`,
provenance.py:156-174): `frozen_captures` inverts a reach map by rescanning it
once per registry rule (provenance.py:477-509, ~126 rules x every import-time
node), and `hardcoding_readers` recomputes `g.closure(g.nodes_in(m))` INSIDE
its entry loop (provenance.py:512-529) -- the very hoist `consultation()`
already does two functions earlier (provenance.py:425-440), just with a
different (blocked) seed set.

networkx is the backend (Ruling 4's default). This is a lint/provenance path,
not a per-build path, so a pure-Python library costs nothing that matters and
buys correct, tested reachability. `reachable_from` reproduces `Graph.closure`
exactly, including its two quirks: a root missing from `edges` is dropped
rather than seeded, and a blocked node is refused at the EDGE (by the target's
owning module) rather than removed outright, so a blocked root -- reached only
as a seed, never as someone else's target -- still ends up in the result.
"""

from __future__ import annotations

from collections.abc import Iterable
from functools import cached_property
from types import MappingProxyType

import networkx as nx

from flab2bp.dsp.provenance import Graph

_IMPORT_TIME_KINDS = frozenset({"const", "default"})


class ReferenceGraph:
    """Reachability over one immutable construction-time graph snapshot.

    Source mapping changes after construction cannot affect adjacency, root
    membership, ownership or the metadata consumed by lazy query indexes.
    """

    def __init__(self, graph: Graph) -> None:
        self._graph = Graph(
            edges=MappingProxyType(dict(graph.edges)),
            owner=MappingProxyType(dict(graph.owner)),
            kind=MappingProxyType(dict(graph.kind)),
            calls=MappingProxyType(dict(graph.calls)),
        )
        digraph: nx.DiGraph = nx.DiGraph()
        digraph.add_nodes_from(self._graph.edges)
        for node, targets in self._graph.edges.items():
            for target in targets:
                digraph.add_edge(node, target)
        self._digraph = digraph

    @classmethod
    def of(cls, graph: Graph) -> ReferenceGraph:
        """Index a snapshot of one provenance graph."""
        return cls(graph)

    def reachable_from(
        self,
        roots: Iterable[str],
        *,
        block: Iterable[str] = (),
    ) -> frozenset[str]:
        """Everything reachable from ``roots``, never entering a blocked module.

        Matches `Graph.closure` exactly, including its two quirks: a root not
        in ``edges`` is dropped rather than seeded, and a blocked node is
        refused at the EDGE (by the target's owning module) rather than
        removed, so a blocked root is still in the result.
        """
        seeds = [r for r in roots if r in self._graph.edges]
        if not seeds:
            return frozenset()
        blocked = tuple(block)
        if not blocked:
            seen: set[str] = set(seeds)
            for seed in seeds:
                seen |= nx.descendants(self._digraph, seed)
            return frozenset(seen)
        banned = frozenset(blocked)
        allowed = self._digraph.edge_subgraph(
            [(u, v) for u, v in self._digraph.edges if self._graph.owner.get(v, "") not in banned]
        )
        seen = set(seeds)
        for seed in seeds:
            if seed in allowed:
                seen |= nx.descendants(allowed, seed)
        return frozenset(seen)

    def nodes_in(self, module: str) -> frozenset[str]:
        """Every node defined in one module."""
        return self._nodes_by_module.get(module, frozenset())

    @cached_property
    def _nodes_by_module(self) -> dict[str, frozenset[str]]:
        buckets: dict[str, set[str]] = {}
        for node, module in self._graph.owner.items():
            buckets.setdefault(module, set()).add(node)
        return {module: frozenset(nodes) for module, nodes in buckets.items()}

    def module_reach(self, modules: Iterable[str]) -> dict[str, frozenset[str]]:
        """One closure per module, computed once for the whole caller loop."""
        return {module: self.reachable_from(self.nodes_in(module)) for module in modules}

    @cached_property
    def _captures(self) -> dict[str, frozenset[str]]:
        out: dict[str, frozenset[str]] = {}
        for node, node_kind in self._graph.kind.items():
            if node_kind not in _IMPORT_TIME_KINDS:
                continue
            direct = self._graph.edges.get(node, frozenset())
            run = self.reachable_from(self._graph.calls.get(node, frozenset()))
            out[node] = direct | run
        return out

    def import_time_captures(self) -> dict[str, frozenset[str]]:
        """Node -> what it freezes at import, for every import-time node."""
        return dict(self._captures)

    @cached_property
    def _holders(self) -> dict[str, tuple[str, ...]]:
        inverted: dict[str, list[str]] = {}
        for holder, reach in self._captures.items():
            for node in reach:
                if node == holder:
                    continue
                inverted.setdefault(node, []).append(holder)
        return {node: tuple(sorted(holders)) for node, holders in inverted.items()}

    def holders_of(self, node: str) -> tuple[str, ...]:
        """Import-time nodes that froze ``node``, sorted; empty when none did."""
        return self._holders.get(node, ())
