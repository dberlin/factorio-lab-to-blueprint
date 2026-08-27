"""``uv run python -m flab2bp.bench`` -- run the bake-off.

Kept as ``__main__`` rather than a console script so it does not collide with
the ``flab2bp`` entry point, which the parent owns.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from flab2bp.bench.corpus import URL_CORPUS, Tier
from flab2bp.bench.regression import check_against_baseline, write_baseline
from flab2bp.bench.report import matrix_report, render_markdown, write_results
from flab2bp.bench.runner import BENCH_SEED, run_corpus

_RESULTS = Path("bench/results")
_DEFAULT_TIERS = (Tier.TRIVIAL, Tier.SMALL, Tier.MID)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="flab2bp-bench", description=__doc__)
    parser.add_argument(
        "--all",
        action="store_true",
        help="include the large and stress tiers (slow; excluded from CI)",
    )
    parser.add_argument(
        "--candidates",
        type=int,
        choices=range(1, 4),
        default=3,
        help="fixed rate policies to emit (1..3)",
    )
    parser.add_argument(
        "--time-budget", type=float, default=None, help="override the per-tier budget"
    )
    parser.add_argument("--baseline", type=Path, default=Path("bench/baseline.json"))
    parser.add_argument(
        "--check", action="store_true", help="fail if area or validity regressed"
    )
    parser.add_argument(
        "--bless", action="store_true", help="record the current run as the baseline"
    )
    args = parser.parse_args(argv)

    tiers = set(Tier) if args.all else set(_DEFAULT_TIERS)
    entries = [e for e in URL_CORPUS if e.tier in tiers]

    results = run_corpus(
        entries, time_budget_s=args.time_budget, candidates=args.candidates
    )

    matrix = matrix_report(results, "sequence-pair", "freeform")
    markdown = render_markdown(results, matrix=matrix)
    print(markdown)

    write_results(results, _RESULTS / "results.json", seed=BENCH_SEED)
    (_RESULTS / "report.md").write_text(markdown)

    if args.bless:
        write_baseline(results, args.baseline)
        print(f"\nBaseline written to {args.baseline}")
        return 0

    if args.check:
        if not args.baseline.exists():
            print(f"\nNo baseline at {args.baseline}; run with --bless first.")
            return 1
        regression = check_against_baseline(results, args.baseline)
        print("\n" + regression.summary())
        return 0 if regression.ok else 1

    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
