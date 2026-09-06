"""Run ONE (candidate policy, strategy) pair and dump the refusal's telemetry.

``pipeline.build`` runs six of these and reports one sentence each; this runs
exactly one so the sweep counters behind that sentence are visible.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from flab2bp.lab.data import load_vendored  # noqa: E402
from flab2bp.lab.url import parse_url  # noqa: E402
from flab2bp.layout.band_policy import BandPolicy  # noqa: E402
from flab2bp.layout.base import NoValidLayout  # noqa: E402
from flab2bp.rates import CandidatePolicy, build_candidates  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--policy", default="all-products")
    ap.add_argument("--strategy", default="freeform")
    ap.add_argument("--budget", type=float, default=30.0)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--islands", type=int, default=4)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    spec = build_candidates(
        load_vendored(),
        parse_url(args.url),
        candidate_policies=(CandidatePolicy(args.policy),),
    ).candidates[0]

    from flab2bp import pipeline

    strategy = pipeline._new_layout(
        args.strategy,
        belt_vertical_construction=True,
        sequence_islands=args.islands,
        band_policy=BandPolicy("portable"),
        workers=args.workers,
    )
    row: dict[str, object] = {
        "policy": args.policy,
        "strategy": args.strategy,
        "budget_s": args.budget,
        "machines": sum(g.count for g in spec.groups),
    }
    t0 = time.perf_counter()
    try:
        placement = strategy.lay_out(spec, time_budget_s=args.budget)
    except NoValidLayout as exc:
        row["verdict"] = "REFUSED"
        row["reason"] = exc.reason
        row["stats"] = {k: str(v) for k, v in sorted(exc.stats.items())}
        row["attempt_reasons"] = list(exc.attempt_reasons)
        row["projection_failures"] = [
            f"{f.band} {f.check} {f.buildings}: {f.detail}" for f in exc.projection_failures
        ]
    else:
        row["verdict"] = "OK"
        row["area"] = int(placement.area)
        row["stats"] = {k: str(v) for k, v in sorted(dict(placement.stats).items())}
    row["wall_s"] = round(time.perf_counter() - t0, 2)

    text = json.dumps(row, indent=2, default=str)
    if args.out:
        args.out.write_text(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
