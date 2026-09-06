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

* ``settlement_reserve_s(budget) = min(40, max(10, 0.4 * budget))`` -- a share
  of the budget, not the plan's flat 5 s.
* ``_pool_width() = max(1, (workers or 16) // 4)``, and each child is
  constructed with ``_BLOCK_WORKERS = 4`` CP-SAT search workers.
* Per round, ``block_budget = clamp(remaining / waves, 5, 20)`` seconds
  (``BLOCK_BUDGET_MIN_S``/``BLOCK_BUDGET_MAX_S``), where ``remaining`` is the
  parent's wall less the settlement reserve.
* The per-JOB deadline is ``min(parent_deadline, job_start + block_budget)``,
  computed inside :func:`_solve_block` at job start rather than by the round.
* ``MAX_RESPLIT_ATTEMPTS = 4`` is counted PER BLOCK, not as a global round
  bound: a child created by a re-cut starts at attempt 0.
* The pools are SPAWNED (``multiprocessing.get_context("spawn")``), like
  ``strategy_race``'s.

The same list, with the gate measurements behind it, is
``docs/superpowers/evidence/2026-09-07-hierarchical-v1/gate.md``,
"As-shipped strategy constants".
"""

from __future__ import annotations

import math
import multiprocessing
import time
from collections.abc import Callable
from concurrent.futures import Executor, ProcessPoolExecutor
from dataclasses import dataclass, field, replace
from typing import Literal

from flab2bp.layout import finalize, validate
from flab2bp.layout.band_policy import BandPolicy
from flab2bp.layout.base import (
    NoValidLayout,
    Placement,
    PlacementCompletion,
)
from flab2bp.layout.freeform import FreeformLayout
from flab2bp.layout.hierarchy import compose as compose_mod
from flab2bp.layout.hierarchy.contracts import (
    ContractError,
    LaneEnd,
    assign_lanes,
    boundary_lanes,
)
from flab2bp.layout.hierarchy.partition import (
    STRIP_CAP_DEFAULT,
    Unit,
    composed_spec,
    derive_cuts,
    initial_partition,
    split_block,
    strip_count,
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
SETTLEMENT_RESERVE_MIN_S = 10.0
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
#: Mirrors ``pipeline.DEFAULT_WORKER_BUDGET_CAP``, duplicated rather than
#: imported because importing ``pipeline`` here would be a cycle.  It is only
#: the fallback when a caller names no budget.
_WORKER_BUDGET_DEFAULT = 16

BlockStrategyName = Literal["freeform", "sequence-pair", "best"]

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
        # The wall this call ACTUALLY has, which is not `time_budget_s` when a
        # parent handed down a deadline: a refusal that quoted the nominal
        # budget would name a number nobody spent.
        refuse = _refuser(spec, max(0.0, deadline - started_at))
        reserve = settlement_reserve_s(time_budget_s)

        partition = initial_partition(spec, strip_cap=self.strip_cap)
        entries = [_Entry(list(block)) for block in partition.blocks]
        block_wall = 0.0
        resplits = 0
        while True:
            # Re-derived every round: a re-cut changes both the block count and
            # the topological order, and `derive_cuts` returns the permutation
            # precisely so the solved placements can be carried through it.
            order, cuts = derive_cuts([entry.units for entry in entries])
            entries = [entries[index] for index in order]
            todo = [index for index, entry in enumerate(entries) if entry.placement is None]
            if not todo:
                break
            jobs = len(todo) * len(self._arms())
            waves = math.ceil(jobs / self._pool_width())
            remaining = deadline - time.monotonic() - reserve
            share = remaining / waves
            if share < BLOCK_BUDGET_MIN_S:
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
            self._solve_round(spec, entries, todo, block_budget=block_budget, deadline=deadline)
            block_wall += time.monotonic() - started
            still = [index for index in todo if entries[index].placement is None]
            if not still:
                break
            grown, progress = _recut(entries, still)
            if not progress:
                raise refuse(_block_refusal(entries, still, why="out of re-cut attempts"))
            entries = grown
            resplits += 1

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
        # `boundary_lanes` for every entry), then `assign_lanes`, then
        # `compose`. `ContractError` out of `assign_lanes` is a refusal naming
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
            flows = assign_lanes(cuts, tails, heads)
            composition = compose_mod.compose(
                solved,
                flows,
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
        if composition.failures:
            raise refuse("unrouted cut(s): " + "; ".join(composition.failures))

        # The spec the composition is JUDGED against is the one re-derived from
        # the blocks, not the one that was asked for: splitting rounds machine
        # counts up per (recipe, block), and that over-production is real.
        built = composed_spec(spec, blocks)
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

        placement.stats.update(
            {
                "blocks": float(len(blocks)),
                "block_wall_s": round(block_wall, 3),
                "compose_wall_s": round(compose_wall, 3),
                "cut_lanes": float(len(flows)),
                "resplits": float(resplits),
                "strips_max": float(max((strip_count(spec, block) for block in blocks), default=0)),
            }
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
        count -- a narrower pool than the budget funds would only add waves."""
        return max(1, (self.workers or _WORKER_BUDGET_DEFAULT) // _BLOCK_WORKERS)

    def _solve_round(
        self,
        spec: BuildSpec,
        entries: list[_Entry],
        todo: list[int],
        *,
        block_budget: float,
        deadline: float,
    ) -> None:
        """Solve every block in ``todo`` with every arm; smallest valid wins."""
        arms = self._arms()
        jobs: list[_BlockJob] = []
        for index in todo:
            sub = sub_spec(spec, entries[index].units, index)
            jobs.extend(
                (
                    sub,
                    arm,
                    block_budget,
                    self.belt_vertical_construction,
                    _BLOCK_WORKERS,
                    # The PARENT's wall. `_solve_block` combines it with
                    # `block_budget` at job start, so a job in a later wave is
                    # not handed a clock the earlier waves already spent.
                    deadline,
                )
                for arm in arms
            )
        try:
            with self._executor_factory(self._pool_width()) as pool:
                # `_solve_block` is resolved from the module globals at call
                # time, which is what lets a test substitute the worker.
                results = list(pool.map(_solve_block, jobs))
        except Exception as exc:  # noqa: BLE001 - a dead pool is a refusal, not an abort
            # A worker killed by the OOM killer, an unpicklable spec, an
            # interpreter that failed to start: `map` re-raises all of it on the
            # parent side. Losing the whole build to that would be the same
            # mistake `_solve_block`'s own CRASH arm exists to avoid, one level
            # up -- so the round becomes a round of refusals naming the failure.
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

        width = len(arms)
        for slot, index in enumerate(todo):
            outcomes = results[slot * width : (slot + 1) * width]
            winners = [placement for _record, placement in outcomes if placement is not None]
            entries[index].verdicts = tuple(
                str(record.get("verdict", "no verdict")) for record, _placement in outcomes
            )
            if winners:
                entries[index].placement = min(winners, key=lambda p: p.area)


def _recut(entries: list[_Entry], still: list[int]) -> tuple[list[_Entry], bool]:
    """Replace every refusing entry with its children; did anything change?

    Each block spends its OWN attempt counter, so ``split_block``'s four
    distinct cuts are all reachable by a block however late it was created.
    """
    grown: list[_Entry] = []
    progress = False
    refusing = set(still)
    for index, entry in enumerate(entries):
        if index not in refusing:
            grown.append(entry)
            continue
        children = _next_cut(entry)
        if children is None:
            grown.append(entry)
            continue
        progress = True
        grown.extend(_Entry(list(child)) for child in children)
    return grown, progress


def _next_cut(entry: _Entry) -> list[list[Unit]] | None:
    """The next cut of ``entry`` that actually divides it, or ``None``.

    Attempts that yield a single child are spent here rather than costing a
    whole solve round to discover, so ``_recut``'s "nothing moved" answer means
    the block is genuinely indivisible or out of attempts.
    """
    while entry.attempts < MAX_RESPLIT_ATTEMPTS:
        children = split_block(entry.units, attempt=entry.attempts)
        entry.attempts += 1
        if len(children) >= 2:
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


def _refuser(spec: BuildSpec, budget_s: float) -> Callable[[str], NoValidLayout]:
    """One place that knows how this strategy's refusals are labelled."""

    def refuse(reason: str) -> NoValidLayout:
        return NoValidLayout(reason, spec_label=spec.label, budget_s=budget_s)

    return refuse
