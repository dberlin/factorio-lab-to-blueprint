"""One grid per previews value, shared by both rules that ask.

Deviation from this task's brief and from controller ruling P-8's own
suggested fallback -- see `src/flab2bp/indexed/belt_overlap.py`'s module
docstring for the full account. `BeltOverlap` is a geometry-agnostic bucket
grid over pre-computed cells, keyed on the VALUE of the caller's key (not its
identity), because `dsp/colliders.py`'s real callers never hand the two
belt-collision rules the identical `previews` object.
"""

from __future__ import annotations

from flab2bp.indexed import BeltOverlap


def _cells_by_index() -> tuple[tuple[tuple[int, int], ...], ...]:
    """Item 0 spans four cells; item 1 shares one of them; item 2 is alone."""
    return (
        ((0, 0), (0, 1), (1, 0), (1, 1)),
        ((1, 1), (2, 2)),
        ((9, 9),),
    )


def test_candidates_returns_every_item_registered_at_one_cell() -> None:
    index = BeltOverlap.of(_cells_by_index())
    assert index.candidates((0, 0)) == (0,)
    assert index.candidates((1, 1)) == (0, 1)
    assert index.candidates((2, 2)) == (1,)
    assert index.candidates((9, 9)) == (2,)


def test_an_unregistered_cell_answers_empty() -> None:
    index = BeltOverlap.of(_cells_by_index())
    assert index.candidates((50, 50)) == ()


def test_an_empty_item_list_answers_empty() -> None:
    assert BeltOverlap.of(()).candidates((0, 0)) == ()


def test_duplicate_registration_at_one_cell_is_deduplicated_in_first_seen_order() -> None:
    """Two boxes belonging to the same item can register the same cell --
    `dict.fromkeys(grid.get(key, ()))` in the real source removes the repeat
    without disturbing which item was seen first."""
    index = BeltOverlap.of([((0, 0), (0, 0)), ((0, 0),)])
    assert index.candidates((0, 0)) == (0, 1)


def test_for_previews_returns_the_same_index_for_an_equal_but_different_tuple() -> None:
    """The real defect: `layout/validate.py`'s `_paste_previews(ctx)` builds a
    NEW tuple on every call, so two calls with equal content are never the
    same object. `for_previews` must still share one index between them."""
    BeltOverlap.clear_cache()
    builds = 0

    def counting_cells_of(_previews: object) -> tuple[tuple[tuple[int, int], ...], ...]:
        nonlocal builds
        builds += 1
        return _cells_by_index()

    first = BeltOverlap.for_previews(("a", "b"), counting_cells_of)
    second = BeltOverlap.for_previews(("a", "b"), counting_cells_of)
    assert first is second
    assert builds == 1


def test_a_different_previews_value_gets_its_own_index() -> None:
    BeltOverlap.clear_cache()
    first = BeltOverlap.for_previews(("a",), lambda _p: _cells_by_index())
    second = BeltOverlap.for_previews(("b",), lambda _p: _cells_by_index())
    assert first is not second


def test_an_unhashable_previews_value_still_works_without_caching() -> None:
    """`tests/dsp/test_colliders.py` calls `_belt_overlap_candidates` with a
    plain `list` of previews directly; that must never raise."""
    BeltOverlap.clear_cache()
    index = BeltOverlap.for_previews(["a", "b"], lambda _p: _cells_by_index())
    assert index.candidates((0, 0)) == (0,)
