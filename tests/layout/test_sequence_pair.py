from collections.abc import Callable
from dataclasses import FrozenInstanceError
from itertools import combinations, permutations
from typing import Any, cast

import pytest

from flab2bp.layout.sequence_pair import (
    DecodedPlacement,
    GapProfile,
    PlacementProblem,
    SequencePair,
    decode_sequence_pair,
)


def _boxes(
    decoded: DecodedPlacement, sizes: tuple[tuple[int, int], ...]
) -> tuple[tuple[int, int, int, int], ...]:
    return tuple(
        (decoded.x[index], decoded.y[index], decoded.x[index] + width, decoded.y[index] + height)
        for index, (width, height) in enumerate(sizes)
    )


def _assert_no_overlap(
    decoded: DecodedPlacement, sizes: tuple[tuple[int, int], ...]
) -> None:
    boxes = _boxes(decoded, sizes)
    for first, second in combinations(range(len(sizes)), 2):
        ax0, ay0, ax1, ay1 = boxes[first]
        bx0, by0, bx1, by1 = boxes[second]
        assert ax1 <= bx0 or bx1 <= ax0 or ay1 <= by0 or by1 <= ay0


def test_sequence_pair_relations_decode_to_expected_axes() -> None:
    pair = SequencePair(positive=(0, 1, 2), negative=(0, 2, 1))
    decoded = decode_sequence_pair(
        pair, GapProfile.zero(3), ((3, 2), (4, 2), (2, 3)), outline_height=10
    )
    assert decoded.x[1] >= decoded.x[0] + 3
    assert decoded.y[1] >= decoded.y[2] + 3


def test_all_four_sequence_pair_relations_use_the_expected_direction() -> None:
    sizes = ((3, 2), (4, 5))
    expected: dict[
        tuple[tuple[int, int], tuple[int, int]], Callable[[DecodedPlacement], bool]
    ] = {
        ((0, 1), (0, 1)): lambda decoded: decoded.x[1] >= decoded.x[0] + 3,
        ((1, 0), (1, 0)): lambda decoded: decoded.x[0] >= decoded.x[1] + 4,
        ((0, 1), (1, 0)): lambda decoded: decoded.y[0] >= decoded.y[1] + 5,
        ((1, 0), (0, 1)): lambda decoded: decoded.y[1] >= decoded.y[0] + 2,
    }
    for (positive, negative), relation_holds in expected.items():
        decoded = decode_sequence_pair(
            SequencePair(positive, negative),
            GapProfile.zero(2),
            sizes,
            outline_height=7,
        )
        assert relation_holds(decoded)


def test_gap_profile_adds_explicit_channel_space() -> None:
    pair = SequencePair(positive=(0, 1), negative=(0, 1))
    plain = decode_sequence_pair(
        pair, GapProfile.zero(2), ((3, 2), (4, 2)), outline_height=6
    )
    gapped = decode_sequence_pair(
        pair,
        GapProfile(east=(2, 0), north=(0, 0)),
        ((3, 2), (4, 2)),
        outline_height=6,
    )
    assert gapped.x[1] == plain.x[1] + 2
    assert gapped.gap_area == 4


def test_north_gap_is_added_to_outgoing_vertical_constraints() -> None:
    pair = SequencePair(positive=(0, 1), negative=(1, 0))
    plain = decode_sequence_pair(
        pair, GapProfile.zero(2), ((3, 2), (4, 3)), outline_height=8
    )
    gapped = decode_sequence_pair(
        pair,
        GapProfile(east=(0, 0), north=(0, 2)),
        ((3, 2), (4, 3)),
        outline_height=8,
    )
    assert gapped.y[0] == plain.y[0] + 2
    assert gapped.gap_area == 8


def test_decoded_rectangles_never_overlap() -> None:
    sizes = ((3, 2), (4, 3), (2, 5), (1, 4))
    for positive in permutations(range(4)):
        for negative in permutations(range(4)):
            decoded = decode_sequence_pair(
                SequencePair(positive, negative),
                GapProfile.zero(4),
                sizes,
                outline_height=sum(height for _width, height in sizes),
            )
            _assert_no_overlap(decoded, sizes)


def test_coordinate_windows_use_forward_earliest_and_reverse_latest_paths() -> None:
    horizontal = decode_sequence_pair(
        SequencePair((0, 1), (0, 1)),
        GapProfile.zero(2),
        ((3, 2), (4, 2)),
        outline_height=6,
        outline_width=10,
    )
    assert horizontal.x == (0, 3)
    assert horizontal.x_windows == ((0, 3), (3, 6))
    assert horizontal.y_windows == ((0, 4), (0, 4))

    vertical = decode_sequence_pair(
        SequencePair((0, 1), (1, 0)),
        GapProfile.zero(2),
        ((3, 2), (4, 2)),
        outline_height=6,
    )
    assert vertical.y == (2, 0)
    assert vertical.y_windows == ((2, 4), (0, 2))


def test_default_outline_width_is_the_compacted_width() -> None:
    decoded = decode_sequence_pair(
        SequencePair((0, 1), (0, 1)),
        GapProfile.zero(2),
        ((3, 2), (4, 2)),
        outline_height=6,
    )
    assert decoded.width == 7
    assert decoded.x_windows == ((0, 0), (3, 3))


def test_outline_overflow_returns_infeasible_windows_for_scoring() -> None:
    decoded = decode_sequence_pair(
        SequencePair((0, 1), (1, 0)),
        GapProfile.zero(2),
        ((3, 2), (4, 2)),
        outline_height=3,
    )
    assert decoded.used_height == 4
    assert decoded.y_windows == ((2, 1), (0, -1))


def test_generated_cases_are_deterministic_legal_and_integer_only() -> None:
    for size in range(1, 8):
        sizes = tuple((1 + index % 4, 1 + (index * 3) % 5) for index in range(size))
        identity = tuple(range(size))
        generated = {
            (
                identity[offset:] + identity[:offset],
                tuple(reversed(identity[:offset])) + tuple(reversed(identity[offset:])),
            )
            for offset in range(size)
        }
        generated.update(
            (positive, tuple(reversed(negative))) for positive, negative in tuple(generated)
        )
        gaps = GapProfile(
            east=tuple(index % 5 for index in range(size)),
            north=tuple((index * 2) % 5 for index in range(size)),
        )
        outline_height = sum(
            height + gaps.north[index]
            for index, (_width, height) in enumerate(sizes)
        )
        for positive, negative in sorted(generated):
            pair = SequencePair(positive, negative)
            first = decode_sequence_pair(pair, gaps, sizes, outline_height=outline_height)
            second = decode_sequence_pair(pair, gaps, sizes, outline_height=outline_height)
            assert first == second
            assert all(type(coordinate) is int for coordinate in first.x + first.y)
            _assert_no_overlap(first, sizes)


def test_sequence_pair_and_gap_profile_are_validated_and_immutable() -> None:
    pair = SequencePair((0, 1), (1, 0))
    gaps = GapProfile.zero(2)
    with pytest.raises(FrozenInstanceError):
        pair.positive = (1, 0)  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        gaps.east = (1, 0)  # type: ignore[misc]

    for positive, negative in (
        ((0, 0), (0, 1)),
        ((0, 1), (0, 2)),
        ((0,), (0, 1)),
        ((0, "1"), (0, 1)),
    ):
        with pytest.raises(ValueError, match="every strip exactly once"):
            SequencePair(positive, negative)  # type: ignore[arg-type]

    for east, north in (((-1,), (0,)), ((5,), (0,)), ((0,), (0, 1)), ((1.0,), (0,))):
        with pytest.raises(ValueError, match="gap"):
            GapProfile(east, north)  # type: ignore[arg-type]


def test_decode_rejects_structurally_invalid_input() -> None:
    pair = SequencePair((0,), (0,))
    gaps = GapProfile.zero(1)
    floating_sizes = cast(tuple[tuple[int, int], ...], ((1.0, 1),))
    invalid_calls: tuple[Callable[[], DecodedPlacement], ...] = (
        lambda: decode_sequence_pair(pair, GapProfile.zero(2), ((1, 1),), outline_height=1),
        lambda: decode_sequence_pair(pair, gaps, (), outline_height=1),
        lambda: decode_sequence_pair(pair, gaps, ((0, 1),), outline_height=1),
        lambda: decode_sequence_pair(pair, gaps, floating_sizes, outline_height=1),
        lambda: decode_sequence_pair(pair, gaps, ((1, 1),), outline_height=0),
        lambda: decode_sequence_pair(pair, gaps, ((1, 1),), outline_height=1, outline_width=0),
    )
    for call in invalid_calls:
        with pytest.raises(ValueError):
            call()


def test_placement_problem_validates_geometry_nets_and_bounds() -> None:
    problem = PlacementProblem(
        sizes=((3, 2), (4, 3)),
        nets=((0, 1),),
        outline_height=5,
        area_lower_bound=18,
    )
    assert problem.size == 2
    with pytest.raises(FrozenInstanceError):
        problem.outline_height = 6  # type: ignore[misc]

    invalid_kwargs: tuple[dict[str, Any], ...] = (
        {"sizes": ((0, 2),), "nets": (), "outline_height": 2, "area_lower_bound": 0},
        {"sizes": ((1, 2),), "nets": ((0, 1),), "outline_height": 2, "area_lower_bound": 2},
        {"sizes": ((1, 2),), "nets": (), "outline_height": 0, "area_lower_bound": 2},
        {"sizes": ((1, 2),), "nets": (), "outline_height": 2, "area_lower_bound": -1},
    )
    for kwargs in invalid_kwargs:
        with pytest.raises(ValueError):
            PlacementProblem(**kwargs)
