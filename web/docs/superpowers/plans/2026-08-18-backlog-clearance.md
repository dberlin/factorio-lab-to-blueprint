# Backlog Clearance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close all four items in `docs/BACKLOG.md` and leave that file with no items standing.

**Architecture:** Three independent strands. (a) The info panel gains inferred-content rows, sourced from `BeltRun.carried` and from a new per-sorter query, kept out of `describeParameters` so its nineteen per-building decoders stay pure. (b) A checked-in catalog snapshot unlocks fixture-level assertions on the classification chain. (c) Five decoders start printing names instead of raw integers, using enum values decompiled from the game and recorded in the spec.

**Tech Stack:** TypeScript, React 19 + React Compiler, react-three-fiber 9 / three 0.185, zod/mini, rstest + happy-dom, biome + eslint, bun.

**Spec:** `docs/superpowers/specs/2026-08-18-backlog-clearance-design.md`

## Global Constraints

- `src/format/`, `src/model/` and `src/server/` import neither React nor three.js. Enforced by `tests/architecture.test.ts`.
- **No test may perform network I/O.** happy-dom resolves relative URLs against `http://localhost:3000`, which is rsbuild's own dev port, so a stray fetch silently hits the dev server. Tests must not read `public/assets` either — it is build output.
- Verification means reading the whole output and grepping *for trouble* (`error|warn|abort|ECONNRESET|unhandled|reject`), not grepping for a passing count. A zero exit code with "223 passed" has previously hidden two real errors on stderr.
- Gate for every task: `bun run test`, `bun run typecheck`, `bun run lint`, `bun run build` — all must be clean. Run `bun run format` before `lint` if biome complains about formatting.
- Commit messages: use `git commit -F <file>` or a heredoc. Backticks in a commit message get mangled by the shell.
- Each task removes the backlog item it closes, **in the same commit as the code**, so `docs/BACKLOG.md` is never lying about what is outstanding.
- Decompiling a game type, when a task needs evidence the spec does not already record:
  ```bash
  export DOTNET_ROLL_FORWARD=LatestMajor
  ~/.dotnet/tools/ilspycmd -t <TypeName> \
    "/Users/dannyb/Downloads/Dyson Sphere Program/DSPGAME_Data/Managed/Assembly-CSharp.dll"
  ```
  Omitting `DOTNET_ROLL_FORWARD` fails with "You must install or update .NET to run this application". That is a version mismatch, not a missing tool.

---

## File Structure

| File | Responsibility | Tasks |
|------|----------------|-------|
| `src/model/beltGraph.ts` | Belt runs and inference. Gains `runForBelt` and `sorterContents`; `itemsForSorter` becomes reachable from the latter. | 1, 2 |
| `src/model/params.ts` | Per-building parameter decoding. Gains `describeInferred` and the `ParamRow.inferred` flag; five decoders start naming enums. | 1, 2, 4, 5 |
| `src/ui/InfoPanel.tsx` | Renders both row lists and marks inferred `<dd>`s. | 1 |
| `src/ui/app.css` | Styling for the inferred marker. | 1 |
| `tests/fixtures/catalog/*.json` | Checked-in catalog snapshot (items, recipes, models, tags). | 3 |
| `tests/support/catalog.ts` | Builds a real `Catalog` from that snapshot. | 3 |
| `tests/model/classification.test.ts` | Fixture-level assertions on typing and inference. | 3 |
| `docs/BACKLOG.md` | Emptied one item per task. | 2, 3, 4, 5 |

---

### Task 1: Inferred belt contents in the info panel

Closes the belt half of backlog item 1. The sorter half is Task 2, and Task 2 removes the item.

**Files:**
- Modify: `src/model/beltGraph.ts` (add `runForBelt` near `buildBeltRuns`)
- Modify: `src/model/params.ts` (add `inferred` to `ParamRow`; add `describeInferred` after `describeParameters`)
- Modify: `src/ui/InfoPanel.tsx`
- Modify: `src/ui/app.css`
- Test: `tests/model/params.test.ts`, `tests/ui/InfoPanel.coverage.test.tsx`

**Interfaces:**
- Consumes: `BeltRun` (`{ belts: number[]; carried: number[]; … }`), `isBelt(itemId)`, `Catalog.item(id)`, `useBlueprint()` which already exposes `sceneModel`.
- Produces:
  - `runForBelt(index: number, runs: readonly BeltRun[]): BeltRun | undefined`
  - `describeInferred(b: BlueprintBuilding, bp: Blueprint, runs: readonly BeltRun[], catalog: Catalog): ParamRow[]`
  - `ParamRow` gains `inferred?: boolean`

- [ ] **Step 1: Write the failing test**

Add to `tests/model/params.test.ts`. `describeInferred` needs a `Blueprint`; the existing `rowsFor` helper builds a bare building, so build the blueprint inline.

```ts
import { buildBeltRuns, inferCarried } from '../../src/model/beltGraph';
import { describeInferred } from '../../src/model/params';

test('clicking a belt reports the contents inferred for its run', () => {
  // belt 0 <- sorter 1 <- assembler 2 making Iron Ingot. Nothing on the belt
  // record itself says "Iron Ingot"; the run is the only thing that knows.
  const parsed = bp([belt(0, -1), sorter(1, 2, 0), assembler(2)]);
  const runs = buildBeltRuns(parsed);
  inferCarried(parsed, runs, catalog);

  const rows = describeInferred(parsed.buildings[0]!, parsed, runs, catalog);
  expect(rows).toEqual([{ label: 'Carries', value: 'Iron Ingot', inferred: true }]);
});

test('a belt whose run carries nothing gets no inferred row', () => {
  const parsed = bp([belt(0, -1)]);
  const runs = buildBeltRuns(parsed);
  inferCarried(parsed, runs, catalog);
  expect(describeInferred(parsed.buildings[0]!, parsed, runs, catalog)).toEqual([]);
});

test('a non-belt, non-sorter building gets no inferred rows', () => {
  const parsed = bp([belt(0, -1), sorter(1, 2, 0), assembler(2)]);
  const runs = buildBeltRuns(parsed);
  inferCarried(parsed, runs, catalog);
  expect(describeInferred(parsed.buildings[2]!, parsed, runs, catalog)).toEqual([]);
});
```

`bp`, `belt`, `sorter` and `producer(index, recipeId)` already exist in
`tests/model/beltGraph.test.ts` — the recipe-carrying helper is called
`producer`, not `assembler`. Copy them into `params.test.ts` rather than
importing across test files, and rename `producer` to `assembler` in the copy
or adjust the tests above to say `producer`; do not leave two names for it.

- [ ] **Step 2: Run test to verify it fails**

Run: `bun run test 2>&1 | grep -E "failedTests|passedTests"`
Expected: FAIL — `describeInferred` is not exported from `params.ts`.

- [ ] **Step 3: Add the run lookup**

In `src/model/beltGraph.ts`, immediately after `buildBeltRuns`:

```ts
/**
 * The run a belt belongs to, or undefined if the index is not a belt in any
 * run. Linear in the number of belts; the info panel calls it once per click,
 * not once per frame.
 */
export function runForBelt(index: number, runs: readonly BeltRun[]): BeltRun | undefined {
  return runs.find((run) => run.belts.includes(index));
}
```

- [ ] **Step 4: Add the inferred flag and the row builder**

In `src/model/params.ts`, extend the row type:

```ts
export interface ParamRow {
  label: string;
  value: string;
  /**
   * The value was derived from the surrounding blueprint, not read from this
   * building's own record. The panel marks these so a reader never mistakes
   * an inference for a recorded setting.
   */
  inferred?: boolean;
}
```

Add the imports at the top of `params.ts`:

```ts
import type { Blueprint, BlueprintBuilding } from '../format';
import { type BeltRun, isBelt, runForBelt } from './beltGraph';
```

(`BlueprintBuilding` is already imported; add `Blueprint` to the same clause.)

Add after `describeParameters`:

```ts
const names = (ids: readonly number[], catalog: Catalog): string =>
  ids.map((id) => catalog.item(id)?.name ?? `#${id}`).join(', ');

/**
 * Rows the blueprint implies but no single record states.
 *
 * Deliberately separate from describeParameters: that function decodes one
 * building's own parameter block and all nineteen of its decoders are pure in
 * (parameters, catalog). Inference needs the whole blueprint and the belt
 * runs, and threading those through would hand every decoder two arguments
 * none of them use.
 */
export function describeInferred(
  b: BlueprintBuilding,
  bp: Blueprint,
  runs: readonly BeltRun[],
  catalog: Catalog,
): ParamRow[] {
  if (isBelt(b.itemId)) {
    const run = runForBelt(b.index, runs);
    if (!run || run.carried.length === 0) return [];
    return [{ label: 'Carries', value: names(run.carried, catalog), inferred: true }];
  }
  return [];
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `bun run test 2>&1 | grep -E "failedTests|passedTests"`
Expected: PASS, with the three new tests counted.

- [ ] **Step 6: Render the rows in the panel**

In `src/ui/InfoPanel.tsx`, take `sceneModel` from the hook and concatenate:

```tsx
import { describeInferred, describeParameters } from '../model/params';
...
  const { blueprint, catalog, selectedIndex, sceneModel } = useBlueprint();
```

Replace the `describeParameters(b, catalog).map(...)` expression's source with a
combined list computed just above the `return`:

```tsx
  const rows = [
    ...describeParameters(b, catalog),
    ...(sceneModel ? describeInferred(b, blueprint, sceneModel.beltRuns, catalog) : []),
  ];
```

and change the JSX to map over `rows`, marking the inferred ones:

```tsx
        {rows.map((row, i) => (
          // Rows are freshly derived from a pure function every render (never
          // reordered independent of content); combining the index with the
          // label keeps keys unique even if a future decoder emits duplicates.
          // biome-ignore lint/suspicious/noArrayIndexKey: see comment above
          <Fragment key={`${i}-${row.label}`}>
            <dt>{row.label}</dt>
            <dd className={row.inferred ? 'inferred' : undefined}>
              {row.value}
              {row.inferred && <span className="inferred-tag"> (inferred)</span>}
            </dd>
          </Fragment>
        ))}
```

`sceneModel` is declared `SceneModel | null` in
`src/state/BlueprintProvider.tsx:8` and is built only when a blueprint is
loaded (`:31`), so the ternary is real and not dead code.

- [ ] **Step 7: Style the marker**

In `src/ui/app.css`, following whatever custom-property and selector
conventions the file already uses:

```css
.info dd.inferred {
  font-style: italic;
}

.info .inferred-tag {
  font-style: normal;
  font-size: 0.85em;
  opacity: 0.7;
}
```

- [ ] **Step 8: Write the panel test**

In `tests/ui/InfoPanel.coverage.test.tsx`, following the file's existing
render helper:

```tsx
test('an inferred row is marked as inferred in the panel', () => {
  // ...render with a belt selected whose run carries Iron Ingot...
  const dd = screen.getByText('Iron Ingot').closest('dd');
  expect(dd?.className).toContain('inferred');
  expect(dd?.textContent).toContain('(inferred)');
});
```

Match the file's existing setup for building a provider-wrapped panel; do not
invent a new one.

- [ ] **Step 9: Run the full gate**

Run: `bun run test 2>&1 | grep -iE "error|warn|abort|ECONNRESET|unhandled|reject|failedTests|passedTests"`
Then: `bun run typecheck && bun run lint && bun run build`
Expected: no failures, and no error/warning lines beyond the known-clean output.

- [ ] **Step 10: Commit**

```bash
git add src/model/beltGraph.ts src/model/params.ts src/ui/InfoPanel.tsx src/ui/app.css tests/
git commit -F - <<'EOF'
feat(ui): show a belt's inferred contents in the info panel

The scene already draws inferred endpoint icons, but clicking a belt showed
only its own record, which says nothing about what it carries. The answer
lives on the belt run, one level up in SceneModel.

describeInferred is a sibling of describeParameters rather than an extension
of it: the nineteen per-building decoders are pure in (parameters, catalog),
and inference needs the whole blueprint plus the runs.

Rows carry an explicit `inferred` flag and the panel marks them, so a reader
never mistakes a derived value for a recorded setting.
EOF
```

---

### Task 2: Inferred sorter contents in the info panel

Closes backlog item 1 and removes it.

**Files:**
- Modify: `src/model/beltGraph.ts` (export `sorterContents`)
- Modify: `src/model/params.ts` (extend `describeInferred`)
- Modify: `docs/BACKLOG.md` (delete the "Show inferred belt/sorter contents in the info panel" section)
- Test: `tests/model/params.test.ts`

**Interfaces:**
- Consumes: `itemsForSorter(sorter, other, side, catalog)` — currently module-private in `beltGraph.ts`; `isSorter(itemId)`.
- Produces: `sorterContents(s: BlueprintBuilding, bp: Blueprint, catalog: Catalog): { takes: number[]; puts: number[] }`

- [ ] **Step 1: Write the failing test**

```ts
test('clicking a sorter reports what it takes off and puts on a belt', () => {
  // sorter 1 draws from assembler 2 (Iron Ingot) and puts onto belt 0.
  const parsed = bp([belt(0, -1), sorter(1, 2, 0), assembler(2)]);
  const runs = buildBeltRuns(parsed);
  inferCarried(parsed, runs, catalog);

  const rows = describeInferred(parsed.buildings[1]!, parsed, runs, catalog);
  expect(rows).toEqual([{ label: 'Puts on belt', value: 'Iron Ingot', inferred: true }]);
});

test('a sorter draining a belt reports what it takes off it', () => {
  // sorter 1 draws from belt 0 and delivers into assembler 2, so it removes
  // that assembler's ingredients.
  const parsed = bp([belt(0, -1), sorter(1, 0, 2), assembler(2)]);
  const runs = buildBeltRuns(parsed);
  inferCarried(parsed, runs, catalog);

  const rows = describeInferred(parsed.buildings[1]!, parsed, runs, catalog);
  expect(rows.map((r) => r.label)).toEqual(['Takes from belt']);
});

test('a filtered sorter gets no inferred row, because its filter is read not inferred', () => {
  // describeParameters already prints a Filter row for this building; a second
  // row saying the same thing, marked "inferred", would be false.
  const parsed = bp([belt(0, -1), { ...sorter(1, 2, 0), filterId: 1101 }, assembler(2)]);
  const runs = buildBeltRuns(parsed);
  inferCarried(parsed, runs, catalog);
  expect(describeInferred(parsed.buildings[1]!, parsed, runs, catalog)).toEqual([]);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bun run test 2>&1 | grep -E "failedTests|passedTests"`
Expected: FAIL — the sorter branch returns `[]`.

- [ ] **Step 3: Export the per-sorter query**

In `src/model/beltGraph.ts`, add above the private `itemsForSorter`:

```ts
/**
 * What one sorter is inferred to move, per end.
 *
 * `inferCarried` answers the same question but attributes the result to belt
 * runs; this attributes it to the sorter, which is what the info panel needs
 * when a sorter is the selected building. A sorter belongs to no run.
 *
 * The two ends are reported separately, never merged: a sorter that takes
 * Iron Ore off a belt and puts Iron Ingot on another moves both, but not in
 * the same direction, and one merged list would say it moves each in both.
 */
export function sorterContents(
  s: BlueprintBuilding,
  bp: Blueprint,
  catalog: Catalog,
): { takes: number[]; puts: number[] } {
  const byIndex = new Map<number, BlueprintBuilding>();
  for (const b of bp.buildings) byIndex.set(b.index, b);

  // Mirrors inferCarried exactly. Draining a belt delivers into outputObjIdx,
  // so what comes off the belt is that building's inputs; feeding a belt draws
  // from inputObjIdx, so what goes on is that building's results.
  return {
    takes: [...itemsForSorter(s, byIndex.get(s.outputObjIdx), 'inputs', catalog)],
    puts: [...itemsForSorter(s, byIndex.get(s.inputObjIdx), 'results', catalog)],
  };
}
```

- [ ] **Step 4: Extend describeInferred**

Replace the `return [];` tail of `describeInferred` with:

```ts
  if (isSorter(b.itemId)) {
    // A set filterId is read from the record, not inferred -- describeParameters
    // already emits it as the Filter row. Repeating it here, marked "inferred",
    // would misreport how confident we are.
    if (b.filterId > 0) return [];

    const beltIndices = new Set(runs.flatMap((run) => run.belts));
    const { takes, puts } = sorterContents(b, bp, catalog);
    const rows: ParamRow[] = [];
    // Report an end only when that end is actually a belt.
    if (beltIndices.has(b.inputObjIdx) && takes.length > 0) {
      rows.push({ label: 'Takes from belt', value: names(takes, catalog), inferred: true });
    }
    if (beltIndices.has(b.outputObjIdx) && puts.length > 0) {
      rows.push({ label: 'Puts on belt', value: names(puts, catalog), inferred: true });
    }
    return rows;
  }

  return [];
```

Add `isSorter` and `sorterContents` to the `beltGraph` import clause in `params.ts`.

- [ ] **Step 5: Run test to verify it passes**

Run: `bun run test 2>&1 | grep -E "failedTests|passedTests"`
Expected: PASS.

- [ ] **Step 6: Check it against a real blueprint**

Do not trust synthetic fixtures alone here — this is the third time on this
project that a change passed every test and was still wrong in the app.

```bash
bun run dev
```

Load `tests/fixtures/factory-endgame-distribution-hub.txt`, click a belt in a
run that draws icons, and confirm the panel reports the same items the icons
show. Then click one of the sorters at that run's end and confirm its
direction rows read correctly. Record what you saw in the commit or ledger.

- [ ] **Step 7: Remove the backlog item**

Delete the whole `## Show inferred belt/sorter contents in the info panel`
section from `docs/BACKLOG.md`, heading and body.

- [ ] **Step 8: Run the full gate**

Run: `bun run test 2>&1 | grep -iE "error|warn|abort|ECONNRESET|unhandled|reject|failedTests|passedTests"`
Then: `bun run typecheck && bun run lint && bun run build`

- [ ] **Step 9: Commit**

```bash
git add src/model/beltGraph.ts src/model/params.ts docs/BACKLOG.md tests/
git commit -F - <<'EOF'
feat(ui): show a sorter's inferred contents in the info panel

A sorter belongs to no belt run, so the run-level answer does not apply to
it. sorterContents attributes the same inference to the sorter itself and
reports its two ends separately: merging them would claim one sorter moves
each item in both directions.

A sorter with a filterId set gets no inferred row at all -- that filter is
read from the record and describeParameters already prints it. Marking it
"inferred" would misreport how much we actually know.

Retires the backlog item.
EOF
```

---

### Task 3: Pin the classification chain on real fixtures

Closes backlog item 2 and removes it.

**Files:**
- Create: `tests/fixtures/catalog/items.json`, `recipes.json`, `models.json`, `tags.json`
- Create: `tests/support/catalog.ts`
- Create: `tests/model/classification.test.ts`
- Modify: `docs/BACKLOG.md`

**Interfaces:**
- Consumes: `buildCatalog({ items, recipes, models, tags })`, `parseBlueprint`, `buildBeltRuns`, `inferCarried`, `describeParameters`, `Catalog.buildingTypeFor`.
- Produces: `realCatalog: Catalog` exported from `tests/support/catalog.ts`.

- [ ] **Step 1: Snapshot the catalog**

The four files total ~54 KB, small enough to check in whole. No trimming, no
generator, so there is nothing that can drift out of step with itself.

```bash
mkdir -p tests/fixtures/catalog
cp public/assets/items.json public/assets/recipes.json \
   public/assets/models.json public/assets/tags.json tests/fixtures/catalog/
```

If `public/assets` is missing, run `bun run extract-assets` first — it needs
the game install at `/Users/dannyb/Downloads/Dyson Sphere Program`.

- [ ] **Step 2: Add the catalog helper**

Create `tests/support/catalog.ts`:

```ts
import { readFileSync } from 'node:fs';
import { buildCatalog } from '../../src/model/catalog';

/**
 * A real catalog, built from a checked-in snapshot of the extractor's output.
 *
 * Tests may not read public/assets (build output) and may not touch the
 * network, so the snapshot lives here instead. It can drift from a
 * re-extraction; that diff is the signal, not a failure -- review it when
 * `bun run extract-assets` changes these files.
 */
const load = (name: string): unknown =>
  JSON.parse(readFileSync(`tests/fixtures/catalog/${name}.json`, 'utf8'));

export const realCatalog = buildCatalog({
  items: load('items'),
  recipes: load('recipes'),
  models: load('models'),
  tags: load('tags'),
});
```

If `buildCatalog`'s parameter type rejects `unknown`, look at how
`BlueprintProvider` feeds it and match that — it validates with zod
internally, so the raw parsed JSON is the right input.

- [ ] **Step 3: Write the failing test**

Create `tests/model/classification.test.ts`:

```ts
import { readdirSync, readFileSync } from 'node:fs';
import { expect, test } from '@rstest/core';
import { parseBlueprint } from '../../src/format';
import { buildBeltRuns, inferCarried } from '../../src/model/beltGraph';
import { describeParameters } from '../../src/model/params';
import { realCatalog } from '../support/catalog';

/** Every factory fixture. Dyson-sphere blueprints are a different format. */
function factoryFixtures(): { name: string; bp: ReturnType<typeof parseBlueprint> }[] {
  const out = [];
  for (const name of readdirSync('tests/fixtures').filter((f) => f.endsWith('.txt'))) {
    try {
      out.push({ name, bp: parseBlueprint(readFileSync(`tests/fixtures/${name}`, 'utf8').trim()) });
    } catch {
      // DYBP (Dyson sphere) fixtures are deliberately unsupported.
    }
  }
  return out;
}

test('every parameter-carrying building in every fixture resolves to a known type', () => {
  let withParams = 0;
  const untyped: string[] = [];
  for (const { name, bp } of factoryFixtures()) {
    for (const b of bp.buildings) {
      if (b.parameters.length === 0) continue;
      withParams++;
      if (!realCatalog.buildingTypeFor(b.modelIndex, b.itemId)) {
        untyped.push(`${name} item=${b.itemId} model=${b.modelIndex}`);
      }
    }
  }
  // The whole point of deriving types from the game's own *Desc markers.
  expect(untyped).toEqual([]);
  expect(withParams).toBeGreaterThanOrEqual(1900);
});

test('no real building falls back to the generic word-count row', () => {
  const generic: string[] = [];
  for (const { name, bp } of factoryFixtures()) {
    for (const b of bp.buildings) {
      if (b.parameters.length === 0) continue;
      if (describeParameters(b, realCatalog).some((r) => r.label === 'Parameters')) {
        generic.push(`${name} item=${b.itemId} model=${b.modelIndex}`);
      }
    }
  }
  expect(generic).toEqual([]);
});

test('inferred belt contents are always real item ids', () => {
  // A decoder reading the wrong region shows up here as a non-item id long
  // before anyone notices a missing icon. This is what caught the Battlefield
  // Analysis Base reading its drone loadout as cargo.
  const ids = new Set(realCatalog.allItems().map((i) => i.id));
  const bad = new Set<number>();
  for (const { bp } of factoryFixtures()) {
    const runs = buildBeltRuns(bp);
    inferCarried(bp, runs, realCatalog);
    for (const run of runs) for (const c of run.carried) if (!ids.has(c)) bad.add(c);
  }
  expect([...bad]).toEqual([]);
});

test('the endgame hub infers contents for the runs it can reach', () => {
  const bp = parseBlueprint(
    readFileSync('tests/fixtures/factory-endgame-distribution-hub.txt', 'utf8').trim(),
  );
  const runs = buildBeltRuns(bp);
  inferCarried(bp, runs, realCatalog);
  expect(runs.length).toBe(118);
  expect(runs.filter((r) => r.carried.length > 0).length).toBe(34);
});
```

- [ ] **Step 4: Run test to verify it passes**

Unlike a normal TDD step these assert existing behaviour, so they should pass
immediately. That is the point — they are a regression guard, not a driver.

Run: `bun run test tests/model/classification.test.ts 2>&1 | tail -30`
Expected: PASS, 4 tests.

- [ ] **Step 5: Verify the tests can actually fail**

A guard that cannot fail is worse than none, because it reads as coverage.
Temporarily break one thing and confirm the right test goes red, then undo it:

```bash
# In src/model/beltGraph.ts, change the Storage branch slice(10) to slice(1).
bun run test tests/model/classification.test.ts 2>&1 | tail -20
# Expect: 'inferred belt contents are always real item ids' FAILS, because
# word 1 is the storage type (9 on a configured depot) and 9 is not an item.
git checkout src/model/beltGraph.ts
```

Note what this guard does NOT catch, and say so in a comment in the test
file. Measured across all 79 Storage buildings in the fixtures: word 0
(bans) takes `{0, 25, 26, 28, 29}`, word 1 (storage type) takes `{0, 9}`,
and **words 2..9 are always zero**. So no off-by-one in the region offset is
observable — `slice(9)` reads a guaranteed zero that the `> 0` filter drops,
and `slice(11)` merely omits one of thirty identical filters that dedupe to
the same set. The guard catches region *confusion* — reading the mode words
as filters — which is precisely the bug that shipped on the previous branch,
where a Battlefield Analysis Base returned `workEnergyPerTick` and its
fighter loadout as belt cargo.

Record in the commit that you did this and which test fired.

- [ ] **Step 6: Confirm no network I/O**

```bash
lsof -i :3000    # expect no output: nothing listening
bun run test 2>&1 | grep -iE "ECONNRESET|fetch|localhost:3000|ENOTFOUND"
```
Expected: no matches.

- [ ] **Step 7: Remove the backlog item**

Delete the whole `## Pin the classification chain with a fixture-level test`
section from `docs/BACKLOG.md`.

- [ ] **Step 8: Run the full gate**

Run: `bun run test 2>&1 | grep -iE "error|warn|abort|ECONNRESET|unhandled|reject|failedTests|passedTests"`
Then: `bun run typecheck && bun run lint && bun run build`

- [ ] **Step 9: Commit**

```bash
git add tests/fixtures/catalog tests/support/catalog.ts tests/model/classification.test.ts docs/BACKLOG.md
git commit -F - <<'EOF'
test: pin the classification chain against real fixtures

The load-bearing numbers -- every parameter-carrying building across the
fixtures resolving to a known type, none falling back to the generic row,
and no non-item id ever reaching a belt run -- were checked only by hand.
Every test built a synthetic catalog, because tests may not read
public/assets and may not touch the network.

A checked-in catalog snapshot removes that obstacle. At ~54 KB the whole
extractor output fits, so there is no trimming step to drift out of step
with what it claims to represent.

Verified the guard can fail: changing the depot filter slice from 10 to 9
turns the non-item-id test red.

Retires the backlog item.
EOF
```

---

### Task 4: Render the remaining enum words as names

Closes backlog item 3 and removes it. Every value below is quoted from the
spec's Evidence section; do not re-derive them, and do not add names for
words the spec does not cover.

**Files:**
- Modify: `src/model/params.ts` (`Exchanger`, `Lab`, `Dispenser`, `Turret` decoders)
- Modify: `docs/BACKLOG.md`
- Test: `tests/model/params.test.ts`

**Interfaces:**
- Consumes: the existing `at`, `bool` and `enumName` helpers in `params.ts`.
- Produces: no new exports.

- [ ] **Step 1: Write the failing tests**

Extend the table-driven `decoderCases` array in `tests/model/params.test.ts`.
Replace the existing `Exchanger`, `Lab`, `Dispenser` and `Turret` cases:

```ts
  {
    // targetState, clamped to -1..1. InputUpdate runs only at state 1 and
    // input means drawing from the grid, so 1 is charge.
    type: 'Exchanger',
    modelIndex: 113,
    parameters: [-1],
    expect: [['Exchanger mode', 'Discharge']],
  },
  {
    type: 'Exchanger',
    modelIndex: 113,
    parameters: [1],
    expect: [['Exchanger mode', 'Charge']],
  },
  {
    type: 'Exchanger',
    modelIndex: 113,
    parameters: [0],
    expect: [['Exchanger mode', 'Standby']],
  },
  {
    // mode0 2 = research, mode1 = forceAccMode -- the same proliferator
    // toggle the Assembler decoder renders, which Lab used to drop.
    type: 'Lab',
    modelIndex: 107,
    parameters: [2, 1],
    expect: [
      ['Lab mode', 'Research'],
      ['Proliferator', 'production speedup'],
    ],
  },
  {
    type: 'Lab',
    modelIndex: 107,
    parameters: [1, 0],
    expect: [
      ['Lab mode', 'Matrix production'],
      ['Proliferator', 'extra products'],
    ],
  },
  {
    // EPlayerDeliveryMode { None, Recycle, Both, Supply }
    // EStorageDeliveryMode { None, Supply, Demand }
    type: 'Dispenser',
    modelIndex: 102,
    parameters: [2, 1, 0, 1],
    expect: [
      ['Player mode', 'Both'],
      ['Storage mode', 'Supply'],
      ['Courier auto-replenish', 'yes'],
    ],
  },
  {
    // Turret is the one shifted type: [1] is mode0 (group), [2] is mode1
    // (vsSettings). VSLayerMask packs two bits per band, and High is
    // Low|Normal -- 5 is GroundLow | AirLow.
    type: 'Turret',
    modelIndex: 103,
    parameters: [99, 5, 5, 0, 0],
    expect: [
      ['Turret group', '5'],
      ['Target layers', 'Ground Low, Air Low'],
    ],
  },
  {
    type: 'Turret',
    modelIndex: 103,
    parameters: [99, 5, 3, 0, 0],
    expect: [
      ['Turret group', '5'],
      ['Target layers', 'Ground High'],
    ],
  },
```

Keep the existing neighbour-differing convention (`Turret: [99, 5]` deliberately
sets word 0 to a value that would be wrong if read) so a wrong index cannot
coincidentally pass.

- [ ] **Step 2: Run tests to verify they fail**

Run: `bun run test 2>&1 | grep -E "failedTests|passedTests"`
Expected: FAIL on the enum cases.

- [ ] **Step 3: Implement the decoders**

Add the tables near the existing `LOGISTIC_STORAGE`/`IO_DIR` usage in
`params.ts`:

```ts
/** Lab mode0 (BuildingParameters.cs:1254-1263). */
const LAB_MODE = ['Idle', 'Matrix production', 'Research'] as const;
/** EPlayerDeliveryMode, verbatim from the DLL. */
const PLAYER_DELIVERY = ['None', 'Recycle', 'Both', 'Supply'] as const;
/** EStorageDeliveryMode, verbatim from the DLL. */
const STORAGE_DELIVERY = ['None', 'Supply', 'Demand'] as const;

/**
 * VSLayerMask packs a two-bit level into a field per band, so the enum's
 * composite members are unions rather than distinct values: GroundHigh (3) is
 * GroundLow (1) | GroundNormal (2). Decode by band, not by member lookup.
 */
const VS_BANDS = ['Ground', 'Air', 'Orbit', 'Space'] as const;
const VS_LEVELS = ['', 'Low', 'Normal', 'High'] as const;

function targetLayers(mask: number): string {
  const on: string[] = [];
  VS_BANDS.forEach((band, i) => {
    const level = (mask >> (i * 2)) & 0b11;
    if (level > 0) on.push(`${band} ${VS_LEVELS[level]}`);
  });
  return on.join(', ');
}
```

Then replace the four decoders:

```ts
  Dispenser(p) {
    const rows: ParamRow[] = [];
    const player = at(p, 0);
    const storage = at(p, 1);
    if (player !== undefined)
      rows.push({ label: 'Player mode', value: enumName(PLAYER_DELIVERY, player) });
    if (storage !== undefined)
      rows.push({ label: 'Storage mode', value: enumName(STORAGE_DELIVERY, storage) });
    const replenish = bool(at(p, 3));
    if (replenish) rows.push({ label: 'Courier auto-replenish', value: replenish });
    return rows;
  },

  Turret(p) {
    // The one shifted type: _parameters[1..4] = mode0..mode3
    // (BuildingParameters.cs:303-314). group is a plain byte, not an enum.
    const rows: ParamRow[] = [];
    const group = at(p, 1);
    if (group !== undefined) rows.push({ label: 'Turret group', value: String(group) });
    const vs = at(p, 2);
    if (vs !== undefined && vs > 0) {
      rows.push({ label: 'Target layers', value: targetLayers(vs) });
    }
    return rows;
  },

  Lab(p) {
    const rows: ParamRow[] = [];
    const mode = at(p, 0);
    if (mode !== undefined) rows.push({ label: 'Lab mode', value: enumName(LAB_MODE, mode) });
    // mode1 = forceAccMode, the same toggle Assembler renders.
    const acc = at(p, 1);
    if (acc !== undefined) {
      rows.push({
        label: 'Proliferator',
        value: acc > 0 ? 'production speedup' : 'extra products',
      });
    }
    return rows;
  },

  Exchanger(p) {
    // targetState = Mathf.Clamp(parameters[0], -1, 1). InputUpdate runs only
    // at state 1 and OutputUpdate only at -1 (PowerExchangerComponent.cs:249,
    // :296); input draws from the grid, so 1 is charging.
    const state = at(p, 0);
    if (state === undefined) return [];
    const name = state > 0 ? 'Charge' : state < 0 ? 'Discharge' : 'Standby';
    return [{ label: 'Exchanger mode', value: name }];
  },
```

Leave `Ejector` alone: `orbitId` is an orbit index, not an enum, and a raw
integer is the correct rendering. Say so in the commit rather than silently
skipping it.

- [ ] **Step 4: Run tests to verify they pass**

Run: `bun run test 2>&1 | grep -E "failedTests|passedTests"`
Expected: PASS.

- [ ] **Step 5: Check the real values these produce**

The synthetic cases prove the mapping; this proves the mapping is the one the
real data needs. Write a throwaway script under `$CLAUDE_JOB_DIR/tmp` (never
in the repo) that loads every fixture with the checked-in catalog from Task 3
and prints the distinct `Exchanger mode`, `Lab mode`, `Player mode`,
`Storage mode` and `Target layers` values it produces.

Expected from the fixtures as measured during review: 32 Energy Exchangers at
`-1` and 13 at `1`, so both `Discharge` and `Charge` should appear and no
`#-1`-style fallback should. 131 labs at mode 1 should read
`Matrix production`. If any row comes out as `#<n>`, stop — the table is
short a member and the spec needs revisiting before this ships.

- [ ] **Step 6: Remove the backlog item**

Delete the whole `## Render the remaining enum words as names` section from
`docs/BACKLOG.md`.

- [ ] **Step 7: Run the full gate**

Run: `bun run test 2>&1 | grep -iE "error|warn|abort|ECONNRESET|unhandled|reject|failedTests|passedTests"`
Then: `bun run typecheck && bun run lint && bun run build`

- [ ] **Step 8: Commit**

```bash
git add src/model/params.ts docs/BACKLOG.md tests/model/params.test.ts
git commit -F - <<'EOF'
feat(model): render building mode words as names

The design says enum words render as their names. Station did; nine other
decoders printed raw integers because the values' meanings were not
established. They are now, from the game's own types:

- Exchanger targetState is clamped to -1..1, and the component runs its
  input path only at state 1. Input draws from the grid, so 1 is Charge,
  -1 Discharge, 0 Standby. It used to show a bare -1 on 32 real buildings.
- Lab mode0 is 0 Idle / 1 Matrix production / 2 Research, and mode1 is
  forceAccMode -- the proliferator toggle Lab was dropping entirely.
- Dispenser modes are EPlayerDeliveryMode and EStorageDeliveryMode.
- Turret mode1 is a VSLayerMask, which packs a two-bit level per band, so
  High is Low|Normal rather than a distinct member. Decoded by band.

Turret group and Ejector orbitId stay raw integers on purpose: a group
number and an orbit index are not enums, and naming them would invent a
vocabulary the game does not have.

Retires the backlog item.
EOF
```

---

### Task 5: Name the station delivery percentages

Closes backlog item 4 and removes it.

**Files:**
- Modify: `src/model/params.ts` (`Station` decoder's delivery row)
- Modify: `src/model/stationParams.ts` (comment only)
- Modify: `docs/BACKLOG.md`
- Test: `tests/model/params.test.ts`

**Interfaces:**
- Consumes: `StationSettings.deliveryDrones`, `.deliveryShips`.
- Produces: no new exports.

- [ ] **Step 1: Write the failing test**

```ts
test('a station reports its delivery load as a percentage', () => {
  // StationComponent uses both as (carries - 1) * value / 100, and the
  // defaults are 10 and 100 -- a percentage of carrying capacity, not a
  // vessel count.
  const p = new Array(2048).fill(0);
  p[0] = 1101;
  p[1] = 1;
  p[326] = 10;
  p[327] = 100;
  const rows = rowsFor({ itemId: 2104, modelIndex: 50, parameters: p });
  expect(rowValue(rows, 'Delivery load (drones / ships)')).toBe('10% / 100%');
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bun run test 2>&1 | grep -E "failedTests|passedTests"`
Expected: FAIL — the row is still labelled `Delivery drones / ships`.

- [ ] **Step 3: Implement**

In the `Station` decoder, replace the delivery row and its comment:

```ts
      // Percentages of a vessel's carrying capacity, not counts:
      // StationComponent computes (droneCarries - 1) * deliveryDrones / 100
      // (:1542) and (shipCarries - 1) * deliveryShips / 100 (:3384), and
      // defaults them to 10 and 100 (:297-298). All 27 real stations in our
      // fixtures are bounded by 100, which is what first made "count" suspect.
      rows.push({
        label: 'Delivery load (drones / ships)',
        value: `${settings.deliveryDrones}% / ${settings.deliveryShips}%`,
      });
```

In `src/model/stationParams.ts`, the `StationSettings` interface comment (if
it carries one for these fields) should say percentage of carrying capacity.
If there is no comment there, add one line above the two fields.

- [ ] **Step 4: Run test to verify it passes**

Run: `bun run test 2>&1 | grep -E "failedTests|passedTests"`
Expected: PASS.

- [ ] **Step 5: Update any test that asserted the old label**

```bash
grep -rn "Delivery drones / ships\|Drones / ships" tests/ src/
```
Expected after fixing: no matches outside a historical commit message.

- [ ] **Step 6: Remove the backlog item**

Delete the whole `## Establish what deliveryDrones / deliveryShips measure`
section from `docs/BACKLOG.md`.

- [ ] **Step 7: Run the full gate**

Run: `bun run test 2>&1 | grep -iE "error|warn|abort|ECONNRESET|unhandled|reject|failedTests|passedTests"`
Then: `bun run typecheck && bun run lint && bun run build`

- [ ] **Step 8: Commit**

```bash
git add src/model/params.ts src/model/stationParams.ts docs/BACKLOG.md tests/model/params.test.ts
git commit -F - <<'EOF'
feat(model): name the station delivery words as percentages

StationComponent computes (droneCarries - 1) * deliveryDrones / 100 and the
matching line for ships, and defaults them to 10 and 100. They are
percentages of a vessel's carrying capacity, not counts of vessels.

The row previously said "Drones / ships", which read as a count and would
have told a player their station holds 100 vessels. It was then softened to
the DLL's field names while the units were unknown; they are known now.

Retires the backlog item.
EOF
```

---

### Task 6: Confirm the backlog is empty and the branch is whole

No new behaviour. This exists because "each task removes its own item" fails
silently if one task skips its step, and because the four strands have not
been run together.

**Files:**
- Verify only: `docs/BACKLOG.md`

- [ ] **Step 1: Confirm no items remain**

```bash
cat docs/BACKLOG.md
grep -c "^## " docs/BACKLOG.md
```
Expected: the title and intro paragraph only, and a `##` count of `0`. If any
section survives, the task that owned it did not finish — go back and finish
it rather than deleting the section here.

- [ ] **Step 2: Run the whole gate on the combined result**

```bash
lsof -i :3000
bun run test 2>&1 | grep -iE "error|warn|abort|ECONNRESET|unhandled|reject|failedTests|passedTests"
bun run typecheck && bun run lint && bun run build
```
Expected: nothing listening on 3000, zero failures, and no error or warning
lines.

- [ ] **Step 3: Check the app**

```bash
bun run dev
```

Load `tests/fixtures/factory-endgame-distribution-hub.txt` and confirm, in one
sitting: a belt shows a `Carries` row marked inferred; a sorter shows its
direction rows; a station shows `Delivery load (drones / ships)` as
percentages; an Energy Exchanger shows `Charge` or `Discharge`, never a bare
`-1`; and a Matrix Lab shows both its mode and its proliferator setting.

- [ ] **Step 4: Report**

Summarise for the user: what each task delivered, that `docs/BACKLOG.md` is
empty of items, and the final test count. Then use
`superpowers:finishing-a-development-branch` to present integration options.

---

## Self-Review

**Spec coverage.** Each of the spec's five completion criteria maps to a task:
belt rows → Task 1; sorter rows → Task 2; fixture-level guard → Task 3; enum
names and the Lab proliferator → Task 4; delivery percentages → Task 5; the
empty backlog → every task's own removal step, verified in Task 6. The spec's
observation that `Turret group` and `Target orbit` are already correct is
honoured by Task 4 leaving `Ejector` alone and keeping `group` raw, with the
commit message saying why.

**Placeholders.** None: every code step carries the actual code, every enum
table carries its values, and every expected test result is stated.

**Type consistency.** `ParamRow.inferred?: boolean` is introduced in Task 1 and
used unchanged in Task 2. `runForBelt(index, runs)` and
`sorterContents(s, bp, catalog)` are defined once and consumed with the same
signatures. `describeInferred(b, bp, runs, catalog)` keeps its four-argument
shape across both tasks. `realCatalog` is exported in Task 3 and used only
there and in Task 4's throwaway probe.

**Verified while writing this plan.** `sceneModel` is exposed by
`useBlueprint()` and typed `SceneModel | null`
(`src/state/BlueprintProvider.tsx:8,31`), so Task 1's guard is correct as
written. The recipe-carrying test helper in `beltGraph.test.ts` is named
`producer`, not `assembler`. The catalog snapshot Task 3 checks in is ~54 KB
across four files — measured, not estimated.

**Known risk.** Task 4's expected fixture distribution (32 Exchangers at `-1`,
13 at `1`, 131 labs at mode 1) is quoted from the previous branch's review
rather than re-measured. Treat a mismatch as a reason to look, not as a
failure.
