import { readFileSync } from 'node:fs';
import { expect, test } from '@rstest/core';
import { parseBlueprint } from '../../src/format/index';
import type { Blueprint, BlueprintBuilding } from '../../src/format/types';
import {
  beltSuccessors,
  buildBeltRuns,
  computeBeltHeadings,
  inferCarried,
  isBelt,
  runIndexForBelt,
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

/**
 * Task 6 (coater-placed plan): the `placed` arm's coater node is a
 * free-standing four-tile belt run n0->n1->n2->n3, with the Spray Coater
 * addon (item 2313) riding n2 -- the third tile -- at the SAME (x, y, z) as
 * that belt (`seat_x = ox + 1 + half_span` in
 * `src/flab2bp/layout/freeform.py`'s `_coater_node_site_is_clear`, half_span
 * 1 for the coater's 3-tile footprint). n0 is the in-port every producer net
 * and merge sinks into, so its LOCAL inbound count can be 1 (single
 * producer) or >= 2 (a genuine many-to-one merge) -- `buildBeltRuns`
 * segments by exactly that count, starting a new run at any belt whose
 * inbound is not exactly 1.
 *
 * Finds n0..n3 for a coater by walking the blueprint's own belt link graph
 * (not by geometry alone), and reports which `buildBeltRuns` run each tile
 * landed in. Measured on two saved evidence blueprints
 * (`docs/superpowers/evidence/2026-09-07-coater-placed-gate/web/`,
 * `placed` arm, `FLAB2BP_COATER_NODE` unset): 39 coaters total, one of which
 * (`magnetic-coil`/`all-products` reported-URL fixture, coater at (5,7,0))
 * has n0 inbound == 2, a real merge. In every one of the 39, n0..n3 landed
 * in exactly one run -- `buildBeltRuns` stopping "before" a merge point
 * only cuts what comes BEFORE n0, never inside the node itself, because n1,
 * n2 and n3 always have inbound exactly 1 by construction (a straight
 * belt-to-belt chain). See task-6-report.md for the full measurement.
 */
function coaterNodeTiles(
  bp: Blueprint,
): { coaterIndex: number; n0: number; n1: number; n2: number; n3: number }[] {
  const next = beltSuccessors(bp);
  const byPos = new Map<string, BlueprintBuilding>();
  for (const b of bp.buildings) if (isBelt(b.itemId)) byPos.set(`${b.x},${b.y},${b.z}`, b);
  const prevOf = (index: number): BlueprintBuilding | undefined =>
    bp.buildings.find((b) => isBelt(b.itemId) && next.get(b.index) === index);

  const nodes: { coaterIndex: number; n0: number; n1: number; n2: number; n3: number }[] = [];
  for (const c of bp.buildings) {
    if (c.itemId !== 2313) continue; // Spray Coater
    const n2 = byPos.get(`${c.x},${c.y},${c.z}`);
    if (!n2) continue;
    const n1 = prevOf(n2.index);
    const n0 = n1 ? prevOf(n1.index) : undefined;
    const n3Idx = next.get(n2.index);
    if (n1 === undefined || n0 === undefined || n3Idx === undefined) continue;
    nodes.push({ coaterIndex: c.index, n0: n0.index, n1: n1.index, n2: n2.index, n3: n3Idx });
  }
  return nodes;
}

test('coater node: n0..n3 land in exactly one run, merge or not (magnetic-coil, no merges)', () => {
  const parsed = parseBlueprint(readFileSync('tests/fixtures/coater-node-magcoil.txt', 'utf8'));
  const runs = buildBeltRuns(parsed);
  const inbound = new Map<number, number>();
  for (const target of beltSuccessors(parsed).values())
    inbound.set(target, (inbound.get(target) ?? 0) + 1);
  const nodes = coaterNodeTiles(parsed);

  expect(nodes.length).toBe(4); // this fixture has 4 coaters, per the evidence log
  for (const n of nodes) {
    expect(inbound.get(n.n0) ?? 0).toBe(1); // this fixture has no merges under any coater
    const runOf = (i: number) => runIndexForBelt(i, runs);
    const r0 = runOf(n.n0);
    expect(r0).not.toBeNull();
    expect(runOf(n.n1)).toBe(r0);
    expect(runOf(n.n2)).toBe(r0);
    expect(runOf(n.n3)).toBe(r0);
  }
});

test('coater node: a genuine merge at n0 still keeps n0..n3 in one run, and freeInput stays false', () => {
  const parsed = parseBlueprint(
    readFileSync('tests/fixtures/coater-node-reported-all-products.txt', 'utf8'),
  );
  const runs = buildBeltRuns(parsed);
  const inbound = new Map<number, number>();
  for (const target of beltSuccessors(parsed).values())
    inbound.set(target, (inbound.get(target) ?? 0) + 1);
  const nodes = coaterNodeTiles(parsed);

  expect(nodes.length).toBe(35); // this fixture has 35 coaters, per the evidence log

  const merged = nodes.filter((n) => (inbound.get(n.n0) ?? 0) >= 2);
  // At least one coater in this fixture rides a genuine many-to-one merge at
  // n0 -- the case the run-segmentation rule is meant to be tested against.
  expect(merged.length).toBeGreaterThan(0);

  for (const n of nodes) {
    const runOf = (i: number) => runIndexForBelt(i, runs);
    const r0 = runOf(n.n0);
    expect(r0).not.toBeNull();
    // n0..n3 are always one run, whether n0's own inbound is 1 (n0 continues
    // the upstream producer's run) or >= 2 (n0 starts its own run, which
    // still carries n1, n2, n3 forward with it -- a merge only ever cuts
    // what comes BEFORE n0).
    expect(runOf(n.n1)).toBe(r0);
    expect(runOf(n.n2)).toBe(r0);
    expect(runOf(n.n3)).toBe(r0);
    // freeInput requires inbound(head) === 0; n0's inbound is always >= 1 by
    // construction (something always feeds the node), so the run's own head
    // (n0 itself, when n0 starts the run) is never flagged as a free input
    // -- the endpoint-icon flood the brief's failure mode describes does not
    // arise structurally for this node.
    const run = runs[r0 as number];
    if (run?.belts[0] === n.n0) expect(run.freeInput).toBe(false);
  }
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
    // Takes 1104 only: a consumer that shares no item with recipe 1's output,
    // which is how the "the two sides contradict each other" case is built.
    {
      id: 54,
      name: 'Copper Only',
      iconName: '',
      items: [1104],
      itemCounts: [1],
      results: [1302],
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

// ---------------------------------------------------------------------------
// Sorter-fed heads, and the two-sided inference that pins a single item.
// ---------------------------------------------------------------------------

test('a head a sorter drops onto is not a free input', () => {
  // producer 5 -> sorter 1 -> belt 0 -> belt 2. Nothing else feeds belt 0, so
  // the belt-to-belt inbound count is 0, but the run is plainly fed.
  const parsed = bp([belt(0, 2), belt(2, -1), sorter(1, 5, 0), producer(5, 1)]);
  const run = buildBeltRuns(parsed).find((r) => r.belts[0] === 0);
  expect(run!.freeInput).toBe(false);
});

test('a head only DRAINED by a sorter is still a free input', () => {
  // The sorter takes off belt 0 and delivers into producer 5; nothing puts
  // anything on the head, so it is genuinely open.
  const parsed = bp([belt(0, -1), sorter(1, 0, 5), producer(5, 1)]);
  expect(buildBeltRuns(parsed)[0]!.freeInput).toBe(true);
});

test('a head nothing touches at all is a free input', () => {
  const parsed = bp([belt(0, 1), belt(1, -1)]);
  expect(buildBeltRuns(parsed)[0]!.freeInput).toBe(true);
});

test('a run fed and drained carries the intersection: one item, not five', () => {
  // producer 5 (recipe 1) puts its only result 1101 on the belt; the belt
  // feeds producer 6, whose recipe 53 takes 1101 AND 1104. Only 1101 can be
  // on this lane -- the union [1101, 1104] would invent the other.
  const parsed = bp([
    belt(0, -1),
    sorter(1, 5, 0),
    producer(5, 1),
    sorter(2, 0, 6),
    producer(6, 53),
  ]);
  const runs = buildBeltRuns(parsed);
  inferCarried(parsed, runs, testCatalog);
  expect(runs[0]!.carried).toEqual([1101]);
  expect(runs[0]!.carriedFrom).toBe('intersection');
});

test('one-sided inference falls back to the union and says so', () => {
  const parsed = bp([belt(0, -1), sorter(1, 0, 5), producer(5, 53)]);
  const runs = buildBeltRuns(parsed);
  inferCarried(parsed, runs, testCatalog);
  expect(runs[0]!.carried).toEqual([1101, 1104]);
  expect(runs[0]!.carriedFrom).toBe('union');
});

test('two sides that share nothing fall back to the union rather than to nothing', () => {
  // Fed with 1101, drained into a recipe that wants only 1104: the graph
  // contradicts itself (a mis-set recipe, or a lane we cannot model). Showing
  // both candidates is honest; showing none would hide the lane entirely.
  const parsed = bp([
    belt(0, -1),
    sorter(1, 5, 0),
    producer(5, 1),
    sorter(2, 0, 6),
    producer(6, 54),
  ]);
  const runs = buildBeltRuns(parsed);
  inferCarried(parsed, runs, testCatalog);
  expect(runs[0]!.carried).toEqual([1101, 1104]);
  expect(runs[0]!.carriedFrom).toBe('union');
});

test('a run no sorter touches records that nothing was inferred', () => {
  const parsed = bp([belt(0, -1)]);
  const runs = buildBeltRuns(parsed);
  inferCarried(parsed, runs, testCatalog);
  expect(runs[0]!.carried).toEqual([]);
  expect(runs[0]!.carriedFrom).toBe('none');
});

test('an explicit sorter filter still wins on both sides', () => {
  // Feeder filtered to 1104, drain into a recipe that takes 1101 and 1104:
  // the filter is authoritative, so the intersection is the filtered item.
  const parsed = bp([
    belt(0, -1),
    sorter(1, 5, 0, 1104),
    producer(5, 1),
    sorter(2, 0, 6),
    producer(6, 53),
  ]);
  const runs = buildBeltRuns(parsed);
  inferCarried(parsed, runs, testCatalog);
  expect(runs[0]!.carried).toEqual([1104]);
  expect(runs[0]!.carriedFrom).toBe('intersection');
});
