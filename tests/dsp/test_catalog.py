"""Ground-truth checks on the DSP building catalog.

The load-bearing test here is :func:`test_safe_fixtures_have_no_overlaps`, which
replays real game blueprints through the footprint table.  The game cannot
produce an overlapping blueprint, so any overlap it reports is a wrong table.
"""

from __future__ import annotations

import collections
import pathlib

import pytest

from flab2bp.dsp import catalog
from flab2bp.dsp.codec import decode

FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures"


def test_table_loads() -> None:
    buildings = catalog.all_buildings()
    assert len(buildings) > 50
    assert all(b.width >= 1 and b.height >= 1 for b in buildings)


@pytest.mark.parametrize(
    ("box", "expected"),
    [
        (3.82, 3),  # Assembling Machine -- half-extent 1.91 covers 3 tile centres
        (5.6, 5),  # Matrix Lab
        (2.9, 3),  # Arc Smelter
        (8.2, 9),  # Chemical Plant, corroborated by landBBox == 9.0
        (7.2, 7),  # Oil Refinery, long axis
        (0.6, 1),  # Tesla Tower
        (4.5, 5),  # Fractionator / Storage Tank
        (10.0, 9),  # exactly-integer half-extent covers no further centre
    ],
)
def test_derive_footprint(box: float, expected: int) -> None:
    assert catalog.derive_footprint(box) == expected


def test_every_derived_footprint_is_odd() -> None:
    """Even footprints are geometrically impossible for integer-centred buildings.

    Sorters are the one exception the table overrides by hand, and they are odd
    anyway, so this holds across the board.
    """
    for b in catalog.all_buildings():
        assert b.width % 2 == 1, f"{b.name} width {b.width} is even"
        assert b.height % 2 == 1, f"{b.name} height {b.height} is even"


@pytest.mark.parametrize(
    ("item_id", "expected"),
    [
        (2302, (3, 3)),  # Arc Smelter
        (2303, (3, 3)),  # Assembling Machine Mk.I -- was wrongly 4x4
        (2304, (3, 3)),  # Assembling Machine Mk.II
        (2305, (3, 3)),  # Assembling Machine Mk.III
        (2901, (5, 5)),  # Matrix Lab -- was wrongly 6x6
        (2902, (5, 5)),  # Self-evolution Lab
        (2309, (9, 5)),  # Chemical Plant -- was wrongly 8x5, and got BIGGER
        (2308, (3, 7)),  # Oil Refinery
        (2314, (5, 5)),  # Fractionator
        (2201, (1, 1)),  # Tesla Tower
        (2013, (1, 1)),  # Sorter Mk.III
        (2002, (1, 1)),  # Conveyor Belt Mk.II
    ],
)
def test_known_footprints(item_id: int, expected: tuple[int, int]) -> None:
    assert catalog.footprint(item_id) == expected


def test_spray_coater_occupies_no_tile() -> None:
    """It is a belt addon, which is what makes proliferation nearly area-free."""
    coater = catalog.building(catalog.SPRAY_COATER_ID)
    assert coater.is_belt_addon
    assert not coater.occupies_tiles


def test_splitter_is_belt_integrated() -> None:
    """Splitters sit ON the belt line -- measured at dx=0.00, dy=0.00 from a belt."""
    assert catalog.is_belt_integrated(catalog.SPLITTER_ID)
    assert catalog.is_belt_integrated(2013)  # a sorter
    assert catalog.is_belt_integrated(2002)  # a belt
    assert not catalog.is_belt_integrated(2303)  # an assembler


def test_tesla_cover_radius_is_a_radius() -> None:
    """A diameter reading would leave machines in working blueprints unpowered."""
    assert catalog.TESLA_COVER_RADIUS == 10.5


def _footprint_tiles(item_id: int, x: float, y: float, yaw: float) -> list[tuple[int, int]]:
    w, h = catalog.footprint(item_id)
    if round((yaw % 360) / 90) % 4 in (1, 3):
        w, h = h, w
    cx, cy = round(x), round(y)
    return [
        (cx + dx, cy + dy)
        for dx in range(-(w // 2), w // 2 + 1)
        for dy in range(-(h // 2), h // 2 + 1)
    ]


@pytest.mark.parametrize("stem", catalog.GEOMETRY_SAFE_FIXTURES)
def test_safe_fixtures_have_no_overlaps(stem: str) -> None:
    """Real blueprints must not overlap under our footprints.

    This is the test that settled the footprint dispute.  Under the previous
    round-to-nearest table these two fixtures reported 21 and 129 overlapping
    cells respectively; under the derived table both are zero.
    """
    blueprint = decode((FIXTURES / f"{stem}.txt").read_text())

    occupied: dict[int, dict[tuple[int, int], int]] = collections.defaultdict(dict)
    clashes: list[str] = []

    for idx, b in enumerate(blueprint.buildings):
        if catalog.is_belt_integrated(b.item_id):
            continue
        if not catalog.building(b.item_id).occupies_tiles:
            continue
        level = round(b.z)
        for tile in _footprint_tiles(b.item_id, b.x, b.y, b.yaw):
            previous = occupied[level].get(tile)
            if previous is not None:
                other = blueprint.buildings[previous]
                clashes.append(
                    f"tile {tile} at z={level}: "
                    f"{catalog.building(other.item_id).name} @({other.x},{other.y}) "
                    f"vs {catalog.building(b.item_id).name} @({b.x},{b.y})"
                )
            else:
                occupied[level][tile] = idx

    assert not clashes, f"{len(clashes)} overlapping cells:\n" + "\n".join(clashes[:10])


def test_overlap_check_can_fail() -> None:
    """Guard: the regression above must be capable of failing.

    Two assemblers one tile apart genuinely overlap at 3x3, so if this does not
    detect it the fixture test proves nothing.
    """
    a = _footprint_tiles(2303, 0, 0, 0.0)
    b = _footprint_tiles(2303, 1, 0, 0.0)
    assert set(a) & set(b)


def test_low_confidence_footprints_are_not_production_buildings() -> None:
    """Nothing the generator places may sit in the unresolved set."""
    generator_places = {
        2302, 2303, 2304, 2305, 2308, 2309,
        2310, 2314, 2315, 2318, 2319, 2901, 2902,
    }
    assert not (generator_places & catalog.LOW_CONFIDENCE_FOOTPRINTS)
