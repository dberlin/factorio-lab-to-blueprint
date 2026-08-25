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
  // before anyone notices a missing icon -- a Battlefield Analysis Base whose
  // drone loadout is read as cargo fails this test.
  //
  // What this guard cannot see: an off-by-one at the filter region's own
  // boundary. Words 2..9 of a Storage block are structurally zero across
  // every real depot in these fixtures, so a slice starting one word early
  // reads a guaranteed zero that `v > 0` drops, and one starting one word
  // late just drops the first of many identical filter slots -- the
  // remainder still dedupe to the same set. Neither is observable from real
  // data. What the guard does catch is region *confusion*: reading a
  // neighbouring block's words -- mode flags, a storage-type tag -- as
  // filters, which is the bug class that actually shipped here.
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
