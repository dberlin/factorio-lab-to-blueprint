"""Which sub-solver sees a block, chosen before any placer runs.

`hierarchical` is the ORCHESTRATOR (design
`docs/superpowers/specs/2026-09-06-multi-solver-orchestrator-design.md`
§3.1-§3.3): the feature vector is computed once, from the rate solution plus
one strip plan, and the cheapest solver that meets the class's floor is run
FIRST rather than every solver being run always.

THE RULE IS READ OFF EVIDENCE, NOT TUNED HERE.
`docs/superpowers/evidence/2026-09-06-exp-features/README.md` §4(b) item 3
names `coaters` "the arm-choice feature" and cross-tabs the mean freeform /
sequence-pair AREA RATIO against `coaters` and `strips`:

    ratio          coaters = 0        coaters > 0
    strips <= 6    1.059 (n=7)        0.987 (n=15)
    strips >  6    1.399 (n=5)        1.142 (n=10)

A ratio below 1.0 is a freeform win, and there is exactly one such cell.
Experiment 5 re-tested this against the whole live-range and pressure family
and concluded "Arm choice stays with `coaters`".

WHY THERE IS STILL A BOTH-ARMS FALLBACK.  That README's own caveat is that
its thresholds are "this evidence's boundaries, not constants", fitted on 9
refusals over 3 URLs.  So two regions where it explicitly declines to
recommend a placer race both arms (see `UNCOVERED_*`), and `strategy`
re-offers the full arm set to any block whose dispatched arm refused while
wall remains -- escalation, which is design §3.3's rule, rather than a
speculative race up front.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from flab2bp.spec import BuildSpec

ARM_FREEFORM = "freeform"
ARM_SEQUENCE_PAIR = "sequence-pair"

ARM_SMALL_STRIPS = 6
UNCOVERED_ITEMS_ABOVE_ONE_BELT = 8
UNCOVERED_STRIPS = 85

#: The smallest per-block budget at which `sequence-pair` produced an exact
#: layout for EVERY coater-free mall block measured in
#: `docs/superpowers/evidence/2026-09-07-hierarchical-v4/exact-floor.md`.
#: Below it, the arm gives up in one of TWO ways, both terminal for the
#: block's OWN preparation, not just for the wall it was given:
#:   * "deadline exhausted before finding an exact layout"
#:     (`sequence_solver.py:1602`, `deadline_reached()`) -- the search was
#:     still finding new candidates when the wall ran out; a longer budget
#:     COULD have helped.
#:   * "expansion budget exhausted before finding an exact layout"
#:     (`sequence_solver.py:1603`, `self.budget.shared_left == 0`) -- the
#:     search exhausted its own candidate space on its own accounting, a
#:     termination independent of the wall clock. A longer budget CANNOT
#:     help here: nothing was still running when it gave up.
#: 31 of `mall/no-proliferator`'s 54 blocks hit one of these two in the v3
#: gate, on an arm the rule had chosen for them.
#:
#: THIS IS A MEASUREMENT, NOT A TUNING KNOB.  Re-measure it with
#: `floor_probe.py` before changing it; a value picked to make a cell pass is
#: the thing the `UNCOVERED_*` thresholds exist to avoid.
#:
#: Measured 2026-09-07: none of the five swept mall blocks (one each of
#: `magnet`, `iron-ingot`, `electric-motor`, `super-magnetic-ring`, and the
#: `circuit-board`/`processor`/`sorter-1`/`sorter-2`/`sorter-3` block)
#: produced an exact layout at ANY swept budget from `BLOCK_BUDGET_MIN_S`
#: (5.0s) through `BLOCK_BUDGET_MAX_S` (20.0s) -- all 25 cells refused. 15 of
#: those 25 (`magnet`, `iron-ingot`, `electric-motor` -- three of the five
#: shapes, at every swept budget) refused via EXPANSION BUDGET EXHAUSTED, so
#: for those three shapes no per-block budget at all -- not just none up to
#: 20.0s -- is expected to help; only the other 10 (`super-magnetic-ring` and
#: the multi-recipe block) refused via the wall clock. So per the stated rule
#: this is `BLOCK_BUDGET_MAX_S + 1.0`: no per-block budget the funding rule
#: can ever hand a coater-free block is above this floor, and for the
#: majority of the measured shapes that is true independent of the floor's
#: exact value -- which makes the abstain this constant drives STRONGER, not
#: weaker, than "raise the budget and it will eventually work" would suggest.
SEQUENCE_PAIR_EXACT_FLOOR_S = 21.0


@dataclass(frozen=True, slots=True)
class BlockFeatures:
    """The three dispatch-key features that are cheap on ONE block."""

    strips: int
    coaters: int
    items_above_one_belt: int


def lane_capacity(spec: BuildSpec) -> Fraction:
    """Items per second the FASTEST belt this save can build carries.

    The fastest tier, not the floor: `layout/belt_tiers.py` raises a run to
    the cheapest tier that carries its demand, so an item is only genuinely
    above one belt when the best available belt still cannot hold it.  This
    is the same threshold `validate`'s `flow.belt_capacity` uses, which is
    what makes the count comparable to a refusal reason.
    """
    best = max(tier.items_per_second for tier in spec.belt_tiers)
    return best * spec.belt_stack


def item_flows(spec: BuildSpec) -> dict[str, Fraction]:
    """Block-wide items/second per item: the larger of made and eaten."""
    produced: dict[str, Fraction] = {}
    consumed: dict[str, Fraction] = {}
    for group in spec.groups:
        for item_id, rate in group.outputs_per_machine.items():
            produced[item_id] = produced.get(item_id, Fraction(0)) + rate * group.count
        for item_id, rate in group.inputs_per_machine.items():
            consumed[item_id] = consumed.get(item_id, Fraction(0)) + rate * group.count
    for item_id, rate in spec.external_inputs.items():
        produced[item_id] = max(produced.get(item_id, Fraction(0)), rate)
    return {
        item_id: max(produced.get(item_id, Fraction(0)), consumed.get(item_id, Fraction(0)))
        for item_id in set(produced) | set(consumed)
    }


def block_features(sub: BuildSpec) -> BlockFeatures:
    """Score ONE block's own sub-spec.

    `plan_strips` is imported lazily, the same import-cycle shape
    `partition.strip_count` uses: `freeform` is a ~22k-line module and
    nothing else here needs it paid for up front.
    """
    from flab2bp.layout.freeform import plan_strips

    capacity = lane_capacity(sub)
    return BlockFeatures(
        strips=len(plan_strips(sub)),
        coaters=len(sub.spray_lanes),
        items_above_one_belt=sum(1 for flow in item_flows(sub).values() if flow > capacity),
    )


def dispatch_arms(
    features: BlockFeatures, arms: tuple[str, ...], *, budget_s: float | None = None
) -> tuple[str, ...]:
    """The arms this block is offered THIS round, narrowest first.

    THE ANSWER IS ALWAYS A SUBSET OF ``arms``.  The rule below names
    `ARM_FREEFORM` and `ARM_SEQUENCE_PAIR` by hand, because that is what the
    cross-tab above measured; `arms` is whatever the orchestrator is actually
    offering, which is exactly those two today (`strategy.HierarchicalLayout.
    _arms`) but which `strategy`'s THE SUB-SOLVER SEAM explicitly invites a
    later plan to grow.  Returning a name the caller never offered would
    dispatch a block to a solver nobody asked for, so a preferred arm that is
    not on offer falls back to racing the whole offered set -- the same honest
    answer the two `UNCOVERED_*` branches give when the evidence does not
    cover the block.

    A THIRD UNCOVERED REGION, AND IT IS ABOUT THE CLOCK RATHER THAN THE SHAPE.
    The cross-tab above is a ratio between two arms that both FINISHED.  A
    coater-free block funded below `SEQUENCE_PAIR_EXACT_FLOOR_S` has no such
    ratio, because the sequence-pair arm does not finish: it is cancelled
    inside exact preparation and refuses "deadline exhausted before finding an
    exact layout".  The v3 gate measured 31 of `mall/no-proliferator`'s 54
    blocks doing exactly that, against 6 unplaced when both arms were raced.
    So an underfunded coater-free block is evidence the cross-tab does not
    cover, and it gets the same answer the other two uncovered regions get.
    ``budget_s=None`` means "no budget was supplied", which keeps v3's answer
    for every caller that does not pass one.
    """
    if len(arms) < 2:
        return arms
    if features.items_above_one_belt >= UNCOVERED_ITEMS_ABOVE_ONE_BELT:
        return arms
    if features.strips >= UNCOVERED_STRIPS:
        return arms
    if features.coaters > 0 and features.strips <= ARM_SMALL_STRIPS:
        chosen = ARM_FREEFORM
    else:
        if (
            features.coaters == 0
            and budget_s is not None
            and budget_s < SEQUENCE_PAIR_EXACT_FLOOR_S
        ):
            return arms
        chosen = ARM_SEQUENCE_PAIR
    return (chosen,) if chosen in arms else arms


__all__ = [
    "ARM_FREEFORM",
    "ARM_SEQUENCE_PAIR",
    "ARM_SMALL_STRIPS",
    "SEQUENCE_PAIR_EXACT_FLOOR_S",
    "UNCOVERED_ITEMS_ABOVE_ONE_BELT",
    "UNCOVERED_STRIPS",
    "BlockFeatures",
    "block_features",
    "dispatch_arms",
    "item_flows",
    "lane_capacity",
]
