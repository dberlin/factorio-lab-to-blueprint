# dsp-blueprint-viewer

A local web viewer for Dyson Sphere Program blueprint strings. Paste a `BLUEPRINT:` string,
drop a `.txt` file, or give it a blueprint page URL, and it decodes the blueprint and renders
the buildings in 3D with a bill of materials and a per-building info panel.

Runs entirely on your own machine. Nothing is uploaded anywhere; the only outbound request is
the optional URL fetch, which the local server makes on the page's behalf because blueprint
sites do not send CORS headers.

## Prerequisites

- [Bun](https://bun.sh) — the only JavaScript toolchain used here. No npm/yarn/pnpm.
- [uv](https://docs.astral.sh/uv/) — runs the Python extractor and its dependencies.
- **A local Dyson Sphere Program install.** The viewer's item names, icons, recipes and
  building bounding boxes are extracted from the game's own asset bundles, not from a
  community data dump, so the game files must be present on this machine.

## Setup

```sh
bun install
bun run extract-assets "/path/to/Dyson Sphere Program"
bun run dev
```

`bun run extract-assets` **must run before `bun run dev`.** It writes `items.json`,
`recipes.json`, `models.json` and an icon atlas into `public/assets/`, which is gitignored
and therefore absent from a fresh clone. Without it the app fails to start with a
"Could not load /assets/…" error.

The path argument is the game directory containing `DSPGAME_Data/` (pointing directly at a
`DSPGAME_Data`-shaped folder also works). Omitting it falls back to a hardcoded default that
is almost certainly not your install path, so pass it explicitly.

Extraction is a one-time step: its output is cached in `public/assets/` and only needs
rerunning after a game update. Contributors without the game can still run the app from an
existing `public/assets/` directory copied from someone who has it.

## Scripts

| Script | What it does |
|---|---|
| `bun run dev` | Rsbuild dev server on <http://127.0.0.1:3000>, including the `/api/fetch` URL proxy. |
| `bun run build` | Production bundle into `dist/`. |
| `bun run serve` | Serves `dist/` plus the same `/api/fetch` proxy via Bun. Run `build` first. |
| `bun run test` | Rstest suite (`test:watch` for watch mode). |
| `bun run typecheck` | `tsc --noEmit`. |
| `bun run lint` | Biome check plus ESLint (React Hooks rules). |
| `bun run format` | Biome formatter, writing in place. |
| `bun run extract-assets` | Regenerates `public/assets/` from the game install. |

Both servers bind to `127.0.0.1`. `/api/fetch` is an unauthenticated relay to any http(s)
URL, so it is deliberately not reachable from the LAN.

## Architecture

The code is layered so that everything hard to get right can be tested without a renderer.
`src/format/` decodes the blueprint string — base64, gzip, the CSV header envelope, the MD5F
checksum and the binary building records — and `src/model/` turns that into catalog lookups,
a scene layout, a bill of materials and info-panel rows. Neither directory imports React or
three.js, and a guard test in `tests/architecture.test.ts` enforces it; that is what lets the
parser and the layout maths be covered by plain unit tests over real blueprint fixtures
instead of by rendering a canvas and squinting at it. `src/scene/` (react-three-fiber),
`src/ui/` (panels) and `src/state/` (React context, asset loading) sit on top and hold all
the framework-specific code. `src/server/proxy.ts` is shared, dependency-free, and mounted by
both the dev server and the production server so URL loading behaves identically in each.
