from __future__ import annotations

from pathlib import Path

from types import SimpleNamespace

import pytest

from flab2bp.bench import __main__ as bench_main
from flab2bp.bench import runner
from flab2bp.bench.corpus import URL_CORPUS
from flab2bp.rates import CandidatePolicy


def test_run_corpus_generates_one_powered_arm_per_strategy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = URL_CORPUS[0]
    handles = (SimpleNamespace(name="a"), SimpleNamespace(name="b"))
    monkeypatch.setattr(
        runner,
        "specs_for",
        lambda _entry, *, candidate_policies: (object(),),
    )
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

    rows = runner.run_corpus(
        (entry,),
        time_budget_s=1.0,
        candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
    )

    assert len(rows) == 2
    assert all(row.power is True for row in rows)


def test_spec_error_record_retains_constant_powered_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = URL_CORPUS[0]

    def fail_specs(
        _entry: object,
        *,
        candidate_policies: tuple[CandidatePolicy, ...],
    ) -> object:
        del candidate_policies
        raise ValueError("bad fixture")

    monkeypatch.setattr(runner, "specs_for", fail_specs)

    rows = runner.run_corpus(
        (entry,),
        time_budget_s=1.0,
        candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
    )

    assert len(rows) == 1
    assert rows[0].power is True


def test_specs_for_default_emits_the_three_canonical_candidate_identities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = URL_CORPUS[0]
    received: dict[str, object] = {}

    def fake_build_candidates(
        data: object,
        request: object,
        *,
        candidate_policies: tuple[CandidatePolicy, ...],
    ) -> SimpleNamespace:
        del data, request
        received["candidate_policies"] = candidate_policies
        return SimpleNamespace(
            candidates=tuple(
                SimpleNamespace(label=policy.value) for policy in candidate_policies
            )
        )

    monkeypatch.setattr(runner.lab_data, "load_vendored", object)
    monkeypatch.setattr(runner, "parse_url", lambda _url: object())
    monkeypatch.setattr(runner, "build_candidates", fake_build_candidates)

    specs = runner.specs_for(entry)

    expected = (
        CandidatePolicy.NO_PROLIFERATOR,
        CandidatePolicy.ALL_PRODUCTS,
        CandidatePolicy.OUTPUT_PRODUCTS,
    )
    assert received["candidate_policies"] == expected
    assert tuple(spec.label for spec in specs) == tuple(policy.value for policy in expected)


def test_benchmark_cli_passes_named_candidate_policy_subset_in_canonical_order(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    received: dict[str, object] = {}

    def fake_run_corpus(
        entries: object,
        *,
        time_budget_s: float | None,
        candidate_policies: tuple[CandidatePolicy, ...],
    ) -> list[object]:
        del entries, time_budget_s
        received["candidate_policies"] = candidate_policies
        return []

    monkeypatch.setattr(bench_main, "run_corpus", fake_run_corpus)
    monkeypatch.setattr(bench_main, "matrix_report", lambda *args: object())
    monkeypatch.setattr(bench_main, "render_markdown", lambda *args, **kwargs: "")
    monkeypatch.setattr(bench_main, "write_results", lambda *args, **kwargs: None)
    monkeypatch.setattr(bench_main, "_RESULTS", tmp_path)

    assert (
        bench_main.main(
            [
                "--candidate-policy",
                "output-products",
                "--candidate-policy",
                "no-proliferator",
            ]
        )
        == 0
    )
    assert received["candidate_policies"] == (
        CandidatePolicy.NO_PROLIFERATOR,
        CandidatePolicy.OUTPUT_PRODUCTS,
    )
