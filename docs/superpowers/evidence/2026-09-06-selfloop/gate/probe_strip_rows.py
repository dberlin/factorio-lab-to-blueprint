"""Plan-level strip census for the whole stress corpus, on whatever tree runs it.

The audit JSONL exposes `stats.strips` only for cells that finish, and exposes
no per-strip `box_height` at all, so it cannot answer two of the gate's
questions: which specs gained a STRIP and which gained a strip ROW.  This probe
answers both from `plan_strips` alone -- no packing, no routing, no validation
-- so master and the branch can be diffed directly.

Prints one CSV line per (url_id, candidate): strips, flanked strips, total
box_height, tallest box_height, and the total number of input lanes.
"""

from __future__ import annotations

import sys
import traceback

from flab2bp.bench.corpus import URL_CORPUS, Tier
from flab2bp.lab.data import load_vendored
from flab2bp.lab.url import parse_url
from flab2bp.layout.freeform import plan_strips
from flab2bp.rates.candidates import CandidatePolicy, build_candidates

_TIERS = ("trivial", "small", "mid", "large", "stress")


def main() -> None:
    data = load_vendored()
    print("url_id,candidate,strips,flanked,total_box_height,tallest_box_height,input_lanes,mixed_lanes")
    for entry in URL_CORPUS:
        tier = entry.tier.value if isinstance(entry.tier, Tier) else str(entry.tier)
        if tier not in _TIERS:
            continue
        try:
            request = parse_url(entry.url)
        except Exception:  # pragma: no cover - evidence probe
            traceback.print_exc(file=sys.stderr)
            continue
        for policy in (
            CandidatePolicy.NO_PROLIFERATOR,
            CandidatePolicy.ALL_PRODUCTS,
            CandidatePolicy.OUTPUT_PRODUCTS,
        ):
            try:
                spec = build_candidates(
                    data, request, candidate_policies=(policy,)
                ).candidates[0]
                strips = plan_strips(spec)
            except Exception as exc:  # pragma: no cover - evidence probe
                print(f"{entry.url_id},{policy.value},ERROR,,,,,{type(exc).__name__}")
                continue
            lanes = [lane for s in strips for lane in (*s.in_above, *s.in_below)]
            print(
                f"{entry.url_id},{policy.value},{len(strips)},"
                f"{sum(1 for s in strips if s.flank_outputs)},"
                f"{sum(s.box_height for s in strips)},"
                f"{max((s.box_height for s in strips), default=0)},"
                f"{len(lanes)},{sum(1 for lane in lanes if len(lane) > 1)}"
            )


if __name__ == "__main__":
    main()
