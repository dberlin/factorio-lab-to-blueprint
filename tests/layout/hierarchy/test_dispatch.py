"""The arm-choice rule, read off `2026-09-06-exp-features`.

Every threshold here is that evidence's; nothing is tuned locally.  The
cross-tab it implements is README §4(b) item 3.
"""

from __future__ import annotations

from fractions import Fraction

from flab2bp.layout.hierarchy import dispatch
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


def test_a_block_bigger_than_the_evidence_covers_races_both_arms():
    got = dispatch.dispatch_arms(BlockFeatures(strips=85, coaters=0, items_above_one_belt=0), _BOTH)
    assert got == _BOTH


def test_an_explicit_single_arm_is_never_widened():
    got = dispatch.dispatch_arms(
        BlockFeatures(strips=200, coaters=0, items_above_one_belt=99), ("freeform",)
    )
    assert got == ("freeform",)


def test_items_above_one_belt_uses_the_fastest_tier_and_the_cargo_stack(chain_spec):
    # `lane_capacity` is `max(tier.items_per_second) * belt_stack`, the same
    # threshold `validate`'s `flow.belt_capacity` uses.
    capacity = dispatch.lane_capacity(chain_spec)
    assert capacity == Fraction(6) * chain_spec.belt_stack
    assert dispatch.block_features(chain_spec).items_above_one_belt == 0


def test_block_features_counts_the_blocks_own_spray_lanes(chain_spec):
    assert dispatch.block_features(chain_spec).coaters == len(chain_spec.spray_lanes)
