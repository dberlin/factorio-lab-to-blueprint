from __future__ import annotations

import json
import math
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from flab2bp.bench.ab import (
    CrossSummary,
    Outcome,
    RunMeta,
    Sample,
    cross_summary_from_json,
    samples_from_json,
    to_json,
)
from flab2bp.bench.corpus import URL_CORPUS
from flab2bp.bench.promotion import (
    PromotionManifest,
    PromotionReport,
    RequiredCell,
    assess_promotion,
    paired_bootstrap_ci_hi,
    repository_manifest,
)
from flab2bp.bench.promotion import main as promotion_main
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


def fixture_samples(
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
    candidate: str = "default",
    power: bool = False,
) -> list[Sample]:
    assert len(seconds) == len(area) == len(belts) == len(cpu) == len(rss)
    return [
        Sample(
            url_id=url_id,
            candidate=candidate,
            strategy=strategy,
            budget_s=budget_s,
            trial=index,
            outcome=outcome,
            seconds=wall,
            metrics=_metrics(cell_area, belt_tiles) if outcome is Outcome.VALID else None,
            buildings=int(outcome is Outcome.VALID),
            cpu_seconds=cpu_seconds,
            peak_rss_mb=peak_rss_mb,
            power=power,
        )
        for index, (wall, cell_area, belt_tiles, cpu_seconds, peak_rss_mb) in enumerate(
            zip(seconds, area, belts, cpu, rss, strict=True)
        )
    ]


def manifest(*, repeat: int = 3, candidates: int = 1, power: bool = False) -> PromotionManifest:
    return PromotionManifest((RequiredCell("one-cell", 10.0, power, repeat, candidates),))


def eligible_pair() -> tuple[list[Sample], list[Sample]]:
    baseline = fixture_samples()
    candidate = fixture_samples(
        strategy="candidate",
        seconds=(8.0, 8.2, 7.9),
        area=(100, 99, 100),
        belts=(50, 50, 49),
        cpu=(6.0, 6.1, 5.9),
        rss=(90.0, 91.0, 89.0),
    )
    return baseline, candidate


def _complete_cross(*groups: list[Sample]) -> CrossSummary:
    checked = sum(sample.outcome is Outcome.VALID for group in groups for sample in group)
    return CrossSummary(available=True, checked=checked, passed=checked)


def assess(
    baseline: list[Sample],
    candidate: list[Sample],
    *,
    required: PromotionManifest | None = None,
) -> PromotionReport:
    return assess_promotion(
        baseline,
        candidate,
        required=required or manifest(),
        cross=_complete_cross(baseline, candidate),
        bootstrap_seed=7,
        bootstrap_resamples=2_000,
    )


def test_promotion_requires_strict_runtime_ci_and_nonworse_quality() -> None:
    baseline, candidate = eligible_pair()

    report = assess_promotion(
        baseline,
        candidate,
        required=manifest(),
        cross=_complete_cross(baseline, candidate),
        bootstrap_seed=7,
    )

    assert report.eligible
    assert report.reasons == ()
    assert report.runtime_ratio_ci_hi < 1.0
    assert report.p95_ratio <= 1.0
    assert report.cpu_ratio <= 1.0
    assert report.rss_ratio <= 1.0


@pytest.mark.parametrize(
    "cross",
    [
        CrossSummary(available=False),
        CrossSummary(available=True, checked=6, passed=5),
        CrossSummary(
            available=True,
            checked=6,
            passed=6,
            demoted=("one-cell/default/candidate: fixture",),
        ),
    ],
)
def test_promotion_requires_complete_successful_crossvalidation(cross: CrossSummary) -> None:
    baseline, candidate = eligible_pair()

    report = assess_promotion(
        baseline,
        candidate,
        required=manifest(),
        cross=cross,
        bootstrap_seed=7,
    )

    assert not report.eligible
    assert any("cross-validation" in reason for reason in report.reasons)


def test_complete_successful_crossvalidation_can_pass_unit_gate() -> None:
    baseline, candidate = eligible_pair()

    report = assess_promotion(
        baseline,
        candidate,
        required=manifest(),
        cross=CrossSummary(available=True, checked=6, passed=6),
        bootstrap_seed=7,
    )

    assert report.eligible


def test_promotion_cli_threads_persisted_crossvalidation(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    baseline, candidate = eligible_pair()
    document = to_json(
        [*baseline, *candidate],
        RunMeta(
            tiers=("fixture",),
            budgets=(10.0,),
            repeat=3,
            candidates=1,
            power=False,
            urls=1,
            a_name="baseline",
            b_name="candidate",
        ),
        CrossSummary(available=False, reason="fixture unavailable"),
    )
    path = tmp_path / "result.json"
    path.write_text(json.dumps(document))

    assert promotion_main([str(path)]) == 0
    result = json.loads(capsys.readouterr().out)

    assert not result["eligible"]
    assert any("cross-validation" in reason for reason in result["reasons"])


def test_one_cell_fractional_area_regression_blocks_promotion() -> None:
    baseline = fixture_samples(
        seconds=(10.0, 10.0),
        area=(100, 100),
        belts=(50, 50),
        cpu=(8.0, 8.0),
        rss=(100.0, 100.0),
    )
    candidate = fixture_samples(
        strategy="candidate",
        seconds=(8.0, 8.0),
        area=(100, 101),
        belts=(50, 50),
        cpu=(6.0, 6.0),
        rss=(90.0, 90.0),
    )

    report = assess_promotion(
        baseline,
        candidate,
        required=manifest(repeat=2),
        cross=_complete_cross(baseline, candidate),
        bootstrap_seed=7,
    )

    assert not report.eligible
    assert any("100.5" in reason and "area" in reason for reason in report.reasons)


def test_fractional_belt_regression_blocks_promotion() -> None:
    baseline = fixture_samples(
        seconds=(10.0, 10.0),
        area=(100, 100),
        belts=(50, 50),
        cpu=(8.0, 8.0),
        rss=(100.0, 100.0),
    )
    candidate = fixture_samples(
        strategy="candidate",
        seconds=(8.0, 8.0),
        area=(100, 100),
        belts=(50, 51),
        cpu=(6.0, 6.0),
        rss=(90.0, 90.0),
    )

    report = assess_promotion(
        baseline,
        candidate,
        required=manifest(repeat=2),
        cross=_complete_cross(baseline, candidate),
        bootstrap_seed=7,
    )

    assert not report.eligible
    assert any("50.5" in reason and "belts" in reason for reason in report.reasons)


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
        ("runtime", "runtime"),
        ("p95", "p95"),
        ("cpu", "CPU"),
        ("rss", "RSS"),
        ("missing-cpu", "CPU metric"),
        ("missing-rss", "RSS metric"),
    ],
)
def test_every_strict_gate_failure_is_reported(mutation: str, reason: str) -> None:
    baseline, candidate = eligible_pair()
    if mutation in {"invalid", "refusal", "error", "crossfail"}:
        outcome = {
            "invalid": Outcome.INVALID,
            "refusal": Outcome.REFUSED,
            "error": Outcome.ERROR,
            "crossfail": Outcome.CROSSFAIL,
        }[mutation]
        candidate[0] = replace(
            candidate[0],
            outcome=outcome,
            metrics=None,
            buildings=0,
            detail=mutation,
        )
    elif mutation == "runtime":
        candidate = [replace(sample, seconds=sample.seconds + 3.0) for sample in baseline]
    elif mutation == "p95":
        candidate = [
            replace(candidate[0], seconds=1.0),
            replace(candidate[1], seconds=1.0),
            replace(candidate[2], seconds=20.0),
        ]
    elif mutation == "cpu":
        candidate = [replace(sample, cpu_seconds=9.0) for sample in candidate]
    elif mutation == "rss":
        candidate = [replace(sample, peak_rss_mb=110.0) for sample in candidate]
    elif mutation == "missing-cpu":
        candidate = [replace(sample, cpu_seconds=None) for sample in candidate]
    else:
        candidate = [replace(sample, peak_rss_mb=None) for sample in candidate]

    report = assess_promotion(
        baseline,
        candidate,
        required=manifest(),
        cross=_complete_cross(baseline, candidate),
        bootstrap_seed=7,
    )

    assert not report.eligible
    assert any(reason in item for item in report.reasons)


def test_identically_truncated_repeats_are_ineligible() -> None:
    baseline, candidate = eligible_pair()
    baseline.pop()
    candidate.pop()

    report = assess(baseline, candidate)

    assert not report.eligible
    assert any("required trials" in reason for reason in report.reasons)


def test_power_scope_is_part_of_the_raw_and_trial_identity() -> None:
    baseline, candidate = eligible_pair()
    candidate = [replace(sample, power=True) for sample in candidate]

    report = assess(baseline, candidate)

    assert not report.eligible
    assert any("raw sample identities" in reason for reason in report.reasons)
    assert any("required cell" in reason for reason in report.reasons)


def test_missing_or_additional_raw_candidate_is_ineligible() -> None:
    baseline, candidate = eligible_pair()
    candidate.pop()

    report = assess(baseline, candidate)

    assert not report.eligible
    assert any("raw sample identities" in reason for reason in report.reasons)


def test_invalid_nonshipping_candidate_cannot_hide_behind_a_valid_candidate() -> None:
    baseline, candidate = eligible_pair()
    baseline += fixture_samples(candidate="other")
    candidate += fixture_samples(strategy="candidate", candidate="other")
    candidate[-1] = replace(
        candidate[-1],
        outcome=Outcome.INVALID,
        metrics=None,
        buildings=0,
        detail="invalid hidden candidate",
    )

    report = assess_promotion(
        baseline,
        candidate,
        required=manifest(candidates=2),
        cross=_complete_cross(baseline, candidate),
        bootstrap_seed=7,
    )

    assert not report.eligible
    assert any("invalid" in reason for reason in report.reasons)


def test_candidate_refusal_is_compared_at_the_exact_raw_identity() -> None:
    baseline, candidate = eligible_pair()
    candidate[1] = replace(candidate[1], outcome=Outcome.REFUSED, metrics=None, buildings=0)

    report = assess(baseline, candidate)

    assert not report.eligible
    assert any("additional refusal" in reason for reason in report.reasons)


def test_baseline_refusal_can_be_resolved_by_candidate() -> None:
    baseline, candidate = eligible_pair()
    baseline[1] = replace(baseline[1], outcome=Outcome.REFUSED, metrics=None, buildings=0)

    report = assess(baseline, candidate)

    assert report.eligible


def test_old_json_null_buildings_and_missing_metrics_parses_but_cannot_pass() -> None:
    document: dict[str, object] = {
        "meta": {"a": "baseline", "b": "candidate", "power": False},
        "samples": [
            {
                "url_id": "one-cell",
                "candidate": "default",
                "strategy": strategy,
                "budget_s": 10.0,
                "trial": trial,
                "outcome": outcome,
                "seconds": seconds,
                "area": 100 if outcome == "valid" else None,
                "used_tiles": 100 if outcome == "valid" else None,
                "buildings": 1 if outcome == "valid" else None,
                "belt_tiles": 50 if outcome == "valid" else None,
                "direct_inserts": 0 if outcome == "valid" else None,
                "machines": 1 if outcome == "valid" else None,
                "detail": "legacy refusal" if outcome == "refused" else "",
            }
            for strategy, seconds, outcome in (
                ("baseline", 10.0, "valid"),
                ("candidate", 8.0, "refused"),
            )
            for trial in range(3)
        ],
    }

    loaded = samples_from_json(document)
    baseline = [sample for sample in loaded if sample.strategy == "baseline"]
    candidate = [sample for sample in loaded if sample.strategy == "candidate"]
    report = assess_promotion(
        baseline,
        candidate,
        required=manifest(),
        cross=_complete_cross(baseline, candidate),
        bootstrap_seed=7,
    )

    assert all(sample.buildings == 0 for sample in candidate)
    assert all(sample.cpu_seconds is None for sample in loaded)
    assert all(sample.peak_rss_mb is None for sample in loaded)
    assert not report.eligible
    assert any("CPU metric" in reason for reason in report.reasons)
    assert any("RSS metric" in reason for reason in report.reasons)


def test_repository_manifest_is_full_corpus_and_powered_only() -> None:
    required = repository_manifest(budgets=(10.0,), repeat=2, candidates=1)

    assert len(required.cells) == len(URL_CORPUS)
    assert all(cell.power is True for cell in required.cells)
    assert all(cell.repeat == 2 and cell.candidates == 1 for cell in required.cells)


def _persisted_row(outcome: str) -> dict[str, object]:
    valid = outcome == "valid"
    return {
        "url_id": "one-cell",
        "candidate": "default",
        "strategy": "baseline",
        "budget_s": 10.0,
        "trial": 0,
        "outcome": outcome,
        "seconds": 1.0,
        "area": 100 if valid else None,
        "used_tiles": 100 if valid else None,
        "buildings": 1 if valid else None,
        "belt_tiles": 50 if valid else None,
        "direct_inserts": 0 if valid else None,
        "machines": 1 if valid else None,
        "detail": "",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("trial", 0.9),
        ("trial", -1),
        ("trial", float("nan")),
        ("trial", float("inf")),
        ("trial", True),
        ("area", 100.5),
        ("area", -1),
        ("used_tiles", -1),
        ("belt_tiles", -1.2),
        ("direct_inserts", float("nan")),
        ("machines", float("inf")),
        ("buildings", 1.9),
        ("buildings", -1),
    ],
)
def test_persisted_integer_metrics_reject_fractional_or_negative(field: str, value: object) -> None:
    row = _persisted_row("valid")
    row[field] = value

    with pytest.raises(ValueError, match=field):
        samples_from_json({"meta": {"power": False}, "samples": [row]})


@pytest.mark.parametrize(
    "field",
    [
        "trial",
        "area",
        "used_tiles",
        "belt_tiles",
        "direct_inserts",
        "machines",
        "buildings",
    ],
)
def test_required_persisted_integer_evidence_cannot_be_omitted(field: str) -> None:
    row = _persisted_row("valid")
    del row[field]

    with pytest.raises(ValueError, match=field):
        samples_from_json({"meta": {"power": False}, "samples": [row]})


def test_null_trial_identity_is_rejected() -> None:
    row = _persisted_row("valid")
    row["trial"] = None

    with pytest.raises(ValueError, match="trial"):
        samples_from_json({"meta": {"power": False}, "samples": [row]})


def test_valid_null_belt_tiles_is_rejected_instead_of_becoming_zero() -> None:
    row = _persisted_row("valid")
    row["belt_tiles"] = None

    with pytest.raises(ValueError, match="belt_tiles"):
        samples_from_json({"meta": {"power": False}, "samples": [row]})


def test_refused_legacy_null_buildings_is_accepted_as_zero() -> None:
    row = _persisted_row("refused")

    samples = samples_from_json({"meta": {"power": False}, "samples": [row]})

    assert samples[0].outcome is Outcome.REFUSED
    assert samples[0].buildings == 0


def test_mathematically_integral_persisted_metrics_are_accepted() -> None:
    row = _persisted_row("valid")
    for field in (
        "trial",
        "area",
        "used_tiles",
        "belt_tiles",
        "direct_inserts",
        "machines",
        "buildings",
    ):
        row[field] = float(cast(int, row[field]))

    samples = samples_from_json({"meta": {"power": False}, "samples": [row]})

    assert samples[0].trial == 0
    assert samples[0].area == 100
    assert samples[0].buildings == 1


@pytest.mark.parametrize("field", ["checked", "passed"])
@pytest.mark.parametrize("bad", [0.5, -1, float("nan"), float("inf"), True, None])
def test_persisted_crossvalidation_counts_are_strict(
    field: str,
    bad: object,
) -> None:
    document: dict[str, object] = {
        "crossvalidation": {
            "available": True,
            "complete": True,
            "checked": 1,
            "passed": 1,
            "demoted": [],
            "reason": "",
        }
    }
    cross = cast(dict[str, object], document["crossvalidation"])
    cross[field] = bad

    with pytest.raises(ValueError, match=field):
        cross_summary_from_json(document)


@pytest.mark.parametrize("field", ["url_id", "candidate", "strategy"])
@pytest.mark.parametrize("bad", [None, 1, False, ""])
def test_persisted_sample_identity_strings_are_strict(field: str, bad: object) -> None:
    row = _persisted_row("valid")
    row[field] = bad

    with pytest.raises(ValueError, match=field):
        samples_from_json({"meta": {"power": False}, "samples": [row]})


@pytest.mark.parametrize("field", ["a", "b"])
@pytest.mark.parametrize("bad", [None, 1, False, ""])
def test_persisted_backend_names_are_strict(tmp_path: Path, field: str, bad: object) -> None:
    meta: dict[str, object] = {
        "a": "baseline",
        "b": "candidate",
        "repeat": 1,
        "candidates": 1,
        "budgets": [10.0],
        "power": False,
    }
    meta[field] = bad
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"meta": meta, "samples": []}))

    with pytest.raises(ValueError, match=field):
        promotion_main([str(path)])


@pytest.mark.parametrize("field", ["repeat", "candidates"])
@pytest.mark.parametrize("bad", [0.5, -1, float("nan"), float("inf"), True, None])
def test_persisted_run_counts_are_finite_positive_integers(
    tmp_path: Path,
    field: str,
    bad: object,
) -> None:
    meta: dict[str, object] = {
        "a": "baseline",
        "b": "candidate",
        "repeat": 1,
        "candidates": 1,
        "budgets": [10.0],
        "power": False,
    }
    meta[field] = bad
    path = tmp_path / "bad-count.json"
    path.write_text(json.dumps({"meta": meta, "samples": []}))

    with pytest.raises(ValueError, match=field):
        promotion_main([str(path)])


@pytest.mark.parametrize("bad", [None, 1, False, ""])
def test_manifest_url_identity_is_a_nonempty_string(bad: object) -> None:
    with pytest.raises(ValueError, match="url_id"):
        RequiredCell(cast(str, bad), 10.0, False, 1, 1)


def test_matching_malformed_baseline_and_candidate_rows_cannot_reach_the_gate() -> None:
    baseline = _persisted_row("valid")
    candidate = _persisted_row("valid")
    baseline["url_id"] = None
    candidate["url_id"] = None
    candidate["strategy"] = "candidate"

    with pytest.raises(ValueError, match="url_id"):
        samples_from_json({"meta": {"power": False}, "samples": [baseline, candidate]})
