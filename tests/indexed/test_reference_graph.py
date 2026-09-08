"""`ReferenceGraph` answers exactly what the inline walk answered.

The graph it replaces is `dsp.provenance.Graph.closure`, a hand-rolled stack
DFS. Equality against that walk on the REAL graph protects lint verdicts;
mutable-source fixtures protect the construction-time snapshot contract.
"""

from __future__ import annotations

import types

import pytest

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


@pytest.fixture
def mutated_source_index() -> ReferenceGraph:
    """Change every backing map before any lazy query gets its first read."""
    edges = {
        "a.root": frozenset({"b.leaf"}),
        "b.leaf": frozenset(),
        "a.called": frozenset({"b.worker"}),
        "b.worker": frozenset({"c.value"}),
        "c.value": frozenset(),
    }
    owners = {
        "a.root": "a",
        "b.leaf": "b",
        "a.called": "a",
        "b.worker": "b",
        "c.value": "c",
    }
    kinds = {
        "a.root": "const",
        "b.leaf": "func",
        "a.called": "default",
        "b.worker": "func",
        "c.value": "func",
    }
    calls = {"a.root": frozenset(), "a.called": frozenset({"b.worker"})}
    index = ReferenceGraph.of(provenance.Graph(edges=edges, owner=owners, kind=kinds, calls=calls))
    edges["a.root"] = frozenset()
    del edges["b.leaf"]
    edges["later.root"] = frozenset()
    owners["b.leaf"] = "a"
    owners["later.root"] = "later"
    kinds["a.root"] = "func"
    kinds["b.leaf"] = "const"
    calls["a.called"] = frozenset()
    calls["a.root"] = frozenset({"c.value"})
    return index


def test_source_mutation_preserves_reachability_and_blocked_targets(
    mutated_source_index: ReferenceGraph,
) -> None:
    index = mutated_source_index
    assert index.reachable_from(["a.root"]) == frozenset({"a.root", "b.leaf"})
    assert index.reachable_from(["a.root"], block=["b"]) == frozenset({"a.root"})
    assert index.reachable_from(["a.root"], block=["a"]) == frozenset({"a.root", "b.leaf"})


def test_source_mutation_preserves_root_membership(
    mutated_source_index: ReferenceGraph,
) -> None:
    index = mutated_source_index
    assert index.reachable_from(["b.leaf"], block=["b"]) == frozenset({"b.leaf"})
    assert index.reachable_from(["later.root", "missing.root"]) == frozenset()


def test_source_mutation_preserves_module_queries(
    mutated_source_index: ReferenceGraph,
) -> None:
    index = mutated_source_index
    assert index.nodes_in("b") == frozenset({"b.leaf", "b.worker"})
    assert index.nodes_in("later") == frozenset()
    assert index.module_reach(["a", "b", "later"]) == {
        "a": frozenset({"a.root", "b.leaf", "a.called", "b.worker", "c.value"}),
        "b": frozenset({"b.leaf", "b.worker", "c.value"}),
        "later": frozenset(),
    }


def test_source_mutation_preserves_import_time_captures(
    mutated_source_index: ReferenceGraph,
) -> None:
    assert mutated_source_index.import_time_captures() == {
        "a.root": frozenset({"b.leaf"}),
        "a.called": frozenset({"b.worker", "c.value"}),
    }


def test_source_mutation_preserves_holders(
    mutated_source_index: ReferenceGraph,
) -> None:
    index = mutated_source_index
    assert index.holders_of("b.leaf") == ("a.root",)
    assert index.holders_of("c.value") == ("a.called",)
    assert index.holders_of("a.root") == ()
