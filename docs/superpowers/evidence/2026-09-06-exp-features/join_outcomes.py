"""Join the pre-placement feature vector to the outcomes we already paid for.

    uv run python docs/superpowers/evidence/2026-09-06-exp-features/join_outcomes.py

Reads ``features.jsonl`` (written by ``compute_features.py``) plus existing
evidence JSONL -- the batch3 and batch2 corpus gate rounds, and the large-URL
runs -- and writes ``join.tsv`` and ``analysis.txt``.  Nothing is re-run.

Deliberately no scipy: Spearman on 84 points is twenty lines of ranking, and a
throwaway experiment that adds a dependency to the project is a worse trade
than a throwaway experiment that spells out its own statistics.
"""

from __future__ import annotations

import json
import math
import statistics
import sys
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_EVIDENCE = _HERE.parent
_BATCH3 = _EVIDENCE / "2026-09-06-speedups-2-batch3"
_BATCH2 = _EVIDENCE / "2026-09-06-speedups-2-batch2"
_LARGE = _EVIDENCE / "2026-09-05-speedups-2" / "large-urls"

#: Features the analysis ranks.  Ordered size-first so the tables read as
#: "does topology beat size", which is question 4(a).
FEATURES: tuple[str, ...] = (
    "machines",
    "groups",
    "strips",
    "recipes",
    "distinct_items",
    "max_ingredients_per_strip",
    "mean_ingredients_per_strip",
    "coaters",
    "items_above_one_belt",
    "both_fed_items",
    "chain_depth",
    "max_spread",
    "sum_spread",
    "max_consumers",
    "items_with_3plus_consumers",
    "proliferator_consumers",
    "proliferator_span",
    "proliferator_spread",
    # -- experiment 5 -----------------------------------------------------
    "max_live_range",
    "sum_live_range",
    "items_live_range_ge3",
    "max_pressure",
    "max_lane_pressure",
    "sum_pressure",
    "lane_pressure_per_strip",
    "max_pressure_no_spray",
    "max_lane_pressure_no_spray",
    "proliferator_live_range",
)

#: The pair sweep is O(features^2 x thresholds^2 x points), so it runs over a
#: curated shortlist rather than all 28 columns.  These are the candidates any
#: dispatch key would actually be built from -- one per mechanism.
PAIR_FEATURES: tuple[str, ...] = (
    "machines",
    "strips",
    "distinct_items",
    "coaters",
    "items_above_one_belt",
    "chain_depth",
    "max_spread",
    "max_live_range",
    "max_pressure",
    "max_lane_pressure",
    "lane_pressure_per_strip",
)

#: The head-to-head set experiment 5 asks about: the new features against the
#: three that won experiment 1, reported side by side in every table.
HEADLINE: tuple[str, ...] = (
    "strips",
    "distinct_items",
    "items_above_one_belt",
    "max_spread",
    "max_live_range",
    "sum_live_range",
    "items_live_range_ge3",
    "max_pressure",
    "max_lane_pressure",
    "lane_pressure_per_strip",
    "max_pressure_no_spray",
    "max_lane_pressure_no_spray",
)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def refusal_class(text: str) -> str:
    """Bucket a refusal string into the failure classes the evidence shows.

    These are the four distinct things that go wrong, and they want different
    dispatch responses -- which is the whole reason the orchestrator wants a
    class and not just a boolean.
    """
    if not text or text == "OK":
        return "clean"
    lowered = text.lower()
    if "was ever produced at any candidate height" in lowered:
        return "pack-never-produced"
    if "could be wired at any candidate height" in lowered:
        return "pack-unwirable"
    if "rejected by our own validator" in lowered or "flow.belt_capacity" in lowered:
        if "sequence islands refused" in lowered:
            return "island-deadline+belt-capacity"
        return "validator-belt-capacity"
    if "sequence islands refused" in lowered:
        return "island-deadline"
    return "other"


def _spearman(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Rank correlation with tie-averaged ranks; ``None`` when undefined."""
    if len(xs) < 3:
        return None

    def ranks(values: Sequence[float]) -> list[float]:
        order = sorted(range(len(values)), key=lambda i: values[i])
        out = [0.0] * len(values)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
                j += 1
            mean_rank = (i + j) / 2 + 1
            for k in range(i, j + 1):
                out[order[k]] = mean_rank
            i = j + 1
        return out

    rx, ry = ranks(xs), ranks(ys)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    dx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    dy = math.sqrt(sum((b - my) ** 2 for b in ry))
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy)


def _load_features() -> dict[tuple[str, str], dict[str, Any]]:
    rows = _read_jsonl(_HERE / "features.jsonl")
    return {(row["url_id"], row["spec_label"]): row for row in rows}


def _corpus_points(features: dict[tuple[str, str], dict[str, Any]]) -> list[dict[str, Any]]:
    """One point per (corpus spec, strategy), pooling three rounds per batch."""
    rounds: dict[str, list[list[dict[str, Any]]]] = {
        "batch3": [_read_jsonl(_BATCH3 / f"candidate-round{n}.jsonl") for n in (1, 2, 3)],
        "batch2": [_read_jsonl(_BATCH2 / f"candidate-round{n}.jsonl") for n in (1, 2, 3)],
    }
    pooled: dict[tuple[str, str, str], dict[str, list[Any]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for batch, batch_rounds in rounds.items():
        for round_rows in batch_rounds:
            for row in round_rows:
                key = (row["url_id"], row["spec_label"], row["strategy"])
                bucket = pooled[key]
                bucket[f"{batch}_status"].append(row["status"])
                if row["status"] == "CLEAN":
                    bucket[f"{batch}_wall"].append(row["seconds"])
                    bucket[f"{batch}_area"].append(row["area"])
                bucket[f"{batch}_overshoot"].append(row.get("wall_overshoot_s", 0.0) or 0.0)
                bucket[f"{batch}_detail"].append(row.get("detail", ""))
                stats = row.get("stats") or {}
                bucket[f"{batch}_alns"].append(float(stats.get("alns_evaluations", 0.0)))
                bucket[f"{batch}_unspent"].append(float(stats.get("budget_unspent_s", 0.0)))
                bucket[f"{batch}_belt_tiles"].append(float(stats.get("belt_tiles", 0.0)))
                bucket[f"{batch}_direct"].append(float(stats.get("direct_inserts", 0.0)))
                bucket[f"{batch}_certify"].append(float(stats.get("certify_skipped", 0.0)))

    points: list[dict[str, Any]] = []
    for (url_id, spec_label, strategy), bucket in sorted(pooled.items()):
        feature = features.get((url_id, spec_label))
        if feature is None:
            continue
        statuses = bucket["batch3_status"]
        refused_all = all(s != "CLEAN" for s in statuses)
        point: dict[str, Any] = {
            "source": "corpus",
            "url_id": url_id,
            "spec_label": spec_label,
            "strategy": strategy,
            "budget_s": 30.0,
            "rounds": len(statuses),
            "status_batch3": "/".join(statuses),
            "status_batch2": "/".join(bucket["batch2_status"]),
            "clean_rounds": sum(1 for s in statuses if s == "CLEAN"),
            "refused_all_rounds": int(refused_all),
            "any_refusal": int(any(s != "CLEAN" for s in statuses + bucket["batch2_status"])),
            "median_wall_s": (
                round(statistics.median(bucket["batch3_wall"]), 3)
                if bucket["batch3_wall"]
                else None
            ),
            "median_wall_batch2_s": (
                round(statistics.median(bucket["batch2_wall"]), 3)
                if bucket["batch2_wall"]
                else None
            ),
            "median_area": (
                statistics.median(bucket["batch3_area"]) if bucket["batch3_area"] else None
            ),
            "median_overshoot_s": round(statistics.median(bucket["batch3_overshoot"]), 3),
            "median_alns_evaluations": statistics.median(bucket["batch3_alns"]),
            "median_budget_unspent_s": round(statistics.median(bucket["batch3_unspent"]), 3),
            "median_belt_tiles": statistics.median(bucket["batch3_belt_tiles"]),
            "median_direct_inserts": statistics.median(bucket["batch3_direct"]),
            "refusal_class": refusal_class(next((d for d in bucket["batch3_detail"] if d), "")),
        }
        point.update({name: feature[name] for name in FEATURES})
        points.append(point)
    return points


def _large_points(features: dict[tuple[str, str], dict[str, Any]]) -> list[dict[str, Any]]:
    """One point per (large spec, strategy), pooling the 60 s and 100 s runs.

    ``before.jsonl`` is the second point in time: the same twelve arms at an
    older commit.  An arm counts as refused-in-all-rounds only when it refused
    at both budgets in the ``after`` run, which is the strictest reading the
    data supports.
    """
    after = _read_jsonl(_LARGE / "after.jsonl")
    before = _read_jsonl(_LARGE / "before.jsonl")
    pooled: dict[tuple[str, str, str], dict[str, list[Any]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for tag, rows in (("after", after), ("before", before)):
        for row in rows:
            key = (row["label"], row["policy"], row["strategy"])
            bucket = pooled[key]
            verdict = row.get("verdict") or ""
            bucket[f"{tag}_verdict"].append("OK" if verdict == "OK" else "REFUSED")
            bucket[f"{tag}_class"].append(refusal_class(verdict))
            bucket[f"{tag}_wall"].append(row["wall_s"])
            if verdict == "OK" and row.get("area"):
                bucket[f"{tag}_area"].append(row["area"])
            stats = row.get("stats") or {}
            bucket[f"{tag}_alns"].append(float(stats.get("alns_evaluations", 0.0)))
            bucket[f"{tag}_belt_tiles"].append(float(stats.get("belt_tiles", 0.0)))

    points: list[dict[str, Any]] = []
    for (url_id, spec_label, strategy), bucket in sorted(pooled.items()):
        feature = features.get((url_id, spec_label))
        if feature is None:
            continue
        verdicts = bucket["after_verdict"]
        classes = [c for c in bucket["after_class"] if c != "clean"]
        point: dict[str, Any] = {
            "source": "large",
            "url_id": url_id,
            "spec_label": spec_label,
            "strategy": strategy,
            "budget_s": 80.0,  # pooled 60 s and 100 s
            "rounds": len(verdicts),
            "status_batch3": "/".join("CLEAN" if v == "OK" else "REFUSED" for v in verdicts),
            "status_batch2": "/".join(
                "CLEAN" if v == "OK" else "REFUSED" for v in bucket["before_verdict"]
            ),
            "clean_rounds": sum(1 for v in verdicts if v == "OK"),
            "refused_all_rounds": int(all(v != "OK" for v in verdicts)),
            "any_refusal": int(any(v != "OK" for v in verdicts + bucket["before_verdict"])),
            "median_wall_s": round(statistics.median(bucket["after_wall"]), 3),
            "median_wall_batch2_s": round(statistics.median(bucket["before_wall"]), 3),
            "median_area": (
                statistics.median(bucket["after_area"]) if bucket["after_area"] else None
            ),
            "median_overshoot_s": None,
            "median_alns_evaluations": statistics.median(bucket["after_alns"]),
            "median_budget_unspent_s": None,
            "median_belt_tiles": statistics.median(bucket["after_belt_tiles"]),
            "median_direct_inserts": None,
            "refusal_class": classes[0] if classes else "clean",
        }
        point.update({name: feature[name] for name in FEATURES})
        points.append(point)
    return points


def _rank_table(
    points: Sequence[dict[str, Any]],
    target: str,
    *,
    title: str,
    predicate: Any = None,
) -> list[str]:
    rows = [p for p in points if p.get(target) is not None]
    if predicate is not None:
        rows = [p for p in rows if predicate(p)]
    lines = [f"{title}  (n={len(rows)})", f"{'feature':<30}{'spearman':>10}"]
    scored: list[tuple[float, str]] = []
    for name in FEATURES:
        rho = _spearman([float(p[name]) for p in rows], [float(p[target]) for p in rows])
        if rho is not None:
            scored.append((rho, name))
    if not scored:
        lines.append("  (undefined: the target is constant across every point)")
    for rho, name in sorted(scored, key=lambda pair: -abs(pair[0])):
        lines.append(f"{name:<30}{rho:>+10.3f}")
    lines.append("")
    return lines


def _separation_table(points: Sequence[dict[str, Any]], *, title: str) -> list[str]:
    """Best single-feature threshold for "refused in every round".

    Precision/recall are reported for the rule "predict REFUSED when feature >=
    t", sweeping t over the observed values and keeping the best F1.  On this
    many points a sweep is exhaustive, so there is no search to get wrong --
    the honest worry is overfitting, which the README states rather than hides.
    """
    labels = [p["refused_all_rounds"] for p in points]
    positives = sum(labels)
    lines = [
        f"{title}  (n={len(points)}, refused-in-all-rounds={positives})",
        f"{'feature':<30}{'>= t':>8}{'prec':>8}{'rec':>8}{'F1':>8}{'TP':>5}{'FP':>5}{'FN':>5}",
    ]
    scored: list[tuple[float, str, float, float, float, int, int, int]] = []
    for name in FEATURES:
        best: tuple[float, float, float, float, int, int, int] | None = None
        for t in _nontrivial_thresholds(points, name):
            tp = sum(1 for p, y in zip(points, labels, strict=True) if float(p[name]) >= t and y)
            fp = sum(
                1 for p, y in zip(points, labels, strict=True) if float(p[name]) >= t and not y
            )
            fn = positives - tp
            if tp == 0:
                continue
            precision = tp / (tp + fp)
            recall = tp / positives
            f1 = 2 * precision * recall / (precision + recall)
            if best is None or f1 > best[0]:
                best = (f1, t, precision, recall, tp, fp, fn)
        if best is not None:
            f1, t, precision, recall, tp, fp, fn = best
            scored.append((f1, name, t, precision, recall, tp, fp, fn))
    for f1, name, t, precision, recall, tp, fp, fn in sorted(scored, key=lambda s: -s[0]):
        lines.append(
            f"{name:<30}{t:>8.3g}{precision:>8.2f}{recall:>8.2f}{f1:>8.2f}{tp:>5}{fp:>5}{fn:>5}"
        )
    lines.append("")
    return lines


def _nontrivial_thresholds(points: Sequence[dict[str, Any]], name: str) -> list[float]:
    """Candidate thresholds that actually exclude something.

    The minimum observed value is dropped: ``coaters >= 0`` is true of every
    point, so a pair rule containing it is really a single-feature rule wearing
    a second name, and the first version of this table was full of them.
    """
    values = sorted({float(p[name]) for p in points})
    return values[1:]


def _pair_table(points: Sequence[dict[str, Any]], *, title: str, top: int = 8) -> list[str]:
    """Best AND-of-two-thresholds rule, over every feature pair."""
    labels = [p["refused_all_rounds"] for p in points]
    positives = sum(labels)
    scored: list[tuple[float, str, float, str, float, float, float, int, int]] = []
    for i, a in enumerate(PAIR_FEATURES):
        for b in PAIR_FEATURES[i + 1 :]:
            for ta in _nontrivial_thresholds(points, a):
                for tb in _nontrivial_thresholds(points, b):
                    tp = fp = 0
                    for p, y in zip(points, labels, strict=True):
                        if float(p[a]) >= ta and float(p[b]) >= tb:
                            if y:
                                tp += 1
                            else:
                                fp += 1
                    if tp == 0:
                        continue
                    precision = tp / (tp + fp)
                    recall = tp / positives
                    f1 = 2 * precision * recall / (precision + recall)
                    scored.append((f1, a, ta, b, tb, precision, recall, tp, fp))
    lines = [
        f"{title}  (n={len(points)}, refused-in-all-rounds={positives})",
        f"{'rule':<62}{'prec':>7}{'rec':>7}{'F1':>7}{'TP':>5}{'FP':>5}",
    ]
    seen: set[tuple[str, str]] = set()
    for f1, a, ta, b, tb, precision, recall, tp, fp in sorted(scored, key=lambda s: -s[0]):
        if (a, b) in seen:
            continue
        seen.add((a, b))
        rule = f"{a} >= {ta:g} AND {b} >= {tb:g}"
        lines.append(f"{rule:<62}{precision:>7.2f}{recall:>7.2f}{f1:>7.2f}{tp:>5}{fp:>5}")
        if len(seen) >= top:
            break
    lines.append("")
    return lines


def _who_wins(points: Sequence[dict[str, Any]]) -> list[str]:
    """For specs BOTH arms build: what predicts which arm packs smaller."""
    by_spec: dict[tuple[str, str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    for p in points:
        by_spec[(p["source"], p["url_id"], p["spec_label"])][p["strategy"]] = p

    rows: list[dict[str, Any]] = []
    for (source, url_id, spec_label), arms in sorted(by_spec.items()):
        ff, sp = arms.get("freeform"), arms.get("sequence-pair")
        if not ff or not sp or ff["median_area"] is None or sp["median_area"] is None:
            continue
        ratio = ff["median_area"] / sp["median_area"]
        row = {
            "source": source,
            "url_id": url_id,
            "spec_label": spec_label,
            "ff_area": ff["median_area"],
            "sp_area": sp["median_area"],
            "log_area_ratio": math.log(ratio),
            "winner": "freeform" if ratio < 1 else ("tie" if ratio == 1 else "sequence-pair"),
        }
        row.update({name: ff[name] for name in FEATURES})
        rows.append(row)

    lines = [f"WHO WINS ON AREA -- specs both arms build  (n={len(rows)})", ""]
    lines.append(
        f"{'spec':<44}{'ff area':>10}{'sp area':>10}{'ff/sp':>8}{'strips':>8}"
        f"{'coaters':>9}{'maxspr':>8}"
    )
    for row in sorted(rows, key=lambda r: r["log_area_ratio"]):
        spec = f"{row['url_id']}/{row['spec_label']}"
        lines.append(
            f"{spec:<44}{row['ff_area']:>10.0f}{row['sp_area']:>10.0f}"
            f"{math.exp(row['log_area_ratio']):>8.3f}{row['strips']:>8}"
            f"{row['coaters']:>9}{row['max_spread']:>8}"
        )
    lines.append("")
    lines.append(f"{'feature':<30}{'spearman vs log(ff/sp)':>24}")
    scored = []
    for name in FEATURES:
        rho = _spearman([float(r[name]) for r in rows], [float(r["log_area_ratio"]) for r in rows])
        if rho is not None:
            scored.append((rho, name))
    for rho, name in sorted(scored, key=lambda pair: -abs(pair[0])):
        lines.append(f"{name:<30}{rho:>+24.3f}")
    lines.append("")
    lines.append("Positive rho: the bigger the feature, the more freeform's pack loses.")
    lines.append("")

    # Size dominates that ranking, so cross-tabulate coating against size: the
    # batch-1 claim was "freeform wins tiny AND coated", which is two effects
    # a single rank correlation cannot separate.
    lines.append("MEAN ff/sp AREA RATIO, coating x size  (freeform wins below 1.00)")
    lines.append("")
    lines.append(f"{'':<18}{'coaters = 0':>16}{'coaters > 0':>16}")
    for size_label, keep in (
        ("strips <= 6", lambda r: r["strips"] <= 6),
        ("strips > 6", lambda r: r["strips"] > 6),
    ):
        cells = []
        for coated in (False, True):
            group = [
                math.exp(r["log_area_ratio"])
                for r in rows
                if keep(r) and (r["coaters"] > 0) == coated
            ]
            cells.append(f"{statistics.fmean(group):.3f} (n={len(group)})" if group else "-")
        lines.append(f"{size_label:<18}{cells[0]:>16}{cells[1]:>16}")
    lines.append("")

    # Same question asked of the experiment-5 features: does either kind of
    # pressure pick the arm any better than coating does?
    lines.append("MEAN ff/sp AREA RATIO by pressure tercile (freeform wins below 1.00)")
    lines.append("")
    for name in ("max_lane_pressure", "lane_pressure_per_strip", "max_live_range"):
        values = sorted(float(r[name]) for r in rows)
        lo = values[len(values) // 3]
        hi = values[2 * len(values) // 3]
        cells = []
        for label, low, high in (
            (f"< {lo:g}", -math.inf, lo),
            (f"{lo:g}..{hi:g}", lo, hi),
            (f">= {hi:g}", hi, math.inf),
        ):
            group = [math.exp(r["log_area_ratio"]) for r in rows if low <= float(r[name]) < high]
            cells.append(
                f"{label}: {statistics.fmean(group):.3f} (n={len(group)})"
                if group
                else f"{label}: -"
            )
        lines.append(f"{name:<26}" + "   ".join(cells))
    lines.append("")
    return lines


def _policy_invariance(features: dict[tuple[str, str], dict[str, Any]]) -> list[str]:
    """Which features move when only the PROLIFERATION POLICY changes.

    This is the structural fact that decides question 4(a), and it is not a
    statistic -- it is a property of the definitions.  A candidate policy
    changes machine counts (spray means fewer machines for the same output) but
    it does not change the recipe graph: the same recipes, the same
    ingredients, the same depths.  So every graph-shape feature is IDENTICAL
    across a URL's three candidates, while machines, strips and coaters are
    not.

    On the large URLs the refusal boundary runs exactly along the policy --
    ``belt3/all-products`` builds and ``belt3/no-proliferator`` does not, same
    URL -- so a purely topological feature is definitionally blind to the only
    thing that separates them there.
    """
    by_url: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for (url_id, spec_label), row in features.items():
        by_url[url_id][spec_label] = row

    lines = ["FEATURE VARIANCE ACROSS CANDIDATE POLICIES (same URL)", ""]
    lines.append(f"{'feature':<30}{'URLs where it moves':>22}{'of':>4}")
    total = 0
    moved: dict[str, int] = dict.fromkeys(FEATURES, 0)
    for _url_id, policies in sorted(by_url.items()):
        if len(policies) < 2:
            continue
        total += 1
        for name in FEATURES:
            if len({policies[label][name] for label in policies}) > 1:
                moved[name] += 1
    for name, count in sorted(moved.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"{name:<30}{count:>22}{total:>4}")
    lines.append("")
    lines.append("Zero means the feature cannot distinguish a spec that builds from one")
    lines.append("that refuses when the two differ only by proliferation policy.")
    lines.append("")
    return lines


def _large_detail(points: Sequence[dict[str, Any]]) -> list[str]:
    """The twelve large-URL arms in full -- this is where the refusals are."""
    lines = ["LARGE-URL ARMS IN FULL  (the 6 spec x 2 strategy points)", ""]
    lines.append(
        f"{'spec':<28}{'arm':<15}{'60/100s':<20}{'machines':>9}{'strips':>7}"
        f"{'items>belt':>11}{'maxspr':>7}{'depth':>6}{'wall':>7}"
    )
    for p in sorted(points, key=lambda q: (q["url_id"], q["spec_label"], q["strategy"])):
        spec = f"{p['url_id']}/{p['spec_label']}"
        lines.append(
            f"{spec:<28}{p['strategy']:<15}{p['status_batch3']:<20}{p['machines']:>9}"
            f"{p['strips']:>7}{p['items_above_one_belt']:>11}{p['max_spread']:>7}"
            f"{p['chain_depth']:>6}{p['median_wall_s']:>7.1f}"
        )
    lines.append("")
    return lines


def _headline_table(
    points: Sequence[dict[str, Any]],
    *,
    corpus: Sequence[dict[str, Any]],
    large: Sequence[dict[str, Any]],
) -> list[str]:
    """Experiment 5's one table: every headline feature on every question.

    Reading a dozen separate ranked lists to answer "does pressure beat strips"
    is how a comparison gets fudged, so all four columns sit side by side and
    the answer is a column scan.
    """
    freeform = [p for p in corpus if p["strategy"] == "freeform"]
    labels = [p["refused_all_rounds"] for p in points]
    positives = sum(labels)

    def best_f1(rows: Sequence[dict[str, Any]], name: str) -> tuple[float, float, float, float]:
        ys = [p["refused_all_rounds"] for p in rows]
        pos = sum(ys)
        best = (0.0, 0.0, 0.0, 0.0)
        if pos == 0:
            return best
        for t in _nontrivial_thresholds(rows, name):
            tp = sum(1 for p, y in zip(rows, ys, strict=True) if float(p[name]) >= t and y)
            fp = sum(1 for p, y in zip(rows, ys, strict=True) if float(p[name]) >= t and not y)
            if tp == 0:
                continue
            precision, recall = tp / (tp + fp), tp / pos
            f1 = 2 * precision * recall / (precision + recall)
            if f1 > best[0]:
                best = (f1, t, precision, recall)
        return best

    lines = [
        "EXPERIMENT 5 HEAD TO HEAD",
        "",
        f"wall/area: Spearman on the freeform corpus arm (n={len(freeform)}); the",
        "sequence-pair arm is budget-bound and carries no signal.  Refusal: best",
        f"threshold by F1 over all {len(points)} points ({positives} positive), and over the",
        f"{len(large)} large-URL arms alone.",
        "",
        f"{'feature':<28}{'rho wall':>9}{'rho area':>9}{'all F1':>8}{'(t)':>8}"
        f"{'P':>6}{'R':>6}{'lg F1':>7}{'(t)':>7}{'vals':>6}",
    ]
    for name in HEADLINE:
        rho_wall = _spearman(
            [float(p[name]) for p in freeform],
            [float(p["median_wall_s"]) for p in freeform],
        )
        rho_area = _spearman(
            [float(p[name]) for p in freeform if p["median_area"] is not None],
            [float(p["median_area"]) for p in freeform if p["median_area"] is not None],
        )
        f1_all, t_all, precision, recall = best_f1(points, name)
        f1_lg, t_lg, _, _ = best_f1(large, name)
        distinct = len({float(p[name]) for p in points})
        wall_cell = "-" if rho_wall is None else f"{rho_wall:+.3f}"
        area_cell = "-" if rho_area is None else f"{rho_area:+.3f}"
        lines.append(
            f"{name:<28}"
            f"{wall_cell:>9}"
            f"{area_cell:>9}"
            f"{f1_all:>8.2f}{t_all:>8.4g}{precision:>6.2f}{recall:>6.2f}"
            f"{f1_lg:>7.2f}{t_lg:>7.4g}{distinct:>6}"
        )
    lines.append("")
    return lines


def _equivalence_table(points: Sequence[dict[str, Any]]) -> list[str]:
    """Are the new features just re-orderings of the old ones on this data?

    Two questions, and only the second is the interesting one.  ``|rho| = 1``
    means one feature is a monotone relabelling of another -- literally the
    same ranking, so it can add nothing any threshold rule could use.  A low
    distinct-value count means a feature cannot separate much regardless of how
    well it correlates: a column with 5 values across 84 points has at most 4
    usable thresholds.
    """
    lines = [
        "MONOTONE EQUIVALENCE AMONG THE HEADLINE FEATURES",
        "",
        f"distinct values across the {len(points)} points:",
    ]
    for name in HEADLINE:
        values = sorted({float(p[name]) for p in points})
        shown = ", ".join(f"{v:g}" for v in values[:10])
        more = "" if len(values) <= 10 else f", ... (+{len(values) - 10})"
        lines.append(f"  {name:<28}{len(values):>4}   [{shown}{more}]")
    lines.append("")

    lines.append("pairwise Spearman (|rho| = 1.000 means one is a relabelling of the other):")
    lines.append("")
    width = 9
    lines.append(" " * 28 + "".join(f"{name[:8]:>{width}}" for name in HEADLINE))
    identical: list[tuple[str, str]] = []
    for a in HEADLINE:
        cells = []
        for b in HEADLINE:
            rho = _spearman([float(p[a]) for p in points], [float(p[b]) for p in points])
            cells.append("-" if rho is None else f"{rho:+.3f}")
            if rho is not None and a < b and abs(rho) > 0.9995:
                identical.append((a, b))
        lines.append(f"{a:<28}" + "".join(f"{c:>{width}}" for c in cells))
    lines.append("")
    if identical:
        lines.append("Monotone-equivalent pairs on this corpus:")
        for a, b in identical:
            lines.append(f"  {a} == {b}")
    else:
        lines.append("No pair is monotone-equivalent.")
    lines.append("")
    return lines


def _live_contrast(features: dict[tuple[str, str], dict[str, Any]]) -> list[str]:
    """4(c) again, in the experiment-5 numbers."""
    wanted = (
        "copper-ingot-2000",
        "copper-ingot-12000",
        "information-matrix-120",
        "universe-matrix",
    )
    cols = (
        "machines",
        "strips",
        "chain_depth",
        "max_spread",
        "max_live_range",
        "sum_live_range",
        "items_live_range_ge3",
        "max_pressure",
        "max_lane_pressure",
        "lane_pressure_per_strip",
        "proliferator_live_range",
    )
    lines = ["COPPER INGOT vs GREEN CUBE, IN LIVE-RANGE NUMBERS", ""]
    lines.append(f"{'spec':<40}" + "".join(f"{c[:13]:>15}" for c in cols))
    for url_id in wanted:
        for policy in ("no-proliferator", "all-products"):
            row = features.get((url_id, policy))
            if row is None:
                continue
            label = f"{url_id}/{policy}"
            lines.append(f"{label:<40}" + "".join(f"{row[c]:>15}" for c in cols))
    lines.append("")
    lines.append("longest live ranges, and the cut where pressure peaks:")
    for url_id in wanted:
        row = features.get((url_id, "no-proliferator"))
        if row is None:
            continue
        top = ", ".join(f"{item}={rng}" for item, rng in row["top_live_range"])
        lines.append(f"  {url_id:<26} {top}")
        profile = ", ".join(
            f"cut{cut}: {items} items / {lanes} lanes"
            for cut, items, lanes in row["pressure_profile"]
        )
        lines.append(f"  {'':<26} {profile or '(no cuts: depth 0)'}")
    lines.append("")
    return lines


def _contrast_table(features: dict[tuple[str, str], dict[str, Any]]) -> list[str]:
    """4(c): the user's copper-ingot-versus-green-cube contrast, in numbers."""
    wanted = (
        "copper-ingot-2000",
        "copper-ingot-12000",
        "information-matrix-120",
        "universe-matrix",
        "universe-matrix-12",
    )
    cols = (
        "machines",
        "groups",
        "strips",
        "distinct_items",
        "chain_depth",
        "max_consumers",
        "max_spread",
        "sum_spread",
        "items_with_3plus_consumers",
        "items_above_one_belt",
        "coaters",
        "proliferator_spread",
    )
    lines = ["COPPER INGOT vs GREEN CUBE  (4c)", ""]
    header = f"{'spec':<40}" + "".join(f"{c[:11]:>13}" for c in cols)
    lines.append(header)
    for url_id in wanted:
        for policy in ("no-proliferator", "all-products"):
            row = features.get((url_id, policy))
            if row is None:
                continue
            label = f"{url_id}/{policy}"
            lines.append(f"{label:<40}" + "".join(f"{row[c]:>13}" for c in cols))
    lines.append("")
    lines.append("top items by spread (item, consumers x depth-span):")
    for url_id in wanted:
        row = features.get((url_id, "no-proliferator"))
        if row is None:
            continue
        top = ", ".join(f"{item}={spread}" for item, spread in row["top_spread"])
        lines.append(f"  {url_id:<28} {top}")
        widest = sorted(row["items"], key=lambda i: (-i["consumers"], i["item_id"]))[:3]
        fan = ", ".join(
            f"{i['item_id']}(c={i['consumers']},d={i['earliest_consumer_depth']}..{i['latest_consumer_depth']})"
            for i in widest
        )
        lines.append(f"  {'':<28} widest fan-out: {fan}")
    lines.append("")
    return lines


def main() -> int:
    features = _load_features()
    points = _corpus_points(features) + _large_points(features)

    columns = [
        "source",
        "url_id",
        "spec_label",
        "strategy",
        "budget_s",
        "status_batch3",
        "status_batch2",
        "clean_rounds",
        "refused_all_rounds",
        "any_refusal",
        "refusal_class",
        "median_wall_s",
        "median_wall_batch2_s",
        "median_area",
        "median_overshoot_s",
        "median_alns_evaluations",
        "median_budget_unspent_s",
        "median_belt_tiles",
        "median_direct_inserts",
        *FEATURES,
    ]
    tsv = ["\t".join(columns)]
    for p in points:
        tsv.append("\t".join("" if p.get(c) is None else str(p.get(c)) for c in columns))
    (_HERE / "join.tsv").write_text("\n".join(tsv) + "\n")

    corpus = [p for p in points if p["source"] == "corpus"]
    large = [p for p in points if p["source"] == "large"]

    report: list[str] = []
    report.append("ROUTING-DIFFICULTY FEATURES vs OUTCOMES")
    report.append("=" * 72)
    report.append("")
    report.append(
        f"points: {len(points)} spec x arm "
        f"({len(corpus)} corpus at 30 s, {len(large)} large-URL pooled 60/100 s)"
    )
    report.append(
        "refused-in-all-rounds: "
        f"corpus={sum(p['refused_all_rounds'] for p in corpus)}, "
        f"large={sum(p['refused_all_rounds'] for p in large)}"
    )
    report.append("")

    report += _rank_table(
        corpus, "median_wall_s", title="SPEARMAN vs median wall -- corpus, both arms"
    )
    for arm in ("freeform", "sequence-pair"):
        report += _rank_table(
            corpus,
            "median_wall_s",
            title=f"SPEARMAN vs median wall -- corpus, {arm}",
            predicate=lambda p, arm=arm: p["strategy"] == arm,
        )
    report += _rank_table(
        corpus, "median_area", title="SPEARMAN vs median area -- corpus, both arms"
    )
    report += _rank_table(
        corpus,
        "median_overshoot_s",
        title="SPEARMAN vs median wall_overshoot_s -- corpus, both arms",
    )
    report += _rank_table(
        large, "median_wall_s", title="SPEARMAN vs median wall -- large URLs, both arms"
    )

    report += _separation_table(points, title="SINGLE-FEATURE SEPARATION -- all points")
    report += _separation_table(large, title="SINGLE-FEATURE SEPARATION -- large URLs only")
    report += _pair_table(points, title="BEST FEATURE PAIR -- all points")
    report += _large_detail(large)
    report += _policy_invariance(features)

    report += ["REFUSAL CLASS BY SPEC", ""]
    report.append(f"{'spec x arm':<52}{'class':<32}{'wall':>8}")
    for p in points:
        if p["refusal_class"] == "clean":
            continue
        label = f"{p['url_id']}/{p['spec_label']}/{p['strategy']}"
        wall = p["median_wall_s"] if p["median_wall_s"] is not None else 0.0
        report.append(f"{label:<52}{p['refusal_class']:<32}{wall:>8.1f}")
    report.append("")

    report += _who_wins(points)
    report += _contrast_table(features)
    report += _headline_table(points, corpus=corpus, large=large)
    report += _equivalence_table(points)
    report += _live_contrast(features)

    (_HERE / "analysis.txt").write_text("\n".join(report) + "\n")
    print("\n".join(report))
    print(f"WROTE {_HERE / 'join.tsv'} and {_HERE / 'analysis.txt'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
