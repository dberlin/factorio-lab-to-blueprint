from __future__ import annotations

from types import SimpleNamespace

import pytest

from flab2bp.bench import runner
from flab2bp.bench.corpus import URL_CORPUS


def test_run_corpus_generates_one_powered_arm_per_strategy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = URL_CORPUS[0]
    handles = (SimpleNamespace(name="a"), SimpleNamespace(name="b"))
    monkeypatch.setattr(runner, "specs_for", lambda _entry, *, candidates: (object(),))
    monkeypatch.setattr(
        runner,
        "belt_rules_for_url",
        lambda _url: SimpleNamespace(vertical_construction=True),
    )
    monkeypatch.setattr(runner, "available_strategies", lambda **_kwargs: handles)

    def fake_run_cell(
        _handle: object,
        _entry: object,
        _spec: object,
        **kwargs: object,
    ) -> SimpleNamespace:
        return SimpleNamespace(power=kwargs.get("power", True))

    monkeypatch.setattr(runner, "_run_cell", fake_run_cell)

    rows = runner.run_corpus((entry,), time_budget_s=1.0, candidates=1)

    assert len(rows) == 2
    assert all(row.power is True for row in rows)


def test_spec_error_record_retains_constant_powered_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = URL_CORPUS[0]

    def fail_specs(_entry: object, *, candidates: int) -> object:
        raise ValueError("bad fixture")

    monkeypatch.setattr(runner, "specs_for", fail_specs)

    rows = runner.run_corpus((entry,), time_budget_s=1.0, candidates=1)

    assert len(rows) == 1
    assert rows[0].power is True
