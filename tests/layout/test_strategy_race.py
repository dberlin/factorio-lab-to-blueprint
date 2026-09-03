from __future__ import annotations

import inspect
import pickle
import queue
from dataclasses import fields
from fractions import Fraction

import pytest

from flab2bp.dsp import catalog, provenance
from flab2bp.layout import strategy_race
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


def test_the_freeform_share_is_three_quarters_however_it_is_spelled() -> None:
    # The constant is assembled from named parts rather than written as
    # `Fraction(3, 4)`; this is what stops that spelling from drifting.
    assert Fraction(3, 4) == RACE_FREEFORM_WORKER_SHARE


def test_the_module_smuggles_no_game_constant_past_the_provenance_lint() -> None:
    # `Fraction(3, 4)` evaluates to 0.75, which the R1 lint owns as
    # catalog.MAX_BELT_SLOPE / catalog.BELT_Z_PER_WORLD_UNIT.  The worker share
    # is a CPU schedule and shares nothing with a belt, and the lint's exception
    # registry lives in flab2bp.dsp.registry -- a file a layout module has no
    # business editing.  So the module is written to have no needle at all, and
    # this pins it here rather than only in tests/rules/test_rule_registry.py,
    # where the failure arrives with no idea whose it is.
    source = inspect.getsource(strategy_race)

    assert provenance.scan_source("flab2bp.layout.strategy_race", source) == ()
