import { expect, test } from '@rstest/core';
import { layoutDigits } from '../../src/scene/CountLabels';
import { PLUS_GLYPH } from '../../src/scene/digitAtlas';

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

test('a plus-flagged placement gets a leading "+" glyph', () => {
  const quads = layoutDigits([{ position: [0, 0, 0], value: 2, plus: true }]);
  expect(quads.length).toBe(2);
  expect(quads[0]!.digit).toBe(PLUS_GLYPH);
  expect(quads[1]!.digit).toBe(2);
  // The "+" leads, so it sits left of the number it qualifies.
  expect(quads[0]!.position[0]).toBeLessThan(quads[1]!.position[0]);
});

test('a placement can ask for a smaller glyph than the default', () => {
  const [big] = layoutDigits([{ position: [0, 0, 0], value: 7 }]);
  const [small] = layoutDigits([{ position: [0, 0, 0], value: 7, scale: 0.3 }]);
  expect(small!.scale).toBe(0.3);
  expect(small!.scale).toBeLessThan(big!.scale);
});

test('a smaller glyph is spaced proportionally, not at the full-size pitch', () => {
  const wide = layoutDigits([{ position: [0, 0, 0], value: 42 }]);
  const tight = layoutDigits([{ position: [0, 0, 0], value: 42, scale: 0.3 }]);
  const gap = (q: ReturnType<typeof layoutDigits>) => q[1]!.position[0] - q[0]!.position[0];
  expect(gap(tight)).toBeLessThan(gap(wide));
});
