"""Geometry helpers for the spine layout.

These are the pieces where a silent error would be invisible in game: a rounding
that goes the wrong way, a circle linearised too generously, a lane placed out of
sorter reach.  Each is tested against a brute-force oracle rather than against
itself.
"""

from __future__ import annotations

import math
from fractions import Fraction

import pytest

from flab2bp.layout.geometry import (
    SCALE,
    band_offsets,
    covered_by,
    down,
    greedy_tower_xs,
    height_waste,
    lane_order,
    reach_table,
    up,
)


class TestScaling:
    """The integer boundary.  Capacity rounds down, demand rounds up."""

    def test_up_rounds_demand_upward(self) -> None:
        assert up(Fraction(1, 3)) == math.ceil(SCALE / 3)

    def test_down_rounds_capacity_downward(self) -> None:
        assert down(Fraction(1, 3)) == math.floor(SCALE / 3)

    def test_exact_values_are_unchanged_by_either(self) -> None:
        assert up(Fraction(6)) == down(Fraction(6)) == 6 * SCALE

    @pytest.mark.parametrize(
        ("num", "den", "cap_num", "cap_den", "n"),
        [
            (1, 3, 1, 7, 3),
            (22, 7, 5, 3, 2),
            (1, 1000003, 1, 999983, 1),
            (999, 1000, 1, 3, 4),
            (7, 2, 6, 5, 3),
        ],
    )
    def test_safety_lemma(self, num: int, den: int, cap_num: int, cap_den: int, n: int) -> None:
        """If the integer model accepts it, exact arithmetic must accept it too.

        This is the one place a correctness bug would be invisible in game, so it
        is asserted directly: ``n * down(cap) >= up(f)`` must imply the exact
        ``n * cap >= f``.  The converse may fail -- rejecting a marginally
        feasible layout is the safe direction.
        """
        f = Fraction(num, den)
        cap = Fraction(cap_num, cap_den)
        if n * down(cap) >= up(f):
            assert n * cap >= f

    def test_lemma_is_not_vacuous(self) -> None:
        """At least one parametrised case must actually satisfy the premise."""
        satisfied = sum(
            1
            for f, cap, n in [
                (Fraction(1, 3), Fraction(1, 7), 3),
                (Fraction(22, 7), Fraction(5, 3), 2),
                (Fraction(999, 1000), Fraction(1, 3), 4),
                (Fraction(7, 2), Fraction(6, 5), 3),
            ]
            if n * down(cap) >= up(f)
        )
        assert satisfied >= 2


class TestReachTable:
    """Linearising the supply circle at a worst-case vertical offset."""

    def test_matches_exact_circle(self) -> None:
        r = Fraction(21, 2)
        table = reach_table(r)
        for d, hr in enumerate(table):
            assert hr == math.floor(math.sqrt(max(0.0, float(r) ** 2 - d**2)))

    def test_zero_beyond_the_radius(self) -> None:
        table = reach_table(Fraction(21, 2))
        assert table[11] == 0
        assert table[10] > 0

    def test_reach_shrinks_as_vertical_offset_grows(self) -> None:
        table = reach_table(Fraction(21, 2))
        assert all(a >= b for a, b in zip(table, table[1:], strict=False))

    def test_is_not_an_inscribed_square(self) -> None:
        """An inscribed square would give R/sqrt(2) ~= 7 at dy=0; the circle gives 10."""
        assert reach_table(Fraction(21, 2))[0] == 10


class TestTowerCoverage:
    def test_greedy_covers_every_tile(self) -> None:
        for width in range(1, 60):
            for hr in (1, 3, 10):
                xs = greedy_tower_xs(x0=5, width=width, hr=hr, tower_w=1)
                tiles = [(x, 0) for x in range(5, 5 + width)]
                centres = [(x + 0.5, 0.0) for x in xs]
                assert covered_by(tiles, centres, Fraction(hr) + Fraction(1, 2)), (width, hr)

    def test_greedy_is_minimal_for_equal_reach(self) -> None:
        """Greedy interval covering on a line is optimal, so match the closed form."""
        for width in (1, 5, 20, 47):
            xs = greedy_tower_xs(x0=0, width=width, hr=3, tower_w=1)
            assert len(xs) == math.ceil(width / (2 * 3 + 1))

    def test_uncoverable_reach_raises(self) -> None:
        with pytest.raises(ValueError, match="uncoverable"):
            greedy_tower_xs(x0=0, width=10, hr=0, tower_w=1)

    def test_covered_by_uses_true_euclidean_distance(self) -> None:
        """A tile diagonally out of range must be rejected, not accepted."""
        assert not covered_by([(3, 3)], [(0.0, 0.0)], Fraction(4))
        assert covered_by([(3, 3)], [(0.0, 0.0)], Fraction(5))


class TestBandOffsets:
    def test_rows_and_corridors_do_not_overlap(self) -> None:
        rows = [4, 3, 4]
        corridors = [2, 1, 3, 1]
        row_y, corr_y, total = band_offsets(rows, corridors)
        spans = []
        for y, h in zip(corr_y, corridors, strict=True):
            spans.append((y, y + h))
        for y, h in zip(row_y, rows, strict=True):
            spans.append((y, y + h))
        spans.sort()
        for (_, end), (start, _) in zip(spans, spans[1:], strict=False):
            assert end <= start
        assert total == sum(rows) + sum(corridors)

    def test_corridor_zero_is_above_row_zero(self) -> None:
        row_y, corr_y, _ = band_offsets([3], [1, 1])
        assert corr_y[0] < row_y[0] < corr_y[1]

    def test_requires_one_more_corridor_than_rows(self) -> None:
        with pytest.raises(ValueError, match="corridor"):
            band_offsets([3, 3], [1, 1])


class TestLaneOrder:
    """Lanes tapped from a row must sit within sorter reach of it."""

    def test_all_tappable_when_corridor_is_shallow(self) -> None:
        order = lane_order(["a"], ["b"], ["c"], max_reach=3)
        assert order is not None
        assert set(order) == {"a", "b", "c"}

    def test_above_taps_go_near_the_top(self) -> None:
        order = lane_order(above=["a"], below=["b"], passthrough=[], max_reach=3)
        assert order == ["a", "b"]

    def test_passthrough_lanes_sit_in_the_middle(self) -> None:
        order = lane_order(above=["a"], below=["b"], passthrough=["p", "q"], max_reach=3)
        assert order is not None
        assert order[0] == "a"
        assert order[-1] == "b"
        assert set(order[1:-1]) == {"p", "q"}

    def test_unlimited_passthrough_is_still_feasible(self) -> None:
        order = lane_order(["a"], ["b"], [f"p{i}" for i in range(50)], max_reach=3)
        assert order is not None
        assert len(order) == 52

    def test_too_many_taps_on_one_side_is_infeasible(self) -> None:
        assert lane_order(["a", "b", "c", "d"], [], [], max_reach=3) is None

    def test_reach_bound_is_respected_for_every_tapped_lane(self) -> None:
        order = lane_order(["a", "b", "c"], ["x", "y", "z"], ["p"], max_reach=3)
        assert order is not None
        length = len(order)
        for depth, item in enumerate(order):
            if item in {"a", "b", "c"}:
                assert depth + 1 <= 3
            if item in {"x", "y", "z"}:
                assert length - depth <= 3


class TestHeightWaste:
    def test_uniform_row_wastes_nothing(self) -> None:
        assert height_waste(row_height=4, blocks=[(4, 4, 2)]) == 0

    def test_short_machines_in_a_tall_row_waste_tiles(self) -> None:
        # Two 3x3 machines in a row of height 4: one wasted tile per column.
        assert height_waste(row_height=4, blocks=[(3, 3, 2)]) == 6

    def test_matches_brute_force(self) -> None:
        blocks = [(3, 3, 2), (4, 4, 1), (2, 5, 3)]
        row_height = max(h for _, h, _ in blocks)
        expected = sum((row_height - h) * w * k for w, h, k in blocks)
        assert height_waste(row_height, blocks) == expected
