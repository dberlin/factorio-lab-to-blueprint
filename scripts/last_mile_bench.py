"""Replay captured last-mile cluster searches outside a whole cell run.

    uv run python scripts/route_bench.py --capture universe-matrix \
        --policy output-products --stranded --budget 30 \
        --cases /tmp/cluster-cases.pkl
    uv run python scripts/last_mile_bench.py --cases /tmp/cluster-cases.pkl --check

WHY A REPLAY.  A cluster search only happens on a pack that stranded, which on
the cells that matter is one pack in five of a thirty-second run.  Capturing
the search's real environment and replaying it turns a thirty-second
nondeterministic experiment into a millisecond deterministic one, and
``--check`` proves a candidate changed the SPEED and not the ANSWER.
"""

from __future__ import annotations

import argparse
import hashlib
import pickle
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from flab2bp.layout import last_mile  # noqa: E402
from flab2bp.layout.freeform import _astar  # noqa: E402


def _environment(case: dict[str, Any], budget: dict[str, int]) -> last_mile.ClusterEnvironment:
    canvas = case["canvas"]
    grid = case["grid"]

    floor = case["budget_floor"]

    def search(index: int, constraints: frozenset[tuple[int, int, int]]) -> Any:
        starts, goals, routing_ports = case["ends"][index]
        # The live search ran with this net's own ports readable; without that
        # the replay refuses starts the capture admitted and the digest differs
        # for a reason that has nothing to do with the search.
        canvas.routing_ports = routing_ports
        # CAP EACH SEARCH THE WAY THE LIVE PASS DOES.  A capture that ended
        # `bound is BUDGET` because one search hit its private allowance would
        # otherwise replay with no per-search cap, take a different branch, and
        # report DIFFER for something that is not a regression.  Same private
        # dict, same write-back.
        allowance = min(
            last_mile.B_LOW_LEVEL_EXPANSIONS,
            max(0, budget["left"] - floor),
        )
        private = {"left": allowance}
        found = _astar(
            canvas,
            list(starts),
            set(goals),
            case["history"],
            case["pressure"],
            case["bounds"],
            private,
            None,
            {},
            grid,
            # THE SAME SIDE INPUTS THE LIVE SEARCH HAD.  An owned start is a
            # junction-guard cell `_astar` marks PASSABLE, and a rejected-commit
            # cell is one it marks impassable; replaying with neither found a
            # legal but eight-cell-longer route for one `universe-matrix`
            # cluster and reported DIFFER for a difference the router never
            # made.  `released_starts` stays empty because the live cluster
            # search does not pass one either.
            case["owned_starts"][index],
            (),
            case["rejected"][index] | constraints,
            case["blocking_owners"],
        )
        budget["left"] -= allowance - private["left"]
        return found

    return last_mile.ClusterEnvironment(
        search=search,
        offers=lambda _index: ({}, {}, {}),
        budget_left=lambda: budget["left"],
        # REPLAY THE CAPTURED BOUNDS, not an unbounded run.  A case that ended
        # BOUNDED because the shared floor was reached would otherwise replay
        # under an infinite budget, reach PROVED, and report DIFFER for a
        # reason that is not a regression.
        budget_floor=floor,
        expired=lambda: False,
    )


def digest(results: list[last_mile.ClusterResult]) -> str:
    hasher = hashlib.sha256()
    for result in results:
        hasher.update(result.outcome.value.encode())
        for index in sorted(result.paths):
            hasher.update(repr((index, result.paths[index])).encode())
    return hasher.hexdigest()[:16]


def _replayable(case: dict[str, Any]) -> bool:
    """Whether the captured run's bound can be reproduced without a clock."""
    return case["result"].bound is not last_mile.ClusterBound.WALL


def bench(path: Path, rounds: int, check: bool) -> int:
    cases: list[dict[str, Any]] = pickle.loads(path.read_bytes())
    if not cases:
        print("no cluster cases in this capture")
        return 1
    replayable = [case for case in cases if _replayable(case)]
    skipped = len(cases) - len(replayable)
    if not replayable:
        print(f"every one of {len(cases)} captured searches was wall-bounded")
        return 1
    best: tuple[float, list[last_mile.ClusterResult]] | None = None
    for r in range(rounds):
        got: list[last_mile.ClusterResult] = []
        t0 = time.perf_counter()
        for case in replayable:
            budget = {"left": case["budget_left"]}
            got.append(last_mile.solve_cluster(case["problem"], _environment(case, budget)))
        dt = time.perf_counter() - t0
        if best is None or dt < best[0]:
            best = (dt, got)
        nodes = sum(result.nodes for result in got)
        print(f"  round {r + 1}: {dt:.3f}s  {nodes} nodes")
    assert best is not None
    dt, got = best
    counts = {outcome.value: 0 for outcome in last_mile.ClusterOutcome}
    for result in got:
        counts[result.outcome.value] += 1
    sizes = [len(case["problem"].nets) for case in replayable]
    truncated = sum(1 for case in replayable if case["problem"].truncated)
    runs = {run: sum(1 for case in replayable if case["run"] == run) for run in (1, 2)}
    print(
        f"BEST {dt:.3f}s  {len(replayable)} clusters  "
        f"(run1={runs[1]} run2={runs[2]}, skipped {skipped} wall-bounded)  "
        f"sizes {min(sizes)}-{max(sizes)}  truncated {truncated}  "
        + "  ".join(f"{key}={value}" for key, value in sorted(counts.items()))
        + f"  digest {digest(got)}"
    )
    if check:
        want = digest([case["result"] for case in replayable])
        same = digest(got)
        print(f"captured digest {want}   replay digest {same}   "
              f"{'MATCH' if want == same else 'DIFFER'}")
        return 0 if want == same else 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cases", type=Path, required=True)
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    return bench(args.cases, args.rounds, args.check)


if __name__ == "__main__":
    raise SystemExit(main())
