"""Interleaved paired corpus audit of two ``freeform.py`` revisions.

    uv run python scripts/audit_ab.py "$MY_DIR/base.py" "$MY_DIR/cand.py" --rounds 5

One audit run of A, then one of B, then A again, and so on.  CP-SAT is
multi-worker and nondeterministic and this box has other agents on it, so a
block of A followed by a block of B measures the hour as much as the code;
an unpaired comparison in this project once showed a regression that vanished
entirely when re-run interleaved.

Prints every round's clean count and wall, then the totals.  ``INVALID`` is
printed separately and on its own line because it is the one outcome that must
be zero in every round: a blueprint that pastes and does not run is worse than
a refusal.

**PUT THE ARM FILES SOMEWHERE PRIVATE.**  This used to suggest ``/tmp/base.py``
and ``/tmp/cand.py``, and those names cost a real measurement: two agents on
this box wrote the same ``/tmp`` path at the same time, so one of them unknowingly
compared master against *the other agent's branch* and got a flat, plausible,
entirely meaningless result.  Nothing failed; the numbers just meant nothing.
Use a directory only this run writes to.

Two guards below make that class of accident loud rather than silent: both arms
are SNAPSHOTTED and digested before the first round -- so a later writer to the
original path cannot change what is being measured half way through -- and two
arms that hash the same are a hard error, because a file compared against itself
is the exact signature of the collision described above.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
LIVE = HERE.parent / "src" / "flab2bp" / "layout" / "freeform.py"
LINE = re.compile(
    r"=== (\w+): (\d+)/(\d+) clean.*?refused (\d+), invalid (\d+), "
    r"crashed (\d+), not run (\d+)"
)


def once(extra: list[str]) -> tuple[int, int, int, int, float]:
    out = subprocess.run(
        [
            sys.executable,
            str(HERE / "audit.py"),
            "--strategy",
            "freeform",
            "--budget",
            "4",
            "--jobs",
            "16",
            "--max-seconds",
            "250",
            "--quiet",
            *extra,
        ],
        capture_output=True,
        text=True,
    ).stdout
    m = LINE.search(out)
    if not m:
        raise SystemExit(f"unparsable audit output:\n{out[-3000:]}")
    wall = re.search(r"^(\d+)s wall", out, re.M)
    return (
        int(m.group(2)),
        int(m.group(3)),
        int(m.group(4)),
        int(m.group(5)),
        float(wall.group(1)) if wall else 0.0,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--rounds", type=int, default=5)
    ap.add_argument("--extra", nargs="*", default=[])
    args = ap.parse_args()

    # SNAPSHOT BOTH ARMS BEFORE MEASURING ANYTHING.
    #
    # The arm files are paths somebody else can write. Copying them once, here,
    # means a concurrent writer can no longer change what is under test between
    # round 1 and round 12 -- which is not hypothetical: it has happened on this
    # box, through two agents choosing the same `/tmp` name.
    work = Path(tempfile.mkdtemp(prefix="audit_ab-"))
    try:
        arms: dict[str, tuple[Path, str]] = {}
        for name, src in (("A", args.a), ("B", args.b)):
            snap = work / f"{name}.py"
            shutil.copyfile(src, snap)
            arms[name] = (snap, hashlib.sha256(snap.read_bytes()).hexdigest())
            print(f"arm {name}: {src}  sha256 {arms[name][1][:16]}", flush=True)

        # A FILE COMPARED AGAINST ITSELF IS NOT A COMPARISON.
        #
        # It yields two indistinguishable columns and an air of rigour, and it
        # is precisely what a clobbered arm looks like from the inside. Refuse,
        # rather than print a tidy table that means nothing.
        if arms["A"][1] == arms["B"][1]:
            raise SystemExit(
                f"both arms are byte-identical (sha256 {arms['A'][1][:16]}).\n"
                f"  A: {args.a}\n  B: {args.b}\n"
                "Either the same file was passed twice, or one arm was "
                "overwritten -- check for another process writing that path."
            )

        keep = LIVE.read_bytes()
        tallies: dict[str, list[tuple[int, int, int, int, float]]] = {"A": [], "B": []}
        try:
            for r in range(args.rounds):
                for name in ("A", "B"):
                    shutil.copyfile(arms[name][0], LIVE)
                    got = once(args.extra)
                    tallies[name].append(got)
                    print(
                        f"round {r + 1} {name}: {got[0]}/{got[1]} clean  "
                        f"refused {got[2]}  INVALID {got[3]}  {got[4]:.0f}s wall",
                        flush=True,
                    )
        finally:
            LIVE.write_bytes(keep)

        for name in ("A", "B"):
            rows = tallies[name]
            if not rows:
                continue
            clean = [r[0] for r in rows]
            print(
                f"{name}: clean {clean}  mean {sum(clean) / len(clean):.2f}  "
                f"INVALID {sum(r[3] for r in rows)}  "
                f"mean wall {sum(r[4] for r in rows) / len(rows):.1f}s"
            )
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
