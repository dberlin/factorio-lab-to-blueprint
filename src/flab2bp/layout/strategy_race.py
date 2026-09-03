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

This file carries the transport -- the request and outcome that cross the pickle
boundary, the two message kinds, and the channel that publishes and drains them
-- and the race itself: the child-side leg, the pool, and the parent's one
``wait``.  The receivers that consume a hint, and the merge rule that turns two
outcomes into one placement, land on top of it.
"""

from __future__ import annotations

import multiprocessing
import os
import queue
import time
from collections.abc import Callable, Sequence
from concurrent.futures import Future, ProcessPoolExecutor, wait
from dataclasses import dataclass, field
from fractions import Fraction
from typing import TYPE_CHECKING, Literal, Protocol, cast, runtime_checkable

if TYPE_CHECKING:
    from flab2bp.layout.freeform import FreeformLayout
    from flab2bp.layout.sequence_solver import SequencePairLayout

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
#:
#: MEASURED, not guessed, and measured on the right span.  What the grace has to
#: cover is the post-deadline TAIL: at the wall a child is holding a finished
#: ``Placement``, and the parent cannot kill it until that answer has come back
#: -- the child returns, the pool pickles a real ``Placement`` through the result
#: queue, and the parent unpickles it and resolves the future.  Spawn cost is
#: NOT part of this: the child is handed the parent's absolute deadline, so
#: starting up is search it loses, inside the wall rather than after it.
#:
#: ``scripts/spawn_cost.py`` timed that tail over ten runs of the same pool shape
#: this module builds -- worst case 0.001 s -- so this is
#: ``ceil(0.001) + ATOMIC_COMPLETION_GRACE_S = 1 + 5.0``, the second term being
#: the in-process atomic completion a serial arm already gets.  The numbers, the
#: box load and the spawn figure kept as context are in
#: ``docs/superpowers/evidence/2026-09-02-phase-d-portfolio/race-grace.md``.
#:
#: It is deliberately NOT ``sequence_islands._ISLAND_COMPLETION_GRACE_S``, which
#: is 90.0: a grace that large is a second budget.
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
#: This is 0.75, which is also ``catalog.MAX_BELT_SLOPE`` and
#: ``catalog.BELT_Z_PER_WORLD_UNIT``, so the R1 provenance lint sees it -- as it
#: should: ``Fraction(3, 4)`` is exactly the spelling
#: ``test_the_lint_would_catch_a_fraction_spelling_of_one`` exists to catch.  It
#: is a declared coincidence, written down as a ``LintException`` in
#: ``flab2bp.dsp.registry`` beside ``freeform._PACK_SHARE``, not hidden from the
#: lint by spelling the number some other way.
RACE_FREEFORM_WORKER_SHARE = Fraction(3, 4)

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


@runtime_checkable
class _JoinCancellable(Protocol):
    """A queue whose feeder thread can be told not to hold the process open.

    ``multiprocessing.Queue`` has this method and ``queue.Queue`` does not, so
    ``RaceChannels.close`` asks the type rather than the object: an
    ``isinstance`` against this Protocol is Any-free, whereas a ``getattr``
    lookup would type as ``Any``.  (A runtime-checkable Protocol still only
    checks that the attribute exists, so this buys the type, not a stronger
    runtime guarantee.)
    """

    def cancel_join_thread(self) -> None: ...


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
        """Take at most ``RACE_DRAIN_MAX_MESSAGES`` items off the consume queue.

        The bound is on the GETS, not on what survives the type check: the cost
        of a poll is the dequeue, so bounding only the accepted items would let a
        queue holding anything else be drained end to end in one call -- the very
        pause the constant exists to prevent.
        """
        taken: list[RaceMessage] = []
        for _ in range(RACE_DRAIN_MAX_MESSAGES):
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
        if isinstance(self.publish, _JoinCancellable):
            self.publish.cancel_join_thread()


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
        published_incumbents: int = 0,
        consumed_incumbents: int = 0,
    ) -> _StrategyRaceOutcome:
        return cls(
            strategy,
            "refused",
            refusal_reason=reason,
            refusal_spec_label=spec_label,
            refusal_budget_s=budget_s,
            refusal_projection_failures=projection_failures,
            published_incumbents=published_incumbents,
            consumed_incumbents=consumed_incumbents,
        )


def _ordered(outcomes: Sequence[_StrategyRaceOutcome]) -> tuple[_StrategyRaceOutcome, ...]:
    """Return outcomes in ``RACE_STRATEGIES`` order, never in completion order."""
    by_strategy = {outcome.strategy: outcome for outcome in outcomes}
    return tuple(by_strategy[name] for name in RACE_STRATEGIES if name in by_strategy)


#: Referenced so ``catalog`` is not an unused import: the default belt ceiling a
#: caller gets when it does not know the URL's technology set.
DEFAULT_RACE_MAX_BELT_Z = catalog.DEFAULT_MAX_BELT_Z


#: Set by the pool initializer in each child; ``None`` in the parent and when
#: sharing is off.  A module global rather than a request field because a
#: ``multiprocessing.Queue`` cannot be pickled as a TASK argument -- it reaches a
#: child only through ``Process(args=...)``, which is what ``initargs`` becomes.
_RACE_CHANNELS: dict[str, RaceChannels] | None = None


def _install_race_channels(to_freeform: object, to_sequence_pair: object) -> None:
    """Pool initializer: give this child both ends, keyed by who reads which.

    The parameters are ``object`` because the executor hands ``initargs`` through
    untyped; the cast is where the queue type is asserted, once, rather than at
    every use.
    """
    global _RACE_CHANNELS
    freeform_in = cast(_MessageQueue, to_freeform)
    sequence_in = cast(_MessageQueue, to_sequence_pair)
    _RACE_CHANNELS = {
        "freeform": RaceChannels(publish=sequence_in, consume=freeform_in),
        "sequence-pair": RaceChannels(publish=freeform_in, consume=sequence_in),
    }


def _channels_for(strategy: str) -> RaceChannels | None:
    return None if _RACE_CHANNELS is None else _RACE_CHANNELS.get(strategy)


def _build_layout(
    request: _StrategyRaceRequest,
    *,
    portfolio_incumbent: Callable[[], tuple[int, int] | None] | None = None,
    publish_incumbent: Callable[[Placement], None] | None = None,
) -> FreeformLayout | SequencePairLayout:
    """Reconstruct one strategy from the pickled request, in the child."""
    from flab2bp.layout.freeform import FreeformLayout
    from flab2bp.layout.sequence_solver import SequencePairLayout

    if request.strategy == "freeform":
        return FreeformLayout(
            band_policy=request.band_policy,
            workers=request.workers,
            arrangements=request.arrangements,
            belt_vertical_construction=request.belt_vertical_construction,
            portfolio_incumbent=portfolio_incumbent,
            publish_incumbent=publish_incumbent,
        )
    return SequencePairLayout(
        band_policy=request.band_policy,
        belt_vertical_construction=request.belt_vertical_construction,
        config=request.config,
        compact_seed_config=request.compact_seed_config,
        islands=request.sequence_islands,
        portfolio_incumbent=portfolio_incumbent,
        publish_incumbent=publish_incumbent,
    )


def _run_race_leg(request: _StrategyRaceRequest) -> _StrategyRaceOutcome:
    """Reconstruct and run one whole strategy inside a child.

    ``request.soft_deadline`` and not ``time_budget_s`` is what bounds the
    search: the parent started the clock, and spawn, interpreter start and
    unpickling the spec all happened after it did.
    """
    from flab2bp.layout import validate
    from flab2bp.layout.base import NoValidLayout

    channels = _channels_for(request.strategy) if request.share else None

    seen_keys: list[tuple[int, int]] = []
    published = 0
    consumed = 0

    def portfolio_incumbent() -> tuple[int, int] | None:
        nonlocal consumed
        if channels is None:
            return None
        for message in channels.drain():
            if isinstance(message, IncumbentMessage):
                consumed += 1
                seen_keys.append(message.exact_key)
        return min(seen_keys) if seen_keys else None

    def publish(placement: Placement) -> None:
        nonlocal published
        if channels is None:
            return
        # The PARENT's standard of proof, run in the child.  Freeform's in-sweep
        # report and sequence-pair's `validate.certify` are not it, and a bound
        # the parent will reject would prune the other arm on a promise nobody
        # keeps.  One extra validation per PUBLISHED incumbent, off the parent's
        # critical path.
        report = validate.validate(
            placement,
            request.spec,
            ids=validate.id_map(request.spec),
            expect_power=True,
            max_belt_z=request.max_belt_z,
            belt_vertical_construction=request.belt_vertical_construction,
        )
        if not report.ok:
            return
        belt_tiles = int(placement.stats.get("belt_tiles", 0))
        channels.publish_incumbent(
            IncumbentMessage(request.strategy, (placement.area, belt_tiles))
        )
        published += 1

    layout = _build_layout(
        request,
        portfolio_incumbent=portfolio_incumbent,
        publish_incumbent=publish,
    )
    try:
        placement = layout.lay_out(
            request.spec,
            time_budget_s=request.time_budget_s,
            absolute_deadline=request.soft_deadline,
        )
    except NoValidLayout as exc:
        return _StrategyRaceOutcome.refused(
            request.strategy,
            exc.reason,
            exc.spec_label,
            exc.budget_s,
            projection_failures=exc.projection_failures,
            published_incumbents=published,
            consumed_incumbents=consumed,
        )
    finally:
        # In a `finally` because refusing is the common path, and a child that
        # refused still holds whatever it published.
        if channels is not None:
            channels.close()
    return _StrategyRaceOutcome(
        request.strategy,
        "completed",
        placement=placement,
        published_incumbents=published,
        consumed_incumbents=consumed,
        dropped_messages=0 if channels is None else channels.dropped,
    )


#: What ``run_strategy_race`` needs from whatever starts the two legs: given the
#: requests and the channels, return the futures by strategy and the executor to
#: stop.  The seam exists so the parent's wall discipline can be tested without a
#: process pool.
type RaceSubmit = Callable[
    [tuple[_StrategyRaceRequest, ...], dict[str, RaceChannels]],
    tuple[dict[Future[_StrategyRaceOutcome], str], object],
]


def _available_cores() -> int:
    """Cores this process may actually use, Linux-first, with a fallback.

    ``sched_getaffinity`` is Linux-only, so it is probed rather than assumed --
    the same guard ``scripts/audit.py:_available_cores`` already uses.
    """
    affinity = getattr(os, "sched_getaffinity", None)
    if affinity is not None:
        return len(affinity(0)) or 4
    return os.cpu_count() or 4


def _terminate_executor(
    executor: object,
    futures: Sequence[Future[_StrategyRaceOutcome]],
) -> None:
    """Stop whatever is still running, without waiting for its solve ceiling.

    Copied from ``sequence_islands._terminate_executor`` rather than imported:
    the two callers have the same need today, and a change made for islands must
    not silently change what racing does to a live CP-SAT child.
    """
    for future in futures:
        _ = future.cancel()
    try:
        cast(ProcessPoolExecutor, executor).terminate_workers()
    except BaseException:
        try:
            cast(ProcessPoolExecutor, executor).kill_workers()
        except BaseException:
            cast(ProcessPoolExecutor, executor).shutdown(wait=False, cancel_futures=True)


def _pool_submit(
    requests: tuple[_StrategyRaceRequest, ...],
    channels: dict[str, RaceChannels],
) -> tuple[dict[Future[_StrategyRaceOutcome], str], object]:
    """Start both legs in spawned children, one task per child.

    An EMPTY ``channels`` means sharing is off.  The initializer is then omitted
    entirely rather than handed empty queues: only a ``multiprocessing.Queue``
    survives the spawn hand-off, so passing anything else in ``initargs`` fails
    at pickling in the parent.
    """
    context = multiprocessing.get_context("spawn")
    if channels:
        executor = ProcessPoolExecutor(
            max_workers=len(RACE_STRATEGIES),
            mp_context=context,
            max_tasks_per_child=1,
            initializer=_install_race_channels,
            initargs=(channels["freeform"].consume, channels["sequence-pair"].consume),
        )
    else:
        executor = ProcessPoolExecutor(
            max_workers=len(RACE_STRATEGIES),
            mp_context=context,
            max_tasks_per_child=1,
        )
    futures: dict[Future[_StrategyRaceOutcome], str] = {}
    for request in requests:
        futures[executor.submit(_run_race_leg, request)] = request.strategy
    return futures, executor


def run_strategy_race(
    spec: BuildSpec,
    *,
    time_budget_s: float,
    band_policy: BandPolicy,
    belt_vertical_construction: bool,
    max_belt_z: Fraction = DEFAULT_RACE_MAX_BELT_Z,
    workers: int | None = None,
    arrangements: int | None = None,
    sequence_islands: int = 1,
    config: SequenceSolverConfig | None = None,
    compact_seed_config: CompactSeedConfig | None = None,
    share: bool = True,
    submit: RaceSubmit | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> tuple[_StrategyRaceOutcome, ...]:
    """Run both strategies concurrently for ONE budget and return both outcomes.

    The first validator-clean result deliberately does NOT stop the race: the
    other arm may still find something smaller, and ``pipeline.build`` picks the
    winner by ``min(area)`` over whatever both produced.
    """
    if time_budget_s <= 0:
        raise ValueError("racing requires a positive time budget")
    # One queue per direction is a complete graph only for TWO arms, and
    # `_install_race_channels` keys exactly two.  A third strategy must fail
    # loudly here rather than silently receive nothing.
    if len(RACE_STRATEGIES) != 2:
        raise ValueError("the race queue topology is defined for exactly two strategies")
    started = monotonic()
    soft_deadline = started + time_budget_s
    hard_deadline = soft_deadline + RACE_COMPLETION_GRACE_S
    freeform_workers, sequence_workers = race_worker_split(
        _available_cores() if workers is None else workers
    )
    workers_by_strategy = {
        "freeform": freeform_workers,
        "sequence-pair": sequence_workers,
    }
    channels: dict[str, RaceChannels] = {}
    if share:
        context = multiprocessing.get_context("spawn")
        to_freeform = context.Queue(maxsize=RACE_QUEUE_MAXSIZE)
        to_sequence_pair = context.Queue(maxsize=RACE_QUEUE_MAXSIZE)
        channels = {
            "freeform": RaceChannels(publish=to_sequence_pair, consume=to_freeform),
            "sequence-pair": RaceChannels(publish=to_freeform, consume=to_sequence_pair),
        }
    requests = tuple(
        _StrategyRaceRequest(
            spec=spec,
            strategy=name,
            time_budget_s=time_budget_s,
            soft_deadline=soft_deadline,
            band_policy=band_policy,
            belt_vertical_construction=belt_vertical_construction,
            max_belt_z=max_belt_z,
            workers=workers_by_strategy[name],
            arrangements=arrangements,
            sequence_islands=sequence_islands,
            config=config or SequenceSolverConfig(),
            compact_seed_config=compact_seed_config or CompactSeedConfig(),
            share=share,
        )
        for name in RACE_STRATEGIES
    )
    outcomes: list[_StrategyRaceOutcome] = []
    first_error: BaseException | None = None
    try:
        futures, executor = (submit or _pool_submit)(requests, channels)
        strategy_by_future = dict(futures)
        # One future per arm, asserted rather than assumed.  The collector takes
        # the FIRST future for each name and `_ordered` keys a dict on the
        # strategy, so a second future for one arm would be silently dropped at
        # one of those two points -- a lost result reported as a complete race.
        if len(strategy_by_future) != len(set(strategy_by_future.values())):
            raise ValueError("each strategy must be raced exactly once")
        done, not_done = wait(
            tuple(strategy_by_future),
            timeout=max(0.0, hard_deadline - monotonic()),
        )
        del done
        if not_done:
            _terminate_executor(executor, tuple(strategy_by_future))
        else:
            cast(ProcessPoolExecutor, executor).shutdown(wait=True, cancel_futures=False)
        # Walked in RACE_STRATEGIES order, never in `done` order: `done` is a
        # set, and letting its iteration decide which of two crashed arms is
        # re-raised would make a failing race report a different exception run
        # to run.
        for name in RACE_STRATEGIES:
            future = next(
                (item for item, strategy in strategy_by_future.items() if strategy == name),
                None,
            )
            if future is None:
                continue
            if future in not_done:
                outcomes.append(
                    _StrategyRaceOutcome(
                        name,
                        "terminated",
                        refusal_reason=(
                            f"{name} overran the {time_budget_s:g}s budget by more than "
                            f"{RACE_COMPLETION_GRACE_S:g}s and was terminated"
                        ),
                        refusal_spec_label=spec.label,
                        refusal_budget_s=time_budget_s,
                    )
                )
                continue
            error = future.exception()
            if error is not None:
                first_error = first_error or error
                outcomes.append(
                    _StrategyRaceOutcome(
                        name,
                        "crashed",
                        refusal_reason=(
                            f"{name} strategy process failed: {type(error).__name__}: {error}"
                        ),
                    )
                )
                continue
            outcomes.append(future.result())
    finally:
        # Always, even on an exception: an unflushed queue holds its feeder
        # thread, and a held feeder thread holds this process open.
        for side in channels.values():
            side.close()
    if first_error is not None and all(outcome.status == "crashed" for outcome in outcomes):
        raise first_error
    return _ordered(outcomes)
