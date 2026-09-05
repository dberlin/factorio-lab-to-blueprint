"""Prototype 1: what does sequence-pair's one-third compact-seed share buy?

`sequence_solver._COMPACT_SEED_WALL_SHARE` is `Fraction(1, 3)`, so a 30 s
sequence-pair budget hands 10 s to ONE single-worker CP-SAT solve
(`compact_seed.py:453-457`, `num_search_workers = 1`).  The master profile in
this directory shows that solve returning `compact_seed_status = cancelled`
with `deterministic_time_s = 0.0` on gravity-matrix*200 and quantum-chip*180 --
ten seconds of a thirty second budget producing no seed at all.

This runs the same cell at several shares and reports verdict, area and how
much anneal the run got instead.  THROWAWAY: it monkeypatches a module
constant; nothing here is a proposed edit.

    uv run python proto_compact_share.py --out proto-compact.jsonl
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent

CHILD = r'''
import json, sys, time
from fractions import Fraction
sys.path.insert(0, {root!r} + "/src")
sys.path.insert(0, {root!r} + "/scripts")
import route_profile as rp
from flab2bp.layout import sequence_solver
from flab2bp.bench.corpus import _FAST_RANK
from flab2bp.lab.data import load_vendored
from flab2bp.lab.url import parse_url
from flab2bp.layout.band_policy import BandPolicy
from flab2bp.layout.base import NoValidLayout
from flab2bp.layout.sequence_solver import SequencePairLayout
from flab2bp.rates import CandidatePolicy, build_candidates

num, den = {num}, {den}
sequence_solver._COMPACT_SEED_WALL_SHARE = Fraction(num, den)

url = f"https://factoriolab.github.io/dsp/list?o={target}*{rate}&ibe=conveyor-belt-3&mmr={{_FAST_RANK}}&v=11"
spec = build_candidates(load_vendored(), parse_url(url),
                        candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,)).candidates[0]
tally = rp.Tally(); restore = rp.install(tally)
verdict, placement = "OK", None
t0 = time.perf_counter()
try:
    placement = SequencePairLayout(band_policy=BandPolicy("portable")).lay_out(
        spec, time_budget_s={budget})
except NoValidLayout as exc:
    verdict = "REFUSED: " + exc.reason
finally:
    restore()
wall = time.perf_counter() - t0
stats = {{}} if placement is None else {{k: str(v) for k, v in dict(placement.stats).items()}}
print("RESULT " + json.dumps({{
    "share": f"{{num}}/{{den}}", "verdict": verdict, "wall_s": wall,
    "area": None if placement is None else float(placement.area),
    "compact": {{k: v for k, v in stats.items() if k.startswith("compact_seed")}},
    "search": {{k: stats.get(k) for k in
        ("moves", "accepted_moves", "restarts", "stages", "heights",
         "decoded_candidates", "detailed_routes", "expansions", "termination",
         "used_height", "search_energy", "weighted_hpwl", "box_area")}},
    "phases": {{k: [round(tally.t[k], 2), tally.n[k]] for k in sorted(tally.t)}},
}}))
'''

SHARES = ((1, 3), (1, 6), (1, 12), (1, 1000))  # 1/1000 ~= "no compact seed"
CELLS = (("um60", "universe-matrix", 60), ("qc180", "quantum-chip", 180),
         ("gm200", "gravity-matrix", 200), ("um120", "universe-matrix", 120))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--budget", type=float, default=30.0)
    args = ap.parse_args()
    with open(args.out, "w") as fh:
        for tag, target, rate in CELLS:
            for num, den in SHARES:
                src = CHILD.format(root=str(ROOT), num=num, den=den, target=target,
                                   rate=rate, budget=args.budget)
                script = HERE / "_proto_child.py"
                script.write_text(src)
                t0 = time.perf_counter()
                proc = subprocess.run(["uv", "run", "python", str(script)], cwd=ROOT,
                                      capture_output=True, text=True)
                line = next((l for l in proc.stdout.splitlines()
                             if l.startswith("RESULT ")), None)
                row = {"cell": tag, "machines": None, "budget_s": args.budget,
                       "subprocess_wall_s": round(time.perf_counter() - t0, 2)}
                if line:
                    row |= json.loads(line[7:])
                else:
                    row |= {"share": f"{num}/{den}",
                            "verdict": "HARNESS ERROR: " + proc.stderr[-400:]}
                fh.write(json.dumps(row, sort_keys=True) + "\n")
                fh.flush()
                print(json.dumps({k: row.get(k) for k in
                                  ("cell", "share", "verdict", "wall_s", "area")}),
                      flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
