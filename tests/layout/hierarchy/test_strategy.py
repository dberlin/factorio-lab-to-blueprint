"""The hierarchical strategy end to end: partition, solve, compose, certify.

Every test here drives the real placers on ``chain_spec``.  A mocked block
solve would only prove the orchestration talks to itself; what has to hold is
that two independently solved blocks, wired by the lane contract and packed by
the composer, come back as ONE placement the validator accepts.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from flab2bp.layout import validate
from flab2bp.layout.band_policy import BandPolicy
from flab2bp.layout.base import NoValidLayout, Placement, PlacementCompletion
from flab2bp.layout.hierarchy import compose as compose_mod
from flab2bp.layout.hierarchy import strategy
from flab2bp.layout.hierarchy.strategy import HierarchicalLayout
from flab2bp.spec import BuildSpec


def _layout() -> HierarchicalLayout:
    return HierarchicalLayout(
        belt_vertical_construction=True,
        band_policy=BandPolicy.parse("portable"),
        workers=8,
        strip_cap=2,
    )


def test_hierarchical_lays_out_the_chain_as_two_blocks_and_certifies(
    chain_spec: BuildSpec,
) -> None:
    layout = _layout()
    placement = layout.lay_out(chain_spec, time_budget_s=30.0)
    assert placement.completion is PlacementCompletion.COMPACTED_AND_FINALIZED
    assert placement.stats["blocks"] == 2
    assert placement.stats["cut_lanes"] >= 1
    assert validate.certify(placement, chain_spec, expect_power=True).ok


def test_a_block_that_refuses_is_re_cut_before_the_whole_spec_refuses(
    chain_spec: BuildSpec,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []
    real = strategy._solve_block

    def refuse_first_shape(
        args: strategy._BlockJob,
    ) -> tuple[dict[str, object], Placement | None]:
        sub = args[0]
        calls.append(sub.machine_count)
        if sub.machine_count == 2 and len(sub.groups) == 1:  # the unsplit ingot block
            return ({"verdict": "REFUSED: forced", "ok": False, "strategy": args[1]}, None)
        return real(args)

    monkeypatch.setattr(strategy, "_solve_block", refuse_first_shape)
    layout = _layout()
    # The patched worker only exists in THIS process.
    layout._executor_factory = ThreadPoolExecutor
    placement = layout.lay_out(chain_spec, time_budget_s=40.0)
    assert placement.stats["resplits"] >= 1
    assert 1 in calls  # the ingot block was split into 1 + 1


def test_an_unwired_cut_is_a_refusal_not_a_handback(
    chain_spec: BuildSpec,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        strategy.compose_mod,
        "compose",
        lambda *a, **k: compose_mod.ComposeResult(
            Placement(buildings=()), [], 0, ("ingot: block 0 -> block 1: BUDGET",)
        ),
    )
    layout = _layout()
    with pytest.raises(NoValidLayout, match=r"ingot: block 0 -> block 1"):
        layout.lay_out(chain_spec, time_budget_s=30.0)


def test_no_block_outlives_the_parent_deadline(
    chain_spec: BuildSpec,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[float | None] = []
    real = strategy._solve_block

    def spy(args: strategy._BlockJob) -> tuple[dict[str, object], Placement | None]:
        seen.append(args[5])
        return real(args)

    monkeypatch.setattr(strategy, "_solve_block", spy)
    layout = _layout()
    layout._executor_factory = ThreadPoolExecutor
    started = time.monotonic()
    layout.lay_out(chain_spec, time_budget_s=30.0)
    assert seen and all(d is not None for d in seen)
    # And no block gets the parent's WHOLE wall either.  Both backends read
    # `absolute_deadline` as replacing their own budget rather than bounding it,
    # so handing one the parent deadline would let the first round spend
    # everything and leave the re-cut loop unreachable.
    block_budget = min(
        strategy.BLOCK_BUDGET_MAX_S,
        max(strategy.BLOCK_BUDGET_MIN_S, 30.0 * float(strategy.BLOCK_BUDGET_SHARE)),
    )
    assert block_budget < 30.0
    assert all(d is not None and d <= started + block_budget + 1.0 for d in seen)
