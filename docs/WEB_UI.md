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
`flab2bp.dsp.codec.decode`** and asserts `encode(decode(x)) == x` byte for byte. It screenshots
the 3D canvas through CDP and counts distinct colours, because a WebGL surface that never drew
is one flat colour and one flat colour is exactly 1. It then runs a spec the layout model
refuses and checks the reason reaches the page, and a third that pastes a FactorioLab flow
export and checks the report comes back **pinned** rather than derived. Two screenshots and a
`report.json` land in `--out`; it exits non-zero on the first thing that does not hold.

The client arm's `web/smoke.py` is the same gate — it imports the canvas check and the refusal
fixture from this file rather than reimplementing either, so the two arms cannot be held to two
standards.

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
* **Whether the recipe selection was pinned or re-derived.** Re-derived unless a flow export
  was supplied, and the page says which.
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

**`--fetch-flow` is not wired, and on the client arm cannot be.** It drives a headless browser
to make FactorioLab run its own solve, which is a much larger surface than a build here and is
arithmetically impossible in a page — a page cannot drive a headless browser against itself.

`--flow` **is** wired, on both arms. Paste FactorioLab's CSV export into the flow box, or choose
the file; the API takes it as text and it reaches `flow_from_text` and its provenance check
exactly as a file named on the command line does. An export generated from a *different* URL is
refused with the difference spelled out parameter by parameter — it is never quietly ignored,
because a pin the user believes in and the build did not honour is worse than no pin.

Without one, a build reports `flow_pinned: false` — the recipe selection is DERIVED, not
FactorioLab's own. That is the weaker of the two guarantees, and it is stated on the page rather
than left to be inferred.

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

**A refusal leaves the previous blueprint on screen, and now says so.** The viewer keeps
rendering whatever was loaded last, because clearing it would throw away the thing you were
looking at. What used to be wrong was the label: the toolbar went on naming a build a refusal
had superseded. It now reads *previous build — the last one produced no blueprint* whenever the
canvas is not the outcome of the last build, which covers a refusal, an error, and a build whose
string was withheld for failing validation. (The client-side arm rebuilds its whole output
column per solve, so it never had this to fix.)

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

**It does not run the solver client-side — but something else here does.** That was recorded on
this page as *considered and dropped*, and it was then built anyway: `web/CLIENTSIDE.md`
describes a second arm where CPython, CP-SAT and SCIP all run in the tab and the server hands
out nothing but files. The two are measured against each other below.

## Two arms, and which one to ship

There are two of these. This one solves on a server. `web/CLIENTSIDE.md` describes the other:
Pyodide plus or-tools-wasm, the whole pipeline inside the tab, the server handing out nothing
but files. They were built by different agents and had drifted into two applications; they are
now the same application over two solvers. Same options, same report from the same
`flab2bp.web.payload.describe`, same progress sink, same viewer (`web/src/embed.tsx` is the
server arm's own component tree, mounted by the client page), same refusal rendering, same
proof gate.

### The measurement

One URL — the `space-warper 10/min` spec at the top of this file — `best`, 3 candidates,
Tesla Towers on, on a 128-core box.

**Two things bite, and an earlier draft of this section got both wrong.** The budget is
wall-clock, so CPU contention takes search away exactly as a smaller budget does: a browser run
at 6 s taken immediately after a heavy server-arm run came back with the 2 s area. And the
browser's result is *not* deterministic — four-thread CP-SAT is a portfolio with a race in it.
Three runs agreeing is not three runs of evidence. So these are the full distributions, taken
with the box otherwise idle, and any re-measurement has to be too.

| arm | budget/layout | area, tiles, every run | median |
| --- | --- | --- | --- |
| server, CP-SAT on every core | 2s | 1178, 1178, 1216, 1224, 1232, 1232, 1232, 1232 | **1228** |
| browser, CP-SAT on 4 wasm threads | 2s | 1292 × 6 | **1292** |
| browser | **6s** | 1210 × 7, 1232, 1292, 1292 | **1210** |
| browser | 12s | 1210 | — |

Wall clock, browser: 59–71 s at 2 s and 59–63 s at 6 s — indistinguishable, because most of a
browser build is not CP-SAT. 94 s at 12 s. Server: 33–55 s.

**The area gap was a knob.** At 2 s the browser is 5.2% worse than the server arm's median and
is worse on every single run. At 6 s its median is 1.5% *better*, for the same wall clock. The
knob is not free of variance: 3 of the 10 runs at 6 s landed at or above the server arm's
median, and 2 of those got no further than the 2 s figure. What is not in doubt is the
direction — no 6 s run was worse than the best 2 s run, and 7 of 10 beat every server-arm run
but one. Past 6 s the extra budget bought no area on this spec and 50% more wall clock, which is
why 6 is what `web/app.html` now defaults to and what the page's note explains.

### Why, and how that was established without a browser

`web/vendor/ortools`'s CP-SAT runtime is built with `pthreadPoolSize=4`. Native CP-SAT runs
with `num_search_workers = 0`, meaning every core. Parallel CP-SAT is a **portfolio** — the
extra workers explore genuinely different regions rather than merely going faster, which
`src/flab2bp/layout/base.py` already records as 23% of area on one spec — so four workers
against a wall-clock budget buy materially less search.

That predicts the whole gap, and it can be tested natively in 30 seconds a run instead of 90 in
a browser: pin `DEFAULT_SEARCH_WORKERS` to 4 and leave everything else alone.

| native CP-SAT | budget/layout | area, tiles |
| --- | --- | --- |
| every core | 2s | 1232, 1232, 1178, 1224 |
| **4 workers** | 2s | 1400, 1232, 1344, **2193** |
| 4 workers | 6s | 1254, 1232, 1232 |
| 4 workers | 12s | 1110 |

Four workers at three times the budget lands on 1232 — the same number every-core reaches at
2s — and at six times it beats it. The prediction transferred to the real browser exactly.

The **2193** is the more interesting number. That run is not a worse layout: it is a run where
the winning pair, `max-proliferation` / `freeform`, produced *no layout at all* and the build
fell back to a 78%-larger candidate. Under-budgeted four-worker CP-SAT does not degrade
smoothly; it refuses.

What would falsify this: native at 4 workers matching native at every core. It did not — it was
14% worse, and once refused outright.

### The recommendation: ship the server arm, keep the client arm

Not because of density. Density is settled: at the 6 s default the browser's median is 1.5%
better than the server arm's, and it is more variable. The reasons that survive the measurement
are:

1. **57.6 MB over 46 files, cold, every time the cache is.** Measured by `web/serve.py`'s own
   byte tally, largest first: `mp_solver_runtime.wasm` 18.5, `pyodide.asm.wasm` 8.3,
   `cp_sat_runtime.wasm` 7.1, pandas 5.1, sympy 3.9, numpy 3.0, the Python stdlib 2.3, the icon
   atlas 1.4, pydantic-core 1.3 MB. 10–15 s to interactive. The server arm ships 1.2 MB of
   JavaScript plus the same 1.6 MB of catalog and icon atlas — about 2.9 MB, and no wasm at all
   (`find web/dist -name '*.wasm'` is empty). Twenty times less, for the same page.
2. **A hard capability gate.** The client arm needs WebAssembly stack switching (JSPI),
   `SharedArrayBuffer` and cross-origin isolation, and it fails loudly without them rather than
   degrading — which is correct, and which also means it simply does not run where they are
   absent. This box has one browser, Chromium 151, so no cross-browser claim is made here.
3. **`--fetch-flow` cannot be wired to it, ever.** Making FactorioLab produce its own export
   means driving a headless browser, and a page cannot do that to itself. `--flow` — pasting or
   uploading an export you already have — is wired on both arms and is the same pin; it is the
   *fetch* half that is arithmetically out of reach, and the page says so rather than
   mislabelling a derived selection as pinned.
4. **Nothing gets faster.** 59–71 s against 33–55 s, on a spec the CLI does in 34 s.

None of that argues for deleting the client arm, and it should not be deleted. It is the only
one of the two that runs on a static host with no Python anywhere, it is now density-competitive
at its own default, and every claim it makes is re-runnable through `web/smoke.py`.

**What would change the answer.** The payload. 25.6 of the 57.6 MB is the two solver runtimes,
and `mp_solver_runtime.wasm` alone is 18.5 MB for the MILP that solves the *rates* — a problem
several orders smaller than the layout, and the one place a smaller backend would pay for
itself. Another 5.1 MB is pandas, which flab2bp never imports: ortools' own pure-Python
`cp_model.py` does, at `web/pyshim/ortools/sat/python/cp_model.py:69`, for a dataframe API this
code path does not use. numpy and sympy are genuinely needed (`layout/freeform.py`,
`rates/solve.py`). Or `or-tools-wasm` raising its pthread pool, which would remove the reason
the browser needs a 6 s default at all. None of that is work in this repository.

## The API

```
POST /api/build          submit; 202 with an id, or 400 with a reason
GET  /api/build/<id>     poll; state, progress, and the result when there is one
GET  /api/health         is the server up, and is the front end built
GET  /api/fetch?url=...  the viewer's own blueprint-page proxy
GET  /*                  the built front end, with an SPA fallback
```

The submit body takes `url`, `strategy` (`best`/`spine`/`freeform`), `candidates` (1–8),
`budget_s`, `power`, `name`, `allow_invalid`, and `flow` — a FactorioLab CSV export as text,
which pins which recipe makes what. A poll echoes `flow_supplied` rather than the CSV itself
(it can be hundreds of kB and the page already has it); `result.flow_pinned` is the proof it was
honoured. Every bound is a refusal rather than a clamp:
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
