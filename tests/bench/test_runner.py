from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from flab2bp.bench import __main__ as bench_main
from flab2bp.bench import runner
from flab2bp.bench.corpus import URL_CORPUS
from flab2bp.layout import finalize, validate
from flab2bp.layout.band_policy import BandPolicy
from flab2bp.layout.base import (
    AreaFrame,
    LayoutStrategy,
    Placement,
    PlacementCompletion,
)
from flab2bp.rates import CandidatePolicy
from flab2bp.spec import BuildSpec


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
            candidates=tuple(SimpleNamespace(label=policy.value) for policy in candidate_policies)
        )

    monkeypatch.setattr("flab2bp.bench.runner.lab_data.load_vendored", object)
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


def test_run_cell_preserves_completed_placement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completed = Placement(
        buildings=(),
        frame=AreaFrame(1, 1, 4, (4,), False),
        completion=PlacementCompletion.COMPACTED_AND_FINALIZED,
    )
    observed: list[tuple[str, Placement]] = []

    class CompletedStrategy:
        def lay_out(self, spec: BuildSpec, *, time_budget_s: float) -> Placement:
            del spec, time_budget_s
            return completed

    def fail_completion(*args: object, **kwargs: object) -> Placement:
        del args, kwargs
        pytest.fail("completed placement must bypass completion transforms")

    monkeypatch.setattr(
        finalize,
        "compact_open_boundary_belts",
        fail_completion,
    )
    monkeypatch.setattr(finalize, "finalize_placement", fail_completion)
    _stub_cell_observers(monkeypatch, observed)

    runner._run_cell(
        runner.StrategyHandle(
            "completed",
            cast(LayoutStrategy, CompletedStrategy()),
        ),
        URL_CORPUS[0],
        cast(BuildSpec, SimpleNamespace(label="completed fixture")),
        time_budget_s=1.0,
    )

    assert observed == [("measure", completed), ("validate", completed)]
    assert all(placement is completed for _, placement in observed)
    assert completed.completion is PlacementCompletion.COMPACTED_AND_FINALIZED


def test_run_cell_completes_raw_placement_once_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = Placement(buildings=())
    compacted = replace(raw, description="compacted")
    finalized = replace(
        compacted,
        frame=AreaFrame(1, 1, 4, (4,), False),
    )
    observed: list[tuple[str, Placement]] = []

    class RawStrategy:
        def lay_out(self, spec: BuildSpec, *, time_budget_s: float) -> Placement:
            del spec, time_budget_s
            return raw

    def compact_spy(
        placement: Placement,
        spec: BuildSpec,
        *,
        expect_power: bool,
    ) -> Placement:
        del spec
        assert expect_power
        assert placement is raw
        observed.append(("compact", placement))
        return compacted

    def finalize_spy(
        placement: Placement,
        policy: BandPolicy,
    ) -> Placement:
        del policy
        assert placement is compacted
        observed.append(("finalize", placement))
        return finalized

    monkeypatch.setattr(
        finalize,
        "compact_open_boundary_belts",
        compact_spy,
    )
    monkeypatch.setattr(finalize, "finalize_placement", finalize_spy)
    _stub_cell_observers(monkeypatch, observed)

    runner._run_cell(
        runner.StrategyHandle("raw", cast(LayoutStrategy, RawStrategy())),
        URL_CORPUS[0],
        cast(BuildSpec, SimpleNamespace(label="raw fixture")),
        time_budget_s=1.0,
    )

    assert [stage for stage, _ in observed] == [
        "compact",
        "finalize",
        "measure",
        "validate",
    ]
    completed = observed[-1][1]
    assert observed[-2][1] is completed
    assert completed.completion is PlacementCompletion.COMPACTED_AND_FINALIZED
    assert completed.frame is finalized.frame
    assert completed.buildings is finalized.buildings


def _stub_cell_observers(
    monkeypatch: pytest.MonkeyPatch,
    observed: list[tuple[str, Placement]],
) -> None:
    metrics = SimpleNamespace(
        area=1,
        used_tiles=0,
        width=1,
        height=1,
        machines=0,
        belt_tiles=0,
        sorters=0,
        direct_inserts=0,
        towers=0,
        altitude_levels=0,
    )
    report = SimpleNamespace(
        ok=True,
        skipped=(),
        errors=(),
        warnings=(),
        checks_run=(),
    )

    def measure_spy(placement: Placement) -> SimpleNamespace:
        observed.append(("measure", placement))
        return metrics

    def validate_spy(
        placement: Placement,
        spec: BuildSpec,
        **kwargs: object,
    ) -> SimpleNamespace:
        del spec, kwargs
        observed.append(("validate", placement))
        return report

    monkeypatch.setattr(runner, "measure", measure_spy)
    monkeypatch.setattr(validate, "validate", validate_spy)
    monkeypatch.setattr(runner, "_id_map", lambda _spec: object())
