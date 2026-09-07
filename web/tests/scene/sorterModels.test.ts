import { readFileSync } from 'node:fs';
import { expect, test } from '@rstest/core';
import { parseBlueprint } from '../../src/format/index';
import { isSorter } from '../../src/model/beltGraph';
import { RIBBON_THICKNESS, type Vec3 } from '../../src/model/beltRibbons';
import type { BeltRun } from '../../src/model/beltGraph';
import type { BuildingInstance, SceneModel, SorterLink } from '../../src/model/layout';
import { buildSceneModel } from '../../src/model/layout';
import { SORTER } from '../../src/model/sorterModel';
import { buildSorterScene, sorterNearest } from '../../src/scene/SorterModels';
import { realCatalog } from '../support/catalog';

function instance(index: number, itemId: number, at: Vec3, size: Vec3): BuildingInstance {
  return {
    index,
    itemId,
    modelIndex: 1,
    position: at,
    size,
    yawRad: 0,
    color: 0x999999,
    recipeId: 0,
    filterId: 0,
    parameters: [],
  };
}

function model(
  instances: BuildingInstance[],
  sorters: SorterLink[],
  runs: BeltRun[] = [],
): SceneModel {
  return {
    instances,
    sorters,
    beltRuns: runs,
    beltHeadings: new Map(),
    unknownItemIds: [],
    unresolvedTagIds: [],
  } as unknown as SceneModel;
}

const belt = (index: number, at: Vec3) => instance(index, 2003, at, [0.64, 0.12, 0.64]);
const machine = (index: number, at: Vec3) => instance(index, 2303, at, [2.88, 3.8, 2.88]);

const link = (over: Partial<SorterLink> = {}): SorterLink => ({
  index: 100,
  color: 0xaabbcc,
  pick: [0, 0, 0],
  drop: [1.5, 0, 0],
  inputIndex: 1,
  outputIndex: 2,
  ...over,
});

test('a sorter is drawn as a body with an accent plate and one direction marking', () => {
  const scene = buildSorterScene(
    model([belt(1, [0, 0.1, 0]), machine(2, [1.5, 1.9, 0])], [link()]),
  );
  expect(scene.positions.length).toBeGreaterThan(0);
  expect(scene.colors.length).toBe(scene.positions.length);
  expect(scene.accent.positions.length).toBeGreaterThan(0);
  expect(scene.markings.length).toBe(1);
  expect(scene.markings[0]?.dir[0]).toBeCloseTo(1, 6);
  expect(scene.bodies).toEqual([{ index: 100, at: scene.bodies[0]?.at }]);
});

test('the pickup end stands on the belt surface, not inside the strip', () => {
  const scene = buildSorterScene(
    model([belt(1, [0, 0.1, 0]), machine(2, [1.5, 1.9, 0])], [link()]),
  );
  const base = scene.bodies[0]?.at as Vec3;
  // The seated pickup point is at y=0, inside a strip whose surface is at
  // 0.1 + half a thickness. The base stands on that surface at full height.
  expect(base[1] - SORTER.BASE_H / 2).toBeCloseTo(0.1 + RIBBON_THICKNESS / 2, 6);
});

test('an end already seated on its port gets no tie line', () => {
  const scene = buildSorterScene(
    model([belt(1, [0, 0.1, 0]), machine(2, [1.5, 1.9, 0])], [link()]),
  );
  expect(scene.ties.length).toBe(0);
});

test('an end away from what it serves keeps a tie that hugs the outside', () => {
  const scene = buildSorterScene(model([belt(1, [0, 0.1, 0]), machine(2, [9, 1.9, 0])], [link()]));
  expect(scene.ties.length).toBeGreaterThan(0);
  // Every tie vertex stays clear of the machine's interior.
  for (let i = 0; i < scene.ties.length; i += 3) {
    const x = scene.ties[i] as number;
    const inside = x > 9 - 2.88 / 2 + 0.01 && x < 9 + 2.88 / 2 - 0.01;
    expect(inside).toBe(false);
  }
});

test('the marking takes its contrast from the run it drops onto', () => {
  const runs: BeltRun[] = [
    {
      belts: [2],
      freeInput: true,
      freeOutput: true,
      cyclic: false,
      carried: [],
      hasExplicitTag: false,
    },
  ];
  const onRun = buildSorterScene(
    model([machine(1, [0, 1.9, 0]), belt(2, [1.5, 0.1, 0])], [link()], runs),
  );
  const overGround = buildSorterScene(
    model([machine(1, [0, 1.9, 0]), machine(2, [1.5, 1.9, 0])], [link()]),
  );
  // Over bare dark ground the marking is always the light one; over a strip it
  // is whatever reads against that strip's colour.
  expect(overGround.markings[0]?.dark).toBe(false);
  expect(typeof onRun.markings[0]?.dark).toBe('boolean');
});

test('a sorter with no resolvable ends still draws, and clicks find it', () => {
  const scene = buildSorterScene(model([], [link({ inputIndex: -1, outputIndex: -1 })]));
  expect(scene.positions.length).toBeGreaterThan(0);
  expect(scene.ties.length).toBe(0);
  expect(sorterNearest({ x: 0, y: 0, z: 0 }, scene.bodies)).toBe(100);
  expect(sorterNearest({ x: 0, y: 0, z: 0 }, [])).toBeNull();
});

test('a real blueprint draws every sorter, with ties only where an end is off its port', () => {
  const bp = parseBlueprint(
    readFileSync('tests/fixtures/factory-heretical-smelter-block.txt', 'utf8').trim(),
  );
  const sceneModel = buildSceneModel(bp, realCatalog);
  const scene = buildSorterScene(sceneModel);
  const sorters = bp.buildings.filter((b) => isSorter(b.itemId)).length;
  expect(sceneModel.sorters.length).toBe(sorters);
  expect(scene.bodies.length).toBe(sorters);
  expect(scene.markings.length).toBe(sorters);
  // The arm is the connection, so most ends need no tie -- but a real
  // blueprint does have exceptions, and both branches are exercised here.
  //
  // In this fixture 298 of 400 sorter ends are seated on the thing they serve
  // and 102 are not. The 102 are all belt ends: the game re-seats a sorter end
  // onto the slot pose of the building it names ONLY when that building is not
  // a belt (BlueprintUtils.RefreshBuildPreview guards on `!desc.isBelt`), so a
  // belt end keeps whatever the author left it at -- here, a tile and a half
  // short of the belt it feeds. Those are exactly the connections that are not
  // obvious from the geometry, which is what the tie lines are for.
  // Six numbers per segment, two segments per tie.
  const endsWithTies = scene.ties.length / 12;
  expect(endsWithTies).toBeGreaterThan(0);
  expect(endsWithTies).toBeLessThan(sorters);
});
