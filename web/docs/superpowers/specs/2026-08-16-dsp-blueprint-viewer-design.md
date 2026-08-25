# DSP Blueprint Viewer — Design

**Date:** 2026-08-16
**Status:** Approved design, ready for implementation planning

## Goal

A local web app that renders Dyson Sphere Program factory blueprints as they appear
in-game. Paste a `BLUEPRINT:` string, drop a `.txt`, or give it a URL, and get an
interactive 3D view plus per-building detail and a bill of materials.

## Scope

**In:** factory blueprints (`BLUEPRINT:` strings), recipe/filter overlays, click-for-detail,
bill of materials, load from paste/file/URL.

**Out:** Dyson sphere blueprints (`DYBP:` strings — a different data model and a spherical
renderer, roughly doubling the project). Detected and rejected with a clear message.

**Out:** editing. The format work below is written so that adding an exporter later is
tractable, but nothing in v1 mutates a blueprint.

## Key decisions

### Rendering: 2.5D/3D, not top-down

Belts carry an altitude in `localOffset_z`, and stacked or crossing belts at different
heights are common. Fixture data confirms this directly — measured belt z-values include
`[0.0, 0.5, 1.0]` and `[0.01, 0.02, 0.5, 1.0, 1.02]`, with building z up to 33.0. A flat
top-down projection would render those as an unreadable overlap, so a flat schematic is
ruled out.

Buildings occupy an axis-aligned volume on a 3D grid, so a **prism at the true footprint
and height carries all the real information**. Shaped per-building meshes would be
cosmetic only and would need ~100 hand-authored models, so they are not worth it.

Camera is orthographic, opening at the game's blueprint tilt, with 90° rotation steps and
a toggle to unlock free orbit so a tall station can't permanently hide a belt behind it.

The planet surface is treated as **flat**. Blueprints span few enough grid segments that
curvature is visually irrelevant, and flat keeps the layout math simple and testable.

### Stack

- **bun** — package manager and script runner
- **rsbuild 2.1** + `@rsbuild/plugin-react` with `reactCompiler: true`
  (maps to `tools.swc.jsc.transform.reactCompiler`; Rspack's builtin SWC loader, no Babel)
- **React 19.2**, **@react-three/fiber 9.7**, **@react-three/drei 10.7**, **three 0.185**
- **rstest 0.11** + `@testing-library/react` + `happy-dom`
- **biome 2.5** for formatting and general lint
- **ESLint** alongside biome, carrying *only* the `react-hooks` rules — biome does not yet
  implement the React Compiler-mode hooks rules
- **zod 4.4** at trust boundaries (see below)

R3F 9.7 peers `react >=19 <19.3`; React 19.2.8 satisfies it.

## Architecture

Layering is strictly one-way:

```
format/     pure TS. no React, no three.js.
            md5f · envelope · reader · blueprint · params/*
            → parseBlueprint(string): Blueprint

model/      pure TS domain layer. no React, no three.js.
            catalog · layout · bom
            → buildSceneModel(bp): SceneModel   → computeBom(bp): Bom

state/      React only. no three.js.
            BlueprintProvider · useBlueprintSource

scene/      R3F only, consumes model/. no DOM UI.
            BlueprintCanvas · CameraRig · BuildingInstances
            IconInstances · BeltChevrons · GroundGrid

ui/         DOM panels. no three.js.
            App · Toolbar · InputPanel · InfoPanel · BomPanel
```

**Invariant: `format/` and `model/` never import React or three.js.** This is what makes
the parser and layout math testable as plain functions with no renderer, and what lets a
later feature (editing, a second renderer, a CLI) reuse them untouched.

### Instancing

Dense blueprints reach thousands of buildings (largest fixture: 3,974). drei's
`<Instances>`/`<Instance>` creates one React element per instance, which is the wrong
shape at that count.

Instead `BuildingInstances` is a single component taking `SceneModel` as a prop, writing
matrices and colours into `InstancedMesh` buffers in a `useLayoutEffect` and setting
`instanceMatrix.needsUpdate`. Declarative at the boundary, imperative inside where
three.js wants it. Safe because `SceneModel` is a pure derived value.

Icons are a second instanced quad mesh using a texture atlas with per-instance UV offsets.
Picking is a raycast against the instanced mesh, mapping `instanceId → building index`.

### React Compiler

Derivations are written plainly (`const sceneModel = buildSceneModel(blueprint)`) and the
compiler memoizes them, rather than hand-rolled `useMemo`. This is only sound because
`format/` and `model/` are pure and never mutate inputs. Derived state is computed during
render, never synced into state via an effect.

### zod placement

Deliberately at trust boundaries only, not blanket:

**Yes:**
- **Generated asset JSON** (`buildings/items/recipes/icons`). These come from a scraper
  pointed at upstream repos that can change shape without warning. Schemas make
  `extract-assets` fail at generation time with an exact path, instead of the app silently
  rendering every building as a 1×1×1 grey cube. `z.infer` is then the single source of
  truth for those types.
- **The envelope header** — CSV fields arriving as strings from a pasted blob, needing
  coercion.
- **`/api/fetch` proxy responses** and anything persisted to localStorage.

**Schema defined but not run in the hot path:** `BlueprintSchema` / `BuildingSchema`
document the format and give an executable invariant, run in tests and behind a dev flag.
Binary reads produce numbers by construction, so validating a struct we just assembled
field-by-field can only catch bugs in our own reader — never bad input — and at 10k+
buildings that is real per-parse cost for something tests already cover.

**No:** `SceneModel`, instance buffers, internal derived values.

**Cannot be zod's job, so it stays explicit in the reader:** buffer-bounds checks on every
read, `areaCount <= 64`, `buildingCount <= 1048576`, and `primaryAreaIdx` range. These are
stream-position-dependent; a post-hoc schema check happens too late to stop a malformed
length from allocating a gigabyte. The game itself enforces exactly these bounds and
throws `"Corrupt Data"`.

## Blueprint format

Verified against the game's own `Assembly-CSharp.dll` (`BlueprintData.Import`,
`BlueprintBuilding.Import`, `BlueprintArea.Import`, `BPReformData.Import`) and against 10
real blueprints spanning game versions 0.8.19 through 0.10.34.

This matters: **no public reference implementation handles the current format.**
`Wesmania/dspbp` (MIT) asserts the first header field is `0`; `huww98/dsp_blueprint_editor`
and `LRFalk01/DSP-Blueprint-Parser` (MIT) both fail on the same three 0.10.34 fixtures.
The DLL is the source of truth.

### Envelope

```
BLUEPRINT:<hdrVer>,<layout>,<i0>,<i1>,<i2>,<i3>,<i4>,0,<ticks>,<gameVersion>,<shortDesc>[,...]"<base64 gzip>"<MD5F>
```

The CSV field count depends on the leading header version:

| hdrVer | fields | layout |
|--------|--------|--------|
| 0 | 12 | `…,[10] shortDesc, [11] description` |
| 1 | 15 | `…,[10] shortDesc, [11] author, [12] customVersion, [13] attributes (`;`-separated), [14] description` |

Text fields are URL-encoded. `ticks` is .NET ticks (1e7/sec, epoch offset 62135596800s).
The hash covers everything up to but **not including** the closing quote.

MD5F is a DSP-specific MD5 variant (different init constants). Checksum mismatch is a
**non-fatal warning with a UI badge** — some third-party tools emit valid-but-unhashed
strings, and refusing to render those is worse than rendering with a caveat.

### Payload (gunzipped)

```
i32   version
i32   cursorOffset_x, cursorOffset_y
i32   cursorTargetArea
i32   dragBoxSize_x, dragBoxSize_y
i32   primaryAreaIdx
u8    areaCount                      // <= 64, else "Corrupt Data"
      BlueprintArea × areaCount
i32   buildingCount                  // <= 1048576, else "Corrupt Data"
      BlueprintBuilding × buildingCount
if version >= 2:
  i32 patch
  u8  hasReformData
  if hasReformData != 0: BPReformData
```

`BlueprintArea` (14 bytes): `i8 index, i8 parentIndex, i16 tropicAnchor, i16 areaSegments,
i16 anchorLocalOffsetX, i16 anchorLocalOffsetY, i16 width, i16 height`.

Trailing bytes after the reform flag are **ignored**, matching the game — its
`BinaryReader` simply stops. Two 0.10.34 fixtures carry 5 such bytes.

### Building — per-record path dispatch

Each record begins with `i32 num`. This is the crux, and the reason older parsers break:

- `num <= -102` → layout A, **with** trailing `content` string
- `num <= -101` → layout A, **without** `content`
- `num <= -100` → layout B, **with** `tilt`
- otherwise → layout B without `tilt`, and **`num` itself is the building index**

That last branch is why pre-0.10.34 blueprints parse fine with a naive reader: their first
i32 is a small non-negative index.

**Layout A** (`-102` / `-101`):
```
i32  index
i16  itemId
i16  modelIndex
i8   areaIndex
f32  localOffset_x, _y, _z
f32  yaw
     if 2000 < itemId < 2010  (belts):
        f32 tilt                       // offset2 := offset, yaw2 := yaw, tilt2 := tilt
     else if 2010 < itemId < 2020  (sorters):
        f32 tilt, pitch, localOffset_x2, _y2, _z2, yaw2, tilt2, pitch2
     else:
        (nothing; offset2 := offset, yaw2 := yaw)
i32  tempOutputObjIdx, tempInputObjIdx
i8   outputToSlot, inputFromSlot, outputFromSlot, inputToSlot, outputOffset, inputOffset
i16  recipeId, filterId
i16  parameterCount
i32  parameters[parameterCount]
if num <= -102:
  i32 contentLength
  if contentLength > 0: <LEB128-prefixed UTF-8 string>
```

The `content` encoding is C#'s `w.Write(text.Length); w.Write(text)` — a redundant char
count followed by `BinaryWriter`'s own length-prefixed UTF-8.

**Layout B** (`-100` / default):
```
i32  index            (or reuse num for the default branch)
i8   areaIndex
f32  localOffset_x, _y, _z
f32  localOffset_x2, _y2, _z2
f32  yaw, yaw2
f32  tilt             // only when num <= -100
i16  itemId, modelIndex
i32  tempOutputObjIdx, tempInputObjIdx
i8   × 6 slot fields
i16  recipeId, filterId
i16  parameterCount
i32  parameters[parameterCount]
```

**The sorter branch matters for rendering.** Sorters draw as a span between two endpoints,
so `localOffset_x2/_y2/_z2` must be read at the right position within those 8 floats. The
DLL confirms the order above.

### Geometry

Each building becomes one box instance: dimensions from a `modelIndex → box` table,
recentred by that entry's offset, translated to `localOffset`, rotated by `yaw`. Area
`anchorLocalOffset` places multi-area blueprints relative to each other (fixtures reach 23
areas).

Belts are one building per tile, chained via `tempOutputObjIdx`. Rendering each tile as its
own prism at its own z makes stacking and crossings correct for free, with no
special-casing. Flow direction comes from the vector to the output tile, drawn as a chevron.

## Assets — `bun run extract-assets`

**Derived from the user's own game install. No scraping.** This replaces an earlier design
that scraped community repos, which was the single worst fragility in the project.

Source: `DSPGAME_Data/` (`resources.assets`, `sharedassets0.assets`, `Managed/`).
Extractor is a Python script run via `uv`, using UnityPy 1.25 plus `TypeTreeGeneratorAPI`.
MonoBehaviour typetrees are **not** serialized in the release build, so they are generated
from the `Managed/` assemblies at extraction time — `Assembly-CSharp.dll` alone is
insufficient, as it cannot resolve `netstandard` / `UnityEngine.CoreModule`.

Outputs into a gitignored `public/assets/`:

| Output | Source | Verified |
|---|---|---|
| `modelIndex → {selectSize, selectCenter}` | `SlotConfig` MonoBehaviour on each building prefab, joined to `ModelProtoSet.PrefabPath` by prefab name | 62/63 buildable items |
| `itemId → {name, iconPath, gridIndex, modelIndex, canBuild}` | `ItemProtoSet.dataArray` | 174 items |
| `recipeId → {items, itemCounts, results, resultCounts, timeSpend}` | `RecipeProtoSet.dataArray` | 161 recipes |
| icon PNGs → atlas + UV map | `Texture2D`/`Sprite` matched on `IconPath` basename | 188/188 |

The one item without a box is itemId 1131 (地基, terrain foundation), `ModelIndex 0` — the
reform tool, not a placed building. Correctly has no `SlotConfig`.

**This is more accurate than the community table**, not merely better-licensed. Spot-check:
model 38 (`splitter-a`) agrees at `size [2.7, 2.4, 2.7] / center [0, 1.2, 0]`, but model 39
(`splitter-b`) is `size [2.0, 2.94, 2.7] / center [0, 1.47, 0]` in the game versus
`[1.5, 2.4, 2.7] / [0, 1.2, 0]` in the community table. The community values are wrong.

### `selectSize` is a click box, not a silhouette

`SlotConfig.selectSize` is the game's *selection* volume, which is deliberately generous.
Belts come out at `[1.0, 0.5, 1.0]`, but belts stack at 0.5 z-intervals — so drawing raw
`selectSize` makes vertically adjacent belts touch exactly, destroying the stacking
readability that motivated the 2.5D renderer in the first place.

So the renderer applies a **per-category visual scale** to `selectSize`, with belts scaled
down hard on the vertical axis (the community table's `0.12` is a reasonable target). This
is a rendering tuning knob layered over authoritative data, and it belongs in `model/`
where it is testable — not baked into the extractor.

### Localization

Proto `Name` fields are Chinese. English comes from the game's `Locale/` folder, which sits
on disk in the game root next to `DSPGAME.exe` — `Localization.Load` does `Directory.Exists`
on a real path, so it is **not** inside the asset files (`resources.assets` has no
`StringProtoSet` and no locale `TextAsset`s).

Format: UTF-16LE, tab-separated, one folder per LCID (`1033` = English US), with `Names/`
holding the keys. Column 0 is the key matching `ItemProto.Name`; column 3 is the
translation. Files are line-aligned across locales, but keying on column 0 is more robust
than relying on line order.

Merging all of `Locale/1033/*.txt` yields 6,229 entries and covers **174/174 items and
161/161 recipes**. Switching languages later is just a different LCID folder.

## UI

- **Input** — paste box, `.txt` drop target, URL field. URL loading goes through
  `/api/fetch?url=` on the dev server (rsbuild `server.proxy`) and a small bun server in
  production, because sharing sites send no CORS headers.
- **Info panel** — click a building for name, ids, position, yaw, recipe, and the decoded
  parameter block (station slots, splitter priorities, sorter filter, monitor settings).
- **BOM panel** — building counts by type, plus raw-ore cost by recursively expanding
  recipes. **Several items have multiple recipes, so raw cost assumes the default recipe
  per item**; the panel states this rather than presenting one authoritative number.
- **Overlays** — recipe icon on each producer, filter icon on each sorter.

## Testing

TDD throughout. rstest.

- **`format/`, `model/`** — node-environment unit tests, where the real coverage lives:
  MD5F known-answer, parse fixtures, layout transforms, BOM totals.
- **Parser regression** — every fixture in `tests/fixtures/` asserts **exact buffer
  consumption** through the reform flag. This is the assertion that catches a wrong field
  mapping, and is how the sorter float-count error was found during design.
- **`ui/`** — testing-library + happy-dom.
- **`scene/`** — kept deliberately thin; happy-dom has no WebGL context, so anything worth
  asserting is pushed down into `model/`. A design constraint that improves the layering.

### Fixtures

11 committed in `tests/fixtures/`, chosen for coverage, not convenience:

| Fixture | Exercises |
|---|---|
| `factory-quick-start-step-1…` | smallest case, 36 buildings |
| `factory-quick-start-step-3-red-cube` | belt altitudes `[0, 0.01, 0.5, 1.0]` |
| `12-s-purple-science…` | payload v0, 3,678 buildings, z up to 33 |
| `falk-v7-mall-full` | 1,993 buildings, many distinct recipes |
| `temple-of-effectiveness-polar-hub…` | 7 areas |
| `tillable-blackbox-module-polar…` | 5 areas, stacked belts |
| `new-planet-establishment-polar…` | 5 areas, only 5 buildings |
| `factory-heretical-smelter-block` | **v2**, `content` strings, ILS with 2048 params |
| `factory-endgame-distribution-hub` | **v2**, 9 areas, heavy station config |
| `factory-full-planet-wind-ready-for-solar` | **v2**, 23 areas, 3,974 buildings (perf) |
| `dyson-sphere-iridescent` | `DYBP:` — must be **rejected** cleanly |

## Scripts

`bun run dev` · `build` · `serve` · `test` · `extract-assets`

## Risks

1. **`-100`/`-101` paths are unexercised** by any fixture — implemented from the DLL but
   untested against real data. Low risk (they are strict subsets of layouts already
   covered) but worth noting.
2. **Extraction depends on a local game install.** The extractor needs `DSPGAME_Data/`
   present; it is a one-time step whose output is cached in `public/assets/`. Contributors without
   the game cannot regenerate, though they can run the app from an existing `public/assets/`.
   Acceptable for a personal tool.
3. **Extraction is version-coupled.** Field names and prefab names could shift in a future
   game patch. Mitigated by zod schemas on the extractor output, which fail loudly with an
   exact path rather than silently producing grey 1×1×1 cubes.

*(Resolved during design: the asset-scraper fragility, the unlicensed box table, and the
missing English names are all gone — everything is derived from the user's own install.)*

## Pipeline validated end-to-end

Before writing any application code, the full chain — parse → item lookup → localization →
box lookup — was run against the fixtures. All three payload generations produce correct,
self-evidently sane inventories:

| Fixture | Payload | Result |
|---|---|---|
| `factory-heretical-smelter-block` | v2 | 100 Negentropy Smelters, 283 belts, 200 sorters, 1 ILS |
| `factory-full-planet-wind-ready-for-solar` | v2, 23 areas | 3,655 Wind Turbines, 319 Solar Panels |
| `12-s-purple-science…` | v0 | 192 Assembling Machine Mk.III, 120 Matrix Labs, 2,640 belts |
| `falk-v7-mall-full` | v1 | 51 Assembling Machine Mk.I, 30 Depot Mk.I, 1,714 belts |

The blueprint titles match their contents, which is the strongest available end-to-end
check short of rendering.
