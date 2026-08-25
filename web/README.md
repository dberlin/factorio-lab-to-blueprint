# Client-side arm: measurement harness

Everything here exists to answer one question with numbers: can flab2bp run
entirely in a browser, with no server, on a static host?

## What is here

* `vendor/ortools/` -- the browser CP-SAT build extracted from
  `or-tools-wasm@0.9.1`. Only the CP-SAT slice: the npm package unpacks to
  332.7 MB, the part a browser needs is 8.2 MB.
* `pyshim/` -- ortools' OWN generated pure-Python protobuf modules
  (`cp_model_pb2`, `sat_parameters_pb2`), taken from the 9.15 wheel. 13 KB
  zipped. These import with `protobuf` alone and never touch `libortools`.
* `serve.py` -- static server, `--isolated` toggles COOP/COEP so the same
  bytes can be served the way GitHub Pages serves them and the way a host
  that can set headers serves them.
* `coi-serviceworker.js` -- injects COOP/COEP client-side, the only route to
  cross-origin isolation on a host that cannot set headers.
* `probe.html` -- loads CP-SAT, solves a serialized `CpModelProto`, reports
  timings. `?model=`, `?limit=`, `?workers=`, `?mode=bridge|main`.
* `seam.html` -- **the whole architecture in one page**: Pyodide builds a
  `CpModelProto` in pure Python, hands the bytes to `or-tools-wasm`, parses
  the `CpSolverResponse` back in Python.
* `cors.html` -- can an isolated static page reach FactorioLab's dataset?
* `pyodide.html` -- cold payload and boot time for CPython + our deps.
* `models/*.pb` -- CpModelProto and SatParameters fixtures, serialized by
  ortools 9.15 so the browser is fed exactly the schema the project uses.

## Running

    python web/serve.py --port 8481 --dir web              # no COOP/COEP
    python web/serve.py --port 8482 --dir web --isolated   # with them

## Traps this harness already paid for

* `SatParameters.max_time_in_seconds` is field **36** and `num_workers` is
  field **206**. Hand-rolling the varint encoding silently produces a
  parameters proto with no time limit and no worker count, which reads as
  "the solver ignored my budget" and as "threading makes no difference".
  The fixtures in `models/` are serialized by Python for this reason.
* A shared `WebAssembly.Memory` can be *constructed* without cross-origin
  isolation. It cannot be *postMessage'd to a worker*. So the failure does
  not appear at module load, it appears as an infinite hang on
  `dependency: loading-workers`.
