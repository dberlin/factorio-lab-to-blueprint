import { z } from 'zod/mini';

const vec3 = z.tuple([z.number(), z.number(), z.number()]);

export const ItemSchema = z.object({
  id: z.number(),
  name: z.string(),
  iconName: z.string(),
  gridIndex: z.number(),
  modelIndex: z.number(),
  canBuild: z.boolean(),
  color: z.number(),
});

/**
 * The building-type vocabulary, in lockstep with the extractor.
 *
 * These twenty strings are produced by `DESC_TO_TYPE` and the PowerDesc
 * derivation in `scripts/extract_assets.py`, and consumed by the decoder
 * table in `params.ts` and the storage branches in `beltGraph.ts`. Nothing
 * else pins the two ends together: an enum here turns a rename or typo into
 * a parse error at load and a compile error at every consumer, instead of a
 * building quietly falling back to the generic "N word(s)" row.
 */
export const BUILDING_TYPES = [
  'ArtificialStar',
  'Assembler',
  'BattleBase',
  'Belt',
  'Dispenser',
  'Ejector',
  'Exchanger',
  'Gamma',
  'Geothermal',
  'Inserter',
  'Lab',
  'Marker',
  'Miner',
  'Monitor',
  'Silo',
  'Splitter',
  'Station',
  'Storage',
  'Tank',
  'Turret',
] as const;

export type BuildingType = (typeof BUILDING_TYPES)[number];

export const ModelBoxSchema = z.object({
  prefab: z.string(),
  size: vec3,
  center: vec3,
  // Present only for models whose prefab carries a *Desc marker (or, for the
  // four power buildings that have none, a distinguishing PowerDesc field);
  // the extractor emits it for 50 of them. Optional because most models are
  // scenery, not buildings.
  buildingType: z.optional(z.enum(BUILDING_TYPES)),
});

export const RecipeSchema = z.object({
  id: z.number(),
  name: z.string(),
  iconName: z.string(),
  items: z.array(z.number()),
  itemCounts: z.array(z.number()),
  results: z.array(z.number()),
  resultCounts: z.array(z.number()),
  timeSpend: z.number(),
});

export const ItemsSchema = z.array(ItemSchema);
export const ModelsSchema = z.record(z.string(), ModelBoxSchema);
export const RecipesSchema = z.array(RecipeSchema);

export const AtlasSchema = z.object({
  cell: z.number(),
  cols: z.number(),
  rows: z.number(),
  entries: z.record(z.string(), z.tuple([z.number(), z.number()])),
});

export const TagsSchema = z.object({
  signals: z.record(z.string(), z.string()),
  veins: z.record(z.string(), z.string()),
});

export type ItemInfo = z.infer<typeof ItemSchema>;
export type ModelBox = z.infer<typeof ModelBoxSchema>;
export type RecipeInfo = z.infer<typeof RecipeSchema>;
export type Atlas = z.infer<typeof AtlasSchema>;
export type Tags = z.infer<typeof TagsSchema>;
