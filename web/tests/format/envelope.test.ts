import { readFileSync } from 'node:fs';
import { expect, test } from '@rstest/core';
import { BlueprintFormatError, parseEnvelope } from '../../src/format/envelope';

const read = (n: string) => readFileSync(`tests/fixtures/${n}.txt`, 'utf8').trim();

test('parses a 12-field header (headerVersion 0)', () => {
  const e = parseEnvelope(read('factory-quick-start-step-3-red-cube'));
  expect(e.header.headerVersion).toBe(0);
  expect(e.header.gameVersion).toBe('0.10.28.21172');
  expect(e.header.icons).toEqual([603, 2308, 1114, 6002, 0]);
  expect(e.header.shortDesc).toBe('QuickStart-Step3-Oil-RedCube');
  expect(e.hashValid).toBe(true);
  expect(e.payload.length).toBeGreaterThan(0);
});

test('parses a 15-field header (headerVersion 1) with author and attributes', () => {
  const e = parseEnvelope(read('factory-heretical-smelter-block'));
  expect(e.header.headerVersion).toBe(1);
  expect(e.header.gameVersion).toBe('0.10.34.28529');
  expect(e.header.author).toBe('Thagusta');
  expect(e.header.customVersion).toBe('1');
  expect(e.header.attributes).toEqual([]);
  expect(e.header.description).toBe(
    "Very heretical design that minimizes number of belts and sorters used. The building block is not perfect yet as it doesn't seem to paste near the equator. The belts need to be in east-west orientation.\n\nProduces: 600/s iron ingots\nConsumes: 600/s iron ore, 8/s proliferator\nPower: 720.5 MW",
  );
});

test('rejects Dyson sphere blueprints by prefix', () => {
  expect(() => parseEnvelope(read('dyson-sphere-iridescent'))).toThrow(/Dyson sphere blueprint/i);
});

test('rejects a non-blueprint string', () => {
  expect(() => parseEnvelope('hello world')).toThrow(BlueprintFormatError);
});

test('a corrupted hash is reported, not thrown', () => {
  const raw = read('factory-quick-start-step-3-red-cube');
  const broken = `${raw.slice(0, raw.lastIndexOf('"') + 1)}${'0'.repeat(32)}`;
  const e = parseEnvelope(broken);
  expect(e.hashValid).toBe(false);
  expect(e.payload.length).toBeGreaterThan(0);
});

test('a non-numeric timestamp throws BlueprintFormatError, not a raw SyntaxError', () => {
  const bad =
    'BLUEPRINT:0,40,603,2308,1114,6002,0,0,notanumber,0.10.28.21172,QuickStart,desc"AAAA"HASH';
  expect(() => parseEnvelope(bad)).toThrow(BlueprintFormatError);
});
