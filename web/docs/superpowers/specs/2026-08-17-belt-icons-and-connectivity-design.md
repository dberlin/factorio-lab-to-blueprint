# Belt icons, belt connectivity, and direction chevrons

Date: 2026-08-17
Status: approved design, ready for an implementation plan

## Motivation

Belts currently render as featureless coloured prisms. Three things the
game shows and we do not:

1. The **icon tag** a player can attach to a belt, with its number.
2. What an **unconnected belt run carries**, inferred from the sorters
   feeding or draining it.
3. Which way a belt **flows**.

All three are listed in `docs/BACKLOG.md`; this spec supersedes those
entries and its completion removes them.

They are specified together because (2) and (3) both need the same
belt-run graph, which does not exist yet. Designing that pass once, with
both consumers in view, is the reason for a single spec.

## Verified facts

Everything below was checked against the game's own `Assembly-CSharp.dll`
and the 11 blueprint fixtures. Line numbers refer to ILSpy output of the
named type.

### Belt tags

`BuildingParameters.cs:1223-1241` — when a building is a belt, the game
writes:

```csharp
if (factory.entitySignPool[objectId].iconId0 == 0) {
    parameters = null;
} else {
    parameters = new int[2];
    parameters[0] = (int)factory.entitySignPool[objectId].iconId0;
    parameters[1] = (int)(factory.entitySignPool[objectId].count0 + 0.5f);
}
```

So a belt's parameter block is either empty or exactly two words:
`[signalId, count]`. The paste path (`BuildingParameters.cs:1779-1784`)
reads them back through `SetBeltSignalIcon` / `SetBeltSignalNumber`.
Measured across all fixtures: **109 tagged belts, every one with exactly
two parameter words.**

The tag is *not* belt state — it lives in `entitySignPool`, the same
per-entity sign storage used for other signs, and `BeltComponent` itself
has no icon field.

### The count is a free-text player annotation

`UIBeltWindow.OnTagCountInputEndEdit` does `float.TryParse(str, out
result)` on whatever the player types and passes it to
`SetBeltSignalNumber`, which stores it verbatim. There is no unit, no
validation beyond "is it a number", and no gameplay effect.
`SetBeltSignalNumber` zeroes the field whenever no icon is set, so **0 is
the unset value**, and the UI clamps negatives to 0 for display only.

It is a `float` in-game but an `int` in blueprints — `(int)(count0 +
0.5f)` rounds half up, so `2.5` serialises as `3`. That lossiness is the
game's, not ours.

Measured distribution over the 109 tagged belts:

| count | belts |
|---|---|
| 0 | 95 |
| 90 | 6 |
| 180 | 4 |
| 360 | 4 |

The only non-zero values are 90, 180 and 360 — consistent with the player
convention of labelling throughput per minute, though the game attaches no
such meaning.

### Signal ids span five ranges, not two

`SignalProtoSet.IconSprite` is the authoritative resolver:

| Range | Resolves to |
|---|---|
| `< 1000` | `SignalProto` — 39 entries, ids 401–802 |
| `< 12000` | `ItemProto`, id used directly |
| `< 20000` | `VeinProto` at `id - 12000` |
| `< 40000` | `RecipeProto` at `id - 20000` |
| `< 60000` | `TechProto` at `id - 40000` |
| otherwise | nothing |

`SignalProtoSet` was dumped from `resources.assets`: 39 entries, ids
401–802, sprites at `Icons/Signal/signal-NNN`. **All 109 fixture tags fall
in the item band**, so the fixtures alone cannot exercise the other four.
A resolver that only handled "signal vs item" would mis-render a vein tag
as item 12xxx — a *wrong* icon, which is worse than a blank one. This is
why the resolver mirrors all five bands.

### Connectivity is forward-linked only

Blueprints record `outputObjIdx` but effectively not `inputObjIdx`: **277
of 283 belts in `factory-heretical-smelter-block` have `inputObjIdx =
-1`**. A belt's free *input* end therefore cannot be read from a field; it
must be derived by inverting the output links.

Distinguish two different "ends":

- `outputObjIdx < 0` — points at nothing; the run genuinely stops in space.
- `outputObjIdx >= 0` but the target is not a belt — the run feeds a
  building (station, splitter). In heretical: 272 belt→belt, 5 belt→other,
  6 pointing nowhere.

Only the first is "unconnected" for our purposes.

Measured run structure after inverting the links. **These counts come from
a naive walk outward from every head**, which is not quite the
segmentation this spec adopts — see the note below the table:

| Fixture | belts | runs | longest | in cycles | merges |
|---|---|---|---|---|---|
| heretical-smelter | 283 | 11 | 36 | 0 | 0 |
| red-cube step 3 | 194 | 12 | 30 | 0 | 0 |
| falk-v7-mall | 1714 | 39 | 110 | **280** | 0 |
| 12-s-purple | 2640 | 22 | 229 | 0 | **1** |

Two structures the walk must survive: **closed loops** with no head at all
(falk mall, 280 belts) and **merge points** where two runs join
(12-s-purple).

Note on the merge fixture: `12-s-purple` has 22 heads but only 21 tails,
because two runs join and share one tail chain. A naive head-walk
therefore reports 22 runs, with the shared chain arbitrarily absorbed into
whichever head reached it first. The degree-based segmentation specified
below deliberately splits there instead, so it should report **23** runs
for that fixture. That figure is a prediction from the rule, not a
measurement — the implementation must confirm it rather than assume it.

### Sorter filters are frequently unset

Sorter endpoints landing on a head or tail belt, and how many carry a
filter:

| Fixture | end sorters | with filter |
|---|---|---|
| falk-v7-mall | 55 | 55 |
| red-cube step 3 | 5 | 3 |
| heretical-smelter | 18 | **0** |
| 12-s-purple | 22 | **0** |

Filters alone yield nothing on two of four fixtures. Every one of those
unfiltered sorters, however, connects to a building with a real recipe
(observed `recipeId` 1, 50, 51, 53), so the item is recoverable from the
recipe instead.

## Scope

**In:** belt tag decoding and rendering (icon + number); belt run graph;
inferred endpoint icons; direction chevrons; `SignalProtoSet` and
`VeinProtoSet` extraction; unresolved-tag diagnostics.

**Out:** decoding station/splitter/monitor parameter payloads (backlog
item 3 stays); belt throughput simulation; editing blueprints.

## Design

### Module layout

The architecture invariant holds: `src/model/` imports neither React nor
three.js (enforced by `tests/architecture.test.ts`).

```
src/model/beltGraph.ts     NEW  run graph + carried-item inference (pure)
src/model/catalog.ts       MOD  tagIconName(signalId) five-band resolver
src/model/layout.ts        MOD  BuildingInstance.parameters; SceneModel.beltRuns
src/model/overlays.ts      MOD  belt tags + endpoint icons + count placements
src/scene/CountLabels.tsx  NEW  instanced digit quads
src/scene/BeltChevrons.tsx NEW  instanced direction arrows
scripts/extract_assets.py  MOD  SignalProtoSet + VeinProtoSet into the atlas
```

`beltGraph` is its own module rather than more code in `layout.ts`, which
is already carrying coordinate mapping and bounds. `buildSceneModel`
already receives both `bp` and `catalog`, so it calls `buildBeltGraph` and
exposes the result as `SceneModel.beltRuns` — leaving `buildOverlays`'s
signature unchanged.

### The run graph

```ts
export interface BeltRun {
  belts: number[];        // building indices, head -> tail
  freeInput: boolean;     // no belt feeds the head
  freeOutput: boolean;    // tail's outputObjIdx < 0
  cyclic: boolean;
  carried: number[];      // inferred item ids, sorted, deduped
  hasExplicitTag: boolean;
}
```

**Segmentation is deterministic and independent of iteration order.** A
run starts at any belt whose inbound belt count is not exactly 1, and ends
at the belt whose successor has inbound > 1 (or which has no belt
successor). Defining boundaries by local inbound/outbound degree rather
than by "wherever the walk happened to reach first" means the 12-s-purple
merge splits identically on every run — a walk-order-dependent rule would
assign the shared tail to an arbitrary run.

Belts still unvisited once every head has been walked are in cycles. Each
such component becomes one run with `cyclic: true` and
`freeInput/freeOutput: false`, so it contributes no endpoint icons. The
walk carries a visited set regardless, so a malformed blueprint cannot
hang the renderer.

### Tag resolution

`catalog.tagIconName(signalId)` mirrors `SignalProtoSet.IconSprite`
exactly, all five bands, returning `undefined` for anything unresolvable.
Recipes route through the existing `recipeIconName`, which already handles
the empty-`IconPath` fallback to the first result's icon.

The extractor gains `SignalProtoSet` (39 sprites) and `VeinProtoSet` into
the existing atlas, with matching assertions so a missing or renamed table
fails loudly rather than silently dropping icons — following the
extraction invariants already established in `extract_assets.py`.

`TechProto` icons are not extracted: tech tags on factory belts are
vanishingly rare and the table is large. Instead, **any tag id that
resolves to no icon is collected into `SceneModel.unresolvedTagIds`**,
alongside the existing `unknownItemIds` diagnostic, and surfaced in the UI.
A gap becomes visible rather than looking like an untagged belt.

### Carried-item inference

For each run, `carried` is the union over every sorter with an endpoint on
that run:

1. **`filterId > 0`** — authoritative, use it.
2. **`filterId == 0`** — fall back to the building at the sorter's other
   end: pulling *from* it contributes that recipe's results, pushing
   *into* it contributes that recipe's inputs.

Both directions count: what is taken off a belt and what is put onto it
equally describe its contents.

A sorter feeding a multi-input recipe is genuinely ambiguous — the
blueprint does not say which input that sorter carries. All candidate
inputs are contributed rather than guessing one, on the grounds that
showing "one of these" beats showing a confident wrong answer.

### Rendering

Icons already carry an explicit world `position` in `IconPlacement`, so
several icons at one endpoint need no type change — just several
placements fanned along the run's heading so they do not overlap.
`buildOverlays` gains a second pass over `model.beltRuns` after its
existing per-building loop, emitting:

- the **explicit tag icon** for every belt whose `parameters` is non-empty;
- **inferred endpoint icons** at a run's free head and free tail;
- a `CountPlacement { position, value }` for every non-zero tag count.

Counts render as instanced digit quads (`CountLabels.tsx`) sampling a
**digit atlas generated at runtime** by drawing `0`–`9` into a 2D canvas
strip. Digits are not game data, so this keeps the extractor untouched and
adds no font file. Because blueprint counts are always integers, ten
glyphs suffice — no text shaping, no SDF font. Digits lie in the same flat
plane as the icons and are centred beneath them, so they read at the
isometric camera angle exactly as the icons do.

**Counts render only when non-zero**, because 0 is the unset value (see
Verified facts) and applies to 95 of 109 tagged belts; drawing "0" on all
of them would be noise, not fidelity.

Chevrons (`BeltChevrons.tsx`) instance one small arrow per belt, oriented
by a per-belt `headingRad` computed in `beltGraph` from the run order —
the bearing to its successor, with the tail reusing its predecessor's.
Direction lives in the model layer so it is pure and testable; the scene
component only draws.

## Decisions

**Explicit tags suppress inference at run level.** If any belt in a run
carries its own tag, that run gets no inferred endpoint icons; explicit
tags always draw, wherever they sit. This reads "for those without an
icon" as a property of the run, since a run whose contents the player has
already labelled does not need us guessing at its ends.

**Only `outputObjIdx < 0` counts as unconnected.** A belt feeding a
station is connected; labelling its end would clutter exactly the dense
blueprints where clutter hurts most.

**All five id bands, but not all five icon tables.** Resolving fewer bands
produces wrong icons; extracting fewer tables produces missing ones. The
`unresolvedTagIds` diagnostic makes the second failure visible, which the
first can never be.

## Testing

`tests/model/beltGraph.test.ts` — synthetic chains for the mechanics
(merge splitting determinism, cycle termination, free-end classification,
heading computation), plus fixture assertions locking in the numbers
above: heretical 11 runs / longest 36 and falk mall 280 belts in cycles
(both measured, and unaffected by segmentation since neither has a merge).
For 12-s-purple the test asserts the *segmented* count, which the
implementation must establish empirically — expected to be 23 rather than
the 22 a head-walk reports.

`tests/model/overlays.test.ts` — filter-beats-recipe precedence, both
sorter directions, multi-input fan-out, run-level suppression, and that a
zero count emits no `CountPlacement`.

`tests/model/catalog.test.ts` — one case per id band, including a
band-boundary case and an unresolvable id landing in `unresolvedTagIds`.

All of this is pure model-layer work with no I/O. No test may fetch: the
happy-dom default origin is `http://localhost:3000`, rsbuild's own dev
port, so an unmocked fetch silently hits the dev server.

## Completion criteria

- Belt tags render with icon and, when non-zero, number.
- Unconnected run ends show inferred contents; cyclic runs show none.
- Belts show flow direction.
- `bun run test`, `typecheck`, `lint`, `eslint`, `build` all clean, with
  the full output scanned rather than the pass count.
- Visual check in the browser against `factory-endgame-distribution-hub`
  (47 tagged belts) and `falk-v7-mall-full` (cycles + 55 filtered end
  sorters).
- **`docs/BACKLOG.md` items 1 and 2 are deleted** — belt icons and belt
  direction chevrons, both delivered here. Item 3 (station, splitter and
  monitor parameter payloads) stays: this work decodes the *belt*
  parameter block only and leaves those untouched.
