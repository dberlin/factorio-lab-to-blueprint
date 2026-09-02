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


def test_compare_fails_when_the_candidate_never_ran_a_cell() -> None:
    """A cell the candidate lacks is a FAILURE, not an absence of evidence.

    Walking the candidate alone let a run that died part-way through -- or a
    file truncated in transit -- present its survivors, find nothing to
    disagree with, and print PASS.
    """
    baseline = [
        _row("freeform", "plastic", 0, "CLEAN", 100.0, 5.0),
        _row("freeform", "plastic", 1, "CLEAN", 200.0, 6.0),
        _row("sequence-pair", "graphene", 0, "CLEAN", 300.0, 7.0),
    ]
    # Short one row, and every row it DOES have is clean, fast and no larger.
    candidate = [
        _row("freeform", "plastic", 0, "CLEAN", 100.0, 5.0),
        _row("freeform", "plastic", 1, "CLEAN", 200.0, 6.0),
    ]

    verdict = audit_compare.compare(
        baseline, candidate, noise_area=0.013, p95_seconds=30.0, expect_cells=None
    )

    assert not verdict.passed
    assert verdict.reasons == ("MISSING: sequence-pair graphene/label-0",)


def test_compare_counts_the_candidate_rows_against_expect_cells() -> None:
    """The guard from the other side, for when the baseline is short too."""
    baseline = [_row("freeform", "plastic", 0, "CLEAN", 100.0, 5.0)]
    candidate = [_row("freeform", "plastic", 0, "CLEAN", 100.0, 5.0)]

    matching = audit_compare.compare(
        baseline, candidate, noise_area=0.013, p95_seconds=30.0, expect_cells=1
    )
    assert matching.passed

    short = audit_compare.compare(
        baseline, candidate, noise_area=0.013, p95_seconds=30.0, expect_cells=72
    )
    assert not short.passed
    assert short.reasons == ("candidate has 1 rows, expected 72",)

    disabled = audit_compare.compare(
        baseline, candidate, noise_area=0.013, p95_seconds=30.0, expect_cells=None
    )
    assert disabled.passed


def test_cli_expect_cells_defaults_to_the_full_corpus(tmp_path: Path) -> None:
    baseline = tmp_path / "base.jsonl"
    candidate = tmp_path / "cand.jsonl"
    clean = json.dumps(_row("freeform", "plastic", 0, "CLEAN", 100.0, 5.0)) + "\n"
    baseline.write_text(clean)
    candidate.write_text(clean)

    # One row against the default expectation of 72 is a failure...
    assert audit_compare.main([str(baseline), str(candidate)]) == 1
    # ...and saying so explicitly, or switching the guard off, is not.
    assert audit_compare.main([str(baseline), str(candidate), "--expect-cells", "1"]) == 0
    assert audit_compare.main([str(baseline), str(candidate), "--expect-cells", "0"]) == 0


def test_cli_reads_jsonl_and_exits_nonzero_on_failure(tmp_path: Path) -> None:
    baseline = tmp_path / "base.jsonl"
    candidate = tmp_path / "cand.jsonl"
    baseline.write_text(json.dumps(_row("freeform", "plastic", 0, "CLEAN", 100.0, 5.0)) + "\n")
    candidate.write_text(json.dumps(_row("freeform", "plastic", 0, "REFUSED", 0.0, 30.0)) + "\n")

    # `--expect-cells 1` because these fixtures are one cell, not the corpus.
    assert audit_compare.main([str(baseline), str(candidate), "--expect-cells", "1"]) == 1

    candidate.write_text(json.dumps(_row("freeform", "plastic", 0, "CLEAN", 100.0, 5.0)) + "\n")
    assert audit_compare.main([str(baseline), str(candidate), "--expect-cells", "1"]) == 0
