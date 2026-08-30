from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest

from flab2bp.bench.corpus import URL_CORPUS
from flab2bp.layout import validate
from flab2bp.layout.base import Placement
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
