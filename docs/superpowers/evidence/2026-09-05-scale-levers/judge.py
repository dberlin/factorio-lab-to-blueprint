"""Compare one audit round's baseline and candidate JSONL, cell by cell.

`scripts/audit.py` prints ``NOT CLEAN`` whenever any cell refuses and
`scripts/audit_compare.py` prints ``FAIL`` for every non-clean candidate row
regardless of what the baseline did; master itself is not 72/72 here. So the
gate cannot read either banner. It reads status counts and the *set* of cells
whose status differs between the paired files, which is what this prints.

    uv run python judge.py BASELINE.jsonl CANDIDATE.jsonl

Keys rows by ``(strategy, url_id, spec_index)``. Prints, in order: the status
counts for each side; cells CLEAN in the baseline and not CLEAN in the
candidate (candidate regressions); cells that moved the other way; every
INVALID or CRASH row in the candidate with its detail; and the geometric-mean
area ratio over the cells clean in both.
"""

from __future__ import annotations

import json
import math
import sys
from collections import Counter


def load(path: str) -> dict[tuple[str, str, int], dict]:
    rows: dict[tuple[str, str, int], dict] = {}
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            rows[(row["strategy"], row["url_id"], row["spec_index"])] = row
    return rows


def label(key: tuple[str, str, int], row: dict | None) -> str:
    strategy, url_id, index = key
    spec = row.get("spec_label", "") if row else ""
    return f"{strategy} {url_id} [{index}{'/' + spec if spec else ''}]"


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    base_path, cand_path = argv[1], argv[2]
    base, cand = load(base_path), load(cand_path)

    print(f"baseline : {base_path}  ({len(base)} cells)")
    print(f"candidate: {cand_path}  ({len(cand)} cells)")
    base_commit = next(iter(base.values()))["commit"][:7] if base else "?"
    cand_commit = next(iter(cand.values()))["commit"][:7] if cand else "?"
    print(f"commits  : baseline {base_commit}  candidate {cand_commit}")

    base_counts = Counter(r["status"] for r in base.values())
    cand_counts = Counter(r["status"] for r in cand.values())
    statuses = sorted(set(base_counts) | set(cand_counts))
    print("\nstatus counts")
    print(f"  {'status':<10} {'baseline':>9} {'candidate':>10}")
    for status in statuses:
        print(f"  {status:<10} {base_counts[status]:>9} {cand_counts[status]:>10}")

    only_base = sorted(set(base) - set(cand))
    only_cand = sorted(set(cand) - set(base))
    if only_base or only_cand:
        print("\ncells present on one side only")
        for key in only_base:
            print(f"  baseline only : {label(key, base[key])}")
        for key in only_cand:
            print(f"  candidate only: {label(key, cand[key])}")

    shared = sorted(set(base) & set(cand))
    worse = [k for k in shared if base[k]["status"] == "CLEAN" and cand[k]["status"] != "CLEAN"]
    better = [k for k in shared if base[k]["status"] != "CLEAN" and cand[k]["status"] == "CLEAN"]
    other = [
        k
        for k in shared
        if base[k]["status"] != cand[k]["status"] and k not in worse and k not in better
    ]

    print(f"\nCLEAN in baseline, not CLEAN in candidate: {len(worse)}")
    for key in worse:
        detail = (cand[key].get("detail") or "").strip().replace("\n", " ")
        print(f"  {label(key, cand[key])}: -> {cand[key]['status']}  {detail[:200]}")

    print(f"\nnot CLEAN in baseline, CLEAN in candidate: {len(better)}")
    for key in better:
        detail = (base[key].get("detail") or "").strip().replace("\n", " ")
        print(f"  {label(key, base[key])}: {base[key]['status']} ->  {detail[:200]}")

    if other:
        print(f"\nother status changes (neither side CLEAN): {len(other)}")
        for key in other:
            print(f"  {label(key, cand[key])}: {base[key]['status']} -> {cand[key]['status']}")

    bad = [k for k in sorted(cand) if cand[k]["status"] in {"INVALID", "CRASH"}]
    print(f"\nINVALID/CRASH rows in candidate: {len(bad)}")
    for key in bad:
        detail = (cand[key].get("detail") or "").strip().replace("\n", " ")
        print(f"  {cand[key]['status']} {label(key, cand[key])}: {detail[:400]}")

    bad_base = [k for k in sorted(base) if base[k]["status"] in {"INVALID", "CRASH"}]
    print(f"INVALID/CRASH rows in baseline: {len(bad_base)}")
    for key in bad_base:
        detail = (base[key].get("detail") or "").strip().replace("\n", " ")
        print(f"  {base[key]['status']} {label(key, base[key])}: {detail[:400]}")

    both_clean = [
        k
        for k in shared
        if base[k]["status"] == "CLEAN"
        and cand[k]["status"] == "CLEAN"
        and (base[k].get("area") or 0) > 0
        and (cand[k].get("area") or 0) > 0
    ]
    print(f"\ncells CLEAN in both: {len(both_clean)}")
    if both_clean:
        logs = [math.log(cand[k]["area"] / base[k]["area"]) for k in both_clean]
        gmean = math.exp(sum(logs) / len(logs))
        print(f"geometric-mean area ratio (candidate/baseline): {gmean:.5f}")
        moved = sorted(
            (
                (cand[k]["area"] / base[k]["area"], k)
                for k in both_clean
                if abs(cand[k]["area"] / base[k]["area"] - 1.0) > 1e-9
            ),
            key=lambda pair: abs(math.log(pair[0])),
            reverse=True,
        )
        print(f"cells whose area moved at all: {len(moved)}")
        for ratio, key in moved[:10]:
            print(
                f"  {ratio:.4f}  {label(key, cand[key])}"
                f"  {base[key]['area']:.0f} -> {cand[key]['area']:.0f}"
            )

    def p95(rows: dict) -> float:
        walls = sorted(r.get("build_wall_time_s") or 0.0 for r in rows.values())
        if not walls:
            return 0.0
        return walls[min(len(walls) - 1, int(math.ceil(0.95 * len(walls))) - 1)]

    print(f"\np95 build wall: baseline {p95(base):.2f} s  candidate {p95(cand):.2f} s")
    print(
        f"total build wall: baseline {sum(r.get('build_wall_time_s') or 0.0 for r in base.values()):.1f} s"
        f"  candidate {sum(r.get('build_wall_time_s') or 0.0 for r in cand.values()):.1f} s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
