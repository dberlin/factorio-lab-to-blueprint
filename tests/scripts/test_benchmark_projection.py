from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import cast

import pytest

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
        }
        assert case["frame_candidates"] == 0
        assert case["projections"] == 0
        assert case["collider_pairs"] == 0
        assert case["power_pairs"] == 0
        assert case["sorters"] == 0


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
    monkeypatch.setattr(benchmark_projection.time, "perf_counter_ns", lambda: next(readings))

    result = benchmark_projection._time_case(placement, samples=4)

    assert result["median_s"] == 2.5
    assert result["p95_s"] == 4.0


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
