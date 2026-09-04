"""The universe-matrix watched clause: do baseline-1 and each candidate round agree?

Re-runnable against the committed evidence beside this script (baseline-1.jsonl,
candidate-1/2/3.jsonl) with no argument, or against a fresh gate's own directory by
passing it as the one positional argument -- so this is the reproduction check, not
only a transcript of one run.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def cells(path: Path) -> dict[tuple[str, int, str], tuple[str | None, float | None]]:
    out: dict[tuple[str, int, str], tuple[str | None, float | None]] = {}
    with path.open() as fh:
        for line in fh:
            r = json.loads(line)
            if r.get("url_id") == "universe-matrix":
                out[(r["strategy"], r["spec_index"], r["spec_label"])] = (
                    r.get("status"),
                    r.get("area"),
                )
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "evidence_dir",
        type=Path,
        nargs="?",
        default=Path(__file__).resolve().parent,
        help="directory holding baseline-1.jsonl and candidate-1/2/3.jsonl "
        "(default: this script's own directory, i.e. the committed evidence)",
    )
    args = ap.parse_args(argv)

    base = cells(args.evidence_dir / "baseline-1.jsonl")
    print("baseline-1 universe-matrix cells:", len(base))
    moved_any = False
    for round_ in (1, 2, 3):
        cand = cells(args.evidence_dir / f"candidate-{round_}.jsonl")
        for key in sorted(set(base) | set(cand)):
            b = base.get(key)
            c = cand.get(key)
            moved = "" if b == c else "  <<< MOVED"
            moved_any = moved_any or bool(moved)
            print(round_, key, "base", b, "cand", c, moved)
    return 1 if moved_any else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
