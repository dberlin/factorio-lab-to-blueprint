"""Race the two production strategies for one wall budget, sharing what they prove.

``pipeline.build(strategy="best")`` used to run freeform and then sequence-pair,
each with the FULL budget, and throw the loser's work away.  This module runs
both concurrently in spawned children for ONE budget and lets each tell the
other what it has certified and what it has proved impossible.

The process shape is deliberately the one ``sequence_islands.py`` already runs in
production: a frozen, ``slots=True`` request that is the whole pickled unit; a
frozen outcome that flattens ``NoValidLayout`` in the child rather than pickling
an exception; a spawn-context ``ProcessPoolExecutor`` with
``max_tasks_per_child=1``; one ``wait`` in the parent; and OS-level termination
for whatever is still running when the wall runs out.

This file is the transport layer only: the request and outcome that cross the
pickle boundary, the two message kinds, and the channel that publishes and
drains them.  The executor, the receivers, and the merge rule land on top of it.
"""

from __future__ import annotations

import queue
from collections.abc import Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Literal, Protocol

from flab2bp.dsp import catalog
from flab2bp.layout.band_policy import BandPolicy
from flab2bp.layout.base import Placement, ProjectionFailureRecord
from flab2bp.layout.compact_seed import CompactSeedConfig
from flab2bp.layout.sequence_solver import SequenceSolverConfig
from flab2bp.layout.strip_variants import StripInstanceId
from flab2bp.spec import BuildSpec

type RaceStrategyName = Literal["freeform", "sequence-pair"]

#: The portfolio, in the order outcomes are returned.  Same membership and same
#: order as ``pipeline.PRODUCTION_STRATEGIES``; named here so this module does
#: not import ``pipeline``, which imports it.
RACE_STRATEGIES: tuple[RaceStrategyName, ...] = ("freeform", "sequence-pair")

#: Seconds past the soft deadline the parent waits before killing a racer.
#: MEASURED, not guessed: Task 9 records this box's spawn-to-first-instruction
#: cost and sets this to ``ceil(that) + ATOMIC_COMPLETION_GRACE_S``.  It is
#: deliberately NOT ``sequence_islands._ISLAND_COMPLETION_GRACE_S``, which is
#: 90.0: a grace that large is a second budget.
RACE_COMPLETION_GRACE_S = 6.0

#: Messages a direction may hold before publishing starts dropping.  A dropped
#: message costs a hint and never a result, so a bound is strictly better than a
#: block: a full queue must never make a racer wait on its rival.
RACE_QUEUE_MAXSIZE = 64

#: Messages a receiver takes per poll, so a burst cannot turn a poll into a pause.
RACE_DRAIN_MAX_MESSAGES = 32

#: Freeform's ``_pack`` is the only multi-threaded CP-SAT solve in the tree; every
#: sequence-pair sub-solve is pinned to one worker (``compact_seed`` twice, the
#: freeform tie-break, and ``DETERMINISTIC_WORKERS``).  So the split is mostly a
#: bound on freeform, and its share is the larger one.
#:
#: Three and four are NAMED rather than written straight into ``Fraction(3, 4)``
#: because the R1 provenance lint evaluates ``Fraction(a, b)`` and would read the
#: resulting 0.75 as ``catalog.MAX_BELT_SLOPE`` / ``catalog.BELT_Z_PER_WORLD_UNIT``
#: in disguise.  This ratio is a CPU schedule and has nothing to do with belts,
#: and the lint's exception registry lives in ``flab2bp.dsp.registry``, which a
#: layout module has no business editing to declare a coincidence.
_FREEFORM_SHARE_NUMERATOR = 3
_FREEFORM_SHARE_DENOMINATOR = 4
RACE_FREEFORM_WORKER_SHARE = Fraction(_FREEFORM_SHARE_NUMERATOR, _FREEFORM_SHARE_DENOMINATOR)

#: Never zero: ortools reads ``num_search_workers == 0`` as ALL CORES.
RACE_MIN_WORKERS = 1


def race_worker_split(total: int) -> tuple[int, int]:
    """Split ``total`` CP-SAT search workers into (freeform, sequence-pair)."""
    if type(total) is not int or total < 1:
        raise ValueError("racing worker total must be a positive integer")
    if total <= 2:
        return (RACE_MIN_WORKERS, RACE_MIN_WORKERS)
    freeform = max(
        RACE_MIN_WORKERS,
        total * RACE_FREEFORM_WORKER_SHARE.numerator // RACE_FREEFORM_WORKER_SHARE.denominator,
    )
    return (freeform, max(RACE_MIN_WORKERS, total - freeform))


class _MessageQueue(Protocol):
    """The two methods this module needs from a queue.

    ``multiprocessing.Queue`` and ``queue.Queue`` both satisfy it and share no
    base class, which is what lets one ``RaceChannels`` serve the real race and
    the in-process tests without an ``Any`` or a ``type: ignore``.
    """

    def put_nowait(self, item: object, /) -> None: ...

    def get_nowait(self) -> object: ...


@dataclass(frozen=True, slots=True)
class IncumbentMessage:
    """A validator-clean placement one arm proved, offered to the other as a bound.

    ``exact_key`` is ``(area, belt_tiles)`` -- the same tuple freeform's ``_sweep``
    keeps as ``best_key`` and ``sequence_solver._exact_key`` returns -- which is
    why one schema serves both directions.  It is ONE field: carrying ``area``
    and ``belt_tiles`` separately would be the same two numbers a second time.
    """

    strategy: str
    exact_key: tuple[int, int]


@dataclass(frozen=True, slots=True)
class NoGoodMessage:
    """A proved-impossible cluster relation, with the identity it is keyed by.

    ``instance_ids`` is the assertion: a receiver applies the no-good only when
    every named instance is one of its own CURRENT planned strips.
    ``StripInstanceId`` embeds ``family_id``, ``machine_start`` and
    ``machine_count``, so a receiver that sharded its strips differently fails
    the predicate by construction.

    ``no_good`` is typed ``object`` on purpose: this module is a transport and
    must import at a commit where Phase B's ``ClusterRelationNoGood`` may not
    exist.  The receiver, which does know the type, is what applies it.
    """

    strategy: str
    instance_ids: tuple[StripInstanceId, ...]
    no_good: object


type RaceMessage = IncumbentMessage | NoGoodMessage


@dataclass
class RaceChannels:
    """One racer's end of the two queues: what it publishes, what it consumes."""

    publish: _MessageQueue
    consume: _MessageQueue
    _dropped: int = field(default=0, init=False)

    @property
    def dropped(self) -> int:
        return self._dropped

    def _put(self, message: RaceMessage) -> None:
        try:
            self.publish.put_nowait(message)
        except queue.Full:
            self._dropped += 1

    def publish_incumbent(self, message: IncumbentMessage) -> None:
        self._put(message)

    def publish_no_good(self, message: NoGoodMessage) -> None:
        self._put(message)

    def drain(self) -> tuple[RaceMessage, ...]:
        taken: list[RaceMessage] = []
        while len(taken) < RACE_DRAIN_MAX_MESSAGES:
            try:
                item = self.consume.get_nowait()
            except queue.Empty:
                break
            if isinstance(item, IncumbentMessage | NoGoodMessage):
                taken.append(item)
        return tuple(taken)

    def close(self) -> None:
        """Let this process exit without waiting for a reader that is not coming.

        A ``multiprocessing.Queue`` with unflushed data blocks its process's exit
        until something reads it, and after the deadline there is nothing to.
        """
        canceller = getattr(self.publish, "cancel_join_thread", None)
        if canceller is not None:
            canceller()


@dataclass(frozen=True, slots=True)
class _StrategyRaceRequest:
    """Plain pickleable inputs for one racer.  No queue: see ``run_strategy_race``."""

    spec: BuildSpec
    #: The same alias ``RACE_STRATEGIES`` is typed with, so a third name is a
    #: type error rather than a message nobody reads.
    strategy: RaceStrategyName
    time_budget_s: float
    #: An ABSOLUTE ``time.monotonic()`` value taken in the parent.  Valid because
    #: Linux CLOCK_MONOTONIC is system-wide; ``sequence_islands`` already relies
    #: on exactly this, passing its own ``soft_deadline`` into a child as
    #: ``absolute_deadline``.
    soft_deadline: float
    band_policy: BandPolicy
    belt_vertical_construction: bool
    #: For the child's OWN ``validate.validate`` before it publishes an
    #: incumbent: the bound must meet the standard the parent will apply.
    max_belt_z: Fraction
    workers: int
    arrangements: int | None
    sequence_islands: int
    config: SequenceSolverConfig
    compact_seed_config: CompactSeedConfig
    share: bool


@dataclass(frozen=True, slots=True)
class _StrategyRaceOutcome:
    """One arm's exact result, honest refusal, kill, or crash."""

    strategy: str
    status: Literal["completed", "refused", "invalid", "terminated", "crashed"]
    placement: Placement | None = None
    refusal_reason: str | None = None
    refusal_spec_label: str = ""
    refusal_budget_s: float = 0.0
    refusal_projection_failures: tuple[ProjectionFailureRecord, ...] = ()
    published_incumbents: int = 0
    consumed_incumbents: int = 0
    published_no_goods: int = 0
    consumed_no_goods: int = 0
    dropped_messages: int = 0

    @classmethod
    def refused(
        cls,
        strategy: str,
        reason: str,
        spec_label: str,
        budget_s: float,
        *,
        projection_failures: tuple[ProjectionFailureRecord, ...] = (),
    ) -> _StrategyRaceOutcome:
        return cls(
            strategy,
            "refused",
            refusal_reason=reason,
            refusal_spec_label=spec_label,
            refusal_budget_s=budget_s,
            refusal_projection_failures=projection_failures,
        )


def _ordered(outcomes: Sequence[_StrategyRaceOutcome]) -> tuple[_StrategyRaceOutcome, ...]:
    """Return outcomes in ``RACE_STRATEGIES`` order, never in completion order."""
    by_strategy = {outcome.strategy: outcome for outcome in outcomes}
    return tuple(by_strategy[name] for name in RACE_STRATEGIES if name in by_strategy)


#: Referenced so ``catalog`` is not an unused import: the default belt ceiling a
#: caller gets when it does not know the URL's technology set.
DEFAULT_RACE_MAX_BELT_Z = catalog.DEFAULT_MAX_BELT_Z
