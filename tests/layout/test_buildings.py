"""``Buildings`` answers from an index exactly what a brute-force scan answers."""

from __future__ import annotations

from dataclasses import replace
from fractions import Fraction

import pytest

from flab2bp.dsp import catalog
from flab2bp.layout.base import PlacedBuilding
from flab2bp.layout.buildings import Buildings, Kind, MutableBuildings, kind_for


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


def _expected_kind(b: PlacedBuilding) -> Kind:
    """The classification every kind assertion below is measured against."""
    if catalog.is_belt(b.item_id):
        return Kind.BELT
    if catalog.is_sorter(b.item_id):
        return Kind.SORTER
    if b.item_id in (catalog.SPLITTER_ID, catalog.PILER_ID):
        return Kind.OTHER
    return Kind.MACHINE


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
            if b.recipe_id == recipe_id and _expected_kind(b) is Kind.MACHINE
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

    ``_fixture()`` never produces ``Kind.OTHER`` (no splitter or piler record),
    so this only pins BELT/SORTER/MACHINE; see
    ``test_by_kind_other_and_machines_for_recipe_exclude_splitters_and_pilers``
    below for the OTHER branch, which needs its own local records.
    """
    records = _fixture()
    index = Buildings(records)

    for i, b in enumerate(records):
        assert index.kind_of(i) == _expected_kind(b)

    for kind in Kind:
        expected = tuple(i for i, b in enumerate(records) if _expected_kind(b) == kind)
        assert index.by_kind(kind) == expected


def test_by_kind_other_and_machines_for_recipe_exclude_splitters_and_pilers() -> None:
    """Local records, not the shared ``_fixture()`` -- Task 2 reuses that one.

    Pins a divergence a coincidentally-passing brute-force oracle used to
    hide: a splitter's or piler's ``recipe_id`` is 0 only because that is the
    field's default, not because it runs a recipe, so ``machines_for_recipe``
    must not return one just because ``recipe_id`` happens to match.
    """
    records = (
        PlacedBuilding(item_id=2303, model_index=0, x=0, y=0, recipe_id=0),
        PlacedBuilding(item_id=catalog.SPLITTER_ID, model_index=0, x=1, y=0),
        PlacedBuilding(item_id=catalog.PILER_ID, model_index=0, x=2, y=0),
    )
    index = Buildings(records)
    assert index.kind_of(0) is Kind.MACHINE
    assert index.kind_of(1) is Kind.OTHER
    assert index.kind_of(2) is Kind.OTHER
    assert index.by_kind(Kind.OTHER) == (1, 2)
    assert index.splitters() == (1,)
    assert index.machines() == (0,)
    assert index.machines_for_recipe(0) == (0,)


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


def test_sorters_between_matches_brute_force_with_differing_set_sizes_and_overlap() -> None:
    """Exercises both branches of the smaller-set choice, with overlap.

    ``sources`` and ``sinks`` deliberately differ in size and share members,
    so a sorter whose endpoints land in both sets is exercised regardless of
    which set the implementation chooses to iterate.
    """
    records = _fixture()
    index = Buildings(records)
    sources = {i for i in range(0, 60, 3)}  # 20 members
    sinks = {i for i in range(60) if i % 5 != 0}  # 48 members, overlapping
    assert len(sources) != len(sinks)
    assert sources & sinks

    def brute_force(srcs: set[int], sks: set[int]) -> tuple[int, ...]:
        return tuple(
            i
            for i, b in enumerate(records)
            if catalog.is_sorter(b.item_id) and b.input_obj in srcs and b.output_obj in sks
        )

    assert index.sorters_between(sources, sinks) == brute_force(sources, sinks)
    # Mirrored call forces the OTHER branch (now sinks is the smaller set).
    assert index.sorters_between(sinks, sources) == brute_force(sinks, sources)


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


def test_predecessor_of_is_none_for_zero_or_ambiguous_fan_in() -> None:
    records = _fixture()
    index = Buildings(records)
    for i in range(len(records)):
        preds = index.by_output_obj(i)
        if len(preds) == 1:
            assert index.predecessor_of(i) == preds[0]
        else:
            assert index.predecessor_of(i) is None
    assert index.predecessor_of(999_999) is None


def test_splitter_successors_matches_by_input_obj() -> None:
    """A splitter/piler names neither neighbour; its successors pick it up.

    ``splitter_successors`` is what a caller reaches for by name; it must
    agree with ``by_input_obj`` on the splitter's own index, which is the
    link a downstream belt actually stores.
    """
    records = (
        PlacedBuilding(item_id=catalog.SPLITTER_ID, model_index=0, x=0, y=0),
        PlacedBuilding(item_id=next(iter(catalog.BELT_IDS)), model_index=0, x=1, y=0, input_obj=0),
        PlacedBuilding(item_id=next(iter(catalog.BELT_IDS)), model_index=0, x=1, y=1, input_obj=0),
        PlacedBuilding(item_id=next(iter(catalog.BELT_IDS)), model_index=0, x=2, y=0),
    )
    index = Buildings(records)
    assert index.splitter_successors(0) == (1, 2)
    assert index.splitter_successors(0) == index.by_input_obj(0)
    assert index.splitter_successors(999_999) == ()


def test_belt_run_crosses_splitters_and_pilers_and_terminates_on_cycles() -> None:
    """A hand-built chain: belt -> splitter -> {belt, belt} -> piler -> belt,
    with the piler's output looping back to the start.

    ``0 -> 1 -> SPLITTER(2) -> {3, 4}``; ``3 -> 5`` (a dead end); ``4 ->
    PILER(6) -> 7``; ``7 -> 0`` closes the cycle back through everything.
    """
    belt = next(iter(catalog.BELT_IDS))
    records = (
        PlacedBuilding(item_id=belt, model_index=0, x=0, y=0, output_obj=1),  # 0
        PlacedBuilding(item_id=belt, model_index=0, x=1, y=0, output_obj=2),  # 1
        PlacedBuilding(item_id=catalog.SPLITTER_ID, model_index=0, x=2, y=0),  # 2
        PlacedBuilding(item_id=belt, model_index=0, x=3, y=0, input_obj=2, output_obj=5),  # 3
        PlacedBuilding(item_id=belt, model_index=0, x=3, y=1, input_obj=2, output_obj=6),  # 4
        PlacedBuilding(item_id=belt, model_index=0, x=4, y=0),  # 5 (dead end)
        PlacedBuilding(item_id=catalog.PILER_ID, model_index=0, x=4, y=1),  # 6
        PlacedBuilding(item_id=belt, model_index=0, x=5, y=1, input_obj=6, output_obj=0),  # 7
    )
    index = Buildings(records)
    whole_run = frozenset({0, 1, 3, 4, 5, 7})

    assert index.belt_run(0, forward=True) == whole_run
    assert index.belt_run(5, forward=False) == whole_run
    # The splitter and piler themselves are crossed, not counted.
    assert 2 not in index.belt_run(0, forward=True)
    assert 6 not in index.belt_run(0, forward=True)

    def brute_force(start: int, *, forward: bool) -> frozenset[int]:
        onward: dict[int, list[int]] = {}
        for i, building in enumerate(records):
            link = building.output_obj
            if link is None or not 0 <= link < len(records):
                continue
            if catalog.is_belt(building.item_id) and catalog.is_belt(records[link].item_id):
                onward.setdefault(i, []).append(link)
            elif catalog.is_belt(building.item_id):
                for j, other in enumerate(records):
                    if catalog.is_belt(other.item_id) and other.input_obj == link:
                        onward.setdefault(i, []).append(j)
        if not forward:
            backward: dict[int, list[int]] = {}
            for source, destinations in onward.items():
                for destination in destinations:
                    backward.setdefault(destination, []).append(source)
            onward = backward
        seen = {start}
        pending = [start]
        while pending:
            node = pending.pop()
            for following in onward.get(node, ()):
                if following not in seen:
                    seen.add(following)
                    pending.append(following)
        return frozenset(seen)

    for start in range(len(records)):
        for forward in (True, False):
            expected = brute_force(start, forward=forward)
            assert expected
            assert index.belt_run(start, forward=forward) == expected


def test_belt_run_crosses_machine_hosts_only_when_explicitly_requested() -> None:
    belt = next(iter(catalog.BELT_IDS))
    host = catalog.building(catalog.ENERGY_EXCHANGER_ID)
    index = Buildings((
        PlacedBuilding(item_id=belt, model_index=0, x=0, y=0, output_obj=1),
        PlacedBuilding(item_id=catalog.ENERGY_EXCHANGER_ID, model_index=host.model_index, x=1, y=0),
        PlacedBuilding(item_id=belt, model_index=0, x=2, y=0, input_obj=1),
    ))
    assert index.belt_run(0, forward=True) == frozenset({0})
    assert index.belt_run(2, forward=False) == frozenset({2})
    assert index.belt_run(0, forward=True, through_any_host=True) == frozenset({0, 2})
    assert index.belt_run(2, forward=False, through_any_host=True) == frozenset({0, 2})


# --- MutableBuildings ---------------------------------------------------------


def test_append_keeps_every_index_correct() -> None:
    live = MutableBuildings(_fixture())
    extra = PlacedBuilding(item_id=2303, model_index=0, x=200, y=7, recipe_id=1)
    live.append(extra)
    records = tuple(live)
    assert live.by_item(2303) == tuple(i for i, b in enumerate(records) if b.item_id == 2303)
    assert live.machines_for_recipe(1) == tuple(
        i for i, b in enumerate(records) if b.recipe_id == 1 and kind_for(b.item_id) is Kind.MACHINE
    )
    assert live.at_tile(200, 7) == (len(records) - 1,)
    assert live.bounds() == Buildings(records).bounds()


def test_pop_truncates_every_index() -> None:
    records = _fixture()
    live = MutableBuildings(records)
    live.append(PlacedBuilding(item_id=2303, model_index=0, x=200, y=7))
    live.pop()
    assert tuple(live) == records
    assert live.at_tile(200, 7) == ()
    for item_id in {b.item_id for b in records}:
        assert live.by_item(item_id) == Buildings(records).by_item(item_id)


def test_relink_updates_the_link_indexes_and_nothing_else() -> None:
    records = _fixture()
    live = MutableBuildings(records)
    old = records[1]
    live[1] = replace(old, output_obj=42)
    assert 1 not in live.by_output_obj(old.output_obj or -1)
    assert 1 in live.by_output_obj(42)
    assert live.by_item(old.item_id) == Buildings(records).by_item(old.item_id)


def test_a_geometry_rewrite_raises_rather_than_answering_stale() -> None:
    live = MutableBuildings(_fixture())
    with pytest.raises(ValueError, match="geometry"):
        live[0] = replace(live[0], x=999)


def test_a_non_tail_pop_raises() -> None:
    live = MutableBuildings(_fixture())
    with pytest.raises(ValueError, match="tail"):
        live.pop(0)


def test_a_non_tail_delitem_raises_and_the_tail_delitem_works() -> None:
    live = MutableBuildings(_fixture())
    with pytest.raises(ValueError, match="tail"):
        del live[0]
    n = len(live)
    del live[-1]
    assert len(live) == n - 1


def test_pop_from_an_empty_sequence_raises_index_error() -> None:
    live = MutableBuildings(())
    with pytest.raises(IndexError):
        live.pop()


def test_insert_delegates_to_append_at_the_tail_and_raises_elsewhere() -> None:
    live = MutableBuildings(_fixture())
    extra = PlacedBuilding(item_id=2303, model_index=0, x=300, y=9)
    live.insert(len(live), extra)
    assert live[-1] == extra
    with pytest.raises(ValueError):
        live.insert(0, extra)


def test_snapshot_is_frozen_and_independent_of_later_mutation() -> None:
    records = _fixture()
    live = MutableBuildings(records)
    snap = live.snapshot()
    assert isinstance(snap, Buildings)
    assert tuple(snap) == records
    live.append(PlacedBuilding(item_id=2303, model_index=0, x=400, y=9))
    assert len(snap) == len(records)
    assert len(live) == len(records) + 1
    assert snap.by_item(2303) == Buildings(records).by_item(2303)


def test_slicing_matches_list_semantics() -> None:
    records = _fixture()
    live = MutableBuildings(records)
    assert live[5:10] == list(records[5:10])
    assert live[50:] == list(records[50:])
    assert live[-3:] == list(records[-3:])
    assert list(live) == list(records)
    assert tuple(live) == records
    assert len(live) == len(records)


def test_setitem_may_change_z_and_at_tile_reflects_the_new_value() -> None:
    """``z`` is not a geometry field: a relink may change it, and ``at_tile``
    must answer from the current record rather than a stale z-keyed index."""
    b0 = PlacedBuilding(item_id=2303, model_index=0, x=5, y=5, z=Fraction(0))
    b1 = PlacedBuilding(item_id=2303, model_index=0, x=5, y=5, z=Fraction(1, 2))
    live = MutableBuildings([b0, b1])
    assert live.at_tile(5, 5, Fraction(0)) == (0,)
    assert live.at_tile(5, 5, Fraction(1, 2)) == (1,)
    live[1] = replace(b1, z=Fraction(0))
    assert live.at_tile(5, 5, Fraction(0)) == (0, 1)
    assert live.at_tile(5, 5, Fraction(1, 2)) == ()
    assert live.at_tile(5, 5) == (0, 1)


def test_splitter_successors_is_live_within_the_same_append_pass() -> None:
    """``canvas.add()`` grows the list inside the same commit pass that
    queries a splitter's successors -- a memo keyed on the old sequence
    would answer stale here, so this must be recomputed from the live
    ``by_input_obj`` bucket on every call."""
    belt = next(iter(catalog.BELT_IDS))
    live = MutableBuildings([PlacedBuilding(item_id=catalog.SPLITTER_ID, model_index=0, x=0, y=0)])
    assert live.splitter_successors(0) == ()
    live.append(PlacedBuilding(item_id=belt, model_index=0, x=1, y=0, input_obj=0))
    assert live.splitter_successors(0) == (1,)
    live.append(PlacedBuilding(item_id=belt, model_index=0, x=1, y=1, input_obj=0))
    assert live.splitter_successors(0) == (1, 2)


def test_relink_then_tail_pop_keeps_link_buckets_sorted() -> None:
    """A relink can insert a LOW index into a link bucket that already holds
    higher ones; a later tail pop must still be popping the bucket's own
    ascending-order tail, not merely whatever sits at the end of the list."""
    records = _fixture()
    live = MutableBuildings(records)
    assert Buildings(records).by_output_obj(5) == ()  # sanity: nothing points at 5 yet
    live.append(PlacedBuilding(item_id=2303, model_index=0, x=200, y=9, output_obj=5))
    tail = len(live) - 1
    live[2] = replace(live[2], output_obj=5)
    assert live.by_output_obj(5) == (2, tail)
    live.pop()
    assert live.by_output_obj(5) == (2,)
    assert len(live) == len(records)
    for i, b in enumerate(records):
        if i == 2:
            assert live[i] == replace(b, output_obj=5)
        else:
            assert live[i] == b


def test_queries_match_a_rebuilt_index_after_a_mutation_sequence() -> None:
    """The staleness guard: after arbitrary legal mutation, every query agrees
    with a freshly built index over the same records."""
    live = MutableBuildings(_fixture())
    for n in range(20):
        live.append(
            PlacedBuilding(
                item_id=2303 if n % 2 else next(iter(catalog.SORTER_IDS)),
                model_index=0,
                x=100 + n,
                y=9,
                recipe_id=n % 3,
                input_obj=n,
                output_obj=n + 1,
                carries_item=f"item-{n % 7}",
            )
        )
    for _ in range(5):
        live.pop()
    live[3] = replace(live[3], output_obj=11)

    records = tuple(live)
    fresh = Buildings(records)
    assert live.bounds() == fresh.bounds()
    assert live.machines() == fresh.machines()
    assert live.belts() == fresh.belts()
    assert live.sorters() == fresh.sorters()
    for i in range(len(records)):
        assert live.by_output_obj(i) == fresh.by_output_obj(i)
        assert live.by_input_obj(i) == fresh.by_input_obj(i)
    for item_id in {b.item_id for b in records}:
        assert live.by_item(item_id) == fresh.by_item(item_id)
    for carried in {b.carries_item for b in records if b.carries_item}:
        assert live.carrying(carried) == fresh.carrying(carried)


def test_queries_match_a_rebuilt_index_on_spatial_link_and_count_methods() -> None:
    """Extends the staleness guard above to the methods its brief version
    omits: ``at_tile``, ``in_box``, ``predecessor_of``, ``splitter_successors``,
    ``belt_run``, ``attached_to``, ``machines_for_strip`` and the counts."""
    live = MutableBuildings(_fixture())
    for n in range(20):
        live.append(
            PlacedBuilding(
                item_id=2303 if n % 2 else next(iter(catalog.SORTER_IDS)),
                model_index=0,
                x=100 + n,
                y=9,
                recipe_id=n % 3,
                owner_strip=n % 4,
                input_obj=n,
                output_obj=n + 1,
                carries_item=f"item-{n % 7}",
            )
        )
    for _ in range(5):
        live.pop()
    live[3] = replace(live[3], output_obj=11)

    records = tuple(live)
    fresh = Buildings(records)
    assert live.bounds() == fresh.bounds()
    assert live.in_box(*fresh.bounds()) == fresh.in_box(*fresh.bounds())

    for i, b in enumerate(records):
        assert live.at_tile(b.x, b.y) == fresh.at_tile(b.x, b.y)
        assert live.predecessor_of(i) == fresh.predecessor_of(i)
        assert live.splitter_successors(i) == fresh.splitter_successors(i)
        assert live.belt_run(i, forward=True) == fresh.belt_run(i, forward=True)
        assert live.belt_run(i, forward=False) == fresh.belt_run(i, forward=False)
        assert live.attached_to(i) == fresh.attached_to(i)

    for strip in {b.owner_strip for b in records}:
        # `machines_for_strip` is `int`-only by its Task 1 signature; a `None`
        # owner_strip (unstripped belts/sorters in the fixture) only exercises
        # `by_owner_strip`, which does accept it.
        if strip is not None:
            assert live.machines_for_strip(strip) == fresh.machines_for_strip(strip)
        assert live.by_owner_strip(strip) == fresh.by_owner_strip(strip)

    for kind in Kind:
        assert live.count_by_kind(kind) == fresh.count_by_kind(kind)
        assert live.by_kind(kind) == fresh.by_kind(kind)

    for item_id in {b.item_id for b in records}:
        assert live.count_by_item(item_id) == fresh.count_by_item(item_id)


def test_queries_match_a_rebuilt_index_on_kind_filtered_and_between_methods() -> None:
    """Extends the staleness guard to the eight kind-filtered / relational
    query methods the two guards above never call: ``splitters``,
    ``machines_for_recipe``, ``belts_carrying``, ``sorters_carrying``,
    ``belts_into``, ``sorters_into``, ``sorters_out_of`` and
    ``sorters_between`` -- the last of which drives the whole refactor (the
    user's own words: "it also should be walking group_machines, which is
    the smaller set anyway") and had no ``MutableBuildings`` coverage at all
    before this.
    """
    belt = next(iter(catalog.BELT_IDS))
    sorter = next(iter(catalog.SORTER_IDS))
    live = MutableBuildings(_fixture())
    live.append(PlacedBuilding(item_id=catalog.SPLITTER_ID, model_index=0, x=200, y=20))
    live.append(PlacedBuilding(item_id=catalog.PILER_ID, model_index=0, x=201, y=20))
    for n in range(20):
        kind_pick = n % 3
        if kind_pick == 0:
            live.append(
                PlacedBuilding(item_id=2303, model_index=0, x=100 + n, y=9, recipe_id=n % 3)
            )
        elif kind_pick == 1:
            live.append(
                PlacedBuilding(
                    item_id=belt,
                    model_index=0,
                    x=100 + n,
                    y=9,
                    output_obj=n + 1,
                    carries_item=f"item-{n % 7}",
                )
            )
        else:
            live.append(
                PlacedBuilding(
                    item_id=sorter,
                    model_index=0,
                    x=100 + n,
                    y=9,
                    input_obj=n,
                    output_obj=n + 1,
                    carries_item=f"item-{n % 7}",
                )
            )
    for _ in range(5):
        live.pop()
    live[3] = replace(live[3], output_obj=11)

    records = tuple(live)
    fresh = Buildings(records)

    # `splitters()` takes no key, so its own non-emptiness is the check: this
    # fixture appends exactly one live splitter, so a vacuous `() == ()` here
    # would mean the append or the index silently lost it.
    assert live.splitters() == fresh.splitters()
    assert live.splitters()

    # The per-key loops below are driven by keys genuinely PRESENT in the
    # mutated records (every recipe_id/item/index that appears at least
    # once), so an individual key legitimately CAN come back empty (e.g. a
    # `recipe_id` shared with a non-machine record). What must not happen is
    # every comparison in a loop being a vacuous `() == ()`; `any(...)` after
    # each loop turns that spot-check into a guarantee.
    recipe_results = []
    for recipe_id in {b.recipe_id for b in records}:
        got = live.machines_for_recipe(recipe_id)
        assert got == fresh.machines_for_recipe(recipe_id)
        recipe_results.append(got)
    assert any(recipe_results)

    belts_carrying_results = []
    sorters_carrying_results = []
    for carried in {b.carries_item for b in records if b.carries_item}:
        got_belts = live.belts_carrying(carried)
        got_sorters = live.sorters_carrying(carried)
        assert got_belts == fresh.belts_carrying(carried)
        assert got_sorters == fresh.sorters_carrying(carried)
        belts_carrying_results.append(got_belts)
        sorters_carrying_results.append(got_sorters)
    assert any(belts_carrying_results)
    assert any(sorters_carrying_results)

    belts_into_results = []
    sorters_into_results = []
    sorters_out_of_results = []
    for i in range(len(records)):
        got_belts_into = live.belts_into(i)
        got_sorters_into = live.sorters_into(i)
        got_sorters_out_of = live.sorters_out_of(i)
        assert got_belts_into == fresh.belts_into(i)
        assert got_sorters_into == fresh.sorters_into(i)
        assert got_sorters_out_of == fresh.sorters_out_of(i)
        belts_into_results.append(got_belts_into)
        sorters_into_results.append(got_sorters_into)
        sorters_out_of_results.append(got_sorters_out_of)
    assert any(belts_into_results)
    assert any(sorters_into_results)
    assert any(sorters_out_of_results)

    def brute_force_sorters_between(srcs: set[int], sks: set[int]) -> tuple[int, ...]:
        return tuple(
            i
            for i, b in enumerate(records)
            if catalog.is_sorter(b.item_id) and b.input_obj in srcs and b.output_obj in sks
        )

    # `i % 3 == 0` / `i % 2 == 0` (this test's previous sets) are VACUOUS for
    # the forward call by construction, not by bad luck: every surviving
    # sorter's `input_obj` is either `i - 1` for a fixture sorter at index
    # `i` (`i % 3 == 2`, so `input_obj % 3 == 1`) or one of the loop's
    # `{2, 5, 8, 11, 14}` (`% 3 == 2`) -- never `% 3 == 0` -- so no sorter's
    # `input_obj` could ever land in an `i % 3 == 0` set, whatever the pop
    # and relink above do. Picking two REAL sorters and seeding each set from
    # their actual endpoints (rather than a congruence class) guarantees a
    # genuine match in EACH directional call instead.
    sorter_indices = [i for i, b in enumerate(records) if catalog.is_sorter(b.item_id)]
    assert len(sorter_indices) >= 2
    first_sorter = records[sorter_indices[0]]
    last_sorter = records[sorter_indices[-1]]
    assert first_sorter.input_obj is not None and first_sorter.output_obj is not None
    assert last_sorter.input_obj is not None and last_sorter.output_obj is not None

    # Padded to differing sizes so the two directional calls still drive both
    # branches of `sorters_between`'s smaller-set choice, same as before.
    sources = {first_sorter.input_obj, last_sorter.output_obj} | {
        i for i in range(len(records)) if i % 7 == 0
    }
    sinks = {first_sorter.output_obj, last_sorter.input_obj} | {
        i for i in range(len(records)) if i % 2 == 0
    }
    assert len(sources) != len(sinks)

    expected_forward = brute_force_sorters_between(sources, sinks)
    expected_reverse = brute_force_sorters_between(sinks, sources)
    # Non-vacuousness, asserted explicitly rather than left to the equality
    # check alone: `sorter_indices[0]` must satisfy the forward direction
    # (its own input_obj/output_obj seeded `sources`/`sinks`) and
    # `sorter_indices[-1]` must satisfy the reverse one.
    assert expected_forward
    assert expected_reverse
    assert live.sorters_between(sources, sinks) == expected_forward
    assert live.sorters_between(sinks, sources) == expected_reverse


def test_bounds_after_append_to_an_initially_empty_sequence_matches_a_fresh_index() -> None:
    """Pins the one branch of ``_widen_bounds`` the constructor path never
    reaches: the very first append into an empty ``MutableBuildings``."""
    live = MutableBuildings(())
    b = PlacedBuilding(item_id=2303, model_index=0, x=7, y=11, width=3, height=2)
    live.append(b)
    assert live.bounds() == Buildings([b]).bounds()
    assert live.bounds() == (7, 11, 9, 12)


def test_setitem_with_a_slice_raises() -> None:
    live = MutableBuildings(_fixture())
    with pytest.raises(ValueError):
        live[0:2] = [live[0], live[1]]


def test_delitem_with_a_slice_raises() -> None:
    live = MutableBuildings(_fixture())
    with pytest.raises(ValueError):
        del live[0:2]
