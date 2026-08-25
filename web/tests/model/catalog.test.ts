import { expect, test } from '@rstest/core';
import { buildCatalog } from '../../src/model/catalog';

const RAW = {
  items: [
    {
      id: 2001,
      name: 'Conveyor Belt Mk.I',
      iconName: 'belt-1',
      gridIndex: 1101,
      modelIndex: 35,
      canBuild: true,
      color: 0xe3a263,
    },
    {
      id: 2303,
      name: 'Assembling Machine Mk.I',
      iconName: 'assembler-1',
      gridIndex: 1201,
      modelIndex: 65,
      canBuild: true,
      color: 0xedab5c,
    },
    {
      id: 1101,
      name: 'Iron Ingot',
      iconName: 'iron-plate',
      gridIndex: 1,
      modelIndex: 0,
      canBuild: false,
      color: 0x999999,
    },
  ],
  models: {
    '35': { prefab: 'belt-1', size: [1, 0.5, 1], center: [0, 0.1, 0] },
    '65': { prefab: 'assembler-1', size: [4.2, 4.6, 4.2], center: [0, 2.3, 0] },
  },
  recipes: [
    {
      id: 1,
      name: 'Iron Ingot',
      iconName: 'iron-plate',
      items: [1001],
      itemCounts: [1],
      results: [1101],
      resultCounts: [1],
      timeSpend: 60,
    },
    {
      id: 2,
      name: 'Iron Ingot (no icon)',
      iconName: '',
      items: [1001],
      itemCounts: [1],
      results: [1101],
      resultCounts: [1],
      timeSpend: 60,
    },
    {
      id: 3,
      name: 'Nothing produced',
      iconName: '',
      items: [1001],
      itemCounts: [1],
      results: [],
      resultCounts: [],
      timeSpend: 60,
    },
  ],
};

test('looks up items, models and recipes', () => {
  const c = buildCatalog(RAW);
  expect(c.item(2001)?.name).toBe('Conveyor Belt Mk.I');
  expect(c.model(65)?.size).toEqual([4.2, 4.6, 4.2]);
  expect(c.recipe(1)?.timeSpend).toBe(60);
  expect(c.item(9999)).toBeUndefined();
});

test('resolves a box via itemId -> modelIndex', () => {
  const c = buildCatalog(RAW);
  expect(c.boxForItem(2303)?.size).toEqual([4.2, 4.6, 4.2]);
  expect(c.boxForItem(1101)).toBeUndefined();
});

test('indexes recipes by what they produce', () => {
  const c = buildCatalog(RAW);
  expect(c.recipesProducing(1101).map((r) => r.id)).toEqual([1, 2]);
  expect(c.recipesProducing(1001)).toEqual([]);
});

test('rejects malformed asset JSON with a path-specific message', () => {
  const bad = { ...RAW, models: { '35': { prefab: 'belt-1', size: [1, 0.5], center: [0, 0, 0] } } };
  expect(() => buildCatalog(bad)).toThrow(/models/);
});

test('rejects an item missing a required field', () => {
  const bad = { ...RAW, items: [{ id: 2001, name: 'x' }] };
  expect(() => buildCatalog(bad)).toThrow();
});

test('recipeIconName uses the recipe icon when it has one', () => {
  const c = buildCatalog(RAW);
  expect(c.recipeIconName(1)).toBe('iron-plate');
});

test('recipeIconName falls back to the first result item icon when the recipe icon is empty', () => {
  const c = buildCatalog(RAW);
  expect(c.recipeIconName(2)).toBe('iron-plate');
});

test('recipeIconName returns undefined when the recipe has no icon and no results', () => {
  const c = buildCatalog(RAW);
  expect(c.recipeIconName(3)).toBeUndefined();
});

test('recipeIconName returns undefined for an unknown recipe id', () => {
  const c = buildCatalog(RAW);
  expect(c.recipeIconName(9999)).toBeUndefined();
});

test('tagIconName resolves each signal id band', () => {
  const c = buildCatalog({
    items: [
      {
        id: 1101,
        name: 'Iron Ingot',
        iconName: 'iron-plate',
        gridIndex: 1,
        modelIndex: 0,
        canBuild: false,
        color: 1,
      },
    ],
    models: {},
    recipes: [
      {
        id: 16,
        name: 'Gear',
        iconName: 'gear-recipe',
        items: [1101],
        itemCounts: [1],
        results: [1201],
        resultCounts: [1],
        timeSpend: 60,
      },
    ],
    tags: { signals: { '401': 'signal-401' }, veins: { '2': 'coal-vein' } },
  });

  expect(c.tagIconName(401)).toBe('signal-401'); // signal band
  expect(c.tagIconName(1101)).toBe('iron-plate'); // item band, id used directly
  expect(c.tagIconName(12002)).toBe('coal-vein'); // vein band, id - 12000
  expect(c.tagIconName(20016)).toBe('gear-recipe'); // recipe band, id - 20000
  expect(c.tagIconName(40001)).toBeUndefined(); // tech band, not extracted
  expect(c.tagIconName(60000)).toBeUndefined(); // out of range
  expect(c.tagIconName(0)).toBeUndefined(); // unset
});

test('tagIconName resolves the exact boundary of each band transition', () => {
  // The mid-band test above (401, 1101, 12002, 20016, 40001) would not catch
  // a `<` silently becoming `<=`, or an off-by-one in a subtraction offset --
  // a mis-banded id draws a confidently wrong icon rather than none, so this
  // pins every transition exactly.
  const c = buildCatalog({
    items: [
      // Item band lower and upper bound: id used directly, band is [1000, 12000).
      {
        id: 1000,
        name: 'Item at lower bound',
        iconName: 'item-1000',
        gridIndex: 1,
        modelIndex: 0,
        canBuild: false,
        color: 1,
      },
      {
        id: 11999,
        name: 'Item at upper bound',
        iconName: 'item-11999',
        gridIndex: 2,
        modelIndex: 0,
        canBuild: false,
        color: 1,
      },
    ],
    models: {},
    recipes: [
      // Recipe band: signalId - 20000. Lower bound 20000 -> recipe 0;
      // upper bound 39999 -> recipe 19999.
      {
        id: 0,
        name: 'Recipe at lower bound',
        iconName: 'recipe-0',
        items: [],
        itemCounts: [],
        results: [],
        resultCounts: [],
        timeSpend: 60,
      },
      {
        id: 19999,
        name: 'Recipe at upper bound',
        iconName: 'recipe-19999',
        items: [],
        itemCounts: [],
        results: [],
        resultCounts: [],
        timeSpend: 60,
      },
    ],
    tags: {
      // Signal band: id < 1000, used directly.
      signals: { '999': 'signal-999' },
      // Vein band: signalId - 12000. Lower bound 12000 -> vein 0;
      // upper bound 19999 -> vein 7999.
      veins: { '0': 'vein-0', '7999': 'vein-7999' },
    },
  });

  // signal band upper edge: 999 is still < 1000.
  expect(c.tagIconName(999)).toBe('signal-999');
  // item band lower edge: 1000 is the first id no longer treated as a signal.
  expect(c.tagIconName(1000)).toBe('item-1000');
  // item band upper edge: 11999 is still < 12000.
  expect(c.tagIconName(11999)).toBe('item-11999');
  // vein band lower edge: 12000 - 12000 = 0.
  expect(c.tagIconName(12000)).toBe('vein-0');
  // vein band upper edge: 19999 - 12000 = 7999, still < 20000.
  expect(c.tagIconName(19999)).toBe('vein-7999');
  // recipe band lower edge: 20000 - 20000 = 0.
  expect(c.tagIconName(20000)).toBe('recipe-0');
  // recipe band upper edge: 39999 - 20000 = 19999, still < 40000.
  expect(c.tagIconName(39999)).toBe('recipe-19999');
  // tech band: 40000 is the first id past the recipe band. Resolves to
  // undefined because techs are deliberately not extracted, not because the
  // fixture is missing an entry -- there is no tech lookup table at all.
  expect(c.tagIconName(40000)).toBeUndefined();
  // tech band upper edge: 59999 is still < 60000, same "not extracted" reason.
  expect(c.tagIconName(59999)).toBeUndefined();
  // 60000 and above: out of range entirely, past even the tech band.
  expect(c.tagIconName(60000)).toBeUndefined();
});

test('buildingTypeFor resolves by modelIndex, falling back to the item default', () => {
  const c = buildCatalog({
    items: [
      {
        id: 2104,
        name: 'Interstellar Logistics Station',
        iconName: 'station',
        gridIndex: 1,
        modelIndex: 50,
        canBuild: true,
        color: 1,
      },
    ],
    models: {
      '50': { prefab: 'station-2', size: [1, 1, 1], center: [0, 0, 0], buildingType: 'Station' },
      '38': { prefab: 'splitter', size: [1, 1, 1], center: [0, 0, 0], buildingType: 'Splitter' },
      '99': { prefab: 'untyped', size: [1, 1, 1], center: [0, 0, 0] },
    },
    recipes: [],
  });

  // The record's own modelIndex wins, matching buildSceneModel's box lookup.
  expect(c.buildingTypeFor(38, 2104)).toBe('Splitter');
  // Falls back to the item's default model when the record's model is unknown.
  expect(c.buildingTypeFor(4242, 2104)).toBe('Station');
  // A model with a box but no type resolves to undefined, not a guess.
  expect(c.buildingTypeFor(99, 9999)).toBeUndefined();
  expect(c.buildingTypeFor(4242, 9999)).toBeUndefined();
});

test('tagIconName honours the recipe icon fallback', () => {
  const c = buildCatalog({
    items: [
      {
        id: 1201,
        name: 'Gear',
        iconName: 'gear',
        gridIndex: 1,
        modelIndex: 0,
        canBuild: false,
        color: 1,
      },
    ],
    models: {},
    // empty iconName: must fall back to the first result's icon
    recipes: [
      {
        id: 16,
        name: 'Gear',
        iconName: '',
        items: [],
        itemCounts: [],
        results: [1201],
        resultCounts: [1],
        timeSpend: 60,
      },
    ],
    tags: { signals: {}, veins: {} },
  });
  expect(c.tagIconName(20016)).toBe('gear');
});
