"""Ground-truth checks on the DSP building catalog.

The load-bearing test here is :func:`test_safe_fixtures_have_no_overlaps`, which
replays real game blueprints through the footprint table.  The game cannot
produce an overlapping blueprint, so any overlap it reports is a wrong table.
"""

from __future__ import annotations

import collections
import pathlib
from fractions import Fraction

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


def test_tesla_link_distance_tracks_the_extracted_game_table() -> None:
    """The constant must be the game's ``connectDistance``, not a hand-typed guess.

    See the note on :data:`catalog.TESLA_LINK_DISTANCE` for why 22.5 is a
    centre-to-centre *distance* and not half of one: the game's own
    ``PowerSystem.OnNodeAdded`` compares squared node separation against
    ``max(a.connDistance2, b.connDistance2)``, where ``connDistance2`` is this
    field squared.  The corpus cannot discriminate 22.5 from 11.25, so tying the
    constant to the extracted table is the only check available here.
    """
    tower = catalog.building(catalog.TESLA_TOWER_ID)
    assert tower.connect_distance == catalog.TESLA_LINK_DISTANCE
    assert tower.cover_radius == catalog.TESLA_COVER_RADIUS
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
    import json

    raw = json.loads((catalog._RECIPES).read_text())
    known = catalog.known_recipe_ids()
    stranded = [r["name"] for r in raw if catalog._kebab(r["name"]) not in known]
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
    import json

    known = {r["id"] for r in json.loads((catalog._RECIPES).read_text())}
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
