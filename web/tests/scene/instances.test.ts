import { expect, test } from '@rstest/core';
import { Matrix4, Object3D } from 'three';
import type { BuildingInstance, SceneModel } from '../../src/model/layout';
import { drawnInstances, instanceMatrix } from '../../src/scene/BuildingInstances';

const inst = (over: Partial<BuildingInstance> = {}): BuildingInstance => ({
  index: 0,
  itemId: 2303,
  modelIndex: 65,
  position: [3, 1, -21],
  size: [4, 5, 6],
  yawRad: 0,
  color: 0xffffff,
  recipeId: 0,
  filterId: 0,
  parameters: [],
  ...over,
});

test('encodes position and size into the instance matrix', () => {
  const m = instanceMatrix(inst(), new Object3D());
  const pos = new Matrix4().copy(m);
  const e = pos.elements;
  expect(e[12]).toBeCloseTo(3);
  expect(e[13]).toBeCloseTo(1);
  expect(e[14]).toBeCloseTo(-21);
  // scale is the column lengths
  expect(Math.hypot(e[0]!, e[1]!, e[2]!)).toBeCloseTo(4);
  expect(Math.hypot(e[4]!, e[5]!, e[6]!)).toBeCloseTo(5);
  expect(Math.hypot(e[8]!, e[9]!, e[10]!)).toBeCloseTo(6);
});

test('yaw rotates about world Y', () => {
  const m = instanceMatrix(inst({ yawRad: Math.PI / 2, size: [1, 1, 1] }), new Object3D());
  const e = m.elements;
  // rotating +90deg about Y maps local +X to -Z
  expect(e[0]).toBeCloseTo(0);
  expect(e[2]).toBeCloseTo(-1);
});

test('belts and sorters are left to their own layers, not drawn as boxes too', () => {
  // A belt is a strip and a sorter is a little machine; a box in the same
  // place would be a second, wrong shape on top of the right one.
  const instances = [
    { index: 1, itemId: 2003 }, // belt
    { index: 2, itemId: 2014 }, // sorter
    { index: 3, itemId: 2303 }, // assembler
    { index: 4, itemId: 2020 }, // splitter
  ].map((o) => ({
    ...o,
    modelIndex: 1,
    position: [0, 0, 0] as [number, number, number],
    size: [1, 1, 1] as [number, number, number],
    yawRad: 0,
    color: 0x888888,
    recipeId: 0,
    filterId: 0,
    parameters: [] as readonly number[],
  }));
  const drawn = drawnInstances({ instances } as unknown as SceneModel);
  expect(drawn.map((i) => i.index)).toEqual([3, 4]);
});
