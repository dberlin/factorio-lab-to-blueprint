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
    python web/serve.py --port 8481 --dir web --isolated

then open <http://127.0.0.1:8481/app.html>.

`--isolated` sends COOP/COEP.  Without it the page still works, but only
because `coi-serviceworker.js` supplies the same headers from a service worker
on the *second* load -- see "Hosting" below.

To re-run the whole proof, headless, and check what came out:

    uv run python web/smoke.py --json /tmp/report.json

## How it works

    app.html                 UI, viewer, Copy button
      └── worker.js          one Web Worker holding three wasm modules
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

Machine: 128 logical cores, Chromium 151, Pyodide 0.28.3, or-tools-wasm 0.9.1.
**Every number below was taken while three other agents were building and
solving on the same box (load average 20-40).**  They are honest for this
machine under that load and are not clean-room figures; the native baseline in
the paired comparison was taken the same way.

### Cold payload

@@COLD_PAYLOAD@@

### Cold boot to first interactive

@@BOOT@@

### Solve, paired with native, same URL and same options

@@SOLVE@@

### Threading

`cp_sat_runtime.js` is built with `pthreadPoolSize=4`.  The pool is fixed at
build time, so however many cores the machine has -- 128 here, and
`navigator.hardwareConcurrency` reports all of them to the wasm -- CP-SAT gets
at most four search workers in the browser.  The server log shows it directly:
`cp_sat_runtime.js` is fetched five times per solve, once for the module and
once for each pool worker.

That pool needs `SharedArrayBuffer`, which needs cross-origin isolation.  A
shared `WebAssembly.Memory` can be *constructed* without isolation but cannot
be *postMessage'd to a worker*, so the failure is not a load error, it is an
infinite hang on `dependency: loading-workers`.

## Hosting

Cross-origin isolation is **required**, so a host that cannot set headers needs
`coi-serviceworker.js`, which installs on the first load and only takes effect
on the second.  `web/smoke.py --no-isolation` serves without COOP/COEP -- the
way GitHub Pages does -- and drives that path.

@@ISOLATION@@

## What does not work here

* **`--flow` / `--fetch-flow`.**  Pinning the recipe selection to FactorioLab's
  own export means driving a headless browser to run FactorioLab's solve, and a
  page cannot do that to itself.  The page says so in its notes rather than
  quietly deriving and calling it pinned.
* **Per-solution and log callbacks.**  The wasm seam is one call in, one
  response out.  `swig_helper` raises if one is asked for rather than
  installing a callback that never fires.
* **`model_stats`, `solver_response_stats`, LP/MPS export.**  Formatters that
  live in `libortools` with no wasm entry point.  They raise.

## Traps already paid for here

* `SatParameters.max_time_in_seconds` is field **36** and `num_workers` is
  field **206**.  Hand-rolling the varint encoding silently produces a
  parameters proto with no time limit and no worker count, which reads as "the
  solver ignored my budget" and as "threading makes no difference".  The
  fixtures in `models/` are serialized by Python for this reason.
* A shared `WebAssembly.Memory` can be constructed without cross-origin
  isolation but not postMessage'd to a worker: an infinite hang, not an error.
* **Do not build the Python bootstrap as a JavaScript template literal.**  Its
  docstrings contain ``` `` ``` and the literal ends early; the symptom is
  `Uncaught TypeError: "<your whole python file>" is not a function`.  It lives
  in `web/bootstrap.py` and is fetched.
* ortools 9.11 writes `add_allowed_assignments` as `TableConstraintProto.vars`;
  9.15 writes it as single-term `exprs`.  Both fields exist and CP-SAT reads
  both, but it is the one place the vendored 9.11 model differs from what the
  installed ortools would build, and `tests/clientside/` pins it so it cannot
  quietly become two places.
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
* `smoke.py` -- the verification gate, driven with `nodriver`.
* `jspi_probe.html` -- the minimum reproduction of the stack-switching seam.
* `seam.html` -- the original end-to-end proof: Pyodide builds a proto, the
  wasm solves it, Python parses the response.
* `probe.html`, `cors.html`, `pyodide.html`, `models/*.pb` -- the measurement
  harness this arm started as.
