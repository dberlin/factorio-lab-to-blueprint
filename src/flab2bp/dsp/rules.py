"""What the game PERMITS: DSP's own build predicates and their thresholds.

Everything in this module is a rule the game applies, read out of the game --
its decompiled ``Assembly-CSharp``, its locale, or its shipped prefab data --
and not an inference of ours.  Each constant carries the source that establishes
it.  Nothing here is a preference, a habit of the fixture corpus, or a value we
picked because it packed well; those belong elsewhere and are listed below.

Why this module exists
----------------------
The game's rules used to live in three forms at once -- ported predicates in
``layout.validate``, extracted tables under ``dsp/data``, and constants with the
decompiled source quoted in comments across ``dsp.catalog``, ``layout.slots``
and ``layout.junction``.  Rules got re-derived in one form and not the others.
The concrete cost: the ``24f`` skew limit was written twice, once as
``slots.SLOT_ALIGN_DEG`` and once as ``validate._SKEW_AXIS_DEG``, and the two
had no way of knowing about each other; ``slots.INPUT_TO_SLOT`` and
``junction.INPUT_TO_SLOT`` were the SAME NAME for different buildings' slot
fields with different values.

So: a rule is stated here exactly once, with its provenance, and applied
elsewhere.  ``layout.validate`` turns these into ``Finding``s; ``layout.slots``
uses them to choose what to emit so that what we write and what we check agree.

WHERE THE REST OF THE GAME'S RULES LIVE
---------------------------------------
Three forms remain, deliberately, because each is the right home for its kind:

* **Extracted data** -- ``dsp/data/slot_poses.json`` (a building's sorter slot
  poses, ``PrefabDesc.slotPoses``), ``dsp/data/colliders.json``
  (``PrefabDesc.buildColliders``), ``dsp/data/buildings.json``.  Produced by
  ``scripts/extract_dsp_slot_poses.py``, ``scripts/extract_dsp_colliders.py``
  and ``scripts/extract_dsp_tables.py``; served by :mod:`flab2bp.dsp.catalog`.
  Tables belong in tables, not in Python.

* **A ported predicate with its own geometry engine** --
  :mod:`flab2bp.dsp.colliders` is the whole of ``EBuildCondition.Collide``:
  the physics query, the exemptions, the spherical-to-flat argument and
  :data:`~flab2bp.dsp.colliders.GRID_ARC`, the fact that a tile is 1.2566 world
  units and not 1.  It is a module rather than a constant because the rule is an
  algorithm.  ``validate.geom.collide`` applies it.

* **Quantities in** :mod:`flab2bp.dsp.catalog` -- belt and sorter throughput,
  ``MAX_BELT_SLOPE`` and the ``TooSteep``/``TooBendToLift`` family,
  ``BELT_Z_PER_WORLD_UNIT``, ``belt_max_z`` and ``BeltAltitudeRules``,
  ``TESLA_COVER_RADIUS``/``TESLA_LINK_DISTANCE``, footprint derivation.  Those
  are game rules too, and they stay with the building table they are read
  against and with the technology set that parameterises them.  They are listed
  here so that this docstring is a complete index; if you are looking for a rule
  and it is not below, it is there.

Not game rules, and not to be moved here: ``catalog.SORTER_MAX_REACH`` (a
corpus measurement -- spans cluster at 1..3 with nothing at 4),
``catalog.BELT_CLIMB_PER_TILE`` (what we EMIT, not a cap),
``catalog.LOW_CONFIDENCE_FOOTPRINTS`` and ``catalog.GEOMETRY_SAFE_FIXTURES``
(statements about our evidence), and every constant in ``layout.spine`` and
``layout.freeform`` (search parameters).

TWO THINGS THE PORTS DISAGREE ABOUT, RECORDED RATHER THAN SILENTLY PICKED
------------------------------------------------------------------------
Consolidating these rules put two unit questions side by side that were never
next to each other before.  Both are recorded here, unresolved, because
resolving either would CHANGE BEHAVIOUR and this module was a move:

1. :data:`PASTE_SNAP` and :data:`PASTE_RADIAL` are compared against a WORLD
   distance by ``validate.game.inserter_paste``, but the quantity the game
   compares -- ``num40 = zero.magnitude / num38``, with ``num38`` one tile --
   is a distance in TILES.  Read literally, the port's threshold is
   ``0.8`` world units where the game's is ``0.8`` tiles = ``1.005`` world
   units -- the game's bound is a factor of ``GRID_ARC`` = 1.2566 LARGER than
   the one we apply, so our check is TIGHTER.  Tighter is the safe
   direction (we refuse pastes the game would accept, never the reverse) and
   nothing we currently emit lands in the band, but it is not faithful.
   Note that ``num41`` -- :data:`PASTE_LATERAL`, :data:`PASTE_LATERAL_EPS` -- is
   NOT divided by ``num38`` and so genuinely is in world units, which is why the
   two halves of the same ladder can differ.
   By contrast :data:`SLOT_REACH` is unambiguous: ``CheckInserterDataLegal``
   compares a bare ``Vector3.magnitude``, and the port compares world to world.

2. :data:`SORTER_LENGTH` is compared against a distance in TILES by
   ``validate.game.inserter_skew``, while the game's ``magnitude`` there is a
   world-space ``Vector3`` magnitude.  Whether ``num131``/``num132`` are
   pre-scaled by the grid size was never recorded, and the decompiled source is
   not in this repository, so it cannot be settled from here.  It decides
   nothing we emit either way: our sorters span 1 to
   ``catalog.SORTER_MAX_REACH`` = 3 tiles, i.e. 1.0 to 3.0 read as tiles and
   1.257 to 3.770 read as world units, and every one of those is inside every
   band in the table.
"""

from __future__ import annotations

import math

from flab2bp.dsp import colliders

__all__ = [
    "ADDON_AREA_RADIUS",
    "ADDON_FROM_SLOT",
    "ADDON_TO_SLOT",
    "BELT_SLOT",
    "INPUT_TO_SLOT",
    "OUTPUT_FROM_SLOT",
    "PASTE_LATERAL",
    "PASTE_LATERAL_EPS",
    "PASTE_RADIAL",
    "PASTE_SNAP",
    "SKEW_AXIS_DEG",
    "SKEW_PAIR_DEG",
    "SLOT_ALIGN_COS",
    "SLOT_REACH",
    "SORTER_LENGTH",
    "SPLITTER_INPUT_TO_SLOT",
    "SPLITTER_MAX_PORTS",
    "SPLITTER_OUTPUT_FROM_SLOT",
    "WORLD_UNITS_PER_LEVEL",
    "world_gap",
]


# --- frames ----------------------------------------------------------------
#
# Every literal below that the game compares a `Vector3` against is in WORLD
# units, and our grid is in tiles and altitude levels.  There is exactly ONE
# conversion between the two, `world_gap`, and every comparison goes through it.
# `layout.validate` once compared a tile distance with `0.8f` directly and the
# reading that produced had to be retracted; a single conversion is what stops
# that recurring.

#: World units per altitude LEVEL, from the blueprint paste path::
#:
#:     lpos = dir * (localOffset_z * 1.3333333f + 0.2f + realRadius)
WORLD_UNITS_PER_LEVEL = 4.0 / 3.0


def world_gap(dx: float, dy: float, dz: float = 0.0) -> float:
    """A grid-frame offset as the world distance the game would measure.

    Tiles and levels have different sizes in world units, so a bare Euclidean
    distance over the grid frame is not a distance at all.  Every comparison
    against :data:`SLOT_REACH` goes through this.
    """
    ex = dx * colliders.GRID_ARC
    ey = dy * colliders.GRID_ARC
    ez = dz * WORLD_UNITS_PER_LEVEL
    return math.sqrt(ex * ex + ey * ey + ez * ez)


# --- which slot a building's connection names ------------------------------

#: The sorter's own ends.  Constant on all 1288 real sorters in
#: ``tests/fixtures/*.txt``, without a single exception.  These never vary; the
#: game requires exactly this ordering and rejects the sorter outright when it
#: is reversed (``CheckInserterDataLegal``, first two tests).
OUTPUT_FROM_SLOT = 0
INPUT_TO_SLOT = 1

#: What the BELT side of a connection carries.  Also constant on all 1288 (849
#: belt inputs, 391 belt outputs, no other value).  Only the MACHINE side of a
#: connection carries a real index, and that index is a subscript into
#: ``PrefabDesc.slotPoses`` -- served by ``catalog.Building.slot_poses``, not
#: guessed from a ring rule.
BELT_SLOT = -1

#: What a belt ADDON carries in all four of its slot fields.
#:
#: A Spray Coater is not wired to anything.  All eight in the corpus record
#: ``input_obj = output_obj = -1`` with ``(15, 14)`` on both ends, and nothing
#: anywhere names one as a connection.  The game writes the same pair in
#: ``BuildTool_Addon`` (``outputToSlot = 14; inputFromSlot = 15``) and again in
#: the blueprint paste path.  It rides the belt it sits on; the association is
#: positional, and there is no sorter in it.
ADDON_FROM_SLOT = 15
ADDON_TO_SLOT = 14

#: Slot indices every splitter in the corpus uses, without exception: 25 of 25,
#: with both offsets ``0``.  These are constants, not geometry.
#:
#: They were named ``INPUT_TO_SLOT``/``OUTPUT_FROM_SLOT`` in ``layout.junction``
#: -- the same two names this module uses for a SORTER's own ends, holding
#: different values.  Prefixed here so the two can never be confused again.
SPLITTER_INPUT_TO_SLOT = 14
SPLITTER_OUTPUT_FROM_SLOT = 15

#: Ports on a DSP splitter.  Four sides, so at most four belts may attach to one
#: junction tile -- counting both the ones feeding it and the ones drawing from
#: it, since each occupies a side.  Exceeding it pastes as a splitter quietly
#: dropping connections rather than as an error, which is why it is checked.
SPLITTER_MAX_PORTS = 4


# --- BuildTool_BlueprintCopy.CheckInserterDataLegal -------------------------

#: How far a sorter end may sit from the slot pose it names, in WORLD UNITS.
#:
#: ``0.8f`` in ``BuildTool_BlueprintCopy.CheckInserterDataLegal``.  A game
#: constant, not one of ours -- and a ``Vector3.magnitude`` in Unity world
#: space, which is NOT tiles.
#:
#: A tile is ``colliders.GRID_ARC`` = 1.2566 world units, so a distance in tiles
#: has to be scaled before it is compared with this -- see :func:`world_gap`.
#: ``layout.slots`` compared them directly once and reported the corpus's worst
#: gap as 0.774 against 0.8 -- "just inside", and cited as evidence the port was
#: right.  It was evidence of nothing: 0.8 is loose enough that BOTH readings
#: pass, so the control could not tell them apart.  Read correctly the worst
#: real gap is **0.113**, which is what it should look like when the game snaps
#: a sorter end onto a pose.  What settled it was not the corpus but the
#: collider work: an Assembling Machine's 3.82-wide box does not fit a 3-tile
#: pitch at 1.2566 per tile, and real blueprints never pack one at 3.
SLOT_REACH = 0.8


# --- the ErrorInserterData ladder in BlueprintData (paste) ------------------
#
# A different predicate from CheckInserterDataLegal and the one that actually
# fires on a paste, which is what our users do with what we emit.  Pasting does
# not merely test a sorter's end -- it SNAPS it onto the slot pose::
#
#     transformedBy = slotPoses[inputFromSlot].GetTransformedBy(input pose)
#     zero          = transformedBy.position - lpos    # the correction
#     lpos          = transformedBy.position
#     num38         = CalcLocalGridSize(...)           # one tile
#     num40         = zero.magnitude / num38
#     num41         = Abs(Dot(transformedBy.right, zero))
#     if (num40 > 0.8f) {
#         if      (num41 >  0.5f)                 -> ErrorInserterData
#         else if (num41 <  0.1f && num40 > 1.6f) -> ErrorInserterData
#         else if (num41 >= 0.1f && num40 > 0.8f) -> ErrorInserterData
#     }
#     if (Dot(transformedBy.forward, (lpos2 - lpos).normalized) < 0f)
#                                                 -> ErrorInserterData
#
# So the paste is *looser* than the copy check in one band and identical
# everywhere else: a correction that is purely radial -- straight out of the
# machine's face, `num41` under a tenth -- is tolerated out to `PASTE_RADIAL`,
# and anything with real sideways slide is capped at `PASTE_LATERAL`.  This is
# the band that decides real pastes.  Measured on our own output: with every
# machine-side slot forced to 0, 41 of 60 ends landed 1.87 out and the game
# reported "Sorter data error"; with the slot the geometry implies they land
# 0.24 and it does not.  1.87 is over `PASTE_RADIAL` however square the
# approach, which is why forcing 0 could never have worked.
#
# The silo branch (`isSilo`, 2.5/2.4) is not ported: we never emit a Vertical
# Launching Silo, and porting a branch with no way to test it is how the last
# round of guesses got in.

#: The paste path's allowances.  ``num40``/``num41`` in the source; see the unit
#: caveat in this module's docstring, which applies to the two ``num40`` values.
#:
#: :data:`PASTE_LATERAL` is UNREACHABLE for anything but a silo, and it is here
#: anyway.  Its branch runs only when the snap is already over
#: :data:`PASTE_SNAP`, and at that point a lateral of :data:`PASTE_LATERAL_EPS`
#: or more is refused by the third branch and a lateral below it never reaches
#: the first -- so no input can distinguish 0.5 from any larger value.  Dropping
#: it would make the ladder shorter and the port a paraphrase.
PASTE_SNAP = 0.8
PASTE_LATERAL = 0.5
PASTE_RADIAL = 1.6
PASTE_LATERAL_EPS = 0.1


# --- EBuildCondition.TooSkew, in BuildTool_BlueprintPaste -------------------
#
# "Deflection too much" (`偏角太大`, condition 15 -- NOT `TooBend`/`弯曲过度`)::
#
#     magnitude = (lpos2 - lpos).magnitude
#     if (magnitude > num131) -> TooFar
#     if (magnitude < num132) -> TooClose
#     ...
#     if (Quaternion.Angle(lrot, lrot2) > 30f) -> TooSkew
#     normalized4 = (lpos2 - lpos).normalized
#     num135 = Acos(Abs(Dot(normalized4, lrot .Forward()))) in degrees
#     num136 = Acos(Abs(Dot(normalized4, lrot2.Forward()))) in degrees
#     if (num135 > 24f || num136 > 24f) -> TooSkew
#
# `Quaternion.Angle` between two rotations that share an up axis is the angle
# between their forwards, and both of ours are upright, so the 30-degree test is
# done on forwards.
#
# Two of the game's tests are NOT ported, both because they need the planet's
# grid rather than ours: `CalcSegmentsAcross` counts the grid segments a sorter
# crosses, which is a function of latitude, and the combined
# `sqrt(segments^2 + altitude^2)` minimum built on it.  Our sorters never change
# level (`catalog.SORTER_SPANS_ALTITUDE`) and sit on a uniform grid, where the
# length test above is the same statement; near a pole it would not be, and
# nothing we emit goes near one.

#: ``(minLength, maxLength)`` a pasted sorter is allowed, keyed by how many of
#: its two ends land on a BELT -- the ``flag21``/``flag22`` pair.  Belt-to-belt
#: is the tightest, machine-to-machine the loosest.  ``num132``/``num131`` in
#: the source; see the unit caveat in this module's docstring.
SORTER_LENGTH = {2: (0.4, 5.0), 1: (0.6, 5.5), 0: (0.9, 7.5)}

#: Degrees between a sorter's two end rotations.  ``Quaternion.Angle(lrot,
#: lrot2) > 30f``, reporting TooSkew.
SKEW_PAIR_DEG = 30.0

#: Degrees a sorter end may face off the line it runs along.  The pair of
#: ``Acos(Abs(Dot(axis, forward))) > 24f`` tests, also reporting TooSkew.
#:
#: This is ONE rule with two consumers.  ``layout.validate`` checks against it
#: and ``layout.slots`` picks slots so as to satisfy it, and until this module
#: existed each held its own ``24.0`` literal (``_SKEW_AXIS_DEG`` and
#: ``SLOT_ALIGN_DEG``) with nothing tying them together.
SKEW_AXIS_DEG = 24.0

#: :data:`SKEW_AXIS_DEG` as a cosine, for the dot-product form the game uses and
#: the one ``layout.slots`` compares against.
SLOT_ALIGN_COS = math.cos(math.radians(SKEW_AXIS_DEG))


# --- how the game attaches a belt addon ------------------------------------

#: How near a belt must pass an addon area for the game to attach it.
#: ``sqrMagnitude < 1f`` in the addon-connection pass in ``PlanetFactory``::
#:
#:     Pose pose = prefabDesc.addonAreaPoses[i];
#:     Pose transformedBy = pose.GetTransformedBy(entity pose);
#:     if (sqrMagnitude < 1f && DistancePointLine(...) < 0.3f) -> nearest belt
#:     WriteObjectConn(entityId, i, isOutput: true, num2, 13);
#:
#: WORLD units, like every other literal the game compares a ``Vector3`` with,
#: so callers reach it through :func:`world_gap`.  ``layout.validate`` once
#: compared a tile distance with ``0.8f`` the same way and getting the frames
#: wrong there cost a retraction, which is why there is exactly one conversion
#: and every caller uses it.
#:
#: The companion clause, ``Maths.DistancePointLine(...) < 0.3f`` -- how near the
#: area's centre must be to the belt's own LINE -- has never been given a
#: constant or a port; only the radius above is checked.  Recorded here as an
#: unported half of the rule rather than left implicit.
ADDON_AREA_RADIUS = 1.0
