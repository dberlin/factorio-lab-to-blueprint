"""Re-derive every real sorter's slots from its own geometry.

The corpus is the only oracle here: eleven blueprints the game itself wrote,
1288 sorters between them.  ``flab2bp.layout.slots`` claims their slot indices
are a function of geometry; these tests hold it to that claim rather than to a
table copied out of the same measurement.

An `Artificial Star` exclusion is the one hole, and it is a data hole rather
than a rule hole -- see :func:`test_only_artificial_star_is_excluded`.
"""

from __future__ import annotations

import collections
from collections.abc import Callable
from pathlib import Path

import pytest

from flab2bp.dsp import catalog as cat
from flab2bp.dsp.codec import decode
from flab2bp.dsp.envelope import BlueprintFormatError
from flab2bp.dsp.records import Blueprint, BlueprintBuilding
from flab2bp.layout import slots as S

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"

#: Item id of the Artificial Star.  Its records in the polar `tillable-...`
#: fixture put the sorter end tens of tiles from the building it names, so no
#: geometric rule can be checked against them; see the exclusion test.
ARTIFICIAL_STAR = 2210


def _factory_blueprints() -> list[tuple[str, Blueprint]]:
    out: list[tuple[str, Blueprint]] = []
    for path in sorted(FIXTURES.glob("*.txt")):
        try:
            out.append((path.name, decode(path.read_text().strip())))
        except BlueprintFormatError:
            # `dyson-sphere-iridescent` is a DYBP, not a factory blueprint.
            continue
    return out


def _sorter_sides(
    bp: Blueprint,
) -> list[
    tuple[
        BlueprintBuilding,
        BlueprintBuilding | None,
        int,
        tuple[float, float],
        tuple[float, float],
    ]
]:
    """``(sorter, peer, recorded_slot, end, other_end)`` for both ends of each sorter."""
    by_index = {b.index: b for b in bp.buildings}
    rows = []
    for s in bp.buildings:
        if not cat.is_sorter(s.item_id):
            continue
        rows.append(
            (s, by_index.get(s.output_obj_idx), s.output_to_slot, (s.x2, s.y2), (s.x, s.y))
        )
        rows.append(
            (s, by_index.get(s.input_obj_idx), s.input_from_slot, (s.x, s.y), (s.x2, s.y2))
        )
    return rows


CORPUS = _factory_blueprints()


def test_corpus_loaded() -> None:
    """Guard against a silently empty oracle."""
    assert len(CORPUS) == 10
    total = sum(
        1 for _, bp in CORPUS for b in bp.buildings if cat.is_sorter(b.item_id)
    )
    assert total == 1288


def test_sorter_own_ends_are_constant() -> None:
    """``output_from_slot == 0`` and ``input_to_slot == 1`` on every real sorter."""
    seen = collections.Counter(
        (b.output_from_slot, b.input_to_slot)
        for _, bp in CORPUS
        for b in bp.buildings
        if cat.is_sorter(b.item_id)
    )
    assert dict(seen) == {(S.OUTPUT_FROM_SLOT, S.INPUT_TO_SLOT): 1288}


def test_belt_side_is_always_minus_one() -> None:
    values = collections.Counter(
        slot
        for _, bp in CORPUS
        for _s, peer, slot, _e, _o in _sorter_sides(bp)
        if peer is not None and cat.is_belt(peer.item_id)
    )
    assert dict(values) == {S.BELT_SLOT: 1240}


#: How far off the integer grid a machine may sit and still be trusted as
#: geometry.  Polar blueprints compress longitude with latitude, so near a pole
#: a whole tile of x collapses into a fraction of one and distances stop meaning
#: tiles -- which is the same reason ``dsp.codec.tile_to_local_offset`` was
#: verified on only the three uncompressed fixtures.
ON_GRID_TOLERANCE = 0.2


def _off_grid(b: BlueprintBuilding) -> bool:
    return max(abs(b.x - round(b.x)), abs(b.y - round(b.y))) > ON_GRID_TOLERANCE


def test_machine_slots_reproduce_the_corpus() -> None:
    """The rule reproduces the game's own index on every on-grid record.

    This is the whole point of the module: 1206 machine-side records across
    seven building types, four machine yaws and three footprints, each one
    re-derived from the machine's position, footprint and yaw plus the sorter's
    two endpoints -- nothing read back from the record being checked.
    """
    checked = 0
    wrong: list[str] = []
    for name, bp in CORPUS:
        for _s, peer, slot, end, other in _sorter_sides(bp):
            if peer is None or cat.is_belt(peer.item_id):
                continue
            if peer.item_id == ARTIFICIAL_STAR or _off_grid(peer):
                continue
            got = S.machine_slot(
                peer.item_id,
                peer.yaw,
                (end[0] - peer.x, end[1] - peer.y),
                (end[0] - other[0], end[1] - other[1]),
            )
            checked += 1
            if got != slot:
                wrong.append(
                    f"{name}: {cat.building(peer.item_id).name} at "
                    f"({peer.x:.2f},{peer.y:.2f}) yaw={peer.yaw:.1f} "
                    f"end=({end[0]:.2f},{end[1]:.2f}) game={slot} derived={got}"
                )
    assert checked == 1206
    assert wrong == [], f"{len(wrong)} of {checked} mis-derived:\n" + "\n".join(wrong[:20])


def test_latitude_compressed_records_are_bounded() -> None:
    """The off-grid remainder is small, named, and does not grow silently.

    41 machine-side records sit on machines the polar projection pushed off the
    tile grid.  36 of them still come out right; the 5 that do not are all Depot
    Mk.I in ``factory-endgame-distribution-hub``, where the sorter's whole x
    extent has been squashed to ~0.1 tiles and the approach direction can no
    longer be read off it.  That is the coordinate system failing, not the ring
    rule -- but it is a hole, so it is counted rather than hidden.
    """
    total = 0
    wrong: list[tuple[str, str]] = []
    for name, bp in CORPUS:
        for _s, peer, slot, end, other in _sorter_sides(bp):
            if peer is None or cat.is_belt(peer.item_id):
                continue
            if peer.item_id == ARTIFICIAL_STAR or not _off_grid(peer):
                continue
            total += 1
            got = S.machine_slot(
                peer.item_id,
                peer.yaw,
                (end[0] - peer.x, end[1] - peer.y),
                (end[0] - other[0], end[1] - other[1]),
            )
            if got != slot:
                wrong.append((name, cat.building(peer.item_id).name))
    assert total == 41
    assert wrong == [("factory-endgame-distribution-hub.txt", "Depot Mk.I")] * 5


def test_slot_handedness_matches_corpus() -> None:
    """Every entry in the handedness table is what the corpus actually shows.

    Flipping any entry has to break :func:`test_machine_slots_reproduce_the_corpus`,
    or the table is decoration.  This asserts that directly, per building, so a
    wrong entry names the building instead of failing as one number.
    """
    observed: set[int] = set()
    disagrees: collections.Counter[int] = collections.Counter()
    for _name, bp in CORPUS:
        for _s, peer, slot, end, other in _sorter_sides(bp):
            if peer is None or cat.is_belt(peer.item_id):
                continue
            if peer.item_id == ARTIFICIAL_STAR:
                continue
            observed.add(peer.item_id)
            flipped = _slot_with_handedness(
                peer.item_id, peer, end, other, not S.ring_is_mirrored(peer.item_id)
            )
            if flipped != slot:
                disagrees[peer.item_id] += 1

    assert observed == set(S._MIRRORED), "table covers exactly the observed buildings"
    for item_id in sorted(observed):
        assert disagrees[item_id] > 0, (
            f"{cat.building(item_id).name}: the opposite handedness fits every one of "
            f"its records too, so this entry is not evidenced by the corpus"
        )


def _slot_with_handedness(
    item_id: int,
    peer: BlueprintBuilding,
    end: tuple[float, float],
    other: tuple[float, float],
    mirrored: bool,
) -> int:
    original = S._MIRRORED.get(item_id)
    S._MIRRORED[item_id] = mirrored
    try:
        return S.machine_slot(
            item_id,
            peer.yaw,
            (end[0] - peer.x, end[1] - peer.y),
            (end[0] - other[0], end[1] - other[1]),
        )
    finally:
        if original is None:
            del S._MIRRORED[item_id]
        else:
            S._MIRRORED[item_id] = original


def test_only_artificial_star_is_excluded() -> None:
    """The one exclusion is a broken *record*, not a building we cannot model.

    In the polar ``tillable-...`` fixture a sorter names an Artificial Star tens
    of tiles away -- 24 of its 88 records put the sorter end outside the star's
    footprint entirely and 62 more put it in the interior.  There is no geometry
    to check there.  Every other machine-side record in the corpus has its end
    on the named building's perimeter, and this test fails if that ever stops
    being true, so the exclusion can never quietly widen.
    """
    far = 0
    for _name, bp in CORPUS:
        for _s, peer, _slot, end, _other in _sorter_sides(bp):
            if peer is None or cat.is_belt(peer.item_id):
                continue
            b = cat.building(peer.item_id)
            dx = abs(end[0] - peer.x)
            dy = abs(end[1] - peer.y)
            outside = dx > (b.width - 1) / 2 + 0.5 or dy > (b.height - 1) / 2 + 0.5
            if outside:
                assert peer.item_id == ARTIFICIAL_STAR, (
                    f"{b.name} record has its sorter end outside the footprint; "
                    f"the exclusion list would have to grow"
                )
                far += 1
    assert far == 24


@pytest.mark.parametrize(
    ("offset", "approach", "expected"),
    [
        # 3x3, un-mirrored, every one of the twelve slots.
        ((-1, 1), (0, -1), 0),
        ((0, 1), (0, -1), 1),
        ((1, 1), (0, -1), 2),
        ((1, 1), (-1, 0), 3),
        ((1, 0), (-1, 0), 4),
        ((1, -1), (-1, 0), 5),
        ((1, -1), (0, 1), 6),
        ((0, -1), (0, 1), 7),
        ((-1, -1), (0, 1), 8),
        ((-1, -1), (1, 0), 9),
        ((-1, 0), (1, 0), 10),
        ((-1, 1), (1, 0), 11),
    ],
)
def test_unmirrored_ring(
    offset: tuple[int, int], approach: tuple[int, int], expected: int
) -> None:
    assert S.machine_slot(2303, 0.0, offset, approach) == expected


@pytest.mark.parametrize(
    ("offset", "approach", "expected"),
    [
        # 5x5 Matrix Lab, mirrored, every one of the twelve slots.
        ((1, 2), (0, -1), 0),
        ((0, 2), (0, -1), 1),
        ((-1, 2), (0, -1), 2),
        ((-2, 1), (1, 0), 3),
        ((-2, 0), (1, 0), 4),
        ((-2, -1), (1, 0), 5),
        ((-1, -2), (0, 1), 6),
        ((0, -2), (0, 1), 7),
        ((1, -2), (0, 1), 8),
        ((2, -1), (-1, 0), 9),
        ((2, 0), (-1, 0), 10),
        ((2, 1), (-1, 0), 11),
    ],
)
def test_mirrored_ring(
    offset: tuple[int, int], approach: tuple[int, int], expected: int
) -> None:
    assert S.machine_slot(2901, 0.0, offset, approach) == expected


@pytest.mark.parametrize("yaw", [0.0, 90.0, 180.0, 270.0])
def test_yaw_rotates_the_ring(yaw: float) -> None:
    """Turning the machine turns its ring with it, so the slot is unchanged."""
    rot: dict[float, Callable[[int, int], tuple[int, int]]] = {
        0.0: lambda x, y: (x, y),
        90.0: lambda x, y: (y, -x),
        180.0: lambda x, y: (-x, -y),
        270.0: lambda x, y: (-y, x),
    }
    turn = rot[yaw]
    for offset, approach, expected in (
        ((-1, 1), (0, -1), 0),
        ((1, 0), (-1, 0), 4),
        ((0, -1), (0, 1), 7),
        ((-1, 0), (1, 0), 10),
    ):
        assert S.machine_slot(2303, yaw, turn(*offset), turn(*approach)) == expected


def test_wide_side_clamps_to_its_three_slots() -> None:
    """A side has three slots however long it is, so a far column takes the end one.

    The Matrix Lab's south side is five tiles but slots 0/1/2 sit ~0.8 apart
    around its centre, so nothing on that side is further out than one tile.
    """
    assert S.machine_slot(2901, 0.0, (4, 2), (0, -1)) == 0
    assert S.machine_slot(2901, 0.0, (-4, 2), (0, -1)) == 2


def test_diagonal_approach_is_refused() -> None:
    with pytest.raises(S.SlotUndetermined):
        S.machine_slot(2303, 0.0, (1, 1), (-1, -1))


def test_handedness_is_flagged_as_inferred_for_unobserved_buildings() -> None:
    assert S.handedness_is_observed(2303)
    assert S.handedness_is_observed(2901)
    # Chemical Plant: never a sorter peer anywhere in the corpus.
    assert not S.handedness_is_observed(2309)
    assert S.ring_is_mirrored(2309) is True
    # Assembling Machine Mk.II is 3x3, like the two that were observed.
    assert not S.handedness_is_observed(2304)
    assert S.ring_is_mirrored(2304) is False
