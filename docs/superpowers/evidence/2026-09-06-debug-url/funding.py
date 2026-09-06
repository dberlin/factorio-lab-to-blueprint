"""The hierarchical funding arithmetic for this spec, with no solve run.

``HierarchicalLayout.lay_out`` refuses a round before starting it when
``(deadline - now - settlement_reserve) / waves < BLOCK_BUDGET_MIN_S``.  Every
term of that is derivable from the seed partition and the budget, so this
prints it for each candidate policy at each budget rather than inferring it
from a refusal string.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from flab2bp.lab.data import load_vendored  # noqa: E402
from flab2bp.lab.url import parse_url  # noqa: E402
from flab2bp.layout.hierarchy import strategy as H  # noqa: E402
from flab2bp.layout.hierarchy.partition import (  # noqa: E402
    STRIP_CAP_DEFAULT,
    derive_cuts,
    initial_partition,
    strip_count,
    sub_spec,
)
from flab2bp.rates import CandidatePolicy, build_candidates  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--budgets", default="15,30,60")
    ap.add_argument("--workers", type=int, default=None)
    args = ap.parse_args()

    parsed = parse_url(args.url)
    data = load_vendored()
    out: dict[str, object] = {
        "strip_cap": STRIP_CAP_DEFAULT,
        "BLOCK_BUDGET_MIN_S": H.BLOCK_BUDGET_MIN_S,
        "BLOCK_BUDGET_MAX_S": H.BLOCK_BUDGET_MAX_S,
        "SETTLEMENT_RESERVE": [
            H.SETTLEMENT_RESERVE_MIN_S,
            H.SETTLEMENT_RESERVE_MAX_S,
            H.SETTLEMENT_RESERVE_SHARE,
        ],
        "policies": [],
    }
    from flab2bp.layout.band_policy import BandPolicy

    layout = H.HierarchicalLayout(
        belt_vertical_construction=True,
        band_policy=BandPolicy("portable"),
        workers=args.workers,
    )
    pool = layout._pool_width()
    arms = layout._arms()
    for policy in CandidatePolicy:
        spec = build_candidates(data, parsed, candidate_policies=(policy,)).candidates[0]
        partition = initial_partition(spec, strip_cap=STRIP_CAP_DEFAULT)
        order, cuts = derive_cuts([list(b) for b in partition.blocks])
        blocks = [list(partition.blocks[i]) for i in order]
        rows = []
        for index, units in enumerate(blocks):
            sub = sub_spec(spec, units, index)
            rows.append(
                {
                    "block": index,
                    "recipes": sorted({u.recipe for u in units}),
                    "machines": sum(g.count for g in sub.groups),
                    "strips": strip_count(spec, units),
                }
            )
        funding = []
        for budget in (float(b) for b in args.budgets.split(",")):
            reserve = H.settlement_reserve_s(budget)
            jobs = len(blocks) * len(arms)
            waves = math.ceil(jobs / pool)
            remaining = budget - reserve
            share = remaining / waves
            funding.append(
                {
                    "budget_s": budget,
                    "reserve_s": reserve,
                    "jobs": jobs,
                    "pool_width": pool,
                    "waves": waves,
                    "remaining_s": round(remaining, 3),
                    "share_s": round(share, 3),
                    "refuses_round_1": share < H.BLOCK_BUDGET_MIN_S,
                    "block_budget_s": (
                        None
                        if share < H.BLOCK_BUDGET_MIN_S
                        else min(H.BLOCK_BUDGET_MAX_S, max(H.BLOCK_BUDGET_MIN_S, share))
                    ),
                }
            )
        out["policies"].append(  # type: ignore[union-attr]
            {
                "policy": str(policy),
                "arms": list(arms),
                "blocks": len(blocks),
                "cuts": len(cuts),
                "per_block": rows,
                "funding": funding,
            }
        )

    text = json.dumps(out, indent=2, default=str)
    if args.out:
        args.out.write_text(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
