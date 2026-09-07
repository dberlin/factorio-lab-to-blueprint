"""Position lookups equal `tuple.index`, which is the scan being replaced.

`apply_move`'s SWAP_BOTH does `negative.index(first_strip)` and
`negative.index(second_strip)` (sequence_pair.py:1479-1480) once per move inside
`anneal_stage`'s per-move loop (sequence_pair.py:1656) -- two O(N) scans on the
hottest Python loop in the solver. `swapped()` in
`_projection_feedback_stage_update` (sequence_solver.py:3489-3491) does the same
thing up to 32 times per call, and `merge_stage_boundary`
(sequence_pair.py:1902-1905) and `transform_stage` (sequence_solver.py:5646) do
it once each.
"""

from __future__ import annotations

import random

import pytest

from flab2bp.indexed import StripPositions


def test_position_of_equals_tuple_index_for_every_strip() -> None:
    rng = random.Random(41)
    for size in (1, 2, 5, 30, 200):
        permutation = list(range(size))
        rng.shuffle(permutation)
        as_tuple = tuple(permutation)
        index = StripPositions.of(as_tuple)
        for strip in as_tuple:
            assert index.position_of(strip) == as_tuple.index(strip), (size, strip)


def test_positions_of_equals_two_tuple_index_calls() -> None:
    rng = random.Random(42)
    permutation = list(range(64))
    rng.shuffle(permutation)
    as_tuple = tuple(permutation)
    index = StripPositions.of(as_tuple)
    for _ in range(200):
        first, second = rng.sample(as_tuple, 2)
        assert index.positions_of(first, second) == (
            as_tuple.index(first),
            as_tuple.index(second),
        )


def test_strip_at_is_the_inverse_of_position_of() -> None:
    index = StripPositions.of((3, 0, 2, 1))
    for position in range(4):
        assert index.position_of(index.strip_at(position)) == position


def test_an_absent_strip_raises_the_same_shape_of_error_as_index() -> None:
    index = StripPositions.of((0, 1, 2))
    with pytest.raises(KeyError):
        index.position_of(9)


def test_an_empty_permutation_is_legal_and_empty() -> None:
    index = StripPositions.of(())
    assert len(index) == 0
