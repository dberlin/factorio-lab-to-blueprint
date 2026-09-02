from __future__ import annotations

import os
from collections.abc import Callable, Collection, Mapping
from typing import Any

import pytest

import flab2bp.layout.freeform as freeform_module
from flab2bp.layout import route_kernel
from flab2bp.layout.band_policy import BandPolicy
from flab2bp.layout.base import NoValidLayout
from flab2bp.layout.freeform import FreeformLayout, _PathSearchResult
from flab2bp.layout.route_feedback import RouteFailureKind
from flab2bp.spec import BuildSpec
from scripts.route_bench import _snapshot
from tests.layout.test_freeform import plastic_spec, two_stage_spec

Cell = tuple[int, int, int]
Case = dict[str, Any]


def _capture_searches(spec: BuildSpec, budget_s: float) -> list[Case]:
    """Replayable snapshots of every real search one Freeform lay_out makes."""
    original = freeform_module._astar
    cases: list[Case] = []

    def spy(
        canvas: Any,
        starts: list[Cell],
        goals: set[Cell],
        history: dict[Cell, float],
        pressure: float,
        bounds: tuple[int, int, int, int],
        budget: dict[str, int] | None = None,
        deadline: float | None = None,
        blame: dict[Cell, float] | None = None,
        grid: Any = None,
        owned_starts: Collection[Cell] = (),
        released_starts: Collection[Cell] = (),
        forbidden: Collection[Cell] = (),
        blocking_owners: Mapping[Cell, int] | None = None,
    ) -> _PathSearchResult:
        shot_canvas, shot_grid, shot_hist = _snapshot(canvas, grid, history)
        cases.append(
            {
                "canvas": shot_canvas,
                "grid": shot_grid,
                "history": shot_hist,
                "starts": list(starts),
                "goals": set(goals),
                "pressure": pressure,
                "bounds": bounds,
                "owned_starts": tuple(owned_starts),
                "released_starts": tuple(released_starts),
                "forbidden": tuple(forbidden),
                "blocking_owners": None if blocking_owners is None else dict(blocking_owners),
            }
        )
        return original(
            canvas, starts, goals, history, pressure, bounds, budget, deadline, blame,
            grid, owned_starts, released_starts, forbidden, blocking_owners,
        )

    freeform_module._astar = spy
    try:
        FreeformLayout(band_policy=BandPolicy("portable"), workers=1).lay_out(
            spec, time_budget_s=budget_s
        )
    except NoValidLayout:
        pass
    finally:
        freeform_module._astar = original
    return cases


def _require_both_backends() -> Callable[..., object]:
    """The compiled loop, or skip -- but only when it was switched OFF on purpose.

    A comparison of the two backends needs both, and ``FLAB2BP_ROUTE_KERNEL=python``
    is a deliberate request for one.  Anything else missing the extension is a
    build that did not happen, which must fail rather than quietly skip: a parity
    test that reports "skipped" when the thing it compares against is absent is a
    parity test that never runs.
    """
    if os.environ.get("FLAB2BP_ROUTE_KERNEL") == "python":
        pytest.skip("FLAB2BP_ROUTE_KERNEL=python switches the compiled backend off")
    assert route_kernel.compiled_available()
    compiled = route_kernel._compiled_astar
    assert compiled is not None
    return compiled


def _replay(case: Case, budget: dict[str, int] | None = None) -> _PathSearchResult:
    return freeform_module._astar(
        case["canvas"], case["starts"], case["goals"], case["history"], case["pressure"],
        case["bounds"], {"left": 1 << 40} if budget is None else budget, None, {},
        case["grid"], case["owned_starts"], case["released_starts"], case["forbidden"],
        case["blocking_owners"],
    )


@pytest.mark.parametrize("make_spec", [two_stage_spec, plastic_spec])
def test_compiled_astar_matches_python_on_real_searches(
    make_spec: Callable[[], BuildSpec], monkeypatch: pytest.MonkeyPatch
) -> None:
    _require_both_backends()
    cases = _capture_searches(make_spec(), budget_s=4.0)
    assert cases

    compiled = [_replay(case) for case in cases]
    monkeypatch.setattr(route_kernel, "_compiled_astar", None)
    assert route_kernel.selected_backend() == "python"
    python = [_replay(case) for case in cases]

    for compiled_result, python_result in zip(compiled, python, strict=True):
        assert compiled_result.path == python_result.path
        assert compiled_result.kind == python_result.kind
        assert compiled_result.wall == python_result.wall
        assert compiled_result.expansions == python_result.expansions


def test_compiled_astar_honours_expansion_cap_and_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """Both backends must agree on the two exits the parity replay cannot reach.

    ``test_compiled_astar_matches_python_on_real_searches`` replays with
    ``left = 1 << 40`` and no deadline, so no captured case ever leaves through a
    budget or cap path -- and those are the exits carrying the deliberate +1
    asymmetry (``start_left - expansions + 1`` when the cap or the deadline
    stopped the search, ``start_left - expansions`` when the budget ran out).
    Getting that wrong in one backend changes how many nodes every later net in
    a routing pass may spend, so it is compared here rather than assumed.
    """
    compiled = _require_both_backends()
    cases = _capture_searches(two_stage_spec(), budget_s=2.0)
    found = [case for case in cases if _replay(case).expansions >= 3]
    assert found
    case = found[0]

    def under(
        backend: Callable[..., object] | None,
        budget: dict[str, int],
        max_expansions: int | None = None,
    ) -> _PathSearchResult:
        with monkeypatch.context() as forced:
            forced.setattr(route_kernel, "_compiled_astar", backend)
            if max_expansions is not None:
                forced.setattr(freeform_module, "_MAX_EXPANSIONS", max_expansions)
            return _replay(case, budget)

    # The shared budget runs out: charged for the expansion that hit the wall.
    cython_budget, python_budget = {"left": 3}, {"left": 3}
    from_cython = under(compiled, cython_budget)
    from_python = under(None, python_budget)
    assert from_cython == from_python
    assert cython_budget == python_budget
    assert from_cython.path is None
    assert from_cython.kind is RouteFailureKind.BUDGET
    assert from_cython.expansions == 3
    assert cython_budget["left"] == 0

    # The expansion cap fires first: charged one FEWER than it expanded.
    cython_cap, python_cap = {"left": 1 << 40}, {"left": 1 << 40}
    from_cython = under(compiled, cython_cap, max_expansions=2)
    from_python = under(None, python_cap, max_expansions=2)
    assert from_cython == from_python
    assert cython_cap == python_cap
    assert from_cython.kind is RouteFailureKind.BUDGET
    assert from_cython.expansions == 3  # cap + 1, exactly as the Python loop counts it
    assert cython_cap["left"] == (1 << 40) - 2


def test_backend_falls_back_when_extension_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(route_kernel, "_compiled_astar", None)
    assert not route_kernel.compiled_available()
    assert route_kernel.selected_backend() == "python"
