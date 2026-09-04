from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import cast

import pytest

from flab2bp.bench.corpus import URL_CORPUS
from flab2bp.layout import finalize, validate
from flab2bp.layout.band_policy import BandPolicy
from flab2bp.layout.base import AreaFrame, Placement, PlacementCompletion
from flab2bp.rates import CandidatePolicy
from flab2bp.spec import BuildSpec
from scripts import ab_compare


def test_current_judge_rejects_skipped_power_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = SimpleNamespace(ok=True, errors=(), skipped=("power.coverage",))
    monkeypatch.setattr(validate, "validate", lambda *args, **kwargs: report)

    valid, checks = ab_compare.judge_with(
        cast(BuildSpec, object()),
        cast(validate.IdMap, object()),
        cast(Placement, object()),
    )

    assert not valid
    assert checks == ("unchecked:power.coverage",)


def test_collect_persists_constant_powered_metadata_for_spec_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = URL_CORPUS[0]

    def fail_specs(
        _entry: object,
        candidate_policies: tuple[CandidatePolicy, ...],
    ) -> object:
        del candidate_policies
        raise ValueError("bad fixture")

    monkeypatch.setattr(ab_compare, "specs_for", fail_specs)

    samples = ab_compare.collect(
        [entry],
        budgets=[1.0],
        repeat=1,
        candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
    )

    assert len(samples) == 2
    assert all(sample.power is True for sample in samples)


def test_ab_cli_accepts_named_policy_repeats_and_commas_in_canonical_order() -> None:
    args = ab_compare._parse_args(
        [
            "--candidate-policy",
            "output-products",
            "--candidate-policy",
            "all-products,no-proliferator",
        ]
    )

    assert args.candidate_policies == (
        CandidatePolicy.NO_PROLIFERATOR,
        CandidatePolicy.ALL_PRODUCTS,
        CandidatePolicy.OUTPUT_PRODUCTS,
    )


def test_layout_call_preserves_completed_placement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completed = Placement(
        buildings=(),
        frame=AreaFrame(1, 1, 4, (4,), False),
        completion=PlacementCompletion.COMPACTED_AND_FINALIZED,
    )

    class CompletedStrategy:
        def lay_out(self, spec: BuildSpec, *, time_budget_s: float) -> Placement:
            del spec, time_budget_s
            return completed

    def fail_completion(*args: object, **kwargs: object) -> Placement:
        del args, kwargs
        pytest.fail("completed placement must bypass completion transforms")

    monkeypatch.setitem(
        ab_compare.STRATEGIES,
        "completed",
        lambda _vertical: CompletedStrategy(),
    )
    monkeypatch.setattr(
        finalize,
        "compact_open_boundary_belts",
        fail_completion,
    )
    monkeypatch.setattr(finalize, "finalize_placement", fail_completion)

    result = ab_compare._LayoutCall(
        strategy="completed",
        vertical=True,
        spec=cast(BuildSpec, object()),
        budget_s=1.0,
    )()

    assert result is completed
    assert result.completion is PlacementCompletion.COMPACTED_AND_FINALIZED


def test_layout_call_completes_raw_placement_once_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = Placement(buildings=())
    compacted = replace(raw, description="compacted")
    finalized = replace(
        compacted,
        frame=AreaFrame(1, 1, 4, (4,), False),
    )
    stages: list[str] = []

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
        stages.append("compact")
        return compacted

    def finalize_spy(
        placement: Placement,
        policy: BandPolicy,
    ) -> Placement:
        del policy
        assert placement is compacted
        stages.append("finalize")
        return finalized

    monkeypatch.setitem(
        ab_compare.STRATEGIES,
        "raw",
        lambda _vertical: RawStrategy(),
    )
    monkeypatch.setattr(
        finalize,
        "compact_open_boundary_belts",
        compact_spy,
    )
    monkeypatch.setattr(finalize, "finalize_placement", finalize_spy)

    result = ab_compare._LayoutCall(
        strategy="raw",
        vertical=False,
        spec=cast(BuildSpec, object()),
        budget_s=1.0,
    )()

    assert stages == ["compact", "finalize"]
    assert result.completion is PlacementCompletion.COMPACTED_AND_FINALIZED
    assert result.frame is finalized.frame
    assert result.buildings is finalized.buildings
