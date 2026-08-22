"""Command line entry point.

    flab2bp 'https://factoriolab.github.io/dsp/flow?o=super-magnetic-ring*60&...'

Prints the blueprint string to stdout, so it pipes and redirects cleanly; all
diagnostics go to stderr.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from flab2bp import pipeline
from flab2bp.layout import markers


def _report(build: pipeline.Build, *, verbose: bool) -> None:
    """Everything except the blueprint itself goes to stderr."""
    out = sys.stderr
    print(
        f"{build.strategy} / {build.spec.label}: {build.spec.machine_count} machines, "
        f"{build.placement.area} tiles, {len(build.placement.buildings)} buildings",
        file=out,
    )

    unmarked = markers.unmarked_external_inputs(build.placement, build.spec)
    marked = int(build.placement.stats.get("input_markers", 0))
    print(
        f"inputs to belt in: {', '.join(sorted(build.spec.external_inputs)) or 'none'}"
        f"  ({marked} marked with icons)",
        file=out,
    )
    if unmarked:
        # Say it rather than let someone discover it while staring at an
        # unlabelled belt in game.
        print(f"  WARNING: no icon placed for {sorted(unmarked)}", file=out)

    if build.report.skipped:
        print(
            f"  {len(build.report.skipped)} check(s) could not run: "
            f"{', '.join(sorted(build.report.skipped))}",
            file=out,
        )
    if build.report.errors:
        counts = Counter(f.check for f in build.report.errors)
        print(f"  {len(build.report.errors)} VALIDATION ERRORS: {dict(counts)}", file=out)
        for f in build.report.errors[:5]:
            print(f"    {f.check}: {f.message}", file=out)
        print(
            "  This blueprint will paste but may not run correctly.",
            file=out,
        )

    if verbose:
        print(f"\n{'candidate':<20}{'strategy':<10}{'area':>8}{'errors':>8}", file=out)
        for a in sorted(build.attempts, key=lambda a: (not a.ok, a.area)):
            print(
                f"{a.candidate:<20}{a.strategy:<10}{a.area:>8}{len(a.report.errors):>8}",
                file=out,
            )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="flab2bp",
        description="Turn a FactorioLab URL for Dyson Sphere Program into a "
        "pasteable DSP blueprint.",
    )
    ap.add_argument("url", help="a factoriolab.github.io/dsp/... URL")
    ap.add_argument(
        "--strategy",
        choices=("best", "spine", "freeform"),
        default="best",
        help="layout backend; 'best' lays out every candidate with both and keeps "
        "the smallest VALID result (default)",
    )
    ap.add_argument("--no-power", dest="power", action="store_false", help="omit Tesla Towers")
    ap.add_argument(
        "--candidates",
        type=int,
        default=3,
        help="how many proliferation candidates the rate solver emits (default 3)",
    )
    ap.add_argument("--budget", type=float, default=2.0, help="solver seconds per layout")
    ap.add_argument("-o", "--out", type=Path, help="write to a file instead of stdout")
    ap.add_argument("-n", "--name", default="", help="blueprint short description")
    ap.add_argument("-v", "--verbose", action="store_true", help="show every attempt")
    ap.add_argument(
        "--allow-invalid",
        action="store_true",
        help="emit even when validation fails (default: exit non-zero instead, since "
        "an invalid blueprint pastes cleanly and then does not run)",
    )
    args = ap.parse_args(argv)

    try:
        build = pipeline.build(
            args.url,
            strategy=args.strategy,
            power=args.power,
            candidates=args.candidates,
            time_budget_s=args.budget,
            name=args.name,
        )
    except (ValueError, KeyError) as exc:
        print(f"flab2bp: {exc}", file=sys.stderr)
        return 2

    _report(build, verbose=args.verbose)

    if build.report.errors and not args.allow_invalid:
        print(
            "flab2bp: refusing to emit an invalid blueprint; pass --allow-invalid "
            "to override",
            file=sys.stderr,
        )
        return 1

    if args.out:
        args.out.write_text(build.blueprint)
        print(f"written to {args.out}", file=sys.stderr)
    else:
        print(build.blueprint)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
