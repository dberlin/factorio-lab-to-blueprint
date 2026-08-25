import { readFileSync } from 'node:fs';
import { buildCatalog } from '../../src/model/catalog';

/**
 * A real catalog, built from a checked-in snapshot of the extractor's output.
 *
 * Tests may not read public/assets (build output) and may not touch the
 * network, so the snapshot lives here instead. `scripts/extract_assets.py`
 * writes this directory itself, from the same write() calls that produce
 * public/assets, so a re-extraction that changes the catalog shows up here
 * as a reviewable diff -- not as a silent no-op against a stale snapshot.
 */
const load = (name: string): unknown =>
  JSON.parse(readFileSync(`tests/fixtures/catalog/${name}.json`, 'utf8'));

export const realCatalog = buildCatalog({
  items: load('items'),
  recipes: load('recipes'),
  models: load('models'),
  tags: load('tags'),
});
