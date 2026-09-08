"""Turn the per-arm JSONL into the verdict table, the movers and the costs.

    uv run python analyse.py round1/*.jsonl [--baseline off]

Prints, per arm: CLEAN/REFUSED/INVALID/CRASH counts split by strategy, the
coater-merge total, area geomean over the cells clean in EVERY arm, and
attempt-wall p50/p95.  Then the named movers against the baseline arm, and the
``no-proliferator`` control check -- if a control cell moves at all, the switch
leaks and every other number here is invalid.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

CONTROL = "no-proliferator"


def load(paths: list[Path]) -> dict[str, dict[tuple[str, str, str], dict]]:
    arms: dict[str, dict[tuple[str, str, str], dict]] = defaultdict(dict)
    for path in paths:
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            arm = row.get("coater_arm", path.stem)
            arms[arm][row["strategy"], row["url_id"], row["spec_label"]] = row
    return arms


def geomean(values: list[float]) -> float:
    return math.exp(sum(math.log(v) for v in values) / len(values)) if values else 0.0


def pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(q * (len(ordered) - 1) + 0.5))
    return ordered[index]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("jsonl", nargs="+", type=Path)
    ap.add_argument("--baseline", default="off")
    args = ap.parse_args()
    arms = load(args.jsonl)
    order = [a for a in ("off", "seat", "packed", "placed") if a in arms]
    order += [a for a in sorted(arms) if a not in order]

    # Cells present in EVERY arm -- the only fair comparison set, since the
    # `packed` arm has no sequence-pair column.
    shared = set.intersection(*(set(arms[a]) for a in order))
    clean_everywhere = sorted(
        cell for cell in shared if all(arms[a][cell]["status"] == "CLEAN" for a in order)
    )

    print(f"arms: {', '.join(order)}")
    print(f"cells present in every arm: {len(shared)}")
    print(f"cells CLEAN in every arm: {len(clean_everywhere)}\n")

    header = (
        f"{'arm':<8} {'cells':>5} {'CLEAN':>6} {'REFUSED':>8} {'INVALID':>8} "
        f"{'CRASH':>6} {'merges':>7} {'coaters':>8} {'areaGM':>9} "
        f"{'rt p50':>7} {'rt p95':>7} {'ripups':>7} {'nets':>7}"
    )
    print(header)
    print("-" * len(header))
    for arm in order:
        rows = arms[arm]
        status = defaultdict(int)
        for row in rows.values():
            status[row["status"]] += 1
        merges = sum(int(r.get("coater_merges", 0)) for r in rows.values())
        coaters = sum(int(r.get("coaters", 0)) for r in rows.values())
        areas = [float(rows[c]["area"]) for c in clean_everywhere]

        def stat(name: str) -> list[float]:
            return [
                float(rows[c].get("stats", {}).get(name, 0.0))
                for c in clean_everywhere
                if "stats" in rows[c]
            ]

        route = stat("detailed_route_time_s")
        ripups = sum(stat("repair_iterations"))
        nets = sum(stat("nets"))
        print(
            f"{arm:<8} {len(rows):>5} {status['CLEAN']:>6} {status['REFUSED']:>8} "
            f"{status['INVALID']:>8} {status['CRASH']:>6} {merges:>7} {coaters:>8} "
            f"{geomean(areas):>9.1f} {pct(route, 0.5):>7.1f} {pct(route, 0.95):>7.1f} "
            f"{ripups:>7.0f} {nets:>7.0f}"
        )
    print(
        "  (merges/coaters are totals over ALL that arm's cells; areaGM, routing "
        "seconds, rip-ups and nets are over the cells clean in every arm)"
    )

    print("\nper strategy CLEAN / cells")
    for arm in order:
        by_strategy = defaultdict(lambda: [0, 0])
        for (strategy, _u, _p), row in arms[arm].items():
            by_strategy[strategy][1] += 1
            if row["status"] == "CLEAN":
                by_strategy[strategy][0] += 1
        parts = " ".join(f"{s}={c}/{n}" for s, (c, n) in sorted(by_strategy.items()))
        print(f"  {arm:<8} {parts}")

    base = args.baseline
    print(f"\nmovers against `{base}`")
    for arm in order:
        if arm == base:
            continue
        gained, lost, other = [], [], []
        for cell in sorted(set(arms[arm]) & set(arms[base])):
            was = arms[base][cell]["status"]
            now = arms[arm][cell]["status"]
            if was == now:
                continue
            name = "/".join(cell)
            if now == "CLEAN":
                gained.append(name)
            elif was == "CLEAN":
                lost.append(f"{name} -> {now}: {arms[arm][cell]['detail'][:90]}")
            else:
                other.append(f"{name} {was} -> {now}")
        print(f"  {arm}: +{len(gained)} clean, -{len(lost)} clean")
        for name in gained:
            print(f"    GAINED {name}")
        for name in lost:
            print(f"    LOST   {name}")
        for name in other:
            print(f"    moved  {name}")

    print(f"\narea against `{base}` over the {len(clean_everywhere)} cells clean everywhere")
    base_gm = geomean([float(arms[base][c]["area"]) for c in clean_everywhere])
    for arm in order:
        gm = geomean([float(arms[arm][c]["area"]) for c in clean_everywhere])
        delta = (gm / base_gm - 1.0) * 100.0 if base_gm else 0.0
        print(f"  {arm:<8} {gm:9.1f}  {delta:+6.2f}%")

    print("\nproliferated cells only (the cells any arm can move)")
    for arm in order:
        rows = {c: r for c, r in arms[arm].items() if c[2] != CONTROL}
        clean = sum(1 for r in rows.values() if r["status"] == "CLEAN")
        merges = sum(int(r.get("coater_merges", 0)) for r in rows.values())
        print(f"  {arm:<8} {clean}/{len(rows)} clean, {merges} coater-merge findings")

    print(f"\npairwise area against `{base}`, over the cells clean in BOTH arms")
    for arm in order:
        if arm == base:
            continue
        both = sorted(
            cell
            for cell in set(arms[arm]) & set(arms[base])
            if arms[arm][cell]["status"] == "CLEAN" and arms[base][cell]["status"] == "CLEAN"
        )
        if not both:
            print(f"  {arm:<8} no shared clean cells")
            continue
        mine = geomean([float(arms[arm][c]["area"]) for c in both])
        theirs = geomean([float(arms[base][c]["area"]) for c in both])
        bigger = sum(1 for c in both if arms[arm][c]["area"] > arms[base][c]["area"])
        smaller = sum(1 for c in both if arms[arm][c]["area"] < arms[base][c]["area"])
        print(
            f"  {arm:<8} n={len(both):>3}  {theirs:8.1f} -> {mine:8.1f}  "
            f"{(mine / theirs - 1) * 100:+6.2f}%  ({bigger} larger, {smaller} smaller)"
        )

    print("\nno-proliferator controls (must be identical across arms)")
    controls = sorted(cell for cell in shared if cell[2] == CONTROL)
    leaks = 0
    for cell in controls:
        values = {
            arm: (
                arms[arm][cell]["status"],
                arms[arm][cell]["area"],
                arms[arm][cell].get("belt_tiles"),
                arms[arm][cell].get("coaters"),
            )
            for arm in order
        }
        if len(set(values.values())) != 1:
            leaks += 1
            print(f"  LEAK {'/'.join(cell)}: {values}")
    print(f"  {len(controls)} control cells, {leaks} differing -> " + ("FAIL" if leaks else "PASS"))


if __name__ == "__main__":
    main()
