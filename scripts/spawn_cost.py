"""What racing costs at the two ends of a child's life, measured on this box.

    uv run python scripts/spawn_cost.py

Two different numbers, and only one of them sizes ``RACE_COMPLETION_GRACE_S``:

**Spawn-to-first-instruction is INSIDE the wall.** The parent starts the clock
and hands the child an absolute deadline, so whatever the child spends starting
is search it does not get. It is a cost of racing, and it is reported here as
context, but it is not what the parent has to wait out after the wall.

**The post-deadline TAIL is what the grace covers** (Ruling AL). At the soft
deadline a child is holding a finished ``Placement``; the parent cannot kill it
yet, because the answer still has to come back -- the child returns, the pool
pickles a real ``Placement`` through the result queue, the child exits (this
pool recycles every child), and the parent unpickles it and resolves the future.
That span is the first term:

    RACE_COMPLETION_GRACE_S = ceil(tail_max) + ATOMIC_COMPLETION_GRACE_S

The second term, ``base.ATOMIC_COMPLETION_GRACE_S``, is the in-process atomic
completion a serial arm already gets; the tail is the part racing adds.

The measurement cannot run from a heredoc: under the ``spawn`` start method the
child re-imports ``__main__`` by path, and a script fed on stdin has
``__file__ == "<stdin>"``, so the pool fails before it measures anything.
``flab2bp`` is imported inside the functions and never at module level, because
under ``spawn`` a module-level import is paid again by every child -- which
would land in the spawn measurement and make it something else.
"""

from __future__ import annotations

import math
import multiprocessing
import time
from concurrent.futures import ProcessPoolExecutor
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flab2bp.layout.base import Placement
    from flab2bp.spec import BuildSpec

#: Copied, not imported, so the spawn timing below is not charged an import of
#: ``flab2bp``: ``flab2bp.layout.base.ATOMIC_COMPLETION_GRACE_S``.
ATOMIC_COMPLETION_GRACE_S = 5.0
SPAWNS = 10
TAILS = 10
#: The corpus cell the Task 9 end-to-end proof also uses: a real production spec
#: whose freeform solve is a second or two and whose ``Placement`` is a real one.
CELL = "iron-ingot"


def entered(submitted: float) -> float:
    """Runs in the child; the first thing it does is read the clock."""
    return time.monotonic() - submitted


def crossed_holding_a_placement(spec: BuildSpec) -> tuple[float, Placement]:
    """Runs in the child: solve, then cross the wall holding the answer.

    The returned timestamp is the instant the soft deadline passes in the worst
    realistic case -- a child that finished exactly at the wall.  Everything the
    parent must still wait for after that instant is the tail.
    """
    from flab2bp.layout.band_policy import BandPolicy
    from flab2bp.layout.freeform import FreeformLayout

    placement = FreeformLayout(
        band_policy=BandPolicy("portable"),
        workers=1,
        arrangements=1,
    ).lay_out(spec, time_budget_s=30.0)
    return time.monotonic(), placement


def _spec() -> BuildSpec:
    from flab2bp.bench.corpus import URL_CORPUS
    from flab2bp.lab.data import load_vendored
    from flab2bp.lab.url import parse_url
    from flab2bp.rates import DEFAULT_CANDIDATE_POLICIES, build_candidates

    entry = next(item for item in URL_CORPUS if item.url_id == CELL)
    return build_candidates(
        load_vendored(),
        parse_url(entry.url),
        candidate_policies=DEFAULT_CANDIDATE_POLICIES,
    ).candidates[0]


def _pool() -> ProcessPoolExecutor:
    """Exactly the pool shape ``strategy_race._pool_submit`` builds."""
    return ProcessPoolExecutor(
        max_workers=2,
        mp_context=multiprocessing.get_context("spawn"),
        max_tasks_per_child=1,
    )


def _report(label: str, costs: list[float]) -> float:
    costs.sort()
    print(
        f"{label}: runs {len(costs)}  min {costs[0]:.3f}s  "
        f"median {costs[len(costs) // 2]:.3f}s  max {costs[-1]:.3f}s"
    )
    print("  all: " + "  ".join(f"{cost:.3f}" for cost in costs))
    return costs[-1]


def main() -> int:
    spawns: list[float] = []
    for _ in range(SPAWNS):
        with _pool() as pool:
            submitted = time.monotonic()
            spawns.append(pool.submit(entered, submitted).result())
    _report("spawn-to-first-instruction (INSIDE the wall, context only)", spawns)

    spec = _spec()
    tails: list[float] = []
    for _ in range(TAILS):
        with _pool() as pool:
            crossed, placement = pool.submit(crossed_holding_a_placement, spec).result()
            tails.append(time.monotonic() - crossed)
            assert placement.area > 0
    tail_max = _report("post-deadline tail (what the grace covers)", tails)

    grace = math.ceil(tail_max) + ATOMIC_COMPLETION_GRACE_S
    print(
        f"RACE_COMPLETION_GRACE_S = ceil(tail_max) + ATOMIC_COMPLETION_GRACE_S = "
        f"{math.ceil(tail_max)} + {ATOMIC_COMPLETION_GRACE_S} = {grace}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
