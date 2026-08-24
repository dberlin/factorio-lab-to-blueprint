"""Deterministic, audit-only promotion gate for persisted A/B runs."""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from flab2bp.bench.ab import Outcome, Sample, Trial, samples_from_json, trials_from
from flab2bp.bench.corpus import URL_CORPUS
from flab2bp.bench.scoring import geometric_mean

_CellKey = tuple[str, float, bool]
_RawKey = tuple[str, str, float, int, bool]
_TrialKey = tuple[str, float, int, bool]
_INVALID_OUTCOMES = (Outcome.INVALID, Outcome.ERROR, Outcome.CROSSFAIL)


@dataclass(frozen=True, slots=True, order=True)
class RequiredCell:
    """Exact expected run shape for one URL, budget, and power mode."""

    url_id: str
    budget_s: float
    power: bool
    repeat: int
    candidates: int

    def __post_init__(self) -> None:
        if not self.url_id:
            raise ValueError("required cell url_id must not be empty")
        if not math.isfinite(self.budget_s) or self.budget_s <= 0:
            raise ValueError("required cell budget must be finite and positive")
        if self.repeat <= 0 or self.candidates <= 0:
            raise ValueError("required cell repeat and candidates must be positive")

    @property
    def key(self) -> _CellKey:
        return (self.url_id, self.budget_s, self.power)


@dataclass(frozen=True, slots=True)
class PromotionManifest:
    """Repository or fixture scope that persisted samples must cover exactly."""

    cells: tuple[RequiredCell, ...]

    def __post_init__(self) -> None:
        keys = [cell.key for cell in self.cells]
        if len(set(keys)) != len(keys):
            raise ValueError("promotion manifest cells must be unique")
        if not keys:
            raise ValueError("promotion manifest must require at least one cell")


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


def repository_manifest(
    *, budgets: Sequence[float], repeat: int, candidates: int
) -> PromotionManifest:
    """Require the entire repository corpus at every budget and both power modes."""
    cells = tuple(
        RequiredCell(entry.url_id, budget, power, repeat, candidates)
        for entry in URL_CORPUS
        for budget in budgets
        for power in (False, True)
    )
    return PromotionManifest(cells)


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


def _raw_key(sample: Sample) -> _RawKey:
    return (
        sample.url_id,
        sample.candidate,
        sample.budget_s,
        sample.trial,
        sample.power,
    )


def _trial_key(trial: Trial) -> _TrialKey:
    return (trial.url_id, trial.budget_s, trial.trial, trial.power)


def _cell_key(sample: Sample | Trial) -> _CellKey:
    return (sample.url_id, sample.budget_s, sample.power)


def _label(key: _CellKey) -> str:
    return f"{key[0]}@{key[1]:g}s/power={int(key[2])}"


def _preview(keys: Sequence[_CellKey | _RawKey | _TrialKey]) -> str:
    shown = ", ".join(str(key) for key in keys[:3])
    return shown + (", ..." if len(keys) > 3 else "")


def _scope_reasons(
    side: str, samples: Sequence[Sample], required: PromotionManifest
) -> list[str]:
    reasons: list[str] = []
    by_cell: dict[_CellKey, list[Sample]] = {}
    for sample in samples:
        by_cell.setdefault(_cell_key(sample), []).append(sample)
    required_keys = {cell.key for cell in required.cells}
    observed_keys = set(by_cell)
    missing = sorted(required_keys - observed_keys)
    unexpected = sorted(observed_keys - required_keys)
    if missing:
        reasons.append(
            f"{side} missing {len(missing)} required cell(s): {_preview(missing)}"
        )
    if unexpected:
        reasons.append(
            f"{side} has {len(unexpected)} unexpected cell(s): {_preview(unexpected)}"
        )

    requirements = {cell.key: cell for cell in required.cells}
    for key in sorted(required_keys & observed_keys):
        expected = requirements[key]
        rows = by_cell[key]
        trials = {sample.trial for sample in rows}
        wanted_trials = set(range(expected.repeat))
        if trials != wanted_trials:
            reasons.append(
                f"{side} {_label(key)} required trials {sorted(wanted_trials)}, "
                f"observed {sorted(trials)}"
            )
        candidate_sets: list[set[str]] = []
        for trial in sorted(trials):
            candidates = {sample.candidate for sample in rows if sample.trial == trial}
            candidate_sets.append(candidates)
            if len(candidates) != expected.candidates:
                reasons.append(
                    f"{side} {_label(key)} trial {trial} requires "
                    f"{expected.candidates} candidates, observed {len(candidates)}"
                )
        identities_vary = any(
            candidates != candidate_sets[0] for candidates in candidate_sets[1:]
        )
        if candidate_sets and identities_vary:
            reasons.append(f"{side} {_label(key)} candidate identities vary by trial")
    return reasons


def _raw_reasons(baseline: Sequence[Sample], candidate: Sequence[Sample]) -> list[str]:
    reasons: list[str] = []
    baseline_counts = Counter(_raw_key(sample) for sample in baseline)
    candidate_counts = Counter(_raw_key(sample) for sample in candidate)
    duplicate_baseline = sorted(key for key, count in baseline_counts.items() if count != 1)
    duplicate_candidate = sorted(key for key, count in candidate_counts.items() if count != 1)
    if duplicate_baseline:
        reasons.append(
            "baseline duplicate raw sample identities: " + _preview(duplicate_baseline)
        )
    if duplicate_candidate:
        reasons.append(
            "candidate duplicate raw sample identities: " + _preview(duplicate_candidate)
        )

    baseline_keys = set(baseline_counts)
    candidate_keys = set(candidate_counts)
    missing = sorted(baseline_keys - candidate_keys)
    additional = sorted(candidate_keys - baseline_keys)
    if missing:
        reasons.append(
            f"candidate missing {len(missing)} raw sample identities: {_preview(missing)}"
        )
    if additional:
        reasons.append(
            f"candidate has {len(additional)} additional raw sample identities: "
            f"{_preview(additional)}"
        )

    for side, samples in (("baseline", baseline), ("candidate", candidate)):
        for outcome in _INVALID_OUTCOMES:
            bad = sorted(_raw_key(sample) for sample in samples if sample.outcome is outcome)
            if bad:
                reasons.append(
                    f"{side} has {len(bad)} raw {outcome.value} output(s): {_preview(bad)}"
                )

    baseline_refusals = {
        _raw_key(sample) for sample in baseline if sample.outcome is Outcome.REFUSED
    }
    candidate_refusals = {
        _raw_key(sample) for sample in candidate if sample.outcome is Outcome.REFUSED
    }
    additional_refusals = sorted(candidate_refusals - baseline_refusals)
    if additional_refusals:
        reasons.append(
            f"candidate has {len(additional_refusals)} additional refusal(s): "
            f"{_preview(additional_refusals)}"
        )
    return reasons


def _group_trials(trials: Sequence[Trial]) -> dict[_CellKey, list[Trial]]:
    grouped: dict[_CellKey, list[Trial]] = {}
    for trial in trials:
        grouped.setdefault(_cell_key(trial), []).append(trial)
    return grouped


def _median_quality(trials: Sequence[Trial], attribute: str) -> float | None:
    values: list[int] = []
    for trial in trials:
        if trial.metrics is None:
            continue
        values.append(
            trial.metrics.area if attribute == "area" else trial.metrics.belt_tiles
        )
    return float(statistics.median(values)) if values else None


def _median_seconds(trials: Sequence[Trial]) -> float:
    return statistics.median(trial.seconds for trial in trials) if trials else 0.0


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


def assess_promotion(
    baseline: Sequence[Sample],
    candidate: Sequence[Sample],
    *,
    required: PromotionManifest,
    bootstrap_seed: int = 0,
    bootstrap_resamples: int = 10_000,
) -> PromotionReport:
    """Apply every strict gate after verifying the complete raw sample matrix."""
    reasons = _scope_reasons("baseline", baseline, required)
    reasons += _scope_reasons("candidate", candidate, required)
    reasons += _raw_reasons(baseline, candidate)

    baseline_trials = trials_from(baseline)
    candidate_trials = trials_from(candidate)
    baseline_trial_keys = {_trial_key(trial) for trial in baseline_trials}
    candidate_trial_keys = {_trial_key(trial) for trial in candidate_trials}
    if baseline_trial_keys != candidate_trial_keys:
        reasons.append("matched trial identities differ after candidate shipping")

    before_cells = _group_trials(baseline_trials)
    after_cells = _group_trials(candidate_trials)
    matched = sorted(set(before_cells) & set(after_cells))
    runtime_ratios: list[float] = []
    for key in matched:
        before = before_cells[key]
        after = after_cells[key]
        for attribute in ("area", "belts"):
            before_value = _median_quality(before, attribute)
            after_value = _median_quality(after, attribute)
            if before_value is None or after_value is None:
                reasons.append(f"{_label(key)} lacks comparable median {attribute}")
            elif after_value > before_value:
                reasons.append(
                    f"candidate {_label(key)} median {attribute} regressed "
                    f"from {before_value:g} to {after_value:g}"
                )
        runtime_ratio = _ratio(_median_seconds(after), _median_seconds(before))
        if math.isfinite(runtime_ratio) and runtime_ratio > 0:
            runtime_ratios.append(runtime_ratio)
        else:
            reasons.append(f"{_label(key)} lacks comparable positive runtime")

    complete_runtime = len(runtime_ratios) == len(required.cells) == len(matched)
    runtime_ratio_geo_mean = (
        geometric_mean(runtime_ratios) if complete_runtime else math.inf
    )
    runtime_ratio_ci_hi = math.inf
    if complete_runtime:
        runtime_ratio_ci_hi = paired_bootstrap_ci_hi(
            runtime_ratios, seed=bootstrap_seed, resamples=bootstrap_resamples
        )
        if runtime_ratio_ci_hi >= 1.0:
            reasons.append(
                f"runtime paired-bootstrap 95% upper bound is "
                f"{runtime_ratio_ci_hi:.6g}, not < 1"
            )

    baseline_wall = [trial.seconds for trial in baseline_trials]
    candidate_wall = [trial.seconds for trial in candidate_trials]
    p95_ratio = _ratio(
        _percentile(candidate_wall, 0.95), _percentile(baseline_wall, 0.95)
    )
    if p95_ratio > 1.0:
        reasons.append(f"p95 wall ratio is {p95_ratio:.6g}, worse than 1")

    baseline_cpu = [trial.cpu_seconds for trial in baseline_trials]
    candidate_cpu = [trial.cpu_seconds for trial in candidate_trials]
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

    baseline_rss = [trial.peak_rss_mb for trial in baseline_trials]
    candidate_rss = [trial.peak_rss_mb for trial in candidate_trials]
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


def _positive_integer(meta: Mapping[str, object], key: str) -> int:
    value = meta.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"result JSON meta {key!r} must be numeric")
    number = int(value)
    if number <= 0 or number != value:
        raise ValueError(f"result JSON meta {key!r} must be a positive integer")
    return number


def _budgets(meta: Mapping[str, object]) -> tuple[float, ...]:
    raw = meta.get("budgets")
    if not isinstance(raw, list) or not raw:
        raise ValueError("result JSON meta 'budgets' must be a non-empty list")
    budgets: list[float] = []
    for value in raw:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("result JSON budgets must be numeric")
        budget = float(value)
        if not math.isfinite(budget) or budget <= 0:
            raise ValueError("result JSON budgets must be finite and positive")
        budgets.append(budget)
    return tuple(budgets)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("results", nargs="+", type=Path)
    _ = parser.add_argument("--bootstrap-seed", type=int, default=0)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    baseline: list[Sample] = []
    candidate: list[Sample] = []
    expected_pair: tuple[str, str] | None = None
    expected_repeat: int | None = None
    expected_candidates: int | None = None
    budgets: set[float] = set()
    for path in args.results:
        raw = json.loads(path.read_text())
        if not isinstance(raw, dict):
            raise SystemExit(f"{path}: result JSON must be an object")
        document: Mapping[str, object] = raw
        meta = _meta(document)
        pair = (str(meta.get("a", "spine")), str(meta.get("b", "freeform")))
        repeat = _positive_integer(meta, "repeat")
        candidates = _positive_integer(meta, "candidates")
        if expected_pair is None:
            expected_pair = pair
            expected_repeat = repeat
            expected_candidates = candidates
        elif (
            pair != expected_pair
            or repeat != expected_repeat
            or candidates != expected_candidates
        ):
            raise SystemExit(f"{path}: backend pair/repeat/candidates do not match prior runs")
        budgets.update(_budgets(meta))
        samples = samples_from_json(document)
        baseline.extend(sample for sample in samples if sample.strategy == pair[0])
        candidate.extend(sample for sample in samples if sample.strategy == pair[1])

    if expected_repeat is None or expected_candidates is None:
        raise SystemExit("no result JSON supplied")
    required = repository_manifest(
        budgets=tuple(sorted(budgets)),
        repeat=expected_repeat,
        candidates=expected_candidates,
    )
    report = assess_promotion(
        baseline,
        candidate,
        required=required,
        bootstrap_seed=args.bootstrap_seed,
    )
    print(json.dumps(report.to_json(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
