"""Budget semantics: what does the last 20 s of a 30 s budget actually buy?

Runs one cell at a ladder of budgets and records verdict, wall and area.  If
area at 8 s equals area at 30 s, the budget is being spent on nothing the user
sees and "return the first clean layout" is a 3-4x speedup at zero quality cost.

    uv run python budget_ladder.py --out ladder.jsonl
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
HARNESS = ROOT / "docs/superpowers/evidence/2026-09-05-scale-profile/prof_harness.py"
OUT_DIR = Path(__file__).resolve().parent

CELLS = (
    ("um60", ["universe-matrix", "--rate", "60"]),
    ("qc180", ["quantum-chip", "--rate", "180"]),
    ("gm200", ["gravity-matrix", "--rate", "200"]),
    ("um120", ["universe-matrix", "--rate", "120"]),
)
BUDGETS = (4.0, 8.0, 12.0, 20.0, 30.0)
STRATEGIES = ("freeform", "sequence-pair")


def run(name: str, args: list[str], strategy: str, budget: float) -> dict[str, object]:
    tag = f"ladder-{name}-{strategy}-{budget:g}"
    out = OUT_DIR / tag
    t0 = time.perf_counter()
    proc = subprocess.run(
        ["uv", "run", "python", str(HARNESS), *args, "--strategy", strategy,
         "--budget", str(budget), "--out", str(out)],
        cwd=ROOT, capture_output=True, text=True,
    )
    wall = time.perf_counter() - t0
    row: dict[str, object] = {"cell": name, "strategy": strategy, "budget_s": budget,
                              "subprocess_wall_s": wall, "rc": proc.returncode}
    path = out.with_suffix(".json")
    if path.exists():
        got = json.loads(path.read_text())
        row |= {k: got[k] for k in ("verdict", "wall_s", "area", "machines", "phases")}
        row["stats"] = got.get("stats") or {}
        path.unlink()
    else:
        row["verdict"] = f"NO OUTPUT: {proc.stderr[-300:]}"
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    rows = []
    with open(args.out, "w") as fh:
        for name, cell in CELLS:
            for strategy in STRATEGIES:
                for budget in BUDGETS:
                    row = run(name, cell, strategy, budget)
                    rows.append(row)
                    fh.write(json.dumps(row, sort_keys=True) + "\n")
                    fh.flush()
                    print(json.dumps({k: row.get(k) for k in
                                      ("cell", "strategy", "budget_s", "verdict",
                                       "wall_s", "area")}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
