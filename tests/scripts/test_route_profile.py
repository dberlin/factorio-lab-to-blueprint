from __future__ import annotations

import pytest

from flab2bp.layout import freeform
from flab2bp.layout.route_feedback import RouteFailureKind
from scripts import route_profile


def _run_profiled_astar(
    monkeypatch: pytest.MonkeyPatch,
    result: freeform._PathSearchResult,
) -> tuple[freeform._PathSearchResult, route_profile.Tally]:
    monkeypatch.setattr(freeform, "_astar", lambda *args, **kwargs: result)
    tally = route_profile.Tally()
    restore = route_profile.install(tally)
    try:
        returned = freeform._astar(None, [], set(), {}, 0.0, (0, 0, 0, 0))
    finally:
        restore()
    return returned, tally


def test_install_records_successful_path_result(monkeypatch: pytest.MonkeyPatch) -> None:
    result = freeform._PathSearchResult(
        path=((0, 0, 0),),
        kind=None,
        wall=(),
        expansions=7,
    )

    returned, tally = _run_profiled_astar(monkeypatch, result)

    assert returned is result
    assert tally.astar_hit == 1
    assert tally.astar_none == 0
    assert tally.path_cells == 1
    assert tally.expansions == 7


def test_install_records_failed_path_result(monkeypatch: pytest.MonkeyPatch) -> None:
    result = freeform._PathSearchResult(
        path=None,
        kind=RouteFailureKind.SEALED_POCKET,
        wall=(),
        expansions=11,
    )

    returned, tally = _run_profiled_astar(monkeypatch, result)

    assert returned is result
    assert tally.astar_hit == 0
    assert tally.astar_none == 1
    assert tally.path_cells == 0
    assert tally.expansions == 11
