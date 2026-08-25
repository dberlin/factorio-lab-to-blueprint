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
`PATH` and nothing else — `flab2bp.web` is standard library plus `httpx`, which the core
package already required. There is deliberately no `[web]` extra, because there is nothing to
put in it.

| flag | what it does |
| --- | --- |
| `--port N` / `--host H` | move it (default `127.0.0.1:8000`) |
| `--build` | rebuild the TypeScript even though `web/dist` exists |
| `--no-build` | never shell out to `bun`; serve whatever `web/dist` holds |
| `--workers N` | concurrent builds. Leave it at 1 — see below |
| `--dist PATH` | serve a front end built somewhere else |

If the front end is not built and `bun` is missing, the API still serves and the page says so
in plain text rather than 404ing.

## Proving it works

```bash
uv run scripts/web_smoke.py --out out/web-smoke
```

This is the check, not a demo. It starts a server on a free port, drives a real Chromium
through `nodriver`, types the URL, sets the options, presses Build, waits for the job, presses
**Copy blueprint string**, reads the clipboard back, and then **decodes that exact string with
`flab2bp.dsp.codec.decode`** and round-trips it. It then runs a spec the layout model refuses
and checks the reason reaches the page. Two screenshots and a `report.json` land in `--out`;
it exits non-zero on the first thing that does not hold.

`nodriver` rather than Playwright for the same reason `flab2bp.lab.capture` uses it: Playwright
ships its own browser builds and none work on Fedora, so a proof driven through it is a proof
this machine cannot re-run.

## What the page shows

The blueprint's own **title** — which names the *product*, `space-warper 10/min (max prolif)`,
not the candidate that won — then machine count, tile count, building count, which strategy
and candidate produced it, what it makes and what has to be belted in.

Then the parts that read as silence if nobody prints them:

* **Whether the belt ceiling was read or assumed.** A URL with no technology set gets a
  fully-researched save assumed, and the page says so in a warning box. That claim is very
  different from "the URL told us", and only one of them is safe to build against.
* **Whether the recipe selection was pinned or re-derived.** Always re-derived here; `--flow`
  and `--fetch-flow` are not wired (below).
* **Validator warnings.** A warning means a check *ran* and found something to look at — a belt
  run nothing taps, an input arriving on two separate lanes. The build is valid and the string
  is emitted, so nothing else would ever mention them.
* **Every strategy/candidate pair that produced no layout**, with its reason — invisible in the
  attempts table, and silence there reads as "it simply was not the best".

## Progress is real, and where it is not

`pipeline.build` takes an `on_progress` sink and calls it as each (candidate, strategy) pair
starts and as it settles, so the bar counts **pairs finished over pairs to do** and the line
above it names the pair currently in CP-SAT. `GET /api/build/<id>` carries that as `progress`
and `settled`.

Before the layout loop there is nothing to count: parsing the URL and solving the rates happen
first, take an unknown time, and are not divided into pairs. The panel says exactly that and
falls back to elapsed time against `solver_ceiling_s` — `candidates x strategies x budget`,
which bounds CP-SAT only. Validation and encoding are on top of it and a strategy that refuses
spends its retry budget as well, so it is a scale for the wait, never a finish time.

## What it does NOT do

**`--flow` and `--fetch-flow` are not wired.** The first needs a file upload; the second drives
a headless browser and is a much larger surface than a build. So every web build reports
`flow_pinned: false` — the recipe selection is DERIVED, not FactorioLab's own. That is the
weaker of the two guarantees, and it is stated on the page rather than left to be inferred.

**A job does not survive a restart.** The registry is a dict in the server process and the
queue is a `ThreadPoolExecutor`. Restarting `flab2bp-web` abandons every in-flight solve and
every finished result. For one person on localhost that is the right trade; anything
longer-lived wants the job state somewhere it can be re-read, and that is a different program.

**A running solve cannot be cancelled.** "Stop watching" stops the polling, not the solve:
CP-SAT holds its worker until its budget expires. Interrupting it means a `SolutionCallback` or
a solve interrupter inside `src/flab2bp/layout/`. The button is named for what it actually does.

**Concurrency is a queue, not parallelism, and that is deliberate.** One CP-SAT solve already
runs at ~700% CPU (see the note in `pyproject.toml` about why the test suite is not `-n auto`).
`--workers` exists but raising it above 1 on one machine makes every concurrent build slower,
since `time_budget_s` is wall-clock. Two people on one server contend; there is no admission
control beyond the queue and the 300s ceiling per job.

**A refusal leaves the previous blueprint on screen.** The viewer keeps rendering whatever was
loaded last, so after a refusal the toolbar still names the build before it. Clearing it would
throw away the thing you were looking at, which seemed worse; the refusal panel is the answer
and it is unmissable, but the toolbar above it is stale.

**`/api/fetch` is an open relay**, inherited from the viewer's `src/server/proxy.ts` and
reimplemented in Python for parity. It follows redirects, so an allowed http(s) URL can still
reach a loopback address. Mitigated only by binding to 127.0.0.1. Anything public needs this
closed first, along with rate limiting on `/api/build`.

**`web/node_modules` is not committed.** It was, on master, and it was *broken*: the root
`.gitignore`'s unanchored `dist/` pattern stripped every package's `dist/` directory on the way
in, so a fresh clone got a node_modules complete enough that `bun install --frozen-lockfile`
reported "no changes" and incomplete enough that `bun run build` died on
`Cannot find module '@rsbuild/core/dist/index.js'`. `web/.gitignore` already said
`node_modules/`; this branch makes that true. `bun.lock` is the declaration.

**Considered and dropped: running the solver client-side.** `ortools` is not in Pyodide's
package set, and while a WASM port of OR-Tools exists, the whole point of it would be removing
the server — which this does not do. It would be a second solver stack to keep in step with the
Python one, for no capability the server does not already provide.

## The API

```
POST /api/build          submit; 202 with an id, or 400 with a reason
GET  /api/build/<id>     poll; state, progress, and the result when there is one
GET  /api/health         is the server up, and is the front end built
GET  /api/fetch?url=...  the viewer's own blueprint-page proxy
GET  /*                  the built front end, with an SPA fallback
```

The submit body takes `url`, `strategy` (`best`/`spine`/`freeform`), `candidates` (1–8),
`budget_s`, `power`, `name` and `allow_invalid`. Every bound is a refusal rather than a clamp:
a job asking for more than 300s of solving comes back 400 with the arithmetic spelled out,
never silently rounded down to something servable, because running a different build from the
one that was asked for and reporting it as the one that was asked for is the failure mode this
whole project exists to avoid.

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
