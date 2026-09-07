/**
 * Counts the icons buildOverlays actually emits for a blueprint, split into
 * "endpoint" (the inferred belt-run layer) and "other" (per-building recipe /
 * filter icons plus explicit belt tags).
 *
 * Endpoint icons are isolated by running buildOverlays a second time with
 * `beltRuns: []`, which is the only input the endpoint loop reads. That works
 * identically before and after the change, so the two numbers are comparable.
 *
 * The atlas is synthesised from the catalog (every known iconName mapped to
 * cell 0,0) rather than read from public/assets: buildOverlays only ever asks
 * whether a name has a cell.
 */
import { readFileSync } from 'node:fs';

const WEB = process.argv[2] as string;
const files = process.argv.slice(3);

const { parseBlueprint } = await import(`${WEB}/src/format/index.ts`);
const { buildCatalog } = await import(`${WEB}/src/model/catalog.ts`);
const { buildSceneModel } = await import(`${WEB}/src/model/layout.ts`);
const { buildOverlays } = await import(`${WEB}/src/model/overlays.ts`);

const load = (name: string): unknown =>
  JSON.parse(readFileSync(`${WEB}/tests/fixtures/catalog/${name}.json`, 'utf8'));
const catalog = buildCatalog({
  items: load('items'),
  recipes: load('recipes'),
  models: load('models'),
  tags: load('tags'),
});

const names = new Set<string>();
for (const item of load('items') as Array<{ iconName?: string }>) {
  if (item.iconName) names.add(item.iconName);
}
for (const r of load('recipes') as Array<{ iconName?: string; results?: number[] }>) {
  if (r.iconName) names.add(r.iconName);
}
const entries: Record<string, [number, number]> = {};
for (const n of names) entries[n] = [0, 0];
const atlas = { cols: 16, rows: 16, cell: 64, entries };

for (const file of files) {
  const bp = parseBlueprint(readFileSync(file, 'utf8').trim());
  const model = buildSceneModel(bp, catalog);
  const all = buildOverlays(model, catalog, atlas);
  const withoutRuns = buildOverlays({ ...model, beltRuns: [] }, catalog, atlas);
  const endpoint = all.icons.length - withoutRuns.icons.length;
  const runs = model.beltRuns;
  const freeEnds = runs.reduce(
    (n: number, r: { freeInput: boolean; freeOutput: boolean }) =>
      n + (r.freeInput ? 1 : 0) + (r.freeOutput ? 1 : 0),
    0,
  );
  const freeIn = runs.filter((r: { freeInput: boolean }) => r.freeInput).length;
  console.log(
    JSON.stringify({
      file: file.split('/').pop(),
      buildings: bp.buildings.length,
      runs: runs.length,
      freeInputRuns: freeIn,
      freeEnds,
      icons: all.icons.length,
      endpointIcons: endpoint,
      otherIcons: withoutRuns.icons.length,
      counts: all.counts.length,
      beltSizedIcons: all.icons.filter((i: { scale?: number }) => (i.scale ?? 1.6) < 1).length,
      machineSizedIcons: all.icons.filter((i: { scale?: number }) => (i.scale ?? 1.6) >= 1).length,
    }),
  );
}
