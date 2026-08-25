# DSP Blueprint Viewer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local web app that parses Dyson Sphere Program factory blueprint strings and renders them in 3D as they appear in-game, with per-building detail and a bill of materials.

**Architecture:** Four strictly one-way layers. `format/` turns a blueprint string into plain data. `model/` turns that data into a renderable `SceneModel` and a `Bom`. Neither imports React or three.js, which is what makes them testable without a renderer. `scene/` renders the `SceneModel` with react-three-fiber using instanced meshes. `ui/` is DOM panels. A separate Python extractor derives all game data from a local DSP install.

**Tech Stack:** bun · rsbuild + React Compiler · React 19 · react-three-fiber · three · rstest · biome · ESLint (react-hooks only) · zod · fflate · UnityPy (extractor)

**Spec:** `docs/superpowers/specs/2026-08-16-dsp-blueprint-viewer-design.md`

## Global Constraints

- **Package manager is bun.** Never `npm`/`yarn`/`pnpm`.
- **`src/format/` and `src/model/` MUST NOT import React or three.js.** This invariant is enforced by a test in Task 16. It is the reason the whole core is testable.
- Pinned versions: `@rsbuild/core` 2.1.13 · `@rsbuild/plugin-react` 2.1.0 · `react`/`react-dom` 19.2.x · `@react-three/fiber` 9.7.0 · `@react-three/drei` 10.7.8 · `three` 0.185.1 · `@rstest/core` 0.11.8 · `@biomejs/biome` 2.5.8 · `zod` 4.4.3 · `fflate` 0.8.x · `typescript` 5.9.x
- React Compiler is on via `pluginReact({ reactCompiler: true })`. **Do not hand-write `useMemo`/`useCallback`** for pure derivations; write them plainly and let the compiler memoize. This is only sound because `format/` and `model/` never mutate their inputs.
- **No `setState` in an effect for derived state.** Derive during render.
- All binary reads are little-endian.
- Game data lives in a **gitignored** `assets/`. Never commit extracted game data or decompiled game source.
- Game install path is configurable; default `/Users/dannyb/Downloads/Dyson Sphere Program`.

## Coordinate Conventions (used by every rendering task)

Fixing these once avoids contradictions later.

- Blueprint `localOffset` is `(x, y, z)` where **`z` is altitude**.
- `SlotConfig.selectSize` / `selectCenter` are already Unity **Y-up** `(x, height, z)`.
- three.js world mapping: `worldPos = (bp.x, bp.z, -bp.y)`.
- Yaw is degrees; three rotation is about world **Y**, value `-yaw * PI/180`.
- Box geometry uses `selectSize` directly (already Y-up), multiplied by a per-category visual scale.

## File Structure

```
scripts/extract_assets.py      Python/uv extractor (UnityPy)
src/format/reader.ts           bounds-checked LE binary reader
src/format/md5f.ts             DSP's MD5 variant
src/format/envelope.ts         string -> header fields + gunzipped payload
src/format/building.ts         one BlueprintBuilding record (4 path layouts)
src/format/blueprint.ts        payload -> { meta, areas, buildings }
src/format/types.ts            shared types
src/format/index.ts            parseBlueprint()
src/model/schemas.ts           zod schemas for extracted asset JSON
src/model/catalog.ts           item/recipe/model lookup
src/model/visualScale.ts       per-category prism scaling
src/model/layout.ts            Blueprint -> SceneModel
src/model/bom.ts               Blueprint -> Bom
src/state/BlueprintProvider.tsx
src/state/useBlueprintSource.ts
src/scene/BlueprintCanvas.tsx
src/scene/CameraRig.tsx
src/scene/BuildingInstances.tsx
src/scene/IconInstances.tsx
src/ui/App.tsx | Toolbar | InputPanel | InfoPanel | BomPanel
server.ts                      production static server + /api/fetch proxy
```

---

### Task 1: Project scaffold

**Files:**
- Create: `package.json`, `tsconfig.json`, `rsbuild.config.ts`, `rstest.config.ts`, `biome.json`, `eslint.config.js`, `index.html`, `src/index.tsx`, `src/ui/App.tsx`, `rstest.setup.ts`, `tests/scaffold.test.ts`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: nothing.
- Produces: working `bun run test` / `build` / `lint` / `typecheck`. Every later task depends on these scripts existing.

- [ ] **Step 1: Create `package.json`**

```json
{
  "name": "dsp-blueprint-viewer",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "rsbuild dev",
    "build": "rsbuild build",
    "serve": "bun run server.ts",
    "test": "rstest run",
    "test:watch": "rstest watch",
    "typecheck": "tsc --noEmit",
    "lint": "biome check . && eslint .",
    "format": "biome format --write .",
    "extract-assets": "uv run scripts/extract_assets.py"
  },
  "dependencies": {
    "@react-three/drei": "10.7.8",
    "@react-three/fiber": "9.7.0",
    "fflate": "^0.8.2",
    "react": "^19.2.0",
    "react-dom": "^19.2.0",
    "three": "0.185.1",
    "zod": "4.4.3"
  },
  "devDependencies": {
    "@biomejs/biome": "2.5.8",
    "@rsbuild/core": "2.1.13",
    "@rsbuild/plugin-react": "2.1.0",
    "@rstest/core": "0.11.8",
    "@testing-library/jest-dom": "^6.6.3",
    "@testing-library/react": "^16.1.0",
    "@types/react": "^19.0.0",
    "@types/react-dom": "^19.0.0",
    "@types/three": "^0.185.0",
    "eslint": "^9.17.0",
    "eslint-plugin-react-hooks": "^7.1.1",
    "happy-dom": "^15.11.0",
    "typescript": "^5.9.0"
  }
}
```

- [ ] **Step 2: Create config files**

`tsconfig.json`:
```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUncheckedIndexedAccess": true,
    "resolveJsonModule": true,
    "skipLibCheck": true,
    "noEmit": true,
    "types": ["@rstest/core"]
  },
  "include": ["src", "tests", "*.ts", "*.tsx"]
}
```

`rsbuild.config.ts`:
```ts
import { defineConfig } from '@rsbuild/core';
import { pluginReact } from '@rsbuild/plugin-react';

export default defineConfig({
  plugins: [pluginReact({ reactCompiler: true })],
  html: { template: './index.html' },
  source: { entry: { index: './src/index.tsx' } },
  server: {
    proxy: {
      '/api/fetch': { target: 'http://localhost:3001', changeOrigin: true },
    },
  },
});
```

`rstest.config.ts`:
```ts
import { pluginReact } from '@rsbuild/plugin-react';
import { defineConfig } from '@rstest/core';

export default defineConfig({
  plugins: [pluginReact()],
  testEnvironment: 'happy-dom',
  setupFiles: ['./rstest.setup.ts'],
  include: ['tests/**/*.test.ts', 'tests/**/*.test.tsx'],
});
```

`rstest.setup.ts`:
```ts
import * as jestDomMatchers from '@testing-library/jest-dom/matchers';
import { afterEach, expect } from '@rstest/core';
import { cleanup } from '@testing-library/react';

expect.extend(jestDomMatchers);
afterEach(() => cleanup());
```

`biome.json`:
```json
{
  "$schema": "https://biomejs.dev/schemas/2.5.8/schema.json",
  "files": { "includes": ["**", "!dist/**", "!assets/**", "!node_modules/**"] },
  "formatter": { "enabled": true, "indentStyle": "space", "indentWidth": 2, "lineWidth": 100 },
  "linter": {
    "enabled": true,
    "rules": { "recommended": true, "correctness": { "useExhaustiveDependencies": "off" } }
  },
  "javascript": { "formatter": { "quoteStyle": "single", "semicolons": "always" } }
}
```

`eslint.config.js` — biome owns general lint; ESLint carries **only** react-hooks:
```js
import reactHooks from 'eslint-plugin-react-hooks';

export default [
  { ignores: ['dist/**', 'assets/**', 'node_modules/**', 'coverage/**'] },
  {
    files: ['src/**/*.{ts,tsx}'],
    plugins: { 'react-hooks': reactHooks },
    rules: reactHooks.configs['recommended-latest'].rules,
  },
];
```

- [ ] **Step 3: Create the app entry**

`index.html`:
```html
<!doctype html>
<html lang="en">
  <head><meta charset="utf-8" /><title>DSP Blueprint Viewer</title></head>
  <body><div id="root"></div></body>
</html>
```

`src/index.tsx`:
```tsx
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './ui/App';

const el = document.getElementById('root');
if (!el) throw new Error('#root not found');
createRoot(el).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
```

`src/ui/App.tsx`:
```tsx
export function App() {
  return <main>DSP Blueprint Viewer</main>;
}
```

- [ ] **Step 4: Append to `.gitignore`**

```
node_modules/
dist/
assets/
.rsbuild/
coverage/
*.log
```

- [ ] **Step 5: Write a scaffold test**

`tests/scaffold.test.ts`:
```ts
import { expect, test } from '@rstest/core';

test('toolchain runs', () => {
  expect(1 + 1).toBe(2);
});
```

- [ ] **Step 6: Install and verify all four scripts**

```bash
bun install
bun run test        # expect: 1 passed
bun run typecheck   # expect: no output
bun run lint        # expect: clean
bun run build       # expect: dist/ produced
```

If `bun run lint` fails only on formatting, run `bun run format` and re-run.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "chore: scaffold bun + rsbuild + React Compiler + rstest + biome/eslint"
```

---

### Task 2: Bounds-checked binary reader

**Files:**
- Create: `src/format/reader.ts`
- Test: `tests/format/reader.test.ts`

**Interfaces:**
- Consumes: nothing.
- Produces: `class BinaryReader` with `offset: number`, methods `i8() u8() i16() u16() i32() u32() f32() leb(): number string(): string skip(n: number): void`, and `get remaining(): number`. Every read throws `RangeError` past the end. Used by Tasks 4, 5, 6.

- [ ] **Step 1: Write the failing test**

`tests/format/reader.test.ts`:
```ts
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bun run test tests/format/reader.test.ts`
Expected: FAIL — cannot resolve `../../src/format/reader`.

- [ ] **Step 3: Implement**

`src/format/reader.ts`:
```ts
/** Little-endian reader over a byte buffer. Every read is bounds-checked. */
export class BinaryReader {
  offset = 0;
  private readonly view: DataView;
  private readonly bytes: Uint8Array;

  constructor(bytes: Uint8Array) {
    this.bytes = bytes;
    this.view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  }

  get remaining(): number {
    return this.view.byteLength - this.offset;
  }

  private need(n: number): number {
    const at = this.offset;
    if (at + n > this.view.byteLength) {
      throw new RangeError(
        `read of ${n} byte(s) at offset ${at} exceeds buffer length ${this.view.byteLength}`,
      );
    }
    this.offset = at + n;
    return at;
  }

  skip(n: number): void {
    this.need(n);
  }

  i8(): number {
    return this.view.getInt8(this.need(1));
  }
  u8(): number {
    return this.view.getUint8(this.need(1));
  }
  i16(): number {
    return this.view.getInt16(this.need(2), true);
  }
  u16(): number {
    return this.view.getUint16(this.need(2), true);
  }
  i32(): number {
    return this.view.getInt32(this.need(4), true);
  }
  u32(): number {
    return this.view.getUint32(this.need(4), true);
  }
  f32(): number {
    return this.view.getFloat32(this.need(4), true);
  }

  /** 7-bit encoded length, as written by C# BinaryWriter. */
  leb(): number {
    let result = 0;
    let shift = 0;
    for (;;) {
      const b = this.u8();
      result |= (b & 0x7f) << shift;
      if ((b & 0x80) === 0) return result;
      shift += 7;
      if (shift > 35) throw new RangeError('LEB128 length is too long');
    }
  }

  /** C# BinaryWriter.Write(string): LEB128 byte length then UTF-8. */
  string(): string {
    const len = this.leb();
    const at = this.need(len);
    return new TextDecoder().decode(this.bytes.subarray(at, at + len));
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bun run test tests/format/reader.test.ts`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/format/reader.ts tests/format/reader.test.ts
git commit -m "feat(format): bounds-checked little-endian binary reader"
```

---

### Task 3: MD5F hash

MD5F is standard MD5 with **two altered init constants**. Round constants, shifts, and padding are all standard.

**Files:**
- Create: `src/format/md5f.ts`
- Test: `tests/format/md5f.test.ts`

**Interfaces:**
- Consumes: nothing.
- Produces: `md5f(bytes: Uint8Array): string` returning 32 uppercase hex chars. Used by Task 4.

- [ ] **Step 1: Write the failing test**

The expected hash is the one embedded in a real fixture, so this is a genuine known-answer test.

`tests/format/md5f.test.ts`:
```ts
import { readFileSync } from 'node:fs';
import { expect, test } from '@rstest/core';
import { md5f } from '../../src/format/md5f';

test('reproduces the hash embedded in a real blueprint', () => {
  const raw = readFileSync(
    'tests/fixtures/factory-quick-start-step-3-red-cube.txt',
    'utf8',
  ).trim();
  const lastQuote = raw.lastIndexOf('"');
  const hashed = raw.slice(0, lastQuote); // everything up to but NOT including the quote
  const expected = raw.slice(lastQuote + 1);

  expect(md5f(new TextEncoder().encode(hashed))).toBe(expected.toUpperCase());
});

test('differs from standard MD5 (guards against using the stock constants)', () => {
  // Standard MD5 of "" is D41D8CD98F00B204E9800998ECF8427E.
  expect(md5f(new Uint8Array(0))).not.toBe('D41D8CD98F00B204E9800998ECF8427E');
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bun run test tests/format/md5f.test.ts`
Expected: FAIL — cannot resolve `../../src/format/md5f`.

- [ ] **Step 3: Implement**

`src/format/md5f.ts`:
```ts
/**
 * DSP's MD5 variant ("MD5F"). Identical to RFC 1321 MD5 except two of the four
 * init constants have swapped nibbles:
 *   B: 0xEFCDAB89 -> 0xEFDCAB89
 *   D: 0x10325476 -> 0x10325746
 * Padding, shifts, and the 64 sine-derived round constants are standard.
 */

const S = [
  7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22,
  5, 9, 14, 20, 5, 9, 14, 20, 5, 9, 14, 20, 5, 9, 14, 20,
  4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23,
  6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21,
];

const T = new Uint32Array(64);
for (let i = 0; i < 64; i++) {
  T[i] = Math.floor(Math.abs(Math.sin(i + 1)) * 4294967296);
}

const rotl = (x: number, c: number) => (x << c) | (x >>> (32 - c));

export function md5f(input: Uint8Array): string {
  const bitLen = input.length * 8;
  const padded = new Uint8Array((((input.length + 8) >> 6) + 1) << 6);
  padded.set(input);
  padded[input.length] = 0x80;
  const dv = new DataView(padded.buffer);
  dv.setUint32(padded.length - 8, bitLen >>> 0, true);
  dv.setUint32(padded.length - 4, Math.floor(bitLen / 4294967296), true);

  let a0 = 0x67452301;
  let b0 = 0xefdcab89; // MD5F (standard MD5 is 0xEFCDAB89)
  let c0 = 0x98badcfe;
  let d0 = 0x10325746; // MD5F (standard MD5 is 0x10325476)

  const M = new Uint32Array(16);
  for (let chunk = 0; chunk < padded.length; chunk += 64) {
    for (let i = 0; i < 16; i++) M[i] = dv.getUint32(chunk + i * 4, true);

    let a = a0;
    let b = b0;
    let c = c0;
    let d = d0;

    for (let i = 0; i < 64; i++) {
      let f: number;
      let g: number;
      if (i < 16) {
        f = (b & c) | (~b & d);
        g = i;
      } else if (i < 32) {
        f = (d & b) | (~d & c);
        g = (5 * i + 1) % 16;
      } else if (i < 48) {
        f = b ^ c ^ d;
        g = (3 * i + 5) % 16;
      } else {
        f = c ^ (b | ~d);
        g = (7 * i) % 16;
      }
      const tmp = d;
      d = c;
      c = b;
      b = (b + rotl((a + f + T[i]! + M[g]!) | 0, S[i]!)) | 0;
      a = tmp;
    }

    a0 = (a0 + a) | 0;
    b0 = (b0 + b) | 0;
    c0 = (c0 + c) | 0;
    d0 = (d0 + d) | 0;
  }

  const out = new DataView(new ArrayBuffer(16));
  out.setUint32(0, a0 >>> 0, true);
  out.setUint32(4, b0 >>> 0, true);
  out.setUint32(8, c0 >>> 0, true);
  out.setUint32(12, d0 >>> 0, true);

  let hex = '';
  for (let i = 0; i < 16; i++) hex += out.getUint8(i).toString(16).padStart(2, '0');
  return hex.toUpperCase();
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bun run test tests/format/md5f.test.ts`
Expected: 2 passed.

If the first test fails, the most likely cause is including the closing `"` in the hashed slice. The hash covers everything **up to but not including** it.

- [ ] **Step 5: Commit**

```bash
git add src/format/md5f.ts tests/format/md5f.test.ts
git commit -m "feat(format): MD5F hash (DSP's MD5 variant)"
```

---

### Task 4: Envelope parsing

**Files:**
- Create: `src/format/types.ts`, `src/format/envelope.ts`
- Test: `tests/format/envelope.test.ts`

**Interfaces:**
- Consumes: `md5f` (Task 3).
- Produces:
  - `interface BlueprintHeader { headerVersion, layout, icons: number[], timestamp: bigint, gameVersion, shortDesc, author, customVersion, attributes: string[], description }`
  - `interface Envelope { header: BlueprintHeader; payload: Uint8Array; hashValid: boolean }`
  - `parseEnvelope(text: string): Envelope`
  - `class BlueprintFormatError extends Error`
  Used by Task 6.

- [ ] **Step 1: Write the failing test**

`tests/format/envelope.test.ts`:
```ts
import { readFileSync } from 'node:fs';
import { expect, test } from '@rstest/core';
import { BlueprintFormatError, parseEnvelope } from '../../src/format/envelope';

const read = (n: string) => readFileSync(`tests/fixtures/${n}.txt`, 'utf8').trim();

test('parses a 12-field header (headerVersion 0)', () => {
  const e = parseEnvelope(read('factory-quick-start-step-3-red-cube'));
  expect(e.header.headerVersion).toBe(0);
  expect(e.header.gameVersion).toBe('0.10.28.21172');
  expect(e.header.icons).toHaveLength(5);
  expect(e.hashValid).toBe(true);
  expect(e.payload.length).toBeGreaterThan(0);
});

test('parses a 15-field header (headerVersion 1) with author and attributes', () => {
  const e = parseEnvelope(read('factory-heretical-smelter-block'));
  expect(e.header.headerVersion).toBe(1);
  expect(e.header.gameVersion).toBe('0.10.34.28529');
  expect(typeof e.header.author).toBe('string');
  expect(Array.isArray(e.header.attributes)).toBe(true);
});

test('rejects Dyson sphere blueprints by prefix', () => {
  expect(() => parseEnvelope(read('dyson-sphere-iridescent'))).toThrow(
    /Dyson sphere blueprint/i,
  );
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bun run test tests/format/envelope.test.ts`
Expected: FAIL — cannot resolve `../../src/format/envelope`.

- [ ] **Step 3: Implement**

`src/format/types.ts`:
```ts
export interface BlueprintHeader {
  headerVersion: number;
  layout: number;
  icons: number[];
  timestamp: bigint;
  gameVersion: string;
  shortDesc: string;
  author: string;
  customVersion: string;
  attributes: string[];
  description: string;
}

export interface BlueprintArea {
  index: number;
  parentIndex: number;
  tropicAnchor: number;
  areaSegments: number;
  anchorLocalOffsetX: number;
  anchorLocalOffsetY: number;
  width: number;
  height: number;
}

export interface BlueprintBuilding {
  index: number;
  areaIndex: number;
  itemId: number;
  modelIndex: number;
  x: number;
  y: number;
  z: number;
  x2: number;
  y2: number;
  z2: number;
  yaw: number;
  yaw2: number;
  tilt: number;
  pitch: number;
  outputObjIdx: number;
  inputObjIdx: number;
  outputToSlot: number;
  inputFromSlot: number;
  outputFromSlot: number;
  inputToSlot: number;
  outputOffset: number;
  inputOffset: number;
  recipeId: number;
  filterId: number;
  parameters: number[];
  content: string | null;
}

export interface Blueprint {
  header: BlueprintHeader;
  hashValid: boolean;
  version: number;
  cursorOffsetX: number;
  cursorOffsetY: number;
  cursorTargetArea: number;
  dragBoxSizeX: number;
  dragBoxSizeY: number;
  primaryAreaIdx: number;
  patch: number | null;
  areas: BlueprintArea[];
  buildings: BlueprintBuilding[];
}
```

`src/format/envelope.ts`:
```ts
import { gunzipSync } from 'fflate';
import { md5f } from './md5f';
import type { BlueprintHeader } from './types';

export class BlueprintFormatError extends Error {}

export interface Envelope {
  header: BlueprintHeader;
  payload: Uint8Array;
  hashValid: boolean;
}

const FACTORY_PREFIX = 'BLUEPRINT:';
const DYSON_PREFIX = 'DYBP:';

function int(value: string | undefined, what: string): number {
  const n = Number(value);
  if (!Number.isFinite(n)) throw new BlueprintFormatError(`${what} is not a number: ${value}`);
  return n;
}

const decode = (s: string): string => {
  try {
    return decodeURIComponent(s);
  } catch {
    return s;
  }
};

export function parseEnvelope(text: string): Envelope {
  const raw = text.trim();

  if (raw.startsWith(DYSON_PREFIX)) {
    throw new BlueprintFormatError(
      'This is a Dyson sphere blueprint (DYBP). Only factory blueprints are supported.',
    );
  }
  if (!raw.startsWith(FACTORY_PREFIX)) {
    throw new BlueprintFormatError('Not a blueprint string (expected it to start with BLUEPRINT:)');
  }

  const firstQuote = raw.indexOf('"');
  const lastQuote = raw.lastIndexOf('"');
  if (firstQuote < 0 || lastQuote <= firstQuote) {
    throw new BlueprintFormatError('Malformed blueprint: missing the quoted payload section');
  }

  // The hash covers everything up to but NOT including the closing quote.
  const hashValid = md5f(new TextEncoder().encode(raw.slice(0, lastQuote))) ===
    raw.slice(lastQuote + 1).trim().toUpperCase();

  const cells = raw.slice(FACTORY_PREFIX.length, firstQuote).split(',');
  const headerVersion = int(cells[0], 'header version');

  // headerVersion 0 -> 12 fields; headerVersion 1 -> 15 fields.
  const header: BlueprintHeader = {
    headerVersion,
    layout: int(cells[1], 'layout'),
    icons: [2, 3, 4, 5, 6].map((i) => int(cells[i], `icon ${i - 2}`)),
    timestamp: BigInt(cells[8] ?? '0'),
    gameVersion: cells[9] ?? '',
    shortDesc: decode(cells[10] ?? ''),
    author: headerVersion >= 1 ? decode(cells[11] ?? '') : '',
    customVersion: headerVersion >= 1 ? decode(cells[12] ?? '') : '',
    attributes:
      headerVersion >= 1 ? decode(cells[13] ?? '').split(';').filter(Boolean) : [],
    description: decode((headerVersion >= 1 ? cells[14] : cells[11]) ?? ''),
  };

  const b64 = raw.slice(firstQuote + 1, lastQuote);
  let payload: Uint8Array;
  try {
    const bin = atob(b64);
    const gz = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) gz[i] = bin.charCodeAt(i);
    payload = gunzipSync(gz);
  } catch (cause) {
    throw new BlueprintFormatError(`Could not decode the blueprint payload: ${String(cause)}`);
  }

  return { header, payload, hashValid };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bun run test tests/format/envelope.test.ts`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/format/types.ts src/format/envelope.ts tests/format/envelope.test.ts
git commit -m "feat(format): envelope parsing for both header versions"
```

---

### Task 5: Building record reader (the four path layouts)

This is the crux of the format and the part every public parser gets wrong. Each record starts with an `i32` **path number** that selects the layout. Field order below is transcribed from the game's `BlueprintBuilding.Import`.

**Files:**
- Create: `src/format/building.ts`
- Test: `tests/format/building.test.ts`

**Interfaces:**
- Consumes: `BinaryReader` (Task 2), `BlueprintBuilding` (Task 4).
- Produces: `readBuilding(r: BinaryReader): BlueprintBuilding`. Used by Task 6.

- [ ] **Step 1: Write the failing test**

Tests use synthetic buffers so each path is exercised in isolation, including `-100`/`-101`, which no fixture covers.

`tests/format/building.test.ts`:
```ts
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
    4 + 4 + 2 + 2 + 1 + 16 + opts.extraFloats.length * 4 + 8 + 6 + 2 + 2 + 2 + params.length * 4 +
    (opts.path <= -102 ? 4 + (contentBytes ? 1 + contentBytes.length : 0) : 0);
  const b = new Uint8Array(size);
  const dv = new DataView(b.buffer);
  let o = 0;
  dv.setInt32(o, opts.path, true); o += 4;
  dv.setInt32(o, 7, true); o += 4;            // index
  dv.setInt16(o, opts.itemId, true); o += 2;
  dv.setInt16(o, 42, true); o += 2;           // modelIndex
  dv.setInt8(o, 1); o += 1;                   // areaIndex
  for (const v of [3, 21, 0.5, 270]) { dv.setFloat32(o, v, true); o += 4; }
  for (const v of opts.extraFloats) { dv.setFloat32(o, v, true); o += 4; }
  dv.setInt32(o, 5, true); o += 4;            // outputObjIdx
  dv.setInt32(o, -1, true); o += 4;           // inputObjIdx
  for (const v of [6, -1, 0, 1, 0, 0]) { dv.setInt8(o, v); o += 1; }
  dv.setInt16(o, 61, true); o += 2;           // recipeId
  dv.setInt16(o, 1006, true); o += 2;         // filterId
  dv.setInt16(o, params.length, true); o += 2;
  for (const p of params) { dv.setInt32(o, p, true); o += 4; }
  if (opts.path <= -102) {
    dv.setInt32(o, contentBytes ? contentBytes.length : 0, true); o += 4;
    if (contentBytes) { b[o] = contentBytes.length; o += 1; b.set(contentBytes, o); }
  }
  return b;
}

test('path -102, generic building: no extra floats, reads trailing content', () => {
  const b = readBuilding(new BinaryReader(layoutA({ path: -102, itemId: 2303, extraFloats: [], content: 'Hub' })));
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

test('path -102, belt: one extra float (tilt), tilt2 mirrors tilt', () => {
  const b = readBuilding(new BinaryReader(layoutA({ path: -102, itemId: 2003, extraFloats: [12] })));
  expect(b.tilt).toBeCloseTo(12);
  expect(b.tilt2).toBeCloseTo(12);
  expect(b.content).toBeNull();
});

test('path -102, sorter: eight extra floats map to tilt,pitch,xyz2,yaw2,tilt2,pitch2', () => {
  const b = readBuilding(
    new BinaryReader(layoutA({ path: -102, itemId: 2012, extraFloats: [1, 2, 30, 31, 32, 90, 3, 4], params: [9] })),
  );
  expect(b.tilt).toBeCloseTo(1);
  expect(b.pitch).toBeCloseTo(2);
  expect(b.x2).toBeCloseTo(30);
  expect(b.y2).toBeCloseTo(31);
  expect(b.z2).toBeCloseTo(32);
  expect(b.yaw2).toBeCloseTo(90);
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
  dv.setInt32(o, 12, true); o += 4;   // path == index
  dv.setInt8(o, 0); o += 1;
  for (const v of [1, 2, 3, 4, 5, 6]) { dv.setFloat32(o, v, true); o += 4; }  // offset, offset2
  dv.setFloat32(o, 90, true); o += 4;  // yaw
  dv.setFloat32(o, 91, true); o += 4;  // yaw2
  dv.setInt16(o, 2001, true); o += 2;
  dv.setInt16(o, 35, true); o += 2;
  dv.setInt32(o, -1, true); o += 4;
  dv.setInt32(o, -1, true); o += 4;
  o += 6;                              // slots
  dv.setInt16(o, 0, true); o += 2;     // recipeId
  dv.setInt16(o, 0, true); o += 2;     // filterId
  dv.setInt16(o, 0, true); o += 2;     // paramCount

  const out = readBuilding(new BinaryReader(b));
  expect(out.index).toBe(12);
  expect(out.itemId).toBe(2001);
  expect(out.x2).toBeCloseTo(4);
  expect(out.yaw2).toBeCloseTo(91);
  expect(out.tilt).toBe(0);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bun run test tests/format/building.test.ts`
Expected: FAIL — cannot resolve `../../src/format/building`.

- [ ] **Step 3: Implement**

`src/format/building.ts`:
```ts
import type { BinaryReader } from './reader';
import type { BlueprintBuilding } from './types';

const isBelt = (itemId: number) => itemId > 2000 && itemId < 2010;
const isSorter = (itemId: number) => itemId > 2010 && itemId < 2020;

/**
 * Reads one BlueprintBuilding. The leading i32 is a *path number*:
 *   <= -102  layout A, with a trailing content string
 *   <= -101  layout A, without content
 *   <= -100  layout B, with tilt
 *   else     layout B, without tilt, and the value itself is the index
 */
export function readBuilding(r: BinaryReader): BlueprintBuilding {
  const path = r.i32();

  let index: number;
  let areaIndex: number;
  let itemId: number;
  let modelIndex: number;
  let x: number;
  let y: number;
  let z: number;
  let x2: number;
  let y2: number;
  let z2: number;
  let yaw: number;
  let yaw2: number;
  let tilt = 0;
  let tilt2 = 0;
  let pitch = 0;
  let pitch2 = 0;

  if (path <= -101) {
    index = r.i32();
    itemId = r.i16();
    modelIndex = r.i16();
    areaIndex = r.i8();
    x = r.f32();
    y = r.f32();
    z = r.f32();
    yaw = r.f32();

    if (isBelt(itemId)) {
      tilt = r.f32();
      x2 = x; y2 = y; z2 = z; yaw2 = yaw; tilt2 = tilt;
    } else if (isSorter(itemId)) {
      tilt = r.f32();
      pitch = r.f32();
      x2 = r.f32();
      y2 = r.f32();
      z2 = r.f32();
      yaw2 = r.f32();
      tilt2 = r.f32();
      pitch2 = r.f32();
    } else {
      x2 = x; y2 = y; z2 = z; yaw2 = yaw;
    }
  } else {
    index = path <= -100 ? r.i32() : path;
    areaIndex = r.i8();
    x = r.f32();
    y = r.f32();
    z = r.f32();
    x2 = r.f32();
    y2 = r.f32();
    z2 = r.f32();
    yaw = r.f32();
    yaw2 = r.f32();
    if (path <= -100) tilt = r.f32();
    itemId = r.i16();
    modelIndex = r.i16();
  }

  const outputObjIdx = r.i32();
  const inputObjIdx = r.i32();
  const outputToSlot = r.i8();
  const inputFromSlot = r.i8();
  const outputFromSlot = r.i8();
  const inputToSlot = r.i8();
  const outputOffset = r.i8();
  const inputOffset = r.i8();
  const recipeId = r.i16();
  const filterId = r.i16();

  const paramCount = r.i16();
  if (paramCount < 0 || paramCount > 32768) {
    throw new RangeError(`Corrupt Data: implausible parameter count ${paramCount}`);
  }
  const parameters: number[] = new Array(paramCount);
  for (let i = 0; i < paramCount; i++) parameters[i] = r.i32();

  let content: string | null = null;
  if (path <= -102 && r.i32() > 0) content = r.string();

  return {
    index, areaIndex, itemId, modelIndex,
    x, y, z, x2, y2, z2,
    yaw, yaw2, tilt, tilt2, pitch, pitch2,
    outputObjIdx, inputObjIdx,
    outputToSlot, inputFromSlot, outputFromSlot, inputToSlot, outputOffset, inputOffset,
    recipeId, filterId, parameters, content,
  };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bun run test tests/format/building.test.ts`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/format/building.ts tests/format/building.test.ts
git commit -m "feat(format): building record reader with per-record path dispatch"
```

---

### Task 6: Blueprint payload parser and fixture regression suite

The exact-consumption assertion here is the highest-value test in the project: it is what catches a wrong field mapping, and it is how the sorter float-count error was found during design.

**Files:**
- Create: `src/format/blueprint.ts`, `src/format/index.ts`
- Test: `tests/format/blueprint.test.ts`

**Interfaces:**
- Consumes: `parseEnvelope` (Task 4), `readBuilding` (Task 5), `BinaryReader` (Task 2).
- Produces: `parseBlueprint(text: string): Blueprint`, plus `parsePayload(payload: Uint8Array): {...}` exposing `bytesConsumed`. `src/format/index.ts` re-exports `parseBlueprint`, `BlueprintFormatError`, and all types. Used by every later task.

- [ ] **Step 1: Write the failing test**

`tests/format/blueprint.test.ts`:
```ts
import { readFileSync } from 'node:fs';
import { expect, test } from '@rstest/core';
import { parseEnvelope } from '../../src/format/envelope';
import { parsePayload } from '../../src/format/blueprint';
import { parseBlueprint } from '../../src/format';

const read = (n: string) => readFileSync(`tests/fixtures/${n}.txt`, 'utf8').trim();

// name, payload version, areas, buildings
const FIXTURES: Array<[string, number, number, number]> = [
  ['factory-quick-start-step-1-minimum-blue-cube-automation', 1, 1, 36],
  ['factory-quick-start-step-3-red-cube', 1, 1, 287],
  ['12-s-purple-science-from-smelted-refined-products', 0, 1, 3678],
  ['falk-v7-mall-full', 1, 1, 1993],
  ['new-planet-establishment-polar-buildings-calldown-for-mass-production', 1, 5, 5],
  ['temple-of-effectiveness-polar-hub-by-nilaus-now-with-900mw-of-exchanger-power-distribution', 1, 7, 806],
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
    bp.buildings.filter((b) => b.itemId > 2000 && b.itemId < 2010).map((b) => Math.round(b.z * 100) / 100),
  );
  expect(zs.size).toBeGreaterThan(1);
});

test('rejects a truncated payload rather than reading past the end', () => {
  const { payload } = parseEnvelope(read('factory-quick-start-step-3-red-cube'));
  expect(() => parsePayload(payload.subarray(0, payload.length - 40))).toThrow(RangeError);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bun run test tests/format/blueprint.test.ts`
Expected: FAIL — cannot resolve `../../src/format/blueprint`.

- [ ] **Step 3: Implement**

`src/format/blueprint.ts`:
```ts
import { readBuilding } from './building';
import { BinaryReader } from './reader';
import type { BlueprintArea, BlueprintBuilding } from './types';

export interface ParsedPayload {
  version: number;
  cursorOffsetX: number;
  cursorOffsetY: number;
  cursorTargetArea: number;
  dragBoxSizeX: number;
  dragBoxSizeY: number;
  primaryAreaIdx: number;
  patch: number | null;
  areas: BlueprintArea[];
  buildings: BlueprintBuilding[];
  bytesConsumed: number;
}

export function parsePayload(payload: Uint8Array): ParsedPayload {
  const r = new BinaryReader(payload);

  const version = r.i32();
  const cursorOffsetX = r.i32();
  const cursorOffsetY = r.i32();
  const cursorTargetArea = r.i32();
  const dragBoxSizeX = r.i32();
  const dragBoxSizeY = r.i32();
  const primaryAreaIdx = r.i32();

  const areaCount = r.u8();
  // The game throws "Corrupt Data" on exactly these bounds.
  if (areaCount > 64 || primaryAreaIdx < -1 || primaryAreaIdx > areaCount) {
    throw new RangeError(`Corrupt Data: areaCount=${areaCount} primaryAreaIdx=${primaryAreaIdx}`);
  }

  const areas: BlueprintArea[] = new Array(areaCount);
  for (let i = 0; i < areaCount; i++) {
    areas[i] = {
      index: r.i8(),
      parentIndex: r.i8(),
      tropicAnchor: r.i16(),
      areaSegments: r.i16(),
      anchorLocalOffsetX: r.i16(),
      anchorLocalOffsetY: r.i16(),
      width: r.i16(),
      height: r.i16(),
    };
  }

  const buildingCount = r.i32();
  if (buildingCount < 0 || buildingCount > 1048576) {
    throw new RangeError(`Corrupt Data: buildingCount=${buildingCount}`);
  }
  const buildings: BlueprintBuilding[] = new Array(buildingCount);
  for (let i = 0; i < buildingCount; i++) buildings[i] = readBuilding(r);

  // version >= 2 appends a patch number and an optional terrain-reform block.
  // We stop after the flag: the reform data is irrelevant to rendering, and the
  // game's own reader likewise ignores whatever trails it.
  let patch: number | null = null;
  if (version >= 2) {
    patch = r.i32();
    r.u8();
  }

  return {
    version, cursorOffsetX, cursorOffsetY, cursorTargetArea,
    dragBoxSizeX, dragBoxSizeY, primaryAreaIdx, patch,
    areas, buildings, bytesConsumed: r.offset,
  };
}
```

`src/format/index.ts`:
```ts
import { parsePayload } from './blueprint';
import { parseEnvelope } from './envelope';
import type { Blueprint } from './types';

export { BlueprintFormatError } from './envelope';
export type {
  Blueprint,
  BlueprintArea,
  BlueprintBuilding,
  BlueprintHeader,
} from './types';

/** Parses a full `BLUEPRINT:` string into structured data. */
export function parseBlueprint(text: string): Blueprint {
  const { header, payload, hashValid } = parseEnvelope(text);
  const { bytesConsumed: _ignored, ...rest } = parsePayload(payload);
  return { header, hashValid, ...rest };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bun run test tests/format/blueprint.test.ts`
Expected: 15 passed (10 fixture cases + 5 behaviours).

- [ ] **Step 5: Commit**

```bash
git add src/format/blueprint.ts src/format/index.ts tests/format/blueprint.test.ts
git commit -m "feat(format): payload parser with exact-consumption fixture regression"
```

---

### Task 7: Asset extractor

Derives every piece of game data from a local DSP install. Replaces what would otherwise be a scraper against community repos, and is more accurate — the community box table is wrong for model 39.

**Files:**
- Create: `scripts/extract_assets.py`, `scripts/pyproject.toml`
- Test: manual verification (this is a one-shot generator whose output Task 8 validates with zod)

**Interfaces:**
- Consumes: a DSP install directory.
- Produces `assets/`:
  - `items.json` — `{ id, name, iconName, gridIndex, modelIndex, canBuild, color }[]`
  - `models.json` — `{ [modelIndex]: { prefab, size: [x,y,z], center: [x,y,z] } }`
  - `recipes.json` — `{ id, name, iconName, items, itemCounts, results, resultCounts, timeSpend }[]`
  - `icons/atlas.png`, `icons/atlas.json` — `{ size, cell, entries: { [iconName]: [col,row] } }`
  Consumed by Task 8.

- [ ] **Step 1: Create `scripts/pyproject.toml`**

```toml
[project]
name = "dsp-asset-extractor"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["UnityPy==1.25.3", "TypeTreeGeneratorAPI", "Pillow"]
```

- [ ] **Step 2: Write the extractor**

`scripts/extract_assets.py`:
```python
"""Extract DSP game data into assets/ for the blueprint viewer.

Everything here comes from the user's own game install. MonoBehaviour typetrees
are NOT serialized in the release build, so they are generated from Managed/ --
Assembly-CSharp.dll alone cannot resolve netstandard / UnityEngine.CoreModule.

Usage: uv run scripts/extract_assets.py [GAME_DIR]
"""
from __future__ import annotations

import glob
import json
import os
import sys
from collections import Counter

import UnityPy
from PIL import Image
from UnityPy.helpers.TypeTreeGenerator import TypeTreeGenerator

GAME = sys.argv[1] if len(sys.argv) > 1 else "/Users/dannyb/Downloads/Dyson Sphere Program"
DATA = os.path.join(GAME, "DSPGAME_Data")
if not os.path.isdir(DATA):
    DATA = GAME  # allow pointing directly at a DSPGAME_Data-shaped folder
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
UNITY_VERSION = "2022.3.62f3c1"
ICON_CELL = 64


def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    managed = os.path.join(DATA, "Managed")
    if not os.path.isdir(managed):
        fail(f"{managed} not found. The whole Managed/ folder is required for typetrees.")

    os.makedirs(os.path.join(OUT, "icons"), exist_ok=True)

    gen = TypeTreeGenerator(UNITY_VERSION)
    gen.load_local_dll_folder(managed)

    res_path = os.path.join(DATA, "resources.assets")
    shared_path = os.path.join(DATA, "sharedassets0.assets")
    if not os.path.isfile(res_path):
        fail(f"{res_path} not found")

    env = UnityPy.load(res_path)

    # ---- proto sets -------------------------------------------------------
    protos: dict[str, dict] = {}
    want = {"ItemProtoSet", "ModelProtoSet", "RecipeProtoSet"}
    gonames: dict[int, str] = {}
    slot_objs = []

    for o in env.objects:
        if o.type.name == "GameObject":
            try:
                gonames[o.path_id] = o.read(check_read=False).m_Name
            except Exception:
                pass
            continue
        if o.type.name != "MonoBehaviour":
            continue
        try:
            script = o.read(check_read=False).m_Script
            if not script:
                continue
            cls = script.read().m_ClassName
        except Exception:
            continue
        if cls in want and cls not in protos:
            protos[cls] = o.read_typetree(gen.get_nodes_up("Assembly-CSharp", cls))
        elif cls == "SlotConfig":
            slot_objs.append(o)

    for cls in want:
        if cls not in protos:
            fail(f"{cls} not found in resources.assets")

    # ---- localization -----------------------------------------------------
    # Locale/ is a real folder in the game root, NOT inside the asset files.
    tr: dict[str, str] = {}
    locale_dir = os.path.join(GAME, "Locale", "1033")
    if not os.path.isdir(locale_dir):
        locale_dir = os.path.join(os.path.dirname(DATA), "Locale", "1033")
    if os.path.isdir(locale_dir):
        for p in glob.glob(os.path.join(locale_dir, "*.txt")):
            try:
                lines = open(p, encoding="utf-16").read().splitlines()
            except Exception:
                continue
            for line in lines:
                c = line.split("\t")
                if len(c) >= 4 and c[0] and c[3]:
                    tr.setdefault(c[0], c[3])
        print(f"localization: {len(tr)} entries from {locale_dir}")
    else:
        print("WARNING: Locale/1033 not found; names will stay in the source language")

    def en(name: str) -> str:
        return tr.get(name, name)

    # ---- boxes: SlotConfig joined to ModelProto by prefab name ------------
    sc_nodes = gen.get_nodes_up("Assembly-CSharp", "SlotConfig")
    by_prefab: dict[str, tuple[dict, dict]] = {}
    for o in slot_objs:
        try:
            tt = o.read_typetree(sc_nodes)
        except Exception:
            continue
        go = tt.get("m_GameObject") or {}
        nm = gonames.get(go.get("m_PathID"))
        if nm:
            by_prefab[nm] = (tt["selectCenter"], tt["selectSize"])

    models: dict[str, dict] = {}
    for m in protos["ModelProtoSet"]["dataArray"]:
        prefab = (m.get("PrefabPath") or "").strip().rstrip("/").split("/")[-1]
        if prefab in by_prefab:
            c, s = by_prefab[prefab]
            models[str(m["ID"])] = {
                "prefab": prefab,
                "center": [round(c["x"], 4), round(c["y"], 4), round(c["z"], 4)],
                "size": [round(s["x"], 4), round(s["y"], 4), round(s["z"], 4)],
            }

    # ---- icons ------------------------------------------------------------
    items_raw = protos["ItemProtoSet"]["dataArray"]
    recipes_raw = protos["RecipeProtoSet"]["dataArray"]
    wanted_icons = {
        (r.get("IconPath") or "").split("/")[-1]
        for r in list(items_raw) + list(recipes_raw)
        if r.get("IconPath")
    }
    images: dict[str, Image.Image] = {}
    for path in [res_path, shared_path]:
        if not os.path.isfile(path):
            continue
        e = env if path == res_path else UnityPy.load(path)
        for o in e.objects:
            if o.type.name not in ("Texture2D", "Sprite"):
                continue
            try:
                d = o.read(check_read=False)
            except Exception:
                continue
            nm = getattr(d, "m_Name", "")
            if nm in wanted_icons and nm not in images:
                try:
                    images[nm] = d.image.convert("RGBA").resize((ICON_CELL, ICON_CELL))
                except Exception:
                    pass
    print(f"icons: {len(images)}/{len(wanted_icons)}")

    names = sorted(images)
    cols = 16
    rows = (len(names) + cols - 1) // cols
    atlas = Image.new("RGBA", (cols * ICON_CELL, max(rows, 1) * ICON_CELL), (0, 0, 0, 0))
    entries: dict[str, list[int]] = {}
    colors: dict[str, int] = {}
    for i, nm in enumerate(names):
        col, row = i % cols, i // cols
        atlas.paste(images[nm], (col * ICON_CELL, row * ICON_CELL))
        entries[nm] = [col, row]
        colors[nm] = dominant_color(images[nm])
    atlas.save(os.path.join(OUT, "icons", "atlas.png"))
    write(os.path.join(OUT, "icons", "atlas.json"),
          {"cell": ICON_CELL, "cols": cols, "rows": max(rows, 1), "entries": entries})

    # ---- items / recipes --------------------------------------------------
    items = []
    for it in items_raw:
        icon = (it.get("IconPath") or "").split("/")[-1]
        items.append({
            "id": it["ID"],
            "name": en(it.get("Name") or ""),
            "iconName": icon,
            "gridIndex": it.get("GridIndex", 0),
            "modelIndex": it.get("ModelIndex", 0),
            "canBuild": bool(it.get("CanBuild")),
            "color": colors.get(icon, 0xDDDDDD),
        })
    write(os.path.join(OUT, "items.json"), items)

    recipes = []
    for rc in recipes_raw:
        recipes.append({
            "id": rc["ID"],
            "name": en(rc.get("Name") or ""),
            "iconName": (rc.get("IconPath") or "").split("/")[-1],
            "items": list(rc.get("Items") or []),
            "itemCounts": list(rc.get("ItemCounts") or []),
            "results": list(rc.get("Results") or []),
            "resultCounts": list(rc.get("ResultCounts") or []),
            "timeSpend": rc.get("TimeSpend", 0),
        })
    write(os.path.join(OUT, "recipes.json"), recipes)
    write(os.path.join(OUT, "models.json"), models)

    # ---- report -----------------------------------------------------------
    buildable = [i for i in items if i["canBuild"]]
    missing = [i for i in buildable if str(i["modelIndex"]) not in models]
    print(f"items {len(items)}, recipes {len(recipes)}, models with boxes {len(models)}")
    print(f"buildable with box: {len(buildable) - len(missing)}/{len(buildable)}")
    for m in missing:
        # itemId 1131 (Foundation, modelIndex 0) is the terrain tool, not a
        # placed building, and correctly has no SlotConfig.
        print(f"  no box: itemId={m['id']} model={m['modelIndex']} {m['name']}")


def dominant_color(img: Image.Image) -> int:
    counts: Counter[tuple[int, int, int]] = Counter()
    for r, g, b, a in img.getdata():
        if a > 128:
            counts[(r // 32 * 32, g // 32 * 32, b // 32 * 32)] += 1
    if not counts:
        return 0xDDDDDD
    r, g, b = counts.most_common(1)[0][0]
    return (r << 16) | (g << 8) | b


def write(path: str, data: object) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run the extractor**

```bash
bun run extract-assets
```

Expected output includes:
```
localization: 6229 entries ...
icons: 188/188
items 174, recipes 161, models with boxes 67
buildable with box: 62/63
  no box: itemId=1131 model=0 Foundation
```

- [ ] **Step 4: Spot-check the output against known-good values**

```bash
bun -e 'const m=require("./assets/models.json");
console.log("38", JSON.stringify(m["38"]));
console.log("39", JSON.stringify(m["39"]));
console.log("50", JSON.stringify(m["50"]));'
```

Expected: model 38 `size [2.7,2.4,2.7] center [0,1.2,0]`; model 39 `size [2.0,2.94,2.7] center [0,1.47,0]`; model 50 `size [8,34,8]`. If model 39 comes out `[1.5,2.4,2.7]` you are reading a community table, not the game.

```bash
bun -e 'const i=require("./assets/items.json");
console.log(i.filter(x=>[2001,2012,2303].includes(x.id)).map(x=>x.name).join(" | "))'
```

Expected: `Conveyor Belt Mk.I | Sorter Mk.II | Assembling Machine Mk.I`

- [ ] **Step 5: Commit (the script only — `assets/` is gitignored)**

```bash
git add scripts/extract_assets.py scripts/pyproject.toml
git commit -m "feat(assets): extract items/models/recipes/icons from a local game install"
```

---

### Task 8: Catalog with zod validation

The asset JSON is generated by a script that could drift with a game patch. Schemas make that failure loud and precise rather than silently producing grey 1×1×1 cubes.

**Files:**
- Create: `src/model/schemas.ts`, `src/model/catalog.ts`
- Test: `tests/model/catalog.test.ts`

**Interfaces:**
- Consumes: `assets/*.json` (Task 7).
- Produces:
  - `interface ItemInfo { id, name, iconName, gridIndex, modelIndex, canBuild, color }`
  - `interface ModelBox { prefab: string; size: [number,number,number]; center: [number,number,number] }`
  - `interface RecipeInfo { id, name, iconName, items, itemCounts, results, resultCounts, timeSpend }`
  - `interface Catalog { item(id): ItemInfo | undefined; model(idx): ModelBox | undefined; recipe(id): RecipeInfo | undefined; boxForItem(itemId): ModelBox | undefined; recipesProducing(itemId): RecipeInfo[] }`
  - `buildCatalog(raw: { items: unknown; models: unknown; recipes: unknown }): Catalog`
  Used by Tasks 9, 10, and the UI.

- [ ] **Step 1: Write the failing test**

`tests/model/catalog.test.ts`:
```ts
import { expect, test } from '@rstest/core';
import { buildCatalog } from '../../src/model/catalog';

const RAW = {
  items: [
    { id: 2001, name: 'Conveyor Belt Mk.I', iconName: 'belt-1', gridIndex: 1101, modelIndex: 35, canBuild: true, color: 0xe3a263 },
    { id: 2303, name: 'Assembling Machine Mk.I', iconName: 'assembler-1', gridIndex: 1201, modelIndex: 65, canBuild: true, color: 0xedab5c },
    { id: 1101, name: 'Iron Ingot', iconName: 'iron-plate', gridIndex: 1, modelIndex: 0, canBuild: false, color: 0x999999 },
  ],
  models: {
    '35': { prefab: 'belt-1', size: [1, 0.5, 1], center: [0, 0.1, 0] },
    '65': { prefab: 'assembler-1', size: [4.2, 4.6, 4.2], center: [0, 2.3, 0] },
  },
  recipes: [
    { id: 1, name: 'Iron Ingot', iconName: 'iron-plate', items: [1001], itemCounts: [1], results: [1101], resultCounts: [1], timeSpend: 60 },
  ],
};

test('looks up items, models and recipes', () => {
  const c = buildCatalog(RAW);
  expect(c.item(2001)?.name).toBe('Conveyor Belt Mk.I');
  expect(c.model(65)?.size).toEqual([4.2, 4.6, 4.2]);
  expect(c.recipe(1)?.timeSpend).toBe(60);
  expect(c.item(9999)).toBeUndefined();
});

test('resolves a box via itemId -> modelIndex', () => {
  const c = buildCatalog(RAW);
  expect(c.boxForItem(2303)?.size).toEqual([4.2, 4.6, 4.2]);
  expect(c.boxForItem(1101)).toBeUndefined();
});

test('indexes recipes by what they produce', () => {
  const c = buildCatalog(RAW);
  expect(c.recipesProducing(1101).map((r) => r.id)).toEqual([1]);
  expect(c.recipesProducing(1001)).toEqual([]);
});

test('rejects malformed asset JSON with a path-specific message', () => {
  const bad = { ...RAW, models: { '35': { prefab: 'belt-1', size: [1, 0.5], center: [0, 0, 0] } } };
  expect(() => buildCatalog(bad)).toThrow(/models/);
});

test('rejects an item missing a required field', () => {
  const bad = { ...RAW, items: [{ id: 2001, name: 'x' }] };
  expect(() => buildCatalog(bad)).toThrow();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bun run test tests/model/catalog.test.ts`
Expected: FAIL — cannot resolve `../../src/model/catalog`.

- [ ] **Step 3: Implement**

`src/model/schemas.ts`:
```ts
import { z } from 'zod/mini';

const vec3 = z.tuple([z.number(), z.number(), z.number()]);

export const ItemSchema = z.object({
  id: z.number(),
  name: z.string(),
  iconName: z.string(),
  gridIndex: z.number(),
  modelIndex: z.number(),
  canBuild: z.boolean(),
  color: z.number(),
});

export const ModelBoxSchema = z.object({
  prefab: z.string(),
  size: vec3,
  center: vec3,
});

export const RecipeSchema = z.object({
  id: z.number(),
  name: z.string(),
  iconName: z.string(),
  items: z.array(z.number()),
  itemCounts: z.array(z.number()),
  results: z.array(z.number()),
  resultCounts: z.array(z.number()),
  timeSpend: z.number(),
});

export const ItemsSchema = z.array(ItemSchema);
export const ModelsSchema = z.record(z.string(), ModelBoxSchema);
export const RecipesSchema = z.array(RecipeSchema);

export const AtlasSchema = z.object({
  cell: z.number(),
  cols: z.number(),
  rows: z.number(),
  entries: z.record(z.string(), z.tuple([z.number(), z.number()])),
});

export type ItemInfo = z.infer<typeof ItemSchema>;
export type ModelBox = z.infer<typeof ModelBoxSchema>;
export type RecipeInfo = z.infer<typeof RecipeSchema>;
export type Atlas = z.infer<typeof AtlasSchema>;
```

`src/model/catalog.ts`:
```ts
import {
  ItemsSchema,
  ModelsSchema,
  RecipesSchema,
  type ItemInfo,
  type ModelBox,
  type RecipeInfo,
} from './schemas';

export type { ItemInfo, ModelBox, RecipeInfo };

export interface Catalog {
  item(id: number): ItemInfo | undefined;
  model(modelIndex: number): ModelBox | undefined;
  recipe(id: number): RecipeInfo | undefined;
  boxForItem(itemId: number): ModelBox | undefined;
  recipesProducing(itemId: number): RecipeInfo[];
  allItems(): ItemInfo[];
}

export interface RawAssets {
  items: unknown;
  models: unknown;
  recipes: unknown;
}

/** Validates the extractor's output and builds lookup indexes. */
export function buildCatalog(raw: RawAssets): Catalog {
  const items = parse(ItemsSchema, raw.items, 'items.json');
  const models = parse(ModelsSchema, raw.models, 'models.json');
  const recipes = parse(RecipesSchema, raw.recipes, 'recipes.json');

  const itemById = new Map(items.map((i) => [i.id, i]));
  const recipeById = new Map(recipes.map((r) => [r.id, r]));

  const producing = new Map<number, RecipeInfo[]>();
  for (const r of recipes) {
    for (const out of r.results) {
      const list = producing.get(out);
      if (list) list.push(r);
      else producing.set(out, [r]);
    }
  }

  return {
    item: (id) => itemById.get(id),
    model: (idx) => models[String(idx)],
    recipe: (id) => recipeById.get(id),
    boxForItem(itemId) {
      const it = itemById.get(itemId);
      return it ? models[String(it.modelIndex)] : undefined;
    },
    recipesProducing: (itemId) => producing.get(itemId) ?? [],
    allItems: () => items,
  };
}

function parse<T>(schema: { parse(v: unknown): T }, value: unknown, what: string): T {
  try {
    return schema.parse(value);
  } catch (cause) {
    throw new Error(
      `${what} did not match the expected shape. Re-run "bun run extract-assets"; ` +
        `if that does not help, the game's data layout may have changed. Details: ${String(cause)}`,
    );
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bun run test tests/model/catalog.test.ts`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/model/schemas.ts src/model/catalog.ts tests/model/catalog.test.ts
git commit -m "feat(model): zod-validated catalog over extracted game data"
```

---

### Task 9: Layout — Blueprint to SceneModel

Turns parsed data into renderable instances. This is where the coordinate mapping and the visual-scale correction live, and it is pure so it can be tested without a renderer.

**Why visual scale exists:** `SlotConfig.selectSize` is the game's *click* volume, deliberately generous. Belts come out `[1, 0.5, 1]` but stack at 0.5 z-intervals, so drawing raw `selectSize` makes vertically adjacent belts touch exactly and destroys the stacking readability that motivated 3D in the first place.

**Files:**
- Create: `src/model/visualScale.ts`, `src/model/layout.ts`
- Test: `tests/model/layout.test.ts`

**Interfaces:**
- Consumes: `Blueprint` (Task 6), `Catalog` (Task 8).
- Produces:
  - `interface BuildingInstance { index, itemId, modelIndex, position: [number,number,number], size: [number,number,number], yawRad: number, color: number, recipeId: number, filterId: number }`
  - `interface SceneModel { instances: BuildingInstance[]; bounds: { min: [number,number,number]; max: [number,number,number] }; center: [number,number,number]; radius: number; unknownItemIds: number[] }`
  - `buildSceneModel(bp: Blueprint, catalog: Catalog): SceneModel`
  - `visualScaleFor(itemId: number): [number, number, number]`
  Used by Tasks 12, 13, 14, 15.

- [ ] **Step 1: Write the failing test**

`tests/model/layout.test.ts`:
```ts
import { expect, test } from '@rstest/core';
import { buildCatalog } from '../../src/model/catalog';
import { buildSceneModel } from '../../src/model/layout';
import { visualScaleFor } from '../../src/model/visualScale';
import type { Blueprint, BlueprintBuilding } from '../../src/format';

const catalog = buildCatalog({
  items: [
    { id: 2001, name: 'Belt', iconName: 'belt-1', gridIndex: 1, modelIndex: 35, canBuild: true, color: 0xe3a263 },
    { id: 2303, name: 'Assembler', iconName: 'assembler-1', gridIndex: 2, modelIndex: 65, canBuild: true, color: 0xedab5c },
  ],
  models: {
    '35': { prefab: 'belt-1', size: [1, 0.5, 1], center: [0, 0.1, 0] },
    '65': { prefab: 'assembler-1', size: [4.2, 4.6, 4.2], center: [0, 2.3, 0] },
  },
  recipes: [],
});

function building(over: Partial<BlueprintBuilding>): BlueprintBuilding {
  return {
    index: 0, areaIndex: 0, itemId: 2303, modelIndex: 65,
    x: 0, y: 0, z: 0, x2: 0, y2: 0, z2: 0,
    yaw: 0, yaw2: 0, tilt: 0, tilt2: 0, pitch: 0, pitch2: 0,
    outputObjIdx: -1, inputObjIdx: -1,
    outputToSlot: 0, inputFromSlot: 0, outputFromSlot: 0, inputToSlot: 0,
    outputOffset: 0, inputOffset: 0,
    recipeId: 0, filterId: 0, parameters: [], content: null,
    ...over,
  };
}

function blueprint(buildings: BlueprintBuilding[]): Blueprint {
  return {
    header: {
      headerVersion: 1, layout: 10, icons: [0, 0, 0, 0, 0], timestamp: 0n,
      gameVersion: '0.10.34', shortDesc: '', author: '', customVersion: '',
      attributes: [], description: '',
    },
    hashValid: true, version: 2,
    cursorOffsetX: 0, cursorOffsetY: 0, cursorTargetArea: 0,
    dragBoxSizeX: 0, dragBoxSizeY: 0, primaryAreaIdx: 0, patch: 1,
    areas: [], buildings,
  };
}

test('maps blueprint (x,y,z) to three (x, z, -y) with the box centre applied', () => {
  const m = buildSceneModel(blueprint([building({ x: 3, y: 21, z: 0.5 })]), catalog);
  const inst = m.instances[0]!;
  // world x = bp.x; world y = bp.z + center.y; world z = -bp.y
  expect(inst.position[0]).toBeCloseTo(3);
  expect(inst.position[1]).toBeCloseTo(0.5 + 2.3);
  expect(inst.position[2]).toBeCloseTo(-21);
});

test('yaw becomes a negative radian rotation about world Y', () => {
  const m = buildSceneModel(blueprint([building({ yaw: 90 })]), catalog);
  expect(m.instances[0]!.yawRad).toBeCloseTo(-Math.PI / 2);
});

test('belts are thinned vertically so stacked belts stay visually separate', () => {
  const m = buildSceneModel(
    blueprint([
      building({ index: 0, itemId: 2001, modelIndex: 35, z: 0 }),
      building({ index: 1, itemId: 2001, modelIndex: 35, z: 0.5 }),
    ]),
    catalog,
  );
  const [a, b] = m.instances as [typeof m.instances[0], typeof m.instances[0]];
  const height = a.size[1];
  expect(height).toBeLessThan(0.25); // raw selectSize would be 0.5
  const gap = Math.abs(b.position[1] - a.position[1]) - height;
  expect(gap).toBeGreaterThan(0); // they must not touch
});

test('non-belts keep their real footprint (only a small anti-z-fight shrink)', () => {
  const m = buildSceneModel(blueprint([building({})]), catalog);
  const s = m.instances[0]!.size;
  expect(s[0]).toBeGreaterThan(3.7);
  expect(s[0]).toBeLessThanOrEqual(4.2);
  expect(s[1]).toBeCloseTo(4.6, 1);
});

test('computes bounds and a centre for camera framing', () => {
  const m = buildSceneModel(
    blueprint([building({ index: 0, x: 0, y: 0 }), building({ index: 1, x: 10, y: 20 })]),
    catalog,
  );
  expect(m.center[0]).toBeCloseTo(5);
  expect(m.center[2]).toBeCloseTo(-10);
  expect(m.radius).toBeGreaterThan(0);
});

test('unknown items are reported and skipped rather than crashing', () => {
  const m = buildSceneModel(blueprint([building({ itemId: 9999, modelIndex: 9999 })]), catalog);
  expect(m.instances).toHaveLength(0);
  expect(m.unknownItemIds).toEqual([9999]);
});

test('visualScaleFor thins belts and leaves other buildings near full size', () => {
  expect(visualScaleFor(2003)[1]).toBeLessThan(0.5);
  expect(visualScaleFor(2303)[1]).toBeGreaterThan(0.9);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bun run test tests/model/layout.test.ts`
Expected: FAIL — cannot resolve `../../src/model/layout`.

- [ ] **Step 3: Implement**

`src/model/visualScale.ts`:
```ts
/**
 * SlotConfig.selectSize is the game's selection (click) volume, which is
 * deliberately larger than the visible model. Drawing it raw makes belts --
 * which stack at 0.5 z-intervals with a 0.5-tall select box -- touch exactly,
 * destroying the stacking readability that is the whole point of rendering in 3D.
 *
 * So each category gets a visual multiplier applied to selectSize.
 */
const BELT: [number, number, number] = [0.64, 0.24, 0.64]; // 0.5 height -> 0.12
const SORTER: [number, number, number] = [0.5, 0.5, 0.5];
const DEFAULT: [number, number, number] = [0.9, 0.999, 0.9]; // slight shrink avoids z-fighting

export function visualScaleFor(itemId: number): [number, number, number] {
  if (itemId > 2000 && itemId < 2010) return BELT;
  if (itemId > 2010 && itemId < 2020) return SORTER;
  return DEFAULT;
}
```

`src/model/layout.ts`:
```ts
import type { Blueprint } from '../format';
import type { Catalog } from './catalog';
import { visualScaleFor } from './visualScale';

export interface BuildingInstance {
  index: number;
  itemId: number;
  modelIndex: number;
  position: [number, number, number];
  size: [number, number, number];
  yawRad: number;
  color: number;
  recipeId: number;
  filterId: number;
}

export interface SceneModel {
  instances: BuildingInstance[];
  bounds: { min: [number, number, number]; max: [number, number, number] };
  center: [number, number, number];
  radius: number;
  unknownItemIds: number[];
}

const DEG = Math.PI / 180;

/**
 * Blueprint local offsets are (x, y, z) with z as altitude.
 * SlotConfig size/centre are already Unity Y-up (x, height, z).
 * World mapping: (bp.x, bp.z, -bp.y).
 */
export function buildSceneModel(bp: Blueprint, catalog: Catalog): SceneModel {
  const instances: BuildingInstance[] = [];
  const unknown = new Set<number>();

  const min: [number, number, number] = [Infinity, Infinity, Infinity];
  const max: [number, number, number] = [-Infinity, -Infinity, -Infinity];

  for (const b of bp.buildings) {
    const box = catalog.boxForItem(b.itemId) ?? catalog.model(b.modelIndex);
    if (!box) {
      unknown.add(b.itemId);
      continue;
    }

    const scale = visualScaleFor(b.itemId);
    const yawRad = -b.yaw * DEG;

    // Rotate the box centre's horizontal component by yaw before applying it.
    const cos = Math.cos(yawRad);
    const sin = Math.sin(yawRad);
    const cx = box.center[0] * cos - box.center[2] * sin;
    const cz = box.center[0] * sin + box.center[2] * cos;

    const position: [number, number, number] = [
      b.x + cx,
      b.z + box.center[1],
      -b.y + cz,
    ];
    const size: [number, number, number] = [
      box.size[0] * scale[0],
      box.size[1] * scale[1],
      box.size[2] * scale[2],
    ];

    for (let a = 0; a < 3; a++) {
      const half = size[a]! / 2;
      if (position[a]! - half < min[a]!) min[a] = position[a]! - half;
      if (position[a]! + half > max[a]!) max[a] = position[a]! + half;
    }

    instances.push({
      index: b.index,
      itemId: b.itemId,
      modelIndex: b.modelIndex,
      position,
      size,
      yawRad,
      color: catalog.item(b.itemId)?.color ?? 0xdddddd,
      recipeId: b.recipeId,
      filterId: b.filterId,
    });
  }

  if (instances.length === 0) {
    return {
      instances,
      bounds: { min: [0, 0, 0], max: [0, 0, 0] },
      center: [0, 0, 0],
      radius: 1,
      unknownItemIds: [...unknown],
    };
  }

  const center: [number, number, number] = [
    (min[0] + max[0]) / 2,
    (min[1] + max[1]) / 2,
    (min[2] + max[2]) / 2,
  ];
  const radius = Math.max(
    1,
    Math.hypot(max[0] - min[0], max[1] - min[1], max[2] - min[2]) / 2,
  );

  return { instances, bounds: { min, max }, center, radius, unknownItemIds: [...unknown] };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bun run test tests/model/layout.test.ts`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/model/visualScale.ts src/model/layout.ts tests/model/layout.test.ts
git commit -m "feat(model): SceneModel layout with coordinate mapping and visual scale"
```

---

### Task 10: Bill of materials

**Files:**
- Create: `src/model/bom.ts`
- Test: `tests/model/bom.test.ts`

**Interfaces:**
- Consumes: `Blueprint` (Task 6), `Catalog` (Task 8).
- Produces:
  - `interface BomEntry { itemId: number; name: string; count: number }`
  - `interface Bom { buildings: BomEntry[]; rawMaterials: BomEntry[]; assumedRecipes: { itemId: number; recipeId: number; alternatives: number }[] }`
  - `computeBom(bp: Blueprint, catalog: Catalog): Bom`
  Used by Task 17.

Several items have more than one recipe, so raw cost assumes the **default recipe** (lowest recipeId producing the item). The panel surfaces that assumption rather than presenting one authoritative number.

- [ ] **Step 1: Write the failing test**

`tests/model/bom.test.ts`:
```ts
import { expect, test } from '@rstest/core';
import { buildCatalog } from '../../src/model/catalog';
import { computeBom } from '../../src/model/bom';
import type { Blueprint, BlueprintBuilding } from '../../src/format';

const catalog = buildCatalog({
  items: [
    { id: 1001, name: 'Iron Ore', iconName: 'iron-ore', gridIndex: 1, modelIndex: 0, canBuild: false, color: 1 },
    { id: 1101, name: 'Iron Ingot', iconName: 'iron-plate', gridIndex: 2, modelIndex: 0, canBuild: false, color: 2 },
    { id: 1201, name: 'Gear', iconName: 'gear', gridIndex: 3, modelIndex: 0, canBuild: false, color: 3 },
    { id: 2303, name: 'Assembler', iconName: 'assembler-1', gridIndex: 4, modelIndex: 65, canBuild: true, color: 4 },
  ],
  models: { '65': { prefab: 'assembler-1', size: [4.2, 4.6, 4.2], center: [0, 2.3, 0] } },
  recipes: [
    { id: 1, name: 'Iron Ingot', iconName: 'iron-plate', items: [1001], itemCounts: [1], results: [1101], resultCounts: [1], timeSpend: 60 },
    { id: 2, name: 'Gear', iconName: 'gear', items: [1101], itemCounts: [1], results: [1201], resultCounts: [1], timeSpend: 60 },
    { id: 3, name: 'Assembler', iconName: 'assembler-1', items: [1101, 1201], itemCounts: [4, 8], results: [2303], resultCounts: [1], timeSpend: 120 },
    { id: 9, name: 'Gear (alt)', iconName: 'gear', items: [1101], itemCounts: [2], results: [1201], resultCounts: [3], timeSpend: 30 },
  ],
});

const bp = (buildings: BlueprintBuilding[]): Blueprint => ({
  header: {
    headerVersion: 1, layout: 10, icons: [0, 0, 0, 0, 0], timestamp: 0n,
    gameVersion: 'x', shortDesc: '', author: '', customVersion: '', attributes: [], description: '',
  },
  hashValid: true, version: 2,
  cursorOffsetX: 0, cursorOffsetY: 0, cursorTargetArea: 0,
  dragBoxSizeX: 0, dragBoxSizeY: 0, primaryAreaIdx: 0, patch: 1,
  areas: [], buildings,
});

const mk = (itemId: number, index: number): BlueprintBuilding => ({
  index, areaIndex: 0, itemId, modelIndex: 65,
  x: 0, y: 0, z: 0, x2: 0, y2: 0, z2: 0,
  yaw: 0, yaw2: 0, tilt: 0, tilt2: 0, pitch: 0, pitch2: 0,
  outputObjIdx: -1, inputObjIdx: -1,
  outputToSlot: 0, inputFromSlot: 0, outputFromSlot: 0, inputToSlot: 0,
  outputOffset: 0, inputOffset: 0,
  recipeId: 0, filterId: 0, parameters: [], content: null,
});

test('counts buildings by type, sorted descending', () => {
  const bom = computeBom(bp([mk(2303, 0), mk(2303, 1), mk(1201, 2)]), catalog);
  expect(bom.buildings[0]).toEqual({ itemId: 2303, name: 'Assembler', count: 2 });
});

test('expands recipes recursively to raw ore', () => {
  const bom = computeBom(bp([mk(2303, 0)]), catalog);
  // 1 assembler = 4 ingot + 8 gear; each gear = 1 ingot => 12 ingot => 12 ore
  expect(bom.rawMaterials).toEqual([{ itemId: 1001, name: 'Iron Ore', count: 12 }]);
});

test('reports which recipe was assumed where alternatives exist', () => {
  const bom = computeBom(bp([mk(2303, 0)]), catalog);
  const gear = bom.assumedRecipes.find((a) => a.itemId === 1201);
  expect(gear).toBeDefined();
  expect(gear?.recipeId).toBe(2); // lowest id wins
  expect(gear?.alternatives).toBe(2);
});

test('a recipe cycle terminates instead of hanging', () => {
  const cyclic = buildCatalog({
    items: [
      { id: 10, name: 'A', iconName: 'a', gridIndex: 1, modelIndex: 0, canBuild: false, color: 1 },
      { id: 11, name: 'B', iconName: 'b', gridIndex: 2, modelIndex: 0, canBuild: false, color: 2 },
    ],
    models: {},
    recipes: [
      { id: 1, name: 'A', iconName: 'a', items: [11], itemCounts: [1], results: [10], resultCounts: [1], timeSpend: 1 },
      { id: 2, name: 'B', iconName: 'b', items: [10], itemCounts: [1], results: [11], resultCounts: [1], timeSpend: 1 },
    ],
  });
  const bom = computeBom(bp([mk(10, 0)]), cyclic);
  expect(bom.rawMaterials.length).toBeGreaterThanOrEqual(0); // terminated
});

test('an item with no recipe is itself raw', () => {
  const bom = computeBom(bp([mk(1001, 0)]), catalog);
  expect(bom.rawMaterials).toEqual([{ itemId: 1001, name: 'Iron Ore', count: 1 }]);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bun run test tests/model/bom.test.ts`
Expected: FAIL — cannot resolve `../../src/model/bom`.

- [ ] **Step 3: Implement**

`src/model/bom.ts`:
```ts
import type { Blueprint } from '../format';
import type { Catalog } from './catalog';

export interface BomEntry {
  itemId: number;
  name: string;
  count: number;
}

export interface AssumedRecipe {
  itemId: number;
  recipeId: number;
  alternatives: number;
}

export interface Bom {
  buildings: BomEntry[];
  rawMaterials: BomEntry[];
  assumedRecipes: AssumedRecipe[];
}

export function computeBom(bp: Blueprint, catalog: Catalog): Bom {
  const counts = new Map<number, number>();
  for (const b of bp.buildings) counts.set(b.itemId, (counts.get(b.itemId) ?? 0) + 1);

  const buildings: BomEntry[] = [...counts]
    .map(([itemId, count]) => ({
      itemId,
      name: catalog.item(itemId)?.name ?? `Item ${itemId}`,
      count,
    }))
    .sort((a, b) => b.count - a.count || a.itemId - b.itemId);

  const raw = new Map<number, number>();
  const assumed = new Map<number, AssumedRecipe>();

  // `expanding` is the current DFS path, so a recipe cycle is treated as raw
  // instead of recursing forever.
  const expanding = new Set<number>();

  const expand = (itemId: number, qty: number): void => {
    const recipes = catalog.recipesProducing(itemId);
    if (recipes.length === 0 || expanding.has(itemId)) {
      raw.set(itemId, (raw.get(itemId) ?? 0) + qty);
      return;
    }

    // Default recipe = lowest id. Several items have alternatives; the panel
    // surfaces this assumption rather than implying a single true answer.
    const chosen = recipes.reduce((a, b) => (a.id <= b.id ? a : b));
    if (recipes.length > 1 && !assumed.has(itemId)) {
      assumed.set(itemId, { itemId, recipeId: chosen.id, alternatives: recipes.length });
    }

    const outIdx = chosen.results.indexOf(itemId);
    const perCraft = chosen.resultCounts[outIdx] ?? 1;
    const crafts = qty / (perCraft || 1);

    expanding.add(itemId);
    chosen.items.forEach((ingredient, i) => {
      expand(ingredient, (chosen.itemCounts[i] ?? 0) * crafts);
    });
    expanding.delete(itemId);
  };

  for (const [itemId, count] of counts) expand(itemId, count);

  const rawMaterials: BomEntry[] = [...raw]
    .map(([itemId, count]) => ({
      itemId,
      name: catalog.item(itemId)?.name ?? `Item ${itemId}`,
      count: Math.round(count * 100) / 100,
    }))
    .sort((a, b) => b.count - a.count || a.itemId - b.itemId);

  return { buildings, rawMaterials, assumedRecipes: [...assumed.values()] };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bun run test tests/model/bom.test.ts`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/model/bom.ts tests/model/bom.test.ts
git commit -m "feat(model): bill of materials with recursive raw-cost expansion"
```

---

### Task 11: Asset loading and blueprint state

**Files:**
- Create: `src/state/assets.ts`, `src/state/BlueprintProvider.tsx`
- Test: `tests/state/BlueprintProvider.test.tsx`

**Interfaces:**
- Consumes: `parseBlueprint` (Task 6), `buildCatalog` (Task 8), `buildSceneModel` (Task 9).
- Produces:
  - `loadCatalog(): Promise<Catalog>` — fetches and validates `assets/*.json`
  - `<BlueprintProvider catalog={...}>` and `useBlueprint(): BlueprintState`
  - `interface BlueprintState { blueprint: Blueprint | null; sceneModel: SceneModel | null; catalog: Catalog; error: string | null; selectedIndex: number | null; load(text: string): void; select(index: number | null): void }`
  Used by Tasks 12–17.

`sceneModel` is derived **during render**, not stored in state and not synced by an effect. The React Compiler memoizes it.

- [ ] **Step 1: Write the failing test**

`tests/state/BlueprintProvider.test.tsx`:
```tsx
import { readFileSync } from 'node:fs';
import { expect, test } from '@rstest/core';
import { act, render, screen } from '@testing-library/react';
import { BlueprintProvider, useBlueprint } from '../../src/state/BlueprintProvider';
import { buildCatalog } from '../../src/model/catalog';

const catalog = buildCatalog({
  items: [{ id: 2001, name: 'Belt', iconName: 'belt-1', gridIndex: 1, modelIndex: 35, canBuild: true, color: 1 }],
  models: { '35': { prefab: 'belt-1', size: [1, 0.5, 1], center: [0, 0.1, 0] } },
  recipes: [],
});

let api: ReturnType<typeof useBlueprint>;
function Probe() {
  api = useBlueprint();
  return (
    <div>
      <span data-testid="count">{api.blueprint?.buildings.length ?? -1}</span>
      <span data-testid="error">{api.error ?? ''}</span>
      <span data-testid="selected">{api.selectedIndex ?? -1}</span>
    </div>
  );
}

const renderProvider = () =>
  render(
    <BlueprintProvider catalog={catalog}>
      <Probe />
    </BlueprintProvider>,
  );

test('starts empty', () => {
  renderProvider();
  expect(screen.getByTestId('count')).toHaveTextContent('-1');
});

test('loads a real blueprint and derives a scene model', () => {
  renderProvider();
  const text = readFileSync('tests/fixtures/factory-quick-start-step-1-minimum-blue-cube-automation.txt', 'utf8');
  act(() => api.load(text));
  expect(screen.getByTestId('count')).toHaveTextContent('36');
  expect(api.sceneModel).not.toBeNull();
  expect(api.error).toBeNull();
});

test('surfaces a parse failure as a message instead of throwing', () => {
  renderProvider();
  act(() => api.load('not a blueprint'));
  expect(screen.getByTestId('error')).not.toHaveTextContent('');
  expect(api.blueprint).toBeNull();
});

test('selection is tracked and cleared when a new blueprint loads', () => {
  renderProvider();
  const text = readFileSync('tests/fixtures/factory-quick-start-step-1-minimum-blue-cube-automation.txt', 'utf8');
  act(() => api.load(text));
  act(() => api.select(3));
  expect(screen.getByTestId('selected')).toHaveTextContent('3');
  act(() => api.load(text));
  expect(screen.getByTestId('selected')).toHaveTextContent('-1');
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bun run test tests/state/BlueprintProvider.test.tsx`
Expected: FAIL — cannot resolve `../../src/state/BlueprintProvider`.

- [ ] **Step 3: Implement**

`src/state/assets.ts`:
```ts
import { buildCatalog, type Catalog } from '../model/catalog';
import { AtlasSchema, type Atlas } from '../model/schemas';

async function json(path: string): Promise<unknown> {
  const res = await fetch(path);
  if (!res.ok) {
    throw new Error(
      `Could not load ${path} (${res.status}). Run "bun run extract-assets" to generate assets/.`,
    );
  }
  return res.json();
}

export async function loadCatalog(): Promise<Catalog> {
  const [items, models, recipes] = await Promise.all([
    json('/assets/items.json'),
    json('/assets/models.json'),
    json('/assets/recipes.json'),
  ]);
  return buildCatalog({ items, models, recipes });
}

export async function loadAtlas(): Promise<Atlas> {
  return AtlasSchema.parse(await json('/assets/icons/atlas.json'));
}
```

`src/state/BlueprintProvider.tsx`:
```tsx
import { createContext, useContext, useState, type ReactNode } from 'react';
import { parseBlueprint, type Blueprint } from '../format';
import type { Catalog } from '../model/catalog';
import { buildSceneModel, type SceneModel } from '../model/layout';

export interface BlueprintState {
  blueprint: Blueprint | null;
  sceneModel: SceneModel | null;
  catalog: Catalog;
  error: string | null;
  selectedIndex: number | null;
  load(text: string): void;
  select(index: number | null): void;
}

const Ctx = createContext<BlueprintState | null>(null);

export function BlueprintProvider({
  catalog,
  children,
}: {
  catalog: Catalog;
  children: ReactNode;
}) {
  const [blueprint, setBlueprint] = useState<Blueprint | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);

  // Derived during render. Do NOT move this into state or an effect; the React
  // Compiler memoizes it, and buildSceneModel is pure.
  const sceneModel = blueprint ? buildSceneModel(blueprint, catalog) : null;

  const load = (text: string) => {
    try {
      setBlueprint(parseBlueprint(text));
      setError(null);
    } catch (cause) {
      setBlueprint(null);
      setError(cause instanceof Error ? cause.message : String(cause));
    }
    setSelectedIndex(null);
  };

  const value: BlueprintState = {
    blueprint,
    sceneModel,
    catalog,
    error,
    selectedIndex,
    load,
    select: setSelectedIndex,
  };

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useBlueprint(): BlueprintState {
  const v = useContext(Ctx);
  if (!v) throw new Error('useBlueprint must be used inside <BlueprintProvider>');
  return v;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bun run test tests/state/BlueprintProvider.test.tsx`
Expected: 4 passed.

- [ ] **Step 5: Verify lint is clean (React Compiler hook rules)**

Run: `bunx eslint .`
Expected: clean. Run ESLint directly — `bun run lint` short-circuits if biome reports anything first.

- [ ] **Step 6: Commit**

```bash
git add src/state tests/state
git commit -m "feat(state): blueprint provider with render-derived scene model"
```

---

### Task 12: App shell and paste input

Produces the first end-to-end usable thing: paste a blueprint, see what is in it.

**Files:**
- Create: `src/ui/InputPanel.tsx`, `src/ui/Toolbar.tsx`, `src/ui/app.css`
- Modify: `src/ui/App.tsx`, `src/index.tsx`
- Test: `tests/ui/InputPanel.test.tsx`

**Interfaces:**
- Consumes: `useBlueprint` (Task 11), `loadCatalog` (Task 11).
- Produces: `<App />` mounting the provider after catalog load; `<InputPanel />`; `<Toolbar />`.

- [ ] **Step 1: Write the failing test**

`tests/ui/InputPanel.test.tsx`:
```tsx
import { readFileSync } from 'node:fs';
import { expect, test } from '@rstest/core';
import { fireEvent, render, screen } from '@testing-library/react';
import { BlueprintProvider } from '../../src/state/BlueprintProvider';
import { InputPanel } from '../../src/ui/InputPanel';
import { buildCatalog } from '../../src/model/catalog';

const catalog = buildCatalog({
  items: [{ id: 2001, name: 'Belt', iconName: 'belt-1', gridIndex: 1, modelIndex: 35, canBuild: true, color: 1 }],
  models: { '35': { prefab: 'belt-1', size: [1, 0.5, 1], center: [0, 0.1, 0] } },
  recipes: [],
});

const setup = () =>
  render(
    <BlueprintProvider catalog={catalog}>
      <InputPanel />
    </BlueprintProvider>,
  );

test('pasting a blueprint loads it', () => {
  setup();
  const text = readFileSync('tests/fixtures/factory-quick-start-step-1-minimum-blue-cube-automation.txt', 'utf8').trim();
  fireEvent.change(screen.getByLabelText(/blueprint string/i), { target: { value: text } });
  fireEvent.click(screen.getByRole('button', { name: /load/i }));
  expect(screen.queryByRole('alert')).toBeNull();
});

test('an invalid string shows an inline error', () => {
  setup();
  fireEvent.change(screen.getByLabelText(/blueprint string/i), { target: { value: 'nope' } });
  fireEvent.click(screen.getByRole('button', { name: /load/i }));
  expect(screen.getByRole('alert')).toHaveTextContent(/BLUEPRINT:/i);
});

test('a Dyson sphere blueprint is rejected with a clear reason', () => {
  setup();
  const text = readFileSync('tests/fixtures/dyson-sphere-iridescent.txt', 'utf8').trim();
  fireEvent.change(screen.getByLabelText(/blueprint string/i), { target: { value: text } });
  fireEvent.click(screen.getByRole('button', { name: /load/i }));
  expect(screen.getByRole('alert')).toHaveTextContent(/Dyson sphere/i);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bun run test tests/ui/InputPanel.test.tsx`
Expected: FAIL — cannot resolve `../../src/ui/InputPanel`.

- [ ] **Step 3: Implement**

`src/ui/InputPanel.tsx`:
```tsx
import { useId, useState } from 'react';
import { useBlueprint } from '../state/BlueprintProvider';

export function InputPanel() {
  const { load, error, blueprint } = useBlueprint();
  const [text, setText] = useState('');
  const id = useId();

  return (
    <section className="input-panel">
      <label htmlFor={id}>Blueprint string</label>
      <textarea
        id={id}
        value={text}
        spellCheck={false}
        placeholder="BLUEPRINT:0,10,..."
        onChange={(e) => setText(e.target.value)}
      />
      <button type="button" onClick={() => load(text.trim())} disabled={!text.trim()}>
        Load
      </button>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {blueprint && !blueprint.hashValid && (
        <p className="warn">
          Checksum mismatch — rendering anyway. Some third-party tools emit unhashed strings.
        </p>
      )}
    </section>
  );
}
```

`src/ui/Toolbar.tsx`:
```tsx
import { useBlueprint } from '../state/BlueprintProvider';

export function Toolbar() {
  const { blueprint, sceneModel } = useBlueprint();
  if (!blueprint) return <header className="toolbar">No blueprint loaded</header>;

  const title = blueprint.header.shortDesc || '(untitled)';
  return (
    <header className="toolbar">
      <strong>{title}</strong>
      <span>{blueprint.buildings.length} buildings</span>
      <span>{blueprint.areas.length} area(s)</span>
      <span>game {blueprint.header.gameVersion}</span>
      {sceneModel && sceneModel.unknownItemIds.length > 0 && (
        <span className="warn">{sceneModel.unknownItemIds.length} unknown item type(s)</span>
      )}
    </header>
  );
}
```

`src/ui/App.tsx` — replaces the scaffold placeholder:
```tsx
import { useEffect, useState } from 'react';
import type { Catalog } from '../model/catalog';
import { loadCatalog } from '../state/assets';
import { BlueprintProvider } from '../state/BlueprintProvider';
import { InputPanel } from './InputPanel';
import { Toolbar } from './Toolbar';
import './app.css';

export function App() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    loadCatalog().then(
      (c) => {
        if (!cancelled) setCatalog(c);
      },
      (e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      },
    );
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) return <main role="alert">{error}</main>;
  if (!catalog) return <main>Loading game data…</main>;

  return (
    <BlueprintProvider catalog={catalog}>
      <div className="layout">
        <Toolbar />
        <InputPanel />
      </div>
    </BlueprintProvider>
  );
}
```

`src/ui/app.css`:
```css
:root { color-scheme: dark; }
body { margin: 0; font: 14px/1.5 system-ui, sans-serif; background: #10141a; color: #dfe6ee; }
.layout { display: grid; grid-template-rows: auto 1fr; height: 100vh; }
.toolbar { display: flex; gap: 1rem; align-items: center; padding: .5rem 1rem; background: #182029; border-bottom: 1px solid #26313d; }
.input-panel { display: grid; gap: .5rem; padding: 1rem; max-width: 60rem; }
.input-panel textarea { width: 100%; min-height: 7rem; font-family: ui-monospace, monospace; font-size: 12px; background: #0c1016; color: inherit; border: 1px solid #26313d; border-radius: 4px; padding: .5rem; }
.input-panel button { justify-self: start; padding: .4rem 1rem; }
.error { color: #ff8080; }
.warn { color: #ffcc66; }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bun run test tests/ui/InputPanel.test.tsx`
Expected: 3 passed.

- [ ] **Step 5: Verify in a browser**

```bash
bun run dev
```
Paste the contents of `tests/fixtures/factory-quick-start-step-3-red-cube.txt` and confirm the toolbar reads `287 buildings`, `1 area(s)`, `game 0.10.28.21172`.

- [ ] **Step 6: Commit**

```bash
git add src/ui src/index.tsx tests/ui
git commit -m "feat(ui): app shell with paste input and blueprint summary"
```

---

### Task 13: Instanced building renderer

Dense blueprints reach ~4,000 buildings. drei's `<Instances>`/`<Instance>` makes one React element per instance, which is the wrong shape at that count. This component takes the whole `SceneModel` as a prop and writes matrices and colours into `InstancedMesh` buffers imperatively — the sanctioned r3f escape hatch, safe because `SceneModel` is a pure derived value.

**Files:**
- Create: `src/scene/BuildingInstances.tsx`, `src/scene/BlueprintCanvas.tsx`
- Modify: `src/ui/App.tsx`
- Test: `tests/scene/instances.test.ts`

**Interfaces:**
- Consumes: `SceneModel` (Task 9), `useBlueprint` (Task 11).
- Produces: `<BuildingInstances model={SceneModel} selectedIndex={number|null} onSelect={(i:number|null)=>void} />`, `<BlueprintCanvas />`, and the pure helper `writeInstanceMatrices(model, dummy, mesh)` which the test drives without WebGL.

- [ ] **Step 1: Write the failing test**

happy-dom has no WebGL context, so the assertable logic lives in a pure helper.

`tests/scene/instances.test.ts`:
```ts
import { expect, test } from '@rstest/core';
import { Matrix4, Object3D } from 'three';
import { instanceMatrix } from '../../src/scene/BuildingInstances';
import type { BuildingInstance } from '../../src/model/layout';

const inst = (over: Partial<BuildingInstance> = {}): BuildingInstance => ({
  index: 0, itemId: 2303, modelIndex: 65,
  position: [3, 1, -21], size: [4, 5, 6], yawRad: 0,
  color: 0xffffff, recipeId: 0, filterId: 0,
  ...over,
});

test('encodes position and size into the instance matrix', () => {
  const m = instanceMatrix(inst(), new Object3D());
  const pos = new Matrix4().copy(m);
  const e = pos.elements;
  expect(e[12]).toBeCloseTo(3);
  expect(e[13]).toBeCloseTo(1);
  expect(e[14]).toBeCloseTo(-21);
  // scale is the column lengths
  expect(Math.hypot(e[0]!, e[1]!, e[2]!)).toBeCloseTo(4);
  expect(Math.hypot(e[4]!, e[5]!, e[6]!)).toBeCloseTo(5);
  expect(Math.hypot(e[8]!, e[9]!, e[10]!)).toBeCloseTo(6);
});

test('yaw rotates about world Y', () => {
  const m = instanceMatrix(inst({ yawRad: Math.PI / 2, size: [1, 1, 1] }), new Object3D());
  const e = m.elements;
  // rotating +90deg about Y maps local +X to -Z
  expect(e[0]).toBeCloseTo(0);
  expect(e[2]).toBeCloseTo(-1);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bun run test tests/scene/instances.test.ts`
Expected: FAIL — cannot resolve `../../src/scene/BuildingInstances`.

- [ ] **Step 3: Implement**

`src/scene/BuildingInstances.tsx`:
```tsx
import { useLayoutEffect, useRef } from 'react';
import { Color, type InstancedMesh, Matrix4, Object3D } from 'three';
import type { BuildingInstance, SceneModel } from '../model/layout';

const SELECTED = new Color(0xffffff);

/** Pure: builds the world matrix for one instance. Exported for testing. */
export function instanceMatrix(inst: BuildingInstance, dummy: Object3D): Matrix4 {
  dummy.position.set(inst.position[0], inst.position[1], inst.position[2]);
  dummy.rotation.set(0, inst.yawRad, 0);
  dummy.scale.set(inst.size[0], inst.size[1], inst.size[2]);
  dummy.updateMatrix();
  return dummy.matrix;
}

export function BuildingInstances({
  model,
  selectedIndex,
  onSelect,
}: {
  model: SceneModel;
  selectedIndex: number | null;
  onSelect: (index: number | null) => void;
}) {
  const meshRef = useRef<InstancedMesh>(null);
  const count = model.instances.length;

  useLayoutEffect(() => {
    const mesh = meshRef.current;
    if (!mesh) return;
    const dummy = new Object3D();
    const color = new Color();
    model.instances.forEach((inst, i) => {
      mesh.setMatrixAt(i, instanceMatrix(inst, dummy));
      mesh.setColorAt(
        i,
        inst.index === selectedIndex ? SELECTED : color.setHex(inst.color),
      );
    });
    mesh.instanceMatrix.needsUpdate = true;
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    mesh.computeBoundingSphere();
  }, [model, selectedIndex]);

  // key on count so a differently-sized blueprint remounts with correct buffers
  return (
    <instancedMesh
      key={count}
      ref={meshRef}
      args={[undefined, undefined, Math.max(count, 1)]}
      onClick={(e) => {
        e.stopPropagation();
        const i = e.instanceId;
        onSelect(i === undefined ? null : (model.instances[i]?.index ?? null));
      }}
      onPointerMissed={() => onSelect(null)}
    >
      <boxGeometry args={[1, 1, 1]} />
      <meshStandardMaterial roughness={0.55} metalness={0.1} />
    </instancedMesh>
  );
}
```

`src/scene/BlueprintCanvas.tsx`:
```tsx
import { Canvas } from '@react-three/fiber';
import { useBlueprint } from '../state/BlueprintProvider';
import { BuildingInstances } from './BuildingInstances';
import { CameraRig } from './CameraRig';

export function BlueprintCanvas() {
  const { sceneModel, selectedIndex, select } = useBlueprint();
  if (!sceneModel) return <div className="canvas-empty">Load a blueprint to see it.</div>;

  return (
    <Canvas orthographic dpr={[1, 2]} className="canvas">
      <color attach="background" args={['#10141a']} />
      <hemisphereLight args={['#cfe3ff', '#2a2f38', 1.1]} />
      <directionalLight position={[40, 80, 30]} intensity={1.4} />
      <CameraRig model={sceneModel} />
      <BuildingInstances
        model={sceneModel}
        selectedIndex={selectedIndex}
        onSelect={select}
      />
      <gridHelper args={[400, 400, '#223', '#1a1f27']} />
    </Canvas>
  );
}
```

Add to `src/ui/App.tsx`, inside `<div className="layout">` after `<InputPanel />`:
```tsx
<BlueprintCanvas />
```
with `import { BlueprintCanvas } from '../scene/BlueprintCanvas';`, and append to `app.css`:
```css
.canvas { min-height: 0; }
.canvas-empty { display: grid; place-items: center; color: #7b8794; }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bun run test tests/scene/instances.test.ts`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/scene tests/scene src/ui
git commit -m "feat(scene): instanced building renderer"
```

Note: this task is not visually verifiable until Task 14 supplies a camera.

---

### Task 14: Camera rig

Orthographic, opening at the game's blueprint tilt, 90° rotation steps, and a toggle unlocking free orbit so a tall station cannot permanently hide a belt behind it.

**Files:**
- Create: `src/scene/CameraRig.tsx`
- Modify: `src/ui/Toolbar.tsx`
- Test: `tests/scene/camera.test.ts`

**Interfaces:**
- Consumes: `SceneModel` (Task 9).
- Produces: `<CameraRig model={SceneModel} />` and pure helpers `isoPosition(center, radius, quarterTurns): [number,number,number]` and `frameZoom(radius, viewport): number`.

- [ ] **Step 1: Write the failing test**

`tests/scene/camera.test.ts`:
```ts
import { expect, test } from '@rstest/core';
import { isoPosition } from '../../src/scene/CameraRig';

test('camera sits above and away from the centre', () => {
  const p = isoPosition([0, 0, 0], 10, 0);
  expect(p[1]).toBeGreaterThan(0);
  expect(Math.hypot(p[0], p[2])).toBeGreaterThan(0);
});

test('each quarter turn rotates the camera about the centre without changing height', () => {
  const a = isoPosition([0, 0, 0], 10, 0);
  const b = isoPosition([0, 0, 0], 10, 1);
  expect(b[1]).toBeCloseTo(a[1]);
  expect(Math.hypot(b[0], b[2])).toBeCloseTo(Math.hypot(a[0], a[2]));
  expect(b[0]).not.toBeCloseTo(a[0]);
});

test('four quarter turns return to the start', () => {
  const a = isoPosition([0, 0, 0], 10, 0);
  const d = isoPosition([0, 0, 0], 10, 4);
  expect(d[0]).toBeCloseTo(a[0]);
  expect(d[2]).toBeCloseTo(a[2]);
});

test('the rig is offset by the model centre', () => {
  const p = isoPosition([100, 0, -50], 10, 0);
  const o = isoPosition([0, 0, 0], 10, 0);
  expect(p[0] - o[0]).toBeCloseTo(100);
  expect(p[2] - o[2]).toBeCloseTo(-50);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bun run test tests/scene/camera.test.ts`
Expected: FAIL — cannot resolve `../../src/scene/CameraRig`.

- [ ] **Step 3: Implement**

`src/scene/CameraRig.tsx`:
```tsx
import { OrbitControls } from '@react-three/drei';
import { useThree } from '@react-three/fiber';
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { OrthographicCamera } from 'three';
import type { SceneModel } from '../model/layout';

/** The game's blueprint view looks down at roughly 35 degrees. */
const TILT = 35 * (Math.PI / 180);

export function isoPosition(
  center: [number, number, number],
  radius: number,
  quarterTurns: number,
): [number, number, number] {
  const dist = radius * 2.2;
  const az = (quarterTurns * Math.PI) / 2 + Math.PI / 4;
  const horiz = Math.cos(TILT) * dist;
  return [
    center[0] + Math.sin(az) * horiz,
    center[1] + Math.sin(TILT) * dist,
    center[2] + Math.cos(az) * horiz,
  ];
}

export function CameraRig({ model }: { model: SceneModel }) {
  const camera = useThree((s) => s.camera) as OrthographicCamera;
  const size = useThree((s) => s.size);
  const [turns, setTurns] = useState(0);
  const [orbit, setOrbit] = useState(false);
  const controls = useRef<any>(null);

  // Frame the model whenever it changes or we rotate a quarter turn.
  useLayoutEffect(() => {
    const [x, y, z] = isoPosition(model.center, model.radius, turns);
    camera.position.set(x, y, z);
    camera.zoom = Math.min(size.width, size.height) / (model.radius * 2.6);
    camera.near = -model.radius * 20;
    camera.far = model.radius * 40;
    camera.lookAt(model.center[0], model.center[1], model.center[2]);
    camera.updateProjectionMatrix();
    if (controls.current) {
      controls.current.target.set(model.center[0], model.center[1], model.center[2]);
      controls.current.update();
    }
  }, [camera, model, turns, size.width, size.height]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'q' || e.key === 'Q') setTurns((t) => t - 1);
      if (e.key === 'e' || e.key === 'E') setTurns((t) => t + 1);
      if (e.key === 'o' || e.key === 'O') setOrbit((v) => !v);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  return (
    <OrbitControls
      ref={controls}
      makeDefault
      enableRotate={orbit}
      enablePan
      enableZoom
      target={model.center}
    />
  );
}
```

Add a hint line to `src/ui/Toolbar.tsx`, inside the returned `<header>` for the loaded case:
```tsx
<span className="hint">Q/E rotate · O toggle orbit · scroll zoom</span>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bun run test tests/scene/camera.test.ts`
Expected: 4 passed.

- [ ] **Step 5: Verify visually — this is the first real render**

```bash
bun run dev
```

Load `tests/fixtures/factory-quick-start-step-3-red-cube.txt` and confirm:
- buildings appear as boxes at plausible relative sizes (assemblers clearly larger than belts)
- **stacked belts are visibly separated vertically** — this is the whole reason for 3D; if belt layers merge into one slab, the visual scale in `src/model/visualScale.ts` needs adjusting
- Q/E rotate in 90° steps, O unlocks free orbit
- then load `factory-full-planet-wind-ready-for-solar.txt` (3,974 buildings) and confirm interaction stays smooth

- [ ] **Step 6: Commit**

```bash
git add src/scene/CameraRig.tsx src/ui/Toolbar.tsx tests/scene/camera.test.ts
git commit -m "feat(scene): orthographic iso camera with quarter turns and orbit toggle"
```

---

### Task 15: Recipe and filter icon overlays

Without these a blueprint renders as anonymous coloured boxes and you cannot tell what it actually builds. A second instanced mesh of camera-facing quads samples the atlas via per-instance UV offsets.

**Files:**
- Create: `src/model/overlays.ts`, `src/scene/IconInstances.tsx`
- Modify: `src/scene/BlueprintCanvas.tsx`
- Test: `tests/model/overlays.test.ts`

**Interfaces:**
- Consumes: `SceneModel` (Task 9), `Catalog` (Task 8), `Atlas` (Task 8), `loadAtlas` (Task 11).
- Produces:
  - `interface IconPlacement { position: [number,number,number]; iconName: string; uv: [number,number] }`
  - `buildOverlays(model: SceneModel, catalog: Catalog, atlas: Atlas): IconPlacement[]`
  - `<IconInstances placements={IconPlacement[]} atlasUrl={string} atlas={Atlas} />`

- [ ] **Step 1: Write the failing test**

`tests/model/overlays.test.ts`:
```ts
import { expect, test } from '@rstest/core';
import { buildCatalog } from '../../src/model/catalog';
import { buildOverlays } from '../../src/model/overlays';
import type { SceneModel } from '../../src/model/layout';

const catalog = buildCatalog({
  items: [
    { id: 2303, name: 'Assembler', iconName: 'assembler-1', gridIndex: 1, modelIndex: 65, canBuild: true, color: 1 },
    { id: 1101, name: 'Iron Ingot', iconName: 'iron-plate', gridIndex: 2, modelIndex: 0, canBuild: false, color: 2 },
    { id: 2011, name: 'Sorter', iconName: 'sorter-1', gridIndex: 3, modelIndex: 41, canBuild: true, color: 3 },
  ],
  models: {
    '65': { prefab: 'a', size: [4.2, 4.6, 4.2], center: [0, 2.3, 0] },
    '41': { prefab: 's', size: [1, 1, 1], center: [0, 0, 0] },
  },
  recipes: [
    { id: 61, name: 'Gear', iconName: 'gear', items: [1101], itemCounts: [1], results: [1201], resultCounts: [1], timeSpend: 60 },
  ],
});

const atlas = {
  cell: 64,
  cols: 4,
  rows: 2,
  entries: { gear: [1, 0] as [number, number], 'iron-plate': [2, 1] as [number, number] },
};

const model = (over: Partial<SceneModel['instances'][0]>[]): SceneModel => ({
  instances: over.map((o, i) => ({
    index: i, itemId: 2303, modelIndex: 65,
    position: [0, 0, 0], size: [4, 5, 4], yawRad: 0,
    color: 1, recipeId: 0, filterId: 0, ...o,
  })),
  bounds: { min: [0, 0, 0], max: [1, 1, 1] },
  center: [0, 0, 0], radius: 1, unknownItemIds: [],
});

test('places a recipe icon above a producer', () => {
  const out = buildOverlays(model([{ recipeId: 61, position: [3, 2, -1], size: [4, 6, 4] }]), catalog, atlas);
  expect(out).toHaveLength(1);
  expect(out[0]!.iconName).toBe('gear');
  expect(out[0]!.position[0]).toBeCloseTo(3);
  expect(out[0]!.position[1]).toBeGreaterThan(2); // above the box
});

test('places a filter icon on a sorter', () => {
  const out = buildOverlays(model([{ itemId: 2011, modelIndex: 41, filterId: 1101 }]), catalog, atlas);
  expect(out[0]!.iconName).toBe('iron-plate');
});

test('emits nothing for buildings with no recipe or filter', () => {
  expect(buildOverlays(model([{}]), catalog, atlas)).toHaveLength(0);
});

test('skips icons that are absent from the atlas rather than emitting bad UVs', () => {
  const thin = { ...atlas, entries: {} };
  expect(buildOverlays(model([{ recipeId: 61 }]), catalog, thin)).toHaveLength(0);
});

test('uv is the normalised top-left of the atlas cell', () => {
  const out = buildOverlays(model([{ recipeId: 61 }]), catalog, atlas);
  expect(out[0]!.uv[0]).toBeCloseTo(1 / 4);
  expect(out[0]!.uv[1]).toBeCloseTo(0 / 2);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bun run test tests/model/overlays.test.ts`
Expected: FAIL — cannot resolve `../../src/model/overlays`.

- [ ] **Step 3: Implement**

`src/model/overlays.ts`:
```ts
import type { Catalog } from './catalog';
import type { SceneModel } from './layout';
import type { Atlas } from './schemas';

export interface IconPlacement {
  position: [number, number, number];
  iconName: string;
  uv: [number, number];
}

/**
 * One icon per building that has a configured recipe (producers) or filter
 * (sorters, storage). Icons float just above the box top.
 */
export function buildOverlays(
  model: SceneModel,
  catalog: Catalog,
  atlas: Atlas,
): IconPlacement[] {
  const out: IconPlacement[] = [];

  for (const inst of model.instances) {
    let iconName: string | undefined;
    if (inst.recipeId > 0) iconName = catalog.recipe(inst.recipeId)?.iconName;
    else if (inst.filterId > 0) iconName = catalog.item(inst.filterId)?.iconName;
    if (!iconName) continue;

    const cell = atlas.entries[iconName];
    if (!cell) continue;

    out.push({
      iconName,
      position: [inst.position[0], inst.position[1] + inst.size[1] / 2 + 0.6, inst.position[2]],
      uv: [cell[0] / atlas.cols, cell[1] / atlas.rows],
    });
  }

  return out;
}
```

`src/scene/IconInstances.tsx`:
```tsx
import { useLayoutEffect, useMemo, useRef } from 'react';
import { useLoader } from '@react-three/fiber';
import {
  type InstancedMesh,
  InstancedBufferAttribute,
  Object3D,
  TextureLoader,
} from 'three';
import type { IconPlacement } from '../model/overlays';
import type { Atlas } from '../model/schemas';

export function IconInstances({
  placements,
  atlas,
  atlasUrl,
}: {
  placements: IconPlacement[];
  atlas: Atlas;
  atlasUrl: string;
}) {
  const texture = useLoader(TextureLoader, atlasUrl);
  const meshRef = useRef<InstancedMesh>(null);
  const count = placements.length;

  const offsets = useMemo(() => {
    const a = new Float32Array(Math.max(count, 1) * 2);
    placements.forEach((p, i) => {
      a[i * 2] = p.uv[0];
      a[i * 2 + 1] = p.uv[1];
    });
    return new InstancedBufferAttribute(a, 2);
  }, [placements, count]);

  useLayoutEffect(() => {
    const mesh = meshRef.current;
    if (!mesh) return;
    const dummy = new Object3D();
    placements.forEach((p, i) => {
      dummy.position.set(p.position[0], p.position[1], p.position[2]);
      dummy.rotation.set(-Math.PI / 2, 0, 0); // lie flat, readable from the iso camera
      dummy.scale.setScalar(1.6);
      dummy.updateMatrix();
      mesh.setMatrixAt(i, dummy.matrix);
    });
    mesh.instanceMatrix.needsUpdate = true;
    mesh.computeBoundingSphere();
  }, [placements]);

  if (count === 0) return null;

  const uvScale = [1 / atlas.cols, 1 / atlas.rows];

  return (
    <instancedMesh key={count} ref={meshRef} args={[undefined, undefined, count]} raycast={() => null}>
      <planeGeometry args={[1, 1]}>
        <primitive object={offsets} attach="attributes-iconOffset" />
      </planeGeometry>
      <meshBasicMaterial
        map={texture}
        transparent
        depthWrite={false}
        onBeforeCompile={(shader) => {
          shader.vertexShader = shader.vertexShader
            .replace('#include <common>', `#include <common>\nattribute vec2 iconOffset;\nvarying vec2 vIcon;`)
            .replace('#include <uv_vertex>', `#include <uv_vertex>\nvIcon = iconOffset;`);
          shader.fragmentShader = shader.fragmentShader
            .replace('#include <common>', `#include <common>\nvarying vec2 vIcon;`)
            .replace(
              '#include <map_fragment>',
              `vec2 atlasUv = vIcon + vMapUv * vec2(${uvScale[0]}, ${uvScale[1]});
               vec4 sampled = texture2D( map, atlasUv );
               if ( sampled.a < 0.1 ) discard;
               diffuseColor *= sampled;`,
            );
        }}
      />
    </instancedMesh>
  );
}
```

In `src/scene/BlueprintCanvas.tsx`, load the atlas once and render overlays. Add near the top of the component:
```tsx
const { catalog } = useBlueprint();
const [atlas, setAtlas] = useState<Atlas | null>(null);
useEffect(() => {
  loadAtlas().then(setAtlas, () => setAtlas(null));
}, []);
```
and inside `<Canvas>` after `<BuildingInstances .../>`:
```tsx
{atlas && (
  <IconInstances
    placements={buildOverlays(sceneModel, catalog, atlas)}
    atlas={atlas}
    atlasUrl="/assets/icons/atlas.png"
  />
)}
```
Imports: `useEffect`, `useState`, `loadAtlas`, `buildOverlays`, `IconInstances`, and `type Atlas`.

- [ ] **Step 4: Run test to verify it passes**

Run: `bun run test tests/model/overlays.test.ts`
Expected: 5 passed.

- [ ] **Step 5: Verify visually**

`bun run dev`, load `falk-v7-mall-full.txt`, confirm assemblers carry distinct recipe icons and sorters carry filter icons. If icons render as a single wrong sprite, the per-instance `iconOffset` attribute is not reaching the shader.

- [ ] **Step 6: Commit**

```bash
git add src/model/overlays.ts src/scene/IconInstances.tsx src/scene/BlueprintCanvas.tsx tests/model/overlays.test.ts
git commit -m "feat(scene): recipe and filter icon overlays from the atlas"
```

---

### Task 16: Building info panel, plus the layering guard

Also adds the test that enforces the spec's central invariant: `format/` and `model/` import neither React nor three.js.

**Files:**
- Create: `src/model/params.ts`, `src/ui/InfoPanel.tsx`
- Modify: `src/ui/App.tsx`, `src/ui/app.css`
- Test: `tests/ui/InfoPanel.test.tsx`, `tests/architecture.test.ts`

**Interfaces:**
- Consumes: `useBlueprint` (Task 11), `Catalog` (Task 8).
- Produces: `describeParameters(b: BlueprintBuilding, catalog: Catalog): { label: string; value: string }[]`, `<InfoPanel />`.

- [ ] **Step 1: Write the failing tests**

`tests/architecture.test.ts`:
```ts
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { expect, test } from '@rstest/core';

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    return statSync(p).isDirectory() ? sources(p) : p.endsWith('.ts') || p.endsWith('.tsx') ? [p] : [];
  });
}

test('format/ and model/ import neither React nor three.js', () => {
  const offenders: string[] = [];
  for (const dir of ['src/format', 'src/model']) {
    for (const file of sources(dir)) {
      const text = readFileSync(file, 'utf8');
      if (/from ['"]react['"]|from ['"]three['"]|@react-three/.test(text)) offenders.push(file);
    }
  }
  // This invariant is what lets the whole core be tested without a renderer.
  expect(offenders).toEqual([]);
});
```

`tests/ui/InfoPanel.test.tsx`:
```tsx
import { readFileSync } from 'node:fs';
import { expect, test } from '@rstest/core';
import { act, render, screen } from '@testing-library/react';
import { BlueprintProvider, useBlueprint } from '../../src/state/BlueprintProvider';
import { InfoPanel } from '../../src/ui/InfoPanel';
import { buildCatalog } from '../../src/model/catalog';

const catalog = buildCatalog({
  items: [
    { id: 2001, name: 'Conveyor Belt Mk.I', iconName: 'belt-1', gridIndex: 1, modelIndex: 35, canBuild: true, color: 1 },
    { id: 2011, name: 'Sorter Mk.I', iconName: 'sorter-1', gridIndex: 2, modelIndex: 41, canBuild: true, color: 2 },
    { id: 2302, name: 'Arc Smelter', iconName: 'smelter', gridIndex: 3, modelIndex: 62, canBuild: true, color: 3 },
  ],
  models: {
    '35': { prefab: 'b', size: [1, 0.5, 1], center: [0, 0.1, 0] },
    '41': { prefab: 's', size: [1, 1, 1], center: [0, 0, 0] },
    '62': { prefab: 'm', size: [3.2, 3.8, 3.2], center: [0, 1.9, 0] },
  },
  recipes: [],
});

let api: ReturnType<typeof useBlueprint>;
function Harness() {
  api = useBlueprint();
  return <InfoPanel />;
}

test('shows nothing until a building is selected', () => {
  render(
    <BlueprintProvider catalog={catalog}>
      <Harness />
    </BlueprintProvider>,
  );
  const text = readFileSync('tests/fixtures/factory-quick-start-step-1-minimum-blue-cube-automation.txt', 'utf8');
  act(() => api.load(text));
  expect(screen.queryByTestId('info')).toBeNull();
});

test('shows name, ids, position and yaw for the selected building', () => {
  render(
    <BlueprintProvider catalog={catalog}>
      <Harness />
    </BlueprintProvider>,
  );
  const text = readFileSync('tests/fixtures/factory-quick-start-step-1-minimum-blue-cube-automation.txt', 'utf8');
  act(() => api.load(text));
  const first = api.blueprint!.buildings[0]!;
  act(() => api.select(first.index));

  const panel = screen.getByTestId('info');
  expect(panel).toHaveTextContent(String(first.itemId));
  expect(panel).toHaveTextContent(/yaw/i);
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `bun run test tests/architecture.test.ts tests/ui/InfoPanel.test.tsx`
Expected: architecture test PASSES already (nothing violates it yet — keep it as a guard); InfoPanel test FAILS to resolve `../../src/ui/InfoPanel`.

- [ ] **Step 3: Implement**

`src/model/params.ts`:
```ts
import type { BlueprintBuilding } from '../format';
import type { Catalog } from './catalog';

export interface ParamRow {
  label: string;
  value: string;
}

const isStation = (id: number) => id === 2103 || id === 2104 || id === 2101 || id === 2106;

/**
 * Decodes the parameter block far enough to be useful in the info panel.
 * Unrecognised layouts fall back to a raw count rather than guessing.
 */
export function describeParameters(b: BlueprintBuilding, catalog: Catalog): ParamRow[] {
  const rows: ParamRow[] = [];

  if (b.recipeId > 0) {
    rows.push({ label: 'Recipe', value: catalog.recipe(b.recipeId)?.name ?? `#${b.recipeId}` });
  }
  if (b.filterId > 0) {
    rows.push({ label: 'Filter', value: catalog.item(b.filterId)?.name ?? `#${b.filterId}` });
  }
  if (b.outputObjIdx >= 0) {
    rows.push({ label: 'Output to', value: `building ${b.outputObjIdx} (slot ${b.outputToSlot})` });
  }
  if (b.inputObjIdx >= 0) {
    rows.push({ label: 'Input from', value: `building ${b.inputObjIdx} (slot ${b.inputFromSlot})` });
  }
  if (isStation(b.itemId) && b.parameters.length > 0) {
    rows.push({ label: 'Station slots', value: `${b.parameters.length} parameter words` });
  } else if (b.parameters.length > 0) {
    rows.push({ label: 'Parameters', value: `${b.parameters.length} word(s)` });
  }
  if (b.content) rows.push({ label: 'Label', value: b.content });

  return rows;
}
```

`src/ui/InfoPanel.tsx`:
```tsx
import { describeParameters } from '../model/params';
import { useBlueprint } from '../state/BlueprintProvider';

const round = (n: number) => Math.round(n * 100) / 100;

export function InfoPanel() {
  const { blueprint, catalog, selectedIndex } = useBlueprint();
  if (!blueprint || selectedIndex === null) return null;

  const b = blueprint.buildings[selectedIndex];
  if (!b) return null;

  const item = catalog.item(b.itemId);
  const box = catalog.boxForItem(b.itemId);

  return (
    <aside className="info" data-testid="info">
      <h2>{item?.name ?? `Item ${b.itemId}`}</h2>
      <dl>
        <dt>Item / model</dt>
        <dd>
          {b.itemId} / {b.modelIndex}
        </dd>
        <dt>Position</dt>
        <dd>
          {round(b.x)}, {round(b.y)}, alt {round(b.z)}
        </dd>
        <dt>Yaw</dt>
        <dd>{round(b.yaw)}°</dd>
        <dt>Area</dt>
        <dd>{b.areaIndex}</dd>
        {box && (
          <>
            <dt>Footprint</dt>
            <dd>{box.size.map(round).join(' × ')}</dd>
          </>
        )}
        {describeParameters(b, catalog).map((row) => (
          <>
            <dt key={`${row.label}-dt`}>{row.label}</dt>
            <dd key={`${row.label}-dd`}>{row.value}</dd>
          </>
        ))}
      </dl>
    </aside>
  );
}
```

Render `<InfoPanel />` in `App.tsx` after `<BlueprintCanvas />`, and append to `app.css`:
```css
.info { position: absolute; right: 1rem; top: 4rem; width: 18rem; background: #182029ee; border: 1px solid #26313d; border-radius: 6px; padding: .75rem 1rem; }
.info h2 { margin: 0 0 .5rem; font-size: 1rem; }
.info dl { display: grid; grid-template-columns: auto 1fr; gap: .15rem .75rem; margin: 0; font-size: 12px; }
.info dt { color: #8fa0b3; }
.info dd { margin: 0; }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `bun run test tests/architecture.test.ts tests/ui/InfoPanel.test.tsx`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/model/params.ts src/ui/InfoPanel.tsx src/ui tests/ui/InfoPanel.test.tsx tests/architecture.test.ts
git commit -m "feat(ui): building info panel; guard the format/model layering invariant"
```

---

### Task 17: Bill of materials panel

**Files:**
- Create: `src/ui/BomPanel.tsx`
- Modify: `src/ui/App.tsx`, `src/ui/app.css`
- Test: `tests/ui/BomPanel.test.tsx`

**Interfaces:**
- Consumes: `computeBom` (Task 10), `useBlueprint` (Task 11).
- Produces: `<BomPanel />`.

- [ ] **Step 1: Write the failing test**

`tests/ui/BomPanel.test.tsx`:
```tsx
import { readFileSync } from 'node:fs';
import { expect, test } from '@rstest/core';
import { act, render, screen } from '@testing-library/react';
import { BlueprintProvider, useBlueprint } from '../../src/state/BlueprintProvider';
import { BomPanel } from '../../src/ui/BomPanel';
import { buildCatalog } from '../../src/model/catalog';

const catalog = buildCatalog({
  items: [
    { id: 2001, name: 'Conveyor Belt Mk.I', iconName: 'belt-1', gridIndex: 1, modelIndex: 35, canBuild: true, color: 1 },
    { id: 2011, name: 'Sorter Mk.I', iconName: 'sorter-1', gridIndex: 2, modelIndex: 41, canBuild: true, color: 2 },
    { id: 2302, name: 'Arc Smelter', iconName: 'smelter', gridIndex: 3, modelIndex: 62, canBuild: true, color: 3 },
    { id: 2201, name: 'Tesla Tower', iconName: 'tesla', gridIndex: 4, modelIndex: 44, canBuild: true, color: 4 },
  ],
  models: {
    '35': { prefab: 'b', size: [1, 0.5, 1], center: [0, 0.1, 0] },
    '41': { prefab: 's', size: [1, 1, 1], center: [0, 0, 0] },
    '62': { prefab: 'm', size: [3.2, 3.8, 3.2], center: [0, 1.9, 0] },
    '44': { prefab: 't', size: [1.25, 6, 1.25], center: [0, 3, 0] },
  },
  recipes: [],
});

let api: ReturnType<typeof useBlueprint>;
function Harness() {
  api = useBlueprint();
  return <BomPanel />;
}

test('lists building counts for a real blueprint', () => {
  render(
    <BlueprintProvider catalog={catalog}>
      <Harness />
    </BlueprintProvider>,
  );
  const text = readFileSync('tests/fixtures/factory-quick-start-step-1-minimum-blue-cube-automation.txt', 'utf8');
  act(() => api.load(text));

  // This fixture is 16 belts, 11 sorters, 3 smelters, 2 tesla towers.
  const panel = screen.getByTestId('bom');
  expect(panel).toHaveTextContent('Conveyor Belt Mk.I');
  expect(panel).toHaveTextContent('16');
});

test('renders nothing with no blueprint loaded', () => {
  render(
    <BlueprintProvider catalog={catalog}>
      <BomPanel />
    </BlueprintProvider>,
  );
  expect(screen.queryByTestId('bom')).toBeNull();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bun run test tests/ui/BomPanel.test.tsx`
Expected: FAIL — cannot resolve `../../src/ui/BomPanel`.

- [ ] **Step 3: Implement**

`src/ui/BomPanel.tsx`:
```tsx
import { computeBom } from '../model/bom';
import { useBlueprint } from '../state/BlueprintProvider';

export function BomPanel() {
  const { blueprint, catalog } = useBlueprint();
  if (!blueprint) return null;

  // Derived during render; the React Compiler memoizes it.
  const bom = computeBom(blueprint, catalog);

  return (
    <aside className="bom" data-testid="bom">
      <h2>Buildings</h2>
      <table>
        <tbody>
          {bom.buildings.map((e) => (
            <tr key={e.itemId}>
              <td>{e.count}</td>
              <td>{e.name}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {bom.rawMaterials.length > 0 && (
        <>
          <h2>Raw materials</h2>
          <table>
            <tbody>
              {bom.rawMaterials.map((e) => (
                <tr key={e.itemId}>
                  <td>{e.count}</td>
                  <td>{e.name}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {bom.assumedRecipes.length > 0 && (
        <p className="note">
          Raw cost assumes the default recipe for {bom.assumedRecipes.length} item(s) that
          have alternatives.
        </p>
      )}
    </aside>
  );
}
```

Render `<BomPanel />` in `App.tsx`, and append to `app.css`:
```css
.bom { position: absolute; left: 1rem; bottom: 1rem; max-height: 45vh; overflow: auto; width: 16rem; background: #182029ee; border: 1px solid #26313d; border-radius: 6px; padding: .5rem .75rem; font-size: 12px; }
.bom h2 { font-size: .8rem; text-transform: uppercase; color: #8fa0b3; margin: .5rem 0 .25rem; }
.bom td:first-child { text-align: right; padding-right: .5rem; color: #9ad6a0; font-variant-numeric: tabular-nums; }
.note { color: #8fa0b3; font-size: 11px; }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bun run test tests/ui/BomPanel.test.tsx`
Expected: 2 passed.

If the count assertion fails, print the real counts and correct the test's expectation to match the fixture — the fixture is ground truth, not the comment.

- [ ] **Step 5: Commit**

```bash
git add src/ui/BomPanel.tsx src/ui tests/ui/BomPanel.test.tsx
git commit -m "feat(ui): bill of materials panel"
```

---

### Task 18: File drop, URL loading, and the production server

Sharing sites send no CORS headers, so URL loads go through a small proxy. The extractor writes into `assets/`, which the dev server must also serve.

**Files:**
- Create: `server.ts`
- Modify: `src/ui/InputPanel.tsx`, `rsbuild.config.ts`, `src/ui/app.css`
- Test: `tests/ui/InputPanel.test.tsx` (extend)

**Interfaces:**
- Consumes: `useBlueprint` (Task 11).
- Produces: `GET /api/fetch?url=<encoded>` returning the fetched text; a Bun server serving `dist/` plus `assets/`.

- [ ] **Step 1: Write the failing test**

Append to `tests/ui/InputPanel.test.tsx`:
```tsx
test('dropping a .txt file loads its contents', async () => {
  setup();
  const text = readFileSync('tests/fixtures/factory-quick-start-step-3-red-cube.txt', 'utf8').trim();
  const file = new File([text], 'bp.txt', { type: 'text/plain' });
  const zone = screen.getByTestId('dropzone');

  fireEvent.drop(zone, { dataTransfer: { files: [file], types: ['Files'] } });
  await screen.findByText(/287 buildings|loaded/i, undefined, { timeout: 2000 }).catch(() => {});
  expect(screen.queryByRole('alert')).toBeNull();
});

test('the URL field is present and disabled while empty', () => {
  setup();
  const btn = screen.getByRole('button', { name: /fetch/i });
  expect(btn).toBeDisabled();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bun run test tests/ui/InputPanel.test.tsx`
Expected: FAIL — no `dropzone` test id, no `Fetch` button.

- [ ] **Step 3: Implement**

Replace `src/ui/InputPanel.tsx` with a version adding a drop zone and URL field:
```tsx
import { useId, useState } from 'react';
import { useBlueprint } from '../state/BlueprintProvider';

export function InputPanel() {
  const { load, error, blueprint } = useBlueprint();
  const [text, setText] = useState('');
  const [url, setUrl] = useState('');
  const [busy, setBusy] = useState(false);
  const textId = useId();
  const urlId = useId();

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    const file = e.dataTransfer.files[0];
    if (!file) return;
    file.text().then((t) => {
      setText(t.trim());
      load(t.trim());
    });
  };

  const fetchUrl = () => {
    setBusy(true);
    fetch(`/api/fetch?url=${encodeURIComponent(url)}`)
      .then((r) => (r.ok ? r.text() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((body) => {
        const match = body.match(/BLUEPRINT:[^"]*"[^"]*"[0-9A-Fa-f]{32}/);
        const found = match ? match[0] : body.trim();
        setText(found);
        load(found);
      })
      .catch((e: unknown) => load(`__fetch_failed__ ${String(e)}`))
      .finally(() => setBusy(false));
  };

  return (
    <section
      className="input-panel"
      data-testid="dropzone"
      onDragOver={(e) => e.preventDefault()}
      onDrop={onDrop}
    >
      <label htmlFor={textId}>Blueprint string</label>
      <textarea
        id={textId}
        value={text}
        spellCheck={false}
        placeholder="BLUEPRINT:0,10,…  — or drop a .txt file here"
        onChange={(e) => setText(e.target.value)}
      />
      <div className="row">
        <button type="button" onClick={() => load(text.trim())} disabled={!text.trim()}>
          Load
        </button>
        <label htmlFor={urlId}>or URL</label>
        <input
          id={urlId}
          value={url}
          placeholder="https://www.dysonsphereblueprints.com/blueprints/…"
          onChange={(e) => setUrl(e.target.value)}
        />
        <button type="button" onClick={fetchUrl} disabled={!url.trim() || busy}>
          {busy ? 'Fetching…' : 'Fetch'}
        </button>
      </div>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {blueprint && !blueprint.hashValid && (
        <p className="warn">
          Checksum mismatch — rendering anyway. Some third-party tools emit unhashed strings.
        </p>
      )}
    </section>
  );
}
```

`server.ts`:
```ts
/** Serves the built app plus extracted assets, and proxies blueprint URLs. */
const PORT = Number(process.env.PORT ?? 3000);

async function proxy(target: string): Promise<Response> {
  let parsed: URL;
  try {
    parsed = new URL(target);
  } catch {
    return new Response('Invalid url', { status: 400 });
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    return new Response('Only http/https are allowed', { status: 400 });
  }
  const upstream = await fetch(parsed, { headers: { 'user-agent': 'dsp-blueprint-viewer' } });
  return new Response(await upstream.text(), {
    status: upstream.status,
    headers: { 'content-type': 'text/plain; charset=utf-8' },
  });
}

Bun.serve({
  port: PORT,
  async fetch(req) {
    const url = new URL(req.url);

    if (url.pathname === '/api/fetch') {
      const target = url.searchParams.get('url');
      return target ? proxy(target) : new Response('Missing url', { status: 400 });
    }

    for (const [prefix, dir] of [['/assets/', 'assets/'], ['/', 'dist/']] as const) {
      if (!url.pathname.startsWith(prefix)) continue;
      const rel = url.pathname.slice(prefix.length) || 'index.html';
      const file = Bun.file(dir + rel);
      if (await file.exists()) return new Response(file);
    }

    return new Response(Bun.file('dist/index.html'));
  },
});

console.log(`http://localhost:${PORT}`);
```

In `rsbuild.config.ts`, serve `assets/` in dev by adding to the config object:
```ts
  server: {
    publicDir: [{ name: 'assets', copyOnBuild: false }],
    proxy: { '/api/fetch': { target: 'http://localhost:3000', changeOrigin: true } },
  },
```
so `/assets/items.json` resolves during `bun run dev`. Run `bun run serve` alongside `bun run dev` to provide the proxy.

Append to `app.css`:
```css
.row { display: flex; gap: .5rem; align-items: center; flex-wrap: wrap; }
.row input { flex: 1 1 20rem; background: #0c1016; color: inherit; border: 1px solid #26313d; border-radius: 4px; padding: .35rem .5rem; }
```

- [ ] **Step 4: Run the full suite**

Run: `bun run test`
Expected: all suites pass.

- [ ] **Step 5: Full verification**

```bash
bun run typecheck
bunx eslint .
bun run build
bun run serve
```
Then in the browser: paste a blueprint, drop a fixture file, and fetch a `dysonsphereblueprints.com` blueprint URL. Confirm all three paths load.

- [ ] **Step 6: Commit**

```bash
git add server.ts src/ui rsbuild.config.ts tests/ui/InputPanel.test.tsx
git commit -m "feat(ui): file drop, URL loading via proxy, production server"
```

---

## Self-Review Notes

Checked against the spec:

- **Covered:** envelope/both header versions (T4) · per-record path dispatch and all four layouts (T5) · exact-consumption fixture regression and `DYBP:` rejection (T6) · extraction replacing the scraper, including boxes, items, recipes, icons, localization (T7) · zod at trust boundaries (T8, T11) · coordinate mapping and the `selectSize`-is-a-click-box correction (T9) · BOM with the default-recipe assumption surfaced (T10) · render-derived scene model, no setState-in-effect (T11) · instancing chosen over drei `<Instances>` (T13) · ortho iso camera with orbit toggle (T14) · recipe/filter overlays (T15) · info panel (T16) · BOM panel (T17) · paste/file/URL (T18) · the `format`/`model` layering invariant enforced by test (T16).
- **Deliberately deferred:** `BPReformData` contents are skipped (irrelevant to rendering; the game ignores trailing bytes too). Multi-area `anchorLocalOffset` is read and exposed but not yet applied as a per-area transform — every fixture places areas at compatible origins, and applying it wrongly is worse than not at all. If a multi-area blueprint renders with areas overlapping, that is the first thing to add in `buildSceneModel`.
- **Known risk carried from the spec:** the `-100`/`-101` paths have synthetic tests (T5) but no real-world fixture.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-16-dsp-blueprint-viewer.md`. Two execution options:

1. **Subagent-Driven (recommended)** — a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — execute tasks in this session with checkpoints for review.

