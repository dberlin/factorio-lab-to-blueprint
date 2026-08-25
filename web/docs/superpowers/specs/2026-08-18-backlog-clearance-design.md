# Backlog Clearance — Design

Closes all four items standing in `docs/BACKLOG.md` after the
parameter-payloads branch landed. Two came from the user directly; two came
out of that branch's final whole-branch review.

## Background

`docs/BACKLOG.md` holds four items:

1. **Show inferred belt/sorter contents in the info panel.** The user's own
   request: "I see the inferred icons/etc, but when I click on the details,
   it doesn't say anything… Let's make it include the inferred info as well
   (marked as inferred)."
2. **Pin the classification chain with a fixture-level test.** The
   load-bearing end-to-end numbers are verified only by hand.
3. **Render the remaining enum words as names.** Nine decoders print raw
   integers where the design says they should print names.
4. **Establish what `deliveryDrones` / `deliveryShips` measure.**

Items 3 and 4 were written down as blocked on game sources we did not have.
**They are no longer blocked.** `ilspycmd` 9.0.0 is installed as a dotnet
global tool and the game's `Assembly-CSharp.dll` is present, so any type can
be decompiled on demand:

```bash
export DOTNET_ROLL_FORWARD=LatestMajor   # ilspycmd targets .NET 8; only 10.x is installed
~/.dotnet/tools/ilspycmd -t StationComponent \
  "/Users/dannyb/Downloads/Dyson Sphere Program/DSPGAME_Data/Managed/Assembly-CSharp.dll"
```

Without `DOTNET_ROLL_FORWARD` this fails with "You must install or update
.NET to run this application" — that error is a version mismatch, not a
missing tool. Both blocked questions were answered this way while writing
this spec, and the answers are recorded below so no task has to re-derive
them.

## Evidence

### How mode words reach the parameter block

`BuildingParameters` keeps four scalar `modeN` fields separate from the
`parameters` array in the in-game copy path, then packs them into the array
for the blueprint path:

```csharp
_parameters[0] = mode0;   // BuildingParameters.cs:107-108, and 8 more sites
_parameters[1] = mode1;
```

`Turret` is the one type that shifts (`BuildingParameters.cs:303-314`):

```csharp
_parameters[1] = mode0;   // group
_parameters[2] = mode1;   // vsSettings
_parameters[3] = mode2;
_parameters[4] = mode3;
```

This is why the existing `Turret` decoder reads word 1 rather than word 0,
and it is correct as written.

### Energy Exchanger — `targetState` is a tri-state, 1 = charge

`BuildingParameters.cs:3290` clamps the word into `targetState`:

```csharp
powerSystem.excPool[powerExcId].targetState = Mathf.Clamp(parameters[0], -1, 1);
```

`PowerExchangerComponent` settles the polarity — each update path refuses to
run unless `state` has reached the matching pole:

```csharp
public long InputUpdate(...)  { if (state != 1f)  { return 0L; } ... }   // :249
public long OutputUpdate(...) { if (state != -1f) { return 0L; } ... }   // :296
```

Input means drawing energy from the grid into the exchanger's pool, i.e.
charging accumulators. So:

| word | name |
|------|------|
| `1` | Charge |
| `0` | Standby |
| `-1` | Discharge |

### Matrix Lab — `mode0` is a tri-state, and `mode1` is the proliferator

`BuildingParameters.cs:1254-1263`:

```csharp
if (factorySystem.labPool[labId].researchMode)      { mode0 = 2; }
else if (factorySystem.labPool[labId].recipeId > 0) { recipeId = ...; mode0 = 1; }
mode1 = (factorySystem.labPool[labId].forceAccMode ? 1 : 0);
```

| word 0 | name |
|--------|------|
| `0` | Idle |
| `1` | Matrix production |
| `2` | Research |

Word 1 is `forceAccMode`, the same proliferator toggle the `Assembler`
decoder already renders — the `Lab` decoder currently ignores it.

### Logistics Distributor — two real enums

`DispenserComponent.cs:39-41` types the two mode fields, and the enums are:

```csharp
public enum EPlayerDeliveryMode  { None, Recycle, Both, Supply }
public enum EStorageDeliveryMode { None, Supply, Demand }
```

### Interstellar Logistics Station — the delivery words are percentages

`StationComponent` uses both as a percentage of a vessel's carrying
capacity, never as a count:

```csharp
int num19 = (droneCarries - 1) * deliveryDrones / 100;   // StationComponent.cs:1542
int num16 = (shipCarries  - 1) * deliveryShips  / 100;   // StationComponent.cs:3384
```

The defaults confirm the range (`:297-298`): `deliveryDrones = 10;
deliveryShips = 100;`. This matches the fixture distribution exactly — 27
real stations, all values bounded by 100, clustered at 100. The review's
suspicion was right and the current neutral label understates what we know.

### Two rows the review flagged are already correct

- **`Turret group`** is `TurretComponent.group`, a `byte` group number — not
  an enum. A raw integer is the right rendering. What is genuinely missing
  is `mode1` = `vsSettings`, a `VSLayerMask` bitmask.
- **`Target orbit`** is `EjectorComponent.orbitId`, an orbit index. Raw is
  correct.

`VSLayerMask` is a bitmask with a two-bit field per band, so the composite
values are unions rather than distinct members:

```csharp
public enum VSLayerMask : byte {
  None = 0,
  GroundLow = 1, GroundNormal = 2, GroundHigh = 3,
  AirLow = 4,    AirNormal = 8,    AirHigh = 12,
  OrbitLow = 16, OrbitNormal = 32, OrbitHigh = 48,
  SpaceLow = 64, SpaceNormal = 128, SpaceHigh = 192,
}
```

`GroundHigh` is `GroundLow | GroundNormal`, so decoding must name the bands
whose bits are set rather than look up a single member.

### Why the rest legitimately stay raw

The backlog item claimed nine decoders printed raw integers where they
should print names. Four were changed (`Exchanger`, `Lab`, both `Dispenser`
modes) and two were ruled correct-as-is above (`Turret group`, `Target
orbit`). The remainder are not oversights -- each is a genuinely untyped
number with no enum to name it from:

- **`Alarm mode`** -- `MonitorComponent.alarmMode` is a bare `byte`, the
  same shape as `TurretComponent.group`, not a typed enum.
- **`Banned slots (mask)`** -- a bitmask, not a single enum value.
- **`Drone priority`** -- a plain integer priority, not an enum.
- **`Target orbit`** -- `EjectorComponent.orbitId`, an orbit index.
- **`Stack size`** -- a plain count.
- **`Piler`** -- a plain count.
- **`Base ruin`** -- an id, but not an item id, so unlike `Gamma product` it
  cannot resolve through the catalog.
- **`Marker height` / `Marker radius`** -- scaled values (divided by 100),
  not enum members.

## Design

### Inferred contents in the info panel

The panel renders `describeParameters(building, catalog)`, which sees one
building record and nothing else. The inference lives on the **belt run**
(`BeltRun.carried`, filled by `inferCarried`), which is one level up in
`SceneModel`.

`useBlueprint()` already exposes `sceneModel` — `Toolbar.tsx` uses it — so
no provider change is needed. The seam is `describeParameters`'s signature.

**Decision: do not thread `SceneModel` into `describeParameters`.** That
function is a pure per-building decoder and every one of its nineteen
decoders would gain a parameter none of them use. Instead add a second,
sibling function that answers the inference question, and have `InfoPanel`
concatenate the two row lists. `params.ts` keeps decoding records;
`beltGraph.ts` keeps answering inference questions.

Inferred rows must be visually distinguishable from read ones, per the
user's "marked as inferred". A row label suffix is not enough on its own —
it puts the marking in the `<dt>` where it reads as part of the field name.
Rows carry an explicit `inferred?: boolean` flag and the panel renders
those `<dd>`s with a class the stylesheet can mark.

The belt case and the sorter case are different questions and must not be
collapsed:

- **A belt** shows the contents of the run it belongs to. Every belt in a
  run shows the same answer, which is correct — the run is the unit the
  inference is computed over.
- **A sorter** shows what that one sorter is inferred to move: its own
  `filterId` if set, otherwise the neighbour-derived answer (recipe, then
  station storage, then depot filters). A sorter belongs to no run.

A sorter has two ends and can therefore contribute two different answers
(what it drains off a belt, and what it feeds onto one). Report them as
separate rows rather than a merged set, because merging would state that one
sorter moves items it does not.

### Fixture-level regression guard

The blocker was that tests may not read `public/assets` (build output) and
may not touch the network. The four catalog files total ~54 KB, which is
small enough to check in whole — no trimming step, no generator script, no
drift between "the test catalog" and "the catalog".

Snapshot them under `tests/fixtures/catalog/` and build a real `Catalog`
from them. That unlocks assertions on the numbers that currently live only
in hand-run scripts: 1918 parameter-carrying buildings with 0 untyped and 0
generic rows, and 34 of 118 endgame-hub runs carrying items.

The snapshot can drift from a re-extraction. That is acceptable and is
itself the signal: `scripts/extract_assets.py` writes `tests/fixtures/catalog/`
from the same `write()` calls that produce `public/assets/`, after
`validate()` passes, so a re-extraction that changes the catalog shows up
here as a reviewable diff in the snapshot -- not as a silent no-op, since
nothing else writes this directory.

## Completion criteria

- Clicking a belt shows its run's inferred contents, marked as inferred.
- Clicking a sorter shows what it is inferred to move, per end, marked as
  inferred.
- A test builds a real catalog from checked-in JSON and pins: 0 untyped and
  0 generic rows across all fixtures, and the endgame-hub carry count.
- `Exchanger mode`, `Lab mode`, and both Dispenser modes render as names;
  `Lab` also reports its proliferator setting; `Turret` reports its target
  layers.
- The station delivery row names the percentage unit.
- **`docs/BACKLOG.md` contains no items** — each task removes the item it
  closes, in the same commit.
