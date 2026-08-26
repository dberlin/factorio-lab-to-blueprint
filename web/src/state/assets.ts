import { buildCatalog, type Catalog } from '../model/catalog';
import { type Atlas, AtlasSchema } from '../model/schemas';

/**
 * Where the extracted game data lives, without a trailing slash.
 *
 * `/assets` is right for the server arm, where rsbuild copies `public/` to the
 * root of what `flab2bp-web` serves. The client-side arm serves the repo's
 * `web/` directory itself, so the same files sit under `./dist/assets` there —
 * which is why this is a variable rather than six string literals.
 */
let base = '/assets';

export function setAssetBase(next: string): void {
  base = next.replace(/\/+$/, '');
}

export function assetPath(relative: string): string {
  return `${base}/${relative}`;
}

async function json(path: string, signal?: AbortSignal): Promise<unknown> {
  const res = await fetch(path, { signal });
  if (!res.ok) {
    throw new Error(
      `Could not load ${path} (${res.status}). Run "bun run extract-assets" to generate public/assets/.`,
    );
  }
  return res.json();
}

export async function loadCatalog(signal?: AbortSignal): Promise<Catalog> {
  const [items, models, recipes, tags] = await Promise.all([
    json(assetPath('items.json'), signal),
    json(assetPath('models.json'), signal),
    json(assetPath('recipes.json'), signal),
    json(assetPath('tags.json'), signal),
  ]);
  return buildCatalog({ items, models, recipes, tags });
}

export async function loadAtlas(signal?: AbortSignal): Promise<Atlas> {
  return AtlasSchema.parse(await json(assetPath('icons/atlas.json'), signal));
}

/**
 * True for the rejection a caller gets when it aborts its own request.
 * That is the caller's own doing, not a load failure, so it should be
 * swallowed rather than reported — and left un-set-state'd, since the
 * component that started it is on its way out.
 */
export function isAbortError(cause: unknown): boolean {
  return cause instanceof Error && cause.name === 'AbortError';
}
