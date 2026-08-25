# Belt Icons and Connectivity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render belt icon tags (icon + number), infer and show what unconnected belt runs carry, and show belt flow direction.

**Architecture:** A new pure module `src/model/beltGraph.ts` derives belt runs by inverting the blueprint's forward-only `outputObjIdx` links, segmenting deterministically on inbound/outbound degree. `buildSceneModel` calls it and exposes `SceneModel.beltRuns`; `buildOverlays` turns runs into icon and count placements; two new instanced-mesh components draw digits and chevrons.

**Tech Stack:** TypeScript, React 19 + React Compiler, react-three-fiber 9 / three 0.185, zod/mini, rstest + happy-dom, biome + eslint, bun. Asset extraction is Python via `uv` (UnityPy + Pillow).

**Spec:** `docs/superpowers/specs/2026-08-17-belt-icons-and-connectivity-design.md`

## Global Constraints

- `src/format/`, `src/model/`, `src/server/` must import neither React nor three.js. Enforced by `tests/architecture.test.ts` — do not weaken that test.
- React Compiler is on: no hand-written `useMemo`/`useCallback` for pure derivations, no setState-in-effect for derived state.
- **No test may perform network I/O.** happy-dom resolves relative URLs against `http://localhost:3000`, which is rsbuild's own dev port, so an unmocked `fetch` silently hits the dev server. Mock `src/state/assets` in any test that renders a component which loads assets.
- Verification means reading the whole output, not the pass count. Run `bun run test 2>&1` and scan for `error`, `warn`, `abort`, `ECONNRESET`, `unhandled`, `reject` — a zero exit code with "147 passed" has previously coexisted with real stderr errors.
- Belt itemIds are 2001–2009; sorter itemIds are 2011–2019.
- Tag id bands, copied verbatim from `SignalProtoSet.IconSprite`: `<1000` signal · `<12000` item (id used directly) · `<20000` vein at `id-12000` · `<40000` recipe at `id-20000` · `<60000` tech at `id-40000` · otherwise nothing.
- `bun run lint` runs **both** biome and eslint. Both must be clean.
- Commit after every task.

---

### Task 1: Extract signal and vein icons

Adds two proto tables to the extractor so tag ids outside the item band can resolve to an atlas cell. Verified against the game install: `SignalProtoSet` has 39 entries (ids 401–802) and `VeinProtoSet` has 14 (ids 1–14); all 39 + 14 sprites are present in `resources.assets`/`sharedassets0.assets` under their `IconPath` basenames.

**Files:**
- Modify: `scripts/extract_assets.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `public/assets/tags.json` with shape `{ "signals": { "<id>": "<iconName>" }, "veins": { "<id>": "<iconName>" } }`, and atlas entries for all 53 new icon basenames.

- [ ] **Step 1: Add both proto sets to the extraction set**

In `main()`, change the `want` set (currently `{"ItemProtoSet", "ModelProtoSet", "RecipeProtoSet"}`):

```python
    want = {"ItemProtoSet", "ModelProtoSet", "RecipeProtoSet",
            "SignalProtoSet", "VeinProtoSet"}
```

- [ ] **Step 2: Include their icons in the atlas**

Find the `wanted_icons` set comprehension (it currently unions `items_raw` and `recipes_raw`) and extend it:

```python
    items_raw = protos["ItemProtoSet"]["dataArray"]
    recipes_raw = protos["RecipeProtoSet"]["dataArray"]
    signals_raw = protos["SignalProtoSet"]["dataArray"]
    veins_raw = protos["VeinProtoSet"]["dataArray"]
    wanted_icons = {
        (r.get("IconPath") or "").split("/")[-1]
        for r in list(items_raw) + list(recipes_raw) + list(signals_raw) + list(veins_raw)
        if r.get("IconPath")
    }
```

- [ ] **Step 3: Write tags.json**

Next to where `items.json` / `recipes.json` / `models.json` are written, add:

```python
    def basename(proto: dict) -> str:
        return (proto.get("IconPath") or "").split("/")[-1]

    tags = {
        "signals": {str(s["ID"]): basename(s) for s in signals_raw if basename(s)},
        "veins": {str(v["ID"]): basename(v) for v in veins_raw if basename(v)},
    }
    write(os.path.join(OUT, "tags.json"), tags)
```

- [ ] **Step 4: Assert the new tables did not silently vanish**

The extractor already asserts invariants rather than trusting joins. Add matching floors alongside the existing ones (near the `floor(len(tr), MIN_LOCALIZATION_ENTRIES, ...)` call):

```python
    floor(len(tags["signals"]), 39, "signal tag icons")
    floor(len(tags["veins"]), 14, "vein tag icons")
```

Read the existing `floor` helper first and match its signature exactly; if it takes `(actual, minimum, label)` the calls above are correct as written.

- [ ] **Step 5: Run the extractor and verify**

Run: `bun run extract-assets`

Expected: the `icons: N/M` line shows N == M (no missing textures), `public/assets/tags.json` exists with 39 signals and 14 veins. Check:

```bash
jq '{signals: (.signals|length), veins: (.veins|length)}' public/assets/tags.json
```

Expected output: `{"signals": 39, "veins": 14}`

- [ ] **Step 6: Commit**

```bash
git add scripts/extract_assets.py
git commit -m "feat(assets): extract signal and vein tag icons"
```

Note: `public/assets/` is gitignored (assets are fetched at setup, never committed), so only the script is staged.

---

### Task 2: Five-band tag id resolver

**Files:**
- Modify: `src/model/schemas.ts`
- Modify: `src/model/catalog.ts`
- Modify: `src/state/assets.ts`
- Test: `tests/model/catalog.test.ts`

**Interfaces:**
- Consumes: `tags.json` from Task 1.
- Produces: `Catalog.tagIconName(signalId: number): string | undefined`, and `RawAssets.tags?: unknown`.

`tags` is **optional** on `RawAssets` so the ten existing test files that call `buildCatalog` keep working unchanged. It is never optional in the running app: `loadCatalog` always fetches `tags.json`, and the shared `json()` helper throws when the file is missing.

- [ ] **Step 1: Write the failing test**

Add to `tests/model/catalog.test.ts`. Match the existing file's style — it builds a catalog from inline literal objects.

```ts
test('tagIconName resolves each signal id band', () => {
  const c = buildCatalog({
    items: [
      { id: 1101, name: 'Iron Ingot', iconName: 'iron-plate', gridIndex: 1,
        modelIndex: 0, canBuild: false, color: 1 },
    ],
    models: {},
    recipes: [
      { id: 16, name: 'Gear', iconName: 'gear-recipe', items: [1101],
        itemCounts: [1], results: [1201], resultCounts: [1], timeSpend: 60 },
    ],
    tags: { signals: { '401': 'signal-401' }, veins: { '2': 'coal-vein' } },
  });

  expect(c.tagIconName(401)).toBe('signal-401');      // signal band
  expect(c.tagIconName(1101)).toBe('iron-plate');     // item band, id used directly
  expect(c.tagIconName(12002)).toBe('coal-vein');     // vein band, id - 12000
  expect(c.tagIconName(20016)).toBe('gear-recipe');   // recipe band, id - 20000
  expect(c.tagIconName(40001)).toBeUndefined();       // tech band, not extracted
  expect(c.tagIconName(60000)).toBeUndefined();       // out of range
  expect(c.tagIconName(0)).toBeUndefined();           // unset
});

test('tagIconName honours the recipe icon fallback', () => {
  const c = buildCatalog({
    items: [
      { id: 1201, name: 'Gear', iconName: 'gear', gridIndex: 1,
        modelIndex: 0, canBuild: false, color: 1 },
    ],
    models: {},
    // empty iconName: must fall back to the first result's icon
    recipes: [
      { id: 16, name: 'Gear', iconName: '', items: [], itemCounts: [],
        results: [1201], resultCounts: [1], timeSpend: 60 },
    ],
    tags: { signals: {}, veins: {} },
  });
  expect(c.tagIconName(20016)).toBe('gear');
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `bunx rstest run tests/model/catalog.test.ts 2>&1`
Expected: FAIL — `tagIconName is not a function`.

- [ ] **Step 3: Add the schema**

In `src/model/schemas.ts`, after `AtlasSchema`:

```ts
export const TagsSchema = z.object({
  signals: z.record(z.string(), z.string()),
  veins: z.record(z.string(), z.string()),
});

export type Tags = z.infer<typeof TagsSchema>;
```

- [ ] **Step 4: Implement the resolver**

In `src/model/catalog.ts`:

Add `TagsSchema` and `type Tags` to the existing import from `./schemas`. Add to the `Catalog` interface, with a comment matching the file's documented style:

```ts
  /**
   * Resolves the icon for a belt tag id.
   *
   * Mirrors the game's SignalProtoSet.IconSprite, which dispatches across five
   * id ranges. Resolving fewer bands would draw a confidently *wrong* icon (a
   * vein tag read as item 12xxx), which is worse than drawing none, so every
   * band is handled even though only the item band appears in our fixtures.
   * Tech icons are not extracted and resolve to undefined.
   */
  tagIconName(signalId: number): string | undefined;
```

Add `tags?: unknown` to `RawAssets`. In `buildCatalog`, parse it with a default:

```ts
  const tags = raw.tags === undefined
    ? { signals: {}, veins: {} }
    : parse(TagsSchema, raw.tags, 'tags.json');
```

Lift the recipe-icon logic out of the returned object literal so both members can call it without `this`:

```ts
  const resolveRecipeIcon = (recipeId: number): string | undefined => {
    const r = recipeById.get(recipeId);
    if (!r) return undefined;
    if (r.iconName) return r.iconName;
    const firstResult = r.results[0];
    if (firstResult === undefined) return undefined;
    return itemById.get(firstResult)?.iconName;
  };
```

Then in the returned object replace the inline `recipeIconName` with `recipeIconName: resolveRecipeIcon,` and add:

```ts
    tagIconName(signalId) {
      if (signalId <= 0) return undefined;
      if (signalId < 1000) return tags.signals[String(signalId)];
      if (signalId < 12000) return itemById.get(signalId)?.iconName;
      if (signalId < 20000) return tags.veins[String(signalId - 12000)];
      if (signalId < 40000) return resolveRecipeIcon(signalId - 20000);
      return undefined; // techs are not extracted; see the doc comment above
    },
```

- [ ] **Step 5: Load tags.json**

In `src/state/assets.ts`, extend `loadCatalog`:

```ts
export async function loadCatalog(signal?: AbortSignal): Promise<Catalog> {
  const [items, models, recipes, tags] = await Promise.all([
    json('/assets/items.json', signal),
    json('/assets/models.json', signal),
    json('/assets/recipes.json', signal),
    json('/assets/tags.json', signal),
  ]);
  return buildCatalog({ items, models, recipes, tags });
}
```

- [ ] **Step 6: Run tests and lint**

Run: `bunx rstest run tests/model/catalog.test.ts 2>&1` — expected PASS.
Run: `bun run test 2>&1` — all suites pass, no error text anywhere in the output.
Run: `bun run lint && bun run typecheck`

- [ ] **Step 7: Commit**

```bash
git add src/model/schemas.ts src/model/catalog.ts src/state/assets.ts tests/model/catalog.test.ts
git commit -m "feat(model): five-band belt tag icon resolver"
```

---

### Task 3: Carry belt parameters into the scene model

**Files:**
- Modify: `src/model/layout.ts`
- Test: `tests/model/layout.test.ts`

**Interfaces:**
- Produces: `BuildingInstance.parameters: readonly number[]`.

- [ ] **Step 1: Write the failing test**

Add to `tests/model/layout.test.ts`, following the file's existing fixture-loading style:

```ts
test('carries belt tag parameters onto the instance', () => {
  const bp = parseBlueprint(
    readFileSync('tests/fixtures/factory-heretical-smelter-block.txt', 'utf8'),
  );
  const model = buildSceneModel(bp, catalog);
  const tagged = model.instances.filter((i) => i.parameters.length > 0);
  // 11 tagged belts, each exactly [signalId, count]
  expect(tagged.length).toBe(11);
  expect(tagged.every((i) => i.parameters.length === 2)).toBe(true);
});
```

If `tests/model/layout.test.ts` does not already import `readFileSync` and `parseBlueprint`, add those imports.

**The test file's inline catalog must first learn about Mk.III belts.**
`buildSceneModel` skips any building whose box it cannot resolve
(`catalog.model(modelIndex) ?? catalog.boxForItem(itemId)`, then `continue`).
The heretical fixture's belts are **itemId 2003, modelIndex 37**, and the
file's catalog currently has neither — item 2001/model 35 is the Mk.I belt.
Without this, all 283 belts are skipped, `instances` holds no belts at all,
and the assertion above can never pass. Add the real box to the `models` map
(taken from the game's own data — identical dimensions to model 35):

```ts
    '37': { prefab: 'belt-3', size: [1, 0.5, 1], center: [0, 0.1, 0] },
```

and the matching item to the `items` array:

```ts
    {
      id: 2003,
      name: 'Conveyor Belt Mk.III',
      iconName: 'belt-3',
      gridIndex: 6,
      modelIndex: 37,
      canBuild: true,
      color: 0xe3a263,
    },
```

Do **not** make the test load `public/assets/*.json` from disk instead. Those
files are generated by `bun run extract-assets` and are gitignored; a unit
test that reads them stops being hermetic and fails on a fresh checkout.

- [ ] **Step 2: Run it to verify it fails**

Run: `bunx rstest run tests/model/layout.test.ts 2>&1`
Expected: FAIL — `parameters` does not exist on `BuildingInstance`.

- [ ] **Step 3: Add the field**

In `src/model/layout.ts`, add to the `BuildingInstance` interface:

```ts
  parameters: readonly number[];
```

and in the loop that builds each instance, add `parameters: b.parameters,` alongside the existing `recipeId` / `filterId` assignments.

- [ ] **Step 4: Run it to verify it passes**

Run: `bunx rstest run tests/model/layout.test.ts 2>&1` — expected PASS.

- [ ] **Step 5: Commit**

```bash
git add src/model/layout.ts tests/model/layout.test.ts
git commit -m "feat(model): carry belt parameters onto BuildingInstance"
```

---

### Task 4: Belt run graph

The core of the feature. Blueprints record only the forward link — 277 of 283 belts in the heretical fixture have `inputObjIdx = -1` — so runs are derived by inverting `outputObjIdx`.

**Files:**
- Create: `src/model/beltGraph.ts`
- Test: `tests/model/beltGraph.test.ts`

**Interfaces:**
- Consumes: `Blueprint`, `BlueprintBuilding` from `../format/types`.
- Produces:
  - `isBelt(itemId: number): boolean`, `isSorter(itemId: number): boolean`
  - `interface BeltRun { belts: number[]; freeInput: boolean; freeOutput: boolean; cyclic: boolean; carried: number[]; hasExplicitTag: boolean }`
  - `buildBeltRuns(bp: Blueprint): BeltRun[]` — topology only; `carried` is `[]` here and filled in by Task 5.
  - `computeBeltHeadings(runs: BeltRun[], positions: Map<number, readonly [number, number, number]>): Map<number, number>`

- [ ] **Step 1: Write the failing tests**

Create `tests/model/beltGraph.test.ts`:

```ts
import { readFileSync } from 'node:fs';
import { expect, test } from '@rstest/core';
import { parseBlueprint } from '../../src/format/index';
import { buildBeltRuns, computeBeltHeadings } from '../../src/model/beltGraph';
import type { Blueprint, BlueprintBuilding } from '../../src/format/types';

/** Minimal belt record; only the fields the graph reads need to be real. */
function belt(index: number, outputObjIdx: number): BlueprintBuilding {
  return {
    index, areaIndex: 0, itemId: 2001, modelIndex: 35,
    x: index, y: 0, z: 0, x2: 0, y2: 0, z2: 0,
    yaw: 0, yaw2: 0, tilt: 0, tilt2: 0, pitch: 0, pitch2: 0,
    outputObjIdx, inputObjIdx: -1,
    outputToSlot: 0, inputFromSlot: 0, outputFromSlot: 0, inputToSlot: 0,
    outputOffset: 0, inputOffset: 0,
    recipeId: 0, filterId: 0, parameters: [], content: null,
  };
}

function bp(buildings: BlueprintBuilding[]): Blueprint {
  return { buildings } as unknown as Blueprint;
}

test('a simple chain is one run, free at both ends', () => {
  const runs = buildBeltRuns(bp([belt(0, 1), belt(1, 2), belt(2, -1)]));
  expect(runs.length).toBe(1);
  expect(runs[0]!.belts).toEqual([0, 1, 2]);
  expect(runs[0]!.freeInput).toBe(true);
  expect(runs[0]!.freeOutput).toBe(true);
  expect(runs[0]!.cyclic).toBe(false);
});

test('a merge splits into three runs and the shared tail is its own', () => {
  // 0 -> 2, 1 -> 2, 2 -> -1 : belt 2 has inbound degree 2
  const runs = buildBeltRuns(bp([belt(0, 2), belt(1, 2), belt(2, -1)]));
  expect(runs.length).toBe(3);
  expect(runs.map((r) => r.belts).sort()).toEqual([[0], [1], [2]]);
  // the shared tail is fed by belts, so its input is not free
  expect(runs.find((r) => r.belts[0] === 2)!.freeInput).toBe(false);
  expect(runs.find((r) => r.belts[0] === 2)!.freeOutput).toBe(true);
});

test('merge segmentation does not depend on input order', () => {
  const a = buildBeltRuns(bp([belt(0, 2), belt(1, 2), belt(2, -1)]));
  const b = buildBeltRuns(bp([belt(2, -1), belt(1, 2), belt(0, 2)]));
  const key = (rs: ReturnType<typeof buildBeltRuns>) =>
    JSON.stringify(rs.map((r) => r.belts).sort());
  expect(key(a)).toBe(key(b));
});

test('a closed loop terminates and is marked cyclic', () => {
  const runs = buildBeltRuns(bp([belt(0, 1), belt(1, 2), belt(2, 0)]));
  expect(runs.length).toBe(1);
  expect(runs[0]!.cyclic).toBe(true);
  expect(runs[0]!.belts.length).toBe(3);
  expect(runs[0]!.freeInput).toBe(false);
  expect(runs[0]!.freeOutput).toBe(false);
});

test('a belt feeding a non-belt building is connected, not free', () => {
  const station = { ...belt(9, -1), itemId: 2103 };
  const runs = buildBeltRuns(bp([belt(0, 9), station]));
  const run = runs.find((r) => r.belts.includes(0))!;
  expect(run.freeOutput).toBe(false);
});

test('headings point along the run', () => {
  const runs = buildBeltRuns(bp([belt(0, 1), belt(1, -1)]));
  const positions = new Map<number, readonly [number, number, number]>([
    [0, [0, 0, 0]],
    [1, [1, 0, 0]],
  ]);
  const headings = computeBeltHeadings(runs, positions);
  // heading toward +x, measured as atan2(dx, dz)
  expect(headings.get(0)).toBeCloseTo(Math.PI / 2, 5);
  // the tail reuses its predecessor's heading
  expect(headings.get(1)).toBeCloseTo(Math.PI / 2, 5);
});

test('real fixture: heretical smelter resolves to 11 runs', () => {
  const parsed = parseBlueprint(
    readFileSync('tests/fixtures/factory-heretical-smelter-block.txt', 'utf8'),
  );
  const runs = buildBeltRuns(parsed);
  expect(runs.length).toBe(11);
  expect(Math.max(...runs.map((r) => r.belts.length))).toBe(36);
  expect(runs.reduce((n, r) => n + r.belts.length, 0)).toBe(283);
  expect(runs.some((r) => r.cyclic)).toBe(false);
});

test('real fixture: falk mall has belts in cycles', () => {
  const parsed = parseBlueprint(readFileSync('tests/fixtures/falk-v7-mall-full.txt', 'utf8'));
  const runs = buildBeltRuns(parsed);
  // every belt lands in exactly one run, cycles included
  expect(runs.reduce((n, r) => n + r.belts.length, 0)).toBe(1714);
  expect(runs.filter((r) => r.cyclic).reduce((n, r) => n + r.belts.length, 0)).toBe(280);
});
```

**Note on the 12-s-purple fixture:** the spec predicts 23 runs under degree-based segmentation (22 heads plus one merge node), where a naive head-walk reports 22. That number is a prediction, not a measurement. After the implementation is green, run it against `tests/fixtures/12-s-purple-science-from-smelted-refined-products.txt`, record the actual value, and add an assertion for it. If it is not 23, stop and reconcile the rule with the data before continuing — do not simply write down whatever the code produced.

- [ ] **Step 2: Run to verify they fail**

Run: `bunx rstest run tests/model/beltGraph.test.ts 2>&1`
Expected: FAIL — cannot find module `beltGraph`.

- [ ] **Step 3: Implement the graph**

Create `src/model/beltGraph.ts`:

```ts
import type { Blueprint, BlueprintBuilding } from '../format/types';

export function isBelt(itemId: number): boolean {
  return itemId >= 2001 && itemId <= 2009;
}

export function isSorter(itemId: number): boolean {
  return itemId >= 2011 && itemId <= 2019;
}

export interface BeltRun {
  /** Building indices, head to tail. */
  belts: number[];
  /** No belt feeds the head. */
  freeInput: boolean;
  /** The tail points at nothing at all (outputObjIdx < 0). */
  freeOutput: boolean;
  cyclic: boolean;
  /** Item ids the run carries, sorted and deduped. Filled in by inferCarried. */
  carried: number[];
  hasExplicitTag: boolean;
}

/**
 * Groups belts into runs.
 *
 * Blueprints are forward-linked only -- `inputObjIdx` is -1 on almost every
 * belt (277 of 283 in the heretical fixture) -- so a run's head is found by
 * inverting `outputObjIdx` rather than by reading a field.
 *
 * Segmentation is by local degree, not by walk order: a run starts at any belt
 * whose inbound count is not exactly 1, and stops before any belt whose inbound
 * count exceeds 1. Walking outward from heads instead would let whichever head
 * happened to arrive first absorb a shared tail, making the output depend on
 * building order.
 */
export function buildBeltRuns(bp: Blueprint): BeltRun[] {
  const byIndex = new Map<number, BlueprintBuilding>();
  for (const b of bp.buildings) byIndex.set(b.index, b);

  const belts = bp.buildings.filter((b) => isBelt(b.itemId));
  const beltIndices = new Set(belts.map((b) => b.index));

  // Successor links, belt-to-belt only. A belt feeding a station is connected
  // but does not continue a run.
  const next = new Map<number, number>();
  for (const b of belts) {
    if (beltIndices.has(b.outputObjIdx)) next.set(b.index, b.outputObjIdx);
  }

  const inbound = new Map<number, number>();
  for (const target of next.values()) inbound.set(target, (inbound.get(target) ?? 0) + 1);

  const runs: BeltRun[] = [];
  const visited = new Set<number>();

  const makeRun = (belts: number[], cyclic: boolean): BeltRun => {
    const head = belts[0] as number;
    const tail = belts[belts.length - 1] as number;
    return {
      belts,
      freeInput: !cyclic && (inbound.get(head) ?? 0) === 0,
      freeOutput: !cyclic && (byIndex.get(tail)?.outputObjIdx ?? -1) < 0,
      cyclic,
      carried: [],
      hasExplicitTag: belts.some((i) => (byIndex.get(i)?.parameters.length ?? 0) > 0),
    };
  };

  // Pass 1: every belt whose inbound degree is not exactly 1 starts a run.
  for (const b of belts) {
    if ((inbound.get(b.index) ?? 0) === 1) continue;
    const chain: number[] = [];
    let current: number | undefined = b.index;
    while (current !== undefined && !visited.has(current)) {
      visited.add(current);
      chain.push(current);
      const successor: number | undefined = next.get(current);
      // Stop before a merge point: it begins its own run.
      if (successor === undefined || (inbound.get(successor) ?? 0) > 1) break;
      current = successor;
    }
    if (chain.length > 0) runs.push(makeRun(chain, false));
  }

  // Pass 2: anything still unvisited has inbound degree 1 everywhere, i.e. it
  // is a closed loop with no head. Walk each loop once.
  for (const b of belts) {
    if (visited.has(b.index)) continue;
    const chain: number[] = [];
    let current: number | undefined = b.index;
    while (current !== undefined && !visited.has(current)) {
      visited.add(current);
      chain.push(current);
      current = next.get(current);
    }
    if (chain.length > 0) runs.push(makeRun(chain, true));
  }

  return runs;
}

/**
 * Bearing for each belt, used to orient direction chevrons.
 *
 * Belt yaw cannot be used: the game zeroes it when serialising a belt
 * (BuildingParameters.cs sets `yaw = 0f` for BuildingType.Belt), so direction
 * only exists in the link topology. The tail of a run has no successor and
 * reuses its predecessor's bearing.
 */
export function computeBeltHeadings(
  runs: BeltRun[],
  positions: Map<number, readonly [number, number, number]>,
): Map<number, number> {
  const headings = new Map<number, number>();

  for (const run of runs) {
    let previous: number | undefined;
    for (let i = 0; i < run.belts.length; i++) {
      const index = run.belts[i] as number;
      // A cyclic run wraps around to its own head.
      const nextIndex = run.belts[i + 1] ?? (run.cyclic ? run.belts[0] : undefined);
      const from = positions.get(index);
      const to = nextIndex === undefined ? undefined : positions.get(nextIndex);
      if (from && to) {
        const heading = Math.atan2(to[0] - from[0], to[2] - from[2]);
        headings.set(index, heading);
        previous = heading;
      } else if (previous !== undefined) {
        headings.set(index, previous);
      }
    }
  }

  return headings;
}
```

- [ ] **Step 4: Run to verify they pass**

Run: `bunx rstest run tests/model/beltGraph.test.ts 2>&1` — expected PASS.

- [ ] **Step 5: Determine the 12-s-purple run count and assert it**

Run this one-off to get the real number:

```bash
bun -e '
import {readFileSync} from "node:fs";
import {parseBlueprint} from "./src/format/index";
import {buildBeltRuns} from "./src/model/beltGraph";
const bp = parseBlueprint(readFileSync("tests/fixtures/12-s-purple-science-from-smelted-refined-products.txt","utf8"));
const runs = buildBeltRuns(bp);
console.log("runs", runs.length, "belts", runs.reduce((n,r)=>n+r.belts.length,0));
'
```

Expected: `runs 23 belts 2640`. If the count is not 23, stop and reconcile — the spec derives 23 from 22 inbound-degree-0 heads plus one inbound-degree-2 merge node.

Then add the assertion to the test file:

```ts
test('real fixture: 12-s-purple splits at its merge point', () => {
  const parsed = parseBlueprint(
    readFileSync('tests/fixtures/12-s-purple-science-from-smelted-refined-products.txt', 'utf8'),
  );
  const runs = buildBeltRuns(parsed);
  expect(runs.length).toBe(23);
  expect(runs.reduce((n, r) => n + r.belts.length, 0)).toBe(2640);
});
```

- [ ] **Step 6: Run the full suite and lint**

Run: `bun run test 2>&1` then `bun run lint && bun run typecheck`

- [ ] **Step 7: Commit**

```bash
git add src/model/beltGraph.ts tests/model/beltGraph.test.ts
git commit -m "feat(model): derive belt runs from forward-only links"
```

---

### Task 5: Infer what each run carries

**Files:**
- Modify: `src/model/beltGraph.ts`
- Test: `tests/model/beltGraph.test.ts`

**Interfaces:**
- Consumes: `BeltRun` from Task 4, `Catalog.recipe` from `./catalog`.
- Produces: `inferCarried(bp: Blueprint, runs: BeltRun[], catalog: Catalog): void` — mutates each run's `carried` in place.

Sorter semantics: `inputObjIdx` is where the sorter **picks up**, `outputObjIdx` is where it **puts down**. So when the belt is the sorter's *input*, the sorter is draining the belt into a building, and the item is one of that building's recipe **inputs**. When the belt is the sorter's *output*, a building is feeding the belt, and the item is one of that recipe's **results**.

- [ ] **Step 1: Write the failing tests**

Add to `tests/model/beltGraph.test.ts`. Add a `sorter` helper next to the existing `belt` helper:

```ts
function sorter(
  index: number,
  inputObjIdx: number,
  outputObjIdx: number,
  filterId = 0,
): BlueprintBuilding {
  return { ...belt(index, -1), itemId: 2011, inputObjIdx, outputObjIdx, filterId };
}

function producer(index: number, recipeId: number): BlueprintBuilding {
  return { ...belt(index, -1), itemId: 2303, recipeId };
}
```

and the tests:

```ts
const testCatalog = buildCatalog({
  items: [],
  models: {},
  recipes: [
    { id: 1, name: 'Iron Ingot', iconName: '', items: [1001], itemCounts: [1],
      results: [1101], resultCounts: [1], timeSpend: 60 },
    { id: 53, name: 'Two In', iconName: '', items: [1101, 1104], itemCounts: [1, 1],
      results: [1301], resultCounts: [1], timeSpend: 60 },
  ],
});

test('a sorter filter names what the run carries', () => {
  const parsed = bp([belt(0, -1), sorter(1, 0, 5, 1101)]);
  const runs = buildBeltRuns(parsed);
  inferCarried(parsed, runs, testCatalog);
  expect(runs[0]!.carried).toEqual([1101]);
});

test('an unfiltered sorter draining a belt uses the destination recipe inputs', () => {
  // sorter picks up from belt 0, puts into producer 5 running recipe 1 (input 1001)
  const parsed = bp([belt(0, -1), sorter(1, 0, 5), producer(5, 1)]);
  const runs = buildBeltRuns(parsed);
  inferCarried(parsed, runs, testCatalog);
  expect(runs[0]!.carried).toEqual([1001]);
});

test('an unfiltered sorter feeding a belt uses the source recipe results', () => {
  // producer 5 (recipe 1, result 1101) -> sorter -> belt 0
  const parsed = bp([belt(0, -1), sorter(1, 5, 0), producer(5, 1)]);
  const runs = buildBeltRuns(parsed);
  inferCarried(parsed, runs, testCatalog);
  expect(runs[0]!.carried).toEqual([1101]);
});

test('a multi-input recipe contributes every candidate', () => {
  const parsed = bp([belt(0, -1), sorter(1, 0, 5), producer(5, 53)]);
  const runs = buildBeltRuns(parsed);
  inferCarried(parsed, runs, testCatalog);
  expect(runs[0]!.carried).toEqual([1101, 1104]);
});

test('carried items are deduped and sorted across several sorters', () => {
  const parsed = bp([
    belt(0, 1), belt(1, -1),
    sorter(2, 0, 9, 1104), sorter(3, 1, 9, 1101), sorter(4, 0, 9, 1101),
  ]);
  const runs = buildBeltRuns(parsed);
  inferCarried(parsed, runs, testCatalog);
  expect(runs[0]!.carried).toEqual([1101, 1104]);
});
```

Add `buildCatalog` and `inferCarried` to the file's imports.

- [ ] **Step 2: Run to verify they fail**

Run: `bunx rstest run tests/model/beltGraph.test.ts 2>&1`
Expected: FAIL — `inferCarried` is not exported.

- [ ] **Step 3: Implement**

Append to `src/model/beltGraph.ts` (and add `import type { Catalog } from './catalog';` at the top):

```ts
/**
 * Fills in each run's `carried` from the sorters attached to it.
 *
 * A sorter's own filter is authoritative when set, but it frequently is not --
 * across the fixtures, 0 of 18 and 0 of 22 sorters at run ends carry filters in
 * two of the four belt-bearing blueprints. The fallback reads the recipe of the
 * building at the sorter's other end.
 *
 * A sorter feeding a multi-input recipe is genuinely ambiguous: the blueprint
 * never records which of the inputs that particular sorter carries. Every
 * candidate is contributed rather than guessing one.
 */
export function inferCarried(bp: Blueprint, runs: BeltRun[], catalog: Catalog): void {
  const byIndex = new Map<number, BlueprintBuilding>();
  for (const b of bp.buildings) byIndex.set(b.index, b);

  const runOfBelt = new Map<number, BeltRun>();
  for (const run of runs) for (const index of run.belts) runOfBelt.set(index, run);

  const collected = new Map<BeltRun, Set<number>>();
  const add = (run: BeltRun, itemIds: readonly number[]): void => {
    let set = collected.get(run);
    if (!set) {
      set = new Set();
      collected.set(run, set);
    }
    for (const id of itemIds) if (id > 0) set.add(id);
  };

  for (const s of bp.buildings) {
    if (!isSorter(s.itemId)) continue;

    // The belt is the sorter's input: it drains the belt into `outputObjIdx`.
    const drained = runOfBelt.get(s.inputObjIdx);
    if (drained) add(drained, itemsForSorter(s, byIndex.get(s.outputObjIdx), 'inputs', catalog));

    // The belt is the sorter's output: `inputObjIdx` feeds the belt.
    const fed = runOfBelt.get(s.outputObjIdx);
    if (fed) add(fed, itemsForSorter(s, byIndex.get(s.inputObjIdx), 'results', catalog));
  }

  for (const run of runs) {
    const set = collected.get(run);
    run.carried = set ? [...set].sort((a, b) => a - b) : [];
  }
}

function itemsForSorter(
  sorter: BlueprintBuilding,
  other: BlueprintBuilding | undefined,
  side: 'inputs' | 'results',
  catalog: Catalog,
): readonly number[] {
  if (sorter.filterId > 0) return [sorter.filterId];
  if (!other || other.recipeId <= 0) return [];
  const recipe = catalog.recipe(other.recipeId);
  if (!recipe) return [];
  return side === 'inputs' ? recipe.items : recipe.results;
}
```

- [ ] **Step 4: Run to verify they pass**

Run: `bunx rstest run tests/model/beltGraph.test.ts 2>&1` — expected PASS.

- [ ] **Step 5: Wire it into the scene model**

In `src/model/layout.ts`, add to the `SceneModel` interface:

```ts
  beltRuns: BeltRun[];
  beltHeadings: Map<number, number>;
```

Import `buildBeltRuns`, `inferCarried`, `computeBeltHeadings`, `beltSuccessors`, and `type BeltRun` from `./beltGraph`. At the end of `buildSceneModel`, after `instances` is built:

```ts
  const beltRuns = buildBeltRuns(bp);
  inferCarried(bp, beltRuns, catalog);
  const positions = new Map<number, readonly [number, number, number]>(
    instances.map((i) => [i.index, i.position]),
  );
  const beltHeadings = computeBeltHeadings(beltRuns, positions, beltSuccessors(bp));
```

**Note the third argument.** Task 4's review found that looking only *inside*
a run loses direction the graph already has: a single-belt run got no heading
at all, and a tail whose successor lives in another run (which is what happens
at every merge) inherited its predecessor's bearing. `computeBeltHeadings` now
takes the global belt→successor map as a required third parameter, and
`beltSuccessors(bp)` builds it. Passing only two arguments will not typecheck.

and include `beltRuns` and `beltHeadings` in the returned object.

- [ ] **Step 6: Run the full suite and lint**

Run: `bun run test 2>&1` then `bun run lint && bun run typecheck`

Any test constructing a `SceneModel` literal will now fail to typecheck. Fix those by adding `beltRuns: [], beltHeadings: new Map()`.

- [ ] **Step 7: Commit**

```bash
git add src/model/beltGraph.ts src/model/layout.ts tests/
git commit -m "feat(model): infer belt run contents from sorters and recipes"
```

---

### Task 6: Belt tag icons and counts in overlays

**Files:**
- Modify: `src/model/overlays.ts`
- Modify: `src/scene/BlueprintCanvas.tsx`
- Test: `tests/model/overlays.test.ts`

**Interfaces:**
- Consumes: `Catalog.tagIconName` (Task 2), `BuildingInstance.parameters` (Task 3).
- Produces:
  - `interface CountPlacement { position: [number, number, number]; value: number }`
  - `interface Overlays { icons: IconPlacement[]; counts: CountPlacement[] }`
  - `buildOverlays(model, catalog, atlas): Overlays` — **return type changes** from `IconPlacement[]`.

`buildOverlays` silently skips a tag it cannot resolve. Reporting that gap is
`SceneModel.unresolvedTagIds`, computed once in `buildSceneModel` (Task 10) —
not here. The toolbar reads the scene model, and duplicating the resolution
into two places would let the two diagnostics drift apart.

- [ ] **Step 1: Write the failing test**

Add to `tests/model/overlays.test.ts`. The existing file builds a `SceneModel`-shaped literal; extend that pattern with belts carrying `parameters`.

```ts
test('a tagged belt gets an icon, and a non-zero count gets a placement', () => {
  const model = {
    instances: [
      { index: 0, itemId: 2001, modelIndex: 35, position: [0, 0, 0], size: [1, 1, 1],
        yawRad: 0, color: 1, recipeId: 0, filterId: 0, parameters: [1101, 360] },
      { index: 1, itemId: 2001, modelIndex: 35, position: [1, 0, 0], size: [1, 1, 1],
        yawRad: 0, color: 1, recipeId: 0, filterId: 0, parameters: [1101, 0] },
    ],
    beltRuns: [],
    beltHeadings: new Map(),
    unknownItemIds: [],
  } as unknown as SceneModel;

  const out = buildOverlays(model, catalog, atlas);
  // both belts are tagged, so both get an icon
  expect(out.icons.filter((i) => i.iconName === 'iron-plate').length).toBe(2);
  // only the non-zero count is drawn: 0 is the unset value
  expect(out.counts.length).toBe(1);
  expect(out.counts[0]!.value).toBe(360);
});

test('an unresolvable tag id draws nothing rather than a wrong icon', () => {
  const model = {
    instances: [
      { index: 0, itemId: 2001, modelIndex: 35, position: [0, 0, 0], size: [1, 1, 1],
        yawRad: 0, color: 1, recipeId: 0, filterId: 0, parameters: [40001, 0] },
    ],
    beltRuns: [],
    beltHeadings: new Map(),
    unknownItemIds: [],
  } as unknown as SceneModel;

  const out = buildOverlays(model, catalog, atlas);
  expect(out.icons.length).toBe(0);
  expect(out.counts.length).toBe(0);
});
```

The existing tests in this file assert against the array returned by `buildOverlays`; update them to read `.icons`. Ensure the inline `catalog` in this file includes an item with id 1101 and `iconName: 'iron-plate'`, and that the inline `atlas` has an `iron-plate` entry.

- [ ] **Step 2: Run to verify it fails**

Run: `bunx rstest run tests/model/overlays.test.ts 2>&1`
Expected: FAIL — `out.icons` is undefined.

- [ ] **Step 3: Implement**

In `src/model/overlays.ts`, add the new types and change the return shape:

```ts
export interface CountPlacement {
  position: [number, number, number];
  value: number;
}

export interface Overlays {
  icons: IconPlacement[];
  counts: CountPlacement[];
}
```

Change the signature to `export function buildOverlays(...): Overlays`, collect into `icons` and `counts`, and return both. Keep the existing per-building recipe/filter loop as-is, then add belt tag handling inside that same loop:

```ts
    // Belt tags: parameters is either empty or exactly [signalId, count].
    // The game writes null when no icon is set (BuildingParameters.cs).
    //
    // The isBelt() gate is load-bearing, not defensive. Many non-belt
    // buildings carry a parameter block that means something else entirely --
    // in factory-endgame-distribution-hub, stations carry 2048 words of slot
    // config, sorters one word of stack size, splitters one word. Without the
    // gate, parameters[0] of a station is read as a signal id, and because
    // those words happen to BE item ids, they resolve: 10 Interstellar
    // Logistics Stations each drew a confidently wrong icon (lab, tesla coil,
    // oil refinery) plus a bogus count of 1. Only belts carry belt tags.
    const [tagId, tagCount] = inst.parameters;
    if (isBelt(inst.itemId) && tagId !== undefined && tagId > 0) {
      const tagIcon = catalog.tagIconName(tagId);
      const tagCell = tagIcon ? atlas.entries[tagIcon] : undefined;
      if (tagIcon && tagCell) {
        const position: [number, number, number] = [
          inst.position[0],
          inst.position[1] + inst.size[1] / 2 + 0.6,
          inst.position[2],
        ];
        icons.push({
          iconName: tagIcon,
          position,
          uv: [tagCell[0] / atlas.cols, tagCell[1] / atlas.rows],
        });
        // 0 is the unset value, not a number the player chose to display.
        if (tagCount !== undefined && tagCount !== 0) {
          counts.push({ position: [position[0], position[1], position[2] + 0.9], value: tagCount });
        }
      }
      // An unresolvable tag draws nothing; SceneModel.unresolvedTagIds (Task 10)
      // is what reports it, so the gap is visible without duplicating the
      // resolution here.
    }
```

- [ ] **Step 4: Update the caller**

In `src/scene/BlueprintCanvas.tsx`, `buildOverlays(...)` is passed straight into `<IconInstances placements={...}>`. Change it to compute once and pass the icons:

```tsx
      {atlas && atlasTexture && (
        <IconInstances
          placements={buildOverlays(sceneModel, catalog, atlas).icons}
          atlas={atlas}
          texture={atlasTexture}
        />
      )}
```

This is a pure derivation in render; the React Compiler handles memoisation, so do not add `useMemo`.

- [ ] **Step 5: Run tests, lint, typecheck**

Run: `bun run test 2>&1`, `bun run lint`, `bun run typecheck`

- [ ] **Step 6: Commit**

```bash
git add src/model/overlays.ts src/scene/BlueprintCanvas.tsx tests/model/overlays.test.ts
git commit -m "feat(model): render belt tag icons and counts"
```

---

### Task 7: Inferred endpoint icons

**Files:**
- Modify: `src/model/overlays.ts`
- Test: `tests/model/overlays.test.ts`

**Interfaces:**
- Consumes: `SceneModel.beltRuns` (Task 5), `Overlays` (Task 6).
- Produces: no new exports; extends `buildOverlays` output.

- [ ] **Step 1: Write the failing test**

```ts
test('an unconnected run shows its contents at both free ends', () => {
  const model = {
    instances: [
      { index: 0, itemId: 2001, modelIndex: 35, position: [0, 0, 0], size: [1, 1, 1],
        yawRad: 0, color: 1, recipeId: 0, filterId: 0, parameters: [] },
      { index: 1, itemId: 2001, modelIndex: 35, position: [4, 0, 0], size: [1, 1, 1],
        yawRad: 0, color: 1, recipeId: 0, filterId: 0, parameters: [] },
    ],
    beltRuns: [
      { belts: [0, 1], freeInput: true, freeOutput: true, cyclic: false,
        carried: [1101], hasExplicitTag: false },
    ],
    beltHeadings: new Map(),
    unknownItemIds: [],
  } as unknown as SceneModel;

  const out = buildOverlays(model, catalog, atlas);
  // one icon at the head, one at the tail
  expect(out.icons.length).toBe(2);
  expect(out.icons[0]!.position[0]).toBe(0);
  expect(out.icons[1]!.position[0]).toBe(4);
});

test('a run with its own tag is not second-guessed', () => {
  const model = {
    instances: [
      { index: 0, itemId: 2001, modelIndex: 35, position: [0, 0, 0], size: [1, 1, 1],
        yawRad: 0, color: 1, recipeId: 0, filterId: 0, parameters: [1101, 0] },
    ],
    beltRuns: [
      { belts: [0], freeInput: true, freeOutput: true, cyclic: false,
        carried: [1101], hasExplicitTag: true },
    ],
    beltHeadings: new Map(),
    unknownItemIds: [],
  } as unknown as SceneModel;

  const out = buildOverlays(model, catalog, atlas);
  // exactly the explicit tag, no inferred endpoint icons
  expect(out.icons.length).toBe(1);
});

test('a cyclic run has no free end and so no endpoint icons', () => {
  const model = {
    instances: [
      { index: 0, itemId: 2001, modelIndex: 35, position: [0, 0, 0], size: [1, 1, 1],
        yawRad: 0, color: 1, recipeId: 0, filterId: 0, parameters: [] },
    ],
    beltRuns: [
      { belts: [0], freeInput: false, freeOutput: false, cyclic: true,
        carried: [1101], hasExplicitTag: false },
    ],
    beltHeadings: new Map(),
    unknownItemIds: [],
  } as unknown as SceneModel;

  expect(buildOverlays(model, catalog, atlas).icons.length).toBe(0);
});

test('several carried items fan out so they do not overlap', () => {
  const model = {
    instances: [
      { index: 0, itemId: 2001, modelIndex: 35, position: [0, 0, 0], size: [1, 1, 1],
        yawRad: 0, color: 1, recipeId: 0, filterId: 0, parameters: [] },
    ],
    beltRuns: [
      { belts: [0], freeInput: true, freeOutput: false, cyclic: false,
        carried: [1101, 1104], hasExplicitTag: false },
    ],
    beltHeadings: new Map(),
    unknownItemIds: [],
  } as unknown as SceneModel;

  const out = buildOverlays(model, catalog, atlas);
  expect(out.icons.length).toBe(2);
  expect(out.icons[0]!.position[0]).not.toBe(out.icons[1]!.position[0]);
});
```

**This test needs a second resolvable item.** The file's existing inline
catalog has only one item whose icon is also present in its inline atlas
(1101 → `iron-plate`); item 1201 has an empty `iconName`, and the atlas has
only `gear` and `iron-plate`. Add a second item to the catalog:

```ts
    { id: 1104, name: 'Copper Ingot', iconName: 'copper-plate', gridIndex: 5,
      modelIndex: 0, canBuild: false, color: 5 },
```

and a matching cell to the inline atlas, bumping `cols` so the coordinate is
in range:

```ts
const atlas = {
  cell: 64,
  cols: 4,
  rows: 2,
  entries: {
    gear: [1, 0] as [number, number],
    'iron-plate': [2, 1] as [number, number],
    'copper-plate': [3, 1] as [number, number],
  },
};
```

- [ ] **Step 2: Run to verify it fails**

Run: `bunx rstest run tests/model/overlays.test.ts 2>&1` — expected FAIL (0 icons where 2 expected).

- [ ] **Step 3: Implement**

Append a second pass in `buildOverlays`, after the per-building loop:

```ts
  const instanceByIndex = new Map(model.instances.map((i) => [i.index, i]));

  // Inferred endpoint icons. A run whose contents the player already labelled
  // is left alone -- explicit tags win over our guess.
  for (const run of model.beltRuns) {
    if (run.hasExplicitTag || run.carried.length === 0) continue;

    // A Set, not an array: a single-belt run has belts[0] === tail, so when
    // both ends are free an array would hold the same index twice and draw
    // every carried icon twice at the identical position. Such runs are real
    // -- factory-quick-start-step-3-red-cube contains one.
    const ends = new Set<number>();
    if (run.freeInput && run.belts[0] !== undefined) ends.add(run.belts[0]);
    if (run.freeOutput) {
      const tail = run.belts[run.belts.length - 1];
      if (tail !== undefined) ends.add(tail);
    }

    for (const endIndex of ends) {
      const inst = instanceByIndex.get(endIndex);
      if (!inst) continue;
      run.carried.forEach((itemId, slot) => {
        const iconName = catalog.item(itemId)?.iconName;
        const cell = iconName ? atlas.entries[iconName] : undefined;
        if (!iconName || !cell) return;
        // Fan multiple items apart so they do not stack on one another.
        const spread = (slot - (run.carried.length - 1) / 2) * 1.2;
        icons.push({
          iconName,
          position: [
            inst.position[0] + spread,
            inst.position[1] + inst.size[1] / 2 + 0.6,
            inst.position[2],
          ],
          uv: [cell[0] / atlas.cols, cell[1] / atlas.rows],
        });
      });
    }
  }
```

- [ ] **Step 4: Run to verify it passes**

Run: `bunx rstest run tests/model/overlays.test.ts 2>&1` — expected PASS.

- [ ] **Step 5: Full suite, lint, typecheck**

Run: `bun run test 2>&1`, `bun run lint`, `bun run typecheck`

- [ ] **Step 6: Commit**

```bash
git add src/model/overlays.ts tests/model/overlays.test.ts
git commit -m "feat(model): infer endpoint icons for unconnected belt runs"
```

---

### Task 8: Render tag counts

**Files:**
- Create: `src/scene/CountLabels.tsx`
- Modify: `src/scene/BlueprintCanvas.tsx`
- Test: `tests/scene/countLabels.test.ts`

**Interfaces:**
- Consumes: `CountPlacement[]` (Task 6).
- Produces: `layoutDigits(placements): DigitQuad[]`, `makeDigitTexture(): CanvasTexture`, and `<CountLabels placements={...} />`.

Digits are generated at runtime from a 2D canvas rather than extracted: they are not game data, so this adds no font file and leaves the extractor untouched. Blueprint counts are always integers, so ten glyphs are enough — no text shaping.

- [ ] **Step 1: Write the failing test**

Create `tests/scene/countLabels.test.ts`. Test the pure layout helper, not the R3F component — the existing `tests/scene/instances.test.ts` follows this same split.

```ts
import { expect, test } from '@rstest/core';
import { layoutDigits } from '../../src/scene/CountLabels';

test('lays out one quad per digit, centred on the placement', () => {
  const quads = layoutDigits([{ position: [10, 2, 5], value: 360 }]);
  expect(quads.length).toBe(3);
  expect(quads.map((q) => q.digit)).toEqual([3, 6, 0]);
  // centred: mean x offset is the placement's x
  const meanX = quads.reduce((n, q) => n + q.position[0], 0) / quads.length;
  expect(meanX).toBeCloseTo(10, 5);
  expect(quads.every((q) => q.position[1] === 2)).toBe(true);
});

test('handles multi-digit and single-digit values', () => {
  expect(layoutDigits([{ position: [0, 0, 0], value: 7 }]).length).toBe(1);
  expect(layoutDigits([{ position: [0, 0, 0], value: 1800 }]).length).toBe(4);
});

test('emits nothing for an empty list', () => {
  expect(layoutDigits([]).length).toBe(0);
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `bunx rstest run tests/scene/countLabels.test.ts 2>&1` — expected FAIL, module not found.

- [ ] **Step 3: Implement**

Create `src/scene/CountLabels.tsx`:

```tsx
import { useLayoutEffect, useMemo, useRef } from 'react';
import {
  CanvasTexture,
  InstancedBufferAttribute,
  type InstancedMesh,
  Object3D,
} from 'three';
import type { CountPlacement } from '../model/overlays';

const DIGIT_CELL = 64;
const DIGIT_COLS = 10;
const DIGIT_SIZE = 0.9;
const DIGIT_SPACING = 0.62;

export interface DigitQuad {
  position: [number, number, number];
  digit: number;
}

/**
 * One quad per digit, the whole number centred on the placement.
 *
 * Blueprint counts are always integers -- the game rounds its float to int on
 * serialisation -- so this never has to deal with signs or decimal points.
 */
export function layoutDigits(placements: readonly CountPlacement[]): DigitQuad[] {
  const quads: DigitQuad[] = [];
  for (const p of placements) {
    const digits = String(Math.abs(Math.trunc(p.value))).split('').map(Number);
    digits.forEach((digit, i) => {
      const offset = (i - (digits.length - 1) / 2) * DIGIT_SPACING;
      quads.push({ position: [p.position[0] + offset, p.position[1], p.position[2]], digit });
    });
  }
  return quads;
}

/**
 * A 10-cell strip of digit glyphs, drawn at runtime.
 *
 * Digits are not game data, so generating them here keeps the asset extractor
 * untouched and adds no font file to the repo.
 */
export function makeDigitTexture(): CanvasTexture {
  const canvas = document.createElement('canvas');
  canvas.width = DIGIT_CELL * DIGIT_COLS;
  canvas.height = DIGIT_CELL;
  const ctx = canvas.getContext('2d');
  if (ctx) {
    ctx.fillStyle = '#ffffff';
    ctx.font = `bold ${DIGIT_CELL * 0.8}px system-ui, sans-serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    for (let d = 0; d < DIGIT_COLS; d++) {
      ctx.fillText(String(d), d * DIGIT_CELL + DIGIT_CELL / 2, DIGIT_CELL / 2);
    }
  }
  return new CanvasTexture(canvas);
}

export function CountLabels({ placements }: { placements: CountPlacement[] }) {
  const meshRef = useRef<InstancedMesh>(null);
  const quads = layoutDigits(placements);
  const count = quads.length;

  // The texture owns a GPU handle, so it is created once and disposed on
  // unmount rather than rebuilt whenever the placements change.
  const texture = useMemo(() => makeDigitTexture(), []);
  useLayoutEffect(() => () => texture.dispose(), [texture]);

  const offsets = useMemo(() => {
    const a = new Float32Array(Math.max(count, 1));
    quads.forEach((q, i) => {
      a[i] = q.digit / DIGIT_COLS;
    });
    return new InstancedBufferAttribute(a, 1);
  }, [quads, count]);

  useLayoutEffect(() => {
    const mesh = meshRef.current;
    if (!mesh) return;
    const dummy = new Object3D();
    quads.forEach((q, i) => {
      dummy.position.set(q.position[0], q.position[1], q.position[2]);
      dummy.rotation.set(-Math.PI / 2, 0, 0); // lie flat, as the icons do
      dummy.scale.setScalar(DIGIT_SIZE);
      dummy.updateMatrix();
      mesh.setMatrixAt(i, dummy.matrix);
    });
    mesh.instanceMatrix.needsUpdate = true;
    mesh.computeBoundingSphere();
  }, [quads]);

  if (count === 0) return null;

  return (
    <instancedMesh key={count} ref={meshRef} args={[undefined, undefined, count]} raycast={() => null}>
      <planeGeometry args={[1, 1]}>
        <primitive object={offsets} attach="attributes-digitOffset" />
      </planeGeometry>
      <meshBasicMaterial
        map={texture}
        transparent
        depthWrite={false}
        onBeforeCompile={(shader) => {
          shader.vertexShader = shader.vertexShader
            .replace(
              '#include <common>',
              `#include <common>\nattribute float digitOffset;\nvarying float vDigit;`,
            )
            .replace('#include <uv_vertex>', `#include <uv_vertex>\nvDigit = digitOffset;`);
          shader.fragmentShader = shader.fragmentShader
            .replace('#include <common>', `#include <common>\nvarying float vDigit;`)
            .replace(
              '#include <map_fragment>',
              // Single-row strip, so only u is offset; unlike the icon atlas
              // there is no multi-row flipY correction to undo here.
              `vec2 digitUv = vec2( vDigit + vMapUv.x * ${1 / DIGIT_COLS}, vMapUv.y );
               vec4 sampled = texture2D( map, digitUv );
               if ( sampled.a < 0.1 ) discard;
               diffuseColor *= sampled;`,
            );
        }}
      />
    </instancedMesh>
  );
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `bunx rstest run tests/scene/countLabels.test.ts 2>&1` — expected PASS.

- [ ] **Step 5: Mount it**

In `src/scene/BlueprintCanvas.tsx`, hoist the overlays call so both consumers share it, and render counts:

```tsx
  const overlays = atlas ? buildOverlays(sceneModel, catalog, atlas) : null;
```

then inside `<Canvas>`:

```tsx
      {atlas && atlasTexture && overlays && (
        <>
          <IconInstances placements={overlays.icons} atlas={atlas} texture={atlasTexture} />
          <CountLabels placements={overlays.counts} />
        </>
      )}
```

- [ ] **Step 6: Full suite, lint, typecheck**

Run: `bun run test 2>&1`, `bun run lint`, `bun run typecheck`

- [ ] **Step 7: Commit**

```bash
git add src/scene/CountLabels.tsx src/scene/BlueprintCanvas.tsx tests/scene/countLabels.test.ts
git commit -m "feat(scene): render belt tag counts as instanced digits"
```

---

### Task 9: Render direction chevrons

**Files:**
- Create: `src/scene/BeltChevrons.tsx`
- Modify: `src/scene/BlueprintCanvas.tsx`
- Test: `tests/scene/beltChevrons.test.ts`

**Interfaces:**
- Consumes: `SceneModel.beltRuns` and `SceneModel.beltHeadings` (Tasks 4–5).
- Produces: `chevronTransforms(model: SceneModel): ChevronTransform[]` and `<BeltChevrons model={...} />`.

- [ ] **Step 1: Write the failing test**

Create `tests/scene/beltChevrons.test.ts`:

```ts
import { expect, test } from '@rstest/core';
import type { SceneModel } from '../../src/model/layout';
import { chevronTransforms } from '../../src/scene/BeltChevrons';

function model(headings: [number, number][]): SceneModel {
  return {
    instances: [
      { index: 0, itemId: 2001, modelIndex: 35, position: [0, 1, 0], size: [1, 0.2, 1],
        yawRad: 0, color: 1, recipeId: 0, filterId: 0, parameters: [] },
      { index: 1, itemId: 2303, modelIndex: 65, position: [5, 1, 0], size: [3, 3, 3],
        yawRad: 0, color: 1, recipeId: 1, filterId: 0, parameters: [] },
    ],
    beltRuns: [],
    beltHeadings: new Map(headings),
    unknownItemIds: [],
  } as unknown as SceneModel;
}

test('emits one chevron per belt with a heading, sitting on top of the belt', () => {
  const out = chevronTransforms(model([[0, Math.PI / 2]]));
  expect(out.length).toBe(1);
  expect(out[0]!.yawRad).toBeCloseTo(Math.PI / 2, 5);
  // above the belt's top face (position.y + size.y/2)
  expect(out[0]!.position[1]).toBeGreaterThan(1.1);
});

test('ignores non-belt buildings and belts with no heading', () => {
  expect(chevronTransforms(model([])).length).toBe(0);
  // a heading keyed to the assembler must not produce a chevron
  expect(chevronTransforms(model([[1, 0]])).length).toBe(0);
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `bunx rstest run tests/scene/beltChevrons.test.ts 2>&1` — expected FAIL, module not found.

- [ ] **Step 3: Implement**

Create `src/scene/BeltChevrons.tsx`:

```tsx
import { useLayoutEffect, useRef } from 'react';
import { type InstancedMesh, Object3D } from 'three';
import { isBelt } from '../model/beltGraph';
import type { SceneModel } from '../model/layout';

const CHEVRON_SIZE = 0.42;

export interface ChevronTransform {
  position: [number, number, number];
  yawRad: number;
}

/**
 * One arrow per belt, sitting just above the belt's top face.
 *
 * Direction comes from the run topology rather than the belt's own yaw: the
 * game zeroes yaw when it serialises a belt, so the stored value says nothing
 * about which way cargo moves.
 */
export function chevronTransforms(model: SceneModel): ChevronTransform[] {
  const out: ChevronTransform[] = [];
  for (const inst of model.instances) {
    if (!isBelt(inst.itemId)) continue;
    const yawRad = model.beltHeadings.get(inst.index);
    if (yawRad === undefined) continue;
    out.push({
      position: [inst.position[0], inst.position[1] + inst.size[1] / 2 + 0.05, inst.position[2]],
      yawRad,
    });
  }
  return out;
}

export function BeltChevrons({ model }: { model: SceneModel }) {
  const meshRef = useRef<InstancedMesh>(null);
  const transforms = chevronTransforms(model);
  const count = transforms.length;

  useLayoutEffect(() => {
    const mesh = meshRef.current;
    if (!mesh) return;
    const dummy = new Object3D();
    transforms.forEach((t, i) => {
      dummy.position.set(t.position[0], t.position[1], t.position[2]);
      // Lie flat, then spin within that plane to point along the run.
      //
      // The -PI/2 z-term is not cosmetic. circleGeometry puts its first outer
      // vertex -- the arrow's apex -- at local +X, but the heading convention
      // is `atan2(dx, dz)`, whose zero points along +Z. Composing
      // rotation.set(-PI/2, 0, phi) maps local +X to world (cos phi, -sin phi),
      // so reaching the desired (sin yaw, cos yaw) requires phi = yaw - PI/2.
      // Using -yaw instead lands every arrow 90 degrees off, pointing across
      // the belt rather than along it, at every heading.
      dummy.rotation.set(-Math.PI / 2, 0, t.yawRad - Math.PI / 2);
      dummy.scale.setScalar(CHEVRON_SIZE);
      dummy.updateMatrix();
      mesh.setMatrixAt(i, dummy.matrix);
    });
    mesh.instanceMatrix.needsUpdate = true;
    mesh.computeBoundingSphere();
  }, [transforms]);

  if (count === 0) return null;

  return (
    <instancedMesh key={count} ref={meshRef} args={[undefined, undefined, count]} raycast={() => null}>
      {/* A 3-sided circle is a triangle -- an arrowhead without a custom geometry. */}
      <circleGeometry args={[1, 3]} />
      <meshBasicMaterial color="#dfe9ff" transparent opacity={0.75} depthWrite={false} />
    </instancedMesh>
  );
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `bunx rstest run tests/scene/beltChevrons.test.ts 2>&1` — expected PASS.

- [ ] **Step 5: Mount it**

In `src/scene/BlueprintCanvas.tsx`, add inside `<Canvas>`, after `<BuildingInstances .../>`:

```tsx
      <BeltChevrons model={sceneModel} />
```

- [ ] **Step 6: Full suite, lint, typecheck**

Run: `bun run test 2>&1`, `bun run lint`, `bun run typecheck`

- [ ] **Step 7: Commit**

```bash
git add src/scene/BeltChevrons.tsx src/scene/BlueprintCanvas.tsx tests/scene/beltChevrons.test.ts
git commit -m "feat(scene): show belt flow direction with chevrons"
```

---

### Task 10: Surface unresolved tags, retire the backlog, verify end to end

**Files:**
- Modify: `src/model/layout.ts`
- Modify: `src/ui/Toolbar.tsx`
- Modify: `docs/BACKLOG.md`
- Test: `tests/ui/` (Toolbar has no test file yet; add assertions to an existing UI test that renders the toolbar, or create `tests/ui/Toolbar.test.tsx`)

**Interfaces:**
- Consumes: `Catalog.tagIconName` (Task 2), `BuildingInstance.parameters` (Task 3).
- Produces: `SceneModel.unresolvedTagIds: number[]`.

`buildOverlays` skips tags it cannot resolve but does not report them (Task 6). The diagnostic is computed once here in `buildSceneModel`, which has both the belt parameters and the catalog in hand, and is the object `Toolbar` already reads.

- [ ] **Step 1: Write the failing test**

Create `tests/ui/Toolbar.test.tsx`, following the pattern in `tests/ui/InfoPanel.test.tsx` (which mocks `BlueprintProvider`):

```tsx
import { expect, rstest, test } from '@rstest/core';
import { render, screen } from '@testing-library/react';
import type { SceneModel } from '../../src/model/layout';
import { Toolbar } from '../../src/ui/Toolbar';

const sceneModel = {
  instances: [],
  beltRuns: [],
  beltHeadings: new Map(),
  unknownItemIds: [],
  unresolvedTagIds: [40001, 40002],
} as unknown as SceneModel;

// Toolbar returns "No blueprint loaded" and renders nothing else when
// `blueprint` is null, so the mock must supply one or the assertion can
// never pass.
const blueprint = {
  header: { shortDesc: 'Test', gameVersion: '0.10.34' },
  buildings: [],
  areas: [],
} as unknown as Blueprint;

rstest.mock('../../src/state/BlueprintProvider', () => ({
  useBlueprint: () => ({ blueprint, sceneModel, selectedIndex: null, select: () => {} }),
}));

test('reports unresolved belt tags', () => {
  render(<Toolbar />);
  expect(screen.getByText(/2 unrecognised belt tag/)).toBeDefined();
});
```

Import `type { Blueprint }` from `../../src/format/types`. `Toolbar` reads
`{ blueprint, sceneModel }` from `useBlueprint()` and early-returns on a null
blueprint — check the component before writing the mock rather than assuming
its shape.

Also add the model-level test to `tests/model/layout.test.ts`, since that is where the diagnostic is computed:

```ts
test('collects belt tag ids that resolve to no icon', () => {
  const bp = {
    buildings: [
      // 40001 is in the tech band, which is deliberately not extracted
      { ...beltBuilding(0), parameters: [40001, 0] },
      { ...beltBuilding(1), parameters: [1101, 0] },
    ],
    areas: [],
  } as unknown as Blueprint;

  const model = buildSceneModel(bp, catalog);
  expect(model.unresolvedTagIds).toEqual([40001]);
});
```

Build `beltBuilding(index)` as a local helper in the same shape as the `belt` helper in `tests/model/beltGraph.test.ts` (itemId 2001, all pose fields 0, `outputObjIdx: -1`), and make sure the file's `catalog` has item 1101 with a non-empty `iconName`.

- [ ] **Step 2: Run to verify they fail**

Run: `bunx rstest run tests/ui/Toolbar.test.tsx tests/model/layout.test.ts 2>&1` — expected FAIL: text not found, and `unresolvedTagIds` undefined.

- [ ] **Step 3: Compute the diagnostic in the model**

In `src/model/layout.ts`, add `unresolvedTagIds: number[]` to `SceneModel`, and after `beltRuns` is built:

```ts
  // Tag ids we cannot draw (tech icons are not extracted, and a future DSP
  // patch could add a band). Reported rather than silently skipped, so a gap
  // looks like a gap instead of an untagged belt.
  const unresolvedTags = new Set<number>();
  for (const inst of instances) {
    // isBelt gate, exactly as in buildOverlays: only belts carry belt tags.
    // Without it, a sorter's stack-size word and a station's slot config are
    // read as tag ids -- falk-v7-mall has ZERO tagged belts yet would report
    // "3 unrecognised belt tag(s)" from sorter values 1, 2 and 3. A diagnostic
    // that fires on every blueprint hides the one case it exists to surface.
    if (!isBelt(inst.itemId)) continue;
    const tagId = inst.parameters[0];
    if (tagId !== undefined && tagId > 0 && !catalog.tagIconName(tagId)) unresolvedTags.add(tagId);
  }
```

Return `unresolvedTagIds: [...unresolvedTags].sort((a, b) => a - b)`.

- [ ] **Step 4: Show it**

In `src/ui/Toolbar.tsx`, alongside the existing `unknownItemIds` warning:

```tsx
      {sceneModel && sceneModel.unresolvedTagIds.length > 0 && (
        <span className="warn">
          {sceneModel.unresolvedTagIds.length} unrecognised belt tag(s)
        </span>
      )}
```

- [ ] **Step 5: Run to verify they pass**

Run: `bunx rstest run tests/ui/Toolbar.test.tsx tests/model/layout.test.ts 2>&1` — expected PASS.

- [ ] **Step 6: Retire the backlog entries**

Edit `docs/BACKLOG.md`: delete item 1 (Belt icons) and item 2 (Belt direction chevrons) in full, and renumber the remaining "Decode remaining parameter payloads" entry to item 1. That entry **stays** — this work decodes only the belt parameter block, not station/splitter/monitor payloads. If the file would be left with only that one entry, keep the file and its header.

- [ ] **Step 7: Full verification**

```bash
bun run test 2>&1 | tee /tmp/belt-test.log
grep -inE "error|warn|abort|ECONNRESET|hang up|unhandled|reject" /tmp/belt-test.log
bun run lint && bun run typecheck && bun run build
```

Expected: every command exits 0, and the grep returns nothing. A zero exit code alone is not sufficient evidence — read the output.

- [ ] **Step 8: Visual check in the browser**

Start the dev server, load two fixtures, and confirm by eye:

- `tests/fixtures/factory-endgame-distribution-hub.txt` — 47 tagged belts should show icons.
- `tests/fixtures/factory-quick-start-step-3-red-cube.txt` — 36 tagged belts, and it is the only fixture with non-zero counts (90, 180, 360), so digits must appear.
- `tests/fixtures/falk-v7-mall-full.txt` — 280 belts in cycles must render chevrons without hanging, and its 55 filtered end sorters should produce endpoint icons.

Confirm chevrons point *along* each run rather than across it. If they are rotated 90 degrees, the fix is the sign or axis in `chevronTransforms`/`BeltChevrons`, not in `computeBeltHeadings` — that function is unit-tested.

- [ ] **Step 9: Commit**

```bash
git add src/model/layout.ts src/ui/Toolbar.tsx docs/BACKLOG.md tests/ui/Toolbar.test.tsx
git commit -m "feat(ui): report unrecognised belt tags; retire belt backlog items"
```

---

## Notes for the implementer

- **Do not trust the fixture numbers blindly.** Several assertions in Tasks 4 and 5 encode measurements taken before implementation. If one disagrees with your code, work out which is wrong before changing either. The 12-s-purple run count in particular is a *prediction* (23), flagged as such in the spec.
- **Belt yaw is useless.** The game sets `yaw = 0f` for belts on serialisation, so direction must come from topology. If chevrons all point the same way, that is the bug.
- **`parameters` is `[signalId, count]` or empty.** Never a different length — assert if you ever see one, rather than coping silently.
