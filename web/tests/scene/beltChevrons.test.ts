import { expect, test } from '@rstest/core';
import { Object3D, Vector3 } from 'three';
import type { SceneModel } from '../../src/model/layout';
import { chevronRotationEuler, chevronTransforms } from '../../src/scene/BeltChevrons';

function model(headings: [number, number][]): SceneModel {
  return {
    instances: [
      {
        index: 0,
        itemId: 2001,
        modelIndex: 35,
        position: [0, 1, 0],
        size: [1, 0.2, 1],
        yawRad: 0,
        color: 1,
        recipeId: 0,
        filterId: 0,
        parameters: [],
      },
      {
        index: 1,
        itemId: 2303,
        modelIndex: 65,
        position: [5, 1, 0],
        size: [3, 3, 3],
        yawRad: 0,
        color: 1,
        recipeId: 1,
        filterId: 0,
        parameters: [],
      },
    ],
    beltRuns: [],
    beltHeadings: new Map(headings),
    unknownItemIds: [],
  } as unknown as SceneModel;
}

test('emits one chevron per belt with a heading, sitting on top of the belt', () => {
  const out = chevronTransforms(model([[0, Math.PI / 2]]));
  expect(out.length).toBe(1);
  expect(out[0]!.yawRad).toBeCloseTo(Math.PI / 2, 5);
  // above the belt's top face (position.y + size.y/2)
  expect(out[0]!.position[1]).toBeGreaterThan(1.1);
});

test('ignores non-belt buildings and belts with no heading', () => {
  expect(chevronTransforms(model([])).length).toBe(0);
  // a heading keyed to the assembler must not produce a chevron
  expect(chevronTransforms(model([[1, 0]])).length).toBe(0);
});

test('the composed rotation points the arrow apex along the heading, not across it', () => {
  // circleGeometry(1, 3)'s first outer vertex (the apex) sits at local +X.
  const apexLocal = new Vector3(1, 0, 0);
  for (const yaw of [-Math.PI / 2, 0, Math.PI / 2, Math.PI]) {
    const dummy = new Object3D();
    dummy.rotation.set(...chevronRotationEuler(yaw));
    dummy.updateMatrixWorld();
    const worldApex = apexLocal.clone().applyEuler(dummy.rotation);
    // Heading convention is atan2(dx, dz): zero points +Z, so the apex's
    // world (x, z) must land on (sin yaw, cos yaw).
    expect(worldApex.x).toBeCloseTo(Math.sin(yaw), 5);
    expect(worldApex.z).toBeCloseTo(Math.cos(yaw), 5);
  }
});
