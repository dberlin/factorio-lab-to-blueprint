"""The hierarchical strategy end to end: partition, solve, compose, certify.

Every test here drives the real placers on ``chain_spec``.  A mocked block
solve would only prove the orchestration talks to itself; what has to hold is
that two independently solved blocks, wired by the lane contract and packed by
the composer, come back as ONE placement the validator accepts.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures.process import BrokenProcessPool

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
    assert all(d is not None and d <= started + 30.0 + 1.0 for d in seen)


def test_a_job_is_capped_at_its_own_budget_when_it_starts_not_when_the_round_did(
    chain_spec: BuildSpec,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The wall a job gets is computed IN the worker, at job start.

    The pool runs the round's jobs in waves.  A deadline the parent computed
    before the pool started is already spent by the time a second-wave job
    runs, and that job refuses instantly with "deadline exhausted" without
    searching at all -- so index 5 carries the parent's wall and the worker
    combines it with the budget itself.
    """
    seen: dict[str, float | None] = {}

    class _Stub:
        def lay_out(
            self,
            spec: BuildSpec,
            *,
            time_budget_s: float = 15.0,
            absolute_deadline: float | None = None,
        ) -> Placement:
            seen["deadline"] = absolute_deadline
            raise NoValidLayout("stub")

    monkeypatch.setattr(strategy, "_block_layout", lambda *a, **k: _Stub())
    started = time.monotonic()
    # A parent wall ten minutes out, and a three-second job budget.
    record, placement = strategy._solve_block(
        (chain_spec, "freeform", 3.0, True, 4, started + 600.0)
    )
    assert placement is None and record["ok"] is False
    deadline = seen["deadline"]
    assert deadline is not None
    assert started + 2.0 <= deadline <= started + 4.0


def test_a_budget_too_small_to_fund_one_solve_round_refuses_saying_so(
    chain_spec: BuildSpec,
) -> None:
    with pytest.raises(NoValidLayout, match=r"is under the .*s a block solve is given at all"):
        _layout().lay_out(chain_spec, time_budget_s=1.0)


def test_a_dead_pool_is_a_refusal_not_a_crash(chain_spec: BuildSpec) -> None:
    """A parent-side pool failure must not escape as a raw exception.

    `Executor.map` re-raises a `BrokenProcessPool`, an unpicklable argument and
    an interpreter that failed to start, all on the parent side.  Losing the
    build to one is the mistake `_solve_block`'s own CRASH arm exists to avoid,
    one level up.
    """

    class _DeadPool:
        def __init__(self, max_workers: int) -> None:
            self.max_workers = max_workers

        def __enter__(self) -> _DeadPool:
            return self

        def __exit__(self, *exc_info: object) -> bool:
            return False

        def map(self, fn: object, jobs: object) -> object:
            raise BrokenProcessPool("a worker process died abruptly")

    layout = _layout()
    layout._executor_factory = _DeadPool  # type: ignore[assignment]
    with pytest.raises(NoValidLayout, match="BrokenProcessPool"):
        layout.lay_out(chain_spec, time_budget_s=30.0)


def test_a_composer_crash_is_a_refusal_not_a_traceback(
    chain_spec: BuildSpec,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`lay_out` promises a `Placement` or a `NoValidLayout`, never a crash.

    The composer reads geometry assembled out of independently solved blocks --
    shapes no single block showed its own placer -- and `compose._port` asserts
    on one of them (`lane at N is not one contiguous row`, seen on belt3). That
    is the same kind of event as a placer crashing inside a block and is handled
    the same way.
    """

    def explode(*args: object, **kwargs: object) -> compose_mod.ComposeResult:
        raise AssertionError("lane at 9865 is not one contiguous row")

    monkeypatch.setattr(strategy.compose_mod, "compose", explode)
    with pytest.raises(NoValidLayout, match=r"composition crashed: AssertionError: lane at 9865"):
        _layout().lay_out(chain_spec, time_budget_s=30.0)


def test_a_deadline_spent_by_composition_refuses_before_finalization(
    chain_spec: BuildSpec,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Settlement is entered only with wall left to enter it with.

    `assign_sorter_slots` takes no `cancelled` and `certify` is atomic, so a
    composition that ran the clock out must refuse rather than start them.
    """
    real = compose_mod.compose

    def stall(*args: object, **kwargs: object) -> compose_mod.ComposeResult:
        result = real(*args, **kwargs)  # type: ignore[arg-type]
        deadline = kwargs["deadline"]
        assert isinstance(deadline, float)
        while time.monotonic() < deadline:
            time.sleep(0.05)
        return result

    monkeypatch.setattr(strategy.compose_mod, "compose", stall)
    # One arm, so the round is a single wave and a short budget still funds it.
    layout = HierarchicalLayout(
        belt_vertical_construction=True,
        band_policy=BandPolicy.parse("portable"),
        workers=8,
        strip_cap=2,
        block_strategy="freeform",
    )
    with pytest.raises(NoValidLayout, match="deadline exhausted before finalization"):
        layout.lay_out(chain_spec, time_budget_s=12.0)
