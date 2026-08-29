from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path
from typing import cast

import pytest

from flab2bp.layout import finalize
from scripts import audit, benchmark_projection
from scripts.benchmark_projection import BenchmarkResult, CaseResult, run_benchmark


def test_benchmark_result_has_stable_cases_and_counters() -> None:
    result = run_benchmark(samples=2)

    assert set(result["cases"]) == {"small", "medium", "large"}
    for case in result["cases"].values():
        assert case["median_s"] >= 0.0
        assert case["p95_s"] >= case["median_s"]
        assert set(case) >= {
            "frame_candidates",
            "projections",
            "collider_pairs",
            "power_pairs",
            "sorters",
            "area",
            "sorter_result_cache_hits",
            "static_result_cache_hits",
            "power_result_cache_hits",
            "addon_result_cache_hits",
            "addon_splitter_result_cache_hits",
            "invariant_cache_hits",
            "pair_cache_hits",
            "projection_cache_hits",
        }
        assert isinstance(case["refused"], bool)
        assert bool(case["refusal_checks"]) is case["refused"]
        assert case["frame_candidates"] >= 0
        assert case["projections"] >= 0
        assert case["collider_pairs"] >= 0
        assert case["power_pairs"] >= 0
        assert case["sorters"] >= 0
        assert case["invariant_cache_hits"] >= 0
        assert case["pair_cache_hits"] >= 0
        assert case["projection_cache_hits"] >= 0
        assert case["sorter_result_cache_hits"] >= 0
        assert case["static_result_cache_hits"] >= 0

        assert case["power_result_cache_hits"] >= 0
        assert case["addon_result_cache_hits"] >= 0
        assert case["addon_splitter_result_cache_hits"] >= 0

def test_fixture_loader_returns_unfinalized_geometry() -> None:
    for name in ("small", "medium", "large"):
        placement = benchmark_projection._load_case(name)
        assert "area_segments" not in placement.stats
        assert "band_rotated" not in placement.stats
        assert placement.frame is None


def test_time_case_uses_inclusive_p95(monkeypatch: pytest.MonkeyPatch) -> None:
    placement = benchmark_projection._load_case("small")
    readings = iter(
        (
            0,
            1_000_000_000,
            2_000_000_000,
            4_000_000_000,
            5_000_000_000,
            8_000_000_000,
            9_000_000_000,
            13_000_000_000,
        )
    )
    monkeypatch.setattr(time, "perf_counter_ns", lambda: next(readings))
    monkeypatch.setattr(
        finalize,
        "finalize_placement",
        lambda placement, policy: placement,
    )

    result = benchmark_projection._time_case(placement, samples=4)

    assert result["median_s"] == 2.5
    assert result["p95_s"] == 4.0


def test_time_case_records_refusal_and_work_counters() -> None:
    placement = benchmark_projection._load_case("small")

    result = benchmark_projection._time_case(placement, samples=1)

    assert result["refused"] is True
    assert result["refusal_checks"] == ["geom.collide"]
    assert result["frame_candidates"] > 0
    assert result["projections"] > 0
    assert result["invariant_cache_hits"] > 0
    assert result["pair_cache_hits"] > 0
    assert result["projection_cache_hits"] > 0
    assert result["collider_pairs"] > 0
    assert result["sorter_result_cache_hits"] > 0
    assert result["static_result_cache_hits"] > 0
    assert result["area"] == placement.area
    assert result["power_result_cache_hits"] > 0
    assert result["addon_result_cache_hits"] > 0
    assert result["addon_splitter_result_cache_hits"] > 0


def test_cli_writes_stable_sorted_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixed = BenchmarkResult(
        cases={
            "small": CaseResult(
                median_s=0.25,
                p95_s=0.5,
                frame_candidates=0,
                projections=0,
                collider_pairs=0,
                power_pairs=0,
                sorters=0,
                area=12,
                invariant_cache_hits=0,
                pair_cache_hits=0,
                projection_cache_hits=0,
                sorter_result_cache_hits=0,
                static_result_cache_hits=0,
                power_result_cache_hits=0,
                addon_result_cache_hits=0,
                addon_splitter_result_cache_hits=0,
                refused=False,
                refusal_checks=[],
            )
        }
    )
    monkeypatch.setattr(benchmark_projection, "run_benchmark", lambda samples: fixed)
    output = tmp_path / "result.json"

    assert benchmark_projection.main(["--samples", "2", "--output", str(output)]) == 0

    expected = json.dumps(fixed, indent=2, sort_keys=True) + "\n"
    assert output.read_text(encoding="utf-8") == expected


def test_audit_json_record_includes_build_wall_time_and_finalization_counters() -> None:
    job = audit.Job(
        strategy="freeform",
        url_id="graphene",
        url="https://example.invalid",
        tier="small",
        spec_index=0,
        candidates=1,
        budget=4.0,
        power=True,
        workers=1,
    )
    result = audit.Result(
        job=job,
        status="CLEAN",
        spec_label="no-proliferator",
        detail="",
        checks=(),
        seconds=1.25,
        area=42.0,
        projection_frame_candidates=2,
        projection_count=3,
        projection_collider_pairs=5,
        projection_power_pairs=7,
        projection_sorters=11,
    )
    tallies = {"freeform": audit.Tally()}
    audit._JSONL.clear()

    audit.record(tallies, result)

    record = audit._JSONL[0]
    assert record["build_wall_time_s"] == 1.25
    assert {
        key: cast(int, record[key])
        for key in (
            "projection_frame_candidates",
            "projection_count",
            "projection_collider_pairs",
            "projection_power_pairs",
            "projection_sorters",
        )
    } == {
        "projection_frame_candidates": 2,
        "projection_count": 3,
        "projection_collider_pairs": 5,
        "projection_power_pairs": 7,
        "projection_sorters": 11,
    }
    assert tallies["freeform"].checks == Counter()


def _case(*, median_s: float, p95_s: float, area: int) -> CaseResult:
    return CaseResult(
        median_s=median_s,
        p95_s=p95_s,
        frame_candidates=2,
        projections=3,
        collider_pairs=5,
        power_pairs=7,
        sorters=11,
        area=area,
        invariant_cache_hits=0,
        pair_cache_hits=0,
        projection_cache_hits=0,
        sorter_result_cache_hits=0,
        static_result_cache_hits=0,
        power_result_cache_hits=0,
        addon_result_cache_hits=0,
        addon_splitter_result_cache_hits=0,
        refused=False,
        refusal_checks=[],
    )


def test_projection_comparison_applies_added_p95_threshold_per_case() -> None:
    baseline = BenchmarkResult(
        cases={
            "small": _case(median_s=1.0, p95_s=2.0, area=100),
            "medium": _case(median_s=10.0, p95_s=20.0, area=200),
            "large": _case(median_s=100.0, p95_s=200.0, area=300),
        }
    )
    after = BenchmarkResult(
        cases={
            "small": _case(median_s=1.1, p95_s=3.0, area=101),
            "medium": _case(median_s=8.0, p95_s=21.000_001, area=202),
            "large": _case(median_s=90.0, p95_s=150.0, area=303),
        }
    )

    comparison = benchmark_projection.compare_projection_results(baseline, after)

    assert comparison["passed"] is False
    assert set(comparison["cases"]) == {"small", "medium", "large"}
    assert comparison["cases"]["small"]["p95_delta_s"] == 1.0
    assert comparison["cases"]["small"]["threshold_passed"] is True
    assert comparison["cases"]["medium"]["p95_delta_s"] == pytest.approx(1.000_001)
    assert comparison["cases"]["medium"]["threshold_passed"] is False
    assert comparison["cases"]["large"]["threshold_passed"] is True
    assert comparison["cases"]["medium"]["baseline"] == baseline["cases"]["medium"]
    assert comparison["cases"]["medium"]["after"] == after["cases"]["medium"]


def _build_record(
    *,
    strategy: str,
    wall_time_s: float,
    area: float,
    url_id: str = "graphene",
    spec_index: int = 0,
    spec_label: str = "all-products",
    power: bool = False,
    budget: float = 4.0,
    status: str = "CLEAN",
) -> dict[str, object]:
    return {
        "strategy": strategy,
        "url_id": url_id,
        "spec_index": spec_index,
        "spec_label": spec_label,
        "power": power,
        "budget": budget,
        "status": status,
        "area": area,
        "build_wall_time_s": wall_time_s,
        "projection_frame_candidates": 2,
        "projection_count": 3,
        "projection_collider_pairs": 5,
        "projection_power_pairs": 7,
        "projection_sorters": 11,
    }


def test_build_comparison_uses_deadline_grace_for_unchanged_semantics() -> None:
    baseline = [
        _build_record(strategy="freeform", wall_time_s=0.2, area=100.0),
        _build_record(strategy="sequence-pair", wall_time_s=0.2, area=200.0),
    ]
    after = [
        _build_record(strategy="freeform", wall_time_s=9.0, area=100.0),
        _build_record(strategy="sequence-pair", wall_time_s=9.000_002, area=200.0),
    ]

    comparison = benchmark_projection.compare_build_results(baseline, after)

    assert comparison["passed"] is False
    equality, excess = comparison["cases"]
    assert equality["gate_kind"] == "audit_deadline_grace"
    assert equality["semantic_change_reasons"] == []
    assert equality["governing_limit_s"] == 9.0
    assert equality["measured_wall_s"] == 9.0
    assert equality["historical_regression"] is True
    assert equality["wall_time_delta_ratio"] == 44.0
    assert equality["gate_passed"] is True
    assert excess["historical_regression"] is True
    assert excess["gate_passed"] is False


def test_build_comparison_uses_deadline_grace_for_changed_semantics() -> None:
    baseline = [
        _build_record(strategy="freeform", wall_time_s=0.2, area=100.0),
        _build_record(strategy="sequence-pair", wall_time_s=0.2, area=200.0),
    ]
    after = [
        _build_record(
            strategy="freeform",
            wall_time_s=9.0,
            area=0.0,
            status="REFUSED",
        ),
        _build_record(
            strategy="sequence-pair",
            wall_time_s=9.000_002,
            area=201.0,
        ),
    ]

    comparison = benchmark_projection.compare_build_results(baseline, after)

    assert comparison["passed"] is False
    equality, excess = comparison["cases"]
    assert equality["gate_kind"] == "audit_deadline_grace"
    assert equality["semantic_change_reasons"] == [
        "status: CLEAN -> REFUSED",
        "area: 100.0 -> 0.0",
    ]
    assert equality["governing_limit_s"] == 9.0
    assert equality["measured_wall_s"] == 9.0
    assert equality["historical_regression"] is True
    assert equality["wall_time_delta_ratio"] == 44.0
    assert equality["gate_passed"] is True
    assert excess["semantic_change_reasons"] == ["area: 200.0 -> 201.0"]
    assert excess["historical_regression"] is True
    assert excess["gate_passed"] is False


@pytest.mark.parametrize(
    ("field", "changed"),
    (
        ("strategy", "sequence-pair"),
        ("url_id", "plastic"),
        ("spec_index", 1),
        ("spec_label", "no-proliferator"),
        ("power", True),
        ("budget", 5.0),
    ),
)
def test_build_comparison_rejects_every_identity_mismatch(
    field: str,
    changed: object,
) -> None:
    baseline = _build_record(strategy="freeform", wall_time_s=1.0, area=100.0)
    after = baseline.copy()
    after[field] = changed

    with pytest.raises(ValueError, match="build cases differ"):
        benchmark_projection.compare_build_results([baseline], [after])


def test_build_comparison_rejects_missing_extra_and_duplicate_cases() -> None:
    first = _build_record(strategy="freeform", wall_time_s=1.0, area=100.0)
    second = _build_record(
        strategy="sequence-pair",
        wall_time_s=1.0,
        area=100.0,
    )

    with pytest.raises(ValueError, match="build cases differ"):
        benchmark_projection.compare_build_results([first, second], [first])
    with pytest.raises(ValueError, match="build cases differ"):
        benchmark_projection.compare_build_results([first], [first, second])
    with pytest.raises(ValueError, match="duplicates build case"):
        benchmark_projection.compare_build_results([first], [first, first.copy()])
    with pytest.raises(ValueError, match="duplicates build case"):
        benchmark_projection.compare_build_results([first, first.copy()], [first])


def test_build_comparison_keeps_exact_historical_boundary_diagnostic() -> None:
    baseline = [
        _build_record(
            strategy="freeform",
            wall_time_s=10.0,
            area=100.0,
            budget=20.0,
        ),
        _build_record(
            strategy="sequence-pair",
            wall_time_s=10.0,
            area=100.0,
            budget=20.0,
        ),
    ]
    after = [
        _build_record(
            strategy="freeform",
            wall_time_s=11.0,
            area=100.0,
            budget=20.0,
        ),
        _build_record(
            strategy="sequence-pair",
            wall_time_s=11.000_001,
            area=100.0,
            budget=20.0,
        ),
    ]

    comparison = benchmark_projection.compare_build_results(baseline, after)

    equality, excess = comparison["cases"]
    assert equality["wall_time_delta_ratio"] == pytest.approx(0.1)
    assert equality["historical_regression"] is False
    assert excess["wall_time_delta_ratio"] == pytest.approx(0.100_000_1)
    assert excess["historical_regression"] is True
    assert equality["gate_kind"] == excess["gate_kind"] == "audit_deadline_grace"
    assert equality["governing_limit_s"] == excess["governing_limit_s"] == 25.0
    assert equality["gate_passed"] is excess["gate_passed"] is True


def test_cli_combines_projection_and_build_per_case_comparisons(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projection_baseline = BenchmarkResult(
        cases={"small": _case(median_s=1.0, p95_s=2.0, area=100)}
    )
    projection_after = BenchmarkResult(
        cases={"small": _case(median_s=1.1, p95_s=2.2, area=101)}
    )
    monkeypatch.setattr(
        benchmark_projection,
        "run_benchmark",
        lambda samples: projection_after,
    )
    baseline_path = tmp_path / "portable-band-baseline.json"
    after_path = tmp_path / "portable-band-after.json"
    baseline_path.write_text(json.dumps(projection_baseline), encoding="utf-8")

    assert (
        benchmark_projection.main(
            [
                "--samples",
                "20",
                "--baseline",
                str(baseline_path),
                "--output",
                str(after_path),
            ]
        )
        == 0
    )

    build_baseline_path = tmp_path / "portable-band-build-baseline.json"
    build_after_path = tmp_path / "portable-band-build-after.json"
    comparison_path = tmp_path / "portable-band-comparison.json"
    build_baseline_path.write_text(
        json.dumps(_build_record(strategy="freeform", wall_time_s=10.0, area=100.0))
        + "\n",
        encoding="utf-8",
    )
    build_after_path.write_text(
        json.dumps(_build_record(strategy="freeform", wall_time_s=12.0, area=101.0))
        + "\n",
        encoding="utf-8",
    )

    assert (
        benchmark_projection.main(
            [
                "--compare-builds",
                str(build_baseline_path),
                str(build_after_path),
                "--output",
                str(comparison_path),
            ]
        )
        == 0
    )

    after_payload = json.loads(after_path.read_text(encoding="utf-8"))
    comparison_payload = json.loads(comparison_path.read_text(encoding="utf-8"))
    assert after_payload["cases"] == projection_after["cases"]
    assert after_payload["projection_comparison"]["passed"] is True
    assert comparison_payload["passed"] is False
    assert comparison_payload["projection"]["cases"]["small"]["after"]["area"] == 101
    assert comparison_payload["builds"]["cases"][0]["gate_passed"] is False
