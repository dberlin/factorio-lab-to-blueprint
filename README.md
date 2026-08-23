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
