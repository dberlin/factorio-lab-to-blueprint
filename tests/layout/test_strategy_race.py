from __future__ import annotations

import pickle
import queue
from dataclasses import fields
from fractions import Fraction
from typing import get_type_hints

import pytest

from flab2bp.dsp import catalog, provenance, registry
from flab2bp.layout.band_policy import BandPolicy
from flab2bp.layout.compact_seed import CompactSeedConfig
from flab2bp.layout.sequence_solver import SequenceSolverConfig
from flab2bp.layout.strategy_race import (
    RACE_DRAIN_MAX_MESSAGES,
    RACE_FREEFORM_WORKER_SHARE,
    RACE_MIN_WORKERS,
    RACE_QUEUE_MAXSIZE,
    RACE_STRATEGIES,
    IncumbentMessage,
    NoGoodMessage,
    RaceChannels,
    RaceStrategyName,
    _ordered,
    _StrategyRaceOutcome,
    _StrategyRaceRequest,
    race_worker_split,
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
