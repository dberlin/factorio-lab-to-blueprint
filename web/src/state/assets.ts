import { buildCatalog, type Catalog } from '../model/catalog';
import { type Atlas, AtlasSchema } from '../model/schemas';

const ASSET_BASE = '/assets';

export function assetPath(relative: string): string {
  return `${ASSET_BASE}/${relative}`;
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
