"""Throwaway analysis: decompose freeform area into sharing, direct insert, packing.

Reads the four audit JSONL files this directory's ``run_corpus.sh`` writes and
the harness JSONs ``run_large.sh`` writes, and prints the markdown tables the
README quotes.  Nothing here is production code.
"""

from __future__ import annotations

import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

D = Path(__file__).resolve().parent
CONFIGS = ("base", "nodirect", "noshare", "neither")
LABEL = {
    "base": "baseline",
    "nodirect": "no direct insert",
    "noshare": "no belt sharing",
    "neither": "neither",
}


def load(name: str) -> dict[tuple, dict]:
    path = D / f"audit-{name}.jsonl"
    rows: dict[tuple, dict] = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        rows[r["strategy"], r["url_id"], r["spec_index"], r["power"]] = r
    return rows


def stat(row: dict, key: str) -> float:
    try:
        return float(row.get("stats", {}).get(key, 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def geomean(values: list[float]) -> float:
    return math.exp(statistics.fmean(math.log(v) for v in values)) if values else float("nan")


def quartiles(values: list[float]) -> tuple[float, float, float]:
    s = sorted(values)
    if len(s) < 2:
        return (s[0], s[0], s[0]) if s else (float("nan"),) * 3
    q = statistics.quantiles(s, n=4, method="inclusive")
    return q[0], q[1], q[2]


def cell_class(machines: float) -> str:
    if machines <= 10:
        return "tiny (<=10 machines)"
    if machines <= 60:
        return "mid (11-60)"
    return "large (>60)"


def main() -> int:
    data = {c: load(c) for c in CONFIGS}
    keys = sorted(set(data["base"]))

    print("## Status counts (all 72 cells, budget 30)\n")
    print("| arm | configuration | CLEAN | REFUSED | INVALID | other |")
    print("| --- | --- | --- | --- | --- | --- |")
    for arm in ("freeform", "sequence-pair"):
        for c in CONFIGS:
            counts: dict[str, int] = defaultdict(int)
            for k in keys:
                if k[0] != arm:
                    continue
                counts[data[c].get(k, {}).get("status", "MISSING")] += 1
            other = sum(v for s, v in counts.items() if s not in ("CLEAN", "REFUSED", "INVALID"))
            print(
                f"| {arm} | {LABEL[c]} | {counts['CLEAN']} | {counts['REFUSED']} | "
                f"{counts['INVALID']} | {other} |"
            )
    print()

    print("## Pairwise: each configuration against baseline on the cells BOTH build\n")
    print(
        "| arm | configuration | cells clean in both | geomean area ratio | median | max "
        "| geomean belt_tiles ratio |"
    )
    print("| --- | --- | --- | --- | --- | --- | --- |")
    for arm in ("freeform", "sequence-pair"):
        for c in ("nodirect", "noshare", "neither"):
            pair = [
                k
                for k in keys
                if k[0] == arm
                and data["base"].get(k, {}).get("status") == "CLEAN"
                and data[c].get(k, {}).get("status") == "CLEAN"
            ]
            if not pair:
                continue
            rs = [data[c][k]["area"] / data["base"][k]["area"] for k in pair]
            bt = [
                stat(data[c][k], "belt_tiles") / stat(data["base"][k], "belt_tiles")
                for k in pair
                if stat(data["base"][k], "belt_tiles") > 0
            ]
            print(
                f"| {arm} | {LABEL[c]} | {len(pair)} | {geomean(rs):.4f} | "
                f"{statistics.median(rs):.3f} | {max(rs):.3f} | {geomean(bt):.4f} |"
            )
    print()

    print("## Where direct insertion actually happens (baseline freeform, all 36 cells)\n")
    ff = [k for k in keys if k[0] == "freeform" and data["base"][k].get("status") == "CLEAN"]
    with_di = [k for k in ff if stat(data["base"][k], "direct_inserts") > 0]
    with_cand = [k for k in ff if stat(data["base"][k], "direct_insert_candidates") > 0]
    print(
        f"- {len(with_di)}/{len(ff)} clean baseline cells REALIZE at least one direct insert "
        f"(`direct_inserts` stat).\n"
        f"- {len(with_cand)}/{len(ff)} cells have at least one direct-insert CANDIDATE, "
        f"{sum(stat(data['base'][k], 'direct_insert_candidates') for k in with_cand):.0f} in total.\n"
    )
    print("### Internal control for the direct-insert switch\n")
    print("| subset | cells | geomean area ratio (no direct / base) | cells whose area moved |")
    print("| --- | --- | --- | --- |")
    for label, sel in (
        ("candidates == 0 (switch cannot matter)", [k for k in ff if stat(data["base"][k], "direct_insert_candidates") == 0]),
        ("candidates > 0 (switch can matter)", with_cand),
    ):
        ok = [k for k in sel if data["nodirect"].get(k, {}).get("status") == "CLEAN"]
        rs = [data["nodirect"][k]["area"] / data["base"][k]["area"] for k in ok]
        moved = sum(1 for r in rs if abs(r - 1) > 1e-9)
        print(f"| {label} | {len(ok)} | {geomean(rs):.4f} | {moved} |")
    print()
    if not with_di:
        print("No baseline cell realizes a direct insert, so the per-cell table below is empty.\n")
    print("| url_id | spec | machines | direct_inserts | base area | nodirect area | ratio |")
    print("| --- | --- | --- | --- | --- | --- | --- |")
    for k in sorted(with_di, key=lambda k: -stat(data["base"][k], "direct_inserts")):
        nd = data["nodirect"].get(k, {})
        base_area = data["base"][k]["area"]
        if nd.get("status") == "CLEAN":
            nd_area = f"{nd['area']:.0f}"
            ratio = f"{nd['area'] / base_area:.3f}"
        else:
            nd_area = "-"
            ratio = str(nd.get("status", "?"))
        print(
            f"| {k[1]} | {data['base'][k]['spec_label']} | "
            f"{stat(data['base'][k], 'machines'):.0f} | "
            f"{stat(data['base'][k], 'direct_inserts'):.0f} | {base_area:.0f} | "
            f"{nd_area} | {ratio} |"
        )
    print()

    for arm in ("freeform", "sequence-pair"):
        arm_keys = [k for k in keys if k[0] == arm]
        common = [k for k in arm_keys if all(data[c].get(k, {}).get("status") == "CLEAN" for c in CONFIGS)]
        print(f"## {arm}: area ratio vs baseline, {len(common)}/{len(arm_keys)} cells clean in all four\n")
        print("| configuration | geomean area ratio | Q1 | median | Q3 | min | max |")
        print("| --- | --- | --- | --- | --- | --- | --- |")
        ratios: dict[str, list[float]] = {}
        for c in CONFIGS:
            rs = [data[c][k]["area"] / data["base"][k]["area"] for k in common]
            ratios[c] = rs
            if not rs:
                print(f"| {LABEL[c]} | - | - | - | - | - | - |")
                continue
            q1, med, q3 = quartiles(rs)
            print(
                f"| {LABEL[c]} | {geomean(rs):.4f} | {q1:.3f} | {med:.3f} | {q3:.3f} | "
                f"{min(rs):.3f} | {max(rs):.3f} |"
            )
        if ratios["base"]:
            gd, gs, gn = (geomean(ratios[c]) for c in ("nodirect", "noshare", "neither"))
            print(
                f"\nInteraction: geomean(neither) = {gn:.4f} vs "
                f"geomean(no direct) x geomean(no sharing) = {gd * gs:.4f} "
                f"(neither - product = {gn - gd * gs:+.4f})\n"
            )
        if not common:
            print()
            continue

        print(f"### {arm}: mechanism counters (means over the same cells)\n")
        print(
            "| configuration | area | belt_tiles | direct_inserts | sorters | nets "
            "| routed | machines |"
        )
        print("| --- | --- | --- | --- | --- | --- | --- | --- |")
        for c in CONFIGS:
            print(
                f"| {LABEL[c]} "
                f"| {statistics.fmean(data[c][k]['area'] for k in common):.0f} "
                f"| {statistics.fmean(stat(data[c][k], 'belt_tiles') for k in common):.1f} "
                f"| {statistics.fmean(stat(data[c][k], 'direct_inserts') for k in common):.2f} "
                f"| {statistics.fmean(stat(data[c][k], 'sorters') for k in common):.1f} "
                f"| {statistics.fmean(stat(data[c][k], 'nets') for k in common):.1f} "
                f"| {statistics.fmean(stat(data[c][k], 'routed') for k in common):.1f} "
                f"| {statistics.fmean(stat(data[c][k], 'machines') for k in common):.1f} |"
            )
        print()

        if arm != "freeform":
            continue

        by_class: dict[str, list[tuple]] = defaultdict(list)
        for k in common:
            by_class[cell_class(stat(data["base"][k], "machines"))].append(k)
        print("### freeform: geomean area ratio by cell size\n")
        print("| class | cells | no direct insert | no belt sharing | neither |")
        print("| --- | --- | --- | --- | --- |")
        for cls in ("tiny (<=10 machines)", "mid (11-60)", "large (>60)"):
            ks = by_class.get(cls, [])
            if not ks:
                continue
            cols = " | ".join(
                f"{geomean([data[c][k]['area'] / data['base'][k]['area'] for k in ks]):.4f}"
                for c in ("nodirect", "noshare", "neither")
            )
            print(f"| {cls} | {len(ks)} | {cols} |")
        print()

        print("### freeform: cells whose status changed when a mechanism went off\n")
        print("| url_id | spec | machines | base | no direct | no sharing | neither |")
        print("| --- | --- | --- | --- | --- | --- | --- |")
        moved = 0
        for k in [k for k in keys if k[0] == "freeform"]:
            statuses = [data[c].get(k, {}).get("status", "MISSING") for c in CONFIGS]
            if len(set(statuses)) == 1:
                continue
            moved += 1
            label = data["base"].get(k, {}).get("spec_label", "")
            print(
                f"| {k[1]} | {label} | {stat(data['base'].get(k, {}), 'machines'):.0f} | "
                + " | ".join(statuses)
                + " |"
            )
        if not moved:
            print("| (none) | | | | | | |")
        print()

        print("### freeform: biggest area movers (no belt sharing)\n")
        print("| url_id | spec | machines | base area | noshare area | ratio | base belts | noshare belts |")
        print("| --- | --- | --- | --- | --- | --- | --- | --- |")
        rows = sorted(
            common,
            key=lambda k: data["noshare"][k]["area"] / data["base"][k]["area"],
            reverse=True,
        )[:10]
        for k in rows:
            print(
                f"| {k[1]} | {data['base'][k]['spec_label']} | "
                f"{stat(data['base'][k], 'machines'):.0f} | {data['base'][k]['area']:.0f} | "
                f"{data['noshare'][k]['area']:.0f} | "
                f"{data['noshare'][k]['area'] / data['base'][k]['area']:.3f} | "
                f"{stat(data['base'][k], 'belt_tiles'):.0f} | "
                f"{stat(data['noshare'][k], 'belt_tiles'):.0f} |"
            )
        print()

    # ---- large cells -------------------------------------------------------
    large = D / "large"
    if not large.is_dir():
        return 0
    print("## Large cells (prof_harness, freeform)\n")
    print("| cell | configuration | verdict | area | ratio | belt_tiles | direct_inserts | wall s |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for cell in ("um60", "um120", "gm200", "qc180", "belt3"):
        base_area = None
        for c in CONFIGS:
            path = large / f"{cell}-{c}.json"
            if not path.is_file():
                print(f"| {cell} | {LABEL[c]} | (no file) | | | | | |")
                continue
            row = json.loads(path.read_text())
            area = row.get("area")
            if c == "base":
                base_area = area
            ratio = f"{area / base_area:.3f}" if area and base_area else "-"
            stats = row.get("stats", {})
            print(
                f"| {cell} | {LABEL[c]} | {row['verdict'][:40]} | "
                f"{'' if area is None else f'{area:.0f}'} | {ratio} | "
                f"{stats.get('belt_tiles', '')} | {stats.get('direct_inserts', '')} | "
                f"{row['wall_s']:.0f} |"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
