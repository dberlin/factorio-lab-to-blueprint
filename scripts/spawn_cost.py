"""Spawn-to-first-instruction cost, which comes out of a racer's wall budget.

    uv run python scripts/spawn_cost.py

A racing child starts the budget its PARENT started, so whatever it spends
starting is search it does not get.  ``RACE_COMPLETION_GRACE_S`` is sized from
the worst case here plus ``ATOMIC_COMPLETION_GRACE_S``.

The measurement cannot run from a heredoc: under the ``spawn`` start method the
child re-imports ``__main__`` by path, and a script fed on stdin has
``__file__ == "<stdin>"``, so the pool fails before it measures anything.
"""

from __future__ import annotations

import math
import multiprocessing
import time
from concurrent.futures import ProcessPoolExecutor

#: Copied, not imported: this script deliberately does not import ``flab2bp``,
#: so what it times is the interpreter start alone.  The ``BuildSpec`` unpickle
#: a real racer also pays is charged on top and is covered by the ``ceil``.
ATOMIC_COMPLETION_GRACE_S = 5.0
SPAWNS = 10


def entered(submitted: float) -> float:
    """Runs in the child; the first thing it does is read the clock."""
    return time.monotonic() - submitted


def main() -> int:
    costs: list[float] = []
    for _ in range(SPAWNS):
        with ProcessPoolExecutor(
            max_workers=2,
            mp_context=multiprocessing.get_context("spawn"),
            max_tasks_per_child=1,
        ) as pool:
            submitted = time.monotonic()
            costs.append(pool.submit(entered, submitted).result())
    costs.sort()
    grace = math.ceil(costs[-1]) + ATOMIC_COMPLETION_GRACE_S
    print(
        f"spawns {len(costs)}  min {costs[0]:.3f}s  "
        f"median {costs[len(costs) // 2]:.3f}s  max {costs[-1]:.3f}s"
    )
    print("all: " + "  ".join(f"{cost:.3f}" for cost in costs))
    print(
        f"RACE_COMPLETION_GRACE_S = ceil(max) + ATOMIC_COMPLETION_GRACE_S = "
        f"{math.ceil(costs[-1])} + {ATOMIC_COMPLETION_GRACE_S} = {grace}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
