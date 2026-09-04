"""Compare Freeform and SequencePair density with a validated paired corpus.

A real A-to-B test, not a table of numbers nobody can defend.  The measurement
logic lives in :mod:`flab2bp.bench.ab`; this file is the driver that feeds it
real corpus URLs and prints the answer.

    uv run python scripts/ab_compare.py                          # trivial+small
    uv run python scripts/ab_compare.py --tier mid --repeat 5
    uv run python scripts/ab_compare.py --budget 1,2,10          # sweep the budget
    uv run python scripts/ab_compare.py --tier mid --markdown docs/AB_RESULTS.md

This is NOT part of ``pytest``.  A full sweep is minutes of CP-SAT; the suite
stays at ~21s.

WHY THIS SCRIPT IS SHAPED LIKE THIS
-----------------------------------
An earlier comparison here concluded "A wins, geometric mean 1.359" and it was
an artifact: the harness scored layouts the validator had rejected.  Invalid
layouts are systematically SMALLER -- an unrouted net is a belt run that does
not exist, so the broken layout has the tighter bounding box and wins on area.
One build with 119 unrouted nets measured as the densest candidate on offer.

Five things follow from that, and each is enforced rather than remembered:

* **Validity gate.**  A ``Sample`` cannot hold an area unless it is VALID; the
  constructor raises.  There is no path that reads an area off a rejection.
* **Four distinct failures.**  REFUSED (searched, found nothing), INVALID
  (produced something rejected), ERROR (crashed), CROSSFAIL (our validator
  liked it, the game's format did not).  Different bugs, different columns.
* **Denominators everywhere.**  Coverage prints before density and the ratio
  names the subset it describes.  "B is 1.2x denser" is meaningless if B shipped
  3 of 12 specs and A shipped 11.
* **Repeats, because CP-SAT is nondeterministic on purpose.**  Multi-worker is
  the shipping default and worth ~23% density over one worker, so pinning it
  would measure a configuration neither strategy would ship.  ``--repeat``
  measures the noise; a verdict whose spreads overlap is marked *not separated*.
* **Budget sweep.**  A strategy that uses its budget better looks denser at 2s
  and worse at 10s.  ``--budget 1,2,10`` reports whether the winner flips.

Fairness: both strategies get the same ``BuildSpec`` objects (resolved once per
URL), the same budget, the same candidates, and are run back-to-back within each
trial so machine drift hits both equally.  Neither is asked how it did -- the
harness measures the ``Placement`` itself.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from flab2bp.bench.ab import (  # noqa: E402
    Comparison,
    CrossSummary,
    Outcome,
    RunMeta,
    Sample,
    budget_flip,
    compare,
    crossvalidate_samples,
    isolated_attempt,
    render_markdown,
    render_text,
    sample_measured,
    to_json,
    trials_from,
)
from flab2bp.bench.corpus import URL_CORPUS, CorpusEntry, Tier  # noqa: E402
from flab2bp.cli import (  # noqa: E402
    add_candidate_policy_argument,
    candidate_policies_from_args,
)
from flab2bp.dsp import codec  # noqa: E402
from flab2bp.lab.techs import belt_rules_for_url  # noqa: E402
from flab2bp.layout import finalize, markers, validate  # noqa: E402
from flab2bp.layout.band_policy import BandPolicy  # noqa: E402
from flab2bp.layout.base import (  # noqa: E402
    LayoutStrategy,
    Placement,
    PlacementCompletion,
)
from flab2bp.layout.freeform import FreeformLayout  # noqa: E402
from flab2bp.layout.sequence_solver import SequencePairLayout  # noqa: E402
from flab2bp.pipeline import _id_map  # noqa: E402
from flab2bp.rates import (  # noqa: E402
    DEFAULT_CANDIDATE_POLICIES,
    CandidatePolicy,
    build_candidates,
)
from flab2bp.spec import BuildSpec  # noqa: E402

_TIER_ORDER = (Tier.TRIVIAL, Tier.SMALL, Tier.MID, Tier.LARGE, Tier.STRESS)

A_NAME = "sequence-pair"
B_NAME = "freeform"

#: Factories rather than classes so the driver never depends on the two
#: constructors happening to share a signature.
#:
#: The second argument is the save's slope rule, taken from the entry's URL.
#: Both arms must get the same one or the comparison is measuring the
#: technology set rather than the strategies.
STRATEGIES: dict[str, Callable[[bool], LayoutStrategy]] = {
    A_NAME: lambda vertical: SequencePairLayout(
        band_policy=BandPolicy("portable"),
        belt_vertical_construction=vertical,
    ),
    B_NAME: lambda vertical: FreeformLayout(
        band_policy=BandPolicy("portable"),
        belt_vertical_construction=vertical,
    ),
}

Judge = Callable[[Placement], tuple[bool, tuple[str, ...]]]


@dataclass(frozen=True, slots=True)
class _LayoutCall:
    """Picklable solve request executed inside one fresh measurement process."""

    strategy: str
    vertical: bool
    spec: BuildSpec
    budget_s: float

    def __call__(self) -> Placement:
        placement = STRATEGIES[self.strategy](self.vertical).lay_out(
            self.spec, time_budget_s=self.budget_s
        )
        if placement.completion is PlacementCompletion.COMPACTED_AND_FINALIZED:
            return placement
        compacted = finalize.compact_open_boundary_belts(
            placement,
            self.spec,
            expect_power=True,
        )
        finalized = finalize.finalize_placement(compacted, BandPolicy("portable"))
        return replace(
            finalized,
            completion=PlacementCompletion.COMPACTED_AND_FINALIZED,
        )


def specs_for(
    entry: CorpusEntry,
    candidate_policies: tuple[CandidatePolicy, ...] = DEFAULT_CANDIDATE_POLICIES,
) -> tuple[BuildSpec, ...]:
    """Resolve a URL to its candidate frontier, once, shared by both strategies.

    Every candidate is laid out by both strategies and the smallest VALID result
    wins, exactly as ``pipeline.build`` does.  Picking the candidate with fewest
    machines up front would be cheaper and wrong: proliferation cuts machine
    count but forbids direct insertion on the sprayed edges, so fewer machines
    can still lay out larger.
    """
    from flab2bp.lab.data import load_vendored
    from flab2bp.lab.url import parse_url

    request = parse_url(entry.url)
    return build_candidates(
        load_vendored(),
        request,
        candidate_policies=candidate_policies,
    ).candidates


def judge_with(
    spec: BuildSpec, ids: validate.IdMap, placement: Placement
) -> tuple[bool, tuple[str, ...]]:
    """Return whether the powered placement is fully checked and shippable.

    The ``spec`` and its id map are passed to the validator deliberately.
    Without them nine spec-conformance and flow checks silently skip, and a
    build that never ran its throughput checks reads as clean -- a quieter
    version of the same artifact this harness exists to prevent.

    A skipped check is not a passed check. Current runs are always powered, so
    skipped power checks are validation holes rather than a declared off mode.
    """
    report = validate.validate(placement, spec, ids=ids, expect_power=True)
    checks = tuple(sorted({f.check for f in report.errors}))
    if report.skipped:
        return False, checks + tuple(f"unchecked:{c}" for c in report.skipped)
    return report.ok, checks


def encode_with(spec: BuildSpec, placement: Placement) -> str:
    """Encode exactly what the pipeline would ship, external-input markers and all.

    Cross-validating a placement the pipeline would not actually emit would
    check the wrong bytes.
    """
    return codec.encode(markers.mark_external_belts(placement, spec))


def collect(
    entries: list[CorpusEntry],
    *,
    budgets: list[float],
    repeat: int,
    candidate_policies: tuple[CandidatePolicy, ...] = DEFAULT_CANDIDATE_POLICIES,
    a_name: str = A_NAME,
    b_name: str = B_NAME,
) -> list[Sample]:
    """Run the whole matrix.

    Loop order is ``budget -> trial -> url -> candidate -> strategy`` on purpose:
    A and B are measured back-to-back on identical inputs, so thermal
    throttling, other load, and any drift over a long sweep move both of them
    together instead of landing on whichever ran second.
    """
    strategy_names = (a_name, b_name)
    specs: dict[str, tuple[BuildSpec, ...]] = {}
    spec_errors: dict[str, str] = {}
    for entry in entries:
        try:
            specs[entry.url_id] = specs_for(entry, candidate_policies)
        except Exception as exc:  # noqa: BLE001 - a bad URL must not kill the sweep
            spec_errors[entry.url_id] = f"spec: {type(exc).__name__}: {exc}"
            print(f"  spec error {entry.url_id}: {exc}", file=sys.stderr)

    samples: list[Sample] = []
    for budget in budgets:
        for trial in range(repeat):
            for entry in entries:
                if entry.url_id in spec_errors:
                    # A URL that would not resolve still occupies a row, for both
                    # strategies. Dropping it would make a broken URL look like a
                    # URL nobody ran and shrink the denominator silently.
                    samples.extend(
                        Sample(
                            entry.url_id,
                            "-",
                            name,
                            budget,
                            trial,
                            Outcome.ERROR,
                            0.0,
                            detail=spec_errors[entry.url_id],
                            power=True,
                        )
                        for name in strategy_names
                    )
                    continue
                for spec in specs[entry.url_id]:
                    judge: Judge = partial(judge_with, spec, _id_map(spec))
                    encode = partial(encode_with, spec)
                    vertical = belt_rules_for_url(entry.url).vertical_construction
                    for name in strategy_names:
                        samples.append(
                            sample_measured(
                                url_id=entry.url_id,
                                candidate=spec.label or "default",
                                strategy=name,
                                budget_s=budget,
                                trial=trial,
                                attempt=isolated_attempt(_LayoutCall(name, vertical, spec, budget)),
                                judge=judge,
                                encode=encode,
                                power=True,
                            )
                        )
                print(
                    f"  budget={budget:g}s trial={trial + 1}/{repeat} {entry.url_id}",
                    file=sys.stderr,
                )
    return samples


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--a", default=A_NAME, choices=tuple(STRATEGIES))
    ap.add_argument("--b", default=B_NAME, choices=tuple(STRATEGIES))
    ap.add_argument("--tier", default="small", choices=[t.value for t in _TIER_ORDER])
    ap.add_argument(
        "--budget",
        default="2",
        help="seconds per lay_out call; comma-separated to sweep (e.g. 1,2,10)",
    )
    ap.add_argument(
        "--repeat",
        type=int,
        default=3,
        help="trials per cell. CP-SAT is multi-worker and nondeterministic by "
        "design, so one sample is noise and nothing can be declared separated",
    )
    add_candidate_policy_argument(ap)
    ap.add_argument("--only", default="", help="comma-separated url_ids to restrict to")
    ap.add_argument("--json", type=Path, default=None, help="write raw samples here")
    ap.add_argument("--markdown", type=Path, default=None, help="write the report here")
    ap.add_argument(
        "--no-crossvalidate",
        action="store_true",
        help="skip the independent TypeScript decoder (reported as SKIPPED, never as a pass)",
    )
    args = ap.parse_args(argv)
    args.candidate_policies = candidate_policies_from_args(ap, args)
    return args


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.a == args.b:
        print("--a and --b must select different strategies", file=sys.stderr)
        return 2

    budgets = [float(b) for b in str(args.budget).split(",") if b.strip()]
    cutoff = _TIER_ORDER.index(Tier(args.tier))
    wanted = set(_TIER_ORDER[: cutoff + 1])
    entries = [e for e in URL_CORPUS if e.tier in wanted]
    if args.only:
        keep = {u.strip() for u in args.only.split(",")}
        entries = [e for e in entries if e.url_id in keep]
    if not entries:
        print("no corpus entries selected", file=sys.stderr)
        return 2

    started = datetime.now(UTC).isoformat(timespec="seconds")
    t0 = time.perf_counter()
    samples = collect(
        entries,
        budgets=budgets,
        repeat=args.repeat,
        candidate_policies=args.candidate_policies,
        a_name=args.a,
        b_name=args.b,
    )

    if args.no_crossvalidate:
        cross = CrossSummary(available=False, reason="--no-crossvalidate")
    else:
        samples, cross = crossvalidate_samples(samples)

    meta = RunMeta(
        tiers=tuple(t.value for t in _TIER_ORDER[: cutoff + 1]),
        budgets=tuple(budgets),
        repeat=args.repeat,
        candidates=len(args.candidate_policies),
        power=True,
        urls=len(entries),
        started=started,
        seconds=round(time.perf_counter() - t0, 1),
        a_name=args.a,
        b_name=args.b,
    )

    trials = trials_from(samples)
    url_ids = [e.url_id for e in entries]
    comparisons: list[Comparison] = [
        compare(
            trials,
            a_name=args.a,
            b_name=args.b,
            budget_s=b,
            url_ids=url_ids,
            cross=cross,
        )
        for b in budgets
    ]

    for line in meta.lines():
        print(line)
    print(cross.summary())
    for demoted in cross.demoted:
        print(f"  demoted: {demoted}")
    print()

    for comparison in comparisons:
        for line in render_text(comparison):
            print(line)
        print()

    flip = budget_flip(comparisons)
    if flip:
        print(flip, end="\n\n")

    print(
        "Areas come ONLY from placements the validator accepted AND the "
        "independent\ndecoder round-tripped. Invalid layouts are systematically "
        "smaller -- an\nunrouted net is a belt run that does not exist -- so "
        "scoring them would\nreward dropping connections rather than packing well."
    )

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(to_json(samples, meta, cross), indent=2))
        print(f"\nraw samples -> {args.json}")
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(render_markdown(comparisons, meta, cross))
        print(f"report -> {args.markdown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
