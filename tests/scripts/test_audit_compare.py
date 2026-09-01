from __future__ import annotations

import json
from pathlib import Path

from scripts import audit_compare


def _row(
    strategy: str, url_id: str, spec_index: int, status: str, area: float, seconds: float
) -> dict[str, object]:
    return {
        "strategy": strategy,
        "url_id": url_id,
        "spec_index": spec_index,
        "spec_label": f"label-{spec_index}",
        "power": True,
        "budget": 30.0,
        "status": status,
        "area": area,
        "seconds": seconds,
        "detail": "",
    }


def test_compare_pairs_cells_and_reports_area_ratio() -> None:
    baseline = [
        _row("freeform", "plastic", 0, "CLEAN", 100.0, 5.0),
        _row("freeform", "plastic", 1, "CLEAN", 200.0, 6.0),
        _row("sequence-pair", "plastic", 0, "REFUSED", 0.0, 30.0),
    ]
    candidate = [
        _row("freeform", "plastic", 0, "CLEAN", 101.0, 2.0),
        _row("freeform", "plastic", 1, "CLEAN", 190.0, 3.0),
        _row("sequence-pair", "plastic", 0, "CLEAN", 150.0, 12.0),
    ]

    verdict = audit_compare.compare(baseline, candidate, noise_area=0.013, p95_seconds=30.0)

    assert verdict.candidate_clean == 3
    assert verdict.candidate_refused == 0
    assert verdict.candidate_invalid == 0
    assert verdict.candidate_crashed == 0
    assert verdict.paired_cells == 2
    # geometric mean of 101/100 and 190/200
    assert abs(verdict.area_ratio - ((1.01 * 0.95) ** 0.5)) < 1e-9
    assert verdict.p95_seconds == 12.0
    assert verdict.passed


def test_compare_fails_on_refusal_invalid_or_area_regression() -> None:
    baseline = [_row("freeform", "plastic", 0, "CLEAN", 100.0, 5.0)]

    refused = audit_compare.compare(
        baseline,
        [_row("freeform", "plastic", 0, "REFUSED", 0.0, 30.0)],
        noise_area=0.013,
        p95_seconds=30.0,
    )
    assert not refused.passed
    assert "REFUSED" in refused.reasons[0]

    invalid = audit_compare.compare(
        baseline,
        [_row("freeform", "plastic", 0, "INVALID", 90.0, 5.0)],
        noise_area=0.013,
        p95_seconds=30.0,
    )
    assert not invalid.passed

    larger = audit_compare.compare(
        baseline,
        [_row("freeform", "plastic", 0, "CLEAN", 102.0, 5.0)],
        noise_area=0.013,
        p95_seconds=30.0,
    )
    assert not larger.passed
    assert "area" in larger.reasons[0]

    slow = audit_compare.compare(
        baseline,
        [_row("freeform", "plastic", 0, "CLEAN", 100.0, 31.0)],
        noise_area=0.013,
        p95_seconds=30.0,
    )
    assert not slow.passed
    assert "p95" in slow.reasons[0]


def test_cli_reads_jsonl_and_exits_nonzero_on_failure(tmp_path: Path) -> None:
    baseline = tmp_path / "base.jsonl"
    candidate = tmp_path / "cand.jsonl"
    baseline.write_text(json.dumps(_row("freeform", "plastic", 0, "CLEAN", 100.0, 5.0)) + "\n")
    candidate.write_text(json.dumps(_row("freeform", "plastic", 0, "REFUSED", 0.0, 30.0)) + "\n")

    assert audit_compare.main([str(baseline), str(candidate)]) == 1

    candidate.write_text(json.dumps(_row("freeform", "plastic", 0, "CLEAN", 100.0, 5.0)) + "\n")
    assert audit_compare.main([str(baseline), str(candidate)]) == 0
