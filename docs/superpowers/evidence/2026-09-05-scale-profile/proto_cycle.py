"""Prototype: SCC-based replacement for freeform._committed_path_closes_cycle.

Monkeypatches the module function with a wrapper that runs BOTH the original
and the prototype, asserts they agree on every call, and times each.  No
source files are touched.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import route_profile as rp  # noqa: E402
from flab2bp.bench.corpus import _FAST_RANK  # noqa: E402
from flab2bp.dsp import catalog  # noqa: E402
from flab2bp.lab.data import load_vendored  # noqa: E402
from flab2bp.lab.url import parse_url  # noqa: E402
from flab2bp.layout import freeform  # noqa: E402
from flab2bp.layout.base import NoValidLayout  # noqa: E402
from flab2bp.rates import CandidatePolicy, build_candidates  # noqa: E402

ORIG = freeform._committed_path_closes_cycle


def closes_cycle_scc(
    canvas: freeform._Canvas,
    indices: Sequence[int],
    splitter_successors: Mapping[int, Sequence[int]] | None = None,
) -> bool:
    """Any committed belt on a cycle? One Tarjan pass over the reachable belt graph.

    `_leads_back(onward, {index})` is true iff `index` is reachable from its own
    successor, i.e. iff `index` lies on a directed cycle of the belt graph whose
    edges are: splitter -> its branches, belt -> output_obj.  A node lies on a
    cycle iff its SCC has more than one member or it carries a self-edge.
    """
    if splitter_successors is None:
        splitter_successors = freeform._splitter_successors(canvas)
    buildings = canvas.buildings
    n = len(buildings)
    is_belt = catalog.is_belt
    splitter_id = catalog.SPLITTER_ID

    def succ(i: int) -> tuple[int, ...]:
        b = buildings[i]
        if b.item_id == splitter_id:
            return tuple(splitter_successors.get(i, ()))
        if is_belt(b.item_id) and b.output_obj is not None:
            return (b.output_obj,)
        return ()

    index_lo = [-1] * n
    low = [0] * n
    on_stack = [False] * n
    stack: list[int] = []
    counter = 0
    wanted = set(i for i in indices if 0 <= i < n)
    for root in list(wanted):
        if index_lo[root] != -1:
            continue
        # iterative Tarjan
        work = [(root, iter(succ(root)))]
        index_lo[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack[root] = True
        while work:
            v, it = work[-1]
            advanced = False
            for w in it:
                if not 0 <= w < n:
                    continue
                if index_lo[w] == -1:
                    index_lo[w] = low[w] = counter
                    counter += 1
                    stack.append(w)
                    on_stack[w] = True
                    work.append((w, iter(succ(w))))
                    advanced = True
                    break
                if on_stack[w]:
                    if index_lo[w] < low[v]:
                        low[v] = index_lo[w]
            if advanced:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                if low[v] < low[parent]:
                    low[parent] = low[v]
            if low[v] == index_lo[v]:
                comp = []
                while True:
                    w = stack.pop()
                    on_stack[w] = False
                    comp.append(w)
                    if w == v:
                        break
                if len(comp) > 1 and any(c in wanted for c in comp):
                    return True
                if len(comp) == 1:
                    c = comp[0]
                    if c in wanted and c in succ(c):
                        return True
    return False


STATS = {"calls": 0, "orig_s": 0.0, "proto_s": 0.0, "mismatch": 0, "true": 0}


def both(canvas, indices, splitter_successors=None):  # noqa: ANN001
    STATS["calls"] += 1
    t0 = time.perf_counter()
    a = ORIG(canvas, indices, splitter_successors)
    t1 = time.perf_counter()
    b = closes_cycle_scc(canvas, indices, splitter_successors)
    t2 = time.perf_counter()
    STATS["orig_s"] += t1 - t0
    STATS["proto_s"] += t2 - t1
    STATS["true"] += int(a)
    if a != b:
        STATS["mismatch"] += 1
        print(f"MISMATCH orig={a} proto={b} n_indices={len(indices)}", file=sys.stderr)
    return a


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("target")
    ap.add_argument("--rate", type=int, default=60)
    ap.add_argument("--strategy", default="freeform")
    ap.add_argument("--budget", type=float, default=30.0)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    url = f"https://factoriolab.github.io/dsp/list?o={args.target}*{args.rate}&ibe=conveyor-belt-3&mmr={_FAST_RANK}&v=11"
    spec = build_candidates(
        load_vendored(), parse_url(url), candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,)
    ).candidates[0]
    freeform._committed_path_closes_cycle = both
    tally = rp.Tally()
    restore = rp.install(tally)
    verdict = "OK"
    t0 = time.perf_counter()
    try:
        rp._strategy(args.strategy)(workers=args.workers).lay_out(spec, time_budget_s=args.budget)
    except NoValidLayout as exc:
        verdict = f"REFUSED: {exc.reason[:80]}"
    finally:
        restore()
        freeform._committed_path_closes_cycle = ORIG
    wall = time.perf_counter() - t0
    print(
        json.dumps(
            {
                "target": args.target,
                "rate": args.rate,
                "strategy": args.strategy,
                "verdict": verdict,
                "wall_s": round(wall, 2),
                "commit_paths_s": round(tally.t.get("commit_paths", 0.0), 2),
                "commit_calls": tally.n.get("commit_paths", 0),
                "cycle_check": {k: (round(v, 3) if isinstance(v, float) else v) for k, v in STATS.items()},
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
