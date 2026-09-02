from __future__ import annotations

from flab2bp.layout import last_mile
from scripts import last_mile_bench


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
