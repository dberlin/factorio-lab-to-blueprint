"""Interleaved paired A/B of two ``freeform.py`` revisions on captured searches.

    uv run python scripts/route_ab.py /tmp/base.py /tmp/cand.py --rounds 7

The two files are swapped into place one after the other, over and over, and
each is timed on the same captured search corpus.  INTERLEAVED because a quiet
box and a busy box differ by more than any change measured here: running all of
A and then all of B measures when the run happened as much as what it did.

Reports the MINIMUM over rounds, which is the honest statistic for "how long
does this take when nothing else is in the way" -- the mean measures the other
agents on the machine.  Also prints the digest, which must be identical: a
candidate that changes it routed different belts.
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


def run(cases: Path) -> tuple[float, int, str]:
    out = subprocess.run(
        [sys.executable, str(HERE / "route_bench.py"), "--cases", str(cases),
         "--rounds", "1"],
        capture_output=True, text=True, check=True,
    ).stdout
    m = re.search(r"BEST ([\d.]+)s\s+([\d,]+) expansions.*digest (\w+)", out)
    if not m:
        raise SystemExit(f"unparsable bench output:\n{out}")
    return float(m.group(1)), int(m.group(2).replace(",", "")), m.group(3)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--cases", nargs="+", required=True)
    ap.add_argument("--rounds", type=int, default=7)
    args = ap.parse_args()

    keep = LIVE.read_bytes()
    best: dict[tuple[str, str], tuple[float, int, str]] = {}
    try:
        for _ in range(args.rounds):
            for name, src in (("A", args.a), ("B", args.b)):
                shutil.copyfile(src, LIVE)
                for c in args.cases:
                    got = run(Path(c))
                    key = (name, c)
                    if key not in best or got[0] < best[key][0]:
                        best[key] = got
    finally:
        LIVE.write_bytes(keep)

    for c in args.cases:
        ta, na, da = best[("A", c)]
        tb, nb, db = best[("B", c)]
        print(f"{Path(c).stem}")
        print(f"  A {ta:.3f}s  {na:,} exp  digest {da}")
        print(f"  B {tb:.3f}s  {nb:,} exp  digest {db}   "
              f"{100 * (tb - ta) / ta:+.1f}%"
              + ("" if da == db else "   *** DIGEST DIFFERS ***"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
