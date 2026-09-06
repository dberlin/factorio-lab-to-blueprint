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
INVALID or CRASH row in the candidate with its detail; the geometric-mean
area ratio over the cells clean in both, per arm; and the budget-discipline
columns.

Copied unchanged from the 2026-09-06 speedups-2 batch-3 gate for the
2026-09-06 `exp-pressure` arm-B gate (router net order by cut pressure,
``FLAB2BP_PRESSURE_ORDER=1``), plus ONE added section: the freeform routing
time, below.

**On ``route_all_s``.** The exp-pressure README's ``route_all`` seconds come
from ``scripts/route_profile.py``'s tally (``tally.t["route_all"]``, surfaced by
``prof_harness.py`` as ``route_all_s``).  That tally exists only in the
profiling harness; `audit.py` never emits it, on either tree -- verified: zero
rows in either side's JSONL carry the key.  The corpus stand-in is
``detailed_route_time_s``, which `freeform.py` measures around exactly the
detailed-routing call that contains the ``_route_all`` invocation arm B
reorders.  It is reported here BOTH raw and normalised per ALNS evaluation,
because freeform runs to a wall-clock budget: a faster router does not
necessarily spend less total time routing, it attempts more candidates in the
same 30 s.  The raw ratio is what the gate rule reads; the normalised ratio is
what says whether a single route got cheaper.

Adapted from batch 2's copy for the 2026-09-06 speedups-2 THIRD batch (L4
certify only a would-be incumbent, L5 size the next candidate by the median).
Only the FREEFORM arm changed, so the islands / compact-seed sections of the
batch 2 copy are gone and these are here instead:

* ``wall_overshoot_s`` -- THE check that matters for this batch, because L5
  relaxes what must fit before a candidate starts. `audit.py` has already
  subtracted each cell's own allowance, so ANY positive value is a cell over
  its allowance, not merely a slow one. Printed per arm, with the max and the
  whole distribution, on both sides.
* per freeform cell: ``certify_skipped`` (L4's direct evidence),
  ``budget_unspent_s`` (L5's), candidates attempted (``alns_evaluations``),
  ``validation_time_s``, and "budget spent" = ``attempt_wall_s / budget``.
  ``certify_skipped`` and ``budget_unspent_s`` do not exist on the baseline
  tree; missing is printed as ``-``, never defaulted to zero.
* the area report also counts cells that got LARGER vs SMALLER, because Ruling
  D2's exactness claim for this batch is "no worse", not "identical".
"""

from __future__ import annotations

import json
import math
import sys
from collections import Counter

#: The stats the freeform budget-discipline table reads, in print order.
#: ``certify_skipped`` and ``budget_unspent_s`` are new in this batch.
BUDGET_STATS = (
    "certify_skipped",
    "budget_unspent_s",
    "alns_evaluations",
    "validation_time_s",
)


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


def stat(row: dict, name: str) -> float | None:
    """Return one numeric entry of a row's ``stats`` map, or ``None``.

    Missing is reported, never defaulted: a baseline row that carries no
    ``certify_skipped`` at all and a candidate row that skipped zero
    certifications are opposite findings.  `prof_harness` stringifies stats and
    `audit.py` does not, so both shapes are accepted.
    """
    stats = row.get("stats")
    if not isinstance(stats, dict) or name not in stats:
        return None
    try:
        return float(stats[name])
    except (TypeError, ValueError):
        return None


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
    pairs = [
        (base[k]["area"], cand[k]["area"])
        for k in keys
        if (base[k].get("area") or 0) > 0 and (cand[k].get("area") or 0) > 0
    ]
    larger = sum(1 for b, c in pairs if c > b * (1.0 + 1e-9))
    smaller = sum(1 for b, c in pairs if c < b * (1.0 - 1e-9))
    print(
        f"  {name:<14} cells {len(keys):>3}  gmean area ratio {ratio:.5f}"
        f"  ({(ratio - 1.0) * 100.0:+.2f} %)  larger {larger}  smaller {smaller}"
    )


def quantiles(values: list[float]) -> str:
    if not values:
        return "n 0"
    ordered = sorted(values)

    def q(p: float) -> float:
        return ordered[min(len(ordered) - 1, max(0, int(math.ceil(p * len(ordered))) - 1))]

    return (
        f"n {len(ordered)}  min {ordered[0]:.3f}  median {q(0.5):.3f}"
        f"  p95 {q(0.95):.3f}  max {ordered[-1]:.3f}  mean {sum(ordered) / len(ordered):.3f}"
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

    # THE check that matters for this batch. `wall_overshoot_s` is already NET
    # of the cell's own allowance, so the interesting number is not the largest
    # wall but the largest positive residue: that is a cell that ran past
    # budget + grace. L5 relaxes the start rule, so the candidate's max must not
    # exceed the baseline's.
    print("\nwall_overshoot_s (already net of each cell's allowance)")
    maxima: dict[str, float] = {}
    for name, rows in (("baseline", base), ("candidate", cand)):
        present = {k: float(r["wall_overshoot_s"]) for k, r in rows.items() if "wall_overshoot_s" in r}
        maxima[name] = max(present.values()) if present else 0.0
        over = sorted(((v, k) for k, v in present.items() if v > 0.0), reverse=True)
        print(f"  {name:<10} rows carrying it {len(present):>3}  max {maxima[name]:.3f} s  over-allowance {len(over)}")
        print(f"    distribution  {quantiles(list(present.values()))}")
        for arm in arms:
            arm_values = [v for k, v in present.items() if k[0] == arm]
            arm_max = max(arm_values) if arm_values else 0.0
            arm_over = sum(1 for v in arm_values if v > 0.0)
            print(f"    {arm:<14} max {arm_max:.3f} s  over-allowance {arm_over}  {quantiles(arm_values)}")
        for value, key in over[:10]:
            print(f"    OVER {value:.3f} s  {label(key, rows[key])}  wall {rows[key].get('attempt_wall_s', 0.0):.1f} s")
    verdict = "OK" if maxima["candidate"] <= maxima["baseline"] else "WALL-SAFETY FAIL"
    print(
        f"  wall-safety: candidate max {maxima['candidate']:.3f} s vs baseline max"
        f" {maxima['baseline']:.3f} s -> {verdict}"
    )

    # L4 / L5 evidence, per freeform cell. The baseline tree carries neither
    # `certify_skipped` nor `budget_unspent_s`; those columns print `-` there.
    print("\nfreeform budget discipline (per cell)")
    header = (
        f"  {'cell':<44} {'side':<5} {'status':<8} {'wall s':>8} {'bud':>5} {'spent%':>7}"
        f" {'cands':>6} {'certskip':>9} {'unspent':>8} {'valid s':>8}"
    )
    print(header)
    ff_keys = sorted(k for k in set(base) | set(cand) if k[0] == "freeform")
    totals: dict[str, dict[str, list[float]]] = {
        "baseline": {name: [] for name in (*BUDGET_STATS, "spent_share", "unspent_wall")},
        "candidate": {name: [] for name in (*BUDGET_STATS, "spent_share", "unspent_wall")},
    }
    for key in ff_keys:
        for side, rows in (("base", base), ("cand", cand)):
            row = rows.get(key)
            if row is None:
                continue
            bucket = totals["baseline" if side == "base" else "candidate"]
            budget = float(row.get("budget") or 0.0)
            wall = float(row.get("attempt_wall_s") or 0.0)
            share = (wall / budget) if budget > 0 else 0.0
            bucket["spent_share"].append(share)
            if budget > 0:
                bucket["unspent_wall"].append(max(0.0, budget - wall))
            cells = []
            for name in BUDGET_STATS:
                value = stat(row, name)
                if value is not None:
                    bucket[name].append(value)
                cells.append("-" if value is None else f"{value:.3f}".rstrip("0").rstrip("."))
            name_text = label(key, row).replace("freeform ", "")
            print(
                f"  {name_text:<44} {side:<5} {row['status']:<8} {wall:>8.2f} {budget:>5.0f}"
                f" {share * 100.0:>6.1f}% {cells[2]:>6} {cells[0]:>9} {cells[1]:>8} {cells[3]:>8}"
            )
    print("\nfreeform budget discipline (arm totals)")
    for side in ("baseline", "candidate"):
        bucket = totals[side]
        def agg(name: str) -> str:
            values = bucket[name]
            if not values:
                return "absent"
            return f"sum {sum(values):.2f}  mean {sum(values) / len(values):.3f}  n {len(values)}"
        print(f"  {side}")
        print(f"    certify_skipped     {agg('certify_skipped')}")
        print(f"    budget_unspent_s    {agg('budget_unspent_s')}")
        print(f"    candidates attempted (alns_evaluations)  {agg('alns_evaluations')}")
        print(f"    validation_time_s   {agg('validation_time_s')}")
        print(f"    budget - attempt_wall_s (unspent by wall) {agg('unspent_wall')}")
        shares = bucket["spent_share"]
        if shares:
            print(
                f"    budget spent (attempt_wall/budget)  mean {sum(shares) / len(shares) * 100.0:.1f} %"
                f"  min {min(shares) * 100.0:.1f} %  max {max(shares) * 100.0:.1f} %  n {len(shares)}"
            )

    routing_report(shared, base, cand)
    return 0


def routing_report(shared: list, base: dict, cand: dict) -> None:
    """THE speed check for arm B: freeform routing seconds, candidate/baseline.

    ``route_all_s`` is looked for first and reported as absent when no row
    carries it (it never does under `audit.py`; see the module docstring).  The
    stand-in is ``detailed_route_time_s``.  Both the raw ratio and the ratio
    normalised by ``alns_evaluations`` are printed; a cell contributes only when
    both sides carry a positive value.
    """
    print("\nfreeform routing time (candidate/baseline)")
    ff = [k for k in shared if k[0] == "freeform"]
    for name in ("route_all_s", "detailed_route_time_s"):
        pairs = []
        for key in ff:
            b, c = stat(base[key], name), stat(cand[key], name)
            if b is None or c is None or b <= 0.0 or c <= 0.0:
                continue
            pairs.append((key, b, c))
        if not pairs:
            present = sum(1 for k in ff if stat(base[k], name) is not None)
            print(f"  {name}: ABSENT (baseline rows carrying it: {present} of {len(ff)})")
            continue
        ratios = [(c / b, key, b, c) for key, b, c in pairs]
        gm = math.exp(sum(math.log(r) for r, _, _, _ in ratios) / len(ratios))
        slower = sorted((r for r in ratios if r[0] > 1.10), reverse=True)
        faster = sorted(r for r in ratios if r[0] < 1.0)
        print(
            f"  {name}: cells {len(pairs)}  gmean ratio {gm:.4f}"
            f"  ({(gm - 1.0) * 100.0:+.2f} %)"
            f"  faster {len(faster)}  slower>10% {len(slower)}"
            f"  sum {sum(b for _, b, _ in pairs):.2f} -> {sum(c for _, _, c in pairs):.2f} s"
        )
        print(f"    slower by more than 10 % ({len(slower)})")
        for ratio, key, b, c in slower:
            print(f"      {ratio:.4f}  {label(key, cand[key])}  {b:.2f} -> {c:.2f} s")
        print(f"    faster ({len(faster)})")
        for ratio, key, b, c in faster:
            print(f"      {ratio:.4f}  {label(key, cand[key])}  {b:.2f} -> {c:.2f} s")

        # Per-evaluation: freeform spends a fixed wall budget, so total routing
        # seconds conflate "each route is cheaper" with "more routes attempted".
        norm = []
        for key, b, c in pairs:
            be, ce = stat(base[key], "alns_evaluations"), stat(cand[key], "alns_evaluations")
            if be and ce and be > 0 and ce > 0:
                norm.append(((c / ce) / (b / be), key))
        if norm:
            gmn = math.exp(sum(math.log(r) for r, _ in norm) / len(norm))
            print(
                f"    per alns_evaluation: cells {len(norm)}  gmean ratio {gmn:.4f}"
                f"  ({(gmn - 1.0) * 100.0:+.2f} %)"
                f"  faster {sum(1 for r, _ in norm if r < 1.0)}"
            )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
