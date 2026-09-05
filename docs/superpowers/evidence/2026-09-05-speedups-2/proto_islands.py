"""Prototype 2: sequence-pair process islands, which production never turns on.

`SequencePairLayout(islands=...)` (sequence_solver.py:6264) already runs N
complete solves in spawned processes with derived seeds and keeps the best
(`sequence_islands.run_sequence_islands`).  It defaults to 1 everywhere the
corpus and the pipeline go: `pipeline.build(sequence_islands=1)` at
pipeline.py:503, and `cli.py:349` only raises it above 1 for an EXPLICIT
`--strategy sequence-pair`, never for the default `best`.  `scripts/audit.py:126`
builds `SequencePairLayout(...)` with no islands at all.

The box has 128 cores and one build uses ~1.3 (see `cpu-*.json`), so this asks
the direct question: at the SAME 30 s budget, what do 4 and 8 islands buy?

THROWAWAY measurement script; it changes no production default.

    uv run python proto_islands.py --out proto-islands.jsonl
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

# NOTE: `run_sequence_islands` uses a SPAWN-context ProcessPoolExecutor, and a
# spawned child re-imports `__main__`.  Without the `if __name__` guard below
# every island re-ran this whole script and the pool died with
# `BrokenProcessPool` in ~3 s.  The guard is the fix, not a workaround.
CHILD = r'''
import json, sys, time
sys.path.insert(0, {root!r} + "/src")
from flab2bp.bench.corpus import _FAST_RANK
from flab2bp.lab.data import load_vendored
from flab2bp.lab.url import parse_url
from flab2bp.layout.band_policy import BandPolicy
from flab2bp.layout.base import NoValidLayout
from flab2bp.layout.sequence_solver import SequencePairLayout
from flab2bp.rates import CandidatePolicy, build_candidates


def main() -> None:
    url = f"https://factoriolab.github.io/dsp/list?o={target}*{rate}&ibe=conveyor-belt-3&mmr={{_FAST_RANK}}&v=11"
    spec = build_candidates(load_vendored(), parse_url(url),
                            candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,)).candidates[0]
    verdict, placement = "OK", None
    t0 = time.perf_counter()
    try:
        placement = SequencePairLayout(band_policy=BandPolicy("portable"),
                                       islands={islands}).lay_out(spec, time_budget_s={budget})
    except NoValidLayout as exc:
        verdict = "REFUSED: " + exc.reason
    wall = time.perf_counter() - t0
    stats = {{}} if placement is None else {{k: str(v) for k, v in dict(placement.stats).items()}}
    print("RESULT " + json.dumps({{
        "islands": {islands}, "verdict": verdict, "wall_s": wall,
        "area": None if placement is None else float(placement.area),
        "search": {{k: stats.get(k) for k in
            ("moves", "accepted_moves", "restarts", "stages", "heights", "seed",
             "decoded_candidates", "detailed_routes", "expansions", "termination",
             "used_height", "compact_seed_status", "compact_seed_wall_time_s",
             "compact_seed_attempt", "search_energy", "box_area", "gap_area")}},
    }}))


if __name__ == "__main__":
    main()
'''

ISLANDS = (1, 4, 8)
CELLS = (("um60", "universe-matrix", 60), ("qc180", "quantum-chip", 180),
         ("gm200", "gravity-matrix", 200), ("um120", "universe-matrix", 120))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--budget", type=float, default=30.0)
    args = ap.parse_args()
    with open(args.out, "w") as fh:
        for tag, target, rate in CELLS:
            for islands in ISLANDS:
                script = HERE / "_proto_islands_child.py"
                script.write_text(CHILD.format(root=str(ROOT), target=target, rate=rate,
                                               islands=islands, budget=args.budget))
                t0 = time.perf_counter()
                proc = subprocess.run(["uv", "run", "python", str(script)], cwd=ROOT,
                                      capture_output=True, text=True)
                line = next((l for l in proc.stdout.splitlines()
                             if l.startswith("RESULT ")), None)
                row = {"cell": tag, "budget_s": args.budget,
                       "subprocess_wall_s": round(time.perf_counter() - t0, 2)}
                row |= (json.loads(line[7:]) if line else
                        {"islands": islands,
                         "verdict": "HARNESS ERROR: " + proc.stderr[-500:]})
                fh.write(json.dumps(row, sort_keys=True) + "\n")
                fh.flush()
                print(json.dumps({k: row.get(k) for k in
                                  ("cell", "islands", "verdict", "wall_s",
                                   "subprocess_wall_s", "area")}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
