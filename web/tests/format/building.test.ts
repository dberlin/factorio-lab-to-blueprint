import { expect, test } from '@rstest/core';
import { readBuilding } from '../../src/format/building';
import { BinaryReader } from '../../src/format/reader';

/** Builds one record; `extra` is the per-class float block. */
function layoutA(opts: {
  path: number;
  itemId: number;
  extraFloats: number[];
  params?: number[];
  content?: string;
}): Uint8Array {
  const params = opts.params ?? [];
  const contentBytes = opts.content ? new TextEncoder().encode(opts.content) : null;
  const size =
    4 +
    4 +
    2 +
    2 +
    1 +
    16 +
    opts.extraFloats.length * 4 +
    8 +
    6 +
    2 +
    2 +
    2 +
    params.length * 4 +
    (opts.path <= -102 ? 4 + (contentBytes ? 1 + contentBytes.length : 0) : 0);
  const b = new Uint8Array(size);
  const dv = new DataView(b.buffer);
  let o = 0;
  dv.setInt32(o, opts.path, true);
  o += 4;
  dv.setInt32(o, 7, true);
  o += 4; // index
  dv.setInt16(o, opts.itemId, true);
  o += 2;
  dv.setInt16(o, 42, true);
  o += 2; // modelIndex
  dv.setInt8(o, 1);
  o += 1; // areaIndex
  for (const v of [3, 21, 0.5, 270]) {
    dv.setFloat32(o, v, true);
    o += 4;
  }
  for (const v of opts.extraFloats) {
    dv.setFloat32(o, v, true);
    o += 4;
  }
  dv.setInt32(o, 5, true);
  o += 4; // outputObjIdx
  dv.setInt32(o, -1, true);
  o += 4; // inputObjIdx
  for (const v of [6, -1, 0, 1, 0, 0]) {
    dv.setInt8(o, v);
    o += 1;
  }
  dv.setInt16(o, 61, true);
  o += 2; // recipeId
  dv.setInt16(o, 1006, true);
  o += 2; // filterId
  dv.setInt16(o, params.length, true);
  o += 2;
  for (const p of params) {
    dv.setInt32(o, p, true);
    o += 4;
  }
  if (opts.path <= -102) {
    dv.setInt32(o, contentBytes ? contentBytes.length : 0, true);
    o += 4;
    if (contentBytes) {
      b[o] = contentBytes.length;
      o += 1;
      b.set(contentBytes, o);
    }
  }
  return b;
}

test('path -102, generic building: no extra floats, reads trailing content', () => {
  const b = readBuilding(
    new BinaryReader(layoutA({ path: -102, itemId: 2303, extraFloats: [], content: 'Hub' })),
  );
  expect(b.index).toBe(7);
  expect(b.itemId).toBe(2303);
  expect(b.yaw).toBeCloseTo(270);
  expect(b.z).toBeCloseTo(0.5);
  expect(b.outputObjIdx).toBe(5);
  expect(b.recipeId).toBe(61);
  expect(b.content).toBe('Hub');
  // offset2 mirrors offset for non-sorters
  expect(b.x2).toBeCloseTo(b.x);
});

test('path -102, belt: one extra float (tilt), offset2/yaw2/tilt2 mirror offset/yaw/tilt', () => {
  const b = readBuilding(
    new BinaryReader(layoutA({ path: -102, itemId: 2003, extraFloats: [12] })),
  );
  expect(b.tilt).toBeCloseTo(12);
  expect(b.tilt2).toBeCloseTo(12);
  // x=3, y=21, z=0.5, yaw=270 are all distinct, so a cross-wired mirror
  // (e.g. x2 = y instead of x2 = x) is detectable here.
  expect(b.x2).toBeCloseTo(b.x);
  expect(b.y2).toBeCloseTo(b.y);
  expect(b.z2).toBeCloseTo(b.z);
  expect(b.yaw2).toBeCloseTo(b.yaw);
  expect(b.content).toBeNull();
});

test('path -102, sorter: eight extra floats map to tilt,pitch,xyz2,yaw2,tilt2,pitch2', () => {
  const b = readBuilding(
    new BinaryReader(
      layoutA({ path: -102, itemId: 2012, extraFloats: [1, 2, 30, 31, 32, 90, 3, 4], params: [9] }),
    ),
  );
  expect(b.tilt).toBeCloseTo(1);
  expect(b.pitch).toBeCloseTo(2);
  expect(b.x2).toBeCloseTo(30);
  expect(b.y2).toBeCloseTo(31);
  expect(b.z2).toBeCloseTo(32);
  expect(b.yaw2).toBeCloseTo(90);
  expect(b.tilt2).toBeCloseTo(3);
  expect(b.pitch2).toBeCloseTo(4);
  expect(b.parameters).toEqual([9]);
});

test('path -101 uses layout A but has NO content field', () => {
  const b = readBuilding(new BinaryReader(layoutA({ path: -101, itemId: 2303, extraFloats: [] })));
  expect(b.itemId).toBe(2303);
  expect(b.content).toBeNull();
});

test('a non-negative path number IS the building index (legacy layout)', () => {
  const b = new Uint8Array(4 + 1 + 24 + 8 + 4 + 8 + 6 + 6);
  const dv = new DataView(b.buffer);
  let o = 0;
  dv.setInt32(o, 12, true);
  o += 4; // path == index
  dv.setInt8(o, 0);
  o += 1;
  for (const v of [1, 2, 3, 4, 5, 6]) {
    dv.setFloat32(o, v, true);
    o += 4;
  } // offset, offset2
  dv.setFloat32(o, 90, true);
  o += 4; // yaw
  dv.setFloat32(o, 91, true);
  o += 4; // yaw2
  dv.setInt16(o, 2001, true);
  o += 2;
  dv.setInt16(o, 35, true);
  o += 2;
  dv.setInt32(o, -1, true);
  o += 4;
  dv.setInt32(o, -1, true);
  o += 4;
  o += 6; // slots
  dv.setInt16(o, 0, true);
  o += 2; // recipeId
  dv.setInt16(o, 0, true);
  o += 2; // filterId
  dv.setInt16(o, 0, true);
  o += 2; // paramCount

  const out = readBuilding(new BinaryReader(b));
  expect(out.index).toBe(12);
  expect(out.itemId).toBe(2001);
  expect(out.x2).toBeCloseTo(4);
  expect(out.yaw2).toBeCloseTo(91);
  expect(out.tilt).toBe(0);
});
