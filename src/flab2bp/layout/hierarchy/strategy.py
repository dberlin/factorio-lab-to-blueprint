"""The hierarchical strategy: partition, solve the blocks, compose, certify.

This module is ORCHESTRATION ONLY.  Every decision with geometry in it lives in
a sibling: :mod:`~flab2bp.layout.hierarchy.partition` decides where to cut,
:mod:`~flab2bp.layout.hierarchy.contracts` decides which output lane feeds which
entry lane, :mod:`~flab2bp.layout.hierarchy.compose` packs the solved blocks and
runs the real router over the cuts, and the two production backends lay out the
blocks themselves.  What is left here is the loop: hand each block to the
placers, re-cut the ones that refuse, wire what came back, and judge the whole
thing once.

WHY THE CHILDREN ARE CONSTRUCTED HERE RATHER THAN VIA ``pipeline._new_layout``.
``pipeline`` imports this module -- ``_new_layout`` has to be able to return a
``HierarchicalLayout`` -- so importing ``pipeline`` back would be a cycle, and
the usual escapes (a function-level import, or a ``TYPE_CHECKING`` alias plus a
runtime lookup) buy nothing: ``_new_layout`` is a two-branch constructor call
and nothing else.  :func:`_block_layout` is that call, written out, at module
scope where mypy and the import graph can both see it.

HOW THE BUDGET IS DIVIDED.  A round's jobs are ``blocks x arms``, run
``_pool_width()`` at a time, so the round takes ``ceil(jobs / width)`` WAVES and
one block's wall is the round's remaining wall divided by the waves, clamped to
``[BLOCK_BUDGET_MIN_S, BLOCK_BUDGET_MAX_S]``.
:func:`settlement_reserve_s` comes off the top, because composing, ROUTING EVERY
CUT LANE, compacting, finalizing and certifying happen after the last block and
have no budget of their own.  A round whose share falls under the floor is not
started: it would only spend the settlement's wall on solves that cannot
finish.  The per-job wall is combined with the parent's deadline
inside :func:`_solve_block`, at job start -- see its docstring for why the
parent cannot do it.

WHAT THE PARENT PROMISES A CHILD.  A block can finish early but never outlives
the build.  It does NOT get the parent's band policy: the composer discards each
block's own frame (``compose._normalize``) and repacks it, so a child's policy
only shapes its SEARCH, while the composed placement is what gets finalized
against ``self.band_policy`` and certified.

WHAT COMPOSITION COSTS, AND WHY FINALIZATION IS NOT OPTIONAL.  Packing puts
blocks on different latitude rows, which re-prices every east-west spacing
inside them; a block certified where it was solved is not certified where it
landed, and ``game.power_too_close`` is the usual way that shows up.  So the
composed placement is compacted, finalized and certified here, from scratch,
and a :class:`finalize.ProjectionRefusal` is a refusal with the projection
named -- never a crash and never a handback.

THE CONSTANTS AS SHIPPED, in one place, because they differ from the ones the
plan proposed and each is spelled out separately below:

* ``settlement_reserve_s(budget) = min(40, max(5, 0.4 * budget))`` -- a share
  of the budget, not the plan's flat 5 s.  The floor dropped from 10 s to 5 s
  (v2 Task 3): at the web UI's 15 s default the old floor alone (10 s) left a
  5.0 s round -- exactly ``BLOCK_BUDGET_MIN_S``, so any wall at all spent
  partitioning tipped it under the floor and the build refused having
  attempted nothing.  The NEW floor only binds below a 12.5 s budget, but the
  CHANGE reaches further than that: the old 10 s floor bound every budget
  under 25 s (``0.4 * budget < 10`` there), so every build in ``[12.5, 25)``
  also gets a smaller reserve now (``0.4 * budget`` instead of the old flat
  10 s) even though the new floor itself is not what is binding for it.
* ``_pool_width() = max(1, min(_POOL_CAP, (workers or _available_cpu_count())
  // 4))`` with ``_POOL_CAP = 32``, and each child is constructed with
  ``_BLOCK_WORKERS = 4`` CP-SAT search workers.  v1 divided a hardcoded
  fallback of 16 rather than the box's real affinity set: on a 128-core box
  that made the pool 4 wide regardless of what the box could actually run,
  turning an 18-block, 2-arm round (36 jobs) into 9 waves instead of 2 (v2
  Task 3; see ``docs/superpowers/evidence/2026-09-07-hierarchical-v1/gate.md``
  §8).  ``_POOL_CAP`` keeps a nearly-idle box from spawning dozens of
  CP-SAT-holding processes for a build with few blocks -- each is already
  ``_BLOCK_WORKERS`` threads deep, so the pool count itself does not need to
  chase the affinity set past a point.
* Per round, ``block_budget = clamp(remaining / waves, 5, 20)`` seconds
  (``BLOCK_BUDGET_MIN_S``/``BLOCK_BUDGET_MAX_S``), where ``remaining`` is the
  parent's wall less the settlement reserve.
* The per-JOB deadline is ``min(parent_deadline, job_start + block_budget)``,
  computed inside :func:`_solve_block` at job start rather than by the round.
* ``MAX_RESPLIT_ATTEMPTS = 4`` is counted PER BLOCK, not as a global round
  bound: a child created by a re-cut starts at attempt 0.
* A ``(shape, arm)`` no-good memo, local to one :meth:`lay_out` call (v2 Task
  5): ``_solve_round`` solves each distinct shape AT MOST ONCE per round --
  two same-shaped children of one re-cut block routinely land in the same
  round and are answered together rather than asked twice -- and skips a
  ``(shape, arm)`` a prior round already saw refused at this budget or
  higher, without building its sub-spec. ``_next_cut`` skips a cut whose
  every child is remembered refused for every arm, trying the next attempt
  instead. ``stats["nogood_skips"]`` counts TWO different savings in one
  number: the ``(block, arm)`` pairs a SAME-ROUND duplicate shape answered
  without a job of its own, plus the ones a CROSS-ROUND memo hit skipped.
  A refusal is remembered at the wall the job actually received rather than
  at the nominal budget -- see :meth:`_solve_round`.
* The pool is SPAWNED (``multiprocessing.get_context("spawn")``), like
  ``strategy_race``'s, and built ONCE per :meth:`HierarchicalLayout.lay_out`
  call rather than once per round (v2 Task 3): every round of one build shares
  it, so the pool's own spawn start-up -- real wall on a process pool, paid by
  the first job submitted to it -- is paid once per build rather than once per
  round, and a re-cut's extra round does not pay it again.

The same list, with the gate measurements behind it, is
``docs/superpowers/evidence/2026-09-07-hierarchical-v2/gate.md`` -- whose §8
explicitly SUPERSEDES v1's, so it is the current one.  v1's
``docs/superpowers/evidence/2026-09-07-hierarchical-v1/gate.md`` is kept as the
historical record the constants above were first measured against.
"""

from __future__ import annotations

import math
import multiprocessing
import time
from collections.abc import Callable
from concurrent.futures import Executor, ProcessPoolExecutor
from dataclasses import dataclass, field, replace
from typing import Literal, cast

from flab2bp.layout import finalize, validate
from flab2bp.layout.band_policy import BandPolicy
from flab2bp.layout.base import (
    NoValidLayout,
    Placement,
    PlacementCompletion,
    PlacementStats,
)
from flab2bp.layout.freeform import FreeformLayout
from flab2bp.layout.hierarchy import compose as compose_mod
from flab2bp.layout.hierarchy.contracts import (
    ContractError,
    LaneEnd,
    allocate_cuts,
    boundary_lanes,
)
from flab2bp.layout.hierarchy.partition import (
    STRIP_CAP_DEFAULT,
    Unit,
    composed_spec,
    derive_cuts,
    initial_partition,
    split_block,
    sub_spec,
)
from flab2bp.layout.sequence_solver import SequencePairLayout
from flab2bp.layout.slots import SlotUndetermined, assign_sorter_slots
from flab2bp.spec import BuildSpec

#: Floor and ceiling on one block's own wall.  A block gets the round's wall
#: divided by the number of WAVES the pool needs to run the round's jobs, and a
#: round whose share falls below the floor is not started at all: a solve that
#: cannot reach an exact layout only spends the wall the settlement needs.
BLOCK_BUDGET_MIN_S = 5.0
BLOCK_BUDGET_MAX_S = 20.0
#: Bounds and share of :func:`settlement_reserve_s`.
#:
#: The reserve was a flat 5 s while composition was still unreachable, and that
#: was measured wrong the moment it became reachable: on belt3 the blocks all
#: placed, composed and built their ports, and then the ROUTER -- which spends
#: this reserve, and is by far the most expensive thing in it -- refused
#: essentially every one of ~100 cut lanes on ``BUDGET``.  Wiring the block
#: interface is not a rounding error at the end of the build, it is a second
#: routing problem the size of the interface, so the reserve scales with the
#: budget instead of being a constant.
#:
#: The floor was 10 s (v1); dropped to 5 s (v2 Task 3) because at the web UI's
#: 15 s default that floor alone left a round exactly ``BLOCK_BUDGET_MIN_S``
#: wide -- one second of partitioning wall tipped it under the floor and the
#: whole build refused without a single block ever having been offered to a
#: placer.  This floor itself only binds below a 12.5 s budget (where
#: ``SETTLEMENT_RESERVE_SHARE * budget`` is under 5 s), but the CHANGE from 10
#: to 5 reaches every budget under 25 s: the OLD floor bound anywhere
#: ``0.4 * budget < 10``, so a build anywhere in ``[12.5, 25)`` also gets a
#: smaller reserve now even though the new floor is not what is binding for
#: it -- a 20 s build's reserve silently drops from 10 s to 8 s.
SETTLEMENT_RESERVE_MIN_S = 5.0
SETTLEMENT_RESERVE_MAX_S = 40.0
SETTLEMENT_RESERVE_SHARE = 0.4
#: ``partition.split_block`` varies WHERE it cuts by attempt, and offers four
#: distinct cuts (0..3).  Counted PER BLOCK: a child created by a re-cut has
#: never been cut itself, so it starts at attempt 0 rather than inheriting its
#: parent's place in a global round counter.
MAX_RESPLIT_ATTEMPTS = 4
#: Tiles of free ground between packed blocks.  ``compose.MIN_GAP`` is the
#: floor the router needs to turn a trunk out of a block at all.
DEFAULT_GAP = 2

#: CP-SAT search workers one block's freeform arm gets.  Blocks run
#: concurrently, so this is a per-block share rather than the box's width, and
#: it is the divisor the pool width is derived from.
_BLOCK_WORKERS = 4
#: Ceiling on the pool itself, independent of how wide the box's affinity set
#: is.  What it bounds is the PROCESS COUNT AND PEAK MEMORY OF A WIDE ROUND:
#: ``ProcessPoolExecutor`` spawns per submit, so the pool width only becomes
#: real processes once a round actually has that many jobs to give out -- an
#: 80-block, 2-arm round on a 512-core box would otherwise hold 128 spawned
#: interpreters, each carrying a whole placer with ``_BLOCK_WORKERS`` CP-SAT
#: threads and its own copy of the spec.  The cap therefore costs nothing when
#: a round has fewer jobs than this to give out; ``_pool_width`` still floors
#: the box's own affinity set below it.
_POOL_CAP = 32

BlockStrategyName = Literal["freeform", "sequence-pair", "best"]

# THE SUB-SOLVER SEAM.  `hierarchical` is the ORCHESTRATOR (design
# §3.2-§3.3): it decides WHICH solver sees a block, at WHAT budget, and it
# composes the answers.  Everything a solver has to satisfy to be dispatched
# a block is on this page, and nothing in `partition`, `contracts` or
# `compose` needs to change to add one.
#
#   _BlockJob = (spec, arm, budget_s, vertical, workers, parent_deadline)
#     0 spec            a self-contained BuildSpec from `partition.sub_spec`:
#                       boundary items are `external_inputs`/`outputs`, belt
#                       tiers / sorter ladder / stack / piler travel verbatim,
#                       and `spray_lanes` is RECOMPUTED for the block.
#     1 arm             the solver's name, one of `BlockStrategyName`.
#     2 budget_s        the round's per-block wall, in seconds.
#     3 vertical        `belt_vertical_construction`; the composer's `ramped`
#                       is its negation.
#     4 workers         `_BLOCK_WORKERS` CP-SAT search workers for THIS block.
#     5 parent_deadline absolute `time.monotonic()` deadline, or None.  The
#                       WORKER combines it: `min(parent, start + budget_s)`.
#
#   _solve_block(job) -> (record, Placement | None)
#     record["strategy"] : str   the arm, echoed back
#     record["verdict"]  : str   "OK" | "REFUSED: ..." | "CRASH: ..."
#                                | "POOL FAILED: ..."  -- ONLY "REFUSED: " is
#                                remembered by `_ShapeNoGood`, because a crash
#                                or a dead pool says nothing about the SHAPE.
#     record["ok"]       : bool
#     record["wall_s"]   : float what the job actually spent (the memo records
#                                a refusal at THIS, not at the nominal budget)
#     record["area"]     : float on the OK path only
#     A refusal and a crash are RESULTS, not aborts: one block must never take
#     the other nine with it.
#
#   _block_layout(arm, *, vertical, workers) -> LayoutStrategy
#     THE REGISTRY POINT (design §3.2).  A new solver is added HERE, named in
#     `BlockStrategyName`, and given an arm-choice rule in
#     `hierarchy.dispatch`.  It must implement
#     `lay_out(spec, *, time_budget_s, absolute_deadline) -> Placement` and
#     raise `NoValidLayout` rather than return something invalid, and its
#     `Placement` must pickle (it crosses a spawn boundary).  Candidates
#     already named in `docs/speedup-idea-backlog.md`: the pre-generated block
#     library, a revived `spine`, coater-composite strips.
#: One block solve: ``(sub-spec, backend, budget, vertical construction, search
#: workers, absolute deadline)``.  A plain tuple because it crosses a process
#: boundary, and every member of it pickles.
_BlockJob = tuple[BuildSpec, str, float, bool, int, float | None]

#: What a round builds its executor with, taking the pool width.  Swappable so
#: a test that patches :func:`_solve_block` can run it in a thread, where the
#: patch actually exists.
ExecutorFactory = Callable[[int], Executor]


def settlement_reserve_s(time_budget_s: float) -> float:
    """Wall held back from the block solves for everything that follows them.

    Composition, the router that wires every cut lane, the boundary-belt
    compaction, the finalization and the certification all happen after the last
    block and have no budget of their own, so it is withheld rather than hoped
    for.  Computed from the budget the caller named -- including when a parent
    handed down a deadline, because what the settlement costs tracks the size of
    the build, not who started the clock.
    """
    return min(
        SETTLEMENT_RESERVE_MAX_S,
        max(SETTLEMENT_RESERVE_MIN_S, SETTLEMENT_RESERVE_SHARE * time_budget_s),
    )


def _available_cpu_count() -> int:
    """The affinity set this process may actually run on.

    A module-level wrapper, not a lazy import inlined into :meth:`_pool_width`,
    so a test can ``monkeypatch.setattr(strategy, "_available_cpu_count", ...)``
    and have it take: a bare ``from flab2bp.pipeline import _available_cpu_count``
    called from inside ``_pool_width`` would resolve ``pipeline``'s own name
    every time, unreachable from here.  Lazy at CALL time, not at module load,
    because ``pipeline`` imports ``hierarchy`` -- importing it back at module
    scope would be the same cycle :func:`_block_layout`'s docstring explains.
    """
    from flab2bp.pipeline import _available_cpu_count as _impl

    return _impl()


def _spawn_pool(max_workers: int) -> Executor:
    """A block-solving pool, spawned rather than forked.

    Same context, and the same reason, as ``strategy_race`` (~660): forking a
    parent that already holds solver threads and native handles is not safe,
    and the placers hold both.  A block solve is CPU-bound and the placers are
    not thread-parallel, so this is processes rather than threads.
    """
    return ProcessPoolExecutor(
        max_workers=max_workers,
        mp_context=multiprocessing.get_context("spawn"),
    )


def _block_layout(
    strategy: str,
    *,
    vertical: bool,
    workers: int,
) -> FreeformLayout | SequencePairLayout:
    """Construct one block backend.  See the module docstring for why here."""
    if strategy == "freeform":
        return FreeformLayout(
            belt_vertical_construction=vertical,
            band_policy=BandPolicy.parse("portable"),
            workers=workers,
        )
    return SequencePairLayout(
        belt_vertical_construction=vertical,
        band_policy=BandPolicy.parse("portable"),
        islands=1,
    )


def _solve_block(args: _BlockJob) -> tuple[dict[str, object], Placement | None]:
    """Lay out one block with one backend; a refusal and a CRASH are results.

    Lifted from ``docs/superpowers/evidence/2026-09-06-exp-hierarchical/proto/
    run.py``.  A placer that raises inside one block must not lose the other
    nine -- the prototype's ``mall/all-products`` block 3 raised
    ``ValueError: stage-boundary transform must rebuild every restart
    identically`` and took the whole run with it -- and the crash is itself
    evidence about the sub-specs a decomposer hands the placers, so it is
    recorded rather than swallowed silently.

    THE JOB'S WALL IS COMPUTED HERE, at job start, and index 5 of ``args``
    carries the PARENT's deadline rather than a per-round one.  Both backends
    read ``absolute_deadline`` as REPLACING their budget rather than bounding it
    (``freeform`` ~19561, ``sequence_solver`` ~4803), so the two have to be
    combined somewhere -- and a deadline computed by the parent before the pool
    starts is already partly spent by the time a job in the SECOND wave runs.
    A pool two wide running six jobs handed every job after the first two a
    clock with nothing left on it, and they refused instantly with "deadline
    exhausted"; that is why it is the worker, not the round, that does this.
    """
    spec, strategy, budget_s, vertical, workers, parent_deadline = args
    started = time.monotonic()
    deadline = (
        started + budget_s if parent_deadline is None else min(parent_deadline, started + budget_s)
    )
    layout = _block_layout(strategy, vertical=vertical, workers=workers)
    try:
        placement = layout.lay_out(spec, time_budget_s=budget_s, absolute_deadline=deadline)
    except NoValidLayout as exc:
        return (
            {
                "strategy": strategy,
                "wall_s": round(time.monotonic() - started, 2),
                "verdict": f"REFUSED: {exc.reason}"[:400],
                "ok": False,
            },
            None,
        )
    except Exception as exc:  # noqa: BLE001 - a placer CRASH is a result, not an abort
        return (
            {
                "strategy": strategy,
                "wall_s": round(time.monotonic() - started, 2),
                "verdict": f"CRASH: {type(exc).__name__}: {exc}"[:400],
                "ok": False,
                "crash": True,
            },
            None,
        )
    return (
        {
            "strategy": strategy,
            "wall_s": round(time.monotonic() - started, 2),
            "verdict": "OK",
            "ok": True,
            "area": placement.area,
        },
        placement,
    )


#: A block's shape: sorted `(recipe_id, machine count)` pairs, ONE PER
#: `Unit` -- never aggregated by recipe id.  Deliberately NOT keyed on
#: `uid`, `MachineGroup` identity or block position -- `split_block`'s
#: "halve" attempt on a single-recipe block routinely produces two children
#: of the identical shape (a refused two-machine smelter block splits into
#: two one-machine ones), and those ask a placer the identical question, so
#: this key lets `_solve_round` recognise that.  Recipe count is also what
#: the module docstring's "six machines refused, three plus three placed"
#: is about: it is the coarsest key that still tracks what makes the
#: placers say yes or no.
#:
#: AGGREGATING by recipe id would be wrong, not just coarser: a block
#: `[Unit(iron, 1), Unit(iron, 2)]` and a block `[Unit(iron, 3)]` would hash
#: equal, but `sub_spec` builds a TWO-`MachineGroup` spec for the first and
#: a ONE-`MachineGroup` spec for the second -- genuinely different
#: questions, and the second would silently receive the first's placement.
#: `partition.coalesce` merges same-recipe `Unit`s into one today, so this
#: never arises from `split_block`'s own output, but that invariant lives in
#: a different module with nothing here pinning it, so the key does not
#: lean on it.
ShapeKey = tuple[tuple[str, int], ...]


def shape_key(units: list[Unit]) -> ShapeKey:
    """The shape `units` presents to a placer: one `(recipe, count)` per `Unit`.

    NOT aggregated by recipe id -- see `ShapeKey`'s own comment for why that
    would manufacture a collision between two blocks `sub_spec` treats as
    different questions.
    """
    return tuple(sorted((unit.recipe, unit.count) for unit in units))


@dataclass
class _ShapeNoGood:
    """Refused `(shape, arm)` pairs, remembered for the rest of one build.

    Lives on the `lay_out` CALL, not on `HierarchicalLayout` itself: a block
    shape is only evidence about what THIS build's placers can do with THIS
    budget, and stashing it on `self` would leak one build's refusals into
    the next `lay_out` call on the same instance -- exactly the mistake
    `test_the_memo_forgets_across_lay_out_calls` guards against.

    Keyed by the HIGHEST budget a `(shape, arm)` has been refused at, not the
    latest: block size interacts with the placers non-monotonically (the
    module docstring's "six machines refused, three plus three placed"), but
    WALL TIME does not -- a placer given more of it never does worse, so a
    refusal at a higher budget also answers a round asking for less.
    """

    refused: dict[tuple[ShapeKey, str], float] = field(default_factory=dict)

    def remembers(self, key: ShapeKey, arm: str, budget_s: float) -> bool:
        seen = self.refused.get((key, arm))
        return seen is not None and seen >= budget_s

    def record(self, key: ShapeKey, arm: str, budget_s: float) -> None:
        seen = self.refused.get((key, arm))
        if seen is None or budget_s > seen:
            self.refused[(key, arm)] = budget_s


@dataclass(slots=True)
class _Entry:
    """One block: its units, its winning placement, and why it refused."""

    units: list[Unit]
    placement: Placement | None = None
    #: Every arm's verdict from the last round this block was solved in, so a
    #: block that never places can say what the placers actually said.
    verdicts: tuple[str, ...] = field(default_factory=tuple)
    #: How many times THIS block has been re-cut.  Per block, not per round: a
    #: child created by a re-cut has never been cut itself, and starting it at
    #: its parent's count would deny it the cuts `split_block` offers.
    attempts: int = 0


class HierarchicalLayout:
    """Decompose a spec into blocks, solve them apart, and wire them back up."""

    name = "hierarchical"

    def __init__(
        self,
        *,
        belt_vertical_construction: bool,
        band_policy: BandPolicy,
        workers: int | None = None,
        strip_cap: int = STRIP_CAP_DEFAULT,
        block_strategy: BlockStrategyName = "best",
    ) -> None:
        self.band_policy = band_policy
        #: Whether ramps are REQUIRED; the composer's router takes this as
        #: ``ramped``.  Same conditional slope rule, and the same default, as
        #: ``FreeformLayout``.
        self.ramped = not belt_vertical_construction
        self.belt_vertical_construction = belt_vertical_construction
        self.workers = workers
        self.strip_cap = strip_cap
        self.block_strategy = block_strategy
        self._executor_factory: ExecutorFactory = _spawn_pool

    def lay_out(
        self,
        spec: BuildSpec,
        *,
        time_budget_s: float = 15.0,
        absolute_deadline: float | None = None,
    ) -> Placement:
        """Lay out ``spec`` as blocks composed on one canvas."""
        started_at = time.monotonic()
        deadline = (
            absolute_deadline if absolute_deadline is not None else started_at + time_budget_s
        )
        stats = _StrategyStats()
        # The wall this call ACTUALLY has, which is not `time_budget_s` when a
        # parent handed down a deadline: a refusal that quoted the nominal
        # budget would name a number nobody spent.
        refuse = _refuser(spec, max(0.0, deadline - started_at), stats)
        reserve = settlement_reserve_s(time_budget_s)

        partition = initial_partition(spec, strip_cap=self.strip_cap)
        entries = [_Entry(list(block)) for block in partition.blocks]
        stats.blocks = float(len(entries))
        block_wall = 0.0
        # THIS CALL'S OWN no-good memo -- see `_ShapeNoGood`'s docstring for
        # why it is a local rather than `self._nogood`.
        nogood = _ShapeNoGood()
        # ONE POOL FOR THE WHOLE BUILD, not one per round: a re-cut starts a
        # new round with more (smaller) blocks, and building a fresh pool for
        # it would pay a spawned process pool's own start-up again for jobs
        # that pool never even needed to be wider for.  Constructing the
        # executor here does not itself spawn a worker -- `ProcessPoolExecutor`
        # starts processes lazily, on the first `map()` -- so a build that
        # refuses before ever funding a round (the check just below) spawns
        # nothing at all.
        width = self._pool_width()
        try:
            executor = self._executor_factory(width)
        except Exception as exc:  # noqa: BLE001 - a pool that cannot even be built is a refusal
            # `ProcessPoolExecutor.__init__` does not spawn a worker, but it DOES
            # build the multiprocessing queues a worker will use -- pipes plus a
            # POSIX semaphore -- which fail with `OSError` on fd exhaustion
            # (EMFILE) or a full `/dev/shm` (ENOSPC), both real on a shared box
            # that is never idle.  Uncaught, that would escape as a raw
            # traceback, breaking the `Placement` or `NoValidLayout` contract
            # this method promises -- the same failure `_solve_round`'s own
            # guard exists to prevent for a pool that dies mid-round, one step
            # earlier: before it is ever used.
            raise refuse(
                _block_refusal(
                    entries,
                    [index for index, entry in enumerate(entries) if entry.placement is None],
                    why=f"block pool unavailable: {type(exc).__name__}: {exc}",
                )
            ) from exc
        with executor as pool:
            while True:
                # Re-derived every round: a re-cut changes both the block count
                # and the topological order, and `derive_cuts` returns the
                # permutation precisely so the solved placements can be carried
                # through it.
                order, cuts = derive_cuts([entry.units for entry in entries])
                entries = [entries[index] for index in order]
                stats.blocks = float(len(entries))
                todo = [index for index, entry in enumerate(entries) if entry.placement is None]
                if not todo:
                    break
                jobs = len(todo) * len(self._arms())
                waves = math.ceil(jobs / width)
                remaining = deadline - time.monotonic() - reserve
                share = remaining / waves
                if share < BLOCK_BUDGET_MIN_S:
                    stats.blocks_unattempted = float(
                        sum(1 for entry in entries if not entry.verdicts)
                    )
                    raise refuse(
                        _block_refusal(
                            entries,
                            todo,
                            why=(
                                f"{remaining:.1f}s left over {waves} wave(s) is under the "
                                f"{BLOCK_BUDGET_MIN_S:g}s a block solve is given at all"
                            ),
                        )
                    )
                block_budget = min(BLOCK_BUDGET_MAX_S, max(BLOCK_BUDGET_MIN_S, share))
                started = time.monotonic()
                stats.nogood_skips += self._solve_round(
                    spec,
                    entries,
                    todo,
                    pool=pool,
                    block_budget=block_budget,
                    deadline=deadline,
                    nogood=nogood,
                )
                block_wall += time.monotonic() - started
                still = [index for index in todo if entries[index].placement is None]
                if not still:
                    break
                grown, progress = _recut(
                    entries, still, nogood=nogood, arms=self._arms(), budget_s=block_budget
                )
                if not progress:
                    stats.blocks_unattempted = float(
                        sum(1 for entry in entries if not entry.verdicts)
                    )
                    raise refuse(_block_refusal(entries, still, why="out of re-cut attempts"))
                entries = grown
                stats.resplits += 1

        blocks = [entry.units for entry in entries]
        solved = [entry.placement for entry in entries if entry.placement is not None]
        # The loop above only exits when every block placed, so this is a
        # restatement of that for the type checker rather than a new claim.
        assert len(solved) == len(entries)

        # WIRING AND COMPOSITION, UNDER A CRASH GUARD.  `lay_out` promises a
        # valid `Placement` or a `NoValidLayout`, and the guarded body below
        # reads geometry this strategy assembled out of independently solved
        # blocks -- shapes no single block ever showed its own placer.
        #
        # WHAT IS GUARDED, exactly: the per-block loop (`sub_spec` and
        # `boundary_lanes` for every entry), then `allocate_cuts`, then
        # `compose`. `ContractError` out of `allocate_cuts` is a refusal naming
        # the lane contract; ANY OTHER exception out of any of them -- including
        # a bug in `partition`, `contracts` or `compose` themselves -- becomes
        # the refusal `composition crashed: <type>: <message>`.
        #
        # That is deliberate and it is the right trade for a STRATEGY.  A
        # refusal names the build, keeps the other candidates in a race alive
        # and is recorded as evidence; a traceback out of `lay_out` breaks the
        # contract every caller relies on and loses the whole build over a
        # defect in one composed shape. The cost is that such a defect surfaces
        # as a refusal line rather than a stack, which is why the message
        # carries the exception type and text verbatim.
        #
        # The body is kept to exactly those calls, so a defect in the rest of
        # this module -- the settlement below included -- is still a traceback.
        started = time.monotonic()
        try:
            tails: dict[int, list[LaneEnd]] = {}
            heads: dict[int, list[LaneEnd]] = {}
            for index, (entry, placement) in enumerate(zip(entries, solved, strict=True)):
                sub = sub_spec(spec, entry.units, index)
                tails[index], heads[index] = boundary_lanes(placement, sub, index)
            allocation = allocate_cuts(spec, cuts, tails, heads)
            stats.player_fed = float(len(allocation.player_fed))
            stats.cut_lanes = float(len(allocation.flows))
            composition = compose_mod.compose(
                solved,
                allocation.flows,
                spec,
                gap=DEFAULT_GAP,
                ramped=self.ramped,
                # The PARENT's wall, not the reserve. The reserve is what the
                # block rounds were made to leave behind for the router; it is
                # not a second, tighter ceiling to then judge the router by.
                deadline=deadline,
            )
        except ContractError as exc:
            raise refuse(f"lane contract: {exc}") from exc
        except Exception as exc:  # noqa: BLE001 - a composer CRASH is a refusal
            raise refuse(f"composition crashed: {type(exc).__name__}: {exc}"[:400]) from exc
        compose_wall = time.monotonic() - started
        stats.unrouted_cuts = float(len(composition.failures))
        if composition.failures:
            raise refuse("unrouted cut(s): " + "; ".join(composition.failures))

        # The spec the composition is JUDGED against is the one re-derived from
        # the blocks, not the one that was asked for: splitting rounds machine
        # counts up per (recipe, block), and that over-production is real.
        built = composed_spec(spec, blocks, player_fed=allocation.player_fed)
        # The settlement below is the only stretch with no budget of its own:
        # `assign_sorter_slots` takes no `cancelled` and `certify` is atomic. It
        # is entered only with wall left to enter it with; `settlement_reserve_s`
        # is what the rounds above held back so that is normally true.
        if time.monotonic() >= deadline:
            raise refuse("deadline exhausted before finalization")
        # THE SLOT PASS RUNS ON THE COMPOSED LIST, not on the blocks.
        # `slots.assign_sorter_slots` is "the ONE post-pass both strategies
        # already call" on a finished building list, and its belt half assigns
        # each link a free cell in the RECEIVING belt's pool -- an assignment
        # that is only correct over the whole list.  The composition adds links
        # no block ever saw: the router's own belt runs, and the cut lanes that
        # attach to a block's boundary belt.  Left unassigned those keep the
        # dataclass default of 0, which is the receiving belt's OWN output cell,
        # and `game.slot_occupancy` convicts every one of them.
        try:
            placement = replace(
                composition.placement,
                buildings=assign_sorter_slots(composition.placement.buildings),
            )
        except SlotUndetermined as exc:
            raise refuse(f"a composed link's slot could not be derived: {exc}") from exc
        expired = lambda: time.monotonic() >= deadline  # noqa: E731
        try:
            placement = finalize.compact_open_boundary_belts(
                placement, built, expect_power=True, cancelled=expired
            )
            placement = finalize.finalize_placement(placement, self.band_policy, cancelled=expired)
        except finalize.ProjectionCancelled as exc:
            raise refuse("budget expired finalizing the composed placement") from exc
        except finalize.ProjectionRefusal as exc:
            raise refuse(f"composed placement refused finalization: {exc}") from exc

        # Uncancelled, deliberately: certification is the atomic completion step
        # and there is nothing to hand back without it, so it runs under the
        # pipeline's completion grace rather than under this strategy's wall.
        report = validate.certify(placement, built, expect_power=True)
        if not report.ok:
            raise refuse(
                "composed placement failed validation: "
                + "; ".join(f"{f.check}: {f.message}" for f in report.errors[:3])
            )

        # NO `strips_max` HERE.  It was a diagnostic -- strips in the widest
        # block -- and v2 Task 2 made `partition.strip_count` call
        # `freeform.plan_strips`, the real packer, so recomputing it once per
        # block on the SUCCESS path spent real wall AFTER the deadline check
        # and after certification, inflating the reported wall past `--budget`
        # for a number nothing reads back.  The counts are not reachable from
        # here either: `initial_partition` strip-counts the blocks it examines,
        # but `coalesce` then merges them (a merged block's count is not the
        # sum) and `_recut`'s children were never counted at all, so a
        # faithful `strips_max` over the FINAL blocks could only be recomputed.
        placement.stats.update(
            cast(
                PlacementStats,
                {
                    **stats.as_stats(),
                    "block_wall_s": round(block_wall, 3),
                    "compose_wall_s": round(compose_wall, 3),
                },
            )
        )
        return replace(placement, completion=PlacementCompletion.COMPACTED_AND_FINALIZED)

    def _arms(self) -> tuple[str, ...]:
        """Which backends each block is offered to."""
        if self.block_strategy == "best":
            return ("freeform", "sequence-pair")
        return (self.block_strategy,)

    def _pool_width(self) -> int:
        """Jobs run at once.  One job is a whole placer holding CP-SAT workers,
        so the worker budget divides by what a job is given, not by the block
        count -- a narrower pool than the budget funds would only add waves.

        The fallback when no ``workers`` was named is the box's own affinity
        set (:func:`_available_cpu_count`), not a hardcoded guess: a guess
        narrower than the box is waves the box had room to avoid, and one
        wider than the box would oversubscribe it.  ``_POOL_CAP`` still bounds
        the result on a very wide box -- see its own docstring.
        """
        return max(1, min(_POOL_CAP, (self.workers or _available_cpu_count()) // _BLOCK_WORKERS))

    def _solve_round(
        self,
        spec: BuildSpec,
        entries: list[_Entry],
        todo: list[int],
        *,
        pool: Executor,
        block_budget: float,
        deadline: float,
        nogood: _ShapeNoGood,
    ) -> int:
        """Solve every block in ``todo`` with every arm; smallest valid wins.

        ``pool`` is the ONE pool `lay_out` built for the whole build, opened
        and closed there -- this method never constructs or shuts one down.

        A JOB IS KEYED BY ``(shape, arm)``, NOT BY ``(block, arm)``.
        ``_recut``'s "halve" attempt on a single-recipe block routinely hands
        back two children of the IDENTICAL shape (a refused two-machine
        smelter block splits into two one-machine ones), and both land in
        THIS round together -- so every distinct ``(shape, arm)`` in ``todo``
        is solved AT MOST ONCE here: the first block that needs it is the one
        actually offered to a placer, and every later block sharing that
        shape gets the SAME answer, including the same ``Placement`` object.
        That reuse is safe because nothing downstream mutates a ``Placement``
        in place -- the composer only ever reads one through
        ``dataclasses.replace`` (see ``tests/layout/hierarchy/conftest.py``'s
        ``two_solved_blocks`` docstring) -- and it is correct because two
        same-shaped blocks' ``sub_spec``s (see its own docstring) differ
        ONLY in a diagnostic ``label`` (``partition.sub_spec``'s sole use of
        its own ``index`` argument), which reaches nothing but refusal text
        and ``Placement.description`` -- itself overwritten outright by the
        composer.  A refusal verdict recorded against a shared shape may
        therefore NAME A SIBLING BLOCK'S INDEX rather than the one it is
        attached to; that is a cosmetic cost this sharing accepts, not a
        correctness one. ``nogood`` additionally skips a
        ``(shape, arm)`` a PRIOR round already saw refused at this budget or
        higher, without even building its sub-spec. Returns how many
        ``(block, arm)`` pairs this round did NOT hand to a placer -- a
        remembered no-good or a same-round duplicate.
        """
        arms = self._arms()
        shapes = [shape_key(entries[index].units) for index in todo]
        # `(shape, arm) -> todo-slots that need this exact question answered`,
        # insertion-ordered so the FIRST slot to need a key is the one whose
        # sub-spec actually gets built and solved.
        slots_by_key: dict[tuple[ShapeKey, str], list[int]] = {}
        for slot in range(len(todo)):
            for arm in arms:
                slots_by_key.setdefault((shapes[slot], arm), []).append(slot)

        jobs: list[_BlockJob] = []
        job_keys: list[tuple[ShapeKey, str]] = []
        skipped = 0
        for (key, arm), slots in slots_by_key.items():
            if nogood.remembers(key, arm, block_budget):
                skipped += len(slots)
                continue
            index = todo[slots[0]]
            jobs.append(
                (
                    sub_spec(spec, entries[index].units, index),
                    arm,
                    block_budget,
                    self.belt_vertical_construction,
                    _BLOCK_WORKERS,
                    # The PARENT's wall. `_solve_block` combines it with
                    # `block_budget` at job start, so a job in a later wave is
                    # not handed a clock the earlier waves already spent.
                    deadline,
                )
            )
            job_keys.append((key, arm))
            # Every OTHER slot sharing this key is answered without a job of
            # its own -- see the docstring's "AT MOST ONCE".
            skipped += len(slots) - 1
        try:
            # `_solve_block` is resolved from the module globals at call time,
            # which is what lets a test substitute the worker.
            results = list(pool.map(_solve_block, jobs))
        except Exception as exc:  # noqa: BLE001 - a dead pool is a refusal, not an abort
            # A worker killed by the OOM killer, an unpicklable spec, an
            # interpreter that failed to start: `map` re-raises all of it on the
            # parent side. Losing the whole build to that would be the same
            # mistake `_solve_block`'s own CRASH arm exists to avoid, one level
            # up -- so the round becomes a round of refusals naming the failure.
            # The pool itself is left as `lay_out` made it: a pool that died
            # here stays dead, and any further round this build starts (a
            # re-cut) will hit this same guard again rather than crash.
            results = [
                (
                    {
                        "strategy": job[1],
                        "verdict": f"POOL FAILED: {type(exc).__name__}: {exc}"[:400],
                        "ok": False,
                    },
                    None,
                )
                for job in jobs
            ]

        skip_record: tuple[dict[str, object], Placement | None] = (
            {"verdict": "REFUSED: shape already refused this build (no-good)", "ok": False},
            None,
        )
        outcome_by_key: dict[tuple[ShapeKey, str], tuple[dict[str, object], Placement | None]] = {}
        for job_key, result in zip(job_keys, results, strict=True):
            record, _placement = result
            # Only a genuine placer REFUSAL says anything about the SHAPE.
            # "POOL FAILED" and a placer CRASH are infrastructure failures --
            # remembering either as a no-good would hide a pool or placer bug
            # behind "this shape is already known to be impossible."
            if str(record.get("verdict", "")).startswith("REFUSED:"):
                # AT THE WALL THE JOB REALLY GOT, NOT THE ROUND'S NOMINAL
                # BUDGET.  `_solve_block` clips its own deadline to
                # `min(parent_deadline, started + budget_s)`, so a job in a
                # later wave can be handed a clock with nearly nothing left on
                # it and refuse instantly with "deadline exhausted" (its own
                # docstring records that happening).  `_ShapeNoGood`'s
                # soundness argument is that a placer given MORE wall never
                # does worse, so a refusal at a higher budget answers a round
                # asking for less -- and a clipped job breaks exactly that
                # premise: recording it at `block_budget` would claim the shape
                # was tried with wall it never received, skip it for the rest
                # of the build, and spend `_next_cut`'s re-cut attempts on cuts
                # whose children were never really offered to a placer.
                # `wall_s` is what the job actually spent; the `min` clamps a
                # job that OVERRAN its share back to the budget a round would
                # have to offer to re-ask, so the memo never remembers a
                # refusal at a budget no round ever handed out.  The default
                # keeps a record without a `wall_s` (the refusal shape a test
                # double hands back) at the nominal budget.
                wall = record.get("wall_s")
                spent = float(wall) if isinstance(wall, int | float) else block_budget
                nogood.record(job_key[0], job_key[1], min(block_budget, spent))
            outcome_by_key[job_key] = result

        for slot, index in enumerate(todo):
            outcomes = [outcome_by_key.get((shapes[slot], arm), skip_record) for arm in arms]
            winners = [placement for _record, placement in outcomes if placement is not None]
            entries[index].verdicts = tuple(
                str(record.get("verdict", "no verdict")) for record, _placement in outcomes
            )
            if winners:
                entries[index].placement = min(winners, key=lambda p: p.area)
        return skipped


def _recut(
    entries: list[_Entry],
    still: list[int],
    *,
    nogood: _ShapeNoGood,
    arms: tuple[str, ...],
    budget_s: float,
) -> tuple[list[_Entry], bool]:
    """Replace every refusing entry with its children; did anything change?

    Each block spends its OWN attempt counter, so ``split_block``'s four
    distinct cuts are all reachable by a block however late it was created.
    ``nogood``, ``arms`` and ``budget_s`` are threaded through to
    ``_next_cut`` so it can skip a cut this build already knows is wasted --
    see its own docstring.
    """
    grown: list[_Entry] = []
    progress = False
    refusing = set(still)
    for index, entry in enumerate(entries):
        if index not in refusing:
            grown.append(entry)
            continue
        children = _next_cut(entry, nogood=nogood, arms=arms, budget_s=budget_s)
        if children is None:
            grown.append(entry)
            continue
        progress = True
        grown.extend(_Entry(list(child)) for child in children)
    return grown, progress


def _next_cut(
    entry: _Entry, *, nogood: _ShapeNoGood, arms: tuple[str, ...], budget_s: float
) -> list[list[Unit]] | None:
    """The next cut of ``entry`` that actually divides it, or ``None``.

    Attempts that yield a single child are spent here rather than costing a
    whole solve round to discover, so ``_recut``'s "nothing moved" answer means
    the block is genuinely indivisible or out of attempts.

    A cut whose EVERY child is already remembered refused, for EVERY arm, at
    ``budget_s`` or higher is spent too without ever being offered to a
    placer: the round about to run this cut already paid, in an EARLIER
    round, for exactly the refusal solving those children again would only
    rediscover.
    """
    while entry.attempts < MAX_RESPLIT_ATTEMPTS:
        children = split_block(entry.units, attempt=entry.attempts)
        entry.attempts += 1
        if len(children) < 2:
            continue
        if all(
            nogood.remembers(shape_key(child), arm, budget_s) for child in children for arm in arms
        ):
            continue
        return children
    return None


def _block_refusal(entries: list[_Entry], still: list[int], *, why: str) -> str:
    """Name the blocks that never placed, their recipes, and the last verdict."""
    parts: list[str] = []
    for index in still:
        entry = entries[index]
        recipes = ", ".join(sorted({unit.recipe for unit in entry.units}))
        last = entry.verdicts[-1] if entry.verdicts else "not attempted"
        parts.append(f"block {index} ({recipes}): {last}")
    return f"{len(still)} block(s) never placed, {why}: " + "; ".join(parts)


@dataclass
class _StrategyStats:
    """Every number the gate reads, accumulated as the build runs.

    Carried into the `NoValidLayout` of EVERY refusal, not just written onto
    a successful `Placement`: the v2 gate refused on all sixteen runs and
    could therefore read none of these from a shipped surface.
    """

    blocks: float = 0.0
    blocks_unattempted: float = 0.0
    recut_rounds: float = 0.0
    resplits: float = 0.0
    nogood_skips: float = 0.0
    player_fed: float = 0.0
    cut_lanes: float = 0.0
    compose_gap: float = 0.0
    port_demands: float = 0.0
    reservation_missing: float = 0.0
    unrouted_cuts: float = 0.0
    arm_dispatch_freeform: float = 0.0
    arm_dispatch_sequence_pair: float = 0.0
    arm_dispatch_both: float = 0.0

    def as_stats(self) -> dict[str, float]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


def _refuser(
    spec: BuildSpec, budget_s: float, stats: _StrategyStats
) -> Callable[[str], NoValidLayout]:
    def refuse(reason: str) -> NoValidLayout:
        return NoValidLayout(
            reason, spec_label=spec.label, budget_s=budget_s, stats=stats.as_stats()
        )

    return refuse
