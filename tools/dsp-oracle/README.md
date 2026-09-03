# flab2bp build-condition oracle

A BepInEx plugin for Dyson Sphere Program that writes down **the game's own
build-condition verdicts** for a blueprint on the cursor, so they can be diffed
against what our Python port predicts.

Its whole value is that it reimplements no game rule. It reads
`BuildPreview.condition` after the game set it, reads the live references,
objIds and slots after the game chose them, and records the exact PhysX query
arguments/results plus the game's own `PlanetPhysics.GetColliderData`. The
automatic diagnostic uses blueprint-local coordinates only to identify the
requested four-belt cluster and attribute its queries; it never computes or
changes a condition.

## Requirements

- **BepInEx 5.4.17** (what DSP is pinned to). The plugin is compiled against
  exactly that version's reference assemblies, so the emitted assembly
  references are `BepInEx 5.4.17.0` and `0Harmony 2.5.5.0` — the DLLs that are
  actually on disk, not a higher version Mono would have to satisfy.
- Dyson Sphere Program, already running BepInEx (`winhttp.dll` +
  `doorstop_config.ini` in the game root pointing at
  `BepInEx\core\BepInEx.Preloader.dll`).

## Install

The zip is a Thunderstore package, so **r2modman** installs it directly:

> Settings → Import local mod → pick `flab2bp_oracle-1.2.0.zip`

r2modman reads `manifest.json` from the archive root and drops `FlabOracle.dll`
into the profile's `BepInEx/plugins/`. Nothing else to do; it appears in the mod
list as `flab2bp_oracle` and its toggle works like any other mod's.

The manifest declares `xiaoye97-BepInEx-5.4.17`. A local import does **not**
resolve dependencies, so BepInEx must already be in the profile — which it will
be if any other mod is installed there.

<details>
<summary>Manual install, if you are not using a mod manager</summary>

```sh
mkdir -p "$HOME/Dyson Sphere Program/BepInEx/plugins/flab2bp-oracle"
unzip -oj /path/to/flab2bp_oracle-1.2.0.zip FlabOracle.dll \
  -d "$HOME/Dyson Sphere Program/BepInEx/plugins/flab2bp-oracle"
```

`-j` matters: the package is flat, and without it the DLL keeps no useful path.
</details>

Start the game; the BepInEx console should show:

```
[Info   : flab2bp build-condition oracle] Patched BuildTool_BlueprintPaste timeline (DeterminePreviewsPrestage, CheckBuildConditionsPrestage, ArrangeOverlapBP, ActiveColliders, CheckBuildConditions, AddErrorMessage, MatchInserter, CreatePrebuilds).
[Info   : flab2bp build-condition oracle] Patched Physics.OverlapSphereNonAlloc.
[Info   : flab2bp build-condition oracle] Patched Physics.OverlapCapsuleNonAlloc.
[Message: flab2bp build-condition oracle] flab2bp oracle ready. Dump key = F9, output = .../BepInEx/flab2bp-oracle
```

To uninstall, disable or delete it in r2modman (or delete
`BepInEx/plugins/flab2bp-oracle/` for a manual install).

## Triggering a dump

**Hover dump (does not build anything).** Paste a blueprint so the preview is
following the cursor, position it, and press **F9**. The plugin arms itself and
dumps on the next `CheckBuildConditions` pass — the moment at which every
preview's `condition` is the game's finished verdict for that cursor position.
The console prints the full path of the file it wrote.

If the key is pressed while no blueprint is on the cursor, `CheckBuildConditions`
never runs; after 180 frames the plugin says so in the console and nothing is
written. It never dumps a guess.

**Paste dump (automatic).** When a paste is actually committed, `CreatePrebuilds`
produces two records: `createprebuilds-pre` (the verdicts as they stood going in)
and `createprebuilds-post` (after the commit, so `objId` is populated). Turn this
off with `DumpOnPaste = false`.

**Canonical model40 belt capture (automatic, no keypress and no successful
build required).** Import `corrected.txt` and put its preview on the cursor. A
semantic match requires the 75x36/160-band area and both yaw-90 model40
splitters: the y2 control at local `(45,2,0)` and the y6 suspect at `(45,6,0)`,
including each splitter's four attached z1 feed/draw belts. The plugin retains
only condition/pointer state changes and matching Physics queries.

It writes one `model40-belt-capture-YYYYMMDD-HHMMSS-fff.json` from the
`CheckBuildConditions` postfix, after the game's collision rescue and condition
propagation are complete, whether that method returns true or false. A false
`CheckBuildConditionsPrestage`, a stable non-Ok target, and a 1,800-frame window
remain bounded fallbacks if the full check is not reached. The same loaded
blueprint object is deduplicated after the file is written.

The target file keeps the y2 and y6 groups as controls, then enumerates **every**
active non-Ok `bpPool` preview in `nonOkPreviews`; this array is decisive when
the failing records are outside those controls. Each entry maps back to the
canonical blueprint slot/index (using the positive `bpgpuiModelId`, or the
game's active-pool order after overlap handling clears that id), and includes
item/model/descriptor flags, blueprint-local pose, world preview poses,
condition, connection fields, input/output/`coverbp` identities and conditions,
all `AddErrorMessage` arguments, and nearby captured Physics queries.

Control timeline snapshots still include both splitters and all eight adjacent
belts. Root-level prestage, tool-stage, raw grat-box, patch-applied, query
truncation, and target-active-hook-fired metadata distinguish an unavailable
wrapper from a real zero-collider result. The capture is independent of
`DumpOnPaste`; disabling the generic two-file paste dump does not disable this
one-shot diagnostic.

**Stacking facts (hotkey, no blueprint needed).** Press **F10** to write one
`stacking-facts-YYYYMMDD-HHMMSS-fff.json`: the sorter cargo-stacking research
table, the sorter and piler prefab fields, and the Automatic Piler's behaviour.
Load a save first — out of a save the research and live-component halves come
back `null` and only the type-level facts are written. Unlike the hover dump this
one needs no armed pass: every fact is already in `LDB`, in `GameMain.history`,
or on a live component, so it is served on the spot.

Generic files are `BepInEx/flab2bp-oracle/dump-00001.json`,
`dump-00002.json`, … The counter continues from the highest number already in
the directory. Target captures use the separate timestamped
`model40-belt-capture-*.json` pattern, and stacking facts the
`stacking-facts-*.json` one.

## Configuration

`BepInEx/config/org.dberlin.flab2bp.oracle.cfg`, written on first run.

| Section | Key | Default | Meaning |
| --- | --- | --- | --- |
| Trigger | `DumpKey` | `F9` | Dumps the current preview set without building. |
| Trigger | `StackingFactsKey` | `F10` | Dumps the sorter cargo-stacking and Automatic Piler facts. Needs no blueprint on the cursor. |
| Trigger | `DumpOnPaste` | `true` | Also dump on `CreatePrebuilds` (pre and post). |
| Capture | `AlwaysCaptureColliderDetail` | `false` | Identify every overlap collider on **every** frame, not just the armed one. Makes the paste dump carry snap-candidate detail too, at the cost of frame time while a blueprint is on the cursor. |
| Capture | `PatchPhysicsOverlap` | `true` | Hook the exact managed `Physics.OverlapSphereNonAlloc` and `OverlapCapsuleNonAlloc` overloads used by the belt checks. Hooks are process-wide but target capture returns immediately outside the active semantic match. |
| Output | `OutputDirectory` | *(empty)* | Empty means `<BepInEx>/flab2bp-oracle`. |

## What is in a dump

See [`sample-dump.json`](sample-dump.json) for a complete, real example
(generated by the `SerializerCheck` harness from synthetic previews, so the
values are fictional but the shape is exact).

### Header

| Field | Meaning |
| --- | --- |
| `schema` | `"flab2bp-oracle/1"` |
| `trigger` | `hotkey`, `createprebuilds-pre`, or `createprebuilds-post` |
| `utcTime`, `unityFrame`, `toolFrame` | when |
| `checkBuildConditionsResult` | the `bool` `CheckBuildConditions()` returned; `null` for the two paste triggers |
| `colliderDetailRequested` | whether this pass asked for collider identities |
| `overlapPatchApplied` | whether the `Physics.OverlapSphereNonAlloc` hook installed |
| `overlapHookEverFired` | whether it has ever actually been observed firing (see *Known limits*) |
| `planetId`, `blueprintPath`, `pasteResult`, `cursorValid`, `yaw`, `anchorType` | tool state |
| `bpCursor`, `previewCount` | `previews` covers `bpPool[0 .. previewCount)` |
| `conditionCounts` | `"<Name> (<value>)"` → count, over all previews |
| `prefabs` | itemId → prefab data, including `slotPoses` and `portPoses` at full precision |

### Each entry of `previews`

`index`, `objId`, `previewIndex`, `itemId` / `itemName` / `itemNameKey`, the
`desc*` flags, then:

- `condition` — the **numeric** `EBuildCondition` value
- `conditionName` — its enum name (`Ok`, `ErrorInserterData`, …), or
  `Unknown(<n>)` if the game ever produces a value not in the enum
- `conditionText` — the game's localized message, or `null` if it could not be resolved
- `inputObjId`, `inputFromSlot`, `inputToSlot`, `inputOffset` and the four
  `output*` equivalents
- `hasInput` / `hasOutput` — whether the `BuildPreview.input` / `.output`
  references are non-null; `inputPreviewIndex` / `outputPreviewIndex` give the
  index in this same array when the referent is one of these previews
- `lpos`, `lpos2` as `[x, y, z]` and `lrot`, `lrot2` as `[x, y, z, w]`, every
  component formatted `G9` — the shortest form that round-trips a `float`
  exactly. **Nothing is rounded.** Non-finite values appear as the strings
  `"NaN"` / `"Infinity"` / `"-Infinity"` rather than as invalid JSON numbers.
- `tilt`, `recipeId`, `filterId`, `paramCount`, `parameters`, `coverObjId`,
  `willRemoveCover`, `willReconstructCover`, `addonObjId`, `addonAreaIdx`,
  `isConnNode`, `needModel`, `bpgpuiModelId`, `genNearColliderArea2`, `content`
- `inputTarget` / `outputTarget` — the objId resolved through the game's pools.
  `null` when the objId is 0. Positive objIds are `kind: "entity"` and look up
  `factory.entityPool`; negative ones are `kind: "prebuild"` and look up
  `factory.prebuildPool[-objId]`. `resolved: false` means the id was outside the
  live cursor range and nothing was invented in its place.

### `matchInserter`

`null` when `MatchInserter` has never run for that preview. Otherwise:

- `frame` — the Unity frame the observation is from
- `framesStale` — `unityFrame - frame`. **0 means the record is from this exact
  dump's frame.** All four `CreatePrebuilds()` call sites in the game run
  `CheckBuildConditions()` immediately before, in the same frame, so
  `createprebuilds-*` dumps normally show 0 as well. If a value is ever non-zero,
  the record is older than the dump and the field says so rather than hiding it.
- The record table is keyed by `BuildPreview` identity and is dropped whenever
  the game replaces `bpPool` (closing the paste tool does this). A preview that
  has not been re-matched since then reports `matchInserter: null`, never stale
  data from a different blueprint.
- `colliderDetailCaptured` — whether collider identities were recorded that frame
- `callCount` / `calls` — `CheckBuildConditions` calls `MatchInserter` up to
  twice per preview per pass (once with the input side cleared, once with the
  output side cleared) and again later in the pass for multi-level previews. Each
  call is recorded separately; none is overwritten.

Each call has `before` and `after` snapshots of the same connection fields plus
`lpos`/`lpos2`/`lrot`/`lrot2` and the condition, and `overlapQueries`:

- `center`, `radius`, `layerMask` — the arguments the game passed to
  `Physics.OverlapSphereNonAlloc` (the ladder uses radius `0.8`, layer mask
  `393216`)
- `colliderCount` — **the engine's return value**: how many candidates PhysX
  handed the snap ladder
- `colliders` — `null` when detail was not captured; otherwise one entry per
  candidate in the order PhysX returned them, with `name`, `gameObjectLayer`,
  `hasColliderData`, and — when the game's `GetColliderData` recognises it —
  `objId`, `objType`, `usage`, `shape`, `link`, `pos`, `ext`, `radius`, `rot`.

`objId` here follows the game's own convention inside `MatchInserter`:
`EObjectType.None` yields a positive entity id, `EObjectType.Prebuild` yields the
prebuild id, and the ladder negates the latter. The plugin records what
`GetColliderData` reports and does not apply that transform for you.

## What is in a stacking-facts dump

`stacking-facts-*.json`, schema `flab2bp-stacking/1`. Written by
[`StackingFacts.cs`](StackingFacts.cs).

| Key | What it holds |
| --- | --- |
| `gameVersion`, `inGame` | `GameConfig.gameVersion`; whether a save was loaded (if not, `history` and `live` are `null`). |
| `techs[]` | Every `TechProto` that touches sorter stacking, selected by the unlock-function ids `GameHistoryData.UnlockTechFunction` switches on (14 → `inserterStackCountObsolete`, 39 → `inserterStackOutput`, 40 → `inserterBidirectional`, 41 → `inserterStackInput`) or by a name mentioning stack/pile — so localisation cannot hide one. Carries `ID, Name, translatedName, Level, MaxLevel, UnlockFunctions, UnlockValues, UnlockRecipes, PropertyOverrideItems, PropertyItemCounts, PreTechs, HashNeeded` and the live `techState`. |
| `history` | `inserterStackCountObsolete`, `inserterStackInput`, `inserterStackOutput`, `inserterBidirectional`, `stationPilerLevel` — the values the research has already produced in this save. |
| `prefabDescStackFieldNames[]` | Which `PrefabDesc` fields are named for stacking, found by reflection over the type rather than named by us. |
| `items[]` | Every item whose prefab `isInserter` or `isPiler`, with `inserterGrade/STT/Delay` and the value of every stack-named `PrefabDesc` field. |
| `belts[]` | Every belt tier's `beltSpeed`, the cargo/s that implies for a piler, and the piler cooldown row that tier selects. |
| `sorter` | The component's stack-named fields; the grade rules `GameData.OnInserterTechChange` applies (grade 3 uses the obsolete count and forces `stackOutput = 1`; grade 4 uses the newer input/output research); `stackRateFactor`, and `itemsPerCargoDivisor`. |
| `piler` | The component and prefab-component field lists, `PilerState` values, the private `cacheCdTickArray` read by reflection, `stackParameterIndex` (null — the piler has no stack setting, see below), `maxOutputStack`, `outputStackFromUnstackedInput`, `singlePassToMaxStack`, and the throughput rule. |
| `live` | Every piler and sorter in the save (capped at 256 each) with its real state and stack fields, plus the largest cargo `stack` byte currently riding any belt — the empirical check on `maxOutputStack`. |

Three of those are read out of a method body rather than off a field, because the
game keeps them as IL literals. Each is written next to a `…Source` string naming
the method it was read from and a `…Observed: false` flag, so a transcriber can
see which numbers the game handed over and which were quoted:
`piler.maxOutputStack`, `sorter.itemsPerCargoDivisor` and
`sorter.stackRateFactor`. `live.maxCargoStackObserved` is the runtime
cross-check on the first of them.

The piler's `stackParameterIndex` is `null` because the setting does not exist,
not because it was not found: `CargoTraffic.RematchPilerConnection` is the only
writer of `pilerState` and derives Pile/Split/None from which connected belt is
the output side, `PilerComponent.Export`/`Import` serialise no stack setting, and
`BuildingParameters` mentions "piler" only as `StationComponent.pilerCount`.

## Known limits — read before trusting a field

These are stated because the plugin cannot be end-to-end tested outside the game.

1. **Physics observations may be absent.** Both exact managed non-alloc
   overloads are patched manually. If either overload cannot be resolved or
   detoured on a changed game build, startup logs a warning and the rest of the
   target timeline still works. Inspect `spherePatchApplied`,
   `capsulePatchApplied`, and the matching `*HookFiredWhileTargetActive` fields;
   a missing event is never silently presented as a zero-collider result.
2. **`conditionText` is best-effort.** It calls into the game's localization; if
   that throws, the field is `null` and the numeric `condition` — which is what
   matters — is still exact.
3. **The current game build has been play-verified.** The 1.1.1 target hooks
   produced an in-game capture for `corrected.txt`, including managed Physics
   results and the full condition pass. `SerializerCheck` also exercises
   two-cluster semantic matching, pool/reference identity, bounded timeline JSON,
   and strict parsing against the installed game types. A changed DSP or Unity
   build can still invalidate a Harmony target; startup logs and the
   patch/hook-fired fields make that explicit.

## Building

```sh
cd tools/dsp-oracle
./build-zip.sh          # -> dist/flab2bp_oracle-1.2.0.zip
```

Requires the .NET SDK and the game's managed assemblies (referenced by
`HintPath`, never copied into the repo). If the game is not at
`~/Dyson Sphere Program`, set `DSP_MANAGED_DIR=/path/to/DSPGAME_Data/Managed/`.

`NuGet.config` adds `https://nuget.bepinex.dev/v3/index.json`, which is where the
BepInEx reference assemblies live; they are not on nuget.org.

Target framework is **netstandard2.1**. It needs no reference-assembly package on
Linux (unlike `net472`), and it is the lowest netstandard that can reference the
game's assemblies at all — `Assembly-CSharp` and the UnityEngine modules
themselves reference netstandard 2.1, so a netstandard2.0 target is rejected with
`CS1705`.

### Serializer check

```sh
cd tools/dsp-oracle/SerializerCheck
dotnet run -c Release
```

Builds preview/prefab/entity objects out of the real game types, runs the real
serialiser over them, parses the output with a strict JSON reader and asserts
every float came back bit-for-bit. It is mutation-checked: changing the float
format from `G9` to `G7` makes it report seven round-trip failures, and dropping
a single `EndObject()` makes it report unbalanced JSON.

To regenerate `sample-dump.json`:

```sh
FLAB_ORACLE_SAMPLE_OUT=../sample-dump.json dotnet run -c Release
```

## Where the hooks are

Against the decompiled source at
`/home/dannyb/.claude/jobs/66c2051c/tmp/poseless/full/BuildTool_BlueprintPaste.cs`:

| Hook | Location | What it observes |
| --- | --- | --- |
| `DeterminePreviewsPrestage` postfix | stage-0 preview refresh | semantic arming and target state after the actually-invoked preview updater |
| `CheckBuildConditionsPrestage` postfix | line 1111; called every `_OnTick` | the stage-0 boolean gate; deduplicated transitions plus raw tech/area/grat-box evidence |
| plugin `Update` monitor | every Unity frame while semantically armed | condition/pointer tuple changes and automatic flush even when stage 1 is unreachable |
| `ArrangeOverlapBP` prefix/postfix | line 878 | target conditions/pointers before and after blueprint-overlap arrangement |
| `ActiveColliders(BuildModel)` postfix | line 1748 | target state after preview colliders are activated |
| `CheckBuildConditions` prefix/postfix | line 1778 | target state before collision rescue and after final propagation; also serves the manual hotkey dump |
| `AddErrorMessage(EBuildCondition, BuildPreview)` prefix | line 4814 | target condition at pre-rescue, post-rescue, and propagation error-report calls |
| `MatchInserter` prefix/postfix | line 1462 | the connection fields before and after each snap attempt |
| exact managed `Physics.OverlapSphereNonAlloc` / `OverlapCapsuleNonAlloc` postfixes | belt checks near lines 3749/3753 and 3829/3833 | query centres/endpoints, radius/mask/result count, and returned collider/preview-model identities |
| `CreatePrebuilds` prefix/postfix | line 4074 | generic committed set; the prefix is an additional successful-placement flush path |
