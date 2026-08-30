from __future__ import annotations

from flab2bp.bench.report import matrix_report


def test_current_matrix_has_no_power_off_rows() -> None:
    report = matrix_report([], "baseline", "challenger")

    assert set(report.cells) == {True, False}
