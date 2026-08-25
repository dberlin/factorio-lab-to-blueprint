import { readFileSync } from 'node:fs';
import { expect, test } from '@rstest/core';
import { decodeHtmlEntities, findBlueprintString, parseBlueprint } from '../../src/format';

/**
 * tests/fixtures/page-heretical-smelter-block.html is the real `<textarea>`
 * region served by dysonsphereblueprints.com for
 * /blueprints/factory-heretical-smelter-block, saved verbatim -- so the quotes
 * that delimit the gzip payload are `&quot;`, exactly as the live site sends
 * them. The matching unescaped string is the .txt fixture next to it.
 */
const page = readFileSync('tests/fixtures/page-heretical-smelter-block.html', 'utf8');
const plain = readFileSync('tests/fixtures/factory-heretical-smelter-block.txt', 'utf8').trim();

test('the saved page really is escaped, so this fixture tests what it claims to', () => {
  expect(page).toContain('<textarea');
  expect(page).toContain('&quot;');
  // The whole point: no literal quote delimiters anywhere in the served markup.
  expect(/BLUEPRINT:[^"]*"[^"]*"[0-9A-Fa-f]{32}/.test(page)).toBe(false);
});

test('extracts the blueprint from an HTML page that escapes the quotes', () => {
  const found = findBlueprintString(page);
  expect(found).not.toBeNull();
  // Byte-identical to the unescaped fixture: nothing added, dropped or mangled,
  // and the surrounding <textarea> markup is not swept up.
  expect(found).toBe(plain);
});

test('the string recovered from the escaped page still parses with a valid checksum', () => {
  const bp = parseBlueprint(findBlueprintString(page)!);
  expect(bp.hashValid).toBe(true);
  expect(bp.buildings).toHaveLength(591);
  expect(bp.header.gameVersion).toBe('0.10.34.28529');
  expect(bp.header.shortDesc).toBe('Heretical smelter');
});

test('a plain-text body with literal quotes still extracts, byte for byte', () => {
  expect(findBlueprintString(plain)).toBe(plain);
  expect(findBlueprintString(`leading noise\n${plain}\ntrailing noise`)).toBe(plain);
});

test('a page with no blueprint yields null', () => {
  expect(findBlueprintString('<html><body><p>nothing here</p></body></html>')).toBeNull();
  expect(findBlueprintString('')).toBeNull();
  // A BLUEPRINT: prefix without the quote-delimited payload is not a match.
  expect(findBlueprintString('BLUEPRINT:1,10,2319 but truncated')).toBeNull();
});

// `&amp;quot;` is the escaping of the literal text `&quot;`. Decoding `&amp;`
// in its own sweep -- before or after the others -- collapses it to a real
// quote and would split a blueprint string at the wrong offset.
test('&amp;quot; decodes to the text &quot;, not to a quote character', () => {
  expect(decodeHtmlEntities('a&amp;quot;b')).toBe('a&quot;b');
  expect(decodeHtmlEntities('a&amp;quot;b')).not.toContain('"');
  expect(decodeHtmlEntities('&amp;amp;')).toBe('&amp;');
});

test('a spurious &amp;quot; near the payload does not truncate the match', () => {
  const found = findBlueprintString(page.replace('<textarea', '<p>&amp;quot;</p><textarea'));
  expect(found).toBe(plain);
});

test('decodes the named entities a serialiser actually emits', () => {
  expect(decodeHtmlEntities('&quot;&amp;&lt;&gt;&apos;')).toBe('"&<>\'');
  expect(decodeHtmlEntities('&QUOT;')).toBe('"');
});

test('decodes decimal and hexadecimal numeric entities', () => {
  expect(decodeHtmlEntities('&#34;&#39;')).toBe('"\'');
  expect(decodeHtmlEntities('&#x22;&#X27;')).toBe('"\'');
  expect(decodeHtmlEntities('&#128640;')).toBe('\u{1f680}');
});

// Silently dropping an unrecognised entity could delete bytes from a payload.
test('unknown and out-of-range entities are left verbatim', () => {
  expect(decodeHtmlEntities('&notanentity;')).toBe('&notanentity;');
  expect(decodeHtmlEntities('&#1114112;')).toBe('&#1114112;');
  expect(decodeHtmlEntities('a & b')).toBe('a & b');
});

test('extraction takes the first blueprint when a page lists several', () => {
  const second = plain.replace('Heretical%20smelter', 'Second%20one');
  expect(findBlueprintString(`${plain}\n${second}`)).toBe(plain);
});
