import { readFileSync } from 'node:fs';
import { expect, test } from '@rstest/core';
import { parseBlueprint } from '../../src/format/index';
import { arrowIsDark, runColor, type Vec3 } from '../../src/model/beltRibbons';
import type { BeltRun } from '../../src/model/beltGraph';
import type { BuildingInstance, SceneModel } from '../../src/model/layout';
import { buildSceneModel } from '../../src/model/layout';
import {
  beltNearest,
  buildRibbonScene,
  digitPlacements,
  shouldFlip,
} from '../../src/scene/BeltRibbons';
import { realCatalog } from '../support/catalog';

function belt(index: number, at: Vec3): BuildingInstance {
  return {
    index,
    itemId: 2001,
    modelIndex: 35,
    position: at,
    size: [0.64, 0.12, 0.64],
    yawRad: 0,
    color: 0x999999,
    recipeId: 0,
    filterId: 0,
    parameters: [],
  };
}

function run(belts: number[], extra: Partial<BeltRun> = {}): BeltRun {
  return {
    belts,
    freeInput: true,
    freeOutput: true,
    cyclic: false,
    carried: [],
    carriedFrom: 'none',
    hasExplicitTag: false,
    ...extra,
  };
}

function model(instances: BuildingInstance[], runs: BeltRun[], headings: [number, number][] = []) {
  return {
    instances,
    beltRuns: runs,
    beltHeadings: new Map(headings),
    unknownItemIds: [],
    unresolvedTagIds: [],
  } as unknown as SceneModel;
}

const straight = (n: number): BuildingInstance[] =>
  Array.from({ length: n }, (_, i) => belt(i, [0, 0.1, i]));

test('a run becomes one strip, with at least one arrow and its own number', () => {
  const scene = buildRibbonScene(model(straight(12), [run([...Array(12).keys()])]));
  expect(scene.positions.length).toBeGreaterThan(0);
  expect(scene.positions.length).toBe(scene.normals.length);
  expect(scene.colors.length).toBe(scene.positions.length);
  expect(scene.arrows.length).toBeGreaterThan(0);
  expect(scene.labels.length).toBeGreaterThan(0);
  // Run 0 is a single digit.
  expect(scene.labels[0]?.digits).toEqual([0]);
  // Arrows point the way cargo travels, which here is +Z.
  expect(scene.arrows[0]?.dir[2]).toBeCloseTo(1, 6);
});

test('a run numbered in the hundreds carries three digits', () => {
  // 137 stub runs, then a long one that is therefore run 137.
  const instances = Array.from({ length: 137 }, (_, i) => belt(i, [i * 3, 0.1, 0]));
  const runs = Array.from({ length: 137 }, (_, i) => run([i]));
  const headings: [number, number][] = instances.map((_, i) => [i, Math.PI / 2]);
  const long = Array.from({ length: 20 }, (_, i) => belt(1000 + i, [500, 0.1, i]));
  instances.push(...long);
  runs.push(run(long.map((b) => b.index)));

  const scene = buildRibbonScene(model(instances, runs, headings));
  const three = scene.labels.filter((l) => l.digits.length === 3);
  expect(three.length).toBeGreaterThan(0);
  expect(three[0]?.digits).toEqual([1, 3, 7]);
  // A stub too short for a whole block gets a bare arrow and no number, which
  // is why the stubs above contribute arrows but no labels.
  expect(scene.arrows.length).toBeGreaterThan(scene.labels.length);
});

test('a one-belt run is still drawn, using its heading for direction', () => {
  const withHeading = buildRibbonScene(model([belt(0, [0, 0.1, 0])], [run([0])], [[0, 0]]));
  expect(withHeading.positions.length).toBeGreaterThan(0);
  // No heading at all means no direction to draw it along, and nothing is drawn.
  const without = buildRibbonScene(model([belt(0, [0, 0.1, 0])], [run([0])]));
  expect(without.positions.length).toBe(0);
});

test('the strip reaches past the first and last tile centres', () => {
  const scene = buildRibbonScene(model(straight(4), [run([0, 1, 2, 3])]));
  let minZ = Infinity;
  let maxZ = -Infinity;
  for (let i = 0; i < scene.positions.length; i += 3) {
    minZ = Math.min(minZ, scene.positions[i + 2] as number);
    maxZ = Math.max(maxZ, scene.positions[i + 2] as number);
  }
  // Tiles span z 0..3; the strip must overhang both ends so a run that feeds
  // another arrives flush at it instead of stopping half a tile short.
  expect(minZ).toBeLessThan(-0.1);
  expect(maxZ).toBeGreaterThan(3.1);
});

test('arrow contrast is decided per run from that run colour', () => {
  const scene = buildRibbonScene(
    model(straight(40), [
      run([...Array(20).keys()]),
      run([...Array(20).keys()].map((i) => i + 20)),
    ]),
  );
  for (const arrow of scene.arrows) expect(typeof arrow.dark).toBe('boolean');
  expect(scene.labels[0]?.dark).toBe(arrowIsDark(runColor(0)));
});

test('every belt of every run can be found from a click', () => {
  const scene = buildRibbonScene(model(straight(6), [run([0, 1, 2]), run([3, 4, 5])]));
  expect(scene.belts.length).toBe(6);
  expect(beltNearest({ x: 0, y: 0.1, z: 4.1 }, scene.belts)).toBe(4);
  expect(beltNearest({ x: 0, y: 0, z: -9 }, scene.belts)).toBe(0);
  expect(beltNearest({ x: 0, y: 0, z: 0 }, [])).toBeNull();
});

// -------------------------------------------------------------- readability

test('a label flips only when it would otherwise read backwards', () => {
  const east: Vec3 = [1, 0, 0];
  expect(shouldFlip(east, { x: 1, z: 0 })).toBe(false);
  expect(shouldFlip(east, { x: -1, z: 0 })).toBe(true);
});

test('flipping keeps the digits in reading order, not merely un-mirrored', () => {
  const label = { at: [0, 0, 0] as Vec3, dir: [0, 0, 1] as Vec3, digits: [1, 3, 7], dark: false };
  const plain = digitPlacements(label, false);
  const flipped = digitPlacements(label, true);
  expect(plain.map((p) => p.digit)).toEqual([1, 3, 7]);
  // Unflipped, "1" is the furthest back along travel; flipped, it is furthest
  // forward -- so on screen the number still reads 137 left to right.
  expect((plain[0] as { at: Vec3 }).at[2]).toBeLessThan((plain[2] as { at: Vec3 }).at[2]);
  expect((flipped[0] as { at: Vec3 }).at[2]).toBeGreaterThan((flipped[2] as { at: Vec3 }).at[2]);
});

test('digits of a label sit inside the width of their own strip', () => {
  const label = { at: [0, 0, 0] as Vec3, dir: [0, 0, 1] as Vec3, digits: [4, 2], dark: false };
  for (const p of digitPlacements(label, false)) {
    // Travel is +Z, so any spread across the strip would appear in x.
    expect(Math.abs(p.at[0])).toBeLessThan(1e-9);
  }
});

// --------------------------------------------------------------- real data

test('a real blueprint draws every one of its runs', () => {
  const bp = parseBlueprint(
    readFileSync('tests/fixtures/factory-heretical-smelter-block.txt', 'utf8').trim(),
  );
  const sceneModel = buildSceneModel(bp, realCatalog);
  const scene = buildRibbonScene(sceneModel);
  expect(sceneModel.beltRuns.length).toBeGreaterThan(5);
  expect(scene.belts.length).toBe(sceneModel.instances.filter((i) => i.itemId === 2003).length);
  // Every run gets at least one arrow: a strip with no direction on it is
  // exactly the thing this replaces.
  expect(scene.arrows.length).toBeGreaterThanOrEqual(sceneModel.beltRuns.length);
  expect(Number.isFinite(scene.positions[0] as number)).toBe(true);
});

test('arrows point along travel on a straight run, through an L-turn and past a climb', () => {
  // Straight, then a right turn, then a level change, then straight again --
  // the three shapes the brief calls out. Direction comes from run order, so
  // every arrow must agree with the leg it sits on.
  const path: BuildingInstance[] = [];
  let index = 0;
  for (let z = 0; z < 14; z++) path.push(belt(index++, [0, 0.1, z]));
  for (let x = 1; x < 14; x++) path.push(belt(index++, [x, 0.1, 13]));
  path.push(belt(index++, [14, 0.6, 13]));
  for (let x = 15; x < 28; x++) path.push(belt(index++, [x, 0.6, 13]));

  const scene = buildRibbonScene(model(path, [run(path.map((b) => b.index))]));
  expect(scene.arrows.length).toBeGreaterThan(2);
  for (const arrow of scene.arrows) {
    const onFirstLeg = arrow.at[0] < 0.5;
    if (onFirstLeg) {
      expect(arrow.dir[2]).toBeCloseTo(1, 6); // travelling +Z
      expect(arrow.dir[0]).toBeCloseTo(0, 6);
    } else {
      expect(arrow.dir[0]).toBeCloseTo(1, 6); // travelling +X, before and after the climb
      expect(arrow.dir[2]).toBeCloseTo(0, 6);
    }
  }
  // Something is drawn beyond the level change, so the climb does not end the run.
  expect(scene.arrows.some((a) => a.at[0] > 14)).toBe(true);
});
