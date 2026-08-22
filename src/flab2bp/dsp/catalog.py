"""Ground-truth DSP building geometry and constants.

Everything here was extracted from the game's own assets and then validated
against the 11 real blueprints in ``tests/fixtures``.  Where the two disagreed,
the fixtures won.

Footprints
----------
A building's grid footprint is **derived**, not tabulated: it is the set of tiles
whose *centres* the build collider covers.  DSP tile centres sit on integers, so
for a building centred at integer ``c`` with collider half-extent ``e`` the
occupied tiles are those ``k`` with ``|k - c| < e``, giving

    width = 2 * ceil(blueprintBoxSize / 2) - 1

which is **always odd**.  See :func:`derive_footprint`.

That oddness is not an artifact of the formula -- it is forced by the data.
Across the whole fixture corpus every production building is integer-centred
(Assembling Machine Mk.III 196/196, Matrix Lab 131/131, Negentropy Smelter
100/100, Splitter 25/25, and belts 5729/5866), with not one on a half-integer.
An even-width building centred on an integer would straddle tile boundaries, so
an even footprint is geometrically impossible for anything the corpus contains.

This corrects a earlier table that rounded the collider extent to nearest
(Assembling Machine 4x4, Matrix Lab 6x6, Chemical Plant 8x5).  Rounding is wrong
in both directions -- the assembler is really 3x3 and the chemical plant really
9x5 -- so it was not a uniform off-by-one.

.. warning::
   **Never pool fixtures across game versions for geometric validation, and
   never use polar or whole-planet blueprints for it at all.**  Two convincing
   false readings came out of doing so: a Matrix Lab that "measured" 5 tiles
   wide (a 0.8.19 fixture), and a Solar Panel that "measured" 0.075 (a
   whole-planet blueprint, where longitude is latitude-compressed: x-steps of
   4.0 at y=8 but 1.8 at y=17).  Only the two fixtures in
   ``GEOMETRY_SAFE_FIXTURES`` are usable, and both validate at zero overlaps.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from fractions import Fraction
from functools import cache
from pathlib import Path

_DATA = Path(__file__).parent / "data" / "buildings.json"


# --- id ranges -------------------------------------------------------------
# Confirmed against the fixture corpus and the viewer's decoder.

BELT_IDS = range(2001, 2010)
SORTER_IDS = range(2011, 2020)
SPLITTER_ID = 2020
SPRAY_COATER_ID = 2313
FRACTIONATOR_ID = 2314
TESLA_TOWER_ID = 2201


def is_belt(item_id: int) -> bool:
    return item_id in BELT_IDS


def is_sorter(item_id: int) -> bool:
    return item_id in SORTER_IDS


#: Buildings that share a tile with the belt they serve rather than reserving
#: their own.  Sorters straddle their two endpoints; splitters sit *on* the belt
#: line -- measured at dx=0.00, dy=0.00 from a belt in the corpus, i.e. exactly
#: co-located.  A tile-occupancy overlap check must exclude these or it reports
#: violations in blueprints the game itself produced.
BELT_INTEGRATED_IDS = frozenset(BELT_IDS) | frozenset(SORTER_IDS) | {SPLITTER_ID}


def is_belt_integrated(item_id: int) -> bool:
    return item_id in BELT_INTEGRATED_IDS


# --- sorters ---------------------------------------------------------------

#: Maximum sorter span in tiles.  Measured over all 1,288 sorters in the fixture
#: corpus: spans cluster at 1, 2 and 3 with nothing at 4.  Critically this is
#: **not tier-dependent** -- Mk.I reaches 3.4 while Mk.II tops out at 2.2 in the
#: corpus, which shows the cap belongs to sorters generally and Mk.II simply is
#: not used at full stretch there.
SORTER_MAX_REACH = 3

#: Items/second at a span of one tile, by item id.  Derived from
#: ``stackSize / (2 * sttf * d)``, which reproduces the published DSP figures
#: exactly.  Divide by span to get the rate at distance.
SORTER_RATE_AT_1 = {
    2011: Fraction(3, 2),   # Sorter Mk.I
    2012: Fraction(3),      # Sorter Mk.II
    2013: Fraction(6),      # Sorter Mk.III
    2014: Fraction(20),     # Pile Sorter
}

#: Sorters never span altitudes.  ``z2 - z`` is exactly 0.0 for all 1,288
#: sorters in the corpus, across five game versions and ten builders, including
#: blueprints that stack belts.  Treated as a hard constraint; it fails safe.
SORTER_SPANS_ALTITUDE = False


def sorter_rate(item_id: int, span: int) -> Fraction:
    """Items/second a sorter of this tier sustains across ``span`` tiles."""
    if span < 1 or span > SORTER_MAX_REACH:
        raise ValueError(f"span {span} outside 1..{SORTER_MAX_REACH}")
    return SORTER_RATE_AT_1[item_id] / span


# --- belts -----------------------------------------------------------------

BELT_RATE = {
    2001: Fraction(6),
    2002: Fraction(12),
    2003: Fraction(30),
}

#: Belts climb 0.5 per tile, so changing altitude by one level costs 2 tiles.
#: Measured over 7,502 belt records: +/-0.5 appears 125 times along belt chains
#: versus +/-1.0 only 7 times.  Levels themselves are spaced 1.0 apart.
BELT_CLIMB_PER_TILE = Fraction(1, 2)
RAMP_TILES_PER_LEVEL = 2

#: Up to three belts share one (x, y): 426 positions in the corpus carry 2 and
#: 21 carry 3.  Terrain jitter of ~0.03 rides on top and must be denoised with
#: ``round(z * 2) / 2``.
MAX_BELT_STACK_LEVELS = 3


# --- power -----------------------------------------------------------------

#: Tesla Tower supply **radius** in tiles -- not a diameter.  Settled two ways.
#: Game data: ``PrefabDesc.powerCoverRadius`` <- ``PowerDesc.coverRadius`` =
#: 10.5, with no ``coverArea``/``Diameter`` field existing in either struct.
#: Empirically: across working published blueprints, 94 machines sit farther
#: than 5.25 from their nearest tower (which the diameter reading would leave
#: unpowered) and *zero* machines anywhere exceed 10.5.  Bracketed both sides.
TESLA_COVER_RADIUS = Fraction(21, 2)

#: Tower-to-tower link distance.  NOT independently pinned: the largest tower
#: nearest-neighbour distance on a uniform grid is 11.00, which fits both
#: 22.5-as-radius and 11.25-as-diameter -- only 2.2% apart, so the corpus cannot
#: discriminate.  This rides on field naming plus its proven-radius sibling.  It
#: fails *visibly* (a disconnected network) rather than silently, but if the
#: solver ever spaces towers 11.25--22.5 apart, that wants an in-game check.
TESLA_LINK_DISTANCE = Fraction(45, 2)

#: Belts are unpowered in DSP.  Sorters and spray coaters are not.
UNPOWERED_ITEM_IDS = frozenset(BELT_IDS)


# --- fixtures safe for geometric validation --------------------------------

#: The only fixtures whose geometry can be trusted.  Selected by measurement,
#: not by game version: in each, every machine is integer-centred and every yaw
#: is cardinal, so no latitude compression is present.  Both validate at zero
#: overlaps under the derived footprints.
#:
#: ``factory-heretical-smelter-block`` looks eligible (all 108 machines are
#: integer-centred) but is NOT: 11 of its buildings carry non-cardinal yaw and
#: 376 of its 591 buildings are off the half-grid, so it is latitude-distorted
#: despite being 0.10.34.  Version is the wrong criterion; alignment is the
#: right one.
GEOMETRY_SAFE_FIXTURES = (
    "factory-quick-start-step-1-minimum-blue-cube-automation",
    "factory-quick-start-step-3-red-cube",
)

#: Buildings whose extracted collider does not reproduce real blueprints, all of
#: them large and none of them placed by the generator.  Their footprints are
#: the derived value but should not be trusted without an in-game check: the
#: corpus shows Interstellar Logistics Station, Energy Exchanger, Artificial
#: Star, Satellite Substation, Wind Turbine, Solar Panel and Depot overlapping
#: their neighbours.  Most such evidence comes from distorted fixtures, so this
#: may be measurement error rather than a wrong table -- but it is unresolved.
LOW_CONFIDENCE_FOOTPRINTS = frozenset({2101, 2104, 2203, 2205, 2209, 2210, 2212})


# --- recipes ---------------------------------------------------------------

_RECIPES = Path(__file__).parent / "data" / "recipes.json"

#: DSP spells building tiers "Mk.I/II/III" where FactorioLab uses "-1/-2/-3".
_ROMAN_TIERS = {"mk-i": "1", "mk-ii": "2", "mk-iii": "3", "mki": "1", "mkii": "2", "mkiii": "3"}

#: FactorioLab ids whose DSP counterpart carries a different display name, so
#: :func:`_kebab` cannot reach it.  Each pairing was verified by ingredient set
#: rather than by name similarity -- a name match alone would be a guess, and a
#: wrong recipe id produces a blueprint that pastes cleanly and builds the wrong
#: thing:
#:
#:   storage-1         Iron Ingot x4, Stone Brick x4        == DSP 86  Depot Mk.I
#:   storage-2         Steel x8, Stone Brick x8             == DSP 91  Depot Mk.II
#:   sorter-4          Sorter Mk.III x2, Super-magnetic
#:                     Ring x1, Processor x1                == DSP 160 Pile Sorter
#:   logistics-vessel  Titanium Alloy x10, Processor x10,
#:                     Reinforced Thruster x2               == DSP 96  Interstellar
#:                                                                     Logistics Vessel
#:   reforming-refine  Refined Oil x2, Hydrogen, Coal
#:                     -> Refined Oil x3                    == DSP 121 Reformed Refinement
_RECIPE_ALIASES = {
    "storage-1": "Depot Mk.I",
    "storage-2": "Depot Mk.II",
    "sorter-4": "Pile Sorter",
    "logistics-vessel": "Interstellar Logistics Vessel",
    "reforming-refine": "Reformed Refinement",
}

#: Same, for items.  ``Accumulator (full)`` and ``Critical Photon`` exist as DSP
#: items but have no crafting recipe -- charging is an Energy Exchanger
#: operation and critical photons come from a Ray Receiver -- so FactorioLab
#: models them as recipes that DSP does not have.  See :data:`NO_DSP_RECIPE`.
#: The two crystals matter beyond tidiness: they are raw vein items, so they can
#: arrive on an input belt, and an input belt with no item id gets no marker icon.
_ITEM_ALIASES = {
    "storage-1": "Depot Mk.I",
    "storage-2": "Depot Mk.II",
    "sorter-4": "Pile Sorter",
    "logistics-vessel": "Interstellar Logistics Vessel",
    "accumulator-full": "Accumulator (full)",
    "critical-photon": "Critical Photon",
    "optical-grating-crystal": "Grating Crystal",
    "spiniform-stalagmite-crystal": "Stalagmite Crystal",
    "ray-receiver-pro": "Ray Receiver",
}

#: FactorioLab entries with no DSP *item* at all, so no alias exists.
#: ``proliferator-N-products`` / ``-speed`` are FactorioLab's module pseudo-items
#: for the two spray modes; the sprayable items themselves are
#: ``proliferator-1/2/3`` and map normally.  ``mecha-core-1`` and
#: ``universe-exploration-1`` are mecha upgrades.  The remaining 42 are Dark Fog
#: drops.  None can appear on a belt, so none needs an icon.
NO_DSP_ITEM_PREFIXES = ("df-", "proliferator-1-", "proliferator-2-", "proliferator-3-")

#: FactorioLab recipes with no DSP *recipe id*, because the game expresses them
#: as a machine mode rather than a craft.  No alias can help; the id genuinely
#: does not exist.
#:
#: This is NOT the same as "cannot be built", and the distinction matters:
#:
#: * ``accumulator-full`` / ``accumulator-discharge`` are an **Energy Exchanger**
#:   running in charge or discharge mode.  It is an ordinary production node with
#:   real item flow -- charging takes empty Accumulators and produces full ones,
#:   discharging does the reverse -- so it belts, sorts and lays out like any
#:   other machine, and FactorioLab models the flow exactly that way
#:   (``accumulator -> accumulator-full`` and back).  The only thing missing is
#:   the emission: the mode lives in the building's parameter block (the
#:   tri-state ``targetState``) rather than in ``recipe_id``.
#: * ``critical-photon`` / ``critical-photon-graviton`` are likewise a **Ray
#:   Receiver** mode (photon generation, optionally with a graviton lens).
#:
#: So both are capability gaps in the generator, not impossibilities.  The 36
#: ``df-*`` entries are different: Dark Fog drops, genuinely not built by
#: anything.
NO_DSP_RECIPE = frozenset(
    {
        "accumulator-full",
        "accumulator-discharge",
        "critical-photon",
        "critical-photon-graviton",
    }
)

#: DSP item ids of the mode-driven buildings.
ENERGY_EXCHANGER_ID = 2209
RAY_RECEIVER_ID = 2208


@dataclass(frozen=True, slots=True)
class ModeDriven:
    """Which building a :data:`NO_DSP_RECIPE` entry runs on, and in what mode.

    ``mode`` is a plain name, not a parameter word: translating it into the
    building's parameter block is :mod:`flab2bp.dsp.params`' job, which keeps
    block layouts out of the catalog and the dependency pointing one way.
    """

    machine_item_id: int
    machine_name: str
    mode: str


#: The machine each :data:`NO_DSP_RECIPE` entry actually runs on, so the layout
#: stage can place it and ask :func:`flab2bp.dsp.params.parameters_for` for the
#: block that selects the mode.
#:
#: Both photon entries deliberately share the ``photon`` mode: the Graviton Lens
#: that separates FactorioLab's two recipes is an item consumed by the same Ray
#: Receiver, doubling its yield, not a different setting on the building.
MODE_DRIVEN_MACHINE = {
    "accumulator-full": ModeDriven(ENERGY_EXCHANGER_ID, "energy-exchanger", "charge"),
    "accumulator-discharge": ModeDriven(
        ENERGY_EXCHANGER_ID, "energy-exchanger", "discharge"
    ),
    "critical-photon": ModeDriven(RAY_RECEIVER_ID, "ray-receiver", "photon"),
    "critical-photon-graviton": ModeDriven(RAY_RECEIVER_ID, "ray-receiver", "photon"),
}


def _kebab(name: str) -> str:
    """DSP display name -> FactorioLab-style id."""
    s = name.lower().replace(".", "").replace("(", "").replace(")", "")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    for roman, digit in _ROMAN_TIERS.items():
        if s.endswith("-" + roman):
            return s[: -(len(roman) + 1)] + "-" + digit
    return s


@cache
def _recipe_ids() -> dict[str, int]:
    raw = json.loads(_RECIPES.read_text())
    table = {_kebab(r["name"]): int(r["id"]) for r in raw}
    by_name = {r["name"]: int(r["id"]) for r in raw}
    for factoriolab_id, dsp_name in _RECIPE_ALIASES.items():
        if dsp_name in by_name:
            table[factoriolab_id] = by_name[dsp_name]
    return table


def recipe_id(factoriolab_id: str) -> int:
    """DSP numeric recipe id for a FactorioLab recipe id.

    A placed machine carries this in ``PlacedBuilding.recipe_id``; without it
    the game pastes an unconfigured machine that produces nothing.

    Raises ``KeyError`` rather than inventing a value.  Both layout strategies
    previously faked this -- one emitted ``0`` for every machine, the other
    ``abs(hash(name)) % 30000``, which is not a DSP id at all and is not even
    stable across processes, since Python randomises string hashing.  A wrong
    recipe id yields a blueprint that pastes cleanly and builds the wrong thing,
    so failing loudly is the only safe behaviour.

    Coverage is all 161 DSP recipes, the complete set the game ships.  What
    FactorioLab has and DSP does not is :data:`NO_DSP_RECIPE` -- machine *modes*
    rather than crafts, which still need belting and laying out -- plus the 36
    ``df-*`` Dark Fog drops, which are genuinely not built by anything.
    """
    try:
        return _recipe_ids()[factoriolab_id]
    except KeyError:
        entry = MODE_DRIVEN_MACHINE.get(factoriolab_id)
        if entry is not None:
            raise KeyError(
                f"{factoriolab_id!r} is a {entry.machine_name} MODE "
                f"({entry.mode}), not a craft, so DSP has no recipe id for it. It "
                f"is still a real production step with real item flow that must be "
                f"placed, belted and sorted like any other machine -- the mode goes "
                f"in the building's parameter block, which "
                f"flab2bp.dsp.params.parameters_for({factoriolab_id!r}) now "
                f"produces. What is still missing is the layout stage emitting it."
            ) from None
        if factoriolab_id.startswith("df-"):
            raise KeyError(
                f"{factoriolab_id!r} is a Dark Fog drop, not something any "
                f"machine builds, so it cannot appear in a blueprint."
            ) from None
        raise KeyError(
            f"no DSP recipe id known for {factoriolab_id!r}. If DSP does craft "
            f"it, its display name differs from the FactorioLab id and it needs "
            f"an entry in _RECIPE_ALIASES, verified by ingredient set."
        ) from None


def known_recipe_ids() -> frozenset[str]:
    return frozenset(_recipe_ids())


# --- items and belt marker icons -------------------------------------------

_ITEMS = Path(__file__).parent / "data" / "items.json"


@cache
def _item_ids() -> dict[str, int]:
    raw = json.loads(_ITEMS.read_text())
    table = {_kebab(i["name"]): int(i["id"]) for i in raw}
    by_name = {i["name"]: int(i["id"]) for i in raw}
    for factoriolab_id, dsp_name in _ITEM_ALIASES.items():
        if dsp_name in by_name:
            table[factoriolab_id] = by_name[dsp_name]
    return table


def item_id(factoriolab_id: str) -> int:
    """DSP numeric item id for a FactorioLab item id.

    Raises ``KeyError`` rather than guessing, for the same reason as
    :func:`recipe_id`: a wrong id renders a plausible-looking but incorrect
    marker, which is worse than none.
    """
    try:
        return _item_ids()[factoriolab_id]
    except KeyError:
        raise KeyError(f"no DSP item id known for {factoriolab_id!r}") from None


def get_item_id(factoriolab_id: str) -> int | None:
    """:func:`item_id`, or ``None`` when unknown."""
    return _item_ids().get(factoriolab_id)


def belt_marker(dsp_item_id: int) -> tuple[int, int]:
    """The ``parameters`` block that puts an item icon on a belt.

    Measured, not guessed: all 109 belt parameter blocks in the fixture corpus
    are exactly two words, ``(item_id, 0)``, and every first word resolves to a
    real item (Proliferator Mk.III, Space Warper, Pile Sorter, ...).  Icon ids
    are banded -- below 12000 is the item band, so an item id is its own icon
    id, which is why no translation is needed here.
    """
    return (dsp_item_id, 0)


@dataclass(frozen=True, slots=True)
class Building:
    """One buildable thing, with the geometry the layout stage needs."""

    prefab: str
    item_id: int
    name: str
    model_index: int
    width: int
    height: int
    #: 0 = normal building. 1 = belt addon: occupies NO grid tile of its own and
    #: mounts onto a belt (this is what makes the Spray Coater nearly free).
    addon_type: int
    #: Explicit I/O slots, when the building defines any.  Most production
    #: buildings define none at all, which is why a sorter may attach anywhere
    #: on their perimeter.  The Fractionator is the exception that matters.
    slots: tuple[dict[str, float], ...]
    cover_radius: Fraction
    connect_distance: Fraction

    @property
    def is_belt_addon(self) -> bool:
        return self.addon_type == 1

    @property
    def occupies_tiles(self) -> bool:
        return not self.is_belt_addon

    @property
    def has_explicit_slots(self) -> bool:
        return bool(self.slots)


def derive_footprint(blueprint_box: float) -> int:
    """Tiles occupied along one axis by a building of this collider extent.

    A building centred at integer ``c`` with half-extent ``e`` occupies the
    tiles whose centres it covers -- those ``k`` with ``|k - c| < e`` -- which
    numbers ``2 * ceil(e) - 1``.  Always odd, as the corpus requires.

    Verified against every production building: assembler 3.82 -> 3, Matrix Lab
    5.6 -> 5, Arc Smelter 2.9 -> 3, Chemical Plant 8.2 -> 9 (whose independently
    extracted ``landBBox`` is exactly 9.0), Oil Refinery 7.2 -> 7.
    """
    half = blueprint_box / 2.0
    # Subtract an epsilon so an exactly-integer half-extent, which covers no
    # further tile centre, does not round up into one.
    return max(1, 2 * math.ceil(half - 1e-9) - 1)


#: Footprints the derivation cannot produce, each with its reason.
_FOOTPRINT_OVERRIDES: dict[int, tuple[int, int]] = {
    # Sorters have a degenerate collider (0.52 x 0.23) because they are modelled
    # as a line between two endpoints, not a box. Each end occupies one tile.
    2011: (1, 1),
    2012: (1, 1),
    2013: (1, 1),
    2014: (1, 1),
}

#: Belts carry no build collider in the asset table, so they are absent from it
#: entirely. One belt building occupies exactly one tile.
_BELT_ENTRIES = {
    2001: ("belt-1", "Conveyor Belt Mk.I", 35),
    2002: ("belt-2", "Conveyor Belt Mk.II", 36),
    2003: ("belt-3", "Conveyor Belt Mk.III", 37),
}


@cache
def _load() -> dict[int, Building]:
    raw = json.loads(_DATA.read_text())
    out: dict[int, Building] = {}
    for row in raw:
        item_id = row.get("itemId")
        if item_id is None:
            continue  # prefab variant with no item of its own
        if item_id in out:
            # Several prefab variants can share one item id (splitter-a/b/c).
            # The first is authoritative; later ones are alternate models.
            continue
        box = row["blueprintBoxSize"]
        w, h = _FOOTPRINT_OVERRIDES.get(
            item_id, (derive_footprint(box[0]), derive_footprint(box[1]))
        )
        power = row.get("power") or {}
        building = Building(
            prefab=row["prefab"],
            item_id=item_id,
            name=row["name"],
            model_index=row["modelIndex"],
            width=int(w),
            height=int(h),
            addon_type=row.get("addonType", 0),
            slots=tuple(row.get("slots") or ()),
            cover_radius=Fraction(power.get("coverRadius") or 0).limit_denominator(100),
            connect_distance=Fraction(power.get("connectDistance") or 0).limit_denominator(100),
        )
        out[item_id] = building

    for item_id, (prefab, name, model_index) in _BELT_ENTRIES.items():
        out[item_id] = Building(
            prefab=prefab,
            item_id=item_id,
            name=name,
            model_index=model_index,
            width=1,
            height=1,
            addon_type=0,
            slots=(),
            cover_radius=Fraction(0),
            connect_distance=Fraction(0),
        )
    return out


def building(item_id: int) -> Building:
    try:
        return _load()[item_id]
    except KeyError:
        raise KeyError(f"no DSP building with item id {item_id}") from None


def footprint(item_id: int) -> tuple[int, int]:
    b = building(item_id)
    return (b.width, b.height)


def all_buildings() -> tuple[Building, ...]:
    return tuple(_load().values())
