"""Interleaved paired corpus audit of two ``freeform.py`` revisions.

    uv run python scripts/audit_ab.py /tmp/base.py /tmp/cand.py --rounds 5

One audit run of A, then one of B, then A again, and so on.  CP-SAT is
multi-worker and nondeterministic and this box has other agents on it, so a
block of A followed by a block of B measures the hour as much as the code;
today an unpaired comparison in this project showed a regression that vanished
entirely when re-run interleaved.

Prints every round's clean count and wall, then the totals.  ``INVALID`` is
printed separately and on its own line because it is the one outcome that must
be zero in every round: a blueprint that pastes and does not run is worse than
a refusal.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LIVE = HERE.parent / "src" / "flab2bp" / "layout" / "freeform.py"
LINE = re.compile(
    r"=== (\w+): (\d+)/(\d+) clean.*?refused (\d+), invalid (\d+), "
    r"crashed (\d+), not run (\d+)"
)


def once(extra: list[str]) -> tuple[int, int, int, int, float]:
    out = subprocess.run(
        [sys.executable, str(HERE / "audit.py"), "--strategy", "freeform",
         "--budget", "4", "--jobs", "16", "--max-seconds", "250", "--quiet",
         *extra],
        capture_output=True, text=True,
    ).stdout
    m = LINE.search(out)
    if not m:
        raise SystemExit(f"unparsable audit output:\n{out[-3000:]}")
    wall = re.search(r"^(\d+)s wall", out, re.M)
    return (
        int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5)),
        float(wall.group(1)) if wall else 0.0,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--rounds", type=int, default=5)
    ap.add_argument("--extra", nargs="*", default=[])
    args = ap.parse_args()

    keep = LIVE.read_bytes()
    tallies: dict[str, list[tuple[int, int, int, int, float]]] = {"A": [], "B": []}
    try:
        for r in range(args.rounds):
            for name, src in (("A", args.a), ("B", args.b)):
                shutil.copyfile(src, LIVE)
                got = once(args.extra)
                tallies[name].append(got)
                print(f"round {r + 1} {name}: {got[0]}/{got[1]} clean  "
                      f"refused {got[2]}  INVALID {got[3]}  {got[4]:.0f}s wall",
                      flush=True)
    finally:
        LIVE.write_bytes(keep)

    for name in ("A", "B"):
        rows = tallies[name]
        if not rows:
            continue
        clean = [r[0] for r in rows]
        print(f"{name}: clean {clean}  mean {sum(clean) / len(clean):.2f}  "
              f"INVALID {sum(r[3] for r in rows)}  "
              f"mean wall {sum(r[4] for r in rows) / len(rows):.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
