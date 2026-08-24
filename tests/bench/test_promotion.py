from __future__ import annotations

import math

import pytest

from flab2bp.bench.ab import Outcome, Trial
from flab2bp.bench.promotion import (
    assess_promotion,
    paired_bootstrap_ci_hi,
    trials_from_json,
)
from flab2bp.bench.types import Metrics


def _metrics(area: int, belts: int) -> Metrics:
    return Metrics(
        area=area,
        used_tiles=area,
        width=area,
        height=1,
        machines=1,
        belt_tiles=belts,
        sorters=0,
        direct_inserts=0,
        towers=0,
        altitude_levels=1,
    )


def fixture_trials(
    *,
    url_id: str = "one-cell",
    strategy: str = "baseline",
    seconds: tuple[float, ...] = (10.0, 10.2, 9.8),
    area: tuple[int, ...] = (100, 100, 100),
    belts: tuple[int, ...] = (50, 50, 50),
    cpu: tuple[float | None, ...] = (8.0, 8.1, 7.9),
    rss: tuple[float | None, ...] = (100.0, 101.0, 99.0),
    outcome: Outcome = Outcome.VALID,
    budget_s: float = 10.0,
) -> list[Trial]:
    assert len(seconds) == len(area) == len(belts) == len(cpu) == len(rss)
    return [
        Trial(
            url_id=url_id,
            strategy=strategy,
            budget_s=budget_s,
            trial=index,
            outcome=outcome,
            candidate="default",
            seconds=wall,
            metrics=_metrics(cell_area, belt_tiles) if outcome is Outcome.VALID else None,
            cpu_seconds=cpu_seconds,
            peak_rss_mb=peak_rss_mb,
            candidates_valid=int(outcome is Outcome.VALID),
            candidates_total=1,
        )
        for index, (wall, cell_area, belt_tiles, cpu_seconds, peak_rss_mb) in enumerate(
            zip(seconds, area, belts, cpu, rss, strict=True)
        )
    ]


def _eligible_pair() -> tuple[list[Trial], list[Trial]]:
    baseline = fixture_trials()
    candidate = fixture_trials(
        strategy="candidate",
        seconds=(8.0, 8.2, 7.9),
        area=(100, 99, 100),
        belts=(50, 50, 49),
        cpu=(6.0, 6.1, 5.9),
        rss=(90.0, 91.0, 89.0),
    )
    return baseline, candidate


def test_promotion_requires_strict_runtime_ci_and_nonworse_quality() -> None:
    baseline, candidate = _eligible_pair()

    report = assess_promotion(baseline=baseline, candidate=candidate, bootstrap_seed=7)

    assert report.eligible
    assert report.reasons == ()
    assert report.runtime_ratio_ci_hi < 1.0
    assert report.p95_ratio <= 1.0
    assert report.cpu_ratio <= 1.0
    assert report.rss_ratio <= 1.0


def test_one_cell_quality_regression_blocks_promotion() -> None:
    baseline, candidate = _eligible_pair()
    candidate = fixture_trials(
        strategy="candidate",
        seconds=(7.0, 7.1, 6.9),
        area=(101, 101, 101),
        belts=(50, 50, 50),
        cpu=(6.0, 6.1, 5.9),
        rss=(90.0, 91.0, 89.0),
    )

    report = assess_promotion(baseline=baseline, candidate=candidate, bootstrap_seed=7)

    assert not report.eligible
    assert any("area" in reason for reason in report.reasons)


def test_paired_bootstrap_is_deterministic() -> None:
    ratios = (0.5, 0.75, 0.9, 1.05)

    first = paired_bootstrap_ci_hi(ratios, seed=184, resamples=2_000)
    second = paired_bootstrap_ci_hi(ratios, seed=184, resamples=2_000)

    assert first == second
    assert 0.0 < first < math.inf


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("invalid", "invalid"),
        ("refusal", "refusal"),
        ("error", "error"),
        ("crossfail", "crossfail"),
        ("belts", "belts"),
        ("runtime", "runtime"),
        ("p95", "p95"),
        ("cpu", "CPU"),
        ("rss", "RSS"),
        ("missing-cpu", "CPU metric"),
        ("missing-rss", "RSS metric"),
        ("unmatched", "unmatched"),
    ],
)
def test_every_strict_gate_failure_is_reported(mutation: str, reason: str) -> None:
    baseline, candidate = _eligible_pair()
    if mutation in {"invalid", "refusal", "error", "crossfail"}:
        outcome = {
            "invalid": Outcome.INVALID,
            "refusal": Outcome.REFUSED,
            "error": Outcome.ERROR,
            "crossfail": Outcome.CROSSFAIL,
        }[mutation]
        candidate = fixture_trials(
            strategy="candidate",
            seconds=(8.0, 8.2, 7.9),
            area=(100, 100, 100),
            belts=(50, 50, 50),
            cpu=(6.0, 6.1, 5.9),
            rss=(90.0, 91.0, 89.0),
            outcome=outcome,
        )
    elif mutation == "belts":
        candidate = fixture_trials(
            strategy="candidate",
            seconds=(8.0, 8.2, 7.9),
            area=(100, 100, 100),
            belts=(51, 51, 51),
            cpu=(6.0, 6.1, 5.9),
            rss=(90.0, 91.0, 89.0),
        )
    elif mutation == "runtime":
        candidate = fixture_trials(
            strategy="candidate",
            seconds=(10.1, 10.3, 9.9),
            cpu=(6.0, 6.1, 5.9),
            rss=(90.0, 91.0, 89.0),
        )
    elif mutation == "p95":
        candidate = fixture_trials(
            strategy="candidate",
            seconds=(1.0, 1.0, 20.0),
            cpu=(6.0, 6.1, 5.9),
            rss=(90.0, 91.0, 89.0),
        )
    elif mutation == "cpu":
        candidate = fixture_trials(
            strategy="candidate",
            seconds=(8.0, 8.2, 7.9),
            cpu=(9.0, 9.1, 8.9),
            rss=(90.0, 91.0, 89.0),
        )
    elif mutation == "rss":
        candidate = fixture_trials(
            strategy="candidate",
            seconds=(8.0, 8.2, 7.9),
            cpu=(6.0, 6.1, 5.9),
            rss=(110.0, 111.0, 109.0),
        )
    elif mutation == "missing-cpu":
        candidate = fixture_trials(
            strategy="candidate",
            seconds=(8.0, 8.2, 7.9),
            cpu=(None, None, None),
            rss=(90.0, 91.0, 89.0),
        )
    elif mutation == "missing-rss":
        candidate = fixture_trials(
            strategy="candidate",
            seconds=(8.0, 8.2, 7.9),
            cpu=(6.0, 6.1, 5.9),
            rss=(None, None, None),
        )
    else:
        candidate = fixture_trials(
            url_id="different-cell",
            strategy="candidate",
            seconds=(8.0, 8.2, 7.9),
            cpu=(6.0, 6.1, 5.9),
            rss=(90.0, 91.0, 89.0),
        )

    report = assess_promotion(baseline=baseline, candidate=candidate, bootstrap_seed=7)

    assert not report.eligible
    assert any(reason in item for item in report.reasons)


def test_baseline_refusals_do_not_block_when_candidate_has_no_additional_refusal() -> None:
    baseline, candidate = _eligible_pair()
    baseline.append(
        Trial(
            url_id="one-cell",
            strategy="baseline",
            budget_s=10.0,
            trial=3,
            outcome=Outcome.REFUSED,
            candidate="default",
            seconds=10.0,
            cpu_seconds=8.0,
            peak_rss_mb=100.0,
            candidates_total=1,
        )
    )
    candidate.append(
        Trial(
            url_id="one-cell",
            strategy="candidate",
            budget_s=10.0,
            trial=3,
            outcome=Outcome.VALID,
            candidate="default",
            seconds=8.0,
            metrics=_metrics(100, 50),
            cpu_seconds=6.0,
            peak_rss_mb=90.0,
            candidates_valid=1,
            candidates_total=1,
        )
    )

    report = assess_promotion(baseline=baseline, candidate=candidate, bootstrap_seed=7)

    assert report.eligible


def test_old_json_without_cpu_or_rss_parses_but_cannot_pass() -> None:
    document: dict[str, object] = {
        "meta": {"a": "baseline", "b": "candidate", "power": False},
        "samples": [
            {
                "url_id": "one-cell",
                "candidate": "default",
                "strategy": strategy,
                "budget_s": 10.0,
                "trial": trial,
                "outcome": "valid",
                "seconds": seconds,
                "area": 100,
                "used_tiles": 100,
                "buildings": 1,
                "belt_tiles": 50,
                "direct_inserts": 0,
                "machines": 1,
                "detail": "",
            }
            for strategy, seconds in (("baseline", 10.0), ("candidate", 8.0))
            for trial in range(3)
        ],
    }

    baseline, candidate = trials_from_json(document)
    report = assess_promotion(baseline=baseline, candidate=candidate, bootstrap_seed=7)

    assert all(trial.cpu_seconds is None for trial in baseline + candidate)
    assert all(trial.peak_rss_mb is None for trial in baseline + candidate)
    assert not report.eligible
    assert any("CPU metric" in reason for reason in report.reasons)
    assert any("RSS metric" in reason for reason in report.reasons)
