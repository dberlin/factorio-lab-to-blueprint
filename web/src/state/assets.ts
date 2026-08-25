import { buildCatalog, type Catalog } from '../model/catalog';
import { type Atlas, AtlasSchema } from '../model/schemas';

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
    json('/assets/items.json', signal),
    json('/assets/models.json', signal),
    json('/assets/recipes.json', signal),
    json('/assets/tags.json', signal),
  ]);
  return buildCatalog({ items, models, recipes, tags });
}

export async function loadAtlas(signal?: AbortSignal): Promise<Atlas> {
  return AtlasSchema.parse(await json('/assets/icons/atlas.json', signal));
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
