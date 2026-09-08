"""Sorter queries retain row order and resolved cargo over a shared placement."""

from __future__ import annotations

import random
from dataclasses import replace

from flab2bp.dsp import catalog
from flab2bp.indexed import Sorters
from flab2bp.layout.base import PlacedBuilding, Placement
from flab2bp.layout.buildings import Buildings


def _sorter(source: int | None, destination: int | None) -> PlacedBuilding:
    item_id = min(catalog.SORTER_IDS)
    return PlacedBuilding(
        item_id=item_id,
        model_index=catalog.building(item_id).model_index,
        x=0,
        y=0,
        input_obj=source,
        output_obj=destination,
    )


def _fixture(
    seed: int, count: int
) -> tuple[Buildings, list[tuple[int, PlacedBuilding, str | None]]]:
    rng = random.Random(seed)
    items = ("iron-ingot", "copper-ingot", "gear", None)
    records = tuple(
        _sorter(
            rng.choice([None, *range(count)]),
            rng.choice([None, *range(count)]),
        )
        for _ in range(count)
    )
    return Buildings(records), [(i, b, rng.choice(items)) for i, b in enumerate(records)]


def test_drawing_from_equals_the_brute_force_filter_in_placement_order() -> None:
    buildings, rows = _fixture(seed=11, count=200)
    index = Sorters.of(buildings, rows)
    for probe in range(-1, 200):
        brute = tuple(i for i, b, _item in rows if b.input_obj == probe)
        assert index.drawing_from(probe) == brute, probe


def test_feeding_equals_the_brute_force_filter_in_placement_order() -> None:
    buildings, rows = _fixture(seed=12, count=200)
    index = Sorters.of(buildings, rows)
    for probe in range(-1, 200):
        brute = tuple(i for i, b, _item in rows if b.output_obj == probe)
        assert index.feeding(probe) == brute, probe


def test_drawing_from_carrying_equals_the_two_predicate_filter() -> None:
    buildings, rows = _fixture(seed=13, count=200)
    index = Sorters.of(buildings, rows)
    for probe in range(0, 60):
        for item in ("iron-ingot", "copper-ingot", "gear", "absent"):
            brute = tuple(i for i, b, it in rows if b.input_obj == probe and it == item)
            assert index.drawing_from_carrying(probe, item) == brute, (probe, item)


def test_feeding_carrying_equals_the_two_predicate_filter() -> None:
    buildings, rows = _fixture(seed=14, count=200)
    index = Sorters.of(buildings, rows)
    for probe in range(0, 60):
        for item in ("iron-ingot", "gear", "absent"):
            brute = tuple(i for i, b, it in rows if b.output_obj == probe and it == item)
            assert index.feeding_carrying(probe, item) == brute, (probe, item)


def test_carrying_equals_the_item_filter() -> None:
    buildings, rows = _fixture(seed=15, count=200)
    index = Sorters.of(buildings, rows)
    for item in ("iron-ingot", "copper-ingot", "gear", "absent"):
        brute = tuple(i for i, _b, it in rows if it == item)
        assert index.carrying(item) == brute, item


def test_an_empty_collection_answers_empty_rather_than_raising() -> None:
    index = Sorters.of(Buildings(()), ())
    assert index.indices() == ()
    assert index.drawing_from(0) == ()
    assert index.feeding(0) == ()
    assert index.carrying("gear") == ()
    assert index.carrying_or_unknown("gear") == ()


def test_order_and_subset_follow_rows_not_shared_link_bucket_order() -> None:
    belt_id = min(catalog.BELT_IDS)
    records = (
        _sorter(1, 2),
        PlacedBuilding(
            item_id=belt_id,
            model_index=catalog.building(belt_id).model_index,
            x=1,
            y=0,
            input_obj=1,
            output_obj=2,
        ),
        _sorter(1, 2),  # A real sorter excluded from this row collection.
        _sorter(2, 1),
        _sorter(1, 2),
        _sorter(2, 1),
    )
    rows: list[tuple[int, PlacedBuilding, str | None]] = [
        (4, records[4], None),
        (3, records[3], "gear"),
        (0, records[0], None),
        (5, records[5], "gear"),
    ]
    index = Sorters.of(Buildings(records), rows)
    assert index.indices() == (4, 3, 0, 5)
    assert index.drawing_from(1) == (4, 0)
    assert index.feeding(2) == (4, 0)
    assert index.drawing_from_carrying(2, "gear") == (3, 5)
    assert index.feeding_carrying(1, "gear") == (3, 5)
    assert index.carrying("gear") == (3, 5)
    assert index.carrying_or_unknown("gear") == (4, 3, 0, 5)
    assert index.carrying_or_unknown("absent") == (4, 0)


def test_resolved_items_override_building_annotations_without_admitting_unknowns() -> None:
    records = (
        replace(_sorter(0, 1), carries_item="copper-ingot"),
        replace(_sorter(0, 1), carries_item="gear"),
        _sorter(0, 1),
    )
    index = Sorters.of(
        Buildings(records),
        ((0, records[0], "gear"), (1, records[1], None), (2, records[2], "copper-ingot")),
    )
    assert index.drawing_from_carrying(0, "gear") == (0,)
    assert index.feeding_carrying(1, "gear") == (0,)
    assert index.carrying("copper-ingot") == (2,)
    assert index.carrying_or_unknown("gear") == (0, 1)


def test_replaced_placement_gets_new_links_without_changing_old_queries() -> None:
    placement = Placement(buildings=(_sorter(0, 1),))
    old = Sorters.of(Buildings.of(placement), ((0, placement.buildings[0], "gear"),))
    changed = replace(placement, buildings=(replace(placement.buildings[0], input_obj=2),))
    new = Sorters.of(Buildings.of(changed), ((0, changed.buildings[0], "gear"),))
    assert old.drawing_from_carrying(0, "gear") == (0,)
    assert old.drawing_from(2) == ()
    assert new.drawing_from(0) == ()
    assert new.drawing_from_carrying(2, "gear") == (0,)
