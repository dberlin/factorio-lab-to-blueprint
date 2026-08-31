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
    canvas = object.__new__(freeform._Canvas)
    try:
        returned = freeform._astar(canvas, [], set(), {}, 0.0, (0, 0, 0, 0))
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


def test_install_forwards_merge_frontier_belt_prefab(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = {(1, 2, 3)}
    received: list[tuple[int, int] | None] = []

    def merge(
        *_args: object,
        belt_prefab: tuple[int, int] | None = None,
        **_kwargs: object,
    ) -> set[tuple[int, int, int]]:
        received.append(belt_prefab)
        return expected

    monkeypatch.setattr(freeform, "_merge_frontier", merge)
    restore = route_profile.install(route_profile.Tally())
    try:
        returned = freeform._merge_frontier(
            object(),  # type: ignore[arg-type]
            {},
            (),
            belt_prefab=(2001, 35),
        )
    finally:
        restore()

    assert returned is expected
    assert received == [(2001, 35)]
