"""Command line entry point.

    flab2bp 'https://factoriolab.github.io/dsp/flow?o=super-magnetic-ring*60&...'

Prints the blueprint string to stdout, so it pipes and redirects cleanly; all
diagnostics go to stderr.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from pathlib import Path

from flab2bp import pipeline
from flab2bp.layout import markers
from flab2bp.layout.band_policy import BAND_SELECTIONS
from flab2bp.layout.base import NoValidLayout


def _report(build: pipeline.Build, *, verbose: bool) -> None:
    """Everything except the blueprint itself goes to stderr."""
    out = sys.stderr
    frame = build.placement.frame
    if frame is None:
        raise ValueError("successful build placement has no area frame")
    print(
        f"{build.strategy} / {build.spec.label}: {build.spec.machine_count} machines, "
        f"{build.placement.area} tiles, {len(build.placement.buildings)} buildings",
        file=out,
    )
    print(f"primary_band: {frame.primary_band}", file=out)
    print(
        f"certified_bands: {', '.join(map(str, frame.certified_bands))}",
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

    # Say whether the selection was pinned. "No findings" and "nothing was
    # checked" read identically in silence, and only one of them is reassuring.
    if build.flow_pinned:
        if build.flow_findings:
            print(
                f"  {len(build.flow_findings)} difference(s) from the pinned flow:",
                file=out,
            )
            for finding in build.flow_findings:
                print(f"    {finding}", file=out)
        else:
            print("  recipe selection pinned to the supplied flow (no differences)", file=out)
    else:
        print(
            "  recipe selection DERIVED, not pinned -- pass --flow or --fetch-flow "
            "to build FactorioLab's own selection",
            file=out,
        )

    rules = build.belt_rules
    if rules is not None:
        if rules.from_url:
            print(
                f"  belt altitude ceiling {float(rules.max_z)} (lab level "
                f"{rules.lab_level}), vertical belt construction "
                f"{'YES' if rules.vertical_construction else 'no'} -- read from "
                f"the URL's researched technologies",
                file=out,
            )
        else:
            print(
                f"  WARNING: this URL carried no technology set, so a "
                f"FULLY-RESEARCHED save is ASSUMED: belt ceiling "
                f"{float(rules.max_z)} (lab level {rules.lab_level}), vertical "
                f"belt construction "
                f"{'YES' if rules.vertical_construction else 'no'}. A URL "
                f"exported from FactorioLab normally does carry one; if yours "
                f"did, the belts here may climb higher than your save allows.",
                file=out,
            )

    if build.refused:
        # A strategy that produced NO layout is invisible in `attempts`, so say
        # so. Silence here would read as "that combination was simply not the
        # best", which is a different and much more reassuring claim.
        print(f"  {len(build.refused)} strategy/candidate pair(s) produced no layout:", file=out)
        for r in build.refused[:5]:
            print(f"    {r}", file=out)
            for failure in r.projection_failures[:5]:
                print(
                    f"      band {failure.band} {failure.check} buildings "
                    f"{failure.buildings}: {failure.detail}",
                    file=out,
                )

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


def _available_cpu_count() -> int:
    """Return the CPU set this process may actually schedule on."""
    try:
        return max(1, len(os.sched_getaffinity(0)))
    except AttributeError, OSError:
        return max(1, os.process_cpu_count() or 1)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="flab2bp",
        description="Turn a FactorioLab URL for Dyson Sphere Program into a "
        "pasteable DSP blueprint.",
    )
    ap.add_argument("url", help="a factoriolab.github.io/dsp/... URL")
    ap.add_argument(
        "--strategy",
        choices=pipeline.STRATEGY_CHOICES,
        default="best",
        help="layout backend; best runs freeform and sequence-pair and keeps the "
        "smallest valid result (default)",
    )
    ap.add_argument(
        "--band",
        choices=BAND_SELECTIONS,
        default="portable",
        help="latitude-band policy (default: portable, the smallest fitting "
        "band plus up to two wider bands)",
    )
    ap.add_argument(
        "--sequence-islands",
        type=int,
        metavar="N",
        help="whole-solve process islands for explicit sequence-pair (default: "
        "CPU affinity capped at 8; explicit range 1..16)",
    )
    ap.add_argument("--no-power", dest="power", action="store_false", help="omit Tesla Towers")
    ap.add_argument(
        "--candidates",
        type=int,
        choices=range(1, 4),
        default=3,
        help="fixed mode policies to emit: none, all-products, output-products "
        "(1..3; default 3)",
    )
    ap.add_argument(
        "--flow",
        type=Path,
        help="FactorioLab CSV export (the list view's 'download as CSV'). Pins "
        "the recipe selection to the one FactorioLab solved instead of "
        "re-deriving it. Refuses on a file that cannot be this URL's flow; "
        "there is no fallback to re-deriving.",
    )
    ap.add_argument(
        "--fetch-flow",
        action="store_true",
        help="fetch the CSV export ourselves by driving a headless browser to the "
        "URL. FactorioLab solves in the page, so this runs it and waits for the "
        "solve to finish. Off by default: a build should not silently need a "
        "browser or the network.",
    )
    ap.add_argument(
        "--fetch-timeout",
        type=float,
        default=90.0,
        metavar="SECONDS",
        help="how long to wait for FactorioLab to finish solving (default 90)",
    )
    ap.add_argument(
        "--browser",
        help="path to the Chromium or Chrome executable --fetch-flow should drive "
        "(default: search the usual locations, or $FLAB2BP_BROWSER)",
    )
    ap.add_argument(
        "--no-proliferator",
        action="store_true",
        help="build only from candidates that spray nothing, so no Spray Coaters "
        "are emitted. Refuses rather than falling back if every candidate this "
        "URL produces is proliferated.",
    )
    ap.add_argument("--budget", type=float, default=15.0, help="solver seconds per layout")
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
    if args.sequence_islands is not None and args.strategy != "sequence-pair":
        ap.error("--sequence-islands requires --strategy sequence-pair")
    if args.sequence_islands is not None and not 1 <= args.sequence_islands <= 16:
        ap.error("--sequence-islands must be from 1 to 16")
    sequence_islands = (
        args.sequence_islands or min(8, _available_cpu_count())
        if args.strategy == "sequence-pair"
        else 1
    )

    try:
        build = pipeline.build(
            args.url,
            strategy=args.strategy,
            band=args.band,
            power=args.power,
            candidates=args.candidates,
            time_budget_s=args.budget,
            sequence_islands=sequence_islands,
            name=args.name,
            flow=args.flow,
            fetch_flow=args.fetch_flow,
            fetch_timeout_s=args.fetch_timeout,
            browser=args.browser,
            no_proliferator=args.no_proliferator,
        )
        _report(build, verbose=args.verbose)
    except NoValidLayout as exc:
        # Distinct exit code: "no layout exists" is a different outcome from
        # "the URL was bad", and per the user a spec that cannot be laid out in
        # the retry budget is our bug until shown otherwise.
        print(f"flab2bp: {exc}", file=sys.stderr)
        for failure in exc.projection_failures[:5]:
            print(
                f"  band {failure.band} {failure.check} buildings "
                f"{failure.buildings}: {failure.detail}",
                file=sys.stderr,
            )
        return 3
    except (ValueError, KeyError) as exc:
        print(f"flab2bp: {exc}", file=sys.stderr)
        return 2


    if build.report.errors and not args.allow_invalid:
        print(
            "flab2bp: refusing to emit an invalid blueprint; pass --allow-invalid to override",
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
