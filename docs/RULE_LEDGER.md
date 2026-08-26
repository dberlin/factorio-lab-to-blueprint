# The provenance ledger — every rule, its verdict, its citation

Phase V of `docs/RULE_CONSOLIDATION_PLAN.md`. The user's ruling, verbatim:

> all rules should be verified against the game code. Rules that exist in game
> code are kept. Rules that do not are removed. No rules are guessed.

This file is the artifact that makes *"100% of rules are verified"* a checkable
claim rather than an assertion. Every row carries a verdict and, for a KEEP, a
citation you can go and read.

## How to read a citation, and how the offset was settled

Every citation in this ledger is **`File.cs:line`, file-relative**, against
`/home/dannyb/.claude/jobs/66c2051c/tmp/poseless/full/`.

The "constant offset of 143582" that circulated on this project is real but
**not universal**, and this repository contains citations in *both* conventions
— in the same file, three hundred lines apart:

| site | citation as written | resolves how |
|---|---|---|
| `dsp/colliders.py:576` | "`CheckBuildConditions` 2137-2158 of the decompiled `BuildTool_BlueprintPaste`" | **offset 0** — `BuildTool_BlueprintPaste.cs:2137-2158` is the sorter collider stretch |
| `dsp/colliders.py:809` | "`CheckBuildConditions` line 145761" | **offset 143582** — `145761 − 143582 = 2179`, the belt probe sphere |

So the offset was established **per citation, by grepping for the literal and
confirming the surrounding code**, never by assuming. Three anchors were used:

* `145812 − 143582 = 2230` → `BuildTool_BlueprintPaste.cs:2222-2258`, the addon
  `DistancePointLine < 0.3f` clause. Offset 143582 confirmed for that file.
* `BuildTool_BlueprintPaste.cs:3488` is *literally*
  `if (Quaternion.Angle(buildPreview2.lrot, buildPreview2.lrot2) > 30f)`.
  Offset 0 also lands in that file, for other citations.
* `BlueprintUtils.cs:1623` is *literally* the `buildPreview.output = ...` line
  that `docs/RULE_AUDIT.md` D5's addendum cites as 1623. **Offset 0** for
  `BlueprintUtils.cs`, exactly as the plan warned.

`dsp/colliders.py:271` cites `_SEGMENT_TABLE_HEAD` as "decompiled line 102624",
which resolves under **neither** convention. The table is at `PlanetGrid.cs:21`.
Recorded as a citation defect below.

## Verdicts used

| verdict | meaning |
|---|---|
| **KEEP** | a quoted `File.cs:line` shows the game applying it. Citation now in the code. |
| **REMOVE** | claimed as a game rule; no citation exists. Deleted. |
| **OURS** | never was a game rule and no longer claims to be — a functional invariant of what we ship, or an internal model invariant. Relabelled so it stops masquerading. This is the plan's own §1.2 category, not an escape hatch: an **OURS** row may not live in `dsp/` as a rule constant and may not be described as the game's. |
| **OPEN** | could not be settled from the assembly. Reported to the user. |

**UNVERIFIED is empty.** Every row below has one of the four.

A KEEP row also records **what the rule depends on**. Where that is a tech
level, the row names the tech, where the game reads it, and what we assume.

---

# 1. `dsp/rules.py`

| rule | verdict | citation | depends on |
|---|---|---|---|
| `WORLD_UNITS_PER_LEVEL = 4/3` | KEEP | `BuildTool_Path.cs:176`, `(float)altitude * 1.3333333f + ...` | — |
| `OUTPUT_FROM_SLOT = 0` / `INPUT_TO_SLOT = 1` | KEEP | `BuildTool_BlueprintCopy.cs:1774` `if (otherObjId != 0 && !isOutput) return false;` and `:1778` `if ((otherObjId2 != 0) & isOutput2) return false;` | — |
| `BELT_SLOT = -1` (machine half) | KEEP | `BuildTool_BlueprintCopy.cs:1789` `if (!prefabDesc2.isBelt && prefabDesc2.slotPoses.Length > otherSlot)` | — |
| `ADDON_FROM_SLOT = 15` / `ADDON_TO_SLOT = 14` | KEEP | `BuildTool_Addon.cs:443-445` `buildPreview.outputToSlot = 14; ... buildPreview.inputFromSlot = 15;` | — |
| `SPLITTER_INPUT_TO_SLOT = 14` / `SPLITTER_OUTPUT_FROM_SLOT = 15` | KEEP | same pair, splitter side; corpus-unanimous 25/25 | — |
| `BELT_INPUT_SLOTS = (1, 4)` | KEEP | `BuildTool_Path.cs:1911` `for (int num23 = 1; num23 < 4; num23++)` | — |
| `CONN_SLOTS_PER_OBJECT = 16` | KEEP | `PlanetFactory.cs:2582` `int num = entityConnPool[objId * 16 + slot];`, written at `:2637`; eviction at `:2726-2727` `ClearObjectConn(objId, slot); ClearObjectConn(otherObjId, otherSlot);` | — |
| `BELT_SLOT_AUTO_RANGE = (4, 12)` | KEEP | `PlanetFactory.cs:2703` `for (int i = 4; i < 12; i++)` | — |
| `SPLITTER_MAX_PORTS = 4` | KEEP | `PlanetFactory.cs:810-813` reads conns 0..3 only; `CargoTraffic.cs:660` `... && slot >= 0 && slot <= 3` — out-of-range is silently ignored, which is the "pastes and drops connections" failure | — |
| `SLOT_REACH = 0.8` | KEEP | `BuildTool_BlueprintCopy.cs:1791` `if ((objectPose2.position - transformedBy.position).magnitude > 0.8f) return false;` (again `:1815`) | — |
| `PASTE_SNAP / PASTE_LATERAL / PASTE_RADIAL / PASTE_LATERAL_EPS` | KEEP | `BlueprintUtils.cs:2114-2140`, the `ErrorInserterData` ladder | — |
| `SORTER_LENGTH` | KEEP | `BuildTool_Inserter.cs:1313-1329` (`num5`/`num6`), applied `:1332`/`:1338`; paste twin `BuildTool_BlueprintPaste.cs:3462-3472` | — |
| `SKEW_PAIR_DEG = 30` | KEEP | `BuildTool_BlueprintPaste.cs:3488` | — |
| `SKEW_AXIS_DEG = 24` / `SLOT_ALIGN_COS` | KEEP | `BuildTool_BlueprintPaste.cs:3499` `if (num135 > 24f \|\| num136 > 24f)` | — |
| `ADDON_AREA_RADIUS = 1.0` | KEEP | `PlanetFactory.cs:5931` `if (sqrMagnitude < num && sqrMagnitude < 1f && num3 < 0.3f)` | — |
| `ADDON_AXIS_DEG = 20.5` / `ADDON_TURRET_AXIS_DEG = 18` | KEEP | `BuildTool_Addon.cs:877` `float num4 = (buildPreview2.desc.isTurret ? 18f : 20.5f);` | — |
| `ADDON_NEIGHBOUR_RADIAL_GAP = 0.6` | KEEP | `BuildTool_Addon.cs:897,905` `flag &= Mathf.Abs(objectPose.position.magnitude - beltOutputBeltPose.position.magnitude) < 0.6f;` | — |
| **`MATCH_SNAP_MAX_SQR = 6.0`** (new) | KEEP | `BuildTool_BlueprintPaste.cs:1588` `if (num4 < 6f && ...)` — a SQUARED world distance, 2.449 world units | reached **only** when the peer is absent |
| **`MATCH_ALIGN_COS = 0.9702957`** (new) | KEEP | `BuildTool_BlueprintPaste.cs:1536` `if (num13 > 0.9702957f && num14 > 0.9702957f)` — cos 14, on BOTH dots | same |

## 1a. The `SKEW_AXIS_DEG` row is the one this phase got wrong twice

Both `docs/RULE_AUDIT.md` D5 and Phase 4.2 of the plan say `slots.attachment`'s
cos-24 gate is stricter than the game and should be relaxed to a sign test. **It
was tried, and it is wrong.** The relaxation makes an Oil Refinery servable from
the north; the game refuses that as `TooSkew`, and the existing test caught it.

The mechanism nobody had traced: the paste **snaps the sorter end onto the slot
and takes the slot's rotation with it** —
`BlueprintUtils.RefreshBuildPreview`, `BlueprintUtils.cs:2096-2097`:

```csharp
buildPreview2.lpos = transformedBy.position;
buildPreview2.lrot = transformedBy.rotation;
```

`TooSkew` then runs on the snapped values, `BuildTool_BlueprintPaste.cs:3494-3501`:

```csharp
Vector3 normalized4 = (buildPreview2.lpos2 - buildPreview2.lpos).normalized;
float f = Mathf.Abs(Vector3.Dot(normalized4, buildPreview2.lrot.Forward()));
...
if (num135 > 24f || num136 > 24f) -> EBuildCondition.TooSkew
```

With `lrot` **being** the slot's rotation and `lpos` **being** the pose, that is
`Dot(slot forward, run direction measured from the pose)` against cos 24 — which
is `slots.attachment`'s test exactly, origin included. `Mathf.Abs` makes the
game's form unsigned; the ladder's sign test at `BlueprintUtils.cs:2136` supplies
the sign. So there are **three** game predicates on this pair, not one, and ours
is the conjunction of two of them rather than a borrowed tolerance.

`SKEW_AXIS_DEG` is therefore **one rule with two consumers after all**, and D5's
headline claim is retracted. The reasoning is now written into `slots.py` at the
test so it is not re-derived a third time.

## 1a-bis. Two reach rules, and a row is not finished until it says *when it applies*

`RULE_AUDIT` D5 conflated these because each row recorded only a threshold. Both
are real; they are different functions reached by different code paths.

| rule | threshold | citation | **applies when** |
|---|---|---|---|
| `SLOT_REACH` | **0.8** world units, on a bare `Vector3.magnitude` | `BuildTool_BlueprintCopy.cs:1791` `if ((objectPose2.position - transformedBy.position).magnitude > 0.8f) return false;` | `CheckInserterDataLegal`, on a sorter that **names its peer**. This is every sorter we emit. **Governing for our output.** |
| `MATCH_SNAP_MAX_SQR` | **6.0** squared world units = **2.449** | `BuildTool_BlueprintPaste.cs:1588` `if (num4 < 6f && ...)` | `MatchInserter`, reached **only** when the peer preview is null — `BuildTool_BlueprintPaste.cs:1795-1810` gates the call on `input == null` / `output == null`, and `BlueprintUtils.cs:1623-1624` fills those from the blueprint's own `inputObj` / `outputObj`. **Never reached by our output.** |

The 584 divergent points the differential found are real and are *not* evidence
that `SLOT_REACH` is too strict: they are the two functions disagreeing, which
they are entitled to do. Every row in this ledger that could be reached by more
than one code path now carries an applicability condition for the same reason.

## 1b. Why `MatchInserter` does **not** replace `SLOT_REACH` / `SLOT_ALIGN_COS`

The Phase V brief said the two oracle disagreements "must replace what we have".
They must not, and the assembly says why. `MatchInserter` is called only for an
end whose peer preview came back null — `BuildTool_BlueprintPaste.cs:1793-1810`:

```csharp
bool num = buildPreview.input == null;
bool flag3 = buildPreview.output == null;
if (num)   { buildPreview.inputObjId  = 0; MatchInserter(buildPreview); }
if (flag3) { buildPreview.outputObjId = 0; MatchInserter(buildPreview); }
```

and `BlueprintUtils.cs:1623-1624` fills those two fields straight from the
blueprint's own `outputObj` / `inputObj`. Every sorter either strategy emits
names both peers, so **`MatchInserter` never runs on our output** and neither
constant binds. `docs/RULE_AUDIT.md`'s D5 addendum already said this
("still LATENT for what we emit"); the brief's framing did not.

They are ported anyway, with the condition recorded, because they bind the
moment we emit a sorter reaching outside the blueprint. Their consumer is
`tests/bench/test_snap_oracle.py::test_the_two_match_inserter_constants_reproduce_the_compiled_ladder`,
which rebuilds `MatchInserter` from *only* these two constants and checks it
against the game's own compiled `MatchInserter` over the 15488-case sweep:
**exact agreement, verdict and slot index alike**. Mutation-checked — cos 24
moves 440 of them, `SLOT_REACH**2` moves 576.

---

# 2. `dsp/catalog.py` — the rule half

| rule | verdict | citation / disposition | depends on |
|---|---|---|---|
| `GRID_ARC = 2π/5` (in `colliders`) | KEEP | `PlanetGrid.cs:1063` `MathF.PI * 2f / (float)(segment * 5)` | planet segment (200 for a terrestrial) |
| `MAX_BELT_SLOPE = 4/5` | KEEP | `BuildTool_Path.cs:1954` `if (!history.beltVerticalConstruction && num25 > 0.8f) ... TooSteep` (again `:1963`) | **TECH** — `beltVerticalConstruction`, `GameHistoryData.cs:558` default false, unlocked `:1956`; FactorioLab tech `super-magnetic-field-generator` |
| `BELT_Z_PER_WORLD_UNIT = 3/4` | KEEP | inverse of `BuildTool_Path.cs:176`'s `1.3333333f` | — |
| `belt_max_z()` / `DEFAULT_LAB_LEVEL = 3` | KEEP | `GameHistoryData.cs:228-238` `if (labLevel < 15) return (float)labLevel * 4f - 0.6f; return (float)labLevel * 4f + 4f;`; default `:577`; raised `:1889` `case 25: labLevel += num;`. Applied `BuildTool_BlueprintPaste.cs:2075` → `:2078 OutOfReach` | **TECH** — `labLevel`, Vertical Construction |
| `BELT_SLOPE_UNLOCK_TECH` | KEEP | `GameHistoryData.cs:1956`; locale line quoted in place | **TECH** |
| `VERTICAL_CONSTRUCTION_PREFIX` | KEEP | `GameHistoryData.cs:1889` | **TECH** |
| `BEND_MIN_ANGLE_WHEN_SLOPED_RAD = 5/2`, `SLOPE_DEADZONE = 1/10` | KEEP (citation) — **but zero readers** | `BuildTool_Path.cs:1980` `if (num21 < 2.5f && num25 > 0.1f) { buildPreview2.condition = EBuildCondition.TooBendToLift; }` | — |
| **`SORTER_MAX_REACH = 3`** | **KEEP — upgraded from "corpus measurement"** | `BuildTool_Inserter.cs:1316-1329` (`num7` = 3.499 / 3.2 / 3.799) applied `:1341` `if (num2 > num7) ... TooFar`; span recorded clamped at `:1352` `Mathf.RoundToInt(Mathf.Clamp(num3, 1f, 3f))` | **not** tier-dependent — no `num5/6/7/8` reads `inserterGrade` |
| `TESLA_COVER_RADIUS = 21/2` | KEEP | `PowerDesc.cs:10` `coverRadius` → `PrefabDesc.cs:1440` → `PowerSystem.cs:921,961` `if (num11 <= coverRadius)` on squares | building prefab, not tech |
| `TESLA_LINK_DISTANCE = 45/2` | KEEP | `PowerDesc.cs:8` → `PrefabDesc.cs:1439` → `PowerSystem.cs:920,940-945`, `max` of the pair confirmed at `:940-944` | building prefab |
| `SORTER_RATE_AT_1`, `BELT_RATE` | KEEP (tier-indexed, already) | prefab `inserterSTT`/`inserterStackSize` (`PrefabDesc.cs:1356-1360`) | **TIER**, already a dict. *Not* research-scaled: `inserterStackCountObsolete` (`GameHistoryData.cs:42`) is obsolete and nothing else scales belt throughput |
| **`SORTER_SPANS_ALTITUDE = False`** | **REMOVE — deleted** | contradicted: `BuildTool_Inserter.cs:1311` `float num4 = Mathf.Abs(lpos.magnitude - lpos2.magnitude) / 0.2f;` used at `:1347` as a **minimum** | — |
| **`BELT_CROSSING_CLEARANCE = 1`** | **REMOVE — deleted** | no citation; no validator ever read it; `colliders.belt_crossing_height` is the real rule and gives 2.80-4.97, not 1 | — |
| `BELT_Z_QUANTUM` | **OURS** — relabelled, check deleted | the game's altitude is an integer counter (`BuildTool_Path.cs:388` `altitude++`, clamp `:444`); nothing compares a height to a step | — |
| `BELT_CLIMB_PER_TILE`, `RAMP_TILES_PER_LEVEL`, `VERTICAL_STEP` | OURS (already documented as what we EMIT) | — | — |
| `GEOMETRY_SAFE_FIXTURES`, `LOW_CONFIDENCE_FOOTPRINTS` | OURS (statements about our evidence) | — | — |

---

# 3. `dsp/colliders.py`

| rule | verdict | citation |
|---|---|---|
| `EBuildCondition.Collide` (the whole module) | KEEP | `BuildTool_BlueprintPaste.cs:2179` box/sphere query; verdict `:2490` `buildPreview2.condition = EBuildCondition.Collide;` |
| `SORTER_END_EXTENSION = 0.35` | KEEP | `BuildTool_BlueprintPaste.cs:2142-2143` `colliderData.pos.z -= 0.35f; colliderData.ext.z += 0.35f;` |
| `SORTER_HALF_LENGTH_MIN = 0.1` | KEEP | `BuildTool_BlueprintPaste.cs:2160-2162` |
| `BELT_PROBE_RADIUS = 0.23` / `BELT_PROBE_LIFT = 0.2` | KEEP | `BuildTool_BlueprintPaste.cs:2179` `Physics.OverlapSphereNonAlloc(buildPreview2.lpos + buildPreview2.lpos.normalized * 0.2f, 0.23f, ...)` |
| the sorter-vs-sorter excusal | KEEP | `BuildTool_BlueprintPaste.cs:2290`, the `isInserter` XOR `continue` |
| `_SEGMENT_TABLE` (was `_SEGMENT_TABLE_HEAD`) | KEEP — **was a partial port; completed** | `PlanetGrid.cs:19-80`. See §3a. |
| `GRID_ARC`, `PLANET_RADIUS`, `PLANET_SEGMENT` | KEEP | `PlanetGrid.cs:1063` |

## 3a. The planet grid is quantised, and our port of the table stopped at entry 8

**The question was: which game function is `colliders.py` mirroring, and does it
use the table or the raw cosine?** It mirrors
`BlueprintUtils.RefreshBuildPreview`, and that function **does go through the
table**. The chain, all offset 0:

* `BlueprintUtils.cs:270-273` —
  `GetLongitudeRadPerGrid(float _latitudeRad, int _segmentCnt)` returns
  `MathF.PI * 2f / (float)(GetLongitudeSegmentCount(_latitudeRad, _segmentCnt) * 5);`
* which resolves to `PlanetGrid.cs:1838`
  `DetermineLongitudeSegmentCount`, cosine-based and then
  `if (num < 500) { return segmentTable[num]; }`
* `PlanetGrid.cs:19` — `segmentTable`, 512 entries, **17 distinct values**
  `{1, 4, 8, 16, 20, 32, 40, 60, 80, 100, 120, 160, 200, 240, 300, 400, 500}`.

So the quantisation is part of the paste-time rule, not an artefact of grid
construction. Our model was mirroring the right function.

**But the port was partial, and that is a defect.** `_SEGMENT_TABLE_HEAD` held
the first **eight** entries; `_longitude_segment_count` then fell through to
`return raw` for every index from 8 to 499. Measured:
`segmentTable[i] != i` for **478 of those 492 indices**. The port was correct
only at the 14 where the table happens to be the identity — and `200`, the one
index the equatorial model reaches, is one of them. That is exactly why it never
surfaced.

Fixed: all 512 entries are ported, with `PlanetGrid.cs:19` / `:1838` quoted next
to them. **The equator is unchanged** (`segmentTable[200] == 200`), so
`collisions()` and every area figure derived from it are untouched — that is the
control, and it is asserted in the new test. What changes is `preview_pose`,
which takes an `anchor_lat` and was silently wrong for it everywhere off the
equator.

The old citation, "decompiled line 102624", resolves under **neither**
convention. Corrected.

**Consequence for the open backlog item.** `area_segments` is an *output* of
this table, so it names one of 17 **bands** of latitude index, not a latitude.
Two of five single-area fixtures (`12-s-purple-science-…`, 670 ends, max 0.027
tiles; `falk-v7-mall-full`, 229 ends, max 0.024) refusing to collapse under any
single latitude is the signature of fitting a continuous model to a quantised
one, and the residuals are the right order for it. The backlog item should be
re-tested against the band before anyone edits the Assembling Machine slot-pose
table. It cannot move a sorter verdict — 0.027 tiles against a 0.26 box
half-width — so this is a correctness-of-model row, not a live bug.

---

# 4. `layout/validate.py` — the rule checks

| check | verdict | citation / disposition |
|---|---|---|
| `geom.collide` | KEEP | `BuildTool_BlueprintPaste.cs:2179`, verdict `:2490` |
| `game.sorter_collide` | KEEP — **fitting risk recorded, see §4a** | `:2142-2143`, `:2162`, excusal `:2290` |
| `geom.belt_single_occupancy` | KEEP (discretized proxy) | the sphere probe `:2179`, belt-vs-belt **not** excused at `:2290` |
| `geom.altitude_step` | KEEP | `BuildTool_Path.cs:1954,1963` |
| `geom.altitude_range` — ceiling | KEEP | `BuildTool_BlueprintPaste.cs:2075` `history.buildMaxHeight + 0.5f + realRadius * ...` → `:2078 OutOfReach` |
| **`geom.altitude_range` — the `1/2` quantum clause** | **REMOVE — deleted** | the game quantises nothing; `BuildTool_Path.cs:388,444,176` |
| `geom.bounds` — 1048576 buildings | KEEP | `BlueprintData.cs:788` `if (num2 < 0 \|\| num2 > 1048576) throw new Exception("Corrupt Data");` |
| **`geom.bounds` — parameter cap** | **KEEP, and it was off by one** | `BlueprintBuilding.cs:304-305` `w.Write((short)num);`, read `:121` `r.ReadInt16()`. Signed Int16 ⇒ cap is **32767**; we permitted 32768, the one value that cannot round-trip. Fixed. |
| `sorter.reach` — span 1..3 | KEEP | `BuildTool_Inserter.cs:1341` |
| `sorter.reach` — "sorters are straight-line" | KEEP (derived) | no direct citation, but implied for cardinal machines by `TooSkew` at `:3499`; a diagonal run puts every slot forward well past 24° |
| **`sorter.altitude`** | **REMOVE — deleted** | `BuildTool_Inserter.cs:1311,1347` |
| `sorter.own_slots` | KEEP | `BuildTool_BlueprintCopy.cs:1774,1778` |
| `sorter.peer_slots` — machine half | KEEP | `BuildTool_BlueprintCopy.cs:1789-1794` |
| `game.inserter_data` | KEEP | `BuildTool_BlueprintCopy.cs:1794,1798` |
| `game.slot_occupancy` | KEEP | `PlanetFactory.cs:2582`, eviction `:2726-2727`, auto range `:2703` |
| `game.inserter_paste` | KEEP | `BlueprintUtils.cs:2114-2138` |
| `game.inserter_skew` | KEEP | `BuildTool_Inserter.cs:1313-1329`; `BuildTool_BlueprintPaste.cs:3488,3499` |
| `game.addon_supply` | KEEP | `PlanetFactory.cs:5931` → `:5939` |
| `game.addon_facing` | KEEP | `BuildTool_BlueprintPaste.cs:4451-4454` `num3 = Mathf.Abs(Vector3.Dot((vector2 - vector).normalized, rhs)); ... flag3 &= num3 > 0.95f;` |
| `game.addon_corner` | KEEP | `BuildTool_BlueprintPaste.cs:2248-2259`; hand tool `BuildTool_Addon.cs:877,897,905` |
| `game.belt_crossing` / `game.belt_collide` | KEEP | `:2179`, asymmetric excusal `:2290` |
| `junction.ports` | KEEP | `CargoTraffic.cs:660`; `PlanetFactory.cs:810-813` |
| `power.coverage` | KEEP (over-strict) | `PowerSystem.cs:921,961`. The game tests the consumer's single `plugPos` (`:954`); we test every tile — tighter than the game, and safe |
| `power.connectivity` — the link predicate | KEEP | `PowerSystem.cs:940-945`, `max` of the pair |
| `power.connectivity` — "one network" | **OURS** | `PowerSystem.cs:990` `num17 = NewNetwork();` — the game spawns a second network without complaint. Our blueprints carry no generation, so a stranded tower is a build that does not run. Functional invariant, not a paste rule. |
| `geom.footprint`, `geom.overlap`, `geom.machine_ground`, `sorter.anchors_present`, `sorter.endpoints`, `sorter.endpoint_pair`, `sorter.filter`, `junction.colocated`, `junction.records_no_links` | **OURS** — see §4b | none is a game predicate. `EBuildCondition.Occupied` is a belt-junction *port*, not a tile (`BuildTool_Path.cs:1258`, `BuildPreview.cs:125` `"接口已占用"`). |

## 4b. OURS is a verdict, not an exemption — and one of these rows is a density lead

The ruling is "rules that do not exist in game code are removed". **OURS** is not
a way around it. It is the plan's own §1.2 category, and it means: *this was
never a claim about the game, it is a property of our model or of the artifact we
ship, and it has been relabelled so it can never again be mistaken for a game
rule.* The four **REMOVE** rows above were deleted precisely because they DID
claim to be the game's.

The test applied to each row below was: **would deleting it change what we emit
or what we refuse?**

* `sorter.anchors_present`, `sorter.endpoint_pair`, `junction.records_no_links`,
  `sorter.filter`, `geom.footprint` — no. They are record-integrity
  preconditions for the ported checks, or assertions on our own cache. Deleting
  them removes a guard rail and gains nothing; they are relabelled, not deleted,
  and none is a constant in `dsp/`.
* `power.connectivity`'s one-network clause — deleting it would change what we
  ship, and for the worse. Our blueprints carry no generation, so a second
  network is a half-powered build. `PowerSystem.cs:990` proves the *game* does
  not object; that makes it our requirement, which is exactly what it is now
  labelled.
* **`geom.overlap` is a lead I did not chase, and I am flagging it rather than
  closing it.** It is a coarse discretisation of `geom.collide`: the footprint
  it compares is itself derived from `buildColliders` (`catalog.derive_footprint`),
  so it is a projection of the real rule, not an independent one — which is why
  it is OURS and not REMOVE. But the projection rounds *outward*
  (`width = 2 * ceil(e / GRID_ARC) - 1`, always odd), so there are pairs whose
  tiles overlap and whose colliders do not, and `geom.overlap` refuses those.
  **How many, and what they are worth in area, is unmeasured.** It is a genuine
  Phase 4 density candidate and it needs a packer experiment, not a ledger entry.
  Recording it as an open lead is honest; calling it verified either way would
  not be.
| `prolif.*`, `flow.*`, `machine.*`, `spec.*`, `belt.*` | **OURS** | rate, spec and routing correctness. Out of the legality set by the plan's own line. |

## 4a. `game.sorter_collide` — KEEP, with the fitting risk stated

The check is on master and it convicts. It was built knowing the game refused
exactly buildings `{21, 46, 55, 162, 163}` in `tests/fixtures/ours/`, and it
outputs exactly that set. **That positive case is a fit to a known answer**, and
this ledger records it as such rather than counting it as confirmation.

A competing explanation exists with hard evidence: the two fixtures sit in
**different latitude bands** — `area_segments = 200` for ours against `160` for
the game's build, areas 30x31 against 31x30. §3a is the mechanism that makes
that a real alternative: the same integer local grid describes different world
geometry in different bands, and five refusals could follow with no collision
involved. A same-band paste test is being run by the user to separate the two.

**The verdict is still KEEP, and here is the part that survives either way.**
The question asked was whether the rule's derivation needs anything beyond the
quoted C#. It does not. Every term traces to a quotation or to shipped data:

* the stretch `Distance(lpos2, lpos) * 0.5f + ext.z - 0.5f` — quoted,
  `BuildTool_BlueprintPaste.cs:2139`;
* `SORTER_END_EXTENSION = 0.35` — quoted, `:2142-2143`;
* `SORTER_HALF_LENGTH_MIN = 0.1` — quoted, `:2162`;
* `ext.x = 0.26`, `ext.y = 0.15` — the shipped prefab collider table, not a
  fitted value;
* the XOR excusal — quoted, `:2290`;
* the box's centre and rotation — quoted, `:1848-1854`.

**There is no tuned constant.** Nothing was moved to land on those five. The
only free parameter would have been a fudge in the box, and there is none: the
negative control is that the same box reports **zero** pairs over the 1132
sorters in the five single-area fixtures, which is not vacuous because that same
corpus contains 97 pairs of sorter bodies sharing a plan tile and 35
belt-to-belt sorters.

One term **is** modelled out, and the code says so: the belt-end drag
(`slots.DRAG_MAX_ALIGNMENT = 0.5`, `BlueprintUtils.cs:2102`). Measured at 0.263
against 0.300 units of penetration on the same three pairs — it changes no
verdict, which is a disclosure, not a fit.

So: do not weaken it. If the same-band test shows latitude explains the five,
what that falsifies is the *fixture's* evidentiary value, not the ported rule.

---

# 5. Legality predicates embedded in the layout modules

Enumerated in full; the interesting rows only are reproduced here.

## 5a. `spine.py` / `junction.py` / `slots.py`

| site | rule | verdict |
|---|---|---|
| `spine.py:4638` `_tower_keep_out`, `junction.py:143` `site_is_clear` | two independently hand-written copies of `(clearance(a) + clearance(b)) / 2` as a circle test | KEEP (rule real, `geom.collide`) — but a circle approximation of an OBB test that `dsp.colliders` already does exactly. Phase 1.3. |
| `slots.py:701` `DRAG_MAX_ALIGNMENT = 0.5` | belt-end drag threshold | **KEEP with a citation it did not have**: `BlueprintUtils.cs:2102` `if (Mathf.Abs(Vector3.Dot((buildPreview2.lpos2 - buildPreview2.lpos).normalized, buildPreview2.output.lrot.Forward())) < 0.5f)`. A game constant living in `layout/`; belongs in `dsp/rules.py`. |
| `spine.py:3065` `_trunk_x` | hardcodes `2` where `catalog.RAMP_TILES_PER_LEVEL` is 2; the docstring names the constant the code does not read | OURS-with-a-defect — a bare literal duplicating a `dsp/` constant |
| `spine.py:3032` `_TRUNK_Z` | trunk altitude | **OURS** — was `catalog.BELT_CROSSING_CLEARANCE`; now a spine-local `Fraction(1)` |
| sorter reach, inlined | 11 sites across the three files | KEEP (rule real) — only `slots.py:351` is canonical |
| `spine.py` never calls `junction.site_is_clear`, `junction.keepout_cells`, `slots.sorter_seat_is_clear` | three finished legality gates bypassed on the spine path | **defect, handed over** |

## 5b. `freeform.py` — recorded only; the file is another agent's

| site | rule | verdict |
|---|---|---|
| `freeform.py:2174-2178` `_Canvas.add`, `solid=True` at every level | "machines are solid at every altitude" | **REMOVE** — no citation. The game prices a machine crossing by height (`colliders.belt_crossing_height`) and spine already sells it. **Deletion is the Phase 4.1 agent's; the code is untouched here.** |
| `freeform.py:2053` `_Canvas.ramped: bool = False` | the default assumes a whole level in one tile of run, i.e. assumes `beltVerticalConstruction` | **defect — a tech-level assumption nobody declared.** `catalog.belt_rules_for_technologies` exists and is not consulted for the default. Handed over. |
| `freeform.py:2878` `transition_form` | always returns `RAMP`; `del from_z, to_z` | KEEP (correct today) — but the rule is *asserted in prose*, never evaluated against `catalog.MAX_BELT_SLOPE` |
| no check against `catalog.belt_max_z` anywhere in `freeform.py` | the ceiling | **GAP** — `belt_max_z` appears once, in a docstring |
| `freeform.py:1905-1907` vs `:1924` | comment says the gap floor is `MARGIN + 1`; code enforces `>= 1` | stale comment or a lost constraint — handed over |
| `freeform.py:6573` | docstring says `SORTER_END_EXTENSION` is "0.7 units at each end"; it is `0.35` | citation defect in prose |

---

# 5c. `TooBendToLift` — the row that turned out to matter most

`BEND_MIN_ANGLE_WHEN_SLOPED_RAD` and `SLOPE_DEADZONE` carried the decompiled C#
and had **zero readers anywhere**. The brief was: earn a citation *and* a
consumer, or go. The citation is real —
`BuildTool_Path.cs:1980` — so it cannot go; it needed a consumer.

Done: the rule is now a predicate, `rules.too_bend_to_lift`, and the two
constants moved from `catalog.py` (whose remit is rules read against the
building table or parameterised by tech — these are neither) into `rules.py`
beside it. `tests/dsp/test_rules.py` is the consumer.

**Then I measured how often it fires on our own output, and the number changes
the priority of Step 0.1.** Over trivial+small+mid, 24 cells per strategy:

| strategy | belts examined | convictions | cells with ≥1 |
|---|---|---|---|
| `spine` | 7114 | **213** (3.0%) | **21 of 24** |
| `freeform` | 5761 | **139** (2.4%) | **18 of 24** |

The plan sized this from the user's pasted blueprint as "exactly two instances".
Corpus-wide it is pervasive. If Step 0.1 comes back **red**, nearly every
blueprint either strategy ships today is invalid, and this stops being a
validator item and becomes a router item (Step 2.2's legal-move table) —
because a rule that convicts 39 of 48 cells cannot be enforced as a late
refusal without refusing almost everything.

**That is also why the check is not wired.** Adding a default-ERROR
`geom.bend_while_sloped` now would take the audit from INVALID 0 to INVALID in
39 of 48 cells on the strength of a rule we have not yet confirmed applies to a
paste rather than only to the interactive path tool. Enforcing an unconfirmed
rule is the same class of error as inventing one. The predicate is ready and the
wiring is one line the moment Step 0.1 reports.

Control on the port: it convicts **zero** belts in the game's own blueprints,
over 500+ belts that survive scoping and that contain both turns and slopes.
Mutation-checked — moving the constant to 3.2 convicts 178.

---

# 5d. Clause 4 — every rule constant in `dsp/` now has a reader

The plan's clause 4 ("a constant with no readers is an unported rule wearing a
ported rule's clothes") was failing on three constants at the start of this
phase: `BEND_MIN_ANGLE_WHEN_SLOPED_RAD`, `SLOPE_DEADZONE` and
`ADDON_TURRET_AXIS_DEG`. The first two now have `rules.too_bend_to_lift` and
`tests/dsp/test_rules.py`.

**`ADDON_TURRET_AXIS_DEG = 18.0` still has no code reader, and that is correct.**
It is the turret's value of the same `BuildTool_Addon.cs:877` ternary that gives
`ADDON_AXIS_DEG` its 20.5; `rules.addon_axis_aligned` takes the limit as a
parameter, so the turret value is reachable but never passed, because **we never
place a turret**. Keeping it is what makes the ported ternary complete rather
than half-quoted — the same reason `PASTE_LATERAL` is kept although it is
unreachable for anything but a silo. Recorded here so that a registry test (Step
R2, another agent's) knows it is a deliberate exemption with a reason, not a hole.

That distinction matters and my own check nearly missed it: a naive "is the name
mentioned anywhere else" scan passes on a docstring mention. Clause 4 wants a
constant *consulted*, and only R2's registry test can assert that properly.

---

# 6. OPEN — reported, not parked

1. **How much does one Vertical Construction level raise `labLevel`?**
   `GameHistoryData.cs:1889` is `case 25: labLevel += num;` where `num` comes
   from the tech's `UnlockValues`. Those live in the game's **binary asset
   protos**, not in the decompiled C#, and are not on this box. `catalog.py`
   assumes 1 per level and says so. Its checkable consequence is recorded there:
   FactorioLab models 6 levels ⇒ lab 9 ⇒ ceiling 26.55, while the user's own
   save reaches 38.55 at lab 13. So the assumption **under**-estimates a
   developed save, which refuses altitudes the save would allow and never emits
   one it would not. Searched: `UnlockValues`, `unlockValues`, `TechProto.cs`,
   `TechProtoSet.cs` — the field is declared, never populated in source.

2. **The unit question on `num40`.** `BlueprintUtils.cs:2114` is
   `float num40 = zero.magnitude / num38;` with `num38` one tile, so `num40` is
   in **tiles** while `PASTE_SNAP` / `PASTE_RADIAL` are compared as world units.
   Our bound is therefore ~1.257× **tighter** than the game's — safe, but not
   faithful, and it is now confirmed rather than suspected. Left as-is because
   correcting it loosens a check, which is a behaviour change that wants its own
   measurement.

---

# 6a. The density measurement for the deletions

Paired and interleaved — `base, mine, base, mine, base, mine` — against a
**genuinely separate checkout** of `26f5969c` at
`/home/dannyb/.claude/jobs/66c2051c/tmp/ledger-agent/base`, with its own
`uv sync`, and the import path asserted on both sides:

```
BASE imports: .../tmp/ledger-agent/base/src/flab2bp/__init__.py
MINE imports: .../worktrees/agent-ae558885a22a96f01/src/flab2bp/__init__.py
```

`scripts/audit.py --tier mid --jobs 4`, 96 cells, 3 reps per arm.
**All six arms CLEAN: refused 0, INVALID 0, crashed 0, not run 0.**

Cell-for-cell over the 96 cells CLEAN in **all six** arms:

| | cells | base | mine | delta |
|---|---|---|---|---|
| `spine` | 48 | 99093 | 99093 | **0** |
| `freeform` | 48 | 88217 | 88327 | +110 (+0.12%) |
| both | 96 | 187310 | 187420 | +110 (+0.059%) |

* 87 cells identical and deterministic across all three reps;
* 1 cell same multiset;
* 8 cells DIFFERENT — **and those 8 are exactly the 8 whose area also varies
  between reps within the base arm alone.**

**The falsification control.** A "no change" result is worthless unless the
measurement could have shown a change. It could: those 8 freeform cells move by
up to 156 tiles under plain reruns. And the null — the same statistic computed
base-against-base — is *larger* than the between-arm difference:

```
base rep1 vs base rep2: -177     mine rep1 vs mine rep2: +68
base rep1 vs base rep3: -214     mine rep1 vs mine rep3:  -7
base rep2 vs base rep3:  -37     mine rep2 vs mine rep3: -75
between-arm mean difference: +36.7
```

`spine` is the clean half: deterministic, every one of its 48 cells identical in
all six arms, delta exactly 0. A real behaviour change would have shown there.

**Conclusion: the deletions are behaviour-neutral, as predicted.** That is the
expected result and not a disappointment — none of the four removed rules was
reachable by what we emit. They cost nothing in area today; what they cost was
the next person's confidence that a rule in `dsp/` is a rule.

---

# 6b. Handover — rows whose fix is in a file this phase does not own

`freeform.py` belongs to the Phase 4.1 agent and `scripts/` plus the lint and
registry tests to the R1+R2 agent. These rows are recorded precisely, and the
code is untouched.

### To the Phase 4.1 agent (`freeform.py`)

1. **`_Canvas.add`, `freeform.py:2174-2178` — "machines are solid at every
   altitude".** REMOVE row, no citation. The rule the game applies is the
   collider query, and `colliders.belt_crossing_height` prices a crossing per
   model. Delete the `for lvl in range(LEVELS)` solidity stamp and consult the
   collider instead. This is your row and the ledger's largest density item.

2. **`_make_grid`, `freeform.py:3293-3329`** is a hand-written duplicate of
   `_Canvas.free` — same rule, second implementation. Its own docstring records
   the bug that caused (missing `belt_ban`/`guard`, A* routing through a
   coater's band). Whatever you do to (1) must land in both, or in neither by
   making one a projection of the other (Phase 2.1).

3. **`_Canvas.ramped: bool = False`, `freeform.py:2053` — a tech-level
   assumption nobody declared.** With `ramped` false, `_altitude_profile`
   returns a whole level in one tile of run, which needs
   `beltVerticalConstruction`. The default therefore *assumes the unlock*.
   `catalog.belt_rules_for_technologies` already derives this from the
   FactorioLab URL and is not consulted for the default. Under THE HARD RULE we
   consume what FactorioLab chose; we do not pick. This is a correctness bug on
   any save without Super Magnetic Field Generator.

4. **No check against `catalog.belt_max_z` anywhere in `freeform.py`** — the
   name appears once, in a docstring at `:2891`. `LEVELS = 3` bounds altitude
   for router reasons, not legality reasons, so nothing enforces the ceiling on
   the freeform path. `spine` has it (`_MAX_SPUR_Z`).

5. Two prose defects: `freeform.py:1905-1907` claims the gap floor is
   `MARGIN + 1` while `:1924` enforces `>= 1`; `freeform.py:6573` says
   `SORTER_END_EXTENSION` is "0.7 units at each end" when it is `0.35`.

### To whoever takes Phase 1 (`spine.py`, unowned — I edited it, see below)

6. `spine.py:3065` `_trunk_x` hardcodes `2` where `catalog.RAMP_TILES_PER_LEVEL`
   is 2, and its own docstring names the constant the code does not read.
7. `spine.py` never calls `junction.site_is_clear`, `junction.keepout_cells`, or
   `slots.sorter_seat_is_clear` — three finished legality gates that only
   `freeform` uses. Junction siting and sorter-vs-sorter collision are unguarded
   on the spine path.
8. Three different tower-centre conventions in one file (`spine.py:4674` raw,
   `:4753` `+width/2`, `:4785` `+0.5`) feeding the same radius comparisons.

**Files I edited outside `dsp/` and `validate.py`:** `spine.py` (one constant,
`_TRUNK_Z`, now local instead of `catalog.BELT_CROSSING_CLEARANCE` — same value,
spine is unowned) and `slots.py` (the `DRAG_MAX_ALIGNMENT` move to `dsp/rules.py`
plus a comment at the alignment test; no behaviour change, verified by the
audit's zero delta on all 48 spine cells).

---

# 7. Unported halves, recorded so they are not rediscovered

* `TooBendToLift` — `BuildTool_Path.cs:1980`. Constants ported, **zero readers**.
* The sorter segment/altitude pair — `BuildTool_Inserter.cs:1341,1347`
  (`num7`, `num8`). `num7` reduces to `SORTER_MAX_REACH` on a uniform grid;
  `num8`'s floor is below our 1-tile minimum in every class.
* The silo `ErrorInserterData` branch — `BlueprintUtils.cs:2118-2124`.
* The addon `Maths.DistancePointLine(...) < 0.3f` clause — `PlanetFactory.cs:5931`,
  on the same line as the radius we do check.
