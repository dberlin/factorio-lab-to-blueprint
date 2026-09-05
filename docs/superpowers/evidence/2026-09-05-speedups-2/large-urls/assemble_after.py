"""Fold the after-*.json profiles into after.jsonl, shaped like before.jsonl.

`prof_harness.py` writes one JSON per run and knows nothing about the grid it
was called from, so the label/policy/strategy/budget the run belongs to are
re-attached here from the file name -- the same four keys `before.jsonl`
carries, in the same order, so the two files can be joined key-for-key.

    uv run python assemble_after.py DIR > after.jsonl
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    directory = Path(argv[1])
    rows = []
    for path in sorted(directory.glob("after-*.json")):
        stem = path.stem[len("after-") :]
        budget = stem.rsplit("-", 1)[1]
        rest = stem.rsplit("-", 1)[0]
        strategy = "sequence-pair" if rest.endswith("-sequence-pair") else "freeform"
        rest = rest[: -(len(strategy) + 1)]
        label, policy = rest.split("-", 1)
        row = json.loads(path.read_text())
        row["label"] = label
        row["policy"] = policy
        row["strategy"] = strategy
        row["budget"] = int(budget)
        rows.append(row)
    for row in rows:
        print(json.dumps(row, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
