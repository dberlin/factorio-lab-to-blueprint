"""Regression mode: the harness doubles as a guard once a winner is picked."""

from __future__ import annotations

from pathlib import Path
from typing import TypedDict

from pydantic import TypeAdapter

from flab2bp.bench.regression import (
    AREA_TOLERANCE,
    Regression,
    check_against_baseline,
    write_baseline,
)
from flab2bp.bench.types import CellResult


class _BaselineEntry(TypedDict):
    area: int


class _BaselinePayload(TypedDict):
    entries: dict[str, _BaselineEntry]


_BASELINE_ADAPTER = TypeAdapter(_BaselinePayload)


def _cell(url_id: str, *, area: int, valid: bool = True) -> CellResult:
    return CellResult(
        strategy="sequence-pair",
        url_id=url_id,
        candidate="free-proliferation",
        power=True,
        area=area,
        used_tiles=area,
        width=area,
        height=1,
        machines=1,
        belt_tiles=0,
        sorters=0,
        direct_inserts=0,
        towers=0,
        altitude_levels=1,
        solve_seconds=1.0,
        hit_time_budget=False,
        fallback_used=False,
        solver_status="OPTIMAL",
        valid=valid,
        errors=0 if valid else 1,
        warnings=0,
        skipped_checks=(),
        error_checks=(),
    )


def test_unchanged_area_passes(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    write_baseline([_cell("u1", area=100)], baseline)
    result = check_against_baseline([_cell("u1", area=100)], baseline)
    assert result.ok
    assert not result.regressions


def test_area_growth_beyond_tolerance_fails(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    write_baseline([_cell("u1", area=100)], baseline)
    grown = int(100 * (1 + AREA_TOLERANCE * 2)) + 1
    result = check_against_baseline([_cell("u1", area=grown)], baseline)
    assert not result.ok
    assert any(r.kind is Regression.Kind.AREA for r in result.regressions)


def test_area_growth_inside_tolerance_passes(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    write_baseline([_cell("u1", area=1000)], baseline)
    result = check_against_baseline([_cell("u1", area=1010)], baseline)
    assert result.ok


def test_validity_regression_has_zero_tolerance(tmp_path: Path) -> None:
    """Area may wobble a little. Validity may not wobble at all."""
    baseline = tmp_path / "baseline.json"
    write_baseline([_cell("u1", area=100)], baseline)
    result = check_against_baseline([_cell("u1", area=90, valid=False)], baseline)
    assert not result.ok
    assert any(r.kind is Regression.Kind.VALIDITY for r in result.regressions)


def test_improvement_notices_but_does_not_fail(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    write_baseline([_cell("u1", area=1000)], baseline)
    result = check_against_baseline([_cell("u1", area=500)], baseline)
    assert result.ok
    assert result.improvements
    assert "re-baseline" in result.summary().lower()


def test_baseline_roundtrips_as_json(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    write_baseline([_cell("u1", area=100), _cell("u2", area=200)], baseline)
    payload = _BASELINE_ADAPTER.validate_json(baseline.read_bytes())
    assert payload["entries"]["u1"]["area"] == 100
    assert payload["entries"]["u2"]["area"] == 200


def test_new_entry_absent_from_baseline_is_not_a_regression(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    write_baseline([_cell("u1", area=100)], baseline)
    result = check_against_baseline([_cell("u1", area=100), _cell("u2", area=50)], baseline)
    assert result.ok
    assert "u2" in result.summary()
