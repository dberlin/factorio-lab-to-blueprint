# flab2bp

Turn a [FactorioLab](https://factoriolab.github.io/dsp) URL for Dyson Sphere Program into a
dense, pasteable DSP blueprint. The browser interface is the recommended way to use `flab2bp`:
it runs the same solver as the CLI and renders the generated blueprint in 3D.

## Recommended: web interface

### Requirements and setup

- Python 3.14 or newer
- [uv](https://docs.astral.sh/uv/)
- [Bun](https://bun.sh/) for the browser interface and TypeScript cross-validation
- A C++17-capable compiler when building the native extensions from source

The viewer's item names, icons, recipes, and building geometry are extracted from the game and
are not stored in Git. Populate `web/public/assets/` once from a local Dyson Sphere Program
installation, or copy an already-generated directory from another installation:

```bash
uv sync
cd web
bun install --frozen-lockfile
bun run extract-assets "/path/to/Dyson Sphere Program"
cd ..
uv run flab2bp-web
```

Open <http://127.0.0.1:8000>. Skip asset extraction when `web/public/assets/` is already
populated. `flab2bp-web` builds the front end when necessary; pass `--build` to force a rebuild,
`--no-build` to serve an existing build, or `--host` and `--port` to change the listener.

Paste a FactorioLab URL, choose the strategy, candidate policies, and per-layout budget, then
press **Build**. The page exposes the resulting blueprint for copying and renders it without a
second tool.

**A build is a job, not a request.** `--budget` is per layout and `best` lays out every
candidate with freeform, sequence-pair, CaDiCaL-based transport-routing and hierarchical,
so a build can run for seconds to minutes. `best` selects the smallest validator-clean result, not the first to
finish. Transport-routing supports unsprayed and sprayed interfaces, including separate
raw-material and proliferator feeds; every result must pass the same physical validation.
`POST /api/build` returns an id immediately and the page polls `GET /api/build/<id>`. `pipeline.build` reports
each candidate/strategy pair as it starts and settles. A projected total over 300 seconds
warns that the job may take a while; it does not refuse or silently clamp the request.
Raced builds allocate an aggregate CPU budget (by default at most 16 affinity CPUs)
across the widest candidate batch that can fund four workers per candidate. Each
candidate gives hierarchical one quarter of its share (at least one worker), keeps
one worker for transport-routing, and divides the rest between freeform and sequence-pair.
A single 16-worker portfolio starts at 8/3/1/4 workers in that order. When the
request's machine groups already guarantee at least 15 strips, Freeform's existing
single-worker packing rule reduces its share to one and transfers the unused
workers to hierarchy (1/3/1/11 at 16 total; 1/6/1/24 at 32). Smaller requests keep
the base allocation. If four workers cannot be funded, `best` runs the strategies
serially within the aggregate worker budget.
Completed race children perform full validation. The parent reuses that judgment
only for the identical placement, complete request and belt rules; changed geometry
or a missing judgment is validated again. Every retained alternative is still encoded.

Detailed routing and relaxed global congestion routing use the native geometric interval
engine (`route_backend: geometric`), without an A* fallback. Routing budget and `expansions`
counters measure newly prepared cells plus processed active intervals, not historical A*
node expansions. Existing numerical caps, deadlines, and atomic-completion grace remain
unchanged. The two routing modes retain their distinct congestion costs: detailed search
charges arrivals; relaxed search also charges starts and ramp-via cells.
A bounded reverse interval probe can identify a sealed destination pocket without
exhausting the larger source region. Its prepared cells and interval work consume the
same allowance as forward search. Exhaustion reports distinguish the source-reachable
component from the goal-reaching component; interrupted probes supply neither proof.

Constructive transport selection enforces the emitter's inclusive XY canvas envelope
for both selected routes and immutable fixed paths, including owned endpoints.
Out-of-envelope routes are rejected before emission; bounds are not widened to fit
a selected route. Standalone template problems remain unbounded unless bounds are supplied.
Power infill indexes fixed power-node centres per exact projection and frame before
checking prospective sites. The index conservatively narrows static peers; original
power-spacing predicates, candidate order, selected-node checks and final validation remain.

**A refusal is a result.** A spec that cannot be laid out reports why each strategy and
candidate gave up. An invalid build withholds the blueprint and lists the validation errors,
matching the CLI unless `--allow-invalid` is explicitly requested.

Flow provenance is explicit. `--flow FILE` pins a FactorioLab CSV export; `--fetch-flow` is
opt-in and drives installed Chromium to export FactorioLab's solved flow. Capture failure
refuses the build instead of silently deriving a different recipe selection. Automatic fetch
and pasted or uploaded CSV are mutually exclusive.

For TypeScript development, `cd web && bun run dev` starts and supervises both the Python API
on port 8000 and Rsbuild on port 3001. To use an API managed separately at a different origin,
run the frontend from `web/` with:

```bash
FLAB2BP_API=http://127.0.0.1:9000 bun run dev:frontend
```

`web/README.md` documents remote access, external API configuration, asset extraction, and
the individual web commands.

`uv run scripts/web_smoke.py` drives the integrated server in a real browser and decodes the
blueprint copied by the page. [docs/WEB_UI.md](docs/WEB_UI.md) documents the UI and API.

## Alternative: command-line interface

Use the CLI for scripting, automation, or direct access to advanced solver options:

```bash
uv run flab2bp 'https://factoriolab.github.io/dsp/flow?o=super-magnetic-ring*60&ibe=conveyor-belt-2&mmr=arc-smelter~assembling-machine-2~chemical-plant~matrix-lab&mps=proliferator-2-products&v=11'
```

The command prints the blueprint string to standard output. Use `-o FILE` to write it to a
file, and `uv run flab2bp --help` for the full strategy, candidate-policy, latitude-band,
flow-provenance, and validation options.

Power is always included. The web **Power tower** selector and CLI
`--power-tower tesla|substation|wireless` override the URL's preferred machines.
Without an override, the first recognized power building in the URL's machine
rank is used; otherwise it remains Tesla Tower. The Python API accepts the same
choice names as `pipeline.build(..., power_tower="substation")`; web requests
use `"power_tower": "auto"` for URL selection. Non-default blueprint descriptions
and the web **Power** report row name the selected building.

Satellite Substations retain a low-confidence collider caveat: their planner
reserves centred catalog clearance, but a clean certificate alone does not prove
the suppressed substation/belt collider cases. Direct clearance checks and
in-game paste validation remain necessary; larger towers can also expose
conservative power-planning refusals near a coverage boundary.

## What it builds

The whole recipe chain from the FactorioLab flow, minus mining. Ores, water, oil and
proliferator arrive on input belts at one edge; the target item leaves on an output belt at the
other. Everything between is built, wired and throughput-correct: no belt lane carries more than
its tier allows; belts start at the tier the URL chose and a run that needs more is raised to the
cheapest faster belt the URL's technologies unlock; sorters likewise stay within the researched
tiers, no sorter is asked to exceed its rate, and every machine is fed at the rate its
recipe demands.

Density is the objective. The layout may use direct insertion between adjacent machines, long
(2- and 3-tile) sorters, stacked belts at multiple altitudes, and proliferator up to Mk.III --
choosing per recipe between *extra products* mode, which compounds savings up the chain, and
*production speedup* mode, which halves machine count at that step.

The `hierarchical` strategy automatically competes in `best` and can also be selected alone.
It prioritizes a feasible factory: it tries one eligible
solver per unresolved block shape and runs an alternate only if that shape remains unresolved. Divisible
refused blocks are cut before another parent-widening round, within the existing budget.
The initial block schedule reduces workers per block only when needed to fund its
independent waves; that worker profile stays fixed across re-cuts. Final composition
may negotiate further routing rounds within the same deadline and expansion allowance.
This can trade density for lower latency; it does not promise the smallest layout.
The `best` portfolio's smallest-validator-clean-result selection is unchanged.

## Latitude portability

`--band portable` is the default for all layout strategies and the web interface. The
available selections are:

```text
portable
5x20 5x40 5x80 5x100
10x160 10x200
15x300 15x400
25x500 25x600
50x800
160x1000
```

Portable mode starts with the globally smallest band in which the unpadded layout fits (`B0`)
and certifies `B0` plus up to two bands with greater `area_segments`. It checks the same
orientation and frame at every legal latitude anchor in every named band. Near the equator
there may be fewer than three bands left, so the report lists the exact bands actually
certified; Portable does not claim every latitude band on the planet.

The finalizer may add zero through four empty **latitude** rows, split between the north and
south margins, while keeping `B0` fixed. It never adds longitude padding. It picks the smallest
passing frame, or refuses the layout rather than emitting a blueprint with a weaker guarantee.
A refusal retains structured evidence for each distinct projection failure: band, check,
building indices, and the authoritative detail.

An explicit named selection certifies only that requested band, using the same search of up to
four latitude rows. If the layout does not fit the band or fails at any legal anchor, the build
refuses. Successful CLI reports and web results expose both `primary_band` and the literal
`certified_bands` tuple.

Latitude certification does not change the validator's `flow.external_entry_points` warning:
multiple reachable external lanes for one item remain valid, but the player must connect a
supply to every lane.

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
| `layout/freeform.py` | Freeform — CP-SAT rectangle packing + detailed belt router |
| `layout/sequence_solver.py` | SequencePair — staged sequence-pair search using the shared router |
| `layout/transport_routing/` | CaDiCaL-backed constructive transport routing |
| `layout/hierarchy/` | Hierarchical block decomposition, solving and composition |
| `layout/validate.py` | Strategy-independent judge: overlap, reach, continuity, throughput |
| `dsp/codec.py` | `Placement` → binary → gzip → base64 → header → MD5F, and back |
| `bench/` | Compares Freeform and SequencePair over the URL corpus |

Stage 4 has four production implementations behind one interface. `best` runs all four and
returns the smallest validator-clean placement.

Everything upstream of `BuildSpec` is arithmetic on rationals with no geometry. Everything
downstream is geometry with no rate reasoning.

## Correctness

The DSP blueprint format is unforgiving — a checksum mismatch or a byte out of place and the game
silently refuses the paste. Four independent guards:

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

## Gate result

On 2026-09-07, the `lane-fanout` branch's final gate ran two rounds of the stress-tier corpus
(72 cells, both placers) against the master `a1401518` baseline: **FAIL**. Coverage held at
66/72 CLEAN in both rounds, with zero regressions against baseline (0/72 cells moved status in
either direction) and a paired area ratio of 1.000000 (round 1) / 0.999424 (round 2) on the 66
cells CLEAN in both arms. The six `universe-matrix` cells this branch's work targets (both
placers × `no-proliferator`/`all-products`/`output-products`) remain REFUSED in both rounds — the
fan-out guard this branch deleted no longer fires (no candidate refusal says "must tap"), but two
other, pre-existing blockers do: the freeform packer's clock-limited packing shortfall and the
sequence-pair per-island exact-layout search's non-convergence. Full measurements, verbatim
refusal text, and the ranked residual blockers are in
`docs/superpowers/evidence/2026-09-07-lane-fanout/gate/verdict.md`.

## Development

Run the Python and web gates relevant to the files changed:

```bash
uv run pytest
uv run ruff check .
uv run mypy

cd web
bun install --frozen-lockfile
bun run typecheck
bun run lint
bun run test
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
