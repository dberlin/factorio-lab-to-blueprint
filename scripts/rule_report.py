"""Print the rule-consolidation table: R1's verdict and R2's number.

    uv run python scripts/rule_report.py

The tests in ``tests/rules/`` are what ENFORCE these; this is for reading them
without running a suite.  R4's table lives with its tests because producing it
means perturbing the package, which a reporting script has no business doing.
"""

from __future__ import annotations

import sys

from flab2bp.dsp import provenance, registry
from flab2bp.dsp.registry import Kind


def main() -> int:
    graph = provenance.build_graph()
    rows = provenance.consultation(graph)
    counts = provenance.summary(rows)

    print("=== what dsp/ declares ===")
    for kind in Kind:
        print(f"  {kind.value:.<12} {len(registry.of_kind(kind)):>3}")

    print("\n=== R2: who consults each declared rule ===")
    for row in sorted(rows, key=lambda r: (not r.both, r.entry.symbol)):
        checks = f"{len(row.checks)} check(s)" if row.checks else "NO CHECK"
        strategies = (
            ", ".join(m.rsplit(".", 1)[-1] for m in row.strategies)
            if row.strategies
            else "NO STRATEGY"
        )
        print(f"  {row.entry.symbol:44s} {checks:12s} {strategies}")

    print("\n  " + "  ".join(f"{k}={v}" for k, v in counts.items()))
    pct = 100.0 * counts["by_both"] / counts["declared"]
    print(f"  consolidated (named by both a check and a strategy): {pct:.1f}%")

    print("\n=== rules read once at import, and by what ===")
    for symbol, holders in sorted(provenance.frozen_captures(graph).items()):
        print(f"  {symbol:44s} {', '.join(holders)}")

    print("\n=== rules consulted at a hardcoded tech level ===")
    for symbol, readers in sorted(provenance.hardcoding_readers(graph).items()):
        entry = registry.by_symbol(symbol)
        print(f"  {symbol} pins {entry.hardcodes}")
        for reader in readers:
            print(f"      read by {reader}")

    print("\n=== R1: bare game constants outside dsp/ ===")
    unexplained = provenance.unexplained_literals()
    for violation in unexplained:
        print(f"  {violation}")
    print(f"  {len(unexplained)} unexplained, "
          f"{len(registry.LINT_EXCEPTIONS)} declared coincidences")
    stale = provenance.stale_lint_exceptions()
    for exception in stale:
        print(f"  STALE exception: {exception.module}:{exception.where} {exception.value}")
    return 1 if unexplained else 0


if __name__ == "__main__":
    sys.exit(main())
