from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import cast

import pytest

from flab2bp.bench import runner
from flab2bp.bench.corpus import URL_CORPUS
from flab2bp.lab.techs import belt_rules_for_url
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
        belt_rules=belt_rules_for_url(URL_CORPUS[0].url),
        ids=validate.id_map(BuildSpec(groups=())),
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
        belt_rules=belt_rules_for_url(URL_CORPUS[0].url),
        ids=validate.id_map(BuildSpec(groups=())),
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
