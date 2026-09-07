"""Turn one round's two JSONLs into the gate's verdict table, movers and costs.

    uv run python analyse.py roundA/baseline.jsonl roundA/placed.jsonl

Arms are named by FILE STEM, not by the rows' ``coater_arm`` field: the
baseline arm runs from a merge-base checkout whose ``audit.py`` writes
``coater_arm: "off"``, and calling that arm "off" in the table would invite the
reader to confuse it with this branch's ``FLAB2BP_COATER_NODE=off`` path, which
is a different (edited) code path and is NOT what was measured.

Prints, per arm: CLEAN/REFUSED/INVALID/CRASH split by strategy, the coater-merge
total, coaters, area geomean over the cells clean in BOTH arms, route p50/p95
and rip-ups.  Then the four gate clauses' inputs: named movers in both
directions with each lost cell's refusal message, the pairwise area delta with
its larger/smaller split, and belt tiles + nets over the PROLIFERATED cells
clean in both arms.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

CONTROL = "no-proliferator"
Cell = tuple[str, str, str]


def load(paths: list[Path]) -> dict[str, dict[Cell, dict]]:
    arms: dict[str, dict[Cell, dict]] = {}
    for path in paths:
        rows: dict[Cell, dict] = {}
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            rows[row["strategy"], row["url_id"], row["spec_label"]] = row
        arms[path.stem] = rows
    return arms


def geomean(values: list[float]) -> float:
    return math.exp(sum(math.log(v) for v in values) / len(values)) if values else 0.0


def pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * (len(ordered) - 1) + 0.5))]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("jsonl", nargs="+", type=Path)
    ap.add_argument("--baseline", default="baseline")
    args = ap.parse_args()
    arms = load(args.jsonl)
    base = args.baseline
    order = [base] + [a for a in sorted(arms) if a != base]

    shared = set.intersection(*(set(arms[a]) for a in order))
    clean_both = sorted(
        cell for cell in shared if all(arms[a][cell]["status"] == "CLEAN" for a in order)
    )

    print(f"arms: {', '.join(order)}")
    print(f"cells present in every arm: {len(shared)}")
    print(f"cells CLEAN in every arm: {len(clean_both)}\n")

    header = (
        f"{'arm':<9} {'cells':>5} {'CLEAN':>6} {'REFUSED':>8} {'INVALID':>8} "
        f"{'CRASH':>6} {'merges':>7} {'coaters':>8} {'areaGM':>9} "
        f"{'rt p50':>7} {'rt p95':>7} {'ripups':>8} {'nets':>8}"
    )
    print(header)
    print("-" * len(header))
    for arm in order:
        rows = arms[arm]
        status: dict[str, int] = defaultdict(int)
        for row in rows.values():
            status[row["status"]] += 1
        merges = sum(int(r.get("coater_merges", 0)) for r in rows.values())
        coaters = sum(int(r.get("coaters", 0)) for r in rows.values())
        areas = [float(rows[c]["area"]) for c in clean_both]

        def stat(name: str, rows: dict[Cell, dict] = rows) -> list[float]:
            return [
                float(rows[c].get("stats", {}).get(name, 0.0))
                for c in clean_both
                if "stats" in rows[c]
            ]

        route = stat("detailed_route_time_s")
        print(
            f"{arm:<9} {len(rows):>5} {status['CLEAN']:>6} {status['REFUSED']:>8} "
            f"{status['INVALID']:>8} {status['CRASH']:>6} {merges:>7} {coaters:>8} "
            f"{geomean(areas):>9.1f} {pct(route, 0.5):>7.1f} {pct(route, 0.95):>7.1f} "
            f"{sum(stat('repair_iterations')):>8.0f} {sum(stat('nets')):>8.0f}"
        )
    print(
        "  (merges/coaters are totals over ALL that arm's cells; areaGM, routing "
        "seconds, rip-ups and nets are over the cells clean in both arms)"
    )

    print("\nper strategy CLEAN / cells")
    for arm in order:
        by_strategy: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for (strategy, _u, _p), row in arms[arm].items():
            by_strategy[strategy][1] += 1
            if row["status"] == "CLEAN":
                by_strategy[strategy][0] += 1
        parts = " ".join(f"{s}={c}/{n}" for s, (c, n) in sorted(by_strategy.items()))
        print(f"  {arm:<9} {parts}")

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
                lost.append(f"{name} -> {now}: {arms[arm][cell]['detail']}")
            else:
                other.append(f"{name} {was} -> {now}")
        print(f"  {arm}: +{len(gained)} clean, -{len(lost)} clean")
        for name in gained:
            print(f"    GAINED {name}")
        for name in lost:
            print(f"    LOST   {name}")
        for name in other:
            print(f"    moved  {name}")

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
            print(f"  {arm:<9} no shared clean cells")
            continue
        mine = geomean([float(arms[arm][c]["area"]) for c in both])
        theirs = geomean([float(arms[base][c]["area"]) for c in both])
        bigger = sum(1 for c in both if arms[arm][c]["area"] > arms[base][c]["area"])
        smaller = sum(1 for c in both if arms[arm][c]["area"] < arms[base][c]["area"])
        print(
            f"  {arm:<9} n={len(both):>3}  {theirs:8.1f} -> {mine:8.1f}  "
            f"{(mine / theirs - 1) * 100:+6.2f}%  ({bigger} larger, {smaller} smaller, "
            f"{len(both) - bigger - smaller} equal)"
        )

    print("\nbelt tiles and nets over the PROLIFERATED cells clean in both arms")
    prolif = [c for c in clean_both if c[2] != CONTROL]
    for arm in order:
        rows = arms[arm]
        tiles = sum(int(rows[c].get("belt_tiles", 0)) for c in prolif)
        nets = sum(float(rows[c].get("stats", {}).get("nets", 0.0)) for c in prolif)
        coaters = sum(int(rows[c].get("coaters", 0)) for c in prolif)
        print(f"  {arm:<9} n={len(prolif):>3}  belt_tiles={tiles:>7}  nets={nets:>7.0f}  coaters={coaters:>5}")
    if len(order) == 2:
        a, b = order
        for name, key in (("belt_tiles", "belt_tiles"), ("nets", "nets")):
            if key == "nets":
                va = sum(float(arms[a][c].get("stats", {}).get("nets", 0.0)) for c in prolif)
                vb = sum(float(arms[b][c].get("stats", {}).get("nets", 0.0)) for c in prolif)
            else:
                va = sum(int(arms[a][c].get(key, 0)) for c in prolif)
                vb = sum(int(arms[b][c].get(key, 0)) for c in prolif)
            delta = (vb / va - 1) * 100 if va else 0.0
            print(f"  {name} {b} vs {a}: {va:.0f} -> {vb:.0f}  {delta:+.2f}%")

    print("\nproliferated cells only (the cells the switch can move)")
    for arm in order:
        rows = {c: r for c, r in arms[arm].items() if c[2] != CONTROL}
        clean = sum(1 for r in rows.values() if r["status"] == "CLEAN")
        merges = sum(int(r.get("coater_merges", 0)) for r in rows.values())
        print(f"  {arm:<9} {clean}/{len(rows)} clean, {merges} coater-merge findings")

    print("\ncoater-merge findings per cell (any arm, any count)")
    any_merge = False
    for arm in order:
        for cell in sorted(arms[arm]):
            n = int(arms[arm][cell].get("coater_merges", 0))
            if n:
                any_merge = True
                print(f"  {arm:<9} {'/'.join(cell)}: {n}")
    if not any_merge:
        print("  (none in either arm)")


if __name__ == "__main__":
    main()
