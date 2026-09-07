"""Is the fan-out shortfall a SHARDING failure or a TILE BUDGET failure?

`freeform._shard_sinks` can split a producer group across up to `group.count`
strips.  If sharding were the fix, `n` shards would each tap `ceil(n_sink / n)`
consumer lanes with `(machines // n) * pw` tiles.  This probe evaluates that
counterfactual for every `n` the group could actually afford, so the answer is
measured instead of argued.

It also prints the producer strip's machines / pw / width / tail_extension so
the tile budget is on the record.

Usage: uv run python probe_producer_budget.py [url_id ...]
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
    for entry in URL_CORPUS:
        if entry.url_id not in wanted:
            continue
        request = parse_url(entry.url)
        for policy in _POLICIES:
            spec = build_candidates(
                data, request, candidate_policies=(policy,)
            ).candidates[0]
            strips = plan_strips(spec)

            by_group: dict[str, list] = defaultdict(list)
            for s in strips:
                by_group[s.group_key].append(s)

            src_lanes: dict[tuple, int] = defaultdict(int)
            src_tiles: dict[tuple, int] = {}
            sink_lanes: dict[tuple, int] = defaultdict(int)
            for s in strips:
                for item, dest, domain in s.out_lanes:
                    for d in _dests(dest):
                        key = (s.group_key, item, d, domain)
                        src_lanes[key] += 1
                        src_tiles[key] = min(src_tiles.get(key, s.width), s.width)
                for item in s.in_lanes:
                    sink_lanes[s.group_key, item, s.cargo_domain] += 1

            print(f"\n=== {entry.url_id} / {policy.value} ===")
            for (src_key, item, dest, domain), n_src in sorted(src_lanes.items()):
                n_sink = sink_lanes.get((dest, item, domain), 0)
                if not n_sink:
                    continue
                tiles = src_tiles[src_key, item, dest, domain]
                if -(-n_sink // n_src) <= tiles:
                    continue
                group = by_group[src_key]
                machines = sum(s.machines for s in group)
                pw = group[0].pw
                tail = sum(s.tail_extension for s in group)
                print(
                    f"OFFENDS {item}: {src_key} -> {dest} "
                    f"({n_src} src lane(s), {n_sink} sink lane(s), "
                    f"narrowest src {tiles} tiles)"
                )
                print(
                    f"  producer group: strips={len(group)} machines={machines} "
                    f"pw={pw} widths={[s.width for s in group]} "
                    f"tail_extension={tail} "
                    f"TOTAL TILE BUDGET={machines * pw}"
                )
                print(
                    f"  per-strip out_lanes={[len(s.out_lanes) for s in group]} "
                    f"flank_outputs={[s.flank_outputs for s in group]} "
                    f"drain_outermost={[s.drain_outermost for s in group]}"
                )
                print("  sharding counterfactual (n = producer strips for this item):")
                for n in range(1, machines + 1):
                    per_strip_machines = machines // n
                    if per_strip_machines < 1:
                        break
                    w = per_strip_machines * pw
                    taps = -(-n_sink // n)
                    print(
                        f"    n={n:<3} machines/strip={per_strip_machines:<3} "
                        f"width={w:<4} taps/lane={taps:<3} "
                        f"{'FITS' if taps <= w else 'still short'}"
                    )
                need = -(-n_sink // n_src) - tiles
                print(
                    f"  tiles needed on the existing lane: {-(-n_sink // n_src)}; "
                    f"have {tiles}; SHORTFALL {need}"
                )


if __name__ == "__main__":
    main()
