import { readFileSync } from 'node:fs';
import { expect, test } from '@rstest/core';
import { parseBlueprint } from '../../src/format';
import { parsePayload } from '../../src/format/blueprint';
import { parseEnvelope } from '../../src/format/envelope';

const read = (n: string) => readFileSync(`tests/fixtures/${n}.txt`, 'utf8').trim();

// name, payload version, areas, buildings
const FIXTURES: Array<[string, number, number, number]> = [
  ['factory-quick-start-step-1-minimum-blue-cube-automation', 1, 1, 36],
  ['factory-quick-start-step-3-red-cube', 1, 1, 287],
  ['12-s-purple-science-from-smelted-refined-products', 0, 1, 3678],
  ['falk-v7-mall-full', 1, 1, 1993],
  ['new-planet-establishment-polar-buildings-calldown-for-mass-production', 1, 5, 5],
  [
    'temple-of-effectiveness-polar-hub-by-nilaus-now-with-900mw-of-exchanger-power-distribution',
    1,
    7,
    806,
  ],
  ['tillable-blackbox-module-polar-artificial-stars-x85-warper-production-x24', 1, 5, 351],
  ['factory-heretical-smelter-block', 2, 1, 591],
  ['factory-endgame-distribution-hub', 2, 9, 1969],
  ['factory-full-planet-wind-ready-for-solar', 2, 23, 3974],
];

for (const [name, version, areas, buildings] of FIXTURES) {
  test(`parses ${name}`, () => {
    const bp = parseBlueprint(read(name));
    expect(bp.version).toBe(version);
    expect(bp.areas).toHaveLength(areas);
    expect(bp.buildings).toHaveLength(buildings);
    expect(bp.hashValid).toBe(true);
  });
}

test('consumes the payload exactly, through the reform flag', () => {
  for (const [name] of FIXTURES) {
    const { payload } = parseEnvelope(read(name));
    const { bytesConsumed } = parsePayload(payload);
    // The game's BinaryReader stops after the reform flag and ignores any trailing
    // bytes; two 0.10.34 fixtures carry 5 such bytes. Never over-read.
    expect(bytesConsumed).toBeLessThanOrEqual(payload.length);
    expect(payload.length - bytesConsumed).toBeLessThanOrEqual(8);
  }
});

test('building invariants hold across every fixture', () => {
  for (const [name] of FIXTURES) {
    const bp = parseBlueprint(read(name));
    const n = bp.buildings.length;
    bp.buildings.forEach((b, i) => {
      expect(b.index).toBe(i);
      expect(b.areaIndex).toBeGreaterThanOrEqual(0);
      expect(b.areaIndex).toBeLessThan(bp.areas.length);
      expect(b.outputObjIdx).toBeGreaterThanOrEqual(-1);
      expect(b.outputObjIdx).toBeLessThan(n);
      expect(b.inputObjIdx).toBeGreaterThanOrEqual(-1);
      expect(b.inputObjIdx).toBeLessThan(n);
      expect(b.yaw).toBeGreaterThanOrEqual(-0.5);
      expect(b.yaw).toBeLessThanOrEqual(360.5);
      expect(b.itemId).toBeGreaterThan(0);
    });
  }
});

test('belts occupy several distinct altitudes (the reason we render in 3D)', () => {
  const bp = parseBlueprint(read('factory-quick-start-step-3-red-cube'));
  const zs = new Set(
    bp.buildings
      .filter((b) => b.itemId > 2000 && b.itemId < 2010)
      .map((b) => Math.round(b.z * 100) / 100),
  );
  expect(zs.size).toBeGreaterThan(1);
});

test('rejects a truncated payload rather than reading past the end', () => {
  const { payload } = parseEnvelope(read('factory-quick-start-step-3-red-cube'));
  expect(() => parsePayload(payload.subarray(0, payload.length - 40))).toThrow(RangeError);
});

// DSP's latitude-band segment counts, from the game's own area-grid table.
const KNOWN_AREA_SEGMENTS = new Set([4, 8, 16, 20, 32, 40, 60, 80, 100, 120, 160, 200]);

test('pins BlueprintArea field identity for factory-full-planet-wind-ready-for-solar (23 areas)', () => {
  const bp = parseBlueprint(read('factory-full-planet-wind-ready-for-solar'));
  const areas = bp.areas;
  expect(areas).toHaveLength(23);

  // index runs 0..n-1.
  expect(areas.map((a) => a.index)).toEqual([...Array(23).keys()]);

  // Exactly one root area (the equatorial anchor with no parent).
  expect(areas.filter((a) => a.parentIndex === -1)).toHaveLength(1);

  // areaSegments follows DSP's latitude-band sequence: it rises pole-to-equator then
  // mirrors back down, since this fixture covers the whole planet.
  expect(areas.map((a) => a.areaSegments)).toEqual([
    4, 8, 16, 20, 32, 40, 60, 80, 100, 120, 160, 200, 160, 120, 100, 80, 60, 40, 32, 20, 16, 8, 4,
  ]);
  expect(areas.every((a) => KNOWN_AREA_SEGMENTS.has(a.areaSegments))).toBe(true);

  // width/height are positive, and width tapers toward both poles (indices 0 and 22)
  // from its peak at the equatorial area (index 11).
  expect(areas.every((a) => a.width > 0 && a.height > 0)).toBe(true);
  let risingWidth = -Infinity;
  for (const a of areas.slice(0, 12)) {
    expect(a.width).toBeGreaterThan(risingWidth);
    risingWidth = a.width;
  }
  let fallingWidth = Infinity;
  for (const a of areas.slice(11)) {
    expect(a.width).toBeLessThan(fallingWidth);
    fallingWidth = a.width;
  }

  // Whole-object pin on the equatorial/root area: catches any permutation among the
  // same-width i16 fields (width<->height, tropicAnchor<->areaSegments), since a
  // field-by-field check would miss a consistent swap across all 23 areas.
  expect(areas[11]).toEqual({
    index: 11,
    parentIndex: -1,
    tropicAnchor: 0,
    areaSegments: 200,
    anchorLocalOffsetX: 0,
    anchorLocalOffsetY: 0,
    width: 994,
    height: 161,
  });
});

test('pins BlueprintArea field identity for factory-endgame-distribution-hub (9 areas)', () => {
  const bp = parseBlueprint(read('factory-endgame-distribution-hub'));
  const areas = bp.areas;
  expect(areas).toHaveLength(9);

  expect(areas.map((a) => a.index)).toEqual([...Array(9).keys()]);
  expect(areas.filter((a) => a.parentIndex === -1)).toHaveLength(1);

  // This fixture only builds outward from one pole toward the equator (index 8, the
  // root), so areaSegments is the leading, non-mirrored prefix of the sequence.
  expect(areas.map((a) => a.areaSegments)).toEqual([4, 8, 16, 20, 32, 40, 60, 80, 100]);
  expect(areas.every((a) => KNOWN_AREA_SEGMENTS.has(a.areaSegments))).toBe(true);

  expect(areas.every((a) => a.width > 0 && a.height > 0)).toBe(true);
  let risingWidth = -Infinity;
  for (const a of areas) {
    expect(a.width).toBeGreaterThan(risingWidth);
    risingWidth = a.width;
  }

  // Whole-object pin on a non-root, non-boundary area.
  expect(areas[4]).toEqual({
    index: 4,
    parentIndex: 5,
    tropicAnchor: 0,
    areaSegments: 32,
    anchorLocalOffsetX: 0,
    anchorLocalOffsetY: -10,
    width: 160,
    height: 10,
  });
});
