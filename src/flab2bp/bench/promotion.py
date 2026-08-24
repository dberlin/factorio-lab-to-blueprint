"""Deterministic, audit-only promotion gate for persisted A/B runs."""

from __future__ import annotations

import argparse
import json
import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from flab2bp.bench.ab import Cell, Outcome, Trial, samples_from_json, trials_from
from flab2bp.bench.scoring import geometric_mean

_CellKey = tuple[str, float]
_INVALID_OUTCOMES = (Outcome.INVALID, Outcome.ERROR, Outcome.CROSSFAIL)


@dataclass(frozen=True, slots=True)
class PromotionReport:
    """Every strict Pareto measurement and the reasons an audit is ineligible."""

    eligible: bool
    reasons: tuple[str, ...]
    runtime_ratio_geo_mean: float
    runtime_ratio_ci_hi: float
    p95_ratio: float
    cpu_ratio: float
    rss_ratio: float

    def to_json(self) -> dict[str, object]:
        """Return strict JSON data, representing unavailable ratios as null."""
        result: dict[str, object] = asdict(self)
        for key in (
            "runtime_ratio_geo_mean",
            "runtime_ratio_ci_hi",
            "p95_ratio",
            "cpu_ratio",
            "rss_ratio",
        ):
            value = result[key]
            if isinstance(value, float) and not math.isfinite(value):
                result[key] = None
        return result


def paired_bootstrap_ci_hi(
    ratios: Sequence[float], *, seed: int, resamples: int = 10_000
) -> float:
    """Return a deterministic one-sided 95% upper bound over matched cell ratios."""
    if not ratios:
        raise ValueError("paired bootstrap needs at least one matched cell ratio")
    if resamples <= 0:
        raise ValueError("paired bootstrap resamples must be positive")
    if any(not math.isfinite(value) or value <= 0 for value in ratios):
        raise ValueError("paired bootstrap ratios must be finite and positive")

    rng = random.Random(seed)
    count = len(ratios)
    estimates = [
        geometric_mean(ratios[rng.randrange(count)] for _ in range(count))
        for _ in range(resamples)
    ]
    estimates.sort()
    return estimates[math.ceil(0.95 * resamples) - 1]


def _cells(trials: Sequence[Trial]) -> dict[_CellKey, Cell]:
    grouped: dict[_CellKey, list[Trial]] = {}
    for trial in trials:
        grouped.setdefault((trial.url_id, trial.budget_s), []).append(trial)
    return {
        key: Cell(key[0], values[0].strategy, key[1], tuple(values))
        for key, values in grouped.items()
    }


def _label(key: _CellKey) -> str:
    return f"{key[0]}@{key[1]:g}s"


def _percentile(values: Sequence[float], quantile: float) -> float:
    if not values:
        return math.inf
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _ratio(numerator: float, denominator: float) -> float:
    if (
        not math.isfinite(numerator)
        or not math.isfinite(denominator)
        or numerator < 0
        or denominator <= 0
    ):
        return math.inf
    return numerator / denominator


def _quality_median(cell: Cell, attribute: str) -> int | None:
    if attribute == "area":
        return cell.median_area
    return cell.median_of(
        lambda trial: trial.metrics.belt_tiles if trial.metrics is not None else 0
    )


def assess_promotion(
    baseline: Sequence[Trial],
    candidate: Sequence[Trial],
    *,
    bootstrap_seed: int = 0,
    bootstrap_resamples: int = 10_000,
) -> PromotionReport:
    """Apply every strict gate to matched ``(url, budget)`` trial cells."""
    reasons: list[str] = []
    baseline_cells = _cells(baseline)
    candidate_cells = _cells(candidate)
    baseline_keys = set(baseline_cells)
    candidate_keys = set(candidate_cells)
    baseline_only = sorted(baseline_keys - candidate_keys)
    candidate_only = sorted(candidate_keys - baseline_keys)
    if baseline_only:
        reasons.append(
            "unmatched baseline cells: " + ", ".join(_label(key) for key in baseline_only)
        )
    if candidate_only:
        reasons.append(
            "unmatched candidate cells: " + ", ".join(_label(key) for key in candidate_only)
        )

    matched = sorted(baseline_keys & candidate_keys)
    if not matched:
        reasons.append("no matched cells")

    runtime_ratios: list[float] = []
    for key in matched:
        before = baseline_cells[key]
        after = candidate_cells[key]
        for side, cell in (("baseline", before), ("candidate", after)):
            for outcome in _INVALID_OUTCOMES:
                count = cell.count(outcome)
                if count:
                    reasons.append(
                        f"{side} {_label(key)} has {count} {outcome.value} output(s)"
                    )
        extra_refusals = after.count(Outcome.REFUSED) - before.count(Outcome.REFUSED)
        if extra_refusals > 0:
            reasons.append(
                f"candidate {_label(key)} has {extra_refusals} additional refusal(s)"
            )

        for attribute in ("area", "belts"):
            before_value = _quality_median(before, attribute)
            after_value = _quality_median(after, attribute)
            if before_value is None or after_value is None:
                reasons.append(f"{_label(key)} lacks comparable median {attribute}")
            elif after_value > before_value:
                reasons.append(
                    f"candidate {_label(key)} median {attribute} regressed "
                    f"from {before_value} to {after_value}"
                )

        runtime_ratio = _ratio(after.median_seconds, before.median_seconds)
        if math.isfinite(runtime_ratio) and runtime_ratio > 0:
            runtime_ratios.append(runtime_ratio)
        else:
            reasons.append(f"{_label(key)} lacks comparable positive runtime")

    all_runtime_cells = len(runtime_ratios) == len(matched) and bool(matched)
    runtime_ratio_geo_mean = (
        geometric_mean(runtime_ratios) if all_runtime_cells else math.inf
    )
    runtime_ratio_ci_hi = math.inf
    if len(runtime_ratios) == len(matched) and matched:
        runtime_ratio_ci_hi = paired_bootstrap_ci_hi(
            runtime_ratios, seed=bootstrap_seed, resamples=bootstrap_resamples
        )
        if runtime_ratio_ci_hi >= 1.0:
            reasons.append(
                f"runtime paired-bootstrap 95% upper bound is {runtime_ratio_ci_hi:.6g}, not < 1"
            )

    baseline_wall = [trial.seconds for key in matched for trial in baseline_cells[key].trials]
    candidate_wall = [trial.seconds for key in matched for trial in candidate_cells[key].trials]
    p95_ratio = _ratio(_percentile(candidate_wall, 0.95), _percentile(baseline_wall, 0.95))
    if p95_ratio > 1.0:
        reasons.append(f"p95 wall ratio is {p95_ratio:.6g}, worse than 1")

    baseline_cpu = [
        trial.cpu_seconds for key in matched for trial in baseline_cells[key].trials
    ]
    candidate_cpu = [
        trial.cpu_seconds for key in matched for trial in candidate_cells[key].trials
    ]
    if (
        any(value is None for value in baseline_cpu + candidate_cpu)
        or not baseline_cpu
        or not candidate_cpu
    ):
        cpu_ratio = math.inf
        reasons.append("CPU metric is missing from one or more matched trials")
    else:
        cpu_ratio = _ratio(
            sum(value for value in candidate_cpu if value is not None),
            sum(value for value in baseline_cpu if value is not None),
        )
        if cpu_ratio > 1.0:
            reasons.append(f"CPU ratio is {cpu_ratio:.6g}, worse than 1")

    baseline_rss = [
        trial.peak_rss_mb for key in matched for trial in baseline_cells[key].trials
    ]
    candidate_rss = [
        trial.peak_rss_mb for key in matched for trial in candidate_cells[key].trials
    ]
    if (
        any(value is None for value in baseline_rss + candidate_rss)
        or not baseline_rss
        or not candidate_rss
    ):
        rss_ratio = math.inf
        reasons.append("RSS metric is missing from one or more matched trials")
    else:
        rss_ratio = _ratio(
            max(value for value in candidate_rss if value is not None),
            max(value for value in baseline_rss if value is not None),
        )
        if rss_ratio > 1.0:
            reasons.append(f"RSS ratio is {rss_ratio:.6g}, worse than 1")

    return PromotionReport(
        eligible=not reasons,
        reasons=tuple(reasons),
        runtime_ratio_geo_mean=runtime_ratio_geo_mean,
        runtime_ratio_ci_hi=runtime_ratio_ci_hi,
        p95_ratio=p95_ratio,
        cpu_ratio=cpu_ratio,
        rss_ratio=rss_ratio,
    )


def _meta(document: Mapping[str, object]) -> Mapping[str, object]:
    meta = document.get("meta", {})
    if not isinstance(meta, dict):
        raise ValueError("result JSON meta must be an object")
    return meta


def trials_from_json(document: Mapping[str, object]) -> tuple[list[Trial], list[Trial]]:
    """Load baseline/candidate trials from current or legacy persisted A/B JSON."""
    meta = _meta(document)
    a_name = str(meta.get("a", "spine"))
    b_name = str(meta.get("b", "freeform"))
    trials = trials_from(samples_from_json(document))
    return (
        [trial for trial in trials if trial.strategy == a_name],
        [trial for trial in trials if trial.strategy == b_name],
    )


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", nargs="+", type=Path)
    parser.add_argument("--bootstrap-seed", type=int, default=0)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    baseline: list[Trial] = []
    candidate: list[Trial] = []
    expected_pair: tuple[str, str] | None = None
    for path in args.results:
        raw = json.loads(path.read_text())
        if not isinstance(raw, dict):
            raise SystemExit(f"{path}: result JSON must be an object")
        document: Mapping[str, object] = raw
        meta = _meta(document)
        pair = (str(meta.get("a", "spine")), str(meta.get("b", "freeform")))
        if expected_pair is None:
            expected_pair = pair
        elif pair != expected_pair:
            raise SystemExit(
                f"{path}: backend pair {pair[0]}/{pair[1]} does not match "
                f"{expected_pair[0]}/{expected_pair[1]}"
            )
        before, after = trials_from_json(document)
        scope = f"power={int(bool(meta.get('power', False)))}:"
        baseline.extend(replace(trial, url_id=scope + trial.url_id) for trial in before)
        candidate.extend(replace(trial, url_id=scope + trial.url_id) for trial in after)

    report = assess_promotion(
        baseline,
        candidate,
        bootstrap_seed=args.bootstrap_seed,
    )
    print(json.dumps(report.to_json(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
