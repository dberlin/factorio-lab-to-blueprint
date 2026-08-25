import type { Blueprint } from '../format';
import type { Catalog } from './catalog';

export interface BomEntry {
  itemId: number;
  name: string;
  count: number;
}

export interface AssumedRecipe {
  itemId: number;
  recipeId: number;
  alternatives: number;
}

export interface Bom {
  buildings: BomEntry[];
  rawMaterials: BomEntry[];
  assumedRecipes: AssumedRecipe[];
}

export function computeBom(bp: Blueprint, catalog: Catalog): Bom {
  const counts = new Map<number, number>();
  for (const b of bp.buildings) counts.set(b.itemId, (counts.get(b.itemId) ?? 0) + 1);

  const buildings: BomEntry[] = [...counts]
    .map(([itemId, count]) => ({
      itemId,
      name: catalog.item(itemId)?.name ?? `Item ${itemId}`,
      count,
    }))
    .sort((a, b) => b.count - a.count || a.itemId - b.itemId);

  const raw = new Map<number, number>();
  const assumed = new Map<number, AssumedRecipe>();

  // `expanding` is the current DFS path, so a recipe cycle is treated as raw
  // instead of recursing forever.
  const expanding = new Set<number>();

  const expand = (itemId: number, qty: number): void => {
    const recipes = catalog.recipesProducing(itemId);
    if (recipes.length === 0 || expanding.has(itemId)) {
      raw.set(itemId, (raw.get(itemId) ?? 0) + qty);
      return;
    }

    // Default recipe = lowest id. Several items have alternatives; the panel
    // surfaces this assumption rather than implying a single true answer.
    const chosen = recipes.reduce((a, b) => (a.id <= b.id ? a : b));
    if (recipes.length > 1 && !assumed.has(itemId)) {
      assumed.set(itemId, { itemId, recipeId: chosen.id, alternatives: recipes.length });
    }

    const outIdx = chosen.results.indexOf(itemId);
    const perCraft = chosen.resultCounts[outIdx] ?? 1;
    const crafts = qty / (perCraft || 1);

    expanding.add(itemId);
    chosen.items.forEach((ingredient, i) => {
      expand(ingredient, (chosen.itemCounts[i] ?? 0) * crafts);
    });
    expanding.delete(itemId);
  };

  for (const [itemId, count] of counts) expand(itemId, count);

  const rawMaterials: BomEntry[] = [...raw]
    .map(([itemId, count]) => ({
      itemId,
      name: catalog.item(itemId)?.name ?? `Item ${itemId}`,
      count: Math.round(count * 100) / 100,
    }))
    .sort((a, b) => b.count - a.count || a.itemId - b.itemId);

  return { buildings, rawMaterials, assumedRecipes: [...assumed.values()] };
}
