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
from typing import Any

__all__ = [
    "ENTRIES",
    "Entry",
    "Kind",
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

    @property
    def module(self) -> str:
        return self.symbol.split(".", 1)[0]

    @property
    def name(self) -> str:
        return self.symbol.split(".", 1)[1]

    @property
    def dotted(self) -> str:
        return f"flab2bp.dsp.{self.symbol}"


def _e(symbol: str, kind: Kind, **kw: Any) -> Entry:
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
    _e("catalog.SPRAY_COATER_ID", Kind.DATA),
    _e("catalog.FRACTIONATOR_ID", Kind.DATA),
    _e("catalog.TESLA_TOWER_ID", Kind.DATA),
    _e("catalog.ENERGY_EXCHANGER_ID", Kind.DATA),
    _e("catalog.RAY_RECEIVER_ID", Kind.DATA),
    _e(
        "catalog.BELT_INTEGRATED_IDS",
        Kind.DERIVED,
        projection_of="catalog.BELT_IDS",
        note="Union of the belt, sorter and splitter ids; no content of its own.",
    ),
    _e(
        "catalog.UNPOWERED_ITEM_IDS",
        Kind.RULE,
        note="Which buildings the game does not require power for.  Belts only.",
        unconsulted_because=(
            "LEDGER ROW, found by R2.  No production code reads it -- only "
            "tests/layout/test_spine.py does.  `power.coverage` decides who "
            "needs power from `validate._POWERED`, a hand-written set of Kinds "
            "with the comment 'Belts are unpowered in DSP'.  That is the same "
            "rule stated twice, in the module the plan calls the "
            "best-consolidated rule in the codebase.  Companion to step 1.4."
        ),
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
            "With the unlock there is no slope limit at all, so the rule is a "
            "function of researched tech; BeltAltitudeRules.vertical_construction "
            "is where the variation lives."
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
    # `catalog.BELT_CROSSING_CLEARANCE` was declared here as a RULE whose fix
    # was "the ledger's".  Phase V's answer was that there is no rule: no
    # citation exists and no validator ever read it.  It survives only as a
    # spine-local trunk-altitude knob, which is not this registry's business.
    _e(
        "rules.BEND_MIN_ANGLE_WHEN_SLOPED_RAD",
        Kind.RULE,
        lint=True,
        unconsulted_because=(
            "The audit's headline finding, and plan step 0.1 is IN FLIGHT to "
            "settle it by pasting.  Ported with a citation, read by nothing.  "
            "This row is the reason R2 exists; it is not excused by being here."
        ),
    ),
    _e(
        "rules.SLOPE_DEADZONE",
        Kind.RULE,
        lint=True,
        unconsulted_because="Companion to BEND_MIN_ANGLE_WHEN_SLOPED_RAD; same row.",
    ),
    _e(
        "catalog.DEFAULT_LAB_LEVEL",
        Kind.RULE,
        depends_on=(_TECH_LAB,),
        resolved_by="catalog.belt_rules_for_technologies",
        note="GameHistoryData.Init: labLevel = 3 on a new save.",
    ),
    _e("catalog.BELT_SLOPE_UNLOCK_TECH", Kind.DATA),
    _e("catalog.VERTICAL_CONSTRUCTION_PREFIX", Kind.DATA),
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
    _e("catalog.TESLA_COVER_RADIUS", Kind.RULE, lint=True),
    _e("catalog.TESLA_LINK_DISTANCE", Kind.RULE, lint=True),
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
        note="GameHistoryData.buildMaxHeight, quoted in the function's docstring.",
    ),
    _e(
        "catalog.clearance",
        Kind.RULE,
        depends_on=("building item id", "yaw"),
        note="The compiled projection the plan's Phase 2 holds up as the good case.",
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
    _e("colliders.SORTER_END_EXTENSION", Kind.RULE, lint=True),
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
        note="`num133`, BuildTool_BlueprintPaste.cs:3446-3459.",
    ),
    _e(
        "planet.SORTER_COMBINED_MIN",
        Kind.RULE,
        depends_on=("how many ends are machines",),
        note=(
            "`num134`, same passage: a floor on "
            "sqrt(segmentsAcross^2 + altitudeSteps^2) in GRID CELLS, not world "
            "units.  This is what convicts a one-tile machine-to-machine direct "
            "insert at 1.329 against a floor of 1.451."
        ),
    ),
    _e(
        "planet.SORTER_PARAM_BIAS",
        Kind.RULE,
        depends_on=("how many ends are machines",),
        unconsulted_because=(
            "LEDGER ROW.  Nothing reads it: `planet.sorter_condition` ports the "
            "`num129` bias inline rather than through this mapping, so the "
            "constant and the code that implements it have already drifted "
            "apart on the day they landed."
        ),
        note="`num129 -= 0.3f` in the machine-to-machine case.",
    ),
    _e(
        "planet.SORTER_ALTITUDE_UNIT",
        Kind.RULE,
        # 0.2 is far too common a literal to lint on; see MATCH_SNAP_MAX_SQR.
        lint=False,
        note=(
            "`num130 = Abs(lpos.magnitude - lpos2.magnitude) / 0.2f`.  The "
            "game's own unit for a radial step -- not a tile, not a level."
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
    _e("rules.BELT_INPUT_SLOTS", Kind.RULE, note=_SLOT_INDEX_NOTE),
    _e(
        "rules.CONN_SLOTS_PER_OBJECT",
        Kind.RULE,
        unconsulted_because=(
            "LEDGER ROW, found by R2.  Plan step 1.7 calls for removing three "
            "hand-rolled `* 16 + slot` copies; what R2 actually finds is that "
            "`entityConnPool[objId * 16 + slot]` survives only in PROSE -- "
            "slots.py:827, spine.py:2543, freeform.py:795 and :2726 quote it in "
            "docstrings -- while the constant itself is read by no code at all, "
            "in dsp or out of it.  R1 cannot see those either, because 16 is far "
            "too ordinary a literal to hunt for.  A rule quoted four times and "
            "enforced nowhere."
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
    ),
    _e("rules.SPLITTER_MAX_PORTS", Kind.RULE),
    _e("rules.SLOT_REACH", Kind.RULE, lint=True),
    _e("rules.PASTE_SNAP", Kind.RULE, lint=True),
    _e("rules.PASTE_LATERAL", Kind.RULE),
    _e("rules.PASTE_RADIAL", Kind.RULE, lint=True),
    _e("rules.PASTE_LATERAL_EPS", Kind.RULE, lint=True),
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
    _e("rules.ADDON_AXIS_DEG", Kind.RULE, lint=True),
    _e(
        "rules.ADDON_TURRET_AXIS_DEG",
        Kind.RULE,
        lint=True,
        unconsulted_because=(
            "The same limit for a turret.  We never place a turret, so nothing "
            "can consult it and no perturbation can turn anything red.  This is "
            "the one row where zero readers is the correct state -- but it is "
            "declared, so R2 counts it as unconsulted rather than hiding it."
        ),
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
    return getattr(module, entry.name)


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


#: Measured, not assumed.  Running R1 with no exceptions at all produced exactly
#: thirteen hits across the twelve sites below and nothing else, and every one
#: of them is a quality knob
#: whose number happens to coincide with a game constant.  That is the finding
#: R1 actually produced: the plan expected it to "start green", and it does --
#: but only once the coincidences are written down, because the game's constants
#: are ordinary numbers.  0.8 is both ``SLOT_REACH`` and four fifths.
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
        "flab2bp.layout.freeform",
        "_astar",
        30.0,
        "`1 << 30` as an infinity sentinel for the heuristic; not degrees",
    ),
    LintException(
        "flab2bp.layout.freeform",
        "_route_all",
        1.6,
        "rip-up pressure growth `0.5 * 1.6**it`; the plan names this exact knob",
    ),
    LintException(
        "flab2bp.layout.freeform",
        "FreeformLayout",
        0.1,
        "floor on a time budget in seconds, twice; not a slope deadzone",
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
        "flab2bp.layout.spine",
        "_link_towers",
        0.6,
        "aim a relay 60% of a link out; a fraction of TESLA_LINK_DISTANCE, "
        "not the addon radial gap",
    ),
    LintException(
        "flab2bp.rates.candidates",
        "build_candidates",
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
