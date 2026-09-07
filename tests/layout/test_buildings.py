"""``Buildings`` answers from an index exactly what a brute-force scan answers."""

from __future__ import annotations

from fractions import Fraction

from flab2bp.dsp import catalog
from flab2bp.layout.base import PlacedBuilding
from flab2bp.layout.buildings import Buildings, Kind


def _fixture() -> tuple[PlacedBuilding, ...]:
    """A spread with every kind, repeated keys, ``None`` links and shared tiles."""
    belt = next(iter(catalog.BELT_IDS))
    sorter = next(iter(catalog.SORTER_IDS))
    records: list[PlacedBuilding] = []
    for i in range(60):
        if i % 3 == 0:
            records.append(
                PlacedBuilding(
                    item_id=2303,
                    model_index=0,
                    x=i,
                    y=0,
                    width=3,
                    height=3,
                    recipe_id=i % 4,
                    owner_strip=i % 5,
                )
            )
        elif i % 3 == 1:
            records.append(
                PlacedBuilding(
                    item_id=belt,
                    model_index=0,
                    x=i,
                    y=1,
                    output_obj=i + 2 if i + 2 < 60 else None,
                    carries_item=f"item-{i % 7}",
                )
            )
        else:
            records.append(
                PlacedBuilding(
                    item_id=sorter,
                    model_index=0,
                    x=i,
                    y=2,
                    input_obj=i - 1,
                    output_obj=(i + 1) % 60,
                    carries_item=f"item-{i % 7}",
                )
            )
    return tuple(records)


def test_by_item_matches_a_brute_force_scan() -> None:
    records = _fixture()
    index = Buildings(records)
    for item_id in {b.item_id for b in records}:
        expected = tuple(i for i, b in enumerate(records) if b.item_id == item_id)
        assert index.by_item(item_id) == expected


def test_machines_for_recipe_matches_a_brute_force_scan() -> None:
    records = _fixture()
    index = Buildings(records)
    for recipe_id in {b.recipe_id for b in records}:
        expected = tuple(
            i
            for i, b in enumerate(records)
            if b.recipe_id == recipe_id
            and not catalog.is_belt(b.item_id)
            and not catalog.is_sorter(b.item_id)
        )
        assert index.machines_for_recipe(recipe_id) == expected


def test_link_indexes_match_a_brute_force_scan() -> None:
    records = _fixture()
    index = Buildings(records)
    for target in range(len(records)):
        assert index.by_output_obj(target) == tuple(
            i for i, b in enumerate(records) if b.output_obj == target
        )
        assert index.by_input_obj(target) == tuple(
            i for i, b in enumerate(records) if b.input_obj == target
        )
        assert index.sorters_into(target) == tuple(
            i
            for i, b in enumerate(records)
            if catalog.is_sorter(b.item_id) and b.output_obj == target
        )
        assert index.sorters_out_of(target) == tuple(
            i
            for i, b in enumerate(records)
            if catalog.is_sorter(b.item_id) and b.input_obj == target
        )


def test_missing_keys_answer_empty_not_raise() -> None:
    index = Buildings(_fixture())
    assert index.by_item(999_999) == ()
    assert index.machines_for_recipe(999_999) == ()
    assert index.by_output_obj(999_999) == ()
    assert index.by_index(999_999) is None
    assert index.by_index(None) is None
    assert index.by_index(-1) is None


def test_empty_sequence_is_answerable() -> None:
    index = Buildings(())
    assert len(index) == 0
    assert index.belts() == ()
    assert index.bounds() == (0, 0, 0, 0)


def test_kind_of_and_by_kind_match_the_catalog_classification() -> None:
    """Closes the gap: nothing above exercises ``kind_of``/``by_kind`` directly.

    A record is OTHER exactly when it is a splitter or a piler; MACHINE
    otherwise (the fixture's "every third" branch uses item 2303, an ordinary
    machine id that is neither a belt nor a sorter).
    """
    records = _fixture()
    index = Buildings(records)

    def expected_kind(b: PlacedBuilding) -> Kind:
        if catalog.is_belt(b.item_id):
            return Kind.BELT
        if catalog.is_sorter(b.item_id):
            return Kind.SORTER
        if b.item_id in (catalog.SPLITTER_ID, catalog.PILER_ID):
            return Kind.OTHER
        return Kind.MACHINE

    for i, b in enumerate(records):
        assert index.kind_of(i) == expected_kind(b)

    for kind in Kind:
        expected = tuple(i for i, b in enumerate(records) if expected_kind(b) == kind)
        assert index.by_kind(kind) == expected


def test_bounds_matches_a_brute_force_scan_on_a_real_blueprint() -> None:
    from pathlib import Path

    from flab2bp.dsp.codec import decode

    fixture = Path(__file__).parent.parent / "fixtures" / "factory-heretical-smelter-block.txt"
    decoded = decode(fixture.read_text())
    records = tuple(
        PlacedBuilding(
            item_id=b.item_id,
            model_index=b.model_index,
            x=int(b.x),
            y=int(b.y),
            recipe_id=b.recipe_id,
            output_obj=b.output_obj_idx if b.output_obj_idx >= 0 else None,
            input_obj=b.input_obj_idx if b.input_obj_idx >= 0 else None,
        )
        for b in decoded.buildings
    )
    index = Buildings(records)
    xs = [b.x for b in records] + [b.x + b.width - 1 for b in records]
    ys = [b.y for b in records] + [b.y + b.height - 1 for b in records]
    assert index.bounds() == (min(xs), min(ys), max(xs), max(ys))
    for item_id in {b.item_id for b in records}:
        assert index.by_item(item_id) == tuple(
            i for i, b in enumerate(records) if b.item_id == item_id
        )


def test_at_tile_and_in_box_match_a_brute_force_scan() -> None:
    records = _fixture()
    index = Buildings(records)

    def covers(b: PlacedBuilding, x: int, y: int) -> bool:
        return b.x <= x < b.x + b.width and b.y <= y < b.y + b.height

    for x in range(-2, 64):
        for y in range(-2, 5):
            assert index.at_tile(x, y) == tuple(i for i, b in enumerate(records) if covers(b, x, y))
    assert index.in_box(0, 0, 10, 3) == tuple(
        i
        for i, b in enumerate(records)
        if any(covers(b, x, y) for x in range(0, 11) for y in range(0, 4))
    )


def test_sorters_between_drives_off_the_smaller_set() -> None:
    records = _fixture()
    index = Buildings(records)
    sources = {i for i in range(0, 60, 3)}
    sinks = {i for i in range(1, 60, 3)}
    assert index.sorters_between(sources, sinks) == tuple(
        i
        for i, b in enumerate(records)
        if catalog.is_sorter(b.item_id) and b.input_obj in sources and b.output_obj in sinks
    )


def test_at_tile_honours_z_when_given() -> None:
    records = (
        PlacedBuilding(item_id=2303, model_index=0, x=0, y=0, z=Fraction(0)),
        PlacedBuilding(item_id=2303, model_index=0, x=0, y=0, z=Fraction(1, 2)),
    )
    index = Buildings(records)
    assert index.at_tile(0, 0) == (0, 1)
    assert index.at_tile(0, 0, Fraction(0)) == (0,)
    assert index.at_tile(0, 0, Fraction(1, 2)) == (1,)
    assert index.at_tile(0, 0, Fraction(3, 2)) == ()
