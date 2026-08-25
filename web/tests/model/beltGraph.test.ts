import { readFileSync } from 'node:fs';
import { expect, test } from '@rstest/core';
import { parseBlueprint } from '../../src/format/index';
import type { Blueprint, BlueprintBuilding } from '../../src/format/types';
import {
  beltSuccessors,
  buildBeltRuns,
  computeBeltHeadings,
  inferCarried,
} from '../../src/model/beltGraph';
import { buildCatalog } from '../../src/model/catalog';

/** Minimal belt record; only the fields the graph reads need to be real. */
function belt(index: number, outputObjIdx: number): BlueprintBuilding {
  return {
    index,
    areaIndex: 0,
    itemId: 2001,
    modelIndex: 35,
    x: index,
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
    outputObjIdx,
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
  };
}

function bp(buildings: BlueprintBuilding[]): Blueprint {
  return { buildings } as unknown as Blueprint;
}

function sorter(
  index: number,
  inputObjIdx: number,
  outputObjIdx: number,
  filterId = 0,
): BlueprintBuilding {
  return { ...belt(index, -1), itemId: 2011, inputObjIdx, outputObjIdx, filterId };
}

function producer(index: number, recipeId: number): BlueprintBuilding {
  return { ...belt(index, -1), itemId: 2303, recipeId };
}

test('a simple chain is one run, free at both ends', () => {
  const runs = buildBeltRuns(bp([belt(0, 1), belt(1, 2), belt(2, -1)]));
  expect(runs.length).toBe(1);
  expect(runs[0]!.belts).toEqual([0, 1, 2]);
  expect(runs[0]!.freeInput).toBe(true);
  expect(runs[0]!.freeOutput).toBe(true);
  expect(runs[0]!.cyclic).toBe(false);
});

test('a merge splits into three runs and the shared tail is its own', () => {
  // 0 -> 2, 1 -> 2, 2 -> -1 : belt 2 has inbound degree 2
  const runs = buildBeltRuns(bp([belt(0, 2), belt(1, 2), belt(2, -1)]));
  expect(runs.length).toBe(3);
  expect(runs.map((r) => r.belts).sort()).toEqual([[0], [1], [2]]);
  // the shared tail is fed by belts, so its input is not free
  expect(runs.find((r) => r.belts[0] === 2)!.freeInput).toBe(false);
  expect(runs.find((r) => r.belts[0] === 2)!.freeOutput).toBe(true);
});

test('merge segmentation does not depend on input order', () => {
  const a = buildBeltRuns(bp([belt(0, 2), belt(1, 2), belt(2, -1)]));
  const b = buildBeltRuns(bp([belt(2, -1), belt(1, 2), belt(0, 2)]));
  const key = (rs: ReturnType<typeof buildBeltRuns>) =>
    JSON.stringify(rs.map((r) => r.belts).sort());
  expect(key(a)).toBe(key(b));
});

test('a closed loop terminates and is marked cyclic', () => {
  const runs = buildBeltRuns(bp([belt(0, 1), belt(1, 2), belt(2, 0)]));
  expect(runs.length).toBe(1);
  expect(runs[0]!.cyclic).toBe(true);
  expect(runs[0]!.belts.length).toBe(3);
  expect(runs[0]!.freeInput).toBe(false);
  expect(runs[0]!.freeOutput).toBe(false);
});

test('a self-loop is its own one-belt cyclic run', () => {
  const runs = buildBeltRuns(bp([belt(0, 0)]));
  expect(runs.length).toBe(1);
  expect(runs[0]!.belts).toEqual([0]);
  expect(runs[0]!.cyclic).toBe(true);
});

test('two disjoint cycles resolve to two separate cyclic runs', () => {
  const runs = buildBeltRuns(bp([belt(0, 1), belt(1, 0), belt(2, 3), belt(3, 2)]));
  expect(runs.length).toBe(2);
  expect(runs.every((r) => r.cyclic)).toBe(true);
  expect(runs.map((r) => r.belts).sort()).toEqual([
    [0, 1],
    [2, 3],
  ]);
});

test('hasExplicitTag is set when any belt in the run carries a filter tag', () => {
  const tagged = { ...belt(0, 1), parameters: [1001] };
  const runs = buildBeltRuns(bp([tagged, belt(1, -1)]));
  expect(runs[0]!.hasExplicitTag).toBe(true);
});

test('a belt feeding a non-belt building is connected, not free', () => {
  const station = { ...belt(9, -1), itemId: 2103 };
  const runs = buildBeltRuns(bp([belt(0, 9), station]));
  const run = runs.find((r) => r.belts.includes(0))!;
  expect(run.freeOutput).toBe(false);
});

test('headings point along the run', () => {
  const buildings = bp([belt(0, 1), belt(1, -1)]);
  const runs = buildBeltRuns(buildings);
  const positions = new Map<number, readonly [number, number, number]>([
    [0, [0, 0, 0]],
    [1, [1, 0, 0]],
  ]);
  const headings = computeBeltHeadings(runs, positions, beltSuccessors(buildings));
  // heading toward +x, measured as atan2(dx, dz)
  expect(headings.get(0)).toBeCloseTo(Math.PI / 2, 5);
  // the tail has no successor at all (free output), so it reuses its
  // predecessor's heading
  expect(headings.get(1)).toBeCloseTo(Math.PI / 2, 5);
});

test('a singleton run feeding a merge still gets a heading', () => {
  // 0 -> 2, 1 -> 2, 2 -> -1 : belt 2 has inbound degree 2, so belt 0 alone
  // (no in-run successor) is a singleton run whose true successor is belt 2.
  const buildings = bp([belt(0, 2), belt(1, 2), belt(2, -1)]);
  const runs = buildBeltRuns(buildings);
  const singleton = runs.find((r) => r.belts.length === 1 && r.belts[0] === 0)!;
  expect(singleton.freeOutput).toBe(false);
  const positions = new Map<number, readonly [number, number, number]>([
    [0, [0, 0, 0]],
    [1, [0, 0, 0]],
    [2, [1, 0, 0]],
  ]);
  const headings = computeBeltHeadings(runs, positions, beltSuccessors(buildings));
  // belt 0's only heading source is its true successor, belt 2, at +x.
  expect(headings.get(0)).toBeCloseTo(Math.PI / 2, 5);
});

test('a run tail feeding a separate cycle points at its real successor', () => {
  // 0 -> 1, 1 -> 2 -> 3 -> 1 : belt 1 has inbound degree 2 (from 0 and 3), so
  // it heads its own run [1, 2, 3]; belt 0 is a singleton run whose tail
  // hands off across the run boundary into that cycle-bearing run's head.
  const buildings = bp([belt(0, 1), belt(1, 2), belt(2, 3), belt(3, 1)]);
  const runs = buildBeltRuns(buildings);
  expect(runs.find((r) => r.belts.includes(1))!.cyclic).toBe(false);
  const positions = new Map<number, readonly [number, number, number]>([
    [0, [0, 0, 0]],
    [1, [1, 0, 0]],
    [2, [1, 0, 0]],
    [3, [1, 0, 0]],
  ]);
  const headings = computeBeltHeadings(runs, positions, beltSuccessors(buildings));
  // belt 0's true successor is belt 1, at +x -- not a fallback to nothing.
  expect(headings.get(0)).toBeCloseTo(Math.PI / 2, 5);
});

test('real fixture: heretical smelter resolves to 11 runs', () => {
  const parsed = parseBlueprint(
    readFileSync('tests/fixtures/factory-heretical-smelter-block.txt', 'utf8'),
  );
  const runs = buildBeltRuns(parsed);
  expect(runs.length).toBe(11);
  expect(Math.max(...runs.map((r) => r.belts.length))).toBe(36);
  expect(runs.reduce((n, r) => n + r.belts.length, 0)).toBe(283);
  expect(runs.some((r) => r.cyclic)).toBe(false);
});

test('real fixture: falk mall has belts in cycles', () => {
  const parsed = parseBlueprint(readFileSync('tests/fixtures/falk-v7-mall-full.txt', 'utf8'));
  const runs = buildBeltRuns(parsed);
  // every belt lands in exactly one run, cycles included
  expect(runs.reduce((n, r) => n + r.belts.length, 0)).toBe(1714);
  expect(runs.filter((r) => r.cyclic).reduce((n, r) => n + r.belts.length, 0)).toBe(280);
});

test('real fixture: 12-s-purple splits at its merge point', () => {
  const parsed = parseBlueprint(
    readFileSync('tests/fixtures/12-s-purple-science-from-smelted-refined-products.txt', 'utf8'),
  );
  const runs = buildBeltRuns(parsed);
  expect(runs.length).toBe(23);
  expect(runs.reduce((n, r) => n + r.belts.length, 0)).toBe(2640);
});

const testCatalog = buildCatalog({
  items: [],
  models: {},
  recipes: [
    {
      id: 1,
      name: 'Iron Ingot',
      iconName: '',
      items: [1001],
      itemCounts: [1],
      results: [1101],
      resultCounts: [1],
      timeSpend: 60,
    },
    {
      id: 53,
      name: 'Two In',
      iconName: '',
      items: [1101, 1104],
      itemCounts: [1, 1],
      results: [1301],
      resultCounts: [1],
      timeSpend: 60,
    },
  ],
});

test('a sorter filter names what the run carries', () => {
  const parsed = bp([belt(0, -1), sorter(1, 0, 5, 1101)]);
  const runs = buildBeltRuns(parsed);
  inferCarried(parsed, runs, testCatalog);
  expect(runs[0]!.carried).toEqual([1101]);
});

test('an unfiltered sorter draining a belt uses the destination recipe inputs', () => {
  // sorter picks up from belt 0, puts into producer 5 running recipe 1 (input 1001)
  const parsed = bp([belt(0, -1), sorter(1, 0, 5), producer(5, 1)]);
  const runs = buildBeltRuns(parsed);
  inferCarried(parsed, runs, testCatalog);
  expect(runs[0]!.carried).toEqual([1001]);
});

test('an unfiltered sorter feeding a belt uses the source recipe results', () => {
  // producer 5 (recipe 1, result 1101) -> sorter -> belt 0
  const parsed = bp([belt(0, -1), sorter(1, 5, 0), producer(5, 1)]);
  const runs = buildBeltRuns(parsed);
  inferCarried(parsed, runs, testCatalog);
  expect(runs[0]!.carried).toEqual([1101]);
});

test('a multi-input recipe contributes every candidate', () => {
  const parsed = bp([belt(0, -1), sorter(1, 0, 5), producer(5, 53)]);
  const runs = buildBeltRuns(parsed);
  inferCarried(parsed, runs, testCatalog);
  expect(runs[0]!.carried).toEqual([1101, 1104]);
});

test('carried items are deduped and sorted across several sorters', () => {
  const parsed = bp([
    belt(0, 1),
    belt(1, -1),
    sorter(2, 0, 9, 1104),
    sorter(3, 1, 9, 1101),
    sorter(4, 0, 9, 1101),
  ]);
  const runs = buildBeltRuns(parsed);
  inferCarried(parsed, runs, testCatalog);
  expect(runs[0]!.carried).toEqual([1101, 1104]);
});

function station(index: number, storage: [number, number][]): BlueprintBuilding {
  // storage entries are [itemId, localLogic]; 1 = Supply, 2 = Demand.
  const p = new Array(2048).fill(0);
  storage.forEach(([itemId, localLogic], s) => {
    p[s * 6] = itemId;
    p[s * 6 + 1] = localLogic;
  });
  return { ...belt(index, -1), itemId: 2104, modelIndex: 50, parameters: p };
}

function depot(index: number, filters: number[]): BlueprintBuilding {
  // A Storage building writes per-slot item filters from word 10 onward.
  // [0] is the ban mask and [1] the storage type, as every real depot has.
  const p = new Array(10 + filters.length).fill(0);
  p[0] = 28;
  p[1] = 9;
  filters.forEach((itemId, i) => {
    p[10 + i] = itemId;
  });
  return { ...belt(index, -1), itemId: 2101, modelIndex: 51, parameters: p };
}

/**
 * A Battlefield Analysis Base in the layout every real one in the fixture
 * corpus uses: storage type 0, so no filters at all and the module block at 10
 * -- workEnergyPerTick, five booleans, dronePriority, then the fighter
 * loadout. None of those are cargo.
 */
function battleBaseNoFilters(index: number): BlueprintBuilding {
  const p = new Array(110).fill(0);
  p[0] = 10;
  p[10] = 200000;
  for (let i = 11; i <= 15; i++) p[i] = 1;
  for (let i = 17; i <= 28; i++) p[i] = 5101;
  return { ...belt(index, -1), itemId: 3009, modelIndex: 453, parameters: p };
}

/** The same building with a storage type set: filters at 10, module at 70. */
function battleBaseWithFilters(index: number, filters: number[]): BlueprintBuilding {
  const p = new Array(110).fill(0);
  p[0] = 10;
  p[1] = 9;
  filters.forEach((itemId, i) => {
    p[10 + i] = itemId;
  });
  p[70] = 200000;
  for (let i = 71; i <= 75; i++) p[i] = 1;
  for (let i = 77; i <= 88; i++) p[i] = 5101;
  return { ...belt(index, -1), itemId: 3009, modelIndex: 453, parameters: p };
}

const stationCatalog = buildCatalog({
  items: [],
  models: {
    '50': { prefab: 'station-2', size: [1, 1, 1], center: [0, 0, 0], buildingType: 'Station' },
    '51': { prefab: 'depot', size: [1, 1, 1], center: [0, 0, 0], buildingType: 'Storage' },
    '453': { prefab: 'bab', size: [1, 1, 1], center: [0, 0, 0], buildingType: 'BattleBase' },
  },
  recipes: [
    {
      id: 1,
      name: 'Iron Ingot',
      iconName: '',
      items: [1001],
      itemCounts: [1],
      results: [1101],
      resultCounts: [1],
      timeSpend: 60,
    },
  ],
});

test('a sorter feeding a belt from a station contributes what the station supplies', () => {
  // station 5 supplies 1101, demands 1104; sorter picks up FROM the station.
  const parsed = bp([
    belt(0, -1),
    sorter(1, 5, 0),
    station(5, [
      [1101, 1],
      [1104, 2],
    ]),
  ]);
  const runs = buildBeltRuns(parsed);
  inferCarried(parsed, runs, stationCatalog);
  expect(runs[0]!.carried).toEqual([1101]);
});

test('a sorter draining a belt into a station contributes what the station demands', () => {
  const parsed = bp([
    belt(0, -1),
    sorter(1, 0, 5),
    station(5, [
      [1101, 1],
      [1104, 2],
    ]),
  ]);
  const runs = buildBeltRuns(parsed);
  inferCarried(parsed, runs, stationCatalog);
  expect(runs[0]!.carried).toEqual([1104]);
});

test('a station slot set to None contributes to neither direction', () => {
  const parsed = bp([belt(0, -1), sorter(1, 5, 0), station(5, [[1101, 0]])]);
  const runs = buildBeltRuns(parsed);
  inferCarried(parsed, runs, stationCatalog);
  expect(runs[0]!.carried).toEqual([]);
});

test('a sorter filter still wins over the station fallback', () => {
  const parsed = bp([belt(0, -1), sorter(1, 5, 0, 1104), station(5, [[1101, 1]])]);
  const runs = buildBeltRuns(parsed);
  inferCarried(parsed, runs, stationCatalog);
  expect(runs[0]!.carried).toEqual([1104]);
});

test('a sorter draining a belt into a depot contributes its filtered items', () => {
  const parsed = bp([belt(0, -1), sorter(1, 0, 5), depot(5, [1143])]);
  const runs = buildBeltRuns(parsed);
  inferCarried(parsed, runs, stationCatalog);
  expect(runs[0]!.carried).toEqual([1143]);
});

test('a sorter feeding a belt from a depot contributes its filtered items', () => {
  // storage filters carry no direction, unlike a station's localLogic: a
  // depot is genuinely both a source and a sink for what it holds.
  const parsed = bp([belt(0, -1), sorter(1, 5, 0), depot(5, [1143])]);
  const runs = buildBeltRuns(parsed);
  inferCarried(parsed, runs, stationCatalog);
  expect(runs[0]!.carried).toEqual([1143]);
});

test('depot filters are deduped across slots', () => {
  const parsed = bp([belt(0, -1), sorter(1, 0, 5), depot(5, [1101, 1101, 1104])]);
  const runs = buildBeltRuns(parsed);
  inferCarried(parsed, runs, stationCatalog);
  expect(runs[0]!.carried).toEqual([1101, 1104]);
});

test('zero-valued (unfiltered) depot slots contribute nothing', () => {
  const parsed = bp([belt(0, -1), sorter(1, 0, 5), depot(5, [0, 0, 0])]);
  const runs = buildBeltRuns(parsed);
  inferCarried(parsed, runs, stationCatalog);
  expect(runs[0]!.carried).toEqual([]);
});

test('a battlefield analysis base with no storage type contributes nothing', () => {
  // Its module block sits where a depot keeps filters. Reading it as filters
  // would put workEnergyPerTick (200000), five booleans and the twelve
  // fighter itemIds of the drone loadout on the belt.
  const parsed = bp([belt(0, -1), sorter(1, 0, 5), battleBaseNoFilters(5)]);
  const runs = buildBeltRuns(parsed);
  inferCarried(parsed, runs, stationCatalog);
  expect(runs[0]!.carried).toEqual([]);
});

test('a battlefield analysis base with a storage type contributes its filters', () => {
  const parsed = bp([belt(0, -1), sorter(1, 0, 5), battleBaseWithFilters(5, [1143, 1143])]);
  const runs = buildBeltRuns(parsed);
  inferCarried(parsed, runs, stationCatalog);
  // 200000 and the 5101 loadout live past word 70 and must stay out.
  expect(runs[0]!.carried).toEqual([1143]);
});
