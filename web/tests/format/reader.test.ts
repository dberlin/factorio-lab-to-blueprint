import { expect, test } from '@rstest/core';
import { BinaryReader } from '../../src/format/reader';

test('reads little-endian primitives in order', () => {
  const buf = new Uint8Array(14);
  const dv = new DataView(buf.buffer);
  dv.setInt32(0, -102, true);
  dv.setInt16(4, 2003, true);
  dv.setUint16(6, 37, true);
  dv.setFloat32(8, 1.5, true);
  dv.setInt8(12, -1);
  dv.setUint8(13, 200);

  const r = new BinaryReader(buf);
  expect(r.i32()).toBe(-102);
  expect(r.i16()).toBe(2003);
  expect(r.u16()).toBe(37);
  expect(r.f32()).toBeCloseTo(1.5);
  expect(r.i8()).toBe(-1);
  expect(r.u8()).toBe(200);
  expect(r.remaining).toBe(0);
});

test('throws RangeError past the end instead of returning garbage', () => {
  const r = new BinaryReader(new Uint8Array(2));
  expect(() => r.i32()).toThrow(RangeError);
});

test('reads a C# BinaryWriter string (LEB128 length + UTF-8)', () => {
  // 0x0d = 13 bytes follow
  const text = '\n\nHub\\s518;\n';
  const bytes = new TextEncoder().encode(text);
  const buf = new Uint8Array(1 + bytes.length);
  buf[0] = bytes.length;
  buf.set(bytes, 1);
  expect(new BinaryReader(buf).string()).toBe(text);
});

test('reads multi-byte LEB128 lengths', () => {
  // 300 => 0xAC 0x02
  const body = new Uint8Array(300).fill(0x41);
  const buf = new Uint8Array(2 + 300);
  buf[0] = 0xac;
  buf[1] = 0x02;
  buf.set(body, 2);
  expect(new BinaryReader(buf).string()).toBe('A'.repeat(300));
});

test('a read of exactly the remaining bytes succeeds; one more throws', () => {
  const r = new BinaryReader(new Uint8Array(4));
  expect(r.i32()).toBe(0);
  expect(r.remaining).toBe(0);
  expect(() => new BinaryReader(new Uint8Array(3)).i32()).toThrow(RangeError);
});

test('a string whose declared length exceeds the buffer throws', () => {
  // says 200 bytes follow, but only 2 do
  const buf = new Uint8Array([200, 1, 0x41, 0x42]);
  expect(() => new BinaryReader(buf).string()).toThrow(RangeError);
});

test('an overflowing 5-byte LEB128 length throws instead of going negative', () => {
  const buf = new Uint8Array([0x80, 0x80, 0x80, 0x80, 0x08]);
  expect(() => new BinaryReader(buf).leb()).toThrow(RangeError);
});

test('a dangling LEB128 continuation byte at EOF throws', () => {
  expect(() => new BinaryReader(new Uint8Array([0x80])).leb()).toThrow(RangeError);
});
