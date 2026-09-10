from __future__ import annotations

import contextlib
import multiprocessing
import pickle
import time
from collections.abc import Callable, Mapping
from concurrent.futures import Future, ProcessPoolExecutor
from dataclasses import replace
from multiprocessing.context import BaseContext
from typing import Never, TypedDict

import pytest

import flab2bp.layout.sequence_islands as islands_module
from flab2bp.lab.techs import belt_rules_for_url
from flab2bp.layout import validate
from flab2bp.layout.band_policy import BandPolicy
from flab2bp.layout.base import (
    NoValidLayout,
    PlacedBuilding,
    Placement,
    ProjectionFailureRecord,
)
from flab2bp.layout.compact_seed import CompactSeedConfig, solve_compact_seed
from flab2bp.layout.sequence_islands import (
    _merge_sequence_island_outcomes,
    _run_sequence_island,
    _sequence_island_deadlines,
    _sequence_island_seeds,
    _SequenceIslandOutcome,
    _SequenceIslandRequest,
)
from flab2bp.layout.sequence_pair import PlacementProblem, derive_stage_seed
from flab2bp.layout.sequence_solver import SequencePairLayout, SequenceSolverConfig
from flab2bp.layout.strategy_race import RACE_COMPLETION_GRACE_S
from flab2bp.spec import BuildSpec
from tests.layout.test_freeform import two_stage_spec

_BELT_RULES = belt_rules_for_url("https://factoriolab.github.io/dsp/list?o=iron-ingot*60&v=11")


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
            SequencePairLayout(
                belt_rules=_BELT_RULES, band_policy=BandPolicy("portable"), islands=islands
            )

    def factory(
        spec: BuildSpec,
        *,
        time_budget_s: float,
        power: bool,
        strip_len: int,
        config: SequenceSolverConfig,
    ) -> Never:
        del spec, time_budget_s, power, strip_len, config
        raise AssertionError("factory must not be called")

    with pytest.raises(ValueError, match="solver factory requires exactly one island"):
        SequencePairLayout(
            belt_rules=_BELT_RULES,
            band_policy=BandPolicy("portable"),
            islands=2,
            solver_factory=factory,
        )


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


def test_refused_island_keeps_its_observed_stage_through_race_and_json() -> None:
    import json

    from flab2bp.layout.base import LayoutAttemptFailure
    from flab2bp.layout.strategy_race import _StrategyRaceOutcome
    from flab2bp.pipeline import _raced_result
    from flab2bp.web.payload import attempt_failure

    config = SequenceSolverConfig.test()
    request = _SequenceIslandRequest(
        spec=two_stage_spec(),
        time_budget_s=0.001,
        soft_deadline=time.monotonic(),
        power=False,
        band_policy=BandPolicy("portable"),
        belt_rules=_BELT_RULES,
        strip_len=6,
        config=config,
        island_id=3,
        seed=config.seed,
        compact_seed_attempt=None,
        compact_seed_base_seed=config.seed,
        compact_seed_config=CompactSeedConfig(max_deterministic_time=0.01),
    )
    outcome = pickle.loads(pickle.dumps(_run_sequence_island(request)))
    with pytest.raises(NoValidLayout) as refused:
        _merge_sequence_island_outcomes(
            (outcome,), requested=1, spec_label=request.spec.label, budget_s=request.time_budget_s
        )
    assert len(refused.value.attempt_failures) == 1
    child = refused.value.attempt_failures[0]
    assert child.stats["stages"] == 0
    assert child.stats["backend"] == "sequence-pair"
    assert child.strategy == "sequence-pair/island-3"
    raced = _StrategyRaceOutcome.refused(
        "sequence-pair",
        refused.value.reason,
        request.spec.label,
        request.time_budget_s,
        attempt_failures=refused.value.attempt_failures,
    )
    result = _raced_result(
        pickle.loads(pickle.dumps(raced)), request.spec.label, request.time_budget_s
    )
    assert isinstance(result, NoValidLayout)
    body = attempt_failure(
        LayoutAttemptFailure(
            request.spec.label, "sequence-pair", result.reason, children=result.attempt_failures
        )
    )
    assert isinstance(body, dict)
    children = body["children"]
    assert isinstance(children, list)
    leaf = children[0]
    assert isinstance(leaf, dict)
    assert leaf["reason"] == child.reason
    assert leaf["strategy"] == "sequence-pair/island-3"
    stats = leaf["stats"]
    assert isinstance(stats, dict)
    assert stats["stages"] == 0
    assert stats["backend"] == "sequence-pair"
    assert stats["seed"] == config.seed
    json.dumps(body, allow_nan=False)


class _ExecutorKwargs(TypedDict):
    max_workers: int
    mp_context: BaseContext
    max_tasks_per_child: int


class _ImmediateExecutor:
    raised: BaseException | None = None
    instances: list[_ImmediateExecutor] = []

    def __init__(
        self,
        *,
        max_workers: int,
        mp_context: BaseContext,
        max_tasks_per_child: int,
    ) -> None:
        self.kwargs: _ExecutorKwargs = {
            "max_workers": max_workers,
            "mp_context": mp_context,
            "max_tasks_per_child": max_tasks_per_child,
        }
        self.requests: list[_SequenceIslandRequest] = []
        self.terminated = False
        self.killed = False
        self.shutdown_calls: list[tuple[bool, bool]] = []
        type(self).instances.append(self)

    def submit(
        self,
        fn: Callable[[_SequenceIslandRequest], _SequenceIslandOutcome],
        request: _SequenceIslandRequest,
    ) -> Future[_SequenceIslandOutcome]:
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
    def submit(
        self,
        fn: Callable[[_SequenceIslandRequest], _SequenceIslandOutcome],
        request: _SequenceIslandRequest,
    ) -> Future[_SequenceIslandOutcome]:
        del fn
        self.requests.append(request)
        future: Future[_SequenceIslandOutcome] = Future()
        return future


def test_compact_portfolio_uses_root_seed_once_while_search_seeds_stay_distinct(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = 20260824
    config = SequenceSolverConfig.test()
    assert config.seed == root
    _ImmediateExecutor.instances.clear()
    _ImmediateExecutor.raised = None
    monkeypatch.setattr(islands_module, "ProcessPoolExecutor", _ImmediateExecutor)

    SequencePairLayout(
        belt_rules=_BELT_RULES, band_policy=BandPolicy("portable"), islands=8, config=config
    ).lay_out(
        two_stage_spec(),
        time_budget_s=2.0,
    )

    requests = _ImmediateExecutor.instances[-1].requests
    assert [request.seed for request in requests] == list(_sequence_island_seeds(root, 8))
    assert {request.power for request in requests} == {True}
    assert len({request.seed for request in requests}) == 8
    seeded = requests
    assert [request.compact_seed_attempt for request in seeded] == list(range(8))
    assert {request.compact_seed_base_seed for request in seeded} == {root}

    problem = PlacementProblem(
        sizes=((1, 1),),
        nets=(),
        outline_height=1,
        area_lower_bound=1,
    )
    compact_config = CompactSeedConfig(max_deterministic_time=0.01)
    for request in seeded:
        attempt = request.compact_seed_attempt
        assert attempt is not None
        from_request = solve_compact_seed(
            problem,
            base_seed=request.compact_seed_base_seed,
            attempt=attempt,
            config=compact_config,
        )
        standalone = solve_compact_seed(
            problem,
            base_seed=root,
            attempt=attempt,
            config=compact_config,
        )
        assert from_request.status is standalone.status
        assert from_request.state == standalone.state
        assert from_request.diagnostics.solver_seed == (
            derive_stage_seed(root, attempt) % ((1 << 31) - 1)
        )


@pytest.mark.parametrize("raised", [RuntimeError("worker exploded"), KeyboardInterrupt()])
def test_worker_failure_or_interrupt_terminates_and_propagates(
    monkeypatch: pytest.MonkeyPatch,
    raised: BaseException,
) -> None:
    _ImmediateExecutor.instances.clear()
    _ImmediateExecutor.raised = raised
    monkeypatch.setattr(islands_module, "ProcessPoolExecutor", _ImmediateExecutor)

    with pytest.raises(type(raised), match=str(raised) or None):
        SequencePairLayout(
            belt_rules=_BELT_RULES, band_policy=BandPolicy("portable"), islands=2
        ).lay_out(two_stage_spec(), time_budget_s=2.0)

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
        SequencePairLayout(
            belt_rules=_BELT_RULES, band_policy=BandPolicy("portable"), islands=2
        ).lay_out(two_stage_spec(), time_budget_s=2.0)

    executor = _ImmediateExecutor.instances[-1]
    assert executor.terminated
    assert not executor.killed


def test_parent_deadline_preserves_settled_refusals_in_island_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _PendingExecutor.instances.clear()
    monkeypatch.setattr(islands_module, "ProcessPoolExecutor", _PendingExecutor)
    refusal_zero = (
        "no scheduled stage produced an exact layout; "
        "no legal DSP latitude band/orientation accepts the final placement: "
        "band 160 geom.collide (4, 9): first projected collision"
    )
    refusal_two = (
        "no scheduled stage produced an exact layout; "
        "no legal DSP latitude band/orientation accepts the final placement: "
        "band 240 game.power_too_close (2, 7): later projected power refusal"
    )
    first = ProjectionFailureRecord(
        band=160,
        check="geom.collide",
        buildings=(4, 9),
        detail="first projected collision; collider A; collider B",
    )
    second = ProjectionFailureRecord(
        band=240,
        check="game.power_too_close",
        buildings=(2, 7),
        detail="later projected power refusal; north; south",
    )

    def settle_two_islands(
        futures: list[Future[_SequenceIslandOutcome]],
        *,
        timeout: float | None,
    ) -> tuple[set[Future[_SequenceIslandOutcome]], set[Future[_SequenceIslandOutcome]]]:
        assert timeout is not None
        executor = _PendingExecutor.instances[-1]
        futures[2].set_result(
            _SequenceIslandOutcome.refused(
                2,
                executor.requests[2].seed,
                refusal_two,
                "mixed",
                2.0,
                projection_failures=(second,),
            )
        )
        futures[0].set_result(
            _SequenceIslandOutcome.refused(
                0,
                executor.requests[0].seed,
                refusal_zero,
                "mixed",
                2.0,
                projection_failures=(first,),
            )
        )
        return {futures[2], futures[0]}, {futures[1]}

    monkeypatch.setattr(islands_module, "wait", settle_two_islands)

    with pytest.raises(NoValidLayout) as caught:
        SequencePairLayout(
            belt_rules=_BELT_RULES,
            band_policy=BandPolicy("portable"),
            islands=3,
        ).lay_out(two_stage_spec(), time_budget_s=2.0)

    assert caught.value.reason == (
        "deadline exhausted before any sequence island produced an exact layout; "
        f"settled island refusals: island 0: {refusal_zero}; island 2: {refusal_two}"
    )
    assert [
        (failure.band, failure.check, failure.buildings, failure.detail)
        for failure in caught.value.projection_failures
    ] == [
        (failure.band, failure.check, failure.buildings, failure.detail)
        for failure in (first, second)
    ]
    executor = _PendingExecutor.instances[-1]
    assert executor.terminated
    assert not executor.killed


def test_child_soft_deadline_leaves_parent_time_to_collect_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _PendingExecutor.instances.clear()
    monkeypatch.setattr(islands_module, "ProcessPoolExecutor", _PendingExecutor)
    ticks = iter((100.0, 101.0))
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

    compact_config = CompactSeedConfig(max_deterministic_time=0.125)
    placement = SequencePairLayout(
        belt_rules=_BELT_RULES,
        band_policy=BandPolicy("portable"),
        islands=3,
        compact_seed_config=compact_config,
    ).lay_out(
        two_stage_spec(),
        time_budget_s=2.0,
    )

    executor = _PendingExecutor.instances[-1]
    assert {request.soft_deadline for request in executor.requests} == {102.0}
    assert [request.compact_seed_attempt for request in executor.requests] == [0, 1, 2]
    assert {request.compact_seed_base_seed for request in executor.requests} == {
        SequenceSolverConfig().seed
    }
    assert pickle.loads(pickle.dumps(executor.requests[1])) == executor.requests[1]
    # started 100.0, budget 2.0, second tick 101.0: the parent waits to the soft
    # deadline (102.0) plus the race grace, less the second it has already spent.
    assert observed_waits == [1.0 + RACE_COMPLETION_GRACE_S]
    assert executor.kwargs["mp_context"].get_start_method() == "spawn"
    assert executor.kwargs["max_tasks_per_child"] == 1
    assert placement.stats["islands_requested"] == 3.0
    assert placement.stats["islands_completed"] == 3.0
    assert placement.stats["islands_refused"] == 0.0
    assert placement.stats["winner_island_id"] == 0
    assert placement.stats["winner_island_seed"] == SequenceSolverConfig().seed
    assert placement.stats["island_result_reserve_s"] == RACE_COMPLETION_GRACE_S
    assert executor.shutdown_calls[-1] == (True, False)


def test_island_reuses_authoritative_search_validation_after_soft_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    placement = _placement(area=20, belt_tiles=4)

    class Solver:
        def search(self, *, feasibility_continuation: bool = False) -> object:
            del feasibility_continuation
            return object()

    class Run:
        solver = Solver()

    monkeypatch.setattr(
        islands_module,
        "_production_run",
        lambda *_args, **_kwargs: Run(),
    )
    monkeypatch.setattr(
        islands_module,
        "_with_observational_stats",
        lambda *_args, **_kwargs: placement,
    )
    monkeypatch.setattr(time, "monotonic", lambda: 101.0)

    def reject_revalidation(*_args: object, **_kwargs: object) -> Never:
        raise AssertionError("island must reuse the solver's authoritative validation")

    class RejectingValidator:
        certify = staticmethod(reject_revalidation)

    monkeypatch.setattr(
        islands_module,
        "validate",
        RejectingValidator,
        raising=False,
    )
    request = _SequenceIslandRequest(
        spec=two_stage_spec(),
        time_budget_s=1.0,
        soft_deadline=100.0,
        power=False,
        band_policy=BandPolicy("portable"),
        belt_rules=_BELT_RULES,
        strip_len=6,
        config=SequenceSolverConfig.test(),
        island_id=0,
        seed=SequenceSolverConfig.test().seed,
        compact_seed_attempt=None,
        compact_seed_base_seed=SequenceSolverConfig.test().seed,
        compact_seed_config=CompactSeedConfig(max_deterministic_time=0.01),
    )

    outcome = _run_sequence_island(request)

    assert outcome.status == "completed"
    assert outcome.placement is placement


def test_island_child_asks_its_solver_to_continue_for_feasibility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An island child carries its own deadline, so it gets the continuation too."""
    placement = _placement(area=20, belt_tiles=4)
    captured: dict[str, object] = {}

    class Solver:
        def search(self, **kwargs: object) -> object:
            captured.update(kwargs)
            return object()

    class Run:
        solver = Solver()

    monkeypatch.setattr(
        islands_module,
        "_production_run",
        lambda *_args, **_kwargs: Run(),
    )
    monkeypatch.setattr(
        islands_module,
        "_with_observational_stats",
        lambda *_args, **_kwargs: placement,
    )

    request = _SequenceIslandRequest(
        spec=two_stage_spec(),
        time_budget_s=1.0,
        soft_deadline=time.monotonic() + 100.0,
        power=False,
        band_policy=BandPolicy("portable"),
        belt_rules=_BELT_RULES,
        strip_len=6,
        config=SequenceSolverConfig.test(),
        island_id=0,
        seed=SequenceSolverConfig.test().seed,
        compact_seed_attempt=None,
        compact_seed_base_seed=SequenceSolverConfig.test().seed,
        compact_seed_config=CompactSeedConfig(max_deterministic_time=0.01),
    )

    assert _run_sequence_island(request).status == "completed"
    assert captured["feasibility_continuation"] is True


@pytest.mark.parametrize(
    ("time_budget_s", "ceiling", "soft_deadline", "hard_deadline"),
    (
        (0.0, 0.0, 100.0, 100.0),
        (0.01, 0.01, 100.01, 100.01 + RACE_COMPLETION_GRACE_S),
        (30.0, 30.0, 130.0, 130.0 + RACE_COMPLETION_GRACE_S),
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


def test_two_real_spawned_islands_are_unseeded_then_seeded_and_both_valid() -> None:
    spec = two_stage_spec()
    config = replace(SequenceSolverConfig.test(), seed=9_007_199_254_740_993)
    compact_config = CompactSeedConfig(max_deterministic_time=0.05)
    seeds = _sequence_island_seeds(config.seed, 2)
    soft_deadline = time.monotonic() + 20.0
    requests = tuple(
        _SequenceIslandRequest(
            spec=spec,
            time_budget_s=2.0,
            soft_deadline=soft_deadline,
            power=False,
            band_policy=BandPolicy("portable"),
            belt_rules=_BELT_RULES,
            strip_len=6,
            config=config,
            island_id=island_id,
            seed=seed,
            compact_seed_attempt=None if island_id == 0 else island_id - 1,
            compact_seed_base_seed=config.seed,
            compact_seed_config=compact_config,
        )
        for island_id, seed in enumerate(seeds)
    )
    assert pickle.loads(pickle.dumps(requests)) == requests

    with ProcessPoolExecutor(
        max_workers=2,
        mp_context=multiprocessing.get_context("spawn"),
        max_tasks_per_child=1,
    ) as executor:
        outcomes = tuple(executor.map(_run_sequence_island, requests))

    assert [outcome.status for outcome in outcomes] == ["completed", "completed"]
    island0, island1 = (outcome.placement for outcome in outcomes)
    assert island0 is not None and island1 is not None
    assert not validate.certify(island0, spec, belt_rules=_BELT_RULES, expect_power=False).errors
    assert not validate.certify(island1, spec, belt_rules=_BELT_RULES, expect_power=False).errors
    assert "compact_seed_attempt" not in island0.stats
    assert "compact_seed_closures" not in island0.stats
    assert island1.stats["compact_seed_attempt"] == 0.0
    assert island1.stats["compact_seed_base_seed"] == config.seed
    observational_stats: Mapping[str, object] = island1.stats
    assert observational_stats["compact_seed_status"] in {"optimal", "feasible"}
    assert island1.stats["compact_seed_decoded_width"] >= 1.0
    assert island1.stats["compact_seed_closures"] == 1.0
    assert observational_stats["compact_seed_closure_status"] == "routed"
    assert observational_stats["compact_seed_closure_backend"] == "cython"
    assert island1.stats["compact_seed_closure_exact"] == 1.0


def test_one_island_keeps_the_serial_seed_exactly() -> None:
    # Exactness contract: a 1-island run must be bit-identical to the serial
    # run, and that rests entirely on island zero keeping the serial seed.
    for seed in (0, 1, 9_007_199_254_740_993):
        assert _sequence_island_seeds(seed, 1) == (seed,)
        assert _sequence_island_seeds(seed, 8)[0] == seed


def test_the_island_completion_grace_is_the_race_grace() -> None:
    # `_ISLAND_COMPLETION_GRACE_S = 90.0` was a second budget, not a grace.
    # The island runner now waits exactly as long past the deadline as the
    # strategy race does, and the old constant must be gone rather than
    # merely unused.
    assert not hasattr(islands_module, "_ISLAND_COMPLETION_GRACE_S")
    _, soft, hard = _sequence_island_deadlines(30.0, started=100.0)
    assert hard - soft == RACE_COMPLETION_GRACE_S


def test_a_real_island_pool_spawns_and_returns_promptly_at_a_tiny_ceiling() -> None:
    """A SPAWN SMOKE, not the grace regression guard.

    It proves the real pool starts, settles and tears down without hanging, and
    it would catch a runner that waited out a second budget.  It does NOT
    discriminate 6.0 from 90.0: at a 0.001 s ceiling the children refuse almost
    immediately, so `wait` returns long before either grace could expire.  The
    grace itself is guarded by
    `test_deadline_split_preserves_the_parent_ceiling`'s table and by
    `test_child_soft_deadline_leaves_parent_time_to_collect_result`'s
    `observed_waits` assertion, both of which read the constant directly.
    """
    spec = two_stage_spec()
    config = replace(SequenceSolverConfig.test(), seed=9_007_199_254_740_993)
    started = time.monotonic()
    # Either shape is a pass: what is under test is WHEN the parent gives up,
    # not whether two children with a millisecond of budget found a layout.
    with contextlib.suppress(NoValidLayout):
        islands_module.run_sequence_islands(
            spec,
            time_budget_s=0.001,
            band_policy=BandPolicy("portable"),
            belt_rules=_BELT_RULES,
            strip_len=6,
            config=config,
            compact_seed_config=CompactSeedConfig(max_deterministic_time=0.01),
            islands=2,
        )
    elapsed = time.monotonic() - started
    #: 20 s of spawn slack: two children each pay ~1 s of import, and this box
    #: is shared.  The point of the bound is that it is nowhere near 90.
    assert elapsed < 0.001 + RACE_COMPLETION_GRACE_S + 20.0
    assert elapsed < 90.0


def test_a_parent_deadline_clamps_the_island_soft_and_hard_deadlines() -> None:
    """Islands inside a raced child must not outlive the parent's allowance.

    The pool starts its clock AFTER spawn, so `started + ceiling` lands one
    spawn-cost past the deadline the race parent is holding everyone to -- and
    the hard deadline lands past the parent's kill time, so the parent killed
    the sequence-pair arm the moment the islands used any of their grace.
    """
    parent_soft = 128.0
    ceiling, soft, hard = _sequence_island_deadlines(
        30.0,
        started=100.0,  # spawn cost: the child started 2 s into the parent's 30
        absolute_deadline=parent_soft,
    )
    #: The ceiling is what was ASKED for, not what is left -- it is what a
    #: refusal reports, and what decides whether a grace is owed at all.
    assert ceiling == 30.0
    assert soft == parent_soft
    assert hard == parent_soft + RACE_COMPLETION_GRACE_S

    # A parent deadline that is not the binding one changes nothing.
    assert _sequence_island_deadlines(
        30.0,
        started=100.0,
        absolute_deadline=1_000.0,
    ) == (30.0, 130.0, 130.0 + RACE_COMPLETION_GRACE_S)


def test_the_island_runner_passes_the_parent_deadline_to_its_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`SequencePairLayout.lay_out` must hand `absolute_deadline` down.

    Without this wiring the clamp above is unreachable from a raced child, which
    is the only place it matters.
    """
    _PendingExecutor.instances.clear()
    monkeypatch.setattr(islands_module, "ProcessPoolExecutor", _PendingExecutor)
    ticks = iter((100.0, 101.0))
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

    placement = SequencePairLayout(
        belt_rules=_BELT_RULES,
        band_policy=BandPolicy("portable"),
        islands=2,
        compact_seed_config=CompactSeedConfig(max_deterministic_time=0.125),
    ).lay_out(
        two_stage_spec(),
        time_budget_s=30.0,
        # The race parent's wall: 1.5 s before this pool's own `started + 30`.
        absolute_deadline=128.5,
    )

    executor = _PendingExecutor.instances[-1]
    assert {request.soft_deadline for request in executor.requests} == {128.5}
    # 128.5 + grace, less the one second the parent clock already spent.
    assert observed_waits == [128.5 + RACE_COMPLETION_GRACE_S - 101.0]
    assert placement.stats["island_result_reserve_s"] == RACE_COMPLETION_GRACE_S
