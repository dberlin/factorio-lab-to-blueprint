# The web UI

Paste a FactorioLab URL, set the options, press Build, copy the blueprint string, and see it
rendered — all on one page, with the same solver the CLI runs.

## Starting it

```bash
uv sync
uv run flab2bp-web          # http://127.0.0.1:8000
```

That is the whole command. On first run it builds the front end itself (`bun install
--frozen-lockfile && bun run build` in `web/`), so the prerequisites are `uv` and `bun` on
`PATH` and nothing else — `flab2bp.web` uses the standard-library HTTP server plus `httpx`
and Pydantic, which the core package already requires. There is deliberately no `[web]` extra,
because there is nothing to put in it.

| flag | what it does |
| --- | --- |
| `--port N` / `--host H` | move it (default `127.0.0.1:8000`) |
| `--build` | rebuild the TypeScript even though `web/dist` exists |
| `--no-build` | never shell out to `bun`; serve whatever `web/dist` holds |
| `--workers N` | concurrent builds. Leave it at 1 — see below |
| `--dist PATH` | serve a front end built somewhere else |

If the front end is not built and `bun` is missing, the API still serves and the page says so
in plain text rather than 404ing.

## Strategy choices

The web request contract is `best`, `freeform`, or the exact wire spelling
`sequence-pair`. `best` runs both Freeform and SequencePair and returns the
smallest validator-clean result.

The solver-work ceiling is `candidates × active production strategies × budget` for `best`,
using the pipeline's canonical active-strategy tuple. The promoted portfolio has two strategies.
One build defaults to an aggregate budget of at most 16 CPUs from its process affinity set.
For an unpinned request, the widest candidate batch runs whose shares can fund Freeform plus
every requested SequencePair island; the aggregate budget is divided exactly across that
batch. If even one two-strategy race cannot fit, the strategies run serially instead.
Uploaded or fetched flows remain a single pinned candidate. An explicit Freeform or
SequencePair request remains serial across candidates and gives the current layout the whole
worker budget.

## Latitude bands

The selector defaults to **Portable (smallest + up to two wider)**. The request field is the string
`band`, and its complete shared Python/TypeScript enum is:

```text
portable | 4 | 8 | 16 | 20 | 32 | 40 | 60 | 80 | 100 | 120 | 160 | 200
```

Portable finds the globally smallest band in which the unpadded content fits (`B0`) and
certifies `B0` plus up to two bands with greater `area_segments`. The same frame must pass at
every legal latitude anchor in each required band. Near the equator only one or two bands may
remain, so `certified_bands` reports the literal set checked; Portable is not a promise about
every planetary band.

The frame search may add zero through four empty latitude rows, distributed between its north
and south margins, without changing `B0`. It never pads longitude. If none of those frames
passes, the build is refused instead of silently falling back to a single band.

Selecting a number is explicit-only: `200`, for example, certifies only band 200 with the same
up-to-four-row latitude-padding search. A frame that does not fit the requested band or fails at
any legal anchor refuses. Successful results display `primary_band` and exact
`certified_bands`; projection refusals retain the band, check, building indices, and detail for
each distinct projection failure.

## Proving it works

```bash
uv run scripts/web_smoke.py --out out/web-smoke
```

This is the check, not a demo. It starts a server on a free port, drives a real Chromium
through `nodriver`, types the URL, sets the options, presses Build, waits for the job, presses
**Copy blueprint string**, reads the clipboard back, and then **decodes that exact string with
`flab2bp.dsp.codec.decode`** and asserts `encode(decode(x)) == x` byte for byte. It screenshots
the 3D canvas through CDP and counts distinct colours, because a WebGL surface that never drew
is one flat colour and one flat colour is exactly 1. It then runs a spec the layout model
refuses and checks the reason reaches the page, and a third that pastes a FactorioLab flow
export and checks the report comes back **pinned** rather than derived. Two screenshots and a
`report.json` land in `--out`; it exits non-zero on the first thing that does not hold.


`nodriver` rather than Playwright for the same reason `flab2bp.lab.capture` uses it: Playwright
ships its own browser builds and none work on Fedora, so a proof driven through it is a proof
this machine cannot re-run.

`nodriver` is intentionally pinned to 0.47.0, the newest verified release whose Python source
is importable. The pin remains until a newer importable release is verified.

## What the page shows

The blueprint's own **title** names the *product*, `space-warper 10/min (max prolif)`,
not the candidate that won. Auto-generated titles are capped at 60 C# UTF-16 code units,
matching Dyson Sphere Program's save check. If the composed title is too long, the second
displayed product is shortened to uppercase initials first, then the first product; numeric
hyphen-delimited tokens remain whole. Rates, output order, `+N more`, and the policy suffix
stay unchanged whenever initials are enough. If they are not, the whole title is truncated
at a valid UTF-16 boundary and ends in one `…`.

The web **Name** input has the same 60-character browser limit. The page then shows the title,
machine count, tile count, building count, which strategy and candidate produced it, what it
makes and what has to be belted in.

Then the parts that read as silence if nobody prints them:

* **Whether the belt ceiling was read or assumed.** A URL with no technology set gets a
  fully-researched save assumed, and the page says so in a warning box. That claim is very
  different from "the URL told us", and only one of them is safe to build against.
* **Whether the recipe selection was pinned or re-derived.** Re-derived unless a flow export
  was supplied, and the page says which.
* **Validator warnings.** A warning means a check *ran* and found something to look at — a belt
  run nothing taps, or one item arriving through multiple external-entry lanes. The latter
  remains valid and does not block emission, but the player must connect every lane; latitude
  certification does not change `flow.external_entry_points`.
* **Every strategy/candidate pair that produced no layout**, with its reason — invisible in the
  attempts table, and silence there reads as "it simply was not the best".

## Progress is real, and where it is not

`pipeline.build` takes an `on_progress` sink and calls it as each (candidate, strategy) pair
starts and as it settles, so the bar counts **pairs finished over pairs to do**. Unpinned
`best` web requests may have several candidate portfolios active at once; the line above the
bar therefore names the most recently reported pair, while `settled` retains every completed
pair. `GET /api/build/<id>` carries both fields.

Before layout there is nothing to count: parsing the URL and solving the rates take an unknown
time and are not divided into pairs. The panel says exactly that and falls back to elapsed time
against `solver_ceiling_s` — `candidates × strategies × budget`. This is an aggregate
solver-work/admission bound, not a wall-clock prediction: bounded candidate concurrency can
spend several budgets simultaneously, and validation and encoding are on top.

## Flow provenance

Paste FactorioLab's CSV export into the flow box, or choose the file, to pin recipe selection.
The API takes it as text and sends it through `flow_from_text` and its provenance check exactly
as a file named on the command line does. An export generated from a *different* URL is refused
with the difference spelled out parameter by parameter; it is never quietly ignored.

The **Fetch FactorioLab flow automatically** checkbox is initially unchecked. Selecting it
launches the server's installed Chromium, waits for FactorioLab to solve, and exports the flow.
Automatic capture is allowed only for HTTPS pages on `factoriolab.github.io` at `/dsp/list` or
`/dsp/flow`, with no nonstandard port; the final page after navigation must remain on that
allowlist too. Pasted/uploaded flow and automatic fetch are mutually exclusive in web requests,
and the controls disable reciprocally. If capture fails, the build is refused rather than
silently falling back to re-derived recipes.

Without pasted or captured flow, a build reports `flow_pinned: false` — the recipe selection is
DERIVED, not FactorioLab's own. That is the weaker guarantee, and the page says so.

## What it does NOT do

**A job does not survive a restart.** The registry is a dict in the server process and the
queue is a `ThreadPoolExecutor`. Restarting `flab2bp-web` abandons every in-flight solve and
every finished result. For one person on localhost that is the right trade; anything
longer-lived wants the job state somewhere it can be re-read, and that is a different program.

**A running solve cannot be cancelled.** "Stop watching" stops the polling, not the solve:
CP-SAT holds its worker until its budget expires. The button is named for what it actually does,
which is the honest half. The fix is not in this package at all — it needs a `SolutionCallback`
or a solve interrupter threaded through the layout backends that build and run a `CpSolver`.
It is the one item on this list that is unfinished rather than decided.

**Jobs queue; one job's candidate portfolio may run in bounded parallel.** The default
one-job queue prevents two users from each claiming a solver budget. Inside that job, the
pipeline uses at most 16 available CPUs by default and divides them across concurrent
candidate races. Each race divides its share between Freeform and SequencePair, and requested
SequencePair islands must fit the latter share. Otherwise candidate concurrency narrows or
the two strategies run serially. `--workers` above 1 still permits concurrent jobs and can
make every build slower because
`time_budget_s` is wall-clock. There is no admission control at all beyond the queue: the
budget has no upper bound, and a projected total over 300s is warned about rather than
refused.

**A refusal leaves the previous blueprint on screen, and now says so.** The viewer keeps
rendering whatever was loaded last, because clearing it would throw away the thing you were
looking at. What used to be wrong was the label: the toolbar went on naming a build a refusal
had superseded. It now reads *previous build — the last one produced no blueprint* whenever the
canvas is not the outcome of the last build, which covers a refusal, an error, and a build whose
string was withheld for failing validation.

**`/api/fetch` is a relay, and it no longer relays into this machine.** Inherited from the
viewer's `src/server/proxy.ts`, which followed redirects blind — so an allowed public URL could
answer `302 Location: http://127.0.0.1:8000/api/build` and be fetched, which is the entire
redirect-based SSRF. Redirects are now followed by hand and every hop is resolved and rejected
if it lands on a loopback, private, link-local or reserved address; all of a name's addresses
are checked, not just the first.

It is deliberately **not** offered as a complete defence: the address is resolved in
`private_address` and connected to by httpx a moment later, so a DNS entry that changes between
the two still gets through. Closing that needs a transport pinned to the address it checked.
What is closed is the redirect hop, which needed no race at all. Anything public still needs
rate limiting on `/api/build` before it goes anywhere.

**`web/node_modules` is not committed.** It was, on master, and it was *broken*: the root
`.gitignore`'s unanchored `dist/` pattern stripped every package's `dist/` directory on the way
in, so a fresh clone got a node_modules complete enough that `bun install --frozen-lockfile`
reported "no changes" and incomplete enough that `bun run build` died on
`Cannot find module '@rsbuild/core/dist/index.js'`. `web/.gitignore` already said
`node_modules/`; this branch makes that true. `bun.lock` is the declaration.


## The API

```
POST /api/build          submit; 202 with an id, or 400 with a reason
GET  /api/build/<id>     poll; state, progress, and the result when there is one
GET  /api/health         is the server up, and is the front end built
GET  /api/fetch?url=...  the viewer's own blueprint-page proxy
GET  /*                  the built front end, with an SPA fallback
```

The submit body takes `url`, `strategy` (`best`/`freeform`/`sequence-pair`), `candidates`
(1–8), positive finite `budget_s`, `band`
(`portable`/`4`/`8`/`16`/`20`/`32`/`40`/`60`/`80`/`100`/`120`/`160`/`200`),
`name`, `allow_invalid`, `flow`, and `fetch_flow`. `band` defaults to `portable`.
Power is always enabled: every web build includes Tesla Towers, and the page has no power
selector. The retired `power` request key is rejected rather than ignored.
`flow` is a FactorioLab CSV export as text, while `fetch_flow: true` asks the server to capture
one from an allowlisted FactorioLab page; the two are mutually exclusive. A poll echoes
`flow_supplied` rather than the CSV itself (it can be hundreds of kB and the page already has
it); `result.flow_pinned` is the proof it was honoured. A successful `result` also carries
`primary_band` and literal `certified_bands`. Every bound is a refusal rather than a clamp,
never silently rounded down to something servable, because running a different build from the
one that was asked for and reporting it as the one that was asked for is the failure mode this
whole project exists to avoid.

`budget_s` is the one field with no upper bound, for that same reason: how long to search is
the caller's call. It must be positive and finite, and that is all. A job whose projected
total — `candidates × strategies × (budget + completion grace)` — exceeds 300s is accepted
with a `warning` string on the job snapshot spelling out the arithmetic; `warning` is `null`
otherwise. The page shows the same sum next to the budget box before you submit, and the
Build button stays enabled: it is a warning, not a gate.

`blueprint` is `null` when validation failed and `allow_invalid` was not set — the same refusal
the CLI makes without `--allow-invalid`, moved to the place the string would be copied from.
The page then offers a button that says what you would be asking for.

## Working on the TypeScript

```bash
cd web && bun run dev      # rsbuild on 3001, /api proxied to flab2bp-web on 8000
```

The solver is Python, so `flab2bp-web` has to be running either way. `web/` is the former
`dsp-blueprint-viewer` — React, rsbuild, three.js — taken in-tree and taken over rather than
vendored, and its own gates still apply:

```bash
cd web && bun run typecheck && bun run lint && bun run test
```
