"""The maintained count must survive a REWRITE, not only an append.

`sequence_solver.py:2106-2107` does
`self._stage_stats[-1] = replace(observation, global_skip_reason="projection-feedback")`
AFTER the stage was appended, and `_counts_as_scheduled_stage`
(sequence_solver.py:865-871) is False for that reason. So a counter incremented
only at the append site over-counts, and `stage_limit` at :1280 and :2036 then
stops the search early. That is the staleness test this file exists for.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, replace

from flab2bp.indexed import Stages


@dataclass(frozen=True, slots=True)
class _FakeStage:
    stage_index: int
    global_skip_reason: str | None = None


_UNSCHEDULED = ("shared-pack", "topology-beam", "projection-feedback")


def _counts(stage: _FakeStage) -> bool:
    return stage.global_skip_reason not in _UNSCHEDULED


def test_scheduled_count_equals_the_brute_force_sum_after_every_append() -> None:
    rng = random.Random(31)
    ledger: Stages[_FakeStage] = Stages(_counts)
    seen: list[_FakeStage] = []
    for i in range(500):
        stage = _FakeStage(i, rng.choice([None, None, None, *_UNSCHEDULED]))
        ledger.append(stage)
        seen.append(stage)
        assert ledger.scheduled_count() == sum(_counts(s) for s in seen), i


def test_replace_last_updates_the_count_when_the_predicate_flips_off() -> None:
    ledger: Stages[_FakeStage] = Stages(_counts)
    ledger.append(_FakeStage(0))
    assert ledger.scheduled_count() == 1
    ledger.replace_last(replace(ledger.last(), global_skip_reason="projection-feedback"))
    assert ledger.scheduled_count() == 0


def test_replace_last_updates_the_count_when_the_predicate_flips_on() -> None:
    ledger: Stages[_FakeStage] = Stages(_counts)
    ledger.append(_FakeStage(0, "shared-pack"))
    assert ledger.scheduled_count() == 0
    ledger.replace_last(replace(ledger.last(), global_skip_reason=None))
    assert ledger.scheduled_count() == 1


def test_replace_last_leaves_the_count_alone_when_the_predicate_does_not_move() -> None:
    ledger: Stages[_FakeStage] = Stages(_counts)
    ledger.append(_FakeStage(0))
    ledger.append(_FakeStage(1))
    ledger.replace_last(_FakeStage(99))
    assert ledger.scheduled_count() == 2
    assert ledger.last().stage_index == 99


def test_the_count_matches_a_brute_force_sum_under_interleaved_appends_and_rewrites() -> None:
    rng = random.Random(32)
    ledger: Stages[_FakeStage] = Stages(_counts)
    seen: list[_FakeStage] = []
    for i in range(1000):
        if seen and rng.random() < 0.3:
            stage = _FakeStage(i, rng.choice([None, *_UNSCHEDULED]))
            ledger.replace_last(stage)
            seen[-1] = stage
        else:
            stage = _FakeStage(i, rng.choice([None, None, *_UNSCHEDULED]))
            ledger.append(stage)
            seen.append(stage)
        assert ledger.scheduled_count() == sum(_counts(s) for s in seen), i


def test_iteration_reverse_iteration_and_indexing_match_the_list_it_replaces() -> None:
    ledger: Stages[_FakeStage] = Stages(_counts)
    made = [_FakeStage(i) for i in range(10)]
    for stage in made:
        ledger.append(stage)
    assert list(ledger) == made
    assert list(reversed(ledger)) == list(reversed(made))
    assert ledger[-1] is made[-1]
    assert ledger.as_tuple() == tuple(made)
    assert len(ledger) == 10


def test_replace_last_on_an_empty_ledger_raises_rather_than_corrupting_the_count() -> None:
    ledger: Stages[_FakeStage] = Stages(_counts)
    try:
        ledger.replace_last(_FakeStage(0))
    except IndexError:
        return
    raise AssertionError("replace_last on an empty ledger must raise IndexError")
