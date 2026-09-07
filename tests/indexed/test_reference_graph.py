"""`ReferenceGraph` answers exactly what the inline walk answered.

The graph it replaces is `dsp.provenance.Graph.closure`, a hand-rolled stack
DFS. Equality against that walk on the REAL graph -- not a toy -- is the whole
proof, because the thing being protected is a lint verdict.
"""

from __future__ import annotations

import types

from flab2bp.dsp import provenance
from flab2bp.indexed import ReferenceGraph


def _toy() -> provenance.Graph:
    return provenance.Graph(
        edges=types.MappingProxyType(
            {
                "m.a": frozenset({"m.b"}),
                "m.b": frozenset({"n.c"}),
                "n.c": frozenset(),
                "n.d": frozenset({"m.a"}),
            }
        ),
        owner=types.MappingProxyType({"m.a": "m", "m.b": "m", "n.c": "n", "n.d": "n"}),
        kind=types.MappingProxyType(
            {"m.a": "const", "m.b": "func", "n.c": "default", "n.d": "func"}
        ),
        calls=types.MappingProxyType({"m.a": frozenset({"m.b"}), "n.c": frozenset()}),
    )


def test_reachable_from_equals_the_inline_closure_on_a_toy_graph() -> None:
    g = _toy()
    index = ReferenceGraph.of(g)
    for root in g.edges:
        assert index.reachable_from([root]) == g.closure([root])


def test_reachable_from_honours_a_blocked_module_exactly_as_the_walk_does() -> None:
    g = _toy()
    index = ReferenceGraph.of(g)
    assert index.reachable_from(["m.a"], block=["n"]) == g.closure(["m.a"], block=["n"])


def test_reachable_from_equals_the_inline_closure_on_the_real_graph() -> None:
    g = provenance.build_graph()
    index = ReferenceGraph.of(g)
    for root in g.edges:
        assert index.reachable_from([root]) == g.closure([root]), root


def test_module_reach_equals_a_closure_per_module() -> None:
    g = provenance.build_graph()
    index = ReferenceGraph.of(g)
    modules = sorted({m for m in g.owner.values()})[:6]
    assert index.module_reach(modules) == {m: g.closure(g.nodes_in(m)) for m in modules}


def test_holders_of_equals_a_brute_force_scan_of_the_captures() -> None:
    g = provenance.build_graph()
    index = ReferenceGraph.of(g)
    captured = index.import_time_captures()
    for node in sorted(g.edges):
        brute = tuple(sorted(n for n, reach in captured.items() if n != node and node in reach))
        assert index.holders_of(node) == brute, node


def test_import_time_captures_matches_frozen_captures_inline_formula_on_the_real_graph() -> None:
    """Independently reproduces `frozen_captures`'s per-node formula.

    `frozen_captures` (dsp/provenance.py:477-509) computes, for every
    `const`/`default` node, `g.edges.get(node, frozenset()) | g.closure(calls)`
    using the REAL hand-rolled `Graph.closure` -- not `ReferenceGraph` itself.
    This proves `import_time_captures()` reproduces that exact formula rather
    than merely being internally self-consistent (which the brute-force
    holders test above already covers for the inversion step alone).
    """
    g = provenance.build_graph()
    index = ReferenceGraph.of(g)
    captured = index.import_time_captures()
    import_time_nodes = [n for n, k in g.kind.items() if k in {"const", "default"}]
    assert import_time_nodes, "fixture must exercise at least one import-time node"
    for node in import_time_nodes:
        direct = g.edges.get(node, frozenset())
        run = g.closure(g.calls.get(node, frozenset()))
        assert captured[node] == direct | run, node
