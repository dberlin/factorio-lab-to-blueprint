import { expect, test } from '@rstest/core';
import {
  ARROW_LENGTH,
  arrowIsDark,
  arrowWedge,
  extendEnds,
  blockLength,
  CORNER_RADIUS,
  labelLength,
  layoutBlocks,
  RIBBON_THICKNESS,
  RIBBON_WIDTH,
  ribbonMesh,
  roundCorners,
  runColor,
  steppedClimb,
  straightStretches,
  type Vec3,
} from '../../src/model/beltRibbons';

const line = (n: number, step: Vec3, from: Vec3 = [0, 0.1, 0]): Vec3[] =>
  Array.from({ length: n }, (_, i) => [
    from[0] + step[0] * i,
    from[1] + step[1] * i,
    from[2] + step[2] * i,
  ]);

// ---------------------------------------------------------------- climbs

test('a level change becomes a riser that leans along travel, never a vertical face', () => {
  const out = steppedClimb([
    [0, 0.1, 0],
    [0, 0.1, 1],
    [0, 0.6, 2],
    [0, 0.6, 3],
  ]);
  // Two points inserted around the midpoint of the climbing segment.
  expect(out.length).toBe(6);
  const [low, high] = [out[2] as Vec3, out[3] as Vec3];
  expect(low[1]).toBeCloseTo(0.1, 6);
  expect(high[1]).toBeCloseTo(0.6, 6);
  // The lean is what stops the strip's top and bottom faces being coplanar,
  // which z-fights into a fringe. Do not "simplify" these to one point.
  expect(high[2] - low[2]).toBeGreaterThan(0.05);
  expect(high[2] - low[2]).toBeLessThan(0.4);
});

test('a flat run is returned unchanged', () => {
  const flat = line(4, [0, 0, 1]);
  expect(steppedClimb(flat)).toEqual(flat);
});

// --------------------------------------------------------------- corners

test('a straight polyline keeps its points; a right angle gains an arc', () => {
  const straight = line(4, [0, 0, 1]);
  expect(roundCorners(straight, CORNER_RADIUS)).toEqual(straight);

  const corner: Vec3[] = [
    [0, 0.1, 0],
    [0, 0.1, 2],
    [2, 0.1, 2],
  ];
  const rounded = roundCorners(corner, CORNER_RADIUS);
  expect(rounded.length).toBeGreaterThan(corner.length);
  // The arc stays inside the corner's own box -- it cuts the corner, never
  // bulges past it.
  for (const [x, , z] of rounded) {
    expect(x).toBeGreaterThanOrEqual(-1e-9);
    expect(x).toBeLessThanOrEqual(2 + 1e-9);
    expect(z).toBeGreaterThanOrEqual(-1e-9);
    expect(z).toBeLessThanOrEqual(2 + 1e-9);
  }
  // and the corner point itself is gone, replaced by the arc
  expect(rounded.some(([x, , z]) => x === 0 && z === 2)).toBe(false);
});

// ------------------------------------------------------------------ mesh

test('every ribbon triangle is wound to agree with the normal it carries', () => {
  // Materials are DoubleSide, and three flips the shading normal on a
  // back-facing fragment: a top face wound the wrong way is lit as though the
  // sun were under the floor. This is the regression test for that.
  const { positions, normals } = ribbonMesh(
    roundCorners(
      [
        [0, 0.1, 0],
        [0, 0.1, 3],
        [3, 0.1, 3],
      ],
      CORNER_RADIUS,
    ),
    RIBBON_WIDTH,
    RIBBON_THICKNESS,
  );
  expect(positions.length % 9).toBe(0);
  expect(normals.length).toBe(positions.length);

  let checked = 0;
  for (let i = 0; i < positions.length; i += 9) {
    const ax = positions[i] as number,
      ay = positions[i + 1] as number,
      az = positions[i + 2] as number;
    const bx = positions[i + 3] as number,
      by = positions[i + 4] as number,
      bz = positions[i + 5] as number;
    const cx = positions[i + 6] as number,
      cy = positions[i + 7] as number,
      cz = positions[i + 8] as number;
    const ux = bx - ax,
      uy = by - ay,
      uz = bz - az;
    const vx = cx - ax,
      vy = cy - ay,
      vz = cz - az;
    const gx = uy * vz - uz * vy,
      gy = uz * vx - ux * vz,
      gz = ux * vy - uy * vx;
    const dot =
      gx * (normals[i] as number) +
      gy * (normals[i + 1] as number) +
      gz * (normals[i + 2] as number);
    // Degenerate slivers (zero area) are allowed; anything with area must agree.
    if (Math.hypot(gx, gy, gz) > 1e-9) {
      expect(dot).toBeGreaterThan(0);
      checked++;
    }
  }
  expect(checked).toBeGreaterThan(20);
});

test('a straight ribbon is exactly one width across and one thickness deep', () => {
  const { positions } = ribbonMesh(line(4, [0, 0, 1]), RIBBON_WIDTH, RIBBON_THICKNESS);
  let minX = Infinity,
    maxX = -Infinity,
    minY = Infinity,
    maxY = -Infinity;
  for (let i = 0; i < positions.length; i += 3) {
    minX = Math.min(minX, positions[i] as number);
    maxX = Math.max(maxX, positions[i] as number);
    minY = Math.min(minY, positions[i + 1] as number);
    maxY = Math.max(maxY, positions[i + 1] as number);
  }
  expect(maxX - minX).toBeCloseTo(RIBBON_WIDTH, 6);
  expect(maxY - minY).toBeCloseTo(RIBBON_THICKNESS, 6);
});

test('a run of fewer than two points produces no geometry', () => {
  expect(ribbonMesh([[0, 0, 0]], RIBBON_WIDTH, RIBBON_THICKNESS).positions).toEqual([]);
});

// -------------------------------------------------------------- stretches

test('stretches split at a turn and exclude the climbing segment', () => {
  const points: Vec3[] = [
    [0, 0.1, 0],
    [0, 0.1, 1],
    [0, 0.1, 2],
    [0, 0.6, 3], // climbs
    [0, 0.6, 4],
    [1, 0.6, 4], // turns
    [2, 0.6, 4],
  ];
  const stretches = straightStretches(points);
  // flat +Z leg, flat +Z leg after the climb, then the +X leg
  expect(stretches.length).toBe(3);
  expect(stretches[0]?.dir).toEqual([0, 0, 1]);
  expect(stretches[2]?.dir).toEqual([1, 0, 0]);
  // The climbing segment belongs to no stretch, so nothing can be laid on it.
  const covered = stretches.reduce((sum, s) => sum + (s.end - s.start), 0);
  expect(covered).toBeLessThan(6);
});

// ----------------------------------------------------------------- blocks

test('a block is longer for a longer number, so cadence follows the content', () => {
  expect(labelLength(3)).toBeGreaterThan(labelLength(1));
  expect(blockLength(3)).toBeGreaterThan(blockLength(1));
});

test('the arrow leads and the number trails, in travel order', () => {
  const blocks = layoutBlocks(line(40, [0, 0, 1]), 2);
  expect(blocks.length).toBeGreaterThan(0);
  for (const b of blocks) {
    expect(b.label).not.toBeNull();
    // travel is +Z, so the arrow must sit further along Z than its number
    expect((b.arrow[2] as number) > (b.label as Vec3)[2]).toBe(true);
  }
});

test('blocks repeat with a gap of two blocks between them', () => {
  const blocks = layoutBlocks(line(60, [0, 0, 1]), 2);
  expect(blocks.length).toBeGreaterThan(2);
  const step = (blocks[1] as { arrow: Vec3 }).arrow[2] - (blocks[0] as { arrow: Vec3 }).arrow[2];
  expect(step).toBeCloseTo(blockLength(2) * 3, 4);
});

test('no block straddles a turn: every block lies on one leg', () => {
  const points: Vec3[] = [...line(20, [0, 0, 1]), ...line(20, [1, 0, 0], [1, 0.1, 19])];
  for (const b of layoutBlocks(points, 3)) {
    const onFirstLeg = b.arrow[0] < 0.001 && (b.label === null || b.label[0] < 0.001);
    const onSecondLeg = b.arrow[2] > 18.999 && (b.label === null || b.label[2] > 18.999);
    expect(onFirstLeg || onSecondLeg).toBe(true);
  }
});

test('a run too short for a whole block still gets a bare arrow, and a tiny one gets nothing', () => {
  const short = layoutBlocks(line(3, [0, 0, 0.4]), 3);
  expect(short.length).toBe(1);
  expect(short[0]?.label).toBeNull();

  expect(
    layoutBlocks(
      [
        [0, 0.1, 0],
        [0, 0.1, ARROW_LENGTH / 3],
      ],
      1,
    ),
  ).toEqual([]);
});

test('a block never sits on the climbing segment of a run', () => {
  const points: Vec3[] = [
    ...line(12, [0, 0, 1]),
    [0, 0.6, 12],
    ...line(12, [0, 0, 1], [0, 0.6, 13]),
  ];
  for (const b of layoutBlocks(points, 2)) {
    const zs = [b.arrow[2], ...(b.label ? [b.label[2]] : [])];
    for (const z of zs) expect(z < 11 || z > 13).toBe(true);
  }
});

// ---------------------------------------------------------------- palette

test('run colours are deterministic and well separated', () => {
  expect(runColor(7)).toBe(runColor(7));
  const seen = new Set([0, 1, 2, 3, 4, 5].map(runColor));
  expect(seen.size).toBe(6);
});

test('arrow contrast follows the ribbon it sits on', () => {
  expect(arrowIsDark(0xf3ec8a)).toBe(true); // pale yellow run
  expect(arrowIsDark(0x2a2f8f)).toBe(false); // navy run
});

// ------------------------------------------------------------- run extents

test('a run is grown half a tile at each end so junctions meet flush', () => {
  const grown = extendEnds([
    [0, 0.1, 0],
    [0, 0.1, 1],
    [0, 0.1, 2],
  ]);
  expect(grown.length).toBe(3);
  expect((grown[0] as Vec3)[2]).toBeCloseTo(-0.5, 6);
  expect((grown[2] as Vec3)[2]).toBeCloseTo(2.5, 6);
  // the interior is untouched
  expect(grown[1]).toEqual([0, 0.1, 1]);
});

test('a one-belt run becomes a tile-long strip along its own heading', () => {
  const grown = extendEnds([[3, 0.1, -2]], Math.PI / 2); // heading +X
  expect(grown.length).toBe(2);
  expect((grown[0] as Vec3)[0]).toBeLessThan(3);
  expect((grown[1] as Vec3)[0]).toBeGreaterThan(3);
  expect((grown[0] as Vec3)[2]).toBeCloseTo(-2, 6);
  // With no heading there is no direction to extend along, so nothing is drawn.
  expect(extendEnds([[3, 0.1, -2]])).toEqual([]);
});

test('the arrow wedge points along travel and is wound to match its normals', () => {
  const { positions, normals } = arrowWedge();
  let maxZ = -Infinity;
  let minZ = Infinity;
  for (let i = 0; i < positions.length; i += 3) {
    maxZ = Math.max(maxZ, positions[i + 2] as number);
    minZ = Math.min(minZ, positions[i + 2] as number);
  }
  // The apex is at +Z: the glyph's local +Z is travel.
  expect(maxZ).toBeGreaterThan(-minZ);
  expect(maxZ - minZ).toBeCloseTo(ARROW_LENGTH, 5);

  for (let i = 0; i < positions.length; i += 9) {
    const a = positions.slice(i, i + 3) as number[];
    const b = positions.slice(i + 3, i + 6) as number[];
    const c = positions.slice(i + 6, i + 9) as number[];
    const u = [b[0]! - a[0]!, b[1]! - a[1]!, b[2]! - a[2]!];
    const v = [c[0]! - a[0]!, c[1]! - a[1]!, c[2]! - a[2]!];
    const g = [
      u[1]! * v[2]! - u[2]! * v[1]!,
      u[2]! * v[0]! - u[0]! * v[2]!,
      u[0]! * v[1]! - u[1]! * v[0]!,
    ];
    const dot = g[0]! * normals[i]! + g[1]! * normals[i + 1]! + g[2]! * normals[i + 2]!;
    if (Math.hypot(g[0]!, g[1]!, g[2]!) > 1e-9) expect(dot).toBeGreaterThan(0);
  }
});
