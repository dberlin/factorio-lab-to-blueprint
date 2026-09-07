"""An append-and-rewrite ledger that keeps its own predicate count.

`SequenceSolver` sums `_counts_as_scheduled_stage` over `self._stage_stats` on
EVERY iteration of its top-level `while True:` driver (sequence_solver.py:1280)
and again inside `_run_pending_projection_feedback` (:2030), which that same
loop reaches from three sites. The list grows one entry per stage, so the sum is
O(S) per iteration and O(S^2) over a solve.

The list is also REWRITTEN in place: sequence_solver.py:2106-2107 replaces
`[-1]` with a copy whose `global_skip_reason` is "projection-feedback", and the
predicate is False for that reason. That is why this type owns BOTH mutations
and re-evaluates the predicate on each; a counter bumped only on append reports
a number the scan never would.

Backend: a plain list plus an int. The only repeated query is a count under one
predicate, on the hottest write path in the solver -- Ruling 2's plain-index
clause, and a littletable insert per stage would move cost onto that write for a
question one integer answers.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator


class Stages[T]:
    """Ordered stage observations with a maintained "counts as scheduled" total."""

    __slots__ = ("_counts", "_scheduled", "_stages")

    def __init__(self, counts: Callable[[T], bool]) -> None:
        self._counts = counts
        self._stages: list[T] = []
        self._scheduled = 0

    def append(self, stage: T) -> None:
        """Record one observation."""
        self._stages.append(stage)
        if self._counts(stage):
            self._scheduled += 1

    def replace_last(self, stage: T) -> None:
        """Rewrite the most recent observation, re-deciding whether it counts."""
        if not self._stages:
            raise IndexError("replace_last on an empty stage ledger")
        if self._counts(self._stages[-1]):
            self._scheduled -= 1
        self._stages[-1] = stage
        if self._counts(stage):
            self._scheduled += 1

    def last(self) -> T:
        """The most recent observation."""
        return self._stages[-1]

    def scheduled_count(self) -> int:
        """How many observations consume a scheduled search stage."""
        return self._scheduled

    def as_tuple(self) -> tuple[T, ...]:
        """Every observation, in order, as an immutable snapshot."""
        return tuple(self._stages)

    def __len__(self) -> int:
        return len(self._stages)

    def __iter__(self) -> Iterator[T]:
        return iter(self._stages)

    def __reversed__(self) -> Iterator[T]:
        return reversed(self._stages)

    def __getitem__(self, index: int) -> T:
        return self._stages[index]
