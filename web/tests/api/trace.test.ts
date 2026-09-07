import { expect, test } from '@rstest/core';
import { TraceFrame, TracePage } from '../../src/api/trace';

const good = {
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

test('a frame parses and rejects a row of the wrong arity', () => {
  expect(() => TraceFrame.parse(good)).not.toThrow();
  expect(() => TraceFrame.parse({ ...good, buildings: [[1, 2, 3]] })).toThrow();
});

test('a page carries a cursor, a drop count and a completion flag', () => {
  const page = TracePage.parse({ frames: [], next: 7, dropped: 3, complete: true });
  expect(page.next).toBe(7);
  expect(page.dropped).toBe(3);
  expect(page.complete).toBe(true);
});
