import { expect, test } from '@rstest/core';
import type { TraceFrame } from '../../src/api/trace';
import { traceFrameToBlueprint } from '../../src/model/traceScene';
import { realCatalog } from '../support/catalog';

const frame: TraceFrame = {
  seq: 1,
  t: 0.5,
  strategy: 'freeform',
  candidate: 'all-products',
  phase: 'incumbent',
  height: 34,
  arrangement: 2,
  restart: null,
  stage: null,
  island: null,
  round: null,
  block: null,
  area: 12,
  belt_tiles: 2,
  incumbent: true,
  reason: null,
  bounds: [0, 0, 3, 3],
  truncated: false,
  stranded: [],
  no_goods: [],
  buildings: [
    [2001, 35, 0, 0, 0, 0, 61, 0, 1, -1],
    [2001, 35, 1, 0, 0.5, 90, 0, 0, -1, 0],
  ],
};

test('rows become buildings whose index is their array position', () => {
  const bp = traceFrameToBlueprint(frame);
  expect(bp.buildings).toHaveLength(2);
  expect(bp.buildings[0]?.index).toBe(0);
  expect(bp.buildings[1]?.index).toBe(1);
  expect(bp.buildings[0]?.itemId).toBe(2001);
  expect(bp.buildings[1]?.z).toBe(0.5);
  expect(bp.buildings[1]?.yaw).toBe(90);
});

test('connection indices survive so belt runs can be built', () => {
  const bp = traceFrameToBlueprint(frame);
  expect(bp.buildings[0]?.outputObjIdx).toBe(1);
  expect(bp.buildings[0]?.inputObjIdx).toBe(-1);
  expect(bp.buildings[1]?.inputObjIdx).toBe(0);
});

test('a synthesised frame is renderable by buildSceneModel', async () => {
  // Ruling 1 (task-5-addendum.md): there is no `tests/helpers/catalog` loader.
  // The real fixture is `tests/support/catalog.ts`, exporting a ready-built
  // catalog as a value.
  const { buildSceneModel } = await import('../../src/model/layout');
  const model = buildSceneModel(traceFrameToBlueprint(frame), realCatalog);
  expect(model.instances).toHaveLength(2);
});

test('a synthesised frame was never hashed or encoded', () => {
  // A trace frame is never pasteable (constraints.md, task-5-addendum.md): it
  // carries no blueprint string and no validity claim.
  const bp = traceFrameToBlueprint(frame);
  expect(bp.hashValid).toBe(false);
  expect(bp.patch).toBeNull();
});
