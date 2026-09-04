"""Behavioral tests for piler merge planning."""

from __future__ import annotations

from fractions import Fraction

from flab2bp.layout.piling import LaneLoad, MergePlan, PilerPlan, plan_merges


def _load(i: int, demand: int, stack: int = 1) -> LaneLoad:
    return LaneLoad(
        lane_id=f"lane-{i}",
        strip_ordinal=i,
        demand=Fraction(demand),
        stack=stack,
    )


def _plan(loads: list[LaneLoad], *, sink_pick_stack: int = 4) -> MergePlan:
    return plan_merges(
        loads,
        lane_capacity=Fraction(30),
        max_stack=4,
        sink_pick_stack=sink_pick_stack,
    )


def test_four_full_lanes_pile_to_four_through_two_pilers_each() -> None:
    # A piler doubles: 1 -> 2 -> 4, so an unstacked lane needs two in series.
    plan = _plan([_load(i, 30) for i in range(4)])

    assert plan == MergePlan(
        stack=4,
        groups=(("lane-0", "lane-1", "lane-2", "lane-3"),),
        pilers=tuple(PilerPlan(f"lane-{i}", count=2, stack=4) for i in range(4)),
    )
    assert sum(piler.count for piler in plan.pilers) == 8


def test_two_twenties_pile_to_the_smallest_stack_that_fits() -> None:
    plan = _plan([_load(0, 20), _load(1, 20)], sink_pick_stack=2)

    assert plan == MergePlan(
        stack=2,
        groups=(("lane-0", "lane-1"),),
        pilers=(
            PilerPlan("lane-0", count=1, stack=2),
            PilerPlan("lane-1", count=1, stack=2),
        ),
    )


def test_a_lane_that_starts_stacked_needs_one_piler_where_an_unstacked_one_needs_two() -> None:
    plan = _plan(
        [
            _load(0, 30, stack=2),
            _load(1, 30),
            _load(2, 30),
            _load(3, 30),
        ]
    )

    assert plan == MergePlan(
        stack=4,
        groups=(("lane-0", "lane-1", "lane-2", "lane-3"),),
        pilers=(
            PilerPlan("lane-0", count=1, stack=4),
            PilerPlan("lane-1", count=2, stack=4),
            PilerPlan("lane-2", count=2, stack=4),
            PilerPlan("lane-3", count=2, stack=4),
        ),
    )


def test_a_lane_at_stack_three_reaches_four_in_one_piler() -> None:
    # A level-3 Pile Sorter places 3; 2 x 3 caps at the maximum stack.
    plan = _plan([_load(0, 40, stack=3), _load(1, 40, stack=3)])

    assert plan == MergePlan(
        stack=4,
        groups=(("lane-0", "lane-1"),),
        pilers=(
            PilerPlan("lane-0", count=1, stack=4),
            PilerPlan("lane-1", count=1, stack=4),
        ),
    )


def test_lanes_that_already_fit_share_a_belt_without_a_piler() -> None:
    plan = _plan([_load(0, 10), _load(1, 10)], sink_pick_stack=1)

    assert plan == MergePlan(
        stack=1,
        groups=(("lane-0", "lane-1"),),
        pilers=(),
    )


def test_a_lane_already_above_the_uniform_stack_keeps_it_and_gets_no_piler() -> None:
    plan = _plan([_load(0, 20, stack=4), _load(1, 20)], sink_pick_stack=4)

    assert plan == MergePlan(
        stack=2,
        groups=(("lane-0", "lane-1"),),
        pilers=(PilerPlan("lane-1", count=1, stack=2),),
    )


def test_a_flow_stack_four_cannot_absorb_is_grouped_by_ordinal() -> None:
    plan = _plan([_load(i, 30) for i in range(5)])

    assert plan == MergePlan(
        stack=4,
        groups=(
            ("lane-0", "lane-1", "lane-2", "lane-3"),
            ("lane-4",),
        ),
        pilers=tuple(PilerPlan(f"lane-{i}", count=2, stack=4) for i in range(5)),
    )
    assert sum(piler.count for piler in plan.pilers) == 10


def test_the_sink_pick_stack_caps_the_stack_and_forces_parallel_belts() -> None:
    plan = _plan([_load(0, 30), _load(1, 30)], sink_pick_stack=1)

    assert plan == MergePlan(
        stack=1,
        groups=(("lane-0",), ("lane-1",)),
        pilers=(),
    )


def test_a_sink_that_picks_three_is_planned_at_two_because_a_piler_cannot_land_on_three() -> None:
    # The limit is 3, but the doubling ladder offers only 1 and 2 below it.
    plan = _plan([_load(0, 30), _load(1, 20)], sink_pick_stack=3)

    assert plan == MergePlan(
        stack=2,
        groups=(("lane-0", "lane-1"),),
        pilers=(
            PilerPlan("lane-0", count=1, stack=2),
            PilerPlan("lane-1", count=1, stack=2),
        ),
    )


def test_the_plan_is_deterministic_across_input_order() -> None:
    loads = [_load(2, 30), _load(0, 20), _load(1, 25)]
    by_ordinal = sorted(loads, key=_ordinal)
    expected = MergePlan(
        stack=4,
        groups=(("lane-0", "lane-1", "lane-2"),),
        pilers=(
            PilerPlan("lane-0", count=2, stack=4),
            PilerPlan("lane-1", count=2, stack=4),
            PilerPlan("lane-2", count=2, stack=4),
        ),
    )

    assert _plan(loads) == expected
    assert _plan(by_ordinal) == expected


def _ordinal(load: LaneLoad) -> int:
    return load.strip_ordinal
