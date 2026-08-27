"""The winner rule, and the guards that keep it honest.

The rule is lexicographic on purpose -- validity, then density, then time. A
weighted sum would invite tuning the weights until the preferred strategy wins.
"""

from __future__ import annotations

import math

import pytest

from flab2bp.bench.scoring import (
    DENSITY_DEADBAND,
    Verdict,
    compare,
    geometric_mean,
)
from flab2bp.bench.types import CellResult


def _cell(
    strategy: str,
    url_id: str,
    *,
    area: int,
    seconds: float = 1.0,
    valid: bool = True,
) -> CellResult:
    return CellResult(
        strategy=strategy,
        url_id=url_id,
        candidate="no-proliferator",
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
        solve_seconds=seconds,
        hit_time_budget=False,
        fallback_used=False,
        solver_status="OPTIMAL",
        valid=valid,
        errors=0 if valid else 1,
        warnings=0,
        skipped_checks=(),
        error_checks=(),
    )


def test_geometric_mean_is_not_dominated_by_one_huge_case() -> None:
    ratios = [0.5, 0.5, 100.0]
    assert geometric_mean(ratios) < sum(ratios) / len(ratios)
    assert math.isclose(geometric_mean([2.0, 8.0]), 4.0)


def test_geometric_mean_of_nothing_is_one() -> None:
    assert geometric_mean([]) == 1.0


def test_validity_beats_density_outright() -> None:
    """A dense invalid blueprint is worth nothing."""
    a = [_cell("sequence-pair", "u1", area=1000), _cell("sequence-pair", "u2", area=1000)]
    b = [_cell("freeform", "u1", area=10), _cell("freeform", "u2", area=10, valid=False)]
    verdict = compare(a + b, "sequence-pair", "freeform")
    assert verdict.winner == "sequence-pair"
    assert verdict.reason is Verdict.Reason.VALIDITY


def test_density_wins_when_margin_exceeds_deadband() -> None:
    a = [_cell("sequence-pair", "u1", area=1000)]
    b = [_cell("freeform", "u1", area=500)]
    verdict = compare(a + b, "sequence-pair", "freeform")
    assert verdict.winner == "freeform"
    assert verdict.reason is Verdict.Reason.DENSITY


def test_density_tie_inside_deadband_falls_through_to_time() -> None:
    """A 1% area edge is noise, not a win."""
    a = [_cell("sequence-pair", "u1", area=1000, seconds=0.5)]
    b = [_cell("freeform", "u1", area=990, seconds=50.0)]
    verdict = compare(a + b, "sequence-pair", "freeform")
    assert verdict.reason is Verdict.Reason.TIME
    assert verdict.winner == "sequence-pair"
    assert abs(verdict.area_ratio - 0.99) < 1e-9
    assert 1 - verdict.area_ratio < DENSITY_DEADBAND


def test_ratio_uses_only_urls_where_both_strategies_succeeded() -> None:
    a = [_cell("sequence-pair", "u1", area=100), _cell("sequence-pair", "u2", area=100)]
    b = [_cell("freeform", "u1", area=50), _cell("freeform", "u2", area=1, valid=False)]
    verdict = compare(a + b, "sequence-pair", "freeform")
    # u2 is excluded from the ratio, so the ratio is u1's alone.
    assert math.isclose(verdict.area_ratio, 0.5)
    assert verdict.comparable == 1


def test_missing_strategy_is_reported_not_crashed() -> None:
    """Strategy B may not exist yet; the harness must still produce a report."""
    a = [_cell("sequence-pair", "u1", area=100)]
    verdict = compare(a, "sequence-pair", "freeform")
    assert verdict.comparable == 0
    assert verdict.reason is Verdict.Reason.INCOMPARABLE
    assert verdict.winner is None


@pytest.mark.parametrize("ratio", [0.98, 1.02])
def test_deadband_is_symmetric(ratio: float) -> None:
    a = [_cell("sequence-pair", "u1", area=1000, seconds=1.0)]
    b = [_cell("freeform", "u1", area=int(1000 * ratio), seconds=2.0)]
    verdict = compare(a + b, "sequence-pair", "freeform")
    assert verdict.reason is Verdict.Reason.TIME
