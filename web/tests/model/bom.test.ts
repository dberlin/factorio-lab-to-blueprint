import { expect, test } from '@rstest/core';
import type { Blueprint, BlueprintBuilding } from '../../src/format';
import { computeBom } from '../../src/model/bom';
import { buildCatalog } from '../../src/model/catalog';

const catalog = buildCatalog({
  items: [
    {
      id: 1001,
      name: 'Iron Ore',
      iconName: 'iron-ore',
      gridIndex: 1,
      modelIndex: 0,
      canBuild: false,
      color: 1,
    },
    {
      id: 1101,
      name: 'Iron Ingot',
      iconName: 'iron-plate',
      gridIndex: 2,
      modelIndex: 0,
      canBuild: false,
      color: 2,
    },
    {
      id: 1201,
      name: 'Gear',
      iconName: 'gear',
      gridIndex: 3,
      modelIndex: 0,
      canBuild: false,
      color: 3,
    },
    {
      id: 2303,
      name: 'Assembler',
      iconName: 'assembler-1',
      gridIndex: 4,
      modelIndex: 65,
      canBuild: true,
      color: 4,
    },
  ],
  models: { '65': { prefab: 'assembler-1', size: [4.2, 4.6, 4.2], center: [0, 2.3, 0] } },
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
      name: 'Gear',
      iconName: 'gear',
      items: [1101],
      itemCounts: [1],
      results: [1201],
      resultCounts: [1],
      timeSpend: 60,
    },
    {
      id: 3,
      name: 'Assembler',
      iconName: 'assembler-1',
      items: [1101, 1201],
      itemCounts: [4, 8],
      results: [2303],
      resultCounts: [1],
      timeSpend: 120,
    },
    {
      id: 9,
      name: 'Gear (alt)',
      iconName: 'gear',
      items: [1101],
      itemCounts: [2],
      results: [1201],
      resultCounts: [3],
      timeSpend: 30,
    },
  ],
});

const bp = (buildings: BlueprintBuilding[]): Blueprint => ({
  header: {
    headerVersion: 1,
    layout: 10,
    icons: [0, 0, 0, 0, 0],
    timestamp: 0n,
    gameVersion: 'x',
    shortDesc: '',
    author: '',
    customVersion: '',
    attributes: [],
    description: '',
  },
  hashValid: true,
  version: 2,
  cursorOffsetX: 0,
  cursorOffsetY: 0,
  cursorTargetArea: 0,
  dragBoxSizeX: 0,
  dragBoxSizeY: 0,
  primaryAreaIdx: 0,
  patch: 1,
  areas: [],
  buildings,
});

const mk = (itemId: number, index: number): BlueprintBuilding => ({
  index,
  areaIndex: 0,
  itemId,
  modelIndex: 65,
  x: 0,
  y: 0,
  z: 0,
  x2: 0,
  y2: 0,
  z2: 0,
  yaw: 0,
  yaw2: 0,
  tilt: 0,
  tilt2: 0,
  pitch: 0,
  pitch2: 0,
  outputObjIdx: -1,
  inputObjIdx: -1,
  outputToSlot: 0,
  inputFromSlot: 0,
  outputFromSlot: 0,
  inputToSlot: 0,
  outputOffset: 0,
  inputOffset: 0,
  recipeId: 0,
  filterId: 0,
  parameters: [],
  content: null,
});

test('counts buildings by type, sorted descending', () => {
  const bom = computeBom(bp([mk(2303, 0), mk(2303, 1), mk(1201, 2)]), catalog);
  expect(bom.buildings[0]).toEqual({ itemId: 2303, name: 'Assembler', count: 2 });
});

test('expands recipes recursively to raw ore', () => {
  const bom = computeBom(bp([mk(2303, 0)]), catalog);
  // 1 assembler = 4 ingot + 8 gear; each gear = 1 ingot => 12 ingot => 12 ore
  expect(bom.rawMaterials).toEqual([{ itemId: 1001, name: 'Iron Ore', count: 12 }]);
});

test('reports which recipe was assumed where alternatives exist', () => {
  const bom = computeBom(bp([mk(2303, 0)]), catalog);
  const gear = bom.assumedRecipes.find((a) => a.itemId === 1201);
  expect(gear).toBeDefined();
  expect(gear?.recipeId).toBe(2); // lowest id wins
  expect(gear?.alternatives).toBe(2);
});

test('a recipe cycle terminates instead of hanging', () => {
  const cyclic = buildCatalog({
    items: [
      { id: 10, name: 'A', iconName: 'a', gridIndex: 1, modelIndex: 0, canBuild: false, color: 1 },
      { id: 11, name: 'B', iconName: 'b', gridIndex: 2, modelIndex: 0, canBuild: false, color: 2 },
    ],
    models: {},
    recipes: [
      {
        id: 1,
        name: 'A',
        iconName: 'a',
        items: [11],
        itemCounts: [1],
        results: [10],
        resultCounts: [1],
        timeSpend: 1,
      },
      {
        id: 2,
        name: 'B',
        iconName: 'b',
        items: [10],
        itemCounts: [1],
        results: [11],
        resultCounts: [1],
        timeSpend: 1,
      },
    ],
  });
  const bom = computeBom(bp([mk(10, 0)]), cyclic);
  expect(bom.rawMaterials.length).toBeGreaterThanOrEqual(0); // terminated
});

test('an item with no recipe is itself raw', () => {
  const bom = computeBom(bp([mk(1001, 0)]), catalog);
  expect(bom.rawMaterials).toEqual([{ itemId: 1001, name: 'Iron Ore', count: 1 }]);
});

test('divides ingredient requirement by a default recipe that yields more than one unit', () => {
  // Bolt's only recipe makes 3 Bolt per craft from 2 Iron Ingot.
  // Iron Ingot's only recipe makes 1 Iron Ingot per craft from 1 Iron Ore.
  // Machine needs 6 Bolt:
  //   6 Bolt / 3 per craft = 2 crafts of the Bolt recipe
  //   2 crafts * 2 Iron Ingot/craft = 4 Iron Ingot
  //   4 Iron Ingot / 1 per craft = 4 crafts of the Iron Ingot recipe
  //   4 crafts * 1 Iron Ore/craft = 4 Iron Ore
  const multiOutput = buildCatalog({
    items: [
      {
        id: 1001,
        name: 'Iron Ore',
        iconName: 'iron-ore',
        gridIndex: 1,
        modelIndex: 0,
        canBuild: false,
        color: 1,
      },
      {
        id: 1101,
        name: 'Iron Ingot',
        iconName: 'iron-plate',
        gridIndex: 2,
        modelIndex: 0,
        canBuild: false,
        color: 2,
      },
      {
        id: 1301,
        name: 'Bolt',
        iconName: 'bolt',
        gridIndex: 3,
        modelIndex: 0,
        canBuild: false,
        color: 3,
      },
      {
        id: 2000,
        name: 'Machine',
        iconName: 'machine',
        gridIndex: 4,
        modelIndex: 0,
        canBuild: true,
        color: 4,
      },
    ],
    models: {},
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
        name: 'Bolt',
        iconName: 'bolt',
        items: [1101],
        itemCounts: [2],
        results: [1301],
        resultCounts: [3],
        timeSpend: 30,
      },
      {
        id: 3,
        name: 'Machine',
        iconName: 'machine',
        items: [1301],
        itemCounts: [6],
        results: [2000],
        resultCounts: [1],
        timeSpend: 90,
      },
    ],
  });
  const bom = computeBom(bp([mk(2000, 0)]), multiOutput);
  expect(bom.rawMaterials).toEqual([{ itemId: 1001, name: 'Iron Ore', count: 4 }]);
});

test('matches the produced item to its own index in results, not index 0', () => {
  // Mirrors real recipe 16 "Plasma Refining": 2 Crude Oil -> 1 Hydrogen + 2 Refined Oil,
  // with Refined Oil at results[1] / resultCounts[1] = 2 per craft.
  // Machine needs 4 Refined Oil:
  //   4 Refined Oil / 2 per craft = 2 crafts of the refining recipe
  //   2 crafts * 2 Crude Oil/craft = 4 Crude Oil
  // (Using resultCounts[0] = 1 instead would wrongly give 4 crafts -> 8 Crude Oil.)
  const multiResult = buildCatalog({
    items: [
      {
        id: 3001,
        name: 'Crude Oil',
        iconName: 'crude-oil',
        gridIndex: 1,
        modelIndex: 0,
        canBuild: false,
        color: 1,
      },
      {
        id: 4001,
        name: 'Hydrogen',
        iconName: 'hydrogen',
        gridIndex: 2,
        modelIndex: 0,
        canBuild: false,
        color: 2,
      },
      {
        id: 4002,
        name: 'Refined Oil',
        iconName: 'refined-oil',
        gridIndex: 3,
        modelIndex: 0,
        canBuild: false,
        color: 3,
      },
      {
        id: 5000,
        name: 'Machine',
        iconName: 'machine',
        gridIndex: 4,
        modelIndex: 0,
        canBuild: true,
        color: 4,
      },
    ],
    models: {},
    recipes: [
      {
        id: 16,
        name: 'Plasma Refining',
        iconName: '',
        items: [3001],
        itemCounts: [2],
        results: [4001, 4002],
        resultCounts: [1, 2],
        timeSpend: 40,
      },
      {
        id: 20,
        name: 'Machine',
        iconName: 'machine',
        items: [4002],
        itemCounts: [4],
        results: [5000],
        resultCounts: [1],
        timeSpend: 90,
      },
    ],
  });
  const bom = computeBom(bp([mk(5000, 0)]), multiResult);
  expect(bom.rawMaterials).toEqual([{ itemId: 3001, name: 'Crude Oil', count: 4 }]);
});
