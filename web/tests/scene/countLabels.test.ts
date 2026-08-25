import { expect, test } from '@rstest/core';
import { layoutDigits } from '../../src/scene/CountLabels';

test('lays out one quad per digit, centred on the placement', () => {
  const quads = layoutDigits([{ position: [10, 2, 5], value: 360 }]);
  expect(quads.length).toBe(3);
  expect(quads.map((q) => q.digit)).toEqual([3, 6, 0]);
  // centred: mean x offset is the placement's x
  const meanX = quads.reduce((n, q) => n + q.position[0], 0) / quads.length;
  expect(meanX).toBeCloseTo(10, 5);
  expect(quads.every((q) => q.position[1] === 2)).toBe(true);
});

test('handles multi-digit and single-digit values', () => {
  expect(layoutDigits([{ position: [0, 0, 0], value: 7 }]).length).toBe(1);
  expect(layoutDigits([{ position: [0, 0, 0], value: 1800 }]).length).toBe(4);
});

test('emits nothing for an empty list', () => {
  expect(layoutDigits([]).length).toBe(0);
});

test('draws 0 as a single "0" digit', () => {
  // layoutDigits itself has no notion of "unset" -- overlays.ts never emits
  // a CountPlacement for 0, but this pins what layoutDigits would do if it
  // were ever handed one, since callers rely on its Math.abs(Math.trunc(...))
  // as defence in depth, not on this contract being exercised in practice.
  const quads = layoutDigits([{ position: [0, 0, 0], value: 0 }]);
  expect(quads.map((q) => q.digit)).toEqual([0]);
});

test('a negative value is drawn via Math.abs, as defence in depth', () => {
  // overlays.ts is the actual gate against negative counts (Fix 1); this
  // pins layoutDigits' own fallback behaviour so the contract is explicit
  // rather than assumed.
  const quads = layoutDigits([{ position: [0, 0, 0], value: -5 }]);
  expect(quads.map((q) => q.digit)).toEqual([5]);
});
