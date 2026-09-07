"""`ReferenceGraph`-backed provenance mechanisms.

`frozen_captures` (`dsp/provenance.py`) used to build its `captured` map once
(`g.closure` per import-time node -- that part was never the defect) and then,
for EACH of the ~126 registry rules, linear-scan `captured.items()` looking for
holders: O(rules x captured-map-size). It now goes through `ReferenceGraph`
(`flab2bp.indexed`), whose `holders_of` answers the same question from a map
(`_holders`, a `cached_property`) inverted once and then looked up by key --
O(rules) dict lookups after one O(captured-map-size) build.

`hardcoding_readers` was ALSO converted to `ReferenceGraph.module_reach` in a
first pass, then reverted -- see the note on that function in
`src/flab2bp/dsp/provenance.py` and this task's report. `module_reach` seeds
`reachable_from` with `nodes_in(module)`, and `ReferenceGraph.reachable_from`
calls `nx.descendants` once PER SEED rather than doing one multi-source
traversal; for a module like `flab2bp.layout.freeform` (438 top-level
definitions) that made the "hoisted" form ~9x slower than the hand-rolled
`Graph.closure` version it was meant to replace, measured on the realistic
call pattern (`frozen_captures` and `hardcoding_readers` both called on one
graph, as `scripts/rule_report.py` does). `hardcoding_readers` therefore keeps
its master-identical body; its behaviour is already covered by
`tests/rules/test_rule_registry.py::test_a_rule_consulted_only_at_a_hardcoded_tech_level_is_reported`.
"""

from __future__ import annotations

from flab2bp.dsp import provenance


def test_frozen_captures_is_unchanged_by_the_index() -> None:
    """The converted body answers exactly what the scan answered.

    This reproduces master's `frozen_captures` body verbatim as the oracle: it
    builds `captured` the same way (one `g.closure` per import-time node) and
    then answers each rule from it by the same linear scan master used, so a
    divergence in `ReferenceGraph.holders_of`'s answer -- not merely its
    algorithmic cost -- would show up as a value mismatch here.
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
