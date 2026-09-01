"""What in ``dsp/`` is a game rule, declared rather than guessed.

This module holds no rules.  It holds the *declaration* of which module-level
names in :mod:`flab2bp.dsp` are rules, which are data, and which are quality
knobs -- and, for a rule that is a function of something, what that something
is.  :mod:`flab2bp.dsp.provenance` is the machinery that reads it; the tests in
``tests/rules/`` are what turn it into a number.

Why a declaration and not a heuristic
-------------------------------------

Steps R1 and R2 of ``docs/RULE_CONSOLIDATION_PLAN.md`` both need to tell a game
constant from a quality knob.  ``freeform.LEVELS = 3`` and
``spine.UNIFORM_ROW_PITCH`` were set by measurement and look exactly like rules;
``1.8975``, ``0.8`` and ``1.6`` are the game's.  No regex over numbers separates
those, and a lint that guesses wrong gets switched off by the next person who
trips on it.  So the distinction is written down here, once, and every mechanism
reads it from here.

The four kinds
--------------

``RULE``
    Falsifiable by pasting: get it wrong and the game draws the build red, or
    silently drops a connection.  These are the entries R2 counts and R4
    perturbs.  A ``RULE`` entry may resolve to a constant *or to a function* --
    see the next section.

``KNOB``
    Set by measurement, tunable without lying about the game.  Density, pitch,
    the altitude we choose to emit.  A knob that migrates into a ``RULE`` row is
    a consolidation that has made the codebase worse.

``DATA``
    Identity and encoding: item ids, recipe names, format versions, fixture
    lists.  Wrong values here break us, but not because the game's *rules* say
    so.

``DERIVED``
    A projection of another declared entry, which must be named in
    ``projection_of``.  A derived value is allowed to have no independent
    citation precisely because it has no independent content.

A rule may be a function of technology level
--------------------------------------------

``docs/RULE_CONSOLIDATION_PLAN.md``: *"a rule whose value depends on researched
tech, building tier, or unlock state is still a rule with a citation -- the
citation just resolves to a table or a lookup rather than a literal."*

So every entry records ``depends_on``: the declared inputs the rule varies over,
in words.  Empty means the rule really is a scalar.  Non-empty means the value
varies, and then exactly one of two things must be true, which
:mod:`flab2bp.dsp.provenance` checks mechanically:

* the entry's value is itself a lookup (a mapping, or a callable taking the
  input); or
* ``resolved_by`` names the ``dsp`` callable that resolves the dependency,
  and the entry is that callable's default or one of its cases.

An entry with a non-empty ``depends_on``, a scalar value, and no ``resolved_by``
is a **flattened rule**: right by coincidence at one tech level and silently
wrong at every other.  ``provenance.flattened()`` reports those, and they are
ledger rows.

``hardcodes`` is the other half of the same idea.  ``DEFAULT_MAX_BELT_Z`` is
``belt_max_z()`` evaluated at the starting lab level; a layout module that reads
it is consulting the rule *at a hardcoded tech level*, which R2 reports
separately from not consulting it at all.
"""

from __future__ import annotations

import importlib
from collections.abc import Iterator
from dataclasses import dataclass
from enum import Enum
from typing import TypedDict, Unpack, cast

__all__ = [
    "ENTRIES",
    "Entry",
    "Kind",
    "PASTE_AMBIGUITIES",
    "by_symbol",
    "of_kind",
    "resolve",
    "rules",
]


class Kind(Enum):
    """See the module docstring.  The four-way split is the whole point."""

    RULE = "rule"
    KNOB = "knob"
    DATA = "data"
    DERIVED = "derived"


@dataclass(frozen=True, slots=True)
class Entry:
    """One declared module-level name in :mod:`flab2bp.dsp`."""

    #: ``"catalog.MAX_BELT_SLOPE"`` -- module basename inside ``flab2bp.dsp``.
    symbol: str
    kind: Kind
    #: Declared inputs this rule varies over, in words.  Empty = a true scalar.
    depends_on: tuple[str, ...] = ()
    #: ``dsp`` callable that resolves ``depends_on`` for callers.
    resolved_by: str | None = None
    #: For ``DERIVED``: the entry this one is computed from.
    projection_of: str | None = None
    #: Inputs this entry pins to a fixed value.  A reader of an entry with a
    #: non-empty ``hardcodes`` is consulting the rule at an assumed tech level.
    hardcodes: tuple[str, ...] = ()
    #: Whether R1 should hunt for this value as a bare literal outside ``dsp``.
    #: ``False`` for values too ordinary to be evidence of anything -- ``3``,
    #: ``0.5``, slot indices -- where a match would be noise, not a finding.
    lint: bool = False
    #: For a callable rule with a finite domain: how to enumerate its values so
    #: R1 can hunt for those too.  Only ``"model_index"`` is implemented.
    lint_enumerate: str | None = None
    #: Free text.  Where the evidence lives, or why a row is unusual.
    note: str = ""
    #: Set for a ``RULE`` that is knowingly consulted by nothing, with the
    #: reason.  R2 counts these separately; it does not excuse them.
    unconsulted_because: str | None = None
    #: Why R4 deliberately does not perturb this RULE.  Reserved for a rule
    #: outside emitted-blueprint paste, or a dead protocol bound with no reader;
    #: applicable paste rules stay in R4 even while their downstream reader is
    #: a declared gap.
    mutation_exempt_because: str | None = None

    @property
    def module(self) -> str:
        return self.symbol.split(".", 1)[0]

    @property
    def name(self) -> str:
        return self.symbol.split(".", 1)[1]

    @property
    def dotted(self) -> str:
        return f"flab2bp.dsp.{self.symbol}"


class _EntryOptions(TypedDict, total=False):
    depends_on: tuple[str, ...]
    resolved_by: str | None
    projection_of: str | None
    hardcodes: tuple[str, ...]
    lint: bool
    lint_enumerate: str | None
    note: str
    unconsulted_because: str | None
    mutation_exempt_because: str | None


def _e(symbol: str, kind: Kind, **kw: Unpack[_EntryOptions]) -> Entry:
    return Entry(symbol=symbol, kind=kind, **kw)


_TECH_SLOPE = "technology: super-magnetic-field-generator (belt vertical construction)"
_TECH_LAB = "technology: vertical-construction-* (lab level)"

#: What ``EBuildCondition.PowerTooClose``'s three tiers vary over.  Not a tech
#: level -- a pair of ``PrefabDesc`` flags on the buildings themselves, served
#: by ``catalog.Building.wind_forced_power`` / ``.geothermal``.  A dependency is
#: a dependency whatever it is a function OF; recording only the 12.25 would be
#: a flattened rule in exactly the sense this module defines.
_POWER_TIER = (
    "building: PrefabDesc.windForcedPower",
    "building: PrefabDesc.geothermal",
)


# --- catalog ---------------------------------------------------------------

_CATALOG: tuple[Entry, ...] = (
    _e("catalog.BELT_IDS", Kind.DATA, note="Item ids for the three belt tiers."),
    _e("catalog.SORTER_IDS", Kind.DATA),
    _e("catalog.SPLITTER_ID", Kind.DATA),
    _e(
        "catalog.SPLITTER_MODEL_INDICES",
        Kind.DATA,
        note=(
            "Game model identities for the Splitter variants supported by the "
            "port validator; the model numbers are protocol data, not geometry."
        ),
    ),
    _e("catalog.SPRAY_COATER_ID", Kind.DATA),
    _e("catalog.FRACTIONATOR_ID", Kind.DATA),
    _e("catalog.TESLA_TOWER_ID", Kind.DATA),
    _e("catalog.STORAGE_STACK_IDS", Kind.DATA),
    _e("catalog.MATRIX_LAB_IDS", Kind.DATA),
    _e("catalog.ENERGY_EXCHANGER_ID", Kind.DATA),
    _e("catalog.RAY_RECEIVER_ID", Kind.DATA),
    _e(
        "catalog.BELT_INTEGRATED_IDS",
        Kind.DERIVED,
        projection_of="catalog.BELT_IDS",
        note="Union of the belt, sorter and splitter ids; no content of its own.",
    ),
    _e(
        "catalog.SORTER_MAX_REACH",
        Kind.RULE,
        lint=False,
        note=(
            "Declared NOT tier-dependent, and the docstring carries the corpus "
            "evidence for that: Mk.I reaches 3.4 while Mk.II tops out at 2.2, so "
            "the cap belongs to sorters generally.  Recorded here as a scalar "
            "with an empty depends_on ON THAT EVIDENCE, not by default."
        ),
    ),
    _e(
        "catalog.SORTER_RATE_AT_1",
        Kind.RULE,
        depends_on=("sorter tier (item id)",),
        resolved_by="catalog.sorter_rate",
        note="Keyed by item id; sorter_rate divides by span.",
    ),
    _e(
        "catalog.SORTER_TIERS",
        Kind.DERIVED,
        projection_of="catalog.SORTER_RATE_AT_1",
        note="Sorter ids ordered by their one-tile throughput.",
    ),
    # `catalog.SORTER_SPANS_ALTITUDE` was declared here.  Phase V deleted it:
    # the game MEASURES a sorter's altitude span (`BuildTool_Inserter.cs:1311`)
    # and applies a MINIMUM to it (`:1347`).  Nothing caps it, so the rule we
    # declared never existed.  See `docs/RULE_LEDGER.md`.
    _e(
        "catalog.BELT_RATE",
        Kind.RULE,
        depends_on=("belt tier (item id)",),
        note="A mapping, so the tier dependency is modelled rather than flattened.",
    ),
    _e("catalog.BELT_Z_PER_WORLD_UNIT", Kind.RULE, lint=True),
    _e(
        "catalog.MAX_BELT_SLOPE",
        Kind.RULE,
        depends_on=(_TECH_SLOPE,),
        resolved_by="catalog.belt_rules_for_technologies",
        lint=True,
        note=(
            "The blueprint-paste sine gate at BuildTool_BlueprintPaste.cs:2093 "
            "is tan(theta) <= 3/4.  With the unlock there is no slope limit, so "
            "BeltAltitudeRules.vertical_construction resolves the tech branch."
        ),
    ),
    _e(
        "catalog.BELT_CLIMB_PER_TILE",
        Kind.KNOB,
        note=(
            "Its own docstring: 'NOT a cap ... this is the value we EMIT'.  "
            "MAX_BELT_SLOPE is the rule; this is the altitude we choose to use."
        ),
    ),
    _e(
        "catalog.RAMP_TILES_PER_LEVEL",
        Kind.KNOB,
        note="Follows from BELT_CLIMB_PER_TILE, which is itself a choice.",
    ),
    _e(
        "catalog.VERTICAL_STEP",
        Kind.RULE,
        depends_on=(_TECH_SLOPE,),
        resolved_by="catalog.belt_rules_for_technologies",
    ),
    # `BELT_CROSSING_CLEARANCE` had no game predicate.  The Path-only
    # `TooBendToLift` thresholds also used to live here despite never running
    # during BlueprintPaste; both dead definitions are deliberately absent.
    _e(
        "catalog.DEFAULT_LAB_LEVEL",
        Kind.RULE,
        depends_on=(_TECH_LAB,),
        resolved_by="catalog.belt_rules_for_technologies",
        unconsulted_because=(
            "Save-rule normalization consumes this outside layout/validator roots."
        ),
        mutation_exempt_because=("R4 measures emitted-layout seams, not request normalization."),
        note="GameHistoryData.Init: labLevel = 3 on a new save.",
    ),
    _e(
        "catalog.DEFAULT_STORAGE_LEVEL",
        Kind.RULE,
        depends_on=(_TECH_LAB,),
        resolved_by="catalog.belt_rules_for_technologies",
        unconsulted_because=(
            "BeltAltitudeRules carries the derived storage level, but no emitted-"
            "paste strategy or validator consumes that field yet."
        ),
        mutation_exempt_because=(
            "R4 perturbs observable emitted-paste seams; carrying this value in an "
            "otherwise-read dataclass is not an observable seam."
        ),
        note="GameHistoryData.Init: storageLevel = 2 on a new save.",
    ),
    _e("catalog.MASS_CONSTRUCTION_PREFIX", Kind.DATA),
    _e(
        "catalog.BLUEPRINT_LIMIT_BY_LEVEL",
        Kind.DATA,
        note="Mass Construction prototype lookup; None is the unlimited tier.",
    ),
    _e("catalog.BELT_SLOPE_UNLOCK_TECH", Kind.DATA),
    _e("catalog.VERTICAL_CONSTRUCTION_PREFIX", Kind.DATA),
    _e(
        "catalog.belt_slope_allowed",
        Kind.RULE,
        depends_on=(_TECH_SLOPE, "world rise", "horizontal run"),
        note=(
            "The exact TooSteep predicate is read by validation and routing; no "
            "downstream literal or fixed move table owns the rule."
        ),
    ),
    _e(
        "catalog.blueprint_limit_for_technologies",
        Kind.RULE,
        depends_on=("Mass Construction technology level",),
        unconsulted_because=(
            "PASTE GAP BlueprintNeedTech: migrate reporting/validation to compare "
            "the emitted building count with this lookup."
        ),
    ),
    _e(
        "catalog.stack_pitch_z",
        Kind.RULE,
        depends_on=("building item id", "PrefabDesc.stackHeight"),
        note=(
            "The splitter builder and validator both resolve the prefab-derived "
            "pitch rather than restating the installed Splitter's two-level step."
        ),
    ),
    _e(
        "catalog.vertical_construction_allowed",
        Kind.RULE,
        depends_on=("building item id", "blueprint z", _TECH_LAB),
        unconsulted_because=(
            "PASTE GAP OutOfVerticalConstructionHeight: migrate splitter/lab "
            "placement and validation to this tech-aware predicate."
        ),
    ),
    _e(
        "catalog.DEFAULT_MAX_BELT_Z",
        Kind.DERIVED,
        projection_of="catalog.belt_max_z",
        depends_on=(_TECH_LAB,),
        resolved_by="catalog.belt_rules_for_technologies",
        hardcodes=("lab_level = DEFAULT_LAB_LEVEL",),
        note=(
            "belt_max_z() at the starting lab level.  Reading THIS rather than "
            "the spec-derived BeltAltitudeRules.max_z is consulting the ceiling "
            "at an assumed tech level."
        ),
    ),
    _e(
        "catalog.BELT_Z_QUANTUM",
        Kind.DERIVED,
        projection_of="catalog.BELT_CLIMB_PER_TILE",
        note="Plan step 4.2: the game quantises nothing.  This is our emitter's step.",
    ),
    _e("catalog.GEOMETRY_SAFE_FIXTURES", Kind.DATA),
    _e("catalog.LOW_CONFIDENCE_FOOTPRINTS", Kind.DATA),
    _e("catalog.NO_DSP_ITEM_PREFIXES", Kind.DATA),
    _e("catalog.NO_DSP_RECIPE", Kind.DATA),
    _e("catalog.MODE_DRIVEN_MACHINE", Kind.DATA),
    # Callable rules.  A rule does not stop being a rule for being a function.
    _e(
        "catalog.belt_max_z",
        Kind.RULE,
        depends_on=("lab level, i.e. researched vertical construction",),
        resolved_by="catalog.belt_rules_for_technologies",
        unconsulted_because=("Save-rule normalization resolves this before layout strategies run."),
        mutation_exempt_because=("R4 measures emitted-layout seams, not request normalization."),
        note="GameHistoryData.buildMaxHeight, quoted in the function's docstring.",
    ),
    _e(
        "catalog.clearance",
        Kind.RULE,
        depends_on=("building item id", "yaw"),
        note=(
            "Compiled reservation projection read by packers.  Validation asks "
            "the underlying collider predicate directly, so R4's seam is strategy-only."
        ),
    ),
    _e(
        "catalog.sorter_rate",
        Kind.RULE,
        depends_on=("sorter tier (item id)", "span"),
    ),
    _e(
        "catalog.footprint",
        Kind.RULE,
        depends_on=("building item id",),
    ),
)


# --- colliders -------------------------------------------------------------

_COLLIDERS: tuple[Entry, ...] = (
    _e(
        "colliders.GRID_ARC",
        Kind.RULE,
        lint=True,
        note="One tile of longitude at the equator: 2*pi/5 world units, not 1.",
    ),
    _e("colliders.PLANET_RADIUS", Kind.RULE, lint=True),
    _e("colliders.PLANET_SEGMENT", Kind.RULE, lint=True),
    _e(
        "colliders.SORTER_END_EXTENSION",
        Kind.RULE,
        lint=True,
        note=(
            "Read by sorter collider construction on both production paths; R4's "
            "current boundary corpus moves strategy seating only, not a validator verdict."
        ),
    ),
    _e("colliders.SORTER_HALF_LENGTH_MIN", Kind.RULE, lint=True),
    _e("colliders.BELT_PROBE_RADIUS", Kind.RULE, lint=True),
    _e("colliders.BELT_PROBE_LIFT", Kind.RULE, lint=True),
    # --- dsp/planet.py: the longitude-band model and the paste sorter ladder --
    #
    # The three SORTER_* mappings are the paste's own tiered limits, keyed by
    # HOW MANY OF THE SORTER'S TWO ENDS ARE MACHINES (2, 1, 0) -- so they are
    # modelled as lookups rather than flattened to one number, which is what
    # `rules.py` did when it recorded `num133`/`num134` as deliberately
    # unported.  Its reason ("on a uniform grid `num7` reduces to
    # SORTER_MAX_REACH") fails twice: the grid is not uniform within a band,
    # and a SEATED sorter's ends are not on tile centres.
    _e(
        "planet.SORTER_SEGMENTS_MAX",
        Kind.RULE,
        depends_on=("how many ends are machines",),
        mutation_exempt_because=(
            "Final band selection consumes this threshold and has direct boundary "
            "and fit-selection controls; R4 has no integer-anchor strategy probe "
            "that isolates it from the rest of the sorter ladder."
        ),
        note="`num133`, BuildTool_BlueprintPaste.cs:3446-3459.",
    ),
    _e(
        "planet.SORTER_COMBINED_MIN",
        Kind.RULE,
        depends_on=("how many ends are machines",),
        mutation_exempt_because=(
            "Final band selection consumes this threshold and has direct boundary "
            "and fit-selection controls; R4 has no integer-anchor strategy probe "
            "that isolates it from the rest of the sorter ladder."
        ),
        note=("`num134`: a floor on sqrt(segmentsAcross^2 + altitudeSteps^2) in grid cells."),
    ),
    _e(
        "planet.SORTER_PARAM_BIAS",
        Kind.RULE,
        depends_on=("how many ends are machines",),
        unconsulted_because=(
            "PASTE GAP sorter parameter emission: sorter_parameter owns the "
            "projection, but no downstream emitter consumes it yet."
        ),
        mutation_exempt_because=(
            "The centralized projection has a direct boundary control, but emitted "
            "blueprints do not consume the parameter yet."
        ),
        note="`num129 -= 0.3f` in the machine-to-machine case.",
    ),
    _e(
        "planet.sorter_parameter",
        Kind.RULE,
        depends_on=("projected sorter pose", "how many ends are machines"),
        unconsulted_because=(
            "PASTE GAP sorter parameter emission: migrate the blueprint emitter "
            "from its span approximation to this paste projection."
        ),
        mutation_exempt_because=(
            "The centralized projection has a direct boundary control, but emitted "
            "blueprints do not call it yet."
        ),
    ),
    _e(
        "planet.SORTER_ALTITUDE_UNIT",
        Kind.RULE,
        lint=False,
        mutation_exempt_because=(
            "Final band selection consumes this altitude scale and has direct "
            "boundary controls; R4 has no integer-anchor strategy probe that "
            "isolates it from the combined sorter floor."
        ),
        note=(
            "`num130 = Abs(lpos.magnitude - lpos2.magnitude) / 0.2f`, the game's radial-step unit."
        ),
    ),
    _e(
        "planet.SEGMENT_TABLE",
        Kind.DATA,
        # Not DERIVED: `projection_of` must name a DECLARED entry, and
        # `colliders._SEGMENT_TABLE` is private and so not classified.  It is a
        # re-export, not a projection -- band code reads one table, not two.
        note="Alias of `colliders._SEGMENT_TABLE`, the game's PlanetGrid table.",
    ),
    _e(
        "planet.MATHF_PI",
        Kind.DATA,
        note=(
            "float32 pi.  Not a rule -- a representation detail, and a "
            "load-bearing one: the band arithmetic is float32 throughout "
            "because at segment=144, latIdx=24 double and float disagree about "
            "which band a row is in."
        ),
    ),
    _e(
        "colliders.belt_crossing_height",
        Kind.RULE,
        depends_on=("building model index",),
        lint=True,
        lint_enumerate="model_index",
        note=(
            "How high a belt must fly to clear a given building: 2.80-4.97 world "
            "units, 1.8975 for a coater.  A function, so R1 hunts for every value "
            "it can return rather than for one literal."
        ),
    ),
    _e(
        "colliders.belt_keepout_offsets",
        Kind.RULE,
        depends_on=("building model index", "yaw", "reach", "levels"),
        note="The other compiled projection Phase 2 cites as the good case.",
    ),
)


# --- rules -----------------------------------------------------------------

_SLOT_INDEX_NOTE = (
    "A slot index in the game's connection protocol.  lint=False: the bare "
    "integer is far too ordinary for a literal match to mean anything."
)

_RULES: tuple[Entry, ...] = (
    _e("rules.WORLD_UNITS_PER_LEVEL", Kind.RULE, lint=True),
    _e("rules.OUTPUT_FROM_SLOT", Kind.RULE, note=_SLOT_INDEX_NOTE),
    _e("rules.INPUT_TO_SLOT", Kind.RULE, note=_SLOT_INDEX_NOTE),
    _e("rules.BELT_SLOT", Kind.RULE, note=_SLOT_INDEX_NOTE),
    _e("rules.ADDON_FROM_SLOT", Kind.RULE, note=_SLOT_INDEX_NOTE),
    _e("rules.ADDON_TO_SLOT", Kind.RULE, note=_SLOT_INDEX_NOTE),
    _e("rules.SPLITTER_INPUT_TO_SLOT", Kind.RULE, note=_SLOT_INDEX_NOTE),
    _e("rules.SPLITTER_OUTPUT_FROM_SLOT", Kind.RULE, note=_SLOT_INDEX_NOTE),
    _e(
        "rules.SPLITTER_OUTPUT_TO_SLOT",
        Kind.RULE,
        note=(
            f"{_SLOT_INDEX_NOTE} The Splitter's output-side sentinel is written "
            "by both junction placement and final blueprint encoding."
        ),
    ),
    _e(
        "rules.SPLITTER_INPUT_FROM_SLOT",
        Kind.RULE,
        note=(
            f"{_SLOT_INDEX_NOTE} The Splitter's input-side sentinel is written "
            "by both junction placement and final blueprint encoding."
        ),
    ),
    _e(
        "rules.BELT_INPUT_SLOTS",
        Kind.RULE,
        note=(
            f"{_SLOT_INDEX_NOTE} Emission allocates this range; validation checks "
            "the resulting occupied cells rather than consulting the range."
        ),
    ),
    _e(
        "rules.BELT_PORT_FEED_FROM_SLOT",
        Kind.RULE,
        note=(
            "The belt's own output pool cell when it feeds a building port; all "
            "70 game-authored records use slot 0."
        ),
    ),
    _e(
        "rules.BELT_PORT_DRAW_TO_SLOT",
        Kind.RULE,
        note=(
            "The belt's own input pool cell when it draws from a building port; "
            "all 108 game-authored records use slot 1."
        ),
    ),
    _e(
        "rules.BELT_PORT_MAX_TILE_GAP",
        Kind.KNOB,
        note=(
            "A corpus-derived validator bound, not a paste threshold: the game "
            "replays the recorded port link without re-deriving its pose."
        ),
    ),
    _e(
        "rules.BELT_SLOT_AUTO_RANGE",
        Kind.RULE,
        unconsulted_because=(
            "Plan step 3.3.  Its second consequence -- a belt tile silently drops "
            "the 9th auto-slot connection -- is enforced by nothing.  Corpus "
            "worst is 6, so it has never bound."
        ),
        mutation_exempt_because=(
            "No emitted-paste reader consults the silent auto-slot pool bound; R2 "
            "keeps the dead protocol rule explicit."
        ),
    ),
    _e("rules.SPLITTER_MAX_PORTS", Kind.RULE),
    _e(
        "rules.CHEMICAL_OUTPUT_BUFFER_CRAFTS",
        Kind.RULE,
        lint=True,
        note=(
            "AssemblerComponent.InternalUpdate admits exactly 20 ordinary Chemical "
            "craft completions into each product buffer before blocking the next."
        ),
    ),
    _e("rules.SLOT_REACH", Kind.RULE, lint=True),
    _e("rules.PASTE_SNAP", Kind.RULE, lint=True),
    _e(
        "rules.PASTE_LATERAL",
        Kind.RULE,
        mutation_exempt_because=(
            "The branch is reachable only for a silo, and this project emits no "
            "silo; the applicable snap/epsilon/radial branches remain in R4."
        ),
    ),
    _e("rules.PASTE_RADIAL", Kind.RULE, lint=True),
    _e("rules.PASTE_LATERAL_EPS", Kind.RULE, lint=True),
    _e(
        "rules.PASTE_BELT_LINK_MAX_SQR",
        Kind.RULE,
        lint=True,
        unconsulted_because=(
            "PASTE GAP TooFar: migrate belt-link validation to the 5.3 squared-"
            "world-distance cap; vertical construction does not disable it."
        ),
    ),
    _e(
        "rules.belt_link_too_far",
        Kind.RULE,
        depends_on=("squared world distance between linked belts",),
        unconsulted_because=(
            "PASTE GAP TooFar: no validator currently checks a two-level belt link."
        ),
    ),
    _e(
        "rules.COATER_RESHAPE_MAX",
        Kind.RULE,
        lint=True,
        unconsulted_because=(
            "PASTE GAP TooSkew: selected-band coater reshape is not yet validated."
        ),
    ),
    _e(
        "rules.coater_reshape_allowed",
        Kind.RULE,
        depends_on=("SpraycoaterComponent reshape x", "reshape y"),
        unconsulted_because=("PASTE GAP TooSkew: migrate band certification to this predicate."),
    ),
    _e(
        "rules.SORTER_LENGTH",
        Kind.RULE,
        depends_on=("how many of the sorter's two ends land on a belt (0, 1 or 2)",),
        note="Keyed by endpoint kind, NOT by sorter tier.  flag21/flag22 in the source.",
    ),
    _e("rules.SKEW_PAIR_DEG", Kind.RULE, lint=True),
    _e(
        "rules.SKEW_AXIS_DEG",
        Kind.RULE,
        lint=True,
        note="Plan step 1.5: one constant currently serving two different rules.",
    ),
    _e(
        "rules.SLOT_ALIGN_COS",
        Kind.DERIVED,
        projection_of="rules.SKEW_AXIS_DEG",
        note="cos(SKEW_AXIS_DEG).  Plan step 4.2 questions the rule, not the projection.",
    ),
    _e("rules.ADDON_AREA_RADIUS", Kind.RULE),
    _e("rules.ADDON_LINE_MAX_DISTANCE", Kind.RULE),
    _e("rules.ADDON_AXIS_DEG", Kind.RULE, lint=True),
    _e(
        "rules.ADDON_TURRET_AXIS_DEG",
        Kind.RULE,
        lint=True,
        unconsulted_because=(
            "The same limit for a turret.  We never place a turret, so nothing "
            "can consult it.  This is declared for R2/R1 rather than mutated as "
            "though a blueprint emitted by this project could reach it."
        ),
        mutation_exempt_because="Turret addon placement is outside emitted blueprints.",
    ),
    _e("rules.ADDON_NEIGHBOUR_RADIAL_GAP", Kind.RULE, lint=True),
    # The three Phase V added after this registry was written.  MATCH_* are the
    # `MatchInserter` ladder, which is REACHED ONLY when the peer preview is
    # null -- and `BlueprintUtils.cs:1623-1624` fills that from the blueprint's
    # own records, so it never runs on anything we emit.  That applicability
    # condition is the rule, as much as the number is: recording the constant
    # without it is how RULE_AUDIT D5 came to conflate this ladder with
    # `CheckInserterDataLegal`'s 0.8.
    _e(
        "rules.MATCH_SNAP_MAX_SQR",
        Kind.RULE,
        # NOT linted: the value is 6.0, and `bench.corpus` and three sites in
        # `freeform` legitimately hold 6.0 as a budget or a count.  This
        # registry's own finding is that the game's constants are ordinary
        # numbers; linting one this common buys three declared coincidences per
        # site and teaches the next reader that R1 cries wolf.  Lint earns its
        # keep on DISTINCTIVE values -- 1.8975, 0.9702957 -- not on 6.
        lint=False,
        unconsulted_because=(
            "`MatchInserter` is reached only when the peer preview is null, and "
            "`BlueprintUtils.cs:1623-1624` fills that from the blueprint's own "
            "records -- so the ladder never runs on anything we emit.  Ported "
            "because the compiled oracle checks us against it (15488/15488); "
            "unread by the pipeline BY THE RULE'S OWN TERMS, not by neglect."
        ),
        mutation_exempt_because=(
            "MatchInserter is an interactive missing-peer recovery path; every "
            "sorter this project emits carries both peers."
        ),
        note=(
            "BuildTool_BlueprintPaste.cs:1588 `if (num4 < 6f && ...)` -- a "
            "SQUARED world distance, so 2.449 world units, NOT a sibling of "
            "SLOT_REACH.  Conflating the two is RULE_AUDIT D5's error."
        ),
    ),
    _e(
        "rules.MATCH_ALIGN_COS",
        Kind.RULE,
        lint=True,  # 0.9702957 is distinctive; a bare copy of it IS a defect.
        unconsulted_because="Same ladder, same reachability condition, same reason.",
        mutation_exempt_because=(
            "MatchInserter is an interactive missing-peer recovery path; every "
            "sorter this project emits carries both peers."
        ),
        note="BuildTool_BlueprintPaste.cs:1536, cos 14 on BOTH dots.",
    ),
    _e(
        "rules.DRAG_MAX_ALIGNMENT",
        Kind.RULE,
        # NOT linted, same reasoning: the value is 0.5.
        lint=False,
        note=(
            "The belt-end drag's alignment gate, moved out of layout/ by Phase "
            "V so the rule lives where the other paste rules do."
        ),
    ),
    # --- EBuildCondition.PowerTooClose and its two upper tiers --------------
    #
    # A rule this registry's own tech-and-tier clause is about: `num37` is a
    # LOOKUP on two `PrefabDesc` flags, not a scalar, and flattening the three
    # tiers to the ordinary one would let a wind farm pack four times too
    # tightly.  So the three bounds are declared as the three cases of
    # `power_node_gate_sqr`, which is what `resolved_by` is for.
    _e(
        "rules.POWER_TOO_CLOSE_SQR",
        Kind.RULE,
        depends_on=_POWER_TIER,
        resolved_by="rules.power_node_gate_sqr",
        lint=True,
        note=(
            "`num37`'s ordinary case, BuildTool_BlueprintPaste.cs:2547.  A "
            "SQUARED WORLD distance: 3.5 units, 2.785 tiles.  Reading it as "
            "tiles is the `SLOT_REACH` mistake again, 26% the other way."
        ),
    ),
    _e(
        "rules.WIND_TOO_CLOSE_SQR",
        Kind.RULE,
        depends_on=_POWER_TIER,
        resolved_by="rules.power_node_gate_sqr",
        lint=True,
        note="Wind Turbine against Wind Turbine only; 10.5 world units.",
    ),
    _e(
        "rules.GEOTHERMAL_TOO_CLOSE_SQR",
        Kind.RULE,
        depends_on=_POWER_TIER,
        resolved_by="rules.power_node_gate_sqr",
        lint=True,
        note="Geothermal Power Station against itself only; 12.0 world units.",
    ),
    _e(
        "rules.PASTE_POWER_NODE_IDS",
        Kind.RULE,
        lint=False,  # 2199 and 2300 are ids; a bare match would be noise
        note=(
            "`protoId < 2199 || protoId > 2299` in both blueprint-side loops of "
            "the spacing pass.  Identity, not flags: the Signal Tower (3007) is "
            "a power node and is outside it, which makes the rule one-sided in "
            "a second way."
        ),
    ),
    _e("rules.power_node_gate_sqr", Kind.RULE, depends_on=_POWER_TIER),
    _e(
        "rules.power_node_condition",
        Kind.RULE,
        depends_on=(*_POWER_TIER, "squared world distance between the two lpos"),
    ),
    _e(
        "rules.power_node_keepout_offsets",
        Kind.RULE,
        depends_on=_POWER_TIER,
        note=(
            "The compiled projection of `power_node_condition` onto the grid, "
            "the way `colliders.belt_keepout_offsets` projects the collider "
            "test.  Both packers read it; neither restates the radius."
        ),
    ),
    _e("rules.world_gap", Kind.RULE, depends_on=("dx", "dy", "dz")),
    _e(
        "rules.addon_line_distance",
        Kind.RULE,
        depends_on=("point", "line_a", "line_b"),
    ),
    _e("rules.addon_axis_aligned", Kind.RULE, depends_on=("yaw", "dx", "dy")),
    _e(
        "rules.addon_ride_is_straight",
        Kind.RULE,
        depends_on=("yaw", "incoming", "outgoing"),
    ),
)


# --- encoding --------------------------------------------------------------

_ENCODING: tuple[Entry, ...] = (
    _e("codec.DEFAULT_GAME_VERSION", Kind.DATA),
    _e("codec.DEFAULT_PAYLOAD_VERSION", Kind.DATA),
    _e("codec.DEFAULT_HEADER_VERSION", Kind.DATA),
    _e("envelope.FACTORY_PREFIX", Kind.DATA),
    _e("envelope.DYSON_PREFIX", Kind.DATA),
    _e("envelope.DOTNET_EPOCH_OFFSET_S", Kind.DATA),
    _e("envelope.TICKS_PER_SECOND", Kind.DATA),
    _e("params.CRITICAL_PHOTON_ITEM_ID", Kind.DATA),
)


#: Paste-time facts that cannot honestly be certified from the blueprint alone,
#: or whose binary prototype data has not yet been extracted.  The reporting
#: script prints these separately from code migrations.
PASTE_AMBIGUITIES: tuple[tuple[str, str], ...] = (
    (
        "NeedGround",
        "terrain and water raycasts depend on the exact planet location chosen by the player",
    ),
    (
        "PowerTooClose/live state",
        "live-network and prebuild loops depend on objects already present on the planet",
    ),
    (
        "Collide/live state",
        "birth-point and existing-object collision branches depend on the target planet",
    ),
    (
        "Vertical Construction unlock values",
        "GameHistoryData assignments are decompiled, but TechProto.UnlockValues remain "
        "unextracted; one level per FactorioLab tier is the explicit safe assumption",
    ),
    (
        "Mass Construction intermediate limits",
        "the paste comparison and assignment are decompiled and UI pins 150/3600/unlimited; "
        "the 300/900 intermediate prototype values still need an asset dump",
    ),
    (
        "INAPPLICABLE desc flags",
        "group D guards are traced to named buildings but not yet cross-checked against a "
        "complete PrefabDesc flag dump",
    ),
)


ENTRIES: tuple[Entry, ...] = _CATALOG + _COLLIDERS + _RULES + _ENCODING

_BY_SYMBOL: dict[str, Entry] = {e.symbol: e for e in ENTRIES}
if len(_BY_SYMBOL) != len(ENTRIES):  # pragma: no cover - a typo guard, not a branch
    raise RuntimeError("duplicate symbol in the dsp rule registry")


def by_symbol(symbol: str) -> Entry:
    """The entry for ``"catalog.MAX_BELT_SLOPE"``."""
    return _BY_SYMBOL[symbol]


def of_kind(kind: Kind) -> tuple[Entry, ...]:
    return tuple(e for e in ENTRIES if e.kind is kind)


def rules() -> tuple[Entry, ...]:
    """Every declared game rule.  This is the denominator R2 prints."""
    return of_kind(Kind.RULE)


def resolve(entry: Entry) -> object:
    """The live object an entry names.  Raises if the declaration has rotted."""
    module = importlib.import_module(f"flab2bp.dsp.{entry.module}")
    # Erase reflection's dynamic type only to top-type object; callers must narrow.
    return cast(object, getattr(module, entry.name))


def declared_symbols() -> Iterator[str]:
    for e in ENTRIES:
        yield e.symbol


#: Module-level names in ``dsp`` that the completeness check does not require an
#: entry for.  Private names and imports are excluded structurally; this is for
#: the handful that are neither.
EXEMPT: frozenset[str] = frozenset()


# --- R1's declared coincidences --------------------------------------------


@dataclass(frozen=True, slots=True)
class LintException:
    """One site where a literal equals a rule constant and is not that rule.

    Keyed on ``(module, top-level definition, value)`` and deliberately NOT on a
    line number, which rots on the next edit.  A stale exception -- one that
    matches nothing -- is reported and does not fail: the alternative is a lint
    that breaks whenever somebody else renames a function, and a lint that
    breaks for the wrong reason gets switched off.
    """

    module: str
    where: str
    value: float
    why: str


#: Measured, not assumed.  Running R1 with no exceptions produced the sites
#: below and nothing else.  Each is a quality knob, timeout, or integer infinity
#: sentinel whose number happens to coincide with a game constant.  That is the
#: finding R1 actually produced: the game's constants are ordinary numbers.
#: The plan expected R1 to start green; it does once these coincidences are
#: written down.  ``0.8`` remains ``SLOT_REACH`` even though the
#: paste-authoritative belt slope is now ``3/4``.
#:
#: The teeth are still there.  These suppress a value AT A SITE, not the value.
#: A new ``0.8`` anywhere else in ``layout/`` still fails.
LINT_EXCEPTIONS: tuple[LintException, ...] = (
    LintException(
        "flab2bp.bench.snaporacle",
        "selftest",
        200.0,
        "subprocess timeout in seconds; PLANET_RADIUS is world units",
    ),
    LintException(
        "flab2bp.bench.snaporacle",
        "ask",
        200.0,
        "subprocess timeout in seconds; PLANET_RADIUS is world units",
    ),
    LintException(
        "flab2bp.layout.freeform",
        "<module>",
        0.35,
        "_PACK_SHARE: CP-SAT's share of a sweep's clock, set by measurement",
    ),
    LintException(
        "flab2bp.layout.sequence_pair",
        "SearchEnergy",
        0.35,
        "weighted-HPWL objective coefficient; not SORTER_END_EXTENSION geometry",
    ),
    LintException(
        "flab2bp.layout.sequence_pair",
        "SearchEnergy",
        0.2,
        "history-cost objective coefficient; not BELT_PROBE_LIFT geometry",
    ),
    LintException(
        "flab2bp.layout.sequence_pair",
        "SearchEnergy",
        0.1,
        "direct-insert miss objective coefficient; not sorter geometry or paste epsilon",
    ),
    LintException(
        "flab2bp.layout.compact_seed",
        "CompactTopologyBeamConfig",
        0.2,
        "per-candidate CP deterministic work; not BELT_PROBE_LIFT geometry",
    ),
    LintException(
        "flab2bp.layout.finalize",
        "uses_tall_saturated_role",
        24.0,
        "shared strip-count complexity cap; not skew degrees",
    ),
    LintException(
        "flab2bp.layout.sequence_solver",
        "<module>",
        24.0,
        "_TOPOLOGY_BEAM_MAX_STRIPS: quadratic model-size cap; not skew degrees",
    ),
    LintException(
        "flab2bp.layout.sequence_solver",
        "<module>",
        0.1,
        "_COMPACT_LARGE_VARIANT_DETERMINISTIC_CAP: CP deterministic work; "
        "not sorter geometry or the paste lateral epsilon",
    ),
    LintException(
        "flab2bp.layout.sequence_solver",
        "<module>",
        0.2,
        "_TOPOLOGY_BEAM_DETERMINISTIC_SECONDS: CP work; not BELT_PROBE_LIFT geometry",
    ),
    LintException(
        "flab2bp.layout.sequence_solver",
        "<module>",
        200.0,
        "_SHARED_PACK_MACHINE_MAX: measured seed-role size cap; not planet geometry",
    ),
    LintException(
        "flab2bp.layout.sequence_solver",
        "<module>",
        30.0,
        "_COMPACT_SEED_DIRECT_MIN_BUDGET_S: wall seconds; not skew degrees",
    ),
    LintException(
        "flab2bp.layout.freeform",
        "_astar",
        30.0,
        "`1 << 30` as an infinity sentinel for the heuristic; not degrees",
    ),
    LintException(
        "flab2bp.layout.sequence_pair",
        "derive_stage_seed",
        30.0,
        "`value >> 30` bit-mixing shift; not the sorter skew angle",
    ),
    LintException(
        "flab2bp.layout.freeform",
        "_route_all",
        1.6,
        "rip-up pressure growth `0.5 * 1.6**it`; the plan names this exact knob",
    ),
    LintException(
        "flab2bp.layout.freeform",
        "_candidate_heights",
        0.6,
        "height sweep factors (0.6, 0.8, 1.0, 1.25, 1.6) -- dimensionless ratios",
    ),
    LintException(
        "flab2bp.layout.freeform",
        "_candidate_heights",
        0.8,
        "height sweep factor; SLOT_REACH is world units",
    ),
    LintException(
        "flab2bp.layout.freeform",
        "_candidate_heights",
        1.6,
        "height sweep factor; PASTE_RADIAL is world units",
    ),
    LintException(
        "flab2bp.rates.candidates",
        "build_candidates",
        30.0,
        "CP-SAT time limit in seconds; not degrees",
    ),
    LintException(
        "flab2bp.rates.candidates",
        "_build_candidates_canonical",
        30.0,
        "CP-SAT time limit in seconds; not degrees",
    ),
    LintException(
        "flab2bp.rates.solve",
        "solve",
        30.0,
        "CP-SAT time limit in seconds; not degrees",
    ),
)
