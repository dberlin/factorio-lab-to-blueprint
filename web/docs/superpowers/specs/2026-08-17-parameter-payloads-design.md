# Decoding building parameter payloads

Date: 2026-08-17
Status: approved design, ready for an implementation plan

## Motivation

Every building in a blueprint may carry a parameter block. The viewer
decodes exactly one of them — the belt icon tag — and reports the rest as
`"N parameter words"`. That block holds the settings that make a blueprint
worth copying: what a logistics station supplies and demands, how a
splitter prioritises its belts, what a monitor alarms on, how a storage is
filtered.

There is also a functional consequence, found during the belt work: on
`factory-endgame-distribution-hub` the inferred-belt-contents feature
produces **nothing**. 78 sorters touch a belt there, only 1 carries a
filter, and **0** have a building with a recipe at the far end — 35 of them
connect to *stations*, whose carried item lives in precisely this
undecoded block. Decoding station storage turns that feature on for
station-heavy blueprints.

This supersedes `docs/BACKLOG.md` item 1, and its completion removes it.

## Verified facts

Everything here was checked against the game's own `Assembly-CSharp.dll`
and the 11 blueprint fixtures.

### The dispatch is a single authoritative table

`BuildingParameters.ToParamsArray` branches once per building type and
fixes both the word count and the layout. Recovered in full:

| BuildingType | words | Contents |
|---|---|---|
| Miner | 0 | early return, no block |
| Splitter | 6 | `[0..3]` priority flag per belt A–D; `[4] [5]` carried through |
| Monitor | 128 | see below |
| Storage | 110 | `[0]` mode0, `[1]` mode1, `[10..]` carried through |
| BattleBase | 110 | `[0]` mode0, `[1]` mode1, `[2]` prior `[0]`, `[10..]` carried |
| Tank | 2 | `[0]` mode0, `[1]` mode1 |
| Assembler | 1 | `[0]` carried through |
| Inserter | 1 | `[0]` stack size |
| Belt | 0 or 2 | `[signalId, count]` — **already implemented** |
| Ejector | 3 | `[0]` orbitId, `[1]` boost, `[2]` mode2 |
| Lab | 2 | `[0]` mode0, `[1]` mode1 |
| Marker | 2048 | `[0]` signal, `[1]` height×100, `[2]` radius×100, `[3..6]` |
| Station | 2048 | see below |
| Dispenser | 128 | `[0]` playerMode, `[1]` storageMode, `[2]` energy/tick, `[3]` courierAutoReplenish |
| Turret | 128 | `[1]` group, `[2]` vsSettings, `[3]` phasePos, `[4]` mode3 |
| Gamma | 1 | `[0]` productId |
| ArtificialStar | 1 | `[0]` boost |
| Geothermal | 1 | `[0]` baseRuinId |
| Exchanger | 1 | `[0]` targetState |
| Silo | 1 | `[0]` mode0 |
| anything else | 0 | no block |

### Station, 2048 words in three regions

Written at `BuildingParameters.cs:1293-1350`. The block is allocated at
2048 but only the first ~384 words are meaningful; the rest is zero
padding, which is why stations dominate blueprint size.

**Storage slots** — offset `0`, 32 slots × 6 words:

| +k | field |
|---|---|
| 0 | `itemId` |
| 1 | `localLogic` — `ELogisticStorage`: 0 None, 1 Supply, 2 Demand |
| 2 | `remoteLogic` — same enum |
| 3 | `max` |
| 4 | `keepMode` |
| 5 | `keepIncRatio` × 100000 |

**Belt slots** — offset `192`, 32 slots × 4 words:

| +k | field |
|---|---|
| 0 | `dir` — `IODir`: 0 None, 1 Output, 2 Input |
| 1 | `storageIdx` — **1-based** into the storage slots; 0 = unassigned |
| 2, 3 | unused |

The 1-based reading is established from data, not assumed. A station in
`factory-endgame-distribution-hub` has 5 populated storage slots and 6
populated belt slots whose `storageIdx` values are a permutation of
`{0,1,2,3,4,5}`. Read 0-based, index 5 would point past the last storage
slot; read 1-based, `1..5` map onto storage `0..4` and the single `0` is
the one unassigned belt slot. Only the 1-based reading is consistent.

Decoded, that station reads: supplies Conveyor Belt Mk.III (max 3500),
Pile Sorter (1500), Splitter (100), Re-composing Assembler (200) and
Negentropy Smelter (200), all `localLogic = 1` (Supply) — which is exactly
the kind of fact the info panel should be showing and currently is not.

**Settings** — offset `320`:

| +k | field |
|---|---|
| 0 | `workEnergyPerTick` |
| 1 | `tripRangeDrones` × 1e8 |
| 2 | `tripRangeShips` ÷ 100 |
| 3 | `includeOrbitCollector`, 1 / −1 |
| 4 | `warpEnableDist` |
| 5 | `warperNecessary`, 1 / −1 |
| 6 | `deliveryDrones` |
| 7 | `deliveryShips` |
| 8 | `pilerCount` |
| 9 | miner speed, vein collectors only |
| 10 | `droneAutoReplenish` |
| 11 | `shipAutoReplenish` |
| 12, 13 | `remoteGroupMask` low, high |
| 14 | `routePriority` |

Note the booleans use **1 / −1**, not 1 / 0, so `!== 0` is the wrong test
for them; `> 0` is correct.

### Monitor, 128 words

| index | field | | index | field |
|---|---|---|---|---|
| 0 | `targetBeltId` | | 10 | `systemWarningMode` |
| 1 | `offset` | | 11 | speaker `repeat` |
| 2 | `targetCargoBytes` | | 12 | `alarmMode` |
| 3 | `curPeriodTickCount` | | 13 | speaker `length` × 10000 |
| 4 | `passOperator` | | 14 | `cargoFilter` |
| 5 | `passColorId` | | 17 | `systemWarningSignalId` |
| 6 | `failColorId` | | 18 | speaker `falloffRadius0` × 10 |
| 7 | speaker `tone` | | 19 | speaker `falloffRadius1` × 10 |
| 8 | speaker `volume` | | 20 | `spawnItemOperator` |
| 9 | speaker `pitch` | | 21 | carried through |

### Classification: itemId → BuildingType

This was the hard part. A blueprint stores `itemId`; the layouts are keyed
by `BuildingType`. The game bridges them through `ItemProto.prefabDesc`,
which is assigned from `ModelProto.prefabDesc` (`ItemProto.cs:547`) and
loaded from prefabs at runtime.

**`PrefabDesc` is not serialised anywhere extractable** — confirmed absent
from `resources.assets`, `sharedassets0.assets` and
`globalgamemanagers.assets`, and the install ships no asset bundles.

It is, however, recoverable another way. The prefabs carry **per-type
marker components** — `StationDesc`, `MonitorDesc`, `StorageDesc`,
`BattleBaseDesc`, `TankDesc`, `AssemblerDesc`, `InserterDesc`, `BeltDesc`,
`EjectorDesc`, `LabDesc`, `MarkerDesc`, `DispenserDesc`, `TurretDesc`,
`SiloDesc`, `SplitterDesc`, `MinerDesc` — one per BuildingType we need.

Joining those to `ModelProto` by `PrefabPath` basename is **the same join
`extract_assets.py` already performs for `SlotConfig`**. Measured: 46
prefab GameObjects carry a `*Desc`, all 46 resolve to a name, and **all 46
join successfully**. Spot checks against facts established independently
during the belt work: models 35/36/37 → Belt (37 is `belt-3`, Mk.III),
38/39/40 → Splitter (including model 39, which a community data table got
wrong), 41/42/43 → Inserter, 49/50 → Station, 51 → Storage.

Exactly two models carry two types, and both are real game semantics
rather than join failures:

- **model 256 → Miner + Station** — the Orbital / Vein Collector. The DLL
  has `isCollector` and `isVeinCollector` for exactly this case.
- **model 453 → BattleBase + Storage** — the Battlefield Analysis Base,
  which has storage. Both layouts are 110 words, so they do not conflict.

The game resolves both by evaluation order: its export checks Station
after Miner, and BattleBase after Storage. We adopt the same precedence.

### What the fixtures actually contain

| Building | count | words |
|---|---|---|
| Matrix Lab | 120 | 1 |
| Negentropy Smelter | 100 | 1 |
| Conveyor Belt Mk.III | 71 | 2 |
| Depot Mk.I | 49 | 110 |
| Logistics Distributor | 49 | 128 |
| Energy Exchanger | 45 | 1 |
| Conveyor Belt Mk.I | 38 | 2 |
| Artificial Star | 32 | 1 |
| Depot Mk.I | 30 | 1 |
| Interstellar Logistics Station | 27 | 2048 |
| Splitter | 21 | 4 |
| Oil Refinery | 12 | 1 |
| Matrix Lab | 11 | 2 |
| Arc Smelter | 9 | 1 |
| Battlefield Analysis Base | 4 | 110 |
| Splitter | 4 | 6 |
| Assembling Machine Mk.III | 4 | 1 |
| Assembling Machine Mk.I | 2 | 1 |
| Holo Beacon | 1 | 2048 |
| Storage Tank | 1 | 2 |

Three things follow. **Monitors appear zero times**, so their decoder can
be verified against the DLL layout but not against real data. Splitters
appear with **4 and 6** words though the current game writes 6 — older
blueprints are shorter, so every decoder must tolerate a short block.
Depot Mk.I appears with both 110 and 1 words for the same itemId, for the
same reason.

## Scope

**In:** the whole dispatch table above; a `buildingType` per model emitted
by the extractor; a per-type decoder producing labelled rows for the info
panel; structured station storage; station storage feeding belt-content
inference.

**Out:** editing or re-encoding parameters; rendering station or monitor
state in the 3D scene; decoding `content` strings (marker text).

## Design

### Module layout

The architecture invariant holds: `src/format/`, `src/model/` and
`src/server/` import neither React nor three.js.

```
scripts/extract_assets.py   MOD  *Desc join -> buildingType per model
src/model/schemas.ts        MOD  ModelBox gains buildingType
src/model/catalog.ts        MOD  buildingTypeFor(modelIndex, itemId)
src/model/params.ts         MOD  per-type decoders, replacing the word count
src/model/stationParams.ts  NEW  station block -> structured slots/settings
src/model/beltGraph.ts      MOD  station storage as a third inference fallback
src/ui/InfoPanel.tsx        MOD  render decoded rows
```

`stationParams.ts` is separate because the station block is the only one
with internal structure worth a type of its own, and folding 380 words of
region maths into `params.ts` would swamp the other nineteen decoders.

### Classification

The extractor emits `buildingType` on each entry of `models.json`. Where a
model carries two `*Desc` components, precedence follows the game's own
evaluation order: **Station over Miner**, **BattleBase over Storage**.

Two assertions, in the extractor's established style:

- all 46 `*Desc`-carrying prefabs join to a `ModelProto`;
- exactly two models are multi-type, and they are 256 and 453.

A future patch that adds a building type, renames a prefab, or introduces a
third ambiguity therefore fails loudly at extract time rather than silently
classifying a building as untyped.

`catalog.buildingTypeFor` resolves through `modelIndex` first, matching
`LDB.models.Select(modelIndex).prefabDesc`, and is the single place any
decoder asks what a building is.

### Decoding

`params.ts` becomes a lookup from `BuildingType` to a decoder function.
Each returns `{ label, value }` rows, as it does today.

**Every decoder must tolerate a block shorter than the current game
writes.** Splitters in our own fixtures come in 4-word and 6-word forms; a
decoder that indexes `[5]` unconditionally will read `undefined`. Read
defensively and omit the row when the word is absent, rather than printing
a wrong value.

Enum words render as their names — `Supply` / `Demand`, `Output` /
`Input` — not raw integers. Scaled words are divided back out
(`keepIncRatio` ÷ 100000, `tripRangeShips` × 100). The 1 / −1 booleans test
`> 0`.

Monitors are implemented from the DLL layout and **marked in the code as
unverified against real data**, because no fixture contains one. That note
is the honest record of what the tests do and do not prove.

### Station storage feeding belt inference

`inferCarried` currently resolves a sorter's item by filter, then by the
recipe of the building at the far end. A third fallback is added: if that
building is a **station**, contribute the item ids of its storage slots.

Direction is respected the way the recipe fallback already respects it: a
sorter *draining* a belt into a station contributes slots the station
**demands**; a sorter *feeding* a belt from a station contributes slots it
**supplies**. `localLogic` carries that, and where it is `None` the slot
contributes to neither direction rather than both.

This is what makes `factory-endgame-distribution-hub` show inferred icons
instead of nothing, and it is the one part of this work with behaviour
visible outside the info panel.

## Decisions

**Classification comes from game data, not a hand-maintained table.** A
curated itemId list would have been quicker, but it rots against content
patches and cannot be checked. The `*Desc` join is the game's own
relationship, and it is already proven in this codebase by `SlotConfig`.

**Length is not a usable substitute for type.** `factory-endgame-
distribution-hub` contains a Holo Beacon whose block is also 2048 words,
but it is a Marker, not a Station. Decoded with the station layout its
first "storage slot" reads `itemId 13, localLogic 3750, max 2` — garbage.
Read correctly as a Marker it is signal 13 at height 37.5 and radius 5.0.
Same length, unrelated meaning: a decoder that dispatches on word count
produces confident nonsense, which is the failure this design exists to
prevent. The same trap sits under 110 (Storage vs BattleBase), 128
(Monitor vs Dispenser vs Turret) and 1 (five types).

**Ambiguous models resolve by the game's precedence, not by ours.** Where
the game checks Station after Miner, so do we; inventing a rule would make
Orbital Collectors decode differently from how the game reads them.

**Monitors ship undecodable-by-test.** The alternative — omitting them —
leaves a type the backlog explicitly named unimplemented. Implementing
with an honest marker is better than either silently pretending coverage
or skipping the work.

## Testing

`tests/model/params.test.ts` — one case per building type, driven by
synthetic blocks, plus a short-block case per type that has a variable
length in the fixtures (splitter 4 vs 6, depot 1 vs 110).

`tests/model/stationParams.test.ts` — region offsets (a slot at index 31
lands at word 186, not past the belt-slot region), enum decoding, scaled
values, and the 1 / −1 booleans.

`tests/model/catalog.test.ts` — `buildingTypeFor` including both ambiguous
models.

`tests/model/beltGraph.test.ts` — the station fallback in both directions,
and that a `None` slot contributes to neither.

Fixture-level assertions pin what the fixture table above measures, so a
decoder that starts skipping buildings is caught.

No test may perform network I/O, and no unit test may read
`public/assets/*.json` — that is gitignored build output.

## Completion criteria

- The info panel shows decoded settings for every type in the table, in
  place of `"N parameter words"`.
- `factory-endgame-distribution-hub` shows inferred belt icons where it
  currently shows none.
- Extractor assertions cover the join and the two known ambiguities.
- `bun run test`, `typecheck`, `lint` and `build` all clean, with the full
  output scanned rather than the pass count, and the suite green with
  nothing listening on port 3000.
- `docs/BACKLOG.md` item 1 is deleted.
