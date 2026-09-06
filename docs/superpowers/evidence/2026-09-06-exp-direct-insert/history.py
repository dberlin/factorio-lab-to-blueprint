"""Where in the history did freeform's `direct_inserts` go to zero?

Reads every committed evidence JSONL, groups the rows by the commit each run
recorded, orders those commits by author date, and prints one row per
`(commit, strategy)`.  No build is run: this is the record the corpus already
made.
"""

from __future__ import annotations

import collections
import glob
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
EVIDENCE = ROOT / "docs" / "superpowers" / "evidence"


def _num(value: object) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except TypeError, ValueError:
        return 0.0


def main() -> int:
    agg: dict[tuple[str, str], list[float]] = collections.defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
    for path in glob.glob(str(EVIDENCE / "**" / "*.jsonl"), recursive=True):
        for line in Path(path).read_text().splitlines():
            if '"direct_inserts"' not in line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = ((row.get("commit") or "?")[:8], str(row.get("strategy")))
            stats = row.get("stats") or {}
            cell = agg[key]
            cell[0] += 1
            cell[1] += _num(stats.get("direct_inserts"))
            cell[2] += 1.0 if _num(stats.get("direct_inserts")) > 0 else 0.0
            cell[3] += _num(stats.get("direct_insert_candidates"))

    described: dict[str, str] = {}
    for commit, _strategy in agg:
        if commit not in described:
            described[commit] = subprocess.run(
                ["git", "-C", str(ROOT), "show", "-s", "--format=%ci|%s", commit],
                capture_output=True,
                text=True,
                check=False,
            ).stdout.strip()

    rows = [
        {
            "commit": commit,
            "strategy": strategy,
            "when": described[commit].split("|")[0],
            "subject": described[commit].partition("|")[2][:70],
            "rows": int(cell[0]),
            "direct_inserts": int(cell[1]),
            "rows_with_direct": int(cell[2]),
            "direct_insert_candidates": int(cell[3]),
        }
        for (commit, strategy), cell in agg.items()
    ]
    rows.sort(key=lambda r: (r["when"] or "zzz", r["strategy"]))
    for row in rows:
        print(
            f"{row['commit']} {row['strategy']:14s} rows={row['rows']:4d} "
            f"di={row['direct_inserts']:4d} rows_di>0={row['rows_with_direct']:3d} "
            f"cand={row['direct_insert_candidates']:5d}  {row['when']} {row['subject']}"
        )
    Path(__file__).with_name("history.json").write_text(json.dumps(rows, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
