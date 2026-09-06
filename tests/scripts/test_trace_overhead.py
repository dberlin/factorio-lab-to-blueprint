from __future__ import annotations

from scripts.trace_overhead import CELLS, WallResult, wall_verdict


def test_the_three_named_cells_exist_with_their_budgets() -> None:
    assert set(CELLS) == {"um60", "qc180", "belt3"}
    assert CELLS["um60"].entry_id == "universe-matrix"
    assert CELLS["um60"].budget_s == 60.0
    assert CELLS["qc180"].entry_id == "quantum-chip"
    assert CELLS["qc180"].budget_s == 180.0
    assert CELLS["belt3"].budget_s == 60.0


def test_wall_verdict_passes_at_exactly_one_percent() -> None:
    result = WallResult(cell="um60", off_s=[100.0] * 5, on_s=[101.0] * 5)
    assert wall_verdict(result) == "PASS"


def test_wall_verdict_fails_above_one_percent() -> None:
    result = WallResult(cell="um60", off_s=[100.0] * 5, on_s=[101.5] * 5)
    assert wall_verdict(result) == "FAIL"


def test_overlapping_spreads_are_reported_as_not_separated_and_are_a_fail() -> None:
    # A verdict whose spreads straddle the 1% line has not measured anything.
    result = WallResult(cell="um60", off_s=[90.0, 110.0], on_s=[91.0, 111.0])
    assert wall_verdict(result) == "NOT SEPARATED"


def test_purity_compares_area_belt_tiles_and_the_refusal_ledger() -> None:
    from scripts.trace_overhead import purity_verdict

    off = {"attempts": [("all-products", "freeform", 2244, 611)], "refused": []}
    on = {"attempts": [("all-products", "freeform", 2244, 611)], "refused": []}
    assert purity_verdict(off, on) == "PASS"
    on_bad = {"attempts": [("all-products", "freeform", 2246, 611)], "refused": []}
    assert purity_verdict(off, on_bad) == "FAIL"
