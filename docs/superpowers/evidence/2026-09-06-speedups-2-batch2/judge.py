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

Extended for the 2026-09-05 speedups-2 batch (L2 compact-seed share + L1
sequence-pair islands), because only the sequence-pair arm changed and the
gate's four named checks live in per-cell fields rather than in the banner:

* the area ratio is reported PER STRATEGY ARM as well as overall, so a
  freeform arm that must be bit-identical is visibly bit-identical and the
  sequence-pair arm's movement is not diluted by it;
* ``wall_overshoot_s`` -- audit.py has already subtracted each cell's own
  allowance (``RACE_COMPLETION_GRACE_S`` = 6 s for a cell whose islands
  resolve above one, the serial grace otherwise), so ANY positive value is a
  cell over its allowance, not merely a slow one;
* ``compact_seed_status`` / ``compact_seed_wall_time_s`` per sequence-pair
  cell, which is the only direct evidence L2 changed anything;
* ``islands_requested`` / ``islands_completed`` / ``islands_refused``, which
  is the only direct evidence L1 ran at all;
* peak RSS if the rows carry it under any ``*rss*`` key -- they do not today,
  and the report says so rather than inventing a number.
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


def stat(row: dict, name: str) -> float | str | None:
    """Return one entry of a row's ``stats`` map, or ``None`` if absent.

    Missing is reported, never defaulted: a zero island count and no island
    count at all are opposite findings.
    """
    stats = row.get("stats")
    if not isinstance(stats, dict):
        return None
    return stats.get(name)


def gmean_ratio(keys: list, base: dict, cand: dict) -> float | None:
    logs = [
        math.log(cand[k]["area"] / base[k]["area"])
        for k in keys
        if (base[k].get("area") or 0) > 0 and (cand[k].get("area") or 0) > 0
    ]
    if not logs:
        return None
    return math.exp(sum(logs) / len(logs))


def area_report(name: str, keys: list, base: dict, cand: dict) -> None:
    ratio = gmean_ratio(keys, base, cand)
    if ratio is None:
        print(f"  {name:<14} cells 0")
        return
    moved = [
        k
        for k in keys
        if (base[k].get("area") or 0) > 0
        and (cand[k].get("area") or 0) > 0
        and abs(cand[k]["area"] / base[k]["area"] - 1.0) > 1e-9
    ]
    print(
        f"  {name:<14} cells {len(keys):>3}  gmean area ratio {ratio:.5f}"
        f"  ({(ratio - 1.0) * 100.0:+.2f} %)  moved {len(moved)}"
    )


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

    arms = sorted({key[0] for key in set(base) | set(cand)})
    print("\nstatus counts per arm")
    for arm in arms:
        b = Counter(r["status"] for k, r in base.items() if k[0] == arm)
        c = Counter(r["status"] for k, r in cand.items() if k[0] == arm)
        keys = sorted(set(b) | set(c))
        summary = "  ".join(f"{s} {b[s]}->{c[s]}" for s in keys)
        print(f"  {arm:<14} {summary}")

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
        print("geometric-mean area ratio (candidate/baseline)")
        area_report("all", both_clean, base, cand)
        for arm in arms:
            area_report(arm, [k for k in both_clean if k[0] == arm], base, cand)
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
        for ratio, key in moved[:20]:
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

    # `wall_overshoot_s` is already NET of the cell's own allowance, so the
    # interesting number is not the largest wall but the largest positive
    # residue: that is a cell that ran past budget + grace.
    print("\nwall_overshoot_s (already net of each cell's allowance)")
    for name, rows in (("baseline", base), ("candidate", cand)):
        present = {k: r["wall_overshoot_s"] for k, r in rows.items() if "wall_overshoot_s" in r}
        over = sorted(((v, k) for k, v in present.items() if v > 0.0), reverse=True)
        top = max(present.values()) if present else 0.0
        print(f"  {name:<10} rows carrying it {len(present):>3}  max {top:.3f} s  over-allowance {len(over)}")
        for value, key in over[:10]:
            print(f"    {value:.3f} s  {label(key, rows[key])}  wall {rows[key].get('attempt_wall_s', 0.0):.1f} s")

    # L1 evidence: islands only exist on the sequence-pair arm, and only the
    # candidate should carry them at all.
    print("\nislands (sequence-pair arm)")
    for name, rows in (("baseline", base), ("candidate", cand)):
        seq = {k: r for k, r in rows.items() if k[0] == "sequence-pair"}
        with_islands = {k: r for k, r in seq.items() if stat(r, "islands_requested") is not None}
        req = Counter(int(stat(r, "islands_requested") or 0) for r in with_islands.values())
        done = Counter(int(stat(r, "islands_completed") or 0) for r in with_islands.values())
        refused = Counter(int(stat(r, "islands_refused") or 0) for r in with_islands.values())
        print(
            f"  {name:<10} sequence-pair rows {len(seq)}  carrying island stats {len(with_islands)}"
        )
        print(f"    islands_requested {dict(sorted(req.items()))}")
        print(f"    islands_completed {dict(sorted(done.items()))}")
        print(f"    islands_refused   {dict(sorted(refused.items()))}")
        winners = Counter(
            int(stat(r, "winner_island_id") or 0)
            for r in with_islands.values()
            if stat(r, "winner_island_id") is not None
        )
        if winners:
            print(f"    winner_island_id  {dict(sorted(winners.items()))}")

    # L2 evidence: the compact seed's status and the wall it actually spent.
    print("\ncompact seed (sequence-pair arm)")
    for name, rows in (("baseline", base), ("candidate", cand)):
        seq = [r for k, r in rows.items() if k[0] == "sequence-pair"]
        statuses = Counter(
            str(stat(r, "compact_seed_status")) for r in seq if stat(r, "compact_seed_status") is not None
        )
        walls = [
            float(stat(r, "compact_seed_wall_time_s"))
            for r in seq
            if stat(r, "compact_seed_wall_time_s") is not None
        ]
        print(f"  {name:<10} rows carrying compact_seed_status {sum(statuses.values())} of {len(seq)}")
        print(f"    status {dict(sorted(statuses.items()))}")
        if walls:
            walls_sorted = sorted(walls)
            print(
                f"    compact_seed_wall_time_s  n {len(walls)}  max {walls_sorted[-1]:.2f}"
                f"  median {walls_sorted[len(walls_sorted) // 2]:.2f}"
                f"  mean {sum(walls) / len(walls):.2f}"
            )

    # Per-cell detail for the arm that changed, so the gate record does not
    # rest on aggregates alone.
    print("\nper sequence-pair cell: status, area, wall, islands, compact seed")
    seq_keys = sorted(k for k in set(base) | set(cand) if k[0] == "sequence-pair")
    header = (
        f"  {'cell':<46} {'base':<8} {'cand':<8} {'base area':>10} {'cand area':>10}"
        f" {'cand wall':>10} {'isl':>7} {'seed':>10} {'seed s':>7}"
    )
    print(header)
    for key in seq_keys:
        b, c = base.get(key), cand.get(key)
        name = label(key, c or b).replace("sequence-pair ", "")
        islands = "-"
        if c is not None and stat(c, "islands_requested") is not None:
            islands = (
                f"{int(stat(c, 'islands_requested'))}/"
                f"{int(stat(c, 'islands_completed') or 0)}/"
                f"{int(stat(c, 'islands_refused') or 0)}"
            )
        seed_status = "-" if c is None or stat(c, "compact_seed_status") is None else str(stat(c, "compact_seed_status"))
        seed_wall = "-" if c is None or stat(c, "compact_seed_wall_time_s") is None else f"{float(stat(c, 'compact_seed_wall_time_s')):.2f}"
        print(
            f"  {name:<46} {(b['status'] if b else '-'):<8} {(c['status'] if c else '-'):<8}"
            f" {(b.get('area') or 0.0) if b else 0.0:>10.0f} {(c.get('area') or 0.0) if c else 0.0:>10.0f}"
            f" {(c.get('build_wall_time_s') or 0.0) if c else 0.0:>10.2f} {islands:>7} {seed_status:>10} {seed_wall:>7}"
        )

    # Peak RSS: recorded only if the rows carry it. `strategy_race` measures
    # `process_peak_rss_kib` for RACED children; the explicit sequence-pair arm
    # audit.py runs is not raced, so nothing writes it here. Report the gap.
    rss_keys = sorted(
        {
            name
            for rows in (base, cand)
            for r in rows.values()
            for name in (r.get("stats") or {})
            if "rss" in name.lower()
        }
        | {name for rows in (base, cand) for r in rows.values() for name in r if "rss" in name.lower()}
    )
    print("\npeak RSS")
    if not rss_keys:
        print("  no *rss* key in either file: audit.py records none for the explicit")
        print("  sequence-pair arm (strategy_race._peak_rss_kib covers RACED children only)")
    else:
        for name in rss_keys:
            values = [
                float(v)
                for rows in (base, cand)
                for r in rows.values()
                for k, v in {**(r.get("stats") or {}), **r}.items()
                if k == name and isinstance(v, (int, float))
            ]
            if values:
                print(f"  {name}: max {max(values):.0f}  n {len(values)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
