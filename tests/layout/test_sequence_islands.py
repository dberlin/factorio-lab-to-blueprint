from __future__ import annotations

from concurrent.futures import Future
from dataclasses import replace
from typing import Any

import pytest

import flab2bp.layout.sequence_islands as islands_module
from flab2bp.layout.base import NoValidLayout, PlacedBuilding, Placement
from flab2bp.layout.sequence_islands import (
    _merge_sequence_island_outcomes,
    _sequence_island_deadlines,
    _sequence_island_result_reserve_s,
    _sequence_island_seeds,
    _SequenceIslandOutcome,
)
from flab2bp.layout.sequence_pair import derive_stage_seed
from flab2bp.layout.sequence_solver import SequencePairLayout, SequenceSolverConfig
from tests.layout.test_freeform import two_stage_spec


def _placement(*, area: int, belt_tiles: int) -> Placement:
    return Placement(
        buildings=(
            PlacedBuilding(
                item_id=1,
                model_index=1,
                x=0,
                y=0,
                width=area,
                height=1,
            ),
        ),
        stats={"belt_tiles": float(belt_tiles)},
    )


def test_island_count_is_bounded_and_solver_factory_stays_serial() -> None:
    for islands in (0, 17, True):
        with pytest.raises(ValueError, match="islands must be an integer from 1 to 16"):
            SequencePairLayout(islands=islands)

    def factory(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("factory must not be called")

    with pytest.raises(ValueError, match="solver factory requires exactly one island"):
        SequencePairLayout(islands=2, solver_factory=factory)


def test_island_seed_plan_preserves_base_then_derives_stable_distinct_seeds() -> None:
    base = 20260824
    first = _sequence_island_seeds(base, 4)
    second = _sequence_island_seeds(base, 4)

    assert first == second
    assert first == (base,) + tuple(derive_stage_seed(base, island_id) for island_id in range(1, 4))
    assert len(set(first)) == len(first)


def test_deterministic_merge_uses_area_belts_and_id_not_completion_order() -> None:
    outcomes = (
        _SequenceIslandOutcome.completed(3, 303, _placement(area=20, belt_tiles=4)),
        _SequenceIslandOutcome.completed(2, 202, _placement(area=19, belt_tiles=9)),
        _SequenceIslandOutcome.completed(1, 101, _placement(area=19, belt_tiles=8)),
        _SequenceIslandOutcome.completed(0, 100, _placement(area=19, belt_tiles=8)),
    )

    forward = _merge_sequence_island_outcomes(
        outcomes,
        requested=4,
        spec_label="merge",
        budget_s=15.0,
    )
    reverse = _merge_sequence_island_outcomes(
        tuple(reversed(outcomes)),
        requested=4,
        spec_label="merge",
        budget_s=15.0,
    )

    assert forward == reverse
    assert forward.island_id == 0
    assert forward.seed == 100


def test_partial_refusals_and_invalid_outcomes_do_not_displace_valid_exact() -> None:
    valid = _SequenceIslandOutcome.completed(2, 202, _placement(area=30, belt_tiles=5))
    outcomes = (
        _SequenceIslandOutcome.refused(0, 100, "deadline exhausted", "partial", 15.0),
        _SequenceIslandOutcome.invalid(1, 101, _placement(area=1, belt_tiles=1)),
        valid,
    )

    assert (
        _merge_sequence_island_outcomes(
            outcomes,
            requested=3,
            spec_label="partial",
            budget_s=15.0,
        )
        == valid
    )


def test_all_refused_raises_structured_no_valid_layout() -> None:
    outcomes = (
        _SequenceIslandOutcome.refused(1, 101, "unroutable", "all", 15.0),
        _SequenceIslandOutcome.refused(0, 100, "deadline exhausted", "all", 15.0),
    )

    with pytest.raises(NoValidLayout) as exc_info:
        _merge_sequence_island_outcomes(
            outcomes,
            requested=2,
            spec_label="all",
            budget_s=15.0,
        )

    assert exc_info.value.spec_label == "all"
    assert exc_info.value.budget_s == 15.0
    assert exc_info.value.reason == (
        "all 2 sequence islands refused: island 0: deadline exhausted; island 1: unroutable"
    )


class _ImmediateExecutor:
    raised: BaseException | None = None
    instances: list[_ImmediateExecutor] = []

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.requests: list[Any] = []
        self.terminated = False
        self.killed = False
        self.shutdown_calls: list[tuple[bool, bool]] = []
        type(self).instances.append(self)

    def submit(self, fn: Any, request: Any) -> Future[_SequenceIslandOutcome]:
        del fn
        self.requests.append(request)
        future: Future[_SequenceIslandOutcome] = Future()
        if self.raised is not None:
            future.set_exception(self.raised)
        else:
            future.set_result(
                _SequenceIslandOutcome.completed(
                    request.island_id,
                    request.seed,
                    _placement(area=20 + request.island_id, belt_tiles=4),
                )
            )
        return future

    def terminate_workers(self) -> None:
        self.terminated = True

    def kill_workers(self) -> None:
        self.killed = True

    def shutdown(self, wait: bool = True, *, cancel_futures: bool = False) -> None:
        self.shutdown_calls.append((wait, cancel_futures))


class _PendingExecutor(_ImmediateExecutor):
    def submit(self, fn: Any, request: Any) -> Future[_SequenceIslandOutcome]:
        del fn
        self.requests.append(request)
        future: Future[_SequenceIslandOutcome] = Future()
        return future


@pytest.mark.parametrize("raised", [RuntimeError("worker exploded"), KeyboardInterrupt()])
def test_worker_failure_or_interrupt_terminates_and_propagates(
    monkeypatch: pytest.MonkeyPatch,
    raised: BaseException,
) -> None:
    _ImmediateExecutor.instances.clear()
    _ImmediateExecutor.raised = raised
    monkeypatch.setattr(islands_module, "ProcessPoolExecutor", _ImmediateExecutor)

    with pytest.raises(type(raised), match=str(raised) or None):
        SequencePairLayout(islands=2).lay_out(two_stage_spec(), time_budget_s=2.0)

    executor = _ImmediateExecutor.instances[-1]
    assert executor.terminated
    assert not executor.killed


def test_parent_deadline_terminates_active_workers_and_refuses_without_an_exact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ImmediateExecutor.instances.clear()
    _ImmediateExecutor.raised = None
    monkeypatch.setattr(islands_module, "ProcessPoolExecutor", _ImmediateExecutor)
    monkeypatch.setattr(
        islands_module,
        "wait",
        lambda futures, *, timeout: (set(), set(futures)),
    )

    with pytest.raises(NoValidLayout, match="deadline exhausted"):
        SequencePairLayout(islands=2).lay_out(two_stage_spec(), time_budget_s=2.0)

    executor = _ImmediateExecutor.instances[-1]
    assert executor.terminated
    assert not executor.killed


def test_child_soft_deadline_leaves_parent_time_to_collect_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _PendingExecutor.instances.clear()
    monkeypatch.setattr(islands_module, "ProcessPoolExecutor", _PendingExecutor)
    ticks = iter((100.0, 111.0))
    monkeypatch.setattr(
        "flab2bp.layout.sequence_islands.time.monotonic",
        lambda: next(ticks),
    )
    observed_waits: list[float | None] = []

    def complete_at_soft_deadline(
        futures: list[Future[_SequenceIslandOutcome]],
        *,
        timeout: float | None,
    ) -> tuple[set[Future[_SequenceIslandOutcome]], set[Future[_SequenceIslandOutcome]]]:
        observed_waits.append(timeout)
        executor = _PendingExecutor.instances[-1]
        for future, request in zip(futures, executor.requests, strict=True):
            future.set_result(
                _SequenceIslandOutcome.completed(
                    request.island_id,
                    request.seed,
                    _placement(area=20 + request.island_id, belt_tiles=4),
                )
            )
        return set(futures), set()

    monkeypatch.setattr(islands_module, "wait", complete_at_soft_deadline)

    placement = SequencePairLayout(islands=3).lay_out(
        two_stage_spec(),
        time_budget_s=2.0,
    )

    executor = _PendingExecutor.instances[-1]
    assert {request.soft_deadline for request in executor.requests} == {111.0}
    assert observed_waits == [4.0]
    assert executor.kwargs["mp_context"].get_start_method() == "spawn"
    assert executor.kwargs["max_tasks_per_child"] == 1
    assert placement.stats["islands_requested"] == 3.0
    assert placement.stats["islands_completed"] == 3.0
    assert placement.stats["islands_refused"] == 0.0
    assert placement.stats["winner_island_id"] == 0
    assert placement.stats["winner_island_seed"] == SequenceSolverConfig().seed
    assert placement.stats["island_result_reserve_s"] == 4.0
    assert executor.shutdown_calls[-1] == (True, False)


@pytest.mark.parametrize(
    ("time_budget_s", "ceiling", "soft_deadline", "hard_deadline"),
    (
        (0.0, 15.0, 111.0, 115.0),
        (0.01, 15.0, 111.0, 115.0),
        (30.0, 30.0, 126.0, 130.0),
    ),
)
def test_deadline_split_preserves_the_parent_ceiling(
    time_budget_s: float,
    ceiling: float,
    soft_deadline: float,
    hard_deadline: float,
) -> None:
    assert _sequence_island_deadlines(time_budget_s, started=100.0) == (
        ceiling,
        soft_deadline,
        hard_deadline,
    )


@pytest.mark.parametrize(
    ("ceiling", "expected"),
    ((9.0, 3.0), (12.0, 4.0), (30.0, 4.0), (60.0, 4.0)),
)
def test_result_reserve_formula_is_bounded(
    ceiling: float,
    expected: float,
) -> None:
    assert _sequence_island_result_reserve_s(ceiling) == expected


def test_two_spawned_islands_match_the_same_islands_run_serially() -> None:
    spec = two_stage_spec()
    config = SequenceSolverConfig.test()
    seeds = _sequence_island_seeds(config.seed, 2)
    serial = tuple(
        SequencePairLayout(config=replace(config, seed=seed)).lay_out(spec, time_budget_s=2.0)
        for seed in seeds
    )
    expected_id, expected = min(
        enumerate(serial),
        key=lambda item: (
            item[1].area,
            int(item[1].stats["belt_tiles"]),
            item[0],
        ),
    )

    parallel = SequencePairLayout(islands=2, config=config).lay_out(spec, time_budget_s=2.0)

    assert parallel.buildings == expected.buildings
    assert parallel.area == expected.area
    assert parallel.stats["belt_tiles"] == expected.stats["belt_tiles"]
    assert parallel.stats["winner_island_id"] == expected_id
    assert parallel.stats["islands_completed"] >= 1.0
    assert parallel.stats["winner_island_seed"] == seeds[expected_id]
