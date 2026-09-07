"""`ReferenceGraph`-backed provenance mechanisms: `frozen_captures`, `hardcoding_readers`.

`frozen_captures` and `hardcoding_readers` (`dsp/provenance.py:478-530`) both used to
rewalk `Graph` by hand on every call -- the first inverting a per-node capture map
built inline, the second recomputing `closure(nodes_in(m))` once per
(entry, module) pair. Both now go through `ReferenceGraph` (`flab2bp.indexed`),
which memoizes the same walks: `holders_of` for the first, `module_reach` hoisted
out of the entry loop for the second.
"""

from __future__ import annotations

import pytest

from flab2bp.dsp import provenance


def test_frozen_captures_is_unchanged_by_the_index() -> None:
    """The converted body answers exactly what the scan answered.

    provenance.py:507 rescanned every import-time node's reach ONCE PER
    REGISTRY RULE (~126 of them). The captured map is the same for every rule,
    so inverting it once is the same answer with one pass instead of 126.
    """
    g = provenance.build_graph()
    captured: dict[str, frozenset[str]] = {}
    for node, node_kind in g.kind.items():
        if node_kind not in {"const", "default"}:
            continue
        captured[node] = g.edges.get(node, frozenset()) | g.closure(g.calls.get(node, frozenset()))
    expected: dict[str, tuple[str, ...]] = {}
    for entry in provenance.registry.rules():
        node = entry.dotted
        holders = [n for n, reach in captured.items() if n != node and node in reach]
        if holders:
            expected[entry.symbol] = tuple(sorted(holders))
    assert provenance.frozen_captures(g) == expected


def test_hardcoding_readers_is_unchanged_by_the_hoist() -> None:
    """provenance.py:527 recomputed `closure(nodes_in(m))` inside the entry loop."""
    modules = (*provenance.STRATEGY_MODULES, provenance.VALIDATE_MODULE)
    g = provenance.build_graph()
    expected: dict[str, tuple[str, ...]] = {}
    for entry in provenance.registry.ENTRIES:
        if not entry.hardcodes:
            continue
        expected[entry.symbol] = tuple(
            sorted(m for m in modules if entry.dotted in g.closure(g.nodes_in(m)))
        )
    assert provenance.hardcoding_readers(g) == expected


def test_hardcoding_readers_stops_calling_graph_closure_per_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The hoist is the point: before it, every hardcoding entry called
    `Graph.closure` once per module (:527); after it, `hardcoding_readers`
    never calls `Graph.closure` at all -- it reads `ReferenceGraph.module_reach`,
    computed once for the whole loop.

    This is a corrected replacement for the plan's own counter test (which
    counted calls to `ReferenceGraph.reachable_from` and could not fail: that
    method is never invoked by the pre-conversion body, so the assertion
    `len(calls) <= len(modules)` holds trivially both before and after -- 0 is
    always <= len(modules)). Counting `Graph.closure` calls instead actually
    distinguishes the two implementations.
    """
    calls: list[str] = []
    original = provenance.Graph.closure

    def counting(self, roots, *, block=()):  # type: ignore[no-untyped-def]
        calls.append("closure")
        return original(self, roots, block=block)

    monkeypatch.setattr(provenance.Graph, "closure", counting)
    provenance.hardcoding_readers(provenance.build_graph())
    assert calls == []
