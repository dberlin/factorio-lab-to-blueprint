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
  ``MAX_BELT_SLOPE`` and the ``TooSteep`` family, ``SORTER_MAX_REACH``,
  ``BELT_Z_PER_WORLD_UNIT``, ``belt_max_z`` and ``BeltAltitudeRules``,
  ``TESLA_COVER_RADIUS``/``TESLA_LINK_DISTANCE``, footprint derivation.  Those
  are game rules too, and they stay with the building table they are read
  against and with the technology set that parameterises them.  They are listed
  here so that this docstring is a complete index; if you are looking for a rule
  and it is not below, it is there.

Not game rules, and not to be moved here: ``catalog.BELT_CLIMB_PER_TILE`` and
``catalog.BELT_Z_QUANTUM`` (what we EMIT, not a cap -- the game quantises
nothing), ``catalog.LOW_CONFIDENCE_FOOTPRINTS`` and
``catalog.GEOMETRY_SAFE_FIXTURES`` (statements about our evidence), and every
constant in ``layout.spine`` and ``layout.freeform`` (search parameters).

``catalog.SORTER_MAX_REACH`` used to head that list, as "a corpus measurement --
spans cluster at 1..3 with nothing at 4".  It is a GAME rule and the corpus was
agreeing with it, not establishing it: ``BuildTool_Inserter.cs:1341`` refuses a
sorter crossing more than ``num7`` grid segments, ``num7`` being 3.2 / 3.499 /
3.799 by how many ends land on a belt.  The citation is now in ``catalog.py``
next to the constant.  A constant filed under "not a rule" for want of anyone
looking is the same defect as one filed as a rule for want of anyone checking,
and this module's docstring had one of each.

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
    "ADDON_AXIS_DEG",
    "ADDON_FROM_SLOT",
    "ADDON_NEIGHBOUR_RADIAL_GAP",
    "ADDON_TO_SLOT",
    "ADDON_TURRET_AXIS_DEG",
    "BELT_INPUT_SLOTS",
    "BELT_SLOT",
    "BELT_SLOT_AUTO_RANGE",
    "BEND_MIN_ANGLE_WHEN_SLOPED_RAD",
    "CONN_SLOTS_PER_OBJECT",
    "INPUT_TO_SLOT",
    "MATCH_ALIGN_COS",
    "MATCH_SNAP_MAX_SQR",
    "OUTPUT_FROM_SLOT",
    "PASTE_LATERAL",
    "PASTE_LATERAL_EPS",
    "PASTE_RADIAL",
    "PASTE_SNAP",
    "SKEW_AXIS_DEG",
    "SKEW_PAIR_DEG",
    "SLOT_ALIGN_COS",
    "SLOPE_DEADZONE",
    "SLOT_REACH",
    "SORTER_LENGTH",
    "SPLITTER_INPUT_TO_SLOT",
    "SPLITTER_MAX_PORTS",
    "SPLITTER_OUTPUT_FROM_SLOT",
    "WORLD_UNITS_PER_LEVEL",
    "addon_axis_aligned",
    "addon_axis_offset_deg",
    "addon_ride_is_straight",
    "too_bend_to_lift",
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

#: The three slots a belt receives INPUT on, as a half-open range.
#:
#: A belt's slot 0 carries its own OUTPUT link -- the belt pathfinder reads it
#: that way throughout (``ReadObjectConn(objId, 0, ...)`` for "what does this
#: belt feed"), and slots 1..3 are the three things that may feed it, which is
#: what ``BuildTool_Path`` walks when it looks for a free one::
#:
#:     for (int num163 = 1; num163 < 4; num163++)
#:     {
#:         factory.ReadObjectConn(coverObjId, num163, out ..., out otherObjId4, ...);
#:         if (otherObjId4 == 0) { outputToSlot = num163; ... break; }
#:         if (num163 == 3) { output = null; outputToSlot = 0; }   # give up
#:     }
#:
#: Counted over the fixture corpus, every belt-to-belt link the game wrote names
#: **1** (7169 records), **2** (95) or **3** (38) on the receiving belt, and
#: never 0 and never more than 3.  Both strategies used to leave the field at
#: the dataclass default of 0, which is not a value the game writes and which
#: collides with the receiving belt's own output link.
BELT_INPUT_SLOTS = (1, 4)


#: How many connection slots one object HAS.  A hard property of the game's
#: storage, not a limit it chooses to apply::
#:
#:     public void ReadObjectConn(int objId, int slot, out bool isOutput,
#:                                out int otherObjId, out int otherSlot)
#:     {
#:         ...
#:         int num = entityConnPool[objId * 16 + slot];
#:
#:     private void WriteObjectConnDirect(int objId, int slot, bool isOutput,
#:                                        int otherObjId, int otherSlot)
#:     {
#:         ...
#:         entityConnPool[objId * 16 + slot] = num;
#:
#: ONE ``int`` per ``(object, slot)``.  A slot therefore holds at most one
#: connection -- occupancy is keyed on the slot INDEX, not on the slot's pose,
#: because the pose never enters the address.  Two poses on one face are two
#: independent cells; two sorters on one index are one cell, and the second wins:
#:
#:     public void WriteObjectConn(int objId, int slot, bool isOutput,
#:                                 int otherObjId, int otherSlot)
#:     {
#:         ...
#:         if (otherSlot >= 0)
#:         {
#:             ClearObjectConn(objId, slot);
#:             ClearObjectConn(otherObjId, otherSlot);   # <- evicts the sitting tenant
#:             WriteObjectConnDirect(objId, slot, isOutput, otherObjId, otherSlot);
#:             WriteObjectConnDirect(otherObjId, otherSlot, !isOutput, objId, slot);
#:         }
#:     }
#:
#: So a blueprint naming one machine slot from two sorters does not fail loudly
#: on the pool -- it pastes with the earlier sorter silently unwired, having been
#: evicted by ``ClearObjectConn``.  What the player sees first is geometry: both
#: sorters snap onto the SAME slot pose (``BuildTool_BlueprintPaste`` sets
#: ``lpos = transformedBy.position``), land on top of each other and go
#: ``EBuildCondition.Collide``; every sorter connected to a building in error is
#: then reddened in turn::
#:
#:     else if (buildPreview16.desc.isInserter
#:              && buildPreview16.condition == EBuildCondition.Ok
#:              && ((buildPreview16.input  != null && input .condition != Ok && != NotEnoughItem)
#:               || (buildPreview16.output != null && output.condition != Ok && != NotEnoughItem)))
#:         buildPreview16.condition = EBuildCondition.ConnWithErrorBuilding;
#:
#: -- which is the "Connection target cannot be laid" of the paste that produced
#: this constant, reported next to "Collide with other object".
#:
#: Confirmed on the corpus, which is what a rule this consequential deserves:
#: over the 10 real game blueprints in ``tests/fixtures`` -- ~10,000 connection
#: records -- **no** ``(object, slot)`` is named twice, on either reading of the
#: scope (machine peers only, or every peer carrying an explicit index).
CONN_SLOTS_PER_OBJECT = 16

#: Where the game puts a connection whose peer slot is left to it, i.e. one
#: recorded as :data:`BELT_SLOT`.  ``WriteObjectConn`` scans this half-open
#: range for the first free cell::
#:
#:     if (otherSlot == -1)
#:         for (int i = 4; i < 12; i++)
#:             if (entityConnPool[otherObjId * 16 + i] == 0) { otherSlot = i; break; }
#:
#: Two consequences, and only the first is checked anywhere.  A ``-1`` end
#: names no fixed cell, so it cannot share one and is exempt from the uniqueness
#: rule above.  And a belt tile accepts at most ``12 - 4`` such connections:
#: past that ``otherSlot`` stays ``-1``, the guarded ``if (otherSlot >= 0)``
#: fails and the connection is dropped with no error at all.  The corpus's
#: worst belt tile carries 6, so nothing here has ever been near it and no
#: check asserts it; recorded so the bound is written down rather than
#: rediscovered.
BELT_SLOT_AUTO_RANGE = (4, 12)


#: Ports on a DSP splitter.  Four sides, so at most four belts may attach to one
#: junction tile -- counting both the ones feeding it and the ones drawing from
#: it, since each occupies a side.  Exceeding it pastes as a splitter quietly
#: dropping connections rather than as an error, which is why it is checked.
SPLITTER_MAX_PORTS = 4


# --- BuildTool_BlueprintCopy.CheckInserterDataLegal -------------------------

#: How far a sorter end may sit from the slot pose it names, in WORLD UNITS.
#:
#: ``BuildTool_BlueprintCopy.cs:1791`` (and again at ``:1815`` for the other
#: end), in ``CheckInserterDataLegal``::
#:
#:     Pose transformedBy = pose.GetTransformedBy(new Pose(objectPose3.position,
#:                                                         objectPose3.rotation));
#:     if ((objectPose2.position - transformedBy.position).magnitude > 0.8f)
#:     {
#:         return false;
#:     }
#:
#: A game constant, not one of ours -- and a ``Vector3.magnitude`` in Unity world
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


# --- BuildTool_BlueprintPaste.MatchInserter --------------------------------
#
# A THIRD predicate on a sorter end, and the one most easily mistaken for the
# two above.  It does not judge an end -- it CHOOSES the slot for an end whose
# peer the blueprint did not name.  ``BuildTool_BlueprintPaste.cs:1793-1810``::
#
#     if (buildPreview.condition == EBuildCondition.Ok && buildPreview.desc.isInserter)
#     {
#         bool num = buildPreview.input == null;
#         bool flag3 = buildPreview.output == null;
#         if (num)   { buildPreview.inputObjId  = 0; MatchInserter(buildPreview); }
#         if (flag3) { buildPreview.outputObjId = 0; MatchInserter(buildPreview); }
#     }
#
# and ``BlueprintUtils.cs:1623-1624`` fills those two fields straight from the
# blueprint's own records::
#
#     buildPreview.output = ((blueprintBuilding.outputObj == null) ? null : _bpArray[...]);
#     buildPreview.input  = ((blueprintBuilding.inputObj  == null) ? null : _bpArray[...]);
#
# So for a sorter whose BOTH peers are inside the blueprint -- which is every
# sorter either strategy emits -- ``MatchInserter`` never runs, and neither
# constant below binds.  They bind the moment we emit a sorter reaching for
# something the blueprint does not contain.  Recorded with that condition
# stated, because the alternative is somebody "correcting" `SLOT_REACH` or
# `SLOT_ALIGN_COS` to these values and tightening a rule that is not the one
# those constants port.

#: The squared WORLD distance inside which ``MatchInserter`` will drag an end
#: onto a slot.  ``BuildTool_BlueprintPaste.cs:1588``::
#:
#:     if (num4 < 6f && (num5 != 0 || buildPreview2 != null))
#:
#: ``num4`` accumulates ``(slotPos - end).sqrMagnitude`` (``:1539``, ``:1568``,
#: ``:1580``), so the gate is ``sqrt(6)`` = 2.449 WORLD units -- three times
#: :data:`SLOT_REACH`, and a different code path.  The candidates it ranges over
#: are whatever ``Physics.OverlapSphereNonAlloc(vector, 0.8f, ...)``
#: (``:1491``) put in the buffer, so 0.8 appears here too, as a PhysX query
#: radius rather than as a legality threshold.
MATCH_SNAP_MAX_SQR = 6.0

#: The alignment ``MatchInserter`` demands of a candidate slot, as a cosine.
#: ``BuildTool_BlueprintPaste.cs:1536`` (machine) and ``:1564`` (a peer still in
#: preview), with ``BuildTool_Click.cs:831``/``:859`` the hand-tool twins::
#:
#:     float num13 = Vector3.Dot(lhs, rhs2);
#:     float num14 = Vector3.Dot((vector6 - vector2).normalized, rhs2);
#:     if (num13 > 0.9702957f && num14 > 0.9702957f)
#:
#: ``rhs2`` is the slot's own ``-forward``, ``lhs`` the sorter's axis and
#: ``vector2`` its far end.  TWO dots, both strictly above ``cos 14``.  Our
#: :data:`SLOT_ALIGN_COS` is ``cos 24`` on ONE of the two, and the two numbers
#: are unrelated: 24 is ``TooSkew``'s limit on a sorter's END ROTATIONS, not on
#: a slot's facing.  ``tests/bench/test_snap_oracle.py`` drives 15488 synthetic
#: ends through the game's own compiled ``MatchInserter`` and pins the
#: disagreement at 584 ends it connects and we refuse, 256 we accept and it
#: refuses, and 8 where both connect to different slots.
MATCH_ALIGN_COS = 0.9702957


#: How square a belt must lie ACROSS a sorter before the paste drags that end
#: along with the seat it just applied to the other end.
#:
#: ``BlueprintUtils.cs:2102``, in ``RefreshBuildPreview``, and its mirror at
#: ``:2153``::
#:
#:     if (Mathf.Abs(Vector3.Dot((buildPreview2.lpos2 - buildPreview2.lpos).normalized,
#:                               buildPreview2.output.lrot.Forward())) < 0.5f)
#:     {
#:         Vector3 vector6 = buildPreview2.lrot2.Forward();
#:         float num39 = Vector3.Dot(zero, vector6);
#:         buildPreview2.lpos2 += zero - vector6 * num39;
#:     }
#:
#: A belt running ALONG the sorter is left where the record put it; one lying
#: across it follows.  This lived in ``layout.slots`` as ``DRAG_MAX_ALIGNMENT``
#: -- a game constant with the decompiled source quoted, in the wrong module,
#: which is the exact shape of defect this module exists to end.  ``slots``
#: re-exports it under the old name so the call sites read unchanged.
DRAG_MAX_ALIGNMENT = 0.5


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
# The same passage carries a THIRD and a FOURTH bound, on the same three-way
# key, and only the first has been ported as a threshold.
# `BuildTool_Inserter.cs:1313-1329` sets all four together::
#
#     float num5 = 5.5f;  float num6 = 0.6f;  float num7 = 3.499f;  float num8 = 0.88f;
#     if (belt && belt)        { num6 = 0.4f; num5 = 5f;   num7 = 3.2f;   num8 = 0.8f;   }
#     else if (!belt && !belt) { num6 = 0.9f; num5 = 7.5f; num7 = 3.799f;
#                                num8 = 1.451f; num3 -= 0.3f; }
#
# `num5`/`num6` are `SORTER_LENGTH` below.  `num7` bounds the grid segments the
# sorter crosses (`:1341`, `if (num2 > num7) -> TooFar`) and is the citation
# behind `catalog.SORTER_MAX_REACH = 3`; a span of 4 is over it in all three
# classes and a span of 3 under it in all three.  `num8` is a MINIMUM on
# `sqrt(segments^2 + altitude^2)` (`:1347`, reporting `TooClose`), where
# altitude is `num4 = Abs(lpos.magnitude - lpos2.magnitude) / 0.2f` -- which is
# the line that establishes the game models an altitude-spanning sorter, and so
# the line that retired our invented `sorter.altitude` check.
#
# `num7` and `num8` are not ported AS THRESHOLDS because `CalcSegmentsAcross` is
# a function of latitude and our grid is uniform, where the length test above is
# the same statement; near a pole it would not be, and nothing we emit goes near
# one.  On a uniform grid `num7` reduces exactly to `SORTER_MAX_REACH`, which is
# ported, and `num8`'s floor is below the 1-tile minimum span in every class.

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

#: How far off an addon's own axis the belt it rides may travel, in DEGREES.
#: ``BuildTool_Addon.CheckBuildConditions``, the hand tool, over every belt its
#: area boxes found::
#:
#:     float num4 = (buildPreview2.desc.isTurret ? 18f : 20.5f);
#:     float num5 = num4;  float num6 = 180f - num4;
#:     bool flag = true;
#:     if (hasOutput) {
#:         normalized = (beltOutputBeltPose.position - objectPose.position).normalized;
#:         num9 = Quaternion.Angle(Quaternion.LookRotation(normalized, up), b);
#:         flag &= num9 < num5 || num9 > num6;
#:         flag &= Mathf.Abs(objectPose.position.magnitude
#:                           - beltOutputBeltPose.position.magnitude) < 0.6f;
#:     }
#:     if (hasInput) { ... the same, from beltInputBeltPose ... }
#:     ...
#:     if (!flag && !flag2) buildPreview2.condition = EBuildCondition.Collide;
#:
#: ``b`` is the addon AREA's rotation, which the addon's own yaw aims, so this
#: is the belt's direction of travel against the addon's axis.  ``flag2`` is
#: false exactly for the belt INSIDE the area box -- the one the addon rides --
#: so for that belt both halves must hold or the addon is a collision.
#:
#: ``Mathf.Abs`` is not used; the game brackets the angle from BOTH ends
#: (``< 20.5`` or ``> 159.5``), so a reversed belt passes and a right angle does
#: not.  That is why this convicts a CORNER: a belt that turns on the addon's
#: tile has an incoming direction and an outgoing direction a quarter turn
#: apart, and no addon axis is within 20.5 degrees of both.
#:
#: The paste path states the same rule as a DISTANCE rather than an angle, at
#: decompiled 145812, where a pasted addon meets a belt already on the planet::
#:
#:     flag10 &= Maths.DistancePointLine(objectPose2.position, ...) < 0.3f;
#:     if (flag10 && (objectPose2.position - buildPreview2.lpos).magnitude < 2.5f) {
#:         if (hasOutput) flag10 &= DistancePointLine(beltOutputBeltPose.position, ...) < 0.3f;
#:         if (hasInput)  flag10 &= DistancePointLine(beltInputBeltPose.position, ...) < 0.3f;
#:     }
#:
#: Same two neighbours, same verdict.  The angular form is what is ported,
#: because our grid is cardinal and the angle carries the altitude clause with
#: it.
#:
#: NOT in ``AddonPass``, the third clause: a belt and an addon from the SAME
#: paste are excused without either test, and ``AddonPass``'s own direction test
#: is dead for a mid-run belt because ``flag`` is set only when exactly one of
#: ``input``/``output`` is null.  So this rule binds on hand placement and on a
#: paste that meets an existing belt or prebuild, and not on the first paste of
#: a self-contained blueprint onto bare ground.
ADDON_AXIS_DEG = 20.5

#: The same limit for a turret, which is the other belt addon that has one.
ADDON_TURRET_AXIS_DEG = 18.0

#: How far the ridden belt's neighbours may differ from it in RADIUS -- world
#: units, so callers reach it through :func:`world_gap` with a pure ``dz``.
#: The ``< 0.6f`` clause quoted above.  An altitude LEVEL is 1.3333 and a half
#: level 0.6667, so this refuses a belt that changes height across the addon.
ADDON_NEIGHBOUR_RADIAL_GAP = 0.6


#: ``EBuildCondition.TooBendToLift``'s two thresholds.  ``BuildTool_Path.cs:1980``::
#:
#:     if (num21 < 2.5f && num25 > 0.1f)
#:     {
#:         buildPreview2.condition = EBuildCondition.TooBendToLift;
#:         continue;
#:     }
#:
#: These lived in :mod:`flab2bp.dsp.catalog`, which is the home for a rule read
#: against the building table or parameterised by technology.  These are neither:
#: they are bare ``EBuildCondition`` thresholds, so they belong here, next to the
#: predicate that applies them.  Moving them was free -- they had no readers at
#: all, anywhere, which is what :func:`too_bend_to_lift` now fixes.
BEND_MIN_ANGLE_WHEN_SLOPED_RAD = 2.5
SLOPE_DEADZONE = 0.1


def too_bend_to_lift(
    incoming: tuple[float, float] | None,
    outgoing: tuple[float, float] | None,
    slope: float,
) -> bool:
    """``EBuildCondition.TooBendToLift``: a belt may not TURN while sloped.

    ``BuildTool_Path.cs:1980``::

        if (num21 < 2.5f && num25 > 0.1f)
        {
            buildPreview2.condition = EBuildCondition.TooBendToLift;
            continue;
        }

    ``num21`` is the angle at this belt between its input and its output, in
    radians -- ``Maths.SphericalAngleAOBInRAD(buildPreview2.lpos, vector9,
    vector10)`` at ``:1892``, defaulting to ``MathF.PI`` at ``:1889`` when the
    belt has only one neighbour.  ``num25`` is the steeper of the two slopes,
    ``Mathf.Abs(Maths.SphericalSlopeRatio(...))`` at ``:1953`` and ``:1962``.

    So a straight belt is ``pi`` and always legal; a quarter turn is ``pi/2``
    and illegal above :data:`~flab2bp.dsp.catalog.SLOPE_DEADZONE`; a belt
    reversing on its own tile is ``0``.  Anything bending more than
    ``pi - 2.5`` = 36.6 degrees off straight must be level.

    ``incoming`` is the grid step INTO this belt, ``outgoing`` the step out of
    it; either may be ``None`` for an end of a run, which the game treats as the
    ``pi`` default.  ``slope`` is the steeper adjacent slope as world rise over
    world run -- the same quantity :data:`~flab2bp.dsp.catalog.MAX_BELT_SLOPE`
    is compared against, so callers already have it.

    .. warning::
       **No check consults this yet, deliberately, and the number below is why
       that decision is load-bearing rather than cautious.**

       Whether the rule binds on a PASTE -- rather than only on the interactive
       path tool it is decompiled from -- is Step 0.1 of
       ``docs/RULE_CONSOLIDATION_PLAN.md``, an in-game experiment the user is
       running.  Measured over the trivial+small+mid corpus, 24 cells per
       strategy, this predicate convicts:

       ===========  ==========  =============  ======================
       strategy     belts       convictions    cells with >= 1
       ===========  ==========  =============  ======================
       ``spine``    7114        **213** (3.0%)  **21 of 24**
       ``freeform`` 5761        **139** (2.4%)  **18 of 24**
       ===========  ==========  =============  ======================

       So this is not an edge case waiting on a formality.  If Step 0.1 comes
       back RED, nearly every blueprint either strategy currently ships is
       invalid, and both routers need the constraint at search time (Step 2.2)
       rather than as a late refusal.  Wiring a default-ERROR check *now* would
       take the audit from INVALID 0 to INVALID in 39 of 48 cells on the
       strength of a rule we have not yet confirmed applies to a paste -- which
       is a guess in the opposite direction, and an expensive one.

       ``tests/dsp/test_rules.py`` is the consumer: it pins the predicate
       case-by-case against the decompiled branch and checks it convicts nothing
       in blueprints the game itself wrote.
    """
    if slope <= SLOPE_DEADZONE:
        return False
    if incoming is None or outgoing is None:
        return False  # `num21` keeps its `MathF.PI` default: no bend to measure
    ax, ay = incoming
    bx, by = outgoing
    na = math.hypot(ax, ay)
    nb = math.hypot(bx, by)
    if na == 0.0 or nb == 0.0:
        return False
    # `SphericalAngleAOBInRAD` is the angle at the belt subtended by its two
    # neighbours, so the vectors run OUTWARD from it: back along `incoming` and
    # forward along `outgoing`.
    cos = (-ax * bx - ay * by) / (na * nb)
    angle = math.acos(max(-1.0, min(1.0, cos)))
    return angle < BEND_MIN_ANGLE_WHEN_SLOPED_RAD


def addon_axis_offset_deg(yaw_deg: float, dx: float, dy: float) -> float:
    """Angle in ``[0, 180]`` between a belt's travel and an addon's own axis.

    Our yaw convention is the game's: yaw 0 aims ``+y``, yaw 90 aims ``+x``,
    which is ``atan2(dx, dy)``.  ``Quaternion.Angle`` is unsigned, so this is
    too, and the caller brackets it from both ends the way the game does.
    """
    if dx == 0 and dy == 0:
        raise ValueError("a belt with no direction of travel has no axis offset")
    off = (math.degrees(math.atan2(dx, dy)) - yaw_deg) % 360.0
    return off if off <= 180.0 else 360.0 - off


def addon_axis_aligned(
    yaw_deg: float, dx: float, dy: float, *, limit_deg: float = ADDON_AXIS_DEG
) -> bool:
    """``num9 < num5 || num9 > num6``: is the belt along the addon's axis?

    Either way along it.  A belt that runs the addon's axis backwards is
    accepted by the game and by this.
    """
    off = addon_axis_offset_deg(yaw_deg, dx, dy)
    return off < limit_deg or off > 180.0 - limit_deg


def addon_ride_is_straight(
    yaw_deg: float,
    incoming: tuple[float, float, float] | None,
    outgoing: tuple[float, float, float] | None,
    *,
    limit_deg: float = ADDON_AXIS_DEG,
) -> bool:
    """Whether a belt addon may sit on a belt with these neighbours.

    ``incoming`` is the grid step from the ridden belt's INPUT belt to it;
    ``outgoing`` the step from it to its OUTPUT belt.  Both are ``(dx, dy, dz)``
    and either may be ``None`` when the belt is an end of its run -- the game
    reads them from ``GetBeltInputBeltPose`` / ``GetBeltOutputBeltPose`` and
    tests only the ones that exist.

    A belt that TURNS on the addon's tile fails: the two directions are a
    quarter turn apart and no axis is within :data:`ADDON_AXIS_DEG` of both.
    """
    for step in (incoming, outgoing):
        if step is None:
            continue
        dx, dy, dz = step
        if (dx, dy) == (0, 0):
            continue
        if not addon_axis_aligned(yaw_deg, dx, dy, limit_deg=limit_deg):
            return False
        if world_gap(0.0, 0.0, dz) >= ADDON_NEIGHBOUR_RADIAL_GAP:
            return False
    return True
