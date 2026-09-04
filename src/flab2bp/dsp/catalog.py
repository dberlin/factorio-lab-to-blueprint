"""Ground-truth DSP building geometry and constants.

Everything here was extracted from the game's own assets and then validated
against the 11 real blueprints in ``tests/fixtures``.  Where the two disagreed,
the fixtures won.

Footprints
----------
A building's grid footprint is **derived**, not tabulated: it is the set of tiles
whose *centres* the build collider covers.  Tile centres are
``colliders.GRID_ARC`` = 1.2566 world units apart, so for a building centred on a
tile with collider half-extent ``e`` the occupied tiles are those ``k`` with
``|k| * GRID_ARC < e``, giving

    width = 2 * ceil(e / GRID_ARC) - 1

which is **always odd**.  ``e`` comes from ``PrefabDesc.buildColliders`` -- the
boxes the game's own paste test puts into the physics world -- and NOT from
``blueprintBoxSize``, which the game derives from the one Build box those
exclude.  See :func:`derive_footprint`, which carries the evidence for both
halves of that.

That oddness is not an artifact of the formula -- it is forced by the data.
Across the whole fixture corpus every production building is integer-centred
(Assembling Machine Mk.III 196/196, Matrix Lab 131/131, Negentropy Smelter
100/100, Splitter 25/25, and belts 5729/5866), with not one on a half-integer.
An even-width building centred on an integer would straddle tile boundaries, so
an even footprint is geometrically impossible for anything the corpus contains.

This corrects a earlier table that rounded the collider extent to nearest
(Assembling Machine 4x4, Matrix Lab 6x6, Chemical Plant 8x5).  Rounding is wrong
in both directions -- the assembler is really 3x3 -- so it was not a uniform
off-by-one.  The Chemical Plant is 7x5: it read 9x5 for as long as the divisor
above was 1.0 instead of ``GRID_ARC``, which is the error :func:`derive_footprint`
now records.

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
from collections.abc import Mapping, Set
from dataclasses import dataclass
from fractions import Fraction
from functools import cache, lru_cache
from pathlib import Path
from typing import Protocol, TypedDict, TypeGuard

from flab2bp.dsp.rules import WORLD_UNITS_PER_LEVEL, PowerNode

_DATA = Path(__file__).parent / "data" / "buildings.json"
_SLOT_POSES = Path(__file__).parent / "data" / "slot_poses.json"


class _JsonLoads(Protocol):
    def __call__(self, value: str | bytes | bytearray, /) -> object: ...


_JSON_LOADS: _JsonLoads = json.loads


class _CatalogDataError(ValueError):
    """A bundled asset has the wrong JSON shape."""


class _PoseData(TypedDict):
    pos: tuple[float, float, float]
    fwd: tuple[float, float, float]


class _PoseEntry(TypedDict):
    slotPoses: tuple[_PoseData, ...]
    portPoses: tuple[_PoseData, ...]
    addonAreas: tuple[tuple[float, float, float], ...]


type _PoseTable = dict[str, _PoseEntry]


def _json(path: Path) -> object:
    return _JSON_LOADS(path.read_bytes())


def _is_object_mapping(value: object) -> TypeGuard[Mapping[object, object]]:
    return isinstance(value, Mapping)


def _is_object_list(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)


def _mapping(value: object, path: str) -> Mapping[object, object]:
    if not _is_object_mapping(value):
        raise _CatalogDataError(f"{path} must be an object, got {type(value).__name__}")
    return value


def _array(value: object, path: str) -> list[object]:
    if not _is_object_list(value):
        raise _CatalogDataError(f"{path} must be an array, got {type(value).__name__}")
    return value


def _required(row: Mapping[object, object], key: str, path: str) -> object:
    if key not in row:
        raise _CatalogDataError(f"{path}.{key} is required")
    return row[key]


def _string(value: object, path: str) -> str:
    if not isinstance(value, str):
        raise _CatalogDataError(f"{path} must be a string, got {type(value).__name__}")
    return value


def _integer(value: object, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _CatalogDataError(f"{path} must be an integer, got {type(value).__name__}")
    return value


def _number(value: object, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _CatalogDataError(f"{path} must be a number, got {type(value).__name__}")
    return float(value)


def _boolean(value: object, path: str) -> bool:
    if not isinstance(value, bool):
        raise _CatalogDataError(f"{path} must be a boolean, got {type(value).__name__}")
    return value


def _tuple3(value: object, path: str) -> tuple[float, float, float]:
    parts = _array(value, path)
    if len(parts) != 3:
        raise _CatalogDataError(f"{path} must contain exactly three numbers")
    return (
        _number(parts[0], f"{path}[0]"),
        _number(parts[1], f"{path}[1]"),
        _number(parts[2], f"{path}[2]"),
    )


def _optional_integer(
    row: Mapping[object, object], key: str, path: str, default: int
) -> int:
    if key not in row:
        return default
    return _integer(row[key], f"{path}.{key}")


def _pose_data(value: object, path: str) -> _PoseData:
    row = _mapping(value, path)
    return {
        "pos": _tuple3(_required(row, "pos", path), f"{path}.pos"),
        "fwd": _tuple3(_required(row, "fwd", path), f"{path}.fwd"),
    }


def _parse_pose_table(value: object) -> _PoseTable:
    raw = _mapping(value, str(_SLOT_POSES))
    table: _PoseTable = {}
    for key, entry_value in raw.items():
        prefab = _string(key, f"{_SLOT_POSES} key")
        path = f"{_SLOT_POSES}.{prefab}"
        entry = _mapping(entry_value, path)
        slot_values = (
            _array(entry["slotPoses"], f"{path}.slotPoses")
            if "slotPoses" in entry
            else []
        )
        port_values = (
            _array(entry["portPoses"], f"{path}.portPoses")
            if "portPoses" in entry
            else []
        )
        addon_values = (
            _array(entry["addonAreas"], f"{path}.addonAreas")
            if "addonAreas" in entry
            else []
        )
        table[prefab] = {
            "slotPoses": tuple(
                _pose_data(item, f"{path}.slotPoses[{index}]")
                for index, item in enumerate(slot_values)
            ),
            "portPoses": tuple(
                _pose_data(item, f"{path}.portPoses[{index}]")
                for index, item in enumerate(port_values)
            ),
            "addonAreas": tuple(
                _tuple3(item, f"{path}.addonAreas[{index}]")
                for index, item in enumerate(addon_values)
            ),
        }
    return table


def _optional_number(
    row: Mapping[object, object], key: str, path: str
) -> float | None:
    if key not in row or row[key] is None:
        return None
    return _number(row[key], f"{path}.{key}")


def _optional_boolean(
    row: Mapping[object, object], key: str, path: str
) -> bool:
    if key not in row:
        return False
    return _boolean(row[key], f"{path}.{key}")


# --- id ranges -------------------------------------------------------------
# Confirmed against the fixture corpus and the viewer's decoder.

BELT_IDS = range(2001, 2010)
SORTER_IDS = range(2011, 2020)
SPLITTER_ID = 2020
#: Exact prefab models the Splitter item may select.
#:
#: Model 121 (Storage Tank) is a representative trap: it also exposes four
#: cardinal ``portPoses``, but an item/model pair of Splitter/Storage Tank is not
#: a Splitter variant and must never reach the encoder.
SPLITTER_MODEL_INDICES = frozenset((38, 39, 40))
SPRAY_COATER_ID = 2313
FRACTIONATOR_ID = 2314
TESLA_TOWER_ID = 2201
MATRIX_LAB_IDS = (2901, 2902)
STORAGE_STACK_IDS = (2020, 2101, 2102, 2106)


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

#: Maximum sorter span in tiles.
#:
#: This was recorded as a corpus measurement -- "spans cluster at 1, 2 and 3
#: with nothing at 4" -- and listed in ``dsp.rules``' docstring under "not game
#: rules".  It IS a game rule, and the corpus was agreeing with it rather than
#: establishing it.  ``BuildTool_Inserter.cs:1316-1329`` sets a per-class bound
#: on the grid segments a sorter crosses, alongside the world-length pair that
#: :data:`flab2bp.dsp.rules.SORTER_LENGTH` already ports::
#:
#:     float num5 = 5.5f;  float num6 = 0.6f;  float num7 = 3.499f;  ...
#:     if (belt && belt)     { num6 = 0.4f; num5 = 5f;   num7 = 3.2f;   ... }
#:     else if (!belt && !belt) { num6 = 0.9f; num5 = 7.5f; num7 = 3.799f; ... }
#:
#: and applies it at ``:1341``::
#:
#:     if (num2 > num7)
#:     {
#:         buildPreview.condition = EBuildCondition.TooFar;
#:         continue;
#:     }
#:
#: where ``num2 = CalcSegmentsAcross(...)``.  A span of 4 is over ``num7`` in
#: every one of the three classes -- 4 > 3.799 is the loosest failure -- and a
#: span of 3 is under it in every one.  The paste path repeats the same table
#: and the same test at ``BuildTool_BlueprintPaste.cs:3474``.
#:
#: The game then clamps the span it RECORDS to the same 3,
#: ``BuildTool_Inserter.cs:1352``::
#:
#:     int num9 = Mathf.RoundToInt(Mathf.Clamp(num3, 1f, 3f));
#:     buildPreview.SetOneParameter(num9);
#:
#: **Not tier-dependent, and now known rather than inferred:** none of ``num5``,
#: ``num6``, ``num7`` or ``num8`` reads ``inserterGrade``.  The corpus reading
#: (Mk.I at 3.4, Mk.II at 2.2) was the right conclusion from the wrong evidence.
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

#: Sorter item ids ordered from cheapest/slowest to fastest.
SORTER_TIERS = tuple(
    sorted(SORTER_RATE_AT_1, key=SORTER_RATE_AT_1.__getitem__)
)

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

#: Blueprint ``z`` per WORLD unit of height.  Blueprint z is not world height:
#: the game's vertical pitches are 4 for a Matrix Lab, 8/3 for a Splitter and
#: 4/3 for a belt, and the same three measure 3, 2 and 1 in blueprint z.  Two
#: independent pitches agreeing on 3/4 is what pins it -- the lab spacing is
#: visible in ``12-s-purple`` (120 labs, 10 columns of 12 at z = 0, 3, ... 33)
#: and the belt spacing in the max-height blueprint (39 belts one z apart).
#:
#: It matters because the game's slope limit is in WORLD units.  A blueprint
#: rise of 1/2 over one tile is a world slope of 2/3, not 1/2.
BELT_Z_PER_WORLD_UNIT = Fraction(3, 4)

#: The steepest a BELT-TO-BELT LINK may be pasted without the
#: vertical-construction unlock, as ``world rise / horizontal run``.
#:
#: This must come from ``BuildTool_BlueprintPaste``, not ``BuildTool_Path``:
#: the path tool compares its rise/run ratio with ``0.8f``, while the paste at
#: ``BuildTool_BlueprintPaste.cs:2093-2095`` compares the sine directly::
#:
#:     if (!history.beltVerticalConstruction
#:         && Abs(Dot(lpos.normalized, (output.lpos - lpos).normalized)) > 0.6f)
#:         condition = EBuildCondition.TooSteep;
#:
#: The dot is the radial component of the unit link vector, so it is
#: ``sin(theta)``.  ``sin(theta) <= 3/5`` is exactly
#: ``tan(theta) <= 3/4``.  With the unlock the test is skipped entirely.
MAX_BELT_SLOPE = Fraction(3, 4)

def belt_slope_allowed(
    world_rise: Fraction | int,
    horizontal_run: Fraction | int,
    *,
    unlocked: bool,
) -> bool:
    """Whether the paste's ``TooSteep`` clause accepts one belt link."""
    if unlocked:
        return True
    rise = abs(Fraction(world_rise))
    run = abs(Fraction(horizontal_run))
    return run > 0 and rise <= MAX_BELT_SLOPE * run

#: A belt climbs this much per tile of run at the steepest slope the corpus
#: uses.  NOT a cap: ``MAX_BELT_SLOPE`` allows up to ``9/16`` of blueprint z per
#: tile, and with the unlock, any amount.  This is the value we EMIT, chosen
#: because it lands altitudes on :data:`BELT_Z_QUANTUM` and because all 118
#: clean ramp steps in the corpus use it.
BELT_CLIMB_PER_TILE = Fraction(1, 2)
RAMP_TILES_PER_LEVEL = 2

#: Height gained by one step of the VERTICAL form, which costs no horizontal
#: run and therefore has infinite slope.  It requires
#: ``GameHistoryData.beltVerticalConstruction`` -- a tech unlock (upgrade case
#: 42), ``false`` on a new save -- because that is the flag that switches off
#: the ``MAX_BELT_SLOPE`` test.  Every one of the 38 steps in the user's
#: max-height blueprint is exactly this.
VERTICAL_STEP = Fraction(1)

# `BELT_CROSSING_CLEARANCE = Fraction(1)` was here, described as "height a belt
# must gain to pass OVER a ground-level obstruction, per the user".  It carried
# no citation because there is no rule of that shape to cite: what the game
# applies is the collider query, and how high a belt must ride to clear a
# particular building is a property of that building's box.
# `dsp.colliders.belt_crossing_height` answers it per model and returns
# 2.80-4.97 world units where this said a flat 1 -- it is not even the right
# number for a Spray Coater, whose box is 1.8975 high.
#
# The scalar was deleted because no validator consulted it; crossing height is
# derived per collider by ``dsp.colliders.belt_crossing_height``.

# Path-only ``TooBendToLift`` constants used to live here.  The applicability
# audit proved BlueprintPaste never assigns that condition, so the dead
# definitions were deleted rather than promoted into the paste registry.

#: Lab level on a NEW save, from ``GameHistoryData.Init``: ``labLevel = 3``.
DEFAULT_LAB_LEVEL = 3

#: Storage level on a new save, ``GameHistoryData.cs:576``.
DEFAULT_STORAGE_LEVEL = 2

#: FactorioLab prefix for Mass Construction, whose five levels set
#: ``GameHistoryData.blueprintLimit`` through ``UnlockTechFunction`` case 28.
MASS_CONSTRUCTION_PREFIX = "mass-construction-"

#: Facility-count cap by Mass Construction level.  Index 0 is an explicitly
#: unresearched save; level 5 is unlimited and therefore represented by
#: ``None`` rather than by an invented finite sentinel.
#:
#: The paste compares this value literally at
#: ``BuildTool_BlueprintPaste.cs:1122``.  ``GameHistoryData.cs:1898`` is the
#: assignment, and ``UITechTree.cs:1625`` distinguishes finite values through
#: 3600 from the unlimited tier.
BLUEPRINT_LIMIT_BY_LEVEL: tuple[int | None, ...] = (0, 150, 300, 900, 3600, None)


def belt_max_z(lab_level: int = DEFAULT_LAB_LEVEL) -> Fraction:
    """Highest blueprint ``z`` a belt may reach in a save at this lab level.

    ``GameHistoryData.buildMaxHeight`` is the game's ceiling, in world units::

        if (labLevel < 15) return labLevel * 4f - 0.6f;
        return labLevel * 4f + 4f;

    and every build is tested against it as
    ``lpos.sqrMagnitude > (buildMaxHeight + 0.5 + radius)^2``.  Belts are NOT
    subject to the separate per-building stack limit -- that one reads
    ``isTank || isStorage || isLab || isSplitter`` and belts are none of them --
    so this is the whole of what bounds a belt.

    Converted into blueprint z by :data:`BELT_Z_PER_WORLD_UNIT`.  At the
    starting lab level of 3 that is ``8.55``; the user's save reached ``z = 38``,
    which needs lab level 13 (``3*13 - 0.45 = 38.55``) and is the independent
    check that the conversion and the formula are both right.
    """
    if lab_level < 15:
        world = Fraction(lab_level) * 4 - Fraction(3, 5)
    else:
        world = Fraction(lab_level) * 4 + 4
    return world * BELT_Z_PER_WORLD_UNIT


#: FactorioLab technology id that grants ``beltVerticalConstruction``.
#:
#: From the game's own locale, ``Locale/1033/base.txt``::
#:
#:     传送带坡度可升级   (Need to unlock Super Magnetic Field Generator)
#:     解锁传送带坡度上限  Unlock slope limit when building Conveyor Belts
#:
#: which is the hint the build cursor shows on ``TooSteep``.  So the tech that
#: removes the slope limit is Super Magnetic Field Generator -- NOT Vertical
#: Construction, which the same locale says covers "Depots, Storage Tanks, and
#: Matrix Labs".  Guessing that the two were the same line was tempting and
#: would have been wrong.
BELT_SLOPE_UNLOCK_TECH = "super-magnetic-field-generator"

#: FactorioLab id prefix for the levelled Vertical Construction upgrade, which
#: is what raises ``labLevel`` and so ``buildMaxHeight``.  ``UnlockTechFunction``
#: case 25 is ``labLevel += num``.
VERTICAL_CONSTRUCTION_PREFIX = "vertical-construction-"


@dataclass(frozen=True, slots=True)
class BeltAltitudeRules:
    """What a particular SAVE allows a belt to do, vertically.

    Both fields are properties of the player's researched technologies, which
    is why they are derived from the FactorioLab URL rather than defaulted or
    asked for on the command line.  FactorioLab already carries the researched
    set, and this project's rule is that FactorioLab's answer is authoritative.
    """

    #: Highest blueprint z a belt may occupy.
    max_z: Fraction
    #: Whether the slope limit is lifted -- i.e. whether a belt may climb with
    #: no horizontal run at all.
    vertical_construction: bool
    #: Storage/splitter stack level derived from Vertical Construction.
    storage_level: int
    #: Lab level the ceiling and lab stack threshold were derived from.
    lab_level: int
    #: False when the URL carried no technology set at all.  The values above
    #: are then FactorioLab's own default -- every technology researched -- not
    #: a guess of ours and not a new save.
    from_url: bool


@dataclass(frozen=True, slots=True)
class LogisticsTiers:
    """Which belts and sorters a particular SAVE can build.

    Both come from the player's researched technologies, read from the
    dataset's ``recipeUnlock`` lists, so they are derived from the FactorioLab
    URL rather than defaulted or asked for on the command line -- the same
    rule as :class:`BeltAltitudeRules`.
    """

    #: FactorioLab belt item ids, slowest first.  Never empty and never
    #: slower than the URL's own belt, which is always a member: FactorioLab's
    #: choice is authoritative whether or not the technology set unlocks it.
    belt_item_ids: tuple[str, ...]
    #: FactorioLab sorter item ids, slowest first.  Never empty.
    sorter_item_ids: tuple[str, ...]
    #: False when the URL carried no technology set at all, in which case
    #: every technology is taken as researched -- FactorioLab's own default.
    from_url: bool


def _technology_level(technology_ids: Set[str], prefix: str) -> int:
    """Highest numeric suffix researched for one levelled technology."""
    levels = (
        int(suffix)
        for technology_id in technology_ids
        if technology_id.startswith(prefix)
        and (suffix := technology_id.removeprefix(prefix)).isdigit()
    )
    return max(levels, default=0)


def blueprint_limit_for_technologies(
    technology_ids: Set[str] | None,
    all_technology_ids: Set[str],
) -> int | None:
    """Paste facility-count cap for the FactorioLab technology selection."""
    effective = all_technology_ids if technology_ids is None else technology_ids
    level = min(_technology_level(effective, MASS_CONSTRUCTION_PREFIX), 5)
    return BLUEPRINT_LIMIT_BY_LEVEL[level]


def belt_rules_for_technologies(
    technology_ids: Set[str] | None,
    all_technology_ids: Set[str],
) -> BeltAltitudeRules:
    """Derive the belt altitude rules from a FactorioLab researched-tech set.

    **Absence is not emptiness.**  ``None`` means the URL said nothing about
    technologies, and FactorioLab's answer to that is not "none researched" --
    it is "all of them".  From ``settings-store.ts::computeSettings``::

        const techIds =
          state.researchedTechnologyIds ?? defaults?.researchedTechnologyIds;
        let researchedTechnologyIds = new Set(data.technologyIds);
        if (techIds != null && researchedTechnologyIds.size > 0) {
          // Filter for only technologies that still exist in this data set
          researchedTechnologyIds = new Set(filteredTechs);
        }

    It starts from the WHOLE dataset and only narrows when a set was actually
    supplied.  ``initialSettingsState`` never sets the field, and the DSP mod
    data carries no ``researchedTechnologies`` default, so a URL without ``tre``
    lands on the unnarrowed set.  The mod defaults corroborate it: FactorioLab
    ships ``maxBelt: conveyor-belt-3`` and a ``maxMachineRank`` of top-tier
    machines, which a save with nothing researched could not build.

    So ``None`` grants every technology, exactly as ``_excluded_recipes`` gives
    ``None`` the mod's own defaults rather than the most restrictive reading.

    .. note::
       **This is a DECISION, not only a reading.**  The user settled it -- "I
       think defaulting to all-researched is a fine default" -- and the
       ``computeSettings`` quote above is why the decision is also the faithful
       one.  Recorded as a decision so that nobody later "corrects" it back to
       the restrictive reading on the grounds that our own evidence is
       second-hand.  If it is ever revisited, revisit it as a product choice.

    This is the THIRD instance today of one class of bug: a URL that is SILENT
    about something read as a URL that FORBIDS it.  The others were recipe
    exclusions (``60d5f0f``, which re-disabled recipes the player had enabled
    and changed the blueprint's inputs) and this one, which refused 19 of 72
    audit cells for want of a slope unlock the player had.  When a field is
    optional, the question is never "what is the empty value" -- it is "what
    does FactorioLab do when it is missing".

    An explicit empty set still means a save with nothing researched, and is
    honoured as such.

    The lab and storage levels are their starting values plus the highest
    researched Vertical Construction level.  ``UnlockValues`` lives in the
    game's binary asset protos and could not be read, so "one per level" remains
    an explicit assumption.  FactorioLab models six levels, giving at most lab
    9 and a ceiling of 26.55, while the user's own save reaches 38.55 at lab 13.
    This under-estimates a developed save, the safe direction: it refuses
    altitudes the save would allow and never emits one it would not.
    """
    effective = all_technology_ids if technology_ids is None else technology_ids
    levels = _technology_level(effective, VERTICAL_CONSTRUCTION_PREFIX)
    lab_level = DEFAULT_LAB_LEVEL + levels
    storage_level = DEFAULT_STORAGE_LEVEL + levels
    return BeltAltitudeRules(
        max_z=belt_max_z(lab_level),
        vertical_construction=BELT_SLOPE_UNLOCK_TECH in effective,
        storage_level=storage_level,
        lab_level=lab_level,
        from_url=technology_ids is not None,
    )


# --- cargo stacking --------------------------------------------------------
#
# Read out of the game files on this box, never from a live dump: the
# behavioural facts come from an ``ilspycmd`` decompile of ``Assembly-CSharp``
# and the per-level unlock values from ``resources.assets`` via
# ``scripts/extract_dsp_tables.py``.  ``data/stacking.json`` carries the file
# and line for every number; nothing here restates a rule the game owns.
#
# Two things about DSP stacking are easy to get backwards, so they are written
# down here rather than left to the reader of the tables:
#
#   * ``pick_stack`` counts CARGOS, not items.  A sorter picks until
#     ``stackCount == stackInput`` and each pick adds the picked cargo's own
#     stack byte to ``itemCount`` (``InserterComponent.cs:358``, ``:313``,
#     ``:392``).  A Pile Sorter at pick 4 fed a stack-4 belt carries 16 items
#     per swing.  ``place_stack`` is the largest stack it may FORM on the
#     output belt (``:443-448``), and is not consulted at all when inserting
#     into a building (``:471-474``).
#
#   * Only the Pile Sorter's ladder is live.  ``Sorter Cargo Stacking``
#     (techs 3301-3305) carries ``IsObsolete = 1``, which is what hides a tech
#     from the tree (``UITechNode.cs:914``), so ``inserterStackCountObsolete``
#     never leaves its new-game 1 on this build and Mk.III stacks nothing.

_STACKING = Path(__file__).parent / "data" / "stacking.json"


@cache
def _stacking() -> Mapping[object, object]:
    return _mapping(_json(_STACKING), str(_STACKING))


def _level_key(key: object, path: str) -> int:
    """A stacking table's keys are research levels spelt as JSON object keys."""
    text = _string(key, f"{path} key")
    if not text.isdigit():
        raise _CatalogDataError(f"{path} key {text!r} is not a research level")
    return int(text)


def _level_table(value: object, path: str, levels: int) -> dict[int, int]:
    row = _mapping(value, path)
    table = {
        _level_key(key, path): _integer(entry, f"{path}.{key}")
        for key, entry in row.items()
    }
    absent = [level for level in range(levels + 1) if level not in table]
    if absent:
        raise _CatalogDataError(f"{path} has no entry for levels {absent}")
    return table


@cache
def _sorter_stacking() -> tuple[int, dict[int, tuple[dict[int, int], dict[int, int]]]]:
    """``(levels, {item id: (pick by level, place by level)})``.

    Every sorter tier gets an entry: the ones the shared table covers point at
    the same two dicts, and the Pile Sorter points at its own.
    """
    path = f"{_STACKING}.sorter_cargo_stacking"
    row = _mapping(_required(_stacking(), "sorter_cargo_stacking", str(_STACKING)), path)
    levels = _integer(_required(row, "levels", path), f"{path}.levels")

    def pick_and_place(
        entry: Mapping[object, object], where: str
    ) -> tuple[dict[int, int], dict[int, int]]:
        def table(kind: str) -> dict[int, int]:
            key = f"{kind}_stack_by_level"
            return _level_table(_required(entry, key, where), f"{where}.{key}", levels)

        return table("pick"), table("place")

    shared = pick_and_place(row, path)

    pile_path = f"{path}.pile_sorter"
    pile = _mapping(_required(row, "pile_sorter", path), pile_path)
    pile_id = _integer(_required(pile, "item_id", pile_path), f"{pile_path}.item_id")
    own = pick_and_place(pile, pile_path)

    applies_path = f"{path}.applies_to"
    applies = _mapping(_required(row, "applies_to", path), applies_path)
    entries = _array(_required(applies, "items", applies_path), f"{applies_path}.items")
    tables: dict[int, tuple[dict[int, int], dict[int, int]]] = {}
    for index, value in enumerate(entries):
        entry_path = f"{path}.applies_to.items[{index}]"
        entry = _mapping(value, entry_path)
        item_id = _integer(_required(entry, "item_id", entry_path), f"{entry_path}.item_id")
        tables[item_id] = own if item_id == pile_id else shared
    if pile_id not in tables:
        raise _CatalogDataError(
            f"{pile_path}.item_id {pile_id} is absent from {applies_path}.items"
        )
    return levels, tables


#: Research levels the live cargo-stacking ladder has.  ``0`` means nothing
#: researched, so a table covers ``0..SORTER_STACKING_LEVELS`` inclusive.
SORTER_STACKING_LEVELS: int = _sorter_stacking()[0]


def _stack_table(item_id: int, level: int) -> tuple[dict[int, int], dict[int, int]]:
    levels, tables = _sorter_stacking()
    if item_id not in tables:
        raise ValueError(f"item {item_id} is not a sorter with a stacking table")
    if level < 0 or level > levels:
        raise ValueError(f"research level {level} outside 0..{levels}")
    return tables[item_id]


def sorter_pick_stack(item_id: int, level: int) -> int:
    """Belt cargos a sorter of this tier accumulates per swing at ``level``.

    ``history.inserterStackInput`` for the Pile Sorter,
    ``history.inserterStackCountObsolete`` for Mk.III, 1 for the rest -- the
    grade rule in ``GameData.OnInserterTechChange``.  Cargos, not items: the
    items carried are this many cargos times the stack riding on them.
    """
    return _stack_table(item_id, level)[0][level]


def sorter_place_stack(item_id: int, level: int) -> int:
    """Largest stack it may form on the OUTPUT BELT at ``level``.

    ``history.inserterStackOutput``, passed straight to
    ``TryInsertItemToBeltWithStackIncreasement``.  Inserting into a building
    splits the load evenly instead and never reads it.
    """
    return _stack_table(item_id, level)[1][level]


@cache
def _sorter_stack_rate_factor() -> bool:
    path = f"{_STACKING}.sorter_stack_rate_factor"
    row = _mapping(_required(_stacking(), "sorter_stack_rate_factor", str(_STACKING)), path)
    return _boolean(_required(row, "value", path), f"{path}.value")


#: Whether a sorter carrying a stack of ``n`` moves ``n`` items on that trip.
#: True: every pick does ``itemCount += stack`` and the Inserting stage
#: delivers ``itemCount`` items, so sorter throughput scales with the stack.
SORTER_STACK_RATE_FACTOR: bool = _sorter_stack_rate_factor()


@cache
def _piler() -> Mapping[object, object]:
    return _mapping(_required(_stacking(), "piler", str(_STACKING)), f"{_STACKING}.piler")


#: Largest stack an Automatic Piler emits.
PILER_MAX_STACK: int = _integer(
    _required(_piler(), "max_stack", f"{_STACKING}.piler"), f"{_STACKING}.piler.max_stack"
)

#: Whether ONE piler takes an unstacked belt straight to :data:`PILER_MAX_STACK`.
#:
#: False.  ``PilerComponent`` caches at most two cargos and emits their sum, so
#: it DOUBLES: an unstacked belt leaves the first piler at stack 2 and reaching
#: 4 needs a second one in series.  Any plan that budgets one piler per belt is
#: wrong by a factor of two in piler count.
PILER_SINGLE_PASS: bool = _boolean(
    _required(_piler(), "single_pass", f"{_STACKING}.piler"), f"{_STACKING}.piler.single_pass"
)


def piler_output_stack(input_stack: int) -> int:
    """Stack one piler emits when fed a belt of uniform ``input_stack`` cargos."""
    if input_stack < 1:
        raise ValueError(f"input stack {input_stack} must be at least 1")
    return min(2 * input_stack, PILER_MAX_STACK)


@cache
def _piler_throughput() -> Fraction:
    path = f"{_STACKING}.piler.throughput_cargo_per_second"
    row = _mapping(_required(_piler(), "throughput_cargo_per_second", f"{_STACKING}.piler"), path)
    return Fraction(_integer(_required(row, "per_belt_speed", path), f"{path}.per_belt_speed"))


#: Cargo per second one piler passes, PER UNIT of ``PrefabDesc.beltSpeed``.
#:
#: Stored per unit speed rather than as one belt's number because the piler has
#: no rate of its own: it charges ``beltSpeed * 1000`` per tick and spends
#: 10000 per cargo, so its timed branch alone runs at ``6 * beltSpeed`` cargo
#: per second -- and ``PILER_THROUGHPUT * beltSpeed`` reproduces
#: :data:`BELT_RATE` exactly for all three tiers.  A caller that wants an
#: absolute rate on a given belt should read ``BELT_RATE``; this constant is
#: what says the two agree.  It is also a LOWER bound: the untimed pick branch
#: takes cargo without charging ``timeSpend`` at all.
PILER_THROUGHPUT: Fraction = _piler_throughput()


@cache
def _piler_stack_parameter() -> int | None:
    """``null`` is a FINDING here, so the key must be present to say it."""
    path = f"{_STACKING}.piler"
    value = _required(_piler(), "parameter_index", path)
    if value is None:
        return None
    return _integer(value, f"{path}.parameter_index")


#: Which ``BuildingParameters`` slot carries a piler's stack setting.  ``None``
#: because there is no such setting: ``PilerDesc`` declares no fields, nothing
#: in ``BuildingParameters`` handles a ``PilerComponent``, and Pile-vs-Split is
#: derived from which belt is wired as the output.  A blueprint cannot ask a
#: piler for a stack, so a plan must place pilers in series instead.
PILER_STACK_PARAMETER: int | None = _piler_stack_parameter()


#: Default ceiling on belt altitude, in blueprint z.
#:
#: Derived from the game, not from the corpus.  The corpus said 1.0 and the
#: game says 8.55 on a NEW save -- the fixtures were showing a habit of their
#: builders, and reading a habit as a limit is what cost us a day.  A blueprint
#: built to this default pastes on any save, because no save starts lower.
DEFAULT_MAX_BELT_Z = belt_max_z()

#: The altitude step OUR emitters climb in.  **Not a game rule**, and no longer
#: checked as one.
#:
#: It used to read "altitudes are multiples of this", on the evidence that every
#: one of the 7,502 corpus records lands on one after terrain jitter (max
#: 0.0235) is denoised with ``round(z * 2) / 2``.  That is a fact about the
#: corpus and about our own denoising, not a constraint the game applies: the
#: game's belt altitude is an integer counter (``BuildTool_Path.cs:388``,
#: ``altitude++``; clamped at ``:444`` to 60) turned into a radius at ``:176``,
#: and nothing anywhere compares a belt's height to a step size.
#: ``validate.geom.altitude_range`` enforced it until the provenance audit; the
#: ceiling half of that check is real (``GameHistoryData.buildMaxHeight``) and
#: the quantum half was not.
#:
#: Kept because the emitters genuinely do step in halves -- see
#: :data:`BELT_CLIMB_PER_TILE`, which it aliases -- and a router needs a step.
BELT_Z_QUANTUM = BELT_CLIMB_PER_TILE

#: There is NO useful bound on how many belts share one ``(x, y)``.
#:
#: This replaces ``MAX_BELT_STACK_LEVELS = 3``, whose stated evidence was "426
#: positions in the corpus carry 2 and 21 carry 3".  That count never checked
#: that the three z values DIFFERED: all 21 three-deep positions are
#: ``(0.0, 0.0, 0.0)``, belts at the SAME altitude in polar and whole-planet
#: fixtures where longitude is latitude-compressed and distinct tiles collapse
#: onto one integer cell.  ``factory-endgame-distribution-hub`` has columns
#: holding 21 belts, all at 0.0 -- a squashed coordinate system, not a
#: 21-storey belt.
#:
#: Re-measuring on undistorted fixtures gave a maximum of 2 distinct altitudes
#: per column, which looked like a rule and is not one either: the vertical form
#: stacks 39 belts at one ``(x, y)`` in the max-height blueprint.  A column
#: bound would have rejected that, so no constant replaces it.




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
#:
#: .. note::
#:    ``tests/dsp/test_local_offset.py`` derives a *different* and stricter set
#:    for the same purpose, and the two disagree in both directions.  Its
#:    criterion adds "no two buildings round to the same ``(x, y, z)``", which
#:    catches a distortion that pure alignment misses -- a polar blueprint can
#:    keep whole-number coordinates while collapsing distinct surface tiles onto
#:    one of them.  Under it:
#:
#:    * ``factory-quick-start-step-3-red-cube`` does **not** qualify: 21 of its
#:      232 buildings are off-grid and 9 land on an occupied cell.  A run of
#:      belts near its Storage Tank sits at y = 3.113, 3.987, 4.927, 5.801 --
#:      spacings of 0.87 to 0.94, not 1.0.
#:    * ``12-s-purple-science-from-smelted-refined-products`` **does**, and is
#:      by far the best geometry fixture in the corpus: 3,008 buildings, every
#:      one integer-aligned, no collapsed cells, and a mix of 3x3 assemblers,
#:      5x5 Matrix Labs, 670 sorters and 2,640 belts.
#:
#:    This tuple is left as it is only because ``tests/layout/test_validate.py``
#:    parametrises over it; widening it there is a separate change.
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
    values = _array(_json(_RECIPES), str(_RECIPES))
    table: dict[str, int] = {}
    by_name: dict[str, int] = {}
    for index, value in enumerate(values):
        path = f"{_RECIPES}[{index}]"
        row = _mapping(value, path)
        name = _string(_required(row, "name", path), f"{path}.name")
        dsp_id = _integer(_required(row, "id", path), f"{path}.id")
        table[_kebab(name)] = dsp_id
        by_name[name] = dsp_id
    for factoriolab_id, dsp_name in _RECIPE_ALIASES.items():
        if dsp_name in by_name:
            table[factoriolab_id] = by_name[dsp_name]
    return table


@cache
def _recipe_output_items() -> dict[int, tuple[int, ...]]:
    values = _array(_json(_RECIPES), str(_RECIPES))
    table: dict[int, tuple[int, ...]] = {}
    for index, value in enumerate(values):
        path = f"{_RECIPES}[{index}]"
        row = _mapping(value, path)
        recipe = _integer(_required(row, "id", path), f"{path}.id")
        results = _array(_required(row, "results", path), f"{path}.results")
        table[recipe] = tuple(
            dict.fromkeys(
                _integer(result, f"{path}.results[{result_index}]")
                for result_index, result in enumerate(results)
            )
        )
    return table


def recipe_output_item_ids(recipe: int) -> tuple[int, ...]:
    """Distinct DSP item ids produced by one numeric DSP recipe id."""
    try:
        return _recipe_output_items()[recipe]
    except KeyError:
        raise KeyError(f"no DSP recipe outputs known for recipe id {recipe}") from None


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
    values = _array(_json(_ITEMS), str(_ITEMS))
    table: dict[str, int] = {}
    by_name: dict[str, int] = {}
    for index, value in enumerate(values):
        path = f"{_ITEMS}[{index}]"
        row = _mapping(value, path)
        name = _string(_required(row, "name", path), f"{path}.name")
        dsp_id = _integer(_required(row, "id", path), f"{path}.id")
        table[_kebab(name)] = dsp_id
        by_name[name] = dsp_id
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
class SlotPose:
    """One sorter attachment point, in the building's own unrotated frame.

    This is ``PrefabDesc.slotPoses[i]`` -- the array the game indexes with a
    sorter's ``inputFromSlot`` / ``outputToSlot`` -- with Unity's model axes
    mapped onto our tile grid.

    The mapping is ``dx = model.x``, ``dy = model.z``, ``dz = model.y``: Unity
    puts ``+z`` forward and ``+y`` up, our grid puts ``+y`` north and ``z``
    up.  It is not a guess.  ``test_game_slot_poses`` scores all eight
    axis-permutations against the 1206 machine-side sorter records the game
    itself wrote and this is the only one that lands every end beside the slot
    it names; the next best leaves 779 of them further than a tile away.

    ``fx, fy, fz`` is ``Pose.forward``, in the same frame -- the direction the
    game requires a sorter's approach to agree with.  Near-unit and very nearly
    horizontal; the tiny ``fz`` is the model's own build-in tilt, kept rather
    than zeroed because the game dots against it unrounded.

    All six are floats because the game's are: these are Unity ``Transform``
    world coordinates inside a prefab, on a 0.1-tile lattice that no exact
    rational reconstruction would improve.
    """

    dx: float
    dy: float
    dz: float
    fx: float
    fy: float
    fz: float



@dataclass(frozen=True, slots=True)
class AddonSupplyPose:
    """One game-extracted positional belt connection for an addon.

    Horizontal offsets are in grid tiles and ``dz`` is in project altitude
    levels.  Fractions keep routing decisions exact after the asset loader has
    normalized Unity's rounded world-height value.
    """

    dx: Fraction
    dy: Fraction
    dz: Fraction
    area: int

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
    #: ``PrefabDesc.multiLevel`` -- whether the game lets another building stand
    #: directly ON this one.  Splitters, Depots, Storage Tanks, Matrix Labs and
    #: Spray Coaters all stack, and their belt ports rise with the stack, so a
    #: belt sitting a level above one of these is a CONNECTION rather than a
    #: crossing.  ``game.belt_crossing`` needs to know the difference.
    multi_level: int
    #: ``PrefabDesc.stackHeight`` in world units.  ``None`` for buildings the
    #: paste does not subject to the vertical-construction stack ladder.
    stack_height: Fraction | None
    #: Belt and fluid PORT poses -- ``PrefabDesc.portPoses``, which is
    #: ``SlotConfig.slotPoses`` in the prefab.  The name is the game's and it is
    #: a trap: these are where a belt or a pipe meets the building, and they are
    #: NOT what a sorter's slot index means.  See :attr:`slot_poses`.
    slots: tuple[dict[str, float], ...]
    #: The same ports as :attr:`slots`, with Unity's axes mapped onto the tile
    #: grid and each pose's ``forward`` attached -- see :func:`_port_poses_for`.
    #:
    #: THIS IS WHAT A BELT IS INDEXED INTO.  A belt that docks into a building
    #: names the port's index here in its ``output_to_slot`` (feeding) or
    #: ``input_from_slot`` (drawing); the two arrays are different arrays and
    #: giving a belt a :attr:`slot_poses` index would name the wrong pose.
    #: Non-empty and :attr:`slot_poses` empty is the whole class of building --
    #: Ray Receiver, Energy Exchanger, Fractionator, the mining machines, the
    #: logistic stations -- that takes belts and refuses sorters.
    port_poses: tuple[SlotPose, ...]
    #: Where a sorter may attach -- ``PrefabDesc.slotPoses``, which is
    #: ``SlotConfig.insertPoses`` in the prefab, indexed exactly as a sorter's
    #: ``inputFromSlot`` / ``outputToSlot``.  Empty for a building that accepts
    #: no sorter at all (Storage Tank, Fractionator, Splitter, belts), which is
    #: also how the game's own checks read it: they skip a peer whose
    #: ``slotPoses.Length`` does not cover the index.
    slot_poses: tuple[SlotPose, ...]
    #: Where a belt ADDON looks for the belts it attaches to.
    #:
    #: This is how a Spray Coater is supplied, and it is not by sorter.  On
    #: build the game takes the nearest belt within 1.0 of each area and writes
    #: the connection itself, which is why all eight coaters in the corpus carry
    #: no connection of their own.  Area 0 is the cargo belt it sprays and sits
    #: at ``(0, 0, 0)`` -- the coater rides it.  Area 1 is the PROLIFERATOR
    #: supply, at ``(0, -1.25, 1)``: one tile and a quarter behind the coater
    #: and exactly one altitude level up.
    addon_areas: tuple[AddonSupplyPose, ...]
    cover_radius: Fraction
    connect_distance: Fraction
    #: ``PrefabDesc.isPowerNode`` -- ``PowerDesc.node`` on the prefab, read by
    #: ``scripts/extract_dsp_power.py``.
    #:
    #: NOT the same question as ``cover_radius > 0``, which is what
    #: ``validate._supplies_power`` asks and which is the right question for
    #: ``power.coverage``: a Solar Panel, an Accumulator and a Geothermal Power
    #: Station are all power NODES with a cover radius of exactly zero.  They
    #: join the network and they are subject to
    #: ``EBuildCondition.PowerTooClose``; they supply nothing to the machines
    #: around them.  Three of the thirteen nodes in the table are in that state,
    #: so the two predicates genuinely differ.
    is_power_node: bool = False
    #: ``PrefabDesc.isAccumulator``.  The one exemption from the spacing rule:
    #: ``BuildTool_BlueprintPaste.cs:2527`` gates the whole block on
    #: ``isPowerNode && !isAccumulator``, so accumulators may be packed solid.
    is_accumulator: bool = False
    #: ``PrefabDesc.windForcedPower``.  Raises this building's spacing gate to
    #: :data:`flab2bp.dsp.rules.WIND_TOO_CLOSE_SQR`.
    wind_forced_power: bool = False
    #: ``PrefabDesc.geothermal``.  Raises it to
    #: :data:`flab2bp.dsp.rules.GEOTHERMAL_TOO_CLOSE_SQR`.
    geothermal: bool = False

    @property
    def power_node(self) -> PowerNode:
        """This building as the four flags ``EBuildCondition.PowerTooClose`` reads.

        One conversion, so a caller cannot pass the booleans in the wrong order
        and the check and the two packers cannot drift apart on which flags
        matter.  See :func:`flab2bp.dsp.rules.power_node_condition`.
        """
        return PowerNode(
            is_power_node=self.is_power_node,
            is_accumulator=self.is_accumulator,
            wind_forced_power=self.wind_forced_power,
            geothermal=self.geothermal,
        )

    @property
    def is_belt_addon(self) -> bool:
        return self.addon_type == 1

    @property
    def occupies_tiles(self) -> bool:
        return not self.is_belt_addon

    @property
    def has_explicit_slots(self) -> bool:
        return bool(self.slots)

    @property
    def takes_belt_ports(self) -> bool:
        """Does a BELT dock into this building instead of a sorter serving it?

        The two arrays are independent and the game reads them with two
        different tools -- ``BuildTool_Inserter`` drops a target whose
        ``slotPoses`` (our :attr:`slot_poses`) is empty, ``BuildTool_Path``
        drops one whose ``portPoses`` (our :attr:`port_poses`) is empty -- so
        "has ports" and "takes no sorter" are separate facts and this asks only
        the first.  A Storage Tank has four ports and no insert pose; a Matrix
        Lab has twelve insert poses and no port.  Nothing in the catalog has
        both, but nothing here assumes that either.
        """
        return bool(self.port_poses)


def derive_footprint(extent: float) -> int:
    """Tiles occupied along one axis by a building whose collider is this wide.

    ``extent`` is a FULL width in **world units**, measured about the building's
    own centre -- :func:`colliders.own_centre_extent`.

    A building centred on a tile covers the tile centres its collider reaches.
    Tile centres are ``colliders.GRID_ARC`` = 1.2566 world units apart, **not
    one unit**, so for a half-extent ``e`` the covered tiles are those ``k``
    with ``|k| * GRID_ARC < e``, which numbers

        2 * ceil(e / GRID_ARC) - 1

    and is still always odd.  The oddness is not a convention: across the
    corpus every production building is integer-centred (3,038 of 3,038), and
    an even-width building centred on an integer would straddle tile
    boundaries.  ``tile_to_local_offset``'s half-tile branch therefore stays
    unreachable, and ``test_no_catalog_footprint_is_even`` still holds.

    **This used to divide by 1.0** -- ``2 * ceil(box / 2) - 1`` on a
    ``blueprintBoxSize`` -- which is a unit error, and it was fed a second one:
    ``blueprintBoxSize`` is the game's own ``buildCollider.ext * 2`` for the
    LAST Build box, which for a prefab with three or more boxes is exactly the
    one ``buildColliders`` excludes.  The two errors point opposite ways and
    cancel on most buildings, which is why the old rule scored a clean sheet
    against the corpus.  Where they do not cancel:

    * Chemical Plant: box 8.20 -> 9 tiles, collider 8.60 -> **7**.
    * Energy Exchanger: box 11.70 -> 11, which ``temple-of-effectiveness``
      refutes with 209 overlapping cells; collider 11.70 -> **9**, which is the
      value the hand override used to carry.
    * Sorters: degenerate 0.52 x 0.23 -> 1x1, also formerly a hand override.
    * Splitter: 3x1 -> **1x1**, which ``junction.make_splitter`` already forced
      by hand for exactly this reason.
    * Spray Coater: 1x1 -> **1x3**; its tested box is 3.8 about its own centre,
      not the 2.0 ``blueprintBoxSize`` claims.

    Every corpus-pinned footprint is unchanged: assembler 3.82 -> 3, Matrix Lab
    5.60 -> 5, Arc Smelter 2.90 -> 3, Oil Refinery 3.52x7.80 -> 3x7, Depot Mk.I
    3.00 -> 3, Tesla Tower 0.60 -> 1, Wind Turbine -> 3, Solar Panel -> 3.
    Using the corrected divisor on ``blueprintBoxSize`` instead is REFUTED: it
    makes an Oil Refinery 3x5, and the corpus puts sorter endpoints three tiles
    from a refinery's centre.
    """
    from flab2bp.dsp import colliders

    half = extent / 2.0
    # Subtract an epsilon so a half-extent that lands exactly on a tile centre,
    # which does not cover it, does not round up into one.
    return max(1, 2 * math.ceil(half / colliders.GRID_ARC - 1e-9) - 1)


# There is no footprint override table any more, and its removal is a result
# rather than a tidy-up.  It held two entries, both of them corrections to the
# unit error in :func:`derive_footprint`, and the corrected rule now produces
# both from the collider data alone:
#
# * Sorters (2011-2014): a degenerate 0.52 x 0.23 collider, because a sorter is
#   a line between two endpoints rather than a box -> 1x1, as the table said.
# * Energy Exchanger (2209): the table said 9x9 because the derived 11x11 was
#   refuted by `temple-of-effectiveness` -- 20 exchangers on a clean integer
#   grid exactly 10.0 apart, which at 11x11 is 209 overlapping cells the game
#   cannot have emitted.  The corrected rule derives 9x9 from the same 11.70
#   collider the old one turned into 11.  `test_the_former_overrides_are_now
#   _derived` pins both, so the rule cannot drift back off them silently.

#: Belts carry no build collider in the asset table, so they are absent from it
#: entirely. One belt building occupies exactly one tile.
_BELT_ENTRIES = {
    2001: ("belt-1", "Conveyor Belt Mk.I", 35),
    2002: ("belt-2", "Conveyor Belt Mk.II", 36),
    2003: ("belt-3", "Conveyor Belt Mk.III", 37),
}


def _pose(data: _PoseData) -> SlotPose:
    pos = data["pos"]
    fwd = data["fwd"]
    return SlotPose(
        dx=pos[0],
        dy=pos[2],
        dz=pos[1],
        fx=fwd[0],
        fy=fwd[2],
        fz=fwd[1],
    )


def _slot_poses_for(prefab: str, table: _PoseTable) -> tuple[SlotPose, ...]:
    """``prefab``'s sorter slots, with Unity's model axes mapped onto the grid."""
    entry = table.get(prefab)
    return () if entry is None else tuple(_pose(data) for data in entry["slotPoses"])


def _port_poses_for(prefab: str, table: _PoseTable) -> tuple[SlotPose, ...]:
    """``prefab``'s BELT ports, in the same grid frame as :func:`_slot_poses_for`.

    ``SlotConfig.slotPoses``, which ``PrefabDesc`` calls ``portPoses`` -- the
    array a BELT is indexed into, not a sorter.  ``buildings.json`` carries the
    same positions in :attr:`Building.slots`, as raw ``x/y/z/yaw`` dicts, and
    that field stays as it is because two callers count it.  This is the same
    data with the axes mapped and the ``Pose.forward`` vector attached, which is
    what any geometry has to have: a port's forward is what says which SIDE of
    the building it is on, and the ``yaw`` field in ``slots`` is a rounded
    degree where the forward is the vector the game itself dots against.
    """
    entry = table.get(prefab)
    return () if entry is None else tuple(_pose(data) for data in entry["portPoses"])


@cache
def _port_poses_by_model() -> dict[int, tuple[SlotPose, ...]]:
    """All ``PrefabDesc.portPoses`` arrays, including item-less model variants."""
    values = _array(_json(_DATA), str(_DATA))
    poses = _parse_pose_table(_json(_SLOT_POSES))
    out: dict[int, tuple[SlotPose, ...]] = {}
    for index, value in enumerate(values):
        path = f"{_DATA}[{index}]"
        row = _mapping(value, path)
        model_value = _required(row, "modelIndex", path)
        if model_value is None:
            continue
        model_index = _integer(model_value, f"{path}.modelIndex")
        prefab = _string(_required(row, "prefab", path), f"{path}.prefab")
        out[model_index] = _port_poses_for(prefab, poses)
    return out


def port_poses_for_model(model_index: int) -> tuple[SlotPose, ...]:
    """Return the game's belt-port poses for an exact prefab model.

    Items may select alternate models without separate item ids.  Splitter
    models 38, 39 and 40 are the load-bearing case: their ports have different
    directions and heights, so looking the item up would silently substitute
    model 38 for the two vertical variants.
    """
    try:
        return _port_poses_by_model()[model_index]
    except KeyError as exc:
        raise KeyError(f"unknown DSP model index {model_index}") from exc


#: World units per altitude level, from the blueprint paste path::
#:
#:     lpos = dir * (localOffset_z * 1.3333333f + 0.2f + realRadius)
#:
#: Only :func:`_addon_areas_for` uses it, to turn the prefab's world-space addon
#: offsets into the levels the rest of this project counts in.


def _asset_altitude_level(value: object) -> Fraction:
    """Normalize the asset's rounded Unity height into project levels."""
    level = Fraction(str(value)) / Fraction(WORLD_UNITS_PER_LEVEL).limit_denominator()
    nearest = round(level)
    if abs(level - nearest) <= Fraction(1, 10_000):
        return Fraction(nearest)
    return level.limit_denominator(10_000)


def _asset_stack_height(value: object) -> Fraction:
    """Recover the game's stack pitch from the two-decimal asset dump.

    ``buildings.json`` records the Splitter's ``2.666667f`` as ``2.67``.  In
    blueprint z that is 2.0025 rather than the exact two-level pitch used by
    ``BuildTool_BlueprintPaste.cs:2063``.  Snap only when the converted pitch is
    within the dump's half-cent precision of an integer, then convert back to
    world units.
    """
    height = Fraction(str(value))
    pitch = height * BELT_Z_PER_WORLD_UNIT
    nearest = round(pitch)
    if abs(pitch - nearest) <= Fraction(1, 200):
        return Fraction(nearest) / BELT_Z_PER_WORLD_UNIT
    return height


def stack_pitch_z(item_id: int) -> Fraction | None:
    """One vertical stack step in blueprint ``z``, from prefab data."""
    height = building(item_id).stack_height
    if height is None:
        return None
    return (height * BELT_Z_PER_WORLD_UNIT).limit_denominator(10_000)


def vertical_construction_allowed(
    item_id: int,
    z: Fraction | int,
    altitude_rules: BeltAltitudeRules,
) -> bool:
    """Whether the paste's ``OutOfVerticalConstructionHeight`` ladder accepts it.

    ``BuildTool_BlueprintPaste.cs:2036-2068`` converts world altitude to a
    rounded stack index and refuses when that index is at least the save's lab
    or storage level.  Python's :func:`round` and ``Mathf.RoundToInt`` both use
    midpoint-to-even.
    """
    pitch = stack_pitch_z(item_id)
    if pitch is None:
        return True
    if item_id not in STORAGE_STACK_IDS and item_id not in MATRIX_LAB_IDS:
        return True
    level = (
        altitude_rules.lab_level
        if item_id in MATRIX_LAB_IDS
        else altitude_rules.storage_level
    )
    return round(Fraction(z) / pitch) < level


def _addon_areas_for(
    prefab: str, table: _PoseTable
) -> tuple[AddonSupplyPose, ...]:
    """``prefab``'s addon areas, in tiles across and altitude levels up."""
    entry = table.get(prefab)
    if entry is None:
        return ()
    return tuple(
        AddonSupplyPose(
            dx=Fraction(str(pose[0])),
            dy=Fraction(str(pose[2])),
            dz=_asset_altitude_level(pose[1]),
            area=area,
        )
        for area, pose in enumerate(entry["addonAreas"])
    )


def _number_or_default(
    row: Mapping[object, object], key: str, path: str, default: float = 0.0
) -> float:
    if key not in row:
        return default
    return _number(row[key], f"{path}.{key}")


def _building_slot(value: object, path: str) -> dict[str, float]:
    row = _mapping(value, path)
    return {
        key: _number(_required(row, key, path), f"{path}.{key}")
        for key in ("x", "y", "z", "yaw")
    }


@cache
def _load() -> dict[int, Building]:
    from flab2bp.dsp import colliders

    values = _array(_json(_DATA), str(_DATA))
    poses = _parse_pose_table(_json(_SLOT_POSES))
    out: dict[int, Building] = {}
    for index, value in enumerate(values):
        path = f"{_DATA}[{index}]"
        row = _mapping(value, path)
        item_id_value = _required(row, "itemId", path)
        if item_id_value is None:
            continue  # prefab variant with no item of its own
        item_id = _integer(item_id_value, f"{path}.itemId")
        if item_id in out:
            # Several prefab variants can share one item id (splitter-a/b/c).
            # The first is authoritative; later ones are alternate models.
            continue
        prefab = _string(_required(row, "prefab", path), f"{path}.prefab")
        name = _string(_required(row, "name", path), f"{path}.name")
        model_index_value = _required(row, "modelIndex", path)
        if model_index_value is None:
            raise _CatalogDataError(f"buildable prefab {prefab!r} has no modelIndex")
        model_index = _integer(model_index_value, f"{path}.modelIndex")

        # NOT `row["blueprintBoxSize"]`: the game computes that field from a
        # single collider (`ReadPrefab` 217456) and keeps the LAST Build box,
        # which for a prefab with three or more boxes is precisely the box
        # `buildColliders` leaves out.  Read the colliders instead.
        ex, ez = colliders.own_centre_extent(model_index, 0.0)
        w, h = derive_footprint(ex), derive_footprint(ez)

        slot_values = (
            _array(row["slots"], f"{path}.slots") if "slots" in row else []
        )
        stack_height = _optional_number(row, "stackHeight", path)
        power_value = row.get("power")
        power = (
            None
            if power_value is None
            else _mapping(power_value, f"{path}.power")
        )
        power_path = f"{path}.power"
        building = Building(
            prefab=prefab,
            item_id=item_id,
            name=name,
            model_index=model_index,
            width=int(w),
            height=int(h),
            addon_type=_optional_integer(row, "addonType", path, 0),
            multi_level=_optional_integer(row, "multiLevel", path, 0),
            stack_height=(
                _asset_stack_height(stack_height)
                if stack_height is not None
                else None
            ),
            slots=tuple(
                _building_slot(slot, f"{path}.slots[{slot_index}]")
                for slot_index, slot in enumerate(slot_values)
            ),
            port_poses=_port_poses_for(prefab, poses),
            slot_poses=_slot_poses_for(prefab, poses),
            addon_areas=_addon_areas_for(prefab, poses),
            cover_radius=Fraction(
                _number_or_default(power, "coverRadius", power_path)
                if power is not None
                else 0
            ).limit_denominator(100),
            connect_distance=Fraction(
                _number_or_default(power, "connectDistance", power_path)
                if power is not None
                else 0
            ).limit_denominator(100),
            is_power_node=(
                _optional_boolean(power, "node", power_path)
                if power is not None
                else False
            ),
            is_accumulator=(
                _optional_boolean(power, "accumulator", power_path)
                if power is not None
                else False
            ),
            wind_forced_power=(
                _optional_boolean(power, "wind", power_path)
                if power is not None
                else False
            ),
            geothermal=(
                _optional_boolean(power, "geothermal", power_path)
                if power is not None
                else False
            ),
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
            multi_level=0,
            stack_height=None,
            slots=(),
            port_poses=(),
            slot_poses=(),
            addon_areas=(),
            cover_radius=Fraction(0),
            connect_distance=Fraction(0),
        )
    return out


def addon_supply_pose(item_id: int, *, area: int = 1) -> AddonSupplyPose:
    """Return one addon's authoritative positional belt connection."""
    for pose in building(item_id).addon_areas:
        if pose.area == area:
            return pose
    raise ValueError(f"building item {item_id} has no addon supply area {area}")


def building(item_id: int) -> Building:
    try:
        return _load()[item_id]
    except KeyError:
        raise KeyError(f"no DSP building with item id {item_id}") from None


def footprint(item_id: int) -> tuple[int, int]:
    b = building(item_id)
    return (b.width, b.height)


@lru_cache(maxsize=1024)
def collider_span(item_id: int, yaw: float) -> tuple[float, float]:
    """Oriented collider span in grid tiles, measured about the building centre.

    Falls back to the oriented footprint when collider data is unavailable.
    Unlike :func:`clearance`, this is not rounded up; pairwise center-distance
    checks need the actual half-span sum rather than two independently rounded
    reservation pitches.
    """
    from flab2bp.dsp import colliders

    fw, fh = oriented_footprint(item_id, yaw)
    try:
        boxes = colliders.build_colliders(building(item_id).model_index)
    except Exception:  # noqa: BLE001 - preserve footprint fallback
        return (float(fw), float(fh))
    if not boxes:
        return (float(fw), float(fh))
    half_turn = math.radians(yaw) * 0.5
    spin = (0.0, math.sin(half_turn), 0.0, math.cos(half_turn))
    ex = ez = 0.0
    for centre, half, rot in boxes:
        turned = colliders._qmul(spin, rot)
        rotated_centre = colliders._qrot(spin, centre)
        for sx in (-1.0, 1.0):
            for sy in (-1.0, 1.0):
                for sz in (-1.0, 1.0):
                    local = (sx * half[0], sy * half[1], sz * half[2])
                    spun = colliders._qrot(turned, local)
                    ex = max(ex, abs(rotated_centre[0] + spun[0]))
                    ez = max(ez, abs(rotated_centre[2] + spun[2]))
    return (
        ex * 2 / colliders.GRID_ARC,
        ez * 2 / colliders.GRID_ARC,
    )


@cache
def clearance(item_id: int, yaw: float) -> tuple[int, int]:
    """Tiles to RESERVE for ``item_id`` at ``yaw`` so nothing collides with it.

    Not the same as :func:`oriented_footprint`, and the difference is the whole
    point.  A footprint is the tiles whose centres the building covers; a
    clearance is how much room it needs before the next one.  An Assembling
    Machine covers 3 but its collider is 3.82 world units, and a tile is
    ``colliders.GRID_ARC`` = 1.2566 of them -- so 3 tiles is 3.77 and two of
    them at that pitch INTERSECT.  ``geom.collide`` reported 443 such pairs.

    Reserving ``ceil(extent / GRID_ARC)`` per building and keeping the
    reservations disjoint gives a centre-to-centre distance of at least
    ``(cl_a + cl_b) / 2``, which is at least the ``(ext_a + ext_b) / (2 *
    GRID_ARC)`` the colliders actually require -- for any PAIR, not just two of
    a kind.  It over-reserves by less than a tile per pair, which wastes space
    and can never collide; the reverse trade is what shipped red.

    The extent is measured on the ROTATED collider, not by swapping the two
    numbers: the tested box turns with the building, and a box that is not
    square about its own centre does not have swappable extents.

    Buildings whose colliders cannot be read fall back to the footprint, which
    is what the packer used before this existed.  That is not a guess about
    geometry -- it is the previous behaviour, unchanged, for a building we have
    no collider data for.
    """
    from flab2bp.dsp import colliders

    fw, fh = oriented_footprint(item_id, yaw)
    ex, ez = colliders.own_centre_extent(building(item_id).model_index, yaw)
    if not (ex or ez):
        return (fw, fh)
    return (
        max(fw, math.ceil(ex / colliders.GRID_ARC)),
        max(fh, math.ceil(ez / colliders.GRID_ARC)),
    )


def oriented_footprint(item_id: int, yaw: float) -> tuple[int, int]:
    """Grid extents of ``item_id`` built at ``yaw``, in tiles.

    A quarter turn swaps them.  DSP yaws are stored as floats and real
    blueprints carry values like ``355.5`` and ``-6.7e-07`` for what is plainly
    zero, so the turn is snapped rather than run through trigonometry -- the same
    reasoning, and the same snap, as :func:`flab2bp.layout.slots.to_local`.

    Both extents are odd for everything placeable -- ``derive_footprint`` can
    only return odd, and there is no override table any more -- so a rotated
    building still has a tile at its centre and ``tile_to_local_offset`` stays
    exact.

    Swapping is exactly right rather than merely close, because the extents come
    from an AABB taken about the building's OWN centre: turning such a box by a
    quarter is the same box with its two horizontal extents exchanged.  That is
    not true of the raw collider set, which is why :func:`clearance` sweeps the
    corners instead of swapping.
    """
    w, h = footprint(item_id)
    return (h, w) if int(round(yaw / 90.0)) % 2 else (w, h)


def all_buildings() -> tuple[Building, ...]:
    return tuple(_load().values())
