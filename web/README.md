# flab2bp web interface

The React and three.js front end for `flab2bp`. It submits FactorioLab URLs to the Python
solver, reports build progress, and renders the resulting Dyson Sphere Program blueprint.

The solver is not implemented in TypeScript. Development therefore requires both the Python
API and the Rsbuild development server; `bun run dev` starts and supervises both.

## Prerequisites

- [Bun](https://bun.sh) — the only JavaScript toolchain used here. No npm/yarn/pnpm.
- [uv](https://docs.astral.sh/uv/) — runs the Python extractor and its dependencies.
- **A local Dyson Sphere Program install.** The viewer's item names, icons, recipes and
  building bounding boxes are extracted from the game's own asset bundles, not from a
  community data dump, so the game files must be present on this machine.

## Setup

From the repository root:

```sh
uv sync
cd web
bun install
bun run extract-assets "/path/to/Dyson Sphere Program"
```

`bun run extract-assets` writes `items.json`, `recipes.json`, `models.json` and an icon atlas
into `public/assets/`. Run it before opening the viewer. Its output is cached and only needs
regenerating after a game update. Contributors without the game can use an existing
`public/assets/` directory copied from someone who has it.

## Run

For normal use, run the integrated server from the repository root:

```sh
uv run flab2bp-web
```

Open <http://127.0.0.1:8000>. The command builds the front end when necessary and serves both
the page and the Python API.

For TypeScript development, run this from `web/`:

```sh
bun run dev
```

Open <http://127.0.0.1:3001>. `concurrently` starts `flab2bp-web --no-build` on port
8000 while `wait-on` holds Rsbuild until `/api/health` responds. Ctrl-C terminates both
process trees.

To expose the frontend on all interfaces while keeping the Python API bound to loopback, run:

```sh
bun run dev -- --host 0.0.0.0
```

Open `http://<development-machine>:3001`. Anyone who can reach that port can also reach the
proxied solver and unauthenticated `/api/fetch` relay, so use this only on a trusted network.

To use an API at a different origin, manage that API separately and run:

```sh
FLAB2BP_API=http://127.0.0.1:9000 bun run dev:frontend
```

A proxy error for `/api/build` means the configured Python API is not reachable.

## Scripts

| Script | What it does |
| `bun run dev` | Starts the Python API, waits for it, and supervises it with Rsbuild. |
| `bun run dev:frontend` | Starts only Rsbuild for an externally managed API. |
| `bun run build` | Production bundle into `dist/`. |
| `bun run test` | Rstest suite (`test:watch` for watch mode). |
| `bun run typecheck` | `tsc --noEmit`. |
| `bun run lint` | Oxlint, Oxfmt check, and ESLint (React Hooks rules). |
| `bun run format` | Oxfmt formatter, writing in place. |
| `bun run format:check` | Checks Oxfmt formatting without writing. |
| `bun run extract-assets` | Regenerates `public/assets/` from the game install. |

The development servers bind to `127.0.0.1` by default. Passing a different frontend host
also exposes its proxied `/api` routes; `/api/fetch` is an unauthenticated HTTP(S) relay.

## Architecture

The code is layered so that everything hard to get right can be tested without a renderer.
`src/format/` decodes the blueprint string — base64, gzip, the CSV header envelope, the MD5F
checksum and the binary building records — and `src/model/` turns that into catalog lookups,
a scene layout, a bill of materials and info-panel rows. Neither directory imports React or
three.js, and a guard test in `tests/architecture.test.ts` enforces it; that is what lets the
parser and the layout maths be covered by plain unit tests over real blueprint fixtures
instead of by rendering a canvas and squinting at it. `src/scene/` (react-three-fiber),
`src/ui/` (panels) and `src/state/` (React context, asset loading) sit on top and hold all
the framework-specific code. The Python server in `../src/flab2bp/web/` owns `/api/build`,
`/api/health`, and `/api/fetch`.
Rsbuild proxies `/api` to that server so development and production use the same endpoints.
