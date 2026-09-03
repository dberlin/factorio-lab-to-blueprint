from __future__ import annotations

import multiprocessing
import pickle
import queue
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import fields, replace
from fractions import Fraction
from typing import get_type_hints

import pytest

import flab2bp.layout.strategy_race as strategy_race_module
from flab2bp.dsp import catalog, provenance, registry
from flab2bp.layout.band_policy import BandPolicy
from flab2bp.layout.compact_seed import CompactSeedConfig
from flab2bp.layout.sequence_solver import SequenceSolverConfig
from flab2bp.layout.strategy_race import (
    RACE_COMPLETION_GRACE_S,
    RACE_DRAIN_MAX_MESSAGES,
    RACE_FREEFORM_WORKER_SHARE,
    RACE_MIN_WORKERS,
    RACE_QUEUE_MAXSIZE,
    RACE_STRATEGIES,
    IncumbentMessage,
    NoGoodMessage,
    RaceChannels,
    RaceStrategyName,
    RaceSubmit,
    _channels_for,
    _install_race_channels,
    _JoinCancellable,
    _ordered,
    _run_race_leg,
    _StrategyRaceOutcome,
    _StrategyRaceRequest,
    _terminate_executor,
    race_worker_split,
    run_strategy_race,
)
from flab2bp.layout.strip_variants import StripFamilyId, StripInstanceId
from tests.layout.test_freeform import two_stage_spec


def _request(strategy: RaceStrategyName = "freeform") -> _StrategyRaceRequest:
    return _StrategyRaceRequest(
        spec=two_stage_spec(),
        strategy=strategy,
        time_budget_s=30.0,
        soft_deadline=1234.5,
        band_policy=BandPolicy("portable"),
        belt_vertical_construction=True,
        max_belt_z=catalog.DEFAULT_MAX_BELT_Z,
        workers=6,
        arrangements=None,
        sequence_islands=1,
        config=SequenceSolverConfig(),
        compact_seed_config=CompactSeedConfig(),
        share=True,
    )


def test_the_request_round_trips_through_pickle() -> None:
    request = _request()

    assert pickle.loads(pickle.dumps(request)) == request


def test_the_request_carries_no_queue() -> None:
    # A multiprocessing.Queue cannot be pickled as a pool TASK argument.  Putting
    # one in the request fails ONLY under spawn, which is exactly the mode
    # production uses and the mode a fast unit test does not.
    names = {field.name for field in fields(_StrategyRaceRequest)}

    assert not {name for name in names if "queue" in name or "channel" in name}


def test_every_request_field_is_read_by_a_racer() -> None:
    # `power` was in an earlier draft and is deliberately absent: both lay_out
    # implementations hard-code powered emission, so the field would be a knob
    # that does not turn.
    assert {field.name for field in fields(_StrategyRaceRequest)} == {
        "spec",
        "strategy",
        "time_budget_s",
        "soft_deadline",
        "band_policy",
        "belt_vertical_construction",
        "max_belt_z",
        "workers",
        "arrangements",
        "sequence_islands",
        "config",
        "compact_seed_config",
        "share",
    }


@pytest.mark.parametrize(
    "outcome",
    [
        _StrategyRaceOutcome("freeform", "refused", refusal_reason="deadline exhausted"),
        _StrategyRaceOutcome("sequence-pair", "terminated", refusal_reason="overran"),
        _StrategyRaceOutcome("freeform", "crashed", refusal_reason="ValueError: x"),
    ],
)
def test_outcomes_round_trip_through_pickle(outcome: _StrategyRaceOutcome) -> None:
    assert pickle.loads(pickle.dumps(outcome)) == outcome


def test_messages_round_trip_through_pickle() -> None:
    incumbent = IncumbentMessage("freeform", (480, 62))
    no_good = NoGoodMessage(
        "freeform",
        (StripInstanceId(StripFamilyId("iron-ingot", 0), 0, 4),),
        no_good=("relation", 0, 1),
    )

    assert pickle.loads(pickle.dumps(incumbent)) == incumbent
    assert pickle.loads(pickle.dumps(no_good)) == no_good


def test_the_incumbent_message_is_one_key_not_three_numbers() -> None:
    # `area` and `belt_tiles` as separate fields would be the same two numbers a
    # second time, and `height` had no reader at all.
    assert {field.name for field in fields(IncumbentMessage)} == {"strategy", "exact_key"}


def test_channels_publish_drain_and_drop() -> None:
    outbound: queue.Queue[object] = queue.Queue(maxsize=2)
    inbox: queue.Queue[object] = queue.Queue(maxsize=RACE_QUEUE_MAXSIZE)
    channels = RaceChannels(publish=outbound, consume=inbox)
    first = IncumbentMessage("freeform", (480, 62))
    second = IncumbentMessage("freeform", (470, 60))
    third = IncumbentMessage("freeform", (460, 58))

    channels.publish_incumbent(first)
    channels.publish_incumbent(second)
    channels.publish_incumbent(third)  # queue is full: dropped, not raised

    assert channels.dropped == 1

    spare: queue.Queue[object] = queue.Queue()
    inbound = RaceChannels(publish=spare, consume=channels.publish)

    assert inbound.drain() == (first, second)
    assert inbound.drain() == ()


def test_drain_is_bounded_per_poll() -> None:
    consume: queue.Queue[object] = queue.Queue()
    for area in range(RACE_DRAIN_MAX_MESSAGES + 5):
        consume.put(IncumbentMessage("freeform", (area, 0)))
    publish: queue.Queue[object] = queue.Queue()
    channels = RaceChannels(publish=publish, consume=consume)

    assert len(channels.drain()) == RACE_DRAIN_MAX_MESSAGES
    assert len(channels.drain()) == 5


def test_drain_bounds_what_it_pulls_not_only_what_it_keeps() -> None:
    # The bound exists so a burst cannot turn a poll into a pause, and the cost
    # of a poll is the GET, not the append.  Bounding only the accepted items
    # lets a queue full of things that are not messages be drained end to end in
    # one call -- the exact pause the constant is there to prevent.
    consume: queue.Queue[object] = queue.Queue()
    for _ in range(RACE_DRAIN_MAX_MESSAGES + 5):
        consume.put(object())
    publish: queue.Queue[object] = queue.Queue()
    channels = RaceChannels(publish=publish, consume=consume)

    assert channels.drain() == ()
    assert consume.qsize() == 5


@pytest.mark.parametrize(
    ("total", "expected"),
    [
        (1, (1, 1)),
        (2, (1, 1)),
        (3, (2, 1)),
        (4, (3, 1)),
        (8, (6, 2)),
        (16, (12, 4)),
        (128, (96, 32)),
    ],
)
def test_the_worker_split_never_hands_a_racer_zero(total: int, expected: tuple[int, int]) -> None:
    # ortools reads num_search_workers == 0 as ALL CORES, so a split that ever
    # produced 0 would hand one racer the whole box.
    split = race_worker_split(total)

    assert split == expected
    assert min(split) >= RACE_MIN_WORKERS


def test_the_worker_split_sums_to_the_total_it_was_given() -> None:
    # Only for total >= 3: at 1 and 2 the floor of one worker per racer wins and
    # a single-core box is deliberately oversubscribed by one thread.
    for total in (3, 4, 8, 16, 128):
        assert sum(race_worker_split(total)) == total


def test_the_worker_split_refuses_a_nonsense_total() -> None:
    with pytest.raises(ValueError, match="positive integer"):
        race_worker_split(0)


def test_the_worker_split_refuses_a_negative_total() -> None:
    with pytest.raises(ValueError, match="positive integer"):
        race_worker_split(-4)


def test_the_worker_split_refuses_a_bool() -> None:
    # `True` is an int to isinstance and would split as 1; the exact type check
    # is what keeps a flag from being read as a core count.
    with pytest.raises(ValueError, match="positive integer"):
        race_worker_split(True)


def test_outcomes_are_ordered_by_strategy_not_by_arrival() -> None:
    late = _StrategyRaceOutcome("freeform", "refused", refusal_reason="f")
    early = _StrategyRaceOutcome("sequence-pair", "refused", refusal_reason="s")

    assert tuple(o.strategy for o in _ordered((early, late))) == RACE_STRATEGIES


def test_the_race_runs_exactly_the_two_production_strategies() -> None:
    assert RACE_STRATEGIES == ("freeform", "sequence-pair")


def test_the_freeform_share_is_three_quarters() -> None:
    assert Fraction(3, 4) == RACE_FREEFORM_WORKER_SHARE


def test_the_worker_share_is_a_declared_coincidence_not_a_lint_dodge() -> None:
    # `Fraction(3, 4)` is 0.75, which R1 owns as catalog.MAX_BELT_SLOPE, and
    # `test_the_lint_would_catch_a_fraction_spelling_of_one` exists to make sure
    # that spelling cannot hide.  So the share is written the obvious way and the
    # coincidence is DECLARED, beside freeform's `_PACK_SHARE`.
    #
    # `not stale` is the half with teeth: an exception matching no site is what
    # `provenance.stale_lint_exceptions` reports, so re-spelling the constant to
    # duck the lint -- named integers, a division, anything -- fails here rather
    # than quietly leaving a declaration behind that explains nothing.
    site = ("flab2bp.layout.strategy_race", "<module>", 0.75)
    declared = {(e.module, e.where, e.value) for e in registry.LINT_EXCEPTIONS}
    stale = {(e.module, e.where, e.value) for e in provenance.stale_lint_exceptions()}

    assert site in declared
    assert site not in stale


def test_the_incumbent_key_is_pinned_to_two_ints() -> None:
    # freeform's `best_key` and `sequence_solver._exact_key` are both
    # (area, belt_tiles); a widened annotation here would let a third number in
    # on one side of the race and not the other.
    assert get_type_hints(IncumbentMessage)["exact_key"] == tuple[int, int]


def test_close_cancels_the_join_thread_when_the_queue_has_one() -> None:
    # multiprocessing.Queue has cancel_join_thread and queue.Queue does not, so
    # close() must act on the first and be a no-op on the second.  Without this,
    # a child with unflushed hints blocks its own exit until a reader that is
    # never coming arrives.
    class _Cancellable:
        def __init__(self) -> None:
            self.cancelled = 0

        def put_nowait(self, item: object, /) -> None:
            raise AssertionError("close() must not publish")

        def get_nowait(self) -> object:
            raise queue.Empty

        def cancel_join_thread(self) -> None:
            self.cancelled += 1

    publish = _Cancellable()
    consume: queue.Queue[object] = queue.Queue()

    RaceChannels(publish=publish, consume=consume).close()

    assert publish.cancelled == 1


def test_close_is_a_no_op_on_a_queue_without_a_feeder_thread() -> None:
    publish: queue.Queue[object] = queue.Queue()
    consume: queue.Queue[object] = queue.Queue()

    RaceChannels(publish=publish, consume=consume).close()  # must not raise


def test_close_cancels_the_join_thread_on_a_real_spawn_context_queue() -> None:
    """The stub proves the branch; only a real queue proves the METHOD exists.

    Task 8 could only test ``close()`` against an in-process stub, because a
    ``queue.Queue`` has no feeder thread to cancel.  The object the race actually
    hands it is a spawn-context ``multiprocessing.Queue``, and if that one ever
    stopped satisfying ``_JoinCancellable`` the stub test would keep passing
    while every child hung on exit holding unflushed hints.

    ``_joincancelled`` is CPython's own record that ``cancel_join_thread`` ran
    (``multiprocessing/queues.py``); it is read through ``vars`` so this test
    does not have to assert against a private attribute mypy cannot see.
    """
    context = multiprocessing.get_context("spawn")
    publish = context.Queue(maxsize=RACE_QUEUE_MAXSIZE)
    consume = context.Queue(maxsize=RACE_QUEUE_MAXSIZE)
    try:
        channels = RaceChannels(publish=publish, consume=consume)
        channels.publish_incumbent(IncumbentMessage("freeform", (480, 62)))

        assert isinstance(publish, _JoinCancellable)
        assert vars(publish)["_joincancelled"] is False

        channels.close()

        assert vars(publish)["_joincancelled"] is True
    finally:
        publish.cancel_join_thread()
        consume.cancel_join_thread()
        publish.close()
        consume.close()


class _NoopExecutor:
    """Stands in for the pool.  Class-level flag so a test can see the kill."""

    terminated = False

    def shutdown(self, wait: bool = True, cancel_futures: bool = False) -> None:
        return None

    def terminate_workers(self) -> None:
        type(self).terminated = True


def _stub_submit(results: dict[str, object]) -> RaceSubmit:
    """Resolve both legs synchronously; ``None`` means "never returns".

    The futures are built in REVERSED ``RACE_STRATEGIES`` order on purpose: the
    order tests below must fail if the parent ever collects in future order
    rather than in strategy order, and building them in strategy order would
    make those assertions pass for the wrong reason.
    """

    def submit(
        requests: tuple[_StrategyRaceRequest, ...],
        channels: dict[str, RaceChannels],
    ) -> tuple[dict[Future[_StrategyRaceOutcome], str], object]:
        futures: dict[Future[_StrategyRaceOutcome], str] = {}
        for request in reversed(requests):
            future: Future[_StrategyRaceOutcome] = Future()
            outcome = results[request.strategy]
            if isinstance(outcome, BaseException):
                future.set_exception(outcome)
            elif outcome is not None:
                assert isinstance(outcome, _StrategyRaceOutcome)
                future.set_result(outcome)
            futures[future] = request.strategy
        return futures, _NoopExecutor()

    return submit


def _race(
    results: dict[str, object],
    *,
    monotonic: Callable[[], float] = time.monotonic,
) -> tuple[_StrategyRaceOutcome, ...]:
    return run_strategy_race(
        two_stage_spec(),
        time_budget_s=0.05,
        band_policy=BandPolicy("portable"),
        belt_vertical_construction=True,
        share=False,
        submit=_stub_submit(results),
        monotonic=monotonic,
    )


def test_both_arms_return_in_strategy_order() -> None:
    outcomes = _race(
        {
            "sequence-pair": _StrategyRaceOutcome(
                "sequence-pair", "refused", refusal_reason="s"
            ),
            "freeform": _StrategyRaceOutcome("freeform", "refused", refusal_reason="f"),
        }
    )

    assert tuple(o.strategy for o in outcomes) == ("freeform", "sequence-pair")


def test_a_crashed_arm_is_reported_and_the_survivor_decides() -> None:
    outcomes = _race(
        {
            "freeform": ValueError("boom"),
            "sequence-pair": _StrategyRaceOutcome(
                "sequence-pair", "refused", refusal_reason="s"
            ),
        }
    )
    crashed = next(o for o in outcomes if o.strategy == "freeform")

    assert crashed.status == "crashed"
    assert "ValueError: boom" in (crashed.refusal_reason or "")
    assert next(o for o in outcomes if o.strategy == "sequence-pair").status == "refused"


def test_two_crashed_arms_reraise_the_first_in_strategy_order() -> None:
    # freeform is first in RACE_STRATEGIES, so its exception is the one that
    # propagates -- deterministically, not by `done`-set iteration order.  The
    # stub hands the futures back sequence-pair first, so a parent that walked
    # them in future order would raise the KeyError instead.
    with pytest.raises(ValueError, match="boom"):
        _race({"freeform": ValueError("boom"), "sequence-pair": KeyError("other")})


def test_a_surviving_arm_means_a_crash_is_reported_and_not_raised() -> None:
    # Only BOTH crashing re-raises: one crash plus one refusal is a race that
    # still has an answer, and turning it into an exception would classify a
    # cell CRASH -- the status the audit reserves for "always a bug here".
    outcomes = _race(
        {
            "freeform": ValueError("boom"),
            "sequence-pair": _StrategyRaceOutcome(
                "sequence-pair", "refused", refusal_reason="s"
            ),
        }
    )

    assert [o.status for o in outcomes] == ["crashed", "refused"]


def test_an_arm_that_ignores_the_wall_is_terminated() -> None:
    _NoopExecutor.terminated = False
    # A fake clock, so the test does not sit out RACE_COMPLETION_GRACE_S.  The
    # first call sets `started`; every later one is already past the hard
    # deadline, so `wait` is entered with timeout 0.0 and returns at once.
    ticks = iter([0.0] + [10_000.0] * 8)
    outcomes = _race(
        {
            "freeform": None,
            "sequence-pair": _StrategyRaceOutcome(
                "sequence-pair", "refused", refusal_reason="s"
            ),
        },
        monotonic=lambda: next(ticks),
    )
    stuck = next(o for o in outcomes if o.strategy == "freeform")

    assert stuck.status == "terminated"
    assert "was terminated" in (stuck.refusal_reason or "")
    assert _NoopExecutor.terminated is True


def test_the_race_spends_the_measured_grace_before_it_kills() -> None:
    """An arm still finishing INSIDE the grace is waited for, not killed.

    The clock says the soft deadline passed half a grace ago, so the parent must
    enter ``wait`` with ``RACE_COMPLETION_GRACE_S / 2`` seconds left rather than
    with 0.0.  The slow arm answers 0.05 s later, sixty times inside that
    allowance; a busier box only makes the parent wait LONGER, never shorter, so
    the assertion is load-monotone in the safe direction.  Drop the grace from
    ``hard_deadline`` and the timeout is 0.0, the arm is `terminated`, and this
    fails.
    """
    _NoopExecutor.terminated = False
    started = 1000.0
    budget_s = 10.0
    ticks = iter([started, started + budget_s + RACE_COMPLETION_GRACE_S / 2] + [0.0] * 8)
    slow: Future[_StrategyRaceOutcome] = Future()

    def submit(
        requests: tuple[_StrategyRaceRequest, ...],
        channels: dict[str, RaceChannels],
    ) -> tuple[dict[Future[_StrategyRaceOutcome], str], object]:
        futures: dict[Future[_StrategyRaceOutcome], str] = {slow: "freeform"}
        quick: Future[_StrategyRaceOutcome] = Future()
        quick.set_result(
            _StrategyRaceOutcome("sequence-pair", "refused", refusal_reason="s")
        )
        futures[quick] = "sequence-pair"
        return futures, _NoopExecutor()

    late = threading.Timer(
        0.05,
        slow.set_result,
        args=(_StrategyRaceOutcome("freeform", "refused", refusal_reason="late"),),
    )
    late.start()
    try:
        outcomes = run_strategy_race(
            two_stage_spec(),
            time_budget_s=budget_s,
            band_policy=BandPolicy("portable"),
            belt_vertical_construction=True,
            share=False,
            submit=submit,
            monotonic=lambda: next(ticks),
        )
    finally:
        late.cancel()

    assert next(o for o in outcomes if o.strategy == "freeform").status == "refused"
    assert _NoopExecutor.terminated is False


def test_the_requests_carry_the_parents_wall_not_a_budget_to_start_later() -> None:
    # A child cannot compute its own deadline: spawn, interpreter start and
    # unpickling the spec all happen after the parent started the clock.  So the
    # request carries an ABSOLUTE soft deadline taken in the parent.
    seen: list[float] = []
    ticks = iter([1000.0] + [1000.0] * 8)

    def submit(
        requests: tuple[_StrategyRaceRequest, ...],
        channels: dict[str, RaceChannels],
    ) -> tuple[dict[Future[_StrategyRaceOutcome], str], object]:
        futures: dict[Future[_StrategyRaceOutcome], str] = {}
        for request in requests:
            seen.append(request.soft_deadline)
            future: Future[_StrategyRaceOutcome] = Future()
            future.set_result(
                _StrategyRaceOutcome(request.strategy, "refused", refusal_reason="x")
            )
            futures[future] = request.strategy
        return futures, _NoopExecutor()

    run_strategy_race(
        two_stage_spec(),
        time_budget_s=10.0,
        band_policy=BandPolicy("portable"),
        belt_vertical_construction=True,
        share=False,
        submit=submit,
        monotonic=lambda: next(ticks),
    )

    assert seen == [1010.0, 1010.0]


def test_share_false_creates_no_channels() -> None:
    seen: list[int] = []

    def submit(
        requests: tuple[_StrategyRaceRequest, ...],
        channels: dict[str, RaceChannels],
    ) -> tuple[dict[Future[_StrategyRaceOutcome], str], object]:
        seen.append(len(channels))
        futures: dict[Future[_StrategyRaceOutcome], str] = {}
        for request in requests:
            future: Future[_StrategyRaceOutcome] = Future()
            future.set_result(
                _StrategyRaceOutcome(request.strategy, "refused", refusal_reason="x")
            )
            futures[future] = request.strategy
        return futures, _NoopExecutor()

    run_strategy_race(
        two_stage_spec(),
        time_budget_s=0.05,
        band_policy=BandPolicy("portable"),
        belt_vertical_construction=True,
        share=False,
        submit=submit,
    )

    assert seen == [0], "share=False must not build queues the pool cannot pickle"


def test_share_true_wires_the_two_queues_crosswise_and_closes_them() -> None:
    # One queue per direction is a complete graph only for two arms: what
    # freeform publishes into is what sequence-pair consumes from, and back.
    # The queues are real spawn-context ones, so the `finally` that closes them
    # is exercised on the object whose feeder thread can hold a process open.
    captured: dict[str, RaceChannels] = {}

    def submit(
        requests: tuple[_StrategyRaceRequest, ...],
        channels: dict[str, RaceChannels],
    ) -> tuple[dict[Future[_StrategyRaceOutcome], str], object]:
        captured.update(channels)
        return {}, _NoopExecutor()

    run_strategy_race(
        two_stage_spec(),
        time_budget_s=0.05,
        band_policy=BandPolicy("portable"),
        belt_vertical_construction=True,
        share=True,
        submit=submit,
    )

    assert set(captured) == set(RACE_STRATEGIES)
    assert captured["freeform"].publish is captured["sequence-pair"].consume
    assert captured["sequence-pair"].publish is captured["freeform"].consume
    assert all(vars(side.publish)["_joincancelled"] is True for side in captured.values())


def test_the_queues_are_closed_even_when_the_race_raises() -> None:
    # An unflushed queue holds its feeder thread and a held feeder thread holds
    # this process open, so the close cannot be on the happy path only.
    captured: dict[str, RaceChannels] = {}

    def submit(
        requests: tuple[_StrategyRaceRequest, ...],
        channels: dict[str, RaceChannels],
    ) -> tuple[dict[Future[_StrategyRaceOutcome], str], object]:
        captured.update(channels)
        raise RuntimeError("the pool refused to start")

    with pytest.raises(RuntimeError, match="the pool refused to start"):
        run_strategy_race(
            two_stage_spec(),
            time_budget_s=0.05,
            band_policy=BandPolicy("portable"),
            belt_vertical_construction=True,
            share=True,
            submit=submit,
        )

    assert set(captured) == set(RACE_STRATEGIES)
    assert all(vars(side.publish)["_joincancelled"] is True for side in captured.values())


def test_the_worker_split_reaches_the_requests() -> None:
    seen: dict[str, int] = {}

    def submit(
        requests: tuple[_StrategyRaceRequest, ...],
        channels: dict[str, RaceChannels],
    ) -> tuple[dict[Future[_StrategyRaceOutcome], str], object]:
        futures: dict[Future[_StrategyRaceOutcome], str] = {}
        for request in requests:
            seen[request.strategy] = request.workers
            future: Future[_StrategyRaceOutcome] = Future()
            future.set_result(
                _StrategyRaceOutcome(request.strategy, "refused", refusal_reason="x")
            )
            futures[future] = request.strategy
        return futures, _NoopExecutor()

    run_strategy_race(
        two_stage_spec(),
        time_budget_s=0.05,
        band_policy=BandPolicy("portable"),
        belt_vertical_construction=True,
        share=False,
        workers=8,
        submit=submit,
    )

    assert seen == {"freeform": 6, "sequence-pair": 2}


def test_a_race_without_a_budget_is_refused() -> None:
    with pytest.raises(ValueError, match="positive time budget"):
        run_strategy_race(
            two_stage_spec(),
            time_budget_s=0.0,
            band_policy=BandPolicy("portable"),
            belt_vertical_construction=True,
            submit=_stub_submit({}),
        )


def test_a_third_strategy_fails_loudly_rather_than_losing_every_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # One queue per direction is a complete graph only for TWO arms, and
    # `_install_race_channels` keys exactly two.  A third must fail at the guard
    # rather than silently receive nothing.
    monkeypatch.setattr(
        strategy_race_module,
        "RACE_STRATEGIES",
        ("freeform", "sequence-pair", "beam"),
    )

    with pytest.raises(ValueError, match="exactly two strategies"):
        run_strategy_race(
            two_stage_spec(),
            time_budget_s=1.0,
            band_policy=BandPolicy("portable"),
            belt_vertical_construction=True,
            submit=_stub_submit({}),
        )


class _RecordingExecutor:
    """A pool that records which stop it was asked for, and can refuse each."""

    def __init__(self, refuse: tuple[str, ...] = ()) -> None:
        self.calls: list[str] = []
        self._refuse = refuse

    def _step(self, name: str) -> None:
        self.calls.append(name)
        if name in self._refuse:
            raise RuntimeError(f"this pool has no {name}")

    def terminate_workers(self) -> None:
        self._step("terminate_workers")

    def kill_workers(self) -> None:
        self._step("kill_workers")

    def shutdown(self, wait: bool = True, cancel_futures: bool = False) -> None:
        self.calls.append(f"shutdown(wait={wait}, cancel_futures={cancel_futures})")


def test_terminate_cancels_every_future_and_then_stops_the_pool() -> None:
    executor = _RecordingExecutor()
    pending: tuple[Future[_StrategyRaceOutcome], ...] = (Future(), Future())

    _terminate_executor(executor, pending)

    assert all(future.cancelled() for future in pending)
    assert executor.calls == ["terminate_workers"]


def test_terminate_falls_back_to_kill_when_the_pool_cannot_terminate() -> None:
    executor = _RecordingExecutor(refuse=("terminate_workers",))

    _terminate_executor(executor, ())

    assert executor.calls == ["terminate_workers", "kill_workers"]


def test_terminate_falls_back_to_shutdown_when_neither_kill_works() -> None:
    # The last resort must not WAIT: a racer that ignored the wall is exactly
    # the one whose solve ceiling the parent must not sit through.
    executor = _RecordingExecutor(refuse=("terminate_workers", "kill_workers"))

    _terminate_executor(executor, ())

    assert executor.calls == [
        "terminate_workers",
        "kill_workers",
        "shutdown(wait=False, cancel_futures=True)",
    ]


class _RecordingQueue:
    """A queue that satisfies both module Protocols and counts the cancel."""

    def __init__(self) -> None:
        self.cancelled = 0
        self.items: list[object] = []

    def put_nowait(self, item: object, /) -> None:
        self.items.append(item)

    def get_nowait(self) -> object:
        raise queue.Empty

    def cancel_join_thread(self) -> None:
        self.cancelled += 1


def test_install_race_channels_keys_each_arm_to_its_own_inbox() -> None:
    # The initializer runs in the CHILD and hands it both ends; which end is
    # which is decided by the child's own strategy name.  Crossing these would
    # make each arm read its own messages and hear nothing from its rival.
    to_freeform: queue.Queue[object] = queue.Queue()
    to_sequence_pair: queue.Queue[object] = queue.Queue()
    _install_race_channels(to_freeform, to_sequence_pair)
    try:
        freeform = _channels_for("freeform")
        sequence = _channels_for("sequence-pair")

        assert freeform is not None
        assert sequence is not None
        assert freeform.consume is to_freeform
        assert freeform.publish is to_sequence_pair
        assert sequence.consume is to_sequence_pair
        assert sequence.publish is to_freeform

        incumbent = IncumbentMessage("freeform", (480, 62))
        freeform.publish_incumbent(incumbent)

        assert sequence.drain() == (incumbent,)
        assert freeform.drain() == ()
    finally:
        strategy_race_module._RACE_CHANNELS = None


def test_channels_are_none_in_a_process_the_initializer_never_ran_in() -> None:
    strategy_race_module._RACE_CHANNELS = None

    assert _channels_for("freeform") is None


@pytest.mark.parametrize("strategy", RACE_STRATEGIES)
def test_a_leg_runs_on_the_parents_wall_and_not_on_a_fresh_budget(
    strategy: RaceStrategyName,
) -> None:
    """The whole reason ``absolute_deadline`` exists, end to end in one process.

    The request carries a 30 s budget and a soft deadline that is already a
    second in the past.  A leg that computed ``now + time_budget_s`` would search
    for thirty more seconds; one that uses the parent's wall refuses at once.
    """
    request = replace(
        _request(strategy),
        time_budget_s=30.0,
        soft_deadline=time.monotonic() - 1.0,
        workers=1,
        share=False,
    )
    started = time.monotonic()

    outcome = _run_race_leg(request)

    assert outcome.strategy == strategy
    assert outcome.status == "refused"
    assert outcome.refusal_reason
    assert time.monotonic() - started < 10.0, (
        "the leg must use the parent's wall, not buy itself a fresh 30s budget"
    )


def test_a_leg_closes_its_channels_even_when_the_layout_refuses() -> None:
    # The close is in a `finally` because the refusal path is the common one:
    # a child that refused still holds whatever it published.
    to_freeform = _RecordingQueue()
    to_sequence_pair = _RecordingQueue()
    _install_race_channels(to_freeform, to_sequence_pair)
    try:
        outcome = _run_race_leg(
            replace(
                _request("freeform"),
                time_budget_s=30.0,
                soft_deadline=time.monotonic() - 1.0,
                workers=1,
                share=True,
            )
        )

        assert outcome.status == "refused"
        # freeform publishes into the sequence-pair inbox, and closes THAT end.
        assert to_sequence_pair.cancelled == 1
        assert to_freeform.cancelled == 0
    finally:
        strategy_race_module._RACE_CHANNELS = None


def test_a_leg_with_sharing_off_touches_no_channel() -> None:
    to_freeform = _RecordingQueue()
    to_sequence_pair = _RecordingQueue()
    _install_race_channels(to_freeform, to_sequence_pair)
    try:
        outcome = _run_race_leg(
            replace(
                _request("freeform"),
                time_budget_s=30.0,
                soft_deadline=time.monotonic() - 1.0,
                workers=1,
                share=False,
            )
        )

        assert outcome.status == "refused"
        assert to_sequence_pair.cancelled == 0
        assert to_freeform.cancelled == 0
    finally:
        strategy_race_module._RACE_CHANNELS = None
