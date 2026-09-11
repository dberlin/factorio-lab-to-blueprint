from __future__ import annotations

import json
import sys
from collections.abc import Callable
from typing import cast

import pytest

from flab2bp.layout import freeform, routing_domain, sequence_solver, strip_variants
from flab2bp.layout.route_feedback import DetailedRouteResult, DetailedRouteStatus
from scripts import route_profile


class _Layout:
    kwargs: dict[str, object]

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs

    def lay_out(self, spec: object, *, time_budget_s: float) -> None:
        assert spec is _SPEC
        assert time_budget_s == 4.0


_SPEC = object()


def test_freeform_profile_runs_current_routing_callbacks(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["route_profile.py", "plastic", "--strategy", "freeform", "--budget", "15", "--json"],
    )

    assert route_profile.main() == 0
    record = json.loads(capsys.readouterr().out)
    assert record["verdict"] == "OK"
    assert record["route_all_s"] > 0


def test_tally_reads_iterations_from_detailed_route_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = DetailedRouteResult(DetailedRouteStatus.ROUTED, (), (), 7, 123)
    monkeypatch.setattr(routing_domain, "_route_all", lambda *args, **kwargs: result)
    tally = route_profile.Tally()
    restore = route_profile.install(tally)
    wrapped = cast(Callable[..., DetailedRouteResult], routing_domain._route_all)
    try:
        assert wrapped(None, [], 1, 1, (0, 0, 0, 0)) is result
    finally:
        restore()

    assert tally.passes == 1
    assert tally.rounds == 7


def test_install_wraps_preparation_phases_and_restores() -> None:
    tally = route_profile.Tally()
    original = routing_domain._prepared_junction_ban
    restore = route_profile.install(tally)
    try:
        assert routing_domain._prepared_junction_ban is not original
        routing_domain._prepared_junction_ban((), ())
    finally:
        restore()
    assert routing_domain._prepared_junction_ban is original
    assert tally.n["junction_ban"] == 1
    assert tally.t["junction_ban"] >= 0.0


def test_install_wraps_sequence_solvers_reimported_bindings_too() -> None:
    # `sequence_solver` imports `_prepare_routing_problem` from routing_domain,
    # `plan_strips` from freeform, and `generate_strip_families` from
    # strip_variants, each
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
        assert seq_prepare() is routing_domain._prepare_routing_problem
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
