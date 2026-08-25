import { readdirSync, readFileSync } from 'node:fs';
import { expect, test } from '@rstest/core';
import { md5f } from '../../src/format/md5f';

test('reproduces the embedded hash of every committed fixture', () => {
  const files = readdirSync('tests/fixtures').filter((f) => f.endsWith('.txt'));
  expect(files.length).toBeGreaterThanOrEqual(11);

  const mismatches: Array<{ name: string; expected: string; got: string }> = [];

  for (const name of files) {
    const raw = readFileSync(`tests/fixtures/${name}`, 'utf8').trim();
    const lastQuote = raw.lastIndexOf('"');
    const hashed = raw.slice(0, lastQuote);
    const expected = raw.slice(lastQuote + 1).toUpperCase();

    const result = md5f(new TextEncoder().encode(hashed));
    if (result !== expected) {
      mismatches.push({ name, expected, got: result });
    }
  }

  if (mismatches.length > 0) {
    const details = mismatches
      .map((m) => `  ${m.name}: expected ${m.expected}, got ${m.got}`)
      .join('\n');
    throw new Error(`${mismatches.length} fixture(s) failed:\n${details}`);
  }
});

test('differs from standard MD5 (guards against using the stock constants)', () => {
  // Standard MD5 of "" is D41D8CD98F00B204E9800998ECF8427E.
  expect(md5f(new Uint8Array(0))).not.toBe('D41D8CD98F00B204E9800998ECF8427E');
});
