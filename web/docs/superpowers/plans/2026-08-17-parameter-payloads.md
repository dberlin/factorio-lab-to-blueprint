# Parameter Payload Decoding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decode every building's parameter block so the info panel shows real settings instead of `"N parameter words"`, and feed station storage into belt-content inference.

**Architecture:** The extractor learns each model's `BuildingType` by joining the prefabs' per-type `*Desc` marker components to `ModelProto` by prefab-path basename — the same join it already does for `SlotConfig`. `catalog.buildingTypeFor` becomes the single place anything asks what a building is; `params.ts` dispatches on that to a per-type decoder; the station block gets its own module because it is the only one with internal structure.

**Tech Stack:** TypeScript, React 19 + React Compiler, react-three-fiber 9 / three 0.185, zod/mini, rstest + happy-dom, biome + eslint, bun. Asset extraction is Python via `uv` (UnityPy + Pillow).

**Spec:** `docs/superpowers/specs/2026-08-17-parameter-payloads-design.md`

## Global Constraints

- `src/format/`, `src/model/`, `src/server/` must import neither React nor three.js. Enforced by `tests/architecture.test.ts` — do not weaken that test.
- React Compiler is on: no hand-written `useMemo`/`useCallback` for pure derivations.
- **No test may perform network I/O**, and no unit test may read `public/assets/*.json` — that is gitignored build output produced by `bun run extract-assets`. happy-dom resolves relative URLs against `http://localhost:3000`, rsbuild's own dev port, so an unmocked `fetch` silently hits the dev server.
- Verification means reading the whole output, not the pass count. Run `bun run test 2>&1` and scan for `error`, `warn`, `abort`, `unhandled`, `reject` — a zero exit code with a passing count has previously coexisted with real stderr errors in this repo. Confirm the suite is green with **nothing listening on port 3000**.
- `bun run lint` runs **both** biome and eslint. Both must be clean. Also `bun run typecheck` and `bun run build`.
- **Every decoder must tolerate a block shorter than the current game writes.** Splitters appear in our fixtures with both 4 and 6 words; Depot Mk.I with both 1 and 110. Indexing past the end yields `undefined` — omit the row rather than printing a wrong value.
- Station booleans are **1 / −1**, not 1 / 0. Test them with `> 0`; `!== 0` is wrong.
- Enum values, verbatim from the DLL: `ELogisticStorage` = 0 None, 1 Supply, 2 Demand. `IODir` = 0 None, 1 Output, 2 Input.
- `storageIdx` is **1-based**; 0 means unassigned.
- Belt tag **rendering in the 3D scene** lives in `overlays.ts` — do not move or duplicate that. The info panel is a separate surface and does need a `Belt` decoder: without one, `Belt` is a known type with no entry, so it falls into the unknown branch and the panel claims "2 word(s)" for a block we fully decode. Both read the same `[signalId, count]` pair.
- Commit after every task.

---

### Task 1: Extract a BuildingType per model

**Files:**
- Modify: `scripts/extract_assets.py`

**Interfaces:**
- Consumes: nothing.
- Produces: each entry of `public/assets/models.json` gains `"buildingType": "<Type>"` where the model's prefab carries a `*Desc` component.

Verified against the game install before this plan was written: 46 prefab GameObjects carry a `*Desc`, all 46 resolve to a GameObject name, all 46 join to a `ModelProto` by `PrefabPath` basename, and **all 46 already appear in `models.json`** (they all have `SlotConfig` boxes), so no entry has to be created that did not exist.

- [ ] **Step 1: Collect the `*Desc` components in the existing object sweep**

Near the top of the module, beside the other constants:

```python
# Prefabs carry a per-type marker component rather than a single PrefabDesc,
# which is not serialised anywhere in the loose asset files. These are the
# types whose parameter blocks we decode.
DESC_TO_TYPE = {
    "StationDesc": "Station",
    "MonitorDesc": "Monitor",
    "StorageDesc": "Storage",
    "BattleBaseDesc": "BattleBase",
    "TankDesc": "Tank",
    "AssemblerDesc": "Assembler",
    "InserterDesc": "Inserter",
    "BeltDesc": "Belt",
    "EjectorDesc": "Ejector",
    "LabDesc": "Lab",
    "MarkerDesc": "Marker",
    "DispenserDesc": "Dispenser",
    "TurretDesc": "Turret",
    "SiloDesc": "Silo",
    "SplitterDesc": "Splitter",
    "MinerDesc": "Miner",
}

# Two prefabs legitimately carry two markers: the Orbital/Vein Collector is
# Miner + Station, and the Battlefield Analysis Base is BattleBase + Storage.
# The game's own export checks Station after Miner and BattleBase after
# Storage, so the later check wins. Mirror that rather than inventing a rule.
DESC_PRECEDENCE = {"Station": 1, "BattleBase": 1}
```

In `main()`, where the object loop already collects `SlotConfig` into `slot_objs`, add a sibling collection. The existing branch reads:

```python
        elif cls == "SlotConfig":
            slot_objs.append(o)
```

Add immediately after it:

```python
        elif cls in DESC_TO_TYPE:
            desc_objs.append((o, DESC_TO_TYPE[cls]))
```

and initialise `desc_objs: list[tuple] = []` next to `slot_objs = []`.

- [ ] **Step 2: Join the markers to prefab names**

Directly after the `by_prefab` loop that builds the SlotConfig join, add:

```python
    # Same join as the boxes above: component -> GameObject name -> ModelProto
    # PrefabPath basename. Verified: 46 marker prefabs, 46 named, 46 matched.
    type_by_prefab: dict[str, str] = {}
    marker_count: dict[str, int] = {}
    for o, type_name in desc_objs:
        try:
            go = o.read(check_read=False).m_GameObject
        except Exception:
            continue
        nm = gonames.get(go.path_id) if go else None
        if not nm:
            continue
        marker_count[nm] = marker_count.get(nm, 0) + 1
        prev = type_by_prefab.get(nm)
        # Precedence is order-independent: whichever marker is read first,
        # Station beats Miner and BattleBase beats Storage.
        if prev is None or DESC_PRECEDENCE.get(type_name, 0) > DESC_PRECEDENCE.get(prev, 0):
            type_by_prefab[nm] = type_name

    ambiguous = sorted(nm for nm, n in marker_count.items() if n > 1)
```

**Power buildings have no marker component of their own.** Exchanger,
Gamma, ArtificialStar and Geothermal are all distinguished by *fields on
`PowerDesc`*, exactly as the game's own export does (`genPool[].gamma`,
`fuelMask == 4`, `geothermal`, and a non-zero `powerExcId`). Without this,
77 real buildings in our fixtures stay untyped — 45 Energy Exchangers and
32 Artificial Stars — and the decoders for those four types are dead code.

Collect `PowerDesc` alongside the markers (add `elif cls == "PowerDesc":
power_objs.append(o)` to the same object loop, and `power_objs: list = []`
beside `desc_objs`), then derive the type after the marker join:

```python
    # Exactly four prefabs match, one per type, and they are mutually
    # exclusive: energy-exchanger, ray-receiver, fusion-reactor (fuelMask 4)
    # and geothermal-power-station. A marker component would be tidier, but
    # the game distinguishes these by PowerDesc fields and so must we.
    pd_nodes = gen.get_nodes_up("Assembly-CSharp", "PowerDesc")
    power_conflicts: list[str] = []
    for o in power_objs:
        try:
            d = o.read_typetree(pd_nodes)
            go = o.read(check_read=False).m_GameObject
        except Exception:
            continue
        nm = gonames.get(go.path_id) if go else None
        if not nm or nm in type_by_prefab:
            continue
        signals = [
            ("Exchanger", bool(d.get("exchanger"))),
            ("Gamma", bool(d.get("gamma"))),
            ("ArtificialStar", d.get("fuelMask") == 4),
            ("Geothermal", bool(d.get("geothermal"))),
        ]
        hits = [name for name, on in signals if on]
        # The if/elif ordering below would silently pick one of two truthy
        # signals. The marker join fails loudly on an unexpected ambiguity;
        # this must too, or a content patch that sets two fields mistypes a
        # building with nothing to catch it -- the MIN_MODELS_WITH_TYPE floor
        # detects undercounting, never mistyping.
        if len(hits) > 1:
            power_conflicts.append(f"{nm} ({', '.join(hits)})")
        if hits:
            type_by_prefab[nm] = hits[0]
```

The `nm in type_by_prefab` guard keeps a real marker winning over a power
field, so this can only add types, never override one.

`marker_count` is tallied here rather than recomputed later: counting in a
second pass would mean re-reading every component and dereferencing
`m_GameObject` again, which can be `None`.

- [ ] **Step 3: Attach the type to each model entry**

In the `models` loop, after the `size`/`center` dict is built, add the type when the prefab has one:

```python
            entry = {
                "prefab": prefab,
                "center": [round(c["x"], 4), round(c["y"], 4), round(c["z"], 4)],
                "size": [round(s["x"], 4), round(s["y"], 4), round(s["z"], 4)],
            }
            building_type = type_by_prefab.get(prefab)
            if building_type:
                entry["buildingType"] = building_type
            models[str(m["ID"])] = entry
```

Replace the existing `models[str(m["ID"])] = { ... }` assignment with the above; do not leave both.

- [ ] **Step 4: Assert the join, including the two known ambiguities**

The extractor asserts invariants rather than trusting name-equality joins — that discipline caught a wrong splitter model earlier in this project. Add beside the existing `floor(...)` calls:

```python
    typed = [k for k, v in models.items() if v.get("buildingType")]
    floor(len(typed), MIN_MODELS_WITH_TYPE, "models with a building type")

    if len(ambiguous) > 2:
        problems.append(
            f"{len(ambiguous)} prefabs carry more than one *Desc marker "
            f"({ambiguous}); only the Orbital Collector and Battlefield "
            "Analysis Base are known to, so a new ambiguity needs a "
            "precedence rule in DESC_PRECEDENCE before it can be trusted."
        )
    if power_conflicts:
        problems.append(
            f"{len(power_conflicts)} power prefabs set more than one type "
            f"signal ({power_conflicts}); the exchanger/gamma/fuelMask/"
            "geothermal fields are assumed mutually exclusive, and the "
            "if/elif chain would silently pick one."
        )
```

and a constant beside the other floors:

```python
MIN_MODELS_WITH_TYPE = 48
```

44 rather than 46, matching the file's stated convention of setting floors a little below the known-good value so a content patch that adds buildings does not trip them.

- [ ] **Step 5: Run the extractor and verify**

Run: `bun run extract-assets`

Then check the join landed:

```bash
jq '[to_entries[] | select(.value.buildingType)] | length' public/assets/models.json
jq '{m35:.["35"].buildingType, m38:.["38"].buildingType, m41:.["41"].buildingType, m49:.["49"].buildingType, m51:.["51"].buildingType, m256:.["256"].buildingType, m453:.["453"].buildingType}' public/assets/models.json
```

Expected: `50` (46 marker-typed + 4 power-typed), then `{"m35":"Belt","m38":"Splitter","m41":"Inserter","m49":"Station","m51":"Storage","m256":"Station","m453":"BattleBase"}`.

Models 256 and 453 must show the *winning* type (Station, BattleBase), not Miner or Storage. If either shows the loser, the precedence in Step 2 is inverted.

- [ ] **Step 6: Commit**

```bash
git add scripts/extract_assets.py
git commit -m "feat(assets): classify each model by BuildingType"
```

`public/assets/` is gitignored, so only the script is staged.

---

### Task 2: Expose the building type through the catalog

**Files:**
- Modify: `src/model/schemas.ts`
- Modify: `src/model/catalog.ts`
- Test: `tests/model/catalog.test.ts`

**Interfaces:**
- Consumes: `models.json` entries with `buildingType` (Task 1).
- Produces: `Catalog.buildingTypeFor(modelIndex: number, itemId: number): string | undefined`, and `ModelBox.buildingType?: string`.

- [ ] **Step 1: Write the failing test**

Add to `tests/model/catalog.test.ts`:

```ts
test('buildingTypeFor resolves by modelIndex, falling back to the item default', () => {
  const c = buildCatalog({
    items: [
      { id: 2104, name: 'Interstellar Logistics Station', iconName: 'station',
        gridIndex: 1, modelIndex: 50, canBuild: true, color: 1 },
    ],
    models: {
      '50': { prefab: 'station-2', size: [1, 1, 1], center: [0, 0, 0], buildingType: 'Station' },
      '38': { prefab: 'splitter', size: [1, 1, 1], center: [0, 0, 0], buildingType: 'Splitter' },
      '99': { prefab: 'untyped', size: [1, 1, 1], center: [0, 0, 0] },
    },
    recipes: [],
  });

  // The record's own modelIndex wins, matching buildSceneModel's box lookup.
  expect(c.buildingTypeFor(38, 2104)).toBe('Splitter');
  // Falls back to the item's default model when the record's model is unknown.
  expect(c.buildingTypeFor(4242, 2104)).toBe('Station');
  // A model with a box but no type resolves to undefined, not a guess.
  expect(c.buildingTypeFor(99, 9999)).toBeUndefined();
  expect(c.buildingTypeFor(4242, 9999)).toBeUndefined();
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `bunx rstest run tests/model/catalog.test.ts 2>&1`
Expected: FAIL — `buildingTypeFor is not a function`.

- [ ] **Step 3: Add the schema field**

In `src/model/schemas.ts`, extend `ModelBoxSchema`:

```ts
export const ModelBoxSchema = z.object({
  prefab: z.string(),
  size: vec3,
  center: vec3,
  // Present only for models whose prefab carries a *Desc marker; the
  // extractor emits it for 50 of them. Optional because most models are
  // scenery, not buildings.
  buildingType: z.optional(z.string()),
});
```

- [ ] **Step 4: Implement the resolver**

In `src/model/catalog.ts`, add to the `Catalog` interface:

```ts
  /**
   * The game's BuildingType for a record, which selects its parameter
   * layout. Resolved through modelIndex first, mirroring the game's own
   * `LDB.models.Select(modelIndex).prefabDesc` and this codebase's existing
   * `catalog.model(modelIndex) ?? catalog.boxForItem(itemId)` precedence.
   */
  buildingTypeFor(modelIndex: number, itemId: number): string | undefined;
```

and to the returned object:

```ts
    buildingTypeFor(modelIndex, itemId) {
      const byModel = models[String(modelIndex)]?.buildingType;
      if (byModel) return byModel;
      const it = itemById.get(itemId);
      return it ? models[String(it.modelIndex)]?.buildingType : undefined;
    },
```

- [ ] **Step 5: Run tests, lint, typecheck**

Run: `bunx rstest run tests/model/catalog.test.ts 2>&1` — expected PASS.
Run: `bun run test 2>&1`, `bun run lint`, `bun run typecheck`.

- [ ] **Step 6: Commit**

```bash
git add src/model/schemas.ts src/model/catalog.ts tests/model/catalog.test.ts
git commit -m "feat(model): resolve a building's type from the catalog"
```

---

### Task 3: Station block decoder

The station block is the only one with internal structure, so it gets its own module rather than swamping the other nineteen decoders in `params.ts`.

**Files:**
- Create: `src/model/stationParams.ts`
- Test: `tests/model/stationParams.test.ts`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `interface StationStorageSlot { slot: number; itemId: number; localLogic: number; remoteLogic: number; max: number; keepMode: number; keepIncRatio: number }`
  - `interface StationBeltSlot { slot: number; dir: number; storageIdx: number }`
  - `interface StationSettings { workEnergyPerTick: number; tripRangeDrones: number; tripRangeShips: number; includeOrbitCollector: boolean; warpEnableDist: number; warperNecessary: boolean; deliveryDrones: number; deliveryShips: number; pilerCount: number; minerSpeed: number; droneAutoReplenish: boolean; shipAutoReplenish: boolean; routePriority: number }`
  - `interface StationParams { storage: StationStorageSlot[]; beltSlots: StationBeltSlot[]; settings: StationSettings | undefined }`
  - `parseStationParams(p: readonly number[]): StationParams`
  - `LOGISTIC_STORAGE: readonly string[]`, `IO_DIR: readonly string[]`

- [ ] **Step 1: Write the failing tests**

Create `tests/model/stationParams.test.ts`:

```ts
import { expect, test } from '@rstest/core';
import { parseStationParams } from '../../src/model/stationParams';

/** A 2048-word block with the given words set, as the game writes it. */
function block(set: Record<number, number>): number[] {
  const p = new Array(2048).fill(0);
  for (const [k, v] of Object.entries(set)) p[Number(k)] = v;
  return p;
}

test('reads storage slots at stride 6 from offset 0', () => {
  const p = block({
    0: 1101, 1: 1, 2: 2, 3: 3500, 4: 0, 5: 50000, // slot 0
    6: 1104, 7: 2, 8: 0, 9: 100, 10: 1, 11: 0, //    slot 1
  });
  const { storage } = parseStationParams(p);
  expect(storage.length).toBe(2);
  expect(storage[0]).toEqual({
    slot: 0, itemId: 1101, localLogic: 1, remoteLogic: 2,
    max: 3500, keepMode: 0, keepIncRatio: 0.5,
  });
  expect(storage[1]!.itemId).toBe(1104);
  expect(storage[1]!.localLogic).toBe(2);
});

test('an empty storage slot is omitted rather than reported as item 0', () => {
  // Only slot 2 is populated; 0 and 1 are untouched zeros.
  const { storage } = parseStationParams(block({ 12: 1005, 15: 200 }));
  expect(storage.length).toBe(1);
  expect(storage[0]!.slot).toBe(2);
});

test('the last storage slot stops before the belt-slot region', () => {
  // Slot 31 is the last: 31 * 6 = 186, and its final word is 191.
  const { storage } = parseStationParams(block({ 186: 1006, 189: 4000 }));
  expect(storage.length).toBe(1);
  expect(storage[0]!.slot).toBe(31);
  expect(storage[0]!.max).toBe(4000);
});

test('reads belt slots at stride 4 from offset 192', () => {
  const p = block({ 192: 1, 193: 2, 196: 2, 197: 0 });
  const { beltSlots } = parseStationParams(p);
  expect(beltSlots.length).toBe(2);
  expect(beltSlots[0]).toEqual({ slot: 0, dir: 1, storageIdx: 2 });
  // dir Input with no storage assigned is still a populated slot.
  expect(beltSlots[1]).toEqual({ slot: 1, dir: 2, storageIdx: 0 });
});

test('reads settings at offset 320, unscaling and decoding 1/-1 booleans', () => {
  const p = block({
    320: 5000000, 321: -100000000, 322: 240000000, 323: 1, 324: 20000,
    325: -1, 326: 100, 327: 20, 328: 0, 329: 0, 330: 1, 331: 1, 334: 3,
  });
  const { settings } = parseStationParams(p);
  expect(settings).toBeDefined();
  expect(settings!.workEnergyPerTick).toBe(5000000);
  expect(settings!.tripRangeDrones).toBeCloseTo(-1, 6); // / 1e8
  expect(settings!.tripRangeShips).toBe(24000000000); //  * 100
  expect(settings!.includeOrbitCollector).toBe(true); //   1
  expect(settings!.warperNecessary).toBe(false); //       -1, not 0
  expect(settings!.deliveryDrones).toBe(100);
  expect(settings!.droneAutoReplenish).toBe(true);
  expect(settings!.routePriority).toBe(3);
});

test('a short block yields no settings rather than reading undefined', () => {
  const { storage, beltSlots, settings } = parseStationParams([1101, 1, 0, 500, 0, 0]);
  expect(storage.length).toBe(1);
  expect(beltSlots.length).toBe(0);
  expect(settings).toBeUndefined();
});
```

- [ ] **Step 2: Run to verify they fail**

Run: `bunx rstest run tests/model/stationParams.test.ts 2>&1`
Expected: FAIL — cannot find module `stationParams`.

- [ ] **Step 3: Implement**

Create `src/model/stationParams.ts`:

```ts
/**
 * The logistics station parameter block.
 *
 * The game allocates 2048 words (BuildingParameters.cs:1293-1350) but only
 * the first ~384 are meaningful; the rest is zero padding, which is why
 * stations dominate blueprint size. Three fixed regions, read by offset
 * rather than by walking the array.
 */

export const STORAGE_OFFSET = 0;
export const STORAGE_STRIDE = 6;
export const STORAGE_COUNT = 32;
export const BELT_OFFSET = 192;
export const BELT_STRIDE = 4;
export const BELT_COUNT = 32;
export const SETTINGS_OFFSET = 320;

/** ELogisticStorage, verbatim from the DLL. */
export const LOGISTIC_STORAGE = ['None', 'Supply', 'Demand'] as const;
/** IODir, verbatim from the DLL. */
export const IO_DIR = ['None', 'Output', 'Input'] as const;

export interface StationStorageSlot {
  slot: number;
  itemId: number;
  localLogic: number;
  remoteLogic: number;
  max: number;
  keepMode: number;
  keepIncRatio: number;
}

export interface StationBeltSlot {
  slot: number;
  dir: number;
  /** 1-based into `storage`; 0 means unassigned. */
  storageIdx: number;
}

export interface StationSettings {
  workEnergyPerTick: number;
  tripRangeDrones: number;
  tripRangeShips: number;
  includeOrbitCollector: boolean;
  warpEnableDist: number;
  warperNecessary: boolean;
  deliveryDrones: number;
  deliveryShips: number;
  pilerCount: number;
  minerSpeed: number;
  droneAutoReplenish: boolean;
  shipAutoReplenish: boolean;
  routePriority: number;
}

export interface StationParams {
  storage: StationStorageSlot[];
  beltSlots: StationBeltSlot[];
  settings: StationSettings | undefined;
}

const at = (p: readonly number[], i: number): number => p[i] ?? 0;

export function parseStationParams(p: readonly number[]): StationParams {
  const storage: StationStorageSlot[] = [];
  for (let s = 0; s < STORAGE_COUNT; s++) {
    const o = STORAGE_OFFSET + s * STORAGE_STRIDE;
    const itemId = at(p, o);
    // An unconfigured slot is all zeros; reporting it as "item 0" would be
    // noise on every station, most of which use far fewer than 32 slots.
    if (itemId <= 0) continue;
    storage.push({
      slot: s,
      itemId,
      localLogic: at(p, o + 1),
      remoteLogic: at(p, o + 2),
      max: at(p, o + 3),
      keepMode: at(p, o + 4),
      keepIncRatio: at(p, o + 5) / 100000,
    });
  }

  const beltSlots: StationBeltSlot[] = [];
  for (let s = 0; s < BELT_COUNT; s++) {
    const o = BELT_OFFSET + s * BELT_STRIDE;
    const dir = at(p, o);
    const storageIdx = at(p, o + 1);
    if (dir === 0 && storageIdx === 0) continue;
    beltSlots.push({ slot: s, dir, storageIdx });
  }

  // A block that never reaches the settings region carries none. Older
  // blueprints and shorter variants are real: our own fixtures hold both
  // 4- and 6-word splitters and both 1- and 110-word depots.
  const settings =
    p.length > SETTINGS_OFFSET
      ? {
          workEnergyPerTick: at(p, SETTINGS_OFFSET),
          tripRangeDrones: at(p, SETTINGS_OFFSET + 1) / 1e8,
          tripRangeShips: at(p, SETTINGS_OFFSET + 2) * 100,
          // 1 / -1, not 1 / 0 -- `!== 0` would report -1 as true.
          includeOrbitCollector: at(p, SETTINGS_OFFSET + 3) > 0,
          warpEnableDist: at(p, SETTINGS_OFFSET + 4),
          warperNecessary: at(p, SETTINGS_OFFSET + 5) > 0,
          deliveryDrones: at(p, SETTINGS_OFFSET + 6),
          deliveryShips: at(p, SETTINGS_OFFSET + 7),
          pilerCount: at(p, SETTINGS_OFFSET + 8),
          minerSpeed: at(p, SETTINGS_OFFSET + 9),
          droneAutoReplenish: at(p, SETTINGS_OFFSET + 10) > 0,
          shipAutoReplenish: at(p, SETTINGS_OFFSET + 11) > 0,
          routePriority: at(p, SETTINGS_OFFSET + 14),
        }
      : undefined;

  return { storage, beltSlots, settings };
}
```

- [ ] **Step 4: Run to verify they pass**

Run: `bunx rstest run tests/model/stationParams.test.ts 2>&1` — expected PASS.

- [ ] **Step 5: Check it against a real station**

Run this one-off. It reads gitignored `public/assets/*.json`, which is fine from the shell but never inside a unit test:

```bash
bun -e '
import {readFileSync} from "node:fs";
import {parseBlueprint} from "./src/format/index";
import {buildCatalog} from "./src/model/catalog";
import {parseStationParams} from "./src/model/stationParams";
const j=(p)=>JSON.parse(readFileSync(p,"utf8"));
const cat=buildCatalog({items:j("public/assets/items.json"),models:j("public/assets/models.json"),recipes:j("public/assets/recipes.json"),tags:j("public/assets/tags.json")});
const bp=parseBlueprint(readFileSync("tests/fixtures/factory-endgame-distribution-hub.txt","utf8"));
const st=bp.buildings.find(b=>b.itemId===2104);
const s=parseStationParams(st.parameters);
console.log("storage:", s.storage.map(x=>`${cat.item(x.itemId)?.name} local=${x.localLogic} max=${x.max}`));
console.log("beltSlots:", s.beltSlots.map(x=>`${x.slot}:dir${x.dir}->idx${x.storageIdx}`).join(" "));
console.log("drones:", s.settings.deliveryDrones, "ships:", s.settings.deliveryShips);
'
```

Expected: five storage slots — Conveyor Belt Mk.III (max 3500), Pile Sorter (1500), Splitter (100), Re-composing Assembler (200), Negentropy Smelter (200), all `local=1`; six belt slots; 100 drones and 20 ships. If the storage items come out as anything else, the offsets are wrong — stop and report rather than adjusting the test.

- [ ] **Step 6: Commit**

```bash
git add src/model/stationParams.ts tests/model/stationParams.test.ts
git commit -m "feat(model): decode the station parameter block"
```

---

### Task 4: Per-type parameter decoders

**Files:**
- Modify: `src/model/params.ts`
- Modify: `tests/model/params.test.ts` — **it already exists**, with two tests that this task deliberately invalidates (see Step 0)

**Interfaces:**
- Consumes: `Catalog.buildingTypeFor` (Task 2), `parseStationParams` (Task 3).
- Produces: `describeParameters(b, catalog)` keeps its signature and `ParamRow` shape, but returns decoded rows.

- [ ] **Step 0: Retire the two tests this task supersedes**

`tests/model/params.test.ts` currently pins the behaviour we are replacing.
Two tests must go, and they are the *point* of the task rather than
collateral — delete them rather than bending them:

- `'station parameter blocks are labelled as station slots, not generic words'`
  asserts `Station slots` → `'4 parameter words'`. Stations now report their
  actual contents.
- `'a non-station parameter block falls back to a raw word count'` uses
  itemId 2303, an Assembling Machine — which is `BuildingType.Assembler`, so
  it now decodes to a `Proliferator` row instead of falling back.

Keep every other test in the file: the recipe, filter, output/input and
empty-block cases are unaffected and still describe correct behaviour.

The generic fallback itself is *not* being removed — it still applies to
buildings with no known type. Its coverage moves to the new
`'an unknown building type falls back to a word count rather than guessing'`
test in Step 1, which uses an itemId the catalog cannot type.

Also extend the file's existing inline catalog with the models the new
tests need — the file builds its catalog near the top; add `buildingType`
entries for models 38 (Splitter), 50 (Station) and 51 (Storage), and items
2020, 2104 and 2101 pointing at them.

**Row labels must be unique within a building.** `InfoPanel` renders rows keyed by `row.label`; duplicate labels collide as React keys. A station with five storage slots therefore emits `Supplies 1`, `Supplies 2`, … not five rows labelled `Supplies`. Task 5 also hardens the key, but the labels should be genuinely distinct regardless.

- [ ] **Step 1: Write the failing tests**

Add these to the existing `tests/model/params.test.ts`, alongside the tests
Step 0 left in place. The file already imports `describeParameters` and
builds a catalog; the block below shows the catalog and helper shape the new
tests assume, so reconcile it with what is already there rather than
declaring a second one.

```ts
import { expect, test } from '@rstest/core';
import type { BlueprintBuilding } from '../../src/format/types';
import { buildCatalog } from '../../src/model/catalog';
import { describeParameters } from '../../src/model/params';

const catalog = buildCatalog({
  items: [
    { id: 1101, name: 'Iron Ingot', iconName: 'iron-plate', gridIndex: 1,
      modelIndex: 0, canBuild: false, color: 1 },
    { id: 2020, name: 'Splitter', iconName: 'splitter', gridIndex: 2,
      modelIndex: 38, canBuild: true, color: 2 },
    { id: 2104, name: 'Interstellar Logistics Station', iconName: 'station',
      gridIndex: 3, modelIndex: 50, canBuild: true, color: 3 },
    { id: 2101, name: 'Depot Mk.I', iconName: 'depot', gridIndex: 4,
      modelIndex: 51, canBuild: true, color: 4 },
  ],
  models: {
    '38': { prefab: 'splitter', size: [1, 1, 1], center: [0, 0, 0], buildingType: 'Splitter' },
    '50': { prefab: 'station-2', size: [1, 1, 1], center: [0, 0, 0], buildingType: 'Station' },
    '51': { prefab: 'depot', size: [1, 1, 1], center: [0, 0, 0], buildingType: 'Storage' },
  },
  recipes: [],
});

function building(over: Partial<BlueprintBuilding>): BlueprintBuilding {
  return {
    index: 0, areaIndex: 0, itemId: 2020, modelIndex: 38,
    x: 0, y: 0, z: 0, x2: 0, y2: 0, z2: 0,
    yaw: 0, yaw2: 0, tilt: 0, tilt2: 0, pitch: 0, pitch2: 0,
    outputObjIdx: -1, inputObjIdx: -1,
    outputToSlot: 0, inputFromSlot: 0, outputFromSlot: 0, inputToSlot: 0,
    outputOffset: 0, inputOffset: 0,
    recipeId: 0, filterId: 0, parameters: [], content: null,
    ...over,
  };
}

const labels = (rows: { label: string }[]) => rows.map((r) => r.label);
const find = (rows: { label: string; value: string }[], label: string) =>
  rows.find((r) => r.label === label)?.value;

test('a station reports its storage slots by name and logistic role', () => {
  const p = new Array(2048).fill(0);
  p[0] = 1101; p[1] = 1; p[2] = 2; p[3] = 3500; // supply iron, demand remotely
  const rows = describeParameters(building({ itemId: 2104, modelIndex: 50, parameters: p }), catalog);
  const v = find(rows, 'Supplies 1');
  expect(v).toContain('Iron Ingot');
  expect(v).toContain('3500');
});

test('station row labels are unique so they can key a list', () => {
  const p = new Array(2048).fill(0);
  p[0] = 1101; p[1] = 1; p[3] = 100;
  p[6] = 2020; p[7] = 1; p[9] = 200;
  const rows = describeParameters(building({ itemId: 2104, modelIndex: 50, parameters: p }), catalog);
  expect(new Set(labels(rows)).size).toBe(labels(rows).length);
});

test('a splitter reports its per-belt priority flags', () => {
  const rows = describeParameters(building({ parameters: [1, 0, 0, 1, 0, 0] }), catalog);
  expect(find(rows, 'Priority belts')).toBe('A, D');
});

test('a 4-word splitter decodes without reading past the end', () => {
  // Our own fixtures hold both 4- and 6-word splitters.
  const rows = describeParameters(building({ parameters: [0, 1, 0, 0] }), catalog);
  expect(find(rows, 'Priority belts')).toBe('B');
});

test('an unknown building type falls back to a word count rather than guessing', () => {
  const rows = describeParameters(
    building({ itemId: 9999, modelIndex: 4242, parameters: [7, 7, 7] }),
    catalog,
  );
  expect(find(rows, 'Parameters')).toBe('3 word(s)');
});

test('a typed building with an empty block emits no parameter row', () => {
  const rows = describeParameters(building({ parameters: [] }), catalog);
  expect(labels(rows).some((l) => l.startsWith('Priority') || l === 'Parameters')).toBe(false);
});
```

- [ ] **Step 2: Run to verify they fail**

Run: `bunx rstest run tests/model/params.test.ts 2>&1`
Expected: FAIL — the station case reports `"2048 parameter words"`, not `Supplies 1`.

- [ ] **Step 3: Implement the dispatch**

Rewrite the parameter portion of `src/model/params.ts`. Keep the existing recipe / filter / output / input / content rows exactly as they are; replace only the two `parameters.length` branches at the end.

Add the imports:

```ts
import { IO_DIR, LOGISTIC_STORAGE, parseStationParams } from './stationParams';
```

Delete the `isStation` const — `catalog.buildingTypeFor` replaces it.

Add above `describeParameters`:

```ts
const at = (p: readonly number[], i: number): number | undefined => p[i];
const bool = (v: number | undefined): string | undefined =>
  v === undefined ? undefined : v > 0 ? 'yes' : 'no';
const enumName = (table: readonly string[], v: number | undefined): string =>
  v === undefined ? '?' : (table[v] ?? `#${v}`);

/**
 * One decoder per BuildingType, mirroring BuildingParameters.ToParamsArray.
 *
 * Every decoder must tolerate a block shorter than the current game writes:
 * our own fixtures hold 4- and 6-word splitters and 1- and 110-word depots,
 * because older blueprints wrote fewer words. Reading past the end yields
 * undefined, so omit the row rather than printing a wrong value.
 */
const DECODERS: Record<string, (p: readonly number[], catalog: Catalog) => ParamRow[]> = {
  Station(p, catalog) {
    const { storage, beltSlots, settings } = parseStationParams(p);
    const rows: ParamRow[] = [];
    storage.forEach((s, i) => {
      const name = catalog.item(s.itemId)?.name ?? `#${s.itemId}`;
      // Label by role so the panel reads as intent, not as a slot dump.
      // Three-way, not a Demand/else ternary: localLogic 0 is None, a real
      // configuration where the slot is passive locally and only its remote
      // role is set. Calling that "Supplies" states the opposite of the truth.
      const role =
        s.localLogic === 2 ? 'Demands' : s.localLogic === 1 ? 'Supplies' : 'Stores';
      rows.push({
        label: `${role} ${i + 1}`,
        value: `${name} — max ${s.max}, remote ${enumName(LOGISTIC_STORAGE, s.remoteLogic)}`,
      });
    });
    const assigned = beltSlots.filter((b) => b.dir !== 0);
    if (assigned.length > 0) {
      rows.push({
        label: 'Belt slots',
        value: assigned
          // storageIdx is 1-based; 0 means the slot feeds nothing specific.
          .map((b) => `${enumName(IO_DIR, b.dir)}${b.storageIdx > 0 ? ` → slot ${b.storageIdx}` : ''}`)
          .join(', '),
      });
    }
    if (settings) {
      rows.push({ label: 'Drones / ships', value: `${settings.deliveryDrones} / ${settings.deliveryShips}` });
      if (settings.pilerCount > 0) rows.push({ label: 'Piler', value: String(settings.pilerCount) });
      rows.push({ label: 'Warper required', value: settings.warperNecessary ? 'yes' : 'no' });
    }
    return rows;
  },

  Splitter(p) {
    const letters = ['A', 'B', 'C', 'D'];
    const on = letters.filter((_, i) => (at(p, i) ?? 0) > 0);
    return on.length > 0 ? [{ label: 'Priority belts', value: on.join(', ') }] : [];
  },

  Monitor(p, catalog) {
    // NOT VERIFIED AGAINST REAL DATA: no fixture contains a monitor, so this
    // layout is transcribed from BuildingParameters.cs and exercised only by
    // synthetic tests. Treat a field mismatch here as likely-ours.
    const rows: ParamRow[] = [];
    const filter = at(p, 14);
    if (filter && filter > 0) {
      rows.push({ label: 'Cargo filter', value: catalog.item(filter)?.name ?? `#${filter}` });
    }
    const target = at(p, 2);
    if (target !== undefined) rows.push({ label: 'Target cargo', value: String(target) });
    const alarm = at(p, 12);
    if (alarm !== undefined && alarm > 0) rows.push({ label: 'Alarm mode', value: String(alarm) });
    return rows;
  },

  Storage(p) {
    // [0] is storageComponent.bans (BuildingParameters.cs:1136), a bitmask of
    // banned slots -- NOT an automation toggle. Reported as the raw mask
    // because the per-bit meaning is not established.
    const bans = at(p, 0);
    return bans === undefined || bans === 0
      ? []
      : [{ label: 'Banned slots (mask)', value: String(bans) }];
  },

  BattleBase(p) {
    const mode = at(p, 0);
    return mode === undefined ? [] : [{ label: 'Drone mode', value: String(mode) }];
  },

  Dispenser(p) {
    const rows: ParamRow[] = [];
    const player = at(p, 0);
    const storage = at(p, 1);
    if (player !== undefined) rows.push({ label: 'Player mode', value: String(player) });
    if (storage !== undefined) rows.push({ label: 'Storage mode', value: String(storage) });
    const replenish = bool(at(p, 3));
    if (replenish) rows.push({ label: 'Courier auto-replenish', value: replenish });
    return rows;
  },

  Turret(p) {
    const group = at(p, 1);
    return group === undefined ? [] : [{ label: 'Turret group', value: String(group) }];
  },

  Ejector(p) {
    const orbit = at(p, 0);
    return orbit === undefined ? [] : [{ label: 'Target orbit', value: String(orbit) }];
  },

  Lab(p) {
    const mode = at(p, 0);
    return mode === undefined ? [] : [{ label: 'Lab mode', value: String(mode) }];
  },

  Inserter(p) {
    const stack = at(p, 0);
    return stack === undefined ? [] : [{ label: 'Stack size', value: String(stack) }];
  },

  Tank(p) {
    // outputSwitch / inputSwitch (BuildingParameters.cs:1195-1196), and both
    // are 1 / -1 like the station booleans -- printing the raw word would
    // show "-1" where the honest answer is "no".
    const rows: ParamRow[] = [];
    const out = bool(at(p, 0));
    const inp = bool(at(p, 1));
    if (out) rows.push({ label: 'Output switch', value: out });
    if (inp) rows.push({ label: 'Input switch', value: inp });
    return rows;
  },

  Marker(p) {
    const rows: ParamRow[] = [];
    const height = at(p, 1);
    const radius = at(p, 2);
    if (height !== undefined) rows.push({ label: 'Marker height', value: String(height / 100) });
    if (radius !== undefined) rows.push({ label: 'Marker radius', value: String(radius / 100) });
    return rows;
  },

  Belt(p, catalog) {
    // Belt tags render in the 3D scene via overlays.ts, but the info panel
    // needs its own row: without a decoder here, `Belt` is a known type with
    // no entry, so it falls into the unknown branch and the panel claims
    // "2 word(s)" for a block we fully decode. 109 tagged belts across the
    // fixtures hit that path. This reads the same [signalId, count] pair;
    // it does not move or duplicate the overlay's placement logic.
    const rows: ParamRow[] = [];
    const tagId = at(p, 0);
    if (tagId === undefined || tagId <= 0) return rows;
    rows.push({ label: 'Belt tag', value: catalog.tagIconName(tagId) ?? `#${tagId}` });
    const count = at(p, 1);
    // 0 is the unset value, not a number the player chose to show.
    if (count !== undefined && count > 0) rows.push({ label: 'Belt tag count', value: String(count) });
    return rows;
  },

  Assembler(p) {
    // forceAccMode (BuildingParameters.cs:1205): the proliferator toggle.
    // The single most common typed block in our fixtures -- ~127 smelters,
    // refineries and assemblers carry it.
    const acc = at(p, 0);
    return acc === undefined
      ? []
      : [{ label: 'Proliferator', value: acc > 0 ? 'production speedup' : 'extra products' }];
  },

  Silo(p) {
    const boost = bool(at(p, 0));
    return boost ? [{ label: 'Boost', value: boost }] : [];
  },

  Geothermal(p) {
    const ruin = at(p, 0);
    return ruin === undefined ? [] : [{ label: 'Base ruin', value: String(ruin) }];
  },

  Gamma(p) {
    const product = at(p, 0);
    return product === undefined ? [] : [{ label: 'Gamma product', value: String(product) }];
  },

  ArtificialStar(p) {
    const boost = bool(at(p, 0));
    return boost ? [{ label: 'Boost', value: boost }] : [];
  },

  Exchanger(p) {
    const state = at(p, 0);
    return state === undefined ? [] : [{ label: 'Exchanger mode', value: String(state) }];
  },
};
```

Then replace the two trailing `parameters.length` branches with:

```ts
  if (b.parameters.length > 0) {
    const type = catalog.buildingTypeFor(b.modelIndex, b.itemId);
    const decoder = type ? DECODERS[type] : undefined;
    if (decoder) {
      // A known type that yields no rows has nothing to report -- a splitter
      // with no priority belt set, say. Falling through to the word count
      // there would claim "we don't understand this block" when we do, and
      // would make that indistinguishable from a genuinely unknown type.
      rows.push(...decoder(b.parameters, catalog));
    } else {
      // Unrecognised layout: report the raw shape rather than guessing.
      rows.push({ label: 'Parameters', value: `${b.parameters.length} word(s)` });
    }
  }
```

That is every type in the dispatch table that carries a block, except
`Belt` (already handled in `overlays.ts` — do not duplicate it here) and
`Miner` (returns early in the game and has no block at all).

- [ ] **Step 4: Run to verify they pass**

Run: `bunx rstest run tests/model/params.test.ts 2>&1` — expected PASS.

- [ ] **Step 5: Full suite, lint, typecheck**

Run: `bun run test 2>&1`, `bun run lint`, `bun run typecheck`.

- [ ] **Step 6: Commit**

```bash
git add src/model/params.ts tests/model/params.test.ts
git commit -m "feat(model): decode parameter blocks per building type"
```

---

### Task 5: Render decoded rows in the info panel

**Files:**
- Modify: `src/ui/InfoPanel.tsx`
- Test: `tests/ui/InfoPanel.test.tsx`

**Interfaces:**
- Consumes: `describeParameters` (Task 4).
- Produces: no new exports.

- [ ] **Step 1: Write the failing test**

Add to `tests/ui/InfoPanel.test.tsx`, matching the file's existing mock shape:

```ts
test('renders every decoded parameter row, including repeats of a kind', () => {
  // Two station storage slots produce two distinct labelled rows; keying by
  // label alone would collide if the decoder ever emitted duplicates.
  render(<InfoPanel />);
  const panel = screen.getByTestId('info');
  expect(panel.textContent).toContain('Supplies 1');
  expect(panel.textContent).toContain('Supplies 2');
});
```

Set the mocked selected building to a station whose block populates storage slots 0 and 1, mirroring `tests/model/params.test.ts`'s `p[0]`/`p[6]` setup. Read the existing file first and follow whatever provider mock it already uses.

- [ ] **Step 2: Run to verify it fails**

Run: `bunx rstest run tests/ui/InfoPanel.test.tsx 2>&1`
Expected: FAIL — the panel shows `2048 parameter words`.

- [ ] **Step 3: Harden the React key**

In `src/ui/InfoPanel.tsx`, the rows are currently keyed by `row.label`. Decoded rows are designed to have unique labels, but a key that depends on decoder discipline is fragile — make it structural:

```tsx
        {describeParameters(b, catalog).map((row, i) => (
          <Fragment key={`${i}-${row.label}`}>
            <dt>{row.label}</dt>
            <dd>{row.value}</dd>
          </Fragment>
        ))}
```

No other change is needed: the panel already renders whatever rows it is given.

- [ ] **Step 4: Run to verify it passes**

Run: `bunx rstest run tests/ui/InfoPanel.test.tsx 2>&1` — expected PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ui/InfoPanel.tsx tests/ui/InfoPanel.test.tsx
git commit -m "feat(ui): show decoded building parameters"
```

---

### Task 6: Station storage feeds belt-content inference

This is the one part of the work with behaviour visible outside the info panel. On `factory-endgame-distribution-hub` the inference feature currently produces nothing: 78 sorters touch a belt, only 1 carries a filter, and 0 have a building with a recipe at the far end — 35 connect to stations.

**Files:**
- Modify: `src/model/beltGraph.ts`
- Test: `tests/model/beltGraph.test.ts`

**Interfaces:**
- Consumes: `Catalog.buildingTypeFor` (Task 2), `parseStationParams` (Task 3).
- Produces: no new exports; `inferCarried` keeps its signature.

- [ ] **Step 1: Write the failing tests**

Add to `tests/model/beltGraph.test.ts`. It already has `belt`, `sorter` and `producer` helpers and a `testCatalog`; extend the catalog with a station model and add a station helper:

```ts
function station(index: number, storage: [number, number][]): BlueprintBuilding {
  // storage entries are [itemId, localLogic]; 1 = Supply, 2 = Demand.
  const p = new Array(2048).fill(0);
  storage.forEach(([itemId, localLogic], s) => {
    p[s * 6] = itemId;
    p[s * 6 + 1] = localLogic;
  });
  return { ...belt(index, -1), itemId: 2104, modelIndex: 50, parameters: p };
}
```

and the tests:

```ts
test('a sorter feeding a belt from a station contributes what the station supplies', () => {
  // station 5 supplies 1101, demands 1104; sorter picks up FROM the station.
  const parsed = bp([belt(0, -1), sorter(1, 5, 0), station(5, [[1101, 1], [1104, 2]])]);
  const runs = buildBeltRuns(parsed);
  inferCarried(parsed, runs, stationCatalog);
  expect(runs[0]!.carried).toEqual([1101]);
});

test('a sorter draining a belt into a station contributes what the station demands', () => {
  const parsed = bp([belt(0, -1), sorter(1, 0, 5), station(5, [[1101, 1], [1104, 2]])]);
  const runs = buildBeltRuns(parsed);
  inferCarried(parsed, runs, stationCatalog);
  expect(runs[0]!.carried).toEqual([1104]);
});

test('a station slot set to None contributes to neither direction', () => {
  const parsed = bp([belt(0, -1), sorter(1, 5, 0), station(5, [[1101, 0]])]);
  const runs = buildBeltRuns(parsed);
  inferCarried(parsed, runs, stationCatalog);
  expect(runs[0]!.carried).toEqual([]);
});

test('a sorter filter still wins over the station fallback', () => {
  const parsed = bp([belt(0, -1), sorter(1, 5, 0, 1104), station(5, [[1101, 1]])]);
  const runs = buildBeltRuns(parsed);
  inferCarried(parsed, runs, stationCatalog);
  expect(runs[0]!.carried).toEqual([1104]);
});
```

Define `stationCatalog` next to the existing `testCatalog`, adding the model so `buildingTypeFor` resolves:

```ts
const stationCatalog = buildCatalog({
  items: [],
  models: { '50': { prefab: 'station-2', size: [1, 1, 1], center: [0, 0, 0], buildingType: 'Station' } },
  recipes: [
    { id: 1, name: 'Iron Ingot', iconName: '', items: [1001], itemCounts: [1],
      results: [1101], resultCounts: [1], timeSpend: 60 },
  ],
});
```

- [ ] **Step 2: Run to verify they fail**

Run: `bunx rstest run tests/model/beltGraph.test.ts 2>&1`
Expected: FAIL — `carried` is `[]` where `[1101]` is expected, because a station has no `recipeId` and the current fallback stops there.

- [ ] **Step 3: Implement the third fallback**

In `src/model/beltGraph.ts`, add the import:

```ts
import { parseStationParams } from './stationParams';
```

Extend `itemsForSorter`. It currently returns `[sorter.filterId]` when filtered, then falls back to the recipe. Insert the station branch between them:

```ts
function itemsForSorter(
  sorter: BlueprintBuilding,
  other: BlueprintBuilding | undefined,
  side: 'inputs' | 'results',
  catalog: Catalog,
): readonly number[] {
  if (sorter.filterId > 0) return [sorter.filterId];
  if (!other) return [];

  // A station carries no recipe, but its storage slots say what it holds.
  // Direction matters exactly as it does for recipes: a sorter draining a
  // belt INTO a station delivers what that station demands, and one feeding
  // a belt FROM a station carries what it supplies. A slot set to None
  // (ELogisticStorage 0) is configured for neither and contributes to
  // neither -- contributing it to both would invent traffic.
  const otherType = catalog.buildingTypeFor(other.modelIndex, other.itemId);

  if (otherType === 'Station') {
    const wanted = side === 'inputs' ? 2 : 1; // 2 Demand, 1 Supply
    return parseStationParams(other.parameters)
      .storage.filter((s) => s.localLogic === wanted)
      .map((s) => s.itemId);
  }

  // A Storage building (Depot / Battlefield Analysis Base) writes its
  // per-slot item filters from word 10 onward:
  //   parameters[10 + i] = storageComponent.grids[i].filter
  // (BuildingParameters.cs:1147-1149). Unfiltered slots are 0.
  //
  // Unlike a station slot, a storage filter carries NO direction: it says
  // "this slot holds item X", not whether the building supplies or demands
  // it. A depot is genuinely both a source and a sink for what it holds, so
  // the filters apply to both directions. That is not the same as the
  // station's localLogic 0 case, where the game explicitly records "neither".
  if (otherType === 'Storage' || otherType === 'BattleBase') {
    return [...new Set(other.parameters.slice(10).filter((v) => v > 0))];
  }

  if (other.recipeId <= 0) return [];
  const recipe = catalog.recipe(other.recipeId);
  if (!recipe) return [];
  return side === 'inputs' ? recipe.items : recipe.results;
}
```

- [ ] **Step 4: Run to verify they pass**

Run: `bunx rstest run tests/model/beltGraph.test.ts 2>&1` — expected PASS.

- [ ] **Step 5: Confirm the fixture actually lights up**

This is the point of the task. Run:

```bash
bun -e '
import {readFileSync} from "node:fs";
import {parseBlueprint} from "./src/format/index";
import {buildCatalog} from "./src/model/catalog";
import {buildSceneModel} from "./src/model/layout";
import {buildOverlays} from "./src/model/overlays";
const j=(p)=>JSON.parse(readFileSync(p,"utf8"));
const cat=buildCatalog({items:j("public/assets/items.json"),models:j("public/assets/models.json"),recipes:j("public/assets/recipes.json"),tags:j("public/assets/tags.json")});
const m=buildSceneModel(parseBlueprint(readFileSync("tests/fixtures/factory-endgame-distribution-hub.txt","utf8")),cat);
const withItems=m.beltRuns.filter(r=>r.carried.length>0);
console.log(`runs=${m.beltRuns.length} withCarried=${withItems.length}`);
console.log("sample:", withItems.slice(0,5).map(r=>r.carried.map(i=>cat.item(i)?.name).join("+")));
console.log("icons:", buildOverlays(m,cat,j("public/assets/icons/atlas.json")).icons.length);
'
```

Before this task `withCarried` was **1** of 118 runs. It must now be substantially higher, with plausible item names. Record the numbers in your report. If it is still 1, the station branch is not being reached — check `buildingTypeFor` resolves for itemId 2104 before adjusting anything else.

- [ ] **Step 6: Full suite, lint, typecheck**

Run: `bun run test 2>&1`, `bun run lint`, `bun run typecheck`.

- [ ] **Step 7: Commit**

```bash
git add src/model/beltGraph.ts tests/model/beltGraph.test.ts
git commit -m "feat(model): infer belt contents from station storage"
```

---

### Task 7: Retire the backlog and verify end to end

**Files:**
- Modify: `docs/BACKLOG.md`

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Delete the backlog item**

`docs/BACKLOG.md` has exactly one entry, "1. Decode remaining parameter payloads". Delete it. The file is then left with only its title and intro paragraph — that is correct; keep the file so the next item has a home, and leave the intro text unchanged.

- [ ] **Step 2: Full gate**

```bash
lsof -ti:3000 | xargs kill -9 2>/dev/null; sleep 1
bun run test 2>&1 | tee /tmp/params-test.log
grep -inE "error|warn|abort|ECONNRESET|hang up|unhandled|reject" /tmp/params-test.log
bun run lint && bun run typecheck && bun run build
```

Every command must exit 0 and the grep must return nothing. Kill the dev server first: a listener on port 3000 has previously masked a real test failure in this repo, because happy-dom resolves relative fetches against that port.

- [ ] **Step 3: Confirm the fixture invariants still hold**

The belt work established these; this change must not move them.

```bash
bun -e '
import {readFileSync,readdirSync} from "node:fs";
import {parseBlueprint} from "./src/format/index";
import {buildCatalog} from "./src/model/catalog";
import {buildSceneModel} from "./src/model/layout";
import {buildOverlays} from "./src/model/overlays";
const j=(p)=>JSON.parse(readFileSync(p,"utf8"));
const cat=buildCatalog({items:j("public/assets/items.json"),models:j("public/assets/models.json"),recipes:j("public/assets/recipes.json"),tags:j("public/assets/tags.json")});
const atlas=j("public/assets/icons/atlas.json");
let counts=0, unres=0;
for (const f of readdirSync("tests/fixtures").filter(f=>f.endsWith(".txt"))) {
  let bp; try{bp=parseBlueprint(readFileSync(`tests/fixtures/${f}`,"utf8"));}catch{continue;}
  const m=buildSceneModel(bp,cat); const o=buildOverlays(m,cat,atlas);
  counts+=o.counts.length; unres+=m.unresolvedTagIds.length;
  if (f.startsWith("factory-heretical")) console.log(`heretical runs=${m.beltRuns.length} belts=${m.beltRuns.reduce((a,b)=>a+b.belts.length,0)}`);
  if (f.startsWith("falk")) console.log(`falk belts=${m.beltRuns.reduce((a,b)=>a+b.belts.length,0)} cyclic=${m.beltRuns.filter(r=>r.cyclic).reduce((a,b)=>a+b.belts.length,0)}`);
}
console.log(`total counts=${counts} (want 14)  unresolvedTagIds=${unres} (want 0)`);
'
```

Expected: heretical 11 runs / 283 belts; falk 1714 belts with 280 cyclic; total counts 14; unresolvedTagIds 0. If any moved, stop and report — do not update an assertion to match.

- [ ] **Step 4: Visual check**

Start the dev server and load `tests/fixtures/factory-endgame-distribution-hub.txt`. Click a logistics station and confirm the info panel shows real supply/demand rows rather than `"2048 parameter words"`. Confirm the belt runs now carry inferred icons where they previously showed none.

- [ ] **Step 5: Commit**

```bash
git add docs/BACKLOG.md
git commit -m "docs: retire the parameter-payload backlog item"
```

---

## Notes for the implementer

- **Classification is the whole design.** If a decoder produces nonsense, suspect `buildingTypeFor` before the layout. `factory-endgame-distribution-hub` contains a Holo Beacon whose block is also 2048 words but is a **Marker**, not a Station — decoded as a station its first "storage slot" reads `itemId 13, localLogic 3750`, which is really signal 13 at height 37.5. Dispatching on word count cannot work; the same trap sits under 110, 128 and 1.
- **Monitors have no fixture coverage.** Their decoder is transcribed from the DLL and exercised only by synthetic tests. The code says so; keep that comment.
- **Short blocks are normal, not corrupt.** Splitters appear with 4 and 6 words, depots with 1 and 110, because older game versions wrote fewer. Never assume the current length.
