# Client-side arm: flab2bp with no server

Paste a FactorioLab URL, set options, press Solve, copy the blueprint, look at
the factory.  Everything -- the URL parse, the rate MILP, the layout CP-SAT,
the validator, the blueprint encoder -- runs in the tab.  The server hands out
files and answers nothing else; it has no POST handler at all, on purpose.

`src/flab2bp` is **unmodified**.  The browser installs the same wheel `uv
build` produces, and the only thing swapped is `ortools`.

## Running it

    python web/fetch_assets.py       # once: Pyodide + the or-tools MPSolver runtime
    python web/build_payload.py      # after any change to src/ or web/pyshim/
    cd web && bun install && bun run build && cd ..   # the viewer, shared with the server arm
    python web/serve.py --port 8481 --dir web --isolated

then open <http://127.0.0.1:8481/app.html>.

`--isolated` sends COOP/COEP.  Without it the page still works, but only
because `coi-serviceworker.js` supplies the same headers from a service worker
on the *second* load -- see "Hosting" below.

To re-run the whole proof, headless, and check what came out:

    uv run python web/smoke.py --json /tmp/report.json

`bun run build` is new, and it is what makes the two arms comparable: the
viewer this page draws with is the *server* arm's own React/three.js tree,
built as a second rsbuild entry (`web/src/embed.tsx`) and mounted here.  This
page used to draw a flat SVG of its own, which meant a user comparing the arms
was partly comparing two drawings.  It writes to `web/dist`; the Python payload
writes to `web/payload`, and those were the same directory until rsbuild's
output cleaning silently deleted the wheel on every server-arm build.

There is no SVG fallback if the bundle is missing.  The page says what to run.
Quietly drawing something else would make the comparison a lie.

## How it works

    app.html                 UI, report, Copy button
      ├── worker.js          one Web Worker holding three wasm modules
      └── dist/embed.js      the server arm's viewer, mounted into this page
            ├── Pyodide           CPython 3.13 -- runs flab2bp, unmodified
            ├── cp_sat_runtime    or-tools CP-SAT       (layout)
            └── mp_solver_runtime or-tools MPSolver/SCIP (rates)

`web/pyshim/` is what makes `import ortools` work with no `libortools`:

* `sat/python/cp_model.py` -- **ortools 9.11's own file, verbatim.**  9.11 is
  the last release whose Python layer builds `CpModelProto` in Python; from
  9.12 `CpModel` subclasses a C++ `CpBaseModel` and reusing it is impossible.
  Vendoring it means the model that reaches the solver is the one ortools'
  own code built, not a reimplementation of its API.
* `sat/cp_model_pb2.py`, `sat/sat_parameters_pb2.py`,
  `linear_solver/linear_solver_pb2.py` -- ortools' own generated protobuf
  modules.  Pure Python, `protobuf` is their only dependency.
* `sat/python/cp_model_helper.py`, `util/python/sorted_interval_list.py` --
  the two things 9.11 still called into C++ for: eight numeric predicates and
  `Domain`.  Both are small, and `tests/clientside/` pins them against the
  installed C++ versions.
* `sat/python/swig_helper.py` -- the seam.  `SolveWrapper.solve` serialises
  the model and the parameters and hands the bytes to the wasm CP-SAT build.
* `linear_solver/pywraplp.py` -- the one real reimplementation, and only of
  what `rates/solve.py` uses.  It builds an `MPModelRequest` with ortools' own
  generated proto code and hands it to the wasm MPSolver.  A differential test
  asserts the model it builds is the same linear program real `pywraplp`
  builds.
* `_wasm_bridge.py` -- the single chokepoint.  If the page has not installed a
  bridge, every solve **raises**.  There is no in-process fallback, because a
  "solver" that answered without a solver would be the worst failure this
  project could have.

### The dataset question, which turned out not to be one

`cors.html` exists to ask whether an isolated static page can fetch
FactorioLab's `data.json`.  It does not need to: flab2bp already **vendors**
the dataset inside its own package (`flab2bp/lab/vendored/data.json`, 264 KB,
plus a 33 KB hash index), and `pipeline.build` loads it from there --
`load_vendored`, not the network.  The whole dataset therefore arrives inside
the 0.47 MB wheel, no cross-origin fetch happens, and under cross-origin
isolation none is even attempted.  That is the same copy the CLI uses offline,
so the browser and the terminal are reading identical data.

### The two things that make it possible

**SCIP is in the wasm build.**  flab2bp needs two solvers, not one: CP-SAT for
layout and SCIP (through `pywraplp`) for the rate MILP.  `or-tools-wasm`'s
CP-SAT slice was already vendored; `mp_solver_runtime.wasm` is 18.5 MB more,
and `mp_solver_supports_problem_type(3)` returns 1 -- SCIP, CBC, GLOP, CLP and
SAT are all compiled in.  PDLP and HiGHS are not.

**JSPI closes the sync/async gap.**  The or-tools runtimes are built with
emscripten pthreads, so every solve returns a Promise, while flab2bp calls
`solver.solve(model)` from the bottom of a deep synchronous call stack and
cannot be made to await.  The page therefore invokes the Python entry point as
`solve.callPromising(...)`, which runs it on a stack the engine can suspend,
and `pyodide.ffi.run_sync` blocks that stack on the solver's promise.  Calling
`pyodide.runPython` instead fails with *"Cannot stack switch because the Python
entrypoint was a synchronous function"* -- that message is the whole design
constraint in one line.

## Measured

Machine: 128 logical cores, Chromium 151, Pyodide 0.28.3, or-tools-wasm 0.9.1,
Linux.  The paired runs below were taken back to back on a quiet box -- native
CP-SAT reached 2742% CPU, i.e. about 27 cores, during them.  Read the ratio,
not the absolute seconds: under contention both arms slow down, but not by the
same factor, because only one of them can use the whole machine.

### Cold payload

**54.98 MB over 33 files**, measured by the static server's own byte tally for
one cold load with `Cache-Control: no-store`.  Where it goes:

| MB | file |
|-----:|------|
| 18.52 | `mp_solver_runtime.wasm` (SCIP, for the rate MILP) |
| 8.25 | `pyodide.asm.wasm` (CPython) |
| 7.10 | `cp_sat_runtime.wasm` (CP-SAT, for layout) |
| 5.05 | `pandas` |
| 3.93 | `sympy` |
| 2.97 | `numpy` |
| 2.30 | `python_stdlib.zip` |
| 1.28 | `pydantic_core` |
| 1.02 | `pyodide.asm.js` |
| 0.95 | `mp_solver_runtime.js` |
| 0.76 | `cp_sat_runtime.js` |
| 0.49 | `pytz` |
| 0.47 | flab2bp's own wheel, vendored dataset included |

Nothing here is gzipped by `serve.py`; a real static host would compress the
`.js` and the wheels, though not usefully the two `.wasm` files.  `pandas` and
`numpy` are there only because ortools' own `cp_model.py` imports them at
module level; `sympy` is the rate stage's exact-rational LP.  The three biggest
items -- 33.9 MB of wasm -- are the price of running two real solvers.

### Cold boot to first interactive

**10-15 s**, cold, from navigation to the Solve button enabling.  Three runs:
14.1 s, 10.1 s, 11.1 s.  Broken down on the 14.1 s one: Pyodide 2.1 s, the
thirteen wheels 2.2 s, then 9.7 s for unpacking the shim, `micropip`-installing
flab2bp's wheel and importing it.  That last figure is dominated by importing
flab2bp itself -- `layout/freeform.py` alone is 378 KB of Python.

### Solve, paired with native, same URL and same options

`--strategy best --candidates 3 --budget 2`, the user's own space-warper URL,
three pairs run alternately on the same machine:

| run | native wall | browser solve | native area | browser area | native buildings | browser buildings |
|----:|-----------:|--------------:|------------:|-------------:|-----------------:|------------------:|
| 1 | 36.4 s | 70.5 s | 1254 | 1456 | 717 | 803 |
| 2 | 22.7 s | 69.6 s | 1170 | 1276 | 723 | 897 |
| 3 | 21.5 s | 62.4 s | 1232 | 1540 | 714 | 809 |

Median 22.7 s native against 69.6 s in the browser: **about 3x slower**, and
the browser figure excludes the 10-15 s boot, which a user pays once per page
load rather than once per solve.

**The browser also builds a bigger factory.**  Every run of both arms picked
`freeform / max-proliferation` with 15 machines and validated with zero errors,
but the browser's areas (1276-1540) are consistently larger than the native
ones (1170-1254) -- 4% to 25% worse.  That is not a bug, it is the four-worker
cap below: `--budget 2` is a wall-clock budget, so fewer search workers means
less search inside the same two seconds, and CP-SAT returns the best packing it
found rather than the best that exists.  Raising `--budget` narrows the gap and
costs wall clock; it is the honest lever, and the page exposes it.

### Threading

`cp_sat_runtime.js` is built with `pthreadPoolSize=4`.  The pool is fixed at
build time, so however many cores the machine has -- 128 here, and
`navigator.hardwareConcurrency` reports all of them to the wasm -- CP-SAT gets
at most four search workers in the browser.  The server log shows it directly:
`cp_sat_runtime.js` is fetched five times per solve, once for the module and
once for each pool worker.

That is the single biggest difference between the two arms.  Native CP-SAT on
this machine runs at ~2742% CPU -- about 27 cores; the browser is capped at
four by a build-time constant in somebody else's npm package.  Changing it
means rebuilding or-tools for wasm, not configuring anything.

That pool needs `SharedArrayBuffer`, which needs cross-origin isolation.  A
shared `WebAssembly.Memory` can be *constructed* without isolation but cannot
be *postMessage'd to a worker*, so the failure is not a load error, it is an
infinite hang on `dependency: loading-workers`.

## Hosting

Cross-origin isolation is **required**, so a host that cannot set headers needs
`coi-serviceworker.js`, which installs on the first load and only takes effect
on the second.  `web/smoke.py --no-isolation` serves without COOP/COEP -- the
way GitHub Pages does -- and drives that path.

**It works, and therefore GitHub Pages works.**  Re-measured after the viewer
became the server arm's: served with no COOP/COEP at all, the page reported
`crossOriginIsolated: true`, `SharedArrayBuffer: available` and JSPI on its
second load, booted in 12.2 s, solved in 61.6 s, produced a blueprint that
decoded to 731 buildings and re-encoded to itself byte for byte, and drew a
canvas with 2835 distinct colours.  Same result as the header-served run, one
extra page load.

The cost is that first load: the service worker installs, then reloads the
page, so a cold visitor pays the navigation twice.  Nothing else differs.  A
host that *can* set the headers (Netlify, Cloudflare Pages, S3+CloudFront, a
plain nginx) skips that and is otherwise identical.

## Proving no server solved it

`smoke.py` asserts this three ways, and the first one could have failed:

1. **The browser runs with every hostname blackholed**
   (`--host-resolver-rules=MAP * ~NOTFOUND`, excluding only `localhost` and
   `127.0.0.1` so the driver and the page's own origin still resolve).  A
   dependency on a CDN, an API, or FactorioLab itself would have failed the
   solve outright rather than leaving the claim resting on a log.  The solve
   passed under it.
2. **The static server logs every request it answered.**  A full run is 60
   requests over 46 distinct files and 57.6 MB, all of them files --
   `app.html`, `worker.js`, `bootstrap.py`, the Pyodide core and wheels, the
   two `.wasm` runtimes, `payload/pyshim.zip`, the flab2bp wheel, and the
   viewer bundle with its icon atlas.  `serve.py` has no POST handler; a POST is logged and
   answered `405`.
3. **Chrome's own CDP network log** is captured, and contains nothing
   off-origin.  This is the weakest of the three and is reported as such: the
   log only covers the top-level document, because the Web Worker and the wasm
   runtimes' pool workers are separate CDP targets it does not attach to.

## The default budget is 6 s, not the CLI's 2

`web/vendor/ortools`'s CP-SAT runtime is built with `pthreadPoolSize=4`, and
native CP-SAT uses every core.  Parallel CP-SAT is a *portfolio*, so four
workers against a wall-clock budget buy materially less search -- which is
where this arm's measured area deficit came from, and all of where it came
from.  It is a knob:

| budget/layout | area, tiles, every run | median | wall clock |
| --- | --- | --- | --- |
| 2 s (the CLI's default) | 1292 x 6 | 1292 | 59-71 s |
| **6 s (this page's default)** | 1210 x 7, 1232, 1292, 1292 | **1210** | 59-63 s |
| 12 s | 1210 | -- | 94 s |

Four-thread CP-SAT is a portfolio with a race in it, so the 6 s cell is a
distribution and not a number -- three runs agreeing is not three runs of
evidence, and an earlier draft of this table said 1210 flat on exactly that
mistake.  What holds is that no 6 s run was worse than any 2 s run, and the
wall clock did not move: the extra 24 s of solver ceiling costs nothing,
because most of a browser build is not CP-SAT.  At 12 s it buys nothing more
and costs 50%.  The page's note under the controls says all of this, because a
default that differs from the CLI's and does not explain itself is a trap.

The budget is wall-clock, so these have to be measured on an idle box: a run
taken right after a heavy server-arm solve came back with the 2 s area.  The
cause -- the runtime's four-thread pool against native CP-SAT's every core --
was pinned down natively, where a baseline can be measured in the same command
as the thing it baselines.  `docs/WEB_UI.md` has that experiment.

The full comparison, including the native four-worker simulation that
established the cause without a browser, is in `docs/WEB_UI.md`.

## What does not work here

* **`--fetch-flow`.**  Making FactorioLab produce its own export means driving
  a headless browser to run FactorioLab's solve, and a page cannot do that to
  itself.  This is the one genuine impossibility here rather than a thing
  nobody got to.

  **`--flow` does work.**  Paste the CSV into the flow box, or choose the file:
  it goes to `pipeline.build(flow_text=...)` and through the same
  `flow_from_text` provenance check a file named on the command line gets, so
  an export from a different URL is refused with the difference spelled out
  rather than quietly ignored.  Proved end to end by `smoke.py --flow-pin`:
  `flow_pinned: true`, candidate `flow-pinned`, 238 tiles, 77 buildings,
  decoded and re-encoded byte for byte in native Python.
* **Per-solution and log callbacks.**  The wasm seam is one call in, one
  response out.  `swig_helper` raises if one is asked for rather than
  installing a callback that never fires.
* **`model_stats`, `solver_response_stats`, LP/MPS export.**  Formatters that
  live in `libortools` with no wasm entry point.  They raise.

  `model_stats` is worth a warning: there IS a `CpSat.modelStats` in
  `vendor/ortools/browser/cp-sat.js`, and it is not the same function.  It
  decodes the proto in JavaScript with protobufjs and returns
  `{name, variables, constraints, hasObjective}` as JSON; libortools'
  `CpModelStats` is a multi-line text report on the presolved model.  Same
  name, unrelated output.  `solver_response_stats` has no counterpart under
  any spelling -- checked against the bundle, not assumed.

## Traps already paid for here

* `SatParameters.max_time_in_seconds` is field **36** and `num_workers` is
  field **206**.  Hand-rolling the varint encoding silently produces a
  parameters proto with no time limit and no worker count, which reads as "the
  solver ignored my budget" and as "threading makes no difference".  The
  fixtures in `models/` are serialized by Python for this reason.
* A shared `WebAssembly.Memory` can be constructed without cross-origin
  isolation but not postMessage'd to a worker: an infinite hang, not an error.
* **JSPI can no longer be switched off in Chromium 151**, so the no-JSPI path
  cannot be driven from a browser on this box any more.  Measured, four ways:
  with no flags, with `--disable-features=WebAssemblyJSPromiseIntegration`,
  with `--js-flags=--no-wasm-jspi` and with
  `--js-flags=--no-experimental-wasm-jspi`, `typeof WebAssembly.Suspending`
  reads `function` every time.  `smoke.py` still passes
  `--enable-features=WebAssemblyJSPromiseIntegration` for older builds, where
  it is not a no-op.  What happens without JSPI is recorded above, from when it
  could still be turned off: `run_sync` raises, loudly, and nothing degrades.
* **Do not build the Python bootstrap as a JavaScript template literal.**  Its
  docstrings contain ``` `` ``` and the literal ends early; the symptom is
  `Uncaught TypeError: "<your whole python file>" is not a function`.  It lives
  in `web/bootstrap.py` and is fetched.
* ortools 9.11 writes `add_allowed_assignments` as `TableConstraintProto.vars`;
  9.15 writes it as single-term `exprs`.  This is the one place the vendored
  9.11 model differs from what the installed ortools would build, and it is
  the shape of bug that would never announce itself -- a dropped table
  constraint just yields a different, still-valid-looking layout.  Checked
  directly against the wasm build: a model with `vars` and no `exprs` and
  allowed pairs `{(3,4), (7,8)}`, minimising `x`, comes back `OPTIMAL` with
  `x, y = 3, 4`.  Honoured.  (It matters: `spine.py` uses
  `add_allowed_assignments` to pin row heights.)  `tests/clientside/` pins the
  difference so it cannot quietly become two places.
* Pyodide 0.28.3 ships `protobuf` **6.31.1**, and ortools 9.15's generated code
  declares gencode 6.33.1, which the runtime refuses.  9.11's gencode is 5.26.1
  and loads fine -- another reason the shim is 9.11 and not 9.15.
* emscripten's node runtime takes over `process.stdin`, so a stdio bridge to
  the wasm from Python silently receives nothing.  (Only relevant to the
  scratch harness, but it costs an hour to find.)

## The other files here

* `serve.py` -- static server.  `--isolated` toggles COOP/COEP; `/__log__` and
  `/__tally__` report every request and every byte, which is how "no server
  solved this" is corroborated from the server side.
* `smoke.py` -- the verification gate, driven with `nodriver`.  It imports the
  canvas check and the refusal fixture from `scripts/web_smoke.py` rather than
  reimplementing either, so the two arms are held to one gate and not two.
* `jspi_probe.html` -- the minimum reproduction of the stack-switching seam.
* `seam.html` -- the original end-to-end proof: Pyodide builds a proto, the
  wasm solves it, Python parses the response.
* `probe.html`, `cors.html`, `pyodide.html`, `models/*.pb` -- the measurement
  harness this arm started as.
