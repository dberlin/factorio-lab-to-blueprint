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
            canvas,
            starts,
            goals,
            history,
            pressure,
            bounds,
            budget,
            deadline,
            blame,
            grid,
            owned_starts,
            released_starts,
            forbidden,
            blocking_owners,
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


def _replay(
    case: Case,
    budget: dict[str, int] | None = None,
    *,
    deadline: float | None = None,
) -> _PathSearchResult:
    return freeform_module._astar(
        case["canvas"],
        case["starts"],
        case["goals"],
        case["history"],
        case["pressure"],
        case["bounds"],
        {"left": 1 << 40} if budget is None else budget,
        deadline,
        {},
        case["grid"],
        case["owned_starts"],
        case["released_starts"],
        case["forbidden"],
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


def test_compiled_astar_deadline_checkpoint_preserves_raw_telemetry_and_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compiled = _require_both_backends()
    cases = _capture_searches(two_stage_spec(), budget_s=2.0)
    found = [case for case in cases if _replay(case).expansions >= 3]
    assert found
    case = found[0]

    def under(
        backend: Callable[..., object] | None,
        budget: dict[str, int],
    ) -> _PathSearchResult:
        expired_checks = 0

        def expire_at_checkpoint(_deadline: float | None) -> bool:
            nonlocal expired_checks
            expired_checks += 1
            return expired_checks > 1

        with monkeypatch.context() as forced:
            forced.setattr(route_kernel, "_compiled_astar", backend)
            forced.setattr(freeform_module, "_DEADLINE_CHECK_EVERY", 1)
            forced.setattr(freeform_module, "_expired", expire_at_checkpoint)
            return _replay(case, budget, deadline=0.0)
    cython_budget, python_budget = {"left": 3}, {"left": 3}
    from_cython = under(compiled, cython_budget)
    from_python = under(None, python_budget)

    assert from_cython == from_python
    assert cython_budget == python_budget
    assert from_cython.path is None
    assert from_cython.kind is RouteFailureKind.BUDGET
    assert from_cython.expansions == 1
    assert cython_budget["left"] == 3


def test_a_start_in_the_pad_degrades_the_backend_and_keeps_the_grid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pad margin picks the LOOP; it must never cost the caller its grid.

    Rebuilding the grid to dodge the kernel's precondition would hand back a
    landmark-free grid, which is a weaker heuristic and a different expansion
    count -- under the Python backend too, where the router must stay
    byte-identical to the pre-kernel one.  So a cell inside the pad falls
    through to the Python loop ON THE SAME GRID, exactly as
    ``global_router._kernel_bounds_hold`` does for the relaxed search.
    """
    compiled = _require_both_backends()

    box = (0, 0, 8, 8)
    canvas = freeform_module._Canvas()
    # `span` is `box` plus exactly the two-cell pad, so a cell on the span's
    # outer edge is inside `span` and two short of the margin.
    grid = freeform_module._make_grid(canvas, box, (-2, -2, 10, 10), {})

    took_python: list[str] = []
    took_kernel: list[str] = []
    rebuilt: list[str] = []
    original_loop = freeform_module._astar_python_loop
    original_make = freeform_module._make_grid

    def spy_loop(*args: Any, **kwargs: Any) -> Any:
        took_python.append("called")
        return original_loop(*args, **kwargs)

    def spy_kernel(*args: Any, **kwargs: Any) -> Any:
        took_kernel.append("called")
        return compiled(*args, **kwargs)

    def spy_make(*args: Any, **kwargs: Any) -> Any:
        rebuilt.append("called")
        return original_make(*args, **kwargs)

    monkeypatch.setattr(freeform_module, "_astar_python_loop", spy_loop)
    monkeypatch.setattr(freeform_module, "_make_grid", spy_make)
    monkeypatch.setattr(route_kernel, "_compiled_astar", spy_kernel)

    def search(cell: Cell) -> None:
        # Goal == start, so this terminates on the first pop and the assertion
        # is about which loop ran rather than about what it found.
        freeform_module._astar(canvas, [cell], {cell}, {}, 1.0, box, {"left": 1 << 20}, grid=grid)

    in_the_pad = (-2, 4, 0)
    assert not freeform_module._kernel_margin_holds(grid, [in_the_pad])
    search(in_the_pad)
    assert took_python == ["called"]
    assert took_kernel == []
    assert rebuilt == []  # the caller's grid, landmark fields and all, was kept

    # Control: the same grid, a cell clear of the pad, and the kernel runs --
    # so the assertion above is about the margin and not about a kernel that
    # was never going to be reached.
    took_python.clear()
    clear_of_the_pad = (2, 4, 0)
    assert freeform_module._kernel_margin_holds(grid, [clear_of_the_pad])
    search(clear_of_the_pad)
    assert took_kernel == ["called"]
    assert took_python == []
    assert rebuilt == []


def test_backend_falls_back_when_extension_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(route_kernel, "_compiled_astar", None)
    assert not route_kernel.compiled_available()
    assert route_kernel.selected_backend() == "python"
