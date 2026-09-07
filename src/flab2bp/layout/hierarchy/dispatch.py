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


def dispatch_arms(features: BlockFeatures, arms: tuple[str, ...]) -> tuple[str, ...]:
    """The arms this block is offered THIS round, narrowest first."""
    if len(arms) < 2:
        return arms
    if features.items_above_one_belt >= UNCOVERED_ITEMS_ABOVE_ONE_BELT:
        return arms
    if features.strips >= UNCOVERED_STRIPS:
        return arms
    if features.coaters > 0 and features.strips <= ARM_SMALL_STRIPS:
        return (ARM_FREEFORM,)
    return (ARM_SEQUENCE_PAIR,)


__all__ = [
    "ARM_FREEFORM",
    "ARM_SEQUENCE_PAIR",
    "ARM_SMALL_STRIPS",
    "UNCOVERED_ITEMS_ABOVE_ONE_BELT",
    "UNCOVERED_STRIPS",
    "BlockFeatures",
    "block_features",
    "dispatch_arms",
    "item_flows",
    "lane_capacity",
]
