import {
  type BuildingType,
  type ItemInfo,
  ItemsSchema,
  type ModelBox,
  ModelsSchema,
  type RecipeInfo,
  RecipesSchema,
  type Tags,
  TagsSchema,
} from './schemas';

export type { BuildingType, ItemInfo, ModelBox, RecipeInfo };

export interface Catalog {
  item(id: number): ItemInfo | undefined;
  model(modelIndex: number): ModelBox | undefined;
  recipe(id: number): RecipeInfo | undefined;
  boxForItem(itemId: number): ModelBox | undefined;
  /**
   * The game's BuildingType for a record, which selects its parameter
   * layout. Resolved through modelIndex first, mirroring the game's own
   * `LDB.models.Select(modelIndex).prefabDesc` and this codebase's existing
   * `catalog.model(modelIndex) ?? catalog.boxForItem(itemId)` precedence.
   */
  buildingTypeFor(modelIndex: number, itemId: number): BuildingType | undefined;
  recipesProducing(itemId: number): RecipeInfo[];
  /**
   * Resolves the icon a recipe should render.
   *
   * Mirrors the game's RecipeProto.Preload: a recipe with no iconName of its
   * own draws the icon of its first result item instead (147 of 161 real
   * recipes have an empty iconName and rely on this fallback).
   */
  recipeIconName(recipeId: number): string | undefined;
  allItems(): ItemInfo[];
  /**
   * Resolves the icon for a belt tag id.
   *
   * Mirrors the game's SignalProtoSet.IconSprite, which dispatches across five
   * id ranges. Resolving fewer bands would draw a confidently *wrong* icon (a
   * vein tag read as item 12xxx), which is worse than drawing none, so every
   * band is handled even though only the item band appears in the fixtures.
   * Tech icons are not extracted and resolve to undefined.
   */
  tagIconName(signalId: number): string | undefined;
}

export interface RawAssets {
  items: unknown;
  models: unknown;
  recipes: unknown;
  tags?: unknown;
}

/** Validates the extractor's output and builds lookup indexes. */
export function buildCatalog(raw: RawAssets): Catalog {
  const items = parse(ItemsSchema, raw.items, 'items.json');
  const models = parse(ModelsSchema, raw.models, 'models.json');
  const recipes = parse(RecipesSchema, raw.recipes, 'recipes.json');
  const tags: Tags =
    raw.tags === undefined ? { signals: {}, veins: {} } : parse(TagsSchema, raw.tags, 'tags.json');

  const itemById = new Map(items.map((i) => [i.id, i]));
  const recipeById = new Map(recipes.map((r) => [r.id, r]));

  const producing = new Map<number, RecipeInfo[]>();
  for (const r of recipes) {
    for (const out of r.results) {
      const list = producing.get(out);
      if (list) list.push(r);
      else producing.set(out, [r]);
    }
  }

  const resolveRecipeIcon = (recipeId: number): string | undefined => {
    const r = recipeById.get(recipeId);
    if (!r) return undefined;
    if (r.iconName) return r.iconName;
    const firstResult = r.results[0];
    if (firstResult === undefined) return undefined;
    return itemById.get(firstResult)?.iconName;
  };

  return {
    item: (id) => itemById.get(id),
    model: (idx) => models[String(idx)],
    recipe: (id) => recipeById.get(id),
    boxForItem(itemId) {
      const it = itemById.get(itemId);
      return it ? models[String(it.modelIndex)] : undefined;
    },
    buildingTypeFor(modelIndex, itemId) {
      const byModel = models[String(modelIndex)]?.buildingType;
      if (byModel) return byModel;
      const it = itemById.get(itemId);
      return it ? models[String(it.modelIndex)]?.buildingType : undefined;
    },
    recipesProducing: (itemId) => producing.get(itemId) ?? [],
    recipeIconName: resolveRecipeIcon,
    allItems: () => items,
    tagIconName(signalId) {
      if (signalId <= 0) return undefined;
      if (signalId < 1000) return tags.signals[String(signalId)];
      if (signalId < 12000) return itemById.get(signalId)?.iconName;
      if (signalId < 20000) return tags.veins[String(signalId - 12000)];
      if (signalId < 40000) return resolveRecipeIcon(signalId - 20000);
      return undefined; // techs are not extracted; see the doc comment above
    },
  };
}

function parse<T>(schema: { parse(v: unknown): T }, value: unknown, what: string): T {
  try {
    return schema.parse(value);
  } catch (cause) {
    throw new Error(
      `${what} did not match the expected shape. Re-run "bun run extract-assets"; ` +
        `if that does not help, the game's data layout may have changed. Details: ${String(cause)}`,
    );
  }
}
