"""Ground-truth checks on the DSP building catalog.

The load-bearing test here is :func:`test_safe_fixtures_have_no_overlaps`, which
replays real game blueprints through the footprint table.  The game cannot
produce an overlapping blueprint, so any overlap it reports is a wrong table.
"""

from __future__ import annotations

import collections
import json
import math
import pathlib
from fractions import Fraction
from typing import ClassVar, TypedDict

import pytest
from pydantic import BaseModel, ConfigDict, TypeAdapter

from flab2bp.dsp import catalog, colliders
from flab2bp.dsp.codec import decode

FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures"


class _AssetRow(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="allow")


class _BuildingBoxRow(_AssetRow):
    itemId: int | None
    blueprintBoxSize: tuple[float, float]


class _NamedIdRow(_AssetRow):
    id: int
    name: str


_BUILDING_BOX_ROWS_ADAPTER = TypeAdapter(tuple[_BuildingBoxRow, ...])
_NAMED_ID_ROWS_ADAPTER = TypeAdapter(tuple[_NamedIdRow, ...])


def _blueprint_box_size(item_id: int) -> tuple[float, float]:
    """The field the footprint deliberately no longer reads, for contrast."""
    data = pathlib.Path(catalog.__file__).parent / "data" / "buildings.json"
    for row in _BUILDING_BOX_ROWS_ADAPTER.validate_json(data.read_bytes()):
        if row.itemId == item_id:
            return row.blueprintBoxSize
    raise AssertionError(f"no row for item {item_id}")


def test_table_loads() -> None:
    buildings = catalog.all_buildings()
    assert len(buildings) > 50
    assert all(b.width >= 1 and b.height >= 1 for b in buildings)


def test_catalog_validates_bundled_building_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    malformed = tmp_path / "buildings.json"
    _ = malformed.write_text(
        json.dumps(
            [
                {
                    "prefab": "bad",
                    "itemId": 1,
                    "name": "Bad",
                    "modelIndex": "not-an-integer",
                }
            ]
        )
    )
    monkeypatch.setattr(catalog, "_DATA", malformed)
    catalog._load.cache_clear()

    with pytest.raises(ValueError, match="modelIndex"):
        _ = catalog.all_buildings()

    catalog._load.cache_clear()


def test_catalog_validates_bundled_slot_pose_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    malformed = tmp_path / "slot_poses.json"
    _ = malformed.write_text(
        json.dumps(
            {
                "bad": {
                    "slotPoses": [{"pos": [0.0, 0.0], "fwd": [0.0, 0.0, 1.0]}]
                }
            }
        )
    )
    monkeypatch.setattr(catalog, "_SLOT_POSES", malformed)
    catalog._load.cache_clear()

    with pytest.raises(ValueError, match="pos"):
        _ = catalog.all_buildings()

    catalog._load.cache_clear()


def test_catalog_validates_bundled_name_id_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    malformed = tmp_path / "recipes.json"
    _ = malformed.write_text(json.dumps([{"name": "Bad", "id": "not-an-integer"}]))
    monkeypatch.setattr(catalog, "_RECIPES", malformed)
    catalog._recipe_ids.cache_clear()

    with pytest.raises(ValueError, match="id"):
        _ = catalog.recipe_id("bad")

    catalog._recipe_ids.cache_clear()


@pytest.mark.parametrize(
    ("extent", "expected"),
    [
        # A tile is GRID_ARC = 1.2566 world units, so the tile centres a
        # half-extent `e` reaches are those with |k| * GRID_ARC < e.
        (3.82, 3),  # Assembling Machine -- 1.91 reaches 1.52 tiles
        (5.6, 5),  # Matrix Lab -- 2.80 reaches 2.23
        (2.9, 3),  # Arc Smelter
        (8.6, 7),  # Chemical Plant -- 4.30 reaches 3.42, so seven, not nine
        (7.8, 7),  # Oil Refinery, long axis -- 3.90 reaches 3.10
        (0.6, 1),  # Tesla Tower
        (4.5, 3),  # Fractionator / Storage Tank -- 2.25 reaches 1.79
        (11.7, 9),  # Energy Exchanger -- 5.85 reaches 4.66
        # An extent landing exactly on a tile centre does not cover it.
        (2 * colliders.GRID_ARC, 1),
        (4 * colliders.GRID_ARC, 3),
    ],
)
def test_derive_footprint(extent: float, expected: int) -> None:
    assert catalog.derive_footprint(extent) == expected


def test_the_footprint_rule_divides_by_the_tile_arc_not_by_one() -> None:
    """The regression this file exists to hold: a tile is not one world unit.

    The old rule was ``2 * ceil(extent / 2) - 1`` -- a world-unit half-extent
    compared against tile centres one unit apart, when they are ``GRID_ARC``
    apart.  It over-counted whenever the two divisors straddled a boundary,
    which is exactly where the Chemical Plant sits.  Breaking the fix by putting
    the 1.0 back turns each of these into the second number.
    """
    for extent, right, wrong_with_a_unit_tile in (
        (8.6, 7, 9),  # Chemical Plant
        (4.5, 3, 5),  # Fractionator, Storage Tank
        (11.7, 9, 11),  # Energy Exchanger
        (2.38, 1, 3),  # Splitter
        (6.9, 5, 7),  # Satellite Substation
    ):
        assert catalog.derive_footprint(extent) == right
        assert 2 * math.ceil(extent / 2.0 - 1e-9) - 1 == wrong_with_a_unit_tile


def test_the_footprint_rule_reads_colliders_not_blueprint_box_size() -> None:
    """The other half of the fix, and the corpus refutes the alternative.

    ``blueprintBoxSize`` is the game's own ``buildCollider.ext * 2`` for the
    LAST Build box, which for a prefab with three or more boxes is the box
    ``buildColliders`` excludes.  Dividing THAT by ``GRID_ARC`` makes an Oil
    Refinery 3x5 -- and ``factory-quick-start-step-3-red-cube`` puts sorter
    endpoints three tiles from a refinery's centre, which a 3x5 does not reach.
    """
    refinery = catalog.building(2308)
    box = _blueprint_box_size(refinery.item_id)
    assert box == pytest.approx((3.51, 7.2), abs=0.01)
    assert catalog.derive_footprint(box[1]) == 5, "the field itself would say 5"
    assert catalog.footprint(2308) == (3, 7), "the colliders say 7, and so does the corpus"
    # And the collider really is the longer of the two.
    assert colliders.own_centre_extent(refinery.model_index, 0.0)[1] == pytest.approx(7.8)


def test_the_corpus_puts_sorter_ends_three_tiles_from_an_oil_refinery_centre() -> None:
    """The measurement that refutes ``blueprintBoxSize``, on a blueprint the game wrote.

    ``factory-quick-start-step-3-red-cube`` holds twelve Oil Refineries on a
    clean lattice -- x in 5, 9, ... 25 and y in 2 or 14 -- and all eighteen
    machine-side sorter endpoints in it land **three tiles** from a refinery's
    centre along the building's own long axis.  A footprint of 3x5
    reaches two, so it would put all sixteen outside the machine they serve, and
    the game does not emit a sorter that misses its target.

    That fixture is not in ``test_local_offset.GEOMETRY_CORPUS`` -- it has 21
    off-grid entities and 9 collapsed cells at its edges, which disqualifies it
    from whole-blueprint geometry -- so this asks the narrower question the
    refineries themselves can answer, and it is the only evidence in the corpus
    that separates ``blueprintBoxSize`` (7.20, and so 5 tiles) from the
    ``buildColliders`` figure (7.80, and so 7).
    """
    bp = decode(
        (FIXTURES / "factory-quick-start-step-3-red-cube.txt").read_text(encoding="utf-8").strip()
    )
    belts = {
        (round(b.x), round(b.y), round(b.z))
        for b in bp.buildings
        if catalog.is_belt(b.item_id)
    }
    refineries = [
        (round(b.x), round(b.y), round(b.z), b.yaw)
        for b in bp.buildings
        if b.item_id == 2308
    ]
    machines = [
        (round(b.x), round(b.y), round(b.z))
        for b in bp.buildings
        if not catalog.is_belt(b.item_id) and not catalog.is_belt_integrated(b.item_id)
    ]
    assert len(refineries) == 12, len(refineries)

    local: list[tuple[int, int]] = []
    for b in bp.buildings:
        if not catalog.is_sorter(b.item_id):
            continue
        for px, py in ((b.x, b.y), (b.x2, b.y2)):
            cell = (round(px), round(py), round(b.z))
            if cell in belts:
                continue  # the belt-side end says nothing about the machine
            # Nearest machine by Manhattan distance; refineries sit four tiles
            # apart, so a Chebyshev tie would attribute an endpoint to the wrong
            # one of a neighbouring pair.
            near = min(machines, key=lambda m: abs(cell[0] - m[0]) + abs(cell[1] - m[1]))
            match = [r for r in refineries if (r[0], r[1], r[2]) == near]
            if not match:
                continue
            rx, ry, _rz, yaw = match[0]
            dx, dy = cell[0] - rx, cell[1] - ry
            for _ in range(int(round(yaw / 90.0)) % 4):
                dx, dy = dy, -dx
            local.append((dx, dy))

    assert len(local) == 18, local
    assert all(dy == -3 for _, dy in local), local
    assert max(abs(dy) for _, dy in local) == 3, local
    assert max(abs(dx) for dx, _ in local) <= 1, local
    w, h = catalog.footprint(2308)
    assert h // 2 >= 3, f"a {w}x{h} refinery cannot reach its own sorter endpoints"


def test_the_former_overrides_are_now_derived() -> None:
    """``_FOOTPRINT_OVERRIDES`` is gone because the corrected rule produces it.

    Both entries were corrections to the unit error, not to the data:

    * sorters -- a degenerate 0.52 x 0.23 collider, one tile per end;
    * Energy Exchanger -- 9x9, the value ``temple-of-effectiveness`` bounds it
      at, where the old rule derived 11x11 and put 209 cells on top of each
      other in a blueprint the game itself wrote.
    """
    assert not hasattr(catalog, "_FOOTPRINT_OVERRIDES")
    for sorter in (2011, 2012, 2013, 2014):
        assert catalog.footprint(sorter) == (1, 1)
    assert catalog.footprint(2209) == (9, 9)


def test_every_footprint_contains_every_slot_pose() -> None:
    """Occupancy and spacing are different questions; the poses arbitrate the first.

    A sorter attaches at a ``PrefabDesc.slotPoses`` position, and the layout
    looks for that pose on one of the building's own tiles.  A footprint that
    does not reach its own furthest pose would silently lose wiring options, so
    shrinking one is only safe while this holds.  It holds with room to spare
    nowhere: for the Assembling Machine, Matrix Lab, Oil Refinery and Miniature
    Particle Collider the poses land exactly on the edge tile.
    """
    for b in catalog.all_buildings():
        if not b.slot_poses:
            continue
        need_x = max(abs(p.dx) / colliders.GRID_ARC for p in b.slot_poses)
        need_y = max(abs(p.dy) / colliders.GRID_ARC for p in b.slot_poses)
        assert round(need_x) <= b.width // 2, f"{b.name}: pose at {need_x:.2f} tiles"
        assert round(need_y) <= b.height // 2, f"{b.name}: pose at {need_y:.2f} tiles"


def test_every_derived_footprint_is_odd() -> None:
    """Even footprints are geometrically impossible for integer-centred buildings.

    ``2 * ceil(e / GRID_ARC) - 1`` cannot return an even number, which is what
    keeps ``tile_to_local_offset``'s half-tile branch unreachable -- and the
    corpus insists on that: 3,038 of 3,038 buildings are integer-centred, so a
    building on a half-tile is geometry the game never writes.
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
        (2309, (7, 5)),  # Chemical Plant -- collider 8.60 reaches 3.42 tiles
        (2317, (7, 5)),  # Quantum Chemical Plant, same prefab geometry
        (2308, (3, 7)),  # Oil Refinery
        (2314, (3, 3)),  # Fractionator -- a 4.50 cube reaches 1.79 tiles
        (2106, (3, 3)),  # Storage Tank, likewise
        (2310, (9, 5)),  # Miniature Particle Collider, unchanged by the fix
        (2201, (1, 1)),  # Tesla Tower
        (2013, (1, 1)),  # Sorter Mk.III
        (2002, (1, 1)),  # Conveyor Belt Mk.II
        (2020, (1, 1)),  # Splitter -- `junction.make_splitter` forced this by hand
        (2313, (1, 3)),  # Spray Coater -- its tested box is 3.8, not the 2.0 claimed
    ],
)
def test_known_footprints(item_id: int, expected: tuple[int, int]) -> None:
    assert catalog.footprint(item_id) == expected


def test_spray_coater_occupies_no_tile() -> None:
    """It is a belt addon, which is what makes proliferation nearly area-free."""
    coater = catalog.building(catalog.SPRAY_COATER_ID)
    assert coater.is_belt_addon
    assert not coater.occupies_tiles


def test_spray_coater_addon_supply_pose_is_authoritative_and_exact() -> None:
    coater = catalog.building(catalog.SPRAY_COATER_ID)

    assert coater.slot_poses == ()
    assert catalog.addon_supply_pose(catalog.SPRAY_COATER_ID, area=0) == (
        catalog.AddonSupplyPose(Fraction(0), Fraction(0), Fraction(0), area=0)
    )
    assert catalog.addon_supply_pose(catalog.SPRAY_COATER_ID, area=1) == (
        catalog.AddonSupplyPose(
            Fraction(0),
            Fraction(-5, 4),
            Fraction(1),
            area=1,
        )
    )


def test_splitter_is_belt_integrated() -> None:
    """Splitters sit ON the belt line -- measured at dx=0.00, dy=0.00 from a belt."""
    assert catalog.is_belt_integrated(catalog.SPLITTER_ID)
    assert catalog.is_belt_integrated(2013)  # a sorter
    assert catalog.is_belt_integrated(2002)  # a belt
    assert not catalog.is_belt_integrated(2303)  # an assembler


def test_tesla_power_distances_track_the_extracted_game_table() -> None:
    tower = catalog.building(catalog.TESLA_TOWER_ID)
    assert tower.connect_distance == 22.5
    assert tower.cover_radius == 10.5
    # The link rule takes the larger of the two nodes' reaches, so a longer-range
    # node really does exist and really does out-reach the tower.
    wireless = catalog.building(2202)
    assert wireless.connect_distance > tower.connect_distance


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


# --- recipe and item id mapping --------------------------------------------


@pytest.mark.parametrize(
    ("factoriolab_id", "dsp_recipe_id"),
    [
        # Each pairing was verified by ingredient set, not name similarity.
        ("storage-1", 86),  # Depot Mk.I: Iron Ingot x4, Stone Brick x4
        ("storage-2", 91),  # Depot Mk.II: Steel x8, Stone Brick x8
        ("sorter-4", 160),  # Pile Sorter: Sorter Mk.III x2, Ring, Processor
        ("logistics-vessel", 96),  # Interstellar Logistics Vessel
        ("reforming-refine", 121),  # Reformed Refinement: oil x2 -> oil x3
    ],
)
def test_recipe_aliases_resolve(factoriolab_id: str, dsp_recipe_id: int) -> None:
    """FactorioLab ids whose DSP display name differs need an explicit alias.

    Without these the generator refuses to build anything using them, which is
    how a real user URL failed outright.
    """
    assert catalog.recipe_id(factoriolab_id) == dsp_recipe_id


@pytest.mark.parametrize(
    ("factoriolab_id", "dsp_item_id"),
    [
        ("storage-1", 2101),
        ("sorter-4", 2014),
        ("accumulator-full", 2207),
        ("critical-photon", 1208),
        # Raw vein items: these can arrive on an input belt, and an input belt
        # with no item id gets no marker icon.
        ("optical-grating-crystal", 1014),
        ("spiniform-stalagmite-crystal", 1015),
    ],
)
def test_item_aliases_resolve(factoriolab_id: str, dsp_item_id: int) -> None:
    assert catalog.get_item_id(factoriolab_id) == dsp_item_id


def test_every_dsp_recipe_is_reachable_by_its_factoriolab_id() -> None:
    """No DSP recipe should be stranded behind a name the mapping cannot form."""
    raw = _NAMED_ID_ROWS_ADAPTER.validate_json(catalog._RECIPES.read_bytes())
    known = catalog.known_recipe_ids()
    stranded = [row.name for row in raw if catalog._kebab(row.name) not in known]
    assert not stranded, f"DSP recipes no FactorioLab id reaches: {stranded}"


def test_mode_driven_recipes_explain_themselves() -> None:
    """A machine MODE is not a craft, but it is still buildable and must be belted.

    The error has to say that, because the earlier wording ("cannot appear in a
    blueprint") was wrong: charging takes empty Accumulators and produces full
    ones, which is an ordinary production step needing belts and sorters.
    """
    for factoriolab_id, entry in catalog.MODE_DRIVEN_MACHINE.items():
        with pytest.raises(KeyError) as excinfo:
            catalog.recipe_id(factoriolab_id)
        message = str(excinfo.value)
        assert entry.machine_name in message
        assert entry.mode in message
        assert "belted" in message


def test_dark_fog_drops_are_reported_as_unbuildable() -> None:
    with pytest.raises(KeyError, match="Dark Fog drop"):
        catalog.recipe_id("df-corvette")


def test_unknown_recipe_points_at_the_alias_table() -> None:
    with pytest.raises(KeyError, match="_RECIPE_ALIASES"):
        catalog.recipe_id("not-a-real-recipe")


def test_table_covers_every_recipe_real_blueprints_use() -> None:
    """Real game blueprints are ground truth for what the table must contain.

    A recipe id appearing in a working blueprint that the table does not know
    means the extraction missed something -- which no amount of internal
    consistency would reveal.
    """
    known = {
        row.id
        for row in _NAMED_ID_ROWS_ADAPTER.validate_json(catalog._RECIPES.read_bytes())
    }
    used: set[int] = set()
    for path in sorted(pathlib.Path("tests/fixtures").glob("*.txt")):
        try:
            blueprint = decode(path.read_text().strip())
        except Exception:  # noqa: BLE001 - the DYBP negative fixture is meant to fail
            continue
        used.update(b.recipe_id for b in blueprint.buildings if b.recipe_id)
    assert used, "no recipe ids found in the fixture corpus; the check is vacuous"
    unknown = sorted(used - known)
    assert not unknown, f"recipe ids in real blueprints but not in our table: {unknown}"


class TestBeltAltitudeRulesComeFromTheGame:
    """The altitude numbers are read out of `Assembly-CSharp`, not the corpus.

    The corpus said the ceiling was 1.0, because that is what its builders
    happened to do.  The game says a new save allows 8.55 and the user's allows
    38.55.  Reading a habit as a limit is the mistake these tests exist to stop
    from coming back.
    """

    def test_the_ceiling_is_the_games_formula_not_the_corpus_habit(self) -> None:
        """``buildMaxHeight = labLevel*4 - 0.6`` world, times 3/4 for blueprint z."""
        assert catalog.belt_max_z(3) == Fraction(171, 20)  # 8.55, a new save
        assert catalog.belt_max_z(13) == Fraction(771, 20)  # 38.55
        # At lab 15 the formula changes branch: labLevel*4 + 4.
        assert catalog.belt_max_z(15) == Fraction(48)
        assert catalog.belt_max_z(
            catalog.DEFAULT_LAB_LEVEL
        ) == catalog.DEFAULT_MAX_BELT_Z
        assert catalog.DEFAULT_MAX_BELT_Z > 1, (
            "a ceiling of 1 is the corpus habit, not the game's rule"
        )

    def test_the_user_max_height_blueprint_fits_its_save(self) -> None:
        """The independent check on both the formula and the 3/4 conversion.

        The user built to z=38.  That needs lab level 13 and no more, which is
        the only reason to believe the world->blueprint factor is right.
        """
        assert catalog.belt_max_z(13) >= 38
        assert catalog.belt_max_z(12) < 38

    def test_the_ramp_we_emit_is_inside_the_games_slope_limit(self) -> None:
        """0.5 of blueprint z per tile is a world slope of 2/3, against 4/5."""
        ramp = catalog.BELT_CLIMB_PER_TILE / catalog.BELT_Z_PER_WORLD_UNIT
        assert ramp == Fraction(2, 3)
        assert ramp <= catalog.MAX_BELT_SLOPE

    def test_the_step_we_shipped_is_outside_it(self) -> None:
        """A whole level across one tile is 4/3, which the game calls TooSteep."""
        shipped = Fraction(1) / catalog.BELT_Z_PER_WORLD_UNIT
        assert shipped == Fraction(4, 3)
        assert shipped > catalog.MAX_BELT_SLOPE


class TestBeltRulesComeFromTheUrlsTechnologies:
    """How high a belt may go is a property of the SAVE, so FactorioLab owns it.

    It records the researched set in the URL already, and this project's rule is
    that FactorioLab's answer is authoritative rather than re-derived or asked
    for on the command line.
    """

    @staticmethod
    def _all() -> set[str]:
        from flab2bp.lab.data import load_vendored

        return {i.id for i in load_vendored().items if i.technology is not None}

    def test_absence_means_factoriolabs_default_not_a_new_save(self) -> None:
        """`None` is "the URL said nothing", and FactorioLab answers that with
        EVERY technology -- `computeSettings` starts from `data.technologyIds`
        and only narrows when a set was supplied.

        Reading absence as emptiness here refused 19 of 72 audit cells for want
        of a slope unlock the player had.  Same defect as the stone bug in
        `60d5f0f`.
        """
        r = catalog.belt_rules_for_technologies(None, self._all())
        assert r.from_url is False
        assert r.vertical_construction is True, (
            "an absent tech set must not be read as a save with nothing researched"
        )
        assert r.lab_level > catalog.DEFAULT_LAB_LEVEL
        assert r.max_z > catalog.belt_max_z(catalog.DEFAULT_LAB_LEVEL)

    def test_an_explicit_empty_set_is_a_save_with_nothing_researched(self) -> None:
        """Emptiness IS honoured -- it is only absence that means the default."""
        r = catalog.belt_rules_for_technologies(set(), self._all())
        assert r.from_url is True
        assert r.vertical_construction is False
        assert r.lab_level == catalog.DEFAULT_LAB_LEVEL
        assert r.max_z == catalog.belt_max_z(catalog.DEFAULT_LAB_LEVEL)

    def test_the_slope_unlock_is_super_magnetic_field_generator(self) -> None:
        """From the locale: TooSteep hints "Need to unlock Super Magnetic Field
        Generator", not Vertical Construction."""
        without = catalog.belt_rules_for_technologies(
            {"vertical-construction-1"}, self._all()
        )
        assert without.vertical_construction is False
        with_it = catalog.belt_rules_for_technologies(
            {"super-magnetic-field-generator"}, self._all()
        )
        assert with_it.vertical_construction is True

    def test_vertical_construction_levels_raise_the_ceiling(self) -> None:
        base = catalog.belt_rules_for_technologies(set(), self._all())
        assert base.lab_level == 3
        three = catalog.belt_rules_for_technologies(
            {f"vertical-construction-{n}" for n in (1, 2, 3)}, self._all()
        )
        assert three.lab_level == 6
        assert three.max_z > base.max_z
        assert three.from_url is True

    def test_a_real_url_technology_set_reaches_the_rules(self) -> None:
        """The whole path: `tre=` in the URL -> decoded ids -> altitude rules.

        The unit tests above would still pass if `parse_url` never decoded
        `tre`, which it only does because `tre` is in `_SUBSET_KEYS` and that
        makes it load the hash tables.  This asserts the join actually holds.
        """
        from flab2bp.lab import params as P
        from flab2bp.lab.data import load_vendored_hash_index
        from flab2bp.lab.url import parse_url

        techs = load_vendored_hash_index().technologies
        wanted = [
            "super-magnetic-field-generator",
            "vertical-construction-1",
            "vertical-construction-2",
        ]
        tre = P.ZFIELDSEP.join(P.n_to_id(techs.index(t)) for t in wanted)
        req = parse_url(
            f"https://factoriolab.github.io/dsp/list?o=processor*60&tre={tre}&v=11"
        )
        assert req.researched_technology_ids == set(wanted)

        rules = catalog.belt_rules_for_technologies(
            req.researched_technology_ids, self._all()
        )
        assert rules.from_url is True
        assert rules.vertical_construction is True
        assert rules.lab_level == 5  # 3 base + 2 vertical-construction levels
        assert rules.max_z == catalog.belt_max_z(5)

    def test_a_corpus_url_without_tre_gets_the_full_tech_set(self) -> None:
        """None of the 12 corpus URLs carry `tre`, and they must not be
        penalised for it."""
        from flab2bp.lab.url import parse_url

        req = parse_url("https://factoriolab.github.io/dsp/list?o=processor*60&v=11")
        assert req.researched_technology_ids is None
        rules = catalog.belt_rules_for_technologies(
            req.researched_technology_ids, self._all()
        )
        assert rules.from_url is False
        assert rules.vertical_construction is True


def test_oriented_footprint_swaps_only_on_a_quarter_turn() -> None:
    """A rotated building's extents swap; a half turn's do not.

    Real blueprints record yaws like 355.5 and -6.7e-07 for what is plainly
    zero, so the turn is snapped rather than trusted.
    """
    assert catalog.oriented_footprint(2308, 0.0) == (3, 7)
    assert catalog.oriented_footprint(2308, 90.0) == (7, 3)
    assert catalog.oriented_footprint(2308, 180.0) == (3, 7)
    assert catalog.oriented_footprint(2308, 270.0) == (7, 3)
    assert catalog.oriented_footprint(2308, -6.7e-07) == (3, 7)
    assert catalog.oriented_footprint(2308, 355.5) == (3, 7)


def test_every_oriented_footprint_stays_odd() -> None:
    """Rotation cannot make an even extent, so the centre stays on a tile.

    `tile_to_local_offset` is exact only for odd footprints, and its even branch
    is unreachable -- which stays true only if rotating cannot reach it either.
    """
    for b in catalog.all_buildings():
        for yaw in (0.0, 90.0, 180.0, 270.0):
            w, h = catalog.oriented_footprint(b.item_id, yaw)
            assert w % 2 == 1 and h % 2 == 1, (b.name, yaw, w, h)


def test_clearance_exceeds_the_footprint_exactly_where_the_collider_does() -> None:
    """An Assembling Machine covers 3 tiles and needs 4.

    Its collider is 3.82 world units and a tile is 1.2566, so 3 tiles is 3.77
    and two of them at that pitch intersect -- which is what `geom.collide`
    reported 443 times. A Depot's collider is exactly 3.00 and fits.
    """
    assert catalog.oriented_footprint(2303, 0.0) == (3, 3)
    assert catalog.clearance(2303, 0.0) == (4, 4)
    assert catalog.clearance(2101, 0.0) == (3, 3)  # Depot Mk.I, 3.00 units


def test_clearance_uses_non_footprint_collider_extent() -> None:
    """Collider clearance must not silently collapse to the footprint."""
    item_id = 2303  # Assembling Machine Mk.II
    assert catalog.oriented_footprint(item_id, 0.0) == (3, 3)
    assert colliders.own_centre_extent(
        catalog.building(item_id).model_index, 0.0
    ) == pytest.approx((3.82, 3.82))
    assert catalog.clearance(item_id, 0.0) == (4, 4)
    for b in catalog.all_buildings():
        cw, ch = catalog.clearance(b.item_id, 0.0)
        fw, fh = catalog.oriented_footprint(b.item_id, 0.0)
        assert cw >= fw and ch >= fh, b.name


def test_clearance_is_measured_on_the_rotated_collider() -> None:
    """And for every shipped building that happens to equal swapping the two.

    The tested box turns with the building, so a box not centred on the
    building's own origin does not have swappable extents in general.  Measuring
    the turn is therefore the correct thing to do -- but NO building in the
    catalog distinguishes it from a swap, because the extent is taken
    symmetrically about the origin and that absorbs any offset.  Stated rather
    than left as a mutation that survives: a future building can separate them,
    and this is the test that would notice.
    """
    for b in catalog.all_buildings():
        w, h = catalog.clearance(b.item_id, 0.0)
        assert catalog.clearance(b.item_id, 90.0) == (h, w), b.name
        assert catalog.clearance(b.item_id, 180.0) == (w, h), b.name


# --- belt ports -------------------------------------------------------------


def test_port_poses_and_the_raw_slot_table_agree_everywhere() -> None:
    """Two readings of one array, and they must not drift.

    ``Building.slots`` is ``buildings.json``'s raw ``x/y/z/yaw`` dicts;
    ``Building.port_poses`` is ``slot_poses.json``'s ``portPoses`` with Unity's
    axes mapped and each pose's forward attached.  They come from two extracted
    files and describe the same ``SlotConfig.slotPoses`` array, so a count that
    differs means one of the two extractions has gone stale.
    """
    bad = [
        (b.prefab, len(b.slots), len(b.port_poses))
        for b in catalog.all_buildings()
        if len(b.slots) != len(b.port_poses)
    ]
    assert not bad, bad


def test_the_port_array_and_the_insert_array_are_disjoint() -> None:
    """No building offers both a belt port and a sorter slot.

    Not assumed anywhere -- ``Strip.takes_belt_ports`` asks both questions
    rather than one -- but it is the fact that makes the two arrays safe to
    claim from ONE map: the game addresses a connection as
    ``entityConnPool[objId * 16 + slot]``, so port 0 and insert pose 0 of the
    same building would be the same cell.
    """
    both = [b.prefab for b in catalog.all_buildings() if b.port_poses and b.slot_poses]
    assert not both, both


def test_the_ray_receiver_takes_belts_and_no_sorter() -> None:
    """The prefab behind every ``universe-matrix`` refusal.

    ``ray-receiver`` carries exactly one ``SlotConfig`` on the prefab root, with
    ``insertPoses`` of length ZERO and two ``portPoses`` named ``slot-0`` and
    ``slot-1``, at model ``(0, 0, +-1.41)``.  ``PrefabDesc.slotPoses`` IS
    ``SlotConfig.insertPoses``, and ``BuildTool_Inserter`` drops any cast target
    with none of those, so no sorter attaches to one on any face at any distance.
    """
    info = catalog.building(catalog.RAY_RECEIVER_ID)
    assert info.slot_poses == ()
    assert info.takes_belt_ports
    assert [(round(p.dx, 3), round(p.dy, 3)) for p in info.port_poses] == [
        (0.0, 1.41),
        (0.0, -1.41),
    ]
    assert [(round(p.fx, 3), round(p.fy, 3)) for p in info.port_poses] == [
        (0.0, 1.0),
        (0.0, -1.0),
    ]


def test_the_belt_port_class_is_the_nine_zero_pose_buildings_plus_the_stations() -> None:
    """Which buildings a belt docks into, listed rather than described.

    Every one of these has ZERO insert poses, so a sorter cannot touch it, and
    every one has at least one port.  Pinned because ``freeform._dock_lane``
    serves the CLASS and not the Ray Receiver: a building that quietly joined or
    left it would change what the layout can build without anything saying so.
    """
    ported = sorted(
        b.prefab
        for b in catalog.all_buildings()
        if b.port_poses and b.occupies_tiles and b.item_id != catalog.SPLITTER_ID
    )
    assert ported == [
        "energy-exchanger",
        "fractionator",
        "interstellar-logistic-station",
        "logistic-station",
        "mining-drill",
        "mining-drill-mk2",
        "oil-extractor",
        "piler",
        "ray-receiver",
        "storage-tank",
        "water-pump",
    ]


def test_the_poseless_buildings_a_spec_group_can_reach() -> None:
    """Every recipe producer with no sorter pose remains an explicit refusal."""
    from flab2bp.lab.data import load_vendored

    machine_ids = {
        item_id
        for recipe in load_vendored().recipes
        for producer in recipe.producers
        if (item_id := catalog.get_item_id(producer)) is not None
    }
    machine_ids.update(
        entry.machine_item_id for entry in catalog.MODE_DRIVEN_MACHINE.values()
    )
    poseless = sorted(
        catalog.building(item_id).prefab
        for item_id in machine_ids
        if not catalog.building(item_id).slot_poses
    )
    assert poseless == [
        "energy-exchanger",
        "fractionator",
        "mining-drill",
        "mining-drill-mk2",
        "oil-extractor",
        "orbital-collector",
        "ray-receiver",
        "water-pump",
    ]
    assert not catalog.building(
        catalog.item_id("orbital-collector")
    ).takes_belt_ports, "an Orbital Collector is fed in orbit, not by belt"
    assert all(b.prefab != "ray-receiver-pro" for b in catalog.all_buildings())


def test_belt_rate_matches_the_dataset_belt_speed() -> None:
    """``retier_belts`` measures demand against the dataset; the validator judges
    capacity against ``catalog.BELT_RATE``.  They must never disagree, or a
    dataset bump could desync the pass from the judge without either side
    noticing.
    """
    from flab2bp.lab.data import load_vendored

    dataset = load_vendored()
    checked = 0
    for item in dataset.items:
        if item.belt is None:
            continue
        item_id = catalog.get_item_id(item.id)
        assert item_id is not None, item.id
        assert catalog.BELT_RATE[item_id] == dataset.belt_speed(item.id)
        checked += 1
    assert checked, "the vendored dataset must have at least one belt item"


# --- cargo stacking --------------------------------------------------------
#
# Every table entry is pinned as a LITERAL below, so a change to
# ``data/stacking.json`` fails here rather than silently retiming a plan.  The
# numbers are the game's; ``docs`` for where each one was read out of the
# decompiled ``Assembly-CSharp`` lives in the JSON's ``*_source`` fields and in
# `.superpowers/sdd/2026-09-02-multiple-belts-and-pilers/task-6b-report.md`.

#: DSP item ids for the four sorter tiers, grade 1 to grade 4.
_SORTER_MK1, _SORTER_MK2, _SORTER_MK3, _PILE_SORTER = 2011, 2012, 2013, 2014


def test_sorter_stacking_levels_is_the_live_research_ladder() -> None:
    assert catalog.SORTER_STACKING_LEVELS == 6


@pytest.mark.parametrize(
    ("item_id", "picks", "places"),
    [
        (_SORTER_MK1, (1, 1, 1, 1, 1, 1, 1), (1, 1, 1, 1, 1, 1, 1)),
        (_SORTER_MK2, (1, 1, 1, 1, 1, 1, 1), (1, 1, 1, 1, 1, 1, 1)),
        (_SORTER_MK3, (1, 1, 1, 1, 1, 1, 1), (1, 1, 1, 1, 1, 1, 1)),
        (_PILE_SORTER, (2, 2, 3, 3, 4, 4, 4), (1, 2, 2, 3, 3, 4, 4)),
    ],
)
def test_sorter_stack_tables_are_pinned(
    item_id: int, picks: tuple[int, ...], places: tuple[int, ...]
) -> None:
    """Every level of every tier, as a literal.

    Only the Pile Sorter moves.  Mk.III reads ``inserterStackCountObsolete``,
    whose only writers are the ``IsObsolete`` techs 3301-3305 and the new-game
    baseline of 1, so on this build it never leaves 1.
    """
    got_picks = tuple(
        catalog.sorter_pick_stack(item_id, level)
        for level in range(catalog.SORTER_STACKING_LEVELS + 1)
    )
    got_places = tuple(
        catalog.sorter_place_stack(item_id, level)
        for level in range(catalog.SORTER_STACKING_LEVELS + 1)
    )
    assert got_picks == picks
    assert got_places == places


def test_the_pile_sorter_answers_its_own_entry() -> None:
    """2014 is the one tier whose stacking is not the shared table."""
    assert catalog.sorter_pick_stack(_PILE_SORTER, 0) == 2
    assert catalog.sorter_pick_stack(_SORTER_MK3, 0) == 1
    assert catalog.sorter_place_stack(_PILE_SORTER, 6) == 4
    assert catalog.sorter_place_stack(_SORTER_MK3, 6) == 1


def test_sorter_stack_rejects_an_unknown_tier_or_level() -> None:
    with pytest.raises(ValueError, match="not a sorter"):
        catalog.sorter_pick_stack(catalog.SPLITTER_ID, 0)
    with pytest.raises(ValueError, match="not a sorter"):
        catalog.sorter_place_stack(catalog.SPLITTER_ID, 0)
    with pytest.raises(ValueError, match="outside 0"):
        catalog.sorter_pick_stack(_PILE_SORTER, catalog.SORTER_STACKING_LEVELS + 1)
    with pytest.raises(ValueError, match="outside 0"):
        catalog.sorter_place_stack(_PILE_SORTER, -1)


def test_sorter_stack_rate_factor_is_pinned() -> None:
    assert catalog.SORTER_STACK_RATE_FACTOR is True


def test_piler_facts_are_pinned() -> None:
    assert catalog.PILER_MAX_STACK == 4
    assert catalog.PILER_SINGLE_PASS is False
    assert Fraction(6) == catalog.PILER_THROUGHPUT
    assert catalog.PILER_STACK_PARAMETER is None


def test_one_piler_does_not_reach_max_stack_from_an_unstacked_belt() -> None:
    """The consequence of ``PILER_SINGLE_PASS`` being False, as a number.

    ``PilerComponent`` merges at most the two cargos it has cached, so it
    doubles; 1 -> 2 -> 4 needs two pilers in series.
    """
    assert catalog.piler_output_stack(1) == 2
    assert catalog.piler_output_stack(2) == 4
    assert catalog.piler_output_stack(3) == catalog.PILER_MAX_STACK
    assert catalog.piler_output_stack(4) == catalog.PILER_MAX_STACK
    assert not catalog.PILER_SINGLE_PASS
    with pytest.raises(ValueError, match="at least 1"):
        catalog.piler_output_stack(0)


def test_piler_throughput_is_the_belt_rate_it_sits_on() -> None:
    """``PILER_THROUGHPUT`` is cargo/s per unit of ``PrefabDesc.beltSpeed``.

    Multiplying by the three tiers' belt speeds must reproduce
    :data:`catalog.BELT_RATE` exactly -- that identity is the whole reason the
    constant is stored per unit speed rather than as one belt's number, and it
    is the arithmetic form of "a piler never throttles the belt".
    """
    for item_id, belt_speed in ((2001, 1), (2002, 2), (2003, 5)):
        assert catalog.PILER_THROUGHPUT * belt_speed == catalog.BELT_RATE[item_id]


def test_stacking_json_sources_every_number() -> None:
    """No fact may arrive without saying which file and line it came from."""
    payload = json.loads(
        (pathlib.Path(catalog.__file__).parent / "data" / "stacking.json").read_text()
    )
    assert payload["source"]["game_version"] == "0.10.34"
    assert payload["source"]["assembly"] == "Assembly-CSharp.dll"
    sorter = payload["sorter_cargo_stacking"]
    assert "GameData.OnInserterTechChange" in sorter["applies_to"]["grade_rule_source"]
    assert "TechProtoSet 3311-3316" in sorter["pile_sorter"]["level_source"]
    assert "PilerComponent.cs:195-207" in payload["piler"]["max_stack_source"]
    assert "PilerComponent.cs:161-169" in payload["piler"]["single_pass_source"]
    assert "PilerDesc declares no fields" in payload["piler"]["parameter_index_source"]
    assert "BuildingParameters" in payload["piler"]["parameter_index_source"]


class _TechRow(TypedDict):
    """One row of ``data/stacking_techs.json``, as the extractor writes it."""

    ID: int
    Name: str
    Level: int
    MaxLevel: int
    IsObsolete: int
    UnlockFunctions: list[int]
    UnlockValues: list[float]
    UnlockRecipes: list[int]
    PropertyOverrideItems: list[int]
    englishName: str


def _stacking_techs() -> dict[int, _TechRow]:
    """``data/stacking_techs.json`` keyed by tech id."""
    rows = json.loads(
        (
            pathlib.Path(catalog.__file__).parent / "data" / "stacking_techs.json"
        ).read_text()
    )
    by_id: dict[int, _TechRow] = {row["ID"]: row for row in rows}
    assert sorted(by_id) == [3301, 3302, 3303, 3304, 3305, 3306,
                             3311, 3312, 3313, 3314, 3315, 3316]
    return by_id


def test_only_the_pile_sorter_ladder_is_a_reachable_research_ladder() -> None:
    """The fact ``SORTER_STACKING_LEVELS == 6`` rests on.

    ``IsObsolete`` is what hides a tech from the tree (``UITechNode.cs:914``)
    and from the unlock-everything achievement (``ACH_UnlockAllTech.cs:37``).
    3301-3306 carry it, so ``inserterStackCountObsolete`` never leaves its
    new-game 1 and Sorter Mk.III stacks nothing; 3311-3316 do not, and they are
    the six levels the catalog exposes.  If a game patch ever un-obsoletes the
    old ladder this fails, which is the whole reason the field is extracted.
    """
    by_id = _stacking_techs()
    obsolete = {tech_id for tech_id, row in by_id.items() if row["IsObsolete"]}
    assert obsolete == {3301, 3302, 3303, 3304, 3305, 3306}
    assert sorted(set(by_id) - obsolete) == [3311, 3312, 3313, 3314, 3315, 3316]
    assert len(by_id) - len(obsolete) == catalog.SORTER_STACKING_LEVELS


def test_stacking_techs_table_is_the_provenance_for_the_level_tables() -> None:
    """``stacking_techs.json`` is what the extractor read; the level tables must
    be derivable from it, so a re-extraction that changes the game's unlock
    values fails here instead of silently disagreeing with ``stacking.json``.
    """
    by_id = _stacking_techs()

    # GameHistoryData.SetForNewGame (:554-557).
    pick, place = 2, 1
    picks, places = [pick], [place]
    for tech_id in (3311, 3312, 3313, 3314, 3315, 3316):
        row = by_id[tech_id]
        for func, value in zip(row["UnlockFunctions"], row["UnlockValues"], strict=True):
            if func == 41:  # inserterStackInput
                pick = int(value)
            elif func == 39:  # inserterStackOutput
                place = int(value)
        picks.append(pick)
        places.append(place)

    assert picks == [
        catalog.sorter_pick_stack(_PILE_SORTER, level)
        for level in range(catalog.SORTER_STACKING_LEVELS + 1)
    ]
    assert places == [
        catalog.sorter_place_stack(_PILE_SORTER, level)
        for level in range(catalog.SORTER_STACKING_LEVELS + 1)
    ]
