"""The arm-choice rule, read off `2026-09-06-exp-features`.

Every threshold here is that evidence's; nothing is tuned locally.  The
cross-tab it implements is README §4(b) item 3.
"""

from __future__ import annotations

from fractions import Fraction

from flab2bp.layout.hierarchy import dispatch, strategy
from flab2bp.layout.hierarchy.dispatch import BlockFeatures

_BOTH = ("freeform", "sequence-pair")


def test_a_small_coated_block_goes_to_freeform_alone():
    # cross-tab cell `coaters > 0, strips <= 6`: mean ff/sp ratio 0.987
    got = dispatch.dispatch_arms(BlockFeatures(strips=5, coaters=2, items_above_one_belt=0), _BOTH)
    assert got == ("freeform",)


def test_a_small_uncoated_block_goes_to_sequence_pair_alone():
    # cell `coaters = 0, strips <= 6`: 1.059 -- freeform is the larger pack
    got = dispatch.dispatch_arms(BlockFeatures(strips=5, coaters=0, items_above_one_belt=0), _BOTH)
    assert got == ("sequence-pair",)


def test_a_large_block_goes_to_sequence_pair_whether_or_not_it_is_coated():
    for coaters in (0, 3):
        got = dispatch.dispatch_arms(
            BlockFeatures(strips=11, coaters=coaters, items_above_one_belt=0), _BOTH
        )
        assert got == ("sequence-pair",), coaters


def test_a_block_above_the_belt_capacity_branch_races_both_arms():
    got = dispatch.dispatch_arms(BlockFeatures(strips=5, coaters=2, items_above_one_belt=8), _BOTH)
    assert got == _BOTH


def test_the_exact_preparation_floor_is_inside_the_block_budget_range_or_above_it() -> None:
    # A floor below BLOCK_BUDGET_MIN_S would mean the rule can never fire and
    # the constant is dead; the measurement is what decides which side it is
    # on, so this only pins that it is a real second and not a placeholder.
    assert dispatch.SEQUENCE_PAIR_EXACT_FLOOR_S >= strategy.BLOCK_BUDGET_MIN_S


def test_a_block_bigger_than_the_evidence_covers_races_both_arms():
    got = dispatch.dispatch_arms(BlockFeatures(strips=85, coaters=0, items_above_one_belt=0), _BOTH)
    assert got == _BOTH


def test_an_explicit_single_arm_is_never_widened():
    got = dispatch.dispatch_arms(
        BlockFeatures(strips=200, coaters=0, items_above_one_belt=99), ("freeform",)
    )
    assert got == ("freeform",)


def test_a_preferred_arm_that_is_not_on_offer_races_what_is():
    """The answer is always a SUBSET of `arms`, never a name nobody offered.

    Inert against the arms shipped today -- `strategy._arms()` returns exactly
    `("freeform", "sequence-pair")` whenever it reaches here, so both names the
    rule can pick are always members.  It is the SUB-SOLVER SEAM's third arm
    that would otherwise let a block be dispatched to a solver it was never
    offered to and silently solved by sequence-pair.
    """
    others = ("sequence-pair", "block-library")
    # `coaters > 0, strips <= 6` prefers freeform, which is not on offer here.
    got = dispatch.dispatch_arms(BlockFeatures(strips=5, coaters=2, items_above_one_belt=0), others)
    assert got == others

    no_sp = ("freeform", "block-library")
    # `coaters = 0` prefers sequence-pair, which is not on offer here.
    got = dispatch.dispatch_arms(BlockFeatures(strips=5, coaters=0, items_above_one_belt=0), no_sp)
    assert got == no_sp


def test_items_above_one_belt_uses_the_fastest_tier_and_the_cargo_stack(chain_spec):
    # `lane_capacity` is `max(tier.items_per_second) * belt_stack`, the same
    # threshold `validate`'s `flow.belt_capacity` uses.
    capacity = dispatch.lane_capacity(chain_spec)
    assert capacity == Fraction(6) * chain_spec.belt_stack
    assert dispatch.block_features(chain_spec).items_above_one_belt == 0


def test_block_features_counts_the_blocks_own_spray_lanes(chain_spec):
    assert dispatch.block_features(chain_spec).coaters == len(chain_spec.spray_lanes)


def test_a_coater_free_block_below_the_exact_floor_races_both_arms() -> None:
    features = dispatch.BlockFeatures(strips=4, coaters=0, items_above_one_belt=0)
    arms = (dispatch.ARM_FREEFORM, dispatch.ARM_SEQUENCE_PAIR)

    assert (
        dispatch.dispatch_arms(features, arms, budget_s=dispatch.SEQUENCE_PAIR_EXACT_FLOOR_S - 0.1)
        == arms
    )


def test_a_coater_free_block_at_or_above_the_floor_still_goes_to_sequence_pair() -> None:
    features = dispatch.BlockFeatures(strips=4, coaters=0, items_above_one_belt=0)
    arms = (dispatch.ARM_FREEFORM, dispatch.ARM_SEQUENCE_PAIR)

    assert dispatch.dispatch_arms(
        features, arms, budget_s=dispatch.SEQUENCE_PAIR_EXACT_FLOOR_S
    ) == (dispatch.ARM_SEQUENCE_PAIR,)


def test_a_coatered_block_below_the_floor_is_unaffected() -> None:
    # The floor is about sequence-pair's exact preparation. A block the rule
    # sends to FREEFORM is not funded against that floor at all.
    features = dispatch.BlockFeatures(strips=3, coaters=2, items_above_one_belt=0)
    arms = (dispatch.ARM_FREEFORM, dispatch.ARM_SEQUENCE_PAIR)

    assert dispatch.dispatch_arms(features, arms, budget_s=1.0) == (dispatch.ARM_FREEFORM,)


def test_omitting_the_budget_keeps_the_v3_answer_exactly() -> None:
    features = dispatch.BlockFeatures(strips=4, coaters=0, items_above_one_belt=0)
    arms = (dispatch.ARM_FREEFORM, dispatch.ARM_SEQUENCE_PAIR)

    assert dispatch.dispatch_arms(features, arms) == (dispatch.ARM_SEQUENCE_PAIR,)
