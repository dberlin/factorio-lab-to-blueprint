from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable, Iterator
from typing import cast

import pytest

from flab2bp.layout import freeform, sequence_solver, strip_variants
from flab2bp.layout.route_feedback import DetailedRouteResult, DetailedRouteStatus
from flab2bp.rates import CandidatePolicy
from scripts import route_profile


class _Layout:
    kwargs: dict[str, object]

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs

    def lay_out(self, spec: object, *, time_budget_s: float) -> None:
        assert spec is _SPEC
        assert time_budget_s == 4.0


_SPEC = object()


def _clock(values: list[float]) -> Iterator[float]:
    yield from values


def test_json_profile_emits_one_bounded_machine_readable_record(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    tally = route_profile.Tally()
    tally.t = {"route_all": 4.0, "astar": 1.25, "prepare": 2.5, "plan_strips": 0.5}
    tally.n = {"route_all": 1, "astar": 3, "prepare": 2, "plan_strips": 1}
    tally.prepare_calls = [2.0, 0.5]
    tally.expansions = 123
    tally.astar_hit = 2
    tally.astar_none = 1

    times = _clock([10.0, 15.0])
    monkeypatch.setattr(route_profile, "Tally", lambda: tally)
    monkeypatch.setattr(route_profile, "install", lambda _tally: lambda: None)
    selected_policies: list[CandidatePolicy] = []

    def fake_spec(_url_id: str, policy: CandidatePolicy) -> object:
        selected_policies.append(policy)
        return _SPEC

    monkeypatch.setattr(route_profile, "_spec", fake_spec)
    monkeypatch.setattr(time, "perf_counter", lambda: next(times))
    monkeypatch.setattr(freeform, "FreeformLayout", _Layout)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "route_profile.py",
            "plastic",
            "--workers",
            "1",
            "--json",
            "--candidate-policy",
            "output-products",
        ],
    )

    assert route_profile.main() == 0

    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == {
        "url_id": "plastic",
        "strategy": "freeform",
        "power": True,
        "budget_s": 4.0,
        "run": 1,
        "repeat": 1,
        "verdict": "OK",
        "wall_s": 5.0,
        "route_all_s": 4.0,
        "astar_s": 1.25,
        "astar_routing_share": 0.3125,
        "astar_wall_share": 0.25,
        "expansions": 123,
        "hits": 2,
        "misses": 1,
        "phases": {
            "prepare": {"s": 2.5, "n": 2},
            "plan_strips": {"s": 0.5, "n": 1},
        },
        "prepare_calls_s": [2.0, 0.5],
    }
    assert selected_policies == [CandidatePolicy.OUTPUT_PRODUCTS]


def test_tally_reads_iterations_from_detailed_route_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = DetailedRouteResult(DetailedRouteStatus.ROUTED, (), (), 7, 123)
    monkeypatch.setattr(freeform, "_route_all", lambda *args, **kwargs: result)
    tally = route_profile.Tally()
    restore = route_profile.install(tally)
    wrapped = cast(Callable[..., DetailedRouteResult], freeform._route_all)
    try:
        assert wrapped(None, [], 1, 1, (0, 0, 0, 0)) is result
    finally:
        restore()

    assert tally.passes == 1
    assert tally.rounds == 7


def test_install_wraps_preparation_phases_and_restores() -> None:
    tally = route_profile.Tally()
    original = freeform._prepared_junction_ban
    restore = route_profile.install(tally)
    try:
        assert freeform._prepared_junction_ban is not original
        freeform._prepared_junction_ban((), ())
    finally:
        restore()
    assert freeform._prepared_junction_ban is original
    assert tally.n["junction_ban"] == 1
    assert tally.t["junction_ban"] >= 0.0


def test_install_wraps_sequence_solvers_reimported_bindings_too() -> None:
    # `sequence_solver` does `from flab2bp.layout.freeform import
    # _prepare_routing_problem, plan_strips` and `from
    # flab2bp.layout.strip_variants import generate_strip_families`, each
    # binding the function under its own module -- a shim installed only on
    # the defining module misses every call sequence-pair makes through its
    # own binding. `plan_strips` is re-exported with an explicit `as
    # plan_strips` alias so mypy treats it as public; `_prepare_routing_problem`
    # and `generate_strip_families` are not, so they are read via `getattr`
    # here, the same way `install()` itself patches them.
    def seq_prepare() -> object:
        return getattr(sequence_solver, "_prepare_routing_problem")  # noqa: B009

    def seq_strip_families() -> object:
        return getattr(sequence_solver, "generate_strip_families")  # noqa: B009

    tally = route_profile.Tally()
    originals = {
        "prepare": seq_prepare(),
        "plan_strips": sequence_solver.plan_strips,
        "strip_families": seq_strip_families(),
    }
    restore = route_profile.install(tally)
    try:
        assert seq_prepare() is not originals["prepare"]
        assert seq_prepare() is freeform._prepare_routing_problem
        assert sequence_solver.plan_strips is not originals["plan_strips"]
        assert sequence_solver.plan_strips is freeform.plan_strips
        assert seq_strip_families() is not originals["strip_families"]
        assert seq_strip_families() is strip_variants.generate_strip_families
    finally:
        restore()
    assert seq_prepare() is originals["prepare"]
    assert sequence_solver.plan_strips is originals["plan_strips"]
    assert seq_strip_families() is originals["strip_families"]


def test_normal_profile_honors_sequence_pair_strategy(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    selected: list[dict[str, object]] = []

    class SequencePairLayout(_Layout):
        def __init__(self, **kwargs: object) -> None:
            selected.append(kwargs)
            super().__init__(**kwargs)

    monkeypatch.setattr(route_profile, "_spec", lambda _url_id, _index: _SPEC)
    monkeypatch.setattr(route_profile, "install", lambda _tally: lambda: None)
    monkeypatch.setattr(sequence_solver, "SequencePairLayout", SequencePairLayout)
    monkeypatch.setattr(
        freeform,
        "FreeformLayout",
        lambda **_kwargs: pytest.fail("freeform strategy was selected"),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["route_profile.py", "plastic", "--strategy", "sequence-pair"],
    )

    assert route_profile.main() == 0
    assert len(selected) == 1
    assert "power" not in selected[0]
    assert "band_policy" in selected[0]
    assert "workers" not in selected[0]
    assert "=== plastic" in capsys.readouterr().out
