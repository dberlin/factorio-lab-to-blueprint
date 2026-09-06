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

WHAT THE PARENT PROMISES A CHILD.  Every child gets ``absolute_deadline`` --
the parent's wall, in the parent's ``time.monotonic()`` frame -- as well as its
own budget, so a block can finish early but never outlive the build.  It does
NOT get the parent's band policy: the composer discards each block's own frame
(``compose._normalize``) and repacks it, so a child's policy only shapes its
SEARCH, while the composed placement is what gets finalized against
``self.band_policy`` and certified.

WHAT COMPOSITION COSTS, AND WHY FINALIZATION IS NOT OPTIONAL.  Packing puts
blocks on different latitude rows, which re-prices every east-west spacing
inside them; a block certified where it was solved is not certified where it
landed, and ``game.power_too_close`` is the usual way that shows up.  So the
composed placement is compacted, finalized and certified here, from scratch,
and a :class:`finalize.ProjectionRefusal` is a refusal with the projection
named -- never a crash and never a handback.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import Executor, ProcessPoolExecutor
from dataclasses import dataclass, field, replace
from fractions import Fraction
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

#: Each block's own budget, as a share of the WHOLE build budget.  Blocks are
#: solved in parallel, so this is not a division of the budget between them: it
#: is how much of the wall one block may spend before the parent needs the rest
#: for re-cutting, composing and finalizing.
BLOCK_BUDGET_SHARE = Fraction(1, 2)
BLOCK_BUDGET_MIN_S = 5.0
BLOCK_BUDGET_MAX_S = 20.0
#: ``partition.split_block`` varies WHERE it cuts by attempt, and offers four
#: distinct cuts (0..3).  A fifth round would repeat the last one.
MAX_RESPLIT_ATTEMPTS = 4
#: Tiles of free ground between packed blocks.  ``compose.MIN_GAP`` is the
#: floor the router needs to turn a trunk out of a block at all.
DEFAULT_GAP = 2

#: CP-SAT search workers one block's freeform arm gets.  Blocks run
#: concurrently, so this is a per-block share rather than the box's width.
_BLOCK_WORKERS = 8
#: Mirrors ``pipeline.DEFAULT_WORKER_BUDGET_CAP``, duplicated rather than
#: imported because importing ``pipeline`` here would be a cycle.  It is only
#: the fallback when a caller names no budget.
_WORKER_BUDGET_DEFAULT = 16

BlockStrategyName = Literal["freeform", "sequence-pair", "best"]

#: One block solve: ``(sub-spec, backend, budget, vertical construction, search
#: workers, absolute deadline)``.  A plain tuple because it crosses a process
#: boundary, and every member of it pickles.
_BlockJob = tuple[BuildSpec, str, float, bool, int, float | None]

#: What a worker builds an executor with.  ``ProcessPoolExecutor`` in
#: production -- a block solve is CPU-bound and the placers are not
#: thread-parallel -- and swappable so a test that patches :func:`_solve_block`
#: can run it in a thread, where the patch actually exists.
ExecutorFactory = Callable[..., Executor]


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
    """
    spec, strategy, budget_s, vertical, workers, deadline = args
    started = time.monotonic()
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
        self._executor_factory: ExecutorFactory = ProcessPoolExecutor

    def lay_out(
        self,
        spec: BuildSpec,
        *,
        time_budget_s: float = 15.0,
        absolute_deadline: float | None = None,
    ) -> Placement:
        """Lay out ``spec`` as blocks composed on one canvas."""
        deadline = (
            absolute_deadline if absolute_deadline is not None else time.monotonic() + time_budget_s
        )
        block_budget = min(
            BLOCK_BUDGET_MAX_S,
            max(BLOCK_BUDGET_MIN_S, time_budget_s * float(BLOCK_BUDGET_SHARE)),
        )
        refuse = _refuser(spec, time_budget_s)

        partition = initial_partition(spec, strip_cap=self.strip_cap)
        entries = [_Entry(list(block)) for block in partition.blocks]
        block_wall = 0.0
        resplits = 0
        attempt = 0
        while True:
            # Re-derived every round: a re-cut changes both the block count and
            # the topological order, and `derive_cuts` returns the permutation
            # precisely so the solved placements can be carried through it.
            order, cuts = derive_cuts([entry.units for entry in entries])
            entries = [entries[index] for index in order]
            todo = [index for index, entry in enumerate(entries) if entry.placement is None]
            if not todo:
                break
            started = time.monotonic()
            self._solve_round(spec, entries, todo, block_budget=block_budget, deadline=deadline)
            block_wall += time.monotonic() - started
            still = [index for index in todo if entries[index].placement is None]
            if not still:
                break
            # Two blocks' worth of the minimum is what composing, finalizing and
            # certifying the result needs; starting a round that cannot pay for
            # its own settlement just spends the wall twice.
            out_of_time = time.monotonic() >= deadline - 2 * BLOCK_BUDGET_MIN_S
            if attempt >= MAX_RESPLIT_ATTEMPTS or out_of_time:
                raise refuse(_block_refusal(entries, still, out_of_time=out_of_time))
            grown, progress = _recut(entries, still, attempt)
            if not progress:
                raise refuse(_block_refusal(entries, still, out_of_time=False))
            entries = grown
            resplits += 1
            attempt += 1

        blocks = [entry.units for entry in entries]
        solved = [entry.placement for entry in entries if entry.placement is not None]
        # The loop above only exits when every block placed, so this is a
        # restatement of that for the type checker rather than a new claim.
        assert len(solved) == len(entries)

        tails: dict[int, list[LaneEnd]] = {}
        heads: dict[int, list[LaneEnd]] = {}
        for index, (entry, placement) in enumerate(zip(entries, solved, strict=True)):
            sub = sub_spec(spec, entry.units, index)
            tails[index], heads[index] = boundary_lanes(placement, sub, index)
        try:
            flows = assign_lanes(cuts, tails, heads)
        except ContractError as exc:
            raise refuse(f"lane contract: {exc}") from exc

        started = time.monotonic()
        composition = compose_mod.compose(
            solved,
            flows,
            spec,
            gap=DEFAULT_GAP,
            ramped=self.ramped,
            deadline=deadline,
        )
        compose_wall = time.monotonic() - started
        if composition.failures:
            raise refuse("unrouted cut(s): " + "; ".join(composition.failures))

        # The spec the composition is JUDGED against is the one re-derived from
        # the blocks, not the one that was asked for: splitting rounds machine
        # counts up per (recipe, block), and that over-production is real.
        built = composed_spec(spec, blocks)
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
        try:
            placement = finalize.compact_open_boundary_belts(placement, built, expect_power=True)
            placement = finalize.finalize_placement(
                placement,
                self.band_policy,
                cancelled=lambda: time.monotonic() >= deadline,
            )
        except finalize.ProjectionCancelled as exc:
            raise refuse("budget expired finalizing the composed placement") from exc
        except finalize.ProjectionRefusal as exc:
            raise refuse(f"composed placement refused finalization: {exc}") from exc

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
                "strips_max": float(max(strip_count(spec, block) for block in blocks)),
            }
        )
        return replace(placement, completion=PlacementCompletion.COMPACTED_AND_FINALIZED)

    def _arms(self) -> tuple[str, ...]:
        """Which backends each block is offered to."""
        if self.block_strategy == "best":
            return ("freeform", "sequence-pair")
        return (self.block_strategy,)

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
        # BOTH backends read `absolute_deadline` as REPLACING the budget, not as
        # bounding it -- `deadline = started + ceiling if absolute_deadline is
        # None else absolute_deadline`, freeform ~19561 and sequence_solver
        # ~4803.  Handing a child the parent's whole wall therefore makes
        # `block_budget` inert: measured on belt3, the first round ran the full
        # 60 s and the re-cut loop below could never start.  The wall this round
        # may spend is the SMALLER of the two, which is what both promises --
        # "a block gets `block_budget`" and "no block outlives the parent" --
        # actually mean together.
        round_deadline = min(deadline, time.monotonic() + block_budget)
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
                    round_deadline,
                )
                for arm in arms
            )
        # Blocks, not arms, set the pool width: an arm is a whole placer holding
        # `_BLOCK_WORKERS` CP-SAT workers, so the budget divides by that.
        max_workers = min(
            len(todo), max(1, (self.workers or _WORKER_BUDGET_DEFAULT) // _BLOCK_WORKERS)
        )
        with self._executor_factory(max_workers=max_workers) as pool:
            # Resolved from the module globals at call time, which is what lets
            # a test substitute the worker.
            results = list(pool.map(_solve_block, jobs))

        width = len(arms)
        for slot, index in enumerate(todo):
            outcomes = results[slot * width : (slot + 1) * width]
            winners = [placement for _record, placement in outcomes if placement is not None]
            entries[index].verdicts = tuple(
                str(record.get("verdict", "no verdict")) for record, _placement in outcomes
            )
            if winners:
                entries[index].placement = min(winners, key=lambda p: p.area)


def _recut(
    entries: list[_Entry],
    still: list[int],
    attempt: int,
) -> tuple[list[_Entry], bool]:
    """Replace every refusing entry with its children; did anything change?"""
    grown: list[_Entry] = []
    progress = False
    refusing = set(still)
    for index, entry in enumerate(entries):
        if index not in refusing:
            grown.append(entry)
            continue
        children = split_block(entry.units, attempt=attempt)
        if len(children) < 2:
            grown.append(entry)
            continue
        progress = True
        grown.extend(_Entry(list(child)) for child in children)
    return grown, progress


def _block_refusal(entries: list[_Entry], still: list[int], *, out_of_time: bool) -> str:
    """Name the blocks that never placed, their recipes, and the last verdict."""
    parts: list[str] = []
    for index in still:
        entry = entries[index]
        recipes = ", ".join(sorted({unit.recipe for unit in entry.units}))
        last = entry.verdicts[-1] if entry.verdicts else "no verdict"
        parts.append(f"block {index} ({recipes}): {last}")
    why = "out of budget" if out_of_time else "out of re-cut attempts"
    return f"{len(still)} block(s) never placed, {why}: " + "; ".join(parts)


def _refuser(spec: BuildSpec, budget_s: float) -> Callable[[str], NoValidLayout]:
    """One place that knows how this strategy's refusals are labelled."""

    def refuse(reason: str) -> NoValidLayout:
        return NoValidLayout(reason, spec_label=spec.label, budget_s=budget_s)

    return refuse
