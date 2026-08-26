# `EBuildCondition` coverage — every way the game can refuse us

`docs/RULE_LEDGER.md` verified every rule **we already knew about**. It is
structurally unable to find a rule nobody here ever wrote down, and that gap cost
a real build: the user pasted our blueprint into DSP and two Tesla Towers came
back `PowerTooClose`, a rule we had never modelled because
`colliders.build_colliders(2201)` returns `()` and `geom.collide` was therefore
blind to it.

This file closes that gap from the other end. `EBuildCondition` is the complete
list of refusals the game has; nothing outside it can happen. Every value gets
exactly one verdict here, and `tests/conditions/test_ebuild_coverage.py` fails
the build if a value ever appears without one.

## The count

| verdict | n |
|---|---|
| **IMPLEMENTED** — we model it | 10 |
| **INAPPLICABLE** — it cannot arise from a paste of what we emit | 44 |
| **MISSING** — the game can do this to us and we do not model it | 5 |
| **total** | **59** |

**The enum has 59 values, not 57.** Values 0-54 are contiguous, then
`MayBeBuried = 100`, `MarkerTooClose = 101`, `ConnWithErrorBuilding = 201`,
`BlueprintReformNeedTech = 202`. Counting only the contiguous run gives 55;
counting to `ErrorInserterData` and adding two gives 57. The test parses the
enum rather than trusting any of those numbers.

## The verdict table

This is the machine-readable half of the file:
`tests/conditions/test_ebuild_coverage.py` parses exactly this table, checks it
against the enum, and fails if any value is missing, duplicated, unknown, or
carries a verdict outside the three. Everything below it is the argument; this
is the index. `#` is the enum's own value, not a row number.

<!-- BEGIN VERDICT TABLE -->

| # | condition | verdict | argued in |
|---|---|---|---|
| 0 | `Ok` | INAPPLICABLE | F |
| 1 | `Failure` | INAPPLICABLE | F |
| 2 | `NotEnoughItem` | INAPPLICABLE | B |
| 3 | `NeedTech` | INAPPLICABLE | A |
| 4 | `TooShort` | INAPPLICABLE | B |
| 5 | `PowerTooClose` | MISSING | MISSING #1 |
| 6 | `WindTooClose` | INAPPLICABLE | D |
| 7 | `GeothermalTooClose` | INAPPLICABLE | D |
| 8 | `TowerTooClose` | INAPPLICABLE | D |
| 9 | `EjectorTooClose` | INAPPLICABLE | D |
| 10 | `BlockTooClose` | INAPPLICABLE | D |
| 11 | `MK2MinerTooClose` | INAPPLICABLE | D |
| 12 | `PlasmaTooClose` | INAPPLICABLE | D |
| 13 | `TooClose` | IMPLEMENTED | IMPLEMENTED |
| 14 | `TooFar` | IMPLEMENTED | IMPLEMENTED |
| 15 | `TooSkew` | MISSING | MISSING #4 |
| 16 | `TooSteep` | IMPLEMENTED | IMPLEMENTED |
| 17 | `TooBend` | INAPPLICABLE | B |
| 18 | `TooBendToLift` | INAPPLICABLE | B |
| 19 | `TooBendInBeltJunction` | INAPPLICABLE | B |
| 20 | `JointCannotLift` | INAPPLICABLE | B |
| 21 | `InputConflict` | INAPPLICABLE | B |
| 22 | `InputFull` | INAPPLICABLE | B |
| 23 | `NeedGround` | MISSING | MISSING #5 |
| 24 | `NeedWater` | INAPPLICABLE | D |
| 25 | `NeedGeothermalResource` | INAPPLICABLE | D |
| 26 | `NeedResource` | INAPPLICABLE | D |
| 27 | `NeedSingleResource` | INAPPLICABLE | D |
| 28 | `NeedConn` | IMPLEMENTED | IMPLEMENTED |
| 29 | `NeedExport` | INAPPLICABLE | B |
| 30 | `NeedAddonStorage` | INAPPLICABLE | D |
| 31 | `NeedSupport` | INAPPLICABLE | A |
| 32 | `BeltCannotConnectToBuilding` | INAPPLICABLE | A |
| 33 | `BeltCannotConnectToBuildingWithInserterTip` | INAPPLICABLE | B |
| 34 | `Collide` | IMPLEMENTED | IMPLEMENTED |
| 35 | `Occupied` | INAPPLICABLE | B |
| 36 | `Covered` | INAPPLICABLE | B |
| 37 | `OutOfReach` | IMPLEMENTED | IMPLEMENTED |
| 38 | `BuildInEquator` | INAPPLICABLE | E |
| 39 | `NotEnoughEnergyToWorkCollection` | INAPPLICABLE | E |
| 40 | `OutOfVerticalConstructionHeight` | MISSING | MISSING #2 |
| 41 | `ExceededMaximum` | INAPPLICABLE | D |
| 42 | `FieldGeneratorTooClose` | INAPPLICABLE | D |
| 43 | `BattleBaseTooClose` | INAPPLICABLE | D |
| 44 | `BasePitNotClear` | INAPPLICABLE | A |
| 45 | `BlueprintAreaCrossTropic` | IMPLEMENTED | IMPLEMENTED |
| 46 | `BlueprintAreaNotEnoughSpace` | IMPLEMENTED | IMPLEMENTED |
| 47 | `BlueprintNotAlignTropicAnchor` | INAPPLICABLE | F |
| 48 | `BlueprintWrongTropicRatio` | INAPPLICABLE | F |
| 49 | `BlueprintPreSelectObj` | INAPPLICABLE | C |
| 50 | `BlueprintDeleteSelectObj` | INAPPLICABLE | C |
| 51 | `BlueprintBPOverlap` | IMPLEMENTED | IMPLEMENTED |
| 52 | `BlueprintNeedTech` | MISSING | MISSING #3 |
| 53 | `BlueprintNeedAddonTheCorrectPosition` | INAPPLICABLE | D |
| 54 | `ErrorInserterData` | IMPLEMENTED | IMPLEMENTED |
| 100 | `MayBeBuried` | INAPPLICABLE | F |
| 101 | `MarkerTooClose` | INAPPLICABLE | A |
| 201 | `ConnWithErrorBuilding` | INAPPLICABLE | F |
| 202 | `BlueprintReformNeedTech` | INAPPLICABLE | G |

<!-- END VERDICT TABLE -->

## What we emit — the set every INAPPLICABLE argument depends on

Every "it cannot arise" argument below is an argument about **building types**,
so it stops holding the day we emit a new one. The set is:

| kind | item ids | where |
|---|---|---|
| belts | 2001-2003 | `spine.BELT_ITEM_IDS` |
| sorters | 2011-2014 | `spine.SORTER_TIERS` |
| splitter | 2020 | `catalog.SPLITTER_ID`, `layout/junction.py` |
| Tesla Tower | 2201 | `spine.LayoutConstants.tesla_item_id` |
| Spray Coater | 2313 | `spine.LayoutConstants.spray_item_id`, `freeform.py:6913` |
| machines | 2208, 2209, 2302-2305, 2308-2310, 2314, 2315, 2317-2319, 2901, 2902 | `spine.MACHINE_ITEM_IDS` |

`spine.MACHINE_ITEM_IDS` *also* maps `mining-machine` (2301),
`advanced-mining-machine` (2316), `water-pump` (2306), `oil-extractor` (2307) and
`orbital-collector` (2105) — and **none of the five can ever reach the layout**,
which is what makes five conditions inapplicable rather than merely unlikely.
`rates/solve._buildable_producers` drops every recipe carrying FactorioLab's
`mining` flag, and `lab/flow.py:350,752` drops the same set on the pinned-flow
path. Measured against the vendored dataset (493 recipes, 22 mining-flagged, 306
technology-flagged):

```
producers over ALL recipes:      22 machines, including
                                 advanced-mining-machine, mining-machine,
                                 oil-extractor, orbital-collector, water-pump
producers over BUILDABLE recipes: 17 machines
cut by the mining flag:          exactly those five
```

The mining flag and the five extraction machines coincide exactly. Nothing else
is lost, and nothing extraction-shaped survives.

## How to read a citation

Same convention as `docs/RULE_LEDGER.md`: **`File.cs:line`, file-relative**,
against `/home/dannyb/.claude/jobs/66c2051c/tmp/poseless/full/`. The "+143582"
offset that circulates on this project is not universal — it is 0 for
`BlueprintUtils.cs` and `PlanetGrid.cs`, and not uniform even within
`BuildTool_BlueprintPaste.cs`'s own citations. **Every line number below was
found by grepping for the literal**, not by applying an offset;
`tests/conditions/test_ebuild_coverage.py` re-checks each one against the
decompiled tree when that tree is present.

Most of the citations below are into one file, so a bare `:2586` means
`BuildTool_BlueprintPaste.cs:2586` — and that default is declared in the marker
on the next line rather than left as a habit, because the test parses it:

<!-- CITATIONS DEFAULT BuildTool_BlueprintPaste.cs -->

A citation that names a file **anywhere earlier on its own line** overrides the
default for the rest of that line, and the override stops at the newline. It
does not carry into the next paragraph or the next table row: the first draft of
this parser let it, and quietly attributed sixteen
`BuildTool_BlueprintPaste` line numbers to `BuildTool_BlueprintCopy`.

## Which tool sets it, and why that decides the verdict

`EBuildCondition` is shared by seven build tools. Only **`BuildTool_BlueprintPaste`**
(and `BlueprintUtils.RefreshBuildPreview`, which it calls) governs a paste.
`BuildTool_Path`, `BuildTool_Click`, `BuildTool_Inserter`, `BuildTool_Addon`,
`BuildTool_Dismantle` and `BuildTool_BlueprintCopy` are interactive tools whose
rules do not run on a paste at all. Ten conditions are `BuildTool_Path`-only, and
one of them — `TooBendToLift` — was on its way to convicting 21 of 24 spine cells
before anyone checked which file set it.

`BuildPreview.cs:91-145` is **not** a setter. It is
`BuildPreview.GetConditionText`'s switch, one arm per value. Five values appear
there and *nowhere else in the assembly*: they are dead.

Two more facts govern several rows, both from `AddErrorMessage`,
`BuildTool_BlueprintPaste.cs:4814-4818`:

```csharp
public void AddErrorMessage(EBuildCondition _bdCondition, BuildPreview _bp = null)
{
    if (_bdCondition == EBuildCondition.Ok || _bdCondition == EBuildCondition.NotEnoughItem || _bdCondition == EBuildCondition.BlueprintBPOverlap)
    {
        return;
    }
```

`NotEnoughItem` and `BlueprintBPOverlap` never enter the error set, so neither
can refuse a paste.

---

## MISSING — 5 rows

Ranked by whether they can fire on what we emit **today**, measured over the
12-entry bench corpus (`flab2bp.bench.corpus.URL_CORPUS`) through
`pipeline.build(url, time_budget_s=2.0)` — 11 of 12 built, `universe-matrix`
refusing at that budget. The probes are in
`/home/dannyb/.claude/jobs/66c2051c/tmp/ebuild-audit/`.

**The corpus was run twice and the two runs differ**, because which candidate
wins is a function of what the solver finds inside its wall-clock budget:
`quantum-chip` came out at 8225 buildings in the first pass and 3703 in the
second. Both passes are reported below rather than the better-looking one. What
is stable across them is *which* rules fire, which is the question this file
asks; the counts are not a benchmark.

### 1. `PowerTooClose = 5` — **already firing; another agent is fixing it**

*Status: IN FLIGHT. Recorded here for completeness; this audit did not touch it.*

**Where the game sets it.** Guarded by
`BuildTool_BlueprintPaste.cs:2527` `if (buildPreview2.desc.isPowerNode && !buildPreview2.desc.isAccumulator)`,
then three near-identical blocks — against live power nodes
(`BuildTool_BlueprintPaste.cs:2581-2588`), against prebuilds
(`BuildTool_BlueprintPaste.cs:2631-2638`) and **against other previews in the
same blueprint** (`BuildTool_BlueprintPaste.cs:2675-2682`), which is the one
that catches two of our own towers:

```csharp
else if (!buildPreview2.desc.isPowerGen && nodes[num39].genId == 0 && num35 < 12.25f)
{
    buildPreview2.condition = EBuildCondition.PowerTooClose;
```

**Threshold, with units.** `num35` is a squared world distance
(`BuildTool_BlueprintPaste.cs:2560-2563`), so the rule is
**centre-to-centre < 3.5 world units**. A tile is
`2π·200/1000 = 1.2566` world units in the equatorial band, so 3.5 world units is
**2.79 tiles** there and fewer poleward, where columns compress.

**Which of our buildings.** The three power nodes in our emit set, from
`dsp/data/buildings.json`'s `power.node` field: Tesla Tower 2201, Ray Receiver
2208, Energy Exchanger 2209. The Accumulator (2206) is the one exclusion in the
guard and we never emit it.

**Measured.** Over the 11 builds of the second pass: 118 power nodes, **7 pairs
closer than 3.5 world units**. `electromagnetic-matrix` has three pairs at
**1.258 world units** — adjacent tiles — and `quantum-chip` three more. Distances
are computed through `planet.Projection.position`, the same arithmetic
`BlueprintUtils.RefreshBuildPreview` uses, not a flat tile approximation: an
earlier count that compared tile gaps against 3.5 was wrong by the tile arc and
is not the number quoted here.

**Kind.** Both: a validator rule (`power.*`) and a layout constraint (the tower
placer must keep a 2.79-tile separation in the equatorial band).

### 2. `OutOfVerticalConstructionHeight = 40` — **fires on 4 splitters in the corpus**

**Where the game sets it.** `BuildTool_BlueprintPaste.cs:2036-2068`:

```csharp
if (buildPreview2.desc.isTank || buildPreview2.desc.isStorage || buildPreview2.desc.isLab || buildPreview2.desc.isSplitter)
{
    int num11 = (buildPreview2.desc.isLab ? history.labLevel : history.storageLevel);
    int num12 = (buildPreview2.desc.isLab ? 15 : 8);
    int num13 = 0;
    float num14 = buildPreview2.lpos.magnitude - 200.2f;
    ...
    if (buildPreview2.desc.isSplitter)
    {
        num13 = Mathf.RoundToInt(num14 / 2.666667f);
    }
    if (num13 >= num11)
    {
        ...
        buildPreview2.condition = EBuildCondition.OutOfVerticalConstructionHeight;
```

**Threshold, with units.** `lpos.magnitude` is
`localOffset_z * 1.3333333 + 0.2 + realRadius` (`BlueprintUtils.cs:2048`), and
`200.2` is `realRadius + 0.2` for a 200-radius planet, so `num14 = z * 4/3`
exactly. The divisors are the buildings' own `stackHeight` from
`dsp/data/buildings.json` — Splitter 2.67, Matrix Lab 4.0, Self-evolution Lab
4.0. So:

* **Splitter** — refused when `round(z / 2) >= history.storageLevel`.
* **Lab** — refused when `round(z / 3) >= history.labLevel`.

`GameHistoryData.cs:576-577` gives a new save `storageLevel = 2` and
`labLevel = 3`. `Mathf.RoundToInt` is banker's rounding, so `round(3/2) = 2`:
**a Splitter at z >= 3 is refused on a default save**, and a Lab needs z >= 8.

**Which of our buildings.** Splitters (2020) and Matrix / Self-evolution Labs
(2901, 2902). The labs are already safe and will stay safe only as long as
`geom.machine_ground` holds — it pins every `Kind.MACHINE` to `z = 0`, and its
own docstring calls that our invariant rather than the game's. **Splitters are
`Kind.SPLITTER`, so no check bounds their altitude at all.**

`layout/validate.py:1501-1508` already discusses this condition and concludes
"We never stack any of the four". That is the defect: the game does not measure
*stacking*, it measures **altitude**. A splitter sitting on a belt at z = 3 has
nothing stacked under it and is refused all the same.

**Measured, in both passes.** First pass, splitter altitude histogram over the
corpus: `z=0: 1, z=2: 1, z=3: 4` — **four splitters the game refuses on a default
save**, two from `information-matrix` and four from `quantum-chip`; the z = 2 one
is legal, `round(2/2) = 1 < 2`. Second pass, a different candidate won for
`quantum-chip` and it emitted **one**. Splitters are rare in our output — nine in
total across eleven builds — so the rule fires on a small absolute number and on
100% of the builds that use altitude for a junction.

**Kind.** Both: a validator rule (a splitter's `z` against `storageLevel`, which
is tech and so belongs next to `catalog.belt_max_z`) and a layout constraint
(the junction placer must not put a splitter above z = 2 without the unlock).

### 3. `BlueprintNeedTech = 52` — **every corpus build but one exceeds the first unlock**

**Where the game sets it.** `BuildTool_BlueprintPaste.cs:1113-1131`, inside
`CheckBuildConditionsPrestage`, which `return false`s — this refuses the **whole
paste**, not one building:

```csharp
if (base.actionBuild.history.blueprintLimit < blueprint.buildings.Length)
{
    AddErrorMessage(EBuildCondition.BlueprintNeedTech);
}
```

and the same comparison is `bMeetTech`'s own definition,
`BuildTool_BlueprintPaste.cs:243`.

**Threshold, with units.** A count of buildings, against `history.blueprintLimit`.
`UITechTree.cs:1625` reads that number back: `< 150` means "not yet unlocked",
`<= 3600` shows the number, above that it is unlimited. So the ladder our output
has to clear is **150 at the first unlock and 3600 at the last finite one**.

**Which of our buildings.** All of them — it is a count, not a type.

**Measured.** **9 of 11 corpus builds exceed 150** — everything past
`magnetic-coil` (51). `quantum-chip` came out at **8225 buildings** in the first
pass and 3703 in the second; `information-matrix` 2893 then 3280;
`casimir-crystal` 1815 then 1969. So one to two builds per pass exceed **3600**
as well, which is the last finite rung: those need blueprint research fully
maxed, and nothing anywhere tells the user that.

**Kind.** A validator rule, and a *reporting* one: we cannot make the player's
research bigger, so the right shape is a warning that names the tech tier the
blueprint needs — the same shape `geom.bounds` already uses for its soft-width
warning. Nothing in the repo mentions `blueprintLimit` today.

### 4. `TooSkew = 15`, spray-coater form — **inert at the bands we usually record; live at two of them**

*The two inserter forms of `TooSkew` are modelled (see IMPLEMENTED). This third
form is not, which is why the row is here.*

**Where the game sets it.** `BuildTool_BlueprintPaste.cs:1863-1868`:

```csharp
if (buildPreview2.desc.isSpraycoster || buildPreview2.desc.isTurret)
{
    Vector3 reshapeData = SpraycoaterComponent.GetReshapeData(buildPreview2.lpos, buildPreview2.lrot);
    if (Mathf.Abs(reshapeData.x) > 0.265f || Mathf.Abs(reshapeData.y) > 0.265f)
    {
        buildPreview2.condition = EBuildCondition.TooSkew;
```

**Threshold, with units.** `SpraycoaterComponent.cs:120-146` returns the
coater's curvature stretch. The magnitude scales with
`num = |dot(east, coater.forward)|` — 1 for an east/west coater, 0 for a
north/south one — and with the longitude segment count at that latitude.
Evaluating it for `num = 1` over every band of a segment-200 planet:

| `area_segments` | grid rows | `max abs(x)` | `max abs(y)` | verdict vs 0.265 |
|---|---|---|---|---|
| 200 | 1..80 | 0.0118 | 0.0118 | ok |
| 160 | 81..130 | 0.0148 | 0.0155 | ok |
| 120 | 131..155 | 0.0197 | 0.0211 | ok |
| 100 | 156..180 | 0.0237 | 0.0251 | ok |
| 80 | 181..195 | 0.0296 | 0.0304 | ok |
| 60 | 196..210 | 0.0395 | 0.0417 | ok |
| 40 | 211..220 | 0.0592 | 0.0658 | ok |
| 32 | 221..230 | 0.0740 | 0.0791 | ok |
| 20 | 231..235 | 0.1184 | 0.1302 | ok |
| 16 | 236..240 | 0.1480 | 0.1556 | ok |
| **8** | **241..245** | **0.2953** | **0.3592** | **REFUSED** |
| **4** | **246..250** | **0.5862** | **0.6649** | **REFUSED** |

So the rule bites **only** in the 8-segment and 4-segment bands — latitude
>= 86.8 degrees — and there it refuses an east/west coater outright (0.295 and
0.586 against a 0.265 cap).

**Which of our buildings.** The Spray Coater, 2313. `freeform.py:6960` orients
it `Facing.EAST`, so the `num = 1` worst case is the case we always emit. The
band comes from `codec._area_for`: `stats["area_segments"]` when a strategy has
verified one, else `planet.widest_band_for_extent`. The verified path **does**
produce narrow bands — measured `area_segments = 8` for `iron-ingot` and `32`
for `magnetic-coil`.

**Measured.** No corpus build lands in a refusing band *with* a coater, so this
one has not shipped a refusal yet. But it is one step away, not far away:

| build | buildings | `area_segments` | Spray Coaters |
|---|---|---|---|
| `iron-ingot` | 11 | **8** | 0 |
| `magnetic-coil` | 51 | **32** | **1** |
| every other build | 181-8225 | 200 | 0-40 |

`magnetic-coil` is a proliferated build carrying a Spray Coater whose verified
band is 32 — two rungs above the first band that refuses. A build slightly
smaller than `magnetic-coil` and still proliferated lands on 16, then 8, and the
paste refuses the coater. That is why the row is MISSING rather than
INAPPLICABLE: both halves are produced by our own code, they have been observed
within two rungs of each other, and nothing prevents them meeting.

**Kind.** A validator rule, cheapest as a refusal in `codec._area_for` — a
placement containing a Spray Coater may not record `area_segments` of 8 or 4.

### 5. `NeedGround = 23` — **real, and provably not a property of a blueprint**

**Where the game sets it.** Six setters at
`BuildTool_BlueprintPaste.cs:3248`, `:3257`, `:3265`, `:3295`, `:3304`, `:3312`,
plus `BuildTool_BlueprintPaste.cs:3533` and `:3542` for the belt path. Each is a
terrain raycast per `desc.landPoints` entry:

```csharp
if (Physics.Raycast(new Ray(origin, direction), out hitInfo, 18f, 8704, QueryTriggerInteraction.Collide))
{
    ...
    if (hitInfo.point.magnitude - factory.planet.realRadius < -0.5f - num117)
    {
        buildPreview2.condition = EBuildCondition.NeedGround;
```

and a second clause at `BuildTool_BlueprintPaste.cs:3255`,
`if (!flag17 && num115 - num116 > 0.27f + num117)` — ground and water layers more
than `0.27 + landOffset` apart.

**Which of our buildings.** Every machine with `landPoints`, i.e. all of them.

**Why it is here and not under INAPPLICABLE.** The game genuinely does this to
us, so calling it inapplicable would be false. But the input is the *terrain the
player pastes onto*: the identical blueprint pastes one tile away. No offline
check can predict it, and the paste does not offer to auto-foundation because
reform is a separate opt-in pass (`ComputeReform`). This is already reasoned out
in `layout/validate.py:1491-1499` and `docs/BACKLOG.md`; recorded here as MISSING
so the matrix does not quietly imply we have it covered.

**Kind.** Neither a validator rule nor a layout constraint — a *documentation*
row. The honest fix is a line in the CLI's output telling the user to level the
ground, not a check.

---

## IMPLEMENTED — 10 rows

| # | condition | where the game sets it (paste path only) | our model |
|---|---|---|---|
| 13 | `TooClose` | `BuildTool_BlueprintPaste.cs:3468-3470` `if (magnitude < num132)`, `num132` = 0.4 / 0.6 / 0.9 by belt-end count (`:3444`, `:3449`, `:3456`) | `rules.SORTER_LENGTH` (min), `sorter.reach`, `game.inserter_paste`, `planet.sorter_condition` |
| 14 | `TooFar` | `:3462-3464` `if (magnitude > num131)`, `num131` = 5.0 / 5.5 / 7.5 (`:3443`, `:3450`, `:3457`); belt-to-belt `:2087-2089` `sqrMagnitude > 5.3f`; inserter endpoint `:2100-2125` `> 16f` then `> 28f`, with item 2307 exempt | `rules.SORTER_LENGTH` (max), `sorter.reach`, `belt.link_adjacent`, `planet.sorter_condition` |
| 15 | `TooSkew` | `:3488` `Quaternion.Angle(lrot, lrot2) > 30f`; `:3494-3501` `if (num135 > 24f \|\| num136 > 24f)` | `rules.SKEW_PAIR_DEG = 30`, `rules.SKEW_AXIS_DEG = 24`, `game.inserter_skew`, `slots.attachment`. **The spray-coater form at `:1866` is NOT modelled — see MISSING #4.** |
| 16 | `TooSteep` | `:2093-2095` `if (!history.beltVerticalConstruction && Mathf.Abs(Vector3.Dot(lpos.normalized, (output.lpos - lpos).normalized)) > 0.6f)` | `geom.altitude_step`, `catalog.BeltAltitudeRules.vertical_construction` |
| 28 | `NeedConn` | `:1738-1740` `if (flag \| flag2) { bp.condition = EBuildCondition.NeedConn; }` after `MatchInserter` fails to seat an end | `rules.MATCH_SNAP_MAX_SQR = 6.0`, `rules.MATCH_ALIGN_COS = 0.9702957`, `game.inserter_paste`, `sorter.anchors_present`, `sorter.endpoints`. **Note it never calls `AddErrorMessage`**: an unseated sorter is silently dropped, not refused, which is exactly the failure `game.inserter_paste` exists to catch. |
| 34 | `Collide` | `:2511-2514` the belt probe sphere `OverlapSphereNonAlloc(..., 0.5f, ...)`; `:2484-2490` the addon-on-belt clause; `:2498-2500` `desc.veinMiner`; `:3044-3050` the birth-point capsule zone; `:3710-3715` and `:3786-3788` belt-cover conflicts against objects already on the planet | `geom.collide`, `geom.overlap`, `game.sorter_collide`, `game.belt_collide`, `game.belt_crossing`, `game.addon_facing`, `game.addon_corner`, `game.addon_crossings`, `colliders.build_colliders`. The `veinMiner` clause is inapplicable (no miners); the birth-point and belt-cover clauses are properties of the planet pasted onto, noted in `validate.py:1511-1514`. |
| 37 | `OutOfReach` | `:2073-2078` `float num15 = history.buildMaxHeight + 0.5f + planet.realRadius * (flag4 ? 1.025f : 1f); if (lpos.sqrMagnitude > num15 * num15)` | `geom.altitude_range` via `catalog.belt_max_z()` / `DEFAULT_LAB_LEVEL = 3`; already a KEEP row in `RULE_LEDGER.md`. The second setter `:2688-2692` is `desc.isCollectStation` and inapplicable. |
| 45 | `BlueprintAreaCrossTropic` | `BlueprintUtils.cs:2500` `if (GetAreaCount(_latitude, w, _segmentCnt) > 1) { _areaGratBoxConditions[num5].x++; }`, surfaced `:2063` and refused for the whole paste at `BuildTool_BlueprintPaste.cs:1141-1144` | `dsp/planet.py` (`area_count`, `bands`, `band_for_extent`, `widest_band_for_extent`, `BandRefusal`), consumed by `codec._area_for` |
| 46 | `BlueprintAreaNotEnoughSpace` | `BlueprintUtils.cs:2489-2492` (a box corner past `±1.5712963` rad, i.e. over a pole) and `:2495-2498` (`(curWidth - 1) * longitudeRadPerGrid > 2π - longitudeRadPerGrid`, i.e. wider than the planet); refused at `BuildTool_BlueprintPaste.cs:1146-1149` | the same band model: `Fit` requires `rows <= band.rows` and `cols <= band.columns`, and `Band.anchors(rows)` is non-empty exactly when a pole-free window exists. What remains is the player's choice of anchor, which no blueprint can constrain. |
| 51 | `BlueprintBPOverlap` | `BuildTool_BlueprintPaste.cs:908-932`, two previews hashing to the same cell with `buildPreview2.desc == buildPreview3.desc` (`:910`); for belts the weighted centre `0.7f * lpos + 0.15f * (input.lpos + output.lpos)` must be within `sqrMagnitude < 0.25f` (`:917-920`) | `geom.overlap`, `geom.footprint`, `junction.colocated`, `belt.link_adjacent`. **Not a refusal** — `AddErrorMessage` returns early for it (`:4816`) and `:4575`, `:4620` treat it as drawable. It is a *silent drop*: the earlier preview gets `bpgpuiModelId = -1` and is never built. The `desc == desc` guard at `:910` is what lets a Splitter and a belt share a tile, which is the convention `layout/junction.py` reads off 25 real splitters. |
| 54 | `ErrorInserterData` | `BlueprintUtils.RefreshBuildPreview`, `BlueprintUtils.cs:2114-2141` (input end) and `:2165-2192` (output end): `num40 > 0.8f` then `num41 > 0.5f`, `num41 < 0.1f && num40 > 1.6f`, `num41 >= 0.1f && num40 > 0.8f`, and the reversal test `Vector3.Dot(transformedBy.forward, ...) < 0f` | `rules.PASTE_SNAP = 0.8`, `rules.PASTE_LATERAL = 0.5`, `rules.PASTE_RADIAL = 1.6`, `rules.PASTE_LATERAL_EPS = 0.1`, `game.inserter_data`, `game.slot_occupancy` |

That is 11 rows in the table and 10 in the count, because `TooSkew` is counted
under MISSING: one of its three paste forms is unmodelled, and a row where the
game can still refuse us is not an implemented row. It is listed here as well so
the part that *is* modelled is not lost.

---

## INAPPLICABLE — 44 rows

Grouped by the shape of the argument. Every group names the guard, and every
guard is a `desc.*` flag or a tool the paste never runs.

### A. Never assigned anywhere in the assembly — 5

These appear only in `BuildPreview.GetConditionText`'s switch. `rg` over the
whole decompiled tree finds one hit each, and it is the translation arm.

| # | condition | only occurrence |
|---|---|---|
| 3 | `NeedTech` | `BuildPreview.cs:93` |
| 31 | `NeedSupport` | `BuildPreview.cs:121` |
| 32 | `BeltCannotConnectToBuilding` | `BuildPreview.cs:122` |
| 44 | `BasePitNotClear` | `BuildPreview.cs:141` |
| 101 | `MarkerTooClose` | `BuildPreview.cs:143` |

*Depends on:* nothing of ours. This group is stable against anything we emit and
only moves if the game adds a setter.

### B. Set only by an interactive tool the paste never runs — 12

| # | condition | setter, and the tool |
|---|---|---|
| 2 | `NotEnoughItem` | `BuildTool_Click.cs:1552`, `BuildTool_Path.cs:1419`, `BuildTool_Inserter.cs:1303`, `BuildTool_Addon.cs:1020`. `BuildTool_BlueprintPaste` **reads** it 19 times and **never assigns** it, and `AddErrorMessage` (`BuildTool_BlueprintPaste.cs:4816`) returns early for it, so it can neither be set by a paste nor refuse one. |
| 4 | `TooShort` | `BuildTool_Path.cs:1254`, `:1283` |
| 17 | `TooBend` | `BuildTool_Path.cs:1895`, `:1922`, `:1990`, `:2117` |
| 18 | `TooBendToLift` | `BuildTool_Path.cs:1982` — **only there**. `rules.BEND_MIN_ANGLE_WHEN_SLOPED_RAD` and `rules.SLOPE_DEADZONE` carry its constants with no readers, and `RULE_LEDGER.md` already records that. This is the item that was about to convict 21 of 24 spine cells. |
| 19 | `TooBendInBeltJunction` | `BuildTool_Path.cs:1942`, `:2183` |
| 20 | `JointCannotLift` | `BuildTool_Path.cs:2004`, `:2038`, `:2046` |
| 21 | `InputConflict` | `BuildTool_Path.cs:2112`, `:2129`, `:2145`, `:2161`, `:2202` |
| 22 | `InputFull` | `BuildTool_Path.cs:1851`, `:1855` |
| 29 | `NeedExport` | `BuildTool_Path.cs:1455` |
| 33 | `BeltCannotConnectToBuildingWithInserterTip` | `BuildTool_Path.cs:1339`, `:1342`, `:1346` |
| 35 | `Occupied` | `BuildTool_Path.cs:1258`, `:1261`, `:1287`, `:1290` |
| 36 | `Covered` | `BuildTool_Dismantle.cs` only |

*Depends on:* nothing of ours — it is a property of the tool, not the buildings.
`TooSteep` and `TooClose` are *not* in this group: `BuildTool_Path` sets them too,
but so does the paste, and those rows are IMPLEMENTED on the paste's own citation.

### C. Copy-tool UI states, not paste failures — 2

| # | condition | only setter |
|---|---|---|
| 49 | `BlueprintPreSelectObj` | `BuildTool_BlueprintCopy.cs:1120`, `:1143` — `currSelectMethod == SelectMethod.Add`, i.e. "this object is highlighted for inclusion" |
| 50 | `BlueprintDeleteSelectObj` | `BuildTool_BlueprintCopy.cs:1120`, `:1143` — the `Sub` arm of the same ternary |

Both are set on the *copy* tool's live preview to colour the selection, seven
occurrences each and every one in `BuildTool_BlueprintCopy.cs`. Neither exists on
the paste path.

*Depends on:* nothing of ours.

### D. Guarded by a `desc.*` flag no building we emit carries — 16

The guard is quoted; the DSP building that does carry the flag is named so the
argument is checkable rather than asserted.

| # | condition | guard | the building it is about |
|---|---|---|---|
| 6 | `WindTooClose` | `:2546` `bool windForcedPower = buildPreview2.desc.windForcedPower;` then `:2571`, `:2621`, `:2665` `num35 < 110.25f` | Wind Turbine, 2203. The flag is read off **our own** preview, not the neighbour's, so it is our emit set that decides. |
| 7 | `GeothermalTooClose` | `:2547` `bool geothermal = buildPreview2.desc.geothermal;` then `:2576`, `:2626`, `:2670` `num35 < 144f` | Geothermal Power Station, 2213 |
| 8 | `TowerTooClose` | `:2843` `if (buildPreview2.desc.isStation)` → `:2869`, `:2897`, `:2925` | the logistics stations, 2103/2104 |
| 9 | `EjectorTooClose` | `:2950` and `BuildTool_Addon.cs`; the paste block is under `desc.isEjector` | EM-Rail Ejector, 2311 |
| 10 | `BlockTooClose` | `:3005` `if (buildPreview2.desc.isEjector)` → `:3036-3038` | EM-Rail Ejector, 2311 |
| 11 | `MK2MinerTooClose` | `:2843` `if (buildPreview2.desc.isStation)` → `:2863-2865` | Advanced Mining Machine's collection station |
| 12 | `PlasmaTooClose` | `:3055` `if (buildPreview2.desc.turretType == ETurretType.Plasma \|\| ... LocalPlasma)` → `:3077`, `:3095`, `:3114` | the plasma turrets, 3003 / 3005 |
| 24 | `NeedWater` | `:3317` `for (int num121 = 0; num121 < buildPreview2.desc.waterPoints.Length; num121++)` → `:3336` | Water Pump, 2306 — mining-flagged and cut upstream |
| 25 | `NeedGeothermalResource` | the same loop, `:3330` `if (buildPreview2.desc.geothermal)` → `:3332` | Geothermal Power Station, 2213 |
| 26 | `NeedResource` | the `desc.minerType` vein scan, `:1931`-`:2025` | the mining machines, 2301 / 2316 — cut upstream |
| 27 | `NeedSingleResource` | `:1881` `if (buildPreview2.desc.isVeinCollector)` → `:1914` | Advanced Mining Machine, 2316 — cut upstream |
| 30 | `NeedAddonStorage` | `:3380` `if (buildPreview2.desc.addonType != EAddonType.None && buildPreview2.desc.addonType == EAddonType.Storage)` → `:3384`; again `:4112-4117` | Logistics Distributor, 2107. Our only addon is the Spray Coater, whose `addonType` is **1 (Belt)**, from `dsp/data/buildings.json`. |
| 41 | `ExceededMaximum` | `:2715` `if (buildPreview2.desc.isFieldGenerator)` → `:2748` `else if (num3 >= 80)`, and again `:2782` | Planetary Shield Generator, 2107x — the 80 is its per-planet cap |
| 42 | `FieldGeneratorTooClose` | `:2715` `if (buildPreview2.desc.isFieldGenerator)` → `:2743-2745` `num48 < num47` with `num47 = 1296f` (36 world units) | Planetary Shield Generator |
| 43 | `BattleBaseTooClose` | `:2791` `if (buildPreview2.desc.isBattleBase)` → `:2814-2816` `num60 < num59` with `num59 = 100f` (10 world units) | Battlefield Analysis Base, 3009 |
| 53 | `BlueprintNeedAddonTheCorrectPosition` | `:3391` `if (buildPreview2.desc.isDispenser)` → `:3416-3418` | Logistics Distributor, 2107 |

*Depends on:* the emit set in the table at the top. The day we emit a Wind
Turbine, a logistics station, a turret, a shield generator, a distributor, or any
miner, the corresponding row here becomes live.

### E. Guarded by `desc.isCollectStation` — 2

| # | condition | setter |
|---|---|---|
| 38 | `BuildInEquator` | `:2708-2711` `float y2 = cursorTarget.y; if (y2 > 0.1f \|\| y2 < -0.1f)` |
| 39 | `NotEnoughEnergyToWorkCollection` | `:2698-2705` `num46 = 1.0 - workEnergyPerTick / (stationCollectSpeed * planet.gasTotalHeat / 60)` |
| — | (`OutOfReach`'s second setter, `:2688-2692`, shares the guard; the row itself is IMPLEMENTED on its first setter) |

All three sit under `BuildTool_BlueprintPaste.cs:2688` / `:2695` / `:2707`,
whose guard is
`buildPreview2.desc.isCollectStation` — the **Orbital Collector, 2105**. It is
one of the five machines the mining flag cuts, so it can never reach a layout,
and it is listed separately from group D because the three conditions share one
guard and one building.

*Depends on:* `orbital-collector` staying mining-flagged in FactorioLab's dataset.

### F. Structurally impossible for a blueprint we write — 6

| # | condition | argument |
|---|---|---|
| 0 | `Ok` | The success value. `AddErrorMessage` returns early for it, `:4816`. |
| 1 | `Failure` | Two setters. `:1133-1135` `if (planet != null && planet.gasItems != null && planet.gasItems.Length != 0)` — **no blueprint at all pastes on a gas giant**, so this is not a property of what we emit. `:1856-1858` `if (lpos.sqrMagnitude < 1f)` — a preview at the planet centre; ours are at `realRadius + 0.2 + z·4/3`, i.e. `>= 200.2`. |
| 47 | `BlueprintNotAlignTropicAnchor` | `BlueprintUtils.cs:2557-2560` `float num11 = startLng / longitudeRadPerGrid3; if (Mathf.Abs(Mathf.RoundToInt(num11) - num11) > 0.01f)`. It is inside the loop at `:2513-2572`, which runs **only over secondary areas** and is skipped entirely when `_dotsCursor > 1` or when there is one area. `codec._area_for` writes exactly one `BlueprintArea`, `index = 0, parent_index = -1`, so the loop body never executes. |
| 48 | `BlueprintWrongTropicRatio` | `BlueprintUtils.cs:2564-2566`, the same secondary-area loop, same argument. |
| 100 | `MayBeBuried` | `BuildTool_BlueprintPaste.cs:3505-3509`, inside the `desc.isInserter` block (`:3429` `continue`s otherwise): `float num137 = planet.realRadius - 0.1f; ... if ((lpos + lrot * Vector3.up).sqrMagnitude < num137 && (lpos2 + lrot2 * Vector3.up).sqrMagnitude < num137)`. Both sorter ends must be a metre below the surface. Our sorters' ends are the poses of a machine (`z = 0` by `geom.machine_ground`) and a belt (`z >= 0` by `geom.altitude_range`), so both are at or above `realRadius + 0.2`. `planet.py:880` already records that this one is not ported and why. |
| 201 | `ConnWithErrorBuilding` | `:3998`, `:4012`, `:4022` all require a **neighbour already in error**: `if (buildPreview15.condition == EBuildCondition.Ok && condition2 != EBuildCondition.Ok && ...)`. It has no predicate of its own, so it cannot be a first refusal; closing every other row closes this one. |

*Depends on:* `codec._area_for` continuing to write a single area (rows 47, 48);
`geom.machine_ground` and `geom.altitude_range` continuing to hold (row 100).

### G. A property of the player's save that our blueprint cannot carry — 1

| # | condition | argument |
|---|---|---|
| 202 | `BlueprintReformNeedTech` | `:1126-1128` `if (base.actionBuild.history.bpReformLimit < blueprint.reformData.reformCount)`. `dsp/codec.py:31` pins the payload version to 1, "which avoids the trailing patch/terrain-reform block entirely", and `records.BlueprintHeader.has_reform_data` defaults to 0. `reformCount` is therefore always 0 and `bpReformLimit >= 0` always holds. |

Note that its sibling `BlueprintNeedTech` is **not** here: that one compares
against `blueprint.buildings.Length`, which very much is a property of what we
emit. See MISSING #3.

---

## What this audit did not settle

* **No row is OPEN.** Every INAPPLICABLE claim above rests either on a guard flag
  no emitted building carries, on a tool the paste does not run, or on an
  invariant of ours with a named check behind it.
* The `desc.*` flags in group D are argued from the guard plus the DSP building
  that carries the flag, **not** from a dump of `PrefabDesc` (extracting one needs
  UnityPy against the game install and was not run here). Where the vendored
  `dsp/data/buildings.json` *does* carry the flag — `power.node` for
  `PowerTooClose`, `addonType` for `NeedAddonStorage`, `stackHeight` for
  `OutOfVerticalConstructionHeight` — it was used, and it is cited.
* The `TooSkew` spray-coater trigger is a conjunction the corpus does not
  exhibit. It is recorded as MISSING with both halves shown to be reachable and
  observed two band-rungs apart, not as a demonstrated failure.
* **The MISSING rows were not implemented here, by instruction.** `PowerTooClose`
  is in flight with another agent; the other four are handoffs, each with its
  citation, its threshold and units, the buildings of ours that trigger it, and
  whether it wants a validator check, a layout constraint, or both. Nothing under
  `src/` was touched by this audit.
