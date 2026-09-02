from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any, cast

import pytest

from flab2bp.layout import last_mile
from scripts import last_mile_bench


def _replay_case(*, deadline_remaining: float | None) -> dict[str, Any]:
    """The minimum a captured shot needs for `_environment` to rebuild it."""
    return {
        "canvas": SimpleNamespace(routing_ports=frozenset()),
        "grid": object(),
        "history": {},
        "pressure": 0.0,
        "bounds": (0, 0, 1, 1),
        "ends": {0: ([], set(), frozenset())},
        "budget_floor": 0,
        "budget_left": 10,
        "deadline_remaining": deadline_remaining,
        "owned_starts": {0: frozenset()},
        "rejected": {0: frozenset()},
        "blocking_owners": {},
    }


def test_the_digest_separates_outcomes_and_paths() -> None:
    solved = last_mile.ClusterResult(
        last_mile.ClusterOutcome.SOLVED, {0: ((0, 0, 0),)}, 1, 1, 0.0
    )
    other = last_mile.ClusterResult(
        last_mile.ClusterOutcome.SOLVED, {0: ((1, 0, 0),)}, 1, 1, 0.0
    )
    proved = last_mile.ClusterResult(last_mile.ClusterOutcome.PROVED, {}, 1, 1, 0.0)

    assert last_mile_bench.digest([solved]) != last_mile_bench.digest([other])
    assert last_mile_bench.digest([solved]) != last_mile_bench.digest([proved])
    assert last_mile_bench.digest([proved]) == last_mile_bench.digest([proved])


def test_a_wall_bounded_case_is_not_replayable() -> None:
    """A clock cannot be replayed, so those cases are skipped, not diffed."""
    wall = {
        "result": last_mile.ClusterResult(
            last_mile.ClusterOutcome.BOUNDED,
            {},
            1,
            1,
            0.0,
            bound=last_mile.ClusterBound.WALL,
        )
    }
    nodes = {
        "result": last_mile.ClusterResult(
            last_mile.ClusterOutcome.BOUNDED,
            {},
            1,
            1,
            0.0,
            bound=last_mile.ClusterBound.NODES,
        )
    }

    assert last_mile_bench._replayable(wall) is False
    assert last_mile_bench._replayable(nodes) is True


def test_the_replay_re_anchors_the_captured_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A low-level deadline cut is not `ClusterBound.WALL`, so it must replay.

    `_replayable` only skips CBS-level wall bounds.  A search that ended early
    because `_astar`'s own deadline passed carries no such bound, so replaying
    with `deadline=None` would take a different branch and report DIFFER for
    something the live search never did.
    """
    seen: list[float | None] = []

    def spying_astar(*args: object) -> object:
        seen.append(cast("float | None", args[7]))
        return None

    monkeypatch.setattr(last_mile_bench, "_astar", spying_astar)
    case = _replay_case(deadline_remaining=2.5)
    before = time.monotonic()
    last_mile_bench._environment(case, {"left": 10}).search(0, frozenset())
    after = time.monotonic()

    assert seen and seen[0] is not None
    assert before + 2.5 <= seen[0] <= after + 2.5


def test_a_capture_without_a_deadline_replays_without_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[float | None] = []

    def spying_astar(*args: object) -> object:
        seen.append(cast("float | None", args[7]))
        return None

    monkeypatch.setattr(last_mile_bench, "_astar", spying_astar)
    case = _replay_case(deadline_remaining=None)
    last_mile_bench._environment(case, {"left": 10}).search(0, frozenset())

    assert seen == [None]
