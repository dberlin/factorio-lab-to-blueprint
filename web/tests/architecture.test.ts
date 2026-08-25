import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { expect, test } from '@rstest/core';

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    return statSync(p).isDirectory()
      ? sources(p)
      : p.endsWith('.ts') || p.endsWith('.tsx')
        ? [p]
        : [];
  });
}

// Matches react, react-dom, three, and any @react-three/* subpath, however
// the module is reached: a static `from '...'`, a bare side-effect
// `import '...'`, a dynamic `import('...')`, or `require('...')`. Keyed on
// import/require syntax rather than the bare word, so a comment mentioning
// "three.js" or a variable named `three` does not false-positive.
// Plain template literal, not String.raw: this fragment has no escape
// sequences. The FORBIDDEN_IMPORT parts below do (\b, \s, \(), so they keep it.
const SPEC = `(?:react-dom|react|three|@react-three/[^'"]*)`;
const FORBIDDEN_IMPORT = new RegExp(
  String.raw`\bfrom\s+['"]${SPEC}['"]` +
    String.raw`|\bimport\s+['"]${SPEC}['"]` +
    String.raw`|\bimport\s*\(\s*['"]${SPEC}['"]` +
    String.raw`|\brequire\s*\(\s*['"]${SPEC}['"]`,
);

// src/server is included for a different reason than format/model: it is
// imported by rsbuild.config.ts, which is loaded outside the browser bundle
// and must stay free of any front-end dependency.
test('format/, model/ and server/ import neither React nor three.js', () => {
  const offenders: string[] = [];
  for (const dir of ['src/format', 'src/model', 'src/server']) {
    for (const file of sources(dir)) {
      const text = readFileSync(file, 'utf8');
      if (FORBIDDEN_IMPORT.test(text)) offenders.push(file);
    }
  }
  // This invariant is what lets the whole core be tested without a renderer.
  //
  // Known boundary (deliberately not covered): this greps each file's own
  // text, not the dependency graph, so a transitive import — e.g.
  // src/model/x.ts importing src/ui/y.tsx, which itself imports React —
  // slips through undetected. Closing that requires a module-graph walk;
  // deferred since the realistic violation is a direct named import.
  expect(offenders).toEqual([]);
});
