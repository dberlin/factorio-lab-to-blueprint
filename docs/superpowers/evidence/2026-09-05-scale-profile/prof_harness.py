"""Profile one layout attempt for an arbitrary FactorioLab URL.

Reuses scripts/route_profile.py's phase shims (real seconds) and optionally
cProfile (ratios).  Writes a pstats dump and a JSON tally next to --out.
"""

from __future__ import annotations

import argparse
import cProfile
import io
import json
import pstats
import sys
import time
from pathlib import Path

ROOT = Path("/home/dannyb/sources/factorio-lab-to-blueprint")
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import route_profile as rp  # noqa: E402
from flab2bp.bench.corpus import _FAST_RANK  # noqa: E402
from flab2bp.lab.data import load_vendored  # noqa: E402
from flab2bp.lab.url import parse_url  # noqa: E402
from flab2bp.layout import route_kernel  # noqa: E402
from flab2bp.layout.base import NoValidLayout  # noqa: E402
from flab2bp.rates import CandidatePolicy, build_candidates  # noqa: E402


def make_url(target: str, rate: int, belt: str = "conveyor-belt-3", rank: str = _FAST_RANK) -> str:
    return f"https://factoriolab.github.io/dsp/list?o={target}*{rate}&ibe={belt}&mmr={rank}&v=11"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("target")
    ap.add_argument("--rate", type=int, default=60)
    ap.add_argument("--strategy", default="freeform")
    ap.add_argument("--policy", type=CandidatePolicy, default=CandidatePolicy.NO_PROLIFERATOR)
    ap.add_argument("--budget", type=float, default=30.0)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--cprofile", action="store_true")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    url = make_url(args.target, args.rate)
    spec = build_candidates(
        load_vendored(), parse_url(url), candidate_policies=(args.policy,)
    ).candidates[0]
    n_mach = sum(g.count for g in spec.groups)

    tally = rp.Tally()
    restore = rp.install(tally)
    prof = cProfile.Profile() if args.cprofile else None
    verdict = "OK"
    placement = None
    t0 = time.perf_counter()
    try:
        if prof is not None:
            prof.enable()
        placement = rp._strategy(args.strategy)(workers=args.workers).lay_out(
            spec, time_budget_s=args.budget
        )
    except NoValidLayout as exc:
        verdict = f"REFUSED: {exc.reason[:120]}"
    finally:
        if prof is not None:
            prof.disable()
        restore()
    wall = time.perf_counter() - t0

    out = Path(args.out)
    row = {
        "target": args.target,
        "rate": args.rate,
        "machines": n_mach,
        "groups": len(spec.groups),
        "strategy": args.strategy,
        "policy": str(args.policy),
        "budget_s": args.budget,
        "cprofile": bool(prof),
        "verdict": verdict,
        "wall_s": wall,
        "route_all_s": tally.t.get("route_all", 0.0),
        "astar_s": tally.t.get("astar", 0.0),
        "expansions": tally.expansions,
        "passes": tally.passes,
        "rounds": tally.rounds,
        "hits": tally.astar_hit,
        "misses": tally.astar_none,
        "phases": {k: {"s": tally.t[k], "n": tally.n[k]} for k in sorted(tally.t)},
        "prepare_calls_s": list(tally.prepare_calls),
        "route_backend": route_kernel.selected_backend(),
        "area": None if placement is None else float(getattr(placement, "area", 0.0) or 0.0),
        "stats": {} if placement is None else {k: str(v) for k, v in dict(placement.stats).items()},
    }
    out.with_suffix(".json").write_text(json.dumps(row, indent=1, sort_keys=True))
    if prof is not None:
        prof.dump_stats(str(out.with_suffix(".pstats")))
        for sort in ("tottime", "cumulative"):
            buf = io.StringIO()
            st = pstats.Stats(prof, stream=buf)
            st.sort_stats(sort).print_stats(60)
            out.with_suffix(f".{sort}.txt").write_text(buf.getvalue())
    print(json.dumps({k: row[k] for k in ("target", "rate", "machines", "strategy", "verdict", "wall_s", "route_all_s", "astar_s")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
