from __future__ import annotations

from flab2bp.bench.report import matrix_report


def test_current_matrix_has_no_power_off_rows() -> None:
    report = matrix_report([], "baseline", "challenger")

    assert set(report.cells) == {True, False}


def test_winning_candidates_preserves_ties_and_interleaved_tally_order() -> None:
    from dataclasses import replace

    from flab2bp.bench.report import _winning_candidates
    from tests.bench.test_scoring import _cell

    cells = [
        replace(_cell("a", "u", area=1, valid=False), candidate="invalid"),
        replace(_cell("b", "v", area=30), candidate="first"),
        replace(_cell("a", "u", area=20), candidate="second"),
        replace(_cell("b", "v", area=30), candidate="tied"),
        replace(_cell("a", "w", area=40), candidate="first"),
    ]
    lines = _winning_candidates(cells)
    assert "| v | b | first | 30 |" in lines
    assert "| u | a | second | 20 |" in lines
    assert "Candidate win tally: {'first': 2, 'second': 1}" in lines
