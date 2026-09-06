"""Regenerate every derived number in `gate.md` from the committed JSONL.

    uv run python analyze.py > analysis.txt

`analysis.txt` is authoritative; `gate.md` quotes it.  What `judge.py` prints
per round, this prints across rounds -- in particular the SAME-ARM control
(baseline round i against baseline round j, and candidate against candidate),
without which none of the routing-time ratios can be read: the corpus routing
metric's own run-to-run spread turns out to be larger than the effect under
test.
"""

from __future__ import annotations

import glob
import json
import math
import os
import re
import statistics
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROUNDS = (1, 2, 3)
#: `audit.py` emits no ``route_all_s`` -- that tally lives only in
#: `scripts/route_profile.py`, which only `prof_harness.py` installs.  The
#: corpus stand-in is the wall `freeform.py` measures around the detailed route
#: that contains the ``_route_all`` call arm B reorders.
ROUTE = "detailed_route_time_s"


def load(path: Path) -> dict[tuple[str, str, int], dict]:
    rows: dict[tuple[str, str, int], dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            rows[(row["strategy"], row["url_id"], row["spec_index"])] = row
    return rows


def stat(row: dict, name: str) -> float | None:
    values = row.get("stats") or {}
    if name not in values:
        return None
    try:
        return float(values[name])
    except (TypeError, ValueError):
        return None


def geomean(values: list[float]) -> float:
    return math.exp(sum(math.log(v) for v in values) / len(values))


def area_ratios(x: dict, y: dict, arm: str) -> list[tuple[float, tuple]]:
    out = []
    for key in sorted(set(x) & set(y)):
        if key[0] != arm or x[key]["status"] != "CLEAN" or y[key]["status"] != "CLEAN":
            continue
        a, b = x[key].get("area") or 0.0, y[key].get("area") or 0.0
        if a > 0 and b > 0:
            out.append((b / a, key))
    return out


def route_ratios(x: dict, y: dict, floor: float = 0.0) -> list[tuple[float, tuple, float, float]]:
    out = []
    for key in sorted(set(x) & set(y)):
        if key[0] != "freeform":
            continue
        a, b = stat(x[key], ROUTE), stat(y[key], ROUTE)
        if a is not None and b is not None and a > floor and b > 0:
            out.append((b / a, key, a, b))
    return out


def name(key: tuple) -> str:
    return f"{key[1]}[{key[2]}]"


def main() -> None:
    base = {r: load(HERE / f"baseline-round{r}.jsonl") for r in ROUNDS}
    cand = {r: load(HERE / f"candidate-round{r}.jsonl") for r in ROUNDS}
    print("commits: baseline", next(iter(base[1].values()))["commit"][:8], end="  ")
    print("candidate", next(iter(cand[1].values()))["commit"][:8])

    print("\n== STATUS COUNTS ==")
    for r in ROUNDS:
        def counts(rows: dict) -> str:
            seen: dict[str, int] = {}
            for row in rows.values():
                seen[row["status"]] = seen.get(row["status"], 0) + 1
            return "  ".join(f"{k} {v}" for k, v in sorted(seen.items()))
        print(f" round{r}  baseline: {counts(base[r]):<24} candidate: {counts(cand[r])}")

    print("\n== DIFFERING CELLS (per round) ==")
    for r in ROUNDS:
        diff = [k for k in sorted(set(base[r]) & set(cand[r]))
                if base[r][k]["status"] != cand[r][k]["status"]]
        print(f" round{r}: {len(diff)}")
        for key in diff:
            print(f"   {key[0]} {name(key)}  {base[r][key]['status']} -> {cand[r][key]['status']}")

    every = set.intersection(*(set(base[r]) for r in ROUNDS), *(set(cand[r]) for r in ROUNDS))
    reg = [k for k in sorted(every)
           if all(base[r][k]["status"] == "CLEAN" for r in ROUNDS)
           and all(cand[r][k]["status"] != "CLEAN" for r in ROUNDS)]
    print(f"\nREGRESSIONS (CLEAN in all 3 baseline rounds, non-CLEAN in all 3 candidate): {len(reg)}")
    for key in reg:
        print(f"   {key[0]} {name(key)}")
    for label, side in (("candidate", cand), ("baseline", base)):
        bad = [(r, k) for r in ROUNDS for k in side[r] if side[r][k]["status"] in {"INVALID", "CRASH"}]
        print(f"INVALID/CRASH rows, {label}: {len(bad)}  {[(r, name(k)) for r, k in bad]}")

    print("\n== wall_overshoot_s ==")
    for r in ROUNDS:
        for label, side in (("baseline", base[r]), ("candidate", cand[r])):
            v = [float(x["wall_overshoot_s"]) for x in side.values() if "wall_overshoot_s" in x]
            print(f" round{r} {label:<10} rows {len(v):>3}  max {max(v):.3f} s"
                  f"  over-allowance {sum(1 for y in v if y > 0.0)}")

    for arm in ("freeform", "sequence-pair"):
        print(f"\n== AREA, {arm} -- geomean ratio ==")
        print(" cross (candidate/baseline, the gate number):")
        for r in ROUNDS:
            rs = area_ratios(base[r], cand[r], arm)
            g = geomean([x[0] for x in rs])
            print(f"   round{r}: n {len(rs):>3}  gmean {g:.5f} ({(g - 1) * 100:+.2f} %)"
                  f"  moved {sum(1 for x in rs if abs(x[0] - 1) > 1e-9)}"
                  f"  worse>5% {sum(1 for x in rs if x[0] > 1.05)}"
                  f"  better>5% {sum(1 for x in rs if x[0] < 0.95)}")
        print(" SAME-ARM control (round i against round j on ONE tree):")
        for a, b in ((1, 2), (2, 3), (1, 3)):
            for label, side in (("baseline", base), ("candidate", cand)):
                rs = area_ratios(side[a], side[b], arm)
                g = geomean([x[0] for x in rs])
                print(f"   {label:<10} r{a}->r{b}: n {len(rs):>3}  gmean {g:.5f} ({(g - 1) * 100:+.2f} %)"
                      f"  worse>5% {sum(1 for x in rs if x[0] > 1.05)}")
        print(" cells whose area moved, cross, per round:")
        for r in ROUNDS:
            for ratio, key in sorted(area_ratios(base[r], cand[r], arm),
                                     key=lambda p: -abs(math.log(p[0]))):
                if abs(ratio - 1) > 1e-9:
                    print(f"   r{r} {ratio:.4f}  {name(key)}"
                          f"  {base[r][key]['area']:.0f} -> {cand[r][key]['area']:.0f}")
        worse3 = []
        for key in sorted(k for k in every if k[0] == arm):
            rs = []
            for r in ROUNDS:
                a, b = base[r][key].get("area") or 0.0, cand[r][key].get("area") or 0.0
                if base[r][key]["status"] != "CLEAN" or cand[r][key]["status"] != "CLEAN" or a <= 0 or b <= 0:
                    rs = []
                    break
                rs.append(b / a)
            if rs and all(x > 1.05 for x in rs):
                worse3.append((key, rs))
        print(f" cells >5 % worse in ALL THREE rounds: {len(worse3)}")
        for key, rs in worse3:
            print(f"   {name(key)}  ratios {['%.4f' % x for x in rs]}")

    print(f"\n== FREEFORM ROUTING TIME ({ROUTE}; route_all_s is absent from audit rows) ==")
    print(" cross (candidate/baseline), all 36 freeform cells:")
    for r in ROUNDS:
        rs = route_ratios(base[r], cand[r])
        g = geomean([x[0] for x in rs])
        print(f"   round{r}: n {len(rs)}  gmean {g:.4f} ({(g - 1) * 100:+.2f} %)"
              f"  faster {sum(1 for x in rs if x[0] < 1.0)}"
              f"  slower>10% {sum(1 for x in rs if x[0] > 1.10)}"
              f"  total {sum(x[2] for x in rs):.2f} -> {sum(x[3] for x in rs):.2f} s"
              f" ({(sum(x[3] for x in rs) / sum(x[2] for x in rs) - 1) * 100:+.1f} %)")
    print(" SAME-ARM control on the SAME metric (this is the noise floor):")
    for a, b in ((1, 2), (2, 3), (1, 3)):
        for label, side in (("baseline", base), ("candidate", cand)):
            rs = route_ratios(side[a], side[b])
            g = geomean([x[0] for x in rs])
            print(f"   {label:<10} r{a}->r{b}: gmean {g:.4f} ({(g - 1) * 100:+.2f} %)")
    print(" cross, restricted to cells whose BASELINE routing time is >= 0.5 s:")
    for r in ROUNDS:
        rs = route_ratios(base[r], cand[r], 0.5)
        g = geomean([x[0] for x in rs])
        print(f"   round{r}: n {len(rs)}  gmean {g:.4f} ({(g - 1) * 100:+.2f} %)"
              f"  faster {sum(1 for x in rs if x[0] < 1.0)}")
    print(" same-arm control at that same >= 0.5 s floor:")
    for a, b in ((1, 2), (2, 3), (1, 3)):
        for label, side in (("baseline", base), ("candidate", cand)):
            rs = route_ratios(side[a], side[b], 0.5)
            g = geomean([x[0] for x in rs])
            print(f"   {label:<10} r{a}->r{b}: gmean {g:.4f} ({(g - 1) * 100:+.2f} %)")

    print("\n median-of-three-rounds per cell, then geomean (round noise removed):")
    med = []
    for key in sorted(k for k in every if k[0] == "freeform"):
        b = [stat(base[r][key], ROUTE) for r in ROUNDS]
        c = [stat(cand[r][key], ROUTE) for r in ROUNDS]
        if all(x is not None and x > 0 for x in b + c):
            med.append((statistics.median(c) / statistics.median(b), key,
                        statistics.median(b), statistics.median(c)))
    g = geomean([x[0] for x in med])
    print(f"   all cells: n {len(med)}  gmean {g:.4f} ({(g - 1) * 100:+.2f} %)"
          f"  faster {sum(1 for x in med if x[0] < 1.0)}"
          f"  slower>10% {sum(1 for x in med if x[0] > 1.10)}")
    big = [x for x in med if x[2] >= 0.5]
    gb = geomean([x[0] for x in big])
    print(f"   median baseline >= 0.5 s: n {len(big)}  gmean {gb:.4f} ({(gb - 1) * 100:+.2f} %)"
          f"  faster {sum(1 for x in big if x[0] < 1.0)}")
    for ratio, key, b, c in sorted(big):
        print(f"     {ratio:.3f}  {name(key)}  {b:.2f} -> {c:.2f} s")
    print("   per-round slower>10 % lists:")
    for r in ROUNDS:
        rs = sorted((x for x in route_ratios(base[r], cand[r]) if x[0] > 1.10), reverse=True)
        print(f"     round{r} ({len(rs)}): " + ", ".join(f"{name(k)} {q:.2f}x" for q, k, _, _ in rs))

    print("\n== LARGE URLS (prof_harness, freeform, 60 s, 2 reps per side) ==")
    print(f" {'cell/policy':<26} {'rep':>3} {'side':<5} {'verdict':<12} {'wall s':>8}"
          f" {'route_all s':>12} {'rounds':>7} {'area':>9} {'belt':>7}")
    for path in sorted(glob.glob(str(HERE / "runs-large" / "*.json"))):
        tag = os.path.basename(path)[:-5]
        m = re.match(r"(.+)-(all-products|no-proliferator)-(base|cand)-r(\d)$", tag)
        assert m is not None, tag
        row = json.loads(Path(path).read_text(encoding="utf-8"))
        stats = row.get("stats") or {}
        verdict = "OK" if row["verdict"] == "OK" else "REFUSED"
        print(f" {m[1] + '/' + m[2]:<26} {m[4]:>3} {m[3]:<5} {verdict:<12} {row['wall_s']:>8.2f}"
              f" {row['route_all_s']:>12.2f} {row['rounds']:>7} {str(row['area'] or '-'):>9}"
              f" {str(stats.get('belt_tiles') or '-'):>7}")

    print("\n== FLAKE RE-RUNS: sequence-pair universe-matrix, 3x per tree ==")
    for side in ("base", "cand"):
        for i in ROUNDS:
            path = HERE / f"flake-{side}-um-round{i}.jsonl"
            for row in sorted((json.loads(x) for x in path.read_text().splitlines() if x.strip()),
                              key=lambda x: x["spec_index"]):
                print(f" {side} run{i}  um[{row['spec_index']}/{row['spec_label']:<16}]"
                      f"  {row['status']:<8} area {str(row.get('area') or '-'):>9}")


if __name__ == "__main__":
    main()
