"""Every `Sorters` answer equals the brute-force scan it replaces.

The scan being replaced is validate.py's `_belt_reaches_any` (real source read
at HEAD, ~4608-4627): `for sorter_index, sorter in ctx.of_kind(Kind.SORTER) if
sorter.input_obj == index`, run once per BFS step. The proof obligation is
equality with that filter, including order, because the caller extends a BFS
frontier with the result and a different order is a different traversal.

`ctx.of_kind` (`Context.of_kind`, `layout/validate.py:391-404`) always hands
its rows to `Sorters.of` already in placement order (ascending building
index, via `enumerate(self.placement.buildings)`), so every fixture below
builds rows the same way. One extra test
(`test_order_follows_the_rows_given_not_littletable_internals`) inserts rows
out of index order on purpose, to prove the accessors follow the order `rows`
was given in rather than littletable's own by-key bucket order or a sort by
the numeric index -- measured directly against a live littletable table,
`by.field[value]` returns records in TABLE INSERTION order, which happens to
equal ascending index order in every other fixture here only because those
fixtures insert ascending. That coincidence is exactly what this test does
not rely on.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import cast

from flab2bp.indexed import Sorters
from flab2bp.layout.base import PlacedBuilding


@dataclass(frozen=True, slots=True)
class _FakeBuilding:
    """Stands in for `PlacedBuilding`: slotted and frozen, exactly as it is.

    Cast to `PlacedBuilding` at every call site below: `Sorters` only ever
    reads `.input_obj`/`.output_obj` off what it is given, so the stand-in is
    behaviorally exact, but it is not `PlacedBuilding` itself (deliberately --
    building one for real drags in the DSP catalog for no reason a sorter
    index needs), and `mypy --strict` holds `Sorters.of`'s real, nominal
    signature over this file same as anywhere else.
    """

    input_obj: int | None
    output_obj: int | None


def _fixture(seed: int, count: int) -> list[tuple[int, PlacedBuilding, str | None]]:
    rng = random.Random(seed)
    items = ("iron-ingot", "copper-ingot", "gear", None)
    return [
        (
            i,
            cast(
                PlacedBuilding,
                _FakeBuilding(
                    input_obj=rng.choice([None, *range(count)]),
                    output_obj=rng.choice([None, *range(count)]),
                ),
            ),
            rng.choice(items),
        )
        for i in range(count)
    ]


def test_drawing_from_equals_the_brute_force_filter_in_placement_order() -> None:
    rows = _fixture(seed=11, count=200)
    index = Sorters.of(rows)
    for probe in range(-1, 200):
        brute = tuple(i for i, b, _item in rows if b.input_obj == probe)
        assert index.drawing_from(probe) == brute, probe


def test_feeding_equals_the_brute_force_filter_in_placement_order() -> None:
    rows = _fixture(seed=12, count=200)
    index = Sorters.of(rows)
    for probe in range(-1, 200):
        brute = tuple(i for i, b, _item in rows if b.output_obj == probe)
        assert index.feeding(probe) == brute, probe


def test_drawing_from_carrying_equals_the_two_predicate_filter() -> None:
    rows = _fixture(seed=13, count=200)
    index = Sorters.of(rows)
    for probe in range(0, 60):
        for item in ("iron-ingot", "copper-ingot", "gear", "absent"):
            brute = tuple(i for i, b, it in rows if b.input_obj == probe and it == item)
            assert index.drawing_from_carrying(probe, item) == brute, (probe, item)


def test_feeding_carrying_equals_the_two_predicate_filter() -> None:
    rows = _fixture(seed=14, count=200)
    index = Sorters.of(rows)
    for probe in range(0, 60):
        for item in ("iron-ingot", "gear", "absent"):
            brute = tuple(i for i, b, it in rows if b.output_obj == probe and it == item)
            assert index.feeding_carrying(probe, item) == brute, (probe, item)


def test_carrying_equals_the_item_filter() -> None:
    rows = _fixture(seed=15, count=200)
    index = Sorters.of(rows)
    for item in ("iron-ingot", "copper-ingot", "gear", "absent"):
        brute = tuple(i for i, _b, it in rows if it == item)
        assert index.carrying(item) == brute, item


def test_a_none_item_is_never_returned_by_carrying() -> None:
    rows = _fixture(seed=16, count=80)
    index = Sorters.of(rows)
    assert all(index.item(i) is not None for i in index.carrying("gear"))


def test_building_and_item_hand_back_the_payload_unchanged() -> None:
    rows = _fixture(seed=17, count=40)
    index = Sorters.of(rows)
    for i, building, item in rows:
        assert index.building(i) is building
        assert index.item(i) == item


def test_an_empty_collection_answers_empty_rather_than_raising() -> None:
    index = Sorters.of(())
    assert index.indices() == ()
    assert index.drawing_from(0) == ()
    assert index.carrying("gear") == ()


def test_order_follows_the_rows_given_not_littletable_internals() -> None:
    """Rows arrive out of index order; the answer must still match that order.

    Every fixture above builds `rows` with `i` ascending, so none of them can
    tell "return the order `rows` was given" apart from "return littletable's
    own `by.field[value]` order" or "sort by the numeric index" -- a direct
    probe of littletable (`table.by.input_obj[value]` after inserting shuffled
    rows) shows it returns records in TABLE INSERTION order, which for every
    fixture above happens to equal ascending index order because insertion
    order equals `rows` order equals ascending index order there. This test
    breaks that three-way coincidence: `rows` is handed in an order that is
    neither ascending nor descending by index, so an implementation that
    quietly sorted by the numeric `index` field, or that returned
    `by.field[value]` raw and got lucky, would answer wrong here.
    """
    rows = [
        (30, cast(PlacedBuilding, _FakeBuilding(input_obj=1, output_obj=None)), None),
        (5, cast(PlacedBuilding, _FakeBuilding(input_obj=1, output_obj=None)), None),
        (100, cast(PlacedBuilding, _FakeBuilding(input_obj=2, output_obj=None)), "gear"),
        (17, cast(PlacedBuilding, _FakeBuilding(input_obj=1, output_obj=None)), None),
        (2, cast(PlacedBuilding, _FakeBuilding(input_obj=2, output_obj=None)), "gear"),
    ]
    index = Sorters.of(rows)
    assert index.indices() == (30, 5, 100, 17, 2)
    assert index.drawing_from(1) == (30, 5, 17)
    assert index.drawing_from_carrying(2, "gear") == (100, 2)
    assert index.carrying("gear") == (100, 2)
