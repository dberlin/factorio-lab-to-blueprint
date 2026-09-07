import { expect, test } from '@rstest/core';
import type { TraceFrame } from '../../src/api/trace';
import { overlayGeometry } from '../../src/scene/TraceOverlay';

const frame: TraceFrame = {
  seq: 1,
  t: 0,
  strategy: 'freeform',
  candidate: 'all-products',
  phase: 'routed',
  height: null,
  arrangement: null,
  restart: null,
  stage: null,
  island: null,
  round: null,
  block: null,
  area: null,
  belt_tiles: null,
  incumbent: false,
  reason: null,
  bounds: [0, 0, 10, 10],
  buildings: [],
  truncated: false,
  stranded: [
    [0, 0, 4, 4],
    [1, 1, 2, 6],
  ],
  no_goods: [[3, 7]],
};

test('each stranded net becomes one segment in world coordinates', () => {
  const { segments } = overlayGeometry(frame, { stranded: true, noGoods: false });
  // World mapping is (bp.x, bp.z, -bp.y), exactly as buildSceneModel has it
  // (model/layout.ts); an overlay drawn in a different frame would sit
  // beside the buildings it is meant to indict.
  expect(segments).toHaveLength(2);
  expect(segments[0]).toEqual([0, 0.5, -0, 4, 0.5, -4]);
});

test('a hidden layer contributes nothing', () => {
  const { segments, cells } = overlayGeometry(frame, { stranded: false, noGoods: false });
  expect(segments).toHaveLength(0);
  expect(cells).toHaveLength(0);
});

test('a no-good names the strips it forbids', () => {
  const { cells } = overlayGeometry(frame, { stranded: false, noGoods: true });
  expect(cells).toHaveLength(2);
});

test('a null frame yields nothing for either layer', () => {
  const { segments, cells } = overlayGeometry(null, { stranded: true, noGoods: true });
  expect(segments).toHaveLength(0);
  expect(cells).toHaveLength(0);
});
