"""Census of every producer->consumer lane edge in a spec's strip plan.

`freeform._fanout_shortfall` refuses when a producer lane has fewer TILES than
the consumer lanes it must tap.  The refusal message names one offending edge;
this probe names every edge, offending or not, so the shape of the problem is
measured rather than inferred:

    group_key, item, dest, domain, n_src_lanes, n_sink_lanes, per_lane,
    src_tiles (the narrowest source strip's width), src widths, sink widths

`per_lane > src_tiles` is the refusal condition (freeform.py:19932).

Usage: uv run python probe_fanout_edges.py [url_id ...]
"""

from __future__ import annotations

import sys
from collections import defaultdict

from flab2bp.bench.corpus import URL_CORPUS
from flab2bp.lab.data import load_vendored
from flab2bp.lab.url import parse_url
from flab2bp.layout.freeform import _dests, plan_strips
from flab2bp.rates.candidates import CandidatePolicy, build_candidates

_POLICIES = (
    CandidatePolicy.NO_PROLIFERATOR,
    CandidatePolicy.ALL_PRODUCTS,
    CandidatePolicy.OUTPUT_PRODUCTS,
)


def main() -> None:
    wanted = set(sys.argv[1:]) or {"universe-matrix"}
    data = load_vendored()
    print(
        "url_id,candidate,item,src_group,dest_group,domain,"
        "n_src,n_sink,per_lane,src_tiles,src_widths,sink_widths,offends"
    )
    for entry in URL_CORPUS:
        if entry.url_id not in wanted:
            continue
        request = parse_url(entry.url)
        for policy in _POLICIES:
            spec = build_candidates(
                data, request, candidate_policies=(policy,)
            ).candidates[0]
            strips = plan_strips(spec)

            src_lanes: dict[tuple, int] = defaultdict(int)
            src_tiles: dict[tuple, int] = {}
            src_widths: dict[tuple, list[int]] = defaultdict(list)
            sink_lanes: dict[tuple, int] = defaultdict(int)
            sink_widths: dict[tuple, list[int]] = defaultdict(list)
            for s in strips:
                for item, dest, domain in s.out_lanes:
                    for d in _dests(dest):
                        key = (s.group_key, item, d, domain)
                        src_lanes[key] += 1
                        src_tiles[key] = min(src_tiles.get(key, s.width), s.width)
                        src_widths[key].append(s.width)
                for item in s.in_lanes:
                    sink_lanes[s.group_key, item, s.cargo_domain] += 1
                    sink_widths[s.group_key, item, s.cargo_domain].append(s.width)

            for (src_key, item, dest, domain), n_src in sorted(
                src_lanes.items(), key=lambda e: (e[0][1], e[0][0], e[0][2])
            ):
                n_sink = sink_lanes.get((dest, item, domain), 0)
                if not n_sink:
                    continue
                per_lane = -(-n_sink // n_src)
                tiles = src_tiles[src_key, item, dest, domain]
                sw = sorted(src_widths[src_key, item, dest, domain])
                kw = sorted(sink_widths[dest, item, domain])
                print(
                    f"{entry.url_id},{policy.value},{item},{src_key},{dest},"
                    f"{domain.value},{n_src},{n_sink},{per_lane},{tiles},"
                    f'"{sw}","{kw}",'
                    f"{'YES' if per_lane > tiles else 'no'}"
                )


if __name__ == "__main__":
    main()
