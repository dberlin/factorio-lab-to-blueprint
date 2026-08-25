# flab2bp

Turn a [FactorioLab](https://factoriolab.github.io/dsp) URL for Dyson Sphere Program into a
dense, pasteable DSP blueprint.

```bash
uv run flab2bp 'https://factoriolab.github.io/dsp/flow?o=super-magnetic-ring*60&ibe=conveyor-belt-2&mmr=arc-smelter~assembling-machine-2~chemical-plant~matrix-lab&mps=proliferator-2-products&v=11'
```

## What it builds

The whole recipe chain from the FactorioLab flow, minus mining. Ores, water, oil and
proliferator arrive on input belts at one edge; the target item leaves on an output belt at the
other. Everything between is built, wired and throughput-correct: no belt lane carries more than
its tier allows, no sorter is asked to exceed its rate, and every machine is fed at the rate its
recipe demands.

Density is the objective. The layout may use direct insertion between adjacent machines, long
(2- and 3-tile) sorters, stacked belts at multiple altitudes, and proliferator up to Mk.III --
choosing per recipe between *extra products* mode, which compounds savings up the chain, and
*production speedup* mode, which halves machine count at that step.

## Pipeline

```
URL ──1──> LabRequest ──2──> RateSolution ──3──> BuildSpec ──4──> Placement ──5──> blueprint
           settings +        recipe →            integer          buildings,
           objectives        machines,           machines +       belts, sorters
                             exact Fractions     item flows       on a tile grid
```

| Module | Responsibility |
| --- | --- |
| `lab/url.py` | Parse bare and `z=` compressed FactorioLab URLs |
| `lab/data.py` | Fetch, cache and type the DSP dataset |
| `rates/solve.py` | Objectives → per-recipe machine counts, in exact rational arithmetic |
| `spec.py` | `RateSolution` → `BuildSpec`, the frozen rates/geometry boundary |
| `layout/base.py` | `LayoutStrategy` protocol, `Placement`, geometry primitives |
| `layout/spine.py` | **Strategy A** — structured spine, CP-SAT arrangement |
| `layout/freeform.py` | **Strategy B** — CP-SAT rectangle packing + belt router |
| `layout/validate.py` | Strategy-independent judge: overlap, reach, continuity, throughput |
| `dsp/codec.py` | `Placement` → binary → gzip → base64 → header → MD5F, and back |
| `bench/` | Runs both strategies over a URL corpus and reports density |

Stage 4 has two competing implementations behind one interface. Which one ships is decided
empirically by `bench/`, not by argument.

Everything upstream of `BuildSpec` is arithmetic on rationals with no geometry. Everything
downstream is geometry with no rate reasoning.

## Correctness

The DSP blueprint format is unforgiving — a checksum mismatch or a byte out of place and the game
silently refuses the paste. Three independent guards:

1. **Byte-identical re-encode.** All 11 real game blueprints in `tests/fixtures/` decode and
   re-encode to exactly their original string, checksum included. This proves the writer emits
   what the game itself emits.
2. **Self-check.** Every generated `Placement` goes through `layout/validate.py` before encoding.
3. **Cross-validation.** Generated strings are parsed by the independent TypeScript decoder in
   `../dsp-blueprint-viewer` via `bun`, so an encoder bug cannot hide behind a matching bug in our
   own decoder. Skipped cleanly when that repo or `bun` is absent.
4. **Geometry against real blueprints.** `tile_to_local_offset` — the one place tile space becomes
   DSP world coordinates — is checked against player-built fixtures: 686 of 686 machine-side sorter
   endpoints land inside the machine they serve, where the two corner readings score 248/676 and
   174/666. A blueprint the game emitted is necessarily legal, which makes the fixtures an oracle.

A layout is only shipped if the validator accepts it. When no strategy can produce a valid one,
`lay_out` raises `NoValidLayout` rather than degrading — a blueprint that pastes and then does not
run is the one failure nobody discovers until they are standing in front of it in game.

DSP's blueprint checksum is a *variant* of MD5 — two altered init constants and eight altered
round constants, not derivable from `sin()`. See `dsp/md5f.py`.

## In a browser

Same solver, same options, plus the blueprint rendered in 3D on the page that built it.

```bash
uv run flab2bp-web        # http://127.0.0.1:8000
```

That is the whole command. It builds the front end with `bun` on first run — `bun install &&
bun run build` in `web/` — and then serves it, so the only prerequisites are `uv sync` and
`bun` on `PATH`. Pass `--build` to force a rebuild after changing the TypeScript, `--no-build`
to never shell out to bun, or `--port`/`--host` to move it.

Paste a FactorioLab URL, pick the strategy, candidate count and per-layout budget, and press
Build. The blueprint string is there to copy when it is done, and the viewer renders it in the
same page without a second step.

**A build is a job, not a request.** `--budget` is per layout and `best` lays out every
candidate with both strategies, so a build runs for seconds to minutes; `POST /api/build`
returns an id immediately and the page polls `GET /api/build/<id>`. `pipeline.build` reports
each (candidate, strategy) pair as it starts and as it settles, so the bar counts pairs
finished and the line above it names the pair currently in CP-SAT. Before the layout loop —
parsing the URL, solving the rates — there is nothing to count, and the panel says so rather
than inventing a fraction. A submitted job may ask for at most 300s of solving; over that is
refused with the arithmetic spelled out rather than quietly clamped.

**A refusal is a result.** A spec that cannot be laid out reports one line per strategy and
candidate saying why each gave up, and the page shows that as the answer rather than as a
failure. So is an invalid build: if validation fails, the string is withheld and the errors are
listed, exactly as the CLI refuses to emit without `--allow-invalid` — the page has a button
that says what you are asking for.

Not wired yet: `--flow` and `--fetch-flow`. The page says so rather than leaving "recipe
selection derived, not pinned" to be inferred from silence.

For working on the TypeScript, `cd web && bun run dev` starts rsbuild on port 3001 with `/api`
proxied to `flab2bp-web` on 8000 — the solver is Python, so that process has to be running
either way.

`web/` is the former `dsp-blueprint-viewer` — React, rsbuild and three.js — taken in-tree and
taken over rather than vendored. Its own gates still apply to it: `cd web && bun run typecheck
&& bun run lint && bun run test`.

`uv run scripts/web_smoke.py` drives the whole thing in a real browser and decodes the string
the Copy button actually put on the clipboard. **[docs/WEB_UI.md](docs/WEB_UI.md)** has the
options, the API, and the list of what this does not do.

## Development

```bash
uv sync
uv run pytest          # ~25s, deliberately fast enough for an edit loop
uv run ruff check
uv run mypy --strict src tests
```

### Does it actually work?

`pytest` pins behaviour; it does not answer "can both strategies lay out every real URL, cleanly,
right now". That is a separate gate, because the full matrix is minutes of CP-SAT and belongs
nowhere near an edit loop:

```bash
uv run python scripts/audit.py                  # every tier, both strategies, exits non-zero if not
uv run python scripts/audit.py --tier mid       # quicker
uv run python scripts/audit.py --budget 1,4,15  # sweep the solver budget
```

The budget sweep matters: CP-SAT is time-limited and multi-worker, so "clean at 4s" is not "clean".

```bash
uv run python scripts/ab_compare.py --tier mid --repeat 3   # which strategy is denser
```

Both refuse to score a layout the validator rejected. Invalid layouts are systematically *smaller* —
an unrouted net is a belt run that does not exist — so scoring them rewards dropping connections.
